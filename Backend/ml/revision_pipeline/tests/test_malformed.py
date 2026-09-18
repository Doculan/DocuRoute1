"""Text an edit has broken, reported but never acted on.

These findings are advisories, not issue labels. Two properties matter as much
as the detection itself and are asserted here: they stay out of the trained
label space, and they stay out of the fusion feature vector. Either would
invalidate the shipped model.
"""

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import build_feature_vector, run_layer3
from revision_pipeline.malformed import malformed_advisories, malformed_faults

REASON = {"change_reason": "Updated after the August 2026 management review."}

CITATION_OLD = "Any request shall be governed by E.O. No. 2, series of 2016."
ACRONYM_OLD = "Attach the Authority to Charge Receivable (ACR) to the voucher."


def kinds(old, new):
    return {fault["kind"] for fault in malformed_faults(old, new)}


# -- what it catches -------------------------------------------

def test_a_parenthetical_dropped_inside_an_abbreviation():
    """The real defect: a cross-reference inserted mid-citation."""
    new = ("Any request shall be governed by E.O (see 4.1 Public Bidding). "
           "No. 2, series of 2016.")
    assert "split_abbreviation" in kinds(CITATION_OLD, new)


@pytest.mark.parametrize("stem", ["E.O", "R.A", "No", "Sec", "P.D"])
def test_every_listed_abbreviation_is_protected(stem):
    old = f"Governed by {stem}. 2 of the policy."
    new = f"Governed by {stem} (see 4.1). 2 of the policy."
    assert "split_abbreviation" in kinds(old, new)


def test_a_citation_left_without_its_number():
    assert "truncated_citation" in kinds(
        CITATION_OLD, "Any request shall be governed by E.O.")


def test_an_acronym_whose_name_was_removed():
    assert "orphaned_acronym" in kinds(
        ACRONYM_OLD, "Attach the (ACR) to the voucher.")


def test_a_bracket_the_edit_left_open():
    assert "unbalanced_brackets" in kinds(
        "Attach the voucher (see 4.2) before release.",
        "Attach the voucher (see 4.2 before release.")


def test_one_break_is_not_reported_twice():
    """A split abbreviation also looks truncated; say it once."""
    new = "Any request shall be governed by E.O (see 4.1 Public Bidding). No. 2."
    assert kinds(CITATION_OLD, new) == {"split_abbreviation"}


# -- what it leaves alone --------------------------------------

@pytest.mark.parametrize("old,new", [
    ("The Cashier shall release the cheque within five days.",
     "The Cashier shall release the cheque within ten days."),
    # a well-formed citation, in either spelling
    ("Governed by R.A. 10173 and E.O. No. 2.",
     "Governed by Republic Act No. 10173 and E.O. No. 2."),
    # an acronym that still has its name
    ("Attach the Disbursement Voucher (DV) to the request.",
     "Attach the Disbursement Voucher (DV) to the approved request."),
])
def test_a_clean_edit_is_silent(old, new):
    assert malformed_faults(old, new) == []


def test_a_fault_the_edit_inherited_is_not_blamed_on_the_submitter():
    """The manuals carry extraction oddities; only new breakage counts."""
    old = "Attach the (ACR) to the voucher before release."
    new = "Attach the (ACR) to the voucher before release of funds."
    assert malformed_faults(old, new) == []


def test_republic_act_with_its_number_is_not_truncated():
    """`No.` before the digits must not be read as the end of the citation."""
    assert kinds("Governed by Republic Act 10173.",
                 "Governed by Republic Act No. 10173.") == set()


# -- how it is reported ----------------------------------------

def test_the_advisory_names_the_clause_and_shows_the_span():
    new = "Any request shall be governed by E.O (see 4.1 Public Bidding). No. 2."
    advisory = malformed_advisories(CITATION_OLD, new)[0]
    assert advisory["label"] == "malformed_citation"
    assert advisory["clause"] == "7.5.3"
    assert "E.O (see 4.1 Public Bidding)." in advisory["evidence"]


def test_layer1_reports_it_without_failing_or_flagging():
    new = "Any request shall be governed by E.O (see 4.1 Public Bidding). No. 2."
    result = run_layer1(CITATION_OLD, new, REASON)
    assert not result.failed
    assert "malformed_citation" in {a["label"] for a in result.advisories}
    # it is not an issue label, and must never become one
    assert "malformed_citation" not in {f["label"] for f in result.flags}
    assert "malformed_citation" not in config.ISSUE_LABELS
    assert "malformed_text" not in config.ISSUE_LABELS


# -- and cannot disturb the shipped model ----------------------

def test_it_adds_nothing_to_the_fusion_feature_vector():
    """The vector is built from features and change_type only. If an advisory
    ever reached it, the shipped fusion model would be reading a column it was
    never trained on."""
    clean = "Any request shall be governed by E.O. No. 3, series of 2016."
    broken = "Any request shall be governed by E.O (see 4.1 Public Bidding). No. 3."
    a = run_layer1(CITATION_OLD, clean, REASON)
    b = run_layer1(CITATION_OLD, broken, REASON)
    assert b.advisories and not a.advisories
    assert len(build_feature_vector(a.features, a.change_type, None, None)) == \
           len(build_feature_vector(b.features, b.change_type, None, None))
    assert set(a.features) == set(b.features)


def test_it_does_not_move_the_verdict():
    """affects_verdict is False, so an approve stays an approve."""
    new = "Any request shall be governed by E.O (see 4.1 Public Bidding). No. 2."
    layer1 = run_layer1(CITATION_OLD, new, REASON)
    layer1.flags.clear()          # isolate the advisory from any rule finding
    result = run_layer3(layer1, {"verdict_probs": [0.95, 0.03, 0.02],
                                 "issue_probs": [0.0] * len(config.ISSUE_LABELS)})
    assert result.verdict == "approve"
    assert [o["rule"] for o in result.overrides] == []
    assert "malformed_citation" in {a["label"] for a in result.advisories}


def test_a_vague_reason_still_moves_the_verdict():
    """The gate must not have switched off the clause 6.3 advisory."""
    layer1 = run_layer1(
        "The Cashier shall prepare the report and submit it to the Dean.",
        "The Cashier shall prepare the report, and submit it to the Dean.",
        {"change_reason": "Minor changes as discussed"},
    )
    result = run_layer3(layer1, {"verdict_probs": [0.95, 0.03, 0.02],
                                 "issue_probs": [0.0] * len(config.ISSUE_LABELS)})
    assert result.verdict == "needs_revision"
    assert [o["rule"] for o in result.overrides] == ["advisory"]
