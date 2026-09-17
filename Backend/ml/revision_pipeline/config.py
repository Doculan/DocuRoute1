"""Shared definitions for the revision assessment pipeline.

Everything that has to agree between training, inference and the dataset
builder lives here, so a change in one place cannot silently desync the rest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────

ML_DIR = Path(__file__).resolve().parent.parent          # Backend/ml
PIPELINE_DIR = ML_DIR / "revision_pipeline"
DATASET_DIR = ML_DIR / "datasets" / "context_v2"
MODEL_DIR = ML_DIR / "saved_models" / "context_v2"
RETRIEVAL_CACHE = MODEL_DIR / "retrieval"
REPORTS_DIR = ML_DIR / "reports"

GLOSSARY_PATH = PIPELINE_DIR / "glossary.txt"
GLOSSARY_DRAFT_PATH = PIPELINE_DIR / "glossary_draft.txt"
ENTITIES_PATH = PIPELINE_DIR / "entities.json"
ENTITIES_DRAFT_PATH = PIPELINE_DIR / "entities_draft.json"

SEED = 42

# ── Labels ────────────────────────────────────────────────────

VERDICTS = ["approve", "needs_revision", "reject"]
VERDICT_TO_ID = {v: i for i, v in enumerate(VERDICTS)}

# Fixed order. The multi-hot vectors in the dataset depend on it, so appending
# is safe but reordering invalidates every trained model.
ISSUE_LABELS = [
    "excessive_deletion",
    "key_term_deleted",
    "modal_weakened",
    "negation_changed",
    "numeric_changed",
    "responsibility_changed",
    "requirement_removed",
    "non_equivalent_term",
    "contradicts_manual",
    "out_of_scope_content",
]
ISSUE_TO_ID = {label: i for i, label in enumerate(ISSUE_LABELS)}

CHANGE_TYPES = [
    "cosmetic",
    "terminology_equivalent",
    "terminology_non_equivalent",
    "substantive",
]

# ── ISO clause mapping ────────────────────────────────────────
# Descriptions are our own words; the standard itself is copyrighted.
#
# Clause 7.5.2 (document identification and approval) is deliberately absent:
# document no., revision no. and effectivity date are entered manually and
# handled by the system's audit and document-control features, not by the
# model. See PROGRESS.md, decision 4.

ISO_CLAUSES = {
    "6.3": "Changes are planned, and a reason for the change is recorded.",
    "7.5.3": "Changes stay identifiable and controlled, and earlier versions are retained.",
    "5.3": "Roles, responsibilities and authorities remain assigned.",
}

ISSUE_CLAUSE = {
    "excessive_deletion": "7.5.3",
    "key_term_deleted": "7.5.3",
    "modal_weakened": "7.5.3",
    "negation_changed": "7.5.3",
    "numeric_changed": "7.5.3",
    "responsibility_changed": "5.3",
    "requirement_removed": "7.5.3",
    "non_equivalent_term": "7.5.3",
    "contradicts_manual": "7.5.3",
    "out_of_scope_content": "7.5.3",
}

# ── Severity ──────────────────────────────────────────────────

SEVERITY = {
    "requirement_removed": "high",
    "responsibility_changed": "high",
    "negation_changed": "high",
    "contradicts_manual": "high",
    "excessive_deletion": "high",
    "numeric_changed": "medium",
    "key_term_deleted": "medium",
    "non_equivalent_term": "medium",
    "out_of_scope_content": "medium",
    "modal_weakened": "medium",
}
SEVERITY_RANK = {"high": 2, "medium": 1, "low": 0}

# ── Layer 1 thresholds ────────────────────────────────────────

THRESHOLDS = {
    "excessive_deletion_line_ratio": 0.40,
    "excessive_deletion_word_ratio": 0.40,
    "cosmetic_typo_distance": 2,
    "min_unit_words": 15,
}

# ── Obligation modals ─────────────────────────────────────────
# Appendix A4: this corpus mixes shall/must/will/should for obligations.
# Weakening means moving to a permissive modal. "should -> shall" is a
# strengthening change, which is substantive but not an issue.

OBLIGATION_MODALS = [
    "shall", "must", "will", "should", "is required to", "are required to",
]
PERMISSIVE_MODALS = [
    "may", "can", "could", "might", "is encouraged to", "are encouraged to",
    "is optional", "are optional",
]

# ── How Layer 3 combines the two sources of issues ────────────
# The union was the first thing tried and the only thing tried. Measured on the
# five folds it cost 16 points of issue micro-F1 against the model alone
# (0.853 -> 0.695): every rule false positive is added to a set the model had
# right. ISSUE_POLICY names which rule is in force; evaluate_folds.py scores
# all of them on held-out fold predictions.
#
#   "model"          - what Layer 2 predicts, and nothing else
#   "union"          - every rule flag plus every model issue
#   "rules_precise"  - model issues, plus rule flags only for labels the rules
#                      get right often enough to be worth adding
#   "agree"          - only where both sides say the same thing
ISSUE_POLICY = "union"

# A rule label has to be at least this precise, measured on held-out
# predictions, before "rules_precise" will add it.
RULE_PRECISION_FLOOR = 0.90

# ── Sense reversals ───────────────────────────────────────────
# Pairs that reverse a requirement without using a negation word. Swapping one
# for the other flips what the manual asks for just as surely as inserting
# "not", and the count-of-negation-words test cannot see it.
SENSE_REVERSALS = [
    ("before", "after"),
    ("with", "without"),
    ("at least", "at most"),
    ("not later than", "not earlier than"),
    ("more than", "less than"),
    ("maximum", "minimum"),
    ("include", "exclude"),
    ("includes", "excludes"),
    ("including", "excluding"),
    ("required", "optional"),
    ("mandatory", "optional"),
    ("allowed", "prohibited"),
    ("permitted", "prohibited"),
    ("approved", "disapproved"),
    ("approves", "disapproves"),
    ("eligible", "ineligible"),
    ("qualified", "disqualified"),
    ("complete", "incomplete"),
    ("valid", "invalid"),
    ("accepted", "rejected"),
    ("grants", "denies"),
]

# Words that genuinely negate. The rule used to be a prefix regex -
# ``(un|non|dis|in)[a-z]{3,}`` - which counted "university", "information",
# "internal", "inspection" and "disbursement" as negations, so deleting any row
# containing one of them reported negation_changed.
NEGATED_FORMS = [
    "non-compliant", "non-compliance", "non-conforming", "non-conformity",
    "non-conformance", "unsatisfactory", "unapproved", "unauthorized",
    "unauthorised", "unsigned", "unqualified", "unavailable", "unsuccessful",
    "incomplete", "ineligible", "invalid", "inapplicable", "inaccurate",
    "disapproved", "disapproves", "disqualified", "dishonored", "disallowed",
]

# ── Tokenizer special tokens ──────────────────────────────────
# [DEL]/[INS] mark the change; [ROLE]/[STEP] keep a procedure table's role
# attached to its step once the table is linearised (Appendix A3).

SPECIAL_TOKENS = ["[DEL]", "[/DEL]", "[INS]", "[/INS]", "[ROLE]", "[STEP]"]

MAX_LENGTH = 512

# ── Feature order for Layer 3 ─────────────────────────────────
# The fusion model consumes a flat vector; this fixes its column order.

LAYER1_FEATURES = [
    "deleted_line_ratio",
    "deleted_word_ratio",
    "inserted_word_ratio",
    "net_deleted_word_ratio",
    "sentences_removed",
    "key_terms_deleted_count",
    "modal_weakened_count",
    "negation_changed",
    "numeric_changed_count",
    "role_terms_changed_count",
    "equivalent_swaps",
    "non_equivalent_swaps",
    "unknown_swaps",
    "cross_ref_conflict_count",
]

# ── Feature flags ─────────────────────────────────────────────

PIPELINE_SETTING_NAME = "REVISION_AI_PIPELINE"

PIPELINE_VERSION = "2.0.0"


def pipeline_fingerprint() -> str:
    """Hash of everything a trained model depends on.

    Saved into label_config.json at training time and compared at load time,
    so teammates who pull code changes but keep old local weights are warned
    instead of getting silently wrong predictions.
    """
    payload = json.dumps(
        {
            "version": PIPELINE_VERSION,
            "verdicts": VERDICTS,
            "issues": ISSUE_LABELS,
            "special_tokens": SPECIAL_TOKENS,
            "max_length": MAX_LENGTH,
            "features": LAYER1_FEATURES,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
