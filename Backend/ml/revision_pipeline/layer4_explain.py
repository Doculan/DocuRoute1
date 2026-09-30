"""Layer 4 - the assistive note, written from layer4_wording.yaml.

Every sentence comes from the wording file; this module only chooses and
fills. What it may say is limited to what Layers 1-3 found, the two texts,
and the context the caller passes (the change reason, the retrieved
sections, the other sections changed in the same proposal). It never runs
a check and never changes anything upstream.

How a note is built (the file's `selection` section):

    significance tier -> plan -> blocks -> paragraphs

* **Tier**: one per note, first match wins (blocking ... plain).
* **Firmness** per concern: stated (a rule found it), suggested (the model
  did, and the rules have nothing to say against it), quiet (the model did,
  and the rules looked for the same thing and found none).
* **Plan**: an ordered list of paragraphs, each a list of blocks (OPEN,
  LEAD1, WHY1, ISO, FINE, CLOSE, ...). Blocks with nothing to say are
  dropped; a paragraph left empty is dropped.
* **Rotation**: every pool of interchangeable wording is rotated, never
  sampled. The least recently used variant wins, looking first at the other
  sections of the same proposal and then at the same user's recent notes;
  ties break on a hash of the content. The choices are returned with the
  note, stored with it, and read back as the history for later notes. Same
  inputs and same history give the same note.

The note is plain prose: paragraphs separated by one blank line, nothing
else. Notes stored in the earlier heading format are still recognised by
``is_note``; notes older than that lose their verdict sentences on the way
out through ``without_legacy_verdict``.
"""

from __future__ import annotations

import difflib
import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path

from . import config
from .diffing import _WORD_RE

REVIEWER = "reviewer"
SUBMITTER = "submitter"
_VOICE = {SUBMITTER: "drafter", REVIEWER: "reader"}

WORDING_FILE = Path(__file__).parent / "layer4_wording.yaml"

# Headings of the previous note format. Notes stored in it are never
# rewritten, so the screen and ``is_note`` still recognise them.
CHANGED_YOU = "What you changed"
CHANGED = "What changed"
LOOK_AT = "What to look at"
LOOKS_FINE = "What looks fine"
CANNOT_TELL = "What this check can't tell you"
NOTE_HEADINGS = (CHANGED_YOU, CHANGED, LOOK_AT, LOOKS_FINE, CANNOT_TELL)

MAX_CONCERNS = 2            # selection.emphasis: at most two written in full
MAX_SENTENCES = MAX_CONCERNS  # accepted from older callers
HISTORY_LIMIT = 20          # selection.rotation: the same user's last 20 notes

TIERS = ("blocking", "serious", "notable", "tentative", "minor", "trivial",
         "unclear", "plain")
_CLOSING_WEIGHT = {"trivial": "light", "plain": "light", "minor": "minor",
                   "unclear": "moderate", "tentative": "moderate", "notable": "moderate",
                   "serious": "strong", "blocking": "strong"}

# Drafter-only wording is marked in the file itself (`drafter_only` lists,
# pools split by voice). As a last guard, the reader is never addressed as
# the one who made the change when a neutral variant exists.
_SECOND_PERSON_RE = re.compile(r"\byou(?:[’']ve|[’']ll|r)?\b", re.IGNORECASE)

# Blocks that carry a concern or an advisory: a contrast word ("That said,")
# may follow only these, never a neutral description of the change.
# A quiet line is not one: it says there is likely nothing to act on.
_FINDING_BLOCKS = re.compile(r"^(LEAD|WHY|ASK|CHECK)\d$|^(ADVISORIES|ISO)$")

# Slots that may legitimately be empty; every other slot must be filled or
# the variant is not eligible.
_OPTIONAL_SLOTS = {"at_item", "at_item_tail", "share_clause", "s"}
_SLOT_RE = re.compile(r"\{(\w+)\}")

_WS_RE = re.compile(r"\s+")
_WORDLIKE_RE = re.compile(r"\w")
_ITEM_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)(?=[\s.)]|$)")
_STEP_RE = re.compile(r"\|\s*(\d+)\.\s")
_STRAIGHT_QUOTED_RE = re.compile(r'"([^"]*)"')
_ROW_RE = re.compile(r"^\|.*\|$")
_SEP_RE = re.compile(r"^\|?\s*:?-{2,}")

_SHORT_WORDS = 12
_QUOTABLE_LINE_WORDS = 30
_CONTEXT_WORDS = 2
_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven",
                 "eight", "nine", "ten")


