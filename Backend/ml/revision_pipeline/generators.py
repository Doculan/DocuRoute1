"""Edit generators for the synthetic dataset.

Each generator takes a parsed section plus the document it lives in, applies an
edit the way a person would, and returns the revision it produced. Returning
``None`` means the generator does not apply here - which is the point: a
generator that cannot find a real quantity to change must not renumber a list
and call that a changed figure.

Rules that run through all of them:

* **The whole section is submitted.** Edits land on one to three rows or
  sentences, but ``old_text`` and ``new_text`` are the entire section, because
  that is what the app sends.
* **Edit the real document.** Nothing is fabricated into ``old_text`` to give
  the edit something to bite on. A duplicate row invented so that it can be
  removed produces a section the manual never had.
* **An item number is a label, not a quantity.** Renumbering is not a changed
  figure, and never a contradiction.
* **Stay grammatical.** A swap that leaves "with first exhausting" or "each
  the" teaches the model to spot broken English, not a bad revision.
* **The reason must fit the edit.** "Fixed spelling" on a deleted step is a
  contradiction a reviewer would notice immediately.
* **If the correct verdict is unclear, return None.** A doubtful example is
  worse than a missing one.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from . import config
from .diffing import change_ratios
from .entities import get_entities
from .glossary import NOT_EQUIVALENT, get_glossary
from .section_doc import SectionDoc

# ===============================================================
#  Change reasons, by the kind of edit they belong to
# ===============================================================
# A reason that contradicts the edit is a defect in its own right, so approve
# examples draw from the pool for the edit they actually made. Revisions that
# are not approvals draw from the plausible and vague pools, which fit any
# edit - a reviewer cannot lean on the reason to tell them what happened.

_REASONS = {
    "typo": [
        "Corrected a typographical error found during the internal audit.",
        "Fixed spelling flagged in the last document review.",
        "Corrected a misspelled word.",
    ],
    "format": [
        "Minor formatting correction, no change to the requirement.",
        "Tidied the spacing to match the rest of the manual.",
        "Formatting only; the wording is unchanged.",
    ],
    "term": [
        "Updated the term to match the approved glossary.",
        "Aligned the wording with the rest of the manual.",
        "Used the standard term for consistency.",
    ],
    # One pool per kind of edit. A shared "clarify" pool put "Spelled out the
    # abbreviation on first use" on a revision that had contracted one.
    "acronym": [
        "Spelled out the abbreviation on first use.",
        "Wrote the name in full so new staff can follow it.",
        "Expanded the acronym, as the style guide asks.",
    ],
    "figure": [
        "Wrote the figure out in words, as the rest of the manual does.",
        "Matched the house style for figures.",
        "Spelled the number out for consistency.",
    ],
    "reference": [
        "Made the reference format consistent with the other manuals.",
        "Used the short form of the legal reference, as elsewhere.",
        "Standardised how the issuance is cited.",
    ],
    "pointer": [
        "Added the section reference so readers can find the related step.",
        "Pointed to the section that covers this in detail.",
        "Added a cross-reference after questions from staff.",
    ],
    "merge": [
        "Merged two lines that were one step, for readability.",
        "Joined a step that had been split across two rows.",
    ],
    "split": [
        "Split a crowded step into two lines, for readability.",
        "Put the second sentence on its own line.",
        "Separated the two actions so each reads as its own step.",
    ],
    "reorder": [
        "Listed the entries in alphabetical order.",
        "Put the items in a more logical order.",
    ],
    "plausible": [
        "Updated to reflect the new collection schedule.",
        "Revised following the management review.",
        "Aligned with current office practice.",
        "Updated per the latest memorandum from the VPAF.",
        "Revised after the internal audit finding.",
        "Updated to match how the office actually works.",
    ],
    "vague": [
        "Update.",
        "As discussed.",
        "Per instruction.",
        "Revised.",
        "Changes requested.",
    ],
}


def _reason(rng: random.Random, kind: str) -> str:
    if kind == "none":
        return ""
    return rng.choice(_REASONS[kind])


# ===============================================================
#  Quantities - what counts as a real figure
# ===============================================================

_UNIT_WORDS = (
    r"(?:working\s+days|calendar\s+days|days|day|weeks|week|months|month|years|"
    r"year|hours|hour|minutes|minute|copies|copy|percent|points|point|pages|"
    r"page|sets|set|units|unit|members|member|quotations|quotation|pesos|peso)"
)
# A figure with a unit after it: "15 days", "3 copies", "30%".
_QUANTITY_RE = re.compile(rf"\b(\d{{1,4}})(?=\s*(?:%|{_UNIT_WORDS}\b))", re.IGNORECASE)
# The manual's house style: "three (3) conspicuous places".
_SPELLED_PAIR_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|"
    r"twenty|thirty|sixty|ninety)\s*\((\d{1,3})\)",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"(?:P|PHP|Php|₱)\s?(\d[\d,]*)")

_NUMBER_WORD = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 15: "fifteen",
    20: "twenty", 30: "thirty", 60: "sixty", 90: "ninety",
}

# Frequency and calendar words. These fill a column of their own in several
# tables, which is how "Quarterly" came to be swapped as if it were a role.
_CALENDAR_RE = re.compile(
    r"^(?:daily|weekly|monthly|quarterly|annually|yearly|semi-annually|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|first|second|third|fourth|every|end|start|beginning|"
    r"within|upon|as\s+needed|\d)",
    re.IGNORECASE,
)

# A figure followed by a unit *word*. Percentages are never written out in
# words in these manuals, and "(10%)" became "(ten (10)%)".
_UNIT_QUANTITY_RE = re.compile(rf"\b(\d{{1,4}})(?=\s*{_UNIT_WORDS}\b)", re.IGNORECASE)
# A sentence boundary inside a step, where a crowded cell can be divided.
_SPLITTABLE_RE = re.compile(r"(?<=[a-z0-9)])\.\s+(?=[A-Z])")
_STEP_NO_RE = re.compile(r"^\s*\d{1,2}\.(?!\d)")
# "Accounting Staff-4", which Layer 1 matches by regex rather than by lookup.
_SUFFIXED_ROLE_RE = re.compile(r"^[A-Z][A-Za-z ]+-\s?\d+$")
_SEQUENCE_CUE_RE = re.compile(
    r"\b(?:step|thereafter|then|afterwards|subsequently|once|upon|after|before|"
    r"return to|proceed|next|finally|first|second|third|previous|following)\b",
    re.IGNORECASE,
)


def _quantity_spans(text: str) -> list:
    """Every real figure in the text, as (start, end, kind).

    An item or step number is not here: "3.15" labels a clause and "1." labels
    a step, and changing either is renumbering, not a change of requirement.
    """
    spans = []
    for match in _SPELLED_PAIR_RE.finditer(text):
        spans.append((match.start(), match.end(), "spelled"))
    taken = [(s, e) for s, e, _ in spans]
    for match in _QUANTITY_RE.finditer(text):
        if any(s <= match.start() < e for s, e in taken):
            continue
        spans.append((match.start(), match.end(), "plain"))
    for match in _MONEY_RE.finditer(text):
        spans.append((match.start(1), match.end(1), "money"))
    return spans


def _new_value(value: int, rng: random.Random) -> int:
    """A different, still plausible figure."""
    options = [v for v in (value * 2, value // 2, value + 5, value + 10, value - 5)
               if v != value and v > 0]
    return rng.choice(options) if options else value + 1


_DAYS_PER_UNIT = {
    "day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30,
    "year": 365, "years": 365,
}
_DURATION_RE = re.compile(r"\b(\d{1,4})\s*(days?|weeks?|months?|years?)\b",
                          re.IGNORECASE)


def _restated_in_unit(text: str, fragment: str) -> bool:
    """True when the same figure is stated twice in one unit, two ways.

    "outstanding for more than 365 days or 1 year" says one thing twice.
    Changing one half leaves the sentence contradicting itself, which is a
    different and more serious finding than a changed figure - so the quantity
    generator leaves these alone.
    """
    durations = [(int(m.group(1)), m.group(2).lower().rstrip("s"))
                 for m in _DURATION_RE.finditer(text)]
    canonical = [value * _DAYS_PER_UNIT.get(unit, 0) for value, unit in durations]
    canonical = [c for c in canonical if c]
    if len(canonical) < 2:
        return False
    try:
        mine = int(re.sub(r"\D", "", fragment))
    except ValueError:
        return False
    return any(
        value * _DAYS_PER_UNIT.get(unit, 0) == other and value != mine
        for value, unit in durations
        for other in canonical
        if value * _DAYS_PER_UNIT.get(unit, 0)
    ) and canonical.count(canonical[0]) == len(canonical)


def _change_quantity(text: str, rng: random.Random):
    """Change one real figure. Returns (new_text, was, now) or None."""
    spans = [s for s in _quantity_spans(text)
             if not _restated_in_unit(text, text[s[0]:s[1]])]
    if not spans:
        return None
    start, end, kind = rng.choice(spans)
    fragment = text[start:end]

    if kind == "spelled":
        match = _SPELLED_PAIR_RE.match(fragment)
        value = int(match.group(2))
        replacement_value = _new_value(value, rng)
        word = _NUMBER_WORD.get(replacement_value)
        if not word:
            return None
        replacement = f"{word} ({replacement_value})"
    elif kind == "money":
        value = int(fragment.replace(",", ""))
        replacement_value = _new_value(value, rng)
        replacement = f"{replacement_value:,}" if "," in fragment else str(replacement_value)
    else:
        value = int(fragment)
        replacement = str(_new_value(value, rng))

    if replacement == fragment:
        return None
    return text[:start] + replacement + text[end:], fragment, replacement


# ===============================================================
#  Units: the places an edit can land
# ===============================================================

def _row_setter(index: int):
    def apply(edited: SectionDoc, text: str) -> None:
        edited.set_row_body(index, text)
    return apply


def _sentence_setter(position: int, original: str):
    def apply(edited: SectionDoc, text: str) -> None:
        block = edited.blocks[position]
        block.text = re.sub(r"\s{2,}", " ", block.text.replace(original, text, 1))
    return apply


def _editable_rows(doc: SectionDoc) -> list:
    return [r for r in doc.rows if len(r.body.split()) >= 5]


def _editable_units(doc: SectionDoc, minimum_words: int = 5) -> list:
    """Every place an edit can land: table rows and prose sentences alike."""
    units = [(row.body, _row_setter(row.index)) for row in doc.rows
             if len(row.body.split()) >= minimum_words]
    if not doc.has_table:
        units += [(text, _sentence_setter(position, text))
                  for position, _, text in doc.sentences()
                  if len(text.split()) >= minimum_words]
    return units


def _shuffled(items, rng):
    items = list(items)
    return rng.sample(items, len(items)) if items else []


def _is_procedure_table(doc: SectionDoc) -> bool:
    """A Responsibility / Activity table, as opposed to a list or a calendar."""
    header = next((b.row for b in doc.blocks if b.kind == "header"), None)
    if header and header.cells and re.search(r"responsib", header.cells[0], re.I):
        return True
    return sum(1 for row in doc.rows if _STEP_NO_RE.match(row.body)) >= 2


def _role_rows(doc: SectionDoc) -> list:
    """Rows whose first cell really is a responsible party.

    A frequency column ("Quarterly", "First Week of the Year") sits in the same
    position in several tables, and swapping one of those reads as a changed
    schedule, not a changed responsibility.
    """
    if not _is_procedure_table(doc):
        return []
    entities = get_entities()
    rows = []
    for row in doc.rows:
        role = (row.role or "").strip()
        if not role or _CALENDAR_RE.match(role) or not re.match(r"^[A-Z]", role):
            continue
        # The role has to be one the rule layer knows, or the swap is invisible
        # to it and the example claims an issue nothing can confirm. A suffixed
        # role ("Accounting Staff-4") is matched by regex on both sides, so it
        # counts too.
        if entities.is_role(role) or _SUFFIXED_ROLE_RE.match(role):
            rows.append(row)
    return rows


def _replace_once(text: str, old: str, new: str) -> str:
    """Case-preserving single replacement on a word boundary."""
    pattern = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return text
    found = match.group(0)
    replacement = new.capitalize() if found[0].isupper() else new
    return text[: match.start()] + replacement + text[match.end():]


def _in_title_case_run(text: str, start: int, end: int) -> bool:
    """True when the span sits inside a named document like "Purchase Order"."""
    word = text[start:end]
    if not word[:1].isupper():
        return False
    before = text[:start].rstrip().split()
    after = text[end:].lstrip().split()
    previous = before[-1] if before else ""
    following = after[0] if after else ""
    return bool(re.match(r"^[A-Z]", previous) or re.match(r"^[A-Z]", following))


@dataclass
class Revision:
    """One generated example, before the quality gate sees it."""

    new_text: str
    verdict: str
    issues: list = field(default_factory=list)
    generator: str = ""
    change_reason: str = ""
    edited_units: int = 1
    note: str = ""
    strategy: str = ""


# ===============================================================
#  APPROVE
# ===============================================================

_TYPOS = [
    ("the", "teh"), ("and", "adn"), ("receives", "recieves"),
    ("submits", "submitts"), ("signature", "signatuer"),
    ("approval", "aproval"), ("documents", "documnets"),
    ("office", "ofice"), ("required", "requried"), ("copies", "copys"),
]


def typo_fix(doc, ctx, rng):
    """Someone corrects a misspelling. The submitted section carries it."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for correct, wrong in _shuffled(_TYPOS, rng):
            if not re.search(rf"\b{correct}\b", text):
                continue
            broken = _replace_once(text, correct, wrong)
            if broken == text:
                continue
            fixed_doc = doc.copy()
            apply(fixed_doc, text)
            broken_doc = doc.copy()
            apply(broken_doc, broken)
            return Revision(
                new_text=fixed_doc.render(), verdict="approve",
                generator="typo_fix", change_reason=_reason(rng, "typo"),
                strategy=f"{wrong} -> {correct}",
            ), broken_doc.render()
    return None


