"""The revision assessment pipeline - Layers 1 to 4 behind one call.

``assess_revision(revision)`` takes a Django ``ManualRevision`` and returns one
result dict. ``assess_texts(...)`` does the same for bare strings, which is what
the evaluation scripts and the tests use.

Models are loaded once per process and cached. If Layer 2 has no weights - a
fresh clone, or a teammate who has not trained yet - the pipeline runs Layers
1, 3 and 4 in rules-only mode and marks ``trace.layer2 = "unavailable"``
instead of failing. The app is expected to work without a trained model; it
just says less.
"""

from __future__ import annotations

import threading

from . import config
from .diffing import marked_text
from .layer1_rules import run_layer1
from .layer3_fusion import FusionModel, run_layer3
from .layer4_explain import explain, not_assessed_message
from .retrieval import (
    Section, format_context, is_forms_section, related_texts, sections_for_manual,
)

_LOCK = threading.Lock()
_CACHE: dict = {}


# -- model loading ---------------------------------------------

def load_models(model_dir=None, device: str = "cpu") -> dict:
    """Load Layer 2 and the fusion model once, then reuse.

    Import of torch/transformers happens here rather than at module import, so
    a Django process that never assesses anything does not pay for it.
    """
    model_dir = str(model_dir or config.MODEL_DIR)
    key = (model_dir, device)

    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]

        bundle = {
            "layer2": None,
            "tokenizer": None,
            "thresholds": {},
            "fusion": None,
            "warnings": [],
        }
        try:
            from .layer2_model import RevisionAssessmentModel

            model, tokenizer, thresholds, warnings = RevisionAssessmentModel.load(
                model_dir, device=device
            )
            bundle.update(
                layer2=model, tokenizer=tokenizer,
                thresholds=thresholds, warnings=list(warnings),
            )
        except Exception as error:
            bundle["warnings"].append(f"Layer 2 unavailable: {error}")

        try:
            bundle["fusion"] = FusionModel.load(model_dir)
        except Exception as error:
            bundle["warnings"].append(f"fusion model unavailable: {error}")

        _CACHE[key] = bundle
        return bundle


def clear_model_cache() -> None:
    with _LOCK:
        _CACHE.clear()


# -- Layer 2 inference -----------------------------------------

def _run_layer2(bundle: dict, section_number: str, section_title: str,
                marked: str, context: str, device: str = "cpu") -> dict:
    model, tokenizer = bundle.get("layer2"), bundle.get("tokenizer")
    if model is None or tokenizer is None:
        return {}

    from .layer2_model import build_text_a, encode_pair

    text_a = build_text_a(section_number, section_title, marked)
    encoded = encode_pair(tokenizer, text_a, context)
    output = model.predict(
        encoded["input_ids"].to(device), encoded["attention_mask"].to(device)
    )
    return {
        "verdict_probs": [round(float(p), 5) for p in output["verdict_probs"][0]],
        "issue_probs": [round(float(p), 5) for p in output["issue_probs"][0]],
    }


# -- the pipeline ----------------------------------------------

