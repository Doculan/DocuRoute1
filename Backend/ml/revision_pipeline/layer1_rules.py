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
from .change_reason import blocks_submission, classify_reason
from .diffing import (
    aligned_units,
    change_ratios,
    marked_text,
    normalise,
    sentences_removed,
    word_diff,
    words,
)
from .entities import get_entities
from .glossary import EQUIVALENT, NOT_EQUIVALENT, UNKNOWN, get_glossary
from .malformed import malformed_advisories

# -- Patterns --------------------------------------------------

# A role carrying a numeric suffix: "Accounting Staff-4". Appendix A5 is
# explicit that changing the suffix is a responsibility change, not a numeric
# one, so these are matched first and excluded from number detection.
_SUFFIX_ROLE_RE = re.compile(r"\b[A-Za-z][\w]*(?:\s+[A-Za-z][\w]*){0,3}\s*-\s*\d+\b")
# Spacing around the suffix is not a difference between two people.
_ROLE_SPACING_RE = re.compile(r"\s*-\s*(\d+)\b")


def _normalise_role(role: str) -> str:
    """"Accounting Staff -3" and "Accounting Staff-3" are one role."""
    return _ROLE_SPACING_RE.sub(r"-\1", (role or "").strip())

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
# Explicit negated forms. The prefix regex this replaces matched any word
# starting un/non/dis/in, so "university", "information", "internal",
# "inspection" and "disbursement" all counted as negations and deleting a row
# containing one reported negation_changed.
_NEGATED_FORMS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(f) for f in config.NEGATED_FORMS) + r")\b",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[^\w\s]")


# -- Result container ------------------------------------------

@dataclass
class Layer1Result:
    hard_fails: list = field(default_factory=list)
    features: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    # Soft findings that are not issue labels: they never enter the trained
    # label space, so they cannot disturb Layer 2 or the fusion features, but
    # they do reach the reviewer and can nudge the verdict.
    advisories: list = field(default_factory=list)
    change_type: str = "substantive"
    marked: str = ""
    # The actual term pairs, so the explanation can name them rather than
    # referring vaguely to "the glossary".
    equivalent_swaps: list = field(default_factory=list)

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


def _legal_refs_lost(old_text: str, new_text: str) -> list[str]:
    """Statutes cited in the old text and no longer cited in the new.

    Compared canonically, so rewriting "R.A. 10173" as "Republic Act No.
    10173" is not a loss - that is a formatting change and
    `legal_reference_format` generates it as an approve.

    A citation that stops appearing is treated as a key term gone, because
    that is what it is: the obligation loses the named authority it rested on.
    Before this, the only trace was the statute's digits vanishing from the
    quantity tokens, which surfaced as `numeric_changed` - a finding the
    `rules_precise` policy then discarded, leaving the rule layer silent on an
    edit that replaces one authority with another.

    Returns the spelling as it appeared, so the reviewer sees "Republic Act
    10173" rather than the canonical key.
    """
    original = {}
    for match in _LEGAL_REF_RE.finditer(old_text or ""):
        original.setdefault(
            _canonical_legal_ref(match.group(0)), match.group(0).strip()
        )
    still_cited = {
        _canonical_legal_ref(match.group(0))
        for match in _LEGAL_REF_RE.finditer(new_text or "")
    }
    return [text for key, text in original.items() if key not in still_cited]


def _phrases_present(text: str, phrases: list[str]) -> set[str]:
    """Which of the given phrases occur in the text (case-insensitive)."""
    low = normalise(text)
    return {p for p in phrases if p and normalise(p) in low}


# The number that labels an item or a step, at the start of a line, a cell, or
# a clause: "3.15", "1.", "4.2.1". Renumbering a list is not a change of
# requirement, and treating it as one made every renumbered section look like a
# changed figure - and, where a sibling section still carried the old number,
# like a contradiction.
_ITEM_NUMBER_RE = re.compile(
    r"(?:(?<=^)|(?<=\|)|(?<=\n))\s*\d{1,3}(?:\.\d{1,3})*\.?(?=[\s)])",
    re.MULTILINE,
)


def _strip_item_numbers(text: str) -> str:
    """Blank out item and step numbers so they are not read as quantities."""
    return _ITEM_NUMBER_RE.sub(" ", text or "")


