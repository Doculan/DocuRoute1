"""What Layer 4 needs from the database, gathered from stored rows only.

* ``rotation_for``: the wording choices already made, so a new note rotates
  away from them - the other sections of the same proposal first, then the
  same user's last 20 notes - and the plans of the neighbouring changed
  sections, which the note avoids repeating.
* ``proposal_sections_for``: the other sections changed in the same version,
  so a section's note can say when another is being changed to match.
* ``compose_version_note``: the proposal-level note, composed once at
  submission from the stored section checks and frozen with the version.

Nothing here runs a check. Everything is read from stored snapshots.
"""

from __future__ import annotations

import logging

from .models import ManualSection, RevisionPreAssessment, SectionChange

logger = logging.getLogger(__name__)

VOICES = ("drafter", "reader")
USER_HISTORY = 20


def _changed(version):
    return [c for c in SectionChange.objects.filter(version=version)
            .select_related('section', 'assessment').order_by('section__order')
            if c.has_changed]


def rotation_for(user, version, section, content_hash: str = "") -> dict:
    """Per voice: {"history": [choice records, most relevant first],
    "adjacent_plans": [plan ids of the neighbouring changed sections]}.

    Earlier checks of exactly this content are left out, so re-checking
    unchanged text reproduces its note rather than rotating away from it.
    """
    changed = _changed(version)
    others = sorted(
        (c for c in changed if c.section_id != section.id and c.assessment_id
         and c.assessment.note_choices),
        key=lambda c: c.assessment.assessed_at, reverse=True,
    )
    seen = {c.assessment_id for c in others}
    mine = RevisionPreAssessment.objects.filter(submitted_by=user).exclude(note_choices={})
    if content_hash:
        mine = mine.exclude(content_hash=content_hash)
    recent = [a for a in mine.order_by('-assessed_at')[:USER_HISTORY + len(seen)]
              if a.id not in seen][:USER_HISTORY]

    order = [c.section_id for c in changed]
    neighbours = []
    if section.id in order:
        at = order.index(section.id)
        neighbours = [c for c in changed
                      if order.index(c.section_id) in (at - 1, at + 1)]
    out = {}
    for voice in VOICES:
        out[voice] = {
            "history": [c.assessment.note_choices.get(voice) for c in others
                        if c.assessment.note_choices.get(voice)]
                       + [a.note_choices.get(voice) for a in recent
                          if a.note_choices.get(voice)],
            "adjacent_plans": [
                c.assessment.note_choices[voice]["plan"] for c in neighbours
                if c.assessment_id and (c.assessment.note_choices or {}).get(voice, {}).get("plan")
            ],
        }
    return out


def proposal_sections_for(version, section) -> list:
    return [
        {"label": c.section.subtitle, "old_text": c.old_text, "new_text": c.new_text}
        for c in _changed(version) if c.section_id != section.id
    ]


def _section_record(change) -> dict:
    assessment = change.assessment
    choices = (assessment.note_choices or {}) if assessment else {}
    related = []
    if assessment and assessment.retrieved_section_ids:
        rows = ManualSection.objects.filter(id__in=assessment.retrieved_section_ids)
        related = [(s.subtitle or '', s.content or '') for s in rows]
    return {
        "label": change.section.subtitle,
        "old_text": change.old_text,
        "new_text": change.new_text,
        "tier": (choices.get("drafter") or choices.get("reader") or {}).get("tier"),
        "issues": list(assessment.issues or []) if assessment else [],
        "advisories": list(assessment.advisories or []) if assessment else [],
        "flags": list(((assessment.trace or {}).get("layer1") or {}).get("flags") or [])
        if assessment else [],
        "related": related,
    }


def compose_version_note(version) -> dict:
    """{"drafter": text, "reader": text, "choices": {voice: record}}, or {}
    if it cannot be written. A failure here never blocks a submission."""
    from ml.revision_pipeline.layer4_explain import REVIEWER, SUBMITTER, compose_proposal_note
    try:
        sections = [_section_record(c) for c in _changed(version)]
        if not sections:
            return {}
        earlier = [v.proposal_note.get("choices", {}) for v in
                   version.proposal.versions.filter(number__lt=version.number)
                   .order_by('-number') if v.proposal_note]
        note, choices = {}, {}
        for voice, audience in (("drafter", SUBMITTER), ("reader", REVIEWER)):
            text, chosen = compose_proposal_note(
                sections, audience=audience,
                history=[e.get(voice) for e in earlier if e.get(voice)],
                content_key=f"{version.proposal_id}:{version.number}",
            )
            note[voice], choices[voice] = text, chosen
        note["choices"] = choices
        return note
    except Exception:
        logger.exception("could not compose the proposal note for version %s", version.pk)
        return {}
