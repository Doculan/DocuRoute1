# Layer 4 explanation refinement — 30 September 2026

The AI check now describes small edits as actions in sentences, gives a concrete
next step when the change reason is vague, and qualifies statements based on
absent findings. This addresses the reviewed note that combined arrow-separated
diffs with categorical reassurance such as “responsibilities are untouched.”

## Scope and implementation

- `layer4_explain.py`: small edits with multiple changed spans use the observed
  insertion, deletion or substitution to compose prose. A shared clause location
  is stated once; changes at different locations retain their own locations.
  Substitutions keep surrounding text for context.
- Grouped insertions or deletions containing unchanged words are described as
  substitutions. This prevents an unchanged intervening word from being called
  newly added or removed.
- `layer4_wording.yaml`: wording revision 4 replaces categorical reassurance with
  descriptions of what the check detected. Cosmetic and equivalent-term wording
  also acknowledges the basis of the finding instead of asserting unchanged
  meaning. Section and proposal closings no longer treat an absence of concerns
  as proof of readiness.
- Vague-reason feedback asks the drafter to explain the trigger and intended
  result. Reviewer wording asks for that explanation from the drafting office.
- The composition remains deterministic, uses the existing rotation mechanism,
  and provides separate drafter and reviewer voices. No LLM service was added.

For a fixture reproducing the two edits in the supplied screenshot, the opening
now reads:

> In 3.2 of 3.0 POLICIES, “Any” was removed and “EO” was added.

Examples from the revised wording pools:

> Your change reason is quite general. Explain what prompted these edits and what
> they are intended to clarify or change.

> The check did not flag changes to figures, obligations or named responsibilities.

These are examples, not a promise of identical wording for every check: the
selected plan, voice, findings and rotation history determine the complete note.
The screenshot-like fixture also triggers an existing malformed-citation advisory;
that finding remains visible rather than being suppressed for a cleaner example.

## Assessment behavior and data

Layers 1–3, retrieval, model inputs, trained weights, thresholds, dataset and
evaluation code are unchanged. The pipeline fingerprint remains
`6a6a5c667a3c4d11`. This fingerprint checks the model-input configuration; it is
not a hash of every implementation file. The restricted source diff and the
before/after inference comparison provide additional evidence of scope.

No schema migration, database update or stored-note rewrite is required. Existing
checks retain their stored explanations. Newly executed checks use the revised
wording after the backend loads the updated code. The wording file is cached per
process, so restart existing backend workers. The frontend's existing streaming
reveal is unchanged.

## Verification

| Check | Result |
| --- | --- |
| Original Layer 4 tests before edits | 189 passed |
| Final complete revision-pipeline test suite | 422 passed, including 196 Layer 4 tests |
| New regression cases | Seven; each demonstrated a failure before its corresponding fix |
| Proposal and pre-assessment API tests | 57 passed using the test database and temporary media directory |
| Model setup check | Ready; encoder, tokenizer and fusion model loaded |
| Fingerprint | `6a6a5c667a3c4d11`, matching local weights |
| Trained-model before/after comparison | Wording, numeric and negation cases retained identical non-explanation output |

The inference comparison loaded the original Layer 4 Python code and wording from
commit `79e2d23`, then compared it with the refinement using the same trained model
and inputs. All returned fields except the two explanations and note-choice
metadata matched, including the verdict, confidence, issues, advisories and trace.

Commands used:

```powershell
# Repository root
.\venv\Scripts\python.exe -m pytest Backend/ml/revision_pipeline/tests -q

# Backend directory
..\venv\Scripts\python.exe -X utf8 manage.py test api.tests_proposals api.tests_pre_assessment --noinput
..\venv\Scripts\python.exe -X utf8 ml/revision_pipeline/scripts/check_setup.py
```

## Limits and follow-up

This improves explanation quality; it does not retrain the model or fix its
known overconfidence on realistic harmless rewording. Published verdict figures
were not re-evaluated in this refinement: no scoring layer changed. Those figures
remain measurements of agreement with generated labels, not evidence of the
quality of the new prose or accuracy on real staff revisions.

Generated notes were reviewed from Python output. No browser walkthrough or new
user study was performed. Small edits now read more naturally, but the engine
still cannot infer the author's intent or verify policy/legal correctness.

The test environment emitted existing SVM artifact warnings (scikit-learn 1.8.0
artifacts loaded with 1.9.0), a PyMuPDF import deprecation, and a Windows physical
CPU detection warning with logical-core fallback. Tests and inference completed
successfully; those environment issues were outside this wording refinement.

## Follow-up: wording 4.1

A review of the notes this refinement produced found four defects, fixed in
wording 4.1: a noun-phrase-unsafe opening, an item number repeated after a quote
that already showed it, colon openings joining a lower-case "in", and up to three
"the check did not…" sentences in one note. Openings now read, for example,
"“Any” was removed and “EO” was added at 3.2." The stand-alone change sentence
("In 3.2 of 3.0 POLICIES, …") is unchanged. See PROGRESS.md for verification.
