"""Tests for Layer 4: the note written from layer4_wording.yaml.

What holds for every note: no verdict words; no ".." or " ."; ISO wording
as relevance, never judgement; every slot filled; prose paragraphs only,
as many as the tier allows; the same inputs and rotation history give the
same note; and rotation moves away from wording already used.
"""

import re

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import FusionResult, run_layer3
from revision_pipeline.layer4_explain import (
    NOTE_HEADINGS, REVIEWER, SUBMITTER, TIERS, _Change,
    clause_for, compose_note, compose_proposal_note, explain, is_note,
    not_assessed_message, without_legacy_verdict, wording,
)

REASON = {"change_reason": "Updated after the August 2026 management review."}

POLICIES = (
    "3.1 Any records which may contain personal information shall be handled "
    "in accordance with Republic Act 10173.\n"
    "3.2 Accounts Receivable should be collected in a timely manner.\n"
    "3.3 Accounts outstanding for more than 365 days are considered past due.\n"
    "3.4 Credentials will not be released if fees are unpaid."
)

VERDICT_WORDS = re.compile(
    r"\b(approve[ds]?|approval|reject(?:ed|s)?|needs[ _]revision|verdict|"
    r"confidence|turned down|ready to submit|you can still submit)\b",
    re.IGNORECASE,
)


def agreeing_model(layer1):
    """Layer 2 output that agrees with every rule flag."""
    flagged = {f["label"] for f in layer1.flags}
    return {"verdict_probs": [0.1, 0.2, 0.7],
            "issue_probs": [0.99 if label in flagged else 0.01 for label in config.ISSUE_LABELS]}


def model_issue(label, confidence=0.95):
    return {"label": label, "source": "model", "confidence": confidence,
            "severity": config.SEVERITY[label], "clause": config.ISSUE_CLAUSE[label],
            "evidence": ""}


def compose(old, new, *, verdict=None, issues=None, audience=SUBMITTER, reason=REASON,
            section="3.0 POLICIES", history=None, adjacent=None, key="k", **context):
    # Layer 1 sees the retrieved texts, as in the pipeline; Layer 4 also
    # sees their labels.
    related = context.get("related_sections") or []
    layer1 = run_layer1(old, new, reason, related_sections=[text for _, text in related])
    fusion = run_layer3(layer1, agreeing_model(layer1))
    if verdict is not None or issues is not None:
        fusion = FusionResult(verdict=verdict or fusion.verdict, confidence=0.9,
                              issues=fusion.issues if issues is None else issues,
                              advisories=fusion.advisories)
    return compose_note(fusion, layer1, section_label=section, audience=audience,
                        old_text=old, new_text=new, change_reason=reason["change_reason"],
                        history=history, adjacent_plans=adjacent, content_key=key, **context)


# One edit per tier, as (tier, kwargs for compose).
TIER_CASES = {
    "trivial": dict(old=POLICIES, new=POLICIES.replace("timely manner", "timely manner,")),
    "plain": dict(old=POLICIES, new=POLICIES.replace("Accounts Receivable should",
                                                     "All Accounts Receivable should"),
                  verdict="approve", issues=[]),
    "unclear": dict(old=POLICIES, new=POLICIES.replace("Accounts Receivable should",
                                                       "All Accounts Receivable should"),
                    verdict="needs_revision", issues=[]),
    "minor": dict(old=POLICIES, new=POLICIES.replace("in a timely manner", "in a timly mannerz"),
                  verdict="needs_revision", issues=[]),
    "tentative": dict(old=POLICIES,
                      new=POLICIES + "\n3.5 The Cashier keeps a copy of each receipt for the files.",
                      verdict="reject", issues=[model_issue("out_of_scope_content")]),
    "notable": dict(old=POLICIES, new=POLICIES.replace("shall be handled", "may be handled"),
                    verdict="needs_revision"),
    "serious": dict(old=POLICIES, new=POLICIES.replace("will not be released", "will be released"),
                    verdict="reject"),
    "blocking": dict(old=POLICIES, new=POLICIES.replace("365", "180"),
                     reason={"change_reason": ""}),
}


def all_notes():
    for tier, case in TIER_CASES.items():
        for audience in (SUBMITTER, REVIEWER):
            yield tier, audience, *compose(**case, audience=audience)


NOTES = list(all_notes())
IDS = [f"{t}-{a}" for t, a, _, _ in NOTES]


# -- the tier cases really are each tier ----------------------------------------

@pytest.mark.parametrize("tier", TIERS)
def test_each_tier_case_reaches_its_tier(tier):
    _, choices = compose(**TIER_CASES[tier])
    assert choices["tier"] == tier


