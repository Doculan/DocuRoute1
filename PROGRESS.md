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
| 1 — Prereq fixes + Layer 1 rules | **Done** (CHECKPOINT 1 approved) |
| 2 — Layer 2 context model | **Done** (CHECKPOINT 2 approved) |
| 3 — Layer 3 fusion + Layer 4 explanation | **Done** (CHECKPOINT 3 approved) |
| 4 — Dataset creation | **Done** (CHECKPOINT 4 approved after two rebuilds and a blind audit) |
| 5 — Train and evaluate | **Folds done and settled** — verdicts 0.978 fused, issues 0.854; fusion pinned to boosting and trained; Layer 2 final model still to train (Kaggle) |
| 6 — Wire into the app | Not started |
| 7 — Repo hygiene, setup, README | Started: compiled Python untracked, size check written |

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

## Phase 4 — what was built

### Files

| File | What it holds |
|---|---|
| `revision_pipeline/section_doc.py` | A stored section parsed into the places an edit can land: table rows, prose sentences. Edits one; renders the whole section back. |
| `revision_pipeline/generators.py` | 22 edit generators across approve / needs_revision / reject, plus the change-reason pools. |
| `revision_pipeline/quality.py` | The gate. Judges each candidate as an admin would and discards rather than guesses. |
| `scripts/build_dataset.py` | The build: first pass, top-up passes, dedup, balancing, splits, dataset card, Checkpoint 4 samples. |
| `scripts/report_token_lengths.py` | Token-length distribution on the built dataset (design point 3). |
| `scripts/report_rule_coverage.py` | Measures the rule-hard share instead of trusting the declared set. |
| `tests/test_unit_alignment.py` | The unit-level comparison described below. |

### What the build does

1. **Parse once.** Every usable section is parsed and its context assembled up
   front; generation then runs more than once over the same jobs.
2. **First pass** — every generator, `--per-section` attempts each.
3. **Issue top-ups** — for each label still under the floor, re-run only the
   generators that can produce it. A uniform `--per-section` cannot reach the
   floor for a rare label: 156 units in the whole corpus carry an obligation
   modal, so raising it for everything mostly produces more of what is already
   plentiful.
4. **Approve top-ups** — the issue top-ups only run generators that produce an
   issue, so each round pushes the approve share down. Without its own rounds
   the build came out 8% approve.
5. **Quality gate** on every candidate, counted by reason.
6. **Balancing** (see below), then a document-grouped 5-fold split, the
   dataset card, and the samples.

### Balancing, in priority order

The three goals conflict, and the order matters — getting it wrong cost two
full builds:

1. **Per-label floor** (150). Never traded away.
2. **Verdict balance.** No verdict class is trimmed below `--verdict-floor-share`
   (0.2). A dataset that is 8% approve teaches the model to say no.
3. **Section type.** No type may exceed `--type-max-share` (0.45), trimmed
   weakest-first, and only from examples that are spare under 1 and 2. A type
   that cannot be trimmed that far stays over its share and the report says so.

The first attempt capped each type at 2.5× the smallest with no regard for the
other two, and took its whole surplus out of the approve class: 1,225 examples,
102 of them approve, and not one from `typo_fix`, `whitespace_format`,
`benign_reorder`, `redundant_removal` or `equivalent_synonym`.

### Finding that changed Phase 1: the rules could not see a step change hands

Layer 1 compared roles, key terms and figures as **whole-section sets**. Give
step 4 to an officer who already owns step 7 and the set of roles present is
identical, so the rules reported nothing — and the quality gate then discarded
the example for claiming `responsibility_changed` when Layer 1 could not see
it. 64 examples went that way in the first probe build.

`diffing.aligned_units()` now pairs the units that are the same step before and
after the edit (a table row is matched on its step text, so a changed
Responsibility cell still matches the same step), and Layer 1 compares roles,
key terms and figures **again on each matched pair**, unioning the result with
the section-wide view. Nothing the old view caught is lost; reordering rows
still reports nothing.

Identical units are paired first and only the leftovers go through the
pairwise scan, so the common case — one to three units edited out of twenty —
stays close to linear.

**`RULE_HARD` is now measured, not declared.** The unit-level comparison made
role reassignment visible to the rules, so the declared set drifted.
`report_rule_coverage.py` counts non-approve examples on which Layer 1 raises
no flag at all.

