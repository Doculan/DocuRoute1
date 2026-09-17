"""The quality gate for generated examples.

Every example is judged as if a staff member had written it and an admin were
about to rule on it. Anything that reads mechanically, or whose label a real
reviewer would dispute, is discarded rather than guessed at - a doubtful
example teaches the model a wrong answer, which is worse than one fewer row.

Checks fall into three groups:

* **Readability** - leftover markers, broken sentences, doubled spaces, edits
  that only a script would make.
* **Change sanity** - something actually changed, and not so much that the
  revision is really a rewrite.
* **Label consistency** - the claimed issues line up with what Layer 1 sees.
  Layer 1 is not the oracle, so this only rejects clear contradictions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .diffing import change_ratios, normalise, sentence_match_report
from .layer1_rules import run_layer1

# Markers that should never survive into an example.
_LEFTOVER_RE = re.compile(r"\[DEL\]|\[INS\]|\[/DEL\]|\[/INS\]|<br|&nbsp;|<!--|\*\*|`")
_DOUBLE_SPACE_RE = re.compile(r"[^\S\n]{2,}")
# A space before punctuation, or an empty parenthetical. The old pattern also
# flagged "| | |", but a three-column table whose first cell is empty is the
# normal shape here - it rejected 378 examples for having a correct header.
_BROKEN_PUNCT_RE = re.compile(r"\s+[.,;]|\(\s*\)")
# A row that lost its text entirely.
_EMPTY_ROW_RE = re.compile(r"^\|(\s*\|)+\s*$", re.M)
_SEP_ROW_RE = re.compile(r"^\|?\s*:?-{2,}")

# Issues the rule layer can be trusted to detect. If the example claims one of
# these and Layer 1 sees nothing of the kind, the example is suspect.
_RULE_CHECKABLE = {
    "numeric_changed", "modal_weakened", "negation_changed",
    "responsibility_changed", "excessive_deletion", "key_term_deleted",
}


# ---------------------------------------------------------------
#  Grammar and format, judged at the edit point
# ---------------------------------------------------------------
# Every one of these came out of a Checkpoint 4 sample. A generator that
# leaves "with first exhausting" or "each the" is teaching the model to spot
# broken English rather than a bad revision, so the example goes.

_GRAMMAR_FAULTS = (
    ("repeated function word",
     re.compile(r"\b(the|a|an|of|to|in|for|and|or|is|are|shall|with)\s+\1\b",
                re.IGNORECASE)),
    ("determiner before a determiner",
     re.compile(r"\b(each|every|all|both|any)\s+(the|a|an)\b", re.IGNORECASE)),
    # "all their fees" is English; "any their fees" is what a scope swap left
    # behind when it did not look at the word after it.
    ("\"any\" before a possessive",
     re.compile(r"\bany\s+(?:its|his|her|their|our|your)\b", re.IGNORECASE)),
    ("article before a finite verb",
     re.compile(r"\b(the|a|an)\s+(submits|receives|signs|checks|forwards|"
                r"prepares|issues|approves|records|releases|returns)\b",
                re.IGNORECASE)),
    # "submits the to the Office" - what a deletion leaves when it takes
    # the noun and leaves its article behind.
    ("article before a preposition",
     re.compile(r"\b(the|a|an)\s+(to|of|for|with|from|in|on|by|and|or)\b(?!-)",
                re.IGNORECASE)),
    ("preposition left dangling",
     re.compile(r"\b(?:to|of|for|with|from|in|on|by|the|a|an)\s*[.,;:]"
                r"|\b(?:to|of|for|with|from|in|on|by|the|a|an)\s*$",
                re.IGNORECASE | re.MULTILINE)),
    ("singular determiner with a plural noun",
     re.compile(r"\b(all|both)\s+(office|staff member|document|form|copy)\b",
                re.IGNORECASE)),
    ("\"with\" followed by a gerund",
     re.compile(r"\bwith\s+(?:first\s+)?\w+ing\b", re.IGNORECASE)),
)


# A unit that stops on a word which needs something after it. "Forwards the
# documents to the." and "Submits the form using." are what a deletion leaves
# when it takes the object and not the preposition.
_DANGLING_TAIL_RE = re.compile(
    r"\b(?:of|to|for|with|from|in|on|by|at|as|and|or|the|a|an|into|onto|per|"
    r"using|through|between|among|under|over|before|after|within|upon|"
    r"issues|submits|receives|prepares|forwards|signs|checks|records|releases)"
    r"\s*[.;:]?\s*$",
    re.IGNORECASE,
)
# A unit that opens mid-sentence. "No. 2, series of 2016 or the ..." is the
# back half of a sentence whose front half was removed.
_FRAGMENT_START_RE = re.compile(
    r"^\s*(?:(?:No|Nos|Sec|Art|s)\.\s*\d"
    r"|(?:and|or|but|which|that|who|whom|whose|then|thereof|therein|"
    r"series|portion)\b"
    r"|[a-z])",
)
_LEADING_ITEM_NO_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3})*\.?)(?=[\s)])")


def _unit_lines(text: str) -> list:
    """Every row or prose line, as the text a reader sees."""
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or _SEP_ROW_RE.match(stripped):
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            out.append((cells[-1] if cells else "", cells))
        else:
            out.append((stripped, None))
    return out


def _fragment_faults(old_text: str, new_text: str) -> set:
    """Fragments, lost item numbers and padded columns the edit introduced."""
    faults = set()
    old_units = _unit_lines(old_text)
    new_units = _unit_lines(new_text)

    old_bodies = {body for body, _ in old_units}
    old_dangling = sum(1 for body, _ in old_units if _DANGLING_TAIL_RE.search(body))
    old_fragment = sum(1 for body, _ in old_units if _FRAGMENT_START_RE.match(body))

    dangling = fragment = 0
    for body, cells in new_units:
        if not body or body in old_bodies:
            continue
        if len(body.split()) >= 4 and _DANGLING_TAIL_RE.search(body):
            dangling += 1
        if len(body.split()) >= 4 and _FRAGMENT_START_RE.match(body):
            fragment += 1
    if dangling > old_dangling:
        faults.add("a dangling word")
    if fragment > old_fragment:
        faults.add("a sentence fragment")

    # A line that survived the edit but lost the number that labelled it.
    # Comparing the sets of numbers instead flagged every deletion, since
    # removing a step naturally removes its number too - 607 discards, most of
    # them correct deletions.
    def without_number(body):
        return re.sub(r"\s+", " ", _LEADING_ITEM_NO_RE.sub("", body)).strip().lower()

    numbered_before = {without_number(body) for body, _ in old_units
                       if _LEADING_ITEM_NO_RE.match(body)}
    for body, _ in new_units:
        if _LEADING_ITEM_NO_RE.match(body) or len(body.split()) < 4:
            continue
        if without_number(body) in numbered_before:
            faults.add("an item number dropped from a surviving line")
            break

    # A row padded out with empty cells that its neighbours do not have.
    def empty_tail(units):
        return sum(1 for _, cells in units
                   if cells and len(cells) > 2 and not cells[-1])
    if empty_tail(new_units) > empty_tail(old_units):
        faults.add("a row padded with empty columns")

    return faults


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _table_shape_faults(text: str) -> set:
    """Column counts and truncated rows."""
    faults = set()
    rows = [line.strip() for line in (text or "").splitlines()
            if line.strip().startswith("|")]
    if not rows:
        return faults
    widths = [len(row.strip("|").split("|")) for row in rows]
    if len(set(widths)) > 1:
        faults.add("table rows have different column counts")
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if cells and cells[-1] and re.search(r"\b[a-z]{1,2}$", cells[-1]) and \
                not cells[-1].endswith((".", ")", ":", "%")):
            # A row that stops mid-word, as a wrapped row used to.
            if len(cells[-1].split()) > 3 and cells[-1].split()[-1].islower() \
                    and len(cells[-1].split()[-1]) <= 2:
                faults.add("row ends mid-phrase")
    return faults


def grammar_faults(old_text: str, new_text: str) -> set:
    """Faults the edit introduced, judged by comparing against the source.

    The master copies are not perfectly written, and a pre-existing awkward
    phrase says nothing about the edit.
    """
    def faults_in(text):
        found = {name for name, pattern in _GRAMMAR_FAULTS if pattern.search(text or "")}
        if not _balanced(text or ""):
            found.add("unbalanced parentheses")
        return found

    introduced = faults_in(new_text) - faults_in(old_text)
    introduced |= _table_shape_faults(new_text) - _table_shape_faults(old_text)
    introduced |= _fragment_faults(old_text, new_text)
    return introduced


@dataclass
class Verdict:
    ok: bool
    reasons: list = field(default_factory=list)
    borderline: list = field(default_factory=list)
    score: float = 1.0      # lower is more doubtful

    def reject(self, reason: str, weight: float = 1.0):
        self.ok = False
        self.reasons.append(reason)
        self.score = min(self.score, 1.0 - weight)
        return self


_CHECKS = (
    ("leftover marker or markup", _LEFTOVER_RE),
    ("doubled spaces", _DOUBLE_SPACE_RE),
    ("broken punctuation", _BROKEN_PUNCT_RE),
    ("empty table row", _EMPTY_ROW_RE),
)


def _defects(text: str) -> set:
    found = {name for name, pattern in _CHECKS if pattern.search(text or "")}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and len(stripped) < 3 and not stripped.startswith("|"):
            found.add("stray fragment line")
            break
    return found


def _readable(text: str, result: Verdict, side: str) -> None:
    """Kept for the source-quality survey; the gate uses _defects directly."""
    for name in sorted(_defects(text)):
        result.reject(f"{side}: {name}")


def check(example: dict, *, key_terms=None, related=None) -> Verdict:
    """Judge one candidate example."""
    old_text = example.get("old_text") or ""
    new_text = example.get("new_text") or ""
    verdict = example.get("verdict")
    issues = set(example.get("issues") or [])
    result = Verdict(ok=True)

    # -- readability ---------------------------------------------
    # Judge the *edit*, not the corpus. Several master copies already contain
    # "PROVIDED , that" and similar; rejecting an example because its source
    # section has a pre-existing artefact says nothing about the edit. Only
    # defects the edit introduced count.
    introduced = _defects(new_text) - _defects(old_text)
    for name in sorted(introduced):
        result.reject(f"edit introduced {name}")
    # A leftover generator marker is never acceptable, wherever it came from.
    if _LEFTOVER_RE.search(old_text) or _LEFTOVER_RE.search(new_text):
        result.reject("leftover marker or markup")

    # -- grammar and table shape at the edit point ----------------
    for fault in sorted(grammar_faults(old_text, new_text)):
        result.reject(f"edit introduced {fault}")

    # -- something changed, but not everything -------------------
    if normalise(old_text) == normalise(new_text):
        return result.reject("no change between old and new")
    ratios = change_ratios(old_text, new_text)
    if verdict == "approve" and ratios["net_deleted_word_ratio"] > 0.25:
        result.reject("approve example deletes too much to be uncontroversial")
    if ratios["net_deleted_word_ratio"] > 0.9:
        result.reject("almost nothing of the original survives")

    # -- labels ---------------------------------------------------
    if verdict not in config.VERDICTS:
        result.reject(f"unknown verdict {verdict!r}")
    unknown = issues - set(config.ISSUE_LABELS)
    if unknown:
        result.reject(f"unknown issue labels: {sorted(unknown)}")
    if verdict == "approve" and issues:
        result.reject("approve example carries issues")
    if verdict in ("needs_revision", "reject") and not issues:
        result.reject(f"{verdict} example carries no issue label")

    # -- consistency with the rule layer --------------------------
    layer1 = run_layer1(
        old_text, new_text,
        revision_meta={"change_reason": example.get("change_reason") or "recorded"},
        manual_key_terms=key_terms or [],
        related_sections=related or [],
    )
    flagged = {f["label"] for f in layer1.flags}

    for label in issues & _RULE_CHECKABLE:
        if label not in flagged:
            # These six are exactly the labels the rules detect reliably. If a
            # generator claims one and Layer 1 cannot see it, the edit did not
            # do what the generator thought - usually the role or term was not
            # in the entity list. Discard rather than guess (Phase 4 rule).
            result.reject(f"claimed {label} but Layer 1 did not see it", 0.6)

    if verdict == "approve":
        severe = {f["label"] for f in layer1.flags
                  if config.SEVERITY.get(f["label"]) == "high"}
        # A hard negative is *meant* to trip a rule, so it is flagged for
        # review rather than discarded.
        if severe and not example.get("hard_negative"):
            result.reject(
                f"approve example trips high-severity rules: {sorted(severe)}", 0.6
            )
        elif severe:
            result.score = min(result.score, 0.5)
            result.reasons.append(f"hard negative trips {sorted(severe)} by design")

    # -- borderline sentence matching -----------------------------
    # Only worth the O(n^2) comparison when the sentence count actually moved,
    # or when the example claims a removal. A table-row edit that leaves every
    # row in place cannot be a borderline removal, and running it on every
    # candidate dominated the build time.
    sentences_moved = (
        len(old_text.splitlines()) != len(new_text.splitlines())
        or "requirement_removed" in issues
        or "excessive_deletion" in issues
    )
    report = (sentence_match_report(old_text, new_text) if sentences_moved
              else {"borderline": []})
    if report["borderline"]:
        result.borderline = report["borderline"]
        # Whether these count as removed or edited decides whether the example
        # should carry requirement_removed, so a borderline pair makes the
        # label a coin toss.
        result.score = min(result.score, 0.55)
        result.reasons.append(
            f"{len(report['borderline'])} sentence match(es) near the 0.6 threshold"
        )

    return result


def summarise(results: list) -> dict:
    """Rejection counts by reason, for the build report."""
    from collections import Counter

    reasons = Counter()
    for result in results:
        if result.ok:
            continue
        for reason in result.reasons:
            reasons[reason.split(":")[0].strip()] += 1
    return dict(reasons)
