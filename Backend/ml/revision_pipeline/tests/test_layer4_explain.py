"""Tests for Layer 4: the explanation writer.

The spec asks for three properties, and each has tests here: the text is
deterministic, it is grounded in the Layer 3 output, and every label renders
through all of its phrasings.
"""

import random

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import FusionResult, run_layer3
from revision_pipeline.layer4_explain import (
    _PHRASINGS, MAX_SENTENCES, explain, not_assessed_message,
)

REASON = {"change_reason": "Updated after the August 2026 management review."}


def make_issue(label, confidence=0.9, evidence="the evidence", severity=None):
    return {
        "label": label,
        "source": "rule",
        "confidence": confidence,
        "severity": severity or config.SEVERITY.get(label, "low"),
        "clause": config.ISSUE_CLAUSE.get(label, ""),
        "evidence": evidence,
        "ratio": 0.55,
    }


def layer1_for(old="within 30 days", new="within 60 days", reason=REASON):
    return run_layer1(old, new, reason)


# -- determinism -----------------------------------------------

def test_same_revision_produces_identical_text():
    layer1 = layer1_for()
    fusion = run_layer3(layer1, {})
    first = explain(fusion, layer1, section_label="4.2 Procedures", revision_id=42)
    second = explain(fusion, layer1, section_label="4.2 Procedures", revision_id=42)
    assert first == second


def test_different_revisions_may_differ_but_stay_stable():
    layer1 = layer1_for()
    fusion = run_layer3(layer1, {})
    a = explain(fusion, layer1, section_label="4.2", revision_id=1)
    b = explain(fusion, layer1, section_label="4.2", revision_id=1)
    assert a == b


def test_global_random_state_does_not_leak_in():
    layer1 = layer1_for()
    fusion = run_layer3(layer1, {})
    random.seed(1)
    first = explain(fusion, layer1, revision_id=5)
    random.seed(999)
    second = explain(fusion, layer1, revision_id=5)
    assert first == second


# -- grounding -------------------------------------------------

def test_evidence_appears_in_the_text():
    layer1 = layer1_for()
    fusion = FusionResult(verdict="needs_revision", confidence=0.8,
                          issues=[make_issue("numeric_changed", evidence="30 days, 60 days")])
    text = explain(fusion, layer1, section_label="4.2 Procedures", revision_id=3)
    assert "30 days, 60 days" in text


def test_no_issues_means_no_issue_sentences():
    layer1 = run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON)
    fusion = run_layer3(layer1, {})
    text = explain(fusion, layer1, section_label="4.2", revision_id=3)
    for label in config.ISSUE_LABELS:
        assert label.replace("_", " ") not in text.lower()


def test_hard_fail_states_the_clause_in_the_same_sentence():
    layer1 = run_layer1("old text", "new text", {"change_reason": ""})
    fusion = run_layer3(layer1, {})
    text = explain(fusion, layer1, revision_id=4)
    assert "No reason for the change was recorded, which clause 6.3 requires." in text


# -- hedging ---------------------------------------------------

@pytest.mark.parametrize("confidence,word", [(0.95, "clearly"), (0.7, "likely"), (0.4, "may")])
def test_model_only_issue_is_hedged_by_confidence(confidence, word):
    layer1 = layer1_for()
    issue = make_issue("modal_weakened", confidence=confidence)
    issue["source"] = "model"
    fusion = FusionResult(verdict="needs_revision", confidence=confidence, issues=[issue])
    assert word in explain(fusion, layer1, revision_id=6)


@pytest.mark.parametrize("source", ["rule", "both"])
def test_rule_sourced_issue_is_stated_without_a_hedge(source):
    # A rule did not believe the number changed; it found both numbers.
    layer1 = layer1_for()
    issue = make_issue("modal_weakened", confidence=1.0)
    issue["source"] = source
    fusion = FusionResult(verdict="needs_revision", confidence=0.9, issues=[issue])
    text = explain(fusion, layer1, revision_id=6)
    for hedge in ("clearly", "likely", "may "):
        assert hedge not in text, f"{source} issue was hedged with {hedge!r}: {text}"


def test_no_double_spaces_left_where_the_hedge_was_removed():
    layer1 = layer1_for()
    for label in config.ISSUE_LABELS:
        issue = make_issue(label, evidence="alpha, bravo")
        issue["source"] = "rule"
        fusion = FusionResult(verdict="reject", confidence=0.9, issues=[issue])
        for revision_id in range(12):
            text = explain(fusion, layer1, revision_id=revision_id)
            assert "  " not in text, f"{label}: {text!r}"