### Generators added during the build

- **`bulk_deletion`** — `mass_deletion` only worked on tables, and half a table
  often falls short of the deletion threshold, so `excessive_deletion` reached
  a fifth of the floor. This cuts a run out of a table *or* a prose section and
  keeps the example only when the cut is genuinely large but not a replacement.
- **`key_term_vagueing`** — the commonest way a named control disappears from a
  procedure is not deletion but genericisation ("attach the Disbursement
  Voucher" → "attach the document"), and it leaves a readable step, which
  straight deletion often does not.

Six generators that only ever looked at table rows now edit prose sentences
too (`modal_weaken_single`, `negation_flip`, `numeric_change`,
`non_equivalent_swap`, `partial_key_term_delete`, `contradiction_from_context`).
63 of the 104 usable sections have no table at all, so those generators had
been returning `None` for Objectives, Scope and most Policies — exactly the
section types the dataset was thinnest in. `numeric_change` went from 16
produced to 55 on the same probe.

### Build result (2026-09-17, `--per-section 5`)

**2,637 examples, 19 documents, 22 generators.** 3,238 candidates generated,
75 rejected by the gate, 0 duplicates, 526 trimmed by the type cap.

| | |
|---|---|
| approve | 663 (25%) |
| needs_revision | 667 (25%) |
| reject | 1,307 (50%) |
| Procedures / Policies / Objectives / Scope | 1,423 / 919 / 191 / 104 |
| files | `all.jsonl` 9.3 MB, splits 9.3 MB, ~2.3 MB packed |

Nine of the ten issue labels reach the 150 floor. `negation_changed` reaches
**110** and cannot go higher on this corpus: only about 110 units contain
"shall" and 79 contain a negation word, and 15 further flips were generated
but rejected because they reverse the sense without changing a negation word
("before" → "after"), which Layer 1 does not count.

**Borderline matches:** 69 examples (2.6%) contain a sentence pair scoring in
the 0.5-0.7 band around the 0.6 removal cut-off; 10 more scored 0.5 as hard
negatives that trip a rule by design. Everything else scored 1.0.

**Edited units:** 2,336 examples edit one unit, 162 edit two, 26 edit three.
The 51 above three are `bulk_deletion` and `mass_deletion`, which are bulk cuts
by definition - a deliberate exception to the 1-3 rule.

**Token lengths** (`report_token_lengths.py`): p50 207, p75 477, p90 759,
p99 1,871. `max_length=384` keeps the change whole for **70%** of examples,
512 for 77%. The Phase 2 figure of 83.5% was measured on whole sections with
no edit applied; the markers an edit inserts push it down.

### The 40% rule-hard target is not met

The build report's own figure (43%) is computed from the **declared**
`generators.RULE_HARD` set, which went stale the moment the unit-level
comparison made role reassignment visible to the rules. Measured on the built
dataset:

| Measure | Result |
|---|---|
| Layer 1 raises no flag at all (non-approve) | 136 / 1,974 = **7%** |
| Layer 1 alone reaches the wrong verdict (all) | 833 / 2,637 = **32%** |
| Layer 1 alone reaches the wrong verdict (non-approve) | 417 / 1,974 = **21%** |

The two requirements pull against each other: the quality gate *requires*
Layer 1 to confirm six of the ten labels, which by construction makes those
examples rule-visible. What is left for Layer 2 is where the rules see
something and still reach the wrong answer - all 368 `clarifying_addition`
examples (rules say needs_revision, truth is approve), all 227
`contradiction_from_context` (rules see only a changed figure, truth is
reject), all 111 `step_reorder_dependent` (rules see nothing), and the hard
negatives.

### Deviation: no examples with a missing change reason

The quality bar asks for a few examples with no `change_reason`, to exercise
the clause 6.3 hard fail. They are **not** in the dataset, deliberately:

- A missing reason is a Layer 1 hard fail, so Layer 2 never sees the example —
  the pipeline short-circuits before the model runs.
- Training on them would teach the model to reject content that is fine, since
  the text itself carries no defect.
- The gate would reject them anyway: a reject example with no issue label, and
  there is no issue label for a missing reason.

The hard fail is covered by `tests/test_layer1_rules.py` instead.

### Second sweep of extraction glue (2026-09-17)

The reviewed glue table caught two-word fusions. A sweep of the re-extracted
sections found **17 occurrences of longer runs** the table did not cover —
`itempurchasesintherecords`, `organizationadviseraswitnessesinthe`,
`BUR Sinthe'Utilization'columnoftheRBUD`, `JE Vusing`, `OS Dandfurthersecure`
and ten more. All are written out explicitly in `_LOWER_GLUE`, no segmentation.
Applied to the stored sections with `clean_section_content --apply`
(17 sections; database backed up to `db.sqlite3.bak-2026-09-17-glue` first).
Glue occurrences: **17 → 0**.

Re-cleaning also exposed a latent bug: `_render_table` emitted `|  |` for an
empty cell and only the *storage* path collapsed it to `| |`, so re-cleaning
reported 41 sections as changed when 17 had really changed. The renderer now
collapses the spaces itself, which makes a second cleaning pass a no-op.

---

## Checkpoint 4 — rejected, and what the rebuild changed

The first build was reviewed example by example and **not approved**. Nine
faults were found; all are fixed below. Two of them were faults in the *rule
layer*, not the generators, and would have mislabelled real revisions too.

### 1. Renumbering was being read as a changed figure

The worst of them. Layer 1 treated every digit as a quantity, so changing
"3.15" to "1.15" counted as a changed figure - and where a sibling section
still carried the old number, as a contradiction.

**Measured on the rejected build:**

| Generator | Renumbering only | A real quantity |
|---|---:|---:|
| `contradiction_from_context` | **216 of 227 (95%)** | 11 |
| `numeric_change` | **152 of 160 (95%)** | 8 |

- `layer1_rules._strip_item_numbers` blanks an item or step number at the start
  of a line, a cell or a clause before numeric tokens are read.
- `generators._quantity_spans` finds only real figures: a number with a unit
  ("15 days", "30%"), the house-style "three (3)" pair, or an amount of money.
- `contradiction_from_context` now needs a fact **a sibling section still
  states**. Durations are compared in days, so "1 year" here and "365 days"
  there are recognised as the same fact - which is the example given in the
  review. Only **2 sections in the whole corpus** restate a fact that way, so
  this generator is capacity-limited to 3 examples and `contradicts_manual` is
  carried by `step_reorder_dependent`.

### 2. `benign_reorder` was swapping dependent steps

It now refuses any section that is a procedure table, any pair where either row
opens with a step number, and any pair mentioning a sequence ("Return to step
4", "thereafter", "once"). It is left with genuinely unordered lists, which is
6 examples - small, and correct.

### 3. `redundant_removal` was deleting distinct entries — generator removed

It duplicated a row into `old_text` and then removed it, which made `old_text` a
section the manual never had, and read exactly like deleting a real bank account
row. The corpus was searched for genuine duplicates: the only repeats are the
same step text in **different sub-procedures** of one section, where deleting
one is not approve either. So the generator is gone, replaced by two honest
hard negatives:

- `row_merge_reformat` - joins two rows that are one step, keeping every word.
- `benign_reorder` - as above.

**Why Layer 1 flagged `negation_changed` on the bank rows:** the negation test
was a prefix regex, `(un|non|dis|in)[a-z]{3,}`, which matched **"university"**,
"information", "internal", "inspection" and "disbursement". Deleting any row
containing one of those changed the count. Replaced by an explicit
`config.NEGATED_FORMS` list.

### 4. The approve class was thin and repetitive

`clarifying_addition` was 55% of approvals, reused two sentences, and one of
them ("Copies are retained by the office concerned") added a requirement. It is
deleted. Seven approve generators now work from the section's own content:

| Generator | What it does |
|---|---|
| `typo_fix` | corrects a misspelling the submitted text carries |
| `whitespace_format` | spacing and punctuation only |
| `equivalent_synonym` | a curated phrase swap, grammar-aware |
| `acronym_expansion` | spells an acronym out on first use, from the corpus's own definitions |
| `spell_out_figure` | "15 days" becomes "fifteen (15) days", the manual's house style |
| `legal_reference_format` | "R.A. 9184" becomes "Republic Act No. 9184" - same statute |
| `cross_reference_addition` | adds a pointer to a real sibling section |

`equivalent_synonym` no longer draws from the glossary, which produced "as
mandatory", "Once accomplish" and "all office", and renamed documents ("Form"
became "Template"). It uses a curated list of phrases with their inflections,
skips any span inside a Title-Case run, and is checked by the grammar gate.

A **strategy cap** (`--strategy-max-share`, default 0.07) stops any single
phrasing filling the dataset: no one typo, synonym pair or added clause may
hold more than that share.

### 5. Change reasons now match the edit

`_REASONS` is keyed by the kind of edit - typo, format, term, clarify, merge,
reorder - and each approve generator draws from its own pool. "Fixed spelling"
can no longer appear on a deletion. Revisions that are not approvals draw from
the plausible and vague pools, which fit any edit.

### 6. Broken generators

- **Sentence splitter**: `diffing.sentences` joins a fragment back when the one
  before it ends in an abbreviation. "governed by E.O. No. 2, series of 2016"
  was three sentences, so an edit near it looked like several sentences
  appearing and disappearing.
- **`key_term_vagueing`**: only terms that really name a document are eligible,
  and the replacement is the generic noun for *that kind* of document, with the
  article and any bracketed acronym handled as one unit.
- **`partial_key_term_delete`**: takes the article and the acronym with the
  term, so "submits the Disbursement Voucher (DV) to" no longer leaves "submits
  the to".
- **`non_equivalent_swap`**: modal pairs, sense-reversal pairs and
  strengthening are all excluded. "should" becoming "shall" is not an issue.
- **`negation_flip`**: rebuilt on `config.SENSE_REVERSALS`. with/without is
  only applied where the following word keeps it grammatical, so "without first
  exhausting" is never turned into "with first exhausting".
- **`foreign_insertion`**: a table section takes a row of the matching column
  count, a prose section takes a sentence.
- **Role generators**: `_role_rows` requires a Responsibility/Activity table and
  a role the rule layer itself recognises. The frequency column ("Quarterly",
  "First Week of the Year") is excluded by name.

### 7. A grammar and format gate

`quality.grammar_faults` rejects an example when the **edit introduces**
repeated function words, a determiner before a determiner ("each the"), an
article before a verb or a preposition ("submits the to"), a dangling
preposition, "with" followed by a gerund, unbalanced parentheses, table rows of
differing column counts, or a row that stops mid-phrase. Faults already present
in the master copy do not count against the edit.

### 8. Extraction, third pass

- **Glue**, found by segmenting every rare token against the corpus's own
  vocabulary and then written out by hand: `itreceives`, `overthe`,
  `purchaseditems`, `renderthe`, `Providersif`, `asnecessary`,
  `bidsfromprospective`, `otherSDs`, `supportingdocuments`, `theCGMC`,
  `theVPSDto`, `Fillout`, `backto`, `LNUIGO`, and the
  `BUR Sinthe'Utilization'columnoftheRBUD` run. **Count now 0.**
- **Acronym over-splitting**: the rule split `CGMCreleasinglogbook` into
  "CGM Creleasinglogbook". Its second half is now length-bounded, and both
  spellings are repaired explicitly.
- **Step numbers stranded in the Responsibility cell**: the source writes
  "Student<br>1.", so FAM 6.01 4.4 read "| Student 1. | Pays ... |" and every
  role in the table looked like a different person.
  `_move_stranded_step_numbers` puts the number back at the front of its step.
- **Rows wrapped across two lines**: "(see FAM" / "9.02 Receiving of
  Deliveries)" and "List of Scholars/" / "Grantees per Scholarship Grant" were
  each one step split by the PDF's line wrapping. `_join_wrapped_rows` merges
  them, and is off entirely in tables with no step numbers, so the bank and
  calendar tables are untouched.
