# QMS CDMS — the complete guide

*QMS CDMS: Quality Management System — Controlled Document Management System.*

*Written from `WORKFLOW_AS_BUILT.md` (state at tag `v4.2.0-p3`, 26 October 2026, with the fixes made after it). Where this guide and the code disagree, the code and `WORKFLOW_AS_BUILT.md` are right. Section 20 lists what is not built yet.*

---

## Contents

1. What QMS CDMS is
2. The core ideas
3. Accounts
4. The process at a glance
5. How to — by role
6. Notifications and banners
7. Deadlines and the escalation ladder
8. Delegation and maker-checker
9. The change freeze
10. The AI check (HMRAP)
11. Rules the system enforces
12. Documents and scans
13. Technical overview
14. Setting up on a new machine
15. Running it
16. Backups, the baseline and resetting
17. Commands
18. Testing
19. Troubleshooting
20. Not built yet, limitations and open questions
21. Glossary
22. Where to find what

---

## 1. What QMS CDMS is

A **controlled-document system** for Leyte Normal University's quality manuals. It does three jobs:

1. **Reading and retrieval.** Staff open, search and read manuals every day. This is the most common use.
2. **Revision.** An office proposes a change to a document, the other offices that work with it agree, and the change goes through the university's **Document Change Request (F-QMS-001)** process until the manual is updated.
3. **Assistance.** Each changed section is read by an AI (**HMRAP**) that tells the author what the change does and why it may matter, before anyone else sees it.

QMS CDMS **routes, records, notifies, generates the documents to be signed and stores the signed scans.** It does **not** sign anything and does **not** verify signatures: signatures are on paper (no e-signature yet), and the QMS checks the scans against the physical copies.

---

## 2. The core ideas

### Offices and the hierarchy

Offices form a **tree**; an office can sit under another. Some are **approving levels** (the VPs and the President) because they sign on paper. The organisation is **data entered by the system admin**, not code, so a rename, merge or restructure is data entry. Offices are never deleted: they are renamed, moved, deactivated or merged, and past records keep the name an office had at the time.

### Series and documents

A **manual series** (e.g. *Finance and Administration Manual*) contains numbered **documents** (e.g. *FAM 6.02*). A series holds default settings its documents inherit; a document can override them.

### How an office relates to a document

| Relationship | Can read | Can propose | Must agree to others' proposals | Signs |
| --- | --- | --- | --- | --- |
| **Owner** — an approving-level office (a VP) | yes | only if also concurring | no | yes, on paper |
| **Concurring** | yes | yes | yes | no |
| **Reader** | yes | no | no | no |

The owner can also be concurring (the VP for Student Development proposes on its own manual). When the owner proposes, approval continues to the level above it, so no office approves its own change.

### People and positions

A **person** signs up with their name and is approved by the system admin, who assigns them to **positions** with start and end dates. The process names positions, never people, and generated forms print position titles only.

| Position | Form field | Does |
| --- | --- | --- |
| **Encoder** (several per office) | *Requested by* | Drafts, runs AI checks, sends to the Head, uploads scans |
| **Head** (exactly one per office; may be acting or OIC) | *Department/Unit Head* | Submits, concurs or returns for the office, withdraws |
| **IMR** | Section 3 | Accepts or denies a request; uploads the approving authority's signed DCR |
| **Document Custodian** | To/For, section 5 | Records document status, returns defective packages, makes changes effective |

The system admin configures the system and takes no part in deciding or filing requests.

### System roles and portals

The server decides the portal from the account's role: **system admin** (organisation, deadlines, announcements, freeze, review of everything), **QMS staff** (IMR and Custodian: Requests and the manuals, read-only), and **user** (office staff).

---

## 3. Accounts

This is the working organisation for the thesis deployment. Names are fictional; the manuals are the university's real master copies.

**Password for every account except `Admin`: `Office123!`** (`Admin` keeps its own).

