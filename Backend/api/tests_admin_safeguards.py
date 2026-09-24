"""Confirming a password before something irreversible, and recording why.

Two unrelated-looking changes that answer the same question: after the
fact, can anyone tell what happened and on whose authority?

The re-authentication tests care less about the happy path than about the
ways a guard is quietly useless - a route nothing takes, a token that works
for a different account, an expiry that reports itself as a wrong password.
"""

import time
from datetime import timedelta
from unittest import mock

from django.core.signing import TimestampSigner
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Announcement, CustomUser, Manual, ManualSection,
    SectionHistory,
)
from api.views import REAUTH_SALT, issue_reauth_token

PASSWORD = "correct-horse-battery"


class ReauthenticationTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username="guard-admin", password=PASSWORD, role="admin",
            is_approved=True,
        )
        self.manual = Manual.objects.create(
            title="FAM 6.02", uploaded_by=self.admin,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", content="Text.",
            tag="POLICY",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def token(self):
        response = self.client.post(
            "/api/auth/confirm-password/", {"password": PASSWORD}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        return response.data["token"]

    def delete(self, path, token=None):
        headers = {"HTTP_X_REAUTH_TOKEN": token} if token else {}
        return self.client.delete(path, **headers)

    # -- the exchange ----------------------------------------------

    def test_the_right_password_buys_a_token(self):
        response = self.client.post(
            "/api/auth/confirm-password/", {"password": PASSWORD}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data)

    def test_the_wrong_password_does_not(self):
        response = self.client.post(
            "/api/auth/confirm-password/", {"password": "nope"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("token", response.data)

    def test_a_blank_password_is_a_bad_request_not_a_rejection(self):
        """Submitting an empty box is a mistake, not a failed attempt, and
        telling someone their password is wrong when they typed nothing
        sends them to reset a password that is fine."""
        response = self.client.post(
            "/api/auth/confirm-password/", {"password": ""}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_confirming_issues_nothing_that_can_sign_in(self):
        """The token authorises one kind of action. If it were accepted as
        credentials anywhere, a five-minute confirmation would be a
        five-minute session."""
        token = self.token()
        anonymous = APIClient()
        anonymous.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertIn(
            anonymous.get("/api/admin/dashboard/").status_code, (401, 403)
        )

    # -- the guard -------------------------------------------------

    def test_deleting_without_confirming_is_refused(self):
        response = self.delete(f"/api/manuals/{self.manual.id}/delete/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")
        self.assertTrue(Manual.objects.filter(pk=self.manual.pk).exists())

    def test_deleting_with_a_confirmation_goes_through(self):
        response = self.delete(
            f"/api/manuals/{self.manual.id}/delete/", self.token()
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Manual.objects.filter(pk=self.manual.pk).exists())

    def test_a_forged_token_is_refused(self):
        response = self.delete(
            f"/api/manuals/{self.manual.id}/delete/", "not-a-real-token"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_invalid")
        self.assertTrue(Manual.objects.filter(pk=self.manual.pk).exists())

    def test_another_admin_s_confirmation_does_not_authorise_mine(self):
        """Two admins on one browser is the ordinary case in a shared
        office. A token proves a password was typed; it has to prove
        *whose*."""
        other = CustomUser.objects.create_user(
            username="other-admin", password=PASSWORD, role="admin",
            is_approved=True,
        )
        response = self.delete(
            f"/api/manuals/{self.manual.id}/delete/", issue_reauth_token(other)
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_invalid")
        self.assertTrue(Manual.objects.filter(pk=self.manual.pk).exists())

    def test_an_expired_confirmation_says_so_rather_than_wrong_password(self):
        """An admin who took five minutes over a confirmation must not be
        told their own password is wrong - the next thing they do is try to
        reset it."""
        stale = TimestampSigner(salt=REAUTH_SALT).sign(str(self.admin.pk))
        with mock.patch("api.views.REAUTH_MAX_AGE_SECONDS", 0):
            time.sleep(1.1)
            response = self.delete(
                f"/api/manuals/{self.manual.id}/delete/", stale
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_expired")

    # -- every route that deletes, not just the tidy ones ----------

    def test_the_section_delete_route_is_guarded(self):
        section = ManualSection.objects.create(
            manual=self.manual, subtitle="9.0 delete", content="x", tag="POLICY",
        )
        response = self.delete(f"/api/sections/{section.id}/delete/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ManualSection.objects.filter(pk=section.pk).exists())

    def test_rejecting_a_registration_is_guarded(self):
        applicant = CustomUser.objects.create_user(
            username="applicant", password="pw", role="staff", is_approved=False,
        )
        response = self.delete(f"/api/admin/reject-user/{applicant.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(CustomUser.objects.filter(pk=applicant.pk).exists())

    def test_deleting_an_announcement_is_guarded_but_deactivating_is_not(self):
        """Deactivating is reversible and keeps the record, so it stays a
        single click. The prompt would train people to type the password
        without reading it."""
        announcement = Announcement.objects.create(
            title="Notice", created_by=self.admin,
        )
        self.assertEqual(
            self.delete(f"/api/admin/announcements/{announcement.id}/").status_code,
            403,
        )
        deactivated = self.client.patch(
            f"/api/admin/announcements/{announcement.id}/",
            {"active": False}, format="json",
        )
        self.assertEqual(deactivated.status_code, 200)
        announcement.refresh_from_db()
        self.assertFalse(announcement.active)

    def test_approving_a_user_needs_no_confirmation(self):
        """The guard is for what cannot be undone. Asking on a reversible
        action is not extra safety - it is what makes people stop reading
        the prompt."""
        applicant = CustomUser.objects.create_user(
            username="approve-me", password="pw", role="staff", is_approved=False,
        )
        response = self.client.patch(f"/api/admin/approve-user/{applicant.id}/")
        self.assertEqual(response.status_code, 200)


class SectionEditAttributionTests(TestCase):
    """Every version of a controlled document should say why it exists."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username="history-admin", password=PASSWORD, role="admin",
            is_approved=True,
        )
        self.staff = CustomUser.objects.create_user(
            username="history-staff", password="pw", role="staff",
            is_approved=True,
        )
        self.manual = Manual.objects.create(
            title="FAM 6.02", uploaded_by=self.admin,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES",
            content="The Cashier shall release the cheque.", tag="POLICY",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_a_direct_edit_is_recorded_as_one_with_its_reason(self):
        response = self.client.patch(
            f"/api/sections/{self.section.id}/update/",
            {"content": "The Cashier shall release the cheque in a day.",
             "change_reason": "Corrected the release window after the audit."},
            format="json", HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin),
        )
        self.assertEqual(response.status_code, 200)

        entry = SectionHistory.objects.get(section=self.section)
        self.assertEqual(entry.source, "direct")
        self.assertEqual(entry.edited_by, self.admin)
        self.assertIn("audit", entry.change_reason)
        self.assertIsNone(entry.proposal)

    def test_a_direct_edit_without_a_reason_still_saves(self):
        """Recorded, not enforced. An admin fixing a typo mid-audit should
        not be blocked by a form, and a required field would be filled with
        "." within a week - which is worse than an honest blank."""
        response = self.client.patch(
            f"/api/sections/{self.section.id}/update/",
            {"content": "Typo fixed."}, format="json",
            HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin),
        )
        self.assertEqual(response.status_code, 200)
        entry = SectionHistory.objects.get(section=self.section)
        self.assertEqual(entry.source, "direct")
        self.assertEqual(entry.change_reason, "")

    def test_a_direct_edit_without_the_password_is_refused_and_writes_nothing(self):
        """A direct edit changes a controlled document with nothing behind
        it, so it asks for the password again - and a refusal must leave
        no trace: not the text, not a history row."""
        before = self.section.content
        response = self.client.patch(
            f"/api/sections/{self.section.id}/update/",
            {"content": "Changed without confirming.", "change_reason": "No password."},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")
        self.section.refresh_from_db()
        self.assertEqual(self.section.content, before)
        self.assertFalse(SectionHistory.objects.filter(section=self.section).exists())

    def test_a_wrong_token_is_refused_too(self):
        response = self.client.patch(
            f"/api/sections/{self.section.id}/update/", {"content": "x"},
            format="json", HTTP_X_REAUTH_TOKEN="not-a-token",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_invalid")
        self.section.refresh_from_db()
        self.assertEqual(self.section.content, "The Cashier shall release the cheque.")

    def test_rows_written_before_this_existed_are_unknown_not_guessed(self):
        """Defaulting old rows to "direct" would record a guess as a fact.
        An honest gap is better in an audit trail."""
        entry = SectionHistory.objects.create(
            section=self.section, version=1, subtitle="3.0 POLICIES",
            content="Old text.", tag="POLICY", edited_by=self.admin,
        )
        self.assertEqual(entry.source, "unknown")

    def test_the_history_endpoint_reports_where_each_version_came_from(self):
        self.client.patch(
            f"/api/sections/{self.section.id}/update/",
            {"content": "Edited.", "change_reason": "Because."},
            format="json", HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin),
        )
        rows = self.client.get(f"/api/sections/{self.section.id}/history/").data
        self.assertEqual(rows[0]["source"], "direct")
        self.assertEqual(rows[0]["change_reason"], "Because.")
        # The live section is appended last and is not a snapshot of an edit.
        self.assertEqual(rows[-1]["source"], "current")
