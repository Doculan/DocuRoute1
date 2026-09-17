"""Tests for Layer 1: one per feature, plus the flags and change types.

Cases avoid depending on the mined entity lists where possible, so the suite
stays stable when entities.json is re-reviewed. Where a role is needed, the
suffixed form ("Accounting Staff-4") is used, since that is matched by regex
rather than by lookup.
"""

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1

REASON = {"change_reason": "policy update approved by the QMR"}
GOOD_REASON = REASON["change_reason"]


def feats(old, new, **kw):
    return run_layer1(old, new, REASON, **kw).features


def labels(old, new, **kw):
    return {f["label"] for f in run_layer1(old, new, REASON, **kw).flags}


# -- hard fails ------------------------------------------------

def test_missing_change_reason_is_a_hard_fail_under_clause_6_3():
    result = run_layer1("old text here", "new text here", {"change_reason": ""})
    assert result.failed
    fail = result.hard_fails[0]
    assert fail["reason"] == "no_change_reason"
    assert fail["clause"] == "6.3"


def test_empty_revision_is_a_hard_fail():
    result = run_layer1("something", "   ", REASON)
    assert {f["reason"] for f in result.hard_fails} == {"empty_revision"}


def test_identical_text_is_a_hard_fail():
    result = run_layer1("The QMR shall sign.", "the qmr   shall sign.", REASON)
    assert {f["reason"] for f in result.hard_fails} == {"no_change"}


def test_department_mismatch_is_not_a_hard_fail():
    # Decision 3: FAM documents live in the CAS/CME test departments, so a
    # department check would reject valid revisions.
    result = run_layer1(
        "old wording", "new wording",
        {"change_reason": GOOD_REASON, "submitter_department": "CAS",
         "manual_department": "FAM"},
    )
    assert not result.failed


def test_a_valid_revision_has_no_hard_fails():
    assert not run_layer1("The QMR shall sign.", "The QMR must sign.", REASON).failed


# -- size features ---------------------------------------------

def test_deleted_word_ratio():
    assert feats("a b c d e f g h i j", "a b c d e")["deleted_word_ratio"] == pytest.approx(0.5)


def test_inserted_word_ratio():
    assert feats("a b c d", "a b c d e f")["inserted_word_ratio"] == pytest.approx(0.5)


def test_net_deleted_word_ratio_ignores_moves():
    assert feats("Alpha runs. Bravo walks.", "Bravo walks. Alpha runs.")["net_deleted_word_ratio"] == 0.0


def test_sentences_removed_counts_dropped_requirements():
    f = feats("Staff check the form. Staff sign the log. Staff file it.",
              "Staff check the form. Staff file it.")
    assert f["sentences_removed"] == 1


# -- key terms -------------------------------------------------

def test_key_terms_deleted_count():
    f = feats("Submit the Promissory Note to the office.",
              "Submit the paperwork to the office.",
              manual_key_terms=["Promissory Note"])
    assert f["key_terms_deleted_count"] == 1


def test_key_term_still_present_is_not_counted():
    f = feats("Submit the Promissory Note today.",
              "Submit the Promissory Note tomorrow.",
              manual_key_terms=["Promissory Note"])
    assert f["key_terms_deleted_count"] == 0


# -- modals ----------------------------------------------------

def test_modal_weakened_when_obligation_becomes_permission():
    assert feats("The QMR shall approve it.", "The QMR may approve it.")["modal_weakened_count"] == 1


def test_shall_to_must_is_not_a_weakening():
    # Appendix A4: this corpus uses shall/must/will interchangeably.
    assert feats("The QMR shall approve it.", "The QMR must approve it.")["modal_weakened_count"] == 0


def test_should_to_shall_is_strengthening_not_weakening():
    assert feats("The QMR should approve it.", "The QMR shall approve it.")["modal_weakened_count"] == 0


def test_deleting_the_sentence_is_not_a_weakening():
    # Losing "shall" because the sentence went is a deletion, not a weakening.
    f = feats("Staff file it. The QMR shall approve it.", "Staff file it.")
    assert f["modal_weakened_count"] == 0
    assert f["sentences_removed"] == 1


# -- negation --------------------------------------------------

def test_added_negation_is_detected():
    assert feats("Credentials are released.", "Credentials are not released.")["negation_changed"] >= 1


def test_removed_negation_is_detected():
    assert feats("Credentials are not released.", "Credentials are released.")["negation_changed"] >= 1


def test_unchanged_negation_is_not_flagged():
    assert feats("It is not allowed here.", "It is not allowed there.")["negation_changed"] == 0


# -- numbers ---------------------------------------------------

def test_numeric_change_detected():
    assert feats("within 30 days", "within 60 days")["numeric_changed_count"] > 0


def test_frequency_word_change_detected():
    assert feats("Reports are submitted weekly.", "Reports are submitted monthly.")["numeric_changed_count"] > 0


def test_legal_reference_change_detected():
    assert feats("under Republic Act 10173", "under Republic Act 11032")["numeric_changed_count"] > 0