| Username | Name | Office | Position |
| --- | --- | --- | --- |
| `Admin` | — | — | System admin |
| `QMS_Ana` | Ana Reyes | QMS Office | IMR |
| `QMS_Pedro` | Pedro Cruz | QMS Office | Document Custodian |
| `ACC_Maria` | Maria Santos | Accounting Office | Head |
| `ACC_Juan` | Juan Dela Cruz | Accounting Office | Encoder |
| `BUD_Jose` | Jose Ramos | Budget Office | Head |
| `BUD_Rosa` | Rosa Lim | Budget Office | Encoder |
| `CMO_Carlo` | Carlo Bautista | Cash Management Office | Head |
| `HRM_Liza` | Liza Mendoza | HR Management Office | Head |
| `HRM_Mateo` | Mateo Garcia | HR Management Office | Encoder |
| `GUI_Nena` | Nena Flores | Guidance Office | Head |
| `SFA_Paolo` | Paolo Villanueva | Scholarship & Financial Assistance | Head |
| `CDO_Elena` | Elena Torres | Curriculum Development Office | Head |
| `VPSD_Ramon` | Ramon Aquino | Office of the VP for Student Development | Head |
| `VPAS_Teresa` | Teresa Navarro | Office of the VP for Academic Services | Head |

| Series | Documents | Owner (signs) | Concurring offices |
| --- | --- | --- | --- |
| Finance and Administration Manual (FAM) | 10 | VP for Administration & Finance | Accounting, Budget, Cash Management |
| Human Resource Manual (HRM) | 4 | VP for Administration & Finance | HR Management Office |
| Student Development Manual (SDM) | 4 | VP for Student Development | Guidance, Scholarship & Financial Assistance, VP for Student Development |
| Academic Services Manual (ASM) | 1 | VP for Academic Services | Curriculum Development, VP for Academic Services |

The approval route is the owning VP, then the Office of the President. Check **Organisation → People and positions** if anything has been changed.

---

## 4. The process at a glance

| # | Status | Who acts | Action | Password | Moves to |
| --- | --- | --- | --- | --- | --- |
| 1 | **Draft** | Encoder or Head of a concurring office | Propose changes | yes, to start | — |
| | | Encoder | Send to Head | no | With the Head |
| | | Head | Submit for concurrence | yes | Out for concurrence (or Locked) |
| | | Head | Withdraw (reason) | yes | Withdrawn |
| 1a | **With the Head** | Head | Submit | yes | Out for concurrence (or Locked) |
| | | Head | Return to Encoder (note) | no | Draft |
| | | Encoder | Recall | no | Draft |
| 2 | **Out for concurrence** | Head of each concurring office | Concur | yes | Locked, when the last concurs and the text is unchanged |
| | | Head of each concurring office | Return with feedback | yes | Draft (new version) |
| | | Head of the requesting office | Withdraw (reason) | yes | Withdrawn |
| 3 | **Locked → Awaiting signature** | the system, on the last concurrence | — | — | Awaiting signature |
| 4 | **Awaiting signature** | Encoder or Head of the requesting office | Upload each signed copy | no; **yes to replace** | Ready for the IMR |
| 5 | **Ready for the IMR** | IMR | Accept / Deny (comments to deny) | yes | Awaiting the approving authority / Denied by the IMR |
| 6 | **Awaiting the approving authority** | IMR (or the requesting office) | Upload the signed DCR | no; **yes to replace** | With the Document Custodian |
| 7 | **With the Document Custodian** | Document Custodian | Make effective | yes | Effective |
| | | Document Custodian | Return (names defective copies) | no | Returned for package defects |
| 7a | **Returned for package defects** | whoever may upload that copy | Replace | yes, with a reason | With the Document Custodian |

**Closed:** *Effective*, *Denied by the IMR*, *Withdrawn*.

Things that hold throughout:

- A proposal covers the **whole document**; each changed section has its **own mandatory AI check**.
- **Sections are held** from the first draft until the request is effective, denied or withdrawn; nothing else can change them.
- **Edits only in Draft.** After submission the text changes only through a return or a withdrawal.
- **Participants are frozen at submission.** Later reorganisation never changes who must agree.
- **No self-approval**, and an IMR or Custodian cannot act on a request from an office where they hold a position.

---

## 5. How to — by role

*Use a separate browser profile for each account you want signed in at once; tabs in one profile share a sign-in.*

### Everyone — reading

1. **My Manuals** lists documents linked to your offices, with your relationship beside each. Recently opened is on top; series are grouped with counts.
2. **Sections** searches the text inside sections. Open a document: its header shows number, version, revision and effectivity date, and a section changed through a request shows its revision line.
3. A manual with a deadline carries a **tag** such as *Deadline upcoming 12 Nov 2026* wherever it is listed.

### Encoder — drafting