- A **final glue pass** runs over the assembled text, because the per-fragment
  repair happens before a cell's line breaks are joined.
- `_render_table` now collapses its own doubled spaces, so re-cleaning stored
  content is a no-op. It reported 41 changed sections when 17 had changed.

New command **`api/management/commands/reextract_manuals.py`** re-extracts from
the master-copy files and updates sections **in place**, matched by section
number. The previous re-extraction used a script that was never committed.
203 sections matched, 0 unmatched, nothing deleted; 2 revisions and 3 history
rows still attached. Backups: `db.sqlite3.bak-2026-09-17-glue`,
`db.sqlite3.bak-2026-09-17-cp4fixes`.

### 9. Sensitive data

- Bank account numbers are replaced in the dataset with the fixed placeholder
  `0000-0000-00` (`build_dataset.redact`). 14 distinct numbers in the corpus, 21
  examples carry the placeholder, none survive unredacted. The pattern requires
  two or more hyphens so a year range like "2016-2017" is left alone.
- `CHECKPOINT4_REVIEW.html` is gitignored.
- **The repository is public and the master copies are already in it.** See
  "Known issues" below.

### Decisions applied

- **Rule-hard**: verdict disagreement accepted as the measure, re-measured
  below.
- **Negation**: `config.SENSE_REVERSALS` added (21 pairs), detected on matched
  units, reported under `negation_changed` with the pair as evidence, and
  reported once - never also as a term swap. 32 tests in
  `tests/test_sense_and_numbers.py`.
