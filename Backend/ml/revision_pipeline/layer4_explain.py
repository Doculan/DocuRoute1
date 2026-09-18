"""Layer 4 - writing the explanation.

Templates, not a generative model. Three properties matter more than fluency:

* **Deterministic.** The same revision produces the same words every time,
  seeded by the revision id. An assessment that reworded itself between two
  page loads would be worthless as a record.
* **Grounded.** Only issues, words, sections and clauses present in the Layer 3
  output are ever mentioned. Nothing is invented.
* **Hedged honestly.** A rule-sourced issue is a detected fact - the words
  really did change - so it is stated plainly, with no hedge. Only what the
  model alone believes is hedged, as "clearly", "likely" or "may".

The admin's decision is final; this is advisory text.
"""

from __future__ import annotations

import random
import re

from . import config

_WS_RE = re.compile(r"\s+")

# -- vocabulary ------------------------------------------------

_OPENINGS = {
    "approve": [
        "This revision looks acceptable.",
        "No blocking problems were found in this revision.",
        "This change appears safe to approve.",
    ],
    "needs_revision": [
        "This revision needs changes before it can be approved.",
        "This revision should be sent back for adjustment.",
        "Some points need addressing before this revision is approved.",
    ],
    "reject": [
        "This revision should not be approved as written.",
        "This revision changes the requirement and should be rejected.",
        "This revision cannot be accepted in its current form.",
    ],
}

# An approve that still carries concerns needs an opening that admits them.
# "No blocking problems were found in this revision." followed immediately by a
# medium-severity concern reads as though the two came from different systems,
# and the reader believes the first sentence - which is the one that tells them
# to stop reading. {points} is filled with "one point is" or "three points are".
_APPROVE_WITH_CONCERNS = [
    "No blocking problems were found, but {points} worth checking.",
    "This revision looks broadly acceptable, though {points} worth a look.",
    "Nothing here blocks approval, but {points} worth confirming first.",
]

_CONNECTORS = ["In addition,", "Also,", "Further,"]
_HIGH_CONNECTORS = ["More importantly,", "More seriously,", "Of greater concern,"]

# At least three phrasings per label. The first of each is evidence-free:
# a model-only issue has no quoted words to point at, and without a fillable
# option the renderer fell back to a template with an empty slot, producing
# "is likely stated differently elsewhere" with nothing in front of it.
#
# Those evidence-free variants must still be actionable. "A term this section
# relies on likely no longer appears" is true, unarguable and useless: it tells
# a reviewer neither what kind of term nor where to look, and the model is the
# only source precisely when there is nothing to quote. Each one therefore
# names the category of thing that may have changed and points at where to
# check it, so an unevidenced finding is still a lead rather than a shrug.
_PHRASINGS = {
    "excessive_deletion": [
        "a large part of section {section} was {hedge} removed, so compare the "
        "two versions and confirm nothing required went with it",
        "section {section} {hedge} lost {ratio} of its wording",
        "{portion} of section {section} was {hedge} deleted ({ratio} of the wording)",
    ],
    "key_term_deleted": [
        "a term this section depends on {hedge} no longer appears, so check "
        "the old text for a defined term, form name or legal reference that "
        "is missing from the new one",
        "the term {terms} {hedge} no longer appears",
        "it {hedge} drops {terms} from section {section}",
        "{terms} was {hedge} removed from section {section}",
    ],
    "modal_weakened": [
        "an obligation {hedge} became optional, so look for shall, must or "
        "required giving way to may, should or can",
        "{terms}, so an obligation {hedge} became a permission",
        "{terms}, which {hedge} turns a requirement into a permission",
    ],
    "negation_changed": [
        "a negation {hedge} changed, so look for not, no or never added or "
        "dropped, which reverses what this section requires",
        "the word {terms} was {hedge} {action}, which reverses the meaning",
        "the word {terms} was {hedge} {action}, inverting what this section requires",
        "the sense of this section was {hedge} inverted when {terms} was {action}",
    ],
    "numeric_changed": [
        "a figure in section {section} {hedge} changed, so check each amount, "
        "deadline, percentage and count against the old version",
        "a figure was {hedge} changed from {from_text} to {to_text}",
        "the value {hedge} changed from {from_text} to {to_text}",
        "a figure was {hedge} {direction}: {terms}",
    ],
    "responsibility_changed": [
        "the party responsible {hedge} changed, so check the role named in "
        "section {section} against the one it replaced",
        "the assigned role {hedge} changed ({terms}), which ISO clause {clause} covers",
        "responsibility {hedge} moved to a different party ({terms})",
        "{terms} is {hedge} no longer the party named for this step",
    ],
    "requirement_removed": [
        "a required step was {hedge} removed from section {section}, so look "
        "for a sentence in the old text with no counterpart in the new",
        "the required step “{old}” was {hedge} removed",
        "the revision {hedge} drops a required step: “{old}”",
        "the obligation “{old}” is {hedge} no longer stated",
    ],
    "non_equivalent_term": [
        "a term was {hedge} swapped for one that does not mean the same thing, "
        "so compare the changed wording against how this manual uses it "
        "elsewhere",
        "a term was {hedge} swapped for one that does not mean the same thing ({terms})",
        "{terms}, and those are {hedge} not equivalent in this manual",
        "the substitution {terms} {hedge} changes what is being asked",
    ],
    "contradicts_manual": [
        "it {hedge} conflicts with another section of this document, so check "
        "whether the same value, deadline or role is stated elsewhere",
        "it {hedge} conflicts with another section of the same document ({terms})",
        "{terms} is {hedge} stated differently elsewhere in this document",
        "another section {hedge} still carries the previous value ({terms})",
    ],
    "out_of_scope_content": [
        "wording was {hedge} added that does not belong to section {section}, "
        "so check whether the new text strays into what another section "
        "covers",
        # Every phrasing for this label renders without evidence - the model
        # reports it with nothing to quote - so all three have to be useful.
        "content was {hedge} added that is outside the scope of section "
        "{section}, so read the new text for anything the section did not "
        "cover before",
        "the addition {hedge} sits outside what section {section} covers, so "
        "check whether it belongs in a different section of the manual",
    ],
}

