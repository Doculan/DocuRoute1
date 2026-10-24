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
                               (SQLite file)        (on the filesystem)
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

### Scheduled monitoring ("QMS CDMS monitoring")

`manage.py run_monitoring` does the time-based work: proposals stalled past
their stage threshold, posts with nobody in them (and, from Phase 3,
deadline reminders and escalation). Schedule it **every 5 minutes**. It is
safe to overlap and to repeat — a second run finds the lock held and exits,
and no notice is ever sent twice — and it writes in batches of 200, each in
its own short transaction, so it does not hold the database while the site
is in use. Give it the **same environment** as the web server
(`SQLITE_PATH`, `DJANGO_SETTINGS_MODULE`), or it monitors
a different database.

Dashboards also run one batch themselves when the last finished run is
older than 15 minutes, so a stopped scheduler delays nothing anyone is
looking at — but that is a safety net, not a substitute.

**Windows — Task Scheduler.** Replace `<project folder>` with the folder
holding `Backend/` and `venv/`:

```bat
schtasks /create /tn "QMS CDMS monitoring" /sc minute /mo 5 /ru SYSTEM ^
  /tr "\"<project folder>\venv\Scripts\python.exe\" \"<project folder>\Backend\manage.py\" run_monitoring"
```

Then, in Task Scheduler → the task → Settings, set **"If the task is
already running: Do not start a new instance"**, and add the server's
environment variables to the task (or set them machine-wide).

**Linux — cron.** Same placeholder:

```cron
*/5 * * * * cd <project folder>/Backend && ../venv/bin/python manage.py run_monitoring >> /var/log/qms-cdms/monitoring.log 2>&1
```

A systemd timer works equally well. Where neither exists, a loop under the
process manager is the fallback:
`while true; do python manage.py run_monitoring; sleep 300; done`.

**Checking it.** `manage.py run_monitoring` prints what it flagged and
cleared; each run is a `JobRun` row. `manage.py verify_log system` checks
the system activity log's hash chain and names the first row that does not
follow from the one before it.

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
| `SQLITE_PATH` | `Backend/db.sqlite3` | the database file, on a backed-up volume |
| `DJANGO_CONN_MAX_AGE` | `60` | leave |

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

**SQLite is the database, by decision** (24 October 2026), at every scale
this system is built for. No move to another engine is planned or
prepared. Where a screen cannot cope at scale, the screen is redesigned —
summary first, grouping, filters, top-N, paging, precomputed summary
counts — and where a stress target still cannot be met, a smaller design
limit is set instead of a bigger database.

```bash
SQLITE_PATH=/srv/qms-cdms/data/db.sqlite3     # unset: Backend/db.sqlite3
```

Put the file on a backed-up volume, and back it up with SQLite's own
backup (`sqlite3 db.sqlite3 ".backup copy.sqlite3"` or Python's
`Connection.backup`), not a plain file copy: the database runs in WAL mode
and a copy can miss what is still in the write-ahead log. §7 has the
configuration and the measured limits.

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

## 7. SQLite: configuration and measured limits

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
assumed. The same holds at the scale targets, within the limits below.

**Measured limits on SQLite**, at the full `seed_scale` organisation (500
offices, 3,000 manuals, 7,000 proposals, ~200,000 notifications), waitress
with 8 threads:

| Load | Result |
|---|---|
| 100 people opening the bell at once | p95 0.6 s |
| 100 people marking notices read in the same instant | p50 1.6 s, p95 3.4 s, no errors |
| 50 resolving actions at once | p95 0.9 s |
| 100 bells while a full monitoring run writes | p95 1.4 s |
| First `run_monitoring` over the whole organisation (3,096 stalls) | 25–30 s, in batches |
| Bell, notifications page, Needs your action, staff home (one request) | 2–21 ms |
| My Manuals, QMS and admin Manuals, Awaiting, Involving, Requests, organisation documents: summary or one page of 50 (one request, rebuilt in v4.2 Phase 3B-2) | 5–71 ms, 1–10 queries |

SQLite serialises writers. A burst of simultaneous writes queues; it does
not fail, because transactions are immediate and wait up to the 20-second
busy timeout. The answer to a slow burst is shorter transactions and
fewer writes per request, not another engine. Phase 0's slower figures
(`MONITORING_PHASE0_REPORT.md`) were query-per-row loops, which are being
replaced screen by screen. The seven long lists were rebuilt in Phase 3B-2:
before it, QMS Manuals took 8.7 s, admin Manuals 5.9 s and the organisation's
documents 8.5 s, each with more than 9,000 queries.

Two limits are structural and accepted: one application server (SQLite
cannot be shared across hosts), and backups by file copy through the
backup API rather than replication.

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
[ ] SQLITE_PATH on a backed-up volume; migrate verified
[ ] STATIC_ROOT set; collectstatic run; proxy serving /static/
[ ] /media/ served with access control, on a backed-up volume
[ ] model weights unpacked; check_setup.py prints "Ready."
[ ] model pre-warmed at boot
[ ] gunicorn/waitress behind nginx/Caddy; runserver not in use
[ ] "QMS CDMS monitoring" scheduled every 5 minutes, same environment
[ ] manage.py verify_log system reports the chain intact
[ ] TLS terminated; secure-cookie and HSTS settings enabled
[ ] manage.py check --deploy reviewed
[ ] LOGGING configured to a durable destination
[ ] backups: database, MEDIA_ROOT, and ml/saved_models/context_v2/
```
