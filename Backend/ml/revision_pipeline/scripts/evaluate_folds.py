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
    select_issue_labels,
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


# The ablation asks one question: how much of the verdict is decidable from
# the textual change itself? The clause 6.3 check answers a different one - it
# examines the submission's metadata, not the change - and in the live system
# it fires at the API before an assessment is ever requested, so a revision
# reaching Layer 2 has already passed it.
#
# Leaving it in measured the generators' placeholder reasons instead of the
# rules: 579 of the 2,762 rows carry filler like "Per instruction." that the
# tier-1 check rejects, and rows with no reason at all were handed the literal
# string "recorded", which it also rejects. Every one of those hard-failed, and
# rules_only_verdict returns reject on any hard fail, so a fifth of the corpus
# was scored as reject regardless of its content - dropping rules_only from
# 0.791 to 0.730 for reasons that have nothing to do with the rule layer.
#
# Substituted for every row, so all three systems in the ablation see the same
# thing. In practice only rules_only can notice: model_only reads Layer 2's
# probabilities, and fusion reads the feature vector, which carries no
# reason-derived column (config.LAYER1_FEATURES is entirely textual-diff
# quantities, and change_type is derived from the text and those features).
SCORING_CHANGE_REASON = "Reason recorded with the submission, checked at the API."


def prepare(records: list, dataset: dict) -> list:
    """Join predictions to their text and run Layer 1 once per example."""
    prepared = []
    for record in records:
        row = dataset.get(record.get("id"))
        if row is None:
            continue
        layer1 = run_layer1(
            row.get("old_text", ""), row.get("new_text", ""),
            revision_meta={"change_reason": SCORING_CHANGE_REASON},
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


ISSUE_POLICIES = ("model", "union", "rules_precise", "agree")


def precise_rule_labels(rows: list, floor: float) -> list:
    """Labels the rules get right often enough to be worth adding.

    Measured on the fold's *training* rows, never on the rows the policy is
    then scored on, so a label cannot earn its place on the test set.
    """
    hits = {}
    for row in rows:
        for label in row["rules_issues"]:
            correct, seen = hits.get(label, (0, 0))
            hits[label] = (correct + (label in row["issues_true"]), seen + 1)
    return sorted(
        label for label, (correct, seen) in hits.items()
        if seen >= 5 and correct / seen >= floor
    )


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
    precise = precise_rule_labels(train_rows, config.RULE_PRECISION_FLOOR)
    result = {
        "kind": fusion.kind, "train_n": len(train_rows), "test_n": len(test_rows),
        "precise_rule_labels": precise,
    }
    for name, verdicts, issues in (
        ("rules_only", [r["rules_verdict"] for r in test_rows],
         [r["rules_issues"] for r in test_rows]),
        ("model_only", [r["model_verdict"] for r in test_rows],
         [r["model_issues"] for r in test_rows]),
        ("fusion", fusion_verdicts,
         [select_issue_labels(r["rules_issues"], r["model_issues"],
                              config.ISSUE_POLICY, precise)
          for r in test_rows]),
    ):
        scores = verdict_scores(truth, verdicts)
        scores["issue_micro_f1"] = issue_micro_f1(issues_true, issues)
        result[name] = scores

    # The verdict is fusion's either way; only the issue set changes, so the
    # policies are compared on that alone.
    result["issue_policies"] = {}
    result["silenced_labels"] = {}
    present = {label for row in test_rows for label in row["issues_true"]}
    for policy in ISSUE_POLICIES:
        predicted = [
            select_issue_labels(r["rules_issues"], r["model_issues"], policy, precise)
            for r in test_rows
        ]
        result["issue_policies"][policy] = issue_micro_f1(issues_true, predicted)
        # A label that appears in the truth and is never once reported. Micro-F1
        # hides this: a policy can score well on the frequent labels while
        # never reporting a whole category. "agree" cannot report anything the
        # rules do not also raise, which is every contradicts_manual and
        # out_of_scope_content there is.
        reported = {label for labels in predicted for label in labels}
        result["silenced_labels"][policy] = sorted(present - reported)
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

    policy_means = {
        policy: round(statistics.fmean(
            fold["issue_policies"][policy] for fold in per_fold.values()
        ), 4)
        for policy in ISSUE_POLICIES
    }
    silenced = {
        policy: sorted({
            label for fold in per_fold.values()
            for label in fold["silenced_labels"][policy]
        })
        for policy in ISSUE_POLICIES
    }
    # A policy that never reports a label is not a candidate, whatever its
    # average. Choosing on micro-F1 alone picked "agree", which scores 0.000 on
    # contradicts_manual and out_of_scope_content - the two the rules are blind
    # to, and the reason there is a model at all.
    usable = [p for p in ISSUE_POLICIES if not silenced[p]]
    best_policy = max(usable or list(ISSUE_POLICIES), key=policy_means.get)

    report = {
        "folds": per_fold,
        "averaged": averaged,
        "issue_policies": policy_means,
        "silenced_labels": silenced,
        "best_issue_policy": best_policy,
        "best_chosen_among": usable,
        "configured_issue_policy": config.ISSUE_POLICY,
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

    lines += ["", "## How Layer 3 should combine the two issue sets", "",
              "The verdict is fusion's under every one of these; only the issue",
              "set changes. Scored per fold, then averaged.", "",
              "| policy | issue micro-F1 | labels it never reports |",
              "|---|---:|---|"]
    for policy in ISSUE_POLICIES:
        mark = "  **<- chosen**" if policy == best_policy else ""
        never = ", ".join(silenced[policy]) or "-"
        lines.append(
            f"| {policy} | {policy_means[policy]:.3f}{mark} | {never} |"
        )
    lines += ["", "A policy that never reports a label is not a candidate, "
                  "whatever its average.", ""]
    lines += ["", f"Configured: `{config.ISSUE_POLICY}`. "
                  f"Best measured: `{best_policy}`.",
              "", "Labels the rules were precise enough to add, per fold:"]
    for name, fold in per_fold.items():
        labels = ", ".join(fold["precise_rule_labels"]) or "none"
        lines.append(f"- {name}: {labels}")
    (out_dir / "fold_evaluation.md").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    print("\naveraged over folds:")
    for system in systems:
        scores = averaged[system]
        print(f"   {system:<12} acc {scores['verdict_accuracy']:.3f}  "
              f"macro-F1 {scores['verdict_macro_f1']:.3f}  "
              f"issue micro-F1 {scores['issue_micro_f1']:.3f}")
    print("\nissue policies (verdict is fusion's under each):")
    for policy in ISSUE_POLICIES:
        mark = "   <-- chosen" if policy == best_policy else ""
        never = silenced[policy]
        note = f"   never reports: {', '.join(never)}" if never else ""
        print(f"   {policy:<14} issue micro-F1 "
              f"{policy_means[policy]:.3f}{mark}{note}")
    if best_policy != config.ISSUE_POLICY:
        print(f"\nconfig.ISSUE_POLICY is '{config.ISSUE_POLICY}'; "
              f"'{best_policy}' scores better here.")

    print(f"\nwrote {out_dir / 'fold_evaluation.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
