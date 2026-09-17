"""Train the Layer 3 fusion model from saved fold predictions.

Fusion learns when to believe the rules and when to believe the model, so it
must see Layer 2 behaving as it does on **unseen** text. It is therefore
trained on the **validation** predictions only - never the training split,
where Layer 2 has effectively memorised the answer and fusion would simply
learn "Layer 2 is always right".

Because it reads the saved prediction files rather than a model, this runs in
Colab or on a laptop, with no weights present.

Usage:
    py ml/revision_pipeline/scripts/train_fusion.py \
        --predictions-dir ml/saved_models/context_v2 \
        --data-dir ml/datasets/context_v2 \
        --out-dir ml/saved_models/context_v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                          # noqa: E402
from revision_pipeline.data import load_jsonl                 # noqa: E402
from revision_pipeline.layer1_rules import run_layer1         # noqa: E402
from revision_pipeline.layer3_fusion import (                 # noqa: E402
    FusionModel, build_feature_vector,
)


def find_prediction_files(root: Path) -> list:
    """Every prediction file under root, fold subdirectories included.

    Fold runs write val_predictions.jsonl and test_predictions.jsonl; the
    combined predictions.jsonl is still read so an older run is not orphaned.
    """
    patterns = ("predictions.jsonl", "val_predictions.jsonl",
                "test_predictions.jsonl")
    found = []
    for pattern in patterns:
        found += list(root.glob(pattern))
        found += sorted(root.glob(f"*/{pattern}"))
    return found


def load_predictions(root: Path, split: str = "val") -> list:
    rows = []
    for path in find_prediction_files(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if split and record.get("split") != split:
                continue
            rows.append(record)
    return rows


def index_dataset(data_dir: Path) -> dict:
    """Dataset rows by id, so a prediction can be joined back to its text."""
    rows = {}
    for name in ("all.jsonl", "train.jsonl", "val.jsonl", "test.jsonl"):
        path = data_dir / name
        if not path.exists():
            continue
        for row in load_jsonl(path):
            if row.get("id"):
                rows[row["id"]] = row
    return rows


def build_training_matrix(predictions: list, dataset: dict):
    """Rule features recomputed from the text, plus Layer 2's probabilities."""
    X, y, skipped = [], [], 0

    for record in predictions:
        row = dataset.get(record.get("id"))
        if row is None:
            skipped += 1
            continue

        layer1 = run_layer1(
            row.get("old_text", ""),
            row.get("new_text", ""),
            revision_meta={"change_reason": row.get("change_reason") or "recorded"},
            manual_key_terms=row.get("key_terms"),
            related_sections=row.get("related_sections") or [],
        )
        X.append(build_feature_vector(
            layer1.features, layer1.change_type,
            record.get("verdict_probs"), record.get("issue_probs"),
        ))
        y.append(record["verdict_true"])

    return X, y, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions-dir", default=str(config.MODEL_DIR))
    ap.add_argument("--data-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--out-dir", default=str(config.MODEL_DIR))
    ap.add_argument("--split", default="val",
                    help="which predictions to train on; val by design")
    ap.add_argument("--seed", type=int, default=config.SEED)
    args = ap.parse_args()

    predictions_dir = Path(args.predictions_dir)
    predictions = load_predictions(predictions_dir, args.split)
    if not predictions:
        raise SystemExit(
            f"no '{args.split}' predictions under {predictions_dir} - "
            "run train_layer2.py first"
        )

    dataset = index_dataset(Path(args.data_dir))
    if not dataset:
        raise SystemExit(f"no dataset rows found in {args.data_dir}")

    X, y, skipped = build_training_matrix(predictions, dataset)
    if not X:
        raise SystemExit("no predictions could be joined to dataset rows by id")

    from collections import Counter

    print(f"predictions: {len(predictions)} ({args.split})  usable: {len(X)}"
          + (f"  skipped (no matching row): {skipped}" if skipped else ""))
    print("verdict distribution:", dict(Counter(y)))

    model = FusionModel.train(X, y, seed=args.seed)
    print(f"selected: {model.kind}  scores: {model.selection_scores}")

    out_dir = Path(args.out_dir)
    model.save(out_dir)
    print(f"saved fusion model to {out_dir / 'fusion.pkl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
