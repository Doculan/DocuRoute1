# Revision AI Overhaul — Progress

Working log for the plan in `REVISION_AI_OVERHAUL.md`.
**Read both files at the start of any session.**

---

## Ground rules (in addition to the spec's section 0)

- Never print or open whole dataset files or large logs. Use counts,
  `head -n 5`, or the sampler. Exception: when a full read is genuinely
  needed to make progress, say so first.
- Update this file after every phase and every decision: findings,
  approved decisions, deviations, known issues, resume commands.
- Stop at every CHECKPOINT and wait for go-ahead.

---

## Status

| Phase | State |
|---|---|
| 0 — Explore and report | **Done** (CHECKPOINT 0 approved) |
| 1 — Prereq fixes + Layer 1 rules | **Done** (awaiting CHECKPOINT 1) |
| 2 — Layer 2 context model | Not started |
| 3 — Layer 3 fusion + Layer 4 explanation | Not started |
| 4 — Dataset creation | Not started |
| 5 — Train and evaluate | Not started |
| 6 — Wire into the app | Not started |
| 7 — Repo hygiene, setup, README | Not started |

---

## Phase 0 findings (measured, 2026-09-16)

**Data model.** A DB `Manual` is **one document** (e.g. `FAM 6.02`), not a whole
manual. `ManualSection` mixes both levels: 100 rows are `N.0`, 102 are `N.M`, and
only 2 of 202 have `parent` set, so the hierarchy is effectively flat. Section
text lives in `ManualSection.content`. Group-split by document = split by
`Manual.title`.

**Corpus.** 20 `Manual` rows, 202 sections, 20,913 words.
Families: FAM 10, HRM 4, SDM 4, ASM 1, COE 1.

**Usable revision units (A1 folding rule, >= 15 words): 115.**
Not the ~250 assumed in A9.

**Current assessment.** `ai_assessment_view` (views.py:1538) calls
`ml.distilbert_model.assess_revision(change_type, original_text, revised_text)`
and returns `{overall_verdict, issue_tags, findings, explanation, disclaimer}`.
Nothing is persisted. `train.csv` has 202 rows, binary verdicts
(`Appropriate` / `Needs Revision`), and 12 issue tags that do not overlap the
spec's 10 labels.

**Real revisions.** 2 total (1 rejected, 1 pending), both on FAM 6.02, both by
`eugene_l`.

**Known bugs — both confirmed present.**
- `reviewed_by` does not exist on `ManualRevision`; `review_revision` sets
  `reviewed_at` only.
- `UploadRevision.jsx` posts to `/api/upload/<manualId>/`, which does not
  exist, with no auth header — and the component is imported nowhere. The live
  path is `StaffSections.jsx` -> `/api/revisions/upload/<section_id>/` and
  `/api/revisions/propose-text/<section_id>/`.

---

## Approved decisions

| # | Decision |
|---|---|
| 1 | Dataset size: widen what counts as a unit (A3 linearised table rows), keep the 25/unit cap, accept ~2,000-2,400 examples, and document the shortfall against the 3,000 target in `DATASET_CARD.md`. |
| 2 | **Exclude `COE`** from dataset building — byte-identical MD5 to `HRM 4.02` (same PDF uploaded twice). Leaving it in would leak the same text across split groups. |
| 3 | **No department hard-fail rule** in Layer 1. FAM documents are parked in the CAS/CME test departments, so the check would reject legitimate revisions. Not part of the plan. |
| 4 | **Drop the clause 7.5.2 check.** `Manual` stores no document-no, revision-no or effectivity-date, so there is nothing to read. No new metadata fields. |
| 5 | **Exclude real revisions** from the dataset. Drop `--include-real` and `test_real.jsonl`; one usable row is not an evaluation. |
| 6 | Add `pytest` and `sentence-transformers` to `requirements.txt`. |
| 7 | Clause **7.5.2 is covered by the system, not the model** — document no., revision no. and effectivity date are entered manually and handled by the audit/document-control features. The ISO map for this build is 6.3, 7.5.3, 5.3. |
| 8 | Dataset size (final form of decision 1): widen units with the A3 table rows, keep the 25/unit cap, accept ~2,000–2,400 examples, document the shortfall against 3,000 in the dataset card. |