def _sense_reversals(old_unit: str, new_unit: str) -> list:
    """Pairs where the edit swapped one side of a reversal for the other.

    Returns (from, to) for each reversal found. Word boundaries keep "with"
    from matching inside "without", so with -> without is reported once, by the
    pair, rather than twice.
    """
    found = []
    for first, second in config.SENSE_REVERSALS:
        for a, b in ((first, second), (second, first)):
            pattern_a = re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
            pattern_b = re.compile(rf"\b{re.escape(b)}\b", re.IGNORECASE)
            lost = len(pattern_a.findall(old_unit)) - len(pattern_a.findall(new_unit))
            gained = len(pattern_b.findall(new_unit)) - len(pattern_b.findall(old_unit))
            if lost > 0 and gained > 0:
                found.append((a, b))
                break
    return found


_LEGAL_PREFIX_MAP = (
    (re.compile(r"^republic\s+act", re.IGNORECASE), "ra"),
    (re.compile(r"^r\.?a\.?", re.IGNORECASE), "ra"),
    (re.compile(r"^executive\s+order", re.IGNORECASE), "eo"),
    (re.compile(r"^e\.?o\.?", re.IGNORECASE), "eo"),
    (re.compile(r"^memorandum\s+circular", re.IGNORECASE), "mc"),
    (re.compile(r"^m\.?c\.?", re.IGNORECASE), "mc"),
    (re.compile(r"^presidential\s+decree", re.IGNORECASE), "pd"),
)


def _canonical_legal_ref(reference: str) -> str:
    """"R.A. 9184" and "Republic Act No. 9184" are the same statute.

    Both spellings are used across the manuals, so rewriting one as the other
    is a formatting change. Comparing the raw strings made it a changed figure.
    """
    text = reference.strip()
    for pattern, short in _LEGAL_PREFIX_MAP:
        if pattern.match(text):
            digits = re.sub(r"\D", "", text)
            return f"{short}{digits}"
    return re.sub(r"\s+", " ", text.lower())


def _numeric_tokens(text: str) -> set[str]:
    """Numbers, durations, legal references and frequency words.

    Role suffixes are masked out first, so "Accounting Staff-4" becomes
    "Accounting Staff" and reassigning a step to Staff-7 is not reported as a
    number change.
    """
    masked = _SUFFIX_ROLE_RE.sub(lambda m: m.group(0).rsplit("-", 1)[0], text or "")
    masked = _strip_item_numbers(masked)
    tokens: set[str] = set()
    tokens.update(_canonical_legal_ref(m.group(0)) for m in _LEGAL_REF_RE.finditer(masked))
    tokens.update(m.group(0).lower() for m in _DURATION_RE.finditer(masked))
    tokens.update(m.group(0).lower() for m in _NUMBER_RE.finditer(masked))
    for w in words(masked):
        lw = w.lower()
        if lw in _NUMBER_WORDS or lw in _FREQUENCY_WORDS:
            tokens.add(lw)

    # "30 days" already contains "30". Keeping both double-counted the change
    # and produced evidence reading "30, 30 days, 60, 60 days".
    phrases = {t for t in tokens if " " in t}
    return {
        token for token in tokens
        if " " in token or not any(
            re.search(rf"\b{re.escape(token)}\b", phrase) for phrase in phrases
        )
    }


def _modal_counts(text: str) -> dict:
    low = " " + normalise(text) + " "
    return {
        modal: low.count(" " + modal + " ")
        for modal in config.OBLIGATION_MODALS + config.PERMISSIVE_MODALS
    }


# "No." before a figure is the abbreviation for "number". Counting it as the
# negation "no" made rewriting "R.A. 9184" as "Republic Act No. 9184" look like
# a reversed requirement.
_NUMBER_ABBREV_RE = re.compile(r"\bnos?\.?\s*(?=\d)", re.IGNORECASE)


def _negation_tokens(text: str) -> list:
    low = _NUMBER_ABBREV_RE.sub(" ", normalise(text))
    found = [w for w in words(low) if w in _NEGATIONS]
    found += [m.group(0) for m in _NEGATED_FORMS_RE.finditer(low)]
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


def _drop_contained(phrases) -> set:
    """Keep only the longest form of each matched phrase.

    The entity list holds both "Accounting Staff" and "Accounting Staff-4", so
    a single mention matched both and the evidence read
    "accounting staff, accounting staff-4" as if two roles had changed.
    """
    kept = {p for p in phrases if p}
    return {
        phrase for phrase in kept
        if not any(other != phrase and phrase in other for other in kept)
    }


def _quote_list(values) -> str:
    return ", ".join(f'"{v}"' for v in list(values)[:5])


