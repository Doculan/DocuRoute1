from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser, BasePermission
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Q
from datetime import timedelta
from .models import (
    Announcement, AnnouncementDismissal, Concurrence, CustomUser,
    Manual, ManualSection, Office, OfficeLink,
    Proposal, ProposalVersion, RecentlyOpened, SectionHistory,
)
from ml.ocr_engine import extract_text
from api import access, document_status
from ml.svm_model import predict_section
import difflib
import logging
import re

logger = logging.getLogger(__name__)


class IsAdminRole(BasePermission):
    """
    Custom permission to only allow users with role='admin'.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


# ─── RE-AUTHENTICATION ───────────────────────────────────────
#
# A JWT says who is holding the laptop, not who is sitting at it. For
# actions that cannot be undone - deleting a document, changing who must
# agree - that is the wrong question, so those endpoints ask for the
# password again.
#
# The password buys a short-lived signed token rather than travelling with
# every delete: one confirmation can then cover a bulk operation without
# the browser holding a password across several requests, and nothing has
# to be stored server-side. TimestampSigner enforces the expiry, so there
# is no session or cache row to go stale, and a token from a restarted
# process is still valid - which matters, because a token that silently
# expired on deploy would read to the admin as a rejected password.

REAUTH_SALT = 'api.reauth'

# Long enough to read a confirmation and decide, short enough that a token
# left in a tab is not a standing permission to delete things.
REAUTH_MAX_AGE_SECONDS = 300

REAUTH_HEADER = 'HTTP_X_REAUTH_TOKEN'


def issue_reauth_token(user):
    return TimestampSigner(salt=REAUTH_SALT).sign(str(user.pk))


def reauth_failure(request):
    """``None`` when the caller has confirmed their password recently, or a
    response explaining what is missing.

    The three failures are told apart deliberately. "Expired" has to be
    distinguishable from "wrong", or an admin who took five minutes over a
    confirmation is told their own password is wrong, and the next thing
    they do is try to reset it.
    """
    token = request.META.get(REAUTH_HEADER, '')
    if not token:
        return Response(
            {'error': 'Confirm your password to continue.',
             'reason': 'reauth_required'},
            status=403,
        )

    try:
        signed_pk = TimestampSigner(salt=REAUTH_SALT).unsign(
            token, max_age=REAUTH_MAX_AGE_SECONDS
        )
    except SignatureExpired:
        return Response(
            {'error': 'That confirmation has expired. Please confirm again.',
             'reason': 'reauth_expired'},
            status=403,
        )
    except BadSignature:
        return Response(
            {'error': 'That confirmation could not be verified.',
             'reason': 'reauth_invalid'},
            status=403,
        )

    # A token proves a password was entered; it must also be *this*
    # account's, or one admin's confirmation would authorise another's
    # deletions on a shared browser.
    if signed_pk != str(request.user.pk):
        return Response(
            {'error': 'That confirmation belongs to a different account.',
             'reason': 'reauth_invalid'},
            status=403,
        )
    return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_password(request):
    """Exchange the current account's password for a short-lived token.

    Separate from login on purpose: this issues nothing that can be used to
    sign in, and a failure here must not look like a session problem or the
    client will send the admin back to the login screen mid-delete.
    """
    password = request.data.get('password', '')
    if not password:
        return Response({'error': 'Enter your password.'}, status=400)

    if not request.user.check_password(password):
        return Response({'error': 'That password is not correct.'}, status=403)

    return Response({
        'token': issue_reauth_token(request.user),
        'expires_in': REAUTH_MAX_AGE_SECONDS,
    })


# ─── HELPERS ─────────────────────────────────────────────────

# Word/Symbol-font bullet that survives OCR extraction.
_OCR_BULLET = ''


def normalize_for_diff(text):
    """Strip OCR/HTML artifacts so a diff reflects real edits, not markup noise.

    The editors seed their textarea with the same cleanup applied client-side
    (formatOCRContent), so both sides have to be normalized identically —
    otherwise every line carrying a <br> or bullet glyph reads as changed.

    <br> collapses to a space, not a newline: it marks where a PDF table cell
    ran out of width mid-sentence, so splitting on it is what produced the
    one-word-per-line content in legacy sections.
    """
    if not text:
        return ''
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'&nbsp;', ' ', text, flags=re.IGNORECASE)
    text = text.replace(_OCR_BULLET, '•')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def build_diff(old_text, new_text):
    """Unified diff of two blocks of section content, normalized on both sides."""
    return '\n'.join(difflib.unified_diff(
        normalize_for_diff(old_text).splitlines(),
        normalize_for_diff(new_text).splitlines(),
        lineterm='',
    ))


def preview_diff(diff_text, max_lines=12):
    """Trim a unified diff to whole lines, so a preview never cuts mid-line."""
    if not diff_text:
        return ''
    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text
    hidden = len(lines) - max_lines
    return '\n'.join(lines[:max_lines] + [f'… {hidden} more line{"" if hidden == 1 else "s"}'])


# A Markdown table separator: |---|---| or | --- | :--: |. Must survive the
# artifact filter below, since it carries the table's column count.
_MD_TABLE_SEP_RE = re.compile(r'^\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$')


def _split_into_sections(text, fallback_title='Full Document'):
    # FIX #1: INLINE_TAGS are NO LONGER stripped from lines.
    # Semantic keywords (POLICY, PROCEDURE, RESPONSIBILITY, WORKING INSTRUCTION)
    # must be preserved so the SVM classifier can detect them.

    # Markdown syntax is stripped by ocr_engine._clean before this point, so no
    # cleanup happens here. In particular the "|" cell separators are left
    # intact — flattening them to spaces destroyed every procedure table.

    # A manual numbers its sections one way throughout. If it uses "1.0" style,
    # a bare integer further down is a numbered step inside a procedure table
    # ("9 Calculates total points earned"), not a new section — promoting those
    # split procedure tables into fragments.
    uses_dotted_sections = bool(re.search(r'(?m)^\s*\d+\.0\s+\S', text))

    def is_top_level_number(num_tuple):
        # FIX #2: bare single-digit sections ("1", "2") count as top-level, but
        # only in documents that actually number their sections that way.
        if len(num_tuple) == 1:
            return not uses_dotted_sections
        return len(num_tuple) == 2 and num_tuple[1] == 0

    def is_subsection_number(num_tuple):
        # Only depth-2 sub-sections like 1.1, 1.2, 2.3 are treated as section headers.
        # Depth 3+ (1.1.1, 1.2.3) are always content — they are list items or sub-steps.
        return len(num_tuple) == 2 and num_tuple[1] != 0

    # Articles, prepositions, conjunctions, and pronouns that indicate prose/list items,
    # NOT valid heading titles. Only blocks multi-word phrases starting with these words.
    _PROSE_ARTICLE_STARTERS = re.compile(
        r'^(The|A|An|All|Each|Every|This|These|Those|That|Upon|For|In|To|By|As|If|When|Where)\s',
        re.IGNORECASE
    )

    def looks_like_heading(title_text):
        """Return True only if the text after the number looks like a heading title,
        not a prose sentence or list item.

        Heuristics (all must pass):
        - No title (bare number like '1' or '1.1') is always a heading
        - Single-word title is always a valid heading (e.g. 'PURPOSE', 'Processing')
        - Must be ≤ 60 chars total
        - Must NOT end with a period (sentences do; headings don't)
        - Must NOT start with a lowercase letter
        - Multi-word: must NOT start with articles/prepositions (prose starters)
        - Multi-word: must NOT contain '. ' mid-text
        - Multi-word (>4 words): must NOT have >35% lowercase-initial words
        """
        if not title_text:
            return True   # bare number like '1' or '1.1'
        t = title_text.strip()
        # Too long → it's a sentence
        if len(t) > 60:
            return False
        # Ends with period → sentence
        if t.endswith('.'):
            return False
        # Starts with lowercase → prose
        if t[0].islower():
            return False
        words = t.split()
        # Single-word heading is always valid (e.g. 'PURPOSE', 'Processing', 'Scope')
        if len(words) == 1:
            return True
        # Multi-word: starts with article/preposition/conjunction → list item or sentence
        if _PROSE_ARTICLE_STARTERS.match(t):
            return False
        # Multi-word: contains '. ' mid-text → sentence
        if re.search(r'\.\s', t):
            return False
        # >4 words with >35% lowercase-initial words → prose
        if len(words) > 4:
            lc = sum(1 for w in words if w and w[0].islower())
            if lc / len(words) > 0.35:
                return False
        return True

    lines = text.split('\n')
    sections = []
    current_subtitle = None
    current_content = []
    current_page = None
    current_is_chapter = False
    page_header_buffer = []
    in_page_header = False
    pending_page_header = False

    def flush():
        nonlocal current_subtitle, current_content, current_is_chapter
        # FIX #6: Create sections even if content is empty (e.g., "4.0 PROCEDURES" with no body)
        if current_subtitle:
            content = '\n'.join(l for l in current_content if l.strip()).strip()
            sections.append({
                'subtitle': current_subtitle,
                'content': content,  # May be empty string for heading-only sections
                'page_number': current_page,
                'is_chapter': current_is_chapter,
            })
        current_subtitle = None
        current_content = []
        current_is_chapter = False

    def flush_page_header():
        nonlocal page_header_buffer, current_content, pending_page_header
        if not page_header_buffer:
            pending_page_header = False
            return

        if current_subtitle:
            header_text_lines = [l for l in page_header_buffer if l.strip()]
            if header_text_lines:
                # Append at the current stream position (not prepend),
                # so the output order stays closer to the PDF.
                current_content.extend(header_text_lines)
                current_content.append('')
            page_header_buffer = []
        pending_page_header = False

    # Pre-process: rejoin orphaned number lines with next line
    # e.g. "1.\nOBJECTIVES" → "1 OBJECTIVES" or "1.0\nOBJECTIVES" → "1.0 OBJECTIVES"
    joined_lines = []
    i = 0
    while i < len(lines):
        s = lines[i].strip().replace('\u200b', '').strip()
        if not s:
            i += 1
            continue
        if re.match(r'^\d+(?:\.\d+)*\.?$', s) and i + 1 < len(lines):
            next_s = lines[i + 1].strip().replace('\u200b', '').strip()
            if next_s and not next_s.startswith('##') and not re.match(r'^\d+(?:\.\d+)*\.?$', next_s):
                joined_num = s.rstrip('.')
                joined_lines.append(f"{joined_num} {next_s}")
                i += 2
                continue
        joined_lines.append(s)
        i += 1

    PAGE_HEADER_KEYS = re.compile(
        r'VERSION NO|DOCUMENT NO|DOCUMENT NAME|MANUAL TITLE|REVISION NO|EFFECTIVITY DATE|PAGE NO|APPROVAL DATE|FAM|PROCUREMENT MANAGEMENT|FINANCE AND ADMINISTRATION MANUAL',
        re.IGNORECASE
    )

    for line_idx, line in enumerate(joined_lines):
        # FIX #1: do NOT strip inline tags — only normalize whitespace
        s = re.sub(r'\s{2,}', ' ', line.strip()).strip()
        if not s:
            continue

        # PAGE_HEADER marker
        ph = re.match(r'^##PAGE_HEADER\s+(\d+)\s+FOR\s+.+##$', s)
        if ph:
            flush_page_header()
            current_page = int(ph.group(1))
            in_page_header = True
            continue

        # If we are in page header mode, accumulate header text "as-is"
        # until we hit the next section/chapter heading.
        if in_page_header:
            if s.startswith('##PAGE_HEADER_END##'):
                in_page_header = False
                pending_page_header = True
                continue

            # Stop page header when we hit a section heading or main content
            if re.match(r'^(CHAPTER\s+\d+(?:\.\d+)*)(?:\s*[:\.\-]?\s*(.*))?$', s, re.IGNORECASE) or \
               re.match(r'^(\d+(?:\.\d+)*\.?)(\s+\S+.*)?$', s):
                in_page_header = False
                pending_page_header = True
                # fall through to section/content processing
            else:
                # Keep collecting header lines; don't terminate on "non-key" lines.
                page_header_buffer.append(s)
                continue

        # Drop legacy TABLE_START / TABLE_END markers from old extractions
        if s in ('||TABLE_START||', '||TABLE_END||'):
            continue

        # Drop leftover metadata lines that are unrelated to content
        if PAGE_HEADER_KEYS.search(s):
            continue

        # Drop artifact lines - but not a Markdown table separator, which is
        # made of exactly these characters and is the row that declares the
        # table's column count and marks its header.
        if re.match(r'^[\s:|\-\.]+$', s) and not _MD_TABLE_SEP_RE.match(s):
            continue

        # A line with pipe characters is table content — never a section heading.
        # Guard this before the numbered-section regex so "1 | Activity" doesn't
        # get treated as section "1 Activity".
        if '|' in s:
            if current_subtitle is None:
                current_subtitle = fallback_title
            current_content.append(s)
            continue

        # CHAPTER headings: treat as top-level section
        chapter_match = re.match(r'^(CHAPTER\s+\d+(?:\.\d+)*)(?:\s*[:\.\-]?\s*(.*))?$', s, re.IGNORECASE)
        if chapter_match and len(s) < 150:
            flush()
            chapter_label = chapter_match.group(1).upper()
            chapter_title = chapter_match.group(2) or ''
            if chapter_title:
                current_subtitle = f"{chapter_label} - {chapter_title.strip()}"
            else:
                current_subtitle = chapter_label
            current_is_chapter = True
            current_content = []
            # If we buffered page-header lines right before this first section,
            # append them at the correct stream position.
            if pending_page_header and page_header_buffer:
                header_text_lines = [l for l in page_header_buffer if l.strip()]
                if header_text_lines:
                    current_content.extend(header_text_lines)
                    current_content.append('')
                page_header_buffer = []
                pending_page_header = False
            continue

        # NUMBERED section: headings like "1.", "1.0", "1.1", "1.1.1", etc.
        top_level = re.match(r'^(\d+(?:\.\d+)*\.?)\s*(\S+.*)?$', s)
        if top_level and len(s) < 120:
            num_str = top_level.group(1).rstrip('.')
            num_tuple = tuple(int(x) for x in num_str.split('.'))
            title = top_level.group(2) or ''
            full_heading = f"{num_str} {title.strip()}" if title else num_str

            if is_top_level_number(num_tuple) and looks_like_heading(title):
                # Top-level: start new section (1, 2, 3 or 1.0, 2.0)
                flush()
                current_subtitle = full_heading
                current_content = []
                if pending_page_header and page_header_buffer:
                    header_text_lines = [l for l in page_header_buffer if l.strip()]
                    if header_text_lines:
                        current_content.extend(header_text_lines)
                        current_content.append('')
                    page_header_buffer = []
                    pending_page_header = False

            elif is_subsection_number(num_tuple) and looks_like_heading(title):
                # FIX #5 (revised): only depth-2 subsections that look like headings
                # (e.g. "1.1 SCOPE", "2.3 COVERAGE") start their own section.
                # Depth-3+ lines and prose list items fall through to content.
                flush()
                current_subtitle = full_heading
                current_content = []
                if pending_page_header and page_header_buffer:
                    header_text_lines = [l for l in page_header_buffer if l.strip()]
                    if header_text_lines:
                        current_content.extend(header_text_lines)
                        current_content.append('')
                    page_header_buffer = []
                    pending_page_header = False

            else:
                # Depth 3+, prose list items, numbered steps → append as content
                if current_subtitle is None:
                    current_subtitle = fallback_title
                if pending_page_header and page_header_buffer:
                    header_text_lines = [l for l in page_header_buffer if l.strip()]
                    if header_text_lines:
                        current_content.extend(header_text_lines)
                        current_content.append('')
                    page_header_buffer = []
                    pending_page_header = False
                current_content.append(s)
            continue  # handled by the top_level block — do not fall through

        # Everything else is content (non-numbered lines)
        if current_subtitle is None:
            current_subtitle = fallback_title
        if pending_page_header and page_header_buffer:
            header_text_lines = [l for l in page_header_buffer if l.strip()]
            if header_text_lines:
                current_content.extend(header_text_lines)
                current_content.append('')
            page_header_buffer = []
            pending_page_header = False
        current_content.append(s)

    flush_page_header()
    flush()

    if not sections:
        sections.append({
            'subtitle': fallback_title,
            'content': text.strip(),
            'page_number': None,
            'is_chapter': False,
        })

    return sections


# ─── HELPERS: Parent Section Detection ─────────────────────────

def _parse_section_number(subtitle):
    """Extract section number from subtitle (e.g., '1.2' from '1.2 Introduction')."""
    match = re.match(r'^(\d+(?:\.\d+)?)', subtitle)
    return match.group(1) if match else None


def _is_parent_section(sec_num):
    """Check if section number is a parent (e.g., 1.0 or 1)."""
    if not sec_num:
        return False
    parts = sec_num.split('.')
    return len(parts) == 1 or (len(parts) == 2 and parts[1] == '0')


def _find_parent_section_in_manual(manual, subtitle):
    """Find parent section in manual based on section number hierarchy."""
    current_num = _parse_section_number(subtitle)
    if not current_num or _is_parent_section(current_num):
        # This section is a parent itself or has no number
        return None

    # It's a child section - find its parent
    if '.' in current_num:
        parent_num = current_num.split('.')[0] + '.0'
    else:
        return None

    # Look for parent section in database
    sections = manual.sections.all().order_by('order')
    for section in sections:
        sec_subtitle_num = _parse_section_number(section.subtitle)
        if sec_subtitle_num == parent_num:
            return section

    return None


# ─── AUTH ────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email', '')
    # v4. The process prints position titles and never names, but the
    # system admin approving a request has to know who is asking.
    full_name = (request.data.get('full_name') or '').strip()

    if CustomUser.objects.filter(username=username).exists():
        return Response({'error': 'Username already taken'}, status=400)

    CustomUser.objects.create_user(
        username=username,
        password=password,
        email=email,
        full_name=full_name,
        is_approved=False
    )

    return Response({'message': 'Registration successful. Wait for admin approval.'}, status=201)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    username = request.data.get('username')
    password = request.data.get('password')

    user = authenticate(username=username, password=password)

    if user is None:
        return Response({'error': 'Invalid credentials'}, status=401)

    if not user.is_approved:
        return Response({'error': 'Your account is pending admin approval.'}, status=403)

    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'role': user.role,
        # Which portal, and which nav groups within it.
        'system_role': user.system_role,
        'username': user.username,
    })


# ─── ADMIN: USERS ────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminRole])
def pending_users(request):
    users = CustomUser.objects.filter(is_approved=False)
    # The full name the person gave at sign-up: whoever approves has to know
    # who is asking.
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'full_name': u.full_name} for u in users]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def approved_users(request):
    users = CustomUser.objects.filter(is_approved=True)
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'role': u.role, 'full_name': u.full_name} for u in users]
    return Response(data)


@api_view(['PATCH'])
@permission_classes([IsAdminRole])
def approve_user(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)
    user.is_approved = True
    user.save()
    return Response({'message': f'{user.username} has been approved.'})


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def reject_user(request, user_id):
    """Rejecting a registration deletes the account, so it re-authenticates.

    Not because rejecting is a grave act, but because it is indistinguishable
    from approving by position on screen, and the undo is "ask them to
    register again".
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)
    user.delete()
    return Response({'message': 'User rejected and removed.'})


