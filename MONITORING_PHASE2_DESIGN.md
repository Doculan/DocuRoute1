# Monitoring update (v4.2) — Phase 2 design: notifications

*For approval before anything is built. Spec: `MONITORING_UPDATE_SPEC.md` §5; survey: `MONITORING_PHASE0_REPORT.md` §2–3, §5. 23 October 2026.*

---

## 1. The problem this design solves

Today a `Notification` is a pointer to an `AuditEvent`. An `AuditEvent` needs a **proposal**, a **person who acted** (PROTECT, not null) and an **office**. That covers concurrence traffic and nothing else:

- deadlines, reminders and escalations have no proposal
- vacancies and freezes have no proposal and often no manual
- the scheduled job has no person

There are two dishonest ways round this: invent a "system" user, or attach system work to a random proposal. This design does neither. Instead it has:

1. **Two logs, each honest about its subject.**
   - `AuditEvent`, unchanged: what happened **to a proposal**, done by a person in a position.
   - A new `SystemEvent`: everything else. Its actor is either a person or the label **`system`**, never a fake user. It has its own hash chain.
2. **A `Notification` that stands on its own.** It stores its text when it is created, carries its recipient, severity, link, manual and dedupe key, and points at **exactly one** of the two logs as its cause.

---

## 2. `SystemEvent`, the system activity log

Append-only, with no update or delete path for any role (spec rule 7). The model's `save()` refuses an update, and there is no `delete()` path in code.

