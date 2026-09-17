"""Export a blind label audit: examples to judge, answers kept separately.

The point is to find out whether a person reading the edit cold agrees with the
label the generator assigned. That only works if the label is not on the page,
so this writes two files:

* ``label_audit.csv``    - the examples, with empty columns to fill in.
* ``label_audit_key.csv`` - what each one was labelled, and by which generator.

Sampling is seeded and stratified by verdict, so the audit reflects the
dataset's own mix rather than whichever examples sort first.

    py ml/revision_pipeline/scripts/export_label_audit.py
"""

from __future__ import annotations

import argparse
import collections
import csv
import difflib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                                # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402


def changed_lines(old_text: str, new_text: str) -> str:
    """The lines that moved, marked - what a reviewer actually reads."""
    out = []
    for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(),
                                     lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        out.append(line)
    return "\n".join(out)


def stratified_sample(rows: list, count: int, rng: random.Random) -> list:
    """Sample in proportion to the verdict mix, so the audit is representative."""
    by_verdict = collections.defaultdict(list)
    for row in rows:
        by_verdict[row["verdict"]].append(row)

    total = len(rows)
    picked = []
    for verdict in config.VERDICTS:
        pool = by_verdict.get(verdict, [])
        if not pool:
            continue
        share = max(1, round(count * len(pool) / total))
        picked += rng.sample(pool, min(share, len(pool)))

    # Rounding can overshoot or undershoot by one or two.
    rng.shuffle(picked)
    if len(picked) > count:
        picked = picked[:count]
    elif len(picked) < count:
        remaining = [r for r in rows if r not in picked]
        picked += rng.sample(remaining, min(count - len(picked), len(remaining)))
    rng.shuffle(picked)
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=str(config.DATASET_DIR / "all.jsonl"))
    ap.add_argument("--out-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--seed", type=int, default=config.SEED + 7)
    ap.add_argument("--prefix", default="label_audit",
                    help="basename for the two files, so an earlier "
                         "audit that is still open is not overwritten")
    args = ap.parse_args()

    rows = load_jsonl(args.dataset)
    sample = stratified_sample(rows, args.count, random.Random(args.seed))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = out_dir / f"{args.prefix}.csv"
    key_path = out_dir / f"{args.prefix}_key.csv"

    with audit_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "no", "id", "document", "section", "section_type",
            "change_reason", "changed_lines", "units_edited",
            "your_verdict", "your_issues", "notes",
        ])
        for number, row in enumerate(sample, 1):
            writer.writerow([
                number, row["id"], row["document_no"],
                f"{row['section_number']} {row['section_title']}".strip(),
                row["section_type"],
                row.get("change_reason") or "(none given)",
                changed_lines(row["old_text"], row["new_text"]),
                row.get("edited_units", 1),
                "", "", "",
            ])

    with key_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "no", "id", "verdict", "issues", "generator", "strategy",
            "quality_score", "hard_negative", "note",
        ])
        for number, row in enumerate(sample, 1):
            writer.writerow([
                number, row["id"], row["verdict"], "; ".join(row["issues"]),
                row["generator"], row.get("strategy", ""),
                row.get("quality_score", 1.0), row.get("hard_negative", False),
                row.get("note", ""),
            ])

    counts = collections.Counter(r["verdict"] for r in sample)
    print(f"{len(sample)} examples, seed {args.seed}")
    print("  verdict mix:", dict(counts))
    print(f"  to judge : {audit_path}")
    print(f"  answers  : {key_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
