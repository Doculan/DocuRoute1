# Monitoring update — build spec (v4.2)

*Hand this to Claude Code with `CLAUDE.md`. Report first, build in the phases below, stop at every checkpoint.*

---

## 0. The shift

QMS CDMS stops presenting itself as a **pipeline an office moves a proposal through** and becomes a **monitoring system that makes it obvious who is behind**. Panelists want the system to nudge, and where appropriate escalate, so offices do their revisions, and to show who is late for deadline-driven revisions and for ordinary ad hoc proposals alike.

**Three priorities, in order:**

1. **Notifications** that are clear and actually reach the right people.
2. **Monitoring** that lets offices above see how every office and proposal is doing.
3. **Organisation and clarity**: every screen answers "what do I do now?", and keeps working with hundreds of offices, manuals and proposals at once.

**This is not frontend-only.** It needs new backend pieces: deadline records, a real notification system, a scheduled job, hierarchy-scoped monitoring endpoints and a richer audit trail.

---

## 1. Rules

1. All of `CLAUDE.md` applies: database first, report before changing, migrations tested on a copy with a backup, stop at checkpoints.
2. **Nothing touches the AI pipeline** (Layers 1–4, thresholds, fusion, wording file). Figures stay 0.978 / 0.854 and the fingerprint stays unchanged.
3. **Notify positions, not people.** Recipients are whoever holds the position now. A position with no current holder escalates (§5.5).
4. **Nudge, don't block reading.** Nothing may stop anyone reading a manual. Pressure comes from notifications, persistent action banners and escalation, never from locking the library.
5. **Scale is a design constraint from the start** (§9). Every list is server-filtered and paginated; every summary is an aggregate query, never a loop over rows.
6. **Reading-first design principles still apply**: sparse screens, short labels, details collapsed. The monitoring screens lead with counts and exceptions, not tables of everything.
7. Audit events are append-only. No edit or delete endpoint exists for them, for any role.
8. Tests that expect an error assert the reason; every new test is shown to fail without the code it protects.

---

## 2. Decisions to settle at Checkpoint 0

Claude Code reports what exists, then asks me these. Recommendations are marked ➜.

| # | Question | ➜ Recommendation |
| --- | --- | --- |
| 1 | What counts as an office having "met" a deadline? | Two milestones. **Office milestone = submitted for concurrence** (what the office controls). **Document milestone = made effective** (tracked, but delays after submission are blamed on whoever holds the stage). Also allow **Reviewed, no change** (§6.5) |
| 2 | Announcements vs deadlines | Two explicit kinds (§6.1). Announcements and deadlines are both banners, styled differently; deadlines are tracked obligations |
| 3 | Who is "the VP offices" for escalation? | The nearest approving-level office above the late office, plus QMS. Not the manual's owner, which can differ |
| 4 | Do VP and CAO offices need accounts? | Yes, to monitor. The demo organisation has none for the VPAF; add them, with monitor-only access unless also concurring |
| 5 | Is email available (SMTP from the university)? | Build in-app first. Email as an optional channel behind a setting, off until SMTP exists |
| 6 | Stage-aging thresholds | Provisional defaults, editable by the system admin: **with Head 3 days**, concurrence 7, awaiting signature 14, with IMR 7, with custodian 10 |
| 7 | Scale target | Design and test for 500 offices, 3,000 manuals, 5,000 open proposals, 100 concurrent users. Report SQLite results; see §9 |
| 8 | Change freeze: scope, what it blocks, who lifts it, what happens to deadlines inside it | §6.6 |
| 9 | During a freeze, may proposals already in concurrence keep collecting decisions (but not be made effective)? | Yes, so work in progress is not stranded |
| 10 | Should concurring and reader offices of a manual see a muted "Revision advised for {Office}" tag? | Yes, because they will be asked to concur (§6.7) |

---

## 3. Phase 0 — survey and scale harness

Report before changing anything:

- What exists for announcements (`Announcement`, `AnnouncementDismissal`, endpoints, screens, the derived `shows_as` rule) and how the three current rows would map.
- What exists for notifications (the derived "awaiting your office" list and badges) and what `AuditEvent` records today.
- The admin Proposals screen, the staff Proposals screens, the sign-up office picker and where "not sure" comes from.
- Whether any scheduler exists, and how a periodic job would run on Windows (Task Scheduler) and on a server (cron or a loop).
- Every query behind the admin dashboard and Proposals list, with row counts and any missing indexes.

