"""Text an edit has broken, reported to the reviewer as an advisory.

None of this is an issue label. The ten labels in ``config.ISSUE_LABELS`` are
the trained space; adding to it would change the model's output dimension and
the fusion feature vector. These findings live in ``Layer1Result.advisories``,
carry no feature, and never reach Layer 2 or Layer 3's classifier.

What they are for: a revision can be perfectly sound in meaning and still
arrive with the text mangled - a cross-reference dropped inside a citation, an
acronym whose name was deleted, a bracket left open. No issue label covers
that, so without this the reviewer sees nothing at all.

Only faults the edit *introduced* are reported. The manuals contain plenty of
pre-existing oddities from extraction, and blaming a submitter for those would
make the advisory worthless.
"""

from __future__ import annotations

import re

# Abbreviations whose trailing full stop is not a sentence end. A generator or
# an editor that splits on ". " will cut these in half.
_ABBREVIATION_STEMS = (
    "E.O", "EO", "R.A", "RA", "P.D", "PD", "M.C", "MC", "C.O.A", "COA",
    "No", "Nos", "Sec", "Secs", "Art", "Rev", "Dept", "Atty", "Engr",
    "Hon", "Gov", "Pres", "Inc", "Corp", "Ltd", "St", "Mr", "Ms", "Mrs", "Dr",
)
_STEM_ALTERNATION = "|".join(
    re.escape(stem) for stem in sorted(_ABBREVIATION_STEMS, key=len, reverse=True)
)

# "E.O (see 4.1 Public Bidding). No. 2" - something was inserted between the
# abbreviation and the full stop that belongs to it.
_SPLIT_ABBREVIATION_RE = re.compile(
    r"\b(?:" + _STEM_ALTERNATION + r")\s*\([^)]{0,120}\)\s*\.",
    re.IGNORECASE,
)

# A legal prefix with its number gone: "governed by E.O." and nothing after.
#
# Written as prefix-then-check rather than one regex. With an optional "No.?"
# before a lookahead, the engine happily matches "No" and hands the "." to the
# lookahead, so "Republic Act No. 10173" reads as truncated when it is not.
_CITATION_PREFIX_RE = re.compile(
    r"\b(?:Republic\s+Act|R\.?A\.|Executive\s+Order|E\.?O\.|"
    r"Presidential\s+Decree|P\.?D\.|Memorandum\s+Circular|M\.?C\.)",
    re.IGNORECASE,
)
# What a healthy citation looks like immediately after the prefix.
_CITATION_NUMBER_RE = re.compile(r"^\s*(?:No\.?\s*)?\d")

# A bracketed acronym with nothing in front of it to be the acronym *of*.
_ORPHAN_ACRONYM_RE = re.compile(
    r"(?:(?<=^)|(?<=[.;:|])|(?<=\bthe\s)|(?<=\ba\s)|(?<=\ban\s))"
    r"\s*\(([A-Z]{2,6})\)",
    re.MULTILINE,
)

_OPENERS = {"(": ")", "[": "]"}
_CLOSERS = {")": "(", "]": "["}


def _unbalanced_lines(text: str) -> list[str]:
    """Lines whose brackets do not close. Quotes are left alone - the manuals
    use them unevenly for legitimate reasons."""
    faulty = []
    for line in (text or "").splitlines():
        stack = []
        for char in line:
            if char in _OPENERS:
                stack.append(char)
            elif char in _CLOSERS:
                if stack and stack[-1] == _CLOSERS[char]:
                    stack.pop()
                else:
                    stack.append(char)
                    break
        if stack:
            faulty.append(line.strip())
    return faulty


def _spans(pattern, text: str) -> list[str]:
    return [match.group(0).strip() for match in pattern.finditer(text or "")]


def _new_only(new_items, old_items) -> list:
    """Faults the edit introduced, not ones it inherited."""
    seen = list(old_items)
    fresh = []
    for item in new_items:
        key = re.sub(r"\s+", " ", item).strip().lower()
        matched = next(
            (o for o in seen if re.sub(r"\s+", " ", o).strip().lower() == key), None
        )
        if matched is None:
            fresh.append(item)
        else:
            seen.remove(matched)
    return fresh


