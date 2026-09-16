# Revision AI Overhaul — Implementation Spec for Claude Code

> Place this file in the repo root and tell Claude Code:
> **"Read REVISION_AI_OVERHAUL.md and carry it out phase by phase. Stop at every CHECKPOINT and wait for my go-ahead."**

---

## 0. Context and ground rules

**Project:** DocuRoute1, a Django REST (`Backend/`) + React/Vite (`frontend/`) QMS controlled-document system. Staff propose revisions to sections of quality manuals; admins approve or reject them. An "AI revision assessment" currently uses two fine-tuned DistilBERT models (verdict + issues) trained on single sections from `Backend/ml/datasets/train.csv`.

**Goal:** replace the assessment with a 4-layer pipeline that judges a proposed revision against ISO 9001:2015-style document-control expectations **and** the context of the whole manual, then writes a readable explanation.

**This is a research/testing build, not a deployment.**
- Priority is: the pipeline runs end to end, the models train, and we can measure whether they work.
- Do not spend time on production hardening (auth, env vars, Postgres, Docker).
- The required academic deliverable is **dataset creation/augmentation** from the stored master copies, plus evaluation.

**Environment:**
- Windows, Python 3.13, run Python with `py`. Commands run from `Backend/` unless stated.
- CPU training is the default. Every training script must accept `--device`, `--max-examples`, and `--epochs` so runs can be kept short.
- Seed everything with `42`.

**Rules for you (Claude Code):**
1. **Explore before changing.** Do not assume file or field names in this spec are exact. Where this spec names something (e.g. `ManualRevision`, `upload_revision`), locate the real one and adapt.
2. **Do not delete the existing models, scripts, or `train.csv`.** The new pipeline sits beside them behind a setting (see Phase 6), so we can compare old vs. new.
3. **`Backend/db.sqlite3` is committed to git.** Before any migration, copy it to `Backend/db.sqlite3.bak-<date>`.
4. **ISO text is copyrighted.** Never paste text from the standard. Refer to clause numbers only (e.g. "7.5.3") and write every rule description in your own words.
5. **Order of work:** build the pipeline code and model architecture first (Phases 1–3), then generate the dataset from the master copies (Phase 4), then train and evaluate (Phase 5). The model code must exist before the dataset so the dataset format matches exactly what the model consumes.
6. At each **CHECKPOINT**, give a short summary: files changed, how to run, what you verified, open questions.

---

## Target layout

Create a new package; keep everything for the overhaul inside it.

```
Backend/ml/revision_pipeline/
├── __init__.py
├── config.py              # paths, label lists, thresholds, feature flag names
├── diffing.py             # line/word diffs, [DEL]/[INS] marked text
├── glossary.txt           # controlled term-equivalence list (Phase 1)
├── glossary.py            # loader + lookup
├── layer1_rules.py        # ISO control checks + change features
├── retrieval.py           # related-section retrieval within a manual
├── layer2_model.py        # multi-task DistilBERT (verdict + issues heads)
├── layer3_fusion.py       # stacking model + rule overrides
├── layer4_explain.py      # template-based explanation writer
├── pipeline.py            # assess_revision(...) → one result dict
└── scripts/
    ├── build_glossary_draft.py
    ├── build_dataset.py
    ├── train_layer2.py
    ├── train_fusion.py
    └── evaluate_pipeline.py

Backend/ml/datasets/context_v2/      # generated dataset (Phase 4)
Backend/ml/saved_models/context_v2/  # trained weights (gitignored already via saved_models/)
```

---

## Shared definitions (put these in `config.py`)

**Verdicts (single-label):**
`approve`, `needs_revision`, `reject`

**Issue labels (multi-label, fixed order):**

| Label | Meaning |
|---|---|
| `excessive_deletion` | A large share of the section's lines/words was removed |
| `key_term_deleted` | An important term (glossary or manual key term) was removed |
| `modal_weakened` | Obligation weakened: shall/must → should/may/can |
| `negation_changed` | A negation was added or removed, flipping meaning |
| `numeric_changed` | A number, duration, frequency, or date changed |
| `responsibility_changed` | A role/department/approver was removed or replaced |
| `requirement_removed` | A whole requirement sentence was removed |
| `non_equivalent_term` | A term was swapped for one the glossary marks as NOT equivalent |
| `contradicts_manual` | The revision conflicts with another section of the same manual |
| `out_of_scope_content` | Inserted text does not belong to this section/manual topic |

**Change types (Layer 1 output):**
`cosmetic`, `terminology_equivalent`, `terminology_non_equivalent`, `substantive`

**ISO clause mapping** (used by Layer 1 and Layer 4 — descriptions in our own words):

