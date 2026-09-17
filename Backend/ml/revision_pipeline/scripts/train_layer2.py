"""Train Layer 2 - the context-aware multi-task DistilBERT.

Usage:
    py ml/revision_pipeline/scripts/train_layer2.py \
        --data-dir ml/datasets/context_v2 --out-dir ml/saved_models/context_v2

Everything is seeded with 42. CPU is the default; keep runs short with
--max-examples and --epochs.
"""

from __future__ import annotations

import argparse
import csv
import os
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config                     # noqa: E402
from revision_pipeline.data import (                     # noqa: E402
    RevisionDataset, issue_rows, load_jsonl, make_collate_fn, verdict_ids,
)
from revision_pipeline.layer2_model import (             # noqa: E402
    RevisionAssessmentModel, build_tokenizer,
    issue_pos_weights, verdict_class_weights,
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def peak_memory_mb() -> float:
    """Resident-set size in MB.

    This laptop has 8 GB with about 1 GB usually free, so a run that quietly
    swaps is the difference between slow and unusable. Reported rather than
    guessed at.
    """
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return 0.0


def configure_threads(threads: int = None) -> int:
    """torch defaults to physical cores; on this machine that is 6 of 8.

    Using all logical cores measured ~9% faster for this workload, so the
    default is every core unless told otherwise.
    """
    count = threads or os.cpu_count() or 1
    torch.set_num_threads(count)
    return count


def pick_device(requested: str) -> torch.device:
    if requested and requested != "auto":
        return torch.device(requested)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# -- evaluation ------------------------------------------------

@torch.no_grad()
def evaluate(model, loader, device) -> dict:
    model.eval()
    v_true, v_pred, i_true, i_prob = [], [], [], []

    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        out = model(input_ids=input_ids, attention_mask=attention_mask)

        v_pred.extend(out.verdict_logits.argmax(dim=-1).cpu().tolist())
        v_true.extend(batch["verdict_labels"].cpu().tolist())

        probs = torch.sigmoid(out.issue_logits).cpu().numpy()
        labelled = batch["issues_labeled"].cpu().numpy()
        for row_probs, row_true, is_labelled in zip(
            probs, batch["issue_labels"].cpu().numpy(), labelled
        ):
            if is_labelled:
                i_prob.append(row_probs)
                i_true.append(row_true)

    metrics = {
        "verdict_macro_f1": f1_score(v_true, v_pred, average="macro", zero_division=0),
        "verdict_accuracy": float(np.mean(np.array(v_true) == np.array(v_pred))),
    }
    if i_true:
        i_true_arr = np.array(i_true)
        i_pred_arr = (np.array(i_prob) >= 0.5).astype(int)
        metrics["issues_micro_f1"] = f1_score(
            i_true_arr, i_pred_arr, average="micro", zero_division=0
        )
    else:
        metrics["issues_micro_f1"] = 0.0

    metrics["_issue_true"] = i_true
    metrics["_issue_prob"] = i_prob
    return metrics


@torch.no_grad()
def dump_predictions(model, rows, loader, device, split: str, fold=None) -> list:
    """Per-example Layer 2 outputs, for the fusion model to train on.

    Fold models exist only to measure performance, so their weights are thrown
    away; these predictions are the part worth keeping. Fusion joins them back
    to the dataset rows by id and recomputes the Layer 1 features itself.
    """
    model.eval()
    records, index = [], 0
    for batch in loader:
        out = model(
            input_ids=batch["input_ids"].to(device),
            attention_mask=batch["attention_mask"].to(device),
        )
        verdict_probs = torch.softmax(out.verdict_logits, dim=-1).cpu().tolist()
        issue_probs = torch.sigmoid(out.issue_logits).cpu().tolist()
        for vp, ip in zip(verdict_probs, issue_probs):
            row = rows[index]
            index += 1
            records.append({
                "id": row.get("id"),
                "document_no": row.get("document_no"),
                "split": split,
                "fold": fold,
                "verdict_true": row["verdict"],
                "issues_true": row.get("issues") or [],
                "issues_labeled": bool(row.get("issues_labeled", True)),
                "generator": row.get("generator"),
                "verdict_probs": [round(x, 5) for x in vp],
                "issue_probs": [round(x, 5) for x in ip],
            })
    return records


def tune_thresholds(issue_true, issue_prob) -> dict:
    """Pick the per-label cut-off that maximises F1 on the validation set.

    A single 0.5 cut-off suits none of these labels: they have very different
    base rates, and the rare ones need a lower bar to be predicted at all.
    """
    if not issue_true:
        return {label: 0.5 for label in config.ISSUE_LABELS}

    true_arr = np.array(issue_true)
    prob_arr = np.array(issue_prob)
    thresholds = {}
    for idx, label in enumerate(config.ISSUE_LABELS):
        # With no positives in validation there is nothing to tune on: F1 is 0
        # at every cut-off, so the search would settle on whichever was tried
        # first and the label would then fire on everything. Keep the default.
        if true_arr[:, idx].sum() == 0:
            thresholds[label] = 0.5
            continue

        best_cut, best_f1 = 0.5, -1.0
        # Descending, and ties keep the higher cut: when several thresholds
        # score the same, the more conservative one is the safer default.
        for cut in np.arange(0.95, 0.04, -0.05):
            pred = (prob_arr[:, idx] >= cut).astype(int)
            score = f1_score(true_arr[:, idx], pred, zero_division=0)
            if score > best_f1:
                best_cut, best_f1 = float(cut), score
        thresholds[label] = round(best_cut, 2)
    return thresholds


def median_fold_thresholds(folds_dir) -> dict:
    """Median per-label threshold across the cross-validation folds.

    The final model trains on everything and keeps only an 8% slice for early
    stopping. That slice is far too small to tune a threshold for a rare label
    like contradicts_manual - a couple of examples either way would move the
    cut-off wildly. The folds each tuned on a proper validation split, so their
    median is the more honest estimate.
    """
    folds_dir = Path(folds_dir)
    collected = {label: [] for label in config.ISSUE_LABELS}
    found = 0

    for path in sorted(folds_dir.glob("fold_*/thresholds.json")) or             sorted(folds_dir.glob("*/thresholds.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found += 1
        for label, value in data.items():
            if label in collected:
                collected[label].append(float(value))

    if not found:
        return {}

    thresholds = {}
    for label, values in collected.items():
        thresholds[label] = round(float(np.median(values)), 2) if values else 0.5
    print(f"thresholds: median across {found} folds in {folds_dir}")
    return thresholds


# -- training --------------------------------------------------

def train(args) -> dict:
    set_seed(args.seed)
    threads = configure_threads(args.threads)
    device = pick_device(args.device)

    # 8 GB of RAM with ~1 GB free will not hold a batch of 16 at 384 tokens.
    # Effective batch stays the same via gradient accumulation.
    if args.batch_size is None:
        args.batch_size = 16 if device.type == "cuda" else 4
    effective_batch = args.batch_size * args.grad_accum

    data_dir = Path(args.data_dir)
    train_rows = load_jsonl(data_dir / "train.jsonl", args.max_examples)
    val_rows = load_jsonl(data_dir / "val.jsonl", args.max_examples)
    if not train_rows:
        raise SystemExit(f"no training rows found in {data_dir}")

    print(f"device={device}  threads={threads}  max_length={args.max_length}  "
          f"batch={args.batch_size}x{args.grad_accum}={effective_batch}  "
          f"train={len(train_rows)}  val={len(val_rows)}")

    tokenizer = build_tokenizer()
    model = RevisionAssessmentModel(
        issue_loss_weight=args.issue_loss_weight, vocab_size=len(tokenizer)
    )
    model.verdict_class_weights = verdict_class_weights(verdict_ids(train_rows)).to(device)
    model.issue_pos_weights = issue_pos_weights(issue_rows(train_rows)).to(device)
    model.to(device)

    collate = make_collate_fn(tokenizer)
    train_loader = DataLoader(
        RevisionDataset(train_rows, tokenizer, max_length=args.max_length),
        batch_size=args.batch_size, shuffle=True, collate_fn=collate,
    )
    val_loader = DataLoader(
        RevisionDataset(val_rows, tokenizer, max_length=args.max_length),
        batch_size=args.batch_size, collate_fn=collate,
    ) if val_rows else None

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "training_log.csv"
    log_rows = []

    # A 20-step timing run, so a slow CPU fold is visible before committing to
    # the whole thing rather than after.
    if args.estimate_first and len(train_loader) > 20:
        started = time.time()
        model.train()
        for step, batch in enumerate(train_loader):
            if step >= 20:
                break
            out = model(
                input_ids=batch["input_ids"].to(device),
                attention_mask=batch["attention_mask"].to(device),
                verdict_labels=batch["verdict_labels"].to(device),
                issue_labels=batch["issue_labels"].to(device),
                issues_labeled=batch["issues_labeled"].to(device),
            )
            out.loss.backward()
            optimizer.step()
            optimizer.zero_grad()
        per_step = (time.time() - started) / 20
        peak = peak_memory_mb()
        print(f"~{per_step:.2f}s/step ({per_step / args.batch_size * 1000:.0f} ms/example) "
              f"-> ~{per_step * len(train_loader) * args.epochs / 60:.1f} min for {args.epochs} epochs")
        print(f"   peak RSS {peak:.0f} MB")
        if device.type == "cpu" and peak > 3000:
            print("   WARNING: that is a large share of 8 GB - lower --batch-size "
                  "and raise --grad-accum if the machine starts swapping")
        set_seed(args.seed)

    best_score, best_epoch, patience_left = -1.0, -1, args.patience
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_started = time.time()
        total_loss = 0.0
        optimizer.zero_grad()
        for step, batch in enumerate(train_loader, 1):
            out = model(
                input_ids=batch["input_ids"].to(device),
                attention_mask=batch["attention_mask"].to(device),
                verdict_labels=batch["verdict_labels"].to(device),
                issue_labels=batch["issue_labels"].to(device),
                issues_labeled=batch["issues_labeled"].to(device),
            )
            total_loss += out.loss.detach().item()
            # Scaled so the accumulated gradient matches one large batch.
            (out.loss / args.grad_accum).backward()
            if step % args.grad_accum == 0 or step == len(train_loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()

        row = {
            "epoch": epoch,
            "train_loss": round(total_loss / max(len(train_loader), 1), 4),
            "seconds": round(time.time() - epoch_started, 1),
            "peak_rss_mb": round(peak_memory_mb()),
        }
        if val_loader:
            metrics = evaluate(model, val_loader, device)
            row.update({
                "val_verdict_macro_f1": round(metrics["verdict_macro_f1"], 4),
                "val_verdict_accuracy": round(metrics["verdict_accuracy"], 4),
                "val_issues_micro_f1": round(metrics["issues_micro_f1"], 4),
            })
            # Early stopping watches both heads: a model that nails the verdict
            # while predicting no issues is not the one we want.
            score = metrics["verdict_macro_f1"] + metrics["issues_micro_f1"]
            if score > best_score:
                best_score, best_epoch = score, epoch
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                patience_left = args.patience
            else:
                patience_left -= 1

        log_rows.append(row)
        print("  " + "  ".join(f"{k}={v}" for k, v in row.items()))

        if val_loader and patience_left <= 0:
            print(f"  early stop (best epoch {best_epoch})")
            break

    if best_state is not None:
        model.load_state_dict(best_state)
        model.to(device)

    thresholds = {label: 0.5 for label in config.ISSUE_LABELS}
    if args.thresholds_from:
        thresholds = median_fold_thresholds(args.thresholds_from) or thresholds
    elif val_loader:
        final = evaluate(model, val_loader, device)
        thresholds = tune_thresholds(final["_issue_true"], final["_issue_prob"])

    # Fold runs measure performance; only the final all-documents model is
    # kept. Skipping the encoder saves ~254 MB per fold.
    if args.save_weights:
        model.save(
            out_dir, tokenizer=tokenizer, thresholds=thresholds,
            extra={"best_epoch": best_epoch, "train_examples": len(train_rows),
                   "fold": args.fold},
        )
    else:
        (out_dir / "thresholds.json").write_text(
            json.dumps(thresholds, indent=2), encoding="utf-8"
        )
        print("weights not saved (--no-save-weights)")

    # Predictions for every split we have, so fusion and evaluation can run
    # later without the model - in Colab or locally.
    predictions = []
    if val_loader:
        predictions += dump_predictions(model, val_rows, val_loader, device, "val", args.fold)
    test_rows = load_jsonl(data_dir / "test.jsonl", args.max_examples)
    if test_rows:
        test_loader = DataLoader(
            RevisionDataset(test_rows, tokenizer, max_length=args.max_length),
            batch_size=args.batch_size, collate_fn=collate,
        )
        predictions += dump_predictions(model, test_rows, test_loader, device, "test", args.fold)

    if predictions:
        pred_path = out_dir / "predictions.jsonl"
        pred_path.write_text(
            "\n".join(json.dumps(r) for r in predictions), encoding="utf-8"
        )
        print(f"wrote {len(predictions)} predictions to {pred_path}")

    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps({
        "fold": args.fold,
        "best_epoch": best_epoch,
        "train_examples": len(train_rows),
        "val_examples": len(val_rows),
        "thresholds": thresholds,
        "epochs": log_rows,
        "pipeline_fingerprint": config.pipeline_fingerprint(),
    }, indent=2), encoding="utf-8")

    if log_rows:
        with log_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for r in log_rows for k in r}))
            writer.writeheader()
            writer.writerows(log_rows)

    print(f"saved to {out_dir}")
    return {"best_epoch": best_epoch, "thresholds": thresholds, "log": log_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--out-dir", default=str(config.MODEL_DIR))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch-size", type=int, default=None,
                    help="default 16 on CUDA, 4 on CPU")
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="accumulate this many batches before stepping")
    ap.add_argument("--save-weights", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="--no-save-weights for fold runs: predictions and "
                         "metrics are kept, the 254 MB encoder is not")
    ap.add_argument("--max-examples", type=int, default=None)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--patience", type=int, default=2)
    ap.add_argument("--threads", type=int, default=None,
                    help="CPU threads (default: every core)")
    ap.add_argument("--max-length", type=int, default=config.MAX_LENGTH,
                    help="token budget per example; the main speed lever on CPU")
    ap.add_argument("--issue-loss-weight", type=float, default=1.0)
    ap.add_argument("--fold", default=None, help="fold id, recorded in label_config")
    ap.add_argument("--thresholds-from", default=None, metavar="DIR",
                    help="take per-label thresholds as the median across the "
                         "fold results in DIR instead of tuning on validation; "
                         "used for the final model, whose held-out slice is too "
                         "small to tune rare labels on")
    ap.add_argument("--estimate-first", action="store_true",
                    help="time 20 steps and print an estimate before training")
    args = ap.parse_args()
    train(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
