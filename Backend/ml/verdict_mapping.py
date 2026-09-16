VERDICT_PRIORITY = {
    "No issue detected": 0,
    "Needs review": 1,
    "Needs revision": 2,
    "Not ready for approval": 3,
}

ISSUE_TO_VERDICT = {
    "ambiguous_language": "Needs review",
    "insufficient_detail": "Needs review",
    "missing_responsibility": "Needs revision",
    "missing_approval_step": "Not ready for approval",
    "missing_traceability": "Needs revision",
    "missing_record_or_evidence": "Needs revision",
    "irrelevant_content": "Needs revision",
    "unclear_scope": "Needs review",
    "poor_organization": "Needs revision",
    "illogical_sequence": "Needs revision",
    "possible_contradiction": "Needs review",
    "ocr_quality_issue": "Needs review",
    "Major Content Removal": "Needs revision",
    "Unclear Added Content": "Needs review",
}


def get_issue_verdict(issue_tag):
    return ISSUE_TO_VERDICT.get(issue_tag, "Needs review")


def get_overall_verdict(issue_tags):
    if not issue_tags:
        return "No issue detected"

    return max(
        (get_issue_verdict(tag) for tag in issue_tags),
        key=lambda verdict: VERDICT_PRIORITY[verdict],
    )