Then build `seed_scale` (separate from `seed_demo_org`, tagged and clearable, refuses to run if real data exists): synthetic offices in a hierarchy, manuals, proposals in every status, deadlines, notifications. Phases 4 and 5 are measured against it. **Checkpoint 0.**

---

## 4. Phase 1 — sign-up office option (small, do first)

Replace "not sure" in the sign-up office picker with **"Office not listed"**.

- Selecting it shows one optional short field: *"Office name"* (60 characters).
- The account arrives in the system admin's pending list marked **Office not listed**, with the typed name, and the admin assigns the real office when approving. No office is created automatically.
- Nothing else about sign-up changes. Test: such a sign-up never receives access to any manual until assigned.

---

## 5. Phase 2 — notifications (priority 1)

### 5.1 Model

`Notification`: recipient user, the office and position it was addressed to (kept for history), `kind`, `severity` (**Action required** / **Info**), title, one-line body, link, created time, `read_at`, `acted_at`, `dedupe_key`, source event. Indexed on (recipient, read_at) and (recipient, severity, acted_at).

**Action-required notifications clear only when the action is done** (`acted_at`), not when read. Info clears when read.

### 5.2 Surfaces

- **Bell with an unread count** in every portal, and a notification page with filters (Action required, Info, All).
- **"Needs your action"** on every dashboard, derived from the current state of proposals and deadlines, so it can never be lost even if a notification was missed.
- **Deadline and action banner**: the consolidated deadline banner of §6.1 also carries anything **returned** to the office. A persistent coloured banner at the top of every page names it and links to it. It cannot be dismissed, only resolved. It sits visually apart from announcements, which are dismissible.
- **Email** as an optional second channel behind a setting.

### 5.3 What notifies whom

| Event | Recipients | Severity |
| --- | --- | --- |
| **Encoder sends a draft to the Head** | Head of the initiating office | Action required |
| **Head returns a draft to the Encoder** (internal), with the Head's note | Encoder(s) of the initiating office | Action required |
| Encoder recalls a draft before the Head acts | Head | Info |
| Proposal withdrawn | Initiating Head and Encoder, and every office already notified | Info |
| Proposal submitted for concurrence | Head and Encoder of every concurring office | Action required |
| **A concurring office returns a proposal** | **Head and Encoder of the initiating office**, with the returning office's name, the feedback excerpt, the section pointed at, a link | **Action required** |
| An office concurs | Head and Encoder of the initiating office | Info |
| Resubmitted as a new version | Head and Encoder of every concurring office | Action required |
| Locked, documents generated | Initiating office (Head and Encoder) | Action required |
| Scan uploaded, request ready for IMR | IMR position | Action required |
| IMR accepts or denies | Initiating office; all participating offices on a denial | Action required / Info |
| Package returned by the custodian | Initiating office | Action required |
| Made effective | Initiating office and every participating office | Info |
| Deadline created that targets an office | Head and Encoder of that office | Action required |
| Reminder before a deadline | Head and Encoder of each office still not met | Action required |
| Deadline passed, office not met | Head and Encoder of the office; **nearest VP-level office above; QMS** | Action required |
| A proposal stalled past its stage threshold | The office holding it; initiator as Info | Action required |
| A position with no current holder | Parent office's Head; the system admin | Action required |

Every notification writes an audit event ("notified"), and reading or acting writes another, so the trail shows who was told, when, and what they did.

### 5.4 Reminders, overdue and escalation

A single idempotent management command, `run_monitoring`, does all time-based work: reminders, overdue detection, stall detection, escalation. It must be safe to run every few minutes and twice in a row. Also evaluate opportunistically on dashboard load, so a missed scheduled run never leaves a deadline silently overdue. Document the Windows Task Scheduler setup in `DEPLOYMENT.md` and the demo checklist.

**Escalation ladder** (defaults, editable by the system admin):