def whitespace_format(doc, ctx, rng):
    """Spacing and punctuation tidied; not one word changes."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        broken = None
        if " (" in text:
            broken = text.replace(" (", "(", 1)
        elif ", " in text:
            broken = text.replace(", ", " ,", 1)
        elif ". " in text:
            broken = text.replace(". ", " . ", 1)
        if not broken or broken == text:
            continue
        clean_doc = doc.copy()
        apply(clean_doc, text)
        broken_doc = doc.copy()
        apply(broken_doc, broken)
        return Revision(
            new_text=clean_doc.render(), verdict="approve",
            generator="whitespace_format", change_reason=_reason(rng, "format"),
            strategy="spacing",
        ), broken_doc.render()
    return None


# Phrases that mean the same thing in this register, with their inflections.
# Curated rather than taken from the glossary: bare word swaps produced "as
# mandatory", "Once accomplish" and "all office", and renamed documents
# ("Form" became "Template").
# Phrases that mean the same thing in this register. The third field says
# whether the swap is safe in reverse: "in order to" can always be shortened to
# "to", but expanding every "to" into "in order to" produced "these procedures
# apply in order to the accreditation". Single words of the same part of speech
# are safe both ways.
# Phrases that mean the same thing in this register. The third field says
# whether the swap is safe in reverse. Most are not: shortening "in order to"
# to "to" is always safe, expanding every "to" is not, and the plain word is
# the one the manuals actually use - "use" becoming "utilize", "forwards"
# becoming "endorses" and "check" becoming "verify" all read as someone making
# the text more formal than the document is, not as an equivalent term.
_EQUIVALENT_PHRASES = [
    ("in order to", "to", False),
    ("in the event that", "if", False),
    ("with regard to", "regarding", False),
    ("with respect to", "regarding", False),
    ("as well as", "and", False),
    ("in accordance with", "following", False),
    ("for the purpose of", "for", False),
    ("at the same time", "simultaneously", False),
    ("utilize", "use", False), ("utilizes", "uses", False),
    ("utilized", "used", False),
    ("commence", "begin", False), ("commences", "begins", False),
    ("endorse", "forward", False), ("endorses", "forwards", False),
    ("furnish", "provide", False), ("furnishes", "provides", False),
    ("ascertain", "confirm", False), ("ascertains", "confirms", False),
]

# A named document runs through its lowercase connectors: "Transcript of
# Record", "Notice of Award", "Board of Regents". Testing only the immediate
# neighbours let a swap land on the "of" in the middle of one.
_NAMED_DOCUMENT_RE = re.compile(
    r"\b[A-Z][A-Za-z]+(?:\s+(?:of|for|and|the|to|on|in)\s+[A-Z][A-Za-z]+"
    r"|\s+[A-Z][A-Za-z]+)+\b"
)


def _inside_named_document(text: str, start: int, end: int) -> bool:
    return any(m.start() <= start and end <= m.end()
               for m in _NAMED_DOCUMENT_RE.finditer(text))


def equivalent_synonym(doc, ctx, rng):
    """Swap a phrase for one that means the same and reads the same."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for first, second, reversible in _shuffled(_EQUIVALENT_PHRASES, rng):
            directions = [(first, second)]
            if reversible:
                directions.append((second, first))
            for source, target in directions:
                match = re.search(rf"\b{re.escape(source)}\b", text, re.IGNORECASE)
                if not match:
                    continue
                if (_in_title_case_run(text, match.start(), match.end())
                        or _inside_named_document(text, match.start(), match.end())):
                    continue
                replacement = target
                if match.group(0)[0].isupper():
                    replacement = target[0].upper() + target[1:]
                swapped = re.sub(
                    r"\s{2,}", " ",
                    text[:match.start()] + replacement + text[match.end():],
                )
                if swapped == text:
                    continue
                edited = doc.copy()
                apply(edited, swapped)
                return Revision(
                    new_text=edited.render(), verdict="approve",
                    generator="equivalent_synonym", change_reason=_reason(rng, "term"),
                    strategy=f"{source} -> {target}",
                ), doc.render()
    return None


