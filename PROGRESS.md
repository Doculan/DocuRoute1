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
| 2 — Layer 2 context model | **Done** (awaiting CHECKPOINT 2) |
| 3 — Layer 3 fusion + Layer 4 explanation | **Done** (awaiting CHECKPOINT 3) |
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
| 9 | **"List of Forms" (5.0) sections are not revision units.** No dataset examples are generated from them, and the AI assessment returns *"not assessed — manual admin review"* instead of a verdict. Form **names** are still mined from them for `entities.json`, because Layer 1 uses them to detect deletions inside procedures. The A6 "delete a form from 5.0" contradiction generator is dropped. Cost: 1 usable unit (110 → 109). |

---

## Phase 2 — what was built

- `retrieval.py` — per-document TF-IDF index (optional MiniLM backend), disk +
  memory cache, `get_context()` and `related_texts()`. Knows about decision 9:
  a List of Forms section is retrievable **as context** but is never a query.
- `layer2_model.py` — one DistilBERT encoder, two heads. Verdict head uses
  weighted cross-entropy; issue head uses BCE with per-label `pos_weight`
  capped at 20. Rows with `issues_labeled=false` are masked out of the issue
  loss. `save()`/`load()` write an encoder folder, `heads.pt`,
  `label_config.json` (with the pipeline fingerprint) and `thresholds.json`.
- `data.py` — JSONL loader (accepts `.gz`), multi-hot conversion, and a
  `RevisionDataset` that rebuilds context via `retrieval.py` rather than
  reading it from the dataset file.
- `scripts/train_layer2.py` — all the required args, early stopping on
  *verdict macro-F1 + issues micro-F1*, per-label threshold tuning on the
  validation split, per-epoch CSV log, and `--estimate-first` for a 20-step
  timing run.

### Smoke test (60 synthetic examples, CPU, 2 epochs)

Trains: loss 1.69 → 0.76, verdict macro-F1 1.0. ~55 s/epoch on 45 examples at
batch size 4. Save/load round-trips, the fingerprint matches, and a held-out
role swap predicts `reject` at 0.94. Artifacts deleted afterwards (the encoder
alone is 254 MB).

### Bugs the smoke test caught

| Bug | Fix |
|---|---|
| `_window_around_change` sliced by **words** while the budget was in **tokens**, so an oversized change stayed over the limit and `only_second` had nothing left to truncate — the tokenizer raised *"Sequence to truncate too short"* | Window on token ids |
| A long deletion put the window's midpoint inside the deleted span, so **neither** `[DEL]` nor `[INS]` survived and the model could not see what changed | Keep head **and** tail with a marked gap between |
| Retrieval returned the query's own subsection (`4.0` retrieved `4.5`) | Parent/descendant exclusion; siblings still allowed |
| Threshold tuning collapsed to 0.05 for **every** label, so all ten issues fired on every example. Labels with no validation positives score F1 = 0 at every cut-off, so the search kept whichever value it tried first | Labels with no positives keep the 0.5 default; the search runs high-to-low so ties keep the more conservative cut |
| `float(out.loss)` on a tensor that still required grad | `.detach().item()` |

---

## Phase 3 — what was built

- `layer3_fusion.py` — feature assembly, issue merging with a `source` of
  `rule` / `model` / `both`, a fusion model that fits both LogisticRegression
  and HistGradientBoosting and keeps whichever cross-validates better (recorded
  in `fusion_config.json`), coefficients exposed for `ai_trace`, and a
  rules-only fallback.
- `layer4_explain.py` — deterministic template writer seeded by revision id.
  Three or more phrasings per label, hedging by confidence
  (>0.85 "clearly", >0.65 "likely", else "may"), varied connectors with
  high-severity variants, a six-sentence cap that summarises the remainder,
  and the decision-9 "not assessed" message.
- `pipeline.py` — `assess_revision(revision)` and `assess_texts(...)`, models
  cached per process, torch imported lazily so a Django worker that never
  assesses anything does not pay for it. Missing Layer 2 weights degrade to
  rules-only with `trace.layer2 = "unavailable"` rather than failing.
- `scripts/train_fusion.py` — trains from the saved fold predictions, on the
  **validation** split only.

