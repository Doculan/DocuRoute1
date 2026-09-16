"""Mine roles, offices, systems and forms from the master copies.

Appendix A5: changes to these entities are meaning changes, so Layer 1 needs
to know what they are. Writes entities_draft.json for a human to review; the
accepted result is saved as entities.json.

Usage:  py ml/revision_pipeline/scripts/build_entities_draft.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from revision_pipeline import config                       # noqa: E402
from revision_pipeline.scripts._corpus import load_documents  # noqa: E402

# A table row in either stored format: the new Markdown form
# "| Accounting Staff-4 | 2. | Checks the ledger |" or the legacy flattened
# form "Accounting Staff-4 | 2. | Checks the ledger". Most documents are still
# legacy, so requiring the leading pipe found almost no roles.
_ROW_RE = re.compile(r"^\|?(?P<cells>[^|].*?)\|?\s*$")
_SEP_RE = re.compile(r"^\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$")

# "Office of Student Affairs", "Accounting Office", "Cash Management Office"
_OFFICE_RE = re.compile(
    r"\b((?:[A-Z][\w-]+\s+){0,4}(?:Office|Unit|Department|Committee|Board|Council))\b"
)
# Acronym defined in parentheses: "Student Information and Accounting System (SIAS)"
_ACRONYM_RE = re.compile(r"\b([A-Z][A-Za-z&/ -]{4,60}?)\s*\(([A-Z]{2,8})\)")
# Bare acronyms already in use
_BARE_ACRONYM_RE = re.compile(r"\b([A-Z]{2,8})\b")
# Roles carrying a numeric suffix: "Accounting Staff-4"
_SUFFIX_ROLE_RE = re.compile(r"\b([A-Z][\w]*(?:\s+[A-Z][\w]*){0,3}-\d+)\b")

_STOP_ACRONYMS = {
    "AND", "THE", "FOR", "NOT", "ALL", "ANY", "PDF", "DOC", "NO", "OR",
    "POLICY", "SCOPE", "FORMS", "ROLE", "STEP", "DEL", "INS",
}


def _table_roles(content: str) -> list[str]:
    """First column of every table row - the role column in 4.x procedures."""
    roles, last = [], None
    for line in content.splitlines():
        line = line.strip()
        if "|" not in line or _SEP_RE.match(line):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        if not cells:
            continue
        role = cells[0]
        # A cell holding only a step number is not a role.
        if re.fullmatch(r"\d{1,3}[.)]?", role):
            role = ""
        # A5/A3: an empty role cell inherits the role above it.
        if not role and last:
            role = last
        if role and not role.lower().startswith("responsib"):
            roles.append(role)
            last = role
    return roles


def _forms(docs) -> list[str]:
    """Form names from a 'List of Forms' block.

    The extractor usually promotes each form to its own subsection ("5.1
    Certificate of Good Moral Character") and leaves the 5.0 block empty, so
    the names are in the subtitles. Both shapes are handled.
    """
    out = []
    for doc in docs:
        forms_tops = {
            re.match(r"^(\d+)", s["subtitle"]).group(1)
            for s in doc["sections"]
            if "list of forms" in s["subtitle"].lower()
            and re.match(r"^(\d+)", s["subtitle"])
        }
        for sec in doc["sections"]:
            m = re.match(r"^(\d+)\.(\d+)\s+(.+)$", sec["subtitle"].strip())
            if m and m.group(1) in forms_tops:
                out.append(m.group(3).strip(" .|"))
            if "list of forms" not in sec["subtitle"].lower():
                continue
            for line in sec["content"].splitlines():
                for part in re.split(r"\s*\d+\.\d+\.?\s+", " " + line.strip()):
                    part = re.sub(r"^\s*\d+(\.\d+)*\.?\s*", "", part).strip(" .|")
                    if 3 < len(part) < 90:
                        out.append(part)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(config.ENTITIES_DRAFT_PATH))
    # Bare acronyms are noisy; require a couple of occurrences before believing
    # one is a real system name.
    ap.add_argument("--min-count", type=int, default=1)
    ap.add_argument("--min-acronym-count", type=int, default=3)
    args = ap.parse_args()

    docs = load_documents()
    roles, offices, systems, forms = Counter(), Counter(), Counter(), Counter()

    for doc in docs:
        for sec in doc["sections"]:
            text = sec["content"]
            roles.update(_table_roles(text))
            roles.update(_SUFFIX_ROLE_RE.findall(text))
            offices.update(m.strip() for m in _OFFICE_RE.findall(text))
            for full, acro in _ACRONYM_RE.findall(text):
                if acro not in _STOP_ACRONYMS:
                    systems[f"{full.strip()} ({acro})"] += 1
            for acro in _BARE_ACRONYM_RE.findall(text):
                if acro not in _STOP_ACRONYMS and len(acro) >= 3:
                    systems[acro] += 1
    forms.update(_forms(docs))

    def keep(counter, min_count=None):
        floor = args.min_count if min_count is None else min_count
        return sorted(
            {k.strip(): v for k, v in counter.items() if k.strip() and v >= floor},
            key=lambda k: (-counter[k], k),
        )

    draft = {
        "_comment": (
            "Draft mined from the master copies. Review by hand, delete noise, "
            "then save as entities.json. Counts are occurrences in the corpus."
        ),
        "_documents_scanned": len(docs),
        "roles": keep(roles),
        "offices": keep(offices),
        "systems": keep(systems, args.min_acronym_count),
        "forms": keep(forms),
    }

    out = Path(args.out)
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")
    for k in ("roles", "offices", "systems", "forms"):
        print(f"  {k:<9} {len(draft[k]):>4}   e.g. {draft[k][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
