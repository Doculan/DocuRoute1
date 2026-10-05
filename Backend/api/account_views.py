"""A person's own account: their name, email and password.

Only what someone can safely change for themselves. The username is the
login, so it stays; offices and positions are the system admin's to
assign, so they are shown here but not edited.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .generation.common import position_title
from .models import CustomUser

NAME_MAX = CustomUser._meta.get_field('full_name').max_length
EMAIL_MAX = CustomUser._meta.get_field('email').max_length


def _payload(user):
    from .proposal_views import _current_assignments
    return {
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email,
        'system_role': user.system_role,
        'system_role_label': user.get_system_role_display(),
        'positions': [
            {
                'title': position_title(a.position.office.name, a.position.kind),
                'is_acting': a.is_acting,
                'since': a.starts_on,
            }
            for a in _current_assignments(user)
        ],
        'date_joined': user.date_joined,
    }


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile(request):
    user = request.user
    if request.method == 'GET':
        return Response(_payload(user))

    errors = {}
    fields = []

    if 'full_name' in request.data:
        name = ' '.join((request.data.get('full_name') or '').split())
        if not name:
            errors['full_name'] = 'Enter your name.'
        elif len(name) > NAME_MAX:
            errors['full_name'] = f'Keep it under {NAME_MAX} characters.'
        else:
            user.full_name = name
            fields.append('full_name')

    if 'email' in request.data:
        email = (request.data.get('email') or '').strip()
        # Optional, as at sign-up; but if given, it has to be an address.
        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors['email'] = 'That is not a valid email address.'
        if email and len(email) > EMAIL_MAX:
            errors['email'] = f'Keep it under {EMAIL_MAX} characters.'
        if 'email' not in errors:
            user.email = email
            fields.append('email')

    if errors:
        return Response({'error': ' '.join(errors.values()), 'fields': errors},
                        status=400)
    if fields:
        user.save(update_fields=fields)
    return Response(_payload(user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    current = request.data.get('current_password') or ''
    new = request.data.get('new_password') or ''

    if not user.check_password(current):
        # 400, not 401 or 403: a mistyped password here is a form error,
        # and the client must not take it for an expired session.
        return Response({'error': 'Your current password is not correct.',
                         'reason': 'wrong_password'}, status=400)
    if not new:
        return Response({'error': 'Enter a new password.'}, status=400)
    if new == current:
        return Response({'error': 'The new password is the same as the old one.'},
                        status=400)
    try:
        validate_password(new, user)
    except ValidationError as exc:
        return Response({'error': ' '.join(exc.messages),
                         'reason': 'weak_password'}, status=400)

    user.set_password(new)
    user.save(update_fields=['password'])
    return Response({'message': 'Password changed.'})
