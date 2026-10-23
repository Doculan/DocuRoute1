# Monitoring update (v4.2) — Phase 0 report

*Survey of what exists, and measurements against `seed_scale`. Spec:
`MONITORING_UPDATE_SPEC.md` §3. 23 October 2026, at tag `v4.1.1`.*

---

## 0. What was done before the survey

- Tagged `v4.1.1` at `f37f0ed`. `CHANGELOG.md` has a `[v4.2.0] — Unreleased` entry.
- Backed up `Backend/db.sqlite3` → `db.sqlite3.bak-20261023-pre-v4.2`. `integrity_check` ok; 56 migrations recorded.
- **One migration, `0039_demorecord_source`**, needed by `seed_scale` (§9). It was tested on a copy first: 88 existing rows read as `demo_org`, and office, manual, proposal and user counts were unchanged (14 / 19 / 6 / 15). It was then applied to the live database, with the same result.

---

## 1. Announcements

**Model.** `Announcement`: title, body, `date` (nullable), `office` (one FK; null = everyone; PROTECT), `created_by`, `created_at`, `active`. `AnnouncementDismissal`: (announcement, user) unique, `dismissed_at`.

**The derived `shows_as` rule** (`views._announcement_payload`): `'upcoming' if date else 'banner'`. It is computed, not stored. The staff side applies the same rule separately:
- **Banner**: the newest undated, active, visible announcement this person has not dismissed. **Only one banner is ever shown.**
- **Upcoming**: dated items with `date >= today`, first 5, plus a total. Each drops off the day after its date.
- **Visible**: `office` null, or an office where the person holds a current post (`access.current_offices`).

**Endpoints.**

| Endpoint | Who | Does |
|---|---|---|
| `GET/POST admin/announcements/` | admin | List all (active first); create |
| `GET/PATCH/DELETE admin/announcements/<id>/` | admin | Edit; deactivate via `active`; DELETE asks for the password and really deletes |
| `POST staff/announcements/<id>/dismiss/` | any signed-in user | Dismiss for this person |
| `GET staff/dashboard/` | staff | Carries `announcement` (the one banner) and `upcoming` |
| `GET admin/dashboard/` | admin | Carries `upcoming` (5) and `system.banners_live` |

**Screens.** `admin/Announcements.jsx` is the form. It explains live that "a date makes it Upcoming, no date makes it the banner", which is the confusion the spec retires. `admin/AdminHome.jsx` has an Upcoming widget, and `staff/StaffHome.jsx` shows the banner and Upcoming. The QMS portal shows neither.

**Gaps against §6.1.**
- Targeting is one office or all. The spec needs several offices, which means a new M2M.
- There is no kind, no expiry and no style difference.
- The admin list costs two count queries per row (reach and dismissals).

**The three current rows** (all targeted to everyone, active, 0 dismissals):

| id | Title | date | Today's `shows_as` | Visible now? | Maps to |
|---|---|---|---|---|---|
| 1 | Internal quality audit, week of 6 October | 2026-09-26 | upcoming | No (past) | Announcement, expiry 2026-09-26 → expired |
| 2 | Document control refresher | 2026-09-21 | upcoming | No (past) | Announcement, expiry 2026-09-21 → expired |
| 3 | New revision workflow is live | — | banner | Yes | Announcement, no expiry → banner |

Recommendation: carry `date` over as the expiry date. That keeps what everyone sees exactly as it is today: one live banner and two finished items. Row 1 reads like an audit, but the spec says the rows become Announcements, so **no deadline is created from it**.

---

## 2. Notifications today

**Model.** `Notification(user, event → AuditEvent CASCADE, read_at, created_at)`, unique (user, event), indexed (user, read_at). The message is not stored; `notifications.message(event)` builds it when read.

