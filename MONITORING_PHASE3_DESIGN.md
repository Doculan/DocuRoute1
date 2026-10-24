# Monitoring update (v4.2) — notification coverage, and the Phase 3 design

*For approval before anything is built. Spec: `MONITORING_UPDATE_SPEC.md` §5.3, §5.5, §6, §9, §11.1. Decisions in force: SQLite retained, §11.1 density rules, the test policy in `CLAUDE.md`. 24 October 2026, at `v4.2.0-p2`.*

---

## Part 1 — What is built of §5.3, and delegation

### 1.1 The §5.3 table, row by row

| # | Event | Spec: recipients, severity | Built? |
|---|---|---|---|
| 1 | Encoder sends a draft to the Head | Head; action | **Built** (2B). No Head: parent office's Head and the system admin |
| 2 | Head returns a draft to the Encoder, with the note | Encoder(s); action | **Built** (2B). The note is in the body. No Encoder: the Head |
| 3 | Encoder recalls a draft | Head; info | **Built** (2B) |
| 4 | Proposal withdrawn | Initiating Head and Encoder, and every office already notified; info | **Built**: the initiating office, plus the concurring offices once it has been submitted (they are the ones already told) |
| 5 | Submitted for concurrence | Head and Encoder of every concurring office; action | **Built**, with the Encoder's copy as **info**: only the Head can concur (your Checkpoint 0 answer 3) |
| 6 | **A concurring office returns a proposal** | **Initiating Head and Encoder**, with the returning office's name, feedback excerpt, section and a link; action | **Built.** Title "{office} returned {manual}"; body "“{excerpt}” — {section}"; the link opens the proposal. See 1.2 for the audit side |
| 7 | An office concurs | Initiating Head and Encoder; info | **Built** |
| 8 | Resubmitted as a new version | Head and Encoder of every concurring office; action | **Built** (same kind as 5, body "Version n.") |
| 9 | Locked, documents generated | Initiating office; action | **Built** (on the lock: "print, sign and upload") |
| 10 | Scan uploaded, ready for the IMR | IMR; action | **Built**, when the signed copies are complete |
| 11 | IMR accepts or denies | Initiating office; all participating offices on a denial; "action / info" | **Built, with one gap.** Accept is sent as **info**, because the IMR now uploads the signed DCR (decision of 11 Oct) and the office has nothing to do; the spec's "action" may have meant accept. On a denial, "participating" is built as the **concurring** offices only — the approving offices (owner VP, President) are **not** told. **Q-A, Q-B below** |
| 12 | Package returned by the custodian | Initiating office; action | **Built**, plus the IMR when the signed DCR is one of the returned copies |
| 13 | Made effective | Initiating office and every participating office; info | **Built, same gap as 11**: concurring offices yes, approving offices no |
| 14 | Deadline created for an office | Head and Encoder; action | **Not built** (needs Phase 3A) |
| 15 | Reminder before a deadline | Head and Encoder of each office not met; action | **Not built** (3C) |
| 16 | Deadline passed, office not met | Office; nearest VP-level office; QMS; action | **Not built** (3C, with your ladder from Checkpoint 0) |
| 17 | A proposal stalled past its stage threshold | Office holding it (action); initiator (info) | **Built** (2A, with "with the Head" from 2B) |
| 18 | A position with no current holder | Parent office's Head; system admin; action | **Built** for Head, IMR and Custodian posts (your 2A approval) |
| — | Not in the table, built | Signed DCR uploaded → custodian (action), office (info); package back with the custodian → custodian (action) | Built (decision of 11 Oct; 2A approval) |
| — | §5.2 email channel | Optional, behind a setting | **Not built.** Nothing sends mail; to come after SMTP exists |
| — | §5.4.4 weekly digest | Heads and VP offices | **Not built** (proposed in 3C) |

**"Every notification writes an audit event, and reading or acting writes another"**: built, in the **system activity log** (2A design, approved). There is one `notified` row per causing event listing everyone told, one `notification_read` row per first read and one `notification_acted` row per resolving action. All are hash-chained.

### 1.2 The return by a concurring office: what is recorded

When the Budget Head returns a proposal:

