"""Tests for Layer 4: the assistive note.

What matters, and each has tests here: the note never states a verdict; it
is deterministic; it is grounded in what Layers 1 and 3 found and in the two
texts; firmness is carried by wording; the verdict decides emphasis only;
and the ISO clause file is complete, consistent with the stored clause, and
framed as relevance.
"""

import re

import pytest

from revision_pipeline import config
from revision_pipeline.layer1_rules import run_layer1
from revision_pipeline.layer3_fusion import FusionResult, run_layer3
from revision_pipeline.layer4_explain import (
    CANNOT_TELL, CHANGED, CHANGED_YOU, LOOK_AT, LOOKS_FINE, MAX_CONCERNS,
    NOTE_HEADINGS, REVIEWER, SUBMITTER, _ASK, _CHECK, _MODEL_ONLY, _WHY,
    _iso, clause_for, explain, is_note, not_assessed_message,
    without_legacy_verdict,
)

REASON = {"change_reason": "Updated after the August 2026 management review."}

POLICIES = (
    "3.1 Any records which may contain personal information shall be handled "
    "in accordance with Republic Act 10173.\n"
    "3.2 Accounts Receivable should be collected in a timely manner.\n"
    "3.3 Accounts outstanding for more than 365 days are considered past due.\n"
    "3.4 Credentials will not be released if fees are unpaid."
)

TABLE = (
    "| Responsibility | Activity |\n"
    "| --- | --- |\n"
    "| Accountant | 1. Generates the Schedule of Accounts Receivable. |\n"
    "| | 2. Forwards the demand letters to the University President for signature. |\n"
    "| University President | 3. Signs the Demand Letters. |\n"
    "| Records Management Staff | 4. Sends the Demand Letters to the debtors. |"
)

VERDICT_WORDS = re.compile(
    r"\b(approve[ds]?|approval|reject(?:ed|s)?|needs[ _]revision|verdict|"
    r"confidence|turned down|ready to submit|you can still submit)\b",
    re.IGNORECASE,
)


def note_for(old, new, verdict=None, issues=None, audience=SUBMITTER,
             section="3.0 POLICIES", reason=REASON, advisories=None):
    """Layer 1 on the real texts; Layer 3's verdict and issues as given, or
    as the rules-only fusion produces them when not given."""
    layer1 = run_layer1(old, new, reason)
    fusion = run_layer3(layer1, agreeing_model(layer1))
    if verdict is not None or issues is not None:
        fusion = FusionResult(
            verdict=verdict or fusion.verdict,
            confidence=0.9,
            issues=fusion.issues if issues is None else issues,
            advisories=fusion.advisories if advisories is None else advisories,
        )
    return explain(fusion, layer1, section_label=section, audience=audience,
                   old_text=old, new_text=new), layer1, fusion


def agreeing_model(layer1):
    """Layer 2 output that agrees with every rule flag, as the real pipeline
    produces when the model sees the same change. Without it, Layer 3 runs
    rules-only and its issue policy keeps only the most precise labels."""
    flagged = {f["label"] for f in layer1.flags}
    return {
        "verdict_probs": [0.1, 0.2, 0.7],
        "issue_probs": [0.99 if label in flagged else 0.01
                        for label in config.ISSUE_LABELS],
    }


def fused_issues(old, new):
    layer1 = run_layer1(old, new, REASON)
    return run_layer3(layer1, agreeing_model(layer1)).issues


def parts(note):
    """The note's parts keyed by heading, in the documented text format."""
    out = {}
    for block in note.split("\n\n"):
        lines = block.split("\n")
        assert lines[0] in NOTE_HEADINGS, f"unknown heading: {lines[0]!r}"
        out[lines[0]] = lines[1:]
    return out


def model_issue(label, confidence=0.95):
    return {"label": label, "source": "model", "confidence": confidence,
            "severity": config.SEVERITY[label],
            "clause": config.ISSUE_CLAUSE[label], "evidence": ""}


# -- no verdict, ever --------------------------------------------------------

@pytest.mark.parametrize("verdict", config.VERDICTS)
@pytest.mark.parametrize("audience", [SUBMITTER, REVIEWER])
def test_no_note_states_a_verdict(verdict, audience):
    for old, new in [
        (POLICIES, POLICIES.replace("shall be handled", "may be handled")),
        (POLICIES, POLICIES.replace("365 days", "180 days")),
        (POLICIES, POLICIES.replace("timely manner", "timely manner,")),
        (POLICIES, POLICIES + "\n3.5 Receipts are issued for every payment."),
    ]:
        note, _, _ = note_for(old, new, verdict=verdict, audience=audience)
        assert not VERDICT_WORDS.search(note), note