def _is_modal_pair(a: str, b: str) -> bool:
    """True when a swap is an obligation becoming a permission."""
    left, right = a.lower(), b.lower()
    return (left in config.OBLIGATION_MODALS and right in config.PERMISSIVE_MODALS) or (
        right in config.OBLIGATION_MODALS and left in config.PERMISSIVE_MODALS
    )


def _strip_punct(s: str) -> str:
    """Drop punctuation, then re-collapse whitespace.

    Removing a character leaves a gap behind it, so "sign ." became "sign "
    and compared unequal to "sign" - a moved full stop read as a substantive
    change.
    """
    return re.sub(r"\s+", " ", _PUNCT_RE.sub("", s)).strip()


# -- Main entry point ------------------------------------------

def _role_keys(text: str, role_phrases, numbers) -> set:
    found = _phrases_present(text, role_phrases)
    found |= {_normalise_role(m.group(0)) for m in _SUFFIX_ROLE_RE.finditer(text or "")}
    return _drop_contained(
        normalise(_normalise_role(r)) for r in found
        if normalise(_normalise_role(r)) not in numbers
    )


_EXPANSION_RE = re.compile(r"\(([A-Z][A-Za-z.]{1,9})\)")


def _is_acronym_expansion(role: str, with_full: str, with_acronym: str) -> bool:
    """True when one side writes the role out and the other uses its acronym.

    "Forwards the DV to the BAC" and "Forwards the DV to the Bids and Awards
    Committee (BAC)" name the same party. Without this, spelling an acronym out
    on first use - which is a documentation improvement - was reported as a
    change of responsibility.
    """
    for match in _EXPANSION_RE.finditer(with_full or ""):
        acronym = match.group(1)
        # The role has to be the thing being expanded - the words immediately
        # before the bracket. Merely appearing somewhere earlier in the row is
        # not enough: a step mentioning "(DV)" would otherwise suppress every
        # role change in that row, which is what happened.
        before = normalise(with_full[:match.start()]).rstrip()
        if not before.endswith(role):
            continue
        if re.search(rf"\b{re.escape(acronym)}\b", with_acronym or ""):
            return True
    return False


_ROW_LINE = re.compile(r"^\|.*\|$")
_SEP_LINE = re.compile(r"^\|?\s*:?-{2,}")


