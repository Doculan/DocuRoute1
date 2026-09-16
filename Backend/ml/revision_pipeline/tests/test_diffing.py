"""Tests for the diff helpers.

Each case is hand-written and small enough to reason about by eye.
"""

import pytest

from revision_pipeline.diffing import (
    change_ratios,
    marked_text,
    normalise,
    sentences,
    sentences_removed,
    word_diff,
    words,
)


# -- normalisation ---------------------------------------------

def test_normalise_collapses_whitespace_and_case():
    assert normalise("  The   QMR \n SHALL  ") == "the qmr shall"


def test_words_keeps_hyphenated_and_slashed_tokens():
    assert words("Accounting Staff-4 and/or QMR") == [
        "Accounting", "Staff-4", "and/or", "QMR"
    ]


def test_sentences_splits_on_terminators():
    assert sentences("One thing. Two thing! Three?") == [
        "One thing.", "Two thing!", "Three?"
    ]


def test_sentences_keeps_numbered_items_intact():
    # "4.2.1" must not be read as a sentence boundary.
    assert sentences("4.2.1 Checks the ledger. Then signs.") == [
        "4.2.1 Checks the ledger.", "Then signs."
    ]


# -- marked_text -----------------------------------------------

def test_marked_text_wraps_replacement_in_both_tags():
    out = marked_text("the form is approved by the QMR",
                      "the form is checked by the QMR")
    assert out == "the form is [DEL] approved [/DEL] [INS] checked [/INS] by the QMR"


def test_marked_text_keeps_unchanged_context():
    # Layer 2 needs the surrounding wording to judge whether a change matters.
    out = marked_text("staff shall sign the log", "staff may sign the log")
    assert out.startswith("staff ")
    assert out.endswith(" sign the log")


def test_marked_text_pure_insertion():
    out = marked_text("staff sign", "staff sign the log")
    assert "[INS] the log [/INS]" in out
    assert "[DEL]" not in out


# -- ratios ----------------------------------------------------

def test_replacement_is_not_counted_as_deletion():
    # A reworded line is not a deleted line. Counting it as one fired
    # excessive_deletion on every single-line edit.
    r = change_ratios("the form is approved by QMR", "the form is checked by QMR")
    assert r["deleted_word_ratio"] == 0.0
    assert r["deleted_line_ratio"] == 0.0


def test_deleted_word_ratio_counts_real_removals():
    r = change_ratios("a b c d e f g h i j", "a b c d e")
    assert r["deleted_word_ratio"] == pytest.approx(0.5)


def test_inserted_ratio_is_measured_against_the_original():
    r = change_ratios("a b c d", "a b c d e f")
    assert r["inserted_word_ratio"] == pytest.approx(0.5)


def test_net_ratio_ignores_reordering():
    # Moving text is not removing it.
    r = change_ratios("Staff check the form. Staff file it.",
                      "Staff file it. Staff check the form.")
    assert r["net_deleted_word_ratio"] == 0.0


def test_net_ratio_still_sees_real_deletion():
    r = change_ratios("alpha bravo charlie delta", "alpha bravo")
    assert r["net_deleted_word_ratio"] == pytest.approx(0.5)


def test_ratios_handle_empty_original():
    r = change_ratios("", "anything at all")
    assert r["deleted_word_ratio"] == 0.0
    assert r["inserted_word_ratio"] == 0.0


# -- sentence removal ------------------------------------------

def test_reworded_sentence_is_not_removed():
    assert sentences_removed("The QMR shall aprove the form.",
                             "The QMR shall approve the form.") == []


def test_dropped_sentence_is_detected():
    removed = sentences_removed(
        "Staff check the form. Staff sign the log. Staff file it.",
        "Staff check the form. Staff file it.",
    )
    assert removed == ["Staff sign the log."]


def test_matching_is_one_to_one():
    # These share a skeleton; without one-to-one matching a single survivor
    # vouched for every deleted sibling.
    removed = sentences_removed(
        "Staff check the form. Staff check the log. Staff check the file.",
        "Staff check the form.",
    )
    assert len(removed) == 2


def test_reordering_removes_nothing():
    assert sentences_removed("Alpha runs. Bravo walks.",
                             "Bravo walks. Alpha runs.") == []


# -- word diff -------------------------------------------------

def test_word_diff_reports_replacements():
    d = word_diff("shall approve", "must approve")
    assert d.replaced
    old_chunk, new_chunk = d.replaced[0]
    assert old_chunk == ["shall"] and new_chunk == ["must"]


def test_word_diff_separates_pure_deletion():
    d = word_diff("alpha bravo charlie", "alpha charlie")
    assert d.pure_deleted == ["bravo"]
