"""Clause 6.3 in two tiers.

Tier 1 blocks: the API refuses the submission and Layer 1 hard-fails anything
that reached the database before the validation existed. Tier 2 does not
block: a real but vague reason is flagged for the reviewer and pushes an
otherwise-clean verdict to ``needs_revision``.

The two tiers share one function on purpose, so a revision cannot be accepted
by the API and then hard-failed by the rules for the same reason.
"""

import pytest

from revision_pipeline import config
from revision_pipeline.change_reason import (
    blocks_submission,
    classify_reason,
    content_words,
)
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import run_layer3

OLD = "The Accounting Staff-4 shall verify the request within five days."
NEW = "The Accounting Staff-4 shall verify the request within ten days."


def tier(reason, title=None):
    return classify_reason(reason, title)[0]


# -- tier 1: blocking ------------------------------------------

@pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
def test_an_absent_reason_is_missing(reason):
    assert tier(reason) == "missing"


@pytest.mark.parametrize("reason", [
    "update",            # one word
    "typo fix",          # two words, under the length floor
    "Updated.",          # a sentence, but nothing in it
    "as discussed",
])
def test_a_reason_under_the_floor_is_invalid(reason):
    assert tier(reason) == "invalid"


def test_three_words_are_needed_even_when_long_enough():
    # 19 characters, two words: passes the length floor, fails the word floor.
    assert len("reformatting stuff") >= 15
    assert tier("reformatting stuff") == "invalid"


@pytest.mark.parametrize("reason", [
    "...............",
    "!!!!!!!!!!!!!!!!!!",
    "- - - - - - - - - -",
])
def test_punctuation_alone_is_invalid(reason):
    assert tier(reason) == "invalid"


@pytest.mark.parametrize("reason", [
    "aaaaaaaaaaaaaaaaaaaa",
    "ab ab ab ab ab ab",
    "xxx xxx xxx xxx",
])
def test_repeated_characters_are_invalid(reason):
    assert tier(reason) == "invalid"


def test_a_reason_that_only_repeats_the_section_title_is_invalid():
    title = "3.0 POLICIES ON DISBURSEMENT OF FUNDS"
    assert tier(title, title) == "invalid"
    # and the comparison ignores case, spacing and trailing punctuation
    assert tier("  policies on disbursement of funds.  ",
                "POLICIES ON DISBURSEMENT OF FUNDS") == "invalid"


def test_the_title_check_does_not_catch_a_reason_that_merely_mentions_it():
    title = "3.0 POLICIES ON DISBURSEMENT OF FUNDS"
    reason = "The policies on disbursement of funds now name LandBank as the depository."
    assert tier(reason, title) == "ok"


@pytest.mark.parametrize("bad", ["", "update", "..............."])
def test_tier_one_blocks_submission(bad):
    assert blocks_submission(classify_reason(bad)[0])


def test_tier_one_carries_a_message_that_says_what_to_do():
    for bad in ["", "update", "...............", "reformatting stuff"]:
        message = classify_reason(bad)[1]
        assert message and message[-1] == "."
        assert "please" in message.lower()


# -- tier 1 in Layer 1 -----------------------------------------

@pytest.mark.parametrize("reason,detail", [
    ("", "No reason for the change was recorded."),
    ("...............", "The recorded reason does not describe the change."),
])
def test_layer1_hard_fails_on_both_halves_of_tier_one(reason, detail):
    result = run_layer1(OLD, NEW, {"change_reason": reason})
    assert result.failed
    fail = next(f for f in result.hard_fails if f["reason"] == "no_change_reason")
    assert fail["clause"] == "6.3"
    assert fail["detail"] == detail


def test_layer1_hard_fails_when_the_reason_repeats_the_title():
    title = "3.0 POLICIES ON DISBURSEMENT OF FUNDS"
    result = run_layer1(OLD, NEW, {"change_reason": title, "section_title": title})
    assert result.failed
    assert any(f["reason"] == "no_change_reason" for f in result.hard_fails)


# -- tier 2: weak, but never blocking --------------------------

