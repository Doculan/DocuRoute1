# Deploying DocuRoute

How this system would be run on a server, and what it needs to run well.

Development and the LAN demonstration are described in `README.md`; nothing
here changes them. Everything below is reached by setting environment
variables, so moving from a laptop to a server is a configuration change
rather than a code change.

---

## 1. What runs in production

```
                 ┌────────────────────────────────────────────┐
  browser ──TLS──► nginx / Caddy                              │
                 │   ├─ /static/  ← files on disk             │
                 │   ├─ /media/   ← files on disk (protected)  │
                 │   └─ everything else ──► gunicorn/waitress │
                 │                            └─ Django       │
                 └────────────────────────────────────────────┘
                                                  │
                                       ┌──────────┴──────────┐
                                  database            model weights
                              (MySQL/Postgres)      (on the filesystem)
```

**`manage.py runserver` is not part of it.** It is single-process, reloads on
file change, serves static files itself, and is explicitly not built to face a
network. It is the right tool for development and for the LAN demonstration,
and the wrong one for anything else.

### WSGI server

`backend/wsgi.py` already exists and is the entry point.

```bash
# Linux
gunicorn backend.wsgi:application --bind 127.0.0.1:8000 \
         --workers 2 --threads 4 --timeout 120 --preload

# Windows
waitress-serve --listen=127.0.0.1:8000 --threads=8 backend.wsgi:application
```

Neither is currently in `requirements.txt` — add the one matching the target
platform.

**Worker count is governed by memory, not by CPU.** The usual advice
(`2 × cores + 1`) is wrong for this application: each worker process loads its
own copy of the assessment model, ~700 MB. See §6 before choosing a number.

`--timeout 120` matters because the first assessment in a fresh worker takes
around 14 seconds; gunicorn's 30-second default would survive that, but not
with any margin if the disk is slow. `--preload` loads the application once
before forking, so workers share what they can copy-on-write.

### Reverse proxy

Terminates TLS, serves `/static/` and `/media/` directly from disk, and
forwards the rest. Also the right place for a request size limit — revision
uploads are PDFs — and for rate limiting.

---

## 2. Configuration

All of it comes from the environment. `Backend/.env.example` is the annotated
list; copy it to `Backend/.env` and edit, or set real environment variables,
which take precedence.

| variable | default | production |
|---|---|---|
| `DJANGO_SECRET_KEY` | the development key committed in `settings.py` | **must be set** |
| `DJANGO_DEBUG` | `true` | **`false`** |
| `DJANGO_ALLOWED_HOSTS` | `*` | the real hostnames |
| `DATABASE_URL` | unset → SQLite | the server's database |
| `DJANGO_CONN_MAX_AGE` | `60` | tune to the database |

### DEBUG

`DEBUG=False` is the single most important line in this file. With `DEBUG=True`
an unhandled error returns a full traceback, local variables, and settings to
whoever triggered it, and `ALLOWED_HOSTS` is not enforced.

Turning it off has consequences that must be handled in the same change:

- Django stops serving `/static/` entirely. Run `collectstatic` and let the
  proxy serve the result, or add WhiteNoise.
- `ALLOWED_HOSTS` starts being enforced, so it must be correct or every
  request gets a 400.
- There is no error page any more — configure `LOGGING` to write somewhere
  durable, or failures become invisible.

### Secrets

The key in `settings.py` is a development key, it is in version control, and
it must not be reused. Generate one per deployment:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

`.env` is gitignored; `.env.example` is committed and holds no real values.
Rotating the secret key invalidates existing sessions and JWTs — everyone is
signed out once, which is the intended behaviour if a key is ever exposed.

### Security settings to add for HTTPS

Not enabled by default, because they break plain-HTTP local development:

```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "SAMEORIGIN"   # currently ALLOWALL for the PDF preview
```

`manage.py check --deploy` lists what is still outstanding.

Two things in the current configuration are deliberate for the demonstration
and need revisiting for a real deployment: `X_FRAME_OPTIONS = 'ALLOWALL'`
exists so PDFs can be previewed in an iframe, and `CORS_ALLOWED_ORIGINS` lists
localhost ports. With the frontend built and served as static files by the
proxy, both become unnecessary — everything is one origin.