- **`MAX_LENGTH` was set to 512** at Checkpoint 4, and **reverted to 384 on
  2026-09-17** once it emerged that the notebook had been training at 384
  all along. See "MAX_LENGTH settled at 384" below.

---

## Phase 4 — final dataset (2026-09-17, third round)

**2,811 examples, 19 documents, 25 generators.** 3,962 candidates, 143 discarded
by the gate, 510 by the strategy cap, 498 by the section-type cap.

| | |
|---|---|
| approve / needs_revision / reject | 1,002 (36%) / 661 (24%) / 1,148 (41%) |
| Procedures / Policies / Objectives / Scope | 1,441 / 1,109 / 150 / 111 |
| labels at the 150 floor | 9 of 10 (`key_term_deleted` 123) |
| borderline sentence matches | 64 |
| hard negatives | 21 |
| distinct generator strategies | 116 |
| cross-references | 161 = 16% of approvals |

### Third round of fixes

1. **Grammar gate discards** rather than rewrites: a dangling tail ("of.",
   "using."), a fragment opening ("No. 2, series of ..."), an item number lost
   from a **surviving** line, a truncated row, padded empty columns. Discards
   are reported per generator. The item-number rule had to be narrowed once:
   comparing the sets of numbers flagged every legitimate deletion, 607 of
   them, because removing a step removes its number too.