def test_a_clean_change_with_an_unsettled_verdict_says_so_without_the_label():
    note, _, _ = note_for(POLICIES, POLICIES + "\n3.5 Receipts are issued.",
                          verdict="reject", issues=[])
    assert "less settled" in parts(note)[LOOK_AT][0]
    assert not VERDICT_WORDS.search(note)


def test_a_clean_change_with_no_concern_says_so_honestly():
    note, _, _ = note_for(POLICIES, POLICIES + "\n3.5 Receipts are issued.",
                          verdict="approve", issues=[])
    sections = parts(note)
    assert LOOK_AT not in sections
    assert sections[LOOKS_FINE][0] == "No specific concern passed its threshold."
    # ...and still describes the change.
    assert "Receipts are issued" in sections[CHANGED_YOU][0]


# -- format and determinism ------------------------------------------------

def test_the_same_change_always_produces_the_same_note():
    new = POLICIES.replace("shall be handled", "may be handled")
    assert note_for(POLICIES, new)[0] == note_for(POLICIES, new)[0]


def test_parts_come_in_a_fixed_order():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365 days", "180 days"))
    headings = [block.split("\n")[0] for block in note.split("\n\n")]
    order = [CHANGED_YOU, LOOK_AT, LOOKS_FINE, CANNOT_TELL]
    assert headings == [h for h in order if h in headings]


def test_the_drafter_and_the_reviewers_are_addressed_differently():
    new = POLICIES.replace("shall be handled", "may be handled")
    drafter = parts(note_for(POLICIES, new, audience=SUBMITTER)[0])
    reviewer = parts(note_for(POLICIES, new, audience=REVIEWER)[0])
    assert CHANGED_YOU in drafter and CHANGED in reviewer
    assert any(l.strip().startswith("Expect to be asked") for l in drafter[LOOK_AT])
    assert any(l.strip().startswith("Worth asking the drafting office")
               for l in reviewer[LOOK_AT])
    # The findings themselves are the same.
    assert drafter[LOOK_AT][0] == reviewer[LOOK_AT][0]


def test_is_note_recognises_the_format():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365", "180"))
    assert is_note(note)
    assert not is_note("This revision looks acceptable. The change is cosmetic.")


# -- what changed ------------------------------------------------------------

def test_a_small_edit_is_quoted_word_for_word_and_placed():
    note, _, _ = note_for(POLICIES, POLICIES.replace("shall be handled", "may be handled"))
    line = parts(note)[CHANGED_YOU][0]
    assert "at 3.1" in line
    assert "“personal information shall be handled”" in line
    assert "“personal information may be handled”" in line


def test_nearby_edits_on_one_line_are_quoted_as_one():
    new = POLICIES.replace("more than 365 days", "more than 180 days, or 6 months,")
    line = parts(note_for(POLICIES, new)[0])[CHANGED_YOU][0]
    assert line.count("→") == 1, line


def test_an_added_sentence_is_quoted_in_full():
    new = POLICIES.replace(
        "considered past due.",
        "considered past due. The age of an account is counted from the date it was recorded.")
    line = parts(note_for(POLICIES, new)[0])[CHANGED_YOU][0]
    assert line.startswith("An added sentence in 3.0 POLICIES, at 3.3")
    assert "“The age of an account is counted from the date it was recorded.”" in line
    assert not line.endswith(".”.")


def test_removed_table_rows_are_quoted_as_rows_not_pipes():
    new = "\n".join(l for l in TABLE.splitlines() if "2. Forwards" not in l)
    note, _, _ = note_for(TABLE, new, section="4.5 Other Debtors")
    line = parts(note)[CHANGED_YOU][0]
    assert "“2. Forwards the demand letters" in line
    assert "| |" not in note


def test_a_large_change_gives_its_size_rather_than_quoting():
    new = "3.1 Records are handled under the Data Privacy Act."
    line = parts(note_for(POLICIES, new)[0])[CHANGED_YOU][0]
    assert line.startswith("A large change")
    assert "words removed" in line


