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
real files.

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
`verify_admin` (system admin). Fictional throughout.

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

Commands are listed at the top of `cdp.mjs`: `nav`, `wait`, `click`,
`type`, `upload`, `shot`, `text`, `errors`, and `? ` for an optional
step. `${NAME}` is filled from the environment - `package-encoder.cdp`
needs `SCRATCH` holding `signed-dcr.pdf`, `signed-dcr-rescan.pdf` and
`signed-pages.png` (any real PDF and PNG; the server checks they open).

**Look at the screenshots.** A run of `ok` lines proves the text appeared,
not that the page looks right.

App-specific points:

- **Navigation is `useState`, not a router** - there are no URLs to jump
  to. Always start from `/` and click through (`.nav-item`, then
  `.series-row`).
- **Sign in through the form** (`#login-username`, `#login-password`,
  `button[type=submit]`). `type` goes through real input events, which
  React's controlled inputs need; setting `.value` from script does not.
- **Uploads**: `upload <css> | <path>` uses `DOM.setFileInputFiles`, which
  fires the `change` event React listens for. Upload inputs are hidden
  (`#scan-signed_dcr`, `#scan-signed_pages`); the replace dialog's is
  `#replace-file`.
- A fresh Chrome profile starts signed out; the profile persists between
  drives, so a second drive may need `? click button | Sign out` first.

## 4. Stop

Stop only what listens on the three ports (PowerShell), never a broad
`pkill`:

```powershell
$ports = 8000,5173,9222
Get-NetTCPConnection -State Listen | ? { $ports -contains $_.LocalPort } |
  Select -Expand OwningProcess -Unique | % { Stop-Process -Id $_ -Force -Confirm:$false }
```