# Bodies and registers whose names read with "the" in front of them.
_NEEDS_ARTICLE_RE = re.compile(
    r"^(?:Commission|Board|Department|Office|University|Committee|Registry|"
    r"Council|Bureau|Agency|Secretariat|Government|State|Program)\b"
)


def acronym_expansion(doc, ctx, rng):
    """Expand an acronym on first use, keeping the acronym in brackets."""
    definitions = ctx.get("acronyms") or {}
    for text, apply in _shuffled(_editable_units(doc), rng):
        for acronym, full in _shuffled(list(definitions.items()), rng):
            if f"({acronym})" in text or full.lower() in text.lower():
                continue
            match = re.search(rf"\b{re.escape(acronym)}\b", text)
            if not match:
                continue
            # "by CHED" expands to "by the Commission on Higher Education
            # (CHED)": a body's name takes an article that the acronym did not.
            lead = text[:match.start()].rstrip()
            article = ""
            if (_NEEDS_ARTICLE_RE.match(full)
                    and not re.search(r"\b(?:the|a|an|its|their)$", lead, re.IGNORECASE)
                    and re.search(r"\b(?:by|to|from|for|with|of|at|in|on)$",
                                  lead, re.IGNORECASE)):
                article = "the "
            expanded = (text[:match.start()] + f"{article}{full} ({acronym})"
                        + text[match.end():])
            edited = doc.copy()
            apply(edited, expanded)
            return Revision(
                new_text=edited.render(), verdict="approve",
                generator="acronym_expansion", change_reason=_reason(rng, "acronym"),
                strategy=f"expand {acronym}",
            ), doc.render()
    return None