1. On a document your office concurs on, choose **Propose changes** (password to start).
2. Edit the sections you need. Write **one reason** for the whole proposal (optional note per section).
3. Press **Check with AI** on each changed section. The check is required; its advice never blocks you.
4. When every changed section is checked on its current text, press **Send to Head**.
5. If the Head returns it, the banner shows it with the Head's note. Fix it and send again. You may **Recall** it before the Head acts.

### Head — your office

- **Submit** a draft that was sent to you (password), or **Return to Encoder** with a note. A Head who drafted may submit directly.
- **Concur** or **Return with feedback** on other offices' proposals (password). A return needs feedback and may name a section.
- **Withdraw** your office's own proposal before it locks (password, reason).
- **Reviewed, no change** on a document meets a deadline without a revision (password).
- **While you are away**, name a delegate on your account page (section 8).

### Encoder or Head — the paper step

1. When the proposal locks, download the **DCR**, the **draft copy** and the **concurrence record**; print them.
2. The requester and the Head sign; **upload both signed copies**. The request moves to the IMR by itself.
3. Replacing a scan asks for a reason and the password; the old file is kept.

### IMR

1. **Requests** shows what is ready; the dashboard shows counts.
2. **Accept** or **Deny** (password). Comments are required to deny, and every office involved can read them.
3. After acceptance, the approving authority signs section 4 on paper; **upload the completed signed DCR** (the requesting office may too).

### Document Custodian

1. **Requests** shows packages waiting.
2. **Return** a defective package: tick the defective signed copies and say what is wrong (no password). The office replaces only those.
3. **Make effective** (password): record DCR section 5 (document number, version, revision, effectivity date, date updated). The locked text replaces the section text, the old text is kept in history, and the request closes. Refused for a future date, a lower revision, or a section changed since the offices saw it.

### System admin

- **Organisation:** offices, series and links, people and positions, sign-ups ("Office not listed" is assigned here).
- **Deadlines & announcements:** announcements, deadlines, types, targets, priority manuals, the **change freeze**.
- **Proposals and People** are paged and filterable.

---

## 6. Notifications and banners

Notices go to **posts**, not people. An **action** notice clears only when the thing is done, by anyone entitled to do it; an **info** notice clears when read. The person who acted is not told of their own act. The **bell** appears in every portal, with a notifications page and a **Needs your action** list on the home screens.

