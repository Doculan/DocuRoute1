"""Layer 1 - deterministic rule checks over a proposed revision.

Produces three things:

* **hard fails** - conditions that make a revision unreviewable as submitted,
  which short-circuit the pipeline to ``reject``;
* **features** - a fixed, numeric description of what changed, handed to the
  fusion model in Layer 3;
* **flags** - issue labels the rules are confident enough to raise on their own,
  each carrying the clause it relates to and the actual words involved.

Nothing here is learned. That is the point: these checks are auditable, and the
model in Layer 2 exists to catch what rules cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .diffing import (
    change_ratios,
    marked_text,
    normalise,
    sentences_removed,
    word_diff,
    words,
)
from .entities import get_entities
from .glossary import EQUIVALENT, NOT_EQUIVALENT, UNKNOWN, get_glossary

# -- Patterns --------------------------------------------------

# A role carrying a numeric suffix: "Accounting Staff-4". Appendix A5 is
# explicit that changing the suffix is a responsibility change, not a numeric
# one, so these are matched first and excluded from number detection.
_SUFFIX_ROLE_RE = re.compile(r"\b[A-Za-z][\w]*(?:\s+[A-Za-z][\w]*){0,3}-\d+\b")

# "Republic Act 10173", "Executive Order No. 02, series of 2016"
_LEGAL_REF_RE = re.compile(
    r"\b(?:Republic\s+Act|R\.?A\.?|Executive\s+Order|E\.?O\.?|Memorandum\s+Circular"
    r"|M\.?C\.?|Presidential\s+Decree|CMO)\s*(?:No\.?\s*)?\d[\w.\-]*",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Bare numbers, and numbers spelled out. "Thirty (30)" yields both halves, so a
# disagreement between the word and the figure is visible.
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand",
}
_FREQUENCY_WORDS = {
    "daily", "weekly", "monthly", "quarterly", "annually", "yearly",
    "immediately", "timely", "hourly", "semestral",
}
_DURATION_RE = re.compile(
    r"\b\d+\s*(?:calendar\s+|working\s+|business\s+)?"
    r"(?:second|minute|hour|day|week|month|year|semester)s?\b",
    re.IGNORECASE,
)

_NEGATIONS = {"not", "no", "never", "without", "except", "neither", "nor", "none"}
_NEG_PREFIX_RE = re.compile(r"\b(?:un|non|dis|in)-?[a-z]{3,}\b", re.IGNORECASE)

_PUNCT_RE = re.compile(r"[^\w\s]")


# -- Result container ------------------------------------------

@dataclass
class Layer1Result:
    hard_fails: list = field(default_factory=list)
    features: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    change_type: str = "substantive"
    marked: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.hard_fails)

    def feature_vector(self) -> list[float]:
        """Flat vector in config.LAYER1_FEATURES order, plus one-hot change type."""
        vec = [float(self.features.get(name, 0)) for name in config.LAYER1_FEATURES]
        vec += [1.0 if self.change_type == t else 0.0 for t in config.CHANGE_TYPES]
        return vec

    def to_dict(self) -> dict:
        return {
            "hard_fails": self.hard_fails,
            "features": self.features,
            "flags": self.flags,
            "change_type": self.change_type,
        }


# -- Helpers ---------------------------------------------------

def _flag(label: str, evidence, extra: dict | None = None) -> dict:
    out = {
        "label": label,
        "clause": config.ISSUE_CLAUSE.get(label, ""),
        "severity": config.SEVERITY.get(label, "low"),
        "evidence": evidence,
    }
    if extra:
        out.update(extra)
    return out


def _phrases_present(text: str, phrases: list[str]) -> set[str]:
    """Which of the given phrases occur in the text (case-insensitive)."""
    low = normalise(text)
    return {p for p in phrases if p and normalise(p) in low}


def _numeric_tokens(text: str) -> set[str]:
    """Numbers, durations, legal references and frequency words.

    Role suffixes are masked out first, so "Accounting Staff-4" becomes
    "Accounting Staff" and reassigning a step to Staff-7 is not reported as a
    number change.
    """
    masked = _SUFFIX_ROLE_RE.sub(lambda m: m.group(0).rsplit("-", 1)[0], text or "")
    tokens: set[str] = set()
    tokens.update(m.group(0).lower() for m in _LEGAL_REF_RE.finditer(masked))
    tokens.update(m.group(0).lower() for m in _DURATION_RE.finditer(masked))
    tokens.update(m.group(0).lower() for m in _NUMBER_RE.finditer(masked))
    for w in words(masked):
        lw = w.lower()
        if lw in _NUMBER_WORDS or lw in _FREQUENCY_WORDS:
            tokens.add(lw)
    return tokens


def _modal_counts(text: str) -> dict:
    low = " " + normalise(text) + " "
    return {
        modal: low.count(" " + modal + " ")
        for modal in config.OBLIGATION_MODALS + config.PERMISSIVE_MODALS
    }


def _negation_tokens(text: str) -> list:
    low = normalise(text)
    found = [w for w in words(low) if w in _NEGATIONS]
    found += [m.group(0) for m in _NEG_PREFIX_RE.finditer(low)]
    return found


def _swap_pairs(old: str, new: str) -> list:
    """Word-level replacements as (old_word, new_word).

    Only equal-length replacement runs are paired up. An uneven run is
    rewriting rather than term substitution, and the other features cover it.
    """
    pairs = []
    for old_chunk, new_chunk in word_diff(old, new).replaced:
        if len(old_chunk) == len(new_chunk):
            pairs.extend(zip(old_chunk, new_chunk))
    return pairs


def _typo_distance(a: str, b: str) -> int:
    """Levenshtein distance, iterative two-row form."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _strip_punct(s: str) -> str:
    """Drop punctuation, then re-collapse whitespace.

    Removing a character leaves a gap behind it, so "sign ." became "sign "
    and compared unequal to "sign" - a moved full stop read as a substantive
    change.
    """
    return re.sub(r"\s+", " ", _PUNCT_RE.sub("", s)).strip()


