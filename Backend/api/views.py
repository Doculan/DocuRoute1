from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser, BasePermission
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Q
from datetime import timedelta
from .models import (
    AccessMode, Announcement, AnnouncementDismissal, Concurrence, CustomUser,
    Department, Manual, ManualSection, ManualRevision, Office, OfficeLink,
    Position, PositionAssignment, Proposal, ProposalVersion, RecentlyOpened,
    RevisionPreAssessment, SectionHistory,
)
from ml.ocr_engine import extract_text
from ml.revision_pipeline.change_reason import (
    blocks_submission,
    classify_reason,
)
from api import access, pre_assessment
from ml.svm_model import predict, predict_section
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


# ─── WHO MAY REVIEW (transitional) ───────────────────────────
#
# TRANSITIONAL - REMOVE AT PHASE 1c.
#
# Spec section 5 moves the review screen from the admin to QMS staff.
# Applied literally, that would have left nobody able to review anything:
# QMS staff means holding a current IMR or Document Custodian position,
# positions belong to offices, offices are entered by hand in 1b, and the
# organisation ships empty. Every pending revision would have been
# stranded, and the one account able to fix it is the system admin, who
# by standing rule 7 should not also be deciding requests.
#
# So the system admin keeps review rights *until QMS positions can exist*.
# `tests_transitional_review.py` fails when this is removed, so the
# allowance cannot be forgotten - deleting it has to be a decision
# somebody makes, not something that quietly survives into v4 proper.

TRANSITIONAL_ADMIN_REVIEW = True


def holds_current_qms_position(user):
    """Does this person currently hold an IMR or Custodian position?

    Current means started and not ended. Checked by date rather than by a
    flag on the user, because the whole point of dated assignments is
    that "who holds this now" is derived, never stored and left stale.
    """
    if not (user and user.is_authenticated):
        return False

    today = timezone.localdate()
    return PositionAssignment.objects.filter(
        user=user,
        position__kind__in=Position.QMS_KINDS,
        position__is_active=True,
        starts_on__lte=today,
    ).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)
    ).exists()


class IsQmsReviewer(BasePermission):
    """May decide revisions: QMS staff, or - for now - the system admin.

    The admin half is transitional; see the note above.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if holds_current_qms_position(user):
            return True
        # TRANSITIONAL - REMOVE AT 1c, with TRANSITIONAL_ADMIN_REVIEW.
        return TRANSITIONAL_ADMIN_REVIEW and getattr(user, 'role', None) == 'admin'


# ─── RE-AUTHENTICATION ───────────────────────────────────────
#
# A JWT says who is holding the laptop, not who is sitting at it. For
# actions that cannot be undone - deleting a department takes every manual
# in it with it - that is the wrong question, so those endpoints ask for
# the password again.
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
    department_id = request.data.get('department_id', None)

    if CustomUser.objects.filter(username=username).exists():
        return Response({'error': 'Username already taken'}, status=400)

    user = CustomUser.objects.create_user(
        username=username,
        password=password,
        email=email,
        full_name=full_name,
        is_approved=False
    )

    if department_id:
        try:
            dept = Department.objects.get(id=department_id)
            user.department = dept
            user.save()
        except Department.DoesNotExist:
            pass

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
        # v4. Which portal, and which nav groups within it. The v3 `role`
        # still drives every permission check until 1c; this is sent
        # alongside so the organisation screens can be shown to the people
        # who can actually use them.
        'system_role': user.system_role,
        'username': user.username,
        'department': user.department.name if user.department else None,
        'department_id': user.department.id if user.department else None,
    })


# ─── ADMIN: USERS ────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminRole])
def pending_users(request):
    users = CustomUser.objects.filter(is_approved=False)
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'department': u.department.name if u.department else 'N/A'} for u in users]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def approved_users(request):
    users = CustomUser.objects.filter(is_approved=True)
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'role': u.role,
             'department': u.department.name if u.department else 'N/A'} for u in users]
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


# ─── DEPARTMENTS ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def list_departments(request):
    departments = Department.objects.all()
    data = [{'id': d.id, 'name': d.name} for d in departments]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def create_department(request):
    name = request.data.get('name')
    if not name:
        return Response({'error': 'Department name is required'}, status=400)
    if Department.objects.filter(name=name).exists():
        return Response({'error': 'Department already exists'}, status=400)
    dept = Department.objects.create(name=name)
    return Response({'id': dept.id, 'name': dept.name}, status=201)


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def delete_department(request, dept_id):
    """Disabled in v4 phase 1a. Answers 409, deletes nothing.

    `Manual.department` cascades, so this endpoint destroyed every manual
    in the department, every section under those manuals and every
    revision ever proposed against them - controlled documents and their
    history, removed by one confirmed click.

    That is against the standing rule that nothing in the organisation is
    ever deleted, and `Office` deliberately does not repeat it: every
    relationship into the new organisation is PROTECT, and offices are
    deactivated or merged instead.

    Kept as a 409 rather than deleted outright because the Departments
    screen still calls it and will until Offices replaces that screen at
    1c. A route that vanishes gives the browser a 404 and the admin no
    idea why; this says what happened and what to do instead. **Remove
    this function, its route and its test at 1c**, with the screen.
    """
    try:
        dept = Department.objects.get(id=dept_id)
    except Department.DoesNotExist:
        return Response({'error': 'Department not found'}, status=404)

    return Response({
        'error': (
            f'Departments can no longer be deleted. Deleting "{dept.name}" '
            f'would also delete {dept.manuals.count()} manual(s), their '
            f'sections and every revision proposed against them. '
            f'Departments are being replaced by Offices, which are '
            f'deactivated or merged instead of deleted.'
        ),
        'reason': 'deletion_disabled',
    }, status=409)


# ─── STAFF ENDPOINTS ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_list_manuals(request):
    """Return manuals belonging to the logged-in staff member's department."""
    dept = getattr(request.user, 'department', None)
    if not dept:
        return _no_unit_error()
    manuals = access.manuals_for(
        request.user, Manual.objects.all()
    ).order_by('-uploaded_at')
    data = [{
        'id': m.id,
        'title': m.title,
        # v4: what this document *is* to the reader's offices, which is
        # the question a list of manuals actually answers. The department
        # is kept alongside until it is retired, so nothing that still
        # reads it breaks mid-switchover.
        'department': m.department.name if m.department else 'N/A',
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
    } for m in manuals]
    return Response(data)


