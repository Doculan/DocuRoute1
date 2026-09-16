import os
import re
from difflib import SequenceMatcher

import torch
from django.utils import text
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

from ml.active_issue_tags import ACTIVE_ISSUE_TAGS
from ml.explanation_templates import build_explanation
from ml.issue_guidance import ISSUE_GUIDANCE
from ml.verdict_mapping import get_issue_verdict, get_overall_verdict


BASE_DIR = os.path.dirname(__file__)

ASSESSMENT_MODEL_DIR = os.path.join(
    BASE_DIR,
    "saved_models",
    "distilbert_revision_assessment",
)

ISSUE_MODEL_DIR = os.path.join(
    BASE_DIR,
    "saved_models",
    "distilbert_revision_issues",
)

ASSESSMENT_TOKENIZER = None
ASSESSMENT_MODEL = None
ISSUE_TOKENIZER = None
ISSUE_MODEL = None

ASSESSMENT_HUMAN_REVIEW_THRESHOLD = 0.65


def build_model_input(change_type, original_text, revised_text):
    return (
        f"[CHANGE TYPE]\n{change_type}\n\n"
        f"[ORIGINAL TEXT]\n{original_text}\n\n"
        f"[REVISED TEXT]\n{revised_text}"
    )


def models_are_available():
    return (
        os.path.isdir(ASSESSMENT_MODEL_DIR)
        and os.path.isdir(ISSUE_MODEL_DIR)
    )


def load_models():
    global ASSESSMENT_TOKENIZER
    global ASSESSMENT_MODEL
    global ISSUE_TOKENIZER
    global ISSUE_MODEL

    if not models_are_available():
        raise FileNotFoundError(
            "DistilBERT model folders were not found. "
            "Train and save both models first."
        )

    if ASSESSMENT_MODEL is None:
        ASSESSMENT_TOKENIZER = AutoTokenizer.from_pretrained(
            ASSESSMENT_MODEL_DIR
        )
        ASSESSMENT_MODEL = (
            AutoModelForSequenceClassification.from_pretrained(
                ASSESSMENT_MODEL_DIR
            )
        )
        ASSESSMENT_MODEL.eval()

    if ISSUE_MODEL is None:
        ISSUE_TOKENIZER = AutoTokenizer.from_pretrained(
            ISSUE_MODEL_DIR
        )
        ISSUE_MODEL = AutoModelForSequenceClassification.from_pretrained(
            ISSUE_MODEL_DIR
        )
        ISSUE_MODEL.eval()


def predict_assessment(model_input):
    inputs = ASSESSMENT_TOKENIZER(
        model_input,
        return_tensors="pt",
        truncation=True,
        max_length=512,
        padding=True,
    )

    with torch.no_grad():
        logits = ASSESSMENT_MODEL(**inputs).logits[0]

    probabilities = torch.softmax(logits, dim=0)
    predicted_id = int(torch.argmax(probabilities).item())
    confidence = float(probabilities[predicted_id].item())

    model_label = ASSESSMENT_MODEL.config.id2label[predicted_id]

    if confidence < ASSESSMENT_HUMAN_REVIEW_THRESHOLD:
        assessment = "Needs Human Review"
    else:
        assessment = model_label

    return {
        "assessment": assessment,
        "model_label": model_label,
        "confidence": round(confidence * 100, 2),
    }


def predict_issue_tags(model_input):
    inputs = ISSUE_TOKENIZER(
        model_input,
        return_tensors="pt",
        truncation=True,
        max_length=512,
        padding=True,
    )

    with torch.no_grad():
        logits = ISSUE_MODEL(**inputs).logits[0]

    probabilities = torch.sigmoid(logits).tolist()
    predictions = []

    for tag_id, probability in enumerate(probabilities):
        tag = ISSUE_MODEL.config.id2label[tag_id]

        if tag not in ACTIVE_ISSUE_TAGS:
            continue

        threshold = ACTIVE_ISSUE_TAGS[tag]["threshold"]

        if probability >= threshold:
            predictions.append(
                {
                    "tag": tag,
                    "confidence": round(probability * 100, 2),
                }
            )

    return sorted(
        predictions,
        key=lambda item: item["confidence"],
        reverse=True,
    )


def build_verdict_results(issue_tags):
    findings = []

    for issue in issue_tags:
        tag = issue["tag"]
        guidance = ISSUE_GUIDANCE.get(tag)

        if guidance is None:
            findings.append(
                {
                    "tag": tag,
                    "title": tag.replace("_", " ").title(),
                    "confidence": issue["confidence"],
                    "verdict": get_issue_verdict(tag),
                    "identification": (
                        "A potential document issue was identified and "
                        "should be verified by an authorized reviewer."
                    ),
                    "action": (
                        "Review the affected document section and make "
                        "the required correction if applicable."
                    ),
                }
            )
            continue

        findings.append(
            {
                "tag": tag,
                "title": guidance["title"],
                "confidence": issue["confidence"],
                "verdict": get_issue_verdict(tag),
                "identification": guidance["identification"],
                "action": guidance["action"],
            }
        )

    overall_verdict = get_overall_verdict(
        [finding["tag"] for finding in findings]
    )

    return findings, overall_verdict


PLACEHOLDER_PATTERN = re.compile(
    r"\b(todo|tbd|for demo|demo only|lorem ipsum|placeholder|test)\b",
    re.IGNORECASE,
)


