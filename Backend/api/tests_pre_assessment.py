"""A proposal section's AI check: made once, bound to its text, kept.

Rewritten against the proposal check when the v3 single-section flow was
removed (v4.1.0), so the machinery both used keeps its coverage:

**The check is bound to the text it was made about** - fingerprinted over
the normalised texts, so whitespace alone does not invalidate it, and
checking identical content twice reads identically.

**Rate limits, per person and per proposal**, applied where the check is
run rather than assumed.

**The sweep never touches a check a section change points at.** It used to
select by the v3 `consumed_by` link, which proposals never set, so every
proposal's stored check looked unsubmitted - and a sweep would have deleted
them all.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from api import pre_assessment, proposal_views
from api.models import RevisionPreAssessment, SectionChange
from api.tests_proposals import ProposalFixture

NEW_TEXT = "The Cashier may release the cheque within five days."


class CheckFixture(ProposalFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.start().data['id']
        self.client.patch(
            f'/api/proposals/{self.proposal_id}/',
            {'overall_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )
        self.edit(self.proposal_id, self.s2, NEW_TEXT)

    def check(self):
        return self.client.post(
            f'/api/proposals/{self.proposal_id}/sections/{self.s2.id}/check/',
            {}, format='json',
        )

    def change(self):
        return SectionChange.objects.get(section=self.s2, version__proposal_id=self.proposal_id)

    def a_row(self, *, age_days=0, user=None):
        """A stored check, optionally backdated. assessed_at is auto_now_add,
        so it has to be pushed back with an update after the fact."""
        row = RevisionPreAssessment.objects.create(
            section=self.s2, submitted_by=user or self.drafter,
            content_hash="x" * 64, section_content_hash="y" * 64, verdict="approve",
        )
        if age_days:
            RevisionPreAssessment.objects.filter(pk=row.pk).update(
                assessed_at=timezone.now() - timedelta(days=age_days)
            )
        return row


class BoundToItsTextTests(CheckFixture):

    def test_checking_identical_content_twice_reads_identically(self):
        first = self.check().data['assessment']
        second = self.check().data['assessment']
        self.assertEqual(first['verdict'], second['verdict'])
        self.assertEqual(first['explanation'], second['explanation'])

    def test_whitespace_alone_does_not_invalidate_a_check(self):
        self.check()
        self.edit(self.proposal_id, self.s2, "  " + NEW_TEXT + "  \n")
        self.assertTrue(self.change().check_is_current)

    def test_a_real_edit_does(self):
        self.check()
        self.edit(self.proposal_id, self.s2, NEW_TEXT.replace("five", "ten"))
        self.assertFalse(self.change().check_is_current)

    def test_a_result_sent_by_the_client_is_ignored(self):
        """The check is computed by the server; nothing about its result is
        accepted from the request."""
        response = self.client.post(
            f'/api/proposals/{self.proposal_id}/sections/{self.s2.id}/check/',
            {'verdict': 'approve', 'issues': []}, format='json',
        )
        stored = self.change().assessment
        self.assertEqual(response.data['assessment']['verdict'], stored.verdict)
        self.assertEqual(stored.content_hash, pre_assessment.content_hash(
            self.s2.id, self.s2.content, NEW_TEXT,
            'Consolidated after the 2026 management review.'))


class RateLimitTests(CheckFixture):

    def test_the_limit_per_person_is_enforced(self):
        with mock.patch.object(proposal_views, 'RATE_LIMIT_PER_HOUR', 2):
            self.a_row()
            self.a_row()
            response = self.check()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['reason'], 'rate_limited_user')

    def test_it_is_per_person(self):
        with mock.patch.object(proposal_views, 'RATE_LIMIT_PER_HOUR', 2):
            self.a_row(user=self.reader)
            self.a_row(user=self.reader)
            self.assertEqual(self.check().status_code, 200)

    def test_checks_outside_the_hour_do_not_count(self):
        with mock.patch.object(proposal_views, 'RATE_LIMIT_PER_HOUR', 2):
            self.a_row(age_days=1)
            self.a_row(age_days=1)
            self.assertEqual(self.check().status_code, 200)

    def test_the_limit_per_proposal_is_enforced(self):
        with mock.patch.object(proposal_views, 'RATE_LIMIT_PER_PROPOSAL', 1):
            self.assertEqual(self.check().status_code, 200)
            response = self.check()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['reason'], 'rate_limited_proposal')


class SweepTests(CheckFixture):

    def sweep(self, *args):
        out = StringIO()
        call_command('sweep_pre_assessments', *args, stdout=out)
        return out.getvalue()

    def test_a_check_a_section_points_at_is_never_swept(self):
        """The stored result every reader of the proposal sees."""
        self.check()
        kept = self.change().assessment
        RevisionPreAssessment.objects.filter(pk=kept.pk).update(
            assessed_at=timezone.now() - timedelta(days=pre_assessment.RETENTION_DAYS + 30)
        )
        self.sweep()
        self.assertTrue(RevisionPreAssessment.objects.filter(pk=kept.pk).exists())
        self.assertEqual(self.change().assessment_id, kept.pk)

    def test_a_superseded_check_past_the_window_is_swept(self):
        stale = self.a_row(age_days=pre_assessment.RETENTION_DAYS + 1)
        fresh = self.a_row()
        output = self.sweep()
        self.assertIn('deleted 1', output)
        self.assertFalse(RevisionPreAssessment.objects.filter(pk=stale.pk).exists())
        self.assertTrue(RevisionPreAssessment.objects.filter(pk=fresh.pk).exists())

    def test_a_dry_run_reports_and_deletes_nothing(self):
        stale = self.a_row(age_days=pre_assessment.RETENTION_DAYS + 1)
        self.assertIn('would delete 1', self.sweep('--dry-run'))
        self.assertTrue(RevisionPreAssessment.objects.filter(pk=stale.pk).exists())