def _has_unread_feedback(revision) -> bool:
    """Feedback the submitter has not looked at since it was written."""
    if not (revision.reviewed_at and (revision.reviewer_notes or '').strip()):
        return False
    return (revision.feedback_seen_at is None
            or revision.feedback_seen_at < revision.reviewed_at)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_my_revisions(request):
    """Revisions this staff member submitted, or their whole office.

    Scope and status are filters over one list rather than separate views, so
    the columns stay comparable when the scope is widened - the point of
    looking at the office is to compare it with your own.

    Read-only, and the AI fields are the snapshot stored at submission. The
    check is never re-run here: what the submitter read before submitting is
    the record, and re-running it would produce a second, different verdict
    for the same revision.
    """
    scope = (request.query_params.get('scope') or 'mine').strip().lower()
    status_filter = (request.query_params.get('status') or 'all').strip().lower()

    revisions = ManualRevision.objects.select_related(
        'section', 'section__manual', 'submitted_by', 'reviewed_by'
    )
    if scope == 'office':
        department = getattr(request.user, 'department', None)
        if not department:
            return _no_unit_error()
        revisions = access.revisions_for(request.user, revisions)
    else:
        scope = 'mine'
        revisions = revisions.filter(submitted_by=request.user)

    # "Returned" is not a stored state - a revision sent back is rejected
    # with notes, and that is what the submitter is asked to act on. Splitting
    # it out here rather than adding a state keeps the review flow untouched.
    if status_filter == 'returned':
        revisions = revisions.filter(status='rejected').exclude(reviewer_notes='')
    elif status_filter in ('pending', 'approved', 'rejected'):
        revisions = revisions.filter(status=status_filter)

    revisions = revisions.order_by('-submitted_at')

    data = [{
        'id': r.id,
        'section_id': r.section.id if r.section else None,
        'section': r.section.subtitle if r.section else 'N/A',
        'manual': r.section.manual.title if r.section and r.section.manual else 'N/A',
        'manual_id': r.section.manual.id if r.section and r.section.manual else None,
        'submitted_by': r.submitted_by.username if r.submitted_by else 'N/A',
        'is_mine': r.submitted_by_id == request.user.id,
        'submitted_at': r.submitted_at,
        'status': r.status,
        'reviewer_notes': r.reviewer_notes,
        'reviewed_by': r.reviewed_by.username if r.reviewed_by else None,
        'reviewed_at': r.reviewed_at,
        'has_unread_feedback': _has_unread_feedback(r),
        'diff_preview': preview_diff(r.diff_text),
        'diff_text': r.diff_text,
        'change_reason': r.change_reason,
        # The stored snapshot, exactly as the submitter saw it.
        'ai_source': r.ai_source,
        'ai_verdict': r.ai_verdict,
        'ai_issues': r.ai_issues,
        'ai_explanation_staff': r.ai_explanation_staff,
        'ai_assessed_at': r.ai_assessed_at,
    } for r in revisions]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def staff_mark_feedback_seen(request, revision_id):
    """Record that the submitter has read this revision's feedback.

    The one write this portal adds. Without it the badge on My Revisions
    could only ever count, never clear, which would train people to ignore
    it. Only the submitter can mark their own, and it sets a timestamp -
    nothing about the revision or its assessment changes.
    """
    try:
        revision = ManualRevision.objects.get(
            id=revision_id, submitted_by=request.user
        )
    except ManualRevision.DoesNotExist:
        return Response({'error': 'Revision not found'}, status=404)

    revision.feedback_seen_at = timezone.now()
    revision.save(update_fields=['feedback_seen_at'])
    return Response({'feedback_seen_at': revision.feedback_seen_at})


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


def _superseded_by_proposals(what='This'):
    """The v3 single-section flow, once proposals are the real one.

    Refused rather than removed, like `delete_department`: a route that
    vanishes gives an open browser tab a 404 and the person no idea why.
    This says what replaced it and where to go.

    Only while the access switch is on. With it off these are still the
    only way to change a document, and they work exactly as they did.
    """
    return Response({
        'error': (
            f'{what} has been replaced by proposals. A change is now '
            f'drafted for the whole document, with each changed section '
            f'carrying its own check, and agreed by the offices that '
            f'concur on it.'
        ),
        'reason': 'superseded_by_proposals',
    }, status=409)


def _merging_is_deleting():
    """Merging two sections deletes one of them.

    Out of scope for P2, which changes existing sections only. It returns
    with adding and deleting sections rather than being quietly dropped -
    the operation is legitimate, it just has no home in a proposal yet.
    """
    return Response({
        'error': (
            'Merging sections is not available while a change is proposed '
            'for a whole document. Merging deletes a section, and adding '
            'or deleting sections is not part of a proposal yet.'
        ),
        'reason': 'merge_out_of_scope',
    }, status=409)


def _no_unit_error():
    """What someone sees when their account works and shows nothing.

    Named after whichever unit the system is currently scoping by, because
    telling a person they have no department when the system stopped
    caring about departments sends them to ask the wrong question. It also
    says who fixes it - the alternative is an error that reads like a
    fault in the software.
    """
    if access.by_position():
        return Response({
            'error': (
                'Your account is approved but not yet assigned to an office. '
                'The system administrator will assign you.'
            ),
            'reason': 'no_position',
        }, status=403)
    return Response({
        'error': 'You are not assigned to a department.',
        'reason': 'no_department',
    }, status=403)


def _relationship_for(user, manual):
    """What this document is to the person looking at it.

    Owner, Concurring, Read only - or None before the switchover, when the
    answer is simply "your department's", and saying anything else would
    be inventing a relationship that does not exist yet.

    An office can own a manual *and* concur on it, so more than one label
    can apply and both are shown.
    """
    if not access.by_position():
        return None

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
    """Active announcements for everyone, plus the ones aimed at this
    person's own unit.

    Which unit that is follows the same switch as document access, so
    notices and access change together. Leaving announcements on
    departments after the switch would mean the system scoped documents by
    office and notices by department - two answers to "where do you work"
    living in one application.

    An untargeted announcement is for everyone either way.
    """
    if access.by_position():
        offices = access.current_offices(user) if (
            user and user.is_authenticated
        ) else []
        return Announcement.objects.filter(active=True).filter(
            # Untargeted means untargeted *in this mode*. A notice still
            # carrying only a department has targeting the system can no
            # longer express - and the safe reading of that is "nobody",
            # not "everybody". Treating it as untargeted would take a
            # notice meant for one department and broadcast it to the
            # whole university, which is the worse of the two mistakes by
            # a long way. The switchover screen lists these so they can be
            # re-aimed at an office.
            Q(office__isnull=True, department__isnull=True)
            | Q(office__in=offices)
        ).select_related('office', 'department')

    return Announcement.objects.filter(active=True).filter(
        Q(department__isnull=True) | Q(department=getattr(user, 'department', None))
    ).select_related('department', 'office')