# -- what every note must satisfy ----------------------------------------------------

@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_no_note_states_a_verdict(tier, audience, note, choices):
    assert not VERDICT_WORDS.search(note), VERDICT_WORDS.search(note)


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_no_double_stop_or_space_before_a_stop(tier, audience, note, choices):
    assert ".." not in note.replace("…", "")
    assert " ." not in note


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_every_slot_is_filled(tier, audience, note, choices):
    assert "{" not in note and "}" not in note
    assert "“”" not in note
    assert choices["unfilled"] == [], choices["unfilled"]


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_prose_paragraphs_only(tier, audience, note, choices):
    for paragraph in note.split("\n\n"):
        assert paragraph and "\n" not in paragraph
        assert not paragraph.startswith(("- ", "  "))
        assert paragraph.strip() not in NOTE_HEADINGS


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_paragraph_count_is_within_the_tier(tier, audience, note, choices):
    low, high = wording()["selection"]["length"][tier]
    assert low <= len(note.split("\n\n")) <= high


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_the_reader_is_never_addressed_as_the_drafter(tier, audience, note, choices):
    if audience == REVIEWER:
        assert not re.search(r"\byou've\b|\byour reason\b|\byou gave\b", note, re.I)


# -- ISO: relevance, never judgement ---------------------------------------------------

def test_iso_sentences_speak_of_relevance_only():
    iso = wording()["iso"]
    for template in iso["relevance_first"] + iso["relevance_again"]:
        assert not re.search(r"violat|breach|non-?conform|fail", template, re.I)
    for paraphrases in iso["asks_that"].values():
        for text in paraphrases:
            assert not re.search(r"violat|breach|shall ", text, re.I)


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_iso_is_mentioned_at_most_twice(tier, audience, note, choices):
    assert len(re.findall(r"clause \d", note)) <= 2


def test_the_clause_per_label_matches_the_stored_clause():
    concern_clause = wording()["iso"]["concern_clause"]
    for label, clause in config.ISSUE_CLAUSE.items():
        assert str(concern_clause[label]) == clause
    assert clause_for("adds_requirement") == "6.3"
    for label in ("unknown_word", "inconsistent_terms", "unfinished_sentence"):
        assert clause_for(label) == "7.5.3"


def test_iso_is_not_mentioned_for_a_quiet_or_spelling_only_note():
    note, choices = compose(**TIER_CASES["minor"])
    assert "clause" not in note


# -- determinism and rotation --------------------------------------------------------------

@pytest.mark.parametrize("tier", TIERS)
def test_same_inputs_and_history_give_the_same_note(tier):
    first = compose(**TIER_CASES[tier])
    again = compose(**TIER_CASES[tier])
    assert first == again


def test_rotation_moves_away_from_wording_already_used():
    case = TIER_CASES["serious"]
    first_note, first = compose(**case)
    second_note, second = compose(**case, history=[first])
    assert second_note != first_note
    pool = next(p for p in first["pools"] if p.startswith("openings."))
    assert second["pools"][pool] != first["pools"][pool]


def test_openings_are_not_reused_in_a_proposal_while_unused_ones_remain():
    case = TIER_CASES["serious"]
    pool = f"openings.drafter.serious"
    size = len(wording()["openings"]["drafter"]["serious"])
    history, used = [], []
    for n in range(size):
        _, choices = compose(**case, history=list(reversed(history)), key=f"s{n}")
        used += choices["pools"][pool]
        history.append(choices)
    assert sorted(used) == list(range(size))


def test_neighbouring_sections_do_not_share_a_plan():
    case = TIER_CASES["serious"]
    _, first = compose(**case)
    _, second = compose(**case, adjacent=[first["plan"]], key="other")
    assert second["plan"] != first["plan"]


def test_the_choices_record_tier_plan_and_pools():
    _, choices = compose(**TIER_CASES["notable"])
    assert choices["tier"] == "notable"
    assert choices["plan"] in {p["id"] for p in wording()["selection"]["plans"]["notable"]}
    assert choices["pools"] and all(isinstance(v, list) for v in choices["pools"].values())


# -- the wording file itself ---------------------------------------------------------------

def test_the_file_never_uses_a_verdict_word():
    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for key, value in node.items():
                if key not in ("meta", "slots", "selection"):
                    yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
    for text in strings(wording()):
        assert not VERDICT_WORDS.search(text), text


def test_voice_specific_wording_is_marked_in_the_file():
    """Checks and limit lead-ins are split by voice, and the drafter-only
    change variant sits in its own list, so the reader never gets them."""
    w = wording()
    for label, words in w["concerns"].items():
        assert set(words["check"]) == {"drafter", "reader"}, label
    assert set(w["limits"]["lead_in"]) == {"drafter", "reader"}
    assert w["change"]["added_sentence"]["drafter_only"]
    for text in w["change"]["added_sentence"]["variants"]:
        assert not re.search(r"\byou", text, re.I)


@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_no_words_are_quoted_twice(tier, audience, note, choices):
    quotes = re.findall(r"“([^”]{4,})”", note)
    assert len(quotes) == len(set(quotes)), quotes


@pytest.mark.parametrize("tier", TIERS)
def test_every_tier_has_plans_openings_and_a_length(tier):
    w = wording()
    assert w["selection"]["plans"][tier]
    assert w["selection"]["length"][tier]
    assert w["openings"]["drafter"][tier] and w["openings"]["reader"][tier]


# -- quoting ------------------------------------------------------------------------------------

def test_an_item_number_is_never_cut_when_quoted():
    old = "1.1 To provide guidelines and procedures of accounting services."
    new = "1.1 provide guidelines and procedures of accounting services."
    hunk = _Change(old, new).hunks[0]
    assert hunk["old_ctx"].startswith("1.1 To")
    assert hunk["new_ctx"].startswith("1.1 provide")


def test_both_quotes_carry_the_same_context():
    old = "The Summary shows the said the accountability will be charged."
    new = "The Summary shows the said accountability will be charged."
    hunk = _Change(old, new).hunks[0]
    assert hunk["old_ctx"] == "the said the accountability will"
    assert hunk["new_ctx"] == "the said accountability will"


# -- context passed only to Layer 4 -------------------------------------------------------------

def test_a_conflict_is_named_with_the_section_that_still_states_it():
    old = POLICIES
    new = POLICIES.replace("365 days", "180 days")
    related = [("4.5 Accounts Receivable from Other Debtors",
                "| Accountant | 2. Sort those accounts with age of over 365 days. |")]
    note, _ = compose(old, new, verdict="reject", related_sections=related)
    assert "4.5 Accounts Receivable from Other Debtors" in note


def test_a_consistent_change_in_the_same_proposal_is_said_to_match():
    old = POLICIES
    new = POLICIES.replace("365 days", "180 days")
    label = "4.5 Accounts Receivable from Other Debtors"
    related = [(label, "| Accountant | 2. Sort those accounts with age of over 365 days. |")]
    proposal = [{"label": label, "old_text": related[0][1],
                 "new_text": related[0][1].replace("365", "180")}]
    note, _ = compose(old, new, verdict="reject", related_sections=related,
                      proposal_sections=proposal)
    assert label in note and "still says" not in note


# -- the proposal note --------------------------------------------------------------------------

def _record(label, old, new, tier, flags=(), issues=(), related=()):
    return {"label": label, "old_text": old, "new_text": new, "tier": tier,
            "issues": list(issues), "advisories": [], "flags": list(flags),
            "related": list(related)}


def test_the_proposal_note_names_the_sections_and_a_consistent_figure():
    flag_a = {"label": "numeric_changed", "from_values": ["1 year", "365 days"],
              "to_values": ["180 days", "6 months"]}
    flag_b = {"label": "numeric_changed", "from_values": ["1 year"], "to_values": ["6 months"]}
    sections = [
        _record("3.0 POLICIES", "over 1 year", "over 6 months", "serious", [flag_a],
                [{"label": "numeric_changed"}]),
        _record("4.5 Other Debtors", "aging over 1 year", "aging over 6 months", "notable",
                [flag_b], [{"label": "numeric_changed"}]),
    ]
    for audience in (SUBMITTER, REVIEWER):
        note, choices = compose_proposal_note(sections, audience=audience, content_key="p")
        assert "3.0 POLICIES" in note and "4.5 Other Debtors" in note
        assert "“1 year”" in note and "“6 months”" in note
        assert not VERDICT_WORDS.search(note) and "{" not in note
        assert 2 <= len(note.split("\n\n")) <= 3


def test_the_proposal_note_is_deterministic():
    sections = [_record("2.0 SCOPE", "a", "a,", "trivial"),
                _record("4.5 Other", "b c", "b", "serious", issues=[{"label": "requirement_removed"}])]
    assert compose_proposal_note(sections, content_key="x") == \
        compose_proposal_note(sections, content_key="x")


# -- older notes, and the forms message ---------------------------------------------------------

def test_forms_section_message_says_not_checked():
    message = not_assessed_message("5.0 LIST OF FORMS")
    assert message.startswith("Not checked: 5.0 LIST OF FORMS")
    assert not VERDICT_WORDS.search(message)


def test_a_heading_note_is_recognised_as_one():
    assert is_note("What you changed\nA small edit.")
    assert not is_note("This edit changes what 3.0 POLICIES asks of people.")


def test_a_legacy_paragraph_loses_its_verdict_sentences_only():
    old = ("This would likely be rejected as written. The word “not” was "
           "removed, inverting what this section requires. You can still "
           "submit - the reviewer decides, not this check.")
    assert without_legacy_verdict(old) == (
        "The word “not” was removed, inverting what this section requires.")


def test_explain_returns_the_note_alone():
    layer1 = run_layer1(POLICIES, POLICIES.replace("365", "180"), REASON)
    fusion = run_layer3(layer1, agreeing_model(layer1))
    note = explain(fusion, layer1, section_label="3.0 POLICIES", audience=SUBMITTER,
                   old_text=POLICIES, new_text=POLICIES.replace("365", "180"))
    assert isinstance(note, str) and note


# -- wording file v3 rules ----------------------------------------------------------------------

@pytest.mark.parametrize("tier, audience, note, choices", NOTES, ids=IDS)
def test_a_colon_transition_continues_in_lower_case(tier, audience, note, choices):
    for connector in wording()["transitions"]["second_concern"]:
        if connector.endswith(":"):
            for found in re.finditer(re.escape(connector) + r" (\S)", note):
                assert not found.group(1).isupper() or found.group(1) in "“", note


def test_the_item_is_not_repeated_after_a_quote_that_shows_it():
    old = "1.1 To provide guidelines and procedures of accounting services."
    new = "1.1 provide guidelines and procedures of accounting services."
    for audience in (SUBMITTER, REVIEWER):
        note, _ = compose(old, new, verdict="needs_revision", issues=[], audience=audience,
                          section="1.0 OBJECTIVE")
        assert "” at 1.1" not in note and "1.1, " not in note.split("“")[0]


def test_a_proposal_note_with_nothing_to_raise_still_has_two_paragraphs():
    sections = [_record("2.0 SCOPE", "a", "a,", "trivial")]
    for audience in (SUBMITTER, REVIEWER):
        note, _ = compose_proposal_note(sections, audience=audience, content_key="one")
        assert 2 <= len(note.split("\n\n")) <= 3


@pytest.mark.parametrize("audience", [SUBMITTER, REVIEWER])
def test_small_edits_are_explained_as_actions_with_their_location(audience):
    old = ("3.2 Any request for information shall be governed by Executive Order "
           "No. 02, series of 2016 or the Freedom of Information.")
    new = old.replace("Any request", "Request").replace("Information.", "Information EO.")
    for key in range(12):
        note, choices = compose(old, new, verdict="approve", issues=[],
                                audience=audience, key=str(key))
        assert "→" not in note, note
        assert "“Any” was removed" in note, note
        assert "“EO” was added" in note, note
        assert "3.2" in note, note
        assert not choices["unfilled"]


@pytest.mark.parametrize("audience", [SUBMITTER, REVIEWER])
def test_absent_findings_do_not_claim_unchanged_meaning_or_readiness(audience):
    # No detected issue is not proof that changing the scope is harmless.
    old = "3.2 Records are available to all employees."
    new = "3.2 Records are available to some employees."
    history = []
    for key in range(12):
        note, choices = compose(old, new, verdict="approve", issues=[],
                                audience=audience, history=history, key=str(key))
        assert re.search(r"check (?:did not|didn't|has not)|not flagged|not detected", note), note
        assert not re.search(r"untouched|all as they were|No .* changed\.|good to go|"
                             r"nothing else to flag|should be fine|nothing here changes", note, re.I), note
        history.insert(0, choices)


@pytest.mark.parametrize("audience", [SUBMITTER, REVIEWER])
def test_vague_reason_feedback_has_an_action_without_promising_clearance(audience):
    case = dict(TIER_CASES["plain"], reason={"change_reason": "Update the document."})
    history = []
    for key in range(8):
        note, choices = compose(**case, audience=audience, history=history, key=str(key))
        assert "prompted" in note, note
        assert re.search(r"[Ee]xplain|[Ss]tate|[Aa]sk .*explain", note), note
        assert not re.search(r"Once .*tidied|should be fine|nothing else to flag", note, re.I), note
        history.insert(0, choices)


def test_grouped_insertions_do_not_describe_unchanged_words_as_added():
    old = "3.2 The office keeps the records.\n3.3 Staff read the manual."
    new = "3.2 The central office also keeps the records.\n3.3 Staff read the current manual."
    note, _ = compose(old, new, verdict="approve", issues=[])
    assert "“central office also” was added" not in note, note
    assert "now reads" in note, note
    assert "“current” was added at 3.3" in note, note
