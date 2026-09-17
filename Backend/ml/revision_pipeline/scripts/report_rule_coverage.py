"""How much of the dataset the rule layer can already explain.

The spec asks that at least 40% of the non-approve examples be ones the Layer 1
rules cannot reliably catch - otherwise Layer 2 spends its capacity
re-learning the rule layer. ``generators.RULE_HARD`` declares which generators
those are, but a declaration drifts: the unit-level comparison added in Phase 4
made role reassignment visible to the rules, and the set was not updated by
itself.

This measures it instead. A non-approve example counts as rule-hard when
Layer 1 raises no flag at all on it.

    py ml/revision_pipeline/scripts/report_rule_coverage.py
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config, generators                    # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402
from revision_pipeline.entities import get_entities                 # noqa: E402
from revision_pipeline.layer1_rules import run_layer1               # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=str(config.DATASET_DIR / "all.jsonl"))
    args = ap.parse_args()

    rows = load_jsonl(args.dataset)
    key_terms = get_entities().term_phrases

    seen = collections.Counter()
    silent = collections.Counter()
    for row in rows:
        if row["verdict"] == "approve":
            continue
        result = run_layer1(
            row["old_text"], row["new_text"],
            revision_meta={"change_reason": row.get("change_reason") or "recorded"},
            manual_key_terms=key_terms,
        )
        seen[row["generator"]] += 1
        if not result.flags and not result.failed:
            silent[row["generator"]] += 1

    total = sum(seen.values())
    hard = sum(silent.values())
    print(f"non-approve examples: {total}")
    print(f"rules raise nothing:  {hard}  ({100 * hard / max(total, 1):.0f}%, target >= 40%)")
    print("\nper generator (share the rules cannot see):")
    for name, count in seen.most_common():
        share = 100 * silent[name] / count
        declared = " [declared rule-hard]" if name in generators.RULE_HARD else ""
        print(f"   {name:<28} {silent[name]:>4}/{count:<4} {share:>3.0f}%{declared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