**Two overrides are deliberately not learned:** a Layer 1 hard fail forces
`reject` (the objection is procedural, not the model's call), and a
high-severity issue that *both* sources flag forces at least `needs_revision`.

34 new tests, 112 total, all passing.

### Bugs found while wiring the layers together

| Bug | Fix |
|---|---|
| Numeric evidence read `30, 30 days, 60, 60 days` — the bare number and the duration containing it were both counted, inflating `numeric_changed_count` | Drop a token contained in a longer matched phrase |
| Role evidence listed `accounting staff` and `accounting staff-4` for one mention, because the entity list holds both forms | Keep only the longest matching phrase |

---

## Training budget and the fold decision

**Hardware of record: i3-1215U (2 performance + 4 efficiency cores), 8 GB RAM
with roughly 1 GB usually free.** Local training is a **fallback only**.

Measured on this machine, DistilBERT at batch size 8:

| Setting | ms/example | min/fold (2,180 ex × 3 epochs) |
|---|---|---|
| threads 6 (torch default), max_length 384 | 1547 | 169 |
| threads 8, max_length 384 | 1412 | 154 |
| **threads 8, max_length 256** | **830** | **90** |
| threads 8, max_length 256, short context | 791 | 86 |

**`max_length` is the lever, not padding.** Dynamic padding was measured at
**0.88× — slightly slower**, because `truncation="only_second"` expands the
retrieved context to fill whatever budget is left, so every batch already hits
the cap. It is kept anyway: once Phase 4 produces short units (linearised table
rows), sequences will vary and it will start to pay. Using all 8 cores rather
than torch's default 6 is worth ~9%.

**Token lengths** across 109 real section-sized examples: the full pair is
p50 381 / p95 1321 tokens, so **`max_length=256` covers only 3.7%** of whole
pairs — nowhere near 95%. The more useful figure is the change alone
(`text_a`, which must not be truncated): p50 131, p75 266, p90 569. At
`max_length=256` the change survives whole for **73.4%** of examples; at 384,
82.6%. These are measured on *whole sections*; real revision units will be
smaller, so re-measure after Phase 4 before lowering the default.

**Fold decision: Colab.** The best local figure, 86 min/fold, is over the
~1 hour bar. `MAX_LENGTH` stays **384** — the CPU compromise is unnecessary
on a GPU.

### How the Colab run is organised

- **Google Drive is mounted**, and each fold's `metrics.json`,
  `predictions.jsonl`, `thresholds.json` and `training_log.csv` are copied
  there as soon as that fold finishes. Re-running skips any fold already
  present in Drive, so a disconnect costs one fold rather than the run.
- **Fold weights are never saved.** Folds exist to measure performance, so
  `--no-save-weights` keeps the metrics and predictions and discards the
  encoder: **18 KB per fold instead of 254 MB**.
- **Fusion trains from the saved prediction files**, so it runs in Colab or
  locally after downloading `folds/` — it never needs a fold model.
- **One final model** is trained afterwards on every document, holding out 8%
  purely so **early stopping** has something to watch. Only that model —
  encoder, tokenizer, `heads.pt`, `thresholds.json`, `label_config.json` — is
  zipped to Drive.
- **The final model's per-issue thresholds are the median across the five
  folds** (`--thresholds-from`), not tuned on the 8% slice. That slice is far
  too small for a rare label such as `contradicts_manual`: a couple of examples
  either way would swing the cut-off. Each fold tuned on a proper validation
  split, so their median is the more honest estimate.
- Colab clones from **GitHub**, so whatever is being trained must be pushed
  first. The Phase 7 size check runs before that push.

### Local fallback

`train_layer2.py` now takes `--grad-accum` (effective batch unchanged while
the resident batch shrinks), defaults to **batch 4 on CPU** and 16 on CUDA,
and `--estimate-first` prints peak RSS with a warning past 3 GB. Measured
1,410 MB at batch 2 × 128 tokens, so batch 4 × 384 needs watching on a machine
with 1 GB free. TF-IDF stays the default retrieval backend — no model
download, no extra memory.

---

## Phase 4 — design (agreed before building)

### Unit vs. submission unit

The app submits **whole stored sections** — revision 12 was the entirety of
`4.0 PROCEDURES`, not one row. So:

- **Table rows are where edits are applied**, per A3.
- **`old_text` / `new_text` are the whole stored section**, exactly as the app
  would submit it.
- **1–3 edited rows per example**, so a revision can carry several small
  changes the way a real one does.
- Report the **token-length distribution on the built dataset** — the earlier
  measurements were on whole sections without edits and will not transfer.

### Sampling

- **Stratify by section type** (Objectives / Scope / Policies / Procedures) so
  procedures — which hold all 487 table rows — do not swamp the rest. Report
  counts per type.
- **Minimum 150 positive examples per issue label.** Adjust the generator mix
  to reach it and raise the total above 3,000 if needed; training runs on
  Colab, so size is cheap. Report per-label counts and name any label that
  cannot reach the floor.

All earlier Phase 4 rules stand: the quality bar below, the borderline-match
discard rule, and decision 9.

---

## Phase 4 — dataset quality bar (agreed before building)

**Treat every generated example as if a real staff member submitted it and a
real admin will judge it.** A dataset of mechanical edits teaches the model to
spot mechanical edits, which is not the task.

- **Readability.** Every example must read like something staff would actually
  write: grammatical, in the manual's style, no broken sentences, no leftover
  markers, no obviously mechanical edits (random words, doubled spaces,
  nonsense substitutions).
- **Label correctness.** Every label must be right as a real admin would judge
  it. Where a generator produces an edit whose correct verdict is unclear,
  **discard it rather than guess**.
- **Realistic edit patterns.** Mix them: several small edits in one revision,
  a good change combined with a bad one, a whole sentence reworded rather than
  one word swapped, and legitimate edits that look suspicious.
- **Change reasons.** Every revision carries a realistic `change_reason` in
  staff language ("Updated to reflect the new collection schedule"), including
  some vague or misleading ones on bad revisions. A few have none, to exercise
  the clause 6.3 hard fail.
- **Quality gate in `build_dataset.py`.** Validate each example - markers,
  grammar sanity, label consistency against the Layer 1 flags where applicable
  - and report rejection counts per generator.
- **Report borderline sentence matches.** The 0.6 similarity cut-off in
  `sentences_removed` decides whether an edit is a rewrite or a removal, and so
  whether the example carries `requirement_removed`. Report how many pairs
  scored **0.5-0.7**, with a few examples, using
  `diffing.sentence_match_report()`. A count creeping up means the threshold is
  carrying more weight than it should.
- **At CHECKPOINT 4:** show 5 random examples per generator, plus the 10 the
  quality check scored most borderline, for review as a real admin before any
  training.

---

## Queued — to do after Phase 2, before Phase 4

1. ~~Re-extract the manuals with the new A3 table format.~~ **Done** — see
   "Re-extraction" below.
2. **Extend `clean_section_content` to clean subtitles too.** It currently
   cleans `content` only, which is why `FAM 8.02` still stores
   `'5.0 LIST OF FORMS <!-- End of picture text -->'`. Decision 9 matches on
   that title, so the artifact has to go.
3. **`role_swap` must handle combined roles.** Reducing `"X/Y"` or `"X or Y"`
   to a single party is `responsibility_changed` — never an approve example.
   30 such entries exist in `entities.json` (e.g. `BAC Chairperson/ University
   President`, `Accounting Staff-1 or 6`).
4. **`DATASET_CARD.md` must report example counts per section type**
   (Objectives / Scope / Policies / Procedures).
5. **Before Phase 5:** run the Phase 7 size check (`scripts/check_repo_size.py`)
   and prepare a safe first push — Colab clones from GitHub, so the dataset and
   pipeline have to be on the remote before any training can start.
6. **Phase 7 README must cover** how to fetch the final model from Drive and
   where to unzip it: `Backend/ml/saved_models/context_v2/`, so the folder ends
   up holding `encoder/`, `tokenizer/`, `heads.pt`, `thresholds.json` and
   `label_config.json`. Also: creating and activating the venv.

---

## Re-extraction (done, 2026-09-17)

Ran **in place**, matching stored sections to fresh ones by document + section
number. All **197 stored sections matched**, zero orphans, so no row was ever
deleted and `on_delete=CASCADE` never fired. One section was created
(`SDM 3.06 :: 5.1 Certificate of Good Moral Character`, 0 words, and a forms
subsection so not a revision unit under decision 9).

Verified afterwards: **198 sections** in the 19 documents, **2 revisions** and
**3 history rows** still attached to their original section ids, and sections
carrying a `| --- |` separator row went **1 → 46**.

Safety copy taken first:
`Backend/ml/exports/revisions_and_history_20260917-083912.json`, plus
`db.sqlite3.bak-prereextract-20260917-085407`.

**On the "1 → 46" figure.** 46 sections contained pipe characters before, but
only **one** had a real separator row (`| --- | --- |`, the line that declares
the column count and marks the header) — SDM 3.03, which had been updated by
hand during testing. The other 45 had pipes only as cell delimiters in
flattened rows. The two numbers matching at 46 is a coincidence.

**COE** is a `Manual` row pointing at `HRM_4_MoGMsSE.02.pdf`, MD5-identical to
`HRM_4.02.pdf` — the same document uploaded twice, into the COE department.
It is excluded from entity mining and from the dataset via
`_corpus.EXCLUDED_DOCUMENTS`; `load_documents()` returns 19 documents with COE
absent.

### Extraction artefacts — cleaning pass added

These are damage from the PDF text layer, **not mistakes anyone wrote**.

| Artefact | Before | After |
|---|---:|---:|
| Glued words (`theBookkeeper`) | 18 | **0** |
| Digit glue (`3.Undergraduate`) | 30 | **0** |
| Colon glue (`Undergraduate:If`) | 4 | **0** |
| Merged steps in one cell (`1. … 2. …`) | 17 | **0** |
| Stray backtick (`Responsibility\``) | 1 | **0** |
| Stray punctuation lines | 0 | **0** |

`ocr_engine.repair_artefacts()` handles the glue; merged steps are split into
one row per step with the role inherited from the row above (Appendix A3).
Two ordering bugs were found doing this: the repair originally ran *before*
Markdown stripping, so `3.**Undergraduate:**If` showed an asterisk where the
patterns expected a letter; and the step splitter required a full stop, so a
step ending `…(VPSDAS) 2. Checks…` was missed.

**A7 correction:** these artefacts must **never** be used as `real_typo_fix`
examples. They are extraction damage, not human error, so "correcting" one is
not a revision a person would ever submit. `real_typo_fix` may only use
genuine spelling and grammar errors present in the source document.

**Revision 12's `diff_text` is deliberately left unchanged.** Its baseline
section content changed, so the stored diff no longer reproduces against the
current text. Rewriting a historical record to match a later extraction is
worse than a stale diff; the original is in the export either way.

### Recomputed after cleaning

- **Entities:** 129 roles, 27 offices, 67 systems, 53 forms (was 168/31/73/53).
  The drop is the cleaning working — glued and merged variants no longer mined
  as separate entities.
- **Usable units: 562** (75 prose + 487 table rows), counting each table row as
  a unit per A3. Previously 109 prose-only.
- **`--per-section`:** 3.6 reaches 2,000; **5.3 reaches the 3,000 target**,
  far below the 25/unit cap (ceiling 14,050). **This supersedes decision 8** —
  the 3,000 target is now comfortably reachable and the shortfall note is no
  longer needed.
- **Retrieval re-verified:** `4.0` no longer returns its own `4.5`; `4.5` gets
  sibling `4.4` but not parent `4.0`.
- **Token lengths** (whole sections, 109 measured): text_a p50 140, p95 727.
  `max_length=384` keeps the change whole for 83.5%. Phase 4 units are mostly
  single table rows and will be much shorter — **re-measure on the dataset
  itself before settling `max_length`.**

---

## Known issues / deviations

- **PyPI unreachable from the agent sandbox** (GitHub 200, PyPI times out).
  Dependency installs must be run by the user.
- **Two Python environments exist.** `venv/` has everything including pytest and
  sentence-transformers; the global interpreter does not. Eugene's `py` resolves
  to the venv because it is activated in his shell; an agent shell must call
  `venv/Scripts/python.exe` explicitly. **The venv is the environment of record.**
- **The 2 revisions and 3 history rows are test entries, not real-world data.**
  They must not be treated as an admin-decided evaluation set.
  **Revision 13 is kept as a Phase 6 smoke test:** pending, on
  `FAM 6.02 :: 1.0 OBJECTIVES`, with no `change_reason`. Expected assessment —
  a hard fail for the missing reason (clause 6.3), plus a flag for
  `"accounts"` → `"payments"`.
- **Known gap (clause 7.5.3): admins can edit sections directly**, through the
  Sections screen, bypassing the revision flow entirely. Such an edit gets no
  AI assessment, no `change_reason` and no approval step - only a
  `SectionHistory` row. The controlled-change path is therefore only as strong
  as the convention that admins use it.
- `ml/datasets/train_manual_augmented.csv` has mixed label encodings in one
  column: `['1', 'Appropriate', 'Needs Revision']`. Pre-existing, owned by a
  teammate, not touched by this overhaul.
- ISO clause map for this build is **6.3, 7.5.3, 5.3** (7.5.2 dropped, see #4).

---

## Corpus section structure (all 19 documents)

Every document has exactly the same five top-level sections. There are **no
References, Definitions or Annexes sections anywhere in the corpus** — the only
reference-only section is List of Forms.

| Top-level title | Documents |
|---|---|
| `N.0 OBJECTIVES` (2 as `OBJECTIVE`) | 19 |
| `N.0 SCOPE` | 19 |
| `N.0 POLICIES` | 19 |
| `N.0 PROCEDURES` (2 as `PROCEDURE`) | 19 |
| `5.0 LIST OF FORMS` | 19 |

The forms section is titled `5.0 LIST OF FORMS` in all 19, so decision 9 can
match on that string plus the singular/plural variants above.

**One extraction artifact found:** `FAM 8.02` stores its section as
`'5.0 LIST OF FORMS <!-- End of picture text -->'`. The `clean_section_content`
command cleans `content` but never `subtitle`, so HTML comments in headings
survived. One row affected; worth extending that command.

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

- `entities.json` has been produced by `scripts/clean_entities.py` from the
  mined draft: **171 roles, 34 offices, 73 systems, 54 forms**. Headings, bare
  category words and near-duplicates removed; SIAS and eNGAS added by hand.
  Still worth a human read before the Phase 4 dataset build. Role quality is
  limited by the legacy flattened tables and should improve once the manuals
  are re-extracted with the new table format.
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