# -- Main entry point ------------------------------------------

def run_layer1(
    old_text: str,
    new_text: str,
    revision_meta: dict = None,
    manual_key_terms: list = None,
    related_sections: list = None,
) -> Layer1Result:
    """Rule checks for one proposed revision.

    ``revision_meta`` carries at least ``change_reason``. ``manual_key_terms``
    are terms specific to this manual. ``related_sections`` are the texts of
    other sections in the same document, used for the cross-reference check.
    """
    meta = revision_meta or {}
    glossary = get_glossary()
    ents = get_entities()
    key_terms = list(manual_key_terms or []) + ents.term_phrases

    result = Layer1Result()

    # -- Hard fails -----------------------------------------------
    # There is deliberately no department check: FAM documents live in the
    # CAS/CME test departments, so it would reject valid revisions.
    # PROGRESS.md, decision 3.
    if not (meta.get("change_reason") or "").strip():
        result.hard_fails.append({
            "reason": "no_change_reason",
            "clause": "6.3",
            "detail": "No reason for the change was recorded.",
        })
    if not (new_text or "").strip():
        result.hard_fails.append({
            "reason": "empty_revision",
            "clause": "7.5.3",
            "detail": "The proposed text is empty.",
        })
    elif normalise(old_text) == normalise(new_text):
        result.hard_fails.append({
            "reason": "no_change",
            "clause": "7.5.3",
            "detail": "The proposed text is identical to the current text.",
        })

    result.marked = marked_text(old_text, new_text)

    # -- Size of the change ---------------------------------------
    ratios = change_ratios(old_text, new_text)
    removed_sentences = sentences_removed(old_text, new_text)
    feats = {
        "deleted_line_ratio": round(ratios["deleted_line_ratio"], 4),
        "deleted_word_ratio": round(ratios["deleted_word_ratio"], 4),
        "inserted_word_ratio": round(ratios["inserted_word_ratio"], 4),
        "net_deleted_word_ratio": round(ratios["net_deleted_word_ratio"], 4),
        "sentences_removed": len(removed_sentences),
    }

    # -- Key terms -------------------------------------------------
    old_terms = _phrases_present(old_text, key_terms)
    new_terms = _phrases_present(new_text, key_terms)
    terms_lost = sorted(old_terms - new_terms)
    feats["key_terms_deleted_count"] = len(terms_lost)

    # -- Modals ----------------------------------------------------
    old_modals = _modal_counts(old_text)
    new_modals = _modal_counts(new_text)
    obligation_lost = sum(
        max(0, old_modals[m] - new_modals[m]) for m in config.OBLIGATION_MODALS
    )
    permissive_gained = sum(
        max(0, new_modals[m] - old_modals[m]) for m in config.PERMISSIVE_MODALS
    )
    # A weakening needs both halves: an obligation disappearing *and* a
    # permission appearing. Losing "shall" because the sentence was deleted is
    # a deletion, not a weakening.
    weakened = min(obligation_lost, permissive_gained)
    feats["modal_weakened_count"] = weakened

    # -- Negation --------------------------------------------------
    old_neg = _negation_tokens(old_text)
    new_neg = _negation_tokens(new_text)
    negation_delta = abs(len(old_neg) - len(new_neg))
    feats["negation_changed"] = negation_delta

    # -- Numbers ---------------------------------------------------
    old_nums = _numeric_tokens(old_text)
    new_nums = _numeric_tokens(new_text)
    nums_changed = sorted((old_nums - new_nums) | (new_nums - old_nums))
    feats["numeric_changed_count"] = len(nums_changed)

    # -- Roles -----------------------------------------------------
    old_roles = _phrases_present(old_text, ents.role_phrases)
    new_roles = _phrases_present(new_text, ents.role_phrases)
    # Suffixed roles tracked separately so "Staff-4" -> "Staff-7" counts.
    old_roles |= {m.group(0) for m in _SUFFIX_ROLE_RE.finditer(old_text or "")}
    new_roles |= {m.group(0) for m in _SUFFIX_ROLE_RE.finditer(new_text or "")}
    old_role_keys = {normalise(r) for r in old_roles}
    new_role_keys = {normalise(r) for r in new_roles}
    roles_changed = sorted(old_role_keys ^ new_role_keys)
    feats["role_terms_changed_count"] = len(roles_changed)

    # -- Glossary swaps --------------------------------------------
    equivalent_swaps, non_equivalent_swaps, unknown_swaps = [], [], []
    for a, b in _swap_pairs(old_text, new_text):
        rel = glossary.relation(a, b)
        if rel == EQUIVALENT:
            equivalent_swaps.append((a, b))
        elif rel == NOT_EQUIVALENT:
            non_equivalent_swaps.append((a, b))
        elif rel == UNKNOWN and a.lower() != b.lower():
            unknown_swaps.append((a, b))
    feats["equivalent_swaps"] = len(equivalent_swaps)
    feats["non_equivalent_swaps"] = len(non_equivalent_swaps)
    feats["unknown_swaps"] = len(unknown_swaps)

    # -- Cross-reference conflicts (Appendix A6) -------------------
    # A number or role that changed here but still appears with its old value
    # elsewhere in the document is a contradiction in waiting.
    conflicts = []
    for other in related_sections or []:
        other_norm = normalise(other)
        for token in old_nums - new_nums:
            if token and token in other_norm:
                conflicts.append({"value": token, "kind": "numeric"})
        for role in old_role_keys - new_role_keys:
            if role and role in other_norm:
                conflicts.append({"value": role, "kind": "role"})
    feats["cross_ref_conflict_count"] = len(conflicts)

    result.features = feats

    # -- Change type -----------------------------------------------
    result.change_type = _classify_change(
        old_text, new_text, feats, equivalent_swaps, non_equivalent_swaps
    )

    # -- Flags -----------------------------------------------------
    flags = []
    # Judged on what actually left the section, not on positional churn:
    # reordering two list items is not a deletion.
    if feats["net_deleted_word_ratio"] > config.THRESHOLDS["excessive_deletion_word_ratio"]:
        flags.append(_flag(
            "excessive_deletion",
            "{:.0%} of the wording was removed".format(feats["net_deleted_word_ratio"]),
            {"ratio": feats["net_deleted_word_ratio"]},
        ))
    if terms_lost:
        flags.append(_flag("key_term_deleted", ", ".join(terms_lost[:5]),
                           {"terms": terms_lost}))
    if weakened:
        flags.append(_flag("modal_weakened",
                           "an obligation was changed to a permission"))
    if negation_delta:
        changed_neg = sorted(set(old_neg) ^ set(new_neg))
        flags.append(_flag("negation_changed",
                           ", ".join(changed_neg[:5]) or "a negation changed"))
    if nums_changed:
        flags.append(_flag("numeric_changed", ", ".join(nums_changed[:5]),
                           {"values": nums_changed}))
    if roles_changed:
        flags.append(_flag("responsibility_changed", ", ".join(roles_changed[:5]),
                           {"roles": roles_changed}))
    if removed_sentences:
        flags.append(_flag("requirement_removed", removed_sentences[0][:160],
                           {"count": len(removed_sentences)}))
    if non_equivalent_swaps:
        flags.append(_flag(
            "non_equivalent_term",
            ", ".join(a + " -> " + b for a, b in non_equivalent_swaps[:5]),
            {"swaps": non_equivalent_swaps},
        ))
    if conflicts:
        flags.append(_flag(
            "contradicts_manual",
            ", ".join(str(c["value"]) for c in conflicts[:5]),
            {"conflicts": conflicts},
        ))
    result.flags = flags
    return result