@lru_cache(maxsize=1)
def wording() -> dict:
    import yaml
    with open(WORDING_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def clause_for(label: str) -> str:
    """The ISO clause a concern or advisory relates to (iso.concern_clause)."""
    return str(wording()["iso"]["concern_clause"].get(label, ""))


# -- small text helpers -----------------------------------------------------

def _number_word(count: int) -> str:
    return _NUMBER_WORDS[count] if 0 <= count < len(_NUMBER_WORDS) else str(count)


def _quote(text: str) -> str:
    return f"“{text}”"


def _join(items) -> str:
    """list_rule: "a, b and c"; past max_before_others, "a, b, c and two others"."""
    items = [i for i in items if i]
    limit = int(wording()["list_rule"].get("max_before_others", 3))
    if len(items) > limit + 1:
        rest = len(items) - limit
        items = items[:limit] + [f"{_number_word(rest)} others"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _join_or(items) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _quoted_list(values) -> str:
    return _join([_quote(v) for v in values if v])


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text and text[:1].isalpha() else text


def _uncap(text: str) -> str:
    return text[:1].lower() + text[1:] if text and text[:1].isalpha() else text


def _clip(text: str, limit: int = 160) -> str:
    text = _WS_RE.sub(" ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _find_ci(needle: str, text: str) -> str:
    if not needle:
        return ""
    m = re.search(re.escape(needle), text or "", flags=re.IGNORECASE)
    return m.group(0) if m else ""


def _item_of(line: str) -> str:
    m = _ITEM_RE.match(line or "")
    if m:
        return m.group(1)
    m = _STEP_RE.search(line or "")
    return f"step {m.group(1)}" if m else ""


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:] if end == -1 else text[start:end]


def _tidy_row(line: str, text: str = "") -> str:
    """A table row as "Role — step". A continuation row, whose role cell is
    empty, takes the role from the nearest row above it that names one."""
    line = (line or "").strip()
    if "|" not in line:
        return _WS_RE.sub(" ", line)
    cells = [c.strip() for c in line.strip("|").split("|")]
    role, rest = (cells[0], cells[1:]) if len(cells) > 1 else ("", cells)
    if not role and text:
        rows = [ln.strip() for ln in text.splitlines()]
        if line in rows:
            for above in reversed(rows[:rows.index(line)]):
                if not _ROW_RE.match(above) or _SEP_RE.match(above):
                    continue
                first = above.strip("|").split("|")[0].strip()
                if first and first.lower() != "responsibility":
                    role = first
                    break
    body = " ".join(c for c in rest if c)
    return f"{role} — {body}" if role else body


def _straight_to_items(text: str) -> list:
    return _STRAIGHT_QUOTED_RE.findall(text or "") or ([text] if text else [])


def _stable_hash(*parts) -> int:
    return int(hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12], 16)


# -- what the two texts say changed ------------------------------------------------

class _Change:
    """The edit read straight from the two texts: hunks, lines, places."""

    def __init__(self, old: str, new: str):
        self.old, self.new = old or "", new or ""
        a = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(self.old)]
        b = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(self.new)]
        self._a, self._b = a, b
        matcher = difflib.SequenceMatcher(
            a=[t[0].lower() for t in a], b=[t[0].lower() for t in b], autojunk=False)
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
        """Changed runs, with edits a word or two apart on one line merged."""
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
            groups.append({"i1": i1, "i2": i2, "j1": j1, "j2": j2, "members": [member]})
        return groups

    def _context(self, tokens, text, lo, hi, limit_lo, limit_hi, forward):
        """How many unchanged tokens to take on one side: up to two, stopping
        at a table cell, a line break or the next edit."""
        taken = 0
        run = range(hi, limit_hi) if forward else range(lo - 1, limit_lo - 1, -1)
        for k in run:
            if tokens[k][0] == "|":
                break
            if forward:
                gap = text[tokens[k - 1][2] if k else 0:tokens[k][1]]
            else:
                end = tokens[k + 1][1] if k + 1 < len(tokens) else len(text)
                gap = text[tokens[k][2]:end]
            if "\n" in gap:
                break
            taken += 1
            if taken >= _CONTEXT_WORDS:
                break
        return taken

    @staticmethod
    def _snap(text: str, start: int, end: int) -> str:
        """The span, widened to whole whitespace-delimited chunks without
        crossing a line break or a table cell - so an item number is never
        cut, and "1.1" is never quoted as ".1"."""
        while start > 0 and not text[start - 1].isspace() and text[start - 1] != "|":
            start -= 1
        while end < len(text) and not text[end].isspace() and text[end] != "|":
            end += 1
        return _WS_RE.sub(" ", text[start:end]).strip()

    def _side(self, tokens, text, lo, hi, before, after):
        a, b = max(0, lo - before), min(len(tokens), hi + after)
        if a >= b:
            return ""
        return self._snap(text, tokens[a][1], tokens[b - 1][2])

    def _hunk(self, group, before_group, after_group):
        i1, i2, j1, j2 = group["i1"], group["i2"], group["j1"], group["j2"]
        tags = {m[0] for m in group["members"]}
        tag = tags.pop() if len(tags) == 1 else "replace"
        if j2 > j1:
            line = _line_at(self.new, self._b[j1][1])
        elif i2 > i1:
            line = _line_at(self.old, self._a[i1][1])
        else:
            line = ""
        changed_old = [t for m in group["members"] for t in self._a[m[1]:m[2]]]
        changed_new = [t for m in group["members"] for t in self._b[m[3]:m[4]]]
        # Context is counted on the old side and taken equally on both, so
        # the two quotes line up word for word.
        before = self._context(self._a, self.old, i1, i2,
                               before_group["i2"] if before_group else 0, None, False)
        after = self._context(self._a, self.old, i1, i2, None,
                              after_group["i1"] if after_group else len(self._a), True)
        return {
            "tag": tag,
            "old": self.old[self._a[i1][1]:self._a[i2 - 1][2]] if i2 > i1 else "",
            "new": self.new[self._b[j1][1]:self._b[j2 - 1][2]] if j2 > j1 else "",
            "old_ctx": self._side(self._a, self.old, i1, i2, before, after),
            "new_ctx": self._side(self._b, self.new, j1, j2, before, after),
            "removed": sum(1 for t in changed_old if _WORDLIKE_RE.search(t[0])),
            "added": sum(1 for t in changed_new if _WORDLIKE_RE.search(t[0])),
            "punctuation_only": not any(
                _WORDLIKE_RE.search(t[0]) for t in changed_old + changed_new),
            "item": _item_of(line),
        }

    def _lines(self):
        old_lines = [ln for ln in self.old.splitlines() if ln.strip()]
        new_lines = [ln for ln in self.new.splitlines() if ln.strip()]
        norm = lambda ln: _WS_RE.sub(" ", ln).strip().lower()  # noqa: E731
        matcher = difflib.SequenceMatcher(
            a=[norm(ln) for ln in old_lines], b=[norm(ln) for ln in new_lines], autojunk=False)
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
        lines = self.removed_lines + self.added_lines
        self.lines_quotable = self.only_whole_lines and len(lines) <= 3 and all(
            len(_tidy_row(ln).split()) <= _QUOTABLE_LINE_WORDS for ln in lines)

    @property
    def single_item(self) -> str:
        return self.items[0] if len(self.items) == 1 else ""

    def item_of_text(self, needle: str) -> str:
        for text in (self.new, self.old):
            spelled = _find_ci(needle, text)
            if spelled:
                return _item_of(_line_at(text, text.lower().find(spelled.lower())))
        return ""


# -- rotation -------------------------------------------------------------------------

class _Picker:
    """Chooses from pools by rotation, and records what it chose.

    ``history`` is a list of earlier choice records, most relevant first:
    the other sections of the same proposal, then the user's recent notes.
    A variant never used anywhere in it beats one used long ago, which beats
    one used recently; ties break on a hash of the content key.
    """

    def __init__(self, history, key: str, voice: str):
        self.history = [h for h in (history or []) if isinstance(h, dict)]
        self.key = key
        self.voice = voice
        self.chosen: dict = {}

    def _last_used(self, pool: str, index: int) -> float:
        if index in self.chosen.get(pool, []):
            return -1.0
        for position, record in enumerate(self.history):
            if index in (record.get("pools") or {}).get(pool, []):
                return float(position)
        return math.inf

    def pick(self, pool: str, candidates: list):
        """``candidates``: [(index, rendered text)]. Returns the text."""
        if not candidates:
            return None
        best = max(candidates, key=lambda c: (self._last_used(pool, c[0]),
                                              -_stable_hash(self.key, pool, c[0])))
        self.chosen.setdefault(pool, []).append(best[0])
        return best[1]


# -- filling templates ---------------------------------------------------------------

def _tidy_sentence(text: str) -> str:
    text = _WS_RE.sub(" ", text).strip()
    text = text.replace(" ,", ",").replace(" .", ".").replace(" :", ":").replace(" ;", ";")
    for mark in (".", "?", "!"):
        text = text.replace(f"{mark}”.", f"{mark}”")
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)
    return text


def _fill(template: str, slots: dict):
    """The template with its slots filled, or None when a required slot is
    missing - that variant is then not eligible."""
    missing = []

    def repl(m):
        name = m.group(1)
        value = slots.get(name)
        if value is None or (value == "" and name not in _OPTIONAL_SLOTS):
            missing.append(name)
            return ""
        return str(value)

    out = _SLOT_RE.sub(repl, template)
    return None if missing else _tidy_sentence(out)


class _Writer:
    """Picks and fills from one pool at a time, for one voice."""

    def __init__(self, picker: _Picker, voice: str):
        self.picker, self.voice = picker, voice
        self.unfilled: set = set()     # pools with no fillable variant, for reporting

    def say(self, pool: str, variants, slots: dict, allow=None):
        if isinstance(variants, str):
            variants = [variants]
        candidates = []
        for index, template in enumerate(variants or []):
            if allow is not None and not allow(index, template):
                continue
            text = _fill(template, slots)
            if text is not None:
                candidates.append((index, text))
        if self.voice == "reader":
            neutral = [c for c in candidates if not _SECOND_PERSON_RE.search(c[1])]
            candidates = neutral or candidates
        if not candidates and variants:
            self.unfilled.add(pool)
        return self.picker.pick(pool, candidates)


# -- the note for one section -----------------------------------------------------------

