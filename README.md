# DocuRoute — QMS Controlled Document Management System

Django REST backend + React (Vite) frontend for managing controlled quality
manuals across the university's offices: uploading master copies, splitting
them into sections, and routing changes through the official Document Change
Request process - drafting, concurrence, signing, the IMR's decision and the
Document Custodian making them effective.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.13** | The project is developed against 3.13. Use the `py` launcher on Windows. |
| **Node.js 18+** | For the Vite frontend. |
| **Git** | |
| **Tesseract OCR** | *Optional.* Only needed if you upload **images** (`.jpg` / `.png`) as manuals. PDF and DOCX do not use it. |

There is **no** database server to install — the project uses SQLite.

---

## 2. Setting up on a new machine

**Read this if you have just cloned, or if you pulled and everything now
fails with `no such table: api_customuser`.**

`db.sqlite3` is **not** in version control. It holds the extracted text of
every manual, it is a binary file two people cannot merge, and the repository
is public. It used to be committed; when it was removed from tracking, `git
pull` deleted the local copy on machines that already had one - which is what
that error means. Nothing is broken and nothing is lost: the database is
rebuilt from the master copy PDFs, which *are* committed.

The whole sequence, from a fresh clone to a working system:

```bash
git clone https://github.com/Doculan/DocuRoute1.git
cd DocuRoute1

# Roughly 1 GB - torch and transformers are the bulk of it.
py -m pip install -r requirements.txt

cd Backend
py manage.py migrate
```

### Create an admin account

Two steps, and the second is the one people miss.

```bash
py manage.py createsuperuser
py manage.py make_admin YOUR_USERNAME
```

`createsuperuser` alone is **not enough**. It grants Django-admin access,
which is a different thing from this application's admin role: the login
endpoint refuses any account with `is_approved` false, and the admin screens
check `role == 'admin'`. A fresh superuser is `role='staff'`,
`is_approved=False`, so it can reach `/admin/` and nothing else - which looks
like a broken login rather than a missing flag. `make_admin` sets both.

### Import the manuals

```bash
py manage.py import_mastercopies
py manage.py reextract_manuals --apply
```

The first reads every PDF in `Backend/media/mastercopies/`, creates a manual
for each, splits it into sections and tags them - the same extraction the
upload screen runs, so your checkout matches everyone else's. The manuals
arrive unassigned; which series and offices they belong to is entered on the
organisation screens. Expect **19 manuals and roughly 210 sections**, and
about a minute of work.

The second cleans extraction artefacts out of the stored text. It is a dry run
without `--apply`.

`import_mastercopies --dry-run` lists what it would do; `--replace`
re-imports a manual that is already there.

### A demonstration organisation (optional)

```bash
py manage.py seed_demo_org
py manage.py seed_demo_org --clear
```

A fictional organisation - offices, manual series, and approved accounts
holding positions in them (Encoders, Heads, the IMR and the Document
Custodian), password `Office123!` - so the whole process can be shown without
entering a real organisation by hand. Everything it creates is recorded and
`--clear` removes exactly that. It refuses to run beside a real organisation.

**Fictional data only.** Do not run this on a server holding real data.

### Check it worked

```bash
py ml/revision_pipeline/scripts/check_setup.py
```

Then start both servers (section 6) and sign in. If the staff side shows no
manuals, the account holds no position in an office linked to any - see
section 3.

> **The model weights are separate.** `Backend/ml/saved_models/` is also
> gitignored, and unlike the database it cannot be rebuilt from anything in
> the repository - it needs a GPU. See section 5. Without it the app still
> runs and the rule layer still answers; it just says less.

---

## 3. Accounts and positions

Staff accounts registered through the signup page start unapproved - the
system admin approves them, and assigns positions, from **People**.

What a person can read and do follows the positions they hold. Staff see the
documents linked to their offices (as owner, concurring or reader), and only
a concurring office may propose a change; an approved account holding no
position sees nothing until it is given one.

To make an existing account the system admin:

```bash
py manage.py make_admin someone
```

---

## 4. Frontend setup

```bash
cd frontend
npm install
```

Vite proxies `/api` to `http://127.0.0.1:8000`, so the backend must be running
for anything to load. No frontend `.env` is required.

---

## 5. The revision assessment model

Check what you have first, from the `Backend` directory:

```bash
py ml/revision_pipeline/scripts/check_setup.py
```

It names anything missing and what to do about it. "Ready." means the pipeline
will run.

### Getting the model

`ml/saved_models/` is gitignored — the encoder alone is ~257 MB and GitHub
rejects anything over 100 MB. **You cannot retrain Layer 2 on a laptop**: it
needs a GPU, and the folds took about four minutes each on a Colab T4 against
hours on CPU. So the weights arrive one of two ways:

1. **Copy the folder** from whoever has it. That is the normal path.
2. **Train it** on Kaggle with `notebooks/train_final_kaggle.ipynb`. See
   `PHASE5_TRAINING.md` for the steps.

The finished directory looks like this:

```
Backend/ml/saved_models/context_v2/
├── encoder/            ← fine-tuned DistilBERT (Layer 2)
├── tokenizer/
├── heads.pt            ← verdict and issue heads
├── label_config.json   ← thresholds, label order, fingerprint
├── thresholds.json
├── fusion.pkl          ← Layer 3, trained separately
└── fusion_config.json
```

### Back it up

**This folder is not in git and cannot be rebuilt locally. If you lose it, you
are waiting on a GPU to get it back.** Copy it somewhere that is not this
checkout — an external drive, Google Drive, anywhere:

```bash
# from the repo root
cp -r Backend/ml/saved_models/context_v2 ~/docuroute-model-backup
```

Worth doing before: reinstalling, `git clean`, switching branches that touch
`.gitignore`, or letting anyone else near the folder. `fusion.pkl` is the part
people forget — it is trained from the fold predictions, not by the Kaggle
notebook, so unzipping a fresh Layer 2 over the folder does not replace it and
nothing will tell you it is gone.

Until the model is in place the app runs fine; assessment falls back to the
rule layer alone, which gets about 79% of verdicts right against 97.8% for the
full pipeline.

The SVM section classifier (`ml/svm_model.pkl`, `ml/vectorizer.pkl`) **is**
committed, so section tagging works immediately.

---

## 6. Running it

Two terminals.

**Backend** — from `Backend/`:

```bash
py manage.py runserver
```

**Frontend** — from `frontend/`:

```bash
npm run dev
```

Open **http://localhost:5173** and sign in.

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://127.0.0.1:8000/api/ |
| Django admin | http://127.0.0.1:8000/admin/ |

### On a LAN — several devices at once

> For a live demonstration, follow **`DEMO_CHECKLIST.md`** instead — the
> same steps in order, plus the pre-warm, what to check when a device
> cannot connect, and the hotspot fallback.

For a demonstration with staff and admin on separate machines. The frontend
calls the API by **relative** path, so the browser sends every request to
whichever host served the page and Vite's proxy (`vite.config.js`) forwards it
to Django. That is what makes a second device work, and it keeps everything on
one origin, so no CORS or `ALLOWED_HOSTS` change is needed.

```bash
# Backend/ — listen on every interface, not just loopback
py manage.py runserver 0.0.0.0:8000

# frontend/ — Vite prints the LAN address; host is already set in the config
npm run dev
```

Other devices open the **Network** URL Vite prints, e.g.
`http://192.168.1.14:5173`. Do not give them port 8000; everything goes
through 5173.

**Windows Firewall.** The first run prompts — allow on **Private networks**.
If the prompt is missed, from an elevated PowerShell:

```powershell
New-NetFirewallRule -DisplayName "DocuRoute demo" -Direction Inbound `
  -Protocol TCP -LocalPort 5173,8000 -Action Allow -Profile Private
