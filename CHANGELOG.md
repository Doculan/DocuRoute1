# Changelog

DocuRoute — a document-control system for the university's ISO 9001 manuals.

Versions here mark **foundations**, not releases to users. v3 is the
single-department revision tool; v4 rebuilds the organisation, roles and
drafting model around the official Document Change Request process
(F-QMS-001). The AI pipeline carries across both unchanged.

---

## [v3.0.0] — 2026-09-22

The last version of the one-department, one-admin revision tool. Tagged so
the state before the v4 rebuild stays recoverable.

**Measured performance, unchanged since it was first published:** 0.978
verdict accuracy and 0.854 issue micro-F1, both means of five folds. The
pooled 0.844 is used only for per-label tables.

### The assessment pipeline

- Four layers — rules, a fine-tuned transformer, retrieval against the
  manual, and a gradient-boosting fusion model over their outputs.
- The check is **mandatory before submission and runs once**. The submitter
  sees the result and agrees to it; the snapshot is stored and displayed
  thereafter, never recomputed. A revision shows the reviewer exactly what
  the submitter saw.
- Content hashing with a staleness guard: if the section or the submitted
  text moves after the check, the submission is refused rather than judged
  on text nobody read.
- The same rule applies on the upload and merge paths, where the submitter
  is agreeing to content they did not type, so both hand the extracted or
  merged text back with the result.
- Clause 6.3 is enforced at the API in two tiers — a blank or throwaway
  reason is refused; a vague but real one is flagged for the reviewer
  rather than blocking a legitimate change.

### The staff portal

- Five tabs: Dashboard, My Manuals, Sections, My Revisions, Help.
- Section search across every manual the person can reach, for people who
  know the content but not which document holds it.
- A dashboard that leads with what needs attention and what was last open,
  and shows nothing where there is nothing to show.
- A document voice: serif for the manual's own text, marks a person with a
  red pen would actually make, and a diff that survives greyscale —
  strikethrough and underline carry the change, colour only reinforces it.

### The admin portal

- Users, departments, manuals, sections, revisions and model health.
- Announcements with a computed banner/upcoming split, so the admin list
  and the staff dashboard cannot disagree about which a notice is.
- A dashboard on one summary endpoint, with an activity chart that
  degrades to a table when the history is too thin for a line to mean
  anything.
- Re-authentication before anything irreversible: the password buys a
  short-lived signed token, held in memory only and never stored.
- Section history records **why** each version exists — an approved
  revision, a direct edit, a merge — with the reason copied rather than
  referenced, so deleting a revision cannot erase the record that the
  document changed.

### Setting up

- `import_mastercopies`, `make_admin` and `seed_test_users` rebuild a
  working database from the committed master copies, since `db.sqlite3` is
  not in version control.
- `seed_activity` fills the dashboard chart for a demonstration and
  `--clear` removes exactly what it wrote.

### Known limits at v3

- **No router.** Navigation in both portals is React state, so URLs are not
  shareable, reloading returns to the default page for the role, and the
  browser back button works only for the manual → sections drill-down.
- **One flat `Department`.** No hierarchy, no positions, and access is
  scoped by the single department on a user's account.
- **`is_staff` is overloaded.** Four endpoints use Django's `is_staff` flag
  as a cross-department escape hatch, while the application's own "staff"
  role means the opposite. See the v4 Phase 1 report.
- **Revisions are per section.** The official DCR names a document, so
  whole-manual proposals arrive in v4 Phase 2.
- **Coordinated changes across sections** are each checked against the
  current manual, so `contradicts_manual` can fire on correct work. The
  planned interim answer is an advisory, not a retrieval change.

---

## [v4.0.0] — 2026-09-24

The rebuild around the official Document Change Request (F-QMS-001). A
change is proposed by an office for a whole document, agreed by the other
offices that work with it, signed on paper, decided by the IMR and made
effective by the Document Custodian. Phases were tagged on the way:
`v4.0.0-p1` (organisation), `v4.0.0-p2` (proposals and concurrence),
`v4.0.0-p3` (generated documents and signed copies).

**The AI pipeline is unchanged:** 0.978 verdict accuracy and 0.854 issue
micro-F1, fingerprint `6a6a5c667a3c4d11`. Each changed section is checked
through the same `assess_texts()` call as before.

### The organisation, entered as data

- Offices in a hierarchy, with approving levels, deactivation and merging —
  never deletion — and their past names kept, so history reads correctly.
- Positions (Encoder, Head, IMR, Document Custodian) held by people through
  dated assignments, acting / OIC included; exactly one current Head per
  office. People sign up with a purpose statement and are approved.