1. 30, 14, 7, 3 and 1 days before: Head and Encoder.
2. Due day: Head and Encoder, action banner turns red.
3. Overdue: Head and Encoder, plus the nearest VP-level office and QMS, once. Repeats weekly while unmet.
4. A weekly digest to each Head and VP office: what is late, what is stalled, what is coming.

Dedupe so nobody receives the same reminder twice.

### 5.5 Edge cases to handle

- Position with no holder → escalate (above).
- Head on leave: **delegation**. A Head may name another position holder to act and receive for a dated period; recorded and audited.
- A person who holds several positions receives one notification per event, not one per position.

### 5.6 Encoder to Head: an explicit submission

Today the Head's Submit is the only handoff. Make the internal handoff a real step.

```text
Drafting (Encoder) --Send to Head--> With Head --Submit (password)--> In concurrence
        ^                               |   \
        |------ Return to Encoder ------+    '--> Withdraw
        '------ Recall (Encoder) -------'
```

- **Send to Head** is a button for the Encoder. It requires every changed section to have a **current AI check** and an acceptable overall reason, so the Head sees exactly what the Encoder read. Editing a section afterwards clears its check as it does today.
- **The Head** can **Submit** (password, unchanged) or **Return to Encoder** with a note. The return needs no password.
- **The Encoder can Recall** a draft while it is with the Head and the Head has not acted.
- **Withdraw** stays as built: the Head, before the lock, with a reason and password. A withdrawn proposal remains on record and appears in History.
- If the office has no Encoder, or the Head drafted it, the Head can Submit directly; no Send step is forced.
- **Every step notifies (§5.3), is tracked, and writes an audit event:** sent to Head, recalled, returned to Encoder (with the note), submitted, withdrawn.
- **"With Head" is a status of its own** (§7.2) with its own aging threshold (§2), so a proposal waiting on a Head is a visible bottleneck, with its days counted.

**Checkpoint 2.**

---

## 6. Phase 3 — announcements and deadlines (priority 1)

### 6.1 Two explicit kinds, one admin screen

The admin chooses a **Kind** when creating a notice. The old rule "no date = banner, date = Upcoming" is retired because it confused people. The three existing rows migrate to **Announcement**.

| | Announcement | Deadline |
| --- | --- | --- |
| Purpose | Information | An obligation that is tracked |
| Shown as | **Banner**, always. Dismissible per person | **Banner from the day it is created**, for the targeted offices, until the deadline is met. Also listed in the Deadlines panel and page |
| Targeting | All, or selected offices | All, selected offices, selected manual series or selected manuals |
| Ends | Optional expiry date | Due date |

**Banner rules (both kinds are banners, so they must look different at a glance):**

| | Announcement banner | Deadline banner |
| --- | --- | --- |
| Colour | Neutral blue | Calm while far off, **amber** when due soon (inside the reminder window), **red** when overdue |
| Dismiss | Yes, per person | **No.** It can be collapsed to one slim line, and goes away only when the deadline is met |
| Content | Title and short text | Deadline title and type, **due date and days left**, and the manuals still owed. Links to the manual or proposal |
| Who sees it | Targeted offices, or everyone | Head and Encoder of each targeted office that has **not yet met** it |

- **One consolidated deadline banner, not a stack.** An office with several open deadlines sees a single banner, "3 deadlines · next: ISO surveillance audit, 12 Nov (5 days)", that expands to the list. The most urgent sets its colour.
- At most **two banner rows** at the top of any page: announcements, then deadlines and action items (§5.2). Never a pile.
- When a deadline is met, its banner clears for that office immediately; other offices' banners are unaffected.
- Nothing about a banner blocks reading a manual.

### 6.2 Deadline fields

Title · **type** · due date · targets · **priority manuals** · note · reminder schedule (default from §5.4) · active.

**Deadline types:** a preset list plus **"Add your own"** (a custom type is saved and becomes selectable next time). Presets, with the basis for each:

| Type | Basis |
| --- | --- |
| ISO 9001 surveillance audit | Seen at Philippine SUCs: surveillance audits across the certification cycle, with recertification after it |
| ISO 9001 recertification | Seen at Philippine SUCs, at the end of the cycle |
| PRIME-HRM assessment (Civil Service Commission) | Seen: SUCs are covered, with Level I/II maturity assessments |
| AACCUP program accreditation / institutional accreditation survey | Seen at SUCs |
| CHED SUC Leveling submission | Seen at SUCs |
| CHED Institutional Sustainability Assessment (ISA) | Seen at SUCs |
| COA audit recommendations follow-up | Seen in SUC performance reporting |
| Internal quality audit | Standard ISO practice, **confirm with the QMS office** |
| Management review | Standard ISO practice, **confirm with the QMS office** |
| Periodic document review | Internal; see §6.5 |
| Citizen's Charter update (ARTA) | General knowledge, **confirm with the QMS office** |
| Other (custom) | — |

### 6.3 What "met" means

Per deadline, per targeted office (and per targeted manual when manuals are named), the screen shows the **office milestone** and the **document milestone** from §2 decision 1, plus **Reviewed, no change** when the office attests no revision is needed (see §6.5).

### 6.4 Priority manuals

The admin can mark specific manuals as **priority for specific offices** under a deadline ("Accounting Office: FAM 6.02 and FAM 6.04, due 15 Nov"). A priority pair is a targeted office-and-manual assignment: it appears on the office's dashboard and notifications, ranks first in the admin Proposals list, and is a row in monitoring.

### 6.5 Periodic review and "no change needed" (recommended)

Not every deadline produces a revision, and ISO expects documents to be reviewed. Add to each manual **last reviewed** and **next review due**, and let a Head record **Reviewed, no change** (password, optional note). That counts as meeting the deadline, is audited, and prevents offices being forced to invent revisions. A manual passing its review date can generate a deadline automatically.

### 6.6 Change freeze (audit periods)

A freeze is a **separate control from a deadline**: a deadline says "revise by this date", a freeze says "do not revise now". Do not start one automatically from a deadline.

- **Started and lifted only by the system admin**, with the password. It carries a **reason** and an **expected end date** that users see. It **stays in force until the admin lifts it**; if the expected date passes, the admin is reminded that it is still active.
- **Scope:** the whole system, selected offices, or selected manual series.
- **Blocks:** starting a new proposal, submitting to concurrence, and **making effective** (so controlled documents do not change mid-audit). **Never blocks reading.**
- **Still allowed:** editing and saving **existing drafts**, so preparation is not lost. Starting a new proposal, Send to Head and Submit are disabled and say why and until when. Proposals already in concurrence may continue to collect decisions but cannot be made effective until the freeze lifts. **[confirm at Checkpoint 0]**
- **Exceptions:** the admin can grant a named exception for one proposal or manual, for corrective actions raised by the audit. Audited.
- **Deadlines inside a freeze:** overdue notices and escalation are **paused** for affected offices, and the admin is prompted to extend the date.
- **Optional shortcut:** an audit-type deadline may offer "freeze from N days before through the audit". Off by default.
- Enforced on the server, audited (started, exception granted, lifted), with notifications to affected offices at start and end. A visible **freeze banner** (§6.1 rules: at most two banner rows, so it joins the action row) names the reason and expected end.

### 6.7 The deadline tag: visible wherever the manual appears

Any manual with a deadline, or advised for revision to an office, carries a **deadline tag** on **every screen that lists or opens it**. One shared component and one backend helper serve all of them, so no tab is missed.

**Wording and states** (always text plus colour, never colour alone):

| State | Tag |
| --- | --- |
| Deadline set | **Deadline upcoming 12 Nov 2026** |
| Inside the reminder window | **Deadline upcoming 12 Nov 2026 · 5 days** (amber) |
| Due today | **Deadline today** (amber) |
| Missed | **Overdue · was due 12 Nov 2026** (red) |
| Office milestone met | **Submitted 10 Nov** (muted); stays visible in History as "had a deadline" |
| Under a freeze (§6.6) | **Frozen for audit** (neutral), shown beside any deadline tag |

The deadline type ("ISO surveillance audit") shows on hover or expand. A manual with several deadlines shows the nearest plus **"+1 more"**.

**Who sees which tag:**

| Viewer | Sees |
| --- | --- |
| Head and Encoder of the **advised office** | **Deadline upcoming {date}**, plus "Advised by admin" and the note |
| Heads of offices **above** it, and VP-level offices | **Advised: {Office} · deadline upcoming {date}**, so they see who owes it. Up to two offices, then "+n" |
| QMS and admin | Same as offices above, for every office |
| Concurring and reader offices of that manual | Optional muted info: **Revision advised for {Office}** (they will be asked to concur). **[confirm at Checkpoint 0]** |

