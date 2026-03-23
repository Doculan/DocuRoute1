from django.urls import path
from .views import (
    register, login,
    pending_users, approved_users, approve_user, reject_user,
    list_departments, create_department, delete_department,
    staff_list_manuals, staff_my_revisions,
    list_manuals, upload_manual, preview_manual_sections, confirm_manual_sections, delete_manual, ocr_extract_manual,
    list_sections, create_section, update_section, delete_section, review_section, merge_sections, review_delete_section,
    section_history,
    upload_revision, list_revisions, review_revision,
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
    path('manuals/upload-preview/', preview_manual_sections),
    path('manuals/<int:manual_id>/confirm-sections/', confirm_manual_sections),
    path('manuals/<int:manual_id>/delete/', delete_manual),
    path('manuals/<int:manual_id>/ocr-extract/', ocr_extract_manual),

    # Sections
    path('manuals/<int:manual_id>/sections/', list_sections),
    path('manuals/<int:manual_id>/sections/create/', create_section),
    path('sections/<int:section_id>/review/', review_section),
    path('sections/<int:section_id>/merge/', merge_sections),
    path('sections/<int:section_id>/update/', update_section),
    path('sections/<int:section_id>/delete/', delete_section),
    path('sections/<int:section_id>/review-delete/', review_delete_section),
    path('sections/<int:section_id>/history/', section_history),  # ✅ NEW

    # Staff endpoints
    path('staff/manuals/', staff_list_manuals),
    path('staff/revisions/', staff_my_revisions),

    # Revisions
    path('revisions/upload/<int:section_id>/', upload_revision),
    path('admin/revisions/', list_revisions),
    path('admin/revisions/<int:revision_id>/review/', review_revision),
]