2. **Synonyms are one-directional.** The plain word is the one these manuals
   use, so "use" never becomes "utilize", "forwards" never becomes "endorses".
   `verify | check` is out of the glossary - in this register it is not a
   change of meaning. A swap can no longer land inside a named document
   ("Transcript of Record"), which needed a pattern that runs through the
   lowercase connectors rather than one that checks the immediate neighbours.
3. **Negation flips are discarded** inside an already-negative clause (which
   would produce a double negative) and where the result is a past participle
   used attributively ("disapproved policies").
4. **Role spacing** is normalised at extraction and in Layer 1, so
   "Accounting Staff -3" and "Accounting Staff-3" are one person and a spacing
   difference is never an issue. (`db.sqlite3.bak-2026-09-17-rolespacing`.)
5. **Empty Responsibility cells inherit the role above** before Layer 1
   compares units (A3). A blank cell means the same person is still working,
   not that nobody is.
6. **Cross-references** point only at sections with TF-IDF cosine similarity
   >= 0.08 (the 75th percentile of within-document similarity: median 0.042,
   p75 0.079, p90 0.120), sit at the end of a sentence, never in a table cell
   holding a value and never after a semicolon, and are capped at 15% of the
   approve class after stratification - 16% as shipped.

### Blind label audit

`scripts/export_label_audit.py` writes `label_audit.csv` (50 examples, seeded,
stratified by verdict, with the diff and empty columns to fill in) and
`label_audit_key.csv` (the labels, generator and strategy). The labels are not
in the first file, so the audit measures agreement rather than recognition.

Accepted limitations are recorded in `DATASET_CARD.md`: thin cross-section
contradictions, out-of-sequence steps only as swaps, narrow typo variety, 21
hard negatives, `key_term_deleted` below the floor.

---

## Blind label audit — result (2026-09-17)

50 examples, seeded and stratified by verdict, judged without the labels.

