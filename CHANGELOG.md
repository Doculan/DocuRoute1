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