---

## 3. Database

The `DATABASES` block reads `DATABASE_URL` first, then discrete `DB_*`
variables, then falls back to the SQLite file. No code changes when switching.

```bash
DATABASE_URL=mysql://docuroute:password@10.0.0.5:3306/docuroute
DATABASE_URL=postgres://docuroute:password@10.0.0.5:5432/docuroute
```

Percent-encode `@ : /` in passwords (`@` → `%40`).

### PostgreSQL — recommended

`pip install psycopg[binary]`. Django's best-supported backend, no encoding
traps, and `JSONField` — which `ai_trace` and `ai_issues` use — maps to native
`jsonb`.

### MySQL / MariaDB

`pip install mysqlclient`. On Windows this needs MSVC Build Tools; if that is
not available, `pymysql` with `pymysql.install_as_MySQLdb()` in
`backend/__init__.py` works.

Create the schema as `utf8mb4` — the manuals contain typographic quotes and
dashes that `utf8` (3-byte) silently mangles. The `DATABASE_URL` path sets
`charset: utf8mb4` on the connection automatically.

```sql
CREATE DATABASE docuroute CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Index length:** utf8mb4 uses 4 bytes per character against MySQL's
3072-byte index limit, capping a unique `VARCHAR` at 768 characters. Every
unique text field today is 255 or shorter, which fits. Any future unique
field longer than 768 would not.

### Moving the data

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.Permission -e admin.logentry \
    --indent 2 -o dump.json

DATABASE_URL=... python manage.py migrate
DATABASE_URL=... python manage.py loaddata dump.json
```

The excludes matter: content types and permissions are recreated by `migrate`,
and loading them again collides on unique keys. Expect the custom user model
(`api.CustomUser`) to need loading before anything referencing it; `dumpdata`
usually orders this correctly, but a failure here is the most likely problem.

**Verify after loading** — row counts per model, then a login, a revision
submission, and one assessment. SQLite accepts values that MySQL's strict mode
rejects, and a migration is where that surfaces.

---

## 4. Static and media files

```bash
cd frontend && npm run build          # → frontend/dist
cd Backend && python manage.py collectstatic --noinput
```

`STATIC_ROOT` is not currently set and must be added before `collectstatic`
will run. Serve `frontend/dist` as the site root and let the proxy forward
`/api/` and `/media/` to Django.

**Media files are uploaded manuals and revisions, and they are not public.**
Under `DEBUG=False` Django does not serve `MEDIA_ROOT`, so the proxy does —
which means access control has to be arranged deliberately (signed URLs, or an
authenticated Django view using `X-Accel-Redirect`). Serving `/media/` as
plain static files publishes every uploaded document to anyone who guesses a
filename.

**`media/proposals/` holds signed DCRs and the documents generated for
them** (phase 3). The application never hands out their media URLs: they
are downloaded through `/api/proposals/<id>/attachments/<id>/download/`,
which applies the same visibility check as the proposal. The proxy must
therefore **not** serve `/media/proposals/` at all - denying it outright
costs nothing, since nothing links to it.

Media must also survive deployments: keep `MEDIA_ROOT` on a volume outside the
code directory, and back it up. It is not in version control.

---

## 5. Model weights

**The weights are not in git and must not be.** `Backend/ml/saved_models/` is
gitignored; the Layer 2 encoder alone is a 253 MB `model.safetensors`, and a
repository carrying a few revisions of that becomes unusable.

| | |
|---|---|
| `ml/saved_models/context_v2/` | **255 MB** total |
| ├─ `model.safetensors` | 253.2 MB — the fine-tuned DistilBERT encoder |
| ├─ `heads.pt` | verdict and issue heads |
| ├─ `fusion.pkl` | 0.8 MB — Layer 3, trained locally |
| └─ `thresholds.json`, `label_config.json`, tokenizer | small |

Deliver them as a release artifact: archive the directory, publish it as a
GitHub Release asset or to object storage, and fetch it during deployment.