**Where it must appear** (the list is a checklist, not a suggestion):
My Manuals · the manual's section list · Sections search results · the section and manual view header · every Proposals list and the editor header · Monitoring rows (all lenses) · Home / dashboards · History rows · notifications · and in the admin portal, the Manuals and Organisation lists.

**Implementation rules:**
- One helper, `deadline_tags_for(user, manual_ids)`, computes tags **in bulk** for the manuals on a page (one query, never one per row), and every endpoint that returns manuals calls it.
- **A coverage test** enumerates every endpoint that returns manuals and fails if any lacks the tag field. Check what each screen actually calls, as with earlier route findings.
- Tags honour the viewer's scope: nobody sees another branch's deadlines.

**Checkpoint 3.**

---

## 7. Phase 4 — monitoring (priority 2)

### 7.1 Who sees what

- **Position holders** see monitoring for their own office and **every office beneath it** (read-only above their own work).
- **VP-level offices** see everything under them. **System admin and QMS** see everything.
- This is a new scoping helper in the backend, beside `offices_for` and `can_reach`, with tests that an office never sees a sibling or parent branch.

### 7.2 One status vocabulary

Not started · Drafting · **With Head** · In concurrence · Returned (by another office or by the Head; the row says by whom) · Awaiting signatures · With IMR · With custodian · Effective · Reviewed, no change. **Overdue** and **Stalled** are overlays, not statuses. Every row shows **who holds it now**, **how many days it has been there**, and **what it is waiting on** (e.g. "Concurrence: Budget Office, 9 days").

### 7.3 Screens

A **Monitoring** destination, not a pile of new tabs; overdue items are a filter of it, not a separate tab.

1. **Overview:** counts first. On time, due soon, overdue, stalled, returned and waiting. Every count links to its filtered list.
2. **By office:** the hierarchy as a collapsible tree, each office with its counts rolled up from beneath it, sorted so the most overdue appears first. Drill down to its manuals and proposals.
3. **By deadline:** one deadline, every targeted office, its status, who holds it, days late.
4. **By manual series and manual:** which offices are working on which, and which have not started.
5. **Office timeliness:** on-time rate, average days to respond to a concurrence request, overdue count. Presented as information, with the underlying proposals one click away.
6. **Advised revisions:** a lens inside Monitoring, **not a new tab**. It lists manuals the admin has advised specific offices to revise (§6.4): manual, advised office, deadline and type, status, who holds it now, days late. Heads and VP-level offices see their branch; an office sees its own. It also appears as a count on the Monitoring overview and as a column in **By office** and **By deadline**. Offices see the same items as tags on the manuals themselves (§6.7), and at the top of their own Proposals screen (§8.3).

### 7.4 Ordinary proposals too

Monitoring is not only for deadlines. Every proposal, deadline-driven or ad hoc, carries stage aging against the §2 thresholds, so a request sitting with one office for three weeks is visible and nudges that office even when no deadline exists.

### 7.5 Export

PDF and spreadsheet export of any filtered monitoring view, with its filters and the date printed, as evidence for audits.

**Checkpoint 4.**

---

## 8. Phase 5 — Proposals, rebuilt for admin and staff

The admin Proposals screen and the staff Proposals screen (Head and Encoder) share one idea: **what has a deadline comes first, and everything can be filtered.** Build one shared ranking and one shared row component; the two screens differ only in scope and in which actions each role may take.

### 8.1 Shared ranking: "Needs attention" at the very top

Order, applied the same way on both screens:

1. **Overdue** (most days late first)
2. **Due soonest** (a deadline within the reminder window, nearest first)
3. **Priority manuals** assigned by the admin (§6.4)
4. **Returned** proposals waiting for a redraft
5. **Stalled** proposals past their stage threshold
6. Everything else, by most recent activity

Each row shows: manual, series, **deadline and type** (or "no deadline"), **status** in the §7.2 vocabulary, **who holds it and for how many days**, a compact stage tracker, and **one primary action** that fits the viewer (see 8.3). A manual with a deadline but **no proposal yet** still appears, as **Not started**, so an office can see what it owes, not only what it has begun.

