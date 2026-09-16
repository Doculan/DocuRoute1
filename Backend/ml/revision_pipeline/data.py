"""Loading the context_v2 dataset.

Rows are JSONL, one example per line, in the shape the dataset builder writes
(see REVISION_AI_OVERHAUL.md section 4e). The retrieved ``context`` is not
stored in the file - it is large and regenerable - so it is rebuilt here when a
section lookup is available, and left empty otherwise.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import torch
from torch.utils.data import Dataset

from . import config
from .diffing import marked_text
from .layer2_model import build_text_a, encode_pair


def _open(path: Path):
    """Transparently read .jsonl or .jsonl.gz."""
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def load_jsonl(path, max_examples: int = None) -> list:
    path = Path(path)
    if not path.exists() and Path(str(path) + ".gz").exists():
        path = Path(str(path) + ".gz")
    rows = []
    with _open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if max_examples and len(rows) >= max_examples:
                break
    return rows


def issues_to_multihot(issues) -> list:
    vec = [0.0] * len(config.ISSUE_LABELS)
    for label in issues or []:
        idx = config.ISSUE_TO_ID.get(label)
        if idx is not None:
            vec[idx] = 1.0
    return vec


def multihot_to_issues(vec, thresholds=None) -> list:
    out = []
    for idx, value in enumerate(vec):
        label = config.ISSUE_LABELS[idx]
        cut = (thresholds or {}).get(label, 0.5)
        if value >= cut:
            out.append(label)
    return out


class RevisionDataset(Dataset):
    """Tokenised examples ready for the Layer 2 model.

    ``context_lookup`` is an optional callable taking a row and returning the
    retrieved context string, so training can rebuild context without the
    dataset file carrying it.
    """

    def __init__(self, rows: list, tokenizer, context_lookup=None,
                 max_length: int = None):
        self.rows = rows
        self.tokenizer = tokenizer
        self.context_lookup = context_lookup
        self.max_length = max_length or config.MAX_LENGTH

    def __len__(self) -> int:
        return len(self.rows)

    def _context(self, row) -> str:
        if row.get("context"):
            return row["context"]
        if self.context_lookup:
            return self.context_lookup(row) or ""
        return ""

    def __getitem__(self, idx: int) -> dict:
        row = self.rows[idx]
        marked = row.get("marked") or marked_text(
            row.get("old_text", ""), row.get("new_text", "")
        )
        text_a = build_text_a(
            row.get("section_number", ""), row.get("section_title", ""), marked
        )
        # Unpadded: the collate function pads each batch to its own longest
        # sequence. Padding everything to max_length made every batch as slow
        # as the worst example in the dataset.
        enc = encode_pair(
            self.tokenizer, text_a, self._context(row), self.max_length,
            padding=False, return_tensors=None,
        )

        return {
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
            "verdict_labels": torch.tensor(
                config.VERDICT_TO_ID[row["verdict"]], dtype=torch.long
            ),
            "issue_labels": torch.tensor(
                issues_to_multihot(row.get("issues")), dtype=torch.float
            ),
            # Real admin-decided revisions carry a verdict but no issue labels;
            # those rows must not train the issue head.
            "issues_labeled": torch.tensor(
                bool(row.get("issues_labeled", True)), dtype=torch.bool
            ),
        }


def make_collate_fn(tokenizer):
    """Pad each batch to its own longest sequence, not to max_length."""

    def collate(batch: list) -> dict:
        encoded = tokenizer.pad(
            [{"input_ids": b["input_ids"], "attention_mask": b["attention_mask"]}
             for b in batch],
            padding=True,
            return_tensors="pt",
        )
        return {
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
            "verdict_labels": torch.stack([b["verdict_labels"] for b in batch]),
            "issue_labels": torch.stack([b["issue_labels"] for b in batch]),
            "issues_labeled": torch.stack([b["issues_labeled"] for b in batch]),
        }

    return collate


def token_lengths(rows: list, tokenizer, context_lookup=None,
                  max_length: int = None) -> list:
    """Untruncated token length of every example, for sizing max_length."""
    from .diffing import marked_text as _marked

    lengths = []
    for row in rows:
        marked = row.get("marked") or _marked(row.get("old_text", ""), row.get("new_text", ""))
        text_a = build_text_a(row.get("section_number", ""), row.get("section_title", ""), marked)
        context = row.get("context") or (context_lookup(row) if context_lookup else "") or ""
        lengths.append(len(tokenizer(text_a, context)["input_ids"]))
    return lengths


def verdict_ids(rows: list) -> list:
    return [config.VERDICT_TO_ID[r["verdict"]] for r in rows]


def issue_rows(rows: list) -> list:
    return [issues_to_multihot(r.get("issues")) for r in rows
            if r.get("issues_labeled", True)]


def describe(rows: list) -> dict:
    """Counts used for logging and the dataset card."""
    from collections import Counter

    verdicts = Counter(r["verdict"] for r in rows)
    generators = Counter(r.get("generator", "?") for r in rows)
    issues = Counter()
    for r in rows:
        for label in r.get("issues") or []:
            issues[label] += 1
    return {
        "examples": len(rows),
        "verdicts": dict(verdicts),
        "issues": dict(issues),
        "generators": dict(generators),
        "documents": len({r.get("document_no") or r.get("manual_id") for r in rows}),
    }
