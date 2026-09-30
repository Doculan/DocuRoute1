"""Measure the four text advisories' false positives (advisory_checks.py).

The figures in LAYER4_INPUT_SPEC.md section 7 come from this script:

* unknown_word on the 19 manuals, each scanned with only the other 18 as
  vocabulary and every word treated as newly typed - the worst case;
* unfinished_sentence with every line of the manuals treated as new;
* all four on the 2,762 generated edits, where a hit on a harmless
  (approve) edit is a false positive.

    ../venv/Scripts/python.exe ml/revision_pipeline/scripts/measure_planned_advisories.py \\
        --db <a COPY of db.sqlite3>

Takes about ten minutes, almost all of it the generated edits.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
PIPELINE = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[2]))

from revision_pipeline import advisory_checks as A  # noqa: E402
from revision_pipeline.diffing import sentences  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="a COPY of db.sqlite3")
    args = ap.parse_args()
    speller = A._speller()
    if speller is None:
        raise SystemExit("pyspellchecker is not installed: pip install -r requirements.txt")

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    manuals = defaultdict(list)
    for title, subtitle, content in db.execute(
            "select m.title, s.subtitle, s.content from api_manualsection s "
            "join api_manual m on m.id = s.manual_id order by m.title, s.\"order\""):
        if "LIST OF FORMS" not in (subtitle or "").upper():
            manuals[title].append(content or "")
    print(f"{len(manuals)} manuals")

    fixtures = json.loads((PIPELINE / "tests/fixtures/planned_advisories.json").read_text(encoding="utf-8"))
    print("\n== the fixture edits")
    for edit in fixtures["edits"]:
        found = A.text_advisories(edit["old_text"], edit["new_text"])
        print(f"  {edit['name']}: {[a['label'] for a in found]}")

    print("\n== unknown_word: each manual scanned with the other 18 as vocabulary")
    words = {t: set().union(*(A._checkable_words(c) for c in secs)) for t, secs in manuals.items()}
    extra = set(A._vocabulary()) - {w.strip() for w in A.VOCABULARY_FILE.read_text(encoding="utf-8").splitlines()}
    flagged = Counter()
    for title in manuals:
        others = set().union(*(w for t, w in words.items() if t != title))
        candidates = [w for w in words[title] if w not in others and w not in extra]
        flagged.update(speller.unknown(candidates))
    print(f"  {len(flagged)} distinct words:", sorted(flagged))

    print("\n== unfinished_sentence: every line of the manuals treated as new")
    kinds, lines = Counter(), 0
    for secs in manuals.values():
        for c in secs:
            lines += sum(1 for ln in c.splitlines() if ln.strip())
            for adv in A.unfinished_sentence("", c):
                kinds.update(x["kind"] for x in adv["lines"])
    print(f"  {lines} lines:", dict(kinds))

    sents = [s for secs in manuals.values() for c in secs for s in sentences(c)]
    print(f"\n== sentences stating an obligation: "
          f"{sum(1 for s in sents if A._OBLIGATION_RE.search(s))} of {len(sents)}")

    print("\n== generated edits: rows each check fires on")
    fires, totals = defaultdict(Counter), Counter()
    for line in (PIPELINE.parents[0] / "datasets/context_v2/all.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        group = "harmless (approve)" if row["verdict"] == "approve" else "the rest"
        totals[group] += 1
        for adv in A.text_advisories(row["old_text"], row["new_text"]):
            fires[group][adv["label"]] += 1
    for group, n in totals.items():
        print(f"  {group} ({n} rows):", dict(fires[group]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