def get_added_text(original_text, revised_text):
    original_lines = {
        line.strip()
        for line in (original_text or "").splitlines()
        if line.strip()
    }

    added_lines = [
        line.strip()
        for line in (revised_text or "").splitlines()
        if line.strip() and line.strip() not in original_lines
    ]

    return "\n".join(added_lines)


def is_low_quality_added_text(value):
    clean = re.sub(
        r"^[\-\+\u2022\d.\s]+",
        "",
        value or "",
    ).strip()

    if not clean:
        return False, None

    if PLACEHOLDER_PATTERN.search(clean):
        return True, "placeholder or test wording"

    words = re.findall(r"[A-Za-z]+", clean)

    if len(words) == 1 and len(words[0]) >= 3:
        return True, "an unexplained single-word addition"

    if len(clean) <= 12 and not re.search(r"[.!?]$", clean):
        return True, "a short incomplete addition"

    return False, None


def requires_revision_for_content_removal(original_text, revised_text):
    original_lines = [
        line.strip()
        for line in (original_text or "").splitlines()
        if line.strip()
    ]

    revised_lines = [
        line.strip()
        for line in (revised_text or "").splitlines()
        if line.strip()
    ]

    if not original_lines:
        return False, None

    if not revised_lines:
        return (
            True,
            "The proposed revision removes all original content.",
        )

    def normalize_line(line):
        line = line.lower()
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = re.sub(r"[^a-z0-9\s]", " ", line)
        return re.sub(r"\s+", " ", line).strip()

    normalized_revised_lines = [
        normalize_line(line)
        for line in revised_lines
    ]

    removed_lines = []

    for original_line in original_lines:
        normalized_original = normalize_line(original_line)

        if not normalized_original:
            continue

        best_similarity = max(
            (
                SequenceMatcher(
                    None,
                    normalized_original,
                    normalized_revised_line,
                ).ratio()
                for normalized_revised_line in normalized_revised_lines
            ),
            default=0,
        )

        if best_similarity < 0.55:
            removed_lines.append(original_line)

    if not removed_lines:
        return False, None

    removal_ratio = len(removed_lines) / len(original_lines)

    critical_terms = (
        "shall",
        "must",
        "approval",
        "committee",
        "bids",
        "procurement",
        "regulations",
        "requirements",
        "compliance",
        "control",
        "procedure",
        "ched",
        "curriculum",
        "endorsement",
        "approves",
        "submits",
    )

    removed_critical_lines = [
        line
        for line in removed_lines
        if any(term in line.lower() for term in critical_terms)
    ]

    if removal_ratio >= 0.70:
        return (
            True,
            (
                f"The proposed revision removes or substantially changes "
                f"{len(removed_lines)} of {len(original_lines)} existing "
                "content lines."
            ),
        )

    if len(removed_critical_lines) >= 3 and removal_ratio >= 0.50:
        return (
            True,
            (
                "The proposed revision removes or substantially changes "
                "multiple critical policy or control requirements."
            ),
        )

    return False, None


def assess_revision(change_type, original_text, revised_text):
    load_models()

    model_input = build_model_input(
        change_type=change_type,
        original_text=original_text,
        revised_text=revised_text,
    )

    assessment_result = predict_assessment(model_input)

    print("\n=== AI ASSESSMENT DEBUG ===")
    print("change_type:", change_type)
    print("original_text:", repr(original_text))
    print("revised_text:", repr(revised_text))
    print("raw_model_assessment:", assessment_result["assessment"])

    removal_risk, removal_reason = (
        requires_revision_for_content_removal(
            original_text,
            revised_text,
        )
    )

    print("removal_risk:", removal_risk)
    print("removal_reason:", removal_reason)

    added_text = get_added_text(
        original_text,
        revised_text,
    )

    low_quality, low_quality_reason = (
        is_low_quality_added_text(added_text)
    )

    print("added_text:", repr(added_text))
    print("low_quality:", low_quality)
    print("low_quality_reason:", low_quality_reason)
    print("===========================\n")

    issue_tags = []

    if removal_risk:
        assessment_result["assessment"] = "Needs Revision"

        issue_tags.append(
            {
                "tag": "Major Content Removal",
                "confidence": 100.0,
            }
        )

        explanation = (
            "The proposed revision removes most of the original section "
            f"or established requirements. {removal_reason} "
            "The revision should be revised before approval."
        )

    elif low_quality:
        assessment_result["assessment"] = "Needs Human Review"

        issue_tags.append(
            {
                "tag": "Unclear Added Content",
                "confidence": 100.0,
            }
        )

        explanation = (
            "The proposed revision adds content that appears incomplete, "
            f"unexplained, or non-substantive ({low_quality_reason}). "
            "An authorized reviewer should confirm its meaning and "
            "relevance before approval."
        )

    else:
        issue_tags = predict_issue_tags(model_input)

        explanation = build_explanation(
            assessment_result["assessment"],
            issue_tags,
        )

    findings, overall_verdict = build_verdict_results(issue_tags)

    if overall_verdict == "Not ready for approval":
        assessment_result["assessment"] = "Needs Revision"

    elif overall_verdict == "Needs revision":
        assessment_result["assessment"] = "Needs Revision"

    elif overall_verdict == "Needs review":
        assessment_result["assessment"] = "Needs Human Review"

    return {
        **assessment_result,
        "overall_verdict": overall_verdict,
        "issue_tags": issue_tags,
        "findings": findings,
        "explanation": explanation,
        "disclaimer": (
            "AI-assisted preliminary feedback only. "
            "Final review and approval remain with authorized personnel."
        ),
    }