# ─── STAFF ENDPOINTS ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_list_manuals(request):
    """The documents linked to the offices where this person holds a position."""
    if not access.has_unit(request.user):
        return _no_unit_error()
    manuals = access.manuals_for(
        request.user, Manual.objects.all()
    ).order_by('-uploaded_at')
    data = [{
        'id': m.id,
        'title': m.title,
        # What this document *is* to the reader's offices, which is the
        # question a list of manuals actually answers.
        'series': m.series.code if m.series_id else None,
        'series_title': m.series.title if m.series_id else None,
        'owner': str(m.effective_owner) if m.effective_owner else None,
        'relationship': _relationship_for(request.user, m),
        'uploaded_by': m.uploaded_by.username if m.uploaded_by else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': m.sections.count(),
        'version': m.version,
        'revision': m.revision,
        'display_status': f"v{m.version} rev{m.revision}",
        'status': document_status.status_payload(m.current_status),
    } for m in manuals]
    return Response(data)


# How many places to remember. Long enough to cover a morning's work,
# short enough that the list is still a shortcut rather than a history.
RECENTLY_OPENED_LIMIT = 6


def _record_recently_opened(user, manual, section=None):
    """Remember that this person opened this, and forget the oldest.

    Called from the read endpoints rather than by the client, so it records
    what was actually served. Failures are swallowed: not remembering where
    someone was is never worth failing the page they asked for - but they are
    logged, because a bookmark list that silently stopped working would look
    identical to one nobody had used.
    """
    if not (user and getattr(user, 'is_authenticated', False) and manual):
        return
    try:
        RecentlyOpened.objects.update_or_create(
            user=user, manual=manual, section=section,
        )
        keep = list(
            RecentlyOpened.objects.filter(user=user)
            .order_by('-opened_at')
            .values_list('id', flat=True)[:RECENTLY_OPENED_LIMIT]
        )
        RecentlyOpened.objects.filter(user=user).exclude(id__in=keep).delete()
    except Exception:
        logger.exception("could not record recently-opened for %s", user)


