"""Per-fold fusion: train on a fold's val predictions, score on its test set.

Training fusion on every fold's validation predictions and reporting how well
it does is circular - the same predictions taught it. So for each fold k,
fusion is fitted on fold k's **val** predictions and scored on fold k's
**test** predictions, which that fold's Layer 2 model never trained on and
which fusion has never seen.

Three systems are scored side by side on the same test rows, because the
question is not "is fusion any good" but "does fusion beat what we already
had":

* **rules only** - Layer 1's verdict, no model.
* **model only** - Layer 2's argmax, no rules.
* **fusion**     - Layer 3 over both.

The fusion model the app ships is a different object: it is trained on *all*
folds' val predictions, by train_fusion.py. This script measures; that one
builds.

    py ml/revision_pipeline/scripts/evaluate_folds.py \\
        --predictions-dir /content/drive/MyDrive/DocuRoute/context_v2/folds \\
        --out-dir /content/drive/MyDrive/DocuRoute/context_v2/final
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                                # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402
from revision_pipeline.layer1_rules import run_layer1               # noqa: E402
from revision_pipeline.layer3_fusion import (                       # noqa: E402
    FusionModel, build_feature_vector, rules_only_verdict,
)

ISSUE_THRESHOLD = 0.5


# ---------------------------------------------------------------- metrics

def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    if true_positive == 0:
        return 0.0
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def verdict_scores(truth: list, predicted: list) -> dict:
    """Accuracy and macro-F1 over the three verdicts."""
    correct = sum(1 for t, p in zip(truth, predicted) if t == p)
    per_class = []
    for verdict in config.VERDICTS:
        tp = sum(1 for t, p in zip(truth, predicted) if t == verdict and p == verdict)
        fp = sum(1 for t, p in zip(truth, predicted) if t != verdict and p == verdict)
        fn = sum(1 for t, p in zip(truth, predicted) if t == verdict and p != verdict)
        per_class.append(_f1(tp, fp, fn))
    return {
        "verdict_accuracy": round(correct / len(truth), 4) if truth else 0.0,
        "verdict_macro_f1": round(sum(per_class) / len(per_class), 4),
    }


def issue_micro_f1(truth: list, predicted: list) -> float:
    """One F1 over every (example, label) decision."""
    tp = fp = fn = 0
    for true_set, predicted_set in zip(truth, predicted):
        tp += len(true_set & predicted_set)
        fp += len(predicted_set - true_set)
        fn += len(true_set - predicted_set)
    return round(_f1(tp, fp, fn), 4)


# ---------------------------------------------------------------- data

def index_dataset(data_dir: Path) -> dict:
    rows = {}
    for name in ("all.jsonl", "train.jsonl", "val.jsonl", "test.jsonl"):
        path = data_dir / name
        if path.exists():
            for row in load_jsonl(path):
                if row.get("id"):
                    rows[row["id"]] = row
    return rows


def prepare(records: list, dataset: dict) -> list:
    """Join predictions to their text and run Layer 1 once per example."""
    prepared = []
    for record in records:
        row = dataset.get(record.get("id"))
        if row is None:
            continue
        layer1 = run_layer1(
            row.get("old_text", ""), row.get("new_text", ""),
            revision_meta={"change_reason": row.get("change_reason") or "recorded"},
            manual_key_terms=row.get("key_terms"),
        )
        model_issues = {
            label for label, probability
            in zip(config.ISSUE_LABELS, record.get("issue_probs") or [])
            if probability >= ISSUE_THRESHOLD
        }
        rule_issues = {flag["label"] for flag in layer1.flags}
        prepared.append({
            "features": build_feature_vector(
                layer1.features, layer1.change_type,
                record.get("verdict_probs"), record.get("issue_probs"),
            ),
            "verdict_true": record["verdict_true"],
            "issues_true": set(record.get("issues_true") or []),
            "rules_verdict": rules_only_verdict(layer1),
            "rules_issues": rule_issues,
            "model_verdict": config.VERDICTS[
                max(range(len(config.VERDICTS)),
                    key=lambda i: (record.get("verdict_probs") or [0] * 3)[i])
            ],
            "model_issues": model_issues,
            # What the pipeline actually reports: the rules' findings plus
            # anything the model is confident about.
            "fusion_issues": rule_issues | model_issues,
        })
    return prepared


def score_fold(train_rows: list, test_rows: list, seed: int) -> dict:
    fusion = FusionModel.train(
        [r["features"] for r in train_rows],
        [r["verdict_true"] for r in train_rows],
        seed=seed,
    )
    # FusionModel exposes predict_proba for one row; the estimator underneath
    # takes the whole matrix at once, which matters over thousands of rows.
    fusion_verdicts = [
        str(v) for v in fusion.estimator.predict(
            [r["features"] for r in test_rows]
        )
    ]

    truth = [r["verdict_true"] for r in test_rows]
    issues_true = [r["issues_true"] for r in test_rows]
    result = {"kind": fusion.kind, "train_n": len(train_rows), "test_n": len(test_rows)}
    for name, verdicts, issues in (
        ("rules_only", [r["rules_verdict"] for r in test_rows],
         [r["rules_issues"] for r in test_rows]),
        ("model_only", [r["model_verdict"] for r in test_rows],
         [r["model_issues"] for r in test_rows]),
        ("fusion", fusion_verdicts, [r["fusion_issues"] for r in test_rows]),
    ):
        scores = verdict_scores(truth, verdicts)
        scores["issue_micro_f1"] = issue_micro_f1(issues_true, issues)
        result[name] = scores
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions-dir", required=True,
                    help="directory holding fold_0/ .. fold_n/")
    ap.add_argument("--data-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--seed", type=int, default=config.SEED)
    args = ap.parse_args()

    predictions_dir = Path(args.predictions_dir)
    fold_dirs = sorted(d for d in predictions_dir.glob("fold_*") if d.is_dir())
    if not fold_dirs:
        raise SystemExit(f"no fold_* directories under {predictions_dir}")

    dataset = index_dataset(Path(args.data_dir))
    if not dataset:
        raise SystemExit(f"no dataset rows under {args.data_dir}")

    per_fold = {}
    for fold_dir in fold_dirs:
        val_path = fold_dir / "val_predictions.jsonl"
        test_path = fold_dir / "test_predictions.jsonl"
        if not val_path.exists() or not test_path.exists():
            print(f"{fold_dir.name}: missing val or test predictions, skipped")
            continue
        train_rows = prepare(load_jsonl(val_path), dataset)
        test_rows = prepare(load_jsonl(test_path), dataset)
        if not train_rows or not test_rows:
            print(f"{fold_dir.name}: nothing joined to the dataset, skipped")
            continue
        per_fold[fold_dir.name] = score_fold(train_rows, test_rows, args.seed)
        print(f"{fold_dir.name}: trained on {len(train_rows)} val, "
              f"scored on {len(test_rows)} test")

    if not per_fold:
        raise SystemExit("no fold could be scored")

    systems = ("rules_only", "model_only", "fusion")
    measures = ("verdict_accuracy", "verdict_macro_f1", "issue_micro_f1")
    averaged = {
        system: {
            measure: round(statistics.fmean(
                fold[system][measure] for fold in per_fold.values()
            ), 4)
            for measure in measures
        }
        for system in systems
    }

    report = {
        "folds": per_fold,
        "averaged": averaged,
        "issue_threshold": ISSUE_THRESHOLD,
        "note": (
            "Fusion is fitted on each fold's val predictions and scored on that "
            "fold's test predictions, which neither it nor that fold's Layer 2 "
            "model has seen. The shipped fusion model is trained separately, on "
            "all folds' val predictions."
        ),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fold_evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    lines = ["# Per-fold evaluation", "",
             "Fusion trained on each fold's val predictions, scored on that",
             "fold's test predictions. The shipped fusion model is trained",
             "separately on all folds' val predictions.", "",
             "| fold | system | verdict acc | verdict macro-F1 | issue micro-F1 |",
             "|---|---|---:|---:|---:|"]
    for name, fold in per_fold.items():
        for system in systems:
            scores = fold[system]
            lines.append(
                f"| {name} | {system} | {scores['verdict_accuracy']:.3f} "
                f"| {scores['verdict_macro_f1']:.3f} "
                f"| {scores['issue_micro_f1']:.3f} |"
            )
    lines += ["", "## Averaged over folds", "",
              "| system | verdict acc | verdict macro-F1 | issue micro-F1 |",
              "|---|---:|---:|---:|"]
    for system in systems:
        scores = averaged[system]
        lines.append(
            f"| {system} | {scores['verdict_accuracy']:.3f} "
            f"| {scores['verdict_macro_f1']:.3f} "
            f"| {scores['issue_micro_f1']:.3f} |"
        )
    (out_dir / "fold_evaluation.md").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    print("\naveraged over folds:")
    for system in systems:
        scores = averaged[system]
        print(f"   {system:<12} acc {scores['verdict_accuracy']:.3f}  "
              f"macro-F1 {scores['verdict_macro_f1']:.3f}  "
              f"issue micro-F1 {scores['issue_micro_f1']:.3f}")
    print(f"\nwrote {out_dir / 'fold_evaluation.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