1. **`Concurrence`**: the decision `return`, the **full feedback verbatim**, the section it points at, the person, and the position they held.
2. **`AuditEvent RETURNED`**: actor, position, office and office name at the time, and the **full feedback** in `detail`, on the returned version.
3. **`AuditEvent REDRAFTED`**: on the new version, saying which office returned which version.
4. **Notices** to the initiating Head and Encoders (action), with the excerpt and the section.
5. **System log `notified`**, naming each recipient and the post they were told as.
6. When the office resubmits, every copy clears (`acted_by` = the Head), and one `notification_acted` row lists them.

Not yet: the proposal's own timeline does not show the notified / read / acted rows. That is Phase 6's audit block, which reads both logs.

### 1.3 Delegation (§5.5)

**Not built.** Today a Head on leave has two workarounds: an acting Head (`PositionAssignment.is_acting`, built in Phase 1), or nothing, in which case Head work waits. You placed delegation in **3C**; its design is in §5 below.

### Questions from Part 1

- **Q-A.** Should the IMR's **acceptance** go to the initiating office as **info** (as built), or as **action**? Since 11 October the IMR uploads the signed DCR and the office has nothing to do, so I recommend info.
- **Q-B.** On a **denial** and on **made effective**, should the **approving offices** (the owner VP and the levels above) be told too? I recommend yes, as **info**: they signed or would have signed, and §5.3 says "every participating office". It is a small change in `notifications._messages`, and I would do it in 3A.

---

## Part 2 — Phase 3, split 3A–3D

Every sub-phase follows the same order:

1. A report on the current model.
2. A backup, then the migration tested on a **copy** of the live database, compared before and after.
3. Live only after that, and after the **full suite** where the migration rebuilds a core table.
4. Partial tests during the sub-phase, each new test shown to fail without its code.
5. The full suite at the end of the phase.

**Scale design** (§9, SQLite retained):
- every list is paged at 50 and filtered on the server
- counts come from `GROUP BY` or from **precomputed counters** kept in the same transaction as the change
- no query per row
- `run_monitoring` writes in batches of 200 under its expiring lock

**Screens** follow §11.1: summary first, grouped, top 5 or 15 then "Show more", no empty sections, at most about six blocks above the fold.

---

## 3. Phase 3A — announcements and deadlines

### 3.1 `Announcement`, reshaped (information only, dismissible)

| Field | Type | Notes |
|---|---|---|
| `title` | Char 200 | unchanged |
| `body` | Text | unchanged |
| `audience` | Char 8: `all` / `offices` | **Explicit.** An empty office list must never silently mean "everyone"; the PROTECT comment on today's `office` FK explains why |
| `expires_on` | Date, null | **Renamed from `date`.** Null means it never expires. The rule "a date makes it Upcoming" is retired (§6.1) |
| `active` | Bool | unchanged. Deactivating is now the **only** way to remove one |
| `created_by`, `created_at` | | unchanged |
| `deactivated_by`, `deactivated_at` | FK user / DateTime, null | Who switched it off and when |

`AnnouncementOffice(announcement, office PROTECT)`, unique per pair: the target offices when `audience='offices'`.
`AnnouncementDismissal`: unchanged.

**Visible to a person** = active, not expired, and either `audience='all'` or one of their current offices is targeted.

**Retired:**
- the hard DELETE, which now answers 405 and has no route (your decision)
- `shows_as`
- the "Upcoming" widget, replaced by the Deadlines panel

### 3.2 Deadlines

**`DeadlineType`**

| Field | Type | Notes |
|---|---|---|
| `name` | Char 120, unique | |
| `basis` | Char 255 | The spec's "basis" column, shown on hover |
| `is_preset` | Bool | |
| `confirm_with_qms` | Bool | True for the three the spec marks "confirm with the QMS office" |
| `active` | Bool | A retired type stays on old deadlines |
| `created_by`, `created_at` | | null for presets |

The 11 presets from §6.2 go in by data migration and are editable afterwards. "Other (custom)" is not a row: choosing it opens a name field, and the new name becomes a type, so it is selectable next time.

**`Deadline`**

| Field | Type | Notes |
|---|---|---|
| `title` | Char 200 | |
| `type` | FK DeadlineType, PROTECT | |
| `due_on` | Date | |
| `note` | Text, blank | Shown with "Advised by admin" on tags |
| `reminder_days` | JSON list of ints | Default from `MonitoringSetting` `[30, 14, 7, 3, 1]` (§5.4); editable per deadline |
| `active` | Bool | Deactivated, never deleted |
| `created_by`, `created_at` | | |
| `obligations_total`, `obligations_open`, `obligations_met` | PositiveInt | **Precomputed counters** (§9), updated in the same transaction as any obligation change, and re-derived by `run_monitoring` as a safety net |