def _classify_change(old, new, feats, equivalent_swaps, non_equivalent_swaps) -> str:
    """One of config.CHANGE_TYPES."""
    old_norm, new_norm = normalise(old), normalise(new)

    # Cosmetic: identical once whitespace, case and punctuation are ignored...
    if _strip_punct(old_norm) == _strip_punct(new_norm):
        return "cosmetic"

    # ...or a typo correction, provided nothing meaningful moved with it.
    ow, nw = words(old_norm), words(new_norm)
    if len(ow) == len(nw):
        diffs = [(a, b) for a, b in zip(ow, nw) if a != b]
        if diffs and all(
            _typo_distance(a, b) <= config.THRESHOLDS["cosmetic_typo_distance"]
            and a not in _NEGATIONS and b not in _NEGATIONS
            for a, b in diffs
        ):
            if not (feats["numeric_changed_count"]
                    or feats["role_terms_changed_count"]
                    or feats["modal_weakened_count"]
                    or non_equivalent_swaps):
                return "cosmetic"

    substantive_signals = (
        feats["numeric_changed_count"]
        or feats["role_terms_changed_count"]
        or feats["modal_weakened_count"]
        or feats["negation_changed"]
        or feats["sentences_removed"]
        or feats["key_terms_deleted_count"]
        or feats["inserted_word_ratio"] > 0
        or feats["deleted_word_ratio"] > 0
    )
    if non_equivalent_swaps and not substantive_signals:
        return "terminology_non_equivalent"
    if equivalent_swaps and not non_equivalent_swaps and not substantive_signals:
        return "terminology_equivalent"
    return "substantive"