def spell_out_figure(doc, ctx, rng):
    """Write a figure in the manual's own style: "fifteen (15) days"."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for match in _UNIT_QUANTITY_RE.finditer(text):
            word = _NUMBER_WORD.get(int(match.group(1)))
            if not word:
                continue
            # Never inside brackets, and never where the figure is already
            # written out.
            lead = text[max(0, match.start() - 14):match.start()]
            if lead.rstrip().endswith("(") or _SPELLED_PAIR_RE.search(lead):
                continue
            spelled = (text[:match.start()] + f"{word} ({match.group(1)})"
                       + text[match.end():])
            edited = doc.copy()
            apply(edited, spelled)
            return Revision(
                new_text=edited.render(), verdict="approve",
                generator="spell_out_figure", change_reason=_reason(rng, "figure"),
                strategy="figure in words",
            ), doc.render()
    return None


# The same reference written the other accepted way. Both forms appear across
# the manuals, so neither is a change of substance.
_LEGAL_FORMS = [
    (r"\bR\.?A\.?\s*(?:No\.?\s*)?(\d{4,5})\b", r"Republic Act No. \1"),
    (r"\bRepublic Act No\.?\s*(\d{4,5})\b", r"R.A. No. \1"),
    (r"\bE\.?O\.?\s*No\.?\s*(\d{1,3})\b", r"Executive Order No. \1"),
    (r"\bExecutive Order No\.?\s*(\d{1,3})\b", r"E.O. No. \1"),
    (r"\bseries of (\d{4})\b", r"s. \1"),
    (r"\bs\.\s*(\d{4})\b", r"series of \1"),
]


def legal_reference_format(doc, ctx, rng):
    """Rewrite a legal reference in the other format, same reference."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for pattern, replacement in _shuffled(_LEGAL_FORMS, rng):
            rewritten, count = re.subn(pattern, replacement, text, count=1)
            if not count or rewritten == text:
                continue
            edited = doc.copy()
            apply(edited, rewritten)
            return Revision(
                new_text=edited.render(), verdict="approve",
                generator="legal_reference_format",
                change_reason=_reason(rng, "reference"), strategy="reference format",
            ), doc.render()
    return None


def cross_reference_addition(doc, ctx, rng):
    """Point the reader at a related section, at the end of a sentence.

    A pointer obliges nobody to do anything, which is what makes it a safe
    approve. But it has to sit where a person would put it: at the end of a
    sentence in a step, never inside a table cell that holds a value, and never
    trailing a semicolon in the middle of a list. The target has to be a
    section this one actually relates to - a purchasing step pointing at
    "1.0 OBJECTIVES" is not something anyone would write.
    """
    siblings = ctx.get("related_labels") or []
    if not siblings:
        return None
    for text, apply in _shuffled(_editable_units(doc), rng):
        if "(see" in text.lower() or "(refer" in text.lower():
            continue
        tail = text.rstrip()
        # A cell holding a value, a date or a bare noun phrase is not a
        # sentence and has no end to append to.
        if not tail.endswith(".") or len(tail.split()) < 6:
            continue
        if tail.rstrip(".").rstrip().endswith((";", ":", ",", "/")):
            continue
        edited = doc.copy()
        apply(edited, f"{tail[:-1]} (see {rng.choice(siblings)}).")
        return Revision(
            new_text=edited.render(), verdict="approve",
            generator="cross_reference_addition",
            change_reason=_reason(rng, "pointer"), strategy="cross reference",
        ), doc.render()
    return None


def row_merge_reformat(doc, ctx, rng):
    """Join two rows that are one step, keeping every word.

    A hard negative by design: the rules see a row disappear, and the right
    answer is still approve, because not one word left the section.
    """
    rows = doc.rows
    if len(rows) < 3:
        return None
    candidates = [
        index for index in range(len(rows) - 1)
        if rows[index].role and not rows[index + 1].role
        # The second row has to be a continuation, not a step of its own -
        # merging "1. Prepares the documents" with "2. Receives documents"
        # runs two steps together, which is not a formatting tidy-up.
        and not _STEP_NO_RE.match(rows[index + 1].body)
        and len(rows[index].cells) == len(rows[index + 1].cells)
        and len(rows[index].body.split()) >= 4
        and len(rows[index + 1].body.split()) >= 4
    ]
    if not candidates:
        return None
    index = rng.choice(candidates)
    first, second = rows[index], rows[index + 1]
    merged = doc.copy()
    merged.set_row_body(first.index, f"{first.body.rstrip()} {second.body.strip()}")
    merged.delete_row(second.index)
    return Revision(
        new_text=merged.render(), verdict="approve",
        generator="row_merge_reformat", change_reason=_reason(rng, "merge"),
        edited_units=2, strategy="merge two rows",
        note="hard negative: a row disappears but no wording is lost",
    ), doc.render()


def step_split_reformat(doc, ctx, rng):
    """Split a crowded step into two rows, keeping every word.

    A hard negative by design: the rules see a row appear and the line count
    move, and the right answer is still approve, because nothing was added or
    taken away. It is the inverse of the wrapped-row repair the extractor does,
    and it is what a person does to a cell that has grown two sentences long.
    """
    candidates = [
        row for row in doc.rows
        if row.role and len(row.body.split()) >= 12
        and len(_SPLITTABLE_RE.findall(row.body)) >= 1
    ]
    if not candidates:
        return None
    row = rng.choice(candidates)
    match = rng.choice(list(_SPLITTABLE_RE.finditer(row.body)))
    head, tail = row.body[:match.end()].strip(), row.body[match.end():].strip()
    if len(head.split()) < 4 or len(tail.split()) < 4:
        return None

    edited = doc.copy()
    edited.set_row_body(row.index, head)
    cells = [""] * len(row.cells)
    cells[-1] = tail
    edited.insert_row_after(row.index, cells)
    return Revision(
        new_text=edited.render(), verdict="approve",
        generator="step_split_reformat", change_reason=_reason(rng, "split"),
        edited_units=2, strategy="split a crowded step",
        note="hard negative: a row appears but no wording is added",
    ), doc.render()