**`DeadlineTarget`**: what the admin chose. One row per choice.

| Field | Type |
|---|---|
| `deadline` | FK |
| `kind` | `all` / `office` / `series` / `manual` |
| `office`, `series`, `manual` | FKs, null, PROTECT; exactly one set for its kind (check constraint) |

**`DeadlineObligation`**: who owes what. Materialised from the targets when the deadline is created, and recomputed if the targets change before the due date. Monitoring, banners, tags and counts all read these rows rather than resolving targets on every request.

| Field | Type | Notes |
|---|---|---|
| `deadline` | FK | |
| `office` | FK Office, PROTECT | Who owes it |
| `manual` | FK Manual, null, PROTECT | Set when the target named manuals (series or manual targets), or for a priority pair (3C). Null for an office-level obligation |
| `priority` | Bool | 3C |
| `state` | `open` / `submitted` / `reviewed` / `effective` | `submitted` is the office milestone (§2 decision 1); `effective` is the document milestone |
| `office_met_at` | DateTime, null | |
| `met_by_proposal` | FK Proposal, null | The proposal that met it |
| `effective_at` | DateTime, null | |
| `reviewed` | FK ManualReview, null | 3C |

Unique per (deadline, office, manual). Indexes on (office, state), (manual, state) and (deadline, state).

**How targets become obligations:**

| Target | Obligations | Rows at scale |
|---|---|---|
| `office` | One office-level row for that office | 1 |
| `series` | One row per (concurring office, document) of the series | ~800 per series |
| `manual` | One row per concurring office of that manual | ~8 |
| `all` | One office-level row for every active office that concurs on at least one document (**Q-1**) | ~470 |

**When is it met?**
- **Manual-level row:** the office submits a proposal for that manual for concurrence after the deadline was created, or records Reviewed, no change for it (3C).
- **Office-level row:** the office submits any proposal, or attests Reviewed, no change for the deadline as a whole (**Q-1**).
- The **document milestone** is set when that proposal is made effective.

**Where met is set:** in `concurrence_views.submit` and `qms_views.make_effective`, inside their transactions, which also update the deadline's counters. `run_monitoring` re-derives them idempotently.

### 3.3 Notifications in 3A

| Kind | When | To | Severity |
|---|---|---|---|
| `deadline_created` | A deadline is created | Head and Encoder of each office with an obligation | action. Office-level unless the obligation names a manual. Cleared when the obligation is met |
| `deadline_met` | An office meets one | (none) | Not a notice. The banner and tags change instead |

Reminders, due-day, overdue and escalation notices are 3C.

### 3.4 Endpoints (3A)

| Endpoint | Who | Does |
|---|---|---|
| `GET/POST admin/announcements/` | admin | New shape. Paged at 50, filters active/expired |
| `GET/PATCH admin/announcements/<id>/` | admin | Edit and deactivate. **No DELETE** |
| `GET/POST admin/deadlines/` | admin | List: summary counts first (open, due soon, overdue), then rows with "7 of 12 not yet submitted" from the counters. Create: title, type (or a new custom type), due date, targets, note, reminder days. Creating needs **no password**: it commits no office. Q-2 |
| `GET/PATCH admin/deadlines/<id>/` | admin | Edit before the due date, which recomputes obligations; deactivate |
| `GET admin/deadlines/<id>/obligations/?state=&branch=&page=` | admin | Per office, grouped by branch, paged |
| `GET/POST deadline-types/` | admin (POST); everyone (GET) | List; add a custom type |
| `GET action-banner/` | signed in | Extended: `deadlines: {total, next: {title, type, due_on, days_left, urgency}, items[≤5]}` beside `returned`. One query on obligations for the viewer's offices |
| `GET announcement-banner/` | signed in | The announcement row: the newest visible undismissed one, plus "n more" |
| `POST announcements/<id>/dismiss/` | signed in | Unchanged |
| `GET my-deadlines/?page=` | staff | Their offices' obligations, nearest first: the Deadlines panel and page |
| `GET staff/dashboard/` | staff | Loses `upcoming` and `announcement` (now served by the two banner endpoints). Gains `deadlines_open` |

### 3.5 Screens (3A)