### 8.2 Admin and QMS

- **Filters, not a search bar:** office, manual series, manual, status, deadline, deadline type, priority, overdue, stalled. Remember each admin's last selection.
- "Needs attention" first (8.1), then the full list grouped by series and manual, paginated on the server, sortable by nearest deadline.
- Opening a proposal shows the **Next step** panel: who must act, what they must do, by when.

### 8.3 Staff: Head and Encoder

Scope is **the viewer's own office** (offices above use Monitoring, §7). The same filters as 8.2, limited to that office, plus **"Mine / my office."**

**Top section, "Due for submission":** every manual targeted to the office by a deadline, ranked as in 8.1, so the first thing the office sees is what it must submit and when. Then **"Awaiting your office"** (concurrence requests), then **"Returned to you"**, then everything else.

| Row state | Encoder sees | Head sees |
| --- | --- | --- |
| Not started | **Start proposal** | **Start proposal**, **Reviewed, no change** |
| Drafting | **Continue draft** | **Continue draft** |
| Draft, all changed sections checked, not yet sent | **Send to Head** | **Submit** (a Head may submit their own draft directly) |
| With Head | **Recall**, shown with days waiting | **Submit** or **Return to Encoder** (with a note) |
| Returned by the Head | **Redraft**, Head's note shown | View |
| In concurrence, another office pending | Which office, how many days | Same |
| Awaiting this office's decision | View | **Concur** or **Return** |
| Returned by another office | **Redraft** | **Redraft** |
| Locked, awaiting signatures | **Upload scans** | **Upload scans** |
| Overdue | Same action, row marked **Overdue** | Same action, row marked **Overdue** |

An Encoder never sees a button they cannot use. Where only the Head can act, the Encoder sees who is waiting on whom, so they can nudge in person.

### 8.4 History tab (offices, QMS and admin)

Proposals shows what is **active**; History shows what is **done**. A new **History** destination in the staff, QMS and admin portals.

- **What it holds:** every closed proposal: **Effective**, **Denied**, **Withdrawn**, and **Reviewed, no change**. Superseded drafts and versions live inside each proposal's audit trail, not as separate rows.
- **Grouping: Year, then Month.** The current year is expanded with its months; earlier years are collapsed with a count. Group headers show counts by outcome. Load a group's rows only when it is opened.
- **Filters:** date range on **closed date** or **submitted date** (a switch), with quick chips (this month, this year, last year) and a custom range; outcome; office; manual series and manual; deadline and deadline type; DCR number; initiated by (position).
- **Scope:** an office sees proposals it initiated **or took part in**, with a Mine / Participated toggle. Offices above see their branch (§7.1). QMS and admin see everything. Read-only.
- **Each row:** outcome, DCR number, manual and number of sections, initiating office, opened and closed dates, **days open**, **times returned**, and a link to the full audit trail.
- **Export** the filtered view as PDF and spreadsheet, with the filters and date printed.
- Paginated on the server, with counts from aggregate queries (§9).

**Checkpoint 5.**

---

## 9. Scale requirements (apply to every phase)

- Targets: **500 offices, 3,000 manuals, 5,000 open proposals, 100 concurrent users**, all dashboards and lists responsive.
- Budgets, measured against `seed_scale`: summaries under 500 ms; a list page under 800 ms; the bell's unread count is a single indexed count and polled lightly (about every 60 seconds and on navigation).
- Deadline tags (§6.7) are computed in bulk per page, never per row.
- All lists paginated and filtered on the server (50 per page); counts from `GROUP BY`; no query per row; indexes on every filter column, reported and added.
- Roll-ups for the office tree computed in one pass, not per node.
- **Decision flag.** `DEPLOYMENT.md` justified SQLite for 2–3 users. At this scale that justification no longer holds. Measure on SQLite first and report the numbers. If a budget is missed, recommend PostgreSQL through the existing `DATABASE_URL` setting. Do not migrate without asking.

---

## 10. Phase 6 — audit block, expanded

Today the block under a proposal lists who, action and time. Make it the document an auditor reads.

**Header summary:** initiated by (position, person, office) and when; days open; current stage and who holds it; number of versions; times returned and by whom; deadline linked, if any.

