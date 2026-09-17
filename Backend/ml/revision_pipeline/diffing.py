"""Diffing helpers shared by the rule layer, the model input, and the dataset.

Comparison is done on normalised text (whitespace collapsed, lower-cased) so
that formatting noise does not read as a change, while the original strings are
kept for display and evidence.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+(?:[-'/]\w+)*|[^\w\s]")
# Sentence end: . ! ? followed by space + capital, but not after a section
# number like "4.2.1" or an abbreviation left by extraction.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def normalise(text: str) -> str:
    """Collapse whitespace and case for comparison purposes."""
    return _WS_RE.sub(" ", (text or "").strip()).lower()


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


# Abbreviations that end in a full stop and do not end a sentence. Without
# these, "governed by E.O. No. 2, series of 2016" was three sentences, and an
# edit anywhere near it looked like several sentences appearing and
# disappearing at once.
_ABBREVIATIONS = (
    "e.o", "r.a", "p.d", "c.o.a", "i.e", "e.g", "no", "nos", "sec", "secs",
    "art", "arts", "par", "rep", "inc", "corp", "ltd", "co", "dept", "div",
    "fig", "vol", "atty", "engr", "dr", "mr", "mrs", "ms", "prof", "hon",
    "jr", "sr", "approx", "etc", "vs", "a.m", "p.m", "univ", "govt",
)
_ENDS_ABBREV_RE = re.compile(
    r"(?:\b|^)(?:" + "|".join(a.replace(".", r"\.") for a in _ABBREVIATIONS)
    + r")\.$",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    """Split into sentences, keeping numbered items like '4.2.1 Does a thing.'

    A fragment is joined back to the one before it when that one ends in an
    abbreviation rather than a sentence.
    """
    out = []
    for block in lines(text):
        parts = []
        for part in _SENT_SPLIT_RE.split(block):
            part = part.strip()
            if not part:
                continue
            if parts and _ENDS_ABBREV_RE.search(parts[-1]):
                parts[-1] = parts[-1] + " " + part
            else:
                parts.append(part)
        out.extend(parts)
    return out


@dataclass
class DiffResult:
    """Opcodes plus the concrete text on each side, for evidence."""

    opcodes: list = field(default_factory=list)
    # Everything gone from the old side, replacements included - used when
    # asking "was this word removed?"
    deleted: list = field(default_factory=list)
    inserted: list = field(default_factory=list)
    replaced: list = field(default_factory=list)   # (old_chunk, new_chunk)
    # Removed outright, with nothing put in its place. Ratios use this: a
    # reworded line is not a deleted line, and counting it as one fired
    # excessive_deletion on every single-line edit.
    pure_deleted: list = field(default_factory=list)
    pure_inserted: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.deleted or self.inserted or self.replaced)


def _diff(old_items: list[str], new_items: list[str], key) -> DiffResult:
    matcher = difflib.SequenceMatcher(
        a=[key(x) for x in old_items], b=[key(x) for x in new_items], autojunk=False
    )
    result = DiffResult(opcodes=matcher.get_opcodes())
    for tag, i1, i2, j1, j2 in result.opcodes:
        if tag == "delete":
            result.deleted.extend(old_items[i1:i2])
            result.pure_deleted.extend(old_items[i1:i2])
        elif tag == "insert":
            result.inserted.extend(new_items[j1:j2])
            result.pure_inserted.extend(new_items[j1:j2])
        elif tag == "replace":
            result.replaced.append((old_items[i1:i2], new_items[j1:j2]))
            result.deleted.extend(old_items[i1:i2])
            result.inserted.extend(new_items[j1:j2])
    return result


def line_diff(old: str, new: str) -> DiffResult:
    return _diff(lines(old), lines(new), key=normalise)


def word_diff(old: str, new: str) -> DiffResult:
    return _diff(words(old), words(new), key=lambda w: w.lower())


def marked_text(old: str, new: str) -> str:
    """One string with deletions and insertions wrapped in special tokens.

    This is what Layer 2 reads, so unchanged runs are kept: the model needs the
    surrounding wording to judge whether a change matters.
    """
    old_words, new_words = words(old), words(new)
    matcher = difflib.SequenceMatcher(
        a=[w.lower() for w in old_words], b=[w.lower() for w in new_words], autojunk=False
    )
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(old_words[i1:i2]))
        elif tag == "delete":
            parts.append("[DEL] " + " ".join(old_words[i1:i2]) + " [/DEL]")
        elif tag == "insert":
            parts.append("[INS] " + " ".join(new_words[j1:j2]) + " [/INS]")
        elif tag == "replace":
            parts.append("[DEL] " + " ".join(old_words[i1:i2]) + " [/DEL]")
            parts.append("[INS] " + " ".join(new_words[j1:j2]) + " [/INS]")
    return _WS_RE.sub(" ", " ".join(p for p in parts if p)).strip()


def change_ratios(old: str, new: str) -> dict:
    """Deletion/insertion ratios, measured against the original as the base."""
    old_lines, new_lines = lines(old), lines(new)
    old_words, new_words = words(old), words(new)

    ld = line_diff(old, new)
    wd = word_diff(old, new)

    return {
        "deleted_line_ratio": len(ld.pure_deleted) / len(old_lines) if old_lines else 0.0,
        "deleted_word_ratio": len(wd.pure_deleted) / len(old_words) if old_words else 0.0,
        # Insertions are measured against the original too, so "added half as
        # much again" reads as 0.5 rather than being diluted by its own length.
        "inserted_word_ratio": len(wd.pure_inserted) / len(old_words) if old_words else 0.0,
        # Positional diffs count moved text as deleted-and-reinserted, so a
        # reordered list looked like a large deletion. These bag-of-words
        # measures ask what actually left the section, which is what
        # "excessive deletion" is supposed to mean.
        "net_deleted_word_ratio": (
            sum((Counter(w.lower() for w in old_words)
                 - Counter(w.lower() for w in new_words)).values()) / len(old_words)
            if old_words else 0.0
        ),
        "net_inserted_word_ratio": (
            sum((Counter(w.lower() for w in new_words)
                 - Counter(w.lower() for w in old_words)).values()) / len(old_words)
            if old_words else 0.0
        ),
        "old_line_count": len(old_lines),
        "new_line_count": len(new_lines),
        "old_word_count": len(old_words),
        "new_word_count": len(new_words),
    }


def _content_words(sentence: str) -> set:
    """Words long enough to carry meaning - articles and prepositions inflate
    any overlap measure otherwise."""
    return {w for w in words(normalise(sentence)) if len(w) >= 4}


def _pair_score(old_norm: str, new_norm: str, old_sent: str, new_sent: str):
    """How strongly two sentences look like versions of each other.

    Character similarity alone misses a heavy rewrite that keeps the subject
    and object; content-word overlap alone matches any two sentences about
    "staff". Either signal can carry a match, but the overlap route also needs
    at least two shared content words so one common noun cannot do it.
    """
    ratio = difflib.SequenceMatcher(a=old_norm, b=new_norm).ratio()
    old_words_set, new_words_set = _content_words(old_sent), _content_words(new_sent)
    shared = old_words_set & new_words_set
    smaller = min(len(old_words_set), len(new_words_set)) or 1
    overlap = len(shared) / smaller
    if ratio >= 0.6:
        return ratio
    if overlap >= 0.6 and len(shared) >= 2:
        return overlap
    return 0.0


def sentences_removed(old: str, new: str, similarity: float = 0.6) -> list:
    """Sentences dropped from the original, not merely reworded.

    A sentence counts as surviving only when some sentence in the revision is
    recognisably a version of it. Matching is one-to-one and **content-based**:

    * Counting removals only up to how much the text shrank was gameable -
      deleting a requirement while adding an unrelated sentence kept the count
      level and reported nothing removed.
    * A per-sentence best match let one survivor vouch for its deleted
      siblings, which all share a skeleton ("Staff check the form", "Staff
      sign the log").

    Pairs are therefore scored first and assigned best-first, so an exact match
    claims its partner before a weaker candidate can.
    """
    old_sents = [s for s in sentences(old) if normalise(s)]
    new_sents = [s for s in sentences(new) if normalise(s)]
    old_norms = [normalise(s) for s in old_sents]
    new_norms = [normalise(s) for s in new_sents]

    scored = []
    for i, (old_sent, old_norm) in enumerate(zip(old_sents, old_norms)):
        for j, (new_sent, new_norm) in enumerate(zip(new_sents, new_norms)):
            score = _pair_score(old_norm, new_norm, old_sent, new_sent)
            if score >= similarity:
                scored.append((score, i, j))

    scored.sort(key=lambda item: -item[0])
    matched_old, matched_new = set(), set()
    for score, i, j in scored:
        if i in matched_old or j in matched_new:
            continue
        matched_old.add(i)
        matched_new.add(j)

    return [sent for i, sent in enumerate(old_sents) if i not in matched_old]


def sentence_match_report(old: str, new: str, similarity: float = 0.6,
                          band: float = 0.1) -> dict:
    """Matching decisions with their scores, for dataset quality checking.

    The 0.6 cut-off decides whether an edit counts as a rewrite or a removal,
    which in turn decides whether an example carries ``requirement_removed``.
    A pair scoring 0.58 and one scoring 0.62 are labelled oppositely on a
    hair's breadth, so Phase 4 reports how many land in that band.
    """
    old_sents = [s for s in sentences(old) if normalise(s)]
    new_sents = [s for s in sentences(new) if normalise(s)]
    old_norms = [normalise(s) for s in old_sents]
    new_norms = [normalise(s) for s in new_sents]

    best_for_old = {i: (0.0, None) for i in range(len(old_sents))}
    for i, (old_sent, old_norm) in enumerate(zip(old_sents, old_norms)):
        for new_sent, new_norm in zip(new_sents, new_norms):
            score = _pair_score(old_norm, new_norm, old_sent, new_sent)
            if score > best_for_old[i][0]:
                best_for_old[i] = (score, new_sent)

    borderline = []
    for i, (score, partner) in best_for_old.items():
        if similarity - band <= score <= similarity + band:
            borderline.append({
                "score": round(score, 3),
                "old": old_sents[i],
                "closest_new": partner,
                "counted_as": "edited" if score >= similarity else "removed",
            })

    return {
        "removed": sentences_removed(old, new, similarity),
        "borderline": borderline,
        "old_sentences": len(old_sents),
        "new_sentences": len(new_sents),
    }


# -- unit alignment ------------------------------------------------
# A "unit" is one table row or one prose line: the thing a person edits.
_ROW_LINE_RE = re.compile(r"^\|.*\|$")
_SEP_LINE_RE = re.compile(r"^\|?\s*:?-{2,}")


def _unit_key(line: str) -> str:
    """What identifies a unit across a revision.

    A table row is identified by its step text, not the whole row, so that a
    changed Responsibility cell still matches the same step rather than
    looking like one row deleted and another added.
    """
    stripped = line.strip()
    if _ROW_LINE_RE.match(stripped):
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        return normalise(cells[-1]) if cells else normalise(stripped)
    return normalise(stripped)


def _units(text: str) -> list:
    return [line.strip() for line in (text or "").splitlines()
            if line.strip() and not _SEP_LINE_RE.match(line.strip())]


def aligned_units(old: str, new: str, similarity: float = 0.6) -> list:
    """Pair up the units that are the same step before and after the edit.

    Identical keys are paired first and taken out of the running; only the
    handful left over go through the O(n^2) fuzzy pass. A revision touches one
    to three units out of twenty, so this keeps the common case linear - the
    full pairwise scan was what made the dataset build crawl.
    """
    old_units, new_units = _units(old), _units(new)
    old_keys = [_unit_key(u) for u in old_units]
    new_keys = [_unit_key(u) for u in new_units]

    pairs, matched_old, matched_new = [], set(), set()
    by_key = {}
    for j, key in enumerate(new_keys):
        by_key.setdefault(key, []).append(j)
    for i, key in enumerate(old_keys):
        free = [j for j in by_key.get(key, []) if j not in matched_new]
        if free:
            j = free[0]
            matched_old.add(i)
            matched_new.add(j)
            pairs.append((old_units[i], new_units[j]))

    rest_old = [i for i in range(len(old_units)) if i not in matched_old]
    rest_new = [j for j in range(len(new_units)) if j not in matched_new]

    scored = []
    for i in rest_old:
        for j in rest_new:
            score = _pair_score(old_keys[i], new_keys[j], old_units[i], new_units[j])
            if score >= similarity:
                scored.append((score, i, j))
    scored.sort(key=lambda item: -item[0])
    for _, i, j in scored:
        if i in matched_old or j in matched_new:
            continue
        matched_old.add(i)
        matched_new.add(j)
        pairs.append((old_units[i], new_units[j]))

    return pairs