| Clause | Our check |
|---|---|
| 6.3 | Changes are planned: a reason for the change is given |
| 7.5.2 | Document has identification (code, revision no., date) and is reviewed/approved |
| 7.5.3 | Changes are identifiable, controlled, access-restricted, and prior versions retained |
| 5.3 | Roles, responsibilities, and authorities stay assigned |

---

## Phase 0 — Explore and report (no code changes)

1. Read `README.md`, `CODEBASE_ANALYSIS.md`, `Backend/api/models.py`, `Backend/api/views.py`, `Backend/api/urls.py`, everything in `Backend/ml/`, and `frontend/src/components/UploadRevision.jsx`.
2. Report:
   - The models for Manual, Section, ManualRevision (fields and relations), and where section text is stored.
   - How master copies in `Backend/media/mastercopies/` map to Manual/Section rows. Count manuals, sections per manual, and total words.
   - The current AI assessment: which view calls it, input/output format, and the columns and label values in `train.csv`.
   - How many real revisions exist in the DB and their status values.
   - Whether the known bugs still exist: missing `reviewed_by`, the UploadRevision endpoint mismatch.
3. **CHECKPOINT 0.** Stop and wait.

---

## Phase 1 — Prerequisite fixes + Layer 1 (rules)

### 1a. Prerequisite fixes
- Back up `db.sqlite3`.
- Add to the revision model (names may be adapted):
  - `reviewed_by` (FK to user, null=True)
  - `change_reason` (TextField, blank=True)
  - `ai_verdict` (CharField, blank=True)
  - `ai_issues` (JSONField, default=list)
  - `ai_explanation` (TextField, blank=True)
  - `ai_trace` (JSONField, default=dict) — full per-layer output for auditing
- Set `reviewed_by = request.user` in the review view.
- Fix `UploadRevision.jsx` to call the real upload endpoint with a section id, and add a required "Reason for change" field.
- Make and run migrations.

### 1b. `diffing.py`
- `line_diff(old, new)` and `word_diff(old, new)` using `difflib.SequenceMatcher`.
- `marked_text(old, new)` → one string with deletions and insertions wrapped: `the form is [DEL] approved [/DEL] [INS] checked [/INS] by the QMR`.
- Normalise whitespace and case before comparing; keep originals for display.

### 1c. `glossary.txt` format
One pair per line, pipe-separated, `#` for comments:
```
# term | alternative | relation
shall | must | equivalent
shall | should | not_equivalent
verify | confirm | equivalent
verify | check | not_equivalent
record | document | equivalent
approve | review | not_equivalent
```
- `scripts/build_glossary_draft.py`: extract the top TF-IDF terms and domain terms from the master copies, write `glossary_draft.txt` with `relation = UNREVIEWED`. **A human reviews it** and copies accepted lines into `glossary.txt`. Seed `glossary.txt` with ~30 obvious QMS pairs so the pipeline works immediately.
- Relations are symmetric. Unknown pairs are treated as `unknown`, not equivalent.

### 1d. `layer1_rules.py`
Function: `run_layer1(old_text, new_text, revision_meta, manual_key_terms) -> dict`

**Hard fails** (pipeline short-circuits to `reject`):
- `change_reason` empty → clause 6.3
- Submitter's department ≠ manual's department → clause 7.5.3
- New text is empty, or identical to old text

**Features** (all numeric/boolean, fixed names, passed to Layer 3):
- `deleted_line_ratio`, `deleted_word_ratio`, `inserted_word_ratio`, `sentences_removed`
- `key_terms_deleted_count` (glossary terms + manual key terms)
- `modal_weakened_count` (shall/must → should/may/can/could)
- `negation_changed` (count of added/removed: not, no, never, without, except, un-/non- prefixes on key terms)
- `numeric_changed_count` (regex for numbers, number words, durations, dates)
- `role_terms_changed_count` (role/department list from the manuals + glossary)
- `equivalent_swaps`, `non_equivalent_swaps`, `unknown_swaps`
- `change_type` (one of the four change types, one-hot encoded for Layer 3)

**Rule flags:** map features to issue labels with thresholds from `config.py` (e.g. `deleted_line_ratio > 0.4` → `excessive_deletion`). Each flag carries `{label, clause, evidence}` where evidence is the actual words involved.

**Change type logic:**
- only whitespace/punctuation/case/typo-distance ≤ 2 → `cosmetic`
- only glossary swaps, all equivalent → `terminology_equivalent`
- any non-equivalent swap and nothing else → `terminology_non_equivalent`
- otherwise → `substantive`

Write unit tests (`pytest`) for every feature with small hand-written examples.

**CHECKPOINT 1.**

---

## Phase 2 — Layer 2 (context model)