```bash
curl -L -o context_v2.zip "<release asset URL>"
unzip context_v2.zip -d Backend/ml/saved_models/
python Backend/ml/revision_pipeline/scripts/check_setup.py   # must print "Ready."
```

`check_setup.py` verifies each file is present, that the pipeline loads, and
that the fingerprint in `label_config.json` matches the code — proving the
weights were trained by this version of the pipeline at the same
`MAX_LENGTH`. A mismatch means the weights and the code disagree, and the
assessment would be silently wrong rather than loudly broken.

Two cautions carried over from training:

- `fusion.pkl` is trained separately and locally. Any archive built on the
  training machine must not contain it, or unpacking overwrites the shipped
  model. The Kaggle notebook refuses to package one.
- Layer 2 cannot be retrained on the target hardware — it needs a GPU. The
  weights are the only copy, so back up `context_v2/` independently of the
  repository.

If the weights are absent the application still starts and the rule layer
still answers; the response says the model is unavailable rather than
pretending. That is a degraded mode, not a working one.

---

## 6. Measured resource requirements

Measured on the development laptop — Intel i3-1215U, 6 cores / 8 threads,
7.7 GB RAM, CPU only, no GPU — using the shipped `context_v2` weights.

| | |
|---|---|
| Python + Django baseline | 56 MB |
| after importing torch | 229 MB |
| after loading the model | 476 MB |
| **steady state, serving assessments** | **~680 MB** |
| peak, three assessments at once | 740 MB |
| **cold start** (first assessment in a process) | **13.6 s** |
| warm assessment | **0.29 s** |
| two at once | 0.40 s wall |
| three at once | 0.61 s wall |

### What this means for sizing

**Budget ~700 MB per worker, plus about 200 MB for the rest of the
application.** A 2 GB server runs one worker comfortably and two at a squeeze;
4 GB runs three or four. Adding workers beyond what memory allows causes
swapping, and a swapping worker is far slower than a queued one.

The model is loaded once per **process** and shared by all threads in it —
`load_models()` caches the bundle behind a lock, so simultaneous first
requests wait for one load rather than each performing their own. Memory does
not scale with concurrent users; it scales with worker processes. This is why
threads are preferable to processes here: `--workers 2 --threads 4` serves
eight concurrent requests for 1.4 GB, while `--workers 8` would need 5.6 GB
for the same.

### Pre-warm on boot

The 13.6-second cold start is paid by whichever unlucky user sends the first
assessment to each worker. Eliminate it by loading the model at startup
instead:

```python
# backend/wsgi.py, after application = get_wsgi_application()
if os.environ.get("PREWARM_MODEL", "").lower() in ("1", "true", "yes"):
    from ml.revision_pipeline.pipeline import load_models
    load_models()
```

With `--preload`, this happens once before forking and every worker inherits
it. Without it, add a health check that hits the assessment path once per
worker after deployment. Either way the first real user sees 0.3 s, not 14 s.

---

## 7. Why SQLite was kept for development and the demonstration

A deliberate decision, not an omission, and the numbers above are the reason.

**Every write in this application is a single row held for milliseconds,
because the slow work finishes before the write begins.** The assessment
endpoint runs inference — a few hundred milliseconds — and only then issues
one `UPDATE` of four columns. PDF extraction on upload, and the SVM tagging
call on approval, likewise complete before any row is written. There is no
`ATOMIC_REQUESTS` and no long-running transaction anywhere, so no slow
operation ever holds a database lock.

Measured concurrency, three simultaneous assessments: **0.61 s wall, 740 MB
peak.** The database is not the constraint at this scale; memory and CPU are.

The configuration now also enables:

- **WAL journalling**, so readers are never blocked by a writer;
- a **20-second busy timeout**, so a writer that finds the write lock held
  waits for it;
- **immediate transactions** (`transaction_mode: IMMEDIATE`, added in Phase
  4c), so every transaction takes the write lock when it begins.