| Field | Type | Notes |
|---|---|---|
| `seq` | PositiveBigInteger, unique | Position in the chain, 1, 2, 3… The order the hash covers; `id` is not used, so the hash can be computed before insert |
| `kind` | Char(40), choices | Listed below |
| `actor` | FK user, **null**, PROTECT | The person, when a person acted |
| `actor_label` | Char(255) | `system` when `actor` is null; otherwise the position title at the time (or "System administrator"). **Check constraint:** `actor IS NULL ⇔ actor_label = 'system'` |
| `position` | FK Position, null, SET_NULL | Who acted, as what |
| `office` | FK Office, null, PROTECT | The office the event is about (late office, vacant post's office…) |
| `office_name_at_time` | Char(255), blank | Reads correctly after renames |
| `proposal` | FK Proposal, null, PROTECT | Optional subject (e.g. "notified" about a proposal event, stall) |
| `manual` | FK Manual, null, PROTECT | Optional subject |
| `detail` | JSON | Structured facts: recipients, days late, threshold, counts. Never prose that a screen must parse |
| `at` | DateTime | **Set by the writer, not `auto_now_add`**, so the hash covers the stored value |
| `prev_hash` | Char(64) | The previous row's `hash`; 64 zeros for row 1 |
| `hash` | Char(64), unique | SHA-256, see below |

`Deadline` and `Freeze` FKs are added in Phase 3 with those models. Old rows simply have them null; nothing re-hashes.

**Kinds in Phase 2:**
- `log_started` (genesis)
- `notified` (one row per causing event, listing its recipients)
- `notification_read`, `notification_acted`
- `stalled`, `position_vacant`
- `email_sent` (only once SMTP exists)

Phase 3 adds deadline and freeze kinds (created, reminder, due, overdue, escalated, freeze started/lifted/exception), and Phase 5 the digest.

**Hash.**
```
hash = sha256(prev_hash ‖ canonical_json({seq, kind, actor_id, actor_label,
              position_id, office_id, office_name_at_time, proposal_id,
              manual_id, detail, at (ISO 8601, UTC, microseconds)}))
```
`canonical_json` uses sorted keys and `separators=(',', ':')`, so the same row always hashes the same.

**Writing under concurrency.** A one-row-per-log table `LogHead(log, seq, hash)` is read with `select_for_update()` inside the writer's transaction, which then inserts `seq+1` and updates the head. The project's immediate SQLite transactions serialise writers, and the row lock keeps that true in any case. So two writers can never fork the chain.

**Verify.** `manage.py verify_log system` walks `seq` in order, recomputes each hash, and reports the first break (seq, expected, found). Phase 6 adds a "verify trail" button and an AuditEvent chain using the same helper. That chain will be **per proposal**, so busy proposals don't contend for one global head.

**Volume** (see §6 for the "notified" choice): at most one "notified" row per notifying audit event. That is fewer than the 63,642 audit events at seed scale, plus read/acted rows as they happen.

---

## 3. `Notification`, rebuilt

| Field | Type | Notes |
|---|---|---|
| `recipient` | FK user, CASCADE | Renamed from `user`. CASCADE as today. The record of who was told lives in `SystemEvent.notified`, which is PROTECT, so deleting an unreferenced test account (principle 3's exception) still works only when nothing refers to it |
| `addressed_office` | FK Office, null, PROTECT | The office it was sent to |
| `addressed_office_name` | Char(255) | Snapshot |
| `addressed_position` | FK Position, null, SET_NULL | The post that made this person a recipient. Null for the system admin fallback |
| `addressed_position_title` | Char(255) | Snapshot, e.g. "Accounting Office — Head", or "System administrator" |
| `kind` | Char(40), choices | Below |
| `severity` | Char(8): `action` / `info` | |
| `title` | Char(120) | **Stored at creation**, never rebuilt on read |
| `body` | Char(300) | One line, stored at creation. The returning office's feedback excerpt goes here, trimmed |
| `target_type` | Char(16): `proposal`, `manual`, `deadline`, `office`, `people` | The app has no URL router (navigation is state), so the link is a typed target the client opens, not a URL |
| `target_id` | PositiveInteger, null | |
| `manual` | FK Manual, null, SET_NULL | Carried on **every manual-related** notification, so deadline tags (§6.7) and filters can reach it (see Q1) |
| `manual_title` | Char(255), blank | Snapshot, so the inbox reads correctly if the title changes |
| `proposal` | FK Proposal, null, PROTECT | When there is one; resolvers use it |
| `audit_event` | FK AuditEvent, null, PROTECT | Cause, when a proposal transition |
| `system_event` | FK SystemEvent, null, PROTECT | Cause, otherwise |
| `dedupe_key` | Char(200) | See below |
| `created_at` | DateTime | |
| `read_at` | DateTime, null | |
| `acted_at` | DateTime, null | Action-required only: set when the action is done, by anyone entitled |
| `acted_by` | FK user, null, SET_NULL | Who resolved it (the Head may resolve the Encoder's copy) |

**Constraints:**
- **Exactly one cause:** `(audit_event IS NULL) <> (system_event IS NULL)`.
- **One notice per person per thing:** unique `(recipient, dedupe_key)`. This replaces today's unique `(user, event)`. A person holding Head and Encoder posts in the office gets one row, addressed to the first post in the order Head, Encoder.
- `severity = 'info' ⇒ acted_at IS NULL`.

**Indexes:**
- `(recipient, read_at)` and `(recipient, severity, acted_at)`, as the spec asks
- `(recipient, created_at)` for the notifications page, which today sorts in a temp B-tree
- `(proposal, kind, acted_at)` for resolvers

**Dedupe keys.** Deterministic strings, built in one helper:

| Cause | Key |
|---|---|
| A proposal transition | `audit:{audit_event_id}` |
| Stalled | `stalled:{proposal_id}:{stage}:{entered_stage_at:%Y%m%d%H%M}`: once per stay in a stage |
| Vacant | `vacant:{position_id}:{vacant_since:%Y%m%d}` |
| Phase 3 | `deadline:{id}:office:{id}:{milestone}` with milestone `created`, `remind30`…`remind1`, `due`, `overdue`, `overdue+7`, `weekly:{iso_week}` |

**Bell count**, one indexed query: `severity='info' AND read_at IS NULL` **or** `severity='action' AND acted_at IS NULL`. Polled every 60 s and on navigation, as today.

**Reading and acting.**
- Opening a notification sets `read_at`. That clears an info notice and nothing else.
- Action-required notices clear only when a **resolver** runs. It runs in the same transaction as the action itself, for example:
  ```python
  Notification.objects.filter(kind='concurrence_requested', proposal=p,
      addressed_office=office, acted_at__isnull=True).update(acted_at=now, acted_by=user)
  ```
  Each action-required kind names its resolver in one table (§5), so nothing can stay red after it is done.
- First read and the resolve each write a `SystemEvent` (`notification_read` / `notification_acted`, with `detail={"notification": id, ...}`). That gives "who was told, when, and what they did", as §5.3 requires.

---

## 4. Kinds, recipients and resolvers (Phase 2 scope)

Recipients are **positions held today**, resolved through one helper, `holders_for(office, kinds)`, which extends `notifications.holders_of`. The actor is left out, and people are de-duplicated as above.

| Kind | Cause | Recipients | Severity | Resolved by |
|---|---|---|---|---|
| `sent_to_head` | audit | Head of the initiating office | action | Head submits, returns, or the Encoder recalls |
| `returned_to_encoder` | audit | Encoder(s) of the initiating office | action | Encoder sends to the Head again |
| `recalled` | audit | Head | info | — |
| `withdrawn` | audit | Initiating Head + Encoders, and every office already notified | info | — |
| `concurrence_requested` | audit (submit or resubmit) | Head + Encoders of each concurring office | action | That office concurs or returns; or the version is superseded or withdrawn |
| `returned_by_office` | audit | Head + Encoders of the initiating office; body carries the returning office, feedback excerpt and section | action | A new version is submitted, or withdrawn |
| `concurred` | audit | Initiating Head + Encoders | info | — |
| `locked` | audit | Initiating Head + Encoders | action | Signed copies complete (`package_complete`) |
| `ready_for_imr` | audit (`package_complete`) | IMR position | action | IMR accepts or denies |
| `imr_accepted` | audit | Initiating office | info | — |
| `imr_denied` | audit | Initiating office + every participating office | info | — |
| `approval_uploaded` | audit | Initiating office (info); current custodian (action) | info / action | Custodian accepts or returns |
| `package_returned` | audit | Initiating office | action | The returned item is re-uploaded |
| `made_effective` | audit | Initiating office + every participating office | info | — |
| `stalled` | system | Office holding it (action); initiator (info) | action / info | The proposal leaves that stage |
| `position_vacant` | system | Head of the parent office; system admin | action | Someone is assigned |

Deadline kinds (`deadline_created`, `deadline_reminder`, `deadline_due`, `deadline_overdue`, `deadline_escalated`) and the escalation ladder you set in decision 3 arrive with the `Deadline` model in Phase 3. `run_monitoring` is built so those are new steps, not a rewrite.

**Stall thresholds** (decision 6) live in a small `MonitoringSetting` table the system admin can edit: with Head 3, concurrence 7, awaiting signature 14, with IMR 7, with custodian 10 (days). The "stage entered at" time comes from the latest `AuditEvent` that moved the proposal into its current status, which is why the `AuditEvent(proposal, at)` index arrives in this phase.

---

## 5. `run_monitoring`, and its run lock

`manage.py run_monitoring [--only stalls,vacancies] [--dry-run]`

**Idempotent by construction.** Every notification it would write has a dedupe key, inserted with `bulk_create(ignore_conflicts=True)` against the unique `(recipient, dedupe_key)`. A second run, or two runs at once, cannot double-notify. The lock below exists to save work, not to prevent duplicates.

**Small batches, short transactions** (decision 7):
- Each step reads candidate ids first, outside any transaction.
- It then processes them in batches of **200**, each batch in its own `transaction.atomic()`. A batch writes its `SystemEvent`s (chain head locked only for that batch), its notifications, and nothing else.
- SQLite's write lock is held for milliseconds per batch, so the web requests in between are not starved.

**Run lock: `JobLock(name pk, holder, acquired_at, expires_at)`.**
- **Acquire** with a single conditional `UPDATE … SET holder=?, acquired_at=now, expires_at=now+10min WHERE name='monitoring' AND expires_at < now`. If no row was updated, another run holds the lock, and this run logs "already running" and exits 0. The row is created by the migration.
- A crashed run's lock expires on its own after 10 minutes. No manual clean-up.
- **Release** by setting `expires_at = now` at the end, in a `finally`.

**Each run writes a `JobRun` row**: started, finished, steps, counts written, errors. This is operational, not part of the hash chain; 288 runs a day would bury the real events. The admin Monitoring screen (Phase 4) shows the last run time, and warns if it is older than 30 minutes.

**On dashboard load** (§5.4): if the last finished `JobRun` is older than 15 minutes, the dashboard request tries the lock **without waiting**. If it gets it, it runs the steps **scoped to the viewer's offices**, capped at one batch; otherwise it does nothing. A stopped scheduler therefore delays nothing a person is looking at, and a page load never waits on a full run.

**Scheduling, documented in `DEPLOYMENT.md` and `DEMO_CHECKLIST.md`:**
- **Windows:**
  ```
  schtasks /create /tn "QMS CDMS monitoring" /sc minute /mo 5 /ru SYSTEM ^
    /tr "C:\QMS-CDMS\venv\Scripts\python.exe C:\QMS-CDMS\Backend\manage.py run_monitoring"
  ```
  Then in Task Scheduler, set "Do not start a new instance" and give the task the same `SQLITE_PATH` / `DATABASE_URL` environment as the server.
- **Server:** cron
  ```
  */5 * * * * cd /srv/qms-cdms/Backend && ../venv/bin/python manage.py run_monitoring >> /var/log/qms-cdms/monitoring.log 2>&1
  ```
  A systemd timer works equally well; a loop under the process manager is the fallback.

---

## 6. Choices worth your eye

- **"Notified" is one `SystemEvent` per causing event, listing its recipients** (`detail.recipients = [{user, position_title, office}]`), not one row per recipient. Same evidence, about a third of the rows. Reading and acting are still one row per person, because they are separate acts.
- **Proposal notifications keep their cause in `AuditEvent`**; only the "notified / read / acted" facts go to `SystemEvent`. The proposal's own trail (Phase 6) reads both logs, filtered by `proposal_id`.
- **Email** is a setting (`NOTIFY_EMAIL=false`) and a sender that writes `email_sent`. Nothing is sent until SMTP exists.

---

## 7. Migration plan

Tested on a copy first, after a backup, as always. Live today: **3 notifications** (submitted, concurred, locked, all on proposal 5, all read).

| Migration | What |
|---|---|
| `0042` | Create `SystemEvent`, `LogHead`, `JobLock` (with the `monitoring` row), `JobRun`, `MonitoringSetting` (with the decision-6 defaults). Add the new `Notification` fields, nullable or blank so existing rows stay valid. Add the `AuditEvent(proposal, at)` index |
| `0043` (data) | Write `SystemEvent` seq 1, `log_started` (actor `system`). For each existing notification, details below |
| `0044` | Rename `user` → `recipient`. Drop `event` and the old unique `(user, event)`. Add the exactly-one-cause check, unique `(recipient, dedupe_key)` and the indexes. Make `kind`, `severity`, `title` and `dedupe_key` non-blank |

**`0043`, for each existing notification:**
- `audit_event` = its old `event`, and `proposal` and `manual` from that event.
- `kind`, mapped from `event.event`: submitted → `concurrence_requested`, concurred → `concurred`, returned → `returned_by_office`, locked → `locked`, approval_uploaded → `approval_uploaded`.
- `severity` from §4.
- `title` and `body` from **a frozen copy** of today's `notifications.message()` inside the migration, never an import, so the migration doesn't change if the code does.
- `addressed_office`: the participant office the recipient held a post in for `submitted`, otherwise the initiating office. `addressed_position` is that post if still held, otherwise null, with the title snapshot either way.
- `dedupe_key = audit:{event_id}`. `created_at` and `read_at` kept as they are.
- `acted_at`, for action-required rows, is set only if current data shows the action done (e.g. the `locked` notice once the proposal is past `awaiting_signature`), and left null otherwise. For the three live rows that gives:
  - submitted on proposal 5: acted (the office decided)
  - concurred: info
  - locked: acted, since proposal 5 is now `package_returned`, past awaiting signature (checked read-only on the live database)

**No `notified` events are back-filled.** The genesis row says the log begins at the migration. Inventing past "notified" rows would put fabricated history in a tamper-evident chain.

**Verification on the copy:**
- the notification count is unchanged (3)
- every row has exactly one cause
- `verify_log system` passes
- the bell's count for each recipient is the same before and after

---

## 8. Also in Phase 2 (from the spec, for completeness)

- **The Encoder → Head step** (§5.6): a new status `with_head` between `draft` and `concurrence`, with audit kinds `sent_to_head`, `recalled` and `returned_to_encoder`. A Head who drafted, or an office with no Encoder, submits directly.
- **Surfaces:**
  - the bell in **all three portals** (today it is in the staff portal only)
  - a notifications page with filters (Action required / Info / All)
  - "Needs your action" on every dashboard, derived from state rather than from notifications
  - the action banner (returned items now; deadlines join it in Phase 3)
- **Staff home's awaiting count** becomes one aggregate query (your performance rule), and the notifications page is paginated. Both are measured against `seed_scale` before Checkpoint 2.
- **`seed_scale` gains** notifications in the new shape and a `SystemEvent` chain, so the bell, page and `run_monitoring` are measured at scale.

---

## 9. Questions before building

1. **`manual` on every notification.** `position_vacant` (and Phase 3's freeze notices) concern an office or a series, not one manual. Should `manual` be **required for every kind that concerns a manual and null only for `position_vacant`, freeze and digest kinds**, enforced by a check constraint naming those kinds? That's my recommendation. The alternative is to drop those notices to the system log only, without a notification.
2. **Who resolves an office's action notice.** I propose that **anyone entitled** resolves every copy for that office. Once the Head concurs, the Encoder's copy of `concurrence_requested` clears too, with `acted_by` naming the Head. Agreed?
3. **The Encoder's copy of Head-only actions.** For `concurrence_requested`, only the Head can act. Should the Encoder's copy be **info** (they can nudge, not act) rather than action-required? Spec §8.3 says an Encoder never sees a button they cannot use, which suggests yes. I recommend info for the Encoder, action for the Head.