- Three system roles choose the portal: system admin, QMS staff, users.
- Manual series and their documents, owned by an approving-level office,
  with concurring and reader offices inherited by each document unless it
  overrides them.
- Nothing about the university is in code: the tables start empty and the
  system admin fills them through screens.

### Proposals and concurrence

- One proposal per document, each changed section with its own mandatory
  AI check; editing a section clears only that section's check.
- Submitting freezes who must agree. Every concurring office concurs or
  returns with feedback all offices read; a return makes a new version and
  every concurrence starts again. One decision per office per version,
  refused a second time.
- One open proposal per office per document, held by a database constraint.
- The password is asked again before submitting, concurring, returning,
  withdrawing, deciding and making effective — not on drafting or checking.

### Locking, documents and signed copies

- The last concurrence locks the text, numbers the request and generates the
  pre-filled DCR, the draft copy and the concurrence annex inside the same
  transaction; a generator that fails takes the lock with it.
- Generated documents print position titles, never names, and are checked
  for repeated parts and personal properties before they are stored.
- Signed scans are uploaded, and a replaced one is kept as superseded, never
  overwritten. The system records who uploaded what; it does not verify
  signatures, and the screen says so.

### The QMS portal

- The IMR accepts or denies; a denial's reason is read by every office.
- The approving authority's signed DCR is uploaded after acceptance.
- The Document Custodian records section 5 and makes the change effective —
  the text changes, the history names the DCR, readers see the new revision
  and effectivity date — or returns the package for a defect in a signed
  copy. A starting status can be corrected, with a reason, until a change
  has been made effective; the corrected record is kept.
- Versions and revisions only move forward: a lower version is refused, and
  within a version a lower revision.

### Kept for the transition

The v3 single-section revision flow and department-based access stayed
behind a switch, so the live data could move over when ready. Removed in
v4.1.0.

---

## [v4.1.0] — 2026-09-25

The transition finished: v4 alone, no switch and no v3 flow.

- **Access is by position, permanently.** The switch between department and
  position access is removed, with its screen and readiness gate.
- **Departments are retired**: the model, its screen, the department field in
  sign-up and user management, and department-targeted announcements
  (announcements now target offices). A new document starts unassigned.
- **The v3 single-section revision flow is removed** — its endpoints, the
  admin's Revisions review screen and the staff's revision screens. Reviewing
  belongs to the IMR and the Document Custodian. The admin's section merge
  went with it; it returns with adding and deleting sections through
  proposals.
- **v1 is removed**: the `REVISION_AI_PIPELINE` setting, the v1 model code,
  its training scripts, datasets and metrics. v1 remains in the `v3.0.0`
  tag. The four-layer pipeline and the SVM section classifier are unchanged;
  fingerprint `6a6a5c667a3c4d11`.
- **Dashboards read proposals**: what waits on a person's offices, recent
  proposals and activity.
- **Fixed:** the pre-assessment sweep would have deleted every proposal's
  stored AI check after a week; it now keeps any check a section change
  points at.
- Migrations `0031` (refuses to run while a v3 revision exists) and `0032`.
  Test accounts with no references may be deleted before go-live; nothing
  else in the organisation is.

---

## [v4.2.0] — Unreleased

QMS CDMS becomes a monitoring system: notifications, deadlines with banners
and tags, monitoring for offices above, rebuilt Proposals, an explicit
Encoder-to-Head step, History, a change freeze, an expanded audit trail and a
navigation pass. Specified in `MONITORING_UPDATE_SPEC.md`. The AI pipeline is
not touched (fingerprint `6a6a5c667a3c4d11`; 0.978 / 0.854).

- Phase 0: survey (`MONITORING_PHASE0_REPORT.md`) and the `seed_scale`
  harness, synthetic and exactly clearable. Migration `0039` records which
  seeder wrote each `DemoRecord`, so clearing one never removes the
  other's rows. Tagged `v4.1.1` before it.
- Phase 1: sign-up offers **Office not listed** with an optional office name
  (60 characters) for the admin, and the office picker is searchable and
  grouped by branch. Such an applicant reaches nothing until assigned.
  Migration `0040`.
- **Fixed:** the admin's Proposals screen showed only the six most recently
  updated proposals. It now lists every proposal, paged and filtered by
  status, office and series. Migration `0041` adds the indexes it uses.
- Phase 2A: **notifications rebuilt.**
  - Action-required notices stay until the action is done; info clears
    when read.
  - Each notice stores its own text and names its manual and the post it
    was addressed to. One notice per person per thing.
  - A bell in every portal, a notifications page, and "Needs your action"
    derived from the data.
  - The IMR's and custodian's decisions now notify.
  - A hash-chained system activity log records who was told, read and
    acted, with `system` as its own actor.
  - `run_monitoring` flags stalled proposals and vacant posts (schedule
    "QMS CDMS monitoring").
  - Migrations `0042`–`0044`.
