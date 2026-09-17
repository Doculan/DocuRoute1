"""Tests for Layer 3: merging issues and applying the overrides."""

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import (
    build_feature_vector, feature_names, merge_issues, rules_only_verdict, run_layer3,
)

REASON = {"change_reason": "policy update"}


def probs_for(*labels, value=0.9):
    vec = [0.01] * len(config.ISSUE_LABELS)
    for label in labels:
        vec[config.ISSUE_TO_ID[label]] = value
    return vec


# -- feature vector --------------------------------------------

def test_feature_vector_length_matches_names():
    layer1 = run_layer1("within 30 days", "within 60 days", REASON)
    vec = build_feature_vector(
        layer1.features, layer1.change_type,
        [0.1, 0.2, 0.7], [0.0] * len(config.ISSUE_LABELS),
    )
    assert len(vec) == len(feature_names())


def test_feature_vector_handles_missing_layer2():
    layer1 = run_layer1("a b c", "a b d", REASON)
    vec = build_feature_vector(layer1.features, layer1.change_type, None, None)
    assert len(vec) == len(feature_names())
    assert all(isinstance(v, float) for v in vec)


# -- merging ---------------------------------------------------

def test_rule_only_issue_is_marked_rule():
    flags = [{"label": "numeric_changed", "severity": "medium",
              "clause": "7.5.3", "evidence": "30 days"}]
    merged = merge_issues(flags, [0.0] * len(config.ISSUE_LABELS),
                          policy="union")
    assert merged[0]["source"] == "rule"


def test_model_only_issue_is_marked_model():
    merged = merge_issues([], probs_for("contradicts_manual"))
    assert [i["label"] for i in merged] == ["contradicts_manual"]
    assert merged[0]["source"] == "model"


def test_issue_found_by_both_is_marked_both():
    flags = [{"label": "numeric_changed", "severity": "medium",
              "clause": "7.5.3", "evidence": "30 days"}]
    merged = merge_issues(flags, probs_for("numeric_changed"))
    assert merged[0]["source"] == "both"


def test_model_issue_below_threshold_is_dropped():
    merged = merge_issues([], probs_for("numeric_changed", value=0.4),
                          thresholds={"numeric_changed": 0.8})
    assert merged == []


def test_issues_are_sorted_by_severity_then_confidence():
    flags = [
        {"label": "numeric_changed", "severity": "medium", "clause": "", "evidence": "x"},
        {"label": "requirement_removed", "severity": "high", "clause": "", "evidence": "y"},
    ]
    merged = merge_issues(flags, [0.0] * len(config.ISSUE_LABELS),
                          policy="union")
    assert merged[0]["label"] == "requirement_removed"


def test_extra_flag_fields_survive_the_merge():
    """Layer 4 reads `action` and `ratio`; dropping them silently degraded the
    text to "was changed" and made every {ratio} phrasing unusable."""
    flags = [
        {"label": "negation_changed", "severity": "high", "clause": "7.5.3",
         "evidence": "not", "action": "added", "added": ["not"], "removed": []},
        {"label": "excessive_deletion", "severity": "high", "clause": "7.5.3",
         "evidence": "60% of the wording was removed", "ratio": 0.6},
    ]
    merged = {i["label"]: i for i in
              merge_issues(flags, [0.0] * len(config.ISSUE_LABELS),
                           policy="union")}
    assert merged["negation_changed"]["action"] == "added"
    assert merged["excessive_deletion"]["ratio"] == 0.6


def test_every_merged_issue_carries_clause_and_severity():
    merged = merge_issues([], probs_for("responsibility_changed"))
    assert merged[0]["clause"] == config.ISSUE_CLAUSE["responsibility_changed"]
    assert merged[0]["severity"] == config.SEVERITY["responsibility_changed"]


# -- overrides -------------------------------------------------

