"""Per-label issue scores under the shipped policy, pooled across folds.

`evaluate_folds.py` reports issue micro-F1, which is one number over all ten
labels at once. That is the right headline, and it hides exactly the thing a
reader needs to know: which labels the system is actually good at. A label
with 89 examples can score near zero without moving micro-F1 much.

Scored the way the pipeline reports issues - `select_issue_labels` under the
configured policy, with each fold's precise labels learned from that fold's
*training* rows - so these numbers describe what the application does, not a
separate evaluation path.

    py ml/revision_pipeline/scripts/report_per_label.py \
        --predictions-dir ml/datasets/context_v2/folds_from_drive \
        --out ml/reports/per_label_issue_f1.md
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                                # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402
from revision_pipeline.layer3_fusion import select_issue_labels     # noqa: E402
from revision_pipeline.layer1_rules import run_layer1               # noqa: E402
from revision_pipeline.scripts.evaluate_folds import (              # noqa: E402
    ISSUE_THRESHOLD,
    index_dataset,
    precise_rule_labels,
)


# Each example is one fold's validation row and another fold's test row, so
# running Layer 1 per prediction does the work twice over: 5,514 calls for
# 2,762 examples. Layer 1 is deterministic in the text, so cache on the id.
_RULES_CACHE: dict = {}


def _rule_issues(row: dict) -> set:
    key = row.get("id")
    if key not in _RULES_CACHE:
        layer1 = run_layer1(
            row.get("old_text", ""), row.get("new_text", ""),
            revision_meta={"change_reason": row.get("change_reason") or "recorded"},
            manual_key_terms=row.get("key_terms"),
        )
        _RULES_CACHE[key] = {flag["label"] for flag in layer1.flags}
    return _RULES_CACHE[key]


def prepare(records: list, dataset: dict, label: str = "") -> list:
    """Join predictions to their text and collect both layers' issue sets.

    Only the issue sets are needed here - no fusion features - so this is a
    lighter version of evaluate_folds.prepare, plus the cache above.
    """
    prepared = []
    for index, record in enumerate(records, 1):
        row = dataset.get(record.get("id"))
        if row is None:
            continue
        prepared.append({
            "issues_true": set(record.get("issues_true") or []),
            "rules_issues": _rule_issues(row),
            "model_issues": {
                name for name, probability
                in zip(config.ISSUE_LABELS, record.get("issue_probs") or [])
                if probability >= ISSUE_THRESHOLD
            },
        })
        if label and index % 100 == 0:
            print(f"  {label}: {index}/{len(records)}", flush=True)
    return prepared


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return precision, recall, f1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions-dir", required=True)
    ap.add_argument("--data-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--out", default=None)
    ap.add_argument("--policy", default=config.ISSUE_POLICY)
    args = ap.parse_args()

    predictions_dir = Path(args.predictions_dir)
    dataset = index_dataset(Path(args.data_dir))
    if not dataset:
        print(f"no dataset rows under {args.data_dir}")
        return 1

    # Counted over the whole corpus, not the test folds, so "support" means
    # how much of this label the system was ever shown.
    corpus = collections.Counter()
    for row in dataset.values():
        for label in row.get("issues") or []:
            corpus[label] += 1

    counts = {label: {"tp": 0, "fp": 0, "fn": 0} for label in config.ISSUE_LABELS}
    test_support = collections.Counter()
    folds = 0

    for fold_dir in sorted(predictions_dir.glob("fold_*")):
        test_path = fold_dir / "test_predictions.jsonl"
        val_path = fold_dir / "val_predictions.jsonl"
        if not (test_path.exists() and val_path.exists()):
            continue
        folds += 1
        print(f"{fold_dir.name} ...", flush=True)
        train_rows = prepare(load_jsonl(val_path), dataset, f"{fold_dir.name} val")
        test_rows = prepare(load_jsonl(test_path), dataset, f"{fold_dir.name} test")
        precise = precise_rule_labels(train_rows, config.RULE_PRECISION_FLOOR)

        for row in test_rows:
            predicted = set(select_issue_labels(
                row["rules_issues"], row["model_issues"], args.policy, precise,
            ))
            truth = set(row["issues_true"])
            for label in config.ISSUE_LABELS:
                if label in truth:
                    test_support[label] += 1
                if label in predicted and label in truth:
                    counts[label]["tp"] += 1
                elif label in predicted:
                    counts[label]["fp"] += 1
                elif label in truth:
                    counts[label]["fn"] += 1

    if not folds:
        print(f"no fold_*/ prediction pairs under {predictions_dir}")
        return 1

    lines = [
        "# Per-label issue scores",
        "",
        f"Policy `{args.policy}`, pooled over {folds} folds. Support is the "
        "number of examples carrying the label: *corpus* over the whole "
        "dataset, *test* over the held-out rows these scores come from.",
        "",
        "| label | precision | recall | F1 | test support | corpus |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    rows_out = []
    for label in config.ISSUE_LABELS:
        c = counts[label]
        precision, recall, f1 = _f1(c["tp"], c["fp"], c["fn"])
        rows_out.append({
            "label": label, "precision": round(precision, 3),
            "recall": round(recall, 3), "f1": round(f1, 3),
            "test_support": test_support[label], "corpus_support": corpus[label],
        })
        lines.append(
            f"| `{label}` | {precision:.3f} | {recall:.3f} | {f1:.3f} | "
            f"{test_support[label]} | {corpus[label]} |"
        )

    total_tp = sum(c["tp"] for c in counts.values())
    total_fp = sum(c["fp"] for c in counts.values())
    total_fn = sum(c["fn"] for c in counts.values())
    _, _, micro = _f1(total_tp, total_fp, total_fn)
    lines += ["", f"Pooled micro-F1: **{micro:.3f}**", ""]

    text = "\n".join(lines)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        out.with_suffix(".json").write_text(
            json.dumps({"policy": args.policy, "folds": folds,
                        "micro_f1": round(micro, 4), "labels": rows_out},
                       indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {out} and {out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
