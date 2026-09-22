"""TRANSITIONAL — DELETE THIS FILE AT PHASE 1c.

Spec section 5 moves the review screen from the admin to QMS staff. Taken
literally at 1a that would strand every pending revision: QMS staff means
holding a current IMR or Document Custodian position, positions belong to
offices, offices are entered by hand in 1b, and the organisation ships
empty. Nobody would be able to review anything, and the one account that
could fix it is the system admin — who by standing rule 7 should not also
be deciding requests.

So the system admin keeps review rights until QMS positions can exist.

**This file is the reminder.** It imports `TRANSITIONAL_ADMIN_REVIEW` at
module level, so removing that flag at 1c makes the whole module fail to
import rather than quietly pass — the allowance cannot be deleted from the
code while a green suite still claims it is there, and it cannot survive
into v4 proper unnoticed either. When 1c arrives: delete the flag, delete
this file, and check that `tests_qms_review.py` still passes.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualRevision, ManualSection, Office,
    Position, PositionAssignment,
)

# The import that makes removal loud. Do not soften this to a getattr.
from api.views import TRANSITIONAL_ADMIN_REVIEW


class TransitionalAdminReviewTests(TestCase):

    def setUp(self):
        self.department = Department.objects.create(name="FAM")
        self.admin = CustomUser.objects.create_user(
            username="t-admin", password="pw", role="admin",
            system_role="system_admin", is_approved=True,
        )
        self.staff = CustomUser.objects.create_user(
            username="t-staff", password="pw", role="staff",
            system_role="user", is_approved=True, department=self.department,
        )
        self.manual = Manual.objects.create(
            title="FAM 6.02", department=self.department, uploaded_by=self.admin,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", content="Text.",
            tag="POLICY",
        )
        ManualRevision.objects.create(
            section=self.section, submitted_by=self.staff,
            proposed_content="Changed text.", status="pending",
            change_reason="Management review.",
        )

    def as_admin(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client

    def test_the_allowance_is_still_switched_on(self):
        """If this fails, 1c has happened and this file should be gone."""
        self.assertTrue(
            TRANSITIONAL_ADMIN_REVIEW,
            "The transitional admin review allowance was switched off. "
            "Delete this file and confirm QMS staff can still review.",
        )

    def test_the_system_admin_can_still_review_with_no_qms_position(self):
        """The whole reason the allowance exists: at 1a there are no
        offices, so there can be no QMS staff, so without this nobody
        could act on a pending revision at all."""
        self.assertEqual(Office.objects.count(), 0)
        response = self.as_admin().get("/api/admin/revisions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_an_ordinary_user_still_cannot_review(self):
        """The allowance widens the door for one role, not for everyone."""
        client = APIClient()
        client.force_authenticate(user=self.staff)
        self.assertEqual(client.get("/api/admin/revisions/").status_code, 403)


class QmsPositionReviewTests(TestCase):
    """The part that is *not* transitional: a current QMS position grants
    review rights on its own. These assertions survive 1c."""

    def setUp(self):
        # `timezone.localdate()`, not `date.today()`. The application
        # works in the project's timezone and the machine may be a day
        # ahead of it - which made every assignment here start
        # tomorrow, and every test that needed one fail.
        self.today = timezone.localdate()
        self.qms_office = Office.objects.create(name="Quality Management")
        self.imr = Position.objects.create(
            office=self.qms_office, kind=Position.IMR,
        )
        self.custodian = Position.objects.create(
            office=self.qms_office, kind=Position.DOCUMENT_CUSTODIAN,
        )
        self.person = CustomUser.objects.create_user(
            username="qms-person", password="pw", role="staff",
            system_role="qms_staff", is_approved=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.person)

    def assign(self, position, starts_on=None, ends_on=None):
        return PositionAssignment.objects.create(
            user=self.person, position=position,
            starts_on=starts_on or self.today, ends_on=ends_on,
        )

    def test_a_current_imr_may_review(self):
        self.assign(self.imr)
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 200)

    def test_a_current_custodian_may_review(self):
        self.assign(self.custodian)
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 200)

    def test_holding_no_position_is_not_enough(self):
        """`system_role` routes someone to the QMS area; the position is
        what authorises them once they are there. Someone marked QMS staff
        who holds nothing can act on nothing."""
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 403)

    def test_an_ended_assignment_does_not_still_authorise(self):
        """The reason assignments are dated at all. Someone who left the
        post last month must not still be deciding requests."""
        self.assign(
            self.imr,
            starts_on=self.today - datetime.timedelta(days=60),
            ends_on=self.today - datetime.timedelta(days=30),
        )
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 403)

    def test_an_assignment_that_has_not_started_does_not_authorise_yet(self):
        self.assign(self.imr, starts_on=self.today + datetime.timedelta(days=7))
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 403)

    def test_an_assignment_ending_today_still_authorises_today(self):
        """Its last day is a day they held it, not the day after."""
        self.assign(self.imr, ends_on=self.today)
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 200)

    def test_a_deactivated_position_stops_authorising(self):
        self.assign(self.imr)
        self.imr.is_active = False
        self.imr.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 403)

    def test_an_office_position_is_not_a_qms_position(self):
        """Encoder and Head run an office's side of a request. Deciding it
        is the QMS office's job, and the two must not be confused."""
        head = Position.objects.create(office=self.qms_office, kind=Position.HEAD)
        self.assign(head)
        self.assertEqual(self.client.get("/api/admin/revisions/").status_code, 403)
