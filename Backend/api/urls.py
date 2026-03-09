from django.urls import path
from . import views
from .views import (
    register, login,
    pending_users, approved_users, approve_user, reject_user,
    list_departments, create_department, delete_department,
    list_manuals, upload_manual, delete_manual, ocr_extract_manual,
    list_sections, create_section, update_section, delete_section,
    upload_revision, list_revisions, review_revision,
    section_history,
)

urlpatterns = [
    # Auth
    path('auth/register/', register),
    path('auth/login/', login),

    # Admin - Users
    path('admin/pending-users/', pending_users),
    path('admin/approved-users/', approved_users),
    path('admin/approve-user/<int:user_id>/', approve_user),
    path('admin/reject-user/<int:user_id>/', reject_user),

    # Departments
    path('departments/', list_departments),
    path('departments/create/', create_department),
    path('departments/<int:dept_id>/delete/', delete_department),

    # Manuals
    path('manuals/', list_manuals),
    path('manuals/upload/', upload_manual),
    path('manuals/<int:manual_id>/delete/', delete_manual),
    path('manuals/<int:manual_id>/ocr-extract/', ocr_extract_manual),

    # Sections
    path('manuals/<int:manual_id>/sections/', list_sections),
    path('manuals/<int:manual_id>/sections/create/', create_section),
    path('sections/<int:section_id>/update/', update_section),
    path('sections/<int:section_id>/delete/', delete_section),
    path('sections/<int:section_id>/history/', section_history),

    # Revisions
    path('revisions/upload/<int:section_id>/', upload_revision),
    path('admin/revisions/', list_revisions),
    path('admin/revisions/<int:revision_id>/review/', review_revision),
]