# Only worth saying when it tells the reader something the issue sentences did
# not. After "the required step X was removed", adding "the change alters the
# content of the section" is filler, so "substantive" has no sentence at all.
_CHANGE_TYPE_SENTENCE = {
    "cosmetic": "The change is cosmetic: formatting or spelling only.",
    "terminology_non_equivalent": (
        "The change substitutes terms that are not equivalent in this manual."
    ),
}


def _change_type_sentence(layer1_result) -> str:
    """The change-type line, naming the terms where there are any."""
    change_type = layer1_result.change_type
    if change_type == "terminology_equivalent":
        swaps = getattr(layer1_result, "equivalent_swaps", None) or []
        if swaps:
            named = ", ".join(f'“{a}” with “{b}”' for a, b in swaps[:3])
            return (
                f"The change only replaces {named}, which mean the same thing "
                "here, so the requirement is unchanged."
            )
        return (
            "The change only replaces terms with equivalent ones, so the "
            "requirement is unchanged."
        )
    return _CHANGE_TYPE_SENTENCE.get(change_type, "")


_CLOSINGS = {
    "approve": "Please confirm before approving.",
    "needs_revision": "Please check these points before approving.",
    "reject": "Please check these points before deciding.",
}

MAX_SENTENCES = 6


# -- helpers ---------------------------------------------------

def _hedge(issue: dict) -> str:
    """The hedge word, or empty for anything a rule detected.

    A rule does not believe a number changed, it found the two numbers. Hedging
    that reads as uncertainty the system does not have. Only a model-only issue
    is a judgement call, and only that gets hedged.
    """
    if issue.get("source") in ("rule", "both"):
        return ""
    confidence = float(issue.get("confidence", 0.5))
    if confidence > 0.85:
        return "clearly"
    if confidence > 0.65:
        return "likely"
    return "may"


def _portion_word(ratio) -> str:
    if not isinstance(ratio, (int, float)):
        return ""
    if ratio >= 0.6:
        return "Most"
    if ratio >= 0.35:
        return "Half"
    return "Part"


def _section_slot(section_label: str) -> str:
    label = (section_label or "").strip()
    if not label:
        return "this section"
    first = label.split(None, 1)[0]
    return first if first.replace(".", "").isdigit() else label


_NUMBER_WORDS = ("", "one", "two", "three", "four", "five", "six")


def _number_word(count: int) -> str:
    """Small counts read better as words in a sentence than as digits."""
    return _NUMBER_WORDS[count] if 0 < count < len(_NUMBER_WORDS) else str(count)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


_LEADING_QUOTE_RE = re.compile(r'^["“]([^"”]+)["”]')


def _start_sentence(clause: str) -> str:
    """Capitalise a clause, or give it a lead-in when it opens on a quote.

    Upper-casing a quotation mark does nothing, so a clause beginning
    '"shall" became "may"' started the sentence in lower case. Quoted evidence
    gets a short lead-in instead of being mangled.
    """
    if not clause:
        return clause
    match = _LEADING_QUOTE_RE.match(clause)
    if match:
        lead = "The word" if len(match.group(1).split()) == 1 else "The wording"
        return f"{lead} {clause}"
    return clause[:1].upper() + clause[1:]