def _refuse_if_held(sections, action='changed'):
    """Refuse a direct edit to text a change request is holding.

    A section held by a request is text the offices have agreed - or are
    agreeing - to replace. Editing it underneath them would mean the
    custodian's check at the end fails, or worse, that the request is made
    effective over words nobody on it ever saw. So the text waits until the
    request is made effective, denied or withdrawn.

    Returns a response to send, or None.
    """
    from .models import SectionChange
    ids = [s.pk for s in sections if s is not None]
    change = SectionChange.objects.filter(
        section_id__in=ids, is_open=True,
    ).select_related(
        'section', 'version__proposal__initiating_office',
    ).first()
    if change is None:
        return None
    proposal = change.version.proposal
    label = proposal.dcr_number or 'a change request'
    return Response({
        'error': (
            f'{change.section.subtitle} cannot be {action}: it is held by '
            f'{label} from {proposal.initiating_office.name} until that is '
            f'made effective, denied or withdrawn.'
        ),
        'reason': 'section_held',
        'proposal_id': proposal.pk,
    }, status=409)


def _text_would_change(request, section):
    """Only the text is held. Tag, order and page number are not what the
    offices agreed on, and correcting them does not disturb the request."""
    return any(
        field in request.data and request.data[field] != getattr(section, field)
        for field in ('content', 'subtitle')
    )