| | |
|---|---|
| verdict agreement | **44 / 50 = 88%** |
| issue set exact | **47 / 50 = 94%** |
| both | 44 / 50 |

Confusion: 18 approve and 18 reject agreed outright, 8 needs_revision agreed;
2 needs_revision judged approve, 2 needs_revision judged reject, 2 reject judged
needs_revision.

### The six disagreements, and what changed

| # | Generator | Disagreement | Outcome |
|---|---|---|---|
| 6, 16 | `step_reorder_dependent` | reject vs needs_revision | **Relabelled needs_revision.** A swapped sequence is a slip a reviewer sends back, not a control removed or reversed. 143 examples. |
| 22 | `non_equivalent_swap` | "any records" -> "all records" labelled an issue | **Fixed.** Widening a scope is strengthening, and strengthening is not an issue - the same rule that keeps "should" -> "shall" out. The `any -> all` direction is no longer generated. |
| 30 | `non_equivalent_swap` | "computer file" -> "computer record" labelled an issue | **Fixed.** The glossary pair separates two *verbs*. A pair whose words are noun/verb ambiguous is now only applied in verb position - the start of a step, or after a modal or conjunction. |
| 32 | `numeric_change` | "365 days or 1 year" -> "730 days or 1 year", labelled only a changed figure | **Fixed.** A figure the same unit restates another way is left alone; changing it makes the sentence contradict itself, which is a different finding. |
| 49 | `combo` | needs_revision vs reject on weights that no longer total 100% | Follows from the #32 fix: the generator no longer produces that shape. |

The auditor also flagged, without disputing the label: `acronym_expansion`
dropping an article ("by Commission on Higher Education" - **fixed**, a body's
name now takes "the"), and "settlement of any their" reaching the dataset
(**fixed**, the gate now rejects "any" before a possessive; "all their" is
still fine English and is left alone).

`verify | check` was removed from the glossary in the same pass - in this
register it is not a change of meaning. Three tests that used it as their
example of a non-equivalent swap now use `approve | review`.

---

## Phase 4 — dataset after the audit (2026-09-17)

**2,762 examples, 19 documents, 25 generators.** 3,934 candidates, 143 discarded
by the gate, 534 by the strategy cap, 495 by the section-type cap.

| | |
|---|---|
| approve / needs_revision / reject | 1,019 (37%) / 730 (26%) / 1,013 (37%) |
| Procedures / Policies / Objectives / Scope | 1,402 / 1,084 / 155 / 121 |
| labels at the 150 floor | 8 of 10 (`key_term_deleted` 126, `non_equivalent_term` 89) |
| cross-references | 166 = 16% of approvals |

The verdict mix is now within a point of the planned 40/25/35.
`non_equivalent_term` fell from 150 to 89 as the direct cost of the two audit
fixes, which was the right trade: both cut examples whose label a reviewer
disputed.

A second audit pair is exported as `label_audit_r2.csv` /
`label_audit_r2_key.csv` (the first pair is left untouched).

---

## Phase 5 — Colab training results (2026-09-17)

Five folds on a T4, about 4 minutes each. Fusion fitted on each fold's val
predictions and scored on that fold's test predictions; rules-only and
model-only scored on the same rows. Averaged over the five folds:

| System | Verdict accuracy | Verdict macro-F1 | Issue micro-F1 |
|---|---:|---:|---:|
| rules only | 0.791 | 0.788 | 0.667 |
| model only | 0.951 | 0.946 | **0.853** |
| fusion | 0.975 *(as Colab reported it)* | 0.974 | 0.695 |

**The official figure is 0.978**, not the 0.975 in this table - see "The
official figures" below. The two numbers come from the same predictions; the
difference was the fusion estimator selection, which has since been removed.

**The verdict result is what Phase 2 was for.** The rules alone get 79% of
verdicts right; Layer 2 takes that to 95%, and fusion to 97.8%. The 28%
verdict-disagreement measured on the dataset was a fair prediction of how much
work was left for the model, and the model did it.

**The issue result was a regression, and it came from Layer 3.** Layer 2 alone
scored 0.853 on issue micro-F1; fusion dropped it to 0.695 - below even the
rules. Fusion reported the **union** of the rule flags and the model's issues,
so every rule false positive was added to a set the model had right. The union
was chosen before there was anything to measure it against.