### 2a. `retrieval.py`
- Build a per-manual index of section texts.
- Default: scikit-learn TF-IDF + cosine similarity (no extra download).
- Optional flag: `sentence-transformers/all-MiniLM-L6-v2` if installed.
- `get_context(manual_id, section_id, query_text, k=3)` → parent section title + the top-k **other** sections of the same manual, concatenated, each prefixed with its section number/title.
- Cache indexes to `ml/saved_models/context_v2/retrieval/`.

### 2b. Input format (must be identical in training and inference)
- Add special tokens `[DEL]`, `[/DEL]`, `[INS]`, `[/INS]` to the tokenizer and resize embeddings.
- `text_a` = `"SECTION {number} {title}: " + marked_text(old, new)`
- `text_b` = retrieved context
- Tokenize as a pair, `max_length=384`, `truncation="only_second"` (never truncate the change itself; if `text_a` alone exceeds the limit, keep a window around the changed spans).

### 2c. `layer2_model.py`
- One `distilbert-base-uncased` encoder, two heads on the `[CLS]` vector:
  - verdict head: Linear → 3 classes, cross-entropy loss (class weights from training distribution)
  - issues head: Linear → 10 labels, BCE-with-logits loss (`pos_weight` per label)
- Total loss = `verdict_loss + λ * issues_loss`, `λ = 1.0` default, configurable.
- `predict(batch)` returns verdict probabilities and per-issue probabilities.
- Save/load with `save_pretrained`-style folder + a `heads.pt` + `label_config.json`.

### 2d. `scripts/train_layer2.py`
- Args: `--data-dir`, `--out-dir`, `--epochs 3`, `--lr 3e-5`, `--batch-size 8`, `--max-examples`, `--device`, `--seed 42`.
- Early stopping on validation macro-F1 (verdict) + micro-F1 (issues).
- After training, **tune per-issue thresholds on the validation set** and save them to `thresholds.json`.
- Log metrics per epoch to a CSV.

**CHECKPOINT 2.** (Code only; a tiny smoke-test run on ~50 dummy examples is fine to prove it trains.)

---

## Phase 3 — Layer 3 (fusion) and Layer 4 (explanation)

### 3a. `layer3_fusion.py`
- Input vector = Layer 1 features + Layer 2 verdict probabilities + Layer 2 issue probabilities.
- Model: scikit-learn `LogisticRegression` (multinomial) for the verdict. Also try `HistGradientBoostingClassifier` and keep whichever validates better; record which in `fusion_config.json`.
- **Important:** train the fusion model on Layer 2 predictions for the **validation split**, never the training split (otherwise it learns that Layer 2 is always right).
- Final issues = union of Layer 1 rule flags and Layer 2 issues above threshold, each with `source` (`rule`, `model`, or `both`), `confidence`, `severity`, `clause`, `evidence`.
- Severity weights in `config.py` (e.g. `requirement_removed` and `responsibility_changed` high, `non_equivalent_term` medium).
- **Overrides:** a Layer 1 hard fail → `reject`. Any high-severity issue flagged by both sources → at least `needs_revision`.
- Expose feature importances / coefficients in `ai_trace` so the admin can see what drove the verdict.

### 3b. `layer4_explain.py` — template writer (no generative model)
Requirements:
- **Deterministic:** same revision → same text. Seed `random.Random` with the revision id.
- **Grounded:** only mention issues, words, sections, and clauses present in the Layer 3 output. Never invent content.
- Structure: opening sentence (by verdict) → issues ordered by severity → change-type sentence → closing line addressed to the reviewer.
- Each issue label has **at least 3 phrasings**, with slots: `{section}`, `{clause}`, `{old}`, `{new}`, `{terms}`, `{ratio}`, `{hedge}`.
- Hedging by confidence: > 0.85 "clearly", > 0.65 "likely", otherwise "may".
- Connectors vary ("In addition,", "Also,", "More importantly," for high severity). Lower-case the first letter after a connector.
- Cap at ~6 sentences; if more issues exist, summarise the rest ("Two further minor issues were also noted: …").
- For `approve` with `terminology_equivalent` or `cosmetic`, say so explicitly (e.g. that the change only replaces terms with equivalent ones).
- Unit test: every issue label renders with all its phrasings, and output contains each issue's evidence text.

### 3c. `pipeline.py`
`assess_revision(revision) -> dict` runs Layers 1→4 and returns:
```json
{
  "verdict": "needs_revision",
  "confidence": 0.78,
  "change_type": "substantive",
  "issues": [{"label": "...", "source": "both", "confidence": 0.91,
              "severity": "high", "clause": "5.3", "evidence": "..."}],
  "explanation": "...",
  "trace": {"layer1": {...}, "layer2": {...}, "layer3": {...}}
}
```
Load models once (module-level cache). If Layer 2 weights are missing, run Layers 1, 3 (rules-only mode), and 4, and mark `trace.layer2 = "unavailable"` instead of crashing.