**Timeline, grouped by version**, one line per event, expandable. Each event records: time, **position first with the person's full name beside it**, office, action, the version, the sections affected, the stage it moved from and to, and the time spent in the previous stage.

**Events recorded:** created; section edited; AI check run (section, assessment fingerprint); **sent to Head; recalled; returned to Encoder (with the Head's note)**; submitted; **freeze started, exception granted, freeze lifted**; **notification sent, read and acted on**; concurred; **returned, with the full feedback verbatim and who returned it**; resubmitted; withdrawn; locked; documents generated (names and checksums); scan uploaded or replaced (uploader position, reason, checksum); IMR decision and comments; package returned and fixed; made effective (DCR section 5 values); deadline linked; reminder sent; escalated; marked overdue; reviewed, no change.

- **Filters:** action type, office, version, date range.
- **Tamper evidence:** each event stores a hash of the previous event, and a "verify trail" action confirms the chain is intact.
- **Export** the full trail as PDF and CSV.
- Append-only, as in rule 7.

**Checkpoint 6.**

---

## 11. Phase 7 — navigation and clarity pass (priority 3)

A lack of direction when clicking through is a design failure to fix.

1. **A role-based Home** that answers "what do I do now?": the day's actions first (needs your action, deadlines, returned items), then your office's status, then shortcuts.
2. **A consistent navigation structure per portal:**
   - Staff: Home · Manuals · Proposals (deadlines first, §8.3) · History · Notifications
   - Heads add: Office monitoring
   - QMS: Requests · History
   - Admin: Monitoring · Proposals · History · Deadlines & announcements · Organisation · Audit
3. **Breadcrumbs and a Back link** on every screen below the top level.
4. **A Next step panel on every proposal**, using the same stage tracker everywhere.
5. **Empty states that say what to do next**, not just that nothing is here.
6. **One status vocabulary and colour system** across all screens, as in §7.2.
7. Remove anything that duplicates another screen. Report what was removed.

**Checkpoint 7.** Re-run the end-to-end skill, and `check_setup.py`, and confirm the fingerprint and figures are unchanged.

---

## 12. Definition of done

- "Not sure" is replaced by "Office not listed", handled as in §4.
- Announcements are always banners. Deadlines are a separate, targeted, typed and tracked kind, with preset and custom types, priority manuals and escalation.
- A returned proposal notifies the initiating office's Head and Encoder with the feedback, and writes audit entries.
- Overdue deadlines notify the office, the VP-level office above it, and QMS, and keep nudging until resolved.
- Offices above can see every office beneath them, who holds each proposal, how long, and what it waits on, for deadline-driven and ordinary proposals.
- An Encoder explicitly sends a draft to the Head; the Head submits or returns it with a note; recalls, returns and withdrawals notify, are tracked and audited, and a withdrawn proposal appears in History.
- "With Head" is a visible status with an aging threshold.
- An admin can start and lift a change freeze, scoped to the system, offices or series, which blocks starting, submitting and making effective but never reading, with audited exceptions and paused overdue notices.
- A History tab for staff, QMS and admin groups closed proposals by year then month, with date, outcome, office, series and DCR filters, and exports.
- Any manual with a deadline or advised revision shows a **"Deadline upcoming {date}"** tag on every screen that lists or opens it, with the states in §6.7; a coverage test fails if an endpoint returning manuals omits it.
- Heads and VP-level offices see which offices are advised to revise which manuals, in Monitoring (Advised revisions lens, By office and By deadline) and as tags; an office sees its own on its Proposals screen and Home.
- The admin and staff Proposals screens filter by office, series, manual, status and deadline, and lead with what has a deadline: overdue first, then nearest due, then priority manuals. A manual owed but not started still appears.
- A Head or Encoder opens Proposals and sees their office's manuals due for submission at the top, each with the one action they may take.
- The audit block is detailed, filterable, exportable and tamper-evident.
- Performance budgets in §9 are met on `seed_scale`, or the PostgreSQL recommendation has been reported.
- Pipeline untouched: `check_setup.py` Ready, fingerprint `6a6a5c667a3c4d11`, `evaluate_folds.py` at 0.978 / 0.854.