def _no_unit_error():
    """What someone sees when their account works and shows nothing.

    It says who fixes it - the alternative is an error that reads like a
    fault in the software.
    """
    return Response({
        'error': (
            'Your account is approved but not yet assigned to an office. '
            'The system administrator will assign you.'
        ),
        'reason': 'no_position',
    }, status=403)


def _relationship_for(user, manual):
    """What this document is to the person looking at it.

    Owner, Concurring, Read only - or None for someone whose offices have
    no link to it (the system admin, QMS staff).

    An office can own a manual *and* concur on it, so more than one label
    can apply and both are shown.
    """
    mine = {office.pk for office in access.current_offices(user)}
    if not mine:
        return None

    labels = []
    owner = manual.effective_owner
    if owner is not None and owner.pk in mine:
        labels.append('Owner')
    for link in manual.effective_office_links():
        if link.office_id in mine:
            labels.append(
                'Concurring' if link.relationship == OfficeLink.CONCURRING
                else 'Read only'
            )
    return ' · '.join(dict.fromkeys(labels)) or None


def _visible_announcements(user):
    """Active announcements for everyone, plus the ones aimed at an office
    where this person holds a position - the same offices that decide which
    documents they reach, so notices and access never disagree about where
    someone works."""
    offices = access.current_offices(user) if (
        user and user.is_authenticated
    ) else []
    return Announcement.objects.filter(active=True).filter(
        Q(office__isnull=True) | Q(office__in=offices)
    ).select_related('office')


def _announcement_payload(announcement):
    """One announcement, plus who can actually see it.

    `shows_as` is computed rather than stored: a dated item is Upcoming and
    an undated one is the banner, and deriving it here means the admin list
    and the staff dashboard can never disagree about which a row is.
    """
    audience = CustomUser.objects.filter(role='staff', is_approved=True)
    if announcement.office_id:
        audience = audience.filter(
            position_assignments__position__office_id=announcement.office_id,
            position_assignments__ends_on__isnull=True,
        ).distinct()

    return {
        'id': announcement.id,
        'title': announcement.title,
        'body': announcement.body,
        'date': announcement.date,
        'shows_as': 'upcoming' if announcement.date else 'banner',
        'office_id': announcement.office_id,
        'office': str(announcement.office) if announcement.office_id else None,
        'active': announcement.active,
        'created_by': announcement.created_by.username if announcement.created_by else None,
        'created_at': announcement.created_at,
        'reach': audience.count(),
        'dismissals': announcement.dismissals.count(),
    }


def _clean_announcement_fields(data, partial=False):
    """Validate and coerce what the form sent.

    Returns ``(fields, error)``. An empty date is meaningful here - it is
    what makes something a banner - so "" and None both mean "no date"
    rather than "leave it alone".
    """
    fields = {}

    if 'title' in data or not partial:
        title = (data.get('title') or '').strip()
        if not title:
            return None, Response(
                {'error': 'A title is required.', 'field': 'title'}, status=400
            )
        fields['title'] = title

    if 'body' in data or not partial:
        fields['body'] = (data.get('body') or '').strip()

    if 'date' in data or not partial:
        raw = data.get('date')
        if raw in (None, '', 'null'):
            fields['date'] = None
        else:
            parsed = parse_date(str(raw))
            if parsed is None:
                return None, Response(
                    {'error': 'Use a date like 2026-10-06.', 'field': 'date'},
                    status=400,
                )
            fields['date'] = parsed

    if 'office_id' in data:
        raw = data.get('office_id')
        if raw in (None, '', 'all'):
            fields['office'] = None
        else:
            try:
                fields['office'] = Office.objects.get(id=raw)
            except (Office.DoesNotExist, ValueError, TypeError):
                return None, Response(
                    {'error': 'That office does not exist.',
                     'field': 'office_id'},
                    status=400,
                )

    if 'active' in data:
        value = data.get('active')
        fields['active'] = (value if isinstance(value, bool)
                            else str(value).strip().lower() in ('1', 'true', 'yes', 'on'))

    return fields, None


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def admin_announcements(request):
    """List every announcement, or create one.

    Active items first, then by date - the list is a work queue more than a
    log, and something switched off is not what anyone came to look at.
    """
    if request.method == 'GET':
        rows = Announcement.objects.select_related(
            'office', 'created_by'
        ).order_by('-active', 'date', '-created_at')
        return Response([_announcement_payload(a) for a in rows])

    fields, error = _clean_announcement_fields(request.data)
    if error:
        return error

    announcement = Announcement.objects.create(
        created_by=request.user, **fields
    )
    return Response(_announcement_payload(announcement), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminRole])
def admin_announcement_detail(request, announcement_id):
    """Read, edit, or delete one announcement.

    Deleting is allowed because a mistyped notice should not linger forever,
    but deactivating is the usual move: it keeps the record of what was
    posted, and the staff side already hides inactive rows.
    """
    try:
        announcement = Announcement.objects.select_related(
            'office', 'created_by'
        ).get(id=announcement_id)
    except Announcement.DoesNotExist:
        return Response({'error': 'Announcement not found'}, status=404)

    if request.method == 'GET':
        return Response(_announcement_payload(announcement))

    if request.method == 'DELETE':
        # Deactivating is the reversible move and stays a single click;
        # deleting destroys the record of what was posted, so it asks.
        failure = reauth_failure(request)
        if failure:
            return failure
        announcement.delete()
        return Response(status=204)

    fields, error = _clean_announcement_fields(request.data, partial=True)
    if error:
        return error
    for name, value in fields.items():
        setattr(announcement, name, value)
    announcement.save()
    return Response(_announcement_payload(announcement))


# How many separate days must carry activity before a line through them
# means anything. Four points over four months is not a trend, and drawing
# it as one invites the reader to see a slope that is really just the gaps
# between submissions. Below this the same numbers are shown as a table,
# which makes no claim about the shape.
ACTIVITY_CHART_MINIMUM_DAYS = 5

