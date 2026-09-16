"""Shared helper: load master-copy section text out of the database.

Scripts run standalone (`py ml/revision_pipeline/scripts/x.py`), so Django has
to be configured before the ORM is importable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]      # Backend/


def setup_django() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django

    django.setup()


# COE is a byte-identical duplicate of HRM 4.02 (same PDF uploaded twice).
# Leaving it in leaks the same text across split groups. PROGRESS.md, decision 2.
EXCLUDED_DOCUMENTS = {"COE"}


def load_documents(include_excluded: bool = False) -> list[dict]:
    """Every master copy as {title, department, sections:[{...}]}."""
    setup_django()
    from api.models import Manual

    docs = []
    for manual in Manual.objects.all().order_by("title"):
        if not include_excluded and manual.title in EXCLUDED_DOCUMENTS:
            continue
        docs.append(
            {
                "manual_id": manual.id,
                "title": manual.title,
                "department": manual.department.name if manual.department else "",
                "sections": [
                    {
                        "section_id": s.id,
                        "subtitle": s.subtitle or "",
                        "content": s.content or "",
                        "tag": s.tag,
                        "order": s.order,
                    }
                    for s in manual.sections.all().order_by("order")
                ],
            }
        )
    return docs


def all_text(docs: list[dict]) -> list[str]:
    return [s["content"] for d in docs for s in d["sections"] if s["content"].strip()]