---

## Known issues / deviations

- **PyPI unreachable from the agent sandbox** (GitHub 200, PyPI times out).
  Dependency installs must be run by the user.
- **Two Python environments exist.** `venv/` has everything including pytest and
  sentence-transformers; the global interpreter does not. Eugene's `py` resolves
  to the venv because it is activated in his shell; an agent shell must call
  `venv/Scripts/python.exe` explicitly. **The venv is the environment of record.**
- `ml/datasets/train_manual_augmented.csv` has mixed label encodings in one
  column: `['1', 'Appropriate', 'Needs Revision']`. Pre-existing, owned by a
  teammate, not touched by this overhaul.
- ISO clause map for this build is **6.3, 7.5.3, 5.3** (7.5.2 dropped, see #4).

---

## Phase 1 — what was built

**1a. Prerequisite fixes**
- `ManualRevision` gained `reviewed_by`, `change_reason`, `ai_verdict`,
  `ai_issues`, `ai_explanation`, `ai_trace` (migration `0011`).
- `review_revision` now records `reviewed_by = request.user`.
- All three revision-creating views (`upload_revision`, `propose_text_revision`,
  `propose_merge`) accept and store `change_reason`.
- `list_revisions` returns the new fields.
- **Reason for change** is now a required field on the live staff paths in
  `StaffSections.jsx` (file upload and text edit).
- `UploadRevision.jsx` corrected: it posted to `/api/upload/<manualId>/`, which
  does not exist, with no auth header. It is still mounted nowhere — the live
  path is `StaffSections.jsx` — but it is no longer a broken example to copy.

**1b–1d. Pipeline package** (`Backend/ml/revision_pipeline/`)
- `config.py` — labels, clauses, severities, thresholds, feature order,
  special tokens, `PIPELINE_VERSION` and a fingerprint hash.
- `diffing.py` — line/word diffs, `marked_text`, ratios, sentence removal.
- `glossary.txt` (63 seeded pairs) + `glossary.py`.
- `entities.py` + `scripts/build_entities_draft.py` — mines roles, offices,
  systems and forms from the master copies.
- `layer1_rules.py` — hard fails, 14 features, 9 rule flags, change types.
- `tests/` — **62 tests, all passing.**

### Bugs the tests and smoke runs caught

| Bug | Fix |
|---|---|
| A *replaced* line counted as a deletion, so `excessive_deletion` fired on any single-line edit | Ratios use pure deletions only |
| Every edited sentence counted as removed, so a typo fix reported a removed requirement | Near matches count as surviving |
| One surviving sentence vouched for every deleted sibling (they share a skeleton) | One-to-one sentence matching |
| Reordering two list items read as a large deletion | `excessive_deletion` uses a bag-of-words net ratio |
| Short mined entity phrases ("Office") matched everything | Minimum phrase length of 5 |
| Stripping punctuation left a stray space, so a moved full stop read as substantive | Re-collapse whitespace after stripping |

### Open items for Phase 1

- `entities_draft.json` is mined but **not yet human-reviewed** (188 roles,
  41 offices, 67 systems, 56 forms). It contains noise (e.g. "LIST OF FORMS"
  as a form) and misses some real systems (e.g. SIAS). Review and save as
  `entities.json` before the dataset build in Phase 4.
- `scripts/build_glossary_draft.py` (TF-IDF term mining) is **not yet written**;
  `glossary.txt` is seeded by hand and sufficient for the pipeline to run.

---

## Resume commands

```bash
# corpus stats
cd Backend && py -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');django.setup();from api.models import Manual,ManualSection;print(Manual.objects.count(),ManualSection.objects.count())"

# tests  (venv must be active, or call venv/Scripts/python.exe directly)
cd Backend && py -m pytest ml/revision_pipeline/tests -q

# re-mine the entity draft from the master copies
cd Backend && py ml/revision_pipeline/scripts/build_entities_draft.py
```
