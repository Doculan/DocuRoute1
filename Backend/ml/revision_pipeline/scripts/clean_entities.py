"""Turn entities_draft.json into a reviewed entities.json.

The draft is mined by regex, so it carries three kinds of noise: section
headings that look like titles ("LIST OF FORMS"), bare category words that
match everything ("Office", "Committee"), and near-duplicates that differ only
by case, punctuation or a stray newline.

This pass removes those and folds in a small set of hand-added entries the
miner cannot find - systems named in running text rather than defined in
parentheses. The output is still meant to be read by a human before it is
trusted; it is just short enough now to actually read.

Usage:  py ml/revision_pipeline/scripts/clean_entities.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from revision_pipeline import config  # noqa: E402

# Section headings the miner picked up as entities.
_HEADINGS = {
    "list of forms", "objectives", "objective", "scope", "policies",
    "procedures", "procedure", "responsibility", "activity", "rating",
    "no.", "no", "date", "remarks", "particulars", "amount", "title",
}

# Bare category words. They match almost any sentence, so keeping them makes
# responsibility_changed fire on unrelated edits.
_BARE_CATEGORIES = {
    "office", "unit", "department", "committee", "board", "council",
    "staff", "student", "employee", "personnel", "faculty", "director",
    "head", "chair", "officer", "member", "user", "holder", "stall",
}

# Systems and registries named in running text rather than defined in
# parentheses, so the acronym miner never sees them. Appendix A5 names these.
_EXTRA_SYSTEMS = [
    "SIAS",
    "Student Information and Accounting System (SIAS)",
    "eNGAS",
    "Electronic New Government Accounting System (eNGAS)",
    "eBudget",
    "PhilGEPS",
]

_WS_RE = re.compile(r"\s+")

# A table's column header bleeding into the first cell of a row.
_HEADER_PREFIX_RE = re.compile(
    r"^(?:activity|responsibility|role|step|particulars|remarks)\s+", re.IGNORECASE
)
# Two entries merged into one by the section splitter:
# "Disbursement Voucher (DV) 5.4 Purchase Order (PO)".
_EMBEDDED_NUMBER_RE = re.compile(r"\s+\d+\.\d+\.?\s+")
# "Accounting Staff-4 8" / "Accounting Staff-4 4" - a step number that came
# along with the role cell.
_TRAILING_NUMBER_RE = re.compile(r"(-\d+)\s+\d+$")
# A dangling conjunction left by a split: "Accounting Staff-1 or".
_DANGLING_RE = re.compile(r"\s+(?:or|and|to|of|the|by|for)$", re.IGNORECASE)


def _clean_phrase(value: str) -> str:
    """Collapse whitespace, drop trailing punctuation and extraction debris."""
    text = _WS_RE.sub(" ", (value or "").replace("\n", " ")).strip()
    text = re.sub(r"<!--.*?-->", "", text).strip()
    text = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text)          # leading numbering
    text = _HEADER_PREFIX_RE.sub("", text)
    # Strip trailing punctuation before the regexes below, not after: a
    # trailing full stop in "Accounting Staff-4 4." stopped the step-number
    # pattern from anchoring.
    text = text.strip(" .,:;|-")
    text = _TRAILING_NUMBER_RE.sub(r"\1", text)
    # Normalise the spacing of suffixed roles: "Accounting Staff -3".
    text = re.sub(r"\s+-\s*(\d+)", r"-\1", text)
    text = _DANGLING_RE.sub("", text)
    return text.strip(" .,:;|-")


def _split_merged(values: list) -> list:
    """Break entries that carry a second item behind its own numbering."""
    out = []
    for value in values:
        parts = _EMBEDDED_NUMBER_RE.split(value or "")
        out.extend(p for p in parts if p and p.strip())
    return out


def _is_noise(value: str, *, bare_ok: bool = False) -> bool:
    low = value.lower()
    if len(value) < 3:
        return True
    if low in _HEADINGS:
        return True
    if not bare_ok and low in _BARE_CATEGORIES:
        return True
    if re.fullmatch(r"[\d\W]+", value):                      # digits/punctuation only
        return True
    if value.isupper() and len(value) > 30:                  # a shouted heading
        return True
    return False


def _dedupe(values: list) -> list:
    """Case-insensitive dedupe, keeping the best-cased spelling of each."""
    best: dict = {}
    for raw in _split_merged(values):
        cleaned = _clean_phrase(raw)
        if not cleaned:
            continue
        key = cleaned.lower()
        # Prefer the variant that is not all-caps and not all-lower.
        if key not in best or (best[key].isupper() and not cleaned.isupper()):
            best[key] = cleaned
    return sorted(best.values(), key=lambda s: (s.lower()))


def clean(draft: dict) -> dict:
    roles = [v for v in _dedupe(draft.get("roles", [])) if not _is_noise(v)]
    offices = [v for v in _dedupe(draft.get("offices", [])) if not _is_noise(v)]
    # An acronym is meaningful even when short, so bare category filtering is
    # relaxed here - but headings and pure punctuation still go.
    systems = [
        v for v in _dedupe(list(draft.get("systems", [])) + _EXTRA_SYSTEMS)
        if not _is_noise(v, bare_ok=True)
    ]
    forms = [v for v in _dedupe(draft.get("forms", [])) if not _is_noise(v)]

    return {
        "_comment": (
            "Reviewed entity lists used by Layer 1. Mined by "
            "build_entities_draft.py, cleaned by clean_entities.py, then read "
            "by a human. Edit this file directly; retrain after changing it."
        ),
        "_source_documents": draft.get("_documents_scanned"),
        "roles": roles,
        "offices": offices,
        "systems": systems,
        "forms": forms,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", default=str(config.ENTITIES_DRAFT_PATH))
    ap.add_argument("--out", default=str(config.ENTITIES_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    cleaned = clean(draft)

    print(f"{'list':<9} {'draft':>6} {'kept':>6}  removed")
    for key in ("roles", "offices", "systems", "forms"):
        before, after = len(draft.get(key, [])), len(cleaned[key])
        print(f"{key:<9} {before:>6} {after:>6}  {before - after:>7}")

    if args.dry_run:
        print("\n(dry run - nothing written)")
    else:
        Path(args.out).write_text(
            json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
