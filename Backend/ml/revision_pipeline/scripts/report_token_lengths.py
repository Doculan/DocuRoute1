"""Token-length distribution of a built dataset.

Kept out of ``build_dataset.py`` so the build does not need torch or a
tokenizer download. Phase 4 design point 3: the earlier measurements were on
whole sections with no edit applied, and the markers an edit inserts change the
count, so ``max_length`` has to be re-checked against the real examples.

    py ml/revision_pipeline/scripts/report_token_lengths.py \\
        --dataset ml/datasets/context_v2/all.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                                # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402
from revision_pipeline.layer2_model import build_text_a, build_tokenizer  # noqa: E402
from revision_pipeline.diffing import marked_text                   # noqa: E402


def percentile(values: list, fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=str(config.DATASET_DIR / "all.jsonl"))
    args = ap.parse_args()

    rows = load_jsonl(args.dataset)
    tokenizer = build_tokenizer()

    change_lengths, full_lengths = [], []
    for row in rows:
        marked = row.get("marked") or marked_text(row["old_text"], row["new_text"])
        text_a = build_text_a(row.get("section_number", ""),
                              row.get("section_title", ""), marked)
        change_lengths.append(len(tokenizer(text_a, add_special_tokens=False)["input_ids"]))
        context = row.get("context") or ""
        full_lengths.append(len(tokenizer(text_a, context)["input_ids"]))

    print(f"examples: {len(rows)}")
    for name, values in (("change half (never truncated)", change_lengths),
                         ("change + context", full_lengths)):
        print(f"\n{name}")
        for fraction in (0.5, 0.75, 0.9, 0.95, 0.99, 1.0):
            print(f"   p{int(fraction * 100):<3} {percentile(values, fraction)}")
        for limit in (256, 384, 512):
            covered = sum(1 for v in values if v <= limit) / max(len(values), 1)
            print(f"   <= {limit:<4} {covered:.1%}")

    print(f"\nconfigured MAX_LENGTH: {config.MAX_LENGTH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
