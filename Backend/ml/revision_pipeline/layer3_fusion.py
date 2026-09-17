"""Layer 3 - fusing the rule layer and the model into one verdict.

Layer 1 is precise but blind to meaning; Layer 2 reads meaning but cannot be
audited. This layer takes both - the rule features, the model's verdict
probabilities and its per-issue probabilities - and learns which to believe.

Two things are deliberately *not* learned:

* **Hard fails override everything.** A revision with no recorded reason is
  rejected whatever the model thinks, because the objection is procedural.
* **A high-severity issue both sources agree on** forces at least
  ``needs_revision``. If the rules and the model independently spot a removed
  requirement, that is not a case for a confident ``approve``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config


# -- feature assembly ------------------------------------------

def build_feature_vector(layer1_features: dict, change_type: str,
                         verdict_probs, issue_probs) -> list:
    """One flat row: rule features, then both of Layer 2's outputs.

    Column order is fixed by config so a model trained today can be read back
    tomorrow.
    """
    vec = [float(layer1_features.get(name, 0.0)) for name in config.LAYER1_FEATURES]
    vec += [1.0 if change_type == t else 0.0 for t in config.CHANGE_TYPES]
    vec += [float(p) for p in (verdict_probs or [0.0] * len(config.VERDICTS))]
    vec += [float(p) for p in (issue_probs or [0.0] * len(config.ISSUE_LABELS))]
    return vec


def feature_names() -> list:
    return (
        list(config.LAYER1_FEATURES)
        + [f"change_type={t}" for t in config.CHANGE_TYPES]
        + [f"layer2_verdict={v}" for v in config.VERDICTS]
        + [f"layer2_issue={i}" for i in config.ISSUE_LABELS]
    )


# -- issue merging ---------------------------------------------

def merge_issues(rule_flags: list, issue_probs, thresholds: dict = None) -> list:
    """Union of what the rules flagged and what the model predicted.

    ``source`` records which side raised each one, because "both agree" is a
    much stronger signal than either alone - and it is what the override below
    keys on.
    """
    thresholds = thresholds or {}
    by_label: dict = {}

    # Fields a flag may carry beyond the common ones. Layer 4 reads these:
    # dropping them made "unpaid was added" come out as "unpaid was changed",
    # and left every {ratio} template unusable.
    EXTRA_FIELDS = ("action", "ratio", "terms", "values", "roles", "swaps", "count",
                    "conflicts", "added", "removed", "direction", "from_text",
                    "to_text", "pairs")

    for flag in rule_flags or []:
        label = flag.get("label")
        if not label:
            continue
        merged = {
            "label": label,
            "source": "rule",
            # A rule fired on evidence it can point at, so it is certain about
            # what it saw - not about whether it matters.
            "confidence": 1.0,
            "severity": flag.get("severity") or config.SEVERITY.get(label, "low"),
            "clause": flag.get("clause") or config.ISSUE_CLAUSE.get(label, ""),
            "evidence": flag.get("evidence", ""),
        }
        merged.update({k: flag[k] for k in EXTRA_FIELDS if k in flag})
        by_label[label] = merged

    for idx, prob in enumerate(issue_probs or []):
        label = config.ISSUE_LABELS[idx]
        if float(prob) < thresholds.get(label, 0.5):
            continue
        if label in by_label:
            by_label[label]["source"] = "both"
            by_label[label]["confidence"] = max(
                by_label[label]["confidence"], float(prob)
            )
        else:
            by_label[label] = {
                "label": label,
                "source": "model",
                "confidence": round(float(prob), 4),
                "severity": config.SEVERITY.get(label, "low"),
                "clause": config.ISSUE_CLAUSE.get(label, ""),
                "evidence": "",
            }

    return sorted(
        by_label.values(),
        key=lambda i: (-config.SEVERITY_RANK.get(i["severity"], 0), -i["confidence"]),
    )


# -- the fusion model ------------------------------------------

@dataclass
class FusionResult:
    verdict: str
    confidence: float
    issues: list = field(default_factory=list)
    overrides: list = field(default_factory=list)
    probabilities: dict = field(default_factory=dict)
    # "fusion", "layer2" or "rules" - so the trace says where the number came
    # from rather than presenting a rule-derived figure as a model probability.
    confidence_source: str = "fusion"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 4),
            "issues": self.issues,
            "overrides": self.overrides,
            "probabilities": self.probabilities,
            "confidence_source": self.confidence_source,
        }


class FusionModel:
    """Logistic regression or gradient boosting over the combined features."""

    def __init__(self, estimator=None, kind: str = "logistic"):
        self.estimator = estimator
        self.kind = kind

    # -- training ---------------------------------------------

    @classmethod
    def train(cls, X, y, seed: int = None):
        """Fit both candidates and keep whichever validates better.

        Which one won is recorded, because "we tried two and took the better"
        is only meaningful if the reader can see which it was.
        """
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import f1_score
        from sklearn.model_selection import cross_val_predict

        seed = config.SEED if seed is None else seed
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)

        candidates = {
            "logistic": LogisticRegression(
                max_iter=2000, class_weight="balanced", random_state=seed
            ),
            "boosting": HistGradientBoostingClassifier(random_state=seed),
        }

        # Enough of every class to cross-validate? With a tiny or degenerate
        # label set, fall back to plain fitting rather than crashing.
        counts = {label: int((y == label).sum()) for label in set(y.tolist())}
        folds = min(3, min(counts.values())) if counts else 0

        scores = {}
        for name, estimator in candidates.items():
            if folds >= 2:
                predicted = cross_val_predict(estimator, X, y, cv=folds)
                scores[name] = f1_score(y, predicted, average="macro", zero_division=0)
            else:
                scores[name] = 0.0

        best = max(scores, key=scores.get) if scores else "logistic"
        estimator = candidates[best]
        estimator.fit(X, y)
        model = cls(estimator=estimator, kind=best)
        model.selection_scores = {k: round(float(v), 4) for k, v in scores.items()}
        return model

    # -- prediction -------------------------------------------

    def predict_proba(self, vector) -> dict:
        row = np.asarray(vector, dtype=float).reshape(1, -1)
        probs = self.estimator.predict_proba(row)[0]
        return {
            str(label): float(prob)
            for label, prob in zip(self.estimator.classes_, probs)
        }

    # -- persistence ------------------------------------------

    def save(self, out_dir) -> None:
        import joblib

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.estimator, out / "fusion.pkl")
        (out / "fusion_config.json").write_text(
            json.dumps(
                {
                    "kind": self.kind,
                    "selection_scores": getattr(self, "selection_scores", {}),
                    "feature_names": feature_names(),
                    "pipeline_fingerprint": config.pipeline_fingerprint(),
                    "coefficients": self.coefficients(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, out_dir):
        import joblib

        out = Path(out_dir)
        path = out / "fusion.pkl"
        if not path.exists():
            return None
        cfg = {}
        cfg_path = out / "fusion_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cls(estimator=joblib.load(path), kind=cfg.get("kind", "logistic"))

    def coefficients(self) -> dict:
        """What drove the verdict, exposed so an admin can see it in ai_trace."""
        estimator = self.estimator
        names = feature_names()
        if hasattr(estimator, "coef_"):
            return {
                str(label): {
                    name: round(float(weight), 4)
                    for name, weight in zip(names, row)
                }
                for label, row in zip(estimator.classes_, estimator.coef_)
            }
        return {}


# -- rules-only fallback ---------------------------------------

# How much the rule layer alone is willing to claim. A high-severity flag is
# strong evidence; "nothing tripped" is weak evidence of correctness, because
# the rules cannot see meaning at all.
RULES_ONLY_CONFIDENCE = {"high": 0.9, "medium": 0.7, "low": 0.6}
RULES_ONLY_CLEAN = 0.8      # cosmetic or equivalent-terminology change
RULES_ONLY_UNKNOWN = 0.6    # substantive, but nothing flagged


def rules_only_confidence(layer1_result) -> float:
    """Confidence for a verdict reached without Layer 2.

    Derived from the most severe flag rather than being a flat placeholder, so
    a removed requirement and a quiet result do not read as equally certain.
    """
    if layer1_result.failed:
        return 1.0

    severities = [
        config.SEVERITY.get(flag["label"], "low") for flag in layer1_result.flags
    ]
    if severities:
        return max(RULES_ONLY_CONFIDENCE.get(s, 0.6) for s in severities)
    if layer1_result.change_type in ("cosmetic", "terminology_equivalent"):
        return RULES_ONLY_CLEAN
    return RULES_ONLY_UNKNOWN


def rules_only_verdict(layer1_result) -> str:
    """Verdict from the rule layer alone, for when Layer 2 has no weights.

    Deliberately blunt. This path exists so the app still says something useful
    on a fresh clone, not so it can replace the model.
    """
    if layer1_result.failed:
        return "reject"

    severities = [
        config.SEVERITY.get(flag["label"], "low") for flag in layer1_result.flags
    ]
    if any(s == "high" for s in severities):
        return "reject"
    if severities:
        return "needs_revision"
    if layer1_result.change_type in ("cosmetic", "terminology_equivalent"):
        return "approve"
    return "needs_revision"


# -- the layer itself ------------------------------------------

def run_layer3(layer1_result, layer2_output: dict = None,
               fusion_model: FusionModel = None,
               thresholds: dict = None) -> FusionResult:
    """Combine both layers into one verdict, then apply the overrides."""
    layer2_output = layer2_output or {}
    verdict_probs = layer2_output.get("verdict_probs")
    issue_probs = layer2_output.get("issue_probs")
    confidence_source = "fusion" if fusion_model is not None else "layer2"

    issues = merge_issues(layer1_result.flags, issue_probs, thresholds)
    overrides = []

    # -- hard fail: procedural, and not the model's call ----------
    if layer1_result.failed:
        reasons = ", ".join(f["reason"] for f in layer1_result.hard_fails)
        return FusionResult(
            verdict="reject",
            confidence=1.0,
            issues=issues,
            overrides=[{"rule": "hard_fail", "detail": reasons}],
            probabilities={},
            confidence_source="rules",
        )

    # -- the learned part -----------------------------------------
    if fusion_model is not None:
        vector = build_feature_vector(
            layer1_result.features, layer1_result.change_type,
            verdict_probs, issue_probs,
        )
        probabilities = fusion_model.predict_proba(vector)
        verdict = max(probabilities, key=probabilities.get)
        confidence = probabilities[verdict]
    elif verdict_probs:
        probabilities = {
            v: float(p) for v, p in zip(config.VERDICTS, verdict_probs)
        }
        verdict = max(probabilities, key=probabilities.get)
        confidence = probabilities[verdict]
    else:
        verdict = rules_only_verdict(layer1_result)
        probabilities = {}
        confidence = rules_only_confidence(layer1_result)
        confidence_source = "rules"

    # -- agreement override ---------------------------------------
    agreed_high = [
        issue for issue in issues
        if issue["source"] == "both" and issue["severity"] == "high"
    ]
    if agreed_high and verdict == "approve":
        verdict = "needs_revision"
        overrides.append({
            "rule": "agreed_high_severity",
            "detail": ", ".join(i["label"] for i in agreed_high),
        })

    return FusionResult(
        verdict=verdict,
        confidence=float(confidence),
        issues=issues,
        overrides=overrides,
        probabilities={k: round(float(v), 4) for k, v in probabilities.items()},
        confidence_source=confidence_source,
    )