| Event | Who is told | Severity |
| --- | --- | --- |
| Sent to the Head | the Head (none: the office above's Head and the admin) | action |
| Returned to the Encoder | the Encoders (none: the Head) | action |
| Recalled | the Head | info |
| Submitted / resubmitted | each concurring office | Head action, Encoder info |
| Concurred | the requesting office | info |
| Returned by an office | the requesting office | action |
| Locked | the requesting office | action |
| Locked: documents coming | Heads of the approving offices (none: the admin) | info |
| Both signed copies in | the IMR | action |
| IMR accepts / denies | the requesting office (and all participants on a denial) | info |
| Signed DCR uploaded | the requesting office; the Custodian | info; action |
| Package returned | the requesting office (and the IMR if the approved DCR is named) | action |
| Returned copies all replaced | the Custodian | action |
| Made effective | the requesting office and every participant | info |
| Withdrawn | the requesting office, and concurring offices once submitted | info |
| Stalled | whoever holds the step; the requesting office | action; info |
| Post vacant (Head, IMR, Custodian) | the Head of the office above; the admin | action |

**Stall limits** (editable by the admin): with the Head 3 days; out for concurrence 7; awaiting signed copies 14; with the IMR 7; with the Custodian 10.

**Banners, top to bottom (at most two rows):**

1. **The action row, pinned.** The deadlines your offices owe (most urgent first), work returned to your office, and a change freeze in force. One line, with *Show all* to expand. **It cannot be dismissed**; it clears only when you meet the deadlines and send returned work on.
2. **The announcement row**, beneath it: the newest announcement with "n more", each dismissible per person.

---

## 7. Deadlines and the escalation ladder

The admin sets a **deadline** (title, type, due date, targets, reminder days, optional priority manuals) on offices, a branch (an office and everything beneath it), series, documents, or all offices. Types are presets (ISO 9001 surveillance and recertification, PRIME-HRM, AACCUP accreditation, SUC Leveling, CHED ISA, COA follow-up, internal audit, management review, periodic review, Citizen's Charter) plus custom ones. Three of the presets are marked *confirm with the QMS office*: internal audit, management review and Citizen's Charter.

The unit is **one office's open obligations on one deadline**; one notice names everything owed, priority manuals first. Reminder days default to 30, 14, 7, 3 and 1.

| Rung | When | Who | Severity |
| --- | --- | --- | --- |
| Reminder | each reminder day | the office's Head and Encoders | action |
| Due | the due date | the same | action |
| Overdue | from the day after | the same, plus the Head of the office above | action; info above |
| Escalated | 7 days after | the Head of the nearest approving office, the IMR and the Custodian | info |
| Weekly | from 14 days after, once each ISO week | the same as escalation | info |

- **Fallbacks:** no approving office above → the President's office; an approving office with no Head → the system admin.
- **Each rung is sent once.** A run that missed a day sends what it missed.
- **Met** by submitting a proposal that covers the obligation, or by a Head recording **Reviewed, no change** on the document (it sets the last- and next-review dates). Withdrawing the proposal that met a deadline reopens it; a denial does not.
- **Where it runs:** `run_monitoring`, normally on a schedule. A dashboard runs one capped batch itself if the scheduler has not run for 15 minutes.
- **To preview:** `run_monitoring --dry-run --as-of YYYY-MM-DD` lists what would be sent and writes nothing.

---

## 8. Delegation and maker-checker

- **Who names a delegate:** a Head on leave (on their own account page) or the system admin, with the password, for a dated period and a reason.
- **Who may be named:** a current post holder in the office, or the Head of the office above. A delegate cannot delegate further. Periods never overlap, and ending one early asks for the password.
- **During the period** the delegate holds the Head post for every Head action, works for the office, and receives the Head's notices instead.
- **The record** shows each step as the delegate's, "— Head (delegated)", with *acting for* set to the Head. Forms still print titles only.
- **Maker-checker:** a delegate may not submit, concur on or return a proposal they themselves drafted or sent to the Head.

---

## 9. The change freeze

A **freeze** protects documents during an audit. Only the system admin starts one, with a reason, an expected end and a scope: everything, selected offices, or selected series. Starting, lifting, extending and granting an exception (one manual or one proposal) each ask for the password. It stays in force until the admin lifts it; the admin is reminded if it outlasts its expected end.

| During a freeze | |
| --- | --- |
| Starting a proposal, Send to Head, Submit, Make effective | refused: "Frozen for audit until …" |
| The admin's direct edits, adding, deleting, merging or splitting sections, deleting a manual | refused; a per-manual exception lets them through |
| `reextract_manuals`, `clean_section_content`, `import_mastercopies --replace` | frozen manuals skipped, unless `--ignore-freeze` |
| Editing and checking drafts, concurring and returning, signing, scans, the IMR's decision | allowed |
| Reading | never blocked |

Overdue, escalation and weekly deadline notices **pause** for what a freeze covers and are sent on the first run after it lifts; reminders and the due day continue. Blocked buttons stay visible but disabled, saying why and until when.

---

## 10. The AI check (HMRAP)

**HMRAP** (Hybrid Multi-Layer Revision Assessment Pipeline) reads each changed section in four layers:

1. **ISO rules.** Deterministic checks tied to ISO 9001:2015 clauses 6.3, 5.3 and 7.5.3: weakened obligations, changed figures, removed or reassigned requirements, reversed meaning, size of deletion, plus advisories for spelling, mixed terms, unfinished sentences and new requirements.
2. **Context model.** A fine-tuned DistilBERT that reads the marked change and related sections of the same document.
3. **Fusion.** A gradient-boosting model combines the rules and the model, with fixed overrides.
4. **The note.** A composed, natural-language note from a wording file, using only what the earlier layers found. It is not generated by a language model.

**What users see.** A short note in flowing prose, in one voice for the **drafting office** and another for **everyone else**. It says what changed, where, why it matters, what is likely to be asked, and which ISO clause it relates to, as relevance and never as a violation. **No verdict is shown to anyone**; it is computed internally to set emphasis. The note is stored once and never regenerated, and reviewers read exactly what the drafter read.

**Rules:** the check is **mandatory and its advice never blocks submission**; the reason for the change is never an input to the model; each check is bound to a hash of its text, so editing a section clears only that section's check; without the model files the check still runs on the rules alone.

**Figures** (5-fold cross-validation, grouped by document, fold means): rules alone 79.1%, model alone 95.1%, full pipeline **97.8%** verdict agreement and **0.854** issue micro-F1. Always say it as: *agreement with generated labels on unseen documents, with label quality audited at 44 of 50*. It is not accuracy on real revisions. A known weakness is **overconfidence on harmless real edits** the training data never covered. See `MODEL_EXPLAINED.md` and `EVALUATION.md`.

---

## 11. Rules the system enforces

**The password is asked again for:**

| Area | Actions |
| --- | --- |
| Proposals | Start; submit; concur; return (by an office); withdraw |
| QMS | IMR accept or deny; make effective; record or correct a starting status |
| Scans | **Replacing** a signed copy (not the first upload) |
| Reviews | Reviewed, no change |
| People | Naming a delegate, ending one early |
| Freeze | Starting, lifting, extending, granting an exception |
| Manual content | Any direct edit; deleting a manual or section |
| Organisation | Merge, move or deactivate an office; change an owner or office links; assign or end Head, IMR or Custodian posts; deactivate a person |

**No password** for: Send to Head, Return to Encoder, Recall, editing, running a check, the first upload of a signed copy, the Custodian's return, reading.

**Other rules:** one open proposal per document per office; each office decides once per version; a lock is refused if any concurrence was given on different text; effectivity dates cannot be in the future and a revision cannot go down; making effective is all-or-nothing; direct edits to held sections are refused; AI checks are rate-limited per person and per proposal.

---

## 12. Documents and scans

**Generated at the lock, once, never regenerated:**

| Document | Contents |
| --- | --- |
| **DCR (F-QMS-001)** | Date, DCR number (`DCR-YYYY-NNN`, provisional), the requesting office, *Amend document*, the changed sections and the reason. **Position titles, never names.** Document Title, Revision Status and section 4's title are left blank. One page. |
| **Draft copy** | The new text of the changed sections in the official blank format, header left blank, pages numbered "1 of N". **Known gap: it does not yet contain the whole manual.** |
| **Concurrence record** | Each office's decision, date and position. |

No generated file carries personal metadata.

**Signed copies.** The signed DCR (requester and Head) and the signed draft copy are uploaded by the Encoder or Head of the requesting office. The DCR signed by the approving authority is uploaded by the **current IMR** (decided 11 Oct 2026; the requesting office may as a fallback). Each upload records who, when, the file, the type and the uploader's real position. PDF or image only, within a size limit; empty or corrupt files are refused. A replaced file is kept as superseded and never overwritten. Downloads go only through a signed-in view.

**The system does not verify signatures** or that the right document was uploaded.

---

## 13. Technical overview

| Part | Technology |
| --- | --- |
| Backend | Django and Django REST Framework, JWT sign-in |
| Frontend | React and Vite |
| Database | **SQLite in WAL mode, retained by decision.** Measured limits are in `DEPLOYMENT.md` |
| AI | PyTorch and Transformers (DistilBERT); scikit-learn 1.9.0 (pinned) |
| Documents | `python-docx` with the official templates |
| Time zone | Asia/Manila |

```
<project folder>/
├── CLAUDE.md, README.md, CHANGELOG.md, PROGRESS.md
├── WORKFLOW_AS_BUILT.md          the process as built
├── MODEL_EXPLAINED.md            the AI, explained
├── DEPLOYMENT.md, DEMO_CHECKLIST.md
├── Backend/
│   ├── manage.py
│   ├── db.sqlite3                NOT in git
│   ├── api/                      models, views, access rules, tests
│   ├── media/                    templates, master copies, generated files (NOT served directly)
│   └── ml/
│       ├── revision_pipeline/    HMRAP code, wording file, vocabulary
│       ├── datasets/, reports/
│       └── saved_models/context_v2/   the trained model — NOT in git
└── frontend/
```

**Not in git, copy separately:** `Backend/db.sqlite3`, `Backend/media/proposals/` and the rest of `media`, and `Backend/ml/saved_models/context_v2/` (**`fusion.pkl` is the file people lose**).

**Settings** come from environment variables (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, database settings, `PREWARM_MODEL=1`). `QMS_ALLOW_AS_OF` must **never** be set on live data.

---

## 14. Setting up on a new machine

Prerequisites: **Python 3.13**, **Node.js**, **Git**, about 2 GB of free RAM.

1. Clone the repository and open the project folder.
2. `py -m venv venv`, then `venv\Scripts\activate`, then `py -m pip install -r requirements.txt`.
3. `cd frontend`, `npm install`, `cd ..`.
4. Copy `saved_models/context_v2/` into `Backend/ml/saved_models/`.
5. **Data, choose one:**
   - **Copy yours.** Stop the backend on the source machine first (WAL keeps recent changes in side files), then copy `Backend/db.sqlite3` and `Backend/media/`. Run `manage.py migrate` from `Backend/`.
   - **Build fresh.** `manage.py migrate`, `import_mastercopies`, `seed_demo_org`. If there is no `Admin` account, `make_admin`.
6. Check: `ml\revision_pipeline\scripts\check_setup.py` should say **Ready**.

After pulling new code on any machine: `pip install -r requirements.txt`, `manage.py migrate`, restart the backend.

**Share the database, media and model through a private Drive folder only; never commit them.** The repository is public.

---

## 15. Running it

**One computer:** from `Backend/`, `..\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000`; from `frontend/`, `npm run dev`. Open the address Vite prints.

**Several devices:** they open `http://<this computer's IP>:5173`. Allow the Windows Firewall prompt on **Private** networks (the Wi-Fi profile must be Private). Campus Wi-Fi may block device-to-device traffic; test beforehand and keep a phone hotspot as the fallback (then restart Vite, because the IP changes).

**The scheduler.** Deadlines and stalls depend on `run_monitoring`. On Windows, create a **Task Scheduler** task named *QMS CDMS monitoring* that runs it every 5 minutes with the project's Python (details in `DEPLOYMENT.md`). If it has not run for 15 minutes, a dashboard load runs one capped batch.

**Before a presentation:**

- Set `PREWARM_MODEL=1`, or run one AI check first. The first check after a restart takes about 13 seconds; later ones under half a second.
- Close heavy programs; the model needs about 700 MB.
- One browser profile per account you will show.
- Show the deadline ladder with `run_monitoring --dry-run --as-of` (writes nothing).
- Follow `DEMO_CHECKLIST.md`.

---

## 16. Backups, the baseline and resetting

- **Before anything risky,** stop the backend and copy `Backend/db.sqlite3`.
- **The baseline** is a clean copy (organisation, manuals, no proposals): copy `db.sqlite3` to `db.sqlite3.baseline`, and `media/proposals` to `media/proposals.baseline`, while the backend is stopped. To reset: stop the backend, delete `db.sqlite3` (and `-wal`/`-shm`), copy the baseline back, restore `media/proposals`, restart.
- **Never commit** the baseline or the database, and **do not restore pre-v4 backups**.
- **`seed_demo_org --clear` is not a reset for manuals:** text changed by a completed proposal stays changed.
- **Keep a copy of the model folder off the laptop.**

---

## 17. Commands

Run from `Backend/` with `..\venv\Scripts\python.exe manage.py <command>`.

| Command | Does |
| --- | --- |
| `migrate` | Applies database changes. Run after every pull. |
| `import_mastercopies` | Imports the master-copy PDFs; skips duplicates by file content. |
| `seed_demo_org` / `--clear` | Creates or removes the working organisation, accounts and positions. |
| `run_monitoring` | Reminders, overdue and escalation, stalls, vacancies. `--dry-run [--as-of DATE]` previews and writes nothing. |
| `seed_scale` / `--clear` | Synthetic scale data for testing only; refuses to run on real data. |
| `reextract_manuals`, `clean_section_content` | Re-extract or clean section text; skip frozen manuals. |
| `sweep_pre_assessments` | Removes unused AI checks past retention. |
| `make_admin` | Creates or promotes a system admin. |
| `ml/revision_pipeline/scripts/check_setup.py` | Model, dataset and pipeline readiness, and the fingerprint. |
| `ml/revision_pipeline/scripts/evaluate_folds.py` | Re-scores the saved cross-validation predictions. |

---

## 18. Testing

- **During work,** run only the tests for what you changed and the modules that import it: `manage.py test api.<module>`.
- **The full suite** (`manage.py test api`, and `pytest ml/revision_pipeline/tests -q` for the pipeline) takes a long time; run it at the end of a phase and before a tag, in the background.
- **End to end through the screens:** the project's browser skill drives the real app on a copy of the database.
- A test that expects an error must assert the **reason**, and a new test should be shown to fail without the code it protects.

---

## 19. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| First AI check takes ~13 s | The model is loading. Pre-warm it. |
| "Not yet assigned to an office" | The account has no current position. The admin assigns one. |
| Accounts log each other out | Same browser profile. Use separate profiles. |
| A device cannot connect | Firewall, Public Wi-Fi profile, wrong IP, or client isolation. Try a hotspot. |
| Submit, Send to Head or Make effective is disabled | A change freeze covers it; the message says until when. |
| "A section can't be edited" | It is held by an open request; the message names it. |
| Edit refused on a submitted proposal | Edits are allowed only in Draft. Return or withdraw first. |
| No deadline reminders | `run_monitoring` is not scheduled; check the Task Scheduler task. |
| AI says the model is unavailable | `saved_models/context_v2/` is missing or incomplete. |
| Downloads fail after copying the database | `Backend/media/` was not copied with it. |
| Errors after pulling | Run `pip install -r requirements.txt`, `migrate`, and restart. |

---

## 20. Not built yet, limitations and open questions

**Not built yet (planned for v4.2):** monitoring for offices above (an office sees everything beneath it), the offices bar chart, critical-times timeline, the QMS dashboard and Monitoring, deadline-first Proposals screens, a History tab, the expanded audit block, exports, and a navigation pass. Until then, offices see their own status and the admin sees proposals through the paged Proposals list.

**Limitations to state:**

1. The AI was trained on **synthetic** data from 19 documents of one institution; the figures are agreement with generated labels.
2. It is **overconfident on harmless real edits** it never saw; the verdict is therefore hidden and used only to set emphasis.
3. **The proposal audit trail is not hash-chained.** Only the system log is. Do not call the proposal trail tamper-evident.
4. **The generated draft copy contains only the changed sections**, not the whole manual.
5. **Scanned PDFs are not supported** (no OCR); digital PDFs only.
6. No e-signatures; scans are records, not verification.
7. No router: the browser's Back button is limited and URLs are not shareable.
8. Proposals change existing sections only; adding, deleting and merging sections through proposals is future work.
9. The repository is **public** and its history holds older copies of the database, master copies and template metadata; cleaning that needs the repository owner.
10. A lock refused by `content_changed` leaves the proposal in concurrence; the fix removes the normal route to it, and moving it back to Draft automatically is future work.

**Open questions for the QMS office:** the DCR section 4 title; the DCR number format (`DCR-YYYY-NNN` is provisional); the merged QMS office's official name; what "IDS" in section 5 means; whether more than one IMR or Custodian may serve at once; whether the IMR uploading the approving authority's signed DCR matches practice; the three provisional deadline types and the 12-month review interval.

---

## 21. Glossary

| Term | Meaning |
| --- | --- |
| **DCR** | Document Change Request, form F-QMS-001 |
| **IMR** | Integrated Management Representative: accepts or denies requests |
| **Document Custodian** | Records document status and makes changes effective |
| **Concurrence** | Agreement by the other offices that work with a document |
| **Owner** | The approving-level office that signs for a series |
| **Held section** | A section inside an open request; nothing else can change it |
| **Snapshot** | The stored AI result for a section, bound to its exact text |
| **Action / info notice** | A notice that clears when the thing is done / when read |
| **Obligation** | One office's open work on one deadline |
| **Freeze** | An admin-controlled block on starting, submitting and making effective |
| **Maker-checker** | The person who drafted a proposal cannot also approve it as a stand-in |
| **HMRAP** | Hybrid Multi-Layer Revision Assessment Pipeline: the AI |

---

## 22. Where to find what

| File | For |
| --- | --- |
| `QMS_CDMS_GUIDE.md` | This guide |
| `WORKFLOW_AS_BUILT.md` | The process exactly as built, with every refusal reason |
| `MODEL_EXPLAINED.md` | The AI, for readers without an ML background |
| `Backend/ml/reports/EVALUATION.md` | Full evaluation, figures and limitations |
| `DEMO_CHECKLIST.md` | Running a presentation |
| `DEPLOYMENT.md` | Deploying beyond a laptop, and the measured SQLite limits |
| `MONITORING_UPDATE_SPEC.md` | The v4.2 monitoring plan |
| `PROGRESS.md`, `CHANGELOG.md` | Every phase, decision and change |
