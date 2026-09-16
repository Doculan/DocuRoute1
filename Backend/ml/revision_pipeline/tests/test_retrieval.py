"""Tests for related-section retrieval.

These use hand-made Section records rather than the database, so they run
without Django and stay stable when the corpus changes.
"""

import pytest

from revision_pipeline.retrieval import (
    DocumentIndex,
    Section,
    format_context,
    is_forms_section,
    is_related_by_hierarchy,
    section_number,
)


def make_sections():
    return [
        Section(1, "1.0 OBJECTIVES", "To set out how receivables are monitored and collected.", 0),
        Section(2, "2.0 SCOPE", "Applies to all receivables from official university transactions.", 1),
        Section(3, "3.0 POLICIES", "Accounts past due means unpaid for over 365 days.", 2),
        Section(4, "4.0 PROCEDURES", "Steps for monitoring receivables and issuing clearance.", 3),
        Section(5, "4.4 Student Accounts", "Accounting Staff-4 checks the ledger before clearance.", 4),
        Section(6, "4.5 Other Debtors", "Accounts over 1 year are escalated for collection.", 5),
        Section(7, "5.0 LIST OF FORMS", "Clearance. Promissory Note.", 6),
    ]


# -- section numbers -------------------------------------------

def test_section_number_parses_dotted_numbers():
    assert section_number("4.5 Other Debtors") == (4, 5)
    assert section_number("4.0 PROCEDURES") == (4, 0)


def test_section_number_of_unnumbered_title_is_empty():
    assert section_number("Appendix") == ()


# -- hierarchy ------------------------------------------------

def test_parent_and_child_are_related():
    assert is_related_by_hierarchy("4.0 PROCEDURES", "4.5 Other Debtors")
    assert is_related_by_hierarchy("4.5 Other Debtors", "4.0 PROCEDURES")


def test_siblings_are_not_related():
    # Deliberate: siblings are where a repeated figure or role turns up, which
    # is exactly what the cross-reference check needs to see.
    assert not is_related_by_hierarchy("4.4 Student Accounts", "4.5 Other Debtors")


def test_different_top_level_sections_are_not_related():
    assert not is_related_by_hierarchy("3.0 POLICIES", "4.0 PROCEDURES")


def test_deeper_descendants_are_related():
    assert is_related_by_hierarchy("4.5 Other Debtors", "4.5.1 Escalation")


# -- retrieval -------------------------------------------------

def test_query_does_not_retrieve_its_own_subsection():
    sections = make_sections()
    index = DocumentIndex("doc", sections)
    hits = index.top_k(sections[3].content, exclude_section_id=4, k=5,
                       exclude_subtitle="4.0 PROCEDURES")
    labels = [h.label for h in hits]
    assert "4.4 Student Accounts" not in labels
    assert "4.5 Other Debtors" not in labels


def test_query_does_not_retrieve_its_own_parent():
    sections = make_sections()
    index = DocumentIndex("doc", sections)
    hits = index.top_k(sections[5].content, exclude_section_id=6, k=5,
                       exclude_subtitle="4.5 Other Debtors")
    assert "4.0 PROCEDURES" not in [h.label for h in hits]


def test_siblings_are_still_retrievable():
    sections = make_sections()
    index = DocumentIndex("doc", sections)
    hits = index.top_k("ledger clearance student accounts", exclude_section_id=6, k=5,
                       exclude_subtitle="4.5 Other Debtors")
    assert "4.4 Student Accounts" in [h.label for h in hits]


def test_query_never_returns_itself():
    sections = make_sections()
    index = DocumentIndex("doc", sections)
    hits = index.top_k(sections[2].content, exclude_section_id=3, k=5,
                       exclude_subtitle="3.0 POLICIES")
    assert 3 not in [h.section_id for h in hits]


def test_empty_sections_are_skipped():
    sections = make_sections() + [Section(99, "6.0 EMPTY", "   ", 7)]
    index = DocumentIndex("doc", sections)
    assert 99 not in [s.section_id for s in index.sections]


def test_index_with_no_usable_sections_returns_nothing():
    index = DocumentIndex("doc", [Section(1, "1.0 X", "  ", 0)])
    assert index.top_k("anything") == []


# -- forms sections --------------------------------------------

def test_forms_section_is_recognised():
    # Decision 9: never a revision unit, but still retrievable as context.
    assert is_forms_section("5.0 LIST OF FORMS")
    assert is_forms_section("5.0 list of forms")
    assert not is_forms_section("4.0 PROCEDURES")


def test_forms_section_can_still_be_retrieved_as_context():
    sections = make_sections()
    index = DocumentIndex("doc", sections)
    hits = index.top_k("clearance promissory note", exclude_section_id=4, k=5,
                       exclude_subtitle="4.0 PROCEDURES")
    assert "5.0 LIST OF FORMS" in [h.label for h in hits]


# -- context formatting ----------------------------------------

def test_context_labels_each_section():
    sections = make_sections()
    text = format_context("FAM 6.02", [sections[2]])
    assert text.startswith("PARENT FAM 6.02")
    assert "SECTION 3.0 POLICIES:" in text


def test_context_is_capped():
    long_section = Section(1, "3.0 POLICIES", "word " * 2000, 0)
    text = format_context("DOC", [long_section], max_chars=200)
    assert len(text) <= 210
    assert text.endswith("...")