# Far enough back to show a term's worth of work, short enough that the
# series stays readable at dashboard width.
ACTIVITY_WINDOW_DAYS = 30


def _activity_series(window_start, today):
    """Work per day, oldest first.

    Counted on the day each thing happened: a proposal submitted (once per
    version, so a redraft sent again counts again - it was), agreed (locked:
    every concurring office concurred), or returned by an office. The
    question this answers is how much work is moving, day by day.
    """
    submitted = {}
    approved, rejected = {}, {}

    def add(bucket, value):
        day = timezone.localtime(value).date()
        bucket[day] = bucket.get(day, 0) + 1

    for value in ProposalVersion.objects.filter(
        submitted_at__isnull=False, submitted_at__date__gte=window_start,
    ).values_list('submitted_at', flat=True):
        add(submitted, value)

    for value in Proposal.objects.filter(
        locked_at__isnull=False, locked_at__date__gte=window_start,
    ).values_list('locked_at', flat=True):
        add(approved, value)

    for value in Concurrence.objects.filter(
        decision='return', recorded_at__date__gte=window_start,
    ).values_list('recorded_at', flat=True):
        add(rejected, value)

    days = []
    cursor = window_start
    while cursor <= today:
        days.append({
            'date': cursor,
            'submitted': submitted.get(cursor, 0),
            'approved': approved.get(cursor, 0),
            'rejected': rejected.get(cursor, 0),
        })
        cursor += timedelta(days=1)

    active = sum(1 for d in days
                 if d['submitted'] or d['approved'] or d['rejected'])
    return days, active


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_dashboard(request):
    """Everything the admin landing page shows, in one request.

    Same reasoning as the staff dashboard: the widgets all read the same
    handful of tables, and the landing page is the worst screen to make
    slow. It also replaces the separate count requests the shell once fired
    on every tab change, so the nav badges and the dashboard cannot
    disagree with each other.
    """
    today = timezone.localdate()
    window_start = today - timedelta(days=ACTIVITY_WINDOW_DAYS - 1)

    # -- 1. needs attention --------------------------------------
    # Only the rows that are not zero reach the screen, but the endpoint
    # reports all of them: "nothing is waiting" is a real answer and the
    # client should not have to infer it from a missing key.
    attention = {
        'pending_users': CustomUser.objects.filter(
            is_approved=False, role='staff'
        ).count(),
        'untagged_sections': ManualSection.objects.filter(
            Q(tag='') | Q(tag='UNTAGGED')
        ).count(),
        'proposals_drafting': Proposal.objects.filter(
            status=Proposal.DRAFT
        ).count(),
        'proposals_in_concurrence': Proposal.objects.filter(
            status=Proposal.CONCURRENCE
        ).count(),
        # Agreed and on their way: every frozen status, not just `LOCKED`,
        # or the counter would read zero while the paperwork piled up.
        'proposals_locked': Proposal.objects.filter(
            status__in=Proposal.FROZEN_STATUSES
        ).count(),
    }

    # -- 2. activity over time -----------------------------------
    days, active_days = _activity_series(window_start, today)
    activity = {
        'days': [{
            'date': d['date'].isoformat(),
            'submitted': d['submitted'],
            'approved': d['approved'],
            'rejected': d['rejected'],
        } for d in days],
        'active_days': active_days,
        'window_days': ACTIVITY_WINDOW_DAYS,
        # Decided here rather than in the component so the rule lives in one
        # place and can be tested.
        'enough_for_chart': active_days >= ACTIVITY_CHART_MINIMUM_DAYS,
        'minimum_days': ACTIVITY_CHART_MINIMUM_DAYS,
        'totals': {
            'submitted': sum(d['submitted'] for d in days),
            'approved': sum(d['approved'] for d in days),
            'rejected': sum(d['rejected'] for d in days),
        },
    }

    # -- 3. upcoming ---------------------------------------------
    # The admin sees every office's notices, not only one: this is the
    # posting desk, and the point is to see what has been scheduled.
    scheduled = Announcement.objects.filter(
        active=True, date__gte=today
    ).select_related('office').order_by('date')
    upcoming = [{
        'id': a.id,
        'title': a.title,
        'date': a.date,
        'is_today': a.date == today,
        'office': a.office.name if a.office_id else None,
    } for a in scheduled[:5]]

    # -- 4. system state -----------------------------------------
    system = {
        'manuals': Manual.objects.count(),
        'sections': ManualSection.objects.count(),
        'offices': Office.objects.filter(is_active=True).count(),
        'staff': CustomUser.objects.filter(role='staff', is_approved=True).count(),
        'admins': CustomUser.objects.filter(role='admin').count(),
        'banners_live': Announcement.objects.filter(
            active=True, date__isnull=True
        ).count(),
        'proposals_total': Proposal.objects.count(),
    }

    return Response({
        'attention': attention,
        'activity': activity,
        'proposals': _recent_proposals(),
        'upcoming': upcoming,
        'upcoming_total': scheduled.count(),
        'system': system,
    })