def test_hard_fail_forces_reject_whatever_the_model_says():
    layer1 = run_layer1("old wording here", "new wording here", {"change_reason": ""})
    # Layer 2 is confident this is fine; the objection is procedural.
    result = run_layer3(layer1, {"verdict_probs": [0.99, 0.005, 0.005],
                                 "issue_probs": [0.0] * len(config.ISSUE_LABELS)})
    assert result.verdict == "reject"
    assert result.confidence == 1.0
    assert result.overrides[0]["rule"] == "hard_fail"


def test_agreed_high_severity_blocks_an_approve():
    layer1 = run_layer1(
        "Staff check the form. Staff sign the log. Staff file it.",
        "Staff check the form. Staff file it.", REASON,
    )
    assert any(f["label"] == "requirement_removed" for f in layer1.flags)
    result = run_layer3(layer1, {"verdict_probs": [0.95, 0.03, 0.02],
                                 "issue_probs": probs_for("requirement_removed")})
    assert result.verdict == "needs_revision"
    assert result.overrides[0]["rule"] == "agreed_high_severity"


def test_single_source_high_severity_does_not_override():
    # Only the model flags it; that is not agreement.
    layer1 = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    result = run_layer3(layer1, {"verdict_probs": [0.95, 0.03, 0.02],
                                 "issue_probs": probs_for("requirement_removed")})
    assert result.verdict == "approve"
    assert result.overrides == []


def test_layer2_probabilities_are_used_when_there_is_no_fusion_model():
    layer1 = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    result = run_layer3(layer1, {"verdict_probs": [0.1, 0.8, 0.1],
                                 "issue_probs": [0.0] * len(config.ISSUE_LABELS)})
    assert result.verdict == "needs_revision"
    assert result.confidence == pytest.approx(0.8)


# -- rules-only mode -------------------------------------------

def test_rules_only_approves_a_cosmetic_change():
    layer1 = run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON)
    assert rules_only_verdict(layer1) == "approve"


def test_rules_only_approves_an_equivalent_swap():
    layer1 = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    assert rules_only_verdict(layer1) == "approve"


def test_rules_only_rejects_a_high_severity_flag():
    layer1 = run_layer1("Credentials are released.", "Credentials are not released.", REASON)
    assert rules_only_verdict(layer1) == "reject"


def test_rules_only_rejects_a_hard_fail():
    layer1 = run_layer1("old text", "new text", {"change_reason": ""})
    assert rules_only_verdict(layer1) == "reject"


def test_rules_only_confidence_tracks_the_most_severe_flag():
    from revision_pipeline.layer3_fusion import rules_only_confidence

    high = run_layer1("Credentials are released.", "Credentials are not released.", REASON)
    medium = run_layer1("within 30 days", "within 60 days", REASON)
    clean = run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON)
    failed = run_layer1("old text", "new text", {"change_reason": ""})

    assert rules_only_confidence(high) == 0.9
    assert rules_only_confidence(medium) == 0.7
    assert rules_only_confidence(clean) == 0.8
    assert rules_only_confidence(failed) == 1.0
    # A severe finding must not read as no more certain than a quiet one.
    assert rules_only_confidence(high) > rules_only_confidence(medium)


def test_rules_only_confidence_is_marked_as_such_in_the_result():
    layer1 = run_layer1("within 30 days", "within 60 days", REASON)
    result = run_layer3(layer1, {})
    assert result.confidence_source == "rules"
    assert result.confidence != 0.5


def test_layer2_confidence_is_marked_as_layer2():
    layer1 = run_layer1("The QMR shall sign.", "The QMR must sign.", REASON)
    result = run_layer3(layer1, {"verdict_probs": [0.1, 0.8, 0.1],
                                 "issue_probs": [0.0] * len(config.ISSUE_LABELS)})
    assert result.confidence_source == "layer2"


def test_layer3_falls_back_to_rules_with_no_layer2():
    layer1 = run_layer1("The QMR shall aprove it.", "The QMR shall approve it.", REASON)
    result = run_layer3(layer1, {})
    assert result.verdict == "approve"
    assert result.probabilities == {}