- **Admin → "Deadlines & announcements"** replaces Announcements. Two tabs, Deadlines first.
  - The create form asks for a **Kind** first and shows only that kind's fields.
  - The deadline list opens on three counts: open, due within the reminder window, overdue.
  - Each row: title · type · due date · "7 of 12 not yet submitted" · urgency mark in words and colour.
  - A deadline's detail page shows offices grouped by branch, unmet first, collapsed groups with counts, paged.
- **Banner rows, at most two** (§6.1):
  1. **Announcements:** neutral blue, dismissible per person, the newest one plus "2 more".
  2. **Action row:** the 2B banner gains deadlines. It shows one consolidated line, "3 deadlines · next: ISO surveillance audit, 12 Nov (5 days)", plus the returned count. It is coloured by the most urgent item: calm, then amber inside the reminder window, red when overdue, always in words as well. It folds to one line and cannot be dismissed. It is shown only to the Head and Encoder of offices with an open obligation.
- **Staff Home:** a **Deadlines** panel (top 5, nearest first, "Show all" opens the Deadlines page) replaces Upcoming.
- **All three portals** get the announcement row. The QMS and admin portals get the action row only where they hold office posts.

### 3.6 Migration plan (3A)

**`0046_announcements_and_deadlines`**
- **Schema:**
  - add `audience`, `deactivated_by`, `deactivated_at`
  - rename `date` → `expires_on`
  - add `AnnouncementOffice`
  - create `DeadlineType`, `Deadline`, `DeadlineTarget`, `DeadlineObligation`
  - add the `reminder_days` default to `MonitoringSetting`
- **Data:**
  - the 11 preset types
  - every existing announcement: `audience = 'all'` if `office` is null, otherwise `'offices'` plus one `AnnouncementOffice` row
  - remove `office` once copied

**The three live rows** (all targeted to everyone today, 0 dismissals):

| id | Title | Today | After 0046 |
|---|---|---|---|
| 1 | Internal quality audit, week of 6 October | dated 2026-09-26 → Upcoming, already past | Announcement, `audience all`, `expires_on 2026-09-26` → **expired, not shown**. **No deadline is created from it** |
| 2 | Document control refresher | dated 2026-09-21, past | Announcement, `audience all`, `expires_on 2026-09-21` → expired, not shown |
| 3 | New revision workflow is live | undated → banner | Announcement, `audience all`, no expiry → **still the banner** |

**Tested on a copy first:** the three rows compare as above, the dismissal count is unchanged, and the staff banner shows row 3 and nothing else. `api_announcement` is rebuilt (column rename and drop), but it is not a core table. The full suite runs before live anyway, because the staff dashboard reads it.

### 3.7 Tests (3A)

- Each existing announcement maps as in the table; a migration test from 0045 → 0046 like `tests_migration_0043`.
- An empty office list never means everyone: `audience='offices'` with no rows is refused with reason `no_offices`.
- DELETE is gone: 405.
- Expired and inactive announcements are not shown; dismissal stays per person.
- A custom type becomes selectable; a duplicate name is refused (`type_exists`).
- Targets materialise into the right obligations for each kind, including `all`, an overridden document's own offices, and readers excluded.
- Submitting meets the matching obligation and only it: the counters move by one, in the same transaction, and a rollback leaves them unchanged.
- Making it effective sets the document milestone.
- Banner urgency: calm, amber inside the window, red overdue; met obligations vanish from that office's banner only (§6.1).
- At most two banner rows, whatever exists.
- Scale: the deadline list, a deadline's detail page and the banner meet §9 on `seed_scale`, which gains deadlines of every target kind.

---

## 4. Phase 3B — the deadline tag on every manual, and the 17 endpoints

### 4.1 One helper

`deadline_tags_for(user, manual_ids) -> {manual_id: tag}`, in `deadline_tags.py`.

- **Two queries:**
  1. open or recently met obligations whose `manual_id` is in the page, with their deadline and type
  2. the viewer's scope: their offices and every office beneath them (one query over `Office(id, parent_id)`, walked in memory and cached for the request)
- **The tag**:
  ```
  {state, label, due_on, days_left, type, advised: [office names ≤2], more: n,
   note, muted, frozen (3D)}
  ```
- **Visibility** (§6.7):
  - **The advised office's Head and Encoder** see "Deadline upcoming 12 Nov 2026".
  - **Heads of offices above it** see "Advised: {Office} · deadline upcoming".
  - **QMS and admin** see the same as offices above, for every office.
  - **Concurring and reader offices of that manual** see the muted "Revision advised for {Office}" (decision 10).
  - **Nobody** sees another branch's deadline.