def _recent_proposals():
    """The last few proposals and where each has got to."""
    rows = []
    for proposal in Proposal.objects.select_related(
        'manual', 'initiating_office'
    ).order_by('-updated_at')[:6]:
        version = proposal.current_version()
        participants = proposal.participants.filter(role='concurring')
        decided = Concurrence.objects.filter(
            version=version, decision='concur',
        ).count() if version else 0
        rows.append({
            'id': proposal.id,
            'manual': proposal.manual.title,
            'office': str(proposal.initiating_office),
            'status': proposal.status,
            'status_label': proposal.get_status_display(),
            'version': version.number if version else None,
            'concurred': decided,
            'of': participants.count(),
            'updated_at': proposal.updated_at,
        })
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_dashboard(request):
    """Everything the dashboard shows, in one request.

    One endpoint rather than six: the widgets are all small, they all read
    the same two or three tables, and six round trips would make the landing
    page the slowest screen in the portal for no benefit.
    """
    user = request.user
    today = timezone.localdate()

    # -- recently opened -----------------------------------------
    recent = [{
        'manual_id': row.manual_id,
        'manual': row.manual.title,
        'section_id': row.section_id,
        'section': row.section.subtitle if row.section else None,
        'opened_at': row.opened_at,
    } for row in RecentlyOpened.objects.filter(user=user)
        .select_related('manual', 'section')[:RECENTLY_OPENED_LIMIT]]

    # -- announcements and upcoming ------------------------------
    visible = _visible_announcements(user)
    dismissed = set(
        AnnouncementDismissal.objects.filter(user=user)
        .values_list('announcement_id', flat=True)
    )
    banner = next(
        (a for a in visible.filter(date__isnull=True).order_by('-created_at')
         if a.id not in dismissed),
        None,
    )
    upcoming = [{
        'id': a.id,
        'title': a.title,
        'body': a.body,
        'date': a.date,
        'is_today': a.date == today,
    } for a in visible.filter(date__gte=today).order_by('date')[:5]]

    # -- proposals: how much is waiting on this person's offices ---
    from .concurrence_views import _offices_yet_to_decide
    my_offices = access.current_offices(user)
    my_office_ids = [o.pk for o in my_offices]
    awaiting = 0
    if my_office_ids:
        for proposal in Proposal.objects.filter(
            status=Proposal.CONCURRENCE,
            participants__office_id__in=my_office_ids,
            participants__role='concurring',
        ).distinct():
            undecided = _offices_yet_to_decide(
                proposal, proposal.current_version()
            )
            if any(p.office_id in my_office_ids for p in undecided):
                awaiting += 1

    return Response({
        'proposals_awaiting': awaiting,
        'proposals_mine': Proposal.objects.filter(
            initiating_office__in=my_offices
        ).count(),
        'recently_opened': recent,
        'announcement': None if banner is None else {
            'id': banner.id, 'title': banner.title, 'body': banner.body,
        },
        'upcoming': upcoming,
        'upcoming_total': visible.filter(date__gte=today).count(),
        'stats': {
            'manuals_total': Manual.objects.count(),
            'manuals_mine': access.manuals_for(user, Manual.objects.all()).count(),
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def staff_dismiss_announcement(request, announcement_id):
    """Close the banner for this person only.

    Recorded against the announcement's id rather than as a single flag, so
    the next announcement still appears for someone who dismissed the last.
    """
    try:
        announcement = Announcement.objects.get(id=announcement_id)
    except Announcement.DoesNotExist:
        return Response({'error': 'Announcement not found'}, status=404)

    AnnouncementDismissal.objects.get_or_create(
        announcement=announcement, user=request.user
    )
    return Response({'dismissed': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_sections(request):
    """Sections across every manual this staff member can reach.

    My Manuals navigates by document; this is the route for someone who
    knows the content but not which manual holds it, which is why search is
    what justifies the tab existing at all.

    Deliberately reuses the same filters list_sections already applies, so a
    search means the same thing from either direction.
    """
    if not access.has_unit(request.user):
        return _no_unit_error()

    sections = access.sections_for(
        request.user, ManualSection.objects.select_related('manual')
    )

    manual_id = request.query_params.get('manual')
    if manual_id:
        sections = sections.filter(manual_id=manual_id)

    tag = request.query_params.get('tag')
    if tag:
        sections = sections.filter(tag=tag)

    search = (request.query_params.get('search') or '').strip()
    if search:
        sections = sections.filter(
            Q(subtitle__icontains=search) | Q(content__icontains=search)
        )

    sections = sections.order_by('manual__title', 'order')[:400]

    data = [{
        'id': s.id,
        'manual_id': s.manual.id if s.manual else None,
        'manual': s.manual.title if s.manual else 'N/A',
        'subtitle': s.subtitle,
        'tag': s.tag,
        'order': s.order,
        'page_number': s.page_number,
        'content_preview': (s.content or '')[:220],
    } for s in sections]
    return Response({'count': len(data), 'results': data})


# ─── MANUALS ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminRole])
def list_manuals(request):
    manuals = Manual.objects.all()

    # Apply search filter with searchBy parameter
    search_query = request.query_params.get('search')
    search_by = request.query_params.get('searchBy', 'all')  # 'all', 'title', 'series', 'author'

    if search_query:
        if search_by == 'all':
            manuals = manuals.filter(
                Q(title__icontains=search_query) |
                Q(series__code__icontains=search_query) |
                Q(series__title__icontains=search_query) |
                Q(uploaded_by__username__icontains=search_query)
            )
        elif search_by == 'title':
            manuals = manuals.filter(title__icontains=search_query)
        elif search_by == 'series':
            manuals = manuals.filter(
                Q(series__code__icontains=search_query) |
                Q(series__title__icontains=search_query)
            )
        elif search_by == 'author':
            manuals = manuals.filter(uploaded_by__username__icontains=search_query)

    series_filter = request.query_params.get('series')
    if series_filter:
        manuals = manuals.filter(series_id=series_filter)

    # Apply author filter
    author_filter = request.query_params.get('author')
    if author_filter:
        manuals = manuals.filter(uploaded_by__username__icontains=author_filter)

    # Apply section count filter (minimum sections)
    min_sections = request.query_params.get('minSections')
    if min_sections:
        try:
            min_count = int(min_sections)
            manual_ids = [m.id for m in manuals if m.sections.count() >= min_count]
            manuals = manuals.filter(id__in=manual_ids)
        except ValueError:
            pass

    # Apply sorting
    sort_by = request.query_params.get('sortBy', 'newest')
    if sort_by == 'oldest':
        manuals = manuals.order_by('uploaded_at')
    else:
        manuals = manuals.order_by('-uploaded_at')

    data = [{
        'id': m.id,
        'title': m.title,
        # What this document *is* to the reader's offices, which is the
        # question a list of manuals actually answers.
        'series': m.series.code if m.series_id else None,
        'series_title': m.series.title if m.series_id else None,
        'owner': str(m.effective_owner) if m.effective_owner else None,
        'relationship': _relationship_for(request.user, m),
        'series_id': m.series_id,
        'uploaded_by': m.uploaded_by.username if m.uploaded_by else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': m.sections.count(),
        'version': m.version,
        'revision': m.revision,
        'display_status': f"v{m.version} rev{m.revision}",
        'status': document_status.status_payload(m.current_status),
    } for m in manuals]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def upload_manual(request):
    title = request.data.get('title')
    file = request.FILES.get('file')

    # No office or series here: a new document starts unassigned, and the
    # system admin links it to its series or offices on the organisation
    # screens.
    if not all([title, file]):
        return Response({'error': 'Title and file are required'}, status=400)

    file_bytes = file.read()
    file.seek(0)

    manual = Manual.objects.create(
        title=title,
        uploaded_by=request.user,
        file=file
    )

    try:
        extracted_text = extract_text(file_bytes, file.name)
    except Exception:
        extracted_text = ""

    sections_created = []
    if extracted_text.strip():
        blocks = _split_into_sections(extracted_text, title)
        created_sections = []
        for idx, block in enumerate(blocks):
            try:
                tag = predict_section(block['content']) if block['content'].strip() else 'UNTAGGED'
            except Exception:
                tag = 'UNTAGGED'

            parent = None
            parent_index = block.get('parent_index')
            if parent_index is not None and 0 <= parent_index < len(created_sections):
                parent = created_sections[parent_index]

            section = ManualSection.objects.create(
                manual=manual,
                subtitle=block['subtitle'],
                content=block['content'],
                tag=tag,
                page_number=block.get('page_number'),
                order=idx,
                parent=parent,
                is_reviewed=False,
            )
            created_sections.append(section)
            sections_created.append({
                'id': section.id,
                'subtitle': section.subtitle,
                'tag': section.tag,
            })

    return Response({
        'id': manual.id,
        'title': manual.title,
        'sections_created': len(sections_created),
        'message': f'Manual uploaded with {len(sections_created)} auto-detected sections.'
    }, status=201)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def preview_manual_sections(request):
    """Upload a file and return computed sectioning without saving sections."""
    title = request.data.get('title')
    file = request.FILES.get('file')

    # No office or series here: a new document starts unassigned, and the
    # system admin links it to its series or offices on the organisation
    # screens.
    if not all([title, file]):
        return Response({'error': 'Title and file are required'}, status=400)

    file_bytes = file.read()
    file.seek(0)

    manual = Manual.objects.create(
        title=title,
        uploaded_by=request.user,
        file=file
    )

    try:
        extracted_text = extract_text(file_bytes, file.name)
    except Exception:
        extracted_text = ""

    preview = []
    if extracted_text.strip():
        blocks = _split_into_sections(extracted_text, title)
        
        # Helper: Extract section number from subtitle
        def parse_section_number(subtitle):
            import re
            match = re.match(r'^(\d+(?:\.\d+)?)', subtitle)
            return match.group(1) if match else None
        
        # Helper: Check if section number is a parent (e.g., 1.0 or 1)
        def is_parent_section(sec_num):
            if not sec_num:
                return False
            parts = sec_num.split('.')
            return len(parts) == 1 or (len(parts) == 2 and parts[1] == '0')
        
        # Helper: Get parent index for a child section
        def find_parent_index(current_num, all_sections, current_idx):
            if not current_num:
                return None
            if not is_parent_section(current_num):
                # Skip invalid or unnumbered sections, or handle child sections
                if '.' in current_num:
                    parent_num = current_num.split('.')[0] + '.0'
                else:
                    return None
                
                # Look backwards to find the parent
                for i in range(current_idx - 1, -1, -1):
                    prev_subtitle = all_sections[i].get('subtitle', '')
                    prev_num = parse_section_number(prev_subtitle)
                    if prev_num == parent_num:
                        return i
            return None
        
        # First pass: collect all sections
        for idx, block in enumerate(blocks):
            try:
                tag = predict_section(block['content']) if block['content'].strip() else 'UNTAGGED'
            except Exception:
                tag = 'UNTAGGED'
            
            block_data = {
                'preview_index': idx,
                'subtitle': block['subtitle'],
                'content': block['content'],
                'tag': tag,
                'page_number': block.get('page_number'),
                'is_chapter': block.get('is_chapter', False),
                'parent_index': None,  # Will be set in second pass
            }
            preview.append(block_data)
        
        # Second pass: set parent_index for subsections
        for idx, sec in enumerate(preview):
            sec_num = parse_section_number(sec['subtitle'])
            parent_idx = find_parent_index(sec_num, preview, idx)
            if parent_idx is not None:
                sec['parent_index'] = parent_idx
    

    # `manual.file.url` can raise if the file is not yet saved or storage is misconfigured.
    file_url = None
    file_name = None
    try:
        file_url = manual.file.url
        file_name = manual.file.name
    except Exception:
        # Fall back to None so the preview still works
        file_url = None
        file_name = None

    return Response({
        'manual_id': manual.id,
        'title': manual.title,
        'file_url': file_url,
        'file_name': file_name,
        'sections_preview': preview,
    }, status=200)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def confirm_manual_sections(request, manual_id):
    """Create sections for a manual from a reviewed preview list."""
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)

    sections = request.data.get('sections')
    if not isinstance(sections, list):
        return Response({'error': 'Sections must be a list.'}, status=400)

    created_sections = []
    for idx, sec in enumerate(sections):
        parent = None
        parent_index = sec.get('parent_index')
        if parent_index is not None and 0 <= parent_index < len(created_sections):
            parent = created_sections[parent_index]

        section = ManualSection.objects.create(
            manual=manual,
            subtitle=sec.get('subtitle', ''),
            content=sec.get('content', ''),
            tag=sec.get('tag', 'UNTAGGED'),
            page_number=sec.get('page_number'),
            order=idx,
            parent=parent,
            is_reviewed=sec.get('is_reviewed', False),
        )
        created_sections.append(section)

    manual.revision += 1
    manual.save()

    return Response({
        'manual_id': manual.id,
        'sections_created': len(created_sections),
    }, status=201)


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def delete_manual(request, manual_id):
    """Takes the manual's sections and their revision history with it. The
    PDF on disk survives, so it can be imported again - the extracted text,
    the tagging and every proposed change to it cannot."""
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)
    held = _refuse_if_held(list(manual.sections.all()), 'deleted with the manual')
    if held:
        return held
    manual.delete()
    return Response({'message': 'Manual deleted.'})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def ocr_extract_manual(request, manual_id):
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)

    if not manual.file:
        return Response({'error': 'No file attached to this manual.'}, status=400)

    try:
        with manual.file.open('rb') as f:
            file_bytes = f.read()
        extracted_text = extract_text(file_bytes, manual.file.name)
    except Exception as e:
        return Response({'error': f'OCR failed: {str(e)}'}, status=500)

    return Response({
        'manual_id': manual.id,
        'title': manual.title,
        'extracted_text': extracted_text
    })


# ─── MANUAL SECTIONS ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_sections(request, manual_id):
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)

    if not access.can_reach(request.user, manual):
        return Response({'error': 'Access denied'}, status=403)

    # Remembering here rather than in the client records what was actually
    # served, and survives moving to another device.
    _record_recently_opened(request.user, manual)

    sections_qs = manual.sections.select_related(
        'parent', 'reviewed_by', 'status_changed__proposal',
    ).order_by('order')

    # Apply filters
    tag_filter = request.query_params.get('tag')
    if tag_filter:
        sections_qs = sections_qs.filter(tag=tag_filter)

    pending = request.query_params.get('pending')
    if pending and pending.lower() in ('1', 'true', 'yes'):
        sections_qs = sections_qs.filter(is_reviewed=False)

    # Apply search
    search_query = request.query_params.get('search')
    if search_query:
        sections_qs = sections_qs.filter(
            Q(subtitle__icontains=search_query) | Q(content__icontains=search_query)
        )

    data = [{
        'id': s.id,
        'subtitle': s.subtitle,
        'tag': s.tag,
        'page_number': s.page_number,
        'order': s.order,
        'parent_id': s.parent.id if s.parent else None,
        'content': s.content,
        'content_preview': s.content[:200],
        'version': s.version,
        'is_reviewed': s.is_reviewed,
        'reviewed_at': s.reviewed_at,
        'reviewed_by': s.reviewed_by.username if s.reviewed_by else None,
        # v4: the revision under which a request last changed this section,
        # and those requests. Nothing for a section none has changed.
        'revision': document_status.section_revision(s),
        'changes': document_status.section_changes(s) if s.status_changed_id else [],
    } for s in sections_qs]

    from .qms_views import can_correct_baseline, can_record_baseline
    return Response({
        # v3's counters, still sent for the admin's screens. Readers are
        # shown `status` instead.
        'manual_version': manual.version,
        'manual_revision': manual.revision,
        'display_status': f"v{manual.version} rev{manual.revision}",
        'status': document_status.status_payload(manual.current_status),
        'can_record_baseline': can_record_baseline(request.user, manual),
        'can_correct_baseline': can_correct_baseline(request.user, manual),
        'sections': data,
        'file_url': manual.file.url if manual.file else None,
        'file_name': manual.file.name if manual.file else None,
    })


@api_view(['POST'])
@permission_classes([IsAdminRole])
def create_section(request, manual_id):
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)

    subtitle = request.data.get('subtitle')
    content = request.data.get('content', '')
    page_number = request.data.get('page_number', None)
    order = request.data.get('order', 0)

    if not subtitle:
        return Response({'error': 'Subtitle is required'}, status=400)

    try:
        tag = predict_section(content) if content else 'UNTAGGED'
    except Exception:
        tag = 'UNTAGGED'

    # Determine parent: admin can override, otherwise auto-detect from subtitle
    parent = None
    parent_id = request.data.get('parent_id')

    if parent_id:
        # Admin explicitly specified parent
        try:
            parent = ManualSection.objects.get(id=parent_id, manual=manual)
        except ManualSection.DoesNotExist:
            return Response({'error': 'Parent section not found in this manual'}, status=400)
    else:
        # Auto-detect parent from section numbering
        parent = _find_parent_section_in_manual(manual, subtitle)

    section = ManualSection.objects.create(
        manual=manual,
        subtitle=subtitle,
        content=content,
        tag=tag,
        page_number=page_number,
        order=order,
        parent=parent,
    )

    return Response({
        'id': section.id,
        'subtitle': section.subtitle,
        'tag': section.tag,
        'page_number': section.page_number,
        'order': section.order,
        'parent_id': parent.id if parent else None,
    }, status=201)


