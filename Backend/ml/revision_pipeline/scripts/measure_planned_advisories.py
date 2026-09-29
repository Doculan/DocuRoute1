"""Measure the four planned advisory checks. A prototype, not the checks.

LAYER4_INPUT_SPEC.md section 7 plans four Layer 1 advisories: unknown_word,
inconsistent_terms, unfinished_sentence and adds_requirement. Nothing here is
imported by Layer 1 or anything else; it exists so the false-positive counts
in the spec can be reproduced, and as a starting point when the checks are
built. It reuses Layer 1's diff helpers read-only.

Needs pyspellchecker for the English word list, which the project does not
install (whether it should is an open decision). Install it somewhere
harmless and put it on the path:

    pip install --target <dir> pyspellchecker
    PYTHONPATH=<dir> ../venv/Scripts/python.exe \\
        ml/revision_pipeline/scripts/measure_planned_advisories.py \\
        --db <a COPY of db.sqlite3>

Takes about ten minutes, almost all of it the 2,762 generated edits.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
PIPELINE = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[2]))

from revision_pipeline import config  # noqa: E402
from revision_pipeline.diffing import aligned_units, sentences, sentences_removed, word_diff  # noqa: E402
from revision_pipeline.entities import get_entities  # noqa: E402
from revision_pipeline.glossary import EQUIVALENT, NOT_EQUIVALENT, get_glossary  # noqa: E402
from revision_pipeline.layer1_rules import _is_modal_pair, _swap_pairs, _typo_distance  # noqa: E402

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_ROW_RE = re.compile(r"^\|.*\|$")
_ITEM_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+(\S+)")
_STEP_RE = re.compile(r"^\|[^|]*\|\s*(\d+)\.\s")
_OBLIGATION_RE = re.compile(r"\b(shall|must|(?:is|are) required to|required)\b", re.I)
_TERMINAL = (".", ";", ":", "!", "?", ")", "”", '"', ",")
_CONTINUES_RE = re.compile(r"\b(and|or)$")
# E-mail addresses, URLs and _italicised_ foreign phrases are not words to check.
_MASK_RE = re.compile(r"https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b|_[^_\n]+_")


def _where(line: str) -> str:
    m = _ITEM_RE.match(line)
    if m:
        return m.group(1)
    m = _STEP_RE.match(line.strip())
    return f"step {m.group(1)}" if m else ""


def _line_with(text: str, word: str) -> str:
    for line in (text or "").splitlines():
        if re.search(rf"\b{re.escape(word)}\b", line, re.I):
            return line
    return ""


# -- unknown_word ---------------------------------------------------------------

def unknown_words(old: str, new: str, vocab: set, speller=None) -> list:
    """Lower-case words the edit introduced that are in neither the
    dictionary nor the manuals' own vocabulary. Capitalised words, acronyms
    and mixed case ("eNGAS", "ILS", names) are never checked."""
    def counts(text):
        found = Counter()
        text = _MASK_RE.sub(" ", text or "")
        for m in _TOKEN_RE.finditer(text):
            if text[m.start() - 1:m.start()] == "-" or text[m.end():m.end() + 1] == "-":
                continue            # "pre-", "multi-": a prefix, not a word
            base = re.sub(r"'s$", "", m.group(0))
            if base.islower() and len(base) >= 3:
                found[base] += 1
        return found

    before, after = counts(old), counts(new)
    return [
        {"word": word, "suggestion": speller.correction(word) if speller else None,
         "item": _where(_line_with(new, word))}
        for word in sorted(after)
        if after[word] > before.get(word, 0) and word not in vocab
    ]


# -- inconsistent_terms -----------------------------------------------------------

def _stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ies", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def inconsistent_terms(old: str, new: str) -> list:
    """A word swapped for another in some places and kept in others, where
    the glossary does not treat the two as the same. Pairs another check
    already reports are skipped."""
    glossary = get_glossary()
    roles = {r.lower() for r in get_entities().role_phrases}
    reversal = {w for pair in config.SENSE_REVERSALS for w in pair}
    singles = [(o[0], n[0]) for o, n in word_diff(old, new).replaced
               if len(o) == 1 and len(n) == 1]
    grouped, seen = {}, set()
    for a, b in singles:
        if not (a.isalpha() and b.isalpha()) or a.lower() == b.lower():
            continue
        if glossary.relation(a, b) in (EQUIVALENT, NOT_EQUIVALENT):
            continue            # the same thing, or already non_equivalent_term
        if a.lower() in reversal and b.lower() in reversal:
            continue            # already negation_changed
        if a.lower() in roles and b.lower() in roles:
            continue            # already responsibility_changed
        if _stem(a) == _stem(b) or _typo_distance(a.lower(), b.lower()) <= 2:
            continue            # a spelling fix: unknown_word's business
        if _is_modal_pair(a, b):
            continue
        kept = re.search(rf"\b{re.escape(_stem(a))}\w*\b", new, re.I)
        if not kept or (_stem(a), _stem(b)) in seen:
            continue
        seen.add((_stem(a), _stem(b)))
        group = grouped.setdefault(_stem(a), {"kept": kept.group(0), "introduced": [], "items": []})
        group["introduced"].append(b)
        item = _where(_line_with(new, b))
        if item and item not in group["items"]:
            group["items"].append(item)
    return list(grouped.values())


# -- unfinished_sentence ------------------------------------------------------------

def _is_heading(line: str) -> bool:
    return len(line.split()) <= 8 and bool(
        line.isupper() or re.match(r"^\d+(\.\d+)*\s+[A-Z][A-Z ]+$", line))


def unfinished_lines(old: str, new: str) -> list:
    """Changed or added prose lines that end without punctuation where the
    section's lines have it, or that open an item in lower case where it did
    not before. Table rows and headings are skipped."""
    old_of = {n: o for o, n in aligned_units(old, new)}
    old_lines = {u.strip() for u in (old or "").splitlines()}
    prose = [u.strip() for u in (old or "").splitlines()
             if u.strip() and not _ROW_RE.match(u.strip()) and not _is_heading(u.strip())]
    punctuated = (sum(u.endswith(_TERMINAL) for u in prose) / len(prose)) if prose else 1.0
    out = []
    for line in (new or "").splitlines():
        line = line.strip()
        if not line or line in old_lines or _ROW_RE.match(line) or _is_heading(line):
            continue
        before = old_of.get(line)
        if (len(line.split()) >= 4 and not line.endswith(_TERMINAL)
                and not _CONTINUES_RE.search(line)
                and ((before and before.endswith(_TERMINAL))
                     or (before is None and punctuated >= 0.5))):
            out.append({"kind": "no_final_punctuation", "item": _where(line), "line": line})
        m = _ITEM_RE.match(line)
        if m and m.group(2)[:1].islower() and len(m.group(2)) > 1:
            was = _ITEM_RE.match(before or "")
            if before is None or (was and not was.group(2)[:1].islower()):
                out.append({"kind": "item_opens_lower_case", "item": m.group(1),
                            "was": was.group(2) if was else None, "line": line})
    return out


# -- adds_requirement ---------------------------------------------------------------

def added_requirements(old: str, new: str) -> list:
    """An added sentence stating an obligation, or a permission swapped for
    one ("may" -> "shall")."""
    out = []
    for sent in sentences_removed(new, old):     # sentences of new with no match in old
        m = _OBLIGATION_RE.search(sent)
        if m:
            out.append({"kind": "added_sentence", "word": m.group(1).lower(),
                        "item": _where(sent), "sentence": sent.strip()})
    for a, b in _swap_pairs(old, new):
        if a.lower() in config.PERMISSIVE_MODALS and _OBLIGATION_RE.fullmatch(b):
            line = _line_with(new, b)
            out.append({"kind": "strengthened", "word": b.lower(), "was": a.lower(),
                        "item": _where(line), "sentence": line.strip()})
    return out


# -- measurement ------------------------------------------------------------------

def _words(text: str) -> set:
    return {re.sub(r"'s$", "", t).lower() for t in _TOKEN_RE.findall(text or "")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="a COPY of db.sqlite3")
    args = ap.parse_args()
    try:
        from spellchecker import SpellChecker
    except ImportError:
        raise SystemExit("pyspellchecker is not on the path; see the docstring")

    speller = SpellChecker()
    dictionary = set(speller.word_frequency.dictionary)
    ents = json.loads((PIPELINE / "entities.json").read_text(encoding="utf-8"))
    entity_words = {w for v in ents.values() if isinstance(v, list) for p in v for w in _words(str(p))}
    glossary_words = {w for line in (PIPELINE / "glossary.txt").read_text(encoding="utf-8").splitlines()
                      if not line.startswith("#") for w in _words(line)}

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    manuals = defaultdict(list)
    for title, subtitle, content in db.execute(
            "select m.title, s.subtitle, s.content from api_manualsection s "
            "join api_manual m on m.id = s.manual_id order by m.title, s.\"order\""):
        if "LIST OF FORMS" not in (subtitle or "").upper():
            manuals[title].append((subtitle, content or ""))
    doc_words = {t: set().union(*(_words(c) for _, c in secs)) for t, secs in manuals.items()}
    full_vocab = dictionary | entity_words | glossary_words | set().union(*doc_words.values())
    print(f"{len(manuals)} manuals")

    fixtures = json.loads((PIPELINE / "tests/fixtures/planned_advisories.json").read_text(encoding="utf-8"))
    print("\n== the fixture edits")
    for edit in fixtures["edits"]:
        o, n = edit["old_text"], edit["new_text"]
        print(edit["name"])
        print("  unknown_word       ", unknown_words(o, n, full_vocab, speller))
        print("  inconsistent_terms ", inconsistent_terms(o, n))
        print("  unfinished_sentence", unfinished_lines(o, n))
        print("  adds_requirement   ", added_requirements(o, n))

    print("\n== unknown_word: each manual scanned with the other 18 as vocabulary")
    flagged = Counter()
    for title, secs in manuals.items():
        others = set().union(*(w for t, w in doc_words.items() if t != title))
        vocab = dictionary | entity_words | glossary_words | others
        hits = {h["word"] for _, c in secs for h in unknown_words("", c, vocab)}
        flagged.update(hits)
    print(f"  {len(flagged)} distinct words:", sorted(flagged))

    print("\n== unfinished_sentence: every line of the manuals treated as new")
    kinds, lines = Counter(), 0
    for secs in manuals.values():
        for _, c in secs:
            lines += sum(1 for ln in c.splitlines() if ln.strip())
            kinds.update(f["kind"] for f in unfinished_lines("", c))
    print(f"  {lines} lines:", dict(kinds))

    sents = [s for secs in manuals.values() for _, c in secs for s in sentences(c)]
    print(f"\n== sentences stating an obligation: "
          f"{sum(1 for s in sents if _OBLIGATION_RE.search(s))} of {len(sents)}")

    print("\n== generated edits: rows each check fires on")
    data = [json.loads(line) for line in
            (PIPELINE.parents[0] / "datasets/context_v2/all.jsonl").open(encoding="utf-8")]
    fires, totals = defaultdict(Counter), Counter()
    for row in data:
        group = "harmless (approve)" if row["verdict"] == "approve" else "the rest"
        totals[group] += 1
        o, n = row["old_text"], row["new_text"]
        for name, found in (("unknown_word", unknown_words(o, n, full_vocab)),
                            ("inconsistent_terms", inconsistent_terms(o, n)),
                            ("unfinished_sentence", unfinished_lines(o, n)),
                            ("adds_requirement", added_requirements(o, n))):
            fires[group][name] += bool(found)
    for group, n in totals.items():
        print(f"  {group} ({n} rows):", dict(fires[group]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
