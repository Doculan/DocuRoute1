"""Four text checks reported as advisories: LAYER4_INPUT_SPEC.md section 7.

    unknown_word          a word in neither the dictionary nor the manuals
    inconsistent_terms    one thing called by two names within the section
    unfinished_sentence   a line cut short, or an item that lost its opening
    adds_requirement      a new obligation ("shall", "must", "should", ...)

Like the malformed-text checks, these are advisories and nothing more. They
carry ``affects_verdict: False`` - set explicitly, because Layer 3 treats an
advisory without the field as acting on the verdict - and no feature, so
Layers 2 and 3, the verdict, the pipeline fingerprint and the published
figures are exactly as they were. Each reports only what the edit introduced.

The English word list comes from pyspellchecker (pinned in requirements).
Without it the spelling check is skipped and the other three still run;
``scripts/check_setup.py`` says so.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from . import config
from .diffing import aligned_units, sentences_removed, word_diff
from .entities import get_entities
from .glossary import EQUIVALENT, NOT_EQUIVALENT, get_glossary

VOCABULARY_FILE = Path(__file__).parent / "manual_vocabulary.txt"

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
# E-mail addresses, URLs and _italicised_ foreign phrases are not words to check.
_MASK_RE = re.compile(r"https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b|_[^_\n]+_")
_ROW_RE = re.compile(r"^\|.*\|$")
_ITEM_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+(\S+)")
_STEP_RE = re.compile(r"^\|[^|]*\|\s*(\d+)\.\s")
_TERMINAL = (".", ";", ":", "!", "?", ")", "”", '"', ",")
_CONTINUES_RE = re.compile(r"\b(and|or)$")
# "should" and "is required" count as obligations here; "will" does not, since
# "will not be released" is future tense.
_OBLIGATION_RE = re.compile(
    r"\b(shall|must|should|(?:is|are) required(?: to)?|required)\b", re.IGNORECASE)
_OBLIGATION_WORDS = {"shall", "must", "should"}
_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "hundred", "thousand", "first", "second", "third", "fourth", "fifth",
}


def _advisory(label: str, clause: str, evidence: str, **extra) -> dict:
    return {"label": label, "clause": clause, "severity": "low",
            "affects_verdict": False, "evidence": evidence, **extra}


def _where(line: str) -> str:
    m = _ITEM_RE.match(line or "")
    if m:
        return m.group(1)
    m = _STEP_RE.match((line or "").strip())
    return f"step {m.group(1)}" if m else ""


def _line_with(text: str, word: str) -> str:
    for line in (text or "").splitlines():
        if re.search(rf"\b{re.escape(word)}\b", line, re.IGNORECASE):
            return line
    return ""


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


# -- unknown_word ---------------------------------------------------------------

@lru_cache(maxsize=1)
def _speller():
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return None
    return SpellChecker()


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset:
    """Words the check accepts beyond the dictionary: the manuals' own
    vocabulary (a reviewed, generated file) and the words of the entity lists
    and the glossary."""
    words = set()
    if VOCABULARY_FILE.exists():
        for line in VOCABULARY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line.lower())
    ents = get_entities()
    for phrase in list(ents.role_phrases) + list(ents.term_phrases):
        words.update(t.lower() for t in _TOKEN_RE.findall(phrase))
    glossary = config.PIPELINE_DIR / "glossary.txt"
    if glossary.exists():
        for line in glossary.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                words.update(t.lower() for t in _TOKEN_RE.findall(line))
    return frozenset(words)


def spelling_available() -> bool:
    return _speller() is not None


def _checkable_words(text: str) -> Counter:
    """Lower-case words of three or more letters. Capitalised words, acronyms
    and mixed case ("eNGAS", "ILS", names) are never checked, nor hyphen
    fragments ("pre-"), e-mail addresses, URLs or _italicised_ phrases."""
    found = Counter()
    text = _MASK_RE.sub(" ", text or "")
    for m in _TOKEN_RE.finditer(text):
        if text[m.start() - 1:m.start()] == "-" or text[m.end():m.end() + 1] == "-":
            continue
        base = re.sub(r"'s$", "", m.group(0))
        if base.islower() and len(base) >= 3:
            found[base] += 1
    return found


def unknown_word(old_text: str, new_text: str) -> list:
    speller = _speller()
    if speller is None:
        return []
    known = _vocabulary()
    before, after = _checkable_words(old_text), _checkable_words(new_text)
    candidates = [w for w in sorted(after)
                  if after[w] > before.get(w, 0) and w not in known]
    unknown = sorted(speller.unknown(candidates)) if candidates else []
    if not unknown:
        return []
    words = []
    for word in unknown:
        suggestion = speller.correction(word)
        words.append({"word": word,
                      "suggestion": suggestion if suggestion and suggestion != word else None,
                      "item": _where(_line_with(new_text, word))})
    return [_advisory("unknown_word", "7.5.3", ", ".join(w["word"] for w in words),
                      words=words)]


# -- inconsistent_terms -----------------------------------------------------------

def _stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ies", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def _typo_distance(a: str, b: str) -> int:
    from .layer1_rules import _typo_distance as distance
    return distance(a, b)


def inconsistent_terms(old_text: str, new_text: str) -> list:
    """A lower-case word swapped for another in some places and kept in
    others, where the glossary does not treat the two as the same. Pairs
    another check already reports are skipped: glossary non-equivalents,
    sense reversals, role swaps, number words, modals and spelling fixes."""
    glossary = get_glossary()
    roles = {r.lower() for r in get_entities().role_phrases}
    reversal = {w for pair in config.SENSE_REVERSALS for w in pair}
    modals = set(config.OBLIGATION_MODALS) | set(config.PERMISSIVE_MODALS)
    singles = [(o[0], n[0]) for o, n in word_diff(old_text, new_text).replaced
               if len(o) == 1 and len(n) == 1]
    groups, seen = {}, set()
    for a, b in singles:
        if not (a.isalpha() and b.isalpha() and a.islower() and b.islower()) or a == b:
            continue
        if a in _NUMBER_WORDS or b in _NUMBER_WORDS or a in modals or b in modals:
            continue
        if glossary.relation(a, b) in (EQUIVALENT, NOT_EQUIVALENT):
            continue
        if (a in reversal and b in reversal) or (a in roles and b in roles):
            continue
        if _stem(a) == _stem(b) or _typo_distance(a, b) <= 2:
            continue
        kept = re.search(rf"\b{re.escape(_stem(a))}\w*\b", new_text, re.IGNORECASE)
        if not kept or (_stem(a), _stem(b)) in seen:
            continue
        seen.add((_stem(a), _stem(b)))
        group = groups.setdefault(_stem(a), {"kept": kept.group(0).lower(),
                                             "introduced": [], "items": []})
        group["introduced"].append(b)
        item = _where(_line_with(new_text, b))
        if item and item not in group["items"]:
            group["items"].append(item)
    if not groups:
        return []
    found = list(groups.values())
    evidence = "; ".join(f"{g['kept']} / {', '.join(g['introduced'])}" for g in found)
    return [_advisory("inconsistent_terms", "7.5.3", evidence, groups=found)]


# -- unfinished_sentence ------------------------------------------------------------

def _is_heading(line: str) -> bool:
    words = line.split()
    if len(words) <= 8 and (line.isupper() or re.match(r"^\d+(\.\d+)*\s+[A-Z][A-Z ]+$", line)):
        return True
    # A numbered subsection title: "4.2 Releasing of the Monthly Food Allowance".
    if _ITEM_RE.match(line) and len(words) <= 12:
        long_words = [w for w in words[1:] if len(w) > 3 and w[:1].isalpha()]
        if long_words and sum(w[:1].isupper() for w in long_words) / len(long_words) >= 0.6:
            return True
    return False


def unfinished_sentence(old_text: str, new_text: str) -> list:
    old_of = {n: o for o, n in aligned_units(old_text, new_text)}
    old_lines = {u.strip() for u in (old_text or "").splitlines()}
    prose = [u.strip() for u in (old_text or "").splitlines()
             if u.strip() and not _ROW_RE.match(u.strip()) and not _is_heading(u.strip())]
    punctuated = (sum(u.endswith(_TERMINAL) for u in prose) / len(prose)) if prose else 1.0
    lines = []
    for line in (new_text or "").splitlines():
        line = line.strip()
        if not line or line in old_lines or _ROW_RE.match(line) or _is_heading(line):
            continue
        before = old_of.get(line)
        if (len(line.split()) >= 4 and not line.endswith(_TERMINAL)
                and not _CONTINUES_RE.search(line)
                and ((before and before.endswith(_TERMINAL))
                     or (before is None and punctuated >= 0.5))):
            lines.append({"kind": "no_final_punctuation", "item": _where(line), "line": line})
        m = _ITEM_RE.match(line)
        if m and m.group(2)[:1].islower() and len(m.group(2)) > 1:
            was = _ITEM_RE.match(before or "")
            if before is None or (was and not was.group(2)[:1].islower()):
                lines.append({"kind": "item_opens_lower_case", "item": m.group(1),
                              "was": was.group(2) if was else None,
                              "first_word": m.group(2), "line": line})
    if not lines:
        return []
    return [_advisory("unfinished_sentence", "7.5.3", _clip(lines[0]["line"], 120),
                      kinds=sorted({x["kind"] for x in lines}), lines=lines)]


# -- adds_requirement ---------------------------------------------------------------

def adds_requirement(old_text: str, new_text: str) -> list:
    """An added sentence stating an obligation, or a permission swapped for
    one ("may" -> "shall"). Information, not a fault."""
    from .layer1_rules import _swap_pairs
    found = []
    for sent in sentences_removed(new_text, old_text):   # new sentences with no match in old
        m = _OBLIGATION_RE.search(sent)
        if m:
            found.append({"kind": "added_sentence", "word": m.group(1).lower(),
                          "item": _where(sent), "sentence": sent.strip()})
    for a, b in _swap_pairs(old_text, new_text):
        if a.lower() in config.PERMISSIVE_MODALS and b.lower() in _OBLIGATION_WORDS:
            line = _line_with(new_text, b)
            found.append({"kind": "strengthened", "word": b.lower(), "was": a.lower(),
                          "item": _where(line), "sentence": line.strip()})
    if not found:
        return []
    return [_advisory("adds_requirement", "6.3", _clip(found[0]["sentence"], 160),
                      requirements=found)]


def text_advisories(old_text: str, new_text: str) -> list:
    """All four, in a fixed order."""
    out = []
    for check in (unknown_word, inconsistent_terms, unfinished_sentence, adds_requirement):
        out.extend(check(old_text, new_text))
    return out