def assess_texts(
    old_text: str,
    new_text: str,
    *,
    section_number: str = "",
    section_title: str = "",
    change_reason: str = "",
    related: list = None,
    context: str = "",
    manual_key_terms: list = None,
    revision_id=None,
    model_dir=None,
    device: str = "cpu",
) -> dict:
    """Assess a change given as plain text."""
    section_label = " ".join(p for p in (section_number, section_title) if p).strip()

    # Decision 9: a List of Forms section is a reference list, not a
    # requirement. It gets no verdict.
    if is_forms_section(section_label):
        return {
            "verdict": None,
            "assessed": False,
            "confidence": 0.0,
            "change_type": None,
            "hard_fails": [],
            "issues": [],
            "advisories": [],
            "explanation": not_assessed_message(section_label),
            "trace": {"skipped": "forms_section"},
        }

    bundle = load_models(model_dir, device)

    layer1 = run_layer1(
        old_text, new_text,
        revision_meta={"change_reason": change_reason,
                       "section_title": section_title},
        manual_key_terms=manual_key_terms,
        related_sections=related or [],
    )

    marked = layer1.marked or marked_text(old_text, new_text)
    layer2 = _run_layer2(
        bundle, section_number, section_title, marked, context, device
    )

    layer3 = run_layer3(
        layer1, layer2,
        fusion_model=bundle.get("fusion"),
        thresholds=bundle.get("thresholds"),
    )

    explanation = explain(
        layer3, layer1, section_label=section_label, revision_id=revision_id
    )

    trace = {
        "layer1": layer1.to_dict(),
        "layer2": layer2 or "unavailable",
        "layer3": {
            "probabilities": layer3.probabilities,
            "overrides": layer3.overrides,
            "confidence_source": layer3.confidence_source,
            "fusion_kind": getattr(bundle.get("fusion"), "kind", None),
        },
        "pipeline_version": config.PIPELINE_VERSION,
        "fingerprint": config.pipeline_fingerprint(),
    }
    if bundle.get("warnings"):
        trace["warnings"] = bundle["warnings"]

    return {
        "verdict": layer3.verdict,
        "assessed": True,
        "confidence": round(layer3.confidence, 4),
        "change_type": layer1.change_type,
        # A hard fail is the reason for the verdict when there is one, so it
        # belongs next to the verdict. It was only in trace.layer1, which meant
        # anything reading the result had to know where to dig for the one
        # thing it most needed.
        "hard_fails": [
            {
                "label": fail.get("reason"),
                "clause": fail.get("clause"),
                "evidence": fail.get("detail"),
            }
            for fail in layer1.hard_fails
        ],
        "issues": layer3.issues,
        "advisories": layer3.advisories,
        "explanation": explanation,
        "trace": trace,
    }


def assess_revision(revision, *, model_dir=None, device: str = "cpu") -> dict:
    """Assess a Django ``ManualRevision``.

    Pulls the proposed text out of whichever form the revision took - an edited
    string, an uploaded file, or a merge - and retrieves the context from the
    rest of the document.
    """
    section = revision.section
    manual = section.manual

    new_text = _proposed_text(revision)
    sections = sections_for_manual(manual)
    number, title = _split_label(section.subtitle or "")

    related = related_texts(
        manual.id, section.id, new_text or section.content, sections,
        k=3, section_subtitle=section.subtitle or "",
    )
    context = format_context(
        manual.title,
        [s for s in sections if s.content in related],
    )

    return assess_texts(
        section.content or "",
        new_text or "",
        section_number=number,
        section_title=title,
        change_reason=getattr(revision, "change_reason", "") or "",
        related=related,
        context=context,
        revision_id=revision.id,
        model_dir=model_dir,
        device=device,
    )


# -- helpers ---------------------------------------------------

def _proposed_text(revision) -> str:
    """The revision's new text, whichever way it was submitted."""
    if getattr(revision, "proposed_content", ""):
        return revision.proposed_content

    if getattr(revision, "merge_type", "") == "merge" and revision.merge_section_ids:
        from api.models import ManualSection

        merged = revision.section.content or ""
        sources = ManualSection.objects.filter(
            id__in=revision.merge_section_ids, manual=revision.section.manual
        )
        for source in sources:
            merged = f"{merged}\n\n{source.content}".strip()
        return merged

    if getattr(revision, "uploaded_file", None):
        from ml.ocr_engine import extract_text

        with revision.uploaded_file.open("rb") as handle:
            return extract_text(handle.read(), revision.uploaded_file.name)

    return ""


def _split_label(subtitle: str):
    """"4.2 Online Application" -> ("4.2", "Online Application")."""
    parts = (subtitle or "").strip().split(None, 1)
    if parts and parts[0].replace(".", "").isdigit():
        return parts[0], (parts[1] if len(parts) > 1 else "")
    return "", subtitle or ""
