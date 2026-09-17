# Phase 5 — push, then train Layer 2 on Colab

Everything through Phase 4 is committed locally. Nothing has been pushed. This
is the order to do things in, and what each step should print if it worked.

---

## 1. Settle one thing before you push

**The repository is public, and the master copies are already in it.** Verified
by an anonymous request: `https://github.com/Doculan/DocuRoute1` returns 200
with no credentials, and `raw.githubusercontent.com` serves the files. Already
on `origin/main` since 2026-09-13:

- all 19 master-copy PDFs under `Backend/media/mastercopies/`
- two revision PDFs and one upload
- `Backend/db.sqlite3`, which holds the extracted section text including the
  bank account numbers

The dataset redacts those account numbers. That does nothing about the copies
already public, so the choice is yours and has to be made now, because **the
Colab notebook clones from GitHub** — the push has to happen before training
either way.

| Option | What it costs |
|---|---|
| Leave it public | Nothing to do. Reasonable if the manuals are public documents anyway. |
| Make the repository private | One setting. Does not retract copies already taken, and you must give Colab a token to clone (see §4, option B). |
| Strip the files from history and force-push | Invalidates your groupmate's clone and every other. Does not retract what is already out. Only worth it alongside making the repo private. |

If you make it private, the Colab clone needs a personal access token — §4
covers that.

---

## 2. Before pushing

```bash
cd Backend
../venv/Scripts/python.exe -m pytest ml/revision_pipeline/tests -q
../venv/Scripts/python.exe ml/revision_pipeline/scripts/check_repo_size.py
```

Expected: `177 passed`, and from the size check:

```
tracked files: 205, 13.6 MB in the working tree
files that probably should not be tracked: 0
commits not on origin/main: 13
```

Nothing is near GitHub's limits. The push is **about 4.3 MB over the wire**
(28 MB of files, mostly JSONL, which compresses about 7:1).

### Tell your groupmate first

Two of these commits will change files under them:

- **41 `.pyc` files are removed from tracking.** They will disappear from their
  working tree on pull and be regenerated on the next run. Harmless, but it
  looks alarming in a diff.
- **`Backend/db.sqlite3` is no longer tracked.** Git will delete it from their
  working tree on pull. **They must copy it somewhere before pulling** and put
  it back afterwards. It holds the extracted manual text and the repository is
  public, which is why it is out; it is also binary, so it could never merge.

Ask them to commit or stash their work before pulling.

---

## 3. Push

```bash
git push origin main
```

Then confirm what landed:

```bash
git log --oneline origin/main -6
```

---

## 4. Colab

Open `Backend/ml/revision_pipeline/scripts/train_on_colab.ipynb` in Colab
(**File → Open notebook → GitHub**, paste the repo URL), then
**Runtime → Change runtime type → T4 GPU**.

### Drive folders

The notebook creates these on the first run. You do not need to make them by
hand, but this is where things end up:

```
MyDrive/
└── DocuRoute/
    └── context_v2/
        ├── folds/          ← metrics and predictions per fold
        │   ├── fold_0/     ← metrics.json, val_predictions.jsonl
        │   ├── fold_1/
        │   └── ...
        └── final/
            ├── context_v2_final.zip   ← the model you bring home
            └── reports.zip
```

Results go to Drive after each fold, so a disconnected runtime costs one fold,
not the whole run. Re-running the notebook skips folds that already have a
`metrics.json` in Drive.

### Run the cells in order

| Cell | What it does | What you should see |
|---|---|---|
| 1. Mount Drive | Asks for permission | `results will be written to /content/drive/MyDrive/DocuRoute/context_v2` |
| 2. Clone | Asks for a GitHub token, then clones `main` | Leave the prompt blank if the repo is public. The token is typed with `getpass`, never stored, and is scrubbed from the clone output |
| 3. Install | transformers, datasets, accelerate, scikit-learn | A few quiet minutes |
| 4. Build the splits | Runs `make_splits.py` | Five lines, `fold 0` … `fold 4`, each naming its test documents |
| 5. Folds | Trains five models, keeps **metrics only** | `fold 0 finished in N min` five times. No weights are written to Drive — they are gigabytes and you do not need them |
| 6. Fold summary | Reads the five `metrics.json` | A table of per-fold verdict accuracy and per-label F1 |
| 7. Fusion | Per-fold evaluation, then the shipped model | A table of rules-only / model-only / fusion for each fold and averaged, written to Drive as `final/fold_evaluation.md` and `.json`; then `fusion.pkl` trained on all folds' val predictions |
| 8. Final model | Trains on **all 19 documents**, thresholds taken as the median of the five folds | `saved to ml/saved_models/context_v2/final` |
| 9. Save to Drive | Zips the final model | `NNN MB -> .../final/context_v2_final.zip` |

**If the runtime disconnects**, re-run from cell 1. Finished folds are skipped.

### The token prompt

Cell 2 always asks for a token. **Leave it blank if the repository is public.**
If it is private, create one at GitHub → Settings → Developer settings →
Personal access tokens → Fine-grained, with read access to this repository
only. It is read with `getpass`, deleted from memory after the clone, and
scrubbed out of the clone's output, so it is never written to the notebook.

---

## 5. Bring the model home

Download `MyDrive/DocuRoute/context_v2/final/context_v2_final.zip` and unzip it
so the contents sit directly in `Backend/ml/saved_models/context_v2/`:

```
Backend/ml/saved_models/context_v2/
├── encoder/            ← the fine-tuned DistilBERT
├── tokenizer/
├── heads.pt            ← verdict and issue heads
├── label_config.json   ← thresholds, label order, fingerprint
└── fusion.joblib       ← Layer 3
```

The zip contains the `final/` directory, so unzip it and move what is *inside*
`final/` up one level — the loader looks for `encoder/` directly under
`context_v2/`, not under `context_v2/final/`.

Check it loads:

```bash
cd Backend
../venv/Scripts/python.exe -c "from ml.revision_pipeline.pipeline import load_models; load_models(); print('model loads')"
```

`Backend/ml/saved_models/` is gitignored, so the weights stay out of the
repository. Your groupmate needs their own copy from Drive — send them the
folder, not a commit.

---

## 6. What to look at before wiring it into the app

- **Verdict accuracy per fold**, from the fold summary. Five documents' worth of
  variation across folds is expected; one fold far below the others usually
  means one document is unlike the rest.
- **Per-label F1 for the two thin labels**, `key_term_deleted` (126 examples)
  and `non_equivalent_term` (89). Both are below the 150 floor and will be the
  weakest.
- **Whether fusion beats Layer 1 alone**, from `final/fold_evaluation.md`. It
  scores rules-only, model-only and fusion on the same held-out test rows of
  each fold, so the three are directly comparable. Fusion is fitted on that
  fold's val predictions only - the shipped model is trained separately on all
  folds' val predictions, and is not what these numbers describe.

`DATASET_CARD.md` in `Backend/ml/datasets/context_v2/` lists what the dataset
does not cover, which is the right context for reading any of these numbers.
