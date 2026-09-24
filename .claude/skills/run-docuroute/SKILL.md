---
name: run-docuroute
description: Launch DocuRoute (Django backend + Vite frontend) against a scratch copy of the database and drive it in headless Chrome to see a change working in the real app - sign in, click through, upload files, take screenshots, check the console. Use when asked to run, start, screenshot or verify the app, never against the live database.
---

# Running DocuRoute and driving it

Verified on Windows 11 (Git Bash + PowerShell), Chrome 153, Node 24, the
project venv. The driver is dependency-free: Node's built-in WebSocket
talks to Chrome's DevTools protocol. Nothing is installed.

**Never run against `Backend/db.sqlite3`.** Always a copy. `scratch_settings.py`
refuses the live file, and it also moves `MEDIA_ROOT`: locking a proposal
writes three documents, and a scratch run must not leave them among the
real files. It keeps the project's SQLite options (WAL, the lock timeout,
immediate transactions), so a scratch run fails only where the real app
would.

Paths below: `ROOT` is the repository, `SK` this folder, `SCRATCH` any
temporary folder of your choosing (use the session scratchpad).

## 1. A scratch database

```bash
mkdir -p "$SCRATCH/media"
cp "$ROOT/Backend/db.sqlite3" "$SCRATCH/scratch.sqlite3"     # the copy
export DOCUROUTE_SCRATCH_DB="$SCRATCH/scratch.sqlite3"
export DOCUROUTE_SCRATCH_MEDIA="$SCRATCH/media"
cd "$ROOT/Backend"
PYTHONPATH="$SK" ../venv/Scripts/python.exe manage.py migrate --settings=scratch_settings
PYTHONPATH="$SK" ../venv/Scripts/python.exe manage.py shell --settings=scratch_settings \
  -c "exec(open(r'$SK/seed_scratch.py', encoding='utf-8').read())"
```

The seed turns the switch on and leaves one proposal on `VRF 1.01`,
locked and awaiting signature, with its documents generated. Accounts,
all with password `Verify-scratch-pass!`: `verify_enc` (Encoder),
`verify_head` (Head), `verify_bud_head` (the concurring Head),
`verify_admin` (system admin), `verify_imr` and `verify_custodian` (QMS
staff holding the IMR and Document Custodian positions). Fictional
throughout.

Pipe-feeding the seed to `manage.py shell` does **not** work - the
interactive shell stops at the first blank line inside a block and runs
the rest half-way. Use `-c "exec(...)"` as above. If a seed half-ran,
start again from a fresh copy.

## 2. Three processes

Check first that 8000, 5173 and 9222 are free (PowerShell):
`Get-NetTCPConnection -State Listen | ? LocalPort -in 8000,5173,9222`

Start each in the background (the backend takes ~20 s: it loads the AI
model at import):

```bash
cd "$ROOT/Backend" && PYTHONPATH="$SK" ../venv/Scripts/python.exe manage.py \
  runserver 127.0.0.1:8000 --settings=scratch_settings --noreload
cd "$ROOT/frontend" && npx --no-install vite --port 5173 --strictPort
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new \
  --remote-debugging-port=9222 --user-data-dir="$SCRATCH/chrome-profile" \
  --window-size=1280,1000 --no-first-run --no-default-browser-check about:blank
```

Wait by polling, not sleeping:

```bash
timeout 180 bash -c 'until curl -s -o /dev/null -X POST http://127.0.0.1:8000/api/auth/login/; do sleep 2; done'
timeout 60  bash -c 'until curl -sf http://127.0.0.1:5173 >/dev/null; do sleep 1; done'
timeout 30  bash -c 'until curl -sf http://127.0.0.1:9222/json/version >/dev/null; do sleep 1; done'
```

Vite proxies `/api` to 8000 (`frontend/vite.config.js`), so the page and
the API share an origin.

## 3. Drive it

```bash
node "$SK/cdp.mjs" "$SK/drives/package-encoder.cdp" "$SCRATCH/shots"
node "$SK/cdp.mjs" "$SK/drives/package-admin.cdp"   "$SCRATCH/shots"
```

Order matters where a drive changes the request's state:

| Drive | Needs | Leaves |
|---|---|---|
| `package-encoder` | a fresh seed | ready for the IMR |
| `imr-accept` | ready for the IMR | awaiting the approving authority |
| `imr-deny` | ready for the IMR | denied |
| `denial-seen-by-office` | denied | - |
| `approval-upload` | awaiting the approving authority | with the custodian |
| `custodian-return` | with the custodian | returned (signed DCR named) |
| `office-fixes-return` | returned | with the custodian |
| `qms-reading`, `package-admin` | anything | - |
| `admin-direct-edit` | anything (edits FAM 4.01 from the copy) | - |

The seed starts at the lock. For the **whole process from a draft**, use
the demo data instead - see section 3a.

The seed leaves one request, so accepting and denying need separate
fresh copies.