@pytest.mark.parametrize("reason", [
    "Updated for compliance purposes",
    "Minor changes as discussed",
    "Revised as necessary and appropriate",
    "Corrections were needed here",
])
def test_a_vague_reason_is_weak(reason):
    assert tier(reason) == "weak"


@pytest.mark.parametrize("reason", [
    "Updated for compliance purposes",
    "Minor changes as discussed",
])
def test_tier_two_never_blocks_submission(reason):
    assert not blocks_submission(classify_reason(reason)[0])


def test_layer1_flags_a_weak_reason_without_failing():
    result = run_layer1(OLD, NEW, {"change_reason": "Updated for compliance purposes"})
    assert not result.failed
    assert [a["label"] for a in result.advisories] == ["vague_change_reason"]
    note = result.advisories[0]
    assert note["clause"] == "6.3"
    assert note["severity"] == "low"
    assert note["evidence"]


def test_a_weak_reason_raises_no_issue_label():
    """The advisory must stay outside the trained label space."""
    result = run_layer1(OLD, NEW, {"change_reason": "Updated for compliance purposes"})
    assert "vague_change_reason" not in {f["label"] for f in result.flags}


# -- tier 3: left alone ----------------------------------------

@pytest.mark.parametrize("reason", [
    "Bank account details changed after the branch transfer to LandBank.",
    "Aligned the retention period with Republic Act 10173.",
    "The approving role moved from the Dean to the Vice President in August 2026.",
    "Updated to match how the office actually works.",
])
def test_a_specific_reason_passes_clean(reason):
    assert tier(reason) == "ok"
    result = run_layer1(OLD, NEW, {"change_reason": reason})
    assert not result.failed
    assert result.advisories == []


def test_content_words_ignore_filler_and_boilerplate():
    # "updated", "as" and "discussed" all carry nothing about this change, so
    # only the noun survives - one content word, which is what makes the
    # reason weak. The list stays deliberately short: over-classifying words
    # as boilerplate would flag reasons that are actually fine.
    assert content_words("Updated the section as discussed") == ["section"]
    assert "landbank" in content_words("Changed the depository to LandBank")
    assert content_words("Updated as discussed") == []


# -- the soft tier reaches the verdict -------------------------

CLEAN = "The Cashier shall prepare the report and submit it to the Dean."
COSMETIC = "The Cashier shall prepare the report, and submit it to the Dean."
APPROVE = {"verdict_probs": [0.95, 0.03, 0.02],
           "issue_probs": [0.0] * len(config.ISSUE_LABELS)}


def test_a_vague_reason_turns_an_approve_into_needs_revision():
    """Same edit, different reason: the reason alone moves the verdict."""
    specific = run_layer3(
        run_layer1(CLEAN, COSMETIC, {"change_reason": "Reworded after the June 2026 training."}),
        dict(APPROVE),
    )
    assert specific.verdict == "approve"
    assert specific.advisories == []

    vague = run_layer3(
        run_layer1(CLEAN, COSMETIC, {"change_reason": "Minor changes as discussed"}),
        dict(APPROVE),
    )
    assert vague.verdict == "needs_revision"
    assert [o["rule"] for o in vague.overrides] == ["advisory"]
    assert [a["label"] for a in vague.advisories] == ["vague_change_reason"]


def test_the_soft_tier_never_pushes_a_verdict_the_other_way():
    """It can only tighten. A reject stays a reject; it never becomes approve."""
    result = run_layer3(
        run_layer1(CLEAN, COSMETIC, {"change_reason": "Minor changes as discussed"}),
        {"verdict_probs": [0.02, 0.03, 0.95],
         "issue_probs": APPROVE["issue_probs"]},
    )
    assert result.verdict == "reject"
    assert result.advisories  # still reported, just not acted on


def test_advisories_survive_a_hard_fail_path():
    """A hard fail short-circuits the verdict but must not swallow the notes."""
    result = run_layer3(
        run_layer1(CLEAN, "", {"change_reason": "Minor changes as discussed"}),
        dict(APPROVE),
    )
    assert result.verdict == "reject"
    assert [a["label"] for a in result.advisories] == ["vague_change_reason"]
