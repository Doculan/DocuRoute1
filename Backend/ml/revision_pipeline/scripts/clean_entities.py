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
# Frequency, timing and status words. They appear as table column headers and
# got mined as roles, so a changed schedule was reported as a changed
# responsibility.
_NON_ENTITY_WORDS = {
    "daily", "weekly", "monthly", "quarterly", "annually", "yearly", "hourly",
    "semestral", "immediately", "timely", "ongoing", "as needed", "none",
    "yes", "no", "n/a", "na", "total", "subtotal", "approved", "pending",
}

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

_EXTRA_FORMS = [
    "Report of Cash Disbursements (RCDisb)",
]

_WS_RE = re.compile(r"\s+")

# ── Reviewed decisions ───────────────────────────────────────
# Encoded here rather than hand-edited into entities.json, so re-mining the
# corpus reproduces the same reviewed lists.

# Column headers and cell values the miner read as roles.
_NOT_ROLES = {
    "frequency", "position", "new", "placement", "recruitment", "regular",
    "selection", "rating", "date", "particulars", "remarks",
    # "Program Chair" and "Program Curriculum Committee" are split across
    # table columns in the source, leaving "Pro" and "Pro Com" behind.
    "pro", "pro com",
    # Appears once, as a schedule row label ("Submission of IPCR to HRMO
    # Faculty Personnel"), never as a party carrying a responsibility.
    "faculty personnel",
}

# Whole sentences and schedule labels mined as if they were roles.
_FRAGMENT_MARKERS = (
    "submission of", "submissionof", "calibration of", "monitoring of",
    "informs ", "signs the", "receives the",
)

# Acronyms that name a genuine body. They belong in offices, spelled out.
_ACRONYM_BODIES = {
    "ccc": "College Curriculum Committee (CCC)",
    "ucc": "University Curriculum Committee (UCC)",
    "pmt": "Performance Management Team (PMT)",
}

# Truncated or glued role names, completed from the source document.
_ROLE_REWRITES = {
    "bacmembers": "BAC Members",
    "bacmembers,twg": "BAC Members/TWG",
    "bac members,twg": "BAC Members/TWG",
    "bac members, twg, secretariat": "BAC Members/TWG/Secretariat",
    "bac members, secretariat, twg, end- user": "BAC Members/Secretariat/TWG/End-user",
    "osdstaff": "OSD Staff",
    "vice-president for administrationand":
        "Vice-President for Administration and Finance (VPAF)",
    "vice-president for administration and":
        "Vice-President for Administration and Finance (VPAF)",
    # The source truncates this mid-phrase; completed from the full form that
    # appears elsewhere in the same document.
    "vice-president for administration":
        "Vice-President for Administration and Finance (VPAF)",
    # Instances of one role, not separate roles.
    "student 1": "Student", "student 3": "Student", "student 9": "Student",
    "students": "Student",
}

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
# A leading article picked up with the phrase: "the Accounting Staff-4".
# Left in, the evidence reads "the accounting staff-4" and the same role
# matches twice.
_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
# A dangling conjunction left by a split: "Accounting Staff-1 or".
_DANGLING_RE = re.compile(r"\s+(?:or|and|to|of|the|by|for)$", re.IGNORECASE)


def _clean_phrase(value: str) -> str:
    """Collapse whitespace, drop trailing punctuation and extraction debris."""
    text = _WS_RE.sub(" ", (value or "").replace("\n", " ")).strip()
    text = re.sub(r"<!--.*?-->", "", text).strip()
    text = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text)          # leading numbering
    text = _HEADER_PREFIX_RE.sub("", text)
    text = _ARTICLE_RE.sub("", text)
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


_SHOUTED_PROSE = {
    "provided", "holder", "stall", "whereas", "witnesseth", "further",
    "however", "therefore", "hereby", "subject", "period", "parties",
}


def _is_noise(value: str, *, bare_ok: bool = False) -> bool:
    low = value.lower()
    if len(value) < 3:
        return True
    if low in _HEADINGS:
        return True
    if not bare_ok and low in _BARE_CATEGORIES:
        return True
    if low in _NON_ENTITY_WORDS:
        return True
    if re.fullmatch(r"[\d\W]+", value):                      # digits/punctuation only
        return True
    if value.isupper() and len(value) > 30:                  # a shouted heading
        return True
    # A single capitalised word from contract phrasing set in capitals, not the
    # name of anything: "PROVIDED, that ...", "the STALL HOLDER shall ...".
    if value.isupper() and low in _SHOUTED_PROSE:
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


def _apply_role_decisions(values: list):
    """Returns (roles, bodies_to_move_to_offices)."""
    kept, moved = [], []
    for value in values:
        low = value.lower().strip()
        if low in _NOT_ROLES:
            continue
        if low in _ACRONYM_BODIES:
            moved.append(_ACRONYM_BODIES[low])
            continue
        if any(low.startswith(marker) for marker in _FRAGMENT_MARKERS):
            continue
        kept.append(_ROLE_REWRITES.get(low, value))
    return kept, moved


def clean(draft: dict) -> dict:
    roles = [v for v in _dedupe(draft.get("roles", [])) if not _is_noise(v)]
    roles, promoted = _apply_role_decisions(roles)
    roles = _dedupe(roles)
    offices = [v for v in _dedupe(list(draft.get("offices", [])) + promoted)
               if not _is_noise(v)]
    # An acronym is meaningful even when short, so bare category filtering is
    # relaxed here - but headings and pure punctuation still go.
    systems = [
        v for v in _dedupe(list(draft.get("systems", [])) + _EXTRA_SYSTEMS)
        if not _is_noise(v, bare_ok=True)
    ]
    forms = [v for v in _dedupe(list(draft.get("forms", [])) + _EXTRA_FORMS)
             if not _is_noise(v)]

    # A body promoted to offices must not also sit in roles, and
    # "X Committee" and "X Committee (XC)" are one entry, not two.
    def base(name):
        return re.sub(r"\s*\([A-Z]{2,8}\)\s*$", "", name).strip().lower()

    office_bases = {base(o) for o in offices}
    offices = [
        o for o in offices
        if "(" in o or not any(base(other) == base(o) and "(" in other for other in offices)
    ]
    roles = [r for r in roles if base(r) not in office_bases]

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
