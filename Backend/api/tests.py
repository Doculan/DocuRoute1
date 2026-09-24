"""API-level tests for the clause 6.3 change-reason rule, on proposals.

The tier logic itself is tested in
``ml/revision_pipeline/tests/test_change_reason.py``, which runs without
Django. What matters here is the other half of the contract: that
submitting a proposal applies it - refusing tier 1 with a message the
submitter can act on, and letting tier 2 through, so the pipeline can flag
a vague reason rather than the API blocking a change that may be sound.

Ported from the v3 single-section endpoints when those were removed
(v4.1.0), so the rule keeps its coverage.
"""

from api.models import Proposal
from api.tests_concurrence import ConcurrenceFixture

BLOCKED = [
    "update",                 # one word, under the length floor
    "typo fix",               # two words
    "...............",        # punctuation only
    "aaaaaaaaaaaaaaaaaaaa",   # one character repeated
]

ACCEPTED_BUT_WEAK = "Updated for compliance purposes"
ACCEPTED_CLEAN = "Bank details changed after the branch moved to LandBank."


class ChangeReasonValidationTests(ConcurrenceFixture):
    """Submission enforces the two tiers on the proposal's one reason."""

    def with_reason(self, reason):
        proposal_id = self.a_draft()
        self.client.patch(f'/api/proposals/{proposal_id}/',
                          {'overall_reason': reason}, format='json')
        return proposal_id

    def test_every_tier_one_reason_is_refused_with_a_usable_message(self):
        for reason in BLOCKED:
            with self.subTest(reason=reason):
                proposal_id = self.with_reason(reason)
                response = self.submit(proposal_id)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['reason'], 'reason_rejected')
                self.assertIn(response.data['tier'], ('missing', 'invalid'))
                # The message has to tell the submitter what to do.
                self.assertIn('please', response.data['error'].lower())
                self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.DRAFT)
                Proposal.objects.filter(pk=proposal_id).update(status=Proposal.WITHDRAWN)
                Proposal.objects.get(pk=proposal_id).refresh_open_changes()

    def test_a_missing_reason_blocks_submission(self):
        proposal_id = self.with_reason('')
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_ready')
        self.assertIn('The reason for the change is required.', response.data['blockers'])

    def test_a_weak_reason_is_accepted(self):
        proposal_id = self.with_reason(ACCEPTED_BUT_WEAK)
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.CONCURRENCE)

    def test_a_specific_reason_is_accepted_and_stored_trimmed(self):
        proposal_id = self.with_reason('  ' + ACCEPTED_CLEAN + '  ')
        self.assertEqual(self.submit(proposal_id).status_code, 200)
        version = Proposal.objects.get(pk=proposal_id).current_version()
        self.assertEqual(version.overall_reason, ACCEPTED_CLEAN)

    def test_the_reason_reaches_the_concurring_offices(self):
        proposal_id = self.with_reason(ACCEPTED_CLEAN)
        self.submit(proposal_id)
        data = self.as_(self.bud_head).get(f'/api/proposals/{proposal_id}/full/').data
        self.assertEqual(data['versions'][-1]['overall_reason'], ACCEPTED_CLEAN)
