from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from .models import CustomUser, Department, Manual, ManualSection, ManualRevision, SectionHistory
from ml.ocr_engine import extract_text
from ml.svm_model import predict
import difflib
import re


# ─── HELPERS ─────────────────────────────────────────────────

def _split_into_sections(text, fallback_title='Full Document'):
    lines = text.split('\n')
    sections = []
    current_subtitle = None
    current_content = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_heading = bool(
            len(stripped) < 80 and (
                re.match(r'^\d+[\.\)]\s+\w+', stripped) or
                re.match(r'^[A-Z][A-Z\s]{2,60}$', stripped) or
                re.match(r'^[A-Z][a-z]+(\s[A-Z][a-z]+){0,6}$', stripped)
            )
        )

        if is_heading:
            if current_subtitle and current_content:
                sections.append({
                    'subtitle': current_subtitle,
                    'content': '\n'.join(current_content).strip()
                })
            current_subtitle = stripped
            current_content = []
        else:
            if current_subtitle is None:
                current_subtitle = 'Introduction'
            current_content.append(stripped)

    if current_subtitle and current_content:
        sections.append({
            'subtitle': current_subtitle,
            'content': '\n'.join(current_content).strip()
        })

    if not sections:
        sections.append({
            'subtitle': fallback_title,
            'content': text.strip()
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
        for idx, block in enumerate(blocks):
            try:
                tag = predict(block['content'])[0] if block['content'].strip() else 'UNTAGGED'
            except Exception:
                tag = 'UNTAGGED'
            section = ManualSection.objects.create(
                manual=manual,
                subtitle=block['subtitle'],
                content=block['content'],
                tag=tag,
                order=idx,
            )
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

    sections = manual.sections.all().order_by('order')
    data = [{
        'id': s.id,
        'subtitle': s.subtitle,
        'tag': s.tag,
        'page_number': s.page_number,
        'order': s.order,
        'content': s.content,
        'content_preview': s.content[:200],
        'version': s.version,
    } for s in sections]

    return Response({
        'manual_version': manual.version,
        'sections': data,
        'file_url': manual.file.url if manual.file else None,  # ✅ relative path only
        'file_name': manual.file.name if manual.file else None,
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
        tag = predict(content)[0] if content else 'UNTAGGED'
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
            section.tag = predict(section.content)[0]
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
                section.tag = predict(new_text)[0]
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
