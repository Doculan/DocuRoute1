"""Sense reversals, item numbers, and what is not a negation.

Three rules that were wrong at Checkpoint 4 and are pinned here:

* An item or step number is a label, not a quantity. Renumbering a list is not
  a changed figure, and it is certainly not a contradiction.
* A requirement can be reversed without a negation word: "before" becomes
  "after", "at least" becomes "at most".
* "university", "information", "internal" and "disbursement" are not
  negations, whatever their first three letters suggest.
"""

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1

REASON = {"change_reason": "updated after the management review"}


def labels(old, new, **kw):
    return {f["label"] for f in run_layer1(old, new, REASON, **kw).flags}


def evidence_for(old, new, label):
    for flag in run_layer1(old, new, REASON).flags:
        if flag["label"] == label:
            return flag["evidence"]
    return None


# -- item and step numbers are not quantities ---------------------

@pytest.mark.parametrize("old, new", [
    ("| A | 3.15 Submits the report to the Dean. |",
     "| A | 1.15 Submits the report to the Dean. |"),
    ("| A | 1. Checks the form. |\n| A | 2. Signs the form. |",
     "| A | 2. Checks the form. |\n| A | 3. Signs the form. |"),
    ("3.5 The office keeps the register.", "3.10 The office keeps the register."),
])
def test_renumbering_is_not_a_figure_change(old, new):
    assert "numeric_changed" not in labels(old, new)


def test_a_real_quantity_still_registers():
    old = "| A | 1. Submits the report within 15 days of receipt. |"
    new = "| A | 1. Submits the report within 30 days of receipt. |"
    assert "numeric_changed" in labels(old, new)
    assert evidence_for(old, new, "numeric_changed") == '"15 days" to "30 days"'


def test_an_amount_is_a_quantity_even_at_the_start_of_a_clause():
    old = "| A | 1. Pays the fee of 500 pesos before release. |"
    new = "| A | 1. Pays the fee of 750 pesos before release. |"
    assert "numeric_changed" in labels(old, new)


# -- sense reversals ----------------------------------------------

REVERSALS = [
    ("before", "after"), ("with", "without"), ("at least", "at most"),
    ("include", "exclude"), ("required", "optional"),
    ("allowed", "prohibited"),
]


@pytest.mark.parametrize("first, second", REVERSALS)
def test_reversal_is_reported_as_a_negation_change(first, second):
    old = f"| A | 1. The office shall {first} the supporting documents. |"
    new = f"| A | 1. The office shall {second} the supporting documents. |"
    assert "negation_changed" in labels(old, new)


@pytest.mark.parametrize("first, second", REVERSALS)
def test_reversal_works_in_both_directions(first, second):
    old = f"| A | 1. The office shall {second} the supporting documents. |"
    new = f"| A | 1. The office shall {first} the supporting documents. |"
    assert "negation_changed" in labels(old, new)


def test_reversal_names_the_pair():
    old = "| A | 1. Submits the report before the deadline. |"
    new = "| A | 1. Submits the report after the deadline. |"
    assert evidence_for(old, new, "negation_changed") == '"before" became "after"'


def test_reversal_is_reported_once_not_also_as_a_term_swap():
    old = "| A | 1. Submits the report before the deadline. |"
    new = "| A | 1. Submits the report after the deadline. |"
    assert "non_equivalent_term" not in labels(old, new)


def test_with_to_without_is_one_change_not_two():
    """"without" is a negation word *and* the far side of a reversal."""
    old = "| A | 1. Releases the check with prior approval. |"
    new = "| A | 1. Releases the check without prior approval. |"
    assert evidence_for(old, new, "negation_changed") == '"with" became "without"'


def test_every_configured_pair_is_detectable():
    for first, second in config.SENSE_REVERSALS:
        old = f"The officer shall {first} the request."
        new = f"The officer shall {second} the request."
        assert "negation_changed" in labels(old, new), (first, second)


# -- what is not a negation ---------------------------------------

@pytest.mark.parametrize("word", [
    "University", "information", "internal", "inspection", "disbursement",
    "instruction", "distribution", "unit", "indicates",
])
def test_ordinary_words_are_not_negations(word):
    old = (f"| A | 1. Files the {word} record. |\n"
           "| B | 2. Signs the register. |")
    new = "| B | 2. Signs the register. |"
    assert "negation_changed" not in labels(old, new)


def test_a_genuine_negated_form_still_counts():
    old = "| A | 1. Returns the form when the entries are complete. |"
    new = "| A | 1. Returns the form when the entries are incomplete. |"
    assert "negation_changed" in labels(old, new)


def test_deleting_a_bank_row_reports_only_the_deletion():
    table = ("| No. | Account Name | Bank |\n| --- | --- | --- |\n"
             "| 3 | Cash in Bank, Current Account | Leyte Normal University |\n"
             "| 4 | Cash in Bank, Savings Account | Development Bank |")
    shorter = "\n".join(table.splitlines()[:3])
    assert "negation_changed" not in labels(table, shorter)