**CHECKPOINT 3.**

---

## Phase 4 — Dataset creation and augmentation (main deliverable)

Script: `scripts/build_dataset.py` (args: `--out-dir ml/datasets/context_v2`, `--per-section 12`, `--seed 42`, `--include-real`).

### 4a. Source text
- Use the section text already stored in the DB for the master copies (fall back to re-extracting from `media/mastercopies/` only if a manual has no sections).
- Clean with the existing `clean_section_content` logic. Skip sections under ~15 words.
- Split sections into sentences (simple regex splitter is fine; handle numbered items like "4.2.1").

### 4b. Generators
Each generator takes a section and returns `(old_text, new_text, verdict, issues)` or `None` if it doesn't apply. Record the generator name in every row.

**Acceptable revisions → `approve`, issues `[]`:**
- `typo_fix` — inject a typo into *old* so that *new* is the correction
- `whitespace_format` — spacing, punctuation, capitalisation
- `equivalent_synonym` — swap 1–2 terms using `equivalent` glossary pairs
- `clarifying_addition` — append a short sentence built from the section's own terms that does not change obligations (use a small set of neutral templates, e.g. "This applies to all records covered in this section.")
- `benign_reorder` — reorder two independent list items

**Needs revision → `needs_revision`:**
- `non_equivalent_swap` → `non_equivalent_term`
- `numeric_change` → `numeric_changed`
- `modal_weaken_single` → `modal_weakened`
- `partial_key_term_delete` → `key_term_deleted`

**Reject → `reject`:**
- `negation_flip` → `negation_changed` (add/remove "not", swap "at least"/"at most", "before"/"after", "include"/"exclude")
- `role_swap` → `responsibility_changed` (replace a role with a different role from the same manual, or delete the "by X" phrase)
- `requirement_drop` → `requirement_removed` (+ `excessive_deletion` if > 40% removed)
- `mass_deletion` → `excessive_deletion`, `requirement_removed`
- `foreign_insertion` → `out_of_scope_content` (insert a sentence from a **different manual**)
- `contradiction_from_context` → `contradicts_manual` (take a fact stated in a *related* section — a number, role, or duration — and write the edited section so it states a different value)
- `combo` — apply 2 of the above; verdict = the most severe; issues = union

**Severity ordering for verdicts:** `reject` > `needs_revision` > `approve`.

### 4c. Avoiding a circular dataset (important for honest evaluation)
Layer 1 rules detect several of these perturbations directly, so the model could just re-learn the rules. To make Layer 2 add real value:
- At least **40% of rejected/needs-revision examples** must come from generators rules can't reliably catch: `contradiction_from_context`, `foreign_insertion`, `negation_flip` with paraphrase (e.g. "is required" → "is optional"), and role swaps using roles absent from the glossary.
- Include **hard negatives**: acceptable edits that trip a rule (e.g. deleting a redundant duplicate sentence, or an equivalent swap that changes "shall" → "must").
- In the evaluation, report results **per generator** so it is visible which errors each layer catches.

### 4d. Real revisions
With `--include-real`, add every revision in the DB with an approved/rejected status as examples (verdict from the admin decision; issues left empty and marked `issues_labeled=false` so the issue loss ignores them). Put all of them in the **real test set only** — never in training.

### 4e. Splits and output
- **Split by manual** (group split), 70/15/15 train/val/test, so no manual's text appears in two splits. If there are fewer than 5 manuals, split by top-level section group within each manual instead, and state this limitation in the dataset card.
- Balance verdicts roughly 40% approve / 25% needs_revision / 35% reject; report the exact counts.
- Deduplicate identical `(old, new)` pairs.
- Output JSONL, one row per example:
```json
{"id": "...", "manual_id": 3, "section_id": 41, "section_number": "4.2",
 "section_title": "...", "old_text": "...", "new_text": "...",
 "context": "...", "verdict": "reject",
 "issues": ["responsibility_changed"], "issues_labeled": true,
 "generator": "role_swap", "source": "synthetic"}
```
- Files: `train.jsonl`, `val.jsonl`, `test.jsonl`, `test_real.jsonl` (if any), and `DATASET_CARD.md` containing: source manuals, generator descriptions, counts per verdict/issue/generator/split, split method, known limitations, and the seed.
- Print 3 random examples per generator for human spot-checking.

**CHECKPOINT 4.** I will spot-check samples before training.

---

## Phase 5 — Train and evaluate

