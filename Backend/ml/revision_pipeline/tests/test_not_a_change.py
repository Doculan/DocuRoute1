"""Edits that look like issues to a naive rule but are not.

Each of these was a false positive the rule layer produced at Checkpoint 4,
and each one cost real examples: the generator made a legitimate edit, Layer 1
flagged it, and the quality gate threw the example away as mislabelled.
"""

import pytest

from revision_pipeline.layer1_rules import run_layer1

REASON = {"change_reason": "document review"}


def labels(old, new):
    return {f["label"] for f in run_layer1(old, new, REASON).flags}


# -- expanding an acronym is documentation, not reassignment ------

def test_spelling_out_a_role_is_not_a_changed_responsibility():
    old = "| A | 1. Forwards the DV to the BAC for review. |"
    new = "| A | 1. Forwards the DV to the Bids and Awards Committee (BAC) for review. |"
    assert "responsibility_changed" not in labels(old, new)


def test_a_bracketed_acronym_elsewhere_does_not_hide_a_real_role_change():
    """The filter must look at what sits before the bracket, not the whole row."""
    old = "| Accounting Staff-3 | 6. Prepares the Disbursement Voucher (DV). |"
    new = "| Accounting Staff-4 | 6. Prepares the Disbursement Voucher (DV). |"
    assert "responsibility_changed" in labels(old, new)


# -- the same statute, written the other way ----------------------

@pytest.mark.parametrize("old_form, new_form", [
    ("R.A. 9184", "Republic Act No. 9184"),
    ("Republic Act No. 9184", "R.A. 9184"),
    ("E.O. No. 2", "Executive Order No. 2"),
])
def test_reformatting_a_legal_reference_changes_nothing(old_form, new_form):
    old = f"| A | 1. Procurement follows {old_form} in all cases. |"
    new = f"| A | 1. Procurement follows {new_form} in all cases. |"
    assert labels(old, new) == set()


def test_a_different_statute_is_still_a_change():
    old = "| A | 1. Procurement follows R.A. 9184 in all cases. |"
    new = "| A | 1. Procurement follows R.A. 7160 in all cases. |"
    assert "numeric_changed" in labels(old, new)


def test_number_abbreviation_is_not_a_negation():
    """"No." before a figure is "number", not "no"."""
    old = "| A | 1. Follows Memorandum Circular 5 of the Commission. |"
    new = "| A | 1. Follows Memorandum Circular No. 5 of the Commission. |"
    assert "negation_changed" not in labels(old, new)
