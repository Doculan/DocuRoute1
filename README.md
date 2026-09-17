# DocuRoute — QMS Controlled Document Management System

Django REST backend + React (Vite) frontend for managing controlled quality
manuals: uploading master copies, splitting them into sections, and routing
staff revision proposals through admin review.

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

## 2. Backend setup

```bash
git clone https://github.com/Doculan/DocuRoute1.git
cd DocuRoute1

# Install Python dependencies (from the repo root — requirements.txt lives there)
py -m pip install -r requirements.txt
```

> The first install is large: `torch` and `transformers` pull roughly 1 GB.

Then apply migrations:

```bash
cd Backend
py manage.py migrate
```

A populated `db.sqlite3` is committed to the repo, so after cloning you already
have the manuals and departments. `migrate` is only needed if the schema has
moved on since that snapshot.

---

## 3. Create an admin account

**This is the step people get stuck on.** `createsuperuser` is not enough on its
own: the login endpoint rejects any account where `is_approved` is false, and the
admin UI is only shown when `role == 'admin'`. A fresh superuser defaults to
`role='staff'`, `is_approved=False` — so it cannot log in.

Create the user:

```bash
py manage.py createsuperuser
```

Then promote it:

```bash
py manage.py shell
```

```python
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username="YOUR_USERNAME")
u.role = "admin"
u.is_approved = True
u.save()
exit()
```

Staff accounts registered through the signup page also start unapproved — an
admin approves them from **User Management**.

Every staff account must belong to a department. Staff only ever see manuals in
their own department (`staff_list_manuals` filters on it, and revision uploads
return 403 across departments), so an account with no department, or one in an
empty department, will see nothing.

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

---

## 7. Things worth knowing

**`db.sqlite3` is committed.** Pulling overwrites your local database, including
any accounts or test data you created.

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

## 8. Useful commands

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