1. `py ml/revision_pipeline/scripts/train_layer2.py --data-dir ml/datasets/context_v2 --out-dir ml/saved_models/context_v2`
2. `py ml/revision_pipeline/scripts/train_fusion.py` (uses the val split, see 3a)
3. `py ml/revision_pipeline/scripts/evaluate_pipeline.py` writes `ml/saved_models/context_v2/EVALUATION.md` with:
   - Verdict: accuracy, macro-F1, confusion matrix
   - Issues: per-label precision/recall/F1, micro and macro F1
   - **Ablation table** on the test set:

     | System | Verdict macro-F1 | Issues micro-F1 |
     |---|---|---|
     | Old models (current `saved_models`, if present) | | |
     | Layer 1 only (rules → verdict via fusion on rule features) | | |
     | Layer 2 only | | |
     | Layers 1 + 2 + fusion (full) | | |

   - Per-generator accuracy (shows what each layer catches)
   - Results on `test_real.jsonl` separately, if it exists
   - 10 sample explanations from Layer 4 (mix of verdicts)
   - Training time and hardware used

**CHECKPOINT 5.**

---

## Phase 6 — Wire into the app

- Add `REVISION_AI_PIPELINE = "v2"` to `settings.py` (`"v1"` keeps the old models).
- In the existing assessment view, call `pipeline.assess_revision()` when `v2`, store results in `ai_verdict`, `ai_issues`, `ai_explanation`, `ai_trace`, and return them in the API response.
- Frontend (admin review screen): show the verdict badge, the explanation paragraph, and an issue list with clause, confidence, and evidence. A collapsible "Details" panel shows `ai_trace`. Keep it simple.
- The admin's decision remains final; the AI output is advisory only. Label it that way in the UI.
- Update `README.md`: new training commands, dataset build command, how to switch v1/v2.

**CHECKPOINT 6 — done.**

---

## Definition of done
- `pytest` passes for Layers 1, 3, and 4.
- Dataset builds reproducibly from the master copies with one command, and has a dataset card.
- Layer 2 trains on CPU within a reasonable time using `--max-examples`.
- `EVALUATION.md` exists with the ablation table.
- Submitting a revision in the app shows a verdict, issues, and an explanation, and the pipeline still works (rules-only mode) when model weights are missing.

---

## Appendix A — Manual structure notes (from sample `FAM 6.02`)

A real master copy (FAM 6.02, *Monitoring of Accounts Receivables*, Finance and Administration Manual) was reviewed. Apply the following on top of the phases above. Verify each against the other master copies in Phase 0 and report any documents that differ.

### A1. Document hierarchy
- A **manual** (e.g. Finance and Administration Manual, "FAM") contains many **documents** (e.g. FAM 6.02). Each document has numbered **sections** (1.0 Objectives, 2.0 Scope, 3.0 Policies, 4.0 Procedures, 5.0 List of Forms) and **subsections** (3.1, 4.2, …).
- In Phase 0, report how the DB maps to this: is a DB "Manual" a whole manual or one document? Is a DB "Section" a 1.0-level or 1.1-level unit?
- **Revision unit:** a subsection (e.g. 3.6, 4.5). Policies 3.1–3.7 are each one sentence, so for 3.x items use the whole 3.0 block as the unit when an item is shorter than ~15 words, instead of skipping it.
- **Retrieval scope:** first the same document, then other documents in the same manual.
- **Group split:** split train/val/test by **document number** (FAM 6.02, FAM 6.03, …). This replaces "split by manual" in Phase 4e if there are only a few manuals.

### A2. Header block = ISO 7.5.2 metadata
Every page repeats a header with: version no., manual title, document no., document name, revision no., effectivity date, page no.
- Confirm the header is stripped from section text (see `HEADER_PRESERVATION_CHANGES.md`) but **stored as document metadata**.
- Layer 1 uses it for clause 7.5.2 checks: document no., revision no., and effectivity date must exist. On approval, the revision number should increment and the effectivity date should change.
- Never generate training examples from header text or page numbers.

### A3. Responsibility/Activity tables (sections 4.x)
Procedures are two-column tables. Linearise them so the role stays attached to every step:
```
[ROLE] Accounting Staff-4 [STEP] 2. Checks the ledger/account of the student using the SIAS.
[ROLE] Accounting Staff-4 [STEP] 3. Undergraduate: If the student has accountabilities ...
```
- If a role cell is empty (e.g. FAM 6.02 §4.3 step 3), inherit the role above it.
- Add `[ROLE]` and `[STEP]` as tokenizer special tokens alongside `[DEL]`/`[INS]`.
- Without this, `responsibility_changed` cannot be detected, and it is one of the most important issues in these procedures.
- Additional generators for Phase 4b:
  - `role_step_reassign` (reject): move a step to a different role from the same document.
  - `step_reorder_dependent` (reject, `contradicts_manual`): swap steps that depend on each other (e.g. signing the clearance before settling accountabilities).
  - `step_drop` (reject, `requirement_removed`): remove a control step such as a signature or verification.