- **States** (§6.7):
  - upcoming
  - inside the window with days left (amber)
  - today (amber)
  - overdue (red)
  - submitted (muted, "Submitted 10 Nov")
  - frozen (3D)

  The nearest deadline shows, with "+n more".
- **Office-level obligations do not tag manuals** (**Q-3**). They appear in the banner and the Deadlines panel. Tagging every document an office concurs on would put a tag on 50 rows for one obligation.

### 4.2 The 17 endpoints: what each gains, and how it gets to budget

"Converted" means paged at 50, filtered on the server, and built in a fixed number of queries with `select_related`, `prefetch_related`, aggregate annotations and the two tag queries.

| # | Endpoint (screen) | Today at scale | 3B change |
|---|---|---|---|
| 1 | `staff/manuals/` (My Manuals; **QMS Manuals list**) | 1–8.6 s, 1,500–15,000 queries | **Rebuilt.** `?q=&series=&page=`. Opens on **series groups with counts** (§11.1); a group loads its first 50 documents. Section count, owner, relationship and status come in 4 queries plus 2 for tags. **Budget: 800 ms per page** |
| 2 | `manuals/` (admin Manuals) | 5–24 s, 12,000 queries | As 1, with the admin filters (series, uploader) and the same groups |
| 3 | `manuals/<id>/sections/` (manual view header) | 8 ms | + `deadline` on the header |
| 4 | `staff/sections/` (Sections search) | 51 ms, capped at 400 | + `deadline` per row; paged at 50 instead of a 400 cap |
| 5 | `staff/dashboard/` (Recently opened) | 23 ms | + tags on 6 rows |
| 6 | `admin/dashboard/` (recent proposals) | 69 ms | + tags |
| 7 | `proposals/`, `proposals/<id>/` | 43 ms, 66 queries | + tags; paged |
| 8 | `proposals/awaiting/` | 488 ms, 819 queries | **Rebuilt** on the 2A `awaiting_pairs` aggregate; paged; tags |
| 9 | `proposals/involving/` | 940 ms, 1,501 queries | **Rebuilt** as one query; paged; tags |
| 10 | `proposals/<id>/full/` (editor and detail header) | 18 ms | + `deadline` |
| 11 | `qms/queue/` (Requests) | 606 ms, 905 queries | **Rebuilt**: latest event per row by subquery, not one per row; paged per queue; tags |
| 12 | `notifications/` | 7 ms | + `deadline` (notices now carry `manual_id`) |
| 13 | `org/documents/` | 7 s full; the UI asks `?unassigned=true` | Paged; tags; `section_count` by annotation |
| 14 | `org/documents/<id>/` | — | + tag |
| 15 | `org/series/<id>/` (its documents) | — | Documents paged; tags |
| 16 | `org/series/` (overriding documents) | 64 ms | Tags on the named documents |
| 17 | upload / preview / confirm | transient | **Exempt** (a manual being created has no deadline), listed in the coverage test's exemptions |
| + | `needs-action/`, `action-banner/`, `admin/proposals/` | 2–21 ms | + tags (built after Phase 0, so not in the original 17) |

**Indexes added with 3B, measured before and after:**
- `ManualSection(manual, order)`
- `Manual(series, title)`
- the obligation indexes from 3A
- `ProposalParticipant(office, role)`

### 4.3 The coverage test (§6.7)

It walks `api.urls.urlpatterns` and calls every GET route with a fixture that has an obligation on a manual. It scans each JSON response for any object carrying `manual_id`, or a manual's own `id` + `title` + `series`, and **fails if that object has no `deadline` key**. Exemptions are named in the test with a reason. A new endpoint that returns manuals fails the test until it carries tags, so no tab can be missed silently.

### 4.4 Screens (3B)

- **One `DeadlineTag` component** on every surface in §6.7's checklist: My Manuals, section list, Sections search, the manual and section view header, every Proposals list and the editor header, Home, notifications, and admin Manuals and Organisation lists. Monitoring and History follow in Phases 4–5, using the same component.
- The tag is text plus colour, never colour alone; the type shows on hover or expand.
- **My Manuals / QMS Manuals**, rebuilt for §11.1:
  - a search box
  - series groups with counts, collapsed except the group with open deadlines
  - 50 rows per page inside a group

### 4.5 Tests (3B)