class _Section:
    """Everything the note may draw on, for one section, with the slots
    common to all of it."""

    def __init__(self, fusion_result, layer1_result, section_label, old_text, new_text,
                 change_reason, related_sections, proposal_sections, document_title):
        self.fusion, self.layer1 = fusion_result, layer1_result
        self.features = dict(getattr(layer1_result, "features", {}) or {})
        self.flags = list(getattr(layer1_result, "flags", []) or [])
        self.hard_fails = list(getattr(layer1_result, "hard_fails", []) or [])
        self.advisories = list(getattr(fusion_result, "advisories", None)
                               or getattr(layer1_result, "advisories", []) or [])
        self.change_type = getattr(layer1_result, "change_type", "substantive")
        self.verdict = getattr(fusion_result, "verdict", None)
        self.section = (section_label or "").strip() or "this section"
        self.change = _Change(old_text or "", new_text or "")
        self.reason = change_reason or ""
        self.related = [(str(label), text or "") for label, text in (related_sections or [])]
        self.proposal = [dict(p) for p in (proposal_sections or [])]
        self.document = (document_title or "").strip()

    # places -----------------------------------------------------------------
    def place(self, item: str) -> dict:
        item = item or ""
        at = f"at {item}" if item else ""
        return {"section": self.section, "doc": self.document, "item": item,
                "at_item": at, "at_item_cap": _cap(at), "at_item_tail": f" {at}" if at else "",
                "where": f"{item} of {self.section}" if item else self.section}

    def flag(self, label: str):
        return next((f for f in self.flags if f.get("label") == label), None)

    def other_with(self, value: str):
        """The retrieved section that still states ``value``, if any."""
        needle = _WS_RE.sub(" ", str(value)).strip().lower()
        for label, text in self.related:
            if needle and needle in _WS_RE.sub(" ", text).lower():
                return label
        return ""

    def changed_in_proposal(self, label: str):
        return next((p for p in self.proposal if p.get("label") == label), None)


def _firmness(issue: dict, features: dict) -> str:
    if issue.get("source") in ("rule", "both"):
        return "stated"
    label = issue.get("label")
    counterpart = wording()["selection"]["firmness"]["rule_counterpart"].get(label)
    if not counterpart:
        return "suggested"
    value = float(features.get(counterpart, 0) or 0)
    if label == "excessive_deletion":
        return "quiet" if value < config.THRESHOLDS["excessive_deletion_word_ratio"] else "suggested"
    return "quiet" if value == 0 else "suggested"


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _ordered_concerns(ctx: _Section):
    """stated high -> stated medium -> suggested; quiet ones apart."""
    full, quiet = [], []
    for issue in list(getattr(ctx.fusion, "issues", None) or []):
        if issue.get("label") not in wording()["concerns"]:
            continue
        firm = _firmness(issue, ctx.features)
        (quiet if firm == "quiet" else full).append((firm, issue))
    full.sort(key=lambda c: (c[0] != "stated", _SEVERITY_ORDER.get(c[1].get("severity"), 3)))
    return full, quiet


_MINOR_ADVISORIES = {"unknown_word", "inconsistent_terms", "unfinished_sentence",
                     "malformed_citation", "malformed_text", "vague_change_reason"}


def significance(ctx: _Section, full, quiet) -> str:
    labels = {a.get("label") for a in ctx.advisories}
    stated = [i for f, i in full if f == "stated"]
    if ctx.hard_fails:
        return "blocking"
    if any(i.get("severity") == "high" for i in stated) or (ctx.verdict == "reject" and stated):
        return "serious"
    if stated or "adds_requirement" in labels:
        return "notable"
    if full:
        return "tentative"
    if labels & _MINOR_ADVISORIES or quiet:
        return "minor"
    if ctx.change_type in ("cosmetic", "terminology_equivalent"):
        return "trivial"
    return "plain" if ctx.verdict == "approve" else "unclear"


# -- the change description ---------------------------------------------------------------

def _shape(ctx: _Section) -> str:
    ch = ctx.change
    if not ch.hunks:
        return "formatting_only"
    if ctx.change_type == "cosmetic":
        return "punctuation" if all(h["punctuation_only"] for h in ch.hunks) else "spelling"
    if ctx.change_type == "terminology_equivalent" and ctx.layer1.equivalent_swaps:
        return "equivalent_terms"
    lone = ch.hunks[0] if len(ch.hunks) == 1 else None
    if (lone and lone["tag"] == "insert" and 5 <= lone["added"] <= _QUOTABLE_LINE_WORDS
            and lone["new"].rstrip().endswith((".", "!", "?"))):
        return "added_sentence"
    if ch.only_whole_lines:
        if ch.lines_quotable and ch.removed_lines and not ch.added_lines:
            return "lines_removed_quoted"
        if ch.lines_quotable and ch.added_lines and not ch.removed_lines:
            return "lines_added_quoted"
        if not (ch.removed_lines and ch.added_lines):
            return "lines_unquotable"
    if len(ch.hunks) <= 3 and all(h["removed"] <= _SHORT_WORDS and h["added"] <= _SHORT_WORDS
                                  for h in ch.hunks):
        return "small_edit"
    return "larger_edit"


def _share(ratio: float) -> str:
    """Share of the wording, bare so that "About {share}" reads right:
    "a third", "half", or "55%"."""
    named = ((0.25, "a quarter"), (1 / 3, "a third"), (0.5, "half"),
             (2 / 3, "two thirds"), (0.75, "three quarters"))
    for value, words in named:
        if abs(ratio - value) <= 0.03:
            return words
    return f"{ratio:.0%}"


def _lines_slot(lines, text) -> str:
    return _join([_quote(_tidy_row(ln, text)) for ln in lines])


def _change_slots(ctx: _Section) -> dict:
    ch = ctx.change
    slots = ctx.place(ch.single_item)
    removed_share = float(ctx.features.get("deleted_word_ratio", 0) or 0)
    added_share = float(ctx.features.get("inserted_word_ratio", 0) or 0)
    slots.update({
        "n_lines": _number_word(len(ch.removed_lines or ch.added_lines)),
        "s": "" if len(ch.removed_lines or ch.added_lines) == 1 else "s",
        "were": "was" if len(ch.removed_lines or ch.added_lines) == 1 else "were",
        "n_hunks": _number_word(len(ch.hunks)),
        "n_hunks_cap": _cap(_number_word(len(ch.hunks))),
        "lines_removed": _lines_slot(ch.removed_lines, ch.old),
        "lines_added": _lines_slot(ch.added_lines, ch.new),
        "removed_or_added": "removed" if ch.removed_lines else "added",
        "at_items": f"at {_join(ch.items)}" if ch.items else "",
        "words_removed": _number_word(ch.words_removed),
        "words_added": _number_word(ch.words_added),
        "share": _share(removed_share),
        "share_clause": "",
    })
    if ch.hunks:
        first = ch.hunks[0]
        slots.update({"old_ctx": first["old_ctx"], "new_ctx": first["new_ctx"],
                      "added_sentence": first["new"].strip()})
    if ctx.layer1.equivalent_swaps:
        a, b = ctx.layer1.equivalent_swaps[0]
        slots.update({"a": a, "b": b})
    slots["_large"] = removed_share >= 0.3 or added_share >= 0.3 or (
        ch.words_removed + ch.words_added) > 60
    return slots


def _describe_change(ctx: _Section, writer: _Writer) -> tuple:
    """(inline, sentence): the change as it reads inside an opening, and as
    it reads standing alone in the CHANGE block. They differ only where the
    edit has several places (`several_places` / `several_places_sentence`)."""
    shape = _shape(ctx)
    block = wording()["change"][shape]
    slots = _change_slots(ctx)
    ch = ctx.change
    if shape == "small_edit" and len(ch.hunks) > 1:
        parts = []
        for hunk in ch.hunks:
            piece = f"{_quote(hunk['old_ctx'])} → {_quote(hunk['new_ctx'])}"
            if hunk["item"] and len(ch.items) > 1:
                piece += f" ({hunk['item']})"
            parts.append(piece)
        slots["hunk_list"] = "; ".join(parts)
        inline = writer.say("change.small_edit.several_places", block["several_places"], slots)
        sentence = writer.say("change.small_edit.several_places_sentence",
                              block.get("several_places_sentence"), slots)
        return inline or "", sentence or inline or ""
    variants = list(block["variants"])
    if writer.voice == "drafter":
        variants += list(block.get("drafter_only") or [])
    if True:
        allow = None
        if shape == "larger_edit":
            large = slots["_large"]

            def allow(index, template):
                if "sizeable" in template:
                    return large
                if "moderate" in template:
                    return not large
                return True
        text = writer.say(f"change.{shape}", variants, slots, allow=allow)
    return text or "", text or ""