### A4. Modal verbs in these manuals
The source text mixes "shall" (3.1, 3.2), "should" (3.3, 3.7), and "will"/"will not"/"will only" (3.4, 3.5) for obligations. So:
- Treat `shall`, `must`, `will`, `will not`, `will only`, `should` as **obligation modals** in this corpus.
- `modal_weakened` = obligation modal → `may`, `can`, `could`, `might`, `is encouraged to`, `is optional`.
- `should → shall` or `should → must` is a **strengthening** change: flag as `substantive` change type, not an issue.
- Do not flag `shall ↔ must ↔ will` swaps as issues; add them to `glossary.txt` as `equivalent` for this corpus.

### A5. Protected entities (extend Layer 1 regexes and key-term lists)
Changes to these must be detected as meaning changes:

| Entity type | Examples from FAM 6.02 | Issue label |
|---|---|---|
| Durations / thresholds | "365 days or 1 year", "Thirty (30) days", "over 1 year", "weekly" | `numeric_changed` |
| Word + parenthetical numbers | "Thirty (30)" — handle both parts, and flag if they disagree | `numeric_changed` |
| Roles with numeric suffixes | "Accounting Staff-4", "Accounting Staff-7", "Accounting Staff-2" | `responsibility_changed` (**not** `numeric_changed`) |
| Legal references | "Republic Act 10173", "Executive Order No. 02, series of 2016" | `numeric_changed` (evidence type `legal_reference`) |
| Systems | SIAS, eNGAS | `key_term_deleted` |
| Forms | EAF, Application for Student Records, Clearance, Promissory Note | `key_term_deleted` |
| Offices / external bodies | Cash Management Office, CHED, Accounting Office | `responsibility_changed` |
| Email addresses | the CHED contact address in §4.3 | `key_term_deleted` |
| Frequency words | weekly, monthly, immediately, timely | `numeric_changed` |

Build the role, office, system, and form lists automatically from the master copies (table role columns, acronyms in parentheses, "List of Forms" sections) and write them to `ml/revision_pipeline/entities.json` for human review.

### A6. Cross-section consistency (best source for `contradicts_manual`)
Documents repeat the same facts in different sections. Examples in FAM 6.02:
- §3.6 defines past due as over 365 days / 1 year; §4.5 steps 2–3 use "over 1 year".
- §3.4–3.5 say credentials are withheld until fees are settled; §4.1–4.2 implement that.
- §5.0 lists forms that §4.1, §4.2, and §4.4 use.
- §4.3 uses "30 days" twice.

`contradiction_from_context` should create examples like:
- changing §4.5 to "over 6 months" while §3.6 still says 1 year
- changing §3.5 to "released regardless of unpaid fees" while §4.1 still requires settlement
- deleting "Promissory Note" from §5.0 while §4.4 still uses it

Also add a Layer 1 feature `cross_ref_conflict_count`: for each changed number, role, or form in the revision, check whether the same entity appears with the old value elsewhere in the document.

### A7. Existing imperfections in master copies
The source text contains typos and stray characters (e.g. a backtick in "Responsibility`", "if which particular claim", "Complies any deficiencies", "Enrolment"/"Enrollment", a stray "." line in §4.3, and a PDF line break inside "past due already").
- Clean extraction artefacts (stray punctuation lines, broken line wraps) before generating examples.
- **Keep real typos and grammar errors** in `old_text`: correcting them is a genuine `approve` example. Add a `real_typo_fix` generator that uses these.
- Normalise spelling variants ("Enrolment"/"Enrollment") as `equivalent` in the glossary.

### A8. Dataset size (replaces the note in Phase 4)
One document like FAM 6.02 yields only about 12–15 usable revision units, so roughly 150–180 examples at `--per-section 12`.
- Target **3,000 total examples, minimum 2,000**. Compute `--per-section` automatically from the number of usable units and report the value used.
- Cap any single unit at 25 examples so no section dominates. If the cap prevents reaching the minimum, report the shortfall rather than generating near-duplicates.
- Report the number of documents and units per split in `DATASET_CARD.md`.

### A9. Corpus size and evaluation protocol (19 documents)
The system currently holds **19 master-copy documents**. Report in Phase 0 which manual each belongs to and its number of usable revision units.

**Dataset size:** with ~250 usable units, `--per-section ≈ 12` reaches the 3,000 target. Keep the A8 rules.

**Splits:** a single 70/15/15 split by document leaves only ~3 documents for validation and ~3 for testing, which makes results unstable. Use this protocol instead:

1. **Grouped 5-fold cross-validation by document** (`sklearn.model_selection.GroupKFold`, groups = document number). Each fold holds out ~4 documents as test. Within each fold's training documents, hold out 2–3 documents as validation for early stopping, threshold tuning, and training the fusion model.
2. Try to balance folds by manual and by example count; report the documents in each fold.
3. `build_dataset.py` writes one `all.jsonl` plus `folds.json` (document → fold). Also write a default single split (`train/val/test.jsonl`, using fold 0 as test) for quick runs and debugging.
4. Evaluation reports **mean ± standard deviation across the 5 folds** for every metric in the Phase 5 ablation table.
5. Runtime: Layer 1 and fusion are cheap on all 5 folds. Layer 2 training ×5 may be slow on CPU. Add `--folds` to `train_layer2.py` and `evaluate_pipeline.py` (default `all`). If a full 5-fold run is too slow, run 3 folds and state this in `EVALUATION.md`.
6. Real admin-decided revisions (`test_real.jsonl`) are evaluated with the model from whichever fold did **not** train on that revision's document.
7. Before training, print the estimated time per fold from a 20-step timing run.

---

## Phase 7 — Repository hygiene, first-time setup, and README

The team has **no Git LFS**. GitHub rejects files over 100 MB and warns over 50 MB. Trained weights (~257 MB each), checkpoints, and fold runs (can exceed 2 GB total) must never be committed. Everything needed to **regenerate** them must be committed.

### 7a. What is committed vs. ignored

| Path | Commit? | Why |
|---|---|---|
| `Backend/ml/revision_pipeline/**/*.py` | ✅ | Pipeline and scripts |
| `Backend/ml/revision_pipeline/glossary.txt`, `entities.json` | ✅ | Human-reviewed; cannot be regenerated exactly |
| `Backend/ml/revision_pipeline/glossary_draft.txt`, `entities_draft.json` | ❌ | Regenerable drafts |
| `Backend/ml/revision_pipeline/tests/` | ✅ | |
| `Backend/ml/datasets/context_v2/all.jsonl`, `folds.json`, `DATASET_CARD.md` | ✅ | The dataset is a deliverable; must stay under 50 MB (see 7c) |
| `Backend/ml/datasets/context_v2/train/val/test.jsonl` | ❌ | Regenerated from `all.jsonl` + `folds.json` by `make_splits.py` (avoids duplicating data) |
| `Backend/ml/datasets/context_v2/test_real.jsonl` | ✅ if < 5 MB | Comes from DB state that others may not have |
| `Backend/ml/reports/` (`EVALUATION.md`, metric CSVs, confusion-matrix PNGs) | ✅ | Results for the paper; small |
| `Backend/ml/saved_models/` (all of it, incl. `context_v2/`, fusion `.pkl`, `thresholds.json`, retrieval cache) | ❌ | Large or regenerated by training |
| `Backend/ml/training_checkpoints/`, `runs/`, `logs/`, `wandb/` | ❌ | Intermediate state |
| `Backend/ml/svm_model.pkl`, `vectorizer.pkl` | ✅ (unchanged) | Existing, small, already committed |
| `Backend/api/migrations/*.py` | ✅ | Needed for the new fields |
| `__pycache__/`, `*.pyc`, `.pytest_cache/` | ❌ | Also run `git rm -r --cached __pycache__` — it is currently committed at the repo root |
| `Backend/db.sqlite3.bak-*` | ❌ | Local backups |
| Hugging Face model cache | ❌ | Lives in the user profile, not the repo; never copy it in |

**Move `EVALUATION.md` and metric files** from `saved_models/context_v2/` (Phase 5) to `Backend/ml/reports/` so they can be committed while `saved_models/` stays ignored.

