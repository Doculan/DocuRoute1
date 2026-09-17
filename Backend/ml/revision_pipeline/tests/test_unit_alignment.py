"""Tests for unit-level comparison.

A whole-section comparison sees only which roles, terms and figures are
present somewhere in the section. That misses the most common kind of bad
revision in a procedure table: a step quietly changing hands, or a figure
moving, while the section as a whole still mentions both parties. These tests
pin the behaviour that closes that gap.
"""

from revision_pipeline.diffing import aligned_units
from revision_pipeline.layer1_rules import run_layer1

REASON = {"change_reason": "updated after the management review"}

TABLE = (
    "| Responsibility | Activity |\n"
    "| --- | --- |\n"
    "| Accounting Staff-4 | 1. Receive the request and check the attachments. |\n"
    "| Accounting Staff-7 | 2. Verify the entries against the ledger. |\n"
    "| Accounting Staff-7 | 3. Forward the approved request for signature. |"
)


def flags_of(old, new, **kw):
    return {f["label"] for f in run_layer1(old, new, REASON, **kw).flags}


# -- alignment ----------------------------------------------------

def test_row_matches_on_its_step_text_not_the_whole_row():
    old = "| Clerk | 1. Receive the form. |"
    new = "| Budget Officer | 1. Receive the form. |"
    assert aligned_units(old, new) == [(old, new)]


def test_deleted_row_is_not_paired():
    old = "| A | 1. First step here. |\n| B | 2. Second step here. |"
    new = "| A | 1. First step here. |"
    pairs = aligned_units(old, new)
    assert len(pairs) == 1
    assert "Second step" not in pairs[0][0]


def test_reordered_rows_still_pair_with_themselves():
    old = "| A | 1. First step here. |\n| B | 2. Second step here. |"
    new = "| B | 2. Second step here. |\n| A | 1. First step here. |"
    assert sorted(a for a, _ in aligned_units(old, new)) == sorted(
        b for _, b in aligned_units(old, new)
    )


def test_prose_lines_pair_on_the_whole_line():
    old = "The officer shall verify the entries before release."
    new = "The officer shall verify the entries before payment."
    assert aligned_units(old, new) == [(old, new)]


# -- what the section-wide view missed ----------------------------

def test_step_changing_hands_within_the_section_is_flagged():
    """Staff-7 already owns two steps, so the set of roles does not move."""
    new = TABLE.replace(
        "| Accounting Staff-4 | 1. Receive", "| Accounting Staff-7 | 1. Receive"
    )
    assert "responsibility_changed" in flags_of(TABLE, new)


def test_figure_changed_on_one_step_is_flagged_when_it_survives_elsewhere():
    old = (
        "| A | 1. Submit the report within 5 days. |\n"
        "| B | 2. The 5 day limit is counted from receipt. |"
    )
    new = old.replace("within 5 days", "within 10 days")
    assert "numeric_changed" in flags_of(old, new)


def test_term_dropped_from_one_step_is_flagged_when_named_elsewhere():
    old = (
        "| A | 1. Attach the Disbursement Voucher to the request. |\n"
        "| B | 2. File the Disbursement Voucher after payment. |"
    )
    new = old.replace("Attach the Disbursement Voucher to the request",
                      "Attach the document to the request")
    flags = flags_of(old, new, manual_key_terms=["Disbursement Voucher"])
    assert "key_term_deleted" in flags


# -- and what it must not start reporting -------------------------

def test_reordering_rows_is_not_a_responsibility_change():
    lines = TABLE.splitlines()
    reordered = "\n".join(lines[:2] + [lines[3], lines[2], lines[4]])
    assert "responsibility_changed" not in flags_of(TABLE, reordered)


def test_untouched_section_reports_nothing():
    """An unchanged section is a hard fail, and raises no unit-level flag."""
    result = run_layer1(TABLE, TABLE, REASON)
    assert result.failed
    assert not result.flags