# -- concerns ---------------------------------------------------------------------------------

def _values(flag, issue, side):
    """(from|to) values: the flag's lists when present, else parsed from text."""
    if flag and flag.get(f"{side}_values") is not None:
        return list(flag.get(f"{side}_values") or [])
    return _straight_to_items(issue.get(f"{side}_text") or "")


def _concern(ctx: _Section, firm: str, issue: dict, writer: _Writer, *, opened_lines: bool,
             quoted: str = "") -> dict:
    """Lead, why, ask, check, limit and clause for one concern; each already
    written, or None where the file has nothing fillable.

    ``quoted``: what the note's opening quotes (lower case). When every word
    this concern would quote is already there, its `lead_followup` is used
    instead, so no words are quoted twice in one note."""
    label = issue["label"]
    words = wording()["concerns"][label]
    ch = ctx.change
    slots = ctx.place(ch.single_item)
    flag = ctx.flag(label)
    lead_pool = None
    why_pool = "why"

    if firm == "suggested":
        lead_pool = "lead_suggested"
    elif label == "modal_weakened":
        pairs = issue.get("pairs") or []
        if pairs:
            slots.update({"a": pairs[0][0], "b": pairs[0][1]})
            slots.update(ctx.place(ch.item_of_text(pairs[0][1]) or ch.single_item))
            lead_pool = "lead_stated"
        else:
            lead_pool = "lead_stated_no_pairs"
    elif label == "negation_changed":
        action = issue.get("action")
        reversals = (flag or {}).get("reversals") or []
        if action in ("added", "removed"):
            word = (issue.get(action) or [""])[0]
            slots.update({"neg_word": word, "added_or_removed": action})
            removed_whole = action == "removed" and any(
                re.search(rf"\b{re.escape(word)}\b", ln, re.I) for ln in ch.removed_lines)
            if removed_whole:
                lead_pool = "lead_stated_deleted_sentence"
            else:
                slots.update(ctx.place(ch.item_of_text(word) or ch.single_item))
                lead_pool = "lead_stated_added_removed"
        elif reversals:
            a, b = reversals[0]
            slots["reversal"] = f"{_quote(a)} became {_quote(b)}"
            lead_pool = "lead_stated_reversal"
        else:
            words_used = (issue.get("added") or []) + (issue.get("removed") or [])
            slots.update({"neg_word": _join(words_used), "added_or_removed": "changed"})
            lead_pool = "lead_stated_added_removed"
    elif label == "numeric_changed":
        before, after = _values(flag, issue, "from"), _values(flag, issue, "to")
        slots.update({"from_text": _quoted_list(before), "to_text": _quoted_list(after)})
        from .layer1_rules import _FREQUENCY_WORDS
        if all(v.lower() in _FREQUENCY_WORDS for v in before + after):
            lead_pool = "lead_stated_frequency"
        elif before and after:
            lead_pool = "lead_stated_changed"
        elif after:
            lead_pool = "lead_stated_added"
        else:
            lead_pool = "lead_stated_removed"
    elif label == "responsibility_changed":
        roles = issue.get("roles") or [r.strip() for r in (issue.get("evidence") or "").split(",")]
        gone, came = [], []
        for role in roles:
            in_old, in_new = _find_ci(role, ch.old), _find_ci(role, ch.new)
            if in_old and not in_new:
                gone.append(in_old)
            elif in_new and not in_old:
                came.append(in_new)
        if gone and not came:
            # A role that already appears elsewhere in the section is still
            # the one now named at the edited step.
            came = [spelled for spelled in (_find_ci(r, " ".join(h["new"] for h in ch.hunks))
                                            for r in roles) if spelled and spelled not in gone]
        slots.update({"gone": _join(gone), "came": _join(came),
                      "roles": _join([_quote(r) for r in roles[:3]]),
                      "came_or_the_new_office": _join(came) or "the new office",
                      "came_or_another_office": _join(came) or "another office"})
        lead_pool = ("lead_stated_swap" if gone and came else "lead_stated_gone" if gone
                     else "lead_stated_came" if came else "lead_stated_roles_only")
    elif label == "requirement_removed":
        if opened_lines:
            lead_pool = "lead_stated_already_quoted"
        else:
            count = len(ch.removed_lines) or int(issue.get("count") or 1)
            if count == 1:
                evidence = (issue.get("evidence") or "").strip()
                line = ch.removed_lines[0] if ch.removed_lines else next(
                    (ln for ln in ch.old.splitlines() if evidence[:40] and evidence[:40] in ln), "")
                slots["req_text"] = _tidy_row(line, ch.old) if line else ""
                lead_pool = "lead_stated_one"
            else:
                slots.update({"req_count": _number_word(count),
                              "req_count_cap": _cap(_number_word(count))})
                lead_pool = "lead_stated_many"
    elif label == "excessive_deletion":
        ratio = issue.get("ratio", ctx.features.get("net_deleted_word_ratio", 0))
        slots["share"] = _share(float(ratio or 0))
        lead_pool = "lead_stated"
    elif label == "key_term_deleted":
        from .layer1_rules import _LEGAL_REF_RE
        terms = issue.get("terms") or [issue.get("evidence")]
        spelled = [_find_ci(t, ch.old) or t for t in terms if t]
        slots.update({"terms": _quoted_list(spelled[:3]), "terms_cap": _quoted_list(spelled[:3]),
                      "s": "s" if len(spelled[:3]) == 1 else ""})
        legal = any(_LEGAL_REF_RE.search(t) for t in spelled)
        lead_pool = "lead_stated_legal" if legal else "lead_stated"
        why_pool = "why_legal" if legal else "why"
    elif label == "non_equivalent_term":
        swaps = issue.get("swaps") or []
        if swaps:
            slots.update({"a": swaps[0][0], "b": swaps[0][1]})
            slots.update(ctx.place(ch.item_of_text(swaps[0][1]) or ch.single_item))
        lead_pool = "lead_stated"
    elif label == "contradicts_manual":
        value = str(((issue.get("conflicts") or [{}])[0]).get("value") or issue.get("evidence") or "")
        other = ctx.other_with(value)
        slots.update({"value": value, "other_section": other,
                      "other_section_or_the_other_section": other or "the other section"})
        changed = ctx.changed_in_proposal(other) if other else None
        if changed and value.lower() not in (changed.get("new_text") or "").lower():
            lead_pool = "lead_stated_coordinated"
        else:
            lead_pool = "lead_stated_named" if other else "lead_stated"
    elif label == "out_of_scope_content":
        lead_pool = "lead_suggested"

    if label == "contradicts_manual" and firm == "suggested":
        slots.setdefault("other_section_or_the_other_section", "the other section")
    if label == "requirement_removed" and firm == "suggested":
        slots.setdefault("req_text", "")

    # Never quote the same words twice: if the opening already quoted what
    # this lead would, follow up on it instead.
    followup = False
    if firm == "stated" and words.get("lead_followup") and quoted:
        named = {
            "modal_weakened": [slots.get("a"), slots.get("b")],
            "negation_changed": [slots.get("neg_word")]
            if lead_pool == "lead_stated_added_removed" else [],
            "numeric_changed": _values(flag, issue, "from") + _values(flag, issue, "to"),
            "responsibility_changed": [x for x in (slots.get("gone"), slots.get("came")) if x],
            "non_equivalent_term": [slots.get("a"), slots.get("b")],
        }.get(label) or []
        if named and all(w and w.lower() in quoted for w in named):
            lead_pool, followup = "lead_followup", True

    key = f"concerns.{label}"
    lead = writer.say(f"{key}.{lead_pool}", words.get(lead_pool), slots) if lead_pool else None
    checks = words.get("check")
    if isinstance(checks, dict):
        checks = checks.get(writer.voice)
    return {
        "label": label, "firmness": firm, "slots": slots, "followup": followup,
        "lead": lead,
        "why": writer.say(f"{key}.{why_pool}", words.get(why_pool), slots),
        "ask": writer.say(f"{key}.ask.{writer.voice}", (words.get("ask") or {}).get(writer.voice), slots),
        "check": writer.say(f"{key}.check.{writer.voice}", checks, slots),
        "limit": (words.get("limit") or [""])[0],
        "clause": clause_for(label) if firm == "stated" else "",
        "short_name": wording()["grouping"]["short_names"].get(label, label.replace("_", " ")),
        "definite_name": wording()["grouping"].get("definite_names", {}).get(label, ""),
    }


