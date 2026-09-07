from ml.active_issue_tags import ACTIVE_ISSUE_TAGS


ISSUE_MESSAGES = {
    "ambiguous_language": (
        "The revised wording may be unclear or too general. "
        "Use specific terms, conditions, or actions."
    ),
    "insufficient_detail": (
        "The revision may not contain enough operational detail "
        "to guide consistent implementation."
    ),
    "missing_responsibility": (
        "The revision may no longer identify the role, office, "
        "or person responsible for the action."
    ),
    "missing_approval_step": (
        "The revision may remove or omit a required review, "
        "authorization, or approval step."
    ),
    "missing_traceability": (
        "The revision may remove information needed to trace "
        "an action, decision, version, or process history."
    ),
    "missing_record_or_evidence": (
        "The revision may omit a required form, record, receipt, "
        "signature, report, or other supporting evidence."
    ),
    "unclear_scope": (
        "The revision may make the covered roles, activities, "
        "or boundaries of the section unclear."
    ),
    "illogical_sequence": (
        "The revised order of steps may be inconsistent with "
        "the required operational sequence."
    ),
    "possible_contradiction": (
        "The revised wording may conflict with an existing "
        "requirement or control in the original section."
    ),
}


def build_explanation(assessment, tag_predictions):
    if assessment == "Appropriate":
        return (
            "The proposed revision appears to preserve the section's "
            "main purpose, required controls, and logical flow. "
            "Authorized reviewer validation is still required."
        )

    if assessment == "Needs Human Review":
        return (
            "The system could not provide a sufficiently reliable "
            "preliminary assessment. Please request authorized "
            "reviewer evaluation."
        )

    active_tags = [
        item["tag"]
        for item in tag_predictions
        if item["tag"] in ACTIVE_ISSUE_TAGS
    ]

    messages = [
        ISSUE_MESSAGES[tag]
        for tag in active_tags
        if tag in ISSUE_MESSAGES
    ]

    if not messages:
        return (
            "The proposed revision may require clarification or "
            "additional reviewer evaluation before approval."
        )

    return " ".join(messages[:3])