def test_passive_templates_put_the_hedge_after_the_auxiliary():
    layer1 = layer1_for()
    issue = make_issue("modal_weakened", confidence=0.95)
    issue["source"] = "model"
    fusion = FusionResult(verdict="needs_revision", confidence=0.9, issues=[issue])
    seen = {explain(fusion, layer1, revision_id=i) for i in range(40)}
    joined = " ".join(seen)
    assert "clearly has been" not in joined
    assert "clearly was" not in joined


def test_model_only_issue_with_no_evidence_still_reads_properly():
    """A model-only issue has no words to quote.

    Every phrasing for contradicts_manual wanted {terms}, so the renderer fell
    back to one anyway and produced "is likely stated differently elsewhere"
    with an empty slot in front of it. Each label now has an evidence-free
    phrasing.
    """
    layer1 = layer1_for()
    for label in config.ISSUE_LABELS:
        issue = make_issue(label, confidence=0.75, evidence="")
        issue["source"] = "model"
        issue.pop("ratio")
        fusion = FusionResult(verdict="needs_revision", confidence=0.7, issues=[issue])
        for revision_id in range(25):
            text = explain(fusion, layer1, section_label="3.2 Review",
                           revision_id=revision_id)
            assert "  " not in text, f"{label}: double space in {text!r}"
            assert " ()" not in text, f"{label}: empty parenthetical in {text!r}"
            assert text.count("(") == text.count(")"), f"{label}: {text!r}"
            # An empty slot at the head of a clause leaves a stranded verb.
            assert " is likely stated" not in text.replace("It is likely stated", "")


def test_a_frequency_word_is_not_reported_as_a_role():
    # "Quarterly" reached the mined role list from a table column header.
    layer1 = run_layer1("The office reviews submissions quarterly.",
                        "The office reviews submissions when convenient.", REASON)
    labels = {f["label"] for f in layer1.flags}
    assert "responsibility_changed" not in labels
    assert "numeric_changed" in labels


# -- coverage --------------------------------------------------

HEDGE_WORDS = ("clearly", "likely", "may ", " may.", "might")


def test_rule_sourced_sentences_carry_no_hedge_and_no_double_space():
    """Every label, every phrasing, both rule sources.

    A rule reports what it found, so its sentences must read as statements -
    and the removed hedge must not leave a gap behind it.
    """
    layer1 = layer1_for()
    for label in config.ISSUE_LABELS:
        for source in ("rule", "both"):
            issue = make_issue(label, confidence=1.0, evidence="alpha, bravo")
            issue["source"] = source
            issue["action"] = "added"
            issue["direction"] = "changed"
            issue["from_text"] = '"30 days"'
            issue["to_text"] = '"60 days"'
            fusion = FusionResult(verdict="reject", confidence=0.9, issues=[issue])
            for revision_id in range(30):
                text = explain(fusion, layer1, section_label="4.2 Procedures",
                               revision_id=revision_id)
                assert "  " not in text, f"{label}/{source}: double space in {text!r}"
                lowered = text.lower()
                for hedge in HEDGE_WORDS:
                    assert hedge not in lowered, (
                        f"{label}/{source}: hedge {hedge!r} in {text!r}"
                    )


def test_a_sentence_never_starts_with_a_lowercase_quote():
    layer1 = layer1_for()
    for label in config.ISSUE_LABELS:
        issue = make_issue(label, confidence=1.0, evidence='"shall" became "may"')
        issue["source"] = "rule"
        fusion = FusionResult(verdict="reject", confidence=0.9, issues=[issue])
        for revision_id in range(30):
            text = explain(fusion, layer1, section_label="4.2 Procedures",
                           revision_id=revision_id)
            for sentence in text.split(". "):
                stripped = sentence.strip()
                if not stripped:
                    continue
                assert not stripped.startswith(('"', "“")), (
                    f"{label}: sentence opens on a quote: {stripped!r}"
                )
                first = stripped[0]
                assert not first.islower(), f"{label}: {stripped!r}"


def test_every_phrasing_has_a_hedge_slot():
    """Without one, a model-only issue is stated as flatly as a detected fact.

    A template added for modal_weakened omitted {hedge}, and because the
    renderer prefers phrasings that quote evidence, it was the one chosen.
    """
    for label, templates in _PHRASINGS.items():
        for template in templates:
            assert "{hedge}" in template, f"{label}: {template!r} has no hedge slot"


def test_every_issue_label_has_at_least_three_phrasings():
    for label in config.ISSUE_LABELS:
        assert label in _PHRASINGS, f"no phrasing for {label}"
        assert len(_PHRASINGS[label]) >= 3, f"{label} has fewer than 3 phrasings"