@api_view(['PATCH'])
@permission_classes([IsAdminRole])
def update_section(request, section_id):
    # A direct edit changes a controlled document with no request behind
    # it - no concurrence, no IMR, no custodian - so it asks for the
    # password again, before anything is read or written.
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    # A direct edit is the only way a controlled document changes without
    # a revision behind it: no submitter, no reason, no review. The reason
    # is asked for here because this is the only place it can be asked -
    # every other path inherits one from the submission.
    #
    # It is recorded rather than enforced. An admin fixing a typo mid-audit
    # should not be blocked by a form, and a required field would be filled
    # with "." within a week, which is worse than an honest blank.
    reason = (request.data.get('change_reason') or '').strip()

    if _text_would_change(request, section):
        held = _refuse_if_held([section], 'edited')
        if held:
            return held

    SectionHistory.objects.create(
        section=section,
        version=section.version,
        subtitle=section.subtitle,
        content=section.content,
        tag=section.tag,
        edited_by=request.user,
        source='direct',
        change_reason=reason,
    )

    section.subtitle = request.data.get('subtitle', section.subtitle)
    section.content = request.data.get('content', section.content)
    section.page_number = request.data.get('page_number', section.page_number)
    section.order = request.data.get('order', section.order)
    section.version += 1

    # Allow manual tag override, otherwise auto-tag if content changed
    if 'tag' in request.data:
        section.tag = request.data['tag']
    elif 'content' in request.data:
        try:
            section.tag = predict_section(section.content)
        except Exception:
            section.tag = 'UNTAGGED'

    # Handle parent_id: admin can override, otherwise auto-detect from subtitle if it changed
    parent_id = request.data.get('parent_id')
    if parent_id:
        # Admin explicitly set parent
        try:
            section.parent = ManualSection.objects.get(id=parent_id, manual=section.manual)
        except ManualSection.DoesNotExist:
            return Response({'error': 'Parent section not found in this manual'}, status=400)
    elif 'subtitle' in request.data:
        # Subtitle changed - auto-detect parent from new subtitle
        section.parent = _find_parent_section_in_manual(section.manual, section.subtitle)

    section.save()

    manual = section.manual
    manual.revision += 1
    manual.save()

    return Response({
        'message': 'Section updated.',
        'tag': section.tag,
        'version': section.version,
        'manual_version': manual.version,
        'parent_id': section.parent.id if section.parent else None,
    })


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def delete_section(request, section_id):
    """A section carries its own version history, which goes with it."""
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)
    held = _refuse_if_held([section], 'deleted')
    if held:
        return held
    section.delete()
    return Response({'message': 'Section deleted.'})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def section_history(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    history = section.history.select_related('edited_by', 'proposal').order_by('version')
    data = [{
        'version': h.version,
        'subtitle': h.subtitle,
        'content': h.content,
        'tag': h.tag,
        'edited_by': h.edited_by.username if h.edited_by else 'N/A',
        'edited_at': h.edited_at,
        'source': h.source,
        'source_label': h.get_source_display(),
        'change_reason': h.change_reason,
        'proposal_id': h.proposal_id,
        'dcr_number': h.proposal.dcr_number if h.proposal_id else None,
    } for h in history]

    # The live section, appended as the last row. It has no source of its
    # own: a snapshot records the state *before* an edit, so what produced
    # the current text is recorded on whichever row comes next.
    data.append({
        'version': section.version,
        'subtitle': section.subtitle,
        'content': section.content,
        'tag': section.tag,
        'edited_by': 'Current',
        'edited_at': None,
        'source': 'current',
        'source_label': 'Current version',
        'change_reason': '',
        'proposal_id': None,
        'dcr_number': None,
    })

    return Response(data)


# ─── REVISIONS ───────────────────────────────────────────────


# ─── SVM MODEL EVALUATION ─────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])  # Allow anyone to view evaluation results
def evaluate_svm_model(request):
    """
    Run SVM model evaluation and return comprehensive metrics.
    This endpoint runs the evaluation on the expanded dataset and returns
    performance metrics that can be displayed in the frontend.
    """
    try:
        # Import evaluation components
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

        from expanded_dataset import texts, labels
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.svm import LinearSVC
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.metrics import (
            classification_report, confusion_matrix,
            accuracy_score, f1_score
        )
        from collections import Counter

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )

        # Vectorize
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000)
        X_train_vec = vectorizer.fit_transform(X_train)
        X_test_vec = vectorizer.transform(X_test)

        # Train model
        model = LinearSVC(class_weight='balanced', max_iter=2000, random_state=42)
        model.fit(X_train_vec, y_train)

        # Evaluate
        y_pred = model.predict(X_test_vec)

        # Calculate metrics
        accuracy = accuracy_score(y_test, y_pred)
        f1_weighted = f1_score(y_test, y_pred, average='weighted')
        f1_macro = f1_score(y_test, y_pred, average='macro')

        # Per-class F1 scores
        f1_per_class = f1_score(y_test, y_pred, average=None)
        class_names = sorted(set(labels))

        # Cross-validation
        cv_scores = cross_val_score(model, X_train_vec, y_train, cv=5, scoring='f1_weighted')

        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)

        # Prepare response data
        evaluation_results = {
            'dataset_info': {
                'total_samples': len(texts),
                'categories': class_names,
                'training_samples': len(X_train),
                'test_samples': len(X_test)
            },
            'overall_metrics': {
                'accuracy': round(accuracy * 100, 1),
                'f1_weighted': round(f1_weighted * 100, 1),
                'f1_macro': round(f1_macro * 100, 1)
            },
            'per_class_f1': {
                class_names[i]: round(f1_per_class[i] * 100, 1)
                for i in range(len(class_names))
            },
            'cross_validation': {
                'mean_f1': round(cv_scores.mean() * 100, 1),
                'std_f1': round(cv_scores.std() * 100, 1),
                'scores': [round(score * 100, 1) for score in cv_scores]
            },
            'confusion_matrix': {
                'labels': class_names,
                'matrix': cm.tolist()
            },
            'assessment': 'MODERATE' if accuracy >= 0.6 else 'NEEDS IMPROVEMENT'
        }

        return Response(evaluation_results)

    except Exception as e:
        return Response({
            'error': f'Evaluation failed: {str(e)}',
            'message': 'Unable to run SVM evaluation at this time'
        }, status=500)