def benign_reorder(doc, ctx, rng):
    """Reorder two items whose order carries no meaning.

    Never numbered steps, and never anything that refers to another step:
    swapping "Return to step 4" with the step it returns to is a defect, and it
    is indistinguishable from step_reorder_dependent.
    """
    if _is_procedure_table(doc):
        return None
    rows = doc.rows
    eligible = []
    for index in range(len(rows) - 1):
        first, second = rows[index], rows[index + 1]
        if _STEP_NO_RE.match(first.body) or _STEP_NO_RE.match(second.body):
            continue
        if _SEQUENCE_CUE_RE.search(f"{first.render()} {second.render()}"):
            continue
        # A leading index column ("| 4 | Cash in Bank ...") is an ordering.
        if re.match(r"^\d+$", (first.cells[0] or "x").strip()):
            continue
        if not first.body.strip() or not second.body.strip():
            continue
        # A section can hold several tables, and doc.rows runs straight through
        # them, so consecutive rows are not always neighbours: a two-column
        # schedule row was swapped with a four-column ratings row.
        if len(first.cells) != len(second.cells):
            continue
        eligible.append((first, second))
    if not eligible:
        return None
    first, second = rng.choice(eligible)
    edited = doc.copy()
    edited.swap_rows(first.index, second.index)
    if edited.render() == doc.render():
        return None
    return Revision(
        new_text=edited.render(), verdict="approve", generator="benign_reorder",
        change_reason=_reason(rng, "reorder"), edited_units=2,
        strategy="swap unordered rows",
        note="hard negative: rows move but the list has no sequence",
    ), doc.render()


# ===============================================================
#  NEEDS REVISION
# ===============================================================

# Directions that widen rather than narrow. Generated the other way round only.
_SCOPE_WIDENING = {("any", "all"), ("some", "all"), ("any", "every")}

# Glossary words that are a different thing as a noun than as a verb.
_VERB_ONLY = {
    "file", "record", "note", "issue", "print", "update", "complete", "start",
    "monitor", "audit", "review", "accept", "receive", "replace", "archive",
    "retain", "submit", "approve", "endorse", "acknowledge", "validate",
    "verify", "check",
}
# What a verb follows: the start of a step, a modal, or a conjunction.
_VERB_CUE_RE = re.compile(
    r"(?:^|\|)\s*(?:\d{1,2}\.\s*)?$"
    r"|\b(?:shall|will|may|must|should|can|to|and|or|then|also|shall not)\s+$",
    re.IGNORECASE,
)


def _in_verb_position(text: str, start: int) -> bool:
    return bool(_VERB_CUE_RE.search(text[:start]))


def non_equivalent_swap(doc, ctx, rng):
    """Swap a term for one that does not mean the same thing.

    Three families are excluded. An obligation becoming a permission is
    ``modal_weakened``; a sense reversal such as before/after is
    ``negation_changed``; and strengthening - "should" becoming "shall" - is
    not an issue at all, so it is never generated.
    """
    glossary = get_glossary()
    reversal_words = {w.lower() for pair in config.SENSE_REVERSALS for w in pair}
    modal_words = {m.lower() for m in
                   config.OBLIGATION_MODALS + config.PERMISSIVE_MODALS}
    pairs = [
        (a, b) for (a, b), relation in glossary._pairs.items()
        if relation == NOT_EQUIVALENT and " " not in a and " " not in b
        and a.lower() not in reversal_words and b.lower() not in reversal_words
        and a.lower() not in modal_words and b.lower() not in modal_words
        # Widening a scope is strengthening, and strengthening is not an issue:
        # "any records shall be handled" and "all records shall be handled" ask
        # for the same thing. Only the narrowing direction is generated.
        and (a.lower(), b.lower()) not in _SCOPE_WIDENING
    ]
    units = _editable_units(doc)
    if not units or not pairs:
        return None
    for text, apply in _shuffled(units, rng):
        for a, b in rng.sample(pairs, min(len(pairs), 30)):
            match = re.search(rf"\b{re.escape(a)}\b", text, re.IGNORECASE)
            if not match or _in_title_case_run(text, match.start(), match.end()):
                continue
            if _inside_named_document(text, match.start(), match.end()):
                continue
            # These pairs separate two *verbs* - filing is not recording. Used
            # on the nouns, "encoded in computer file" became "in computer
            # record", which is not a change of meaning at all.
            if a.lower() in _VERB_ONLY and not _in_verb_position(text, match.start()):
                continue
            swapped = _replace_once(text, a, b)
            if swapped == text:
                continue
            edited = doc.copy()
            apply(edited, swapped)
            return Revision(
                new_text=edited.render(), verdict="needs_revision",
                issues=["non_equivalent_term"], generator="non_equivalent_swap",
                change_reason=_reason(rng, "plausible"), strategy=f"{a} -> {b}",
            ), doc.render()
    return None


def numeric_change(doc, ctx, rng):
    """Change a real quantity: a duration, an amount, a count, a percentage."""
    units = [u for u in _editable_units(doc) if _quantity_spans(u[0])]
    if not units:
        return None
    edited = doc.copy()
    changed, evidence = 0, []
    for text, apply in rng.sample(units, min(len(units), rng.choice([1, 1, 2]))):
        result = _change_quantity(text, rng)
        if not result:
            continue
        new_text, was, now = result
        apply(edited, new_text)
        evidence.append(f"{was} -> {now}")
        changed += 1
    if not changed:
        return None
    return Revision(
        new_text=edited.render(), verdict="needs_revision",
        issues=["numeric_changed"], generator="numeric_change",
        change_reason=_reason(rng, "plausible"), edited_units=changed,
        strategy="quantity", note="; ".join(evidence),
    ), doc.render()


_MODAL_WEAKENINGS = [("shall", "may"), ("must", "may"), ("will", "may"),
                     ("shall", "can"), ("must", "should")]