- The tag states and their wording.
- The visibility rules per viewer.
- A sibling branch sees nothing.
- One manual with two deadlines shows the nearest and "+1 more".
- **Query counts that do not grow with the page**, for every converted endpoint.
- The coverage test.
- Every converted endpoint measured on `seed_scale` against §9. Anything still missing its budget gets a **design limit** proposed, not a database.

---

## 5. Phase 3C — priority, reminders, escalation, Reviewed no change, delegation

### 5.1 Priority manuals (§6.4)

No new model: a **priority pair** is a `DeadlineObligation` with `manual` set and `priority=True`.
- **Admin:** a deadline's detail page has "Add priority manuals for an office", which picks an office and then documents it concurs on.
- **Endpoint:** `POST admin/deadlines/<id>/priority/`, with `{office_id, manual_ids}`.
- **Effect:** the pair ranks first wherever obligations are ranked (Phase 5 uses it), shows on the office's Home and notices, and is a row in Monitoring.

### 5.2 Reminders and escalation in `run_monitoring`

New steps: `reminders`, `due`, `overdue`, `escalation`. Each is idempotent by dedupe key, runs in batches of 200 in short transactions, extends the lock, and is skipped for offices under a freeze (3D).

| Step | When (per open obligation) | To | Dedupe key |
|---|---|---|---|
| Reminder | each `reminder_days` value (30, 14, 7, 3, 1 before) | Head + Encoder; action | `deadline:{d}:office:{o}:remind{n}` |
| Due day | `due_on` | Head + Encoder; the banner turns red | `…:due` |
| Overdue | the day after, unmet | Head + Encoder **+ Head of the immediate parent office** | `…:overdue` |
| Escalation | 7 days after due, unmet | **Nearest approving-level office above** (its Head) + **QMS** (IMR and Custodian holders) | `…:escalated` |
| Repeat | weekly while unmet | the escalation recipients | `…:weekly:{iso_year}-{iso_week}` |

**Fallbacks** (your Checkpoint 0 decision 3):
- no approving-level ancestor → the **President's office** (the root approving office)
- that office, or a VP office, with no Head → the **system admin**

Each notice is also written as a `SystemEvent` (`deadline_reminder`, `deadline_due`, `deadline_overdue`, `deadline_escalated`). All clear when the obligation is met.

**Weekly digest (§5.4.4)**, proposed as an optional last step:
- one notice per Head and VP-office Head on a set weekday
- "3 late · 2 stalled · 4 due this fortnight", linking to Monitoring (Phase 4)
- off until Phase 4, because it has nowhere to link before then

### 5.3 Reviewed, no change, and review dates (§6.5)

- **`Manual`** gains `last_reviewed_on` and `next_review_due` (Date, null). A new **`MonitoringSetting` `review_interval_months`** defaults to 12 (**Q-4**).
- **`ManualReview`**: `manual`, `office`, `reviewed_by`, `position` (Head), `note`, `at`, `obligation` (null).
- **`POST manuals/<id>/reviewed-no-change/`**:
  - **Who:** the Head (or their delegate) of a concurring office.
  - **Password:** yes, since it commits the office.
  - **Note:** optional.
  - **What it does:**
    - writes the review
    - sets both dates
    - meets that office's open obligations on the manual (and office-level ones, Q-1) as `reviewed`
    - writes a `SystemEvent reviewed_no_change`
- **Optional `run_monitoring` step** (**Q-5**, off by default): manuals past `next_review_due` are gathered once a month into one "Periodic document review — {month}" deadline, with manual-level obligations.

### 5.4 Delegation (§5.5)

**`HeadDelegation`**

| Field | Notes |
|---|---|
| `office` | FK |
| `head_assignment` | FK PositionAssignment: the Head delegating |
| `delegate` | FK user |
| `starts_on`, `ends_on` | Dates; `ends_on` required (a dated period) |
| `reason` | Required |
| `created_by`, `created_at`, `ended_at`, `ended_by` | Ended early by the Head or the admin; never deleted |

Constraint: no two delegations for one office overlap.

**Who may be a delegate** (**Q-6**): someone holding a current post in the same office, or a Head of its parent office.