def _slots(issue: dict, section_label: str) -> dict:
    # Quoted evidence carries its own full stop, which then collided with the
    # sentence's: ...“Staff sign the log.”. - two periods.
    evidence = (issue.get("evidence") or "").strip().rstrip(".;:,")
    ratio = issue.get("ratio")
    return {
        # Templates say "section {section}", so the slot holds the number
        # alone where there is one - "section 4.2", not "section 4.2 Procedures".
        "section": _section_slot(section_label),
        "action": issue.get("action") or "changed",
        "direction": issue.get("direction") or "changed",
        "from_text": issue.get("from_text") or "",
        "to_text": issue.get("to_text") or "",
        # "Most" of a section is wrong at 50%. Say what the figure supports.
        "portion": _portion_word(ratio),
        "clause": issue.get("clause") or "",
        "terms": evidence,
        "old": evidence,
        "new": evidence,
        "hedge": _hedge(issue),
        "ratio": f"{float(ratio):.0%}" if isinstance(ratio, (int, float)) else "",
    }


def _render(issue: dict, section_label: str, rng: random.Random) -> str:
    """One clause for one issue, or empty if nothing can be said honestly."""
    options = _PHRASINGS.get(issue["label"])
    if not options:
        return ""
    slots = _slots(issue, section_label)

    # Only phrasings whose slots we can fill: a template asking for {terms} is
    # useless when the issue carries no evidence.
    usable = [
        template for template in options
        if all(slots.get(name) for name in _needed_slots(template))
    ]
    # And when there *is* evidence, prefer a phrasing that quotes it. Adding
    # evidence-free variants for the model-only case meant they started winning
    # the draw even on rule issues, so "a requirement has been removed from 4.2"
    # replaced the far more useful quotation of the removed sentence.
    # Every slot that names the actual words. {from_text}/{to_text} were
    # missing here, so the "changed from X to Y" phrasing could never win the
    # draw and the vaguer "a figure was changed: X to Y" always did.
    quoting = [
        template for template in usable
        if any(slot in template
               for slot in ("{old}", "{terms}", "{from_text}", "{to_text}"))
    ]
    chosen = rng.choice(quoting or usable or options)
    try:
        rendered = chosen.format(**slots)
    except KeyError:
        return ""
    # An empty hedge leaves a double space behind it.
    return _WS_RE.sub(" ", rendered).strip()


def _needed_slots(template: str) -> list:
    return [name for name in re.findall(r"\{(\w+)\}", template) if name != "hedge"]


# -- main entry point ------------------------------------------

def explain(fusion_result, layer1_result, section_label: str = "",
            revision_id=None, max_sentences: int = MAX_SENTENCES) -> str:
    """Readable assessment text for one revision."""
    # Seeded by revision id: same revision, same words, every time.
    rng = random.Random(str(revision_id) if revision_id is not None else "0")

    verdict = fusion_result.verdict

    # The body is written first so the opening can describe what the body
    # actually says. Choosing the opening up front is how an approve came to
    # announce "no blocking problems" and then list one.
    procedural = []
    # A hard fail is procedural - say exactly which rule, not a hedged guess.
    if layer1_result.failed:
        for fail in layer1_result.hard_fails:
            detail = (fail.get("detail") or "").rstrip(".")
            clause = fail.get("clause")
            procedural.append(
                f"{detail}, which clause {clause} requires." if clause else f"{detail}."
            )

    issues = list(fusion_result.issues or [])
    body_budget = max_sentences - 1 - len(procedural) - 2  # opening + change + closing
    shown, remaining = issues[:max(body_budget, 0)], issues[max(body_budget, 0):]

    body = []
    for issue in shown:
        clause_text = _render(issue, section_label, rng)
        if not clause_text:
            continue
        if not body:
            sentence = _start_sentence(clause_text)
        else:
            pool = _HIGH_CONNECTORS if issue.get("severity") == "high" else _CONNECTORS
            sentence = f"{rng.choice(pool)} {_lower_first(clause_text)}"
        body.append(sentence.rstrip(".") + ".")

    concerns = len(body) + len(remaining)
    if verdict == "approve" and concerns:
        points = ("one point is" if concerns == 1
                  else f"{_number_word(concerns)} points are")
        opening = rng.choice(_APPROVE_WITH_CONCERNS).format(points=points)
    else:
        opening = rng.choice(_OPENINGS.get(verdict, _OPENINGS["needs_revision"]))

    sentences = [opening] + procedural + body

    if remaining:
        labels = ", ".join(i["label"].replace("_", " ") for i in remaining[:3])
        count = len(remaining)
        sentences.append(
            f"{count} further issue{'s' if count != 1 else ''} "
            f"{'were' if count != 1 else 'was'} also noted: {labels}."
        )

    change_sentence = _change_type_sentence(layer1_result)
    if change_sentence:
        sentences.append(change_sentence)

    sentences.append(_CLOSINGS.get(verdict, _CLOSINGS["needs_revision"]))
    return " ".join(s for s in sentences if s)


def not_assessed_message(section_label: str = "") -> str:
    """Decision 9: List of Forms sections are not assessed by the model."""
    where = f" ({section_label})" if section_label else ""
    return (
        f"Not assessed - manual admin review{where}. This section is a list of "
        "forms rather than a requirement, so the assessment model does not "
        "produce a verdict for it."
    )
