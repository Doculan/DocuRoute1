from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from .models import CustomUser, Department, Manual, ManualSection, ManualRevision, SectionHistory
from ml.ocr_engine import extract_text
from ml.svm_model import predict, predict_section
import difflib
import re


# ─── HELPERS ─────────────────────────────────────────────────

def _split_into_sections(text, fallback_title='Full Document'):
    # FIX #1: INLINE_TAGS are NO LONGER stripped from lines.
    # Semantic keywords (POLICY, PROCEDURE, RESPONSIBILITY, WORKING INSTRUCTION)
    # must be preserved so the SVM classifier can detect them.

    def is_top_level_number(num_tuple):
        # FIX #2: also treat bare single-digit sections ("1", "2") as top-level
        # Previously only "1.0", "2.0" matched; "1" or "2" were silently dropped.
        return len(num_tuple) == 1 or (len(num_tuple) == 2 and num_tuple[1] == 0)

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
        if current_subtitle and current_content:
            content = '\n'.join(l for l in current_content if l.strip()).strip()
            if content:
                sections.append({
                    'subtitle': current_subtitle,
                    'content': content,
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

        # Drop artifact lines
        if re.match(r'^[\s:|\-\.]+$', s):
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


# ─── AUTH ────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email', '')
    department_id = request.data.get('department_id', None)

    if CustomUser.objects.filter(username=username).exists():
        return Response({'error': 'Username already taken'}, status=400)

    user = CustomUser.objects.create_user(
        username=username,
        password=password,
        email=email,
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
        'username': user.username,
        'department': user.department.name if user.department else None,
        'department_id': user.department.id if user.department else None,
    })


# ─── ADMIN: USERS ────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def pending_users(request):
    users = CustomUser.objects.filter(is_approved=False)
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'department': u.department.name if u.department else 'N/A'} for u in users]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def approved_users(request):
    users = CustomUser.objects.filter(is_approved=True)
    data = [{'id': u.id, 'username': u.username, 'email': u.email,
             'role': u.role,
             'department': u.department.name if u.department else 'N/A'} for u in users]
    return Response(data)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def approve_user(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)
    user.is_approved = True
    user.save()
    return Response({'message': f'{user.username} has been approved.'})


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def reject_user(request, user_id):
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
@permission_classes([IsAdminUser])
def create_department(request):
    name = request.data.get('name')
    if not name:
        return Response({'error': 'Department name is required'}, status=400)
    if Department.objects.filter(name=name).exists():
        return Response({'error': 'Department already exists'}, status=400)
    dept = Department.objects.create(name=name)
    return Response({'id': dept.id, 'name': dept.name}, status=201)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_department(request, dept_id):
    try:
        dept = Department.objects.get(id=dept_id)
    except Department.DoesNotExist:
        return Response({'error': 'Department not found'}, status=404)
    dept.delete()
    return Response({'message': f'{dept.name} deleted.'})


# ─── STAFF ENDPOINTS ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_list_manuals(request):
    """Return manuals belonging to the logged-in staff member's department."""
    dept = getattr(request.user, 'department', None)
    if not dept:
        return Response({'error': 'You are not assigned to a department.'}, status=403)
    manuals = Manual.objects.filter(department=dept).order_by('-uploaded_at')
    data = [{
        'id': m.id,
        'title': m.title,
        'department': m.department.name if m.department else 'N/A',
        'uploaded_by': m.uploaded_by.username if m.uploaded_by else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': m.sections.count(),
        'version': m.version,
    } for m in manuals]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_my_revisions(request):
    """Return all revisions submitted by the currently logged-in user."""
    revisions = ManualRevision.objects.filter(
        submitted_by=request.user
    ).order_by('-submitted_at')
    data = [{
        'id': r.id,
        'section_id': r.section.id if r.section else None,
        'section': r.section.subtitle if r.section else 'N/A',
        'manual': r.section.manual.title if r.section else 'N/A',
        'submitted_at': r.submitted_at,
        'status': r.status,
        'reviewer_notes': r.reviewer_notes,
        'reviewed_at': r.reviewed_at,
        'diff_preview': r.diff_text[:400] if r.diff_text else '',
    } for r in revisions]
    return Response(data)