def _quiet_line(ctx: _Section, issue: dict, writer: _Writer):
    label = issue["label"]
    slots = {"share": _share(float(ctx.features.get("net_deleted_word_ratio", 0) or 0))}
    return writer.say(f"quiet_lines.{label}", wording()["quiet_lines"].get(label), slots)


# -- advisories ----------------------------------------------------------------------------------

def _advisory_sentences(ctx: _Section, writer: _Writer):
    """The ADVISORIES block, and the combined new-requirement concern.

    Returns (sentences, combined, findings). ``combined`` is a concern when
    a new requirement ends on a non-word (`combined.new_requirement_unclear`):
    it then leads the note as LEAD1 (selection.emphasis) and its advisories
    are not repeated here. ``findings`` counts the advisories written, for
    `advisories_intro`.
    """
    words = wording()["advisories"]
    by_label = {}
    for adv in ctx.advisories:
        by_label.setdefault(adv.get("label"), adv)
    out, findings, combined = [], 0, None
    unknown_words = (by_label.get("unknown_word") or {}).get("words") or []
    unfinished = by_label.get("unfinished_sentence")
    consumed_unknown, consumed_unfinished = set(), set()

    adds = by_label.get("adds_requirement")
    if adds:
        req = (adds.get("requirements") or [{}])[0]
        slots = ctx.place(req.get("item", ""))
        slots.update({"req_word": req.get("word", ""), "was": req.get("was") or ""})
        partner = next((w for w in unknown_words
                        if w.get("item") == req.get("item") and not w.get("suggestion")), None)
        ask = writer.say(f"advisories.adds_requirement.ask.{writer.voice}",
                         words["adds_requirement"]["ask"][writer.voice], slots)
        text = None
        if partner and req.get("item"):
            slots["word"] = partner["word"]
            pool = wording()["combined"]["new_requirement_unclear"]
            variants = pool["variants"] if writer.voice == "drafter" else pool["reader"]
            text = writer.say(f"combined.new_requirement_unclear.{writer.voice}", variants, slots)
        if text:
            consumed_unknown.add(partner["word"])
            consumed_unfinished.add(req.get("item"))
            combined = {
                "label": "adds_requirement", "firmness": "stated", "slots": slots,
                "followup": False, "lead": text,
                "why": writer.say("advisories.adds_requirement.why_after_unclear",
                                  words["adds_requirement"].get("why_after_unclear"), slots),
                "ask": ask, "check": None, "limit": "",
                "clause": clause_for("adds_requirement"),
                "short_name": wording()["grouping"]["short_names"].get("adds_requirement", ""),
                "definite_name": wording()["grouping"].get("definite_names", {}).get(
                    "adds_requirement", ""),
            }
        else:
            kind = req.get("kind", "added_sentence")
            text = writer.say(f"advisories.adds_requirement.{kind}",
                              words["adds_requirement"].get(kind), slots)
            why = writer.say("advisories.adds_requirement.why", words["adds_requirement"]["why"], slots)
            out += [s for s in (text, why, ask) if s]
            findings += 1

    left = [w for w in unknown_words if w["word"] not in consumed_unknown]
    suffix = words["unknown_word"]["reader_suffix"] if writer.voice == "reader" else ""
    if len(left) > 1:
        text = writer.say("advisories.unknown_word.several", words["unknown_word"]["several"],
                          {"word_list": _quoted_list(w["word"] for w in left)})
        if text:
            out.append(text + suffix)
            findings += len(left)
    elif left:
        w = left[0]
        slots = ctx.place(w.get("item", ""))
        slots.update({"word": w["word"], "suggestion": w.get("suggestion") or ""})
        pool = "with_suggestion" if w.get("suggestion") else "no_suggestion"
        text = writer.say(f"advisories.unknown_word.{pool}", words["unknown_word"][pool], slots)
        if text:
            out.append(text + suffix)
            findings += 1

    terms = by_label.get("inconsistent_terms")
    if terms:
        group = (terms.get("groups") or [{}])[0]
        slots = ctx.place((group.get("items") or [""])[0])
        slots.update({"kept": group.get("kept", ""),
                      "introduced": _quoted_list(group.get("introduced") or [])})
        for part in ("variants", "why", "tip"):
            text = writer.say(f"advisories.inconsistent_terms.{part}",
                              words["inconsistent_terms"][part], slots)
            if text:
                out.append(text)
        findings += 1

    if unfinished:
        pools = words["unfinished_sentence"]
        for line in (unfinished.get("lines") or [])[:2]:
            item = line.get("item") or ""
            if item and item in consumed_unfinished:
                continue
            if line.get("kind") == "item_opens_lower_case":
                pool = ("item_opens_lower_case" if item and line.get("was")
                        else "new_line_opens_lower_case" if item
                        else "opens_lower_case_no_item")
            else:
                pool = "no_final_punctuation" if item else "no_final_punctuation_no_item"
            slots = {"item": item, "first_word": line.get("first_word", ""),
                     "was": line.get("was") or ""}
            text = writer.say(f"advisories.unfinished_sentence.{pool}", pools.get(pool), slots)
            if text:
                out.append(text)
                findings += 1

    if "vague_change_reason" in by_label:
        text = writer.say(f"advisories.vague_change_reason.{writer.voice}",
                          words["vague_change_reason"][writer.voice], {})
        if text:
            out.append(text)
            findings += 1

    for label in ("malformed_citation", "malformed_text"):
        adv = by_label.get(label)
        if adv:
            slots = ctx.place(_item_of(adv.get("evidence", "")))
            slots["evidence"] = _clip(adv.get("evidence", ""), 120)
            text = writer.say(f"advisories.{label}", words[label], slots)
            if text:
                out.append(text)
                findings += 1
    return out, combined, findings


# -- context, fine, limits ------------------------------------------------------------------------

