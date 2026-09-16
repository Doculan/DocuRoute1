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
    RevisionDataset, issue_rows, load_jsonl, verdict_ids,
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


# -- training --------------------------------------------------

def train(args) -> dict:
    set_seed(args.seed)
    device = pick_device(args.device)

    data_dir = Path(args.data_dir)
    train_rows = load_jsonl(data_dir / "train.jsonl", args.max_examples)
    val_rows = load_jsonl(data_dir / "val.jsonl", args.max_examples)
    if not train_rows:
        raise SystemExit(f"no training rows found in {data_dir}")

    print(f"device={device}  train={len(train_rows)}  val={len(val_rows)}")

    tokenizer = build_tokenizer()
    model = RevisionAssessmentModel(
        issue_loss_weight=args.issue_loss_weight, vocab_size=len(tokenizer)
    )
    model.verdict_class_weights = verdict_class_weights(verdict_ids(train_rows)).to(device)
    model.issue_pos_weights = issue_pos_weights(issue_rows(train_rows)).to(device)
    model.to(device)

    train_loader = DataLoader(
        RevisionDataset(train_rows, tokenizer), batch_size=args.batch_size, shuffle=True
    )
    val_loader = DataLoader(
        RevisionDataset(val_rows, tokenizer), batch_size=args.batch_size
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
        print(f"~{per_step:.2f}s/step -> ~{per_step * len(train_loader) * args.epochs / 60:.1f} min "
              f"for {args.epochs} epochs")
        set_seed(args.seed)

    best_score, best_epoch, patience_left = -1.0, -1, args.patience
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_started = time.time()
        total_loss = 0.0
        for batch in train_loader:
            out = model(
                input_ids=batch["input_ids"].to(device),
                attention_mask=batch["attention_mask"].to(device),
                verdict_labels=batch["verdict_labels"].to(device),
                issue_labels=batch["issue_labels"].to(device),
                issues_labeled=batch["issues_labeled"].to(device),
            )
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            total_loss += out.loss.detach().item()

        row = {
            "epoch": epoch,
            "train_loss": round(total_loss / max(len(train_loader), 1), 4),
            "seconds": round(time.time() - epoch_started, 1),
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
    if val_loader:
        final = evaluate(model, val_loader, device)
        thresholds = tune_thresholds(final["_issue_true"], final["_issue_prob"])

    model.save(
        out_dir, tokenizer=tokenizer, thresholds=thresholds,
        extra={"best_epoch": best_epoch, "train_examples": len(train_rows),
               "fold": args.fold},
    )

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
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-examples", type=int, default=None)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--patience", type=int, default=2)
    ap.add_argument("--issue-loss-weight", type=float, default=1.0)
    ap.add_argument("--fold", default=None, help="fold id, recorded in label_config")
    ap.add_argument("--estimate-first", action="store_true",
                    help="time 20 steps and print an estimate before training")
    args = ap.parse_args()
    train(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