**Fixed: `ISSUE_POLICY = "rules_precise"`, and fusion now scores 0.854.**
Verdict accuracy is untouched at **0.978** - the verdict is fusion's under
every policy, only the issue set changes.

| Policy | Issue micro-F1 | Labels it never reports |
|---|---:|---|
| model | 0.853 | - |
| union (was) | 0.695 | - |
| **rules_precise** | **0.854** | - |
| agree | 0.858 | `contradicts_manual`, `out_of_scope_content` |

**`agree` has the best average and is not usable.** It can only report a label
the rules also raised, and the rules raise neither of those two - a reordered
step sequence and inserted foreign content are exactly what Layer 1 is blind to
and Layer 2 exists to catch. Per label it scores 0.000 on both. Micro-F1 does
not show this: it is dominated by the frequent labels, so a policy can silence
a fifth of the categories and still come top. Its lead also rests on one fold -
`agree` wins folds 1 and 4 and loses 0, 2 and 3.

`evaluate_folds.py` now refuses to recommend a policy that never reports a
label that appears in the truth, so this cannot be re-derived by accident.

`rules_precise` adds a rule flag only for labels the rules are precise about,
measured per fold on the validation predictions. The same three cleared the
0.90 floor in all five folds - `excessive_deletion`, `modal_weakened`,
`non_equivalent_term` - so they are pinned in `config.PRECISE_RULE_LABELS`.
Without that list the policy would have no labels to add at inference time and
would silently behave as `model`.

Per-label F1 under the chosen policy against the old union, worst first:
`numeric_changed` 0.460 -> 0.966, `responsibility_changed` 0.596 -> 0.966,
`requirement_removed` 0.637 -> 0.783, `key_term_deleted` 0.694 -> 0.782,
`negation_changed` 0.765 -> 0.951.

### The official figures: 0.978 verdict, 0.854 issues

**The official numbers are the ones in `Backend/ml/reports/fold_evaluation.md`:
verdict accuracy 0.978, issue micro-F1 0.854.** They come from the committed
code, the committed dataset and the pinned seed, over the same fold predictions
Colab produced, and can be reproduced with one command. The Colab run reported
0.975 for the verdict; that environment is not pinned anywhere.

The difference is not in the model. The fold predictions are the same files,
and Layer 1's features are recomputed deterministically from the text. What
moves is which estimator `FusionModel.train` picks: it fits logistic regression
and gradient boosting and keeps whichever validates better, and that decision
is close enough to flip between scikit-learn versions.

Forcing one estimator across all five folds:

| Fusion estimator | Per fold | Mean |
|---|---|---:|
| logistic only | 0.985, 0.946, 0.971, 0.977, 0.979 | 0.9715 |
| boosting only | 0.981, 0.985, 0.965, 0.979, 0.981 | 0.9782 |
| as selected (boost, boost, logistic, boost, boost) | | 0.9794 |

Fold 1 alone swings 4 points on that choice - 0.946 with logistic, 0.985 with
boosting. One fold selecting differently under Colab's scikit-learn accounts
for the 0.4 points exactly.

**Resolved 2026-09-18: fusion is pinned to gradient boosting.** The selection
step is gone. `FusionModel.train` fits one estimator, so the same predictions
give the same result wherever they are fitted, and the official verdict figure
is now **0.978** - the "boosting only" row above, as expected. Boosting was
kept because it was better on four of the five folds and on the average.
A result that depends on which scikit-learn fitted it is not a result. Local
scikit-learn is 1.9.0.

### The shipped Layer 3 model

Trained locally from `folds_from_drive`, on **all five folds' validation
predictions** (2,762 rows), into `Backend/ml/saved_models/context_v2/` as
`fusion.pkl` and `fusion_config.json`. That is a different object from the
per-fold models `evaluate_folds.py` fits to measure: those see one fold's val
predictions each and are thrown away.

`Backend/ml/saved_models/` is gitignored, so this is a local artefact. It has
to travel with the Layer 2 weights - a clone will not have it.

**The Kaggle archive cannot overwrite it.** The archive is built from
`context_v2/final/`, which holds Layer 2 only, so unzipping into `context_v2/`
adds `encoder/`, `tokenizer/`, `heads.pt` and `label_config.json` beside
`fusion.pkl` rather than over it. Verified by unzipping a mock archive over the
real directory: `fusion.pkl` came out byte-identical (sha256 unchanged). The
packaging cell now also refuses to write an archive containing `fusion.pkl` or
`fusion_config.json`, so it cannot start happening later.