# ─── MANUALS ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def list_manuals(request):
    manuals = Manual.objects.all().order_by('-uploaded_at')
    data = [{
        'id': m.id,
        'title': m.title,
        'department': m.department.name if m.department else 'N/A',
        'uploaded_by': m.uploaded_by.username if m.uploaded_by else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': m.sections.count(),
        'version': m.version,
    } for m in manuals]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAdminUser])
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
@permission_classes([IsAdminUser])
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
        for idx, block in enumerate(blocks):
            try:
                tag = predict_section(block['content']) if block['content'].strip() else 'UNTAGGED'
            except Exception:
                tag = 'UNTAGGED'

            preview.append({
                'preview_index': idx,
                'subtitle': block['subtitle'],
                'content': block['content'],
                'tag': tag,
                'page_number': block.get('page_number'),
                'is_chapter': block.get('is_chapter', False),
                'parent_index': block.get('parent_index'),
            })

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
@permission_classes([IsAdminUser])
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

    manual.version += 1
    manual.save()

    return Response({
        'manual_id': manual.id,
        'sections_created': len(created_sections),
    }, status=201)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_manual(request, manual_id):
    try:
        manual = Manual.objects.get(id=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Manual not found'}, status=404)
    manual.delete()
    return Response({'message': 'Manual deleted.'})


@api_view(['POST'])
@permission_classes([IsAdminUser])
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

    if not request.user.is_staff:
        if manual.department != request.user.department:
            return Response({'error': 'Access denied'}, status=403)

    pending = request.query_params.get('pending')
    sections_qs = manual.sections.all().order_by('order')
    if pending and pending.lower() in ('1', 'true', 'yes'):
        sections_qs = sections_qs.filter(is_reviewed=False)

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

    # Only allow access by staff in the same department (or admins)
    if not request.user.is_staff and section.manual.department != request.user.department:
        return Response({'error': 'Access denied'}, status=403)

    # Update content/metadata if provided
    section.subtitle = request.data.get('subtitle', section.subtitle)
    section.content = request.data.get('content', section.content)
    section.tag = request.data.get('tag', section.tag)
    section.page_number = request.data.get('page_number', section.page_number)
    section.order = request.data.get('order', section.order)

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
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
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

    section = ManualSection.objects.create(
        manual=manual,
        subtitle=subtitle,
        content=content,
        tag=tag,
        page_number=page_number,
        order=order
    )

    return Response({
        'id': section.id,
        'subtitle': section.subtitle,
        'tag': section.tag,
        'page_number': section.page_number,
        'order': section.order
    }, status=201)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_section(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    SectionHistory.objects.create(
        section=section,
        version=section.version,
        subtitle=section.subtitle,
        content=section.content,
        tag=section.tag,
        edited_by=request.user,
    )

    section.subtitle = request.data.get('subtitle', section.subtitle)
    section.content = request.data.get('content', section.content)
    section.page_number = request.data.get('page_number', section.page_number)
    section.order = request.data.get('order', section.order)
    section.version += 1

    if 'content' in request.data:
        try:
            section.tag = predict_section(section.content)
        except Exception:
            section.tag = 'UNTAGGED'

    section.save()

    manual = section.manual
    manual.version += 1
    manual.save()

    return Response({
        'message': 'Section updated.',
        'tag': section.tag,
        'version': section.version,
        'manual_version': manual.version,
    })


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_section(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)
    section.delete()
    return Response({'message': 'Section deleted.'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def review_delete_section(request, section_id):
    """Delete a section during review (staff can delete within their department)."""
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    if not request.user.is_staff and section.manual.department != request.user.department:
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

    if not request.user.is_staff and source.manual.department != request.user.department:
        return Response({'error': 'Access denied'}, status=403)

    # Save history for target
    SectionHistory.objects.create(
        section=target,
        version=target.version,
        subtitle=target.subtitle,
        content=target.content,
        tag=target.tag,
        edited_by=request.user,
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
@permission_classes([IsAdminUser])
def section_history(request, section_id):
    try:
        section = ManualSection.objects.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)

    history = section.history.all().order_by('version')
    data = [{
        'version': h.version,
        'subtitle': h.subtitle,
        'content': h.content,
        'tag': h.tag,
        'edited_by': h.edited_by.username if h.edited_by else 'N/A',
        'edited_at': h.edited_at,
    } for h in history]

    data.append({
        'version': section.version,
        'subtitle': section.subtitle,
        'content': section.content,
        'tag': section.tag,
        'edited_by': 'Current',
        'edited_at': None,
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

    if section.manual.department != request.user.department:
        return Response({'error': 'Access denied'}, status=403)

    if 'file' not in request.FILES:
        return Response({'error': 'No file uploaded'}, status=400)

    uploaded_file = request.FILES['file']
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    text_new = extract_text(file_bytes, uploaded_file.name)

    diff = "\n".join(difflib.unified_diff(
        section.content.splitlines(),
        text_new.splitlines(),
        lineterm=""
    ))

    revision = ManualRevision.objects.create(
        section=section,
        submitted_by=request.user,
        uploaded_file=uploaded_file,
        diff_text=diff,
        status='pending'
    )

    return Response({
        'revision_id': revision.id,
        'diff_preview': diff[:500],
        'status': revision.status
    }, status=201)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def list_revisions(request):
    status_filter = request.query_params.get('status', None)
    revisions = ManualRevision.objects.all().order_by('-submitted_at')

    if status_filter:
        revisions = revisions.filter(status=status_filter)

    data = [{
        'id': r.id,
        'section': r.section.subtitle if r.section else 'N/A',
        'manual': r.section.manual.title if r.section else 'N/A',
        'department': r.section.manual.department.name if r.section and r.section.manual.department else 'N/A',
        'submitted_by': r.submitted_by.username if r.submitted_by else 'N/A',
        'submitted_at': r.submitted_at,
        'status': r.status,
        'diff_preview': r.diff_text[:300]
    } for r in revisions]
    return Response(data)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
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
    revision.save()

    if new_status == 'approved':
        try:
            with revision.uploaded_file.open('rb') as f:
                file_bytes = f.read()
            new_text = extract_text(file_bytes, revision.uploaded_file.name)
            section = revision.section

            SectionHistory.objects.create(
                section=section,
                version=section.version,
                subtitle=section.subtitle,
                content=section.content,
                tag=section.tag,
                edited_by=revision.submitted_by,
            )

            section.content = new_text
            try:
                section.tag = predict_section(new_text)
            except Exception:
                section.tag = 'UNTAGGED'
            section.version += 1
            section.save()

            manual = section.manual
            manual.version += 1
            manual.save()

        except Exception:
            pass

    return Response({'message': f'Revision {new_status}.', 'status': revision.status})