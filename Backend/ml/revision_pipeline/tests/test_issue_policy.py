"""How Layer 3 combines the rules' findings with the model's.

The union was the only thing tried until the folds were measured, and it cost
16 points of issue micro-F1. These pin the policy that replaced it, and one
property no aggregate score shows: a policy must never be able to silence a
label outright.
"""

import pytest

from revision_pipeline import config
from revision_pipeline.layer3_fusion import select_issue_labels

RULES_ONLY_BLIND = ("contradicts_manual", "out_of_scope_content")


def test_configured_policy_is_one_of_the_four():
    assert config.ISSUE_POLICY in ("model", "union", "rules_precise", "agree")


@pytest.mark.parametrize("label", RULES_ONLY_BLIND)
def test_the_policy_can_still_report_what_the_rules_never_see(label):
    """The reason for having a model at all.

    Layer 1 raises neither of these - a reordered step sequence and inserted
    foreign content are invisible to it - so a policy that needs the rules to
    agree reports them never. "agree" scored best on average and fails here.
    """
    assert select_issue_labels(set(), {label}) == {label}


def test_a_precise_rule_label_is_added_without_the_model():
    assert "modal_weakened" in select_issue_labels({"modal_weakened"}, set())


def test_an_imprecise_rule_label_alone_is_dropped():
    """requirement_removed did not clear the precision floor."""
    assert select_issue_labels({"requirement_removed"}, set()) == set()


def test_the_model_carries_a_label_the_rules_got_wrong():
    assert select_issue_labels({"requirement_removed"}, {"numeric_changed"}) == {
        "numeric_changed"
    }


def test_precise_labels_are_pinned_not_empty():
    """Without the pinned list, rules_precise silently degrades to model."""
    assert config.PRECISE_RULE_LABELS
    assert set(config.PRECISE_RULE_LABELS) <= set(config.ISSUE_LABELS)


def test_an_explicit_empty_list_still_means_none():
    """evaluate_folds.py passes its own measured set, including an empty one."""
    assert select_issue_labels({"modal_weakened"}, set(),
                               policy="rules_precise", precise_labels=[]) == set()


@pytest.mark.parametrize("policy, expected", [
    ("model", {"numeric_changed"}),
    ("union", {"numeric_changed", "requirement_removed"}),
    ("agree", set()),
])
def test_the_other_policies_still_behave_as_named(policy, expected):
    assert select_issue_labels(
        {"requirement_removed"}, {"numeric_changed"}, policy=policy
    ) == expected