def _announcement_payload(announcement):
    """One announcement, plus who can actually see it.

    `shows_as` is computed rather than stored: a dated item is Upcoming and
    an undated one is the banner, and deriving it here means the admin list
    and the staff dashboard can never disagree about which a row is.
    """
    audience = CustomUser.objects.filter(role='staff', is_approved=True)
    if access.by_position():
        if announcement.office_id:
            audience = audience.filter(
                position_assignments__position__office_id=announcement.office_id,
                position_assignments__ends_on__isnull=True,
            ).distinct()
    elif announcement.department_id:
        audience = audience.filter(department_id=announcement.department_id)

    return {
        'id': announcement.id,
        'title': announcement.title,
        'body': announcement.body,
        'date': announcement.date,
        'shows_as': 'upcoming' if announcement.date else 'banner',
        'department_id': announcement.department_id,
        'department': announcement.department.name if announcement.department else None,
        'office_id': announcement.office_id,
        'office': str(announcement.office) if announcement.office_id else None,
        # Which of the two fields is actually being read right now, so the
        # admin screen does not have to work it out from the flag.
        'targets_by': 'office' if access.by_position() else 'department',
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

    if 'department_id' in data or not partial:
        raw = data.get('department_id')
        if raw in (None, '', 'null', 'all'):
            fields['department'] = None
        else:
            try:
                fields['department'] = Department.objects.get(id=raw)
            except (Department.DoesNotExist, ValueError, TypeError):
                return None, Response(
                    {'error': 'That department does not exist.',
                     'field': 'department_id'},
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
            'department', 'created_by'
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
            'department', 'created_by'
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

    Decisions are counted on the day they were *made*, not the day the
    submission arrived: the question this answers is how much reviewing
    is happening, and a decision taken today about a month-old submission
    is today's work.

    **Reads both flows.** Before the switch the numbers are single-section
    revisions; afterwards they are proposals. Reading only one would make
    the chart go blank at the moment access changed, which would look
    like the system stopped being used.

    The two are counted into the same three series rather than shown
    apart. A reader of this chart is asking how much work is moving, and
    which internal shape a change had is not that question - `mode` says
    which is being counted for anyone who needs it.
    """
    submitted = {}
    approved, rejected = {}, {}

    def add(bucket, value):
        day = timezone.localtime(value).date()
        bucket[day] = bucket.get(day, 0) + 1

    for value in ManualRevision.objects.filter(
        submitted_at__date__gte=window_start
    ).values_list('submitted_at', flat=True):
        add(submitted, value)

    for value, outcome in ManualRevision.objects.filter(
        reviewed_at__isnull=False, reviewed_at__date__gte=window_start
    ).values_list('reviewed_at', 'status'):
        add(approved if outcome == 'approved' else rejected, value)

    # A proposal is submitted once per version, so a redraft counts as
    # another submission - which is true: it was drafted and sent again.
    for value in ProposalVersion.objects.filter(
        submitted_at__isnull=False, submitted_at__date__gte=window_start,
    ).values_list('submitted_at', flat=True):
        add(submitted, value)

    # Locked is the proposal equivalent of approved: everyone agreed.
    for value in Proposal.objects.filter(
        locked_at__isnull=False, locked_at__date__gte=window_start,
    ).values_list('locked_at', flat=True):
        add(approved, value)

    # A return is the equivalent of sending it back.
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
    slow. It also replaces the two separate count requests the shell was
    firing on every tab change, so the nav badges and the dashboard can no
    longer disagree with each other.

    Reads stored assessment fields only. Nothing here re-runs an assessment
    - a dashboard that quietly reassessed six revisions on every load would
    be both slow and dishonest, since the figure shown would not be the one
    the reviewer acted on.
    """
    today = timezone.localdate()
    window_start = today - timedelta(days=ACTIVITY_WINDOW_DAYS - 1)

    pending_revisions = ManualRevision.objects.filter(
        status='pending'
    ).select_related('section', 'section__manual', 'submitted_by')

    # -- 1. needs attention --------------------------------------
    # Only the rows that are not zero reach the screen, but the endpoint
    # reports all of them: "nothing is waiting" is a real answer and the
    # client should not have to infer it from a missing key.
    oldest = pending_revisions.order_by('submitted_at').first()
    stale = sum(1 for r in pending_revisions if _section_moved_since(r))
    attention = {
        'pending_users': CustomUser.objects.filter(
            is_approved=False, role='staff'
        ).count(),
        'pending_revisions': pending_revisions.count(),
        # A revision whose section was edited after the assessment was made:
        # the advice on the review screen is about text that has moved, and
        # the reviewer needs to know before acting on it.
        'stale_assessments': stale,
        'oldest_pending_days': (
            (today - timezone.localtime(oldest.submitted_at).date()).days
            if oldest else None
        ),
        'untagged_sections': ManualSection.objects.filter(
            Q(tag='') | Q(tag='UNTAGGED')
        ).count(),
    }

    # Proposals, once they are the real flow. Reported alongside rather
    # than instead of the revision counts: during the changeover both can
    # be non-zero, and a dashboard that hid one would be wrong for
    # exactly the period somebody was watching it most closely.
    proposals_open = Proposal.objects.filter(
        status__in=Proposal.OPEN_STATUSES
    )
    attention.update({
        'proposals_drafting': proposals_open.filter(
            status=Proposal.DRAFT
        ).count(),
        'proposals_in_concurrence': proposals_open.filter(
            status=Proposal.CONCURRENCE
        ).count(),
        # Agreed and waiting for the paperwork. Every frozen status, not
        # just `LOCKED`: once 3b generates the documents a new lock rests
        # at `AWAITING_SIGNATURE`, and a counter reading one status would
        # quietly fall to zero while the proposals piled up.
        'proposals_locked': Proposal.objects.filter(
            status__in=Proposal.FROZEN_STATUSES
        ).count(),
    })

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

    # -- 3. revisions by department ------------------------------
    # Grouped through the section's manual, which is where a revision's
    # department actually comes from - the submitter's own department can
    # differ after a transfer, and the document is the thing being changed.
    by_department = {}
    for name, outcome in ManualRevision.objects.values_list(
        'section__manual__department__name', 'status'
    ):
        row = by_department.setdefault(
            name or 'Unassigned',
            {'department': name or 'Unassigned',
             'pending': 0, 'approved': 0, 'rejected': 0, 'total': 0},
        )
        if outcome in row:
            row[outcome] += 1
        row['total'] += 1
    departments = sorted(
        by_department.values(),
        key=lambda r: (-r['pending'], -r['total'], r['department']),
    )

    # -- 4. recent decisions -------------------------------------
    decisions = [{
        'revision_id': r.id,
        'manual': r.section.manual.title if r.section and r.section.manual else 'N/A',
        'section': r.section.subtitle if r.section else 'N/A',
        'status': r.status,
        'submitted_by': r.submitted_by.username if r.submitted_by else 'N/A',
        'reviewed_by': r.reviewed_by.username if r.reviewed_by else None,
        'at': r.reviewed_at,
        # What the pipeline had said, so a pattern of overruling it is
        # visible. Stored, never recomputed.
        'ai_verdict': r.ai_verdict or None,
        'agreed': (
            None if not r.ai_verdict else
            (r.status == 'approved') == (r.ai_verdict == 'approve')
        ),
    } for r in ManualRevision.objects.filter(reviewed_at__isnull=False)
        .select_related('section', 'section__manual', 'submitted_by', 'reviewed_by')
        .order_by('-reviewed_at')[:6]]

    # -- 5. upcoming ---------------------------------------------
    # The admin sees every department's notices, not only their own: this is
    # the posting desk, and the point is to see what has been scheduled.
    scheduled = Announcement.objects.filter(
        active=True, date__gte=today
    ).select_related('department').order_by('date')
    upcoming = [{
        'id': a.id,
        'title': a.title,
        'date': a.date,
        'is_today': a.date == today,
        'department': a.department.name if a.department else None,
    } for a in scheduled[:5]]

    # -- 6. system state -----------------------------------------
    # How the assessments on file were produced. "none" is the legacy
    # fallback and a count above zero means old revisions predate the
    # pre-check, which explains why their review screens look different.
    sources = {'staff_precheck': 0, 'admin_legacy': 0, 'none': 0}
    for source in ManualRevision.objects.values_list('ai_source', flat=True):
        key = source or 'none'
        if key in sources:
            sources[key] += 1

    system = {
        'manuals': Manual.objects.count(),
        'sections': ManualSection.objects.count(),
        'departments': Department.objects.count(),
        'staff': CustomUser.objects.filter(role='staff', is_approved=True).count(),
        'admins': CustomUser.objects.filter(role='admin').count(),
        'empty_departments': Department.objects.filter(manuals__isnull=True).count(),
        'revisions_total': ManualRevision.objects.count(),
        'assessment_sources': sources,
        'banners_live': Announcement.objects.filter(
            active=True, date__isnull=True
        ).count(),
    }

    # Which flow the figures above describe. The chart counts both, but
    # a reader deserves to know which one the system is actually using.
    activity['mode'] = 'proposals' if access.by_position() else 'revisions'

    system['proposals_total'] = Proposal.objects.count()

    return Response({
        'attention': attention,
        'activity': activity,
        'departments': departments,
        'decisions': decisions,
        'proposals': _recent_proposals(),
        'upcoming': upcoming,
        'upcoming_total': scheduled.count(),
        'system': system,
    })


def _recent_proposals():
    """The last few proposals and where each has got to.

    The revision list answers "what was decided"; this answers "what is
    moving". Both are shown while both flows can carry work.
    """
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
    department = getattr(user, 'department', None)
    today = timezone.localdate()

    mine = ManualRevision.objects.filter(submitted_by=user).select_related(
        'section', 'section__manual', 'reviewed_by'
    )

    # -- needs your attention ------------------------------------
    returned = [r for r in mine if r.status == 'rejected'
                and (r.reviewer_notes or '').strip()]
    attention = {
        'awaiting_review': mine.filter(status='pending').count(),
        'new_feedback': sum(1 for r in mine if _has_unread_feedback(r)),
        'returned': len(returned),
    }

    # -- recent activity: what happened to your submissions ------
    activity = [{
        'revision_id': r.id,
        'manual': r.section.manual.title if r.section and r.section.manual else 'N/A',
        'section': r.section.subtitle if r.section else 'N/A',
        'status': r.status,
        'returned': bool(r.status == 'rejected' and (r.reviewer_notes or '').strip()),
        'at': r.reviewed_at,
    } for r in mine.exclude(reviewed_at=None).order_by('-reviewed_at')[:5]]

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

    # Which flow this portal is running, so the shell can name the tab
    # "My Revisions" or "My Proposals" without a second request - and how
    # much is waiting on this person's offices, for the badge.
    by_position = access.by_position()
    awaiting = 0
    if by_position:
        from .concurrence_views import _offices_yet_to_decide
        # Not `mine` - that name already holds this person's revisions a
        # few lines above, and rebinding it made the dashboard count a
        # list instead of a queryset.
        my_office_ids = [o.pk for o in access.current_offices(user)]
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
        'access_by_position': by_position,
        'proposals_awaiting': awaiting,
        'proposals_mine': (
            Proposal.objects.filter(
                initiating_office__in=access.current_offices(user)
            ).count() if by_position else 0
        ),
        'attention': attention,
        'activity': activity,
        'recently_opened': recent,
        'announcement': None if banner is None else {
            'id': banner.id, 'title': banner.title, 'body': banner.body,
        },
        'upcoming': upcoming,
        'upcoming_total': visible.filter(date__gte=today).count(),
        'stats': {
            'manuals_total': Manual.objects.count(),
            'manuals_mine': access.manuals_for(user, Manual.objects.all()).count(),
            'revisions_mine': mine.count(),
            'department': department.name if department else None,
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
    department = getattr(request.user, 'department', None)
    if not department:
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
    search_by = request.query_params.get('searchBy', 'all')  # 'all', 'title', 'department', 'author'
    
    if search_query:
        if search_by == 'all':
            manuals = manuals.filter(
                Q(title__icontains=search_query) | 
                Q(department__name__icontains=search_query) |
                Q(uploaded_by__username__icontains=search_query)
            )
        elif search_by == 'title':
            manuals = manuals.filter(title__icontains=search_query)
        elif search_by == 'department':
            manuals = manuals.filter(department__name__icontains=search_query)
        elif search_by == 'author':
            manuals = manuals.filter(uploaded_by__username__icontains=search_query)

    # Apply department filter
    dept_filter = request.query_params.get('department')
    if dept_filter:
        manuals = manuals.filter(department_id=dept_filter)

    # Apply author filter
    author_filter = request.query_params.get('author')
    if author_filter:
        manuals = manuals.filter(uploaded_by__username__icontains=author_filter)

    # Apply version filter
    version_filter = request.query_params.get('version')
    if version_filter:
        try:
            version = int(version_filter)
            manuals = manuals.filter(version=version)
        except ValueError:
            pass

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
        # v4: what this document *is* to the reader's offices, which is
        # the question a list of manuals actually answers. The department
        # is kept alongside until it is retired, so nothing that still
        # reads it breaks mid-switchover.
        'department': m.department.name if m.department else 'N/A',
        'series': m.series.code if m.series_id else None,
        'series_title': m.series.title if m.series_id else None,
        'owner': str(m.effective_owner) if m.effective_owner else None,
        'relationship': _relationship_for(request.user, m),
        'department_id': m.department.id if m.department else None,
        'uploaded_by': m.uploaded_by.username if m.uploaded_by else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': m.sections.count(),
        'version': m.version,
        'revision': m.revision,
        'display_status': f"v{m.version} rev{m.revision}",
    } for m in manuals]
    return Response(data)


@api_view(['PATCH'])
@permission_classes([IsAdminRole])
def set_manual_version(request, manual_id):
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)

    new_version = request.data.get('version')
    if new_version is None:
        return Response({'error': 'Version is required.'}, status=400)

    try:
        new_version_int = int(new_version)
    except (TypeError, ValueError):
        return Response({'error': 'Version must be an integer.'}, status=400)

    if new_version_int <= 0:
        return Response({'error': 'Version must be positive.'}, status=400)

    if new_version_int == manual.version:
        return Response({'message': 'Version unchanged.'}, status=200)

    manual.version = new_version_int
    manual.revision = 0
    manual.save()

    return Response({
        'id': manual.id,
        'version': manual.version,
        'revision': manual.revision,
        'display_status': f"v{manual.version} rev{manual.revision}",
    }, status=200)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def upload_manual(request):
    title = request.data.get('title')
    department_id = request.data.get('department_id')
    file = request.FILES.get('file')

    if not all([title, department_id, file]):
        return Response({'error': 'Title, department, and file are required'}, status=400)

    try:
        department = Department.objects.get(id=department_id)
    except Department.DoesNotExist:
        return Response({'error': 'Department not found'}, status=404)

    file_bytes = file.read()
    file.seek(0)

    manual = Manual.objects.create(
        title=title,
        department=department,
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
        'department': department.name,
        'sections_created': len(sections_created),
        'message': f'Manual uploaded with {len(sections_created)} auto-detected sections.'
    }, status=201)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def preview_manual_sections(request):
    """Upload a file and return computed sectioning without saving sections."""
    title = request.data.get('title')
    department_id = request.data.get('department_id')
    file = request.FILES.get('file')

    if not all([title, department_id, file]):
        return Response({'error': 'Title, department, and file are required'}, status=400)

    try:
        department = Department.objects.get(id=department_id)
    except Department.DoesNotExist:
        return Response({'error': 'Department not found'}, status=404)

    file_bytes = file.read()
    file.seek(0)

    manual = Manual.objects.create(
        title=title,
        department=department,
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
        'department': department.name,
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

    sections_qs = manual.sections.all().order_by('order')

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
    } for s in sections_qs]

    return Response({
        'manual_version': manual.version,
        'manual_revision': manual.revision,
        'display_status': f"v{manual.version} rev{manual.revision}",
        'sections': data,
        'file_url': manual.file.url if manual.file else None,
        'file_name': manual.file.name if manual.file else None,
    })


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def review_section(request, section_id):
    """Review or edit a section before final approval."""
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if not access.can_reach_section(request.user, section):
        return Response({'error': 'Access denied'}, status=403)

    # Update content/metadata if provided
    section.subtitle = request.data.get('subtitle', section.subtitle)
    section.content = request.data.get('content', section.content)
    section.tag = request.data.get('tag', section.tag)
    section.page_number = request.data.get('page_number', section.page_number)
    section.order = request.data.get('order', section.order)

    # Handle parent_id: staff can override, otherwise auto-detect if subtitle changed
    parent_id = request.data.get('parent_id')
    if parent_id:
        try:
            section.parent = ManualSection.objects.get(id=parent_id, manual=section.manual)
        except ManualSection.DoesNotExist:
            return Response({'error': 'Parent section not found in this manual'}, status=400)
    elif 'subtitle' in request.data:
        section.parent = _find_parent_section_in_manual(section.manual, section.subtitle)

    approve = request.data.get('approve', True)
    if isinstance(approve, str):
        approve = approve.lower() in ('1', 'true', 'yes')

    if approve:
        section.is_reviewed = True
        section.reviewed_by = request.user
        section.reviewed_at = timezone.now()
    else:
        section.is_reviewed = False
        section.reviewed_by = None
        section.reviewed_at = None

    # Re-tag if content updated
    if 'content' in request.data:
        try:
            section.tag = predict_section(section.content)
        except Exception:
            section.tag = 'UNTAGGED'

    section.save()

    return Response({
        'id': section.id,
        'subtitle': section.subtitle,
        'tag': section.tag,
        'is_reviewed': section.is_reviewed,
        'reviewed_at': section.reviewed_at,
        'reviewed_by': section.reviewed_by.username if section.reviewed_by else None,
        'parent_id': section.parent.id if section.parent else None,
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
    section.delete()
    return Response({'message': 'Section deleted.'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def review_delete_section(request, section_id):
    """Delete a section during review (staff can delete within their department).

    Guarded like the admin route, because it deletes the same row. The admin
    Sections screen used to call this one *first* and fall back to
    `delete_section`, so asking for a password on the admin route alone
    would have secured a path nothing took - the deletion would simply have
    gone through here. No staff screen calls this endpoint today; the
    permission is left as it was rather than narrowed on a guess about who
    it was for.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if not access.can_reach_section(request.user, section):
        return Response({'error': 'Access denied'}, status=403)

    section.delete()
    return Response({'message': 'Section deleted.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def merge_sections(request, section_id):
    """Merge one section into another. The source is section_id.

    Payload:
      {
        "target_id": <other_section_id>
      }

    The source section is deleted after merging.
    """
    try:
        source = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Source section not found'}, status=404)

    target_id = request.data.get('target_id')
    if not target_id:
        return Response({'error': 'target_id is required'}, status=400)

    try:
        target = ManualSection.objects.get(id=target_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Target section not found'}, status=404)

    # Only allow merge within same manual
    if source.manual_id != target.manual_id:
        return Response({'error': 'Sections must belong to the same manual'}, status=400)

    if access.by_position():
        return _merging_is_deleting()

    if not access.can_reach_section(request.user, source):
        return Response({'error': 'Access denied'}, status=403)

    # Save history for target
    SectionHistory.objects.create(
        section=target,
        version=target.version,
        subtitle=target.subtitle,
        content=target.content,
        tag=target.tag,
        edited_by=request.user,
        source='merge',
        change_reason=f'Merged with "{source.subtitle}".',
    )

    # Merge: append source subtitle + content to target (keep source title as part of merged section)
    separator = "\n\n" if target.content and (source.subtitle or source.content) else ""
    source_header = f"{source.subtitle}\n\n" if source.subtitle else ""
    target.content = f"{target.content}{separator}{source_header}{source.content}"
    try:
        target.tag = predict_section(target.content)
    except Exception:
        target.tag = 'UNTAGGED'

    target.version += 1
    target.save()

    # Delete source after merging
    source.delete()

    return Response({
        'message': 'Sections merged successfully.',
        'target_id': target.id,
        'target_subtitle': target.subtitle,
        'target_tag': target.tag,
        'target_version': target.version,
    })


@api_view(['GET'])
@permission_classes([IsAdminRole])
def section_history(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    history = section.history.select_related('edited_by').order_by('version')
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
        'revision_id': h.revision_id,
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
        'revision_id': None,
    })

    return Response(data)


# ─── REVISIONS ───────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_revision(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if access.by_position():
        return _superseded_by_proposals('Uploading a revision for one section')

    if not access.can_propose_to_section(request.user, section):
        return Response({'error': 'Access denied'}, status=403)

    if 'file' not in request.FILES:
        return Response({'error': 'No file uploaded'}, status=400)

    uploaded_file = request.FILES['file']
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    text_new = extract_text(file_bytes, uploaded_file.name)

    diff = build_diff(section.content, text_new)
    change_reason, error = _validated_change_reason(request, section)
    if error:
        return error

    # Hashed on the extracted text, not the file's bytes. Extraction is what
    # the assessment saw and what the reviewer will read, so that is what has
    # to match - and it means re-uploading a byte-identical file after a check
    # is not treated as a change.
    snapshot, error = _consume_pre_assessment(
        request, section, text_new, change_reason
    )
    if error:
        return error

    revision = ManualRevision.objects.create(
        section=section,
        submitted_by=request.user,
        uploaded_file=uploaded_file,
        diff_text=diff,
        change_reason=change_reason,
        status='pending'
    )
    _attach_pre_assessment(revision, snapshot)

    return Response({
        'revision_id': revision.id,
        'diff_preview': preview_diff(diff),
        'status': revision.status,
        'ai_verdict': revision.ai_verdict,
    }, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def propose_text_revision(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if access.by_position():
        return _superseded_by_proposals('Proposing a change to one section')

    if not access.can_propose_to_section(request.user, section):
        return Response({'error': 'Access denied'}, status=403)

    proposed_content = request.data.get('proposed_content')
    if not proposed_content:
        return Response({'error': 'Proposed content is required'}, status=400)

    diff = build_diff(section.content, proposed_content)
    change_reason, error = _validated_change_reason(request, section)
    if error:
        return error

    snapshot, error = _consume_pre_assessment(
        request, section, proposed_content, change_reason
    )
    if error:
        return error

    revision = ManualRevision.objects.create(
        section=section,
        submitted_by=request.user,
        proposed_content=proposed_content,
        diff_text=diff,
        change_reason=change_reason,
        status='pending'
    )
    _attach_pre_assessment(revision, snapshot)

    return Response({
        'revision_id': revision.id,
        'diff_preview': preview_diff(diff),
        'status': revision.status,
        'ai_verdict': revision.ai_verdict,
    }, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def propose_merge(request):
    source_section_id = request.data.get('source_section_id')
    target_section_id = request.data.get('target_section_id')

    if not source_section_id or not target_section_id:
        return Response({'error': 'source_section_id and target_section_id are required.'}, status=400)

    try:
        source = ManualSection.objects.get(id=source_section_id)
        target = ManualSection.objects.get(id=target_section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if access.by_position():
        return _merging_is_deleting()

    if not access.can_propose_to_section(request.user, target):
        return Response({'error': 'Access denied'}, status=403)

    if source.manual.id != target.manual.id:
        return Response({'error': 'Cannot merge sections from different manuals.'}, status=400)

    if source.id == target.id:
        return Response({'error': 'Source and target must be different sections.'}, status=400)

    sources = _merge_sources(target, [source.id])
    merged_content = _merged_content(target, sources)
    diff = build_diff(target.content, merged_content)
    change_reason, error = _validated_change_reason(request, target)
    if error:
        return error

    # The merged text is derived here exactly as the check derived it, so a
    # merge that was checked still matches. If either the target or a source
    # has moved since, the hash differs and the submitter is told it was not
    # their doing.
    snapshot, error = _consume_pre_assessment(
        request, target, merged_content, change_reason, sources=sources
    )
    if error:
        return error

    revision = ManualRevision.objects.create(
        section=target,
        submitted_by=request.user,
        merge_section_ids=[source.id],
        merge_type='merge',
        diff_text=diff,
        change_reason=change_reason,
        status='pending'
    )
    _attach_pre_assessment(revision, snapshot)

    return Response({
        'revision_id': revision.id,
        'diff_preview': preview_diff(diff),
        'status': revision.status
    }, status=201)


@api_view(['GET'])
@permission_classes([IsQmsReviewer])
def list_revisions(request):
    status_filter = request.query_params.get('status', None)
    revisions = ManualRevision.objects.all().order_by('-submitted_at')

    if status_filter:
        revisions = revisions.filter(status=status_filter)

    data = [{
        'id': r.id,
        'manual_id': r.section.manual.id if r.section and r.section.manual else None,
        'manual': r.section.manual.title if r.section and r.section.manual else 'N/A',
        'department': r.section.manual.department.name if r.section and r.section.manual and r.section.manual.department else 'N/A',
        'section_id': r.section.id if r.section else None,
        'section': r.section.subtitle if r.section else 'N/A',
        'section_content': r.section.content if r.section else '',
        'proposed_content': r.proposed_content,
        'uploaded_file': r.uploaded_file.url if r.uploaded_file else None,
        'merge_section_ids': r.merge_section_ids,
        'merge_type': r.merge_type,
        'submitted_by': r.submitted_by.username if r.submitted_by else 'N/A',
        'submitted_at': r.submitted_at,
        'status': r.status,
        'change_reason': r.change_reason,
        'reviewed_by': r.reviewed_by.username if r.reviewed_by else None,
        'reviewed_at': r.reviewed_at,
        'ai_verdict': r.ai_verdict,
        'ai_issues': r.ai_issues,
        'ai_explanation': r.ai_explanation,
        'ai_trace': r.ai_trace,
        # Where the assessment came from, so a result a reviewer produced
        # under the old workflow is never shown as one the submitter read.
        'ai_source': r.ai_source,
        'ai_explanation_staff': r.ai_explanation_staff,
        'ai_confidence': r.ai_confidence,
        'ai_change_type': r.ai_change_type,
        'ai_hard_fails': r.ai_hard_fails,
        'ai_advisories': r.ai_advisories,
        'ai_assessed_at': r.ai_assessed_at,
        'ai_model_fingerprint': r.ai_model_fingerprint,
        # True when the section has moved since the check, so the advice is
        # about a comparison that no longer holds.
        'ai_section_changed': _section_moved_since(r),
        'diff_preview': preview_diff(r.diff_text),
        'diff_text': r.diff_text,
    } for r in revisions]
    return Response(data)


def _validated_change_reason(request, section):
    """The reason a submitter gave, or a 400 response explaining the problem.

    Returns ``(reason, None)`` when the submission may proceed and
    ``(None, response)`` when it may not. Clause 6.3 is only met if the reason
    says something, so a blank or throwaway string is refused here rather than
    stored and hard-failed later by Layer 1. A vague-but-real reason is
    accepted: the pipeline flags it for the reviewer instead of blocking a
    submission that may be perfectly sound.
    """
    reason = (request.data.get('change_reason') or '').strip()
    tier, message = classify_reason(reason, getattr(section, 'subtitle', '') or '')
    if blocks_submission(tier):
        return None, Response(
            {'error': message, 'field': 'change_reason', 'reason_tier': tier},
            status=400,
        )
    return reason, None


def _merge_sources(target, source_ids):
    """The sections being folded into ``target``, in a stable order."""
    return list(
        ManualSection.objects.filter(
            id__in=list(source_ids or []), manual=target.manual
        ).order_by('id')
    )


def _merged_content(target, sources):
    """Exactly what propose_merge stores, derived the same way in both places
    so the hash of a checked merge matches the hash of a submitted one."""
    merged = target.content or ''
    for source in sources:
        merged = f"{merged}\n\n{source.content}".strip()
    return merged


def _base_texts(section, sources=()):
    """Every server-held text an assessment depends on.

    A merge rests on the target and each source; anything else rests on the
    section alone. Collected here because the hash, the mismatch message and
    the reviewer's "section changed" flag must all ask the same question.
    """
    return [section.content or ''] + [s.content or '' for s in sources]


def _retrieved_section_ids(section, proposed_content):
    """Which sections retrieval pulls in for this check.

    Recorded so the coordinated-change advisory can read stored output
    rather than recomputing anything at display time. The pipeline's trace
    keeps layer1, layer2, layer3, the version and the fingerprint - but
    not what retrieval returned, and `related_texts` hands back raw text
    with the ids already discarded.

    So this asks the index directly, with the same arguments
    `_assess_unsaved` uses. **Nothing under `ml/` changes**: `build_index`
    and `top_k` are read-only and already public, and Layer 2 receives
    exactly what it received before. The cost is one extra index lookup
    per check, against an index that was just built and cached.
    """
    from ml.revision_pipeline.retrieval import build_index, sections_for_manual

    try:
        sections = sections_for_manual(section.manual)
        index = build_index(section.manual.id, sections)
        return [
            s.section_id for s in index.top_k(
                proposed_content or section.content or '',
                exclude_section_id=section.id, k=3,
                exclude_subtitle=section.subtitle or '',
            )
        ]
    except Exception:
        # An advisory is a nicety. Losing it must never cost the check
        # itself, which is the thing the submitter is waiting for.
        logger.exception("could not record retrieval context for %s", section.id)
        return []


def _assess_unsaved(section, proposed_content, change_reason, seed):
    """Run the pipeline over text that has not been saved yet."""
    from ml.revision_pipeline.pipeline import assess_texts
    from ml.revision_pipeline.retrieval import (
        format_context, related_texts, sections_for_manual,
    )

    number, _, title = (section.subtitle or '').partition(' ')
    sections = sections_for_manual(section.manual)
    related = related_texts(
        section.manual.id, section.id, proposed_content or section.content,
        sections, k=3, section_subtitle=section.subtitle or '',
    )
    return assess_texts(
        section.content or '',
        proposed_content or '',
        section_number=number,
        section_title=title.strip(),
        change_reason=change_reason,
        related=related,
        context=format_context(
            section.manual.title,
            [s for s in sections if s.content in related],
        ),
        # Seeded by the content, so this text and the reviewer's copy of it
        # are word-for-word the same, and re-checking identical content
        # produces an identical result rather than a reworded one.
        seed=seed,
    )


def _section_moved_since(revision):
    """Has any text the assessment rested on changed since it was made?

    For a merge that means the sources as well as the target: advice about a
    merge is advice about the combination, and a source edited afterwards
    makes it stale just as surely.
    """
    if not (revision.ai_section_content_hash and revision.section):
        return False
    sources = ()
    if revision.merge_type == 'merge' and revision.merge_section_ids:
        sources = _merge_sources(revision.section, revision.merge_section_ids)
    current = pre_assessment.section_content_hash(
        *_base_texts(revision.section, sources)
    )
    return revision.ai_section_content_hash != current


def _rate_limited(user):
    """A check costs a model run, and the button sits on every staff screen."""
    window = timezone.now() - timedelta(hours=1)
    recent = RevisionPreAssessment.objects.filter(
        submitted_by=user, assessed_at__gte=window
    ).count()
    if recent >= pre_assessment.RATE_LIMIT_PER_HOUR:
        return Response(
            {'error': 'Too many AI checks in the past hour. Please wait a '
                      'few minutes and try again.'},
            status=429,
        )
    return None


def _sweep_pre_assessments():
    """Drop working state left by someone who checked and never submitted.

    Opportunistic, because nothing in this deployment runs a scheduler. The
    `sweep_pre_assessments` management command does the same thing on demand.
    """
    RevisionPreAssessment.objects.filter(
        consumed_by__isnull=True,
        assessed_at__lt=timezone.now() - pre_assessment.RETENTION,
    ).delete()


def _store_snapshot(user, section, content_hash, base_texts, proposed_content,
                    change_reason, result):
    return RevisionPreAssessment.objects.create(
        section=section,
        submitted_by=user,
        content_hash=content_hash,
        section_content_hash=pre_assessment.section_content_hash(*base_texts),
        proposed_content=proposed_content,
        change_reason=change_reason,
        verdict=result.get('verdict') or '',
        confidence=result.get('confidence'),
        change_type=result.get('change_type') or '',
        issues=result.get('issues') or [],
        hard_fails=result.get('hard_fails') or [],
        advisories=result.get('advisories') or [],
        explanation_reviewer=result.get('explanation') or '',
        explanation_staff=result.get('explanation_staff') or '',
        trace=result.get('trace') or {},
        model_fingerprint=(result.get('trace') or {}).get('fingerprint', ''),
        pipeline_version=(result.get('trace') or {}).get('pipeline_version', ''),
    )


def _snapshot_payload(snapshot):
    """What both sides render an assessment from."""
    return {
        'assessment_id': str(snapshot.id),
        'pipeline': 'v2',
        'assessed': bool(snapshot.verdict),
        'verdict': snapshot.verdict,
        'confidence': snapshot.confidence,
        'change_type': snapshot.change_type,
        'hard_fails': snapshot.hard_fails or [],
        'advisories': snapshot.advisories or [],
        'issues': snapshot.issues or [],
        'explanation': snapshot.explanation_staff,
        'assessed_at': snapshot.assessed_at,
        'model_fingerprint': snapshot.model_fingerprint,
        'trace': snapshot.trace or {},
        'advisory_only': True,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pre_assess_text_revision(request, section_id):
    """Assess proposed text before it is submitted.

    The submitter must run this before submitting, and may submit whatever it
    says - the verdict is advice, never a gate. What it returns is stored
    server-side and handed back only as an id, so the reviewer reads the
    assessment this endpoint made rather than anything the client reports.
    """
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if access.by_position():
        return _superseded_by_proposals('Checking one section on its own')

    if not access.can_propose_to_section(request.user, section):
        return Response({'error': 'Access denied'}, status=403)

    # An uploaded revision is assessed on the text the extractor pulls out of
    # the file, which is not always what the submitter believes is in it. The
    # extracted text goes back with the result so they can see what the system
    # actually read before they commit to it - assessing text nobody has seen
    # would be worse than not assessing at all.
    extracted_text = None
    uploaded = request.FILES.get('file')
    if uploaded is not None:
        try:
            extracted_text = extract_text(uploaded.read(), uploaded.name)
        except Exception as error:
            return Response(
                {'error': f'Could not read that file: {error}'}, status=400
            )
        uploaded.seek(0)
        proposed_content = extracted_text
    else:
        proposed_content = request.data.get('proposed_content')

    if not proposed_content or not str(proposed_content).strip():
        return Response(
            {'error': 'No readable content to check. Upload a file or enter '
                      'the revised text.'},
            status=400,
        )

    # The same clause 6.3 tier-1 check the submission endpoint applies, run
    # here so the submitter is told about a throwaway reason now rather than
    # after reading a verdict.
    change_reason, error = _validated_change_reason(request, section)
    if error:
        return error

    limited = _rate_limited(request.user)
    if limited:
        return limited
    _sweep_pre_assessments()

    content_hash = pre_assessment.content_hash(
        section.id, section.content or '', proposed_content, change_reason
    )

    try:
        result = _assess_unsaved(section, proposed_content, change_reason,
                                 seed=content_hash)
    except Exception as error:
        return Response({'error': f'AI check failed: {error}'}, status=500)

    snapshot = _store_snapshot(
        request.user, section, content_hash, _base_texts(section),
        proposed_content, change_reason, result,
    )
    payload = _snapshot_payload(snapshot)
    if extracted_text is not None:
        payload['extracted_text'] = extracted_text
    return Response(payload, status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pre_assess_merge(request):
    """Assess a proposed merge before it is submitted.

    The merged text is derived on the server, exactly as propose_merge will
    derive it, so what is checked is what would be stored. It goes back with
    the result for the same reason an upload's extracted text does: the
    submitter is agreeing to content they did not type.
    """
    try:
        source = ManualSection.objects.get(id=request.data.get('source_section_id'))
        target = ManualSection.objects.get(id=request.data.get('target_section_id'))
    except (ManualSection.DoesNotExist, ValueError, TypeError):
        return Response({'error': 'Section not found'}, status=404)

    if access.by_position():
        return _merging_is_deleting()

    if not access.can_propose_to_section(request.user, target):
        return Response({'error': 'Access denied'}, status=403)
    if source.id == target.id:
        return Response(
            {'error': 'Source and target must be different sections.'},
            status=400,
        )

    change_reason, error = _validated_change_reason(request, target)
    if error:
        return error

    limited = _rate_limited(request.user)
    if limited:
        return limited
    _sweep_pre_assessments()

    sources = _merge_sources(target, [source.id])
    merged = _merged_content(target, sources)
    base_texts = _base_texts(target, sources)
    content_hash = pre_assessment.content_hash(
        target.id, target.content or '', merged, change_reason
    )

    try:
        result = _assess_unsaved(target, merged, change_reason, seed=content_hash)
    except Exception as error:
        return Response({'error': f'AI check failed: {error}'}, status=500)

    snapshot = _store_snapshot(
        request.user, target, content_hash, base_texts, merged, change_reason,
        result,
    )
    payload = _snapshot_payload(snapshot)
    payload['merged_content'] = merged
    return Response(payload, status=200)


def _consume_pre_assessment(request, section, proposed_content, change_reason,
                            sources=()):
    """The snapshot for exactly this content, or a 400 explaining which way
    it failed to match.

    Returns ``(snapshot, None)`` or ``(None, response)``. Enforced here and
    not only in the browser: a check the client can skip is not a check.
    """
    assessment_id = (request.data.get('assessment_id') or '').strip()
    if not assessment_id:
        return None, Response(
            {'error': pre_assessment.NEVER_CHECKED, 'field': 'assessment_id',
             'reason': 'missing'},
            status=400,
        )
    try:
        snapshot = RevisionPreAssessment.objects.get(
            id=assessment_id, submitted_by=request.user, section=section,
            consumed_by__isnull=True,
        )
    except (RevisionPreAssessment.DoesNotExist, ValidationError, ValueError):
        return None, Response(
            {'error': pre_assessment.NEVER_CHECKED, 'field': 'assessment_id',
             'reason': 'unknown'},
            status=400,
        )

    expected = pre_assessment.content_hash(
        section.id, section.content or '', proposed_content, change_reason
    )
    if expected != snapshot.content_hash:
        return None, Response(
            {'error': pre_assessment.mismatch_reason(
                snapshot, *_base_texts(section, sources)),
             'field': 'assessment_id', 'reason': 'stale'},
            status=400,
        )
    return snapshot, None


def _attach_pre_assessment(revision, snapshot):
    """Copy the snapshot onto the revision the reviewer will open."""
    revision.ai_source = 'staff_precheck'
    revision.ai_verdict = snapshot.verdict
    revision.ai_confidence = snapshot.confidence
    revision.ai_change_type = snapshot.change_type
    revision.ai_issues = snapshot.issues
    revision.ai_hard_fails = snapshot.hard_fails
    revision.ai_advisories = snapshot.advisories
    revision.ai_explanation = snapshot.explanation_reviewer
    revision.ai_explanation_staff = snapshot.explanation_staff
    revision.ai_trace = snapshot.trace
    revision.ai_assessed_at = snapshot.assessed_at
    revision.ai_model_fingerprint = snapshot.model_fingerprint
    revision.ai_content_hash = snapshot.content_hash
    revision.ai_section_content_hash = snapshot.section_content_hash
    revision.save()
    snapshot.consumed_by = revision
    snapshot.save(update_fields=['consumed_by'])


@api_view(['PATCH'])
@permission_classes([IsQmsReviewer])
def review_revision(request, revision_id):
    try:
        revision = ManualRevision.objects.get(id=revision_id)
    except ManualRevision.DoesNotExist:
        return Response({'error': 'Revision not found'}, status=404)

    new_status = request.data.get('status')
    if new_status not in ['approved', 'rejected']:
        return Response({'error': 'Status must be approved or rejected'}, status=400)

    revision.status = new_status
    revision.reviewer_notes = request.data.get('reviewer_notes', '')
    revision.reviewed_at = timezone.now()
    # Who made the call, not just when - an approval with no named approver is
    # not an audit trail.
    revision.reviewed_by = request.user
    revision.save()

    if new_status == 'approved':
        section = revision.section

        # The reason is the submitter's own, copied rather than referenced:
        # a revision can be deleted later and the document's history has to
        # survive that. The link is kept too, for as long as it resolves.
        SectionHistory.objects.create(
            section=section,
            version=section.version,
            subtitle=section.subtitle,
            content=section.content,
            tag=section.tag,
            edited_by=revision.submitted_by,
            source='revision',
            change_reason=revision.change_reason or '',
            revision=revision,
        )

        if revision.merge_type == 'merge' and revision.merge_section_ids:
            # Merge source section(s) content into target section and remove source sections
            source_sections = ManualSection.objects.filter(id__in=revision.merge_section_ids, manual=section.manual)
            merged_content = section.content
            for source_section in source_sections:
                merged_content = f"{merged_content}\n\n{source_section.content}".strip()

            section.content = merged_content
            try:
                section.tag = predict_section(merged_content)
            except Exception:
                section.tag = 'UNTAGGED'
            section.version += 1
            section.save()

            # delete source sections
            source_sections.delete()

        else:
            if revision.uploaded_file:
                try:
                    with revision.uploaded_file.open('rb') as f:
                        file_bytes = f.read()
                    new_text = extract_text(file_bytes, revision.uploaded_file.name)
                except Exception:
                    new_text = revision.proposed_content or section.content
            else:
                new_text = revision.proposed_content or section.content

            section.content = new_text
            try:
                section.tag = predict_section(new_text)
            except Exception:
                section.tag = 'UNTAGGED'
            section.version += 1
            section.save()

        manual = section.manual
        manual.revision += 1
        manual.save()

    return Response({'message': f'Revision {new_status}.', 'status': revision.status})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def ai_assessment_view(request, revision_id):
    """Assess one revision and keep the result on it.

    A fallback, not the normal path. Assessment happens before submission now,
    and the reviewer reads what the submitter read - running it again here
    would produce a second verdict for the same revision, which is exactly
    what moving the check was meant to stop.

    It stays for revisions that predate the change and carry no assessment at
    all, so a reviewer is not left with nothing. Anything already assessed,
    by a submitter or by a reviewer under the old workflow, is refused.

    Which pipeline runs is settings.REVISION_AI_PIPELINE. Either way the answer
    is advice: the admin's decision is what counts, and nothing here changes a
    revision's status.
    """
    try:
        revision = ManualRevision.objects.select_related('section').get(
            id=revision_id
        )
    except ManualRevision.DoesNotExist:
        return Response({'detail': 'Revision not found.'}, status=404)

    if revision.ai_source != 'none':
        return Response(
            {'detail': 'This revision already carries an assessment. '
                       'Re-assessing would replace what the submitter read.',
             'ai_source': revision.ai_source},
            status=409,
        )

    change_type = request.query_params.get('change_type', 'Text Revision')
    original_text = revision.section.content

    if revision.proposed_content:
        revised_text = revision.proposed_content
    elif revision.uploaded_file:
        try:
            with revision.uploaded_file.open('rb') as uploaded_file:
                revised_text = extract_text(
                    uploaded_file.read(),
                    revision.uploaded_file.name,
                )
        except Exception as error:
            return Response(
                {'detail': f'Unable to extract revision text: {error}'},
                status=400,
            )
    elif revision.merge_type == 'merge' and revision.merge_section_ids:
        source_sections = ManualSection.objects.filter(
            id__in=revision.merge_section_ids,
            manual=revision.section.manual,
        )
        revised_text = revision.section.content
        for source_section in source_sections:
            revised_text = f'{revised_text}\n\n{source_section.content}'.strip()
    else:
        return Response(
            {'detail': 'Revision does not contain content to assess.'},
            status=400,
        )

    pipeline_version = getattr(settings, 'REVISION_AI_PIPELINE', 'v2')

    if pipeline_version == 'v2':
        try:
            from ml.revision_pipeline.pipeline import assess_revision as assess_v2

            result = assess_v2(revision)
        except Exception as error:
            return Response(
                {'detail': f'AI assessment failed: {error}'},
                status=500,
            )

        # Kept on the revision so the review screen can show it again without
        # re-running the model, and so a decision can be looked at afterwards
        # beside the advice that was on screen at the time.
        revision.ai_verdict = result.get('verdict') or ''
        revision.ai_issues = result.get('issues') or []
        revision.ai_explanation = result.get('explanation') or ''
        revision.ai_trace = result.get('trace') or {}
        revision.save(update_fields=[
            'ai_verdict', 'ai_issues', 'ai_explanation', 'ai_trace',
        ])

        return Response({
            'pipeline': 'v2',
            'assessed': result.get('assessed', True),
            'verdict': result.get('verdict'),
            'confidence': result.get('confidence'),
            'change_type': result.get('change_type'),
            'hard_fails': result.get('hard_fails') or [],
            'advisories': result.get('advisories') or [],
            'explanation': result.get('explanation'),
            'issues': result.get('issues') or [],
            'trace': result.get('trace') or {},
            # The admin decides. This is advice.
            'advisory': True,
        })

    try:
        from ml.distilbert_model import assess_revision

        assessment = assess_revision(
            change_type,
            original_text,
            revised_text,
        )
    except Exception as error:
        return Response(
            {'detail': f'AI assessment failed: {error}'},
            status=500,
        )

    return Response({'pipeline': 'v1', 'advisory': True,
                     'ai_assessment': assessment})


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