def test_a_punctuation_fix_is_named_and_kept_short():
    note, _, _ = note_for(POLICIES, POLICIES.replace("timely manner.", "timely manner;"))
    sections = parts(note)
    assert sections[CHANGED_YOU][0].startswith("A punctuation fix")
    assert CANNOT_TELL not in sections
    assert any("spelling, punctuation or layout only" in l for l in sections[LOOKS_FINE])


# -- concerns: grounded, placed, firm through wording ----------------------

def test_a_rule_finding_is_stated_plainly_with_where_and_why():
    note, _, _ = note_for(POLICIES, POLICIES.replace("shall be handled", "may be handled"))
    lead = parts(note)[LOOK_AT][0]
    assert lead.startswith("- At 3.1, “shall” became “may”")
    assert _WHY["modal_weakened"] in lead
    assert "suspect" not in lead


def test_a_figure_names_both_values():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365 days", "180 days"))
    assert "“365 days” became “180 days”" in parts(note)[LOOK_AT][0]


def test_a_removed_negation_is_named():
    note, _, _ = note_for(POLICIES, POLICIES.replace("will not be released",
                                                       "will be released"))
    assert "At 3.4, “not” was removed" in note


def test_a_reassignment_names_who_left_and_who_arrived():
    new = TABLE.replace("| Records Management Staff | 4.", "| Accounting Staff-4 | 4.")
    note, _, fusion = note_for(TABLE, new, section="4.5 Other Debtors")
    assert "responsibility_changed" in {i["label"] for i in fusion.issues}
    assert ("Records Management Staff is no longer named; Accounting Staff-4 is "
            "named instead") in note


def test_a_model_only_finding_is_attributed_and_hedged_by_confidence():
    for confidence, phrase in [(0.95, "strongly suspects"), (0.75, "suspects"),
                               (0.55, "sees a possibility")]:
        note, _, _ = note_for(
            POLICIES, POLICIES + "\n3.5 Receipts are issued for every payment.",
            verdict="needs_revision",
            issues=[model_issue("out_of_scope_content", confidence)])
        assert f"The check's model {phrase}" in parts(note)[LOOK_AT][0]


def test_a_model_finding_the_rules_contradict_says_it_may_be_a_false_lead():
    note, _, _ = note_for(POLICIES, POLICIES.replace("timely manner", "prompt manner"),
                          verdict="reject", issues=[model_issue("negation_changed")])
    item = parts(note)[LOOK_AT]
    assert "no “not”, “no” or “never” was added or removed" in item[0]
    assert "may be a false lead" in item[0]
    # A likely false lead gets no question, no checklist and no can't-tell line.
    assert not any("Expect to be asked" in l for l in item)
    assert CANNOT_TELL not in parts(note) or not any(
        "law or policy" in l for l in parts(note)[CANNOT_TELL])


def test_corroborated_concerns_come_before_doubtful_ones():
    new = POLICIES.replace("365 days", "180 days")
    note, _, fusion = note_for(POLICIES, new, verdict="reject",
                               issues=[model_issue("negation_changed")]
                               + fused_issues(POLICIES, new))
    items = [l for l in parts(note)[LOOK_AT] if l.startswith("- ")]
    assert "a figure changed" in items[0]
    assert "false lead" in items[-1]


# -- the verdict decides emphasis only -------------------------------------

def two_concerns():
    new = POLICIES.replace("shall be handled", "may be handled").replace("365", "180")
    return new, fused_issues(POLICIES, new)


def test_when_the_change_needs_work_every_concern_gets_its_question():
    new, issues = two_concerns()
    assert len(issues) >= 2
    note, _, _ = note_for(POLICIES, new, verdict="reject", issues=issues)
    asks = [l for l in parts(note)[LOOK_AT] if "Expect to be asked" in l]
    assert len(asks) == len(issues)


def test_otherwise_only_the_first_concern_does():
    new, issues = two_concerns()
    note, _, _ = note_for(POLICIES, new, verdict="approve", issues=issues)
    asks = [l for l in parts(note)[LOOK_AT] if "Expect to be asked" in l]
    assert len(asks) == 1


def test_leftover_concerns_are_named_not_dropped():
    issues = [model_issue(label) for label in config.ISSUE_LABELS[:MAX_CONCERNS + 2]]
    note, _, _ = note_for(POLICIES, POLICIES + "\n3.5 Extra.", verdict="reject",
                          issues=issues)
    assert any(l.startswith("- Also noted:") for l in parts(note)[LOOK_AT])


# -- ISO clauses: relevance, never violation -------------------------------

def test_a_clause_is_given_in_full_once_then_by_number():
    new, issues = two_concerns()
    note, _, _ = note_for(POLICIES, new, verdict="reject", issues=issues)
    assert note.count("clause 7.5.3, which asks that") == 1
    assert "This also touches clause 7.5.3." in note


def test_clauses_are_framed_as_relevance():
    new, issues = two_concerns()
    note, _, _ = note_for(POLICIES, new, verdict="reject", issues=issues)
    assert "This touches ISO 9001:2015 clause" in note
    assert not re.search(r"violat|breach|non-?conform|fails? (the )?clause", note, re.I)


def test_the_clause_file_covers_every_issue_and_matches_the_stored_clause():
    """The note's clause and the one stamped on each stored issue must agree."""
    for label in config.ISSUE_LABELS:
        assert clause_for(label) == config.ISSUE_CLAUSE[label], label


def test_every_clause_used_has_a_paraphrase_that_completes_the_sentence():
    data = _iso()
    for label, clause in data["concerns"].items():
        asks = data["clauses"][clause]["asks_that"]
        assert asks and asks[0].islower() and not asks.endswith("."), (label, asks)


def test_the_clause_file_never_speaks_of_violation():
    text = str(_iso())
    assert not re.search(r"violat|breach|shall ", text, re.I)


def test_a_missing_reason_is_named_with_clause_6_3():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365", "180"),
                          reason={"change_reason": ""})
    look = parts(note)[LOOK_AT]
    assert look[0] == ("- No reason for the change was recorded. The reason is the "
                       "record that the change was planned, and the first thing a "
                       "reviewer or auditor reads.")
    assert "clause 6.3" in look[1]


# -- every label renders ----------------------------------------------------

@pytest.mark.parametrize("label", config.ISSUE_LABELS)
def test_every_label_has_its_wording(label):
    for table in (_WHY, _ASK, _CHECK, _MODEL_ONLY):
        assert table.get(label), label


@pytest.mark.parametrize("label", config.ISSUE_LABELS)
@pytest.mark.parametrize("source", ["rule", "model"])
def test_every_label_renders_without_template_debris(label, source):
    issue = model_issue(label)
    issue.update({"source": source, "evidence": "" if source == "model" else "the word",
                  "ratio": 0.55})
    note, _, _ = note_for(POLICIES, POLICIES.replace("365", "180"),
                          verdict="reject", issues=[issue])
    assert "{" not in note and "}" not in note
    assert "  ." not in note and ".." not in note.replace("…", "")
    assert "This touches" in note or "This also touches" in note


# -- what looks fine only repeats what the rules counted -------------------

def test_what_looks_fine_never_contradicts_a_concern():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365 days", "180 days"))
    fine = " ".join(parts(note).get(LOOKS_FINE, []))
    assert "figure" not in fine


def test_an_addition_is_acknowledged_as_removing_nothing():
    note, _, _ = note_for(POLICIES, POLICIES + "\n3.5 Receipts are issued.",
                          verdict="approve", issues=[])
    assert "Nothing was removed." in parts(note)[LOOKS_FINE]


# -- forms, and notes written before this format ---------------------------

def test_forms_section_message_says_not_checked():
    message = not_assessed_message("5.0 LIST OF FORMS")
    assert message.startswith("Not checked: 5.0 LIST OF FORMS")
    assert not VERDICT_WORDS.search(message)


def test_a_legacy_paragraph_loses_its_verdict_sentences_only():
    old = ("This would likely be rejected as written. The word “not” was "
           "removed, inverting what this section requires. You can still "
           "submit - the reviewer decides, not this check.")
    assert without_legacy_verdict(old) == (
        "The word “not” was removed, inverting what this section requires.")


def test_a_legacy_approve_with_concerns_opening_is_removed():
    old = ("No blocking problems were found, but two points are worth checking "
           "before you submit. A figure was changed. You can go ahead and submit.")
    assert without_legacy_verdict(old) == "A figure was changed."


def test_a_note_in_the_current_format_passes_through_untouched():
    note, _, _ = note_for(POLICIES, POLICIES.replace("365", "180"))
    assert without_legacy_verdict(note) == note