Add to `.gitignore` (merge with what exists; don't duplicate):
```gitignore
# --- Revision AI v2 ---
__pycache__/
*.py[cod]
.pytest_cache/
Backend/ml/saved_models/
Backend/ml/training_checkpoints/
Backend/ml/runs/
Backend/ml/logs/
Backend/ml/datasets/context_v2/train.jsonl
Backend/ml/datasets/context_v2/val.jsonl
Backend/ml/datasets/context_v2/test.jsonl
Backend/ml/datasets/context_v2/fold_*/
Backend/ml/revision_pipeline/*_draft.*
Backend/db.sqlite3.bak-*
*.safetensors
*.bin
*.pt
*.ckpt
*.onnx
```
Note: `*.pt`/`*.bin` are ignored everywhere. If any existing committed file matches, report it instead of removing it.

### 7b. Pre-commit size guard
Create `scripts/check_repo_size.py` (repo root) that:
- lists every **staged** file (`git diff --cached --name-only`) and every tracked file, with size
- **fails** (exit 1) if any file is > 50 MB, and prints a warning for > 10 MB
- warns if any staged path is under `saved_models/`, `training_checkpoints/`, or has a weights extension

Install it as a git pre-commit hook via `scripts/install_hooks.py` (copies a small hook into `.git/hooks/pre-commit`; must work on Windows with `py`). Document it in the README. The hook is opt-in per clone because `.git/hooks` is not versioned.

**Why this matters:** if a large file is committed even once, GitHub rejects the push even after the file is deleted in a later commit, and fixing it requires rewriting history. Check before committing, not after.

### 7c. Keep the dataset small
- `all.jsonl` must not store the retrieved `context` text (it is large and regenerable). Store only `section_id`/`document_no`; `make_splits.py` and the training script rebuild context via `retrieval.py`.
- Round floats, no pretty-printing, UTF-8.
- If `all.jsonl` still exceeds 40 MB, write it gzip-compressed as `all.jsonl.gz` and have loaders accept both.
- `build_dataset.py` prints the final file size.

### 7d. Setup commands
Create:
- `ml/revision_pipeline/scripts/make_splits.py` — builds `train/val/test.jsonl` (and per-fold folders if `--folds`) from `all.jsonl` + `folds.json`.
- `ml/revision_pipeline/scripts/setup_models.py` — one command that runs, in order, skipping steps whose outputs already exist unless `--force`:
  1. `make_splits.py`
  2. build retrieval indexes
  3. `train_layer2.py` (default: single split; `--cv` for all folds)
  4. `train_fusion.py`
  5. a smoke test: assess 3 sample revisions and print verdict + explanation
- `ml/revision_pipeline/scripts/check_setup.py` — prints a ✅/❌ table for: Python version, required packages, dataset files, glossary/entities, retrieval index, Layer 2 weights, thresholds, fusion model, DB migrations applied, `REVISION_AI_PIPELINE` setting. For each ❌, print the exact command that fixes it.
- **Version stamp:** `config.py` defines `PIPELINE_VERSION` and computes a hash of the label lists, special tokens, and input format. Training saves this into `label_config.json`. `check_setup.py` and `pipeline.py` warn: *"Models were trained with an older pipeline version — run `setup_models.py --force`"* when they don't match. This protects teammates who pull code changes but still have old local models.
- `dataset rebuild` is optional: the committed `all.jsonl` is the official dataset. `build_dataset.py` must be deterministic with `--seed 42` so rebuilding from the same DB gives the same file (note in the README that CPU/GPU training can still differ slightly).

### 7e. README
Create `Backend/ml/revision_pipeline/README.md` and replace **section 5 ("Train the ML models")** of the root `README.md` with a short summary that links to it. The pipeline README must cover, in this order:

1. **What it is** — the 4 layers in one diagram/paragraph; the AI is advisory only.
2. **What's in git and what isn't** — the 7a table in short form, and why (no LFS, 100 MB limit).
3. **First-time setup (fresh clone)** — copy-pasteable Windows commands:
   ```
   git clone https://github.com/Doculan/DocuRoute1.git
   cd DocuRoute1
   py -m pip install -r requirements.txt
   py scripts/install_hooks.py
   cd Backend
   py manage.py migrate
   py ml/revision_pipeline/scripts/check_setup.py
   py ml/revision_pipeline/scripts/setup_models.py
   py ml/revision_pipeline/scripts/check_setup.py
   ```
   Then the existing admin-account and run steps from the root README.
4. **After pulling changes** — back up `db.sqlite3` before pulling (existing README warning), run `migrate`, run `check_setup.py`, re-run `setup_models.py --force` if it reports a version mismatch.
5. **Expected time and disk** — measured values from Phase 5 (per model, per fold, total disk for `saved_models/`), CPU vs. CUDA.
6. **Running without trained models** — rules-only mode still works; how to switch `REVISION_AI_PIPELINE` between `v1` and `v2`.
7. **Reproducing the study** — rebuild dataset, cross-validation run (`setup_models.py --cv`), evaluation, where results land (`ml/reports/`).
8. **Editing the glossary/entities** — format, and that the models should be retrained afterwards.
9. **Before you commit** — run `py scripts/check_repo_size.py`; never add anything from `saved_models/`; what to do if a large file was committed by mistake (undo the commit **before** pushing: `git reset --soft HEAD~1`, unstage, commit again).
10. **Troubleshooting** — config-file error = models not trained; out-of-memory = lower `--batch-size`; Hugging Face download failures = check internet or set `HF_HOME`; version-mismatch warning.

### 7f. Final verification before the first push
1. Run `git status` and `py scripts/check_repo_size.py`; report staged files and total size.
2. Simulate a fresh clone: `git clone` the local repo into a temp folder, follow the README exactly (use `--max-examples 200 --epochs 1` to keep it short), and confirm `check_setup.py` ends all ✅ and the smoke test prints an explanation. Report any README step that failed and fix it.
3. **CHECKPOINT 7.** List the commits you propose (suggested split: `.gitignore` + cleanup; migrations + model fields; pipeline code + tests; dataset + card; scripts + README; reports). Do **not** push — I will push.
