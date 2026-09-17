"""Layer 2 - a context-aware multi-task DistilBERT.

One encoder, two heads on the [CLS] vector: a 3-way verdict head trained with
cross-entropy, and a 10-label issue head trained with BCE-with-logits. Training
them together is deliberate - the issues are the evidence for the verdict, and
a shared encoder means the verdict head cannot drift away from them.

Input is a text pair:

    text_a = "SECTION 4.2 Online Application: <marked change>"
    text_b = <retrieved context from the same document>

with ``truncation="only_second"`` so the change itself is never cut. The
special tokens [DEL]/[INS]/[ROLE]/[STEP] are added to the tokenizer and the
embedding matrix is resized to match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer

from . import config

BASE_MODEL = "distilbert-base-uncased"


# -- input construction ----------------------------------------

def build_text_a(section_number: str, section_title: str, marked_change: str) -> str:
    """The half that must never be truncated."""
    label = " ".join(part for part in (section_number, section_title) if part).strip()
    return f"SECTION {label}: {marked_change}".strip()


def build_tokenizer(model_name: str = BASE_MODEL):
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.add_special_tokens({"additional_special_tokens": config.SPECIAL_TOKENS})
    return tokenizer


def encode_pair(tokenizer, text_a: str, text_b: str, max_length: int = None,
                padding="max_length", return_tensors="pt"):
    """Tokenize one example.

    ``only_second`` truncates the context, never the change. If text_a alone
    still overruns, a window is kept around the changed spans rather than the
    head of the string - the tail of a long procedure is where the edit usually
    is.
    """
    max_length = max_length or config.MAX_LENGTH
    ids = tokenizer(text_a, add_special_tokens=False)["input_ids"]
    # Two [SEP]s, one [CLS], and a little room for context.
    budget = max_length - 8
    if len(ids) > budget:
        text_a = _window_around_change(tokenizer, ids, budget)
    return tokenizer(
        text_a,
        text_b or "",
        truncation="only_second",
        max_length=max_length,
        padding=padding,
        return_tensors=return_tensors,
    )


def _window_around_change(tokenizer, ids: list, budget: int) -> str:
    """Keep the marked spans and as much surrounding wording as fits.

    Windowing is done on **token ids**, not words: the budget is a token count,
    and a 248-word window can easily be 400 tokens. Slicing by words left text_a
    over the limit, and ``only_second`` then had nothing left to truncate -
    the tokenizer raised "Sequence to truncate too short".
    """
    marker_ids = {
        tokenizer.convert_tokens_to_ids(token)
        for token in ("[DEL]", "[/DEL]", "[INS]", "[/INS]")
    }
    marks = [i for i, tid in enumerate(ids) if tid in marker_ids]
    if not marks:
        return tokenizer.decode(ids[:budget], skip_special_tokens=False)

    # Head and tail rather than one centred window. A long deletion puts the
    # midpoint inside the deleted span, so a centred window kept neither
    # marker and the model could not see what had changed. This keeps the
    # start of the change and the end of it, with a gap marked in between.
    lead = 16
    head_len = budget // 2
    tail_len = max(budget - head_len - 4, 1)

    head_start = max(0, marks[0] - lead)
    head = ids[head_start:head_start + head_len]

    tail_start = max(head_start + head_len, min(marks[-1] + lead, len(ids)) - tail_len)
    tail = ids[tail_start:tail_start + tail_len]

    decoded_head = tokenizer.decode(head, skip_special_tokens=False)
    if not tail:
        return decoded_head
    return decoded_head + " ... " + tokenizer.decode(tail, skip_special_tokens=False)


# -- model -----------------------------------------------------

@dataclass
class Layer2Output:
    verdict_logits: torch.Tensor
    issue_logits: torch.Tensor
    loss: torch.Tensor = None


class RevisionAssessmentModel(nn.Module):
    def __init__(
        self,
        model_name: str = BASE_MODEL,
        num_verdicts: int = None,
        num_issues: int = None,
        dropout: float = 0.1,
        issue_loss_weight: float = 1.0,
        vocab_size: int = None,
    ):
        super().__init__()
        self.num_verdicts = num_verdicts or len(config.VERDICTS)
        self.num_issues = num_issues or len(config.ISSUE_LABELS)
        self.issue_loss_weight = issue_loss_weight

        self.encoder = AutoModel.from_pretrained(model_name)
        if vocab_size is not None:
            self.encoder.resize_token_embeddings(vocab_size)

        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.verdict_head = nn.Linear(hidden, self.num_verdicts)
        self.issue_head = nn.Linear(hidden, self.num_issues)

        # Set from the training distribution by the training script.
        self.register_buffer("verdict_class_weights", torch.ones(self.num_verdicts))
        self.register_buffer("issue_pos_weights", torch.ones(self.num_issues))

    def forward(
        self,
        input_ids,
        attention_mask,
        verdict_labels=None,
        issue_labels=None,
        issues_labeled=None,
    ) -> Layer2Output:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls = self.dropout(hidden.last_hidden_state[:, 0])

        verdict_logits = self.verdict_head(cls)
        issue_logits = self.issue_head(cls)

        loss = None
        if verdict_labels is not None:
            loss = nn.functional.cross_entropy(
                verdict_logits, verdict_labels, weight=self.verdict_class_weights
            )
            if issue_labels is not None:
                per_label = nn.functional.binary_cross_entropy_with_logits(
                    issue_logits, issue_labels,
                    pos_weight=self.issue_pos_weights, reduction="none",
                )
                # Rows whose issues were never labelled (real admin-decided
                # revisions carry a verdict only) must not train the issue head.
                if issues_labeled is not None:
                    mask = issues_labeled.float().unsqueeze(1)
                    denom = mask.sum() * self.num_issues
                    issue_loss = (per_label * mask).sum() / denom.clamp(min=1.0)
                else:
                    issue_loss = per_label.mean()
                loss = loss + self.issue_loss_weight * issue_loss

        return Layer2Output(verdict_logits, issue_logits, loss)

    @torch.no_grad()
    def predict(self, input_ids, attention_mask) -> dict:
        self.eval()
        out = self.forward(input_ids=input_ids, attention_mask=attention_mask)
        return {
            "verdict_probs": torch.softmax(out.verdict_logits, dim=-1),
            "issue_probs": torch.sigmoid(out.issue_logits),
        }

    # -- persistence -------------------------------------------

    def save(self, out_dir, tokenizer=None, thresholds=None, extra=None) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.encoder.save_pretrained(out / "encoder")
        torch.save(
            {
                "verdict_head": self.verdict_head.state_dict(),
                "issue_head": self.issue_head.state_dict(),
                "verdict_class_weights": self.verdict_class_weights,
                "issue_pos_weights": self.issue_pos_weights,
            },
            out / "heads.pt",
        )
        if tokenizer is not None:
            tokenizer.save_pretrained(out / "tokenizer")

        label_config = {
            "pipeline_version": config.PIPELINE_VERSION,
            # Compared at load time so teammates who pull code changes but keep
            # old local weights are warned instead of silently mispredicting.
            "fingerprint": config.pipeline_fingerprint(),
            "verdicts": config.VERDICTS,
            "issues": config.ISSUE_LABELS,
            "special_tokens": config.SPECIAL_TOKENS,
            "max_length": config.MAX_LENGTH,
            "issue_loss_weight": self.issue_loss_weight,
        }
        if extra:
            label_config.update(extra)
        (out / "label_config.json").write_text(
            json.dumps(label_config, indent=2), encoding="utf-8"
        )
        if thresholds is not None:
            (out / "thresholds.json").write_text(
                json.dumps(thresholds, indent=2), encoding="utf-8"
            )

    @classmethod
    def load(cls, out_dir, device: str = "cpu"):
        """Returns (model, tokenizer, thresholds, warnings)."""
        out = Path(out_dir)
        warnings = []

        # Check the directory before handing a path to transformers. Given a
        # path that does not exist, from_pretrained assumes it is a Hub repo
        # id and fails complaining about the characters in it, which reads as
        # a bug in the name rather than "the weights are not here".
        required = ("encoder", "tokenizer", "heads.pt")
        if not out.is_dir():
            raise FileNotFoundError(
                f"weights not found at {out}. Layer 2 is not in git; see "
                f"PHASE5_TRAINING.md to train it, or restore the folder "
                f"from a backup."
            )
        missing = [name for name in required if not (out / name).exists()]
        if missing:
            raise FileNotFoundError(
                f"weights at {out} are incomplete - missing "
                f"{', '.join(missing)}. Re-unpack the model archive, or see "
                f"PHASE5_TRAINING.md."
            )

        label_config = {}
        cfg_path = out / "label_config.json"
        if cfg_path.exists():
            label_config = json.loads(cfg_path.read_text(encoding="utf-8"))
            if label_config.get("fingerprint") != config.pipeline_fingerprint():
                warnings.append(
                    "Models were trained with an older pipeline version - run "
                    "setup_models.py --force"
                )

        tokenizer = AutoTokenizer.from_pretrained(out / "tokenizer")
        model = cls(
            model_name=str(out / "encoder"),
            issue_loss_weight=label_config.get("issue_loss_weight", 1.0),
        )
        heads = torch.load(out / "heads.pt", map_location=device, weights_only=True)
        model.verdict_head.load_state_dict(heads["verdict_head"])
        model.issue_head.load_state_dict(heads["issue_head"])
        model.verdict_class_weights = heads["verdict_class_weights"].to(device)
        model.issue_pos_weights = heads["issue_pos_weights"].to(device)
        model.to(device)
        model.eval()

        thresholds = {}
        thr_path = out / "thresholds.json"
        if thr_path.exists():
            thresholds = json.loads(thr_path.read_text(encoding="utf-8"))

        return model, tokenizer, thresholds, warnings


# -- class weighting -------------------------------------------

def verdict_class_weights(verdict_ids: list, num_classes: int = None) -> torch.Tensor:
    """Inverse-frequency weights, normalised to mean 1."""
    num_classes = num_classes or len(config.VERDICTS)
    counts = torch.zeros(num_classes)
    for vid in verdict_ids:
        counts[vid] += 1
    counts = counts.clamp(min=1.0)
    weights = counts.sum() / (num_classes * counts)
    return weights / weights.mean()


def issue_pos_weights(issue_rows: list, num_labels: int = None,
                      cap: float = 20.0) -> torch.Tensor:
    """Per-label positive weights for BCE.

    Rare labels would otherwise be ignored entirely, but an uncapped ratio on a
    label with two positives produces a weight that destabilises training.
    """
    num_labels = num_labels or len(config.ISSUE_LABELS)
    positives = torch.zeros(num_labels)
    for row in issue_rows:
        positives += torch.tensor(row, dtype=torch.float)
    total = max(len(issue_rows), 1)
    negatives = (total - positives).clamp(min=1.0)
    return (negatives / positives.clamp(min=1.0)).clamp(max=cap)