def _context_sentences(ctx: _Section, concerns: list, writer: _Writer) -> list:
    words = wording()["context"]
    out = []
    issue_labels = {c["label"] for c in concerns}
    all_issue_labels = {i.get("label") for i in (getattr(ctx.fusion, "issues", None) or [])}

    # A conflict the rules found and the issue policy dropped - numeric
    # conflicts only, never role conflicts (selection.emphasis).
    flag = ctx.flag("contradicts_manual")
    conflict = ((flag or {}).get("conflicts") or [{}])[0]
    if (flag and "contradicts_manual" not in all_issue_labels
            and conflict.get("kind") == "numeric"):
        value = str(conflict.get("value") or "")
        other = ctx.other_with(value)
        if other:
            changed = ctx.changed_in_proposal(other)
            slots = {"other_section": other, "value": value}
            if changed and value.lower() not in (changed.get("new_text") or "").lower():
                text = writer.say("context.coordinated.consistent", words["coordinated"]["consistent"], slots)
            else:
                text = writer.say("context.dropped_rule_findings.contradicts_manual",
                                  words["dropped_rule_findings"]["contradicts_manual"], slots)
            if text:
                out.append(text)

    # A timing word the rules counted as a figure, dropped by the policy.
    flag = ctx.flag("numeric_changed")
    if flag and "numeric_changed" not in all_issue_labels:
        from .layer1_rules import _FREQUENCY_WORDS
        values = (flag.get("from_values") or []) + (flag.get("to_values") or [])
        if values and all(v.lower() in _FREQUENCY_WORDS for v in values):
            text = writer.say("context.dropped_rule_findings.numeric_changed_frequency",
                              words["dropped_rule_findings"]["numeric_changed_frequency"],
                              {"from_text": _quoted_list(flag.get("from_values") or values)})
            if text:
                out.append(text)

    # A model-only conflict, where a retrieved section is being changed too.
    model_conflict = any(c["label"] == "contradicts_manual" and c["firmness"] == "suggested"
                         for c in concerns)
    if model_conflict:
        for label, _ in ctx.related:
            if ctx.changed_in_proposal(label):
                text = writer.say("context.coordinated.conflict_in_proposal",
                                  words["coordinated"]["conflict_in_proposal"], {"other_section": label})
                if text:
                    out.append(text)
                break

    # The reason does not mention the main change.
    linked = {"numeric_changed", "modal_weakened", "requirement_removed", "responsibility_changed"}
    stated = [c for c in concerns if c["firmness"] == "stated" and c["label"] in linked]
    adds = next((a for a in ctx.advisories if a.get("label") == "adds_requirement"), None)
    if ctx.reason and (stated or adds):
        terms = []
        for c in stated:
            s = c["slots"]
            terms += [s.get(k, "") for k in ("gone", "came", "a", "b", "item")]
            terms += _STRAIGHT_QUOTED_RE.findall(s.get("from_text", "").replace("“", '"').replace("”", '"'))
            terms += _STRAIGHT_QUOTED_RE.findall(s.get("to_text", "").replace("“", '"').replace("”", '"'))
        if adds:
            req = (adds.get("requirements") or [{}])[0]
            terms += [req.get("word", ""), req.get("item", "")]
        reason = ctx.reason.lower()
        terms = [t for t in terms if t and len(t) > 1]
        if terms and not any(t.lower() in reason for t in terms):
            text = writer.say(f"context.reason_link.{writer.voice}",
                              words["reason_link"][writer.voice], {})
            if text:
                out.append(text)
    return out


def _fine_sentences(ctx: _Section, concerns: list, quiet: list, writer: _Writer) -> list:
    words = wording()["fine"]
    if ctx.change_type == "cosmetic":
        return [s for s in [writer.say("fine.cosmetic", words["cosmetic"], {})] if s]
    if ctx.change_type == "terminology_equivalent":
        return [s for s in [writer.say("fine.equivalent", words["equivalent"], {})] if s]
    labels = {c["label"] for c in concerns} | {i["label"] for _, i in quiet}
    adv = {a.get("label") for a in ctx.advisories}
    things = []
    if not ctx.features.get("numeric_changed_count") and not labels & {"numeric_changed", "contradicts_manual"}:
        things.append("figure")
    if (not ctx.features.get("modal_weakened_count") and "modal_weakened" not in labels
            and "adds_requirement" not in adv):
        things.append("obligation")
    if not ctx.features.get("role_terms_changed_count") and not labels & {"responsibility_changed", "contradicts_manual"}:
        things.append("named office")
    out = []
    if len(things) == 3:
        text = writer.say("fine.untouched", words["untouched"]["variants"], {})
    elif things:
        text = writer.say("fine.untouched.partial", words["untouched"]["partial"],
                          {"things": _join_or(things)})
    else:
        text = None
    if text:
        out.append(text)
    if (not ctx.change.words_removed and not ctx.features.get("sentences_removed")
            and not labels & {"requirement_removed", "excessive_deletion"}):
        text = writer.say("fine.nothing_removed", words["nothing_removed"], {})
        if text:
            out.append(text)
    return out


def _limit_sentences(ctx: _Section, concerns: list, writer: _Writer) -> list:
    words = wording()["limits"]
    limits = []
    for c in concerns:
        if c["limit"] and c["limit"] not in limits:
            limits.append(c["limit"])
    out = []
    for limit in limits[:2]:
        lead_in = words["lead_in"]
        if isinstance(lead_in, dict):
            lead_in = lead_in.get(writer.voice)
        text = writer.say(f"limits.lead_in.{writer.voice}", lead_in, {"limit": limit})
        if text:
            out.append(text)
    if (not out and ctx.change.words_added
            and ctx.change_type not in ("cosmetic", "terminology_equivalent")):
        text = writer.say("limits.added_wording", words["added_wording"], {})
        if text:
            out.append(text)
    return out


def _iso_owner(plan: dict, blocks: dict, concerns: list, ctx: _Section) -> str:
    """The clause for the ISO block: that of the concern (or hard fail) the
    block immediately follows, skipping blocks with nothing in them. An ISO
    sentence never follows an unrelated concern (selection.emphasis), and is
    only for what iso_rules allow: stated concerns, a new requirement and
    hard fails."""
    order = _plan_blocks(plan)
    if "ISO" not in order:
        return ""
    for block in reversed(order[:order.index("ISO")]):
        if not blocks.get(block):
            continue
        if block == "HARD_FAIL" and ctx.hard_fails:
            return clause_for(ctx.hard_fails[0].get("reason", ""))
        if block[:-1] in ("LEAD", "WHY", "ASK", "CHECK") and block[-1].isdigit():
            n = int(block[-1])
            concern = concerns[n - 1] if n <= len(concerns) else None
            return concern["clause"] if concern and concern["firmness"] == "stated" else ""
        return ""
    return ""


def _iso_sentence(clause: str, writer: _Writer) -> list:
    if not clause:
        return []
    iso = wording()["iso"]
    asks = writer.say(f"iso.asks_that.{clause}", iso["asks_that"].get(clause), {})
    text = writer.say("iso.relevance_first", iso["relevance_first"],
                      {"clause": clause, "asks_that": asks or ""})
    return [text] if text else []


# -- plans and paragraphs --------------------------------------------------------------------------

def _with_transition(writer: _Writer, pool: str, sentence: str, lower_ok: bool) -> str:
    connector = writer.say(f"transitions.{pool}", wording()["transitions"][pool], {})
    if not connector:
        return sentence
    body = _uncap(sentence) if lower_ok and not connector.endswith(":") else sentence
    return f"{connector} {body}"


def _starts_lowerable(sentence: str, protected: list) -> bool:
    """A sentence may take a lower-case first letter after a connector unless
    it opens with a name (a section, a role, a document)."""
    return not any(p and sentence.startswith(p) for p in protected)


def _plan_blocks(plan: dict) -> list:
    return [b for para in plan["paragraphs"] for b in para]


def _opens_before_leads(plan: dict) -> bool:
    order = _plan_blocks(plan)
    first_open = min((order.index(b) for b in ("OPEN", "CHANGE") if b in order), default=None)
    first_lead = min((i for i, b in enumerate(order) if b.startswith("LEAD")), default=None)
    return first_lead is None or (first_open is not None and first_open < first_lead)