def _inherit_roles(text: str) -> str:
    """Fill an empty Responsibility cell with the role above it (A3).

    A procedure table leaves the cell blank while the same person keeps
    working, so a blank cell does not mean "nobody". Reading it literally, a
    step that changed hands from an inherited role looked like no change at
    all, and deleting the row that carried the name looked like the role had
    left the section.
    """
    out, current = [], ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not _ROW_LINE.match(stripped) or _SEP_LINE.match(stripped):
            out.append(line)
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            out.append(line)
            continue
        if cells[0]:
            current = cells[0]
        elif current:
            cells[0] = current
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _unit_level_deltas(old_text: str, new_text: str, key_terms, role_phrases):
    """Roles, key terms and figures that changed *within* a surviving unit.

    Each pair is one step before and after the edit, so a role, a form name or
    a figure that moved off that step counts even when the section as a whole
    still mentions it somewhere. Units that were added or deleted outright are
    not paired: those are deletions, and the deletion rules already cover them.
    """
    roles_changed, terms_lost = set(), set()
    nums_gone, nums_new = set(), set()
    reversals = []

    for old_unit, new_unit in aligned_units(_inherit_roles(old_text),
                                            _inherit_roles(new_text)):
        if normalise(old_unit) == normalise(new_unit):
            continue
        reversals.extend(_sense_reversals(old_unit, new_unit))
        old_nums = _numeric_tokens(old_unit)
        new_nums = _numeric_tokens(new_unit)
        nums_gone |= old_nums - new_nums
        nums_new |= new_nums - old_nums

        old_roles = _role_keys(old_unit, role_phrases, old_nums)
        new_roles = _role_keys(new_unit, role_phrases, new_nums)
        # Expanding an acronym in place - "BAC" becoming "Bids and Awards
        # Committee (BAC)" - adds a name without moving the responsibility. A
        # role still spelled out somewhere in the other side of the pair is the
        # same party, so it is not a change.
        old_norm, new_norm = normalise(old_unit), normalise(new_unit)
        moved = {
            role for role in old_roles ^ new_roles
            if not (role in old_norm and role in new_norm)
            and not _is_acronym_expansion(role, old_unit, new_unit)
            and not _is_acronym_expansion(role, new_unit, old_unit)
        }
        roles_changed |= moved

        terms_lost |= (
            _phrases_present(old_unit, key_terms)
            - _phrases_present(new_unit, key_terms)
        )

    return roles_changed, terms_lost, nums_gone, nums_new, reversals


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
    # Clause 6.3 in two tiers, graded by the same function the API uses when
    # it accepts the submission, so a revision cannot pass one and fail the
    # other. Rows predating that validation still land here as hard fails.
    reason_tier, reason_message = classify_reason(
        meta.get("change_reason"), meta.get("section_title"),
    )
    if blocks_submission(reason_tier):
        result.hard_fails.append({
            "reason": "no_change_reason",
            "clause": "6.3",
            "detail": (
                "No reason for the change was recorded."
                if reason_tier == "missing"
                else "The recorded reason does not describe the change."
            ),
        })
    elif reason_tier == "weak":
        result.advisories.append({
            "label": "vague_change_reason",
            "clause": "6.3",
            "severity": "low",
            # A reason too vague to confirm the change was planned is not
            # something to wave through on the model's word, so this one does
            # move the verdict. Contrast the malformed-text advisories below.
            "affects_verdict": True,
            "evidence": reason_message,
        })

    # Text the edit has broken: a cross-reference dropped inside a citation, an
    # acronym whose name was deleted, a bracket left open. No issue label
    # covers any of it, so without this the reviewer sees nothing at all. These
    # are reported, never acted on - see malformed.py.
    result.advisories.extend(malformed_advisories(old_text, new_text))
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
    # A statute that stops being cited counts here too. The entity lists hold
    # the manuals' own vocabulary, not the statutes they rest on, so without
    # this the rules had nothing to say about an authority being swapped.
    terms_lost = sorted(set(terms_lost) | set(_legal_refs_lost(old_text, new_text)))
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

    # Which way the negation went. "A negation changed" leaves the reader to
    # work out whether the requirement was switched on or off.
    from collections import Counter

    added_neg = sorted((Counter(new_neg) - Counter(old_neg)).elements())
    removed_neg = sorted((Counter(old_neg) - Counter(new_neg)).elements())

    # -- Numbers ---------------------------------------------------
    old_nums = _numeric_tokens(old_text)
    new_nums = _numeric_tokens(new_text)
    nums_gone = sorted(old_nums - new_nums)
    nums_new = sorted(new_nums - old_nums)
    nums_changed = nums_gone + nums_new
    feats["numeric_changed_count"] = len(nums_changed)

    # -- Roles -----------------------------------------------------
    old_roles = _phrases_present(old_text, ents.role_phrases)
    new_roles = _phrases_present(new_text, ents.role_phrases)
    # Suffixed roles tracked separately so "Staff-4" -> "Staff-7" counts.
    old_roles |= {_normalise_role(m.group(0)) for m in _SUFFIX_ROLE_RE.finditer(old_text or "")}
    new_roles |= {_normalise_role(m.group(0)) for m in _SUFFIX_ROLE_RE.finditer(new_text or "")}
    # A frequency or duration word is not a role, however it was mined.
    # "Quarterly" reached the role list from a table column header and was
    # being reported as a change of responsibility.
    old_role_keys = _drop_contained(
        normalise(_normalise_role(r)) for r in old_roles
        if normalise(_normalise_role(r)) not in old_nums
    )
    new_role_keys = _drop_contained(
        normalise(_normalise_role(r)) for r in new_roles
        if normalise(_normalise_role(r)) not in new_nums
    )
    roles_changed = sorted(old_role_keys ^ new_role_keys)

    # A whole-section comparison cannot see a step change hands *within* the
    # section: give step 4 to an officer who already owns step 7 and the set of
    # roles present is identical. Roles, key terms and figures are therefore
    # compared a second time on matched units - the same step before and after
    # - and the two views are unioned. Nothing the set view caught is lost.
    (unit_roles, unit_terms_lost, unit_nums_gone, unit_nums_new,
     unit_reversals) = _unit_level_deltas(
        old_text, new_text, key_terms, ents.role_phrases
    )
    if unit_roles:
        roles_changed = sorted(set(roles_changed) | unit_roles)
    # The section-wide comparison sees the same acronym expansion the unit-level
    # one does, so the filter has to run on the union rather than on one branch.
    roles_changed = [
        role for role in roles_changed
        if not _is_acronym_expansion(role, new_text, old_text)
        and not _is_acronym_expansion(role, old_text, new_text)
    ]
    if unit_terms_lost:
        terms_lost = sorted(set(terms_lost) | unit_terms_lost)
        feats["key_terms_deleted_count"] = len(terms_lost)
    if unit_reversals:
        feats["negation_changed"] = negation_delta + len(unit_reversals)
    if unit_nums_gone or unit_nums_new:
        nums_gone = sorted(set(nums_gone) | unit_nums_gone)
        nums_new = sorted(set(nums_new) | unit_nums_new)
        nums_changed = nums_gone + nums_new
        feats["numeric_changed_count"] = len(nums_changed)

    feats["role_terms_changed_count"] = len(roles_changed)

    # -- Glossary swaps --------------------------------------------
    swaps_all = _swap_pairs(old_text, new_text)
    equivalent_swaps, non_equivalent_swaps, unknown_swaps = [], [], []
    for a, b in swaps_all:
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
    result.equivalent_swaps = equivalent_swaps

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
        # Name the pair. "An obligation was changed to a permission" leaves
        # the reviewer to hunt for which word moved.
        modal_pairs = [(a, b) for a, b in swaps_all if _is_modal_pair(a, b)]
        if modal_pairs:
            evidence = ", ".join(f'"{a}" became "{b}"' for a, b in modal_pairs[:3])
        else:
            evidence = "an obligation became a permission"
        flags.append(_flag("modal_weakened", evidence, {"pairs": modal_pairs}))
    if negation_delta or unit_reversals:
        if unit_reversals and not negation_delta:
            # A sense reversal uses no negation word at all: "before" became
            # "after", "at least" became "at most". The requirement is reversed
            # just as surely, so it is reported under the same label with the
            # pair itself as the evidence.
            action = "reversed"
            evidence = ", ".join(
                f'"{a}" became "{b}"' for a, b in unit_reversals[:3]
            )
        else:
            if added_neg and not removed_neg:
                action, words_used = "added", added_neg
            elif removed_neg and not added_neg:
                action, words_used = "removed", removed_neg
            else:
                action, words_used = "changed", added_neg + removed_neg
            reversal_words = {w.lower() for pair in unit_reversals for w in pair}
            unexplained = [w for w in words_used if w.lower() not in reversal_words]
            if unit_reversals and not unexplained:
                # "with" became "without" is one change, not a reversal plus an
                # added negation word.
                action = "reversed"
                evidence = ", ".join(
                    f'"{a}" became "{b}"' for a, b in unit_reversals[:3]
                )
            else:
                evidence = _quote_list(unexplained or words_used) or "a negation"
                if unit_reversals:
                    evidence += ", and " + ", ".join(
                        f'"{a}" became "{b}"' for a, b in unit_reversals[:2]
                    )
        flags.append(_flag(
            "negation_changed", evidence,
            {"action": action, "added": added_neg, "removed": removed_neg,
             "reversals": unit_reversals},
        ))
    if nums_changed:
        # Direction, not just "a figure changed": one pair reads as
        # "30 days" -> "60 days"; several are listed on each side.
        from_text, to_text = _quote_list(nums_gone), _quote_list(nums_new)
        if nums_gone and nums_new:
            evidence, direction = f"{from_text} to {to_text}", "changed"
        elif nums_new:
            evidence, direction = to_text, "added"
        else:
            evidence, direction = from_text, "removed"
        flags.append(_flag(
            "numeric_changed", evidence,
            {"values": nums_changed, "from_values": nums_gone,
             "to_values": nums_new, "direction": direction,
             "from_text": from_text, "to_text": to_text},
        ))
    if roles_changed:
        flags.append(_flag("responsibility_changed", ", ".join(roles_changed[:5]),
                           {"roles": roles_changed}))
    if removed_sentences:
        flags.append(_flag("requirement_removed", removed_sentences[0][:160],
                           {"count": len(removed_sentences)}))
    # A shall -> may swap is already reported as modal_weakened, which says
    # more. Reporting it again as a non-equivalent term describes the same
    # change twice in the same paragraph.
    # A pair is reported once. A modal weakening and a sense reversal each have
    # their own label, so neither is repeated here as a term swap.
    reversal_words = {w.lower() for pair in unit_reversals for w in pair}
    reportable_swaps = [
        (a, b) for a, b in non_equivalent_swaps
        if not (weakened and _is_modal_pair(a, b))
        and not (a.lower() in reversal_words and b.lower() in reversal_words)
    ]
    if reportable_swaps:
        flags.append(_flag(
            "non_equivalent_term",
            ", ".join(f'"{a}" became "{b}"' for a, b in reportable_swaps[:5]),
            {"swaps": reportable_swaps},
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