**Routing** (`notifications.py`, called from `concurrence_views._record` inside the event's transaction). Recipients are every current holder at the office, Heads and Encoders alike, minus the actor. They are de-duplicated, so a person holding several posts already gets one notice.

| Event | Who is told |
|---|---|
| Submitted (including a resubmitted version) | Every concurring office |
| Concurred, returned, locked | Initiating office |
| Completed signed DCR uploaded | Initiating office + current Document Custodians |
| Everything else | Nobody |

Not notified yet (§5.3): withdrawn, scans ready for the IMR, IMR accept/deny, custodian return, made effective, all deadline, reminder, stall and vacancy events, and the Encoder↔Head steps (which don't exist yet).

**Read semantics.** Opening a proposal marks all its notices read (`mark_read(proposal_id)`). There is a "mark all read", and no `acted_at`, severity or dedupe key.

**Surfaces.**
- `GET notifications/` returns the last 20 and the unread count.
- The bell (`NotificationBell.jsx`, polls every 60 s) is mounted **only in the staff portal**. The admin and QMS portals have none.
- Derived, not notified:
  - "Awaiting my office": `proposals/awaiting/`, plus `proposals_awaiting` on the staff dashboard.
  - "Involving my office": `proposals/involving/`.
  - The QMS queue: `qms/queue/`, by status.
- Badges are shown only when non-zero.

**Structural finding for Phase 2.** A `Notification` must point at an `AuditEvent`, and an `AuditEvent` must have a **proposal**, an **actor** (PROTECT, not null) and an **office**. Deadline, reminder, escalation, vacancy and freeze notices have no proposal, and the scheduler has no actor. §5.1's model can't be added as fields alone. The notification needs its own source (a nullable event, plus a link and dedupe key), and system-generated events need a way to record "system" as the actor. I'll propose the exact shape at the start of Phase 2.

---

## 3. What `AuditEvent` records today

`proposal` (required, CASCADE) · `version` (nullable) · `event` · `actor` (PROTECT) · `position` (nullable) · `office` + `office_name_at_time` · `detail` (free text: return feedback, withdrawal reason and similar) · `at`.

Its 16 kinds: created, submitted, concurred, returned, redrafted, locked, documents_generated, scan_uploaded, scan_replaced, package_complete, imr_accepted, imr_denied, approval_uploaded, package_returned, made_effective, withdrawn.

**Not recorded** (from §10's list):
- section edited; AI check run
- sent to Head / recalled / returned to Encoder
- freeze events
- notification sent, read or acted on
- deadline linked, reminder, escalated, overdue
- reviewed with no change
- the stage moved from/to, and the time in the previous stage
- checksums of generated documents and scans (scans keep their own `Attachment` rows)

It is **append-only by convention only**. No endpoint edits it, but there is no hash chain, and deleting a proposal would cascade to its events. Printed trails are logged separately in `TrailReport`.

---

## 4. Proposals screens and the sign-up picker

**Admin Proposals (`admin/Proposals.jsx`) — a real defect.** It loads `GET admin/dashboard/` and lists `proposals` from it. That is `_recent_proposals()`, **the 6 most recently updated proposals**. Both the "In progress" and "All" tabs filter those same 6, so **the admin can never see more than six proposals**. There is no filter, search or pagination. Opening one shows `proposals/<id>/full/` read-only, with the package, QMS decisions and trail report. QMS staff have `QmsRequests.jsx` (`qms/queue/`), a work queue by status with no history.

**Staff Proposals (`staff/StaffProposals.jsx`).** One component holds the list, the editor and the detail. It has three tabs:

| Tab | Endpoint | Contents |
|---|---|---|
| From my office | `GET proposals/` | Everything the person's offices initiated, every status, unpaginated |
| Awaiting my office | `GET proposals/awaiting/` | In concurrence, my office undecided; looped in Python per proposal |
| Involving my office | `GET proposals/involving/` | Every proposal my office concurs on that is not waiting on it, including closed ones |

Every row runs `_proposal_payload`, which loads the current version and its changes and computes `_submission_blockers` twice. There is no "With Head" state: a draft goes straight to concurrence when the Head submits.

**Sign-up office picker (`Signup.jsx`).**
- A flat `<select>` over `GET auth/offices/`: every active office, alphabetical, including approving-level and QMS offices. At 500 offices it is a 500-item list.
- **"Not sure" is the empty option** (`value=""`, labelled "Not sure — let the administrator assign me"). `register` stores `requested_office = None`.
- On approval, `people_views.place_in_requested_office` has nothing to place, so the admin assigns by hand.
- The label reappears in `admin/UserManagement.jsx` (twice) and `admin/People.jsx` as "Not sure — assign an office after approving".
- Tested by `tests_signup_office.test_not_sure_leaves_it_to_the_admin`.
- There is no free-text office field today.

---

## 5. Scheduler

**None exists.** There is no Celery, APScheduler, django-q, cron config or background thread. Time-based work today is done only by hand-run management commands (e.g. `sweep_pre_assessments`). `DEPLOYMENT.md` mentions a task queue only as future work for the AI assessment.

How `run_monitoring` would run:
- **Windows (Task Scheduler)**:
  ```
  schtasks /create /tn "DocuRoute monitoring" /sc minute /mo 5 /ru SYSTEM /tr "C:\DocuRoute\venv\Scripts\python.exe C:\DocuRoute\Backend\manage.py run_monitoring"
  ```
  Set "Do not start a new instance" if one is still running, and send the log to a file. Use the same environment variables as the server (`SQLITE_PATH` / `DATABASE_URL`).
- **Server**: cron
  ```
  */5 * * * * cd /srv/docuroute/Backend && ../venv/bin/python manage.py run_monitoring >> /var/log/docuroute/monitoring.log 2>&1
  ```
  A systemd timer works equally well. A loop under the process manager (`while true; run; sleep 300`) is the fallback where cron isn't available.
- **Overlapping runs** are made safe by the database, not the scheduler: a unique `dedupe_key` on notifications plus a single-row run lock.
- **Dashboard load** also evaluates the rules opportunistically (§5.4), so a stopped scheduler delays nothing visible.

---

## 6. `seed_scale`

`py manage.py seed_scale [--fraction F] [--clear]`, in `api/management/commands/seed_scale.py`. It is separate from `seed_demo_org`.

- **Refuses** if any office, manual series, manual or proposal exists that it did not create, the demo organisation included, and says why. It refused on a copy of the live database (14 demo offices).
- **Tagged and exact.** Every row is recorded in `DemoRecord` with `source='scale'`. `--clear` removes exactly those rows, and `seed_demo_org --clear` now touches only `source='demo_org'`. Before migration `0039`, clearing the demo organisation would have deleted all scale rows and reported them as demo data; that case is now a test.
- **Contents at full scale** (53 s to seed, 90 MB SQLite):

| Rows | |
|---|---|
| Offices | 500: a President and 6 VPs (approving), 24 directorates, 468 units, 1 QMS office |
| People / assignments | 952 / 957: a Head per office, an Encoder per unit, ~3% of unit Heads vacant, a few acting concurrent Heads |
| Series / manuals / sections | 30 / 3,000 (5% override their series) / 15,000 |
| Proposals | **5,000 open**: draft 1,500 · concurrence 2,000 · locked 150 · awaiting signature 400 · ready for IMR 300 · awaiting approval 250 · with custodian 300 · package returned 100. **2,000 closed**: effective 1,400 · denied 200 · withdrawn 400 |
| Trail | 8,660 versions (25% returned once), 49,765 participants, 32,025 concurrences, 12,986 section changes, 62,909 audit events, 160,630 notifications. Back-dated up to 240 days |

- **Not seeded yet:** deadlines, because the model arrives in Phase 3, and announcements.
- `--clear` at full scale: 16 s, removing 356,643 rows and leaving only the measuring admin.
- **Tests** (`api/tests_scale_seed.py`, 7): refusal beside a real office, a real manual and the demo organisation; refusal to seed twice; every status present with an aged trail; clear removes exactly its rows; demo clear leaves scale rows. Each was run with its protecting code removed and failed:
  - demo clear without `source` scoping: deleted 5,913 rows
  - the refusal disabled: 4 tests fail
  - clear made a no-op: fails
  - auto-timestamps not suspended: fails, after I tightened a first version of that test that had passed without its code
- `tests_demo_seed` still passes.

---

## 7. Measurements on SQLite (full scale, one request at a time)

Measured in-process with Django's test client (median of 3 after a warm-up) on a scratch copy. The personas are the Head and Encoder of the busiest concurring unit, a VP Head, the IMR and the Custodian. Budgets (§9): **summary < 500 ms, list page < 800 ms**.

| Screen (endpoint) | Who | ms | Queries | Rows / size | Budget |
|---|---|---:|---:|---|---|
| Admin home **and admin Proposals** (`admin/dashboard/`) | admin | 70 | 36 | 6 proposals | ok, but shows only 6 |
| Admin Manuals (`manuals/`) | admin | **5,200–23,500** | **12,001** | 3,000, 938 KB | **missed** |
| Admin Organisation documents, full (`org/documents/`) | admin | **6,600–7,300** | **12,002** | 3,000, 1.2 MB | **missed** (the UI only calls `?unassigned=true`) |
| Admin Series (`org/series/`) | admin | 64 | 62 | 30 | ok |
| Admin Offices (`org/offices/`) | admin | 7 | 2 | 500 | ok |
| Admin People (`org/people/`) | admin | **1,014** | **1,912** | 953 | **missed** |
| Staff home (`staff/dashboard/`) | Head | 424 | 615 | — | ok alone; fails under load (below) |
| Staff home | Encoder | 356 | 615 | — | ok alone |
| Staff home | VP Head | 17 | 12 | — | ok |
| My Manuals (`staff/manuals/`) | Head | **978** | **1,503** | 300 | **missed** |
| My Manuals | VP Head | **1,439** | 1,491 | 500 | **missed** |
| My Manuals (QMS reads all) | IMR | **7,300–8,600** | **15,001** | 3,000 | **missed** |
| Proposals: from my office | Head | 43 | 66 | 32 | ok |
| Proposals: awaiting my office | Head | 488 | 819 | 107 | ok, barely |
| Proposals: involving my office | Head | **940** | **1,501** | 448 | **missed** |
| QMS queue (`qms/queue/`) | IMR | 606 | 905 | 550 | ok, barely |
| QMS queue | Custodian | 158 | 303 | 300 | ok |
| Bell (`notifications/`) | Head | 9 | 2 | 20 | ok |
| Section search (`staff/sections/?search=`) | Head | 51 | 3 | 400 (capped) | ok |
| Manual section list | Head | 8 | 16 | 5 | ok |
| Proposal detail (`full/`) | Head | 18 | 25 | — | ok |

*Rows where the query count exceeded Django's 9,000-query log were recounted with an execute wrapper. Ranges show cold versus warm runs.*

**100 concurrent users** (waitress, 8 threads, as `DEPLOYMENT.md` prescribes; 100 different Heads and Encoders at once):

| Endpoint | p50 | p95 | max |
|---|---:|---:|---:|
| `notifications/` (bell) | 385 ms | 608 ms | 642 ms |
| `staff/dashboard/` | **6,359 ms** | **10,478 ms** | 10,567 ms |
| `proposals/` | **3,719 ms** | **4,673 ms** | 5,167 ms |

**Reading the numbers.**
- Every miss is a **query-per-row loop**, not the database engine. The 3,000-row lists run 4–5 queries per manual:
  - section count
  - effective owner
  - `_relationship_for`, which re-resolves links
  - current status
- The proposal lists run 6–8 queries per proposal (current version, changes, and blockers twice).
- The staff dashboard's awaiting count loops over every proposal in concurrence.
- The lists are also **unpaginated**, so their size grows with the data.
- Under concurrency, the per-request query count multiplies across 8 threads holding one SQLite file.
- The bell, which is two indexed queries, holds well even under 100 concurrent requests.

**PostgreSQL recommendation: not yet.** The budgets are missed for reasons PostgreSQL wouldn't fix. A 12,000-query request is slow on any engine. Phases 4–5 replace these lists with paginated, aggregate queries (§9), which have to be built anyway. Re-measure on SQLite after Phase 5. If the 100-user figures still miss then, that is the point to move through `DATABASE_URL`, since SQLite serialises writers and the notification and monitoring jobs add writes. I haven't migrated anything.

---

## 8. Queries behind the admin dashboard and the Proposals lists

Row counts are at scale; plans come from `EXPLAIN QUERY PLAN`.

| Query | Table rows | Plan | Note |
|---|---:|---|---|
| Pending users `is_approved=0, role='staff'` | 953 | full scan | no index; small |
| Untagged sections `tag in ('', 'UNTAGGED')` | 15,000 | full scan | no index on `tag` |
| Drafting / in concurrence / frozen counts (3 queries) | 7,000 | 3 full scans | **no index on `Proposal.status`**; could be one `GROUP BY` |
| Activity: versions submitted in window | 8,660 | full scan | no index on `submitted_at`; looped in Python |
| Activity: proposals locked in window | 7,000 | full scan | no index on `locked_at` |
| Activity: returns in window | 32,025 | full scan | no index on (`decision`, `recorded_at`) |
| Recent proposals `ORDER BY updated_at DESC LIMIT 6` | 7,000 | scan + temp sort | **no index on `updated_at`**; then 3 queries per row |
| Staff `proposals/` by `initiating_office` | 7,000 | index | then ~6 per row |
| `awaiting` / `involving` by participant office | 49,765 | index (`office_id`) | then a per-proposal loop |
| QMS queue: latest event per row `ORDER BY at DESC` | 62,909 | index (`proposal_id`) + temp sort | no (`proposal`, `at`) index; one per row |
| Bell unread count | 160,630 | **covering index** (user, read_at) | good |
| Inbox page `ORDER BY created_at DESC` | 160,630 | index (user) + temp sort | no (`user`, `created_at`) index |

**Missing indexes to add**, with the phase that first filters on each:
- `Proposal(status)`, `Proposal(initiating_office, status)` and `Proposal(updated_at)`: Phases 4–5 filters and "recent activity"
- `Proposal(locked_at)`, `ProposalVersion(submitted_at)` and `Concurrence(decision, recorded_at)`: the activity chart and timeliness (Phase 4)
- `AuditEvent(proposal, at)`: stage aging, "who holds it now, for how many days" (Phase 4) and the timeline (Phase 6)
- `Notification(user, created_at)`: the notifications page (Phase 2)
- `CustomUser(is_approved, role)` and `ManualSection(tag)`: small tables; optional

None are added in Phase 0. Each will go in with the phase that needs it, measured before and after.

---

## 9. Every endpoint that returns manuals (the deadline-tag checklist, §6.7)

Callers were checked in the frontend, as with earlier route findings.

| # | Endpoint | Manual appears as | Called by |
|---|---|---|---|
| 1 | `GET staff/manuals/` | List of manuals | Staff **My Manuals**; Sections search's manual picker |
| 2 | `GET manuals/` | List of manuals | Admin **Manuals**; admin Sections' manual picker |
| 3 | `GET manuals/<id>/sections/` | Manual header + sections | **Manual view** (staff and admin) |
| 4 | `GET staff/sections/` | `manual_id`/`manual` per row | Staff **Sections search** |
| 5 | `GET staff/dashboard/` | `recently_opened` rows | Staff **Home** |
| 6 | `GET admin/dashboard/` | `proposals` rows | Admin **Home** and admin **Proposals** |
| 7 | `GET/POST proposals/`, `GET/PATCH proposals/<id>/` | `manual_id`, `manual`, `series` | Staff Proposals "From my office"; the editor header |
| 8 | `GET proposals/awaiting/` | Same payload | Staff Proposals "Awaiting my office" |
| 9 | `GET proposals/involving/` | Same payload | Staff Proposals "Involving my office" |
| 10 | `GET proposals/<id>/full/` | Same payload + trail | Proposal detail (staff, admin, QMS) |
| 11 | `GET qms/queue/` | `manual` title per row | QMS **Requests** and QMS home |
| 12 | `GET notifications/` | Title inside `message` only — **no `manual_id`** | The bell |
| 13 | `GET org/documents/` (`?unassigned=true` from the UI) | List of documents | Admin **Organisation → Series** (unassigned list) |
| 14 | `GET/PATCH org/documents/<id>/` | One document | Admin document detail |
| 15 | `GET org/series/<id>/` | `documents` of the series | Admin series detail |
| 16 | `GET org/series/` | `overriding_documents` (id, title) per series | Admin Series list |
| 17 | `POST manuals/upload-preview/`, `manuals/upload/`, `manuals/<id>/confirm-sections/` | The new manual | Admin upload flow (transient; no tag needed, but the coverage test must list it as exempt) |

**Need adding with Phase 3:** History, Monitoring and the Deadlines page. Notifications (#12) needs a `manual_id` before it can carry a tag. `org/offices/<id>/` returns only an `owned_documents` count, so it needs no tag.

---

## 10. Other findings worth a decision later (not acted on)

- **Admin Proposals shows at most 6 proposals** (§4). It is fixed properly by Phase 5's rebuild. A stop-gap is possible sooner if wanted.
- **The admin and QMS portals have no bell.**
- **The announcement DELETE really deletes** (with the password). It is not part of the organisation, so principle 3 doesn't forbid it, but the new kinds should probably deactivate only, so the audit trail can say what was posted.
- **The sign-up picker includes approving-level and QMS offices.** That is probably right for the VP accounts of decision 4, but worth knowing.