def _choose_plan(tier: str, needed: set, n_full: int, picker: _Picker, avoid: set,
                 opening_first: bool = False):
    plans = wording()["selection"]["plans"][tier]

    def missing(plan):
        blocks = set(_plan_blocks(plan))
        gaps = {b for b in needed if b not in blocks}
        leads = sum(1 for b in blocks if b.startswith("LEAD"))
        if n_full > leads and "ALSO" not in blocks:
            gaps.add("ALSO")
        return gaps

    scored = [(i, p, missing(p)) for i, p in enumerate(plans)]
    fewest = min(len(g) for _, _, g in scored)
    eligible = [(i, p) for i, p, g in scored if len(g) == fewest]
    if opening_first:
        # A lead that follows up on the quoted change must come after it.
        eligible = [(i, p) for i, p in eligible if _opens_before_leads(p)] or eligible
    not_adjacent = [(i, p) for i, p in eligible if p["id"] not in avoid]
    candidates = not_adjacent or eligible
    chosen_id = picker.pick(f"plans.{tier}", [(i, p["id"]) for i, p in candidates])
    plan = next(p for p in plans if p["id"] == chosen_id)
    return plan, missing(plan)


def _split_to(paragraphs: list, minimum: int) -> list:
    """Split the longest paragraph until there are enough: at a block
    boundary first, at a sentence boundary if a single block is all there is."""
    while len(paragraphs) < minimum:
        index = max(range(len(paragraphs)), key=lambda k: sum(len(s) for s in paragraphs[k]))
        para = paragraphs[index]
        if len(para) < 2:
            break
        cut = len(para) // 2
        paragraphs[index:index + 1] = [para[:cut], para[cut:]]
    return paragraphs


def compose_note(fusion_result, layer1_result, *, section_label: str = "",
                 audience: str = REVIEWER, old_text: str = None, new_text: str = None,
                 change_reason: str = "", related_sections=None, proposal_sections=None,
                 document_title: str = "", history=None, adjacent_plans=None,
                 content_key: str = ""):
    """The note for one section, and the choices made writing it.

    ``history``: earlier choice records for this voice, most relevant first
    (other sections of the proposal, then the user's recent notes).
    ``adjacent_plans``: plan ids of the neighbouring changed sections, which
    this note avoids when another plan is eligible.
    Returns (text, choices).
    """
    voice = _VOICE.get(audience, "reader")
    if old_text is None and new_text is None:
        old_text, new_text = _texts_from_marked(getattr(layer1_result, "marked", ""))
    ctx = _Section(fusion_result, layer1_result, section_label, old_text, new_text,
                   change_reason, related_sections, proposal_sections, document_title)
    key = content_key or f"{old_text}\x1f{new_text}"
    picker = _Picker(history, key, voice)
    writer = _Writer(picker, voice)
    W = wording()

    full, quiet = _ordered_concerns(ctx)
    tier = significance(ctx, full, quiet)
    shape = _shape(ctx)

    blocks: dict = {}
    change, change_sentence = _describe_change(ctx, writer)
    opened_lines = shape == "lines_removed_quoted"
    # What the opening quotes, so no concern quotes the same words again.
    ch = ctx.change
    if shape in ("small_edit", "punctuation", "spelling", "equivalent_terms"):
        quoted = " ".join(h["old_ctx"] + " " + h["new_ctx"] for h in ch.hunks)
    elif shape == "added_sentence":
        quoted = " ".join(h["new"] for h in ch.hunks)
    elif shape in ("lines_removed_quoted", "lines_added_quoted"):
        quoted = " ".join(ch.removed_lines + ch.added_lines)
    else:
        quoted = ""
    quoted = quoted.lower()
    advisory_sentences, combined, findings = _advisory_sentences(ctx, writer)
    written = [_concern(ctx, firm, issue, writer, opened_lines=opened_lines, quoted=quoted)
               for firm, issue in full]
    # The unclear new requirement is the primary concern (selection.emphasis).
    ranked = ([combined] if combined else []) + written
    concerns, extra = ranked[:MAX_CONCERNS], ranked[MAX_CONCERNS:]

    opening = None
    if change:
        # Prefer an opening that neither stacks a second colon before a
        # change that has one, nor names the section the change already names.
        colon = ":" in change
        named = ctx.section in change

        def fits(index, template):
            return not ((colon and ": {change" in template)
                        or (named and "{section}" in template))
        slots = {"change": _uncap(change), "change_cap": _cap(change), "section": ctx.section}
        pool = W["openings"][voice][tier]
        if any(fits(i, v) for i, v in enumerate(pool)):
            opening = writer.say(f"openings.{voice}.{tier}", pool, slots, allow=fits)
        if opening is None:
            opening = writer.say(f"openings.{voice}.{tier}", pool, slots)
    blocks["OPEN"] = [opening] if opening else []
    blocks["CHANGE"] = [_tidy_sentence(_cap(change_sentence) + ".")] if change_sentence else []

    # Leads, why, ask, check - per concern, as far as the plan has room.
    for n, c in enumerate(concerns, start=1):
        blocks[f"LEAD{n}"] = [c["lead"]] if c["lead"] else []
        blocks[f"WHY{n}"] = [c["why"]] if c["why"] else []
        blocks[f"ASK{n}"] = [c["ask"]] if c["ask"] else []
        blocks[f"CHECK{n}"] = [c["check"]] if c["check"] else []

    quiet_lines = [q for q in (_quiet_line(ctx, i, writer) for _, i in quiet) if q]
    blocks["QUIET"] = quiet_lines
    blocks["HARD_FAIL"] = [s for s in (writer.say(f"hard_fails.{f.get('reason')}",
                                                  W["hard_fails"].get(f.get("reason")), {})
                                       for f in ctx.hard_fails) if s]
    blocks["ADVISORIES"] = advisory_sentences
    blocks["CONTEXT"] = _context_sentences(ctx, concerns, writer)
    blocks["FINE"] = _fine_sentences(ctx, concerns, quiet, writer)
    blocks["LIMITS"] = _limit_sentences(ctx, concerns, writer)
    blocks["UNCLEAR"] = ([writer.say(f"unclear.{voice}", W["unclear"][voice], {})]
                         if tier == "unclear" else [])
    # closings.minor is for "something small to tidy". A minor note that
    # only carries a quiet line has nothing to tidy, so it closes lightly.
    weight = _CLOSING_WEIGHT[tier]
    if weight == "minor" and not findings:
        weight = "light"
    blocks["CLOSE"] = [s for s in [writer.say(f"closings.{voice}.{weight}",
                                              W["closings"][voice][weight], {})] if s]

    needed = {b for b in ("HARD_FAIL", "ADVISORIES", "CONTEXT") if blocks[b]}
    needed |= {f"LEAD{n}" for n in range(1, min(len(concerns), 2) + 1) if blocks.get(f"LEAD{n}")}
    plan, gaps = _choose_plan(tier, needed, len(concerns), picker, set(adjacent_plans or []),
                              opening_first=any(c["followup"] for c in concerns) or opened_lines)
    blocks["ISO"] = _iso_sentence(_iso_owner(plan, blocks, concerns, ctx), writer)
    leads_in_plan = sum(1 for b in _plan_blocks(plan) if b.startswith("LEAD"))
    also = [c["short_name"] for c in concerns[leads_in_plan:] + extra if c["short_name"]]
    blocks["ALSO"] = ([writer.say("grouping.also_noted", W["grouping"]["also_noted"],
                                  {"short_names": _join(also)})] if also else [])
    blocks["ALSO"] = [s for s in blocks["ALSO"] if s]

    # Quiet lines go in the looks-fine or closing paragraph when the plan
    # has no QUIET block of its own (selection.firmness.quiet).
    plan_blocks = _plan_blocks(plan)
    if blocks["QUIET"] and "QUIET" not in plan_blocks:
        target = "FINE" if "FINE" in plan_blocks else "CLOSE"
        blocks[target] = blocks["QUIET"] + blocks[target]
        blocks["QUIET"] = []

    protected = [ctx.section, ctx.document] + [c["slots"].get(k, "") for c in concerns
                                               for k in ("gone", "came", "other_section", "section")]
    paragraphs = []
    for para in plan["paragraphs"]:
        sentences, previous = [], None
        for block in para:
            content = list(blocks.get(block, []))
            if not content:
                continue
            if block == "LEAD2":
                content[0] = _with_transition(writer, "second_concern", content[0],
                                              _starts_lowerable(content[0], protected))
            elif block == "ADVISORIES" and sentences:
                content[0] = _with_transition(writer, "add", content[0],
                                              _starts_lowerable(content[0], protected))
            elif block == "ADVISORIES" and not paragraphs:
                # Advisories opening the note get an introduction first.
                intro = W.get("advisories_intro") or {}
                kind = "one" if findings <= 1 else "several"
                lead = writer.say(f"advisories_intro.{kind}", intro.get(kind), {})
                if lead:
                    content = [lead] + content
            elif (block == "FINE" and previous is not None
                  and _FINDING_BLOCKS.match(previous)):
                # A contrast word only after a concern or an advisory.
                content[0] = _with_transition(writer, "contrast", content[0],
                                              _starts_lowerable(content[0], protected))
            sentences += content
            previous = block
        if sentences:
            paragraphs.append(sentences)

    # Blocks the chosen plan has no place for go before the closing line.
    unplaced = [b for b in ("HARD_FAIL", "ADVISORIES", "CONTEXT", "ALSO") if b in gaps and blocks[b]]
    if unplaced and paragraphs:
        extra_sentences = [s for b in unplaced for s in blocks[b]]
        last = paragraphs[-1]
        close = blocks["CLOSE"][0] if blocks["CLOSE"] and last and last[-1] == blocks["CLOSE"][0] else None
        if close:
            last[-1:-1] = extra_sentences
        else:
            last.extend(extra_sentences)

    low, _high = W["selection"]["length"][tier]
    paragraphs = _split_to(paragraphs, low)
    text = "\n\n".join(" ".join(p) for p in paragraphs)
    choices = {"tier": tier, "plan": plan["id"], "voice": voice, "pools": picker.chosen,
               "unfilled": sorted(writer.unfilled)}
    return text, choices