def test_role_suffix_change_is_not_a_numeric_change():
    # Appendix A5 is explicit: Staff-4 -> Staff-7 is a responsibility change.
    f = feats("Accounting Staff-4 checks the ledger.",
              "Accounting Staff-7 checks the ledger.")
    assert f["numeric_changed_count"] == 0
    assert f["role_terms_changed_count"] > 0


# -- roles -----------------------------------------------------

def test_role_change_detected():
    assert feats("Accounting Staff-4 signs.", "Accounting Staff-2 signs.")["role_terms_changed_count"] > 0


def test_unchanged_role_is_not_flagged():
    assert feats("Accounting Staff-4 signs it.", "Accounting Staff-4 files it.")["role_terms_changed_count"] == 0


# -- glossary swaps --------------------------------------------

def test_equivalent_swap_counted():
    assert feats("The QMR shall sign.", "The QMR must sign.")["equivalent_swaps"] == 1


def test_non_equivalent_swap_counted():
    assert feats("The QMR shall approve it.", "The QMR shall review it.")["non_equivalent_swaps"] == 1


def test_unknown_swap_counted():
    f = feats("The zebra walks here.", "The giraffe walks here.")
    assert f["unknown_swaps"] == 1
    assert f["equivalent_swaps"] == 0 and f["non_equivalent_swaps"] == 0


# -- cross-reference conflicts (A6) ----------------------------

def test_cross_ref_conflict_detected():
    # Section says 365 days; a sibling section still states it.
    f = feats("Past due means over 365 days.", "Past due means over 180 days.",
              related_sections=["Accounts unpaid for 365 days are escalated."])
    assert f["cross_ref_conflict_count"] >= 1


def test_no_conflict_when_siblings_do_not_mention_the_value():
    f = feats("Past due means over 365 days.", "Past due means over 180 days.",
              related_sections=["Unrelated wording entirely."])
    assert f["cross_ref_conflict_count"] == 0


# -- change type -----------------------------------------------

def test_whitespace_only_change_is_cosmetic():
    assert run_layer1("The  QMR shall sign.", "The QMR shall sign .", REASON).change_type == "cosmetic"


def test_typo_fix_is_cosmetic():
    assert run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON).change_type == "cosmetic"


def test_equivalent_swap_is_terminology_equivalent():
    assert run_layer1("The QMR shall sign.", "The QMR must sign.", REASON).change_type == "terminology_equivalent"


def test_non_equivalent_swap_is_terminology_non_equivalent():
    assert run_layer1("The QMR shall approve it.", "The QMR shall review it.", REASON).change_type == "terminology_non_equivalent"


def test_meaning_change_is_substantive():
    assert run_layer1("Credentials are released.", "Credentials are not released.", REASON).change_type == "substantive"


# -- flags -----------------------------------------------------

def test_excessive_deletion_flag():
    assert "excessive_deletion" in labels(
        "Alpha runs. Bravo walks. Charlie sits. Delta jumps. Echo waits.", "Alpha runs."
    )


def test_reordering_does_not_flag_excessive_deletion():
    assert "excessive_deletion" not in labels(
        "Staff check the form. Staff file it.", "Staff file it. Staff check the form."
    )


def test_typo_fix_raises_no_flags():
    assert labels("The QMR shall aprove it.", "The QMR shall approve it.") == set()


def test_requirement_removed_flag():
    assert "requirement_removed" in labels(
        "Staff check the form. Staff sign the log. Staff file it.",
        "Staff check the form. Staff file it.",
    )


def test_flags_carry_clause_and_evidence():
    flags = run_layer1("within 30 days", "within 60 days", REASON).flags
    numeric = [f for f in flags if f["label"] == "numeric_changed"][0]
    assert numeric["clause"] == config.ISSUE_CLAUSE["numeric_changed"]
    assert numeric["severity"] == config.SEVERITY["numeric_changed"]
    assert numeric["evidence"]


def test_every_flag_label_is_a_known_issue_label():
    result = run_layer1(
        "Accounting Staff-4 shall verify the ledger within 30 days. Staff sign the log.",
        "Accounting Staff-7 may check the ledger within 60 days.",
        REASON,
    )
    for flag in result.flags:
        assert flag["label"] in config.ISSUE_LABELS


# -- feature vector --------------------------------------------

def test_feature_vector_length_matches_config():
    vec = run_layer1("a b c", "a b d", REASON).feature_vector()
    assert len(vec) == len(config.LAYER1_FEATURES) + len(config.CHANGE_TYPES)


def test_feature_vector_one_hot_marks_the_change_type():
    result = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    vec = result.feature_vector()
    one_hot = vec[len(config.LAYER1_FEATURES):]
    assert sum(one_hot) == 1
    assert one_hot[config.CHANGE_TYPES.index(result.change_type)] == 1.0


def test_every_configured_feature_is_produced():
    result = run_layer1("within 30 days", "within 60 days", REASON)
    missing = set(config.LAYER1_FEATURES) - set(result.features)
    assert not missing, f"features never populated: {sorted(missing)}"
