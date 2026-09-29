"""Three real edits every layer missed, kept as fixtures for the planned
advisory checks (LAYER4_INPUT_SPEC.md section 7).

The checks are planned, not built. So each planned advisory is a strict
xfail: it fails today, and the day a check reports it the xfail turns into
an error until its marker is removed. What must hold before and after is
that the checks add advisories only: the rule flags, which feed Layers 2
and 3 and the published figures, stay exactly as they are.
"""

import json
from pathlib import Path

import pytest

from revision_pipeline.layer1_rules import run_layer1

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "planned_advisories.json")
    .read_text(encoding="utf-8")
)
EDITS = FIXTURES["edits"]
REASON = {"change_reason": FIXTURES["change_reason"]}


def layer1(edit):
    return run_layer1(edit["old_text"], edit["new_text"], REASON)


@pytest.mark.parametrize("edit", EDITS, ids=[e["name"] for e in EDITS])
def test_the_rule_flags_are_what_they_were(edit):
    """None of the three raises a rule flag, today or once the advisory
    checks exist: an advisory never becomes a flag."""
    result = layer1(edit)
    assert result.flags == edit["layer1_today"]["flags"]
    assert result.change_type == edit["layer1_today"]["change_type"]


PLANNED = [(e, p) for e in EDITS for p in e["planned"]]


@pytest.mark.xfail(strict=True, reason="advisory checks planned, not built")
@pytest.mark.parametrize(
    "edit, planned", PLANNED,
    ids=[f"{e['name']}-{p['label']}" for e, p in PLANNED],
)
def test_the_planned_advisory_is_reported(edit, planned):
    found = [a for a in layer1(edit).advisories if a.get("label") == planned["label"]]
    assert found, f"no {planned['label']} advisory"
    evidence = json.dumps(found, ensure_ascii=False)
    for key in ("word", "kept", "item", "kind"):
        if key in planned:
            assert str(planned[key]) in evidence, (key, planned[key], evidence)