**Effect, while the period is current:**
- `concurrence_views._head_of(user, office)` returns the Head position for the delegate too, so they can submit, concur or return, return to the Encoder, withdraw, and record Reviewed, no change.
- **Head notices** go to the delegate instead of the absent Head. Notices keep `addressed_position = Head`, and the title says "for {office} Head".
- **The record:** `AuditEvent` gains `acting_for` (FK user, null): the Head being covered. Positions print as "Accounting Office — Head (delegated)". Generated forms still print **position titles only**; the delegate signs on paper as the person present.

**Endpoints:**
- `POST/GET offices/<id>/delegations/`: the Head, or the admin; **password** (it changes who can commit the office)
- `POST delegations/<id>/end/`

**Screens:**
- a "Delegate while away" panel on the Head's account page: current and future delegations, one line each
- the admin's People screen shows delegations under the office

**Audit:** `SystemEvent` kinds `delegation_started` and `delegation_ended`.

### 5.5 Migration plan (3C)

**`0047_priority_reviews_delegation`**:
- `Manual` review dates
- `ManualReview`
- `HeadDelegation`
- **`AuditEvent.acting_for`**
- the new `MonitoringSetting` rows

`AuditEvent` is a **core table** and SQLite rebuilds it to add the column. So: copy first, compare event counts and the 2A-era rows, then the **full suite**, then live.

### 5.6 Tests (3C)

- **Reminders and escalation:**
  - each ladder rung fires once, on its day, to the right posts
  - a second run sends nothing
  - due-day and overdue go to the parent Head
  - at +7 days the nearest approving level and QMS are told
  - the President fallback, and the VP-without-Head fallback to the admin
  - weekly repeats once per ISO week
  - meeting the deadline clears every open reminder
- **Reviewed, no change:** Head only (`not_head`); password (`reauth_required`); meets only that office's obligations; dates set; logged.
- **Delegation:**
  - a delegate can act only inside the period (`not_head` before and after)
  - overlapping delegations are refused (`delegation_overlaps`)
  - notices go to the delegate
  - `acting_for` is recorded
  - ending a delegation restores the Head at once
  - the generated DCR prints the same titles
- Scale: a full reminder run over `seed_scale`'s deadlines, timed, with batch transactions.

---

## 6. Phase 3D — change freeze (§6.6)

### 6.1 Models

**`Freeze`**

| Field | Notes |
|---|---|
| `reason` | Required |
| `expected_end_on` | Date |
| `scope` | `all` / `offices` / `series` |
| `started_by`, `started_at` | |
| `lifted_by`, `lifted_at` | Null while in force |
| `extended_reminded_on` | When the admin was last told it is past its expected end |

- `FreezeTarget(freeze, office null, series null)`: check constraint, exactly one, matching the scope.
- `FreezeException(freeze, proposal null, manual null, reason, granted_by, granted_at)`.

### 6.2 Enforcement: one helper, on the server

`freeze_refusal(action, proposal=None, manual=None, office=None)` returns a 409 with reason `frozen`, the freeze's reason and its expected end, or None. It covers a freeze in force that covers the office or the manual's series, unless an exception names the proposal or manual.

| Action | Blocked during a freeze? |
|---|---|
| Starting a new proposal | **Yes** |
| Send to Head | **Yes** (§6.6) |
| Submit to concurrence | **Yes** |
| Making effective | **Yes** |
| Editing and saving existing drafts, running checks | No |
| Concurring and returning on proposals already in concurrence | No (decision 9) |
| Signing, scans, IMR decisions | No; only making effective waits |
| Reading anything | **Never** |

**Deadlines inside a freeze:**
- overdue and escalation are **paused** for the affected offices: `run_monitoring` skips them and records `paused_by_freeze` in the run counts
- the admin gets one notice per deadline: "Deadline X falls inside the audit freeze — extend it?"

### 6.3 Endpoints, screens, audit

**Endpoints** (system admin, **password** on each):
- `POST admin/freezes/` to start
- `POST admin/freezes/<id>/lift/`
- `POST admin/freezes/<id>/exceptions/`