- Phase 2B: **the Encoder-to-Head step.**
  - The Encoder sends a ready draft to the Head; it is then "With the
    Head" and frozen. The Head submits it (password) or returns it with a
    note; the Encoder can recall it until the Head acts.
  - A Head submits a draft directly only when they drafted it, or the
    office has no Encoder.
  - Each step is recorded and notifies. With no current Head, the office
    above and the system admin are told; with no current Encoder, the
    Head is.
  - "With the Head" counts as a stall after 3 days.
  - A persistent action banner names work returned to the office, until
    it is sent on.
  - Migration `0045`.
- **Fixed:** a proposal's last activity (`updated_at`) never moved after it
  was created, because transitions saved only their status.
- The QMS landing shows its queue as counts that open Requests.
- **Fixed:** admin Proposals rows could not be told apart when one document
  had several proposals from one office, and the status filter listed
  "Closed" beside "Withdrawn". Rows now carry the DCR number or start date,
  and group and single-status filters are separated. No proposal had been
  listed twice; a test now guarantees each appears exactly once.
- Phase 3A: **deadlines and announcements.**
  - The admin sets deadlines by type, due date and reminder days, aimed
    at every concurring office, an office (and optionally everything
    beneath it), a series or named manuals. Each becomes an obligation
    per office, met when the office submits a proposal and naming the
    proposal that met it. A withdrawal reopens it.
  - Saving shows who will be told first, then notifies each office.
  - Announcements go to everyone or to offices, expire, and are
    deactivated rather than deleted.
  - Two banner rows: a pinned action row (deadlines, most urgent first,
    and returned work) that cannot be dismissed, and an announcement row
    beneath it that can.
  - The approving offices are told when a request is denied or made
    effective.
  - Migration `0046`.
- Phase 3B-1: **the deadline tag.** A manual with a deadline carries a
  tag worded for the viewer: the office that owes it, the offices above
  it, the QMS and the admin, or offices that concur on or read it;
  another branch sees nothing. It shows on the manual view, Sections
  search, Home, Proposals and the editor, Needs your action, the banner,
  notifications, and the admin's Proposals, organisation and deadline
  screens. A test walks every route and fails on any manual without
  one.
- **Fixed (tests):** a test that commits no longer removes the rows the
  migrations insert for the tests after it.
- Phase 3B-2: **the long lists rebuilt.** My Manuals, the QMS and admin
  Manuals lists, Awaiting, Involving, Requests and the organisation's
  document lists open on a summary or a page of 50, filtered on the
  server, each with its deadline tags. My Manuals leads with Recently
  opened, then the series, folded except the one with most deadlines.
  Requests shows its counts first. At full scale the slowest went from
  8.7 s to under 75 ms.
- Admin Manuals sorts on the server and filters by an upload-date range,
  on new indexes (migration `0047`).
- Phase 3C-1: **the deadline ladder, priority manuals and reviews.**
  `run_monitoring` reminds an office on each of a deadline's reminder
  days and on the due day, tells the Head above when it is overdue, and
  at a week late the approving office and the QMS (weekly after that),
  with fallbacks to the President's office and the system admin; every
  notice clears when the office meets the deadline. The admin can mark
  priority manuals for an office. A Head can record "Reviewed, no
  change" on a document (with the password), which meets the office's
  deadlines on it and sets its review dates. An optional monthly step
  gathers documents past review into a deadline. Migration `0048`.
- **Fixed:** the admin's list of a deadline's obligations put met ones
  first.
- `run_monitoring --dry-run [--as-of YYYY-MM-DD]` lists what a run would
  send and writes nothing; `--as-of` on its own is refused unless
  `QMS_ALLOW_AS_OF` is set on a demo database. A dashboard's own catch-up
  run is now tested to include the deadline ladder.
- Phase 3C-2: **delegation.** A Head on leave - or the system admin -
  names a post holder in the office, or the Head above, to act as Head
  for a dated period, with the password. The delegate submits, concurs
  or returns and receives the Head's notices; each step is recorded as
  theirs, acting for the Head, and shown "(delegated)"; forms still print
  titles only. A delegate may not act as the Head on a proposal they
  drafted or sent to the Head. Periods never overlap and are never
  deleted. Migration `0049`.
- The admin's People screen is paged on the server: counts first, the
  sign-ups awaiting approval on top, then 50 people a page with search
  and office, branch, status and position filters. At full scale it went
  from 1.0 s and 1,912 queries to 12 ms and 8.
