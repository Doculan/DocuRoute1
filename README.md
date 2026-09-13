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

## 5. Train the ML models

The AI revision assessment needs two fine-tuned DistilBERT models. **They are not
in the repo** — each weights file is ~257 MB and GitHub rejects anything over
100 MB. You generate them locally; everything required to do so *is* committed
(`ml/datasets/`, both training scripts).

From the `Backend` directory:

```bash
py ml/train_distilbert_assessment.py
py ml/train_distilbert_issues.py
```

Each run downloads `distilbert-base-uncased` from Hugging Face, fine-tunes it on
`ml/datasets/train.csv`, and writes to `ml/saved_models/`. Expect **~20 minutes
per model on CPU**; much faster with CUDA.

Until you do this, the app runs fine — only the *AI revision assessment* button
fails, with a config-file error.

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
any accounts or test data you created. Back it up before pulling if that matters:
`cp Backend/db.sqlite3 Backend/db.sqlite3.mine`.

**Uploaded files are committed too**, under `Backend/media/mastercopies/`, so
everyone works from the same master copies.

**`ml/saved_models/` and `ml/training_checkpoints/` are gitignored** — too large
for git. Checkpoints in particular run to several GB and are only intermediate
training state; you never need them.

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