def modal_weaken_single(doc, ctx, rng):
    """An obligation becomes a permission."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for strong, weak in rng.sample(_MODAL_WEAKENINGS, len(_MODAL_WEAKENINGS)):
            if not re.search(rf"\b{strong}\b", text, re.IGNORECASE):
                continue
            edited = doc.copy()
            apply(edited, _replace_once(text, strong, weak))
            return Revision(
                new_text=edited.render(), verdict="needs_revision",
                issues=["modal_weakened"], generator="modal_weaken_single",
                change_reason=_reason(rng, "plausible"), strategy=f"{strong} -> {weak}",
            ), doc.render()
    return None


# What kind of thing a named document is, so it can be replaced by a generic
# word for that same kind rather than by an arbitrary noun.
_DOCUMENT_NOUNS = {
    "form": "the form", "forms": "the forms", "report": "the report",
    "voucher": "the voucher", "slip": "the slip", "logbook": "the logbook",
    "certificate": "the certificate", "record": "the record",
    "records": "the records", "request": "the request", "order": "the order",
    "notice": "the notice", "statement": "the statement",
    "receipt": "the receipt", "register": "the register", "list": "the list",
    "sheet": "the sheet", "plan": "the plan", "system": "the system",
    "policy": "the policy", "ledger": "the ledger", "payroll": "the payroll",
}
_TRAILING_ACRONYM_RE = re.compile(r"\s*\([A-Za-z./ ]{2,12}\)")


def _generic_for(term: str) -> str:
    """The generic noun phrase for a named document, or "" if it is not one."""
    head = _TRAILING_ACRONYM_RE.sub("", term).strip()
    for word in reversed(head.split()):
        generic = _DOCUMENT_NOUNS.get(word.lower().strip(",.;:"))
        if generic:
            return generic
    return ""


def key_term_vagueing(doc, ctx, rng):
    """Replace a named document with a generic word for the same kind of thing.

    The commonest way a named control disappears is not deletion but
    genericisation - "attach the Disbursement Voucher (DV)" becomes "attach the
    voucher". Only terms that really name a document are eligible, and the
    article and any bracketed acronym go with the term, so the step still reads.
    """
    terms = [t for t in ctx.get("key_terms", []) if len(t) > 6 and _generic_for(t)]
    for text, apply in _shuffled(_editable_units(doc), rng):
        for term in _shuffled(terms, rng):
            pattern = re.compile(
                rf"(the\s+)?{re.escape(term)}(\s*\([A-Za-z./ ]{{2,12}}\))?",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if not match:
                continue
            generic = _generic_for(term)
            if not match.group(1):
                generic = generic[len("the "):]
            replaced = re.sub(
                r"\s{2,}", " ",
                text[:match.start()] + generic + text[match.end():],
            ).strip()
            if replaced == text or len(replaced.split()) < 4:
                continue
            edited = doc.copy()
            apply(edited, replaced)
            return Revision(
                new_text=edited.render(), verdict="needs_revision",
                issues=["key_term_deleted"], generator="key_term_vagueing",
                change_reason=_reason(rng, rng.choice(["plausible", "vague"])),
                strategy="generic noun", note=f"{term} -> {generic}",
            ), doc.render()
    return None


def partial_key_term_delete(doc, ctx, rng):
    """Drop a named document from a step, leaving the step grammatical.

    The article and the bracketed acronym go with the term: removing only the
    term itself left "submits the to the Budget Office".
    """
    # "PROVIDED" reached the key-term list from contract phrasing set in
    # capitals and was being deleted as if it named a control. It is out of the
    # entity list now, so the test here only has to exclude that shape: a
    # single shouted word is not the name of a document.
    terms = [t for t in ctx.get("key_terms", [])
             if len(t) > 6 and not (t.isupper() and len(t.split()) == 1)]
    for text, apply in _shuffled(_editable_units(doc), rng):
        for term in _shuffled(terms, rng):
            pattern = re.compile(
                rf"\s*\b(?:the|a|an)\s+{re.escape(term)}(?:\s*\([A-Za-z./ ]{{2,12}}\))?"
                rf"|\s*{re.escape(term)}(?:\s*\([A-Za-z./ ]{{2,12}}\))?",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if not match:
                continue
            stripped = text[:match.start()] + " " + text[match.end():]
            stripped = re.sub(r"\s{2,}", " ", stripped).strip()
            stripped = re.sub(r"\s+([,.;:])", r"\1", stripped)
            # "assigns number on the ORS/ Budget Utilization Request (BURS)"
            # left "on the ORS/ based on" - the slash was joining the term to
            # the one before it, so removing one half strands the separator.
            if re.search(r"[/&]\s|\s(?:and|or)\s+(?:based|to|for|in|on)\b", stripped):
                if re.search(r"[/&]\s|\s(?:and|or)\s+(?:based|to|for|in|on)\b", text):
                    pass        # the source already reads that way
                else:
                    continue
            if stripped == text or len(stripped.split()) < 4:
                continue
            edited = doc.copy()
            apply(edited, stripped)
            return Revision(
                new_text=edited.render(), verdict="needs_revision",
                issues=["key_term_deleted"], generator="partial_key_term_delete",
                change_reason=_reason(rng, "vague"), strategy="delete term",
                note=f"removed {term}",
            ), doc.render()
    return None


# ===============================================================
#  REJECT
# ===============================================================

# What may follow "without" and still read correctly once it becomes "with".
# "without first exhausting" became "with first exhausting", which is not
# English, and taught the model to spot broken grammar instead of a reversal.
_WITH_OK_NEXT = re.compile(
    r"^(?:the|a|an|any|prior|written|proper|its|his|her|their|our|further|"
    r"[A-Z])", re.IGNORECASE,
)
# "with" is part of a fixed phrase here, not a condition on the requirement.
# "handled in accordance with the Act" became "in accordance without the Act".
_WITH_FIXED_PHRASE = re.compile(
    r"\b(?:accordance|line|compliance|consistent|conjunction|connection|"
    r"together|along|dealing|deal|deals|comply|complies|complied|regard|"
    r"respect|accordingly|consultation|coordination)\s*$",
    re.IGNORECASE,
)


_NEGATIVE_NEARBY_RE = re.compile(
    r"\b(?:not|no|never|without|neither|nor|none|cannot|except|unless)\b",
    re.IGNORECASE,
)
# A past participle turned attributive reads as nonsense: "disapproved
# policies", "ineligible documents". These belong before a decision, not before
# the thing the decision is about.
_ATTRIBUTIVE_NOUNS = re.compile(
    r"^\s*(?:policies|policy|curriculum|curricula|documents|document|reports|"
    r"report|forms|form|records|record|guidelines|procedures|requirements|"
    r"standards|copies|statements)\b",
    re.IGNORECASE,
)


def _apply_reversal(text: str, first: str, second: str):
    """Swap one side of a sense reversal for the other, if it stays grammatical."""
    for source, target in ((first, second), (second, first)):
        match = re.search(rf"\b{re.escape(source)}\b", text, re.IGNORECASE)
        if not match:
            continue
        if source.lower() in ("without", "with") or target.lower() in ("without", "with"):
            if not _WITH_OK_NEXT.match(text[match.end():].lstrip()):
                continue
            if _WITH_FIXED_PHRASE.search(text[:match.start()]):
                continue
        # A clause that is already negative turns into a double negative:
        # "shall not release without approval" becoming "... with approval".
        clause_start = max(0, match.start() - 60)
        if _NEGATIVE_NEARBY_RE.search(text[clause_start:match.start()]):
            continue
        replacement = target
        if match.group(0)[0].isupper():
            replacement = target[0].upper() + target[1:]
        after = text[match.end():]
        if _ATTRIBUTIVE_NOUNS.match(after):
            continue
        return text[:match.start()] + replacement + after, source, target
    return None


def negation_flip(doc, ctx, rng):
    """Reverse a requirement: with a negation word, or with a sense reversal."""
    for text, apply in _shuffled(_editable_units(doc), rng):
        for first, second in _shuffled(config.SENSE_REVERSALS, rng):
            result = _apply_reversal(text, first, second)
            if not result:
                continue
            flipped, source, target = result
            if flipped == text:
                continue
            edited = doc.copy()
            apply(edited, flipped)
            return Revision(
                new_text=edited.render(), verdict="reject",
                issues=["negation_changed"], generator="negation_flip",
                change_reason=_reason(rng, rng.choice(["plausible", "vague"])),
                strategy=f"{source} -> {target}",
                note=f"{source} became {target}",
            ), doc.render()
        if re.search(r"\bshall\b", text, re.IGNORECASE):
            edited = doc.copy()
            apply(edited, _replace_once(text, "shall", "shall not"))
            return Revision(
                new_text=edited.render(), verdict="reject",
                issues=["negation_changed"], generator="negation_flip",
                change_reason=_reason(rng, "vague"), strategy="shall -> shall not",
            ), doc.render()
    return None


def role_swap(doc, ctx, rng):
    """Give a step to a different party already named in the section."""
    rows = _role_rows(doc)
    if len(rows) < 2:
        return None
    row = rng.choice(rows)
    others = [r.role for r in rows if r.role and r.role != row.role]

    if ("/" in row.role or " or " in row.role) and rng.random() < 0.5:
        half = re.split(r"\s*/\s*|\s+or\s+", row.role)[0].strip()
        if half and half != row.role:
            edited = doc.copy()
            edited.set_row_role(row.index, half)
            return Revision(
                new_text=edited.render(), verdict="reject",
                issues=["responsibility_changed"], generator="role_swap",
                change_reason=_reason(rng, "plausible"),
                strategy="split a combined role",
                note="combined role reduced to one party",
            ), doc.render()
    if not others:
        return None
    edited = doc.copy()
    edited.set_row_role(row.index, rng.choice(others))
    return Revision(
        new_text=edited.render(), verdict="reject",
        issues=["responsibility_changed"], generator="role_swap",
        change_reason=_reason(rng, "plausible"), strategy="swap role",
    ), doc.render()


def role_step_reassign(doc, ctx, rng):
    """Move a step to a role from elsewhere in the same document."""
    rows = _role_rows(doc)
    roles = [r for r in ctx.get("document_roles", []) if r]
    if not rows or len(roles) < 2:
        return None
    row = rng.choice(rows)
    candidates = [r for r in roles if r.lower() != row.role.lower()]
    if not candidates:
        return None
    edited = doc.copy()
    edited.set_row_role(row.index, rng.choice(candidates))
    return Revision(
        new_text=edited.render(), verdict="reject",
        issues=["responsibility_changed"], generator="role_step_reassign",
        change_reason=_reason(rng, "plausible"), strategy="reassign a step",
    ), doc.render()


def step_drop(doc, ctx, rng):
    """Remove a control step - a signature, a check, a verification."""
    control = [r for r in _editable_rows(doc)
               if re.search(r"\b(sign|signs|verif|check|approve|countersign|review)\w*\b",
                            r.body, re.IGNORECASE)]
    if not control or len(doc.rows) < 3:
        return None
    row = rng.choice(control)
    edited = doc.copy()
    edited.delete_row(row.index)
    return Revision(
        new_text=edited.render(), verdict="reject",
        issues=["requirement_removed"], generator="step_drop",
        change_reason=_reason(rng, rng.choice(["plausible", "vague"])),
        strategy="drop a control",
    ), doc.render()


def step_reorder_dependent(doc, ctx, rng):
    """Swap two steps that depend on each other."""
    numbered = [r for r in doc.rows if _STEP_NO_RE.match(r.body)]
    if len(numbered) < 3:
        return None
    index = rng.randrange(len(numbered) - 1)
    first, second = numbered[index], numbered[index + 1]
    edited = doc.copy()
    edited.swap_rows(first.index, second.index)
    return Revision(
        # A swapped sequence is a slip a reviewer sends back, not a control
        # that was removed or reversed. The rule layer still escalates it to
        # reject, so these examples are where Layer 2 has to moderate the
        # rules rather than agree with them.
        new_text=edited.render(), verdict="needs_revision",
        issues=["contradicts_manual"], generator="step_reorder_dependent",
        change_reason=_reason(rng, "vague"), edited_units=2,
        strategy="swap numbered steps",
        note="consecutive numbered steps swapped, so the sequence contradicts itself",
    ), doc.render()


def mass_deletion(doc, ctx, rng):
    """Delete the back half of a procedure table."""
    rows = doc.rows
    if len(rows) < 5:
        return None
    edited = doc.copy()
    for row in rows[len(rows) // 2:]:
        edited.delete_row(row.index)
    new_text = edited.render()
    ratio = change_ratios(doc.render(), new_text)["net_deleted_word_ratio"]
    issues = ["requirement_removed"]
    if ratio > config.THRESHOLDS["excessive_deletion_word_ratio"]:
        issues.insert(0, "excessive_deletion")
    return Revision(
        new_text=new_text, verdict="reject", issues=issues,
        generator="mass_deletion", change_reason=_reason(rng, "vague"),
        edited_units=len(rows) - len(rows) // 2, strategy="drop half the table",
    ), doc.render()


def bulk_deletion(doc, ctx, rng):
    """Cut a run of units large enough to cross the deletion threshold."""
    original = doc.render()
    if len(original.split()) < 40:
        return None

    edited = doc.copy()
    removed = 0
    if doc.has_table:
        rows = doc.rows
        if len(rows) < 3:
            return None
        start = rng.randrange(len(rows) - 1)
        for row in rows[start:]:
            edited.delete_row(row.index)
            removed += 1
    else:
        positions = [i for i, b in enumerate(edited.blocks) if b.kind == "prose"]
        if len(positions) < 2:
            return None
        start = rng.randrange(len(positions) - 1)
        for position in reversed(positions[start:]):
            edited.delete_prose(position)
            removed += 1

    new_text = edited.render()
    if not new_text.strip() or not removed:
        return None
    ratio = change_ratios(original, new_text)["net_deleted_word_ratio"]
    if not config.THRESHOLDS["excessive_deletion_word_ratio"] < ratio < 0.9:
        return None
    return Revision(
        new_text=new_text, verdict="reject",
        issues=["excessive_deletion", "requirement_removed"],
        generator="bulk_deletion", change_reason=_reason(rng, "vague"),
        edited_units=removed, strategy="cut a run",
    ), original


def foreign_insertion(doc, ctx, rng):
    """Insert material from a different document, in this section's own format.

    A five-column row dropped into a two-column table is a broken table, not an
    out-of-scope revision, so a table section takes a row of the right width and
    a prose section takes a sentence.
    """
    if doc.has_table:
        rows = doc.rows
        if not rows:
            return None
        width = len(rows[0].cells)
        foreign = [r for r in (ctx.get("foreign_rows") or []) if len(r) == width]
        if not foreign:
            return None
        edited = doc.copy()
        edited.insert_row_after(rng.choice(rows).index, list(rng.choice(foreign)))
    else:
        foreign = ctx.get("foreign_sentences") or []
        if not foreign:
            return None
        edited = doc.copy()
        edited.append_prose(rng.choice(foreign))
    return Revision(
        new_text=edited.render(), verdict="reject",
        issues=["out_of_scope_content"], generator="foreign_insertion",
        change_reason=_reason(rng, "plausible"), strategy="insert foreign material",
    ), doc.render()


def contradiction_from_context(doc, ctx, rng):
    """Change a figure here that a related section still states.

    The disagreement is the point, so the figure has to be one that survives
    elsewhere: after the edit this section says one thing and the sibling
    section still says another. A figure that appears nowhere else is only a
    changed number.
    """
    shared = ctx.get("shared_quantities") or {}
    if not shared:
        return None
    for text, apply in _shuffled(_editable_units(doc), rng):
        for quantity, where in _shuffled(list(shared.items()), rng):
            match = re.search(rf"\b{re.escape(quantity)}\b", text, re.IGNORECASE)
            if not match:
                continue
            digits = re.match(r"(\d[\d,]*)", quantity)
            if not digits:
                continue
            value = int(digits.group(1).replace(",", ""))
            replacement = quantity.replace(digits.group(1), str(_new_value(value, rng)), 1)
            changed = text[:match.start()] + replacement + text[match.end():]
            if changed == text:
                continue
            edited = doc.copy()
            apply(edited, changed)
            return Revision(
                new_text=edited.render(), verdict="reject",
                issues=["contradicts_manual", "numeric_changed"],
                generator="contradiction_from_context",
                change_reason=_reason(rng, "plausible"),
                strategy="contradict a sibling",
                note=f'"{quantity}" is still stated in {where}',
            ), doc.render()
    return None


def requirement_drop(doc, ctx, rng):
    """Remove a whole requirement sentence from a prose section."""
    candidates = [(position, text) for position, _, text in doc.sentences()
                  if len(text.split()) >= 6]
    if len(candidates) < 3:
        return None
    position, text = rng.choice(candidates)
    edited = doc.copy()
    block = edited.blocks[position]
    remaining = block.text.replace(text, "").strip()
    if remaining:
        edited.set_prose(position, re.sub(r"\s{2,}", " ", remaining))
    else:
        edited.delete_prose(position)
    return Revision(
        new_text=edited.render(), verdict="reject",
        issues=["requirement_removed"], generator="requirement_drop",
        change_reason=_reason(rng, rng.choice(["vague", "plausible"])),
        strategy="drop a requirement",
    ), doc.render()


def combo(doc, ctx, rng):
    """One revision carrying an improvement and a problem, as real ones do."""
    good = equivalent_synonym(doc, ctx, rng) or typo_fix(doc, ctx, rng)
    if not good:
        return None
    good_rev, old_text = good
    staged = SectionDoc.parse(doc.subtitle, good_rev.new_text)
    bad = (numeric_change(staged, ctx, rng) or modal_weaken_single(staged, ctx, rng)
           or role_swap(staged, ctx, rng))
    if not bad:
        return None
    bad_rev, _ = bad
    return Revision(
        new_text=bad_rev.new_text, verdict=bad_rev.verdict,
        issues=sorted(set(bad_rev.issues)), generator="combo",
        change_reason=_reason(rng, "plausible"),
        edited_units=good_rev.edited_units + bad_rev.edited_units,
        strategy=f"{good_rev.generator} + {bad_rev.generator}",
        note="an improvement and a problem in one revision",
    ), old_text


# -- registry ---------------------------------------------------

APPROVE = [typo_fix, whitespace_format, equivalent_synonym, acronym_expansion,
           spell_out_figure, legal_reference_format, cross_reference_addition,
           row_merge_reformat, step_split_reformat, benign_reorder]
NEEDS_REVISION = [non_equivalent_swap, numeric_change, modal_weaken_single,
                  partial_key_term_delete, key_term_vagueing]
REJECT = [negation_flip, role_swap, role_step_reassign, step_drop,
          step_reorder_dependent, mass_deletion, bulk_deletion,
          foreign_insertion, contradiction_from_context, requirement_drop,
          combo]

ALL = APPROVE + NEEDS_REVISION + REJECT

# Declared for reference only. What the rules genuinely cannot catch is
# measured on the built dataset by report_rule_coverage.py; a declared set
# drifts the moment a rule improves, which is how it came to claim 43% when
# the real figure was 7%.
RULE_HARD = {
    "contradiction_from_context", "foreign_insertion", "step_reorder_dependent",
    "row_merge_reformat", "step_split_reformat", "benign_reorder", "combo",
}
