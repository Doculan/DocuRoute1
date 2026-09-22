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

## [v4] — in progress

The rebuild: a dynamic organisation the system admin enters through
screens, three system roles, positions with dated assignments,
whole-manual proposals, concurrence, and the generated DCR. See `CLAUDE.md`
for the standing direction and `PROGRESS.md` for what has been decided.