```

Also confirm the Wi-Fi profile is **Private**. On a Public profile Windows
blocks inbound connections whatever the rule says.

**Pre-warm the model before anyone connects.** The first assessment in a fresh
server process spends about 14 seconds loading the encoder from disk; every
one after that takes around 0.3 s. Once the backend is up, run the AI check
on one section of a draft proposal yourself. That pays the cost before the
audience is watching. Restarting the backend resets it, so warm it again.

The model is loaded once per process and shared, so concurrent assessments do
not multiply memory — three at once peak at about 740 MB in total. On a
machine with little free RAM, close other applications first: paging is what
turns a 14-second load into a minute.

**Two roles, two browsers.** Tokens live in `localStorage`, which is per
browser profile — sign in as staff and admin in different browsers, or on
different devices.

**Campus and guest Wi-Fi often isolate clients** from each other, which blocks
this entirely and is invisible until you try it. Test on the actual network
beforehand; a phone hotspot is the usual fallback.

---

## 7. Things worth knowing

**`Backend/db.sqlite3` is no longer tracked** (it holds the extracted manual
text and the repository is public, and a binary file can never merge). If you
are pulling a change from before that, git will delete your copy — back it up
first: `cp Backend/db.sqlite3 Backend/db.sqlite3.mine`.

**Uploaded files are committed too**, under `Backend/media/mastercopies/`, so
everyone works from the same master copies.

**`ml/saved_models/` and `ml/training_checkpoints/` are gitignored** — too large
for git. Checkpoints run to several GB and are only intermediate training
state; you never need them. `saved_models/context_v2/` you very much do — see
section 5 for how to back it up.

**`SECRET_KEY` is hardcoded in `Backend/backend/settings.py` and `DEBUG = True`.**
Fine for coursework, but this must move to an environment variable before the
project is ever deployed anywhere public.

---

## 7b. Deploying it

`runserver` is for development and the demonstration. `DEPLOYMENT.md` covers
the production stack (WSGI server behind a reverse proxy), the environment
variables for secrets, hosts and the database, how the model weights are
delivered outside git, the measured memory and timing requirements, and why
SQLite was kept for development.

Configuration lives in the environment — see `Backend/.env.example`. Every
default matches how the project already runs, so an absent `.env` changes
nothing.

---

## 8. The assessment pipeline and its figures

Every proposed section is checked by the four-layer pipeline in
`ml/revision_pipeline`. The check is advisory: it is stored with the section
change and shown to everyone who reads the proposal, and it never decides
anything. Without the Layer 2 weights the pipeline runs rules-only and says
so (`check_setup.py` reports it).

*The previous system used two older DistilBERT models (an assessment model and
an issue model) behind a `v1`/`v2` setting. Nothing used them once proposals
replaced single-section revisions, and they were removed in v4.1.0; they
remain in the `v3.0.0` tag.*

The pipeline on the five cross-validation folds: **97.8% verdict accuracy** against 79.1%
for the rule layer alone, and **0.854 issue micro-F1** — each the mean of the
five per-fold scores.

The rule layer's 79.1% is measured with the clause 6.3 change-reason check
excluded, because the ablation asks what is decidable from the textual change
and that check examines metadata instead — in the live system it fires at the
API, before any assessment. Scored with it against the corpus's generated
placeholder reasons the figure is 73.0%. `EVALUATION.md` §2 states all three
figures and why.

`Backend/ml/reports/EVALUATION.md` is the full write-up, including what those
numbers do and do not support; `Backend/ml/reports/fold_evaluation.md` is the
raw table.

## 9. Rebuilding the pipeline's data

From `Backend`, in this order. None of it is needed to run the app — the
dataset and entity lists are committed.

```bash
# entity lists, after the manuals change
py ml/revision_pipeline/scripts/build_entities_draft.py
py ml/revision_pipeline/scripts/clean_entities.py

# the training dataset (~25 minutes)
py ml/revision_pipeline/scripts/build_dataset.py

# per-fold splits, for cross-validation
py ml/revision_pipeline/scripts/make_splits.py

# Layer 3, from fold predictions produced by training
py ml/revision_pipeline/scripts/train_fusion.py \
    --predictions-dir <folds> --split val \
    --out-dir ml/saved_models/context_v2

# how good is it
py ml/revision_pipeline/scripts/evaluate_folds.py \
    --predictions-dir <folds> --out-dir ml/reports
```

Layer 2 is trained on a GPU, not here — see section 5.

## 10. Useful commands

Is this checkout ready to assess anything:

```bash
py ml/revision_pipeline/scripts/check_setup.py
```

Tests, from `Backend`:

```bash
py -m pytest ml/revision_pipeline/tests -q
```

What a push would carry:

```bash
py ml/revision_pipeline/scripts/check_repo_size.py
```

Re-clean stored section text after an extraction change (dry run by default):

```bash
py manage.py clean_section_content          # report only
py manage.py clean_section_content --apply  # write changes
```

Frontend checks:

```bash
npm run lint
npm run build
```