def explain(fusion_result, layer1_result, section_label: str = "",
            revision_id=None, max_sentences: int = MAX_SENTENCES,
            seed=None, audience: str = REVIEWER,
            old_text: str = None, new_text: str = None, **context) -> str:
    """The note alone, for callers that do not keep the choices."""
    text, _ = compose_note(fusion_result, layer1_result, section_label=section_label,
                           audience=audience, old_text=old_text, new_text=new_text,
                           content_key=str(seed or ""), **context)
    return text


def _texts_from_marked(marked: str):
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
    """List of Forms sections are not assessed by the model."""
    return _fill(wording()["not_checked"]["list_of_forms"],
                 {"section": section_label or "This section"}) or ""


# -- the proposal note ----------------------------------------------------------------------------

_CONCERN_TIERS = {"blocking", "serious", "notable", "tentative"}
_TIER_RANK = {t: i for i, t in enumerate(TIERS)}


def compose_proposal_note(sections: list, *, audience: str = REVIEWER, history=None,
                          content_key: str = ""):
    """The proposal-level note, composed from the stored section checks.

    ``sections``: one dict per changed section, in document order, with
    ``label``, ``old_text``, ``new_text``, ``tier`` (from the stored
    choices), ``issues``, ``advisories``, ``flags`` (Layer 1's, from the
    stored trace) and ``related`` [(label, current text)] of the sections its
    check retrieved. Nothing is re-run. Returns (text, choices).
    """
    voice = _VOICE.get(audience, "reader")
    picker = _Picker(history, content_key or "|".join(s.get("label", "") for s in sections), voice)
    writer = _Writer(picker, voice)
    words = wording()["proposal_note"]
    labels = [s["label"] for s in sections]
    with_concerns = [s["label"] for s in sections if s.get("tier") in _CONCERN_TIERS]
    kind = "none" if not with_concerns else "all" if len(with_concerns) == len(sections) else "some"
    concern_sentence = _fill(words["scope"]["concern_sections_sentence"][kind],
                             {"concern_sections": _join(with_concerns)}) or ""
    scope = writer.say(f"proposal_note.scope.{voice}", words["scope"][voice], {
        "n_sections": _number_word(len(sections)), "s": "" if len(sections) == 1 else "s",
        "sections_list": _join(labels), "concern_sections_sentence": concern_sentence})
    paragraphs = [[scope]] if scope else []

    # Cross-section: the same figure changed consistently; a conflict with a
    # section left out of the proposal.
    cross = []
    moves = {}
    for s in sections:
        flag = next((f for f in s.get("flags") or [] if f.get("label") == "numeric_changed"), None)
        if flag:
            for value in flag.get("from_values") or []:
                moves.setdefault(value, []).append((s, list(flag.get("to_values") or [])))
    for value, hits in moves.items():
        if len(hits) < 2:
            continue
        pairs = [to for _, to in hits if len(to) == 1]
        target = pairs[0][0] if pairs else ""
        if target and all(target in to and value.lower() not in (s["new_text"] or "").lower()
                          for s, to in hits):
            text = writer.say("proposal_note.cross_section.consistent_figure",
                              words["cross_section"]["consistent_figure"],
                              {"sections_list": _join([s["label"] for s, _ in hits]),
                               "from_text": _quote(value), "to_text": _quote(target)})
            if text:
                cross.append(text)
            break
    changed = set(labels)
    for s in sections:
        flags = [f for f in s.get("flags") or [] if f.get("label") == "contradicts_manual"]
        for f in flags:
            value = str(((f.get("conflicts") or [{}])[0]).get("value") or "")
            for label, text_ in s.get("related") or []:
                if (label not in changed and value
                        and value.lower() in _WS_RE.sub(" ", text_ or "").lower()):
                    text = writer.say("proposal_note.cross_section.unchanged_conflict",
                                      words["cross_section"]["unchanged_conflict"],
                                      {"other_section": label, "value": value})
                    if text and text not in cross:
                        cross.append(text)
    if cross:
        paragraphs.append(cross)

    # The reason advisory once, and the strongest single point.
    last = []
    if any(a.get("label") == "vague_change_reason" for s in sections for a in s.get("advisories") or []):
        text = writer.say(f"advisories.vague_change_reason.{voice}",
                          wording()["advisories"]["vague_change_reason"][voice], {})
        if text:
            last.append(text)
    ranked = sorted((s for s in sections if s.get("tier") in _CONCERN_TIERS),
                    key=lambda s: _TIER_RANK.get(s.get("tier"), 99))
    if ranked:
        top = ranked[0]
        names = wording()["grouping"].get("definite_names", {})
        labels = [i.get("label") for i in top.get("issues") or []]
        labels += [a.get("label") for a in top.get("advisories") or []]
        first = next((label for label in labels if label in names), None)
        if first:
            text = writer.say(f"proposal_note.strongest.{voice}", words["strongest"][voice],
                              {"top_point": names[first], "section": top["label"]})
            if text:
                last.append(text)
    if last:
        paragraphs.append(last)
    text = "\n\n".join(" ".join(p) for p in paragraphs)
    return text, {"voice": voice, "pools": picker.chosen, "unfilled": sorted(writer.unfilled)}


# -- notes written before this format -------------------------------------------------------------

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
    """True for a note in the heading format of 2026-09-29. Current notes
    are recognised by their stored choices, not by their text."""
    first = (text or "").lstrip().split("\n", 1)[0].strip()
    return first in NOTE_HEADINGS or (text or "").startswith("Not checked:")


def without_legacy_verdict(text: str) -> str:
    """An older explanation with its verdict sentences taken out. Only exact
    sentences the first writer produced are removed."""
    if not text or is_note(text):
        return text or ""
    out = _LEGACY_WITH_CONCERNS_RE.sub("", text)
    for sentence in _LEGACY_VERDICT_SENTENCES:
        out = out.replace(sentence, "")
    return _WS_RE.sub(" ", out).strip()