def _truncated(text: str, skip_spans=()) -> list[str]:
    """Citation prefixes left without a number, with a little context.

    ``skip_spans`` suppresses prefixes already reported as a split
    abbreviation: one break should not be announced twice.
    """
    out = []
    for match in _CITATION_PREFIX_RE.finditer(text or ""):
        if _CITATION_NUMBER_RE.match(text[match.end():match.end() + 24]):
            continue
        if any(start <= match.start() < end for start, end in skip_spans):
            continue
        start = max(0, match.start() - 28)
        out.append(("..." if start else "") + text[start:match.end()].strip())
    return out


def malformed_faults(old_text: str, new_text: str) -> list[dict]:
    """Text defects the edit introduced, newest-first by seriousness.

    Returns dicts of ``{label, evidence, kind}``. ``label`` is
    ``malformed_citation`` where a legal reference is involved and
    ``malformed_text`` otherwise, because those read very differently to a
    reviewer deciding whether to send a revision back.
    """
    old_text = old_text or ""
    new_text = new_text or ""
    faults = []

    for span in _new_only(_spans(_SPLIT_ABBREVIATION_RE, new_text),
                          _spans(_SPLIT_ABBREVIATION_RE, old_text)):
        faults.append({
            "label": "malformed_citation",
            "kind": "split_abbreviation",
            "evidence": span,
        })

    split_new = [m.span() for m in _SPLIT_ABBREVIATION_RE.finditer(new_text)]
    split_old = [m.span() for m in _SPLIT_ABBREVIATION_RE.finditer(old_text)]
    for span in _new_only(_truncated(new_text, split_new),
                          _truncated(old_text, split_old)):
        faults.append({
            "label": "malformed_citation",
            "kind": "truncated_citation",
            "evidence": span,
        })

    for span in _new_only(_spans(_ORPHAN_ACRONYM_RE, new_text),
                          _spans(_ORPHAN_ACRONYM_RE, old_text)):
        faults.append({
            "label": "malformed_text",
            "kind": "orphaned_acronym",
            "evidence": span,
        })

    # Brackets are compared by count, not by line text. Many manual lines
    # arrive from extraction already unbalanced; an edit that touches such a
    # line changes its text, and a line-by-line comparison then reads a
    # pre-existing fault as newly introduced - which it was, 12 times out of
    # 18 across the corpus. Only an increase means the edit broke something.
    old_unbalanced = _unbalanced_lines(old_text)
    new_unbalanced = _unbalanced_lines(new_text)
    if len(new_unbalanced) > len(old_unbalanced):
        introduced = _new_only(new_unbalanced, old_unbalanced)
        for line in introduced[:len(new_unbalanced) - len(old_unbalanced)]:
            faults.append({
                "label": "malformed_text",
                "kind": "unbalanced_brackets",
                "evidence": line[:120],
            })

    return faults


def malformed_advisories(old_text: str, new_text: str) -> list[dict]:
    """``malformed_faults`` shaped for ``Layer1Result.advisories``.

    ``affects_verdict`` is False: a mangled bracket is worth showing a
    reviewer and is not grounds for the pipeline to overrule its own verdict.
    Clause 7.5.3 covers changes staying identifiable and controlled, which is
    what text broken by an edit stops being.
    """
    grouped: dict = {}
    for fault in malformed_faults(old_text, new_text):
        entry = grouped.setdefault(fault["label"], {
            "label": fault["label"],
            "clause": "7.5.3",
            "severity": "low",
            "affects_verdict": False,
            "kinds": [],
            "evidence": "",
        })
        if fault["kind"] not in entry["kinds"]:
            entry["kinds"].append(fault["kind"])
        entry.setdefault("_spans", []).append(fault["evidence"])

    advisories = []
    for entry in grouped.values():
        spans = entry.pop("_spans", [])
        entry["evidence"] = "; ".join(spans[:3])
        if len(spans) > 3:
            entry["evidence"] += f" (+{len(spans) - 3} more)"
        advisories.append(entry)
    return advisories
