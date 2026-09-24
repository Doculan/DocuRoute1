from django.urls import path
from . import organisation_views as org
from . import series_views as series
from . import people_views as people
from . import proposal_views as proposals
from . import concurrence_views as concurrence
from . import package_views as package
from . import qms_views as qms
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    register,
    login,
    confirm_password,
    pending_users,
    approved_users,
    approve_user,
    reject_user,
    staff_list_manuals,
    staff_sections,
    staff_dashboard,
    staff_dismiss_announcement,
    admin_announcements,
    admin_announcement_detail,
    admin_dashboard,
    list_manuals,
    upload_manual,
    preview_manual_sections,
    confirm_manual_sections,
    delete_manual,
    ocr_extract_manual,
    list_sections,
    create_section,
    update_section,
    delete_section,
    section_history,
    evaluate_svm_model,
)

urlpatterns = [
    # ─── Organisation (v4, system admin only) ────────────────
    # Offices are never deleted, so there is no delete route here and
    # there will not be one: deactivate, or merge into the office that
    # took the work over.
    path('org/offices/', org.offices),
    path('org/offices/<int:office_id>/', org.office_detail),
    path('org/offices/<int:office_id>/deactivate/', org.deactivate_office),
    path('org/offices/<int:office_id>/reactivate/', org.reactivate_office),
    path('org/offices/<int:office_id>/merge/', org.merge_office),

    # Office links are set as a whole set, with PUT: the relationship
    # being edited *is* a set, and an add/remove pair would let a screen
    # sit half-way through a change with a set nobody chose.
    path('org/series/', series.series_list),
    path('org/series/<int:series_id>/', series.series_detail),
    path('org/series/<int:series_id>/offices/', series.series_offices),
    path('org/documents/', series.documents_list),
    path('org/documents/<int:document_id>/', series.document_detail),
    path('org/documents/<int:document_id>/offices/', series.document_offices),

    # People are deactivated, never deleted; assignments are ended with a
    # date, never removed.
    path('org/people/', people.people),
    path('org/people/<int:person_id>/approve/', people.approve_person),
    path('org/people/<int:person_id>/deactivate/', people.deactivate_person),
    path('org/people/<int:person_id>/reactivate/', people.reactivate_person),
    path('org/people/<int:person_id>/assign/', people.assign_position),
    path('org/assignments/<int:assignment_id>/end/', people.end_assignment),
    path('org/positions/', people.positions_by_office),

    # Proposals: a whole document, each changed section checked.
    path('proposals/', proposals.proposals),
    path('proposals/<int:proposal_id>/', proposals.proposal_detail),
    path('proposals/<int:proposal_id>/sections/<int:section_id>/',
         proposals.proposal_section),
    path('proposals/<int:proposal_id>/sections/<int:section_id>/check/',
         proposals.check_section),

    # Submission through to agreement. Participants freeze at submission;
    # any return makes a new version and resets every concurrence.
    path('proposals/<int:proposal_id>/full/', concurrence.proposal_full),
    path('proposals/<int:proposal_id>/submit/', concurrence.submit),
    path('proposals/<int:proposal_id>/decide/', concurrence.decide),
    path('proposals/<int:proposal_id>/withdraw/', concurrence.withdraw),
    path('proposals/awaiting/', concurrence.awaiting_my_office),
    path('proposals/involving/', concurrence.involving_my_office),
    path('proposals/<int:proposal_id>/package/', package.package),
    path('proposals/<int:proposal_id>/imr/', qms.imr_decide),
    path('proposals/<int:proposal_id>/custodian/return/', qms.custodian_return),
    path('proposals/<int:proposal_id>/custodian/effective/', qms.make_effective),
    path('manuals/<int:manual_id>/status/baseline/', qms.record_baseline),
    path('manuals/<int:manual_id>/status/baseline/correct/', qms.correct_baseline),
    path('qms/queue/', qms.queue),
    path('auth/me/', qms.me),
    path('proposals/<int:proposal_id>/scans/', package.upload_scan),
    path('proposals/<int:proposal_id>/scans/<int:attachment_id>/replace/',
         package.replace_scan),
    path('proposals/<int:proposal_id>/attachments/<int:attachment_id>/download/',
         package.download),

    # Auth
    path('auth/register/', register),
    path('auth/confirm-password/', confirm_password),
    path('auth/login/', login),
    # Exchanges the refresh token for a new access token, so a session does not
    # die after ACCESS_TOKEN_LIFETIME while the user is still working.
    path('auth/refresh/', TokenRefreshView.as_view()),

    # Admin - Users
    path('admin/pending-users/', pending_users),
    path('admin/approved-users/', approved_users),
    path('admin/approve-user/<int:user_id>/', approve_user),
    path('admin/reject-user/<int:user_id>/', reject_user),

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
    path('sections/<int:section_id>/update/', update_section),
    path('sections/<int:section_id>/delete/', delete_section),
    path('sections/<int:section_id>/history/', section_history),  # ✅ NEW

    # Staff endpoints
    path('staff/manuals/', staff_list_manuals),
    # One request for the whole landing page - six widgets reading the
    # same few tables do not need six round trips.
    path('staff/dashboard/', staff_dashboard),
    path('staff/announcements/<int:announcement_id>/dismiss/', staff_dismiss_announcement),
    # Sections across every manual the staff member can reach - the
    # route for someone who knows the content, not the document.
    path('staff/sections/', staff_sections),

    # Admin dashboard and announcements. The staff banner and Upcoming
    # list read these rows; this is the half that puts something in them.
    path('admin/dashboard/', admin_dashboard),
    path('admin/announcements/', admin_announcements),
    path('admin/announcements/<int:announcement_id>/', admin_announcement_detail),

    # SVM Evaluation
    path('evaluate/svm/', evaluate_svm_model),
]