Commands are listed at the top of `cdp.mjs`: `nav`, `wait`, `slowwait`
(3 minutes, for the AI check), `waitgone`, `click`, `type`, `fill`
(replaces what the field holds; a literal `\n` types a newline), `set`
(date inputs, which take no typed text), `select`, `upload`, `shot`,
`text`, `value` (an input's value), `errors`, and `? ` for an optional
step. `${NAME}` is filled from the environment - `package-encoder.cdp`
needs `SCRATCH` holding `signed-dcr.pdf`, `signed-dcr-rescan.pdf` and
`signed-pages.png` (any real PDF and PNG; the server checks they open).

**Look at the screenshots.** A run of `ok` lines proves the text appeared,
not that the page looks right.

App-specific points:

- **Navigation is `useState`, not a router** - there are no URLs to jump
  to. Always start from `/` and click through (`.nav-item`, then
  `.series-row`).
- **The portal is the server's choice** (`/api/auth/me/`), so a drive
  signs in and then waits for something only that portal has - "Requests"
  for QMS staff, "Proposals" for staff.
- **`wait` reads `innerText`, which applies CSS `text-transform`.** The
  sidebar labels are upper-cased: wait for "Requests", not "QMS Portal".
- **Sign in through the form** (`#login-username`, `#login-password`,
  `button[type=submit]`). `type` goes through real input events, which
  React's controlled inputs need; setting `.value` from script does not.
- **Uploads**: `upload <css> | <path>` uses `DOM.setFileInputFiles`, which
  fires the `change` event React listens for. Upload inputs are hidden
  (`#scan-signed_dcr`, `#scan-signed_pages`); the replace dialog's is
  `#replace-file`.
- A fresh Chrome profile starts signed out; the profile persists between
  drives, so a second drive may need `? click button | Sign out` first.

## 3a. Every path of a request, on the demo data

`drives/demo/` drives a request through the screens with the fictional
organisation `manage.py seed_demo_org` creates (demo password
`Office123!`): the Accounting Encoder and Head, the Budget and Cash
Management Heads who concur, a Budget reader, the IMR and the Document
Custodian. Each drive is one step by one person, parameterised by
`${DOC}`, `${SECTION}` and the text; `paths.sh` strings them into the
request's paths, each on its own FAM document, so all five run on one
copy:

| Path | Document | Steps |
|---|---|---|
| `effective` | FAM 6.02 | draft, submit, both concur, signed copies, IMR accepts, approving authority's DCR, custodian records a starting status and corrects it, makes the change effective, a reader opens it |
| `return` | FAM 6.03 | draft, submit, Cash concurs, Budget returns with feedback, the Encoder redrafts and checks again, resubmit, **both** concur again (Cash's first concurrence did not carry over), locked on version 2 |
| `withdraw` | FAM 6.01 | draft, submit, the Head withdraws with a reason, the same section drafted again |
| `deny` | FAM 5.01 | as far as the IMR, who denies; the requesting office and both concurring offices open it and read the reason; the same section drafted again |
| `custodian-return` | FAM 4.02 | as far as the custodian, who returns the signed DCR; the office replaces it; back with the custodian, made effective |

Start from a copy of a database that holds the demo organisation (the
live one does). Copy it with SQLite's backup, not `cp`: the live file is
in WAL mode, and `cp` can miss what is still in the WAL.

```bash
../venv/Scripts/python.exe -c "import sqlite3; s=sqlite3.connect('file:db.sqlite3?mode=ro', uri=True); d=sqlite3.connect(r'$SCRATCH/demo.sqlite3'); s.backup(d)"
export DOCUROUTE_SCRATCH_DB="$SCRATCH/demo.sqlite3" DOCUROUTE_SCRATCH_MEDIA="$SCRATCH/media"
PYTHONPATH="$SK" ../venv/Scripts/python.exe manage.py shell --settings=scratch_settings \
  -c "exec(open(r'$SK/drives/demo/prep_demo.py', encoding='utf-8').read())"
# start the three processes, then:
SK="$SK" SCRATCH="$SCRATCH" OUT="$SCRATCH/shots" \
  bash "$SK/drives/demo/paths.sh" effective return withdraw deny custodian-return
PYTHONPATH="$SK" ../venv/Scripts/python.exe manage.py shell --settings=scratch_settings \
  -c "exec(open(r'$SK/drives/demo/verify_paths.py', encoding='utf-8').read())"
```

`prep_demo.py` turns access by position on in the copy and refuses one
where any of the five documents has already been through a request - a
fresh copy for every run. `paths.sh` prints each step's `TEXT`, `VALUE`,
`FAIL` and console `ERRORS`, and stops a path at its first failure.
`verify_paths.py` then checks in the database what the screens showed -
versions, concurrences per version, holds released, text changed or not,
superseded scans and baselines - and ends `ALL PATHS CONFIRMED`.

Two things learned writing these drives:

- **Wait for the page header, not a button's absence.** A button that
  changes to "Working…" is already "gone"; `wait <status> · version`
  waits for the header to show the new status, which also proves the page
  reloaded.
- `waitgone <css> | <text>` is for proof that an action took where the
  text it leaves might already be on the page - after Concur, the Concur
  button disappearing, not "CONCURRED" appearing.

## 4. Stop

Stop only what listens on the three ports (PowerShell), never a broad
`pkill`:

```powershell
$ports = 8000,5173,9222
Get-NetTCPConnection -State Listen | ? { $ports -contains $_.LocalPort } |
  Select -Expand OwningProcess -Unique | % { Stop-Process -Id $_ -Force -Confirm:$false }
```