**Correction.** This section used to say the busy timeout alone meant a
colliding writer "waits its turn instead of raising `database is locked`".
It did not, for the most common kind of transaction here: one that reads
before it writes. SQLite begins such a transaction as a reader and upgrades
it at the first write; if another request has written in between, the
upgrade is refused at once and the timeout is never consulted. A real run
hit it - saving a section a moment after the reason field had saved itself
failed with `database is locked`. Immediate transactions close it: the
second writer now waits at `BEGIN` for up to the 20 seconds, as this
section always claimed. `api/tests_database.py` runs the collision through
Django's own SQLite backend with these options, and fails without them.
The cost is that two transactions no longer overlap even when one would
only have read - at this scale, milliseconds.

For the two-to-three concurrent users of the demonstration, against a 6 MB
database, this is comfortably sufficient — and it was verified rather than
assumed. Migrating to MySQL would have solved a problem that measurement
showed did not exist, while adding a driver that needs a C toolchain on
Windows and a data migration to go wrong the week of the defence.

**Where SQLite would stop being adequate**, and the move becomes worthwhile:

- more than roughly ten users writing concurrently, since SQLite serialises
  writers regardless of WAL;
- more than one application server, as SQLite cannot be shared across hosts;
- any need for replication, point-in-time recovery, or a managed backup
  service.

At that point `DATABASE_URL` is set and nothing else changes — which is the
purpose of §3.

---

## 8. Known scaling path

**The assessment is CPU-bound and synchronous, and that is the first thing
that will break under load** - and since the check moved to the staff side it
is no longer a distant concern. It used to run when a reviewer chose to press
a button; it now runs on every submission, for every staff member, plus once
more each time someone edits after checking. The per-request cost is unchanged
(0.3-0.5 s warm, ~700 MB per worker, three concurrent in 0.61 s); the arrival
rate is not. Treat the queue below as a requirement for real use rather than a
future refinement. Pre-warming likewise stops being optional: the cold start
now lands on a staff member mid-task. A worker thread running inference occupies a
core for its full duration and cannot serve anything else. At three concurrent
assessments the cost is already visible — 0.61 s against 0.29 s for one,
because six torch threads per request oversubscribe six cores. Under real
load, requests queue behind inference and unrelated pages get slow.

The fix is to stop doing it in the request:

1. **Move the assessment to a task queue.** Celery with Redis, or Django-Q for
   something lighter. `POST /ai-assessment/` enqueues a job and returns `202`
   with a task id instead of blocking.
2. **Poll from the UI.** The review screen already has a loading state per
   revision; it would poll a status endpoint, or subscribe over WebSocket, and
   render when the result arrives. The result is already persisted on the
   revision — `ai_verdict`, `ai_issues`, `ai_explanation`, `ai_trace` — so
   there is nowhere new to put it.
3. **Run workers separately from web workers.** Model memory then lives in a
   small number of dedicated worker processes, and the web tier stays light
   and can scale independently. This is also what makes a GPU worth attaching:
   one GPU worker would serve far more throughput than several CPU ones.
4. **Assess on submission rather than on demand.** Enqueuing when a revision
   is submitted means the result is usually ready before an admin opens the
   review screen, turning a wait into an instant display.

This is documented as the path, not implemented. At the current scale it would
add a broker, a worker process and a polling protocol to solve a problem that
measurement does not yet show — and the persistence and UI structure it
depends on are already in place, so it remains a contained change when the
load justifies it.

---

## 9. Checklist

```
[ ] DJANGO_SECRET_KEY set to a freshly generated value
[ ] DJANGO_DEBUG=false
[ ] DJANGO_ALLOWED_HOSTS naming the real hostnames
[ ] DATABASE_URL set; migrate and loaddata verified
[ ] STATIC_ROOT set; collectstatic run; proxy serving /static/
[ ] /media/ served with access control, on a backed-up volume
[ ] model weights unpacked; check_setup.py prints "Ready."
[ ] model pre-warmed at boot
[ ] gunicorn/waitress behind nginx/Caddy; runserver not in use
[ ] TLS terminated; secure-cookie and HSTS settings enabled
[ ] manage.py check --deploy reviewed
[ ] LOGGING configured to a durable destination
[ ] backups: database, MEDIA_ROOT, and ml/saved_models/context_v2/
```