### The issue policy was chosen on the test folds, and holds on validation too

`ISSUE_POLICY` was selected on each fold's **test** predictions, which is the
same data the reported figures come from. Checked the other way round - the
precise-label set taken from the test rows and the policies scored on the
validation rows, the mirror of what was done - the ranking is identical:

| Policy | Scored on val | Scored on test |
|---|---:|---:|
| model | 0.8534 | 0.8526 |
| union | 0.6955 | 0.6952 |
| rules_precise | **0.8546** | **0.8535** |
| agree | 0.8573 | 0.8577 |

Same order, same margins, and `agree` still unusable for the reason above. The
choice is not an artefact of which split it was measured on.

### Two faults in the Colab run

- **The final-model cell trained on the CPU.** GPU memory sat at 0.0 GB for
  thirty-plus minutes while the folds had taken four minutes each on the same
  runtime. The cell already passed `--device cuda`, the same as the fold cell,
  so the cause is not visible from the arguments. `pick_device` now refuses to
  run at all when a CUDA device is available and the run would not use it, and
  the reverse, so the next run reports the cause instead of being slow about
  it. It also prints the GPU name and per-epoch progress, flushed, since
  thirty minutes of silence reads as a hang.
- **`MAX_LENGTH` was pinned at 384 in the notebook** while `config.MAX_LENGTH`
  said 512. The folds were trained at the wrong length. The notebook now reads
  it from config, so the two cannot drift again. **The reported results above
  were produced at 384.**
- Cell 2 could not be rerun: it deleted the directory it was standing in. It
  now steps out to `/content` first and stops with a clear message if the clone
  fails, rather than letting every later cell fail for an unrelated reason.

### MAX_LENGTH settled at 384

The five folds trained at 384 because the notebook pinned it there while
`config.MAX_LENGTH` said 512. Rather than retrain, `config.MAX_LENGTH` is now
**384**, so the final model and the app run at the length the reported numbers
were measured at. The notebook reads the value from config, so the two can no
longer disagree in either direction.

What it costs: at 512 the marked change fits whole for 75% of examples, at 384
for 68%. The other 32% are not lost - `_window_around_change` keeps a window
around the markers with the head and tail of the section, so the change itself
is always in the input. It is context that is trimmed, not the edit.

The numbers in "Colab training results" above therefore describe the
configuration that is now in force. Raising `MAX_LENGTH` again invalidates
them and means retraining the folds.

---

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

### The GitHub repository is public and holds the master copies

Verified 2026-09-17 by anonymous request: `https://github.com/Doculan/DocuRoute1`
returns 200 to a request with no credentials (a non-existent repository returns
404), and `raw.githubusercontent.com` serves the files.

Already on `origin/main`:

- all **19 master-copy PDFs** under `Backend/media/mastercopies/`, pushed in
  commit `66406da` on 2026-09-13;
- two revision PDFs and one upload under `Backend/media/`;
- **`Backend/db.sqlite3`**, which holds the extracted section text - including
  the bank account numbers the dataset now redacts.

Redacting the dataset does nothing about any of this. The options are to make
the repository private, to remove the files from history and force-push, or to
decide the manuals are public documents. Note that making it private does not
retract copies already taken, and a force-push invalidates every existing
clone.

**Decided 2026-09-17: the repository stays public for now.** Eugene does not
have admin access and the repository owner is unavailable, so neither making it
private nor rewriting history is possible at the moment. This is a deferral,
not a resolution - it should be revisited when the owner is reachable.

What follows from that, for now:

- Colab clones the repository **without a token** (the prompt in cell 2 is left
  blank), which is what a public repository allows.
- `Backend/db.sqlite3` is no longer tracked as of commit `0f377fd`, so it will
  not appear in future commits - but **it is still reachable in the history**
  and served by `raw.githubusercontent.com` at earlier commits. Verified: the
  blob at `291744e` still returns 200 to an anonymous request. Untracking
  stops the bleeding; it does not undo it.
- Nothing further should be pushed while training runs.



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
