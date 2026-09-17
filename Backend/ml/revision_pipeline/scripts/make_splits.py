"""Write the per-fold train/val/test splits the cross-validation reads.

``build_dataset.py`` assigns every *document* to a fold and writes one default
split. Cross-validation needs all five, and the Colab notebook expects them at
``ml/datasets/context_v2/fold_<k>/``. Without them the notebook falls back to
the default split and trains the same data five times, which looks like
cross-validation in the log and is not.

Splitting is by document throughout, so no document's wording appears on both
sides of a fold: for fold k the test set is the documents assigned to k, the
validation set is those assigned to k+1, and everything else trains.

    py ml/revision_pipeline/scripts/make_splits.py
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--folds", default="all",
                    help="'all', or a single fold number to write on its own")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    folds_path = data_dir / "folds.json"
    if not folds_path.exists():
        print(f"no {folds_path} - run build_dataset.py first")
        return 1

    assignment = json.loads(folds_path.read_text(encoding="utf-8"))
    by_document = assignment["by_document"]
    fold_count = assignment.get("folds", 5)
    rows = load_jsonl(data_dir / "all.jsonl")

    print(f"{len(rows)} examples, {len(by_document)} documents, {fold_count} folds\n")
    wanted = (range(fold_count) if args.folds == "all"
              else [int(args.folds)])
    for fold in wanted:
        validation_fold = (fold + 1) % fold_count
        parts = collections.defaultdict(list)
        for row in rows:
            document_fold = by_document.get(row["document_no"])
            if document_fold == fold:
                parts["test"].append(row)
            elif document_fold == validation_fold:
                parts["val"].append(row)
            else:
                parts["train"].append(row)

        out_dir = data_dir / f"fold_{fold}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("train", "val", "test"):
            with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
                for row in parts[name]:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        documents = {
            name: sorted({r["document_no"] for r in parts[name]})
            for name in ("train", "val", "test")
        }
        overlap = set(documents["train"]) & (set(documents["val"]) | set(documents["test"]))
        assert not overlap, f"fold {fold} leaks documents: {overlap}"
        print(f"fold {fold}: train {len(parts['train']):>5}  "
              f"val {len(parts['val']):>4}  test {len(parts['test']):>4}   "
              f"test documents: {', '.join(documents['test'])}")

    written = ", ".join(f"fold_{k}" for k in wanted)
    print(f"\nwritten under {data_dir}: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
