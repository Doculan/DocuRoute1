"""Layer 4 - the assistive note.

Templates, not a generative model. What Layers 1-3 found is written up as a
note in four parts:

    What you changed          the change itself: kind, size, where, and the
                              exact words when they are short
    What to look at           each concern - what changed, where, why it
                              matters, what is likely to be asked, what to
                              check, and the ISO clause it touches
    What looks fine           what the rules checked and found unchanged
    What this check can't     the questions only people can answer about
    tell you                  this particular change

Properties that matter more than fluency:

* **Deterministic.** Phrasing is fixed, so the same change always produces the
  same note. The drafter and every reviewer read the same findings.
* **Grounded.** Only issues, advisories, words, figures and roles present in
  the Layer 1 and Layer 3 output, or in the two texts themselves, are
  mentioned. Nothing is invented, and "what looks fine" only repeats what the
  rules actually counted.
* **Firmness through wording.** A rule-sourced finding is a detected fact and
  is stated plainly. A model-only finding is attributed to the model, hedged
  by its confidence, and - where the rules looked for the same thing and
  found none - says so.
* **No verdict.** The verdict is computed, stored and measured, but never
  written here. It is used only to decide how much detail each concern gets,
  and how the note reads when no specific concern passed its threshold.

ISO clause relevance comes from ``iso_relevance.json``: one file, so the
clause mapping and its paraphrases can be reviewed with the QMS office
without reading code.

**The note's text format** is read by the frontend. Parts are separated by a
blank line; a part's first line is its heading (one of ``NOTE_HEADINGS``);
a line starting ``- `` opens an item; a line starting with two spaces
continues the item above it; any other line is a paragraph.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache

from . import config
from .diffing import _WORD_RE

REVIEWER = "reviewer"
SUBMITTER = "submitter"

CHANGED_YOU = "What you changed"
CHANGED = "What changed"
LOOK_AT = "What to look at"
LOOKS_FINE = "What looks fine"
CANNOT_TELL = "What this check can't tell you"
NOTE_HEADINGS = (CHANGED_YOU, CHANGED, LOOK_AT, LOOKS_FINE, CANNOT_TELL)

# Past this many concerns the rest are named in one line rather than written
# out. A note that runs to a dozen paragraphs is not read.
MAX_CONCERNS = 5
# Kept for callers that still pass it; the note is capped by MAX_CONCERNS.
MAX_SENTENCES = MAX_CONCERNS

_WS_RE = re.compile(r"\s+")
_WORDLIKE_RE = re.compile(r"\w")
_ITEM_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)(?=[\s.)]|$)")
_STEP_RE = re.compile(r"\|\s*(\d+)\.\s")
_STRAIGHT_QUOTED_RE = re.compile(r'"([^"]*)"')

_SHORT_WORDS = 12          # a change this short is quoted word for word
_QUOTABLE_LINE_WORDS = 30  # a whole line this short is quoted in full
_CONTEXT_TOKENS = 2        # unchanged words either side of a quoted edit

_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six",
                 "seven", "eight", "nine", "ten")


# -- ISO relevance -----------------------------------------------

@lru_cache(maxsize=1)
def _iso() -> dict:
    with open(config.PIPELINE_DIR / "iso_relevance.json", encoding="utf-8") as fh:
        return json.load(fh)


def clause_for(label: str) -> str:
    """The clause a concern relates to, from iso_relevance.json."""
    return _iso()["concerns"].get(label, "")


def _clause_line(label: str, seen: set) -> str:
    """The relevance line. In full the first time a clause comes up in a
    note; after that, by number, so three concerns under 7.5.3 do not repeat
    the same sentence three times."""
    clause = clause_for(label)
    asks = _iso()["clauses"].get(clause, {}).get("asks_that", "")
    if not (clause and asks):
        return ""
    if clause in seen:
        return f"This also touches clause {clause}."
    seen.add(clause)
    return (f"This touches {_iso()['standard']} clause {clause}, "
            f"which asks that {asks}.")


# -- small text helpers --------------------------------------------

def _word_count(tokens) -> int:
    return sum(1 for t in tokens if _WORDLIKE_RE.search(t))


def _number_word(count: int) -> str:
    return _NUMBER_WORDS[count] if 0 <= count < len(_NUMBER_WORDS) else str(count)


def _plural(count: int, word: str, plural: str = "") -> str:
    return f"{_number_word(count)} {word if count == 1 else (plural or word + 's')}"


def _join(items) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _quote(text: str) -> str:
    return f"“{text}”"


def _curly(text: str) -> str:
    """Layer 1 quotes its evidence with straight quotes; the note uses curly."""
    return _STRAIGHT_QUOTED_RE.sub(lambda m: _quote(m.group(1)), text or "")


def _end(sentence: str) -> str:
    """Close a sentence once: a quote that already ends in a full stop gets
    no second one after the closing mark."""
    s = (sentence or "").rstrip()
    if s.endswith(("”", '"')) and len(s) >= 2 and s[-2] in ".!?…":
        return s
    return s if s.endswith((".", "!", "?", "…")) else s + "."


def _cap(text: str) -> str:
    """Capitalise, leaving a sentence that opens on a quotation mark alone."""
    return text[:1].upper() + text[1:] if text else text


def _clip(text: str, limit: int = 160) -> str:
    text = _WS_RE.sub(" ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _tidy_line(line: str) -> str:
    """A table row reads as "Role — step", not as pipes and empty cells."""
    line = (line or "").strip()
    if "|" not in line:
        return _WS_RE.sub(" ", line)
    cells = [c.strip() for c in line.strip("|").split("|")]
    return " — ".join(c for c in cells if c)


def _item_of(line: str) -> str:
    """"3.1" for a numbered policy, "step 6" for a table row, else ""."""
    match = _ITEM_RE.match(line or "")
    if match:
        return match.group(1)
    match = _STEP_RE.search(line or "")
    return f"step {match.group(1)}" if match else ""


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:] if end == -1 else text[start:end]


def _find_ci(needle: str, text: str) -> str:
    """The needle as the text spells it, or "" when it is not there."""
    if not needle:
        return ""
    match = re.search(re.escape(needle), text or "", flags=re.IGNORECASE)
    return match.group(0) if match else ""


# -- what the two texts say changed --------------------------------

class _Change:
    """The edit read straight from the two texts: hunks, lines, places."""

    def __init__(self, old: str, new: str):
        self.old, self.new = old or "", new or ""
        a = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(self.old)]
        b = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(self.new)]
        self._a, self._b = a, b
        matcher = difflib.SequenceMatcher(
            a=[t[0].lower() for t in a], b=[t[0].lower() for t in b],
            autojunk=False,
        )
        groups = self._group(matcher.get_opcodes())
        self.hunks = [self._hunk(g, groups[k - 1] if k else None,
                                 groups[k + 1] if k + 1 < len(groups) else None)
                      for k, g in enumerate(groups)]
        self.words_removed = sum(h["removed"] for h in self.hunks)
        self.words_added = sum(h["added"] for h in self.hunks)
        self.items = []
        for hunk in self.hunks:
            if hunk["item"] and hunk["item"] not in self.items:
                self.items.append(hunk["item"])
        self._lines()

    def _group(self, opcodes):
        """Changed runs, with edits a word or two apart on one line merged:
        "365 days or 1 year" -> "180 days or 6 months" is one change to a
        reader, not two."""
        groups = []
        for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
            if tag == "equal":
                continue
            member = (tag, i1, i2, j1, j2)
            if groups and opcodes[index - 1][0] == "equal":
                previous = groups[-1]
                _, gap_start, gap_end, _, _ = opcodes[index - 1]
                start = self._a[previous["i2"] - 1][2] if previous["i2"] else 0
                end = self._a[i1][1] if i1 < len(self._a) else len(self.old)
                if (gap_end - gap_start <= 2
                        and not any(self._a[k][0] == "|" for k in range(gap_start, gap_end))
                        and "\n" not in self.old[start:end]):
                    previous["i2"], previous["j2"] = i2, j2
                    previous["members"].append(member)
                    continue
            groups.append({"i1": i1, "i2": i2, "j1": j1, "j2": j2,
                           "members": [member]})
        return groups

    # The context either side of an edit stops at a table cell, a line break
    # or the next edit, so a quoted change never drags in the neighbouring row.
    def _context(self, group, neighbour, forward):
        if forward:
            limit = neighbour["i1"] if neighbour else len(self._a)
            run = range(group["i2"], limit)
        else:
            limit = neighbour["i2"] if neighbour else 0
            run = range(group["i1"] - 1, limit - 1, -1)
        taken = 0
        for k in run:
            if self._a[k][0] == "|":
                break
            # The gap between this token and the one on the edit's side of it.
            if forward:
                gap = self.old[self._a[k - 1][2] if k else 0:self._a[k][1]]
            else:
                end = self._a[k + 1][1] if k + 1 < len(self._a) else len(self.old)
                gap = self.old[self._a[k][2]:end]
            if "\n" in gap:
                break
            taken += 1
            if taken >= _CONTEXT_TOKENS:
                break
        return taken

    def _span(self, tokens, text, lo, hi):
        if lo >= hi:
            return ""
        return text[tokens[lo][1]:tokens[hi - 1][2]]

    def _hunk(self, group, before_group, after_group):
        i1, i2, j1, j2 = group["i1"], group["i2"], group["j1"], group["j2"]
        tags = {m[0] for m in group["members"]}
        tag = tags.pop() if len(tags) == 1 else "replace"
        before = self._context(group, before_group, False)
        after = self._context(group, after_group, True)
        # Where it happened: the new text's line, unless nothing is left there.
        if j2 > j1:
            line = _line_at(self.new, self._b[j1][1])
        elif i2 > i1:
            line = _line_at(self.old, self._a[i1][1])
        else:
            line = ""
        changed_old = [t for m in group["members"] for t in self._a[m[1]:m[2]]]
        changed_new = [t for m in group["members"] for t in self._b[m[3]:m[4]]]
        return {
            "tag": tag,
            "old": self._span(self._a, self.old, i1, i2),
            "new": self._span(self._b, self.new, j1, j2),
            "old_ctx": self._span(self._a, self.old, i1 - before, i2 + after),
            "new_ctx": self._span(self._b, self.new, j1 - before, j2 + after),
            "removed": _word_count(t[0] for t in changed_old),
            "added": _word_count(t[0] for t in changed_new),
            "punctuation_only": not any(
                _WORDLIKE_RE.search(t[0]) for t in changed_old + changed_new
            ),
            "item": _item_of(line),
        }

    def _lines(self):
        """Whole lines removed or added - how a table row or policy goes."""
        old_lines = [ln for ln in self.old.splitlines() if ln.strip()]
        new_lines = [ln for ln in self.new.splitlines() if ln.strip()]
        norm = lambda ln: _WS_RE.sub(" ", ln).strip().lower()  # noqa: E731
        matcher = difflib.SequenceMatcher(
            a=[norm(ln) for ln in old_lines], b=[norm(ln) for ln in new_lines],
            autojunk=False,
        )
        self.removed_lines, self.added_lines = [], []
        self.only_whole_lines = True
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "delete":
                self.removed_lines += old_lines[i1:i2]
            elif tag == "insert":
                self.added_lines += new_lines[j1:j2]
            elif tag == "replace":
                self.only_whole_lines = False
        if not (self.removed_lines or self.added_lines):
            self.only_whole_lines = False
        # Whether "What changed" quotes the lines in full - in which case a
        # concern about them points back up rather than quoting them again.
        lines = self.removed_lines + self.added_lines
        self.lines_quotable = self.only_whole_lines and len(lines) <= 3 and all(
            len(_tidy_line(ln).split()) <= _QUOTABLE_LINE_WORDS for ln in lines
        )

    @property
    def single_item(self) -> str:
        return self.items[0] if len(self.items) == 1 else ""

    def item_of_text(self, needle: str) -> str:
        """The numbered item a quoted word sits in, where it can be found."""
        for text in (self.new, self.old):
            spelled = _find_ci(needle, text)
            if spelled:
                return _item_of(_line_at(text, text.lower().find(spelled.lower())))
        return ""


def _where(section_label: str, items) -> str:
    section = (section_label or "").strip() or "this section"
    return f"{section}, at {_join(items)}" if items else section


def _describe_change(change: _Change, layer1_result, section_label: str,
                     features: dict) -> str:
    """One or two sentences: what kind of edit, how big, where, which words."""
    where = _where(section_label, change.items)

    if not change.hunks:
        return f"A formatting change to {_where(section_label, [])}: only spacing or line breaks moved."

    if change.only_whole_lines:
        parts = []
        for verb, lines in (("Removed", change.removed_lines),
                            ("Added", change.added_lines)):
            if not lines:
                continue
            count = _plural(len(lines), "line")
            items = [i for i in (_item_of(ln) for ln in lines) if i]
            preposition = "from" if verb == "Removed" else "to"
            if change.lines_quotable:
                quoted = "; ".join(_quote(_tidy_line(ln)) for ln in lines)
                parts.append(f"{verb} {count} {preposition} "
                             f"{_where(section_label, [])}: {quoted}")
            else:
                parts.append(f"{verb} {count} {preposition} "
                             f"{_where(section_label, items)}")
        return " ".join(_end(p) for p in parts)

    total = change.words_removed + change.words_added
    lone = change.hunks[0] if len(change.hunks) == 1 else None
    if (lone and lone["tag"] == "insert" and 5 <= lone["added"] <= _QUOTABLE_LINE_WORDS
            and lone["new"].rstrip().endswith((".", "!", "?"))):
        return _end(f"An added sentence in {where}: {_quote(lone['new'].strip())}")

    short = (len(change.hunks) <= 3
             and all(h["removed"] <= _SHORT_WORDS and h["added"] <= _SHORT_WORDS
                     for h in change.hunks))

    if short:
        if layer1_result.change_type == "cosmetic":
            kind = ("A punctuation fix" if all(h["punctuation_only"] for h in change.hunks)
                    else "A spelling or formatting fix")
        elif layer1_result.change_type == "terminology_equivalent":
            kind = "A change of terms"
        else:
            kind = "A small wording edit"
        edits = []
        for hunk in change.hunks:
            shown = f"{_quote(hunk['old_ctx'])} → {_quote(hunk['new_ctx'])}"
            if len(change.items) > 1 and hunk["item"]:
                shown += f" ({hunk['item']})"
            edits.append(shown)
        return _end(f"{kind} to {where}: {'; '.join(edits)}")

    counts = _join([
        f"{_plural(change.words_removed, 'word')} removed" if change.words_removed else "",
        f"{_plural(change.words_added, 'word')} added" if change.words_added else "",
    ])
    removed_share = float(features.get("deleted_word_ratio", 0) or 0)
    added_share = float(features.get("inserted_word_ratio", 0) or 0)
    large = (removed_share >= 0.3 or added_share >= 0.3 or total > 60)
    size = "A large change" if large else "A moderate change"
    sentence = f"{size} to {where}: {counts}"
    if large and removed_share >= 0.3:
        sentence += f", about {removed_share:.0%} of the section's wording"
    return sentence + "."


# -- concerns ------------------------------------------------------

# Why each kind of concern matters to the document and to the people who use
# it. Deliberately about consequences, not about the rule that fired.
_WHY = {
    "excessive_deletion": (
        "Readers lose guidance they relied on, and whatever the removed text "
        "required stops being required unless it is stated somewhere else."
    ),
    "key_term_deleted": (
        "Other sections, forms and audits may refer to it; without it, readers "
        "may not know which form, office or rule applies."
    ),
    "modal_weakened": (
        "People following the section may now treat the step as optional, and "
        "an auditor can no longer hold the office to it."
    ),
    "negation_changed": (
        "The section now allows what it prohibited, or the reverse, so the "
        "people applying it will act the opposite way."
    ),
    "numeric_changed": (
        "Offices schedule and measure their work against this figure, and "
        "forms, systems and other sections that repeat it may now disagree."
    ),
    "responsibility_changed": (
        "The office now named takes on the work and the accountability for "
        "it; if it has not agreed, the step may go undone."
    ),
    "requirement_removed": (
        "Whatever the removed text required is no longer required by this "
        "document, and an auditor will no longer look for it."
    ),
    "non_equivalent_term": (
        "Readers may apply the new term differently from how the rest of the "
        "manual uses it, so the same rule could be read two ways."
    ),
    "contradicts_manual": (
        "Readers following one section will act differently from those "
        "following the other, and an auditor will ask which one applies."
    ),
    "out_of_scope_content": (
        "Readers looking for this rule may not find it where it belongs, and "
        "the same point may end up stated in two places."
    ),
}

# What a concurring office or the IMR is likely to ask.
_ASK = {
    "excessive_deletion": "Is everything that was removed covered somewhere else?",
    "key_term_deleted": "Is it still needed, or has something replaced it?",
    "modal_weakened": "Is this step meant to become optional, and who decides when it is skipped?",
    "negation_changed": "Is the reversal intended, and does the law or policy behind this section allow it?",
    "numeric_changed": "Where does the new figure come from: a memorandum, a policy or a law?",
    "responsibility_changed": "Has the office now named agreed to take this on?",
    "requirement_removed": "Why is this no longer required, and is it covered somewhere else?",
    "non_equivalent_term": "Is the new term meant to change what is being asked?",
    "contradicts_manual": "Which statement is correct, and will the other section change to match?",
    "out_of_scope_content": "Does this belong in this section, or in another one?",
}

_CHECK = {
    "excessive_deletion": "Compare the two versions and note where each removed requirement now lives.",
    "key_term_deleted": "Search the document and its forms for other references to it.",
    "modal_weakened": "Read the sentence as someone who would rather skip the step, and see whether it still holds.",
    "negation_changed": "Read the sentence before and after, and confirm the new meaning is the one intended.",
    "numeric_changed": "Look for other sections, forms and systems that use the same figure.",
    "responsibility_changed": "Confirm with the office now named, and look for other sections that assign the same step.",
    "requirement_removed": "Say where the requirement now lives, or state in the reason that it is being dropped.",
    "non_equivalent_term": "See how this manual uses both terms elsewhere.",
    "contradicts_manual": "Open the other section and decide which statement stands; if it is also being changed in this proposal, say so.",
    "out_of_scope_content": "See whether another section already covers it.",
}

# The questions only people can answer, per kind of concern.
_CANNOT_TELL = {
    "excessive_deletion": "Whether what was removed is covered by another manual, a memorandum or a form.",
    "requirement_removed": "Whether what was removed is covered by another manual, a memorandum or a form.",
    "key_term_deleted": "Whether the dropped term is still in use elsewhere, such as on a form or in a system.",
    "modal_weakened": "Whether the law or policy this section rests on allows the change.",
    "negation_changed": "Whether the law or policy this section rests on allows the change.",
    "numeric_changed": "Whether the new figure matches the memorandum, policy or law it comes from.",
    "responsibility_changed": "Whether the office now named has agreed, and has the people to do the work.",
    "contradicts_manual": "Which of the two statements the university actually follows.",
    "non_equivalent_term": "What the new wording is meant to change: the check reads words, not intent.",
    "out_of_scope_content": "Whether the added wording is accurate, and where readers expect to find it.",
}

# How a model-only finding is described when there are no words to quote.
_MODEL_ONLY = {
    "excessive_deletion": "that a large part of the section was removed",
    "key_term_deleted": "that a term the section depends on — a defined term, a form name or a legal reference — was dropped",
    "modal_weakened": "that an obligation was softened into a permission",
    "negation_changed": "that a negation changed, reversing what the section requires",
    "numeric_changed": "that a figure, deadline or amount changed",
    "responsibility_changed": "that the party responsible for a step changed",
    "requirement_removed": "that a required step was removed",
    "non_equivalent_term": "that a term was replaced with one that means something different in this manual",
    "contradicts_manual": "that the change conflicts with another section of this document",
    "out_of_scope_content": "that the added wording goes beyond what this section covers",
}

# Where the rules look for the same thing the model reports. When they looked
# and found nothing, that is worth saying: it is a finding too.
_RULE_COUNTERPART = {
    "negation_changed": ("negation_changed",
                         "no “not”, “no” or “never” was added or removed"),
    "numeric_changed": ("numeric_changed_count", "no figure changed"),
    "modal_weakened": ("modal_weakened_count",
                       "no “shall”, “must” or “should” gave way to “may” or “can”"),
    "key_term_deleted": ("key_terms_deleted_count",
                         "no listed term, form name or legal reference is missing from the new text"),
    "responsibility_changed": ("role_terms_changed_count",
                               "no named role was added or removed"),
    "requirement_removed": ("sentences_removed",
                            "no sentence of the old text is missing from the new one"),
}

# How the leftover concerns are named when MAX_CONCERNS is reached.
_SHORT_NAME = {
    "excessive_deletion": "a large removal",
    "key_term_deleted": "a dropped term",
    "modal_weakened": "a softened obligation",
    "negation_changed": "a changed negation",
    "numeric_changed": "a changed figure",
    "responsibility_changed": "a change of responsibility",
    "requirement_removed": "a removed requirement",
    "non_equivalent_term": "a non-equivalent term",
    "contradicts_manual": "a conflict with another section",
    "out_of_scope_content": "content outside the section's scope",
}


def _model_strength(confidence: float) -> str:
    if confidence > 0.85:
        return "The check's model strongly suspects"
    if confidence > 0.65:
        return "The check's model suspects"
    return "The check's model sees a possibility"


def _doubt(issue: dict, features: dict) -> str:
    """For a model-only concern the rules looked for and did not find."""
    if issue.get("source") != "model":
        return ""
    label = issue["label"]
    if label == "excessive_deletion":
        share = float(features.get("net_deleted_word_ratio", 0) or 0)
        if share < config.THRESHOLDS["excessive_deletion_word_ratio"]:
            return (f"The rule check measured {share:.0%} of the wording as removed, "
                    "so this may be a false lead.")
        return ""
    counterpart = _RULE_COUNTERPART.get(label)
    if counterpart and not features.get(counterpart[0]):
        return f"The rule check found that {counterpart[1]}, so this may be a false lead."
    return ""


def _placed(item: str, clause: str) -> str:
    """"At 3.1, <clause>." - the place first, so a sentence never has to open
    on a lower-case quotation."""
    if item:
        return _end(f"At {item}, {clause}")
    if clause.startswith("“"):
        return _end(f"In this section, {clause}")
    return _end(_cap(clause))


def _removed_requirements(issue: dict, change: _Change):
    """(count, quotes) for a removed requirement.

    Whole removed lines are used when Layer 1's sentence split left something
    unreadable - a table row reaches it as "| | 4." - and their count
    replaces the sentence count, which a table row inflates. When "What
    changed" already quotes those lines, nothing is quoted twice.
    """
    evidence = (issue.get("evidence") or "").strip()
    if change.removed_lines and (
            _word_count(_WORD_RE.findall(evidence)) < 3 or change.only_whole_lines):
        quotes = ([] if change.lines_quotable
                  else [_clip(_tidy_line(ln), 140) for ln in change.removed_lines[:2]])
        return len(change.removed_lines), quotes
    # Layer 1 cuts its evidence at 160 characters; finish it from the text.
    full = next((ln for ln in change.old.splitlines()
                 if evidence[:40] and evidence[:40] in ln), "")
    text = _tidy_line(full) if full and len(evidence) >= 160 else evidence
    return int(issue.get("count") or 1), [_clip(text)] if text else []


def _lead(issue: dict, change: _Change) -> str:
    """What changed and where, from the evidence Layer 1 recorded."""
    label = issue["label"]
    if issue.get("source") == "model":
        return (f"{_model_strength(float(issue.get('confidence', 0.5)))} "
                f"{_MODEL_ONLY[label]}, though it found no specific words to point to.")

    evidence = _curly(issue.get("evidence") or "")
    item = change.single_item

    if label == "excessive_deletion":
        ratio = issue.get("ratio")
        share = f"{float(ratio):.0%}" if isinstance(ratio, (int, float)) else "A large part"
        return f"{share} of the section's wording was removed."

    if label == "key_term_deleted":
        terms = issue.get("terms") or [issue.get("evidence")]
        named = _join([_quote(t) for t in terms[:3] if t])
        verb = "no longer appears" if len(terms) == 1 else "no longer appear"
        return _placed("", f"{named} {verb} in the section")

    if label == "modal_weakened":
        pairs = issue.get("pairs") or []
        if pairs:
            said = _join([f"{_quote(a)} became {_quote(b)}" for a, b in pairs[:3]])
            item = change.item_of_text(pairs[0][1]) or item
        else:
            said = evidence or "an obligation became a permission"
        return _placed(item, f"{said}, so a requirement becomes a permission")

    if label == "negation_changed":
        action = issue.get("action")
        if action in ("added", "removed"):
            words = issue.get(action) or []
            named = _join([_quote(w) for w in words[:3]]) or evidence
            verb = "was" if len(words) <= 1 else "were"
            item = (change.item_of_text(words[0]) if words else "") or item
            return _placed(item, f"{named} {verb} {action}, which reverses "
                                 "what the sentence requires")
        said = evidence or "a negation changed"
        return _placed(item, f"{said}, which reverses the sense of the requirement")

    if label == "numeric_changed":
        from_text = _curly(issue.get("from_text") or "")
        to_text = _curly(issue.get("to_text") or "")
        direction = issue.get("direction")
        if from_text and to_text:
            return _placed(item, f"a figure changed: {from_text} became {to_text}")
        if direction == "added" and to_text:
            return _placed(item, f"a figure was added: {to_text}")
        if direction == "removed" and from_text:
            return _placed(item, f"a figure was removed: {from_text}")
        return _placed(item, f"a figure changed: {evidence}")

    if label == "responsibility_changed":
        roles = issue.get("roles") or [r.strip() for r in (issue.get("evidence") or "").split(",")]
        gone, came = [], []
        for role in roles:
            in_old, in_new = _find_ci(role, change.old), _find_ci(role, change.new)
            if in_old and not in_new:
                gone.append(in_old)
            elif in_new and not in_old:
                came.append(in_new)
        if gone and came:
            return _placed(item, f"{_join(gone)} is no longer named; "
                                 f"{_join(came)} is named instead")
        if gone:
            return _placed(item, f"{_join(gone)} is no longer named")
        if came:
            return _placed(item, f"{_join(came)} is now named")
        named = _join([_quote(r) for r in roles[:3]])
        return _placed(item, f"a step changed hands ({named})")

    if label == "requirement_removed":
        count, quotes = _removed_requirements(issue, change)
        head = ("A requirement no longer appears" if count == 1
                else _cap(_plural(count, "requirement")) + " no longer appear")
        if quotes:
            return _end(f"{head}: {'; '.join(_quote(q) for q in quotes)}")
        if change.lines_quotable and change.removed_lines:
            return f"{head}: {'it is' if count == 1 else 'they are'} the "\
                   f"{'line' if count == 1 else 'lines'} removed above."
        return f"{head} in the section."

    if label == "non_equivalent_term":
        swaps = issue.get("swaps") or []
        said = (_join([f"{_quote(a)} became {_quote(b)}" for a, b in swaps[:3]])
                if swaps else evidence)
        return _placed(item, f"{said}; this manual does not treat them as "
                             "meaning the same")

    if label == "contradicts_manual":
        conflicts = issue.get("conflicts") or []
        values = _join([_quote(str(c.get("value"))) for c in conflicts[:3]]) or evidence
        return (f"Another section of this document still uses {values}, which this "
                "change replaces here.")

    if label == "out_of_scope_content":
        return _placed(item, "the added wording may go beyond what this section covers")

    return _end(evidence)


def _concern_item(issue: dict, change: _Change, features: dict, full: bool,
                  to_submitter: bool, seen: set) -> list:
    """One item under "What to look at": a lead line and its detail lines."""
    label = issue["label"]
    doubt = _doubt(issue, features)
    first = _lead(issue, change)
    if doubt:
        first = f"{first} {doubt}"
    else:
        first = f"{first} {_WHY[label]}"

    lines = [first]
    if full and not doubt:
        prefix = "Expect to be asked: " if to_submitter else "Worth asking the drafting office: "
        lines.append(prefix + _ASK[label])
        lines.append("To check: " + _CHECK[label])
    clause = _clause_line(label, seen)
    if clause:
        lines.append(clause)
    return lines


def _hard_fail_item(fail: dict, seen: set) -> list:
    detail = (fail.get("detail") or "").strip()
    lines = [detail if detail.endswith(".") else detail + "."]
    if fail.get("reason") == "no_change_reason":
        lines[0] += (" The reason is the record that the change was planned, and the "
                     "first thing a reviewer or auditor reads.")
    clause = _clause_line(fail.get("reason", ""), seen)
    if clause:
        lines.append(clause)
    return lines


def _advisory_item(advisory: dict, seen: set) -> list:
    label = advisory.get("label", "")
    evidence = _curly(advisory.get("evidence") or "")
    if label == "vague_change_reason":
        lead = ("The reason given is too general to show what prompted the change "
                "or what it is meant to achieve.")
        if evidence:
            lead += f" {evidence.rstrip('.')}."
    elif label == "malformed_citation":
        lead = f"A legal reference looks broken after the edit: {_clip(evidence, 120)}."
    elif label == "malformed_text":
        lead = f"The edit left text that looks broken: {_clip(evidence, 120)}."
    else:
        return []
    lines = [lead]
    clause = _clause_line(label, seen)
    if clause:
        lines.append(clause)
    return lines


def _ordered(issues: list, features: dict) -> list:
    """Layer 3's order - most severe, then most confident - with model-only
    concerns the rules could not corroborate moved to the end."""
    firm = [i for i in issues if not _doubt(i, features)]
    doubtful = [i for i in issues if _doubt(i, features)]
    return firm + doubtful


# -- what looks fine and what cannot be told ---------------------------

_UNCHANGED = (
    # (feature, concern labels that would contradict it, wording)
    ("numeric_changed_count", {"numeric_changed", "contradicts_manual"}, "figure"),
    ("modal_weakened_count", {"modal_weakened"}, "obligation"),
    ("role_terms_changed_count", {"responsibility_changed", "contradicts_manual"}, "named role"),
)


def _looks_fine(layer1_result, labels: set, change: _Change, features: dict,
                no_concerns: bool) -> list:
    lines = []
    if no_concerns:
        lines.append("No specific concern passed its threshold.")

    if layer1_result.change_type == "cosmetic":
        lines.append("Nothing the section requires has changed; the edit touches "
                     "spelling, punctuation or layout only.")
        return lines
    if layer1_result.change_type == "terminology_equivalent":
        swaps = getattr(layer1_result, "equivalent_swaps", None) or []
        if swaps:
            named = _join([f"{_quote(a)} and {_quote(b)}" for a, b in swaps[:3]])
            lines.append(f"{named} mean the same thing in this manual, so the "
                         "requirement is unchanged.")
        else:
            lines.append("The terms swapped mean the same thing in this manual, so "
                         "the requirement is unchanged.")
        return lines

    unchanged = [word for feature, contradicting, word in _UNCHANGED
                 if not features.get(feature) and not (labels & contradicting)]
    if unchanged:
        lines.append(f"No {_join(unchanged).replace(' and ', ' or ')} changed.")
    if (not change.words_removed and not features.get("sentences_removed")
            and not labels & {"requirement_removed", "excessive_deletion"}):
        lines.append("Nothing was removed.")
    return lines


def _cannot_tell(labels: list, change: _Change, layer1_result) -> list:
    lines = []
    for label in labels:
        line = _CANNOT_TELL.get(label)
        if line and line not in lines:
            lines.append(line)
    if (not lines and change.words_added
            and layer1_result.change_type not in ("cosmetic", "terminology_equivalent")):
        what = "added" if not change.words_removed else "new"
        lines.append(f"Whether the {what} wording is accurate: the check compares "
                     "wording, not facts.")
    return lines[:3]


# -- main entry point ------------------------------------------------

def explain(fusion_result, layer1_result, section_label: str = "",
            revision_id=None, max_sentences: int = MAX_SENTENCES,
            seed=None, audience: str = REVIEWER,
            old_text: str = None, new_text: str = None) -> str:
    """The assistive note for one change.

    ``audience`` selects who is addressed: the drafting office (SUBMITTER)
    or the offices and QMS staff reviewing it (REVIEWER). The findings, their
    evidence and their clauses are identical either way.

    ``old_text`` and ``new_text`` let the note say where the change is and
    quote it. Without them it still renders, from the marked text alone.

    ``revision_id``, ``seed`` and ``max_sentences`` are accepted for older
    callers. The phrasing is fixed, so there is nothing left to seed.
    """
    to_submitter = audience == SUBMITTER
    features = dict(getattr(layer1_result, "features", {}) or {})
    if old_text is None and new_text is None:
        old_text, new_text = _texts_from_marked(getattr(layer1_result, "marked", ""))
    change = _Change(old_text or "", new_text or "")

    verdict = fusion_result.verdict
    issues = _ordered(list(fusion_result.issues or []), features)
    labels = {i["label"] for i in issues}
    # The verdict decides emphasis only: when the fused reading is that the
    # change needs work, every concern gets its question and what to check;
    # otherwise only the first does.
    full_detail = verdict in ("reject", "needs_revision")

    items, seen = [], set()
    for fail in getattr(layer1_result, "hard_fails", []) or []:
        items.append(_hard_fail_item(fail, seen))
    shown, rest = issues[:MAX_CONCERNS], issues[MAX_CONCERNS:]
    for index, issue in enumerate(shown):
        if issue.get("label") not in _WHY:
            continue
        items.append(_concern_item(
            issue, change, features, full=full_detail or index == 0,
            to_submitter=to_submitter, seen=seen,
        ))
    if rest:
        named = _join([_SHORT_NAME.get(i["label"], i["label"].replace("_", " "))
                       for i in rest[:3]])
        items.append([f"Also noted: {named}."])
    for advisory in getattr(fusion_result, "advisories", None) or []:
        item = _advisory_item(advisory, seen)
        if item:
            items.append(item)

    parts = [[CHANGED_YOU if to_submitter else CHANGED,
              _describe_change(change, layer1_result, section_label, features)]]

    no_concerns = not items
    if items:
        block = [LOOK_AT]
        for item in items:
            block.append("- " + item[0])
            block.extend("  " + line for line in item[1:])
        parts.append(block)
    elif verdict != "approve":
        # Nothing passed a threshold, yet the fused reading was not settled.
        # Said once, in words, without the label.
        parts.append([LOOK_AT,
                      "No specific concern passed its threshold, but the check's "
                      "overall reading of this change was less settled than that "
                      "suggests. It is worth reading once more against what the "
                      "section is for."])
        no_concerns = False

    fine = _looks_fine(layer1_result, labels, change, features, no_concerns)
    if fine:
        parts.append([LOOKS_FINE] + fine)

    cannot = _cannot_tell([i["label"] for i in shown if not _doubt(i, features)],
                          change, layer1_result)
    if cannot:
        parts.append([CANNOT_TELL] + ["- " + line for line in cannot])

    return "\n\n".join("\n".join(part) for part in parts)


def _texts_from_marked(marked: str):
    """Rebuild approximate old and new texts from Layer 1's marked text, for
    callers that do not pass the originals."""
    old, new, mode = [], [], None
    for token in (marked or "").split():
        if token in ("[DEL]", "[INS]"):
            mode = token
        elif token in ("[/DEL]", "[/INS]"):
            mode = None
        elif mode == "[DEL]":
            old.append(token)
        elif mode == "[INS]":
            new.append(token)
        else:
            old.append(token)
            new.append(token)
    return " ".join(old), " ".join(new)


def not_assessed_message(section_label: str = "") -> str:
    """Decision 9: List of Forms sections are not assessed by the model."""
    what = section_label or "This section"
    return (f"Not checked: {what} is a list of forms rather than a requirement, "
            "so the check does not assess it.")


# -- notes written before this format -------------------------------------

# The openings and closings the previous Layer 4 wrote. Stored snapshots are
# never re-run, so notes saved before this format still carry them; the API
# removes them on the way out, so no screen shows a verdict. The stored text
# itself is left as it was.
_LEGACY_VERDICT_SENTENCES = (
    "This revision looks acceptable.",
    "No blocking problems were found in this revision.",
    "This change appears safe to approve.",
    "This revision needs changes before it can be approved.",
    "This revision should be sent back for adjustment.",
    "Some points need addressing before this revision is approved.",
    "This revision should not be approved as written.",
    "This revision changes the requirement and should be rejected.",
    "This revision cannot be accepted in its current form.",
    "This looks ready to submit.",
    "No blocking problems were found in your change.",
    "This change appears fine to submit.",
    "This would likely be sent back for changes.",
    "A reviewer would probably ask for changes before approving this.",
    "This would likely need adjusting before it is approved.",
    "This would likely be rejected as written.",
    "A reviewer would probably not approve this as written.",
    "This change would likely be turned down in its current form.",
    "You can go ahead and submit.",
    "You can still submit - the reviewer decides, not this check.",
    "Please confirm before approving.",
    "Please check these points before approving.",
    "Please check these points before deciding.",
)
_LEGACY_WITH_CONCERNS_RE = re.compile(
    r"(No blocking problems were found, but|This revision looks broadly acceptable, though"
    r"|Nothing here blocks approval, but|This looks broadly fine, though"
    r"|Nothing here would block approval, but)"
    r" (one point is|\w+ points are) worth [^.]*\."
)


def is_note(text: str) -> bool:
    """True for a note in this format, as opposed to an older paragraph."""
    first = (text or "").lstrip().split("\n", 1)[0].strip()
    return first in NOTE_HEADINGS or (text or "").startswith("Not checked:")


def without_legacy_verdict(text: str) -> str:
    """An older explanation with its verdict sentences taken out.

    Only exact sentences the previous writer produced are removed, so a note
    in the current format, or any other text, passes through unchanged.
    """
    if not text or is_note(text):
        return text or ""
    out = _LEGACY_WITH_CONCERNS_RE.sub("", text)
    for sentence in _LEGACY_VERDICT_SENTENCES:
        out = out.replace(sentence, "")
    return _WS_RE.sub(" ", out).strip()