**Screens:**
- An admin "Freeze" panel under Deadlines & announcements: the current freeze, start, lift, exceptions.
- A **freeze banner** joins the **action row**, so there are still at most two rows: "Frozen for audit until 15 Nov — {reason}".
- Disabled buttons say why and until when. The `DeadlineTag` shows "Frozen for audit" beside any deadline (3B's `frozen` field).

**Notifications:**
- affected offices at start and at lift (info, office-level)
- the admin when the expected end passes (action, cleared by lifting or extending)

**System log:** `freeze_started`, `freeze_exception_granted`, `freeze_lifted`.

**Optional shortcut** (§6.6, off by default): an audit-type deadline can offer "freeze from N days before through the audit". It **proposes** a freeze for the admin to start; it never starts one by itself.

### 6.4 Migration (3D)

`0048_change_freeze` creates three new tables. No core table is rebuilt. Tested on a copy first.

### 6.5 Tests (3D)

- Each blocked action is refused with reason `frozen` and the expected end, inside scope and only there.
- Drafts can still be edited; concurrence continues but making effective waits.
- An exception lets exactly its proposal or manual through.
- Lifting ends every block at once.
- Overdue notices pause and resume.
- Start, lift and exception need the password (`reauth_required`).
- Nothing in a freeze blocks a GET.
- The banner row count stays at most two.

---

## 7. Questions before building

| # | Question | Recommendation |
|---|---|---|
| **Q-A** | IMR **acceptance** to the initiating office: info (as built) or action? | **Info.** The IMR uploads the signed DCR now; the office has nothing to do |
| **Q-B** | Tell the **approving offices** on a denial and on made effective? | **Yes, info**, in 3A |
| **Q-1** | An **office-level** obligation (a deadline targeting an office without naming manuals) is met by…? And who is "all offices"? | Met by **any proposal the office submits** after the deadline was created, **or** its Head attesting Reviewed, no change for the deadline. "All" = every active office that **concurs on at least one document** |
| **Q-2** | Creating a deadline: password or not? | **No**: it commits no office and changes no document. Starting and lifting a freeze do |
| **Q-3** | Office-level obligations: **tag** the manuals the office concurs on? | **No.** Tags only where the deadline names manuals (series, manual or priority pair); office-level obligations show in the banner and the Deadlines panel |
| **Q-4** | Default review interval for "next review due" | **12 months**, editable, **confirm with the QMS office** |
| **Q-5** | Generate the periodic review deadline automatically from overdue review dates? | **Yes, off by default**, once a month, as one grouped deadline |
| **Q-6** | Who may be a Head's **delegate**? | A current post holder in **the same office**, or the **Head of its parent office**; never someone outside the branch |
| **Q-7** | Several live announcements: show how? | The newest in the banner row, with "n more" expanding the rest; each dismissible on its own |

---

## 8. Approved (24 October 2026): answers and changes

**Answers:**
- **Q-A:** info.
- **Q-B:** yes, info, in 3A.
- **Q-1:** as recommended. In addition, the create form warns "No manuals named: any proposal this office submits will count", and each obligation records the proposal that met it (shown in Monitoring).
- **Q-2:** no password, but a preview before saving: "This will notify N offices (M people)".
- **Q-3:** no tags for office-level obligations.
- **Q-4:** 12 months, to confirm with the QMS office.
- **Q-5:** build it, off by default.
- **Q-7:** the newest, plus "n more".
- **Q-6:** as recommended. In addition:
  - a delegate may not submit, concur on or return a proposal they themselves drafted or sent to the Head (no maker-checker collapse)
  - the admin may also set up a delegation, with the password

**Design changes:**
1. **"And everything beneath it."** Office targets, for deadlines and announcements, get this option. It expands to every active descendant office that concurs on at least one document.
2. **In-flight proposals count.** If the office already has a submitted proposal for the manual open when the deadline is created, that proposal meets the obligation at creation.
3. **Withdrawing reopens.** Withdrawing the proposal that met an obligation reopens it; a denial does not. Both are tested.
4. **`AuditEvent.acting_for` must not break existing hashes.** It is hashed only when set, and "verify trail" is shown passing on pre-existing events, on a copy, before live.
5. **3B is split** into 3B-1 (the helper, the coverage test, the small endpoints) and 3B-2 (the slow list rebuilds and their screens), with a checkpoint after each.

**Banner correction** (spec §5.2 and §6.1 amended to match):
- The **deadline and action row is the top row, pinned** while the page scrolls.
- It has no dismiss control: the one-line summary always stays, and only the expanded list folds.
- It disappears for an office only when that office meets its deadline.
- Inside it the most urgent comes first: overdue, due today, due soon; returned work and the freeze notice share the row.
- The **announcement row sits beneath it**, dismissible per person.
- Still at most two rows.
- A test checks that the action row renders above the announcement row and has no dismiss route.

**Tagging:** the end of Phase 3 is tagged `v4.2.0-p3`, after 3D.