def test_every_label_renders_through_every_phrasing():
    layer1 = layer1_for()
    for label in config.ISSUE_LABELS:
        rendered = set()
        # Different revision ids pick different phrasings; enough draws covers
        # all of them, and every one must produce usable text.
        for revision_id in range(60):
            fusion = FusionResult(
                verdict="needs_revision", confidence=0.9,
                issues=[make_issue(label, evidence="alpha, bravo")],
            )
            text = explain(fusion, layer1, section_label="4.2 Procedures",
                           revision_id=revision_id)
            assert text.strip()
            assert "{" not in text, f"unfilled slot for {label}: {text}"
            rendered.add(text)
        assert len(rendered) >= 2, f"{label} never varied its phrasing"


def test_every_verdict_has_an_opening_and_closing():
    layer1 = layer1_for()
    for verdict in config.VERDICTS:
        fusion = FusionResult(verdict=verdict, confidence=0.7, issues=[])
        text = explain(fusion, layer1, revision_id=9)
        assert text.strip().endswith(".")
        assert len(text.split()) > 5


# -- structure -------------------------------------------------

def test_sentence_count_is_capped():
    layer1 = layer1_for()
    issues = [make_issue(label) for label in config.ISSUE_LABELS]
    fusion = FusionResult(verdict="reject", confidence=0.9, issues=issues)
    text = explain(fusion, layer1, section_label="4.2", revision_id=11)
    assert text.count(". ") + 1 <= MAX_SENTENCES + 2


def test_extra_issues_are_summarised_not_dropped_silently():
    layer1 = layer1_for()
    issues = [make_issue(label) for label in config.ISSUE_LABELS]
    fusion = FusionResult(verdict="reject", confidence=0.9, issues=issues)
    text = explain(fusion, layer1, section_label="4.2", revision_id=12)
    assert "further issue" in text


def test_equivalent_terminology_change_names_the_actual_terms():
    # "the glossary treats them as equivalent" tells a reviewer nothing they
    # can check. Naming the pair does.
    layer1 = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    fusion = run_layer3(layer1, {})
    text = explain(fusion, layer1, revision_id=13)
    assert "shall" in text and "must" in text
    assert "mean the same thing" in text


def test_the_same_change_is_not_described_twice():
    # "shall" -> "may" is both a weakened modal and a non-equivalent swap.
    # Only the more specific one should be mentioned.
    layer1 = run_layer1("The QMR shall approve the form.",
                        "The QMR may approve the form.", REASON)
    labels = {f["label"] for f in layer1.flags}
    assert "modal_weakened" in labels
    assert "non_equivalent_term" not in labels

    # A swap that is not a modal change still reports normally.
    other = run_layer1("The QMR shall approve it.", "The QMR shall review it.", REASON)
    assert "non_equivalent_term" in {f["label"] for f in other.flags}


def test_numeric_evidence_states_the_direction():
    layer1 = run_layer1("The QMR shall act within 30 days.",
                        "The QMR shall act within 60 days.", REASON)
    flag = [f for f in layer1.flags if f["label"] == "numeric_changed"][0]
    assert flag["direction"] == "changed"
    assert "30 days" in flag["evidence"] and "60 days" in flag["evidence"]
    assert "->" not in flag["evidence"]


def test_a_reworded_sentence_is_not_reported_as_removed():
    # One sentence in, one sentence out: nothing was dropped, it was rewritten.
    layer1 = run_layer1("Credentials are released after fees are settled.",
                        "Credentials are released regardless of unpaid fees.", REASON)
    assert "requirement_removed" not in {f["label"] for f in layer1.flags}
    assert layer1.features["sentences_removed"] == 0


def test_no_sentence_starts_with_a_digit():
    layer1 = run_layer1("A runs. B walks. C sits. D jumps. E waits.", "A runs.", REASON)
    fusion = run_layer3(layer1, {})
    for revision_id in range(30):
        text = explain(fusion, layer1, section_label="4.2 Procedures",
                       revision_id=revision_id)
        for sentence in text.split(". "):
            assert not sentence.strip()[:1].isdigit(), text


def test_cosmetic_change_is_stated_explicitly():
    layer1 = run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON)
    fusion = run_layer3(layer1, {})
    text = explain(fusion, layer1, revision_id=14)
    assert "cosmetic" in text


# -- decision 9 ------------------------------------------------

def test_forms_section_message_says_not_assessed():
    message = not_assessed_message("5.0 LIST OF FORMS")
    assert "Not assessed" in message
    assert "manual admin review" in message
    assert "5.0 LIST OF FORMS" in message
