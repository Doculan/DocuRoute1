# Revision AI Overhaul — Progress

Working log for the plan in `REVISION_AI_OVERHAUL.md`.
**Read both files at the start of any session.**

---

## Ground rules (in addition to the spec's section 0)

- Never print or open whole dataset files or large logs. Use counts,
  `head -n 5`, or the sampler. Exception: when a full read is genuinely
  needed to make progress, say so first.
- Update this file after every phase and every decision: findings,
  approved decisions, deviations, known issues, resume commands.
- Stop at every CHECKPOINT and wait for go-ahead.
- **A test that expects an error must assert the reason** - the field or
  the message - not only the status code. A 400 is not a claim about
  anything. The example: `test_a_document_override_must_still_be_an_approving_office`
  checked only for 400 and passed on an unrelated blank-field error, so
  for one run it asserted nothing while looking green.
- **A test that passes must be shown to fail without the thing it
  tests.** Remove or break the behaviour, watch the test go red, put it
  back. Green on its own proves only that nothing raised. Two cases so
  far: the approving-level test above, passing on a blank-field error;
  and the 3a transaction guard, passing because Django's `TestCase` wraps
  every test in a transaction, so the guard's condition could never be
  met. Record the demonstration in the phase notes.
- **A staleness check must compare against live state**, never two stored
  values. `SectionChange.check_is_current` first compared the change's
  stored hash with the assessment's stored hash - which is comparing the
  check with itself. Always true, so every edited section reported as
  checked and the guard did nothing. Fingerprint what is there *now*.
- **Read the output you asked for.** The same review reported "no titles
  have stray whitespace" from a command whose result had been cut off by
  `tail`. `FAM 8.03` had a trailing space, and the duplicate-detecting
  importer found it afterwards. Absence of evidence in a truncated
  output is not evidence.

---

# ═══════════════════════════════════════════════════════════
# v4 REBUILD — multi-office document control
# ═══════════════════════════════════════════════════════════

*Standing direction: `CLAUDE.md`. Current spec: `PHASE1_ORGANISATION_SPEC.md`.
Background: `MULTI_OFFICE_WORKFLOW_PLAN.md`.*

*This section is the current work and leads the file. Everything after the
**v3 log** divider below is the previous foundation, kept because the AI
pipeline and both portals carry across unchanged — it is history, not
direction.*

`v3.0.0` is tagged at `ff03583` — the last state before this work.

---

## Phase 1b design — approved 2026-09-22

**The series level.** What the application called a "manual" is a
*document within a manual series*. The blank format's header keeps MANUAL
TITLE and DOCUMENT NO. in separate cells, and the database agreed: **ten
FAM documents sat in two different v3 departments** (CAS and CME).
"Department" was naming the document family and naming who works on it at
once. `ManualSeries` separates them, and turns 19 sets of links into 5.

**Inheritance needs no new column for the owner.** `Manual.owning_office`
was already nullable; null now means *inherit from the series*, and a
document with **no series and no owner** is what "unassigned" means —
which is all nineteen, so nothing had to be backfilled.

**Office links: replace-all** (`Manual.offices_overridden`). A document
either inherits the whole set or owns the whole set. Not per-office
exclusion, because the concurrence list, the notifications, the frozen
participant list and the audit trail all read this: one branch is
something four readers get right, a set difference is something four
readers get subtly differently. Its cost — a later series-level addition
skipping overridden documents — is real, so the series screen names the
documents that will not receive the change.

**No header metadata.** Generated drafts leave VERSION NO., DOCUMENT NAME,
REVISION NO., EFFECTIVITY DATE and PAGE NO. blank for hand-filling. No
columns for any of them; document status becomes real data in P4 when the
custodian records it.

**Three checkpoints** — 1b-i model and Offices, 1b-ii series and
documents, 1b-iii people and positions.

---

## Data cleanups — 2026-09-22

Done before series links are entered, since all three are cheaper to fix
before than after.

**`COE` retired as a duplicate.** Manual id 219, pointing at
`HRM_4_MoGMsSE.02.pdf`. **MD5-identical** to `HRM_4.02.pdf` — both
`6fd175…7723`, 375,187 bytes. Referenced by nothing: no revisions, no
section history, no pre-assessments, no recently-opened rows, no
announcements. Its extraction was also the worse of the two — 5 sections
against HRM 4.02's 17, two of them empty. Deleted.

> The duplicate **PDF is still on disk** and untracked. A fresh clone will
> not have it, but `import_mastercopies` on *this* machine would recreate
> the same phantom document. Worth removing.

**`FAM 8.02 Evaluation of External Providers` → `FAM 8.02`.** The source
header settles it: DOCUMENT NO. is `FAM 8.02`, and "Evaluation of External
Providers" is the DOCUMENT NAME, a separate cell.

**`ASM 3.0` → `ASM 3.00`.** The rule was "leave it unless the source shows
a different number", and the source does: its header reads `ASM 3.00`. A
document number is a controlled identifier, so it follows the document.

**19 manuals, 198 sections** after the cleanups.

The headers also give the series titles, for whoever enters them: ACADEMIC
SERVICES MANUAL, FINANCE AND ADMINISTRATION MANUAL, HUMAN RESOURCE MANUAL,
STUDENT DEVELOPMENT MANUAL.

---

## The duplicate cannot return — 2026-09-22

`HRM_4_MoGMsSE.02.pdf` deleted from disk (19 tracked files, 19 on disk).

`import_mastercopies` now **identifies a PDF by its bytes, not its name**.
Two lookups, because a duplicate arrives from either direction: the same
contents already in the database, or the same contents twice in the
directory under different names. The second is what matters on a fresh
clone, where the first has nothing to say.

Verified against the real case — restoring the duplicate and running a dry
run reports:

```
dup     HRM 4 MoGMsSE.02    same file as "HRM 4.02"
```

Same bytes under the *same* title stays "already imported": calling an
ordinary re-run a duplicate would make the word meaningless on the run
where it matters.

### Open — the ASM correction is not reproducible

The database says `ASM 3.00`, taken from the document's own header. The
file on disk is still `ASM_3.0.pdf`, and `_title_for` derives the title
from the filename — so **a fresh clone would import it as `ASM 3.0`**, and
the correction would not survive a rebuild.

That defeats the purpose of the importer, which exists so a rebuilt
checkout matches everyone else's. The fix is to rename the master copy to
`ASM_3.00.pdf` and repoint `Manual.file`; not done, because renaming a
tracked controlled document is a decision rather than a cleanup. **Decide
before 1b-ii finishes**, or the divergence gets entered into series links.

---

## Phase 1b-i — what was built (awaiting Checkpoint B1)

### Models

`ManualSeries`, `ManualSeriesOffice`, and an abstract `OfficeLink` holding
the relationship vocabulary that both link tables share — declared once so
the two cannot drift apart in a way that stays invisible until a
concurrence list comes out wrong.

`Manual` gains `series`, `offices_overridden`, and `approval_stops_at_owner`
becomes **three-state**: null (inherit), true (stop at the owner), false
(continue upward). An override has to work in both directions or it only
half exists.

Resolution lives on the model — `effective_owner`, `effective_office_links`,
`concurring_offices`, `reader_offices`, `approval_route`,
`can_be_proposed_against`. Later phases ask the same three questions about
every document, and each one answered separately from raw columns is a
chance for two screens to disagree.

> **A name collision worth remembering.** The first version called the
> method `office_links`, which is already the reverse accessor for
> `ManualOffice.manual`. Django's descriptor silently shadows a method of
> the same name, so it returned a manager and failed six tests with an
> error that named neither. Renamed `effective_office_links`, matching
> `effective_owner`.

### The migration that changes a meaning

`approval_stops_at_owner` was `default=False` in 1a — two states, and every
row got False. Null now means inherit, so those nineteen Falses would have
read as *"this document explicitly does not follow its series"*. Nobody
chose them: the field arrived with a default and no screen. Migration 0020
sets them back to null, and reversing restores the two-state field.

Verified on a copy: **19 of 19 with no series, no owner, not overriding,
and `approval_stops_at_owner` null** — no False survived. Every existing
row count unchanged.

### Offices

`api/organisation_views.py`, kept out of `views.py` — which is already
2,800 lines of the v3 application, while this belongs to a part that did
not exist before and will outlive most of it.

**There is no delete endpoint, and there will not be one.** Deactivate, or
merge into the office that took the work over.

- **Deactivating is refused while active children remain.** Retiring an
  office out from under the units reporting to it would leave them
  orphaned in the tree with no sign of why.
- **Merging is two calls** — GET previews what moves, POST moves it. A
  merge rewrites ownership, office links, positions and children in one
  go, and the admin should see the list before agreeing rather than after.
- **Duplicate links are dropped, not re-pointed.** Where both offices
  relate to the same series, re-pointing would break the unique constraint
  and fail the whole merge; the surviving office's relationship is the one
  that keeps applying, and the preview says how many were dropped.
- **Merging upward is refused.** It would put the surviving office inside
  the one being retired, and reparenting the children would then form a
  cycle.
- **Re-authentication on moving, deactivating and merging. Not on creating
  or renaming** — a prompt on routine work is how people learn to type the
  password without reading it.

`IsSystemAdmin` reads **`system_role`**, not the v3 `role`: this is the
first code written against the new field, and a v3 admin who was never
made a system admin configures nothing.

### The screen

`Offices.jsx` — a tree assembled client-side from the flat payload, since
a nested response would have to pick a shape for a hierarchy of no fixed
depth and every picker wants the flat list anyway. An office whose parent
is missing from the list (the usual case: an inactive parent while
inactive rows are hidden) is shown at the top level rather than dropped.

Retired offices stay listed at reduced weight. Row actions appear on
hover but stay reachable by keyboard and are always visible on touch — a
control that exists only on hover does not exist on a tablet.

The **Organisation** nav group is hidden rather than disabled for
non-admins: a disabled group is an invitation to wonder what is behind it.
`login` now returns `system_role` alongside `role`; it decides which nav
groups appear and nothing else, since every endpoint checks for itself.
Server-side routing replaces the stored copy at 1c.

### Merging two offices that both have someone in post

Asked at the checkpoint, and the answer was **not** what the design
intended. The retired office's conflicting position was deactivated, but
its assignment was **left open** - `ends_on` null, still reading as
current. Someone would go on being the current Head of an office that no
longer operates, and every reader asking "who holds this now" would
believe it.

The QMS case looked correct by accident: a conflicting IMR stopped
counting as QMS staff, but only because `holds_current_qms_position`
filters on `position__is_active`. That is a property of one query, not of
the record - any other reader still saw an open assignment.

Now: conflicting assignments are **ended with today's date** before the
position is retired, and the preview **names the people** whose posts
would end rather than reporting a count. Ending someone's appointment is
not a side effect to discover afterwards.

Untouched, deliberately: the surviving office's own holders, assignments
that ended earlier (they keep the date they actually ended, not the date
of the merge), and non-conflicting positions, which move across with their
holders still in post.

### Test state

**234 API tests pass**, 44 of them new. The inheritance ones carry the
weight: that an override *replaces* rather than merges, that override rows
are ignored until the flag is set, that an overriding document does not
receive a later series change (the known cost, asserted so it stays
known), that an override owner is held to the approving-level rule, and
that the approval route skips non-approving offices without ending the
walk.

**Nothing has been run against the real database.**

---

## Phase 1b-ii — what was built (awaiting Checkpoint B2)

### Office links are set as a whole set

`PUT`, not add-and-remove. The relationship being edited **is** a set -
`offices_overridden` means "this document's set replaces the series' set"
- and a row-at-a-time editor would let the screen sit half-way through a
change describing a set nobody chose. One call, one state, and the editor
puts every office on screen with its relationship or none.

A refused call writes nothing: the office ids are checked before the
transaction opens, so a typo in one row does not leave the other rows
applied.

### The cost of replace-all is reported where it is incurred

Changing a series' offices returns `did_not_reach` - **the documents that
override, by title**. The admin is told at the moment of the change, not
left to discover it. The series list and the series page carry the same
list.

Handing a document back to its series **deletes its own rows**. Leaving
them would mean the next person to switch the override on silently
inherits a set somebody chose months ago.

> Worth knowing: handing back gives the series' **current** offices, not
> the ones the document had before it overrode. That is the right
> behaviour - the series is the source of truth - but it is the kind of
> thing someone may expect to work the other way.

### An orphan document cannot be left with nobody

A document with no series has nothing to fall back on, so an empty
override set would mean nobody could ever change it. Refused as a
mistake rather than accepted as a choice.

### A rehearsal on a copy, with the real nineteen documents

Not a test - the tests prove the rules hold. This asked whether the
screens can do the job:

```
8 offices entered (OP > VPA, VPAA > ASO, BO, HRO, REG, SAO)
4 series, owners set, office links set
19 of 19 documents placed          unassigned: 0

FAM 6.02  owner VPA (inherited)  concurring ASO, BO  readers REG
          route VPA -> OP        proposable: yes

override FAM 6.02 to BO only     -> series change reports
                                    did not reach: ['FAM 6.02']
hand it back                     -> concurring ASO, BO again
```

Every document placed on its prefix, which the earlier title cleanups are
what made possible.

### A v3 field that could not be validated

`Manual.uploaded_by` was `null=True` **without `blank=True`**, so the
database accepted a manual with no uploader while `full_clean()` refused
one. Nothing had validated a Manual before, so nothing had hit it. Fixed
to match (migration 0021, no schema change).

It surfaced through a second defect: the validation errors were being
joined **without their field names**, so the message read "This field
cannot be blank" and named no field. That is a message nobody can act on,
and it hid this bug for a test run - and one new test was passing on it,
expecting a 400 for the approving-level rule and getting a 400 for the
blank field instead. The handler now names the field, and that test
asserts the message rather than the status.

### Test state

**261 API tests pass**, 27 of them new in `tests_series_api.py`.

**Nothing has been run against the real database** since migration 0020.

---

## Phase 1b-iii — what was built (awaiting Checkpoint B3)

### The three things this phase was asked to confirm

**One home for the QMS positions, by data.** IMR and Document Custodian
are positions like any other, attached to whichever office the system
admin chooses. The two QMS offices on the 2022 chart having merged means
both are entered against one office - and **nothing in the code says so**.
Tested in all three shapes: both in one office, both held by one person,
and split across two offices again.

Per series resolution is **not built and not prevented**. There is one set
of QMS positions and whoever currently holds them acts on everything;
routing per series would be a field on `ManualSeries` pointing at an
office, and nothing in `people_views.py` would have to change.

`SOLE_HOLDER_KINDS` stays `(HEAD,)`, so two people may currently hold the
IMR post - the permissive choice until question A is answered.

**Acting / officer-in-charge** is a flag on the assignment. Somebody signs
the Head's block while a post is vacant, so the system has to record that
without either pretending the appointment was permanent or refusing it.

It changes **nothing about what the holder may do** - an OIC concurs for
the office exactly as a substantive head does, and still blocks a second
current head, or it would be a way around the rule. The difference is what
the record says afterwards, which is the point of dated assignments.

**Concurrent heads work.** One person can hold two offices' Head posts at
once: the constraint is per *position*, and each office has its own. The
same office still cannot have two current Heads, and the refusal now
**names who holds it** and what to do - a constraint reported as a
database error is something nobody can act on.

### Deactivating a person

Ends every current post with today's date and keeps the record. The same
shape as the merge fix: an assignment left open is a standing claim that
someone still holds a post.

Reactivating **does not restore the posts**. They ended on a date, and
re-opening them would rewrite what the record says happened - so the admin
assigns again and the gap stays visible.

The system admin cannot deactivate themselves: nobody would be left who
could configure anything, and the recovery is a shell.

### Two defects found while testing

**An `IntegrityError` poisoned the transaction.** `assign_position` catches
the one-current-holder constraint to turn it into a readable message - but
the follow-up query that names the current holder could not run, because
the failed insert had broken the surrounding transaction. The handler
failed on exactly the case it exists for. Fixed with a savepoint around
the insert; it would have failed the same way inside any atomic block in
production, not only under `TestCase`.

**A date from JSON is a string.** `ends_on < starts_on` raised `TypeError`
rather than comparing, because one side came from the request body and the
other from the model. Both are parsed before anything is compared.

### Personal data

Sign-up now asks for a full name, with the purpose statement beside it:
why it is collected, who can see the list, and that people who leave are
deactivated rather than deleted. Stated once, where the data is collected,
rather than repeated on every screen.

The full people list is system-admin only.

### Test state

**295 API tests pass**, 34 of them new. Migration 0022 adds one column and
changes no row.

**Not run against the real database.**

---

## No reset. Test data cleared instead — 2026-09-22

The comparison settled it: 198 of 198 sections already match a fresh
extraction, so a reset would have replaced the content with the same
content. Decided against, and the development data cleared instead so v4
starts clean.

Backup at `Backend/db.sqlite3.bak-20260922-pre-clear-testdata`.

```
ManualRevision           6 -> 0
SectionHistory           3 -> 0
RevisionPreAssessment    1 -> 0
RecentlyOpened           3 -> 0

kept: 19 manuals, 198 sections, 7 departments, 6 users, 3 announcements
      and the whole (still empty) organisation
```

Worth naming: **the three history rows were not dependents of the
revisions.** They came from direct admin edits to two `SDM 3.06` sections,
on a document none of the revisions touched. Clearing them was still
right - they are development data - but it means those two sections no
longer carry the text they held before those edits.

The **three announcements were left**, not being on the list. They are
probably test data too.

### Approved for the upload work — not built yet

Upload reads the document's own header:

```
MANUAL TITLE   ACADEMIC SERVICES MANUAL
DOCUMENT NO.   ASM 3.00
DOCUMENT NAME  CURRICULUM DEVELOPMENT, REVIEW AND VALIDATION
```

shows what it found, the uploader confirms, and the series is matched by
code. **The filename is a fallback only, never authoritative** - which is
the whole divergence class that produced `ASM 3.0` and
`FAM 8.02 Evaluation of External Providers`, removed at the root.

---

## Reset report — requested, nothing reset

### 1. Every extraction fix is in the pipeline

Tested by re-extracting **all nineteen documents** from their PDFs through
the real upload path (`extract_text` then `_split_into_sections`) and
comparing subtitle and content against what is stored:

```
198 sections compared
198 identical
  0 differing
  0 documents whose section count changed
```

Including the ASM table reassembly, header stripping, glue-word repair,
merged-step splitting and subtitle cleaning. **A reset re-uploading the
same PDFs reproduces today's text byte for byte.**

`reextract_manuals` and `clean_section_content` both call the same
pipeline functions rather than carrying their own rules, which is why
this holds. Title normalisation is the exception — it is **not** in the
pipeline: `_title_for` derives a title from the filename, which is why
`ASM_3.0.pdf` had to be renamed to `ASM_3.00.pdf` for that correction to
survive an import.

### 2. What a reset removes, and what it keeps

Everything hangs off `ManualSection` by CASCADE:

| Removed with the sections | Now |
|---|---|
| `ManualRevision` | 6 |
| `SectionHistory` | 3 |
| `RevisionPreAssessment` | 1 |
| `RecentlyOpened` | 3 |

Untouched, because none of it hangs off a manual: `Office`, `Position`,
`PositionAssignment`, `CustomUser`, `ManualSeries`, `ManualSeriesOffice`.

**The decisive point: reset *sections*, not manuals.** `Manual.series`,
`Manual.owning_office`, `offices_overridden` and the per-document
`ManualOffice` rows all live on the `Manual` row. Delete and recreate the
manuals and every series link goes with them; replace only their sections
and the whole organisation survives untouched.

So the command should, per document: delete its sections, re-extract from
the PDF, and write new ones against the **same** `Manual` row.

The six revisions are development data (3 pending, 3 rejected) and go
either way, since they hang off the sections. **Worth confirming before
the run.**

### 3. How v4 upload should assign series and document number

Today `_title_for` parses the filename. That is why `ASM 3.0` and
`FAM 8.02 Evaluation of External Providers` were wrong, and why a rename
was needed to fix one of them.

**The document's own header carries the answer**, and it is the controlled
identifier:

```
MANUAL TITLE   ACADEMIC SERVICES MANUAL
DOCUMENT NO.   ASM 3.00
DOCUMENT NAME  CURRICULUM DEVELOPMENT, REVIEW AND VALIDATION
```

Proposed: upload reads the header, **shows what it found and asks the
uploader to confirm** - matching the series by code, offering to create
one if it does not exist. The filename becomes a fallback for a header
that cannot be read, and is never authoritative.

That also removes the divergence class entirely: the database and the PDF
would agree because both came from the same place.

**Series links survive a reset** provided the `Manual` rows do - see
section 2. They are not re-derived and do not need to be.

---

## Phase 1c-i — what was built (awaiting Checkpoint C1)

### The flag and the gate

`AccessMode`, one row. A database row rather than a setting, because
flipping it changes who can see which documents - that should be done from
a screen, by a named person, at a recorded time, not by a redeploy nobody
can point at afterwards.

The gate refuses while any blocker stands, and **there is no force**. Every
blocker is somebody losing access to the documents that govern their work,
which is the one case where making it easy to proceed is the wrong thing
to build.

| | Check |
|---|---|
| **Blocker** | Approved, active, non-admin accounts holding no current position |
| **Blocker** | Documents with no concurring office |
| **Blocker** | An owning office that may propose with no approving level above it |
| Warning | Offices with no current Head |
| Warning | Documents not in a series |
| Warning | Announcements still targeted at a department |

The first blocker clears **two** ways - assign a position, or deactivate
the account. Some of these are test accounts that will never hold a post,
and making a position the only exit would mean inventing one.

Switching **back** is not gated: it only ever restores access, and gating
it would make a rollback harder than the switch.

### Rollback is total

Every function in `access.py` reads the flag, `can_propose` included. A
flag that restored most of the old behaviour would be worse than none,
because the part it did not restore is the part nobody thinks to check.
Tested in both directions.

### The owner may propose

An office can own a manual **and** work on it - the VPSD owns the Student
Development Manual and its own staff draft changes to it. The old comment
claiming the owner "is deliberately not duplicated" in the link table is
gone; nothing ever enforced it anyway.

What cannot happen is the route ending at that same office, because then
the office that wrote the change approves it. `Manual.owner_proposal_conflict`
names the two ways in: the owner concurs while **approval stops at the
owner**, or the owner concurs and has **no approving level above it** at
all. Both are refused **when the configuration is set**, from either
direction, and the write is rolled back rather than half applied - by the
time somebody tries to submit, they have already done the work.

An owner listed as concurring **counts** toward the "has a concurring
office" blocker. Without that, a document only its owner works on would
read as stranded and the switch would be refused for no reason.

### Announcements move with access - and the trap in doing so

Targeted by office once the flag is on, by department before. Otherwise
the system would scope documents by office and notices by department: two
answers to "where do you work" in one application.

**The trap, found by a failing test.** A department-targeted announcement
has `office = NULL`, and null means *everyone*. Read carelessly, the
moment of the switch would take every notice aimed at one department and
**broadcast it to the whole university**. It now means *nobody* instead:
untargeted is `office` null **and** `department` null. A notice whose
targeting the current mode cannot express stops showing rather than going
everywhere - and the switchover screen warns about them first, because a
notice nobody sees is still a notice nobody sees.

### The preview, and one honest row

The blockers catch people who would see **nothing**. The preview catches
what they cannot: somebody who holds a position, but the wrong one. Only a
person reading the two numbers side by side notices that.

It computes both answers **directly**, via a `mode` override, and never
touches the flag. Flipping the row to work out "after" - even inside a
try/finally - would mean a staff member loading a page during the preview
got the other rule.

The system admin is reported as **unscoped**, showing "all" rather than a
comparison. Their reach does not come from an office, so running them
through the office rules produced *"5 documents today, 0 afterwards"* -
alarming, and false.

### The rehearsal, on a copy with the real data

```
10 offices, 4 series, 19 of 19 documents placed

gate, nobody assigned     ready: False   BLOCK staff_without_positions: 4
switch attempt            409 not_ready

assign 3 people, deactivate 1 test account
gate                      ready: True    warn offices_without_a_head: 8

preview
  Admin      -      all -> all      (not scoped)
  Eug        ACC      5 -> 14
  eugene_l   ACC      5 -> 14
  STAFF1     GUID     5 -> 4
  deactivated: try        unapproved: STAFF2

switch 200
  Eug       reaches 14, may propose on 10
  STAFF1    reaches  4, may propose on  4
  SDM 3.01  owner VPSD, concurring [GUID, VPSD], route VPSD -> OP,
            owner may propose: True, conflict: None

rollback 200
  Eug, eugene_l, STAFF1 all back to 5 reached, 5 proposable
```

### Also in 1c-i

- Manual lists show **the reader's relationship** - Owner, Concurring,
  Read only - instead of a department, plus the series and owner. Before
  the switch the server sends nothing there, because "your department's"
  is the only true answer and the list already says it.
- The "not assigned to a department" error follows the flag and becomes
  *"approved but not yet assigned to an office. The system administrator
  will assign you."* Telling someone they have no department when the
  system stopped caring about departments sends them to ask the wrong
  question.
- Sign-up asks for an **Office**.

### Test state

**337 API tests pass**, 42 of them new. Migration 0023 adds one table and
one column.

**Not run against the real database.**

---

## Phase 2a — the old flow, and the new model (awaiting Checkpoint 2A)

### What the old flow is

`ManualRevision` does three jobs in one table: the submission, the
decision, and the assessment snapshot. **One section, one submitter, one
reviewer, one decision** - no version, no office, no notion of more than
one party agreeing. That is the gap P2 closes, and it is structural
rather than a matter of adding fields.

Three submission paths: text, file upload, merge. 11 endpoints, 13
frontend components, 8 test modules. The database is clear, so **nothing
migrates** - the dependency is entirely code.

### Decisions taken

| | |
|---|---|
| **Merge** | Retired when the switch is on. It deletes a section, which is out of P2's scope; it returns with add/delete. |
| **Upload** | Typed text only in P2. *Future work: upload a whole revised document and let the system match its sections into the boxes, with the staff member confirming.* |
| **Old endpoints** | Refuse with an explanation when the switch is on, like `delete_department`. Not removed - removal 404s an open browser tab. |
| **Admin dashboard** | Learns about proposals in 2c, so it does not go blank at the switch. |
| **Rate limit** | 200/hour per user (was 60, sized for one section), plus 80 per proposal so one editor cannot spend the whole budget on one document. Real documents hold 5-17 sections, median 11. |

### The advisory needed something stored that was not

**Confirmed, and it corrected the 2a report.** The pipeline's trace keeps
`layer1`, `layer2`, `layer3`, the version and the fingerprint - **not what
retrieval returned**. `related_texts` hands back raw text with the ids
already discarded. So the coordinated-change advisory could not have read
stored output as described.

Fixed by recording the retrieved section ids on the snapshot at check
time, from the **view**: `build_index` and `top_k` are read-only and
already public, so **nothing under `ml/` changed** and Layer 2 receives
exactly what it received before. The advisory then reads
`retrieved_section_ids` and recomputes nothing.

It fails silently if retrieval errors - an advisory is a nicety, and
losing it must never cost the check the submitter is waiting for.

### The model

`Proposal` (manual, initiating office, status), `ProposalVersion`
(number, overall reason), `SectionChange` (old text **as of the version**,
new text, note, its own assessment, hashes), plus `ProposalParticipant`,
`Concurrence` and `AuditEvent` for 2b.

`old_text` is stored rather than read live: the diff a reviewer sees has
to be the diff the drafter saw, and the section can move underneath both.

`current_version()` is **derived** from the rows, not a stored pointer - a
stored "current" that disagreed with the highest number would be a bug
nobody could see.

### One open proposal per section

A partial unique index on `(section) where is_open`, with `is_open`
copied onto the row because a constraint cannot cross the join to
`Proposal.status`. Same shape as `PositionAssignment.sole_holder`, and
the same hazard: a stale False does not raise, it lets **two offices edit
the same section at once and tells neither**.

Open means *the proposal is open* **and** *this is the current version* -
a superseded version is history, and its sections are free again.
Maintained by `save()`, by the queryset's `bulk_create()` and `update()`,
and by `Proposal.refresh_open_changes()` on every status or version
change. Seven tests, including two rows in one `bulk_create` and an
`update()` that moves a change onto an open version.

The API reports it as what it is: *"3.0 POLICIES is already in an open
proposal by ACC"* - with the office, so the drafter knows who to talk to.

### A bug the tests caught

`check_is_current` compared two **stored** values - the change's hash and
the assessment's - which is comparing the check with itself. Always true.
Every edited section reported as checked, and the per-section staleness
guard did nothing.

It now fingerprints the text **as it is now** and compares that with the
one taken when the check ran. The fingerprint deliberately covers the two
texts and **not** the overall reason: editing one box must clear only that
box, and folding in the shared reason would clear every section at once.
The reason is still checked at submission by the existing clause 6.3
tiers.

### Test state

**376 API tests pass**, 39 of them new. Both switch states covered - with
it off, the single-section pre-check still works end to end.

Migration 0024 on a copy: **every existing row count unchanged**, six new
tables empty, and it **reverses cleanly**. `check_setup.py` Ready, the
pipeline untouched.

**Not run against the real database.**

---

## The demonstration organisation — 2026-09-23

`seed_demo_org`, with `--clear`. **Every person in it is fictional**, and
it exists so the system can be shown to other people before the real
organisation is entered.

Three things make it safe. It **refuses to run beside a real
organisation** - any office or series it did not create means somebody has
started entering the real one, and fictional data beside it could not be
told apart afterwards. It **records what it did, row by row**, in
`DemoRecord`, so `--clear` undoes precisely that rather than deleting
everything that looks like demo data - a real office can share a name with
a fictional one. And it is **not a migration and never will be**: a
migration runs on every machine that deploys, including the one holding
the real data.

`DemoRecord` is a marker table rather than an `is_demo` flag on `Office`,
`CustomUser` and the rest. A demo convenience has no business adding a
column to the models that hold the university's real organisation, where
every query would then have to consider it for ever.

It also records **changes**, not only creations: the nineteen documents
existed already, so it stores each one's previous `series_id` and
`--clear` puts it back rather than blanking it.

Verified as an exact round trip on the real database: 14 offices, 4
series, 14 people, 19 documents placed; then `--clear` back to 0 offices,
the original 6 accounts, 19 documents, none in a series, nothing left.

**A guard found by a failing test.** The refusal covered offices but not
series, so a real series carrying one of the demo codes collided on the
unique constraint and the command died with a raw `IntegrityError`
instead of an explanation. Both are checked now.

### Readiness after seeding

```
ready: False
BLOCK staff_without_positions (4)   Eug, STAFF1, eugene_l, try
warn  offices_without_a_head (5)

ACC_*, BUD_*, CMO_*   0 -> 10      GUI/HRM/SFA/VPSD  0 -> 4
CDO/VPAS              0 ->  1      QMS_Ana, QMS_Pedro 0 -> 0
Admin                all -> all (not scoped)
```

The four blockers are the old v3 test accounts. **QMS at 0 is correct**,
not a gap: the QMS office decides requests and is linked to no series, so
it works on no documents - it reaches them through the QMS role in P4.

---

## Phase 2b — submission through to agreement (awaiting Checkpoint 2B)

Draft → submit → concurrence → locked, with returns making new versions.
No new migration: 2a modelled all of it.

### Submission

Only the initiating office's **Head**, with re-authentication - on the DCR
the Head signs alongside the requester. It refuses on anything unready and
says which section: an unchanged proposal, a missing reason, a section
edited after it was checked.

Clause 6.3 runs on the one overall reason through the **existing** two
tiers, and returns the submitter's own message rather than a generic one.

**With no other concurring office it locks immediately.** There is nobody
to ask, and a concurrence stage with an empty list is a stage that means
nothing.

### Participants freeze for the *request*, not the version

Concurring offices minus the initiator, then the approval route in order,
each with `office_name_at_time`.

> **Found in rehearsal, not by a unit test.** The first version re-froze
> the list on every submission. A test proved a mid-request reorganisation
> changed nothing - but it never resubmitted. Running the whole flow
> against the demo organisation, an office added halfway through became a
> participant on **resubmission** and silently blocked a proposal every
> original participant had already concurred with: both offices agreed and
> it sat in concurrence for ever.
>
> Frozen once now, at the first submission. A redraft after a return is a
> new version of the same request, and the spec is explicit - *later
> changes to the organisation never alter a submitted proposal*. Two tests
> cover it: the list after a resubmission, and that a redrafted proposal
> still locks.

### Concurrence

Only an office's **Head** decides, with re-authentication; an Encoder can
prepare the feedback for the Head to confirm. Read from the **frozen**
list, so somebody moved into a new office mid-request does not acquire a
say in it.

A return **requires feedback** - returning without it leaves the office
nothing to act on - and may point at a section.

**Any return makes a new version and resets every concurrence.** An office
agreed to particular text, and that text no longer exists. The new version
**carries the text but not the checks**: the office is amending its own
work, but a check that survived would be about text nobody submitted. The
old version keeps its decisions - that is history, not a mistake.

Feedback is visible to the initiator and every participating office,
because offices object for the same reasons and seeing each other's
avoids repeated rounds and contradictory demands.

### A constraint collision in the redraft

Copying the changes into the new version before closing the old one left
**both versions holding the same section open** for the length of the
loop, and the one-open-change index refused the copy. The old version is
closed first now.

### Withdrawal, audit, and the awaiting list

Withdrawal needs the initiating Head, re-authentication and a reason; the
record stays and the sections are released.

Every transition is recorded with the actor, the position they held, the
office and its name at the time. The redraft event names the returning
office in full, because *"BUD_Jose redrafted for Accounting"* reads as
though Budget did the drafting.

**"Awaiting your office"** is derived, not notified - notifications are
P5. Per office rather than per position, so an Encoder sees it too.

### The rehearsal, against the demo organisation

```
draft by ACC_Juan (Encoder), 2 sections checked
Encoder submits         403 not_head
ACC_Maria submits       200  concurrence
  approving  VPAF #0, OP #1     concurring  Budget, Cash Management
Library added as concurring mid-request -> frozen list unchanged
BUD_Jose returns        200  draft, version 2, 0 concurrences, 0 checks
redraft, resubmit       200  concurrence
BUD, CMO concur         200  locked

manual unchanged (P4 applies it)    sections released
created / submitted / returned / redrafted / submitted / concurred x2 / locked
```

### Test state

**44 new tests**, 83 across 2a and 2b. Both switch states: everything in
2b refuses with `switch_off` while access is scoped by department.

**A timezone bug the tests exposed.** `TIME_ZONE = 'UTC'` while the
machine runs in Manila, so `timezone.localdate()` was **a day behind**
`date.today()`. Every fixture assignment started "tomorrow" and no
position counted as current. The tests now use `timezone.localdate()`
throughout - but see the open question below, because this is not only a
test problem.

---

## `TIME_ZONE` is now `Asia/Manila` — 2026-09-23

Verified **before** changing it, on the real database: `USE_TZ = True`, and
`api_office.created_at` was stored raw as `2026-09-22 17:48:49` while
Manila read 01:48 on the 23rd. DateTimeFields are held in UTC and
converted only for display; DateFields carry no timezone at all.

**Nothing stored moved.** The same raw bytes before and after; what
changed is `timezone.localdate()`, from `2026-09-22` to `2026-09-23`.

**No stored dates needed correcting and no reseed was necessary.** The
demo assignments were written with `timezone.localdate()` under UTC, so
they read a day early rather than a day late - still `starts_on <= today`.
Zero assignments start in the future.

### A correction to the earlier framing

The window where the two dates disagree is Manila **00:00-07:59**, not the
afternoon. Manila is UTC+8 and never behind it, so the small hours are
when a date picked as "today" in a browser was tomorrow to the server.

### What visibly changes

**No displayed timestamp changes in the React UI.** The API now sends
`2026-09-23T01:48:49+08:00` where it sent `2026-09-22T17:48:49Z` - the
same instant - and every screen renders through
`toLocaleDateString("en-PH")`, which converts to the *browser's*
timezone. A Manila browser was already showing Manila time.

What changes is everything derived from the server's "today":

| Where | Change |
|---|---|
| Position assignments | A post assigned 00:00-07:59 takes effect at once rather than eight hours later |
| Admin activity chart | Day buckets shift to Manila boundaries |
| Upcoming announcements | "Today" starts at Manila midnight, not 08:00 |
| Oldest-pending counts | Match the calendar people are looking at |
| Django `/admin/` | Renders in Manila - the one place with genuinely new text |

Four tests, including one that **pins the bug**: under `TIME_ZONE='UTC'`
the same assignment is *not* current, so reverting the setting fails at
the cause rather than somewhere distant. Another guards the fixture
itself, in case it stops straddling midnight and the others start passing
without proving anything.

---

## Phase 2c — the screens (awaiting Checkpoint 2C)

No migration. The API from 2a and 2b, given something to look at.

### The proposal screens

One tab, three states - list, editor, detail - because they are three
states of one thing and moving between them should not feel like
navigating.

**The editor is the whole document, collapsed.** Opening a section is what
starts an edit, so the closed state is quiet enough to scan twenty of them
and the open one is clearly the thing in hand. Each changed section shows
its own check and its own verdict; a section edited after being checked
says *needs a check* rather than reporting a stale one as current.

The **AI explanation is the one place given room** - a few sentences on
what changed and why it matters - while the rest of the screen stays
sparse, per the design principles. The coordinated-change advisory sits
directly under it.

**`DocDiff`, not `DiffView`**, on the staff side: this is the submitter
looking at their own change, marked the way a person with a red pen would
mark it. The admin screen keeps the technical diff, because that audience
is checking what changed rather than reading the document.

> The first version passed `oldText`/`newText` to `DiffView`, which takes
> `diffText`. It would have rendered an empty state, silently. The server
> now sends `diff_text` per changed section, built with the same
> normaliser the v3 flow uses, so a diff reads identically whichever
> screen shows it.

### The old flow stands aside rather than vanishing

With the switch on, the five v3 paths refuse with an explanation and a
`reason`, like `delete_department`. A route that vanishes gives an open
browser tab a 404 and the person no idea why.

**Merging says something different.** It is not *replaced* by proposals -
it deletes a section, and adding or deleting sections has no home in a
proposal yet. `merge_out_of_scope`, not `superseded_by_proposals`, because
those are different facts and the second would be a lie. The admin
Sections screen merges too, and it deletes the same row, so it refuses on
the same terms.

**Reading is untouched.** Only the ways of *changing* a document stood
aside.

### The dashboards read both flows

The admin activity chart counts revisions **and** proposals into the same
three series. Reading only one would make it go blank at the moment access
changed, which looks like the system stopped being used. A proposal
submitted is a submission, locked is agreed, returned is sent back;
`mode` says which flow is live for anyone who needs it.

Open proposals appear in the attention strip - in concurrence, and locked
and waiting for the paperwork P3 and P4 build.

The staff shell shows **one tab or the other**, never both: *My Revisions*
becomes *Proposals* when access is scoped by position, with a count of
what is waiting on the person's offices. Two ways to change a document,
with nothing deciding between them, is what this phase exists to avoid.

`Propose changes` sits on a section as a **secondary** action, per the
design principles - reading a document is the common case and proposing a
change to it is the rare one.

### A shadowed name

`staff_dashboard` already had a local called `mine` holding this person's
revisions. The new awaiting-count rebound it to a list of office ids, and
`mine.count()` a few lines later became `list.count()` with no argument.
Renamed; the tests caught it immediately.

### Test state

**19 new tests.** Both switch states for every v3 path, that nothing is
written when one refuses, that reading still works, that the dashboards
carry both flows, and that the awaiting count clears when the office
decides.

---

## Phase 3a — the documents a request produces (awaiting Checkpoint 3A)

Migration **0026**, tested on a copy of the live database first. The copy
held **0 proposals**, so there was nothing to backfill: the migration adds
tables and columns and rewrites nothing.

### The template blocker, cleared

The DCR template shipped as a legacy binary `.doc`, and nothing in this
environment can open or convert one - `python-docx` reads only `.docx`,
`docxtpl` and `reportlab` are not installed, and neither LibreOffice nor
Word is on PATH. It was converted by hand outside the project and
committed beside the original.

Two things about that file are worth knowing before 3b touches it:

**The signature labels are floating text boxes.** `Requested by` and
`Department/Unit Head` are not in the table at all, so `python-docx`'s
ordinary API walks straight past them; they turned up only in a raw
search of `document.xml`. Each also exists **twice**, once as DrawingML
and once as a VML fallback, and a generator that writes one copy and not
the other will produce a file that reads correctly in one application and
wrongly in another.

**The IMR title wrapped**, and the arithmetic says exactly why. The cell's
text area is 521.95pt. The tick-box line ends at 294.18pt, the tab throws
to the next default stop at 324pt, five spaces carry it to 337.91pt, and
`Integrated Management Representative` in 10pt Arial Bold is 186.73pt
wide - ending at **524.64pt, over by 2.69**. Removing the five spaces
brings it back to 324-510.73pt, inside the cell with 11pt to spare.

The happy part: the signature line beneath runs 346.5-488.25pt, centre
**417.375**. The trimmed title's centre is **417.367**, and Word's own render (via
COM, exported to PDF and measured) puts it within **0.1pt** of the line's
centre, overhanging 22.5pt left and 22.3pt right. It is not a
coincidence - the name it replaced was set to sit centred on that line,
and dropping the spaces puts the title in the same place, at the same
size, rather than shrinking it. So the fix is five bytes and no font
change, and the package was rewritten entry by entry so every other byte
of the official form is untouched.

**Two personal names were in the file and neither was printed.**
`docProps/core.xml` carried a `dc:creator` and a `cp:lastModifiedBy` -
the people who wrote and last saved the official form. Personal data
under RA 10173, about to go into version control, and invisible to anyone
who opened the document. Both removed, and `CLAUDE.md`'s rule now says to
check the properties as well as the page.

### Locked is not the same as ready to sign

`LOCKED` means the content is frozen. `AWAITING_SIGNATURE` means frozen
**and** the documents to be signed exist. They are separate statuses
because a lock that froze the text but produced nothing to sign is a dead
end - no screen could act on it, and nobody could undo it - and that
difference has to be visible rather than inferred from whether any rows
happen to be in `attachments`.

3a builds the machinery with **no generators registered**, so locking
still rests at `LOCKED`. That is the honest description: telling an office
to go and sign documents that do not exist would be worse than saying
nothing. 3b registers the generators and the same code path then advances.

**Generation runs inside the locking transaction.** A generator that
raises takes the lock with it, and the offices keep a proposal they can
still work on. The guard that enforces this raises rather than asserting:
under `python -O` an assertion vanishes and the protection with it.

> That guard needed a test that is not itself inside a transaction.
> Django's `TestCase` wraps every test in one, so the check passed there
> whatever it did - the first version of the test was green for no
> reason. It now runs under `SimpleTestCase`.

### The DCR number

`DCR-YYYY-NNN`, **provisional**, one constant, pending the QMS office.
Counted per year from the numbers already issued rather than from a stored
counter, so restoring a backup cannot hand the same number out twice; a
partial unique index is the backstop when two locks race, because the
alternative is two requests going out on paper as the same DCR.

Allocated at the lock, not at submission, so a proposal that is returned
and resubmitted does not burn a number.

### Attachments record; they do not verify

The system cannot tell whether a scan shows the right document, whether a
signature is genuine, or whether the signer held the position. The QMS
office checks that against the physical copies. So every field is a fact
about the upload - who, when, what it was called, what type it claimed to
be - and none is a judgement about the contents.

**Replacement supersedes; it never overwrites.** A scan is evidence that a
piece of paper was signed, and quietly replacing the bytes would leave the
record saying something different from what it said yesterday with nothing
to show it had changed. Two partial unique indexes hold the shape: one
live file per slot, and one replacement per file.

`slot` exists because the per-section kinds put several rows under one
kind, and SQLite counts NULLs as distinct - a unique index over a nullable
`section_id` would let the same section through twice.

**The name on disk is never the name the browser sent.** `Manual.file`
once wrote uploads back into the folder being scanned; this one generates
the path and keeps the chosen name in `original_filename`, where it is
data rather than a path.

### A counter that would have gone quiet

The admin dashboard counted `status=LOCKED` for "agreed and waiting for
the paperwork". Once 3b advances a new lock to `AWAITING_SIGNATURE` that
counter falls to **zero** while the proposals pile up, and nothing says
so. Widened to every frozen status now, with a test, rather than left for
3b to trip over.

The activity chart is fine: it reads `locked_at`, not the status.

### A rollback undoes rows, not bytes

If one generator writes its file and a later one fails, the file stays on
disk with no row pointing at it. Harmless - nothing reads an attachment
except through its row - but it wants a sweep once 3b has real generators
capable of orphaning anything.

### Two fields were too narrow

`Proposal.status` and `AuditEvent.event` were `max_length=16`.
`awaiting_signature` is 18 and `documents_generated` is 19. SQLite would
not have complained, which is what makes it worth saying out loud.

### Test state

**21 new tests.**

---

## Checkpoint 3A — approved; what followed

**Migration 0026 applied to the live database**, after a fresh backup
(`db.sqlite3.bak-20260923-pre-0026`). The database runs in WAL mode, so a
copy of the main file alone can miss committed pages still in `-wal`; there
was no `-wal` file, the backup passed `integrity_check`, and its counts
matched the live file.

**The full suite at 3A: 479 tests, 1 failure** - the dashboard test added
in 3A, whose fixture made an admin the dashboard does not recognise
(`is_superuser` rather than `role='admin'`). A fixture error, not a code
error; corrected.

**Every 3A test was then shown to fail without the thing it tests** - 10
of 10, by breaking each target in turn (a scratch harness that patches one
string, runs the named tests, and restores the file whatever happens).

### Personal names in the templates' properties

All four template files were checked, not only the one that prompted it.

| File | Found | Done |
|---|---|---|
| DCR `.docx` | nothing (scrubbed at 3A) | - |
| DCR `.doc` (legacy) | Author, Last saved by - in the OLE summary stream, and again in UTF-16 in Word's own tables | blanked in place, same length, so no offset moves; only name bytes changed |
| `MANUAL_BLANK.docx` | creator, last modified by, Company | cleared |
| `MANUAL_BLANK.docx.bak-20260914-172404` | the same | cleared |

No `w:author` on tracked changes or comments in any of them.

> **Three of these files were already committed, names and all.** Clearing
> them now fixes every future checkout; it does not remove the names from
> history. Rewriting pushed history is the owner's decision, not a side
> effect of this phase. Separately, the `.bak` template is tracked and
> probably should not be.

A standing test now reads every file in both template folders -
`.docx` through its property parts, the legacy `.doc` through a small
reader for its summary property sets, which raises rather than reporting
a file it cannot read as clean.

---

## Phase 3b — generating the documents (Checkpoint 3B approved)

**Decided at the checkpoint:** one draft-copy file per request; Document
Title and Revision Status left for hand-filling; an over-long reason goes
to the annex in full with section 2 saying so. The tracked
`MANUAL_BLANK.docx.bak` is removed from the repository. **`api/__init__.py`
is added as its own small commit after Phase 3**, with the full suite as
the check - not before.

No migration. Three generators, registered with the lock from 3A, so a
proposal that locks now comes to rest at `AWAITING_SIGNATURE` holding its
DCR, its draft copy, and - when there is something to put in it - an
annex.

### Rendering through Word itself

Word 16 turned out to be installed and registered for COM, so every
layout claim below was checked on Word's own output: the file opened
headless, exported to PDF, and measured with PyMuPDF. That is how the
earlier IMR-title claim was confirmed too - its centre is within **0.1pt**
of its line in Word's render, not only in my arithmetic.

It is a development check, not a test: the suite cannot assume Word.
What the suite checks instead is the invariant that produces the result
(below).

### The DCR: one page, nothing moved

Every row of the form is `atLeast` height, so content that outgrows its
space grows the row and pushes sections 3 to 5 down. Section 2 is
therefore measured before it is written:

- **Line height is set, not predicted.** Every paragraph generation writes
  uses exact line spacing, and explicit line breaks at the measured wrap
  points, so the height Word lays out is the height computed.
- **The spacer keeps the total.** The last paragraph in each area takes up
  whatever height its lines leave, so the area is exactly as tall as the
  empty lines it replaced. The test checks precisely that.
- **Widths come from a table**, generated once from Arial and embedded, so
  wrapping decides the same way on any server. Liberation Sans shares
  Arial's widths by design. Every approximation errs towards one line too
  many.

Measured in Word across three scenarios - ordinary; long office names
with fourteen changed sections; a reason too long for any size - every
DCR is **one page**, section 3 starts at **exactly** the blank form's
489.9pt, and the printed labels sit within 0.1pt of where the form put
them.

**Section 2, as decided:** "Sections amended: ...", then "See attached
draft copy." The list shrinks to 8pt and then abbreviates ("...; and 1
other section") - it is a summary, and the draft copy lists them all. The
reason is verbatim, shrinking to 7pt; **when it cannot fit even then, the
box reads "Stated in full in the annex to this request."** and the annex
carries it in full. Neither half of the instruction had to give: the form
stays on one page and the reason is still printed verbatim, one sheet
further on.

### The signature labels, both copies

The position titles go into the two label boxes - in the DrawingML copy
and the VML copy, identically. Each title sits **on** the rule above its
label, as the IMR's title does in section 3: bottom at 460.6pt against a
rule at 460.7 on the left, 460.2 against 460.3 on the right. To make
room, each box is widened to 190pt, centred on its rule, and raised by the
title's height; the label inside it stays exactly where it was.

A long office name takes two lines, and the reason's room shrinks to keep
clear of it (in the stress case the reason ends 8pt above the titles).
The boxes were switched from square wrapping to "in front of text" in the
generated copies only: square wrapping would have pushed the reason's
lines aside wherever the raised boxes overlapped them. The space is kept
clear by measurement instead.

**Which copy Word shows**: a diagnostic file with the DrawingML title
changed to "CHOICE COPY" and the VML one to "FALLBACK COPY", rendered
through Word, shows **CHOICE COPY** only. Current Word reads DrawingML;
older readers (Word 2007, some viewers) read VML. Nothing here can render
a VML-only reader, so the fallback is confirmed by content - the test
reads both copies - not by a render.

### A second properties part

The first sandbox run warned `Duplicate name: 'docProps/core.xml'` for
every DCR. LibreOffice, which converted the form, had declared its
properties under a relationship type with the wrong namespace
(`.../officedocument/2006/relationships/metadata/core-properties` instead
of `.../package/2006/...`). `python-docx` did not recognise it, so the
first touch of `core_properties` created a *second* part under the same
name. Every generated DCR would have held two sets of properties, one
scrubbed, and which one a reader believed was up to the reader.

Fixed in the template (one relationship type). And **every generated
file is now checked as bytes before it is stored** - no repeated part, no
personal property - failing the lock if not. Scrubbing the object said
nothing about what the file contained; reading the file does. A test
round-trips both templates through `python-docx` for repeated parts; run
against the original conversion it fails, 13 entries for 12 names.

### The draft copy

**One file per request, not one per section** - a deviation from the
approved design. Separate files each number their pages from one, and a
sheaf of "Page 1 of 1" is not a draft copy of a document; one file makes
"Page 2 of 5" mean something. `slot` still allows the other if wanted.

The header is left blank as decided, except that `NUMPAGES` is added
beside `PAGE` in every header that numbers pages: "1 of 2", "2 of 2",
confirmed in Word. Text is printed as agreed, line for line. The one
structure recognised is the pipe table the extraction wrote - 46 of the
198 sections have one - printed as a bordered Word table with its header
row repeated across pages, and with deliberately empty columns kept
(`|Responsibility||Activity|`), by the same rule the extraction uses.

### The annex

Offices, decision, date, and the **position** that recorded each -
using the office names frozen at submission, so a rename reads as it was.
Earlier versions' returns are listed with their feedback. A4, to travel
stapled to the DCR. Not generated when there is neither concurrence nor
an over-long reason.

### Left for hand-filling, and why

- **Document Title** - the system stores the document's number
  (`FAM 6.02`) but not its name.
- **Revision Status** - `Manual.revision` is v3's own counter, not the
  official revision, and printing it on a controlled form would mislead.
- **Section 4, Approving Authority** - unchanged. Note the approval route
  can have two levels (VP then President) and the form has one slot;
  that is a P4 question.

### Smaller things

- **A long FROM** shrinks to fit its rule, no smaller than 9pt; past that
  it runs beyond the rule rather than wrapping - a wrapped FROM would push
  the whole form down a line.
- **The Amend tick** first came out as a small red "x": the template's
  blank carries a red, 9pt run. It now takes the brackets' 12pt and prints
  black.
- **Dates** read "September 23, 2026", in Manila time.
- **Tests never write into `media/`**: locking now writes files, so the
  suite runs under a test runner with a temporary `MEDIA_ROOT`.
- **The 2C screens** label the two new statuses and treat them as agreed;
  their real screens - downloads, uploads - are 3C.

### `api/` has no `__init__.py`

The first full run came back 503 tests, one error - not a test but a
failure to *import* `api/generation` during discovery. `api/` is a
namespace package, so Django's top-level finder stops at `api/` itself
and unittest imports everything under it by bare name: every test module
has always been `tests_x`, not `api.tests_x`. Absolute imports survive
that; `from ..models` in the new package reached above the top level.

(My first theory - Django handling the relative label "api" badly - was
wrong; its runner already resolves the path. Reverted before it
landed.)

Fixed by following the convention `api/management` already keeps:
absolute imports for anything outside the package, recorded in its
docstring. **Adding `api/__init__.py` is the conventional repair** but
changes how all the tests are imported, so it is left as a decision
rather than folded into this phase.

> **Done after Phase 3, as its own commit (2026-09-24).** `api/__init__.py`
> added and `api.generation` back on relative imports. Test discovery now
> finds `Backend/` as the top level, so every test module is imported as
> `api.tests_x`, as everything else already imported it. Full suite: 537
> tests, OK - with no recurrence of the duplicate-upload failure.

### Test state

**502 tests, all passing** - 23 new in 3b. Nothing is left in `media/`
after a run.

**Every 3b test shown to fail without the thing it tests: 15 of 15.** The
first pass was 14 of 15, and the odd one out was a real finding. The
pipe-table test used the empty *middle* column of
`|Responsibility||Activity|` - which survives stripping every pipe from
the ends anyway, so the test proved nothing. The case that breaks is an
empty cell at an *end* (`||VERSION NO.|...`); the test now checks that,
and the docstring that repeated the wrong claim is corrected. The two
tests that read the committed template files were shown to fail against
the original files instead: the name check flags three of them, the
round-trip check catches the repeated part.

`check_setup.py` reports Ready, fingerprint `6a6a5c667a3c4d11` unchanged;
nothing under `ml/` was touched.

---

## Phase 3c — signed copies (awaiting Checkpoint 3C)

Migration **0027**, tested on a copy of the live database (forward, back,
forward) and **not yet applied to the live one**. It adds one column,
`Attachment.created_as`, and one audit event label; the event label alone
is a no-op in SQL.

### What was built

- **The package**: `GET /api/proposals/<id>/package/` - the generated
  documents, each signed copy with its current file and every earlier
  one, what is outstanding, and whether this person may upload.
- **The first upload** of each signed copy: no password.
- **Replacement**: a reason and the password. The old row is superseded,
  never overwritten; the new one carries the reason.
- **Downloads** through an authenticated view, never as media URLs.
  DEPLOYMENT.md now says the proxy must not serve `/media/proposals/`.
- **Ready for the IMR**, automatically, when both signed copies are in,
  recorded as its own audit event (`package_complete`).
- **The screen**, shared by the staff and admin portals. The admin and QMS
  see the same package with nothing to press, because the server says
  they may not upload.

### Decisions taken in building it

- **Who uploads: any current Encoder or Head of the initiating office.**
  The design did not settle it. The secretary usually does the scanning,
  so an Encoder can; the Head can too. No other office, and not the
  system admin or QMS staff.
- **What "the IMR has decided" means before P4 exists.** Uploading and
  replacing are allowed only while the request is awaiting signature or
  ready for the IMR (`Proposal.SCAN_STATUSES`). P4's decided statuses
  will fall outside that, so option A holds without further code.
- **Files are judged by their bytes.** The first bytes decide PDF, PNG or
  JPEG, never the name or the type the browser sent; then the file must
  actually open. Empty, over 20 MB, unsupported, damaged, truncated and
  password-protected files are each refused with their own reason.
- **The uploader's position is written down at upload** (`created_as`),
  not looked up when displayed. Found before it shipped: the first
  version looked it up, so an Encoder later made Head would have seen
  their old upload start saying "Head" - the silent rewriting of history
  the project's rules forbid.

### Seen working in the real app

Not only tests. The app was run against a scratch copy of the database -
Django on the scratch settings, Vite, and headless Chrome driven over the
DevTools protocol by a small dependency-free Node script - and walked end
to end: sign in as an Encoder, open the proposal, download list shown,
upload a signed DCR, replace it with a reason and password, upload the
signed draft copy, see the request become **Ready for the IMR** with the
earlier scan kept under "Replaced 1 time". Then the same proposal as a
system admin: Download only. No console errors at any step.

Two wording fixes came out of looking at it: the replace dialog had
lower-cased the form's proper name, and "Documents to sign" stayed as the
heading after everything was signed.

### Test state

**533 tests, all passing** - 31 new in 3c. Nothing left in `media/`.
`check_setup.py` Ready, fingerprint `6a6a5c667a3c4d11` unchanged; nothing
under `ml/` touched.

**Shown to fail without what they test: 18 of 19**, and the nineteenth is
the point. Duplicate uploads are stopped twice - a check before writing,
and the unique index behind it. Removing the check alone leaves the test
passing, because the index still holds; removing both fails it. That is
defence in depth doing its job, not a weak test.

> The first run of that pair was invalid: the harness change that applies
> a second substitution had not taken (an escaping slip), so "both
> removed" silently ran as "pre-check removed". Caught from the identical
> results, fixed, and re-run.

### Open

- **An intermittent failure, not explained.** Right after this session
  resumed, `test_the_same_copy_cannot_be_uploaded_twice` failed twice
  with an unhandled `IntegrityError` - the behaviour of a build with both
  duplicate guards removed - and then passed every time after, seven
  runs and the full suite. The bytecode cache matched the source, the
  test database is in memory per process, and the file held both guards
  throughout. Recorded rather than dismissed; the full suite now keeps
  its complete log so a recurrence leaves a traceback.
- ~~Participant rows showed the recording person's username.~~ **Decided
  at Checkpoint 3C:** the screens show the **position first, then the
  person's full name**, never the username; generated documents stay
  titles-only. Applied to all three places a username appeared on the
  proposal screens - the participant rows, the admin history rows, and
  the version's submitter - since the rule is the same for each. A person
  with no full name shows as the position alone, not the username.
  Tests shown to fail when broken, 2 of 2.

---

## Phase 4 — design approved (2026-09-24)

Decided at the design review:

1. **Section 4's printed title stays blank** until the QMS office answers
   (question D).
2. **A future effectivity date is refused**; the custodian makes the change
   effective on or after it.
3. **Revision numbers**: typed by the custodian, prefilled with the last
   plus one, stored as text; a lower number than the current is refused
   when both are numeric.
4. **A baseline per document**: the custodian may record a starting status
   (number, version, revision, effectivity date), since the manuals carry
   real revisions on paper. A section never changed through a request
   shows nothing of its own; the document header shows the baseline or
   the latest status.
5. **Conflict of interest**: no IMR decision, and no custodian making it
   effective, by anyone holding a position in the requesting office.
6. **Direct edits to held sections are refused.**
7. **The v3 counters keep incrementing**, and stop being shown to readers.

4d, removing the transitional admin review, waits until the switch is
confirmed as having held. Retiring `Department` stays separate.

---

## Phase 4a — the IMR, the hold, the QMS portal (awaiting Checkpoint 4A)

Migration **0028**, tested on copies of the live database and **not yet
applied to the live one**. It holds the whole Phase 4 schema, database
first: the new statuses, `QmsDecision`, `DocumentStatus` with
`Manual.current_status` and `ManualSection.status_changed`, section
history's "proposal" source and link, the approving authority's
attachment kind, and the new audit events. 4b and 4c add behaviour, not
tables.

### A request holds its sections until it is closed

Found in the design survey: a section was held only while its proposal
was drafted or out for concurrence. At the lock it was released, and a
second office could begin changing the same text while the first request
was still collecting signatures - the two would have met at the
custodian's desk, and one would have overwritten the other. Now a request
holds its sections through every frozen status, until it is denied,
withdrawn or made effective. `is_open` keeps its meaning (still being
worked on); a new `holds_sections` drives the hold.

One Phase 2 test encoded the old rule - its own docstring said "until
P4" - and was rewritten for the new one, in both directions.

**The migration restores holds** for requests already frozen. Tested
properly, not only applied to an empty copy: a seeded frozen request,
migrated back to 0027 (released, as the old code would have) and forward
again (held). And the collision: where another request had claimed the
section in between, the step leaves it unheld and **prints "NOT HELD"**
naming both, rather than failing or silently breaking the index.

### Direct edits wait for the request

Seven paths write section text directly: the admin edit, the staff edit,
both deletes, deleting a manual, merging, and approving a v3 revision.
Each refuses a held section, naming the DCR and the office holding it.
Only the text is held - subtitle and content. Tag, order and page number
are not what the offices agreed on, and correcting them still works.

### The QMS portal, chosen by the server

There was no QMS portal: the browser picked admin or staff from a `role`
kept in local storage, and the review screen lived in the admin portal,
so a QMS account landed with nothing to do. Now:

- **`/api/auth/me/`** answers which portal an account belongs in. The
  browser asks it on every load and after login, and no longer reads the
  role from storage - anyone can edit that.
- **The QMS portal** leads with reading, like the others: it opens on the
  manuals, read only (no edit, merge, propose or "my revisions"), with
  **Requests** beside them - a count only when something is waiting.
- **QMS staff read every document** once access is by position - the
  custodian keeps them all. Reading only: proposing is unchanged, and the
  switchover preview still reports their pre-switch reach honestly.

### The IMR's decision

Accept or deny, with comments and the password. Only a current IMR; never
on a request from an office where they hold any position; only a request
ready for the IMR. **A denial needs a reason, closes the request, releases
its sections, and is shown first, in red, to every office involved.** An
acceptance moves it to the approving authority and keeps the sections
held. The signed copies close with the decision (option A).

### A bug found on the way: lists asked for a department

The manual list, the section search and "my revisions" refused anyone
without a v3 **department** - while the refusal itself said "not yet
assigned to an office". Every v4 account is a position holder whether or
not it has a department, so under position-based access this turned away
the very people the switch is for. Found when QMS reading failed; fixed
with `access.has_unit`, which asks for a current office after the switch.

### Seen working in the real app

With the `run-docuroute` skill, from a cold start, twice: the Encoder's
signed copies; the IMR landing in the QMS portal from the server's
answer, seeing the request in the queue, being refused a denial without a
reason, then denying; the requesting office reading the denial in red;
then a fresh run with the IMR accepting, the queue emptying, and the
office reading "Accepted" with no way left to replace a scan; the
custodian reading a document their office has no link to, read only.

Looking at it caught three things the tests could not:

- **A stale package line.** After the decision the package still said
  "The IMR decides next": it had loaded its data before the decision.
  It now remounts when the status changes.
- The sidebar printed the IMR's full title, upper-cased, over four lines;
  it now says "IMR".
- A lone "My revisions" tab for readers who submit nothing.

The skill gained QMS accounts in its seed and four drives (IMR accept,
IMR deny, the office reading a denial, QMS reading); its cold run caught
two drive mistakes of mine (upper-cased labels in `innerText`, a
confirmation that lives on another page).

### Open

- **The direct edit asks for no password.** `update_section` (the admin's
  edit) and `review_section` do not re-authenticate, although CLAUDE.md's
  table requires it for "any direct edit to manual content", and P1 was to
  add it. Not changed in 4a - it needs the admin Sections screen to ask for
  the password too - but it should not wait long.
- **The v3 counters are still shown to readers** ("Document v1", "Revision
  No.", "Manual Version" on a section). Decision 7 removes them; that is
  4c's reader display.

### Test state

**566 tests, all passing** - 29 more than before 4a. No `IntegrityError`
anywhere in the log: the duplicate-upload failure has not recurred.
`check_setup.py` Ready, fingerprint `6a6a5c667a3c4d11` unchanged; nothing
under `ml/` touched.

**Shown to fail without what they test: 15 of 15** - the hold through the
lock, the release on denial, only-the-IMR, the conflict of interest, the
reason for a denial, the password, the status check, the decision shown
to every office, the queue, the server's portal, the direct-write refusal
and its text-only scope, QMS reading and list reach, and the department
gate.

---

## Questions for the QMS office — open

*The full list lives in `MULTI_OFFICE_WORKFLOW_PLAN.md` section 8. These are
the ones a build decision is currently resting on, recorded here so the
provisional choice and its reason stay next to the work.*

| # | Question | Provisional choice until answered |
|---|---|---|
| **A** | **May a university have more than one IMR, or more than one Document Custodian, at once?** | Unrestricted. `Position.SOLE_HOLDER_KINDS` is `(HEAD,)` only. The permissive choice on purpose: a wrong restriction blocks real work, a missing one can be added later. |
| **B** | Does the approval route always continue upward from the owner, or stop at the owner for some manuals? *(plan section 8, question 5)* | Continues upward by default; `Manual.approval_stops_at_owner` overrides per manual. |
| **C** | Is multi-office concurrence actual practice? The DCR has no section for it. *(question 1 — the largest one)* | Built as designed, with the concurrence record printed as an annex. |
| **D** | Does section 4's **approving authority** mean the owning office's head (the VP), with the draft copy's two unlabelled footer boxes carrying the VP and the President? The approval route can have two levels; the form has one slot. *(raised in 3b; also a P4 design question)* | **Not guessed.** Section 4's printed title is left blank, and the footer boxes are left empty. |

---

## Phase 1a — the survey (2026-09-22)

### The data model as it stood

Eleven models, 17 migrations. `Department` was the only organisational
structure: `name` (unique) and `created_at`. No hierarchy, no parent, no
active flag, no abbreviation. Three foreign keys pointed at it —
`CustomUser.department` (SET_NULL), `Manual.department` (**CASCADE,
non-nullable**), `Announcement.department` (CASCADE, nullable).

Two consequences shaped the plan:

- **`Manual.department` could not express "unassigned"**, so that state has
  to live on the new `owning_office`.
- **Deleting a department destroyed its manuals, their sections and every
  revision against them** — flatly against rule 3, "nothing in the
  organisation is ever deleted".

Live data at survey: 7 departments, 20 manuals, 203 sections, 6 revisions,
6 users (1 admin, 5 staff, one of those unapproved).

### Access scoping was thirteen sites, not one

Not a helper — **nine inline `!=` comparisons and four queryset filters**:

| Kind | Views |
|---|---|
| Inline comparison | `list_sections`, `review_section`, `review_delete_section`, `merge_sections`, `upload_revision`, `propose_text_revision`, `propose_merge`, `pre_assess_text_revision`, `pre_assess_merge` |
| Queryset filter | `staff_list_manuals`, `staff_my_revisions`, `staff_sections`, `staff_dashboard` |

Thirteen places to change, and a missed one looks like nothing.

### `is_staff` was overloaded, and it was live

Four views used Django's `is_staff` as the cross-department escape hatch,
while the application's own role field uses `'staff'` to mean **the
opposite** — an ordinary non-admin user. So `is_staff=True` granted
cross-department access while `role='staff'` denied it, and any account
made with `createsuperuser` picked that up silently.

### Admin rights were three overlapping mechanisms

`role` (the real one, guarding 23 endpoints via `IsAdminRole`),
`is_approved` (a separate login gate), and Django's `is_staff` /
`is_superuser`. Portal choice was made client-side from a `role` string in
`localStorage` — not a privilege hole, since the API enforces per
endpoint, but not something to add a third role to.

---

## Approved decisions — Phase 1a

**1. The review-rights gap.** Mapping the single admin account to *system
admin* would have left **nobody able to review anything**: no QMS staff can
exist until offices exist, and three pending revisions would have been
stranded. The one person who could fix it is the system admin, who by rule
7 should not also be deciding requests.

> **Decided (option 1):** review is allowed for `system_admin` **or** a
> current QMS position, **until 1c**. Marked transitional in code, with a
> test that fails when 1c removes it so the allowance cannot be forgotten.

**2. `is_staff`.** Fixed in 1a as part of the scoping refactor. It stays
**only** for Django's `/admin/` site and is never again consulted for
access scoping.

**3. `delete_department`.** Disabled now, in 1a, because the cascade
destroys manuals and revisions today. The Departments screen retires at 1c
when Offices replaces it. `Announcement.department`'s cascade is being
checked in the same pass, and **nothing in v4 inherits a cascade from the
organisation.**

**4. Name history — denormalise.** `office_name_at_time` on the records
that must read historically, not an `OfficeNameHistory` table.

Why: nothing stored a department name — every display derived it live, so
renaming already rewrote the past everywhere, silently. A history table
fixes that only if all thirteen-plus display sites learn to ask "what was
this called on that date", and each is a chance to forget. One column is
impossible to get wrong at read time, and it matches the call already made
for `SectionHistory.change_reason`, copied rather than referenced for
exactly this reason. Live organisation screens show the current name
because they are about the present.

**5. Approval route — design for both.** Default continues upward (owner,
then approving levels above it); a per-manual **"approval stops at owner"**
boolean overrides it. **Provisional, pending the QMS office** — question 5
of `MULTI_OFFICE_WORKFLOW_PLAN.md` §8.

**6. Refactor before behaviour change.** One `offices_for(user)` /
`can_reach(user, manual)` helper; all thirteen sites converted **while it
still returns the department answer**, with the existing tests as the
check; the helper's answer changes in one commit at 1c. Thirteen edits
where a mistake is invisible becomes one commit with one test surface.

**7. Portal routing.** At 1c, the server returns the role from an
authenticated endpoint rather than the client trusting `localStorage`.

---

## Phase 1a — what was built (awaiting Checkpoint A)

### The access refactor

`Backend/api/access.py`. All thirteen sites now ask it; **it still returns
the v3 answer on purpose**, so the existing tests are a real check that
nothing moved. At 1c the body of `offices_for` changes and nothing else
has to.

**The refactor found something the survey had merged.** The thirteen sites
were not thirteen copies of one rule. Four (`list_sections`,
`review_section`, `review_delete_section`, `merge_sections`) let an admin
through via `is_staff`; the five submission paths let **nobody** through —
an admin outside the department was refused like anyone else. Collapsing
them into a single `can_reach` would have handed admins the right to
propose changes to any manual in the university, which no v3 screen ever
allowed.

So there are two questions, not one: **`can_reach`** (opening a document —
admins pass) and **`can_propose`** (changing one — they do not). That split
is also exactly what 1c needs, where an owning office and a reader office
both open a manual and neither may propose against it.

### `is_staff` is gone from access control

It no longer appears anywhere in `views.py`. It was Django's `/admin/`
flag being used as a cross-department escape hatch while the application's
own `role` field uses `'staff'` to mean the opposite — an ordinary user —
so any account made with `createsuperuser` silently bypassed scoping
whatever its role said. Admin reach is now `role == 'admin'`, which is
what the other 23 endpoints already meant by admin.

### `delete_department` withdrawn

Answers **409** and deletes nothing. It used to destroy every manual in
the department, their sections and every revision against them.

Kept as a 409 rather than removed outright because the Departments screen
still calls it until Offices replaces that screen at 1c — a route that
vanishes gives the browser a 404 and the admin no idea why. The message
names the number of manuals that would have gone.

**Both cascades into the organisation are now PROTECT** (migration 0019).
The endpoint was only the route; the Django admin and the shell reach the
same collector, so the guarantee belongs on the relationship.
`Announcement.department` is PROTECT rather than SET_NULL because null on
that field does not mean "no department" — it means **show this to
everyone**, so clearing it would broadcast a departmental notice to the
whole university.

### Where the design changed under testing

**The one-current-Head constraint could not be written as planned.** The
migration-shape note above said a partial unique index on
`(position) WHERE ends_on IS NULL AND position.kind = 'head'`. Django
refuses it: *"Joined field references are not permitted in this query"* —
a constraint condition cannot cross a relationship, and `kind` lives on
`Position`. The earlier note blamed the database; SQLite would in fact
have accepted the index.

Fixed by copying the one fact the constraint needs onto the row:
`PositionAssignment.sole_holder`, recomputed on every save from
`position.kind in Position.SOLE_HOLDER_KINDS`. The constraint is then
`unique(position) where ends_on is null and sole_holder`, and because
`Position` is already unique per (office, kind), one current assignment to
a head position **is** one current head for that office. Still a real
database constraint, so the rule holds against the shell, a management
command, and two requests arriving together.

`SOLE_HOLDER_KINDS` is `(HEAD,)` only. IMR and Custodian are deliberately
left out — nothing has said whether a university may have two, and
guessing would encode a rule nobody agreed to. **Open question for the QMS
office** (added to the list below); stays `(HEAD,)` until answered.

### The flag had a hole, and it was the quiet kind

`sole_holder` was recomputed in `save()` — and `bulk_create()` and
`QuerySet.update()` never call `save()`. Both would have written rows at
the field's default of **False**, and False there does not raise: it means
the partial index does not apply, so two current Heads for one office
would have gone in without complaint. A flag invented to carry a
constraint, quietly switching that constraint off.

Closed by making every writer maintain it rather than documenting around
it. `PositionAssignmentQuerySet` recomputes on `bulk_create()`, and on
`update()` whenever `position` is among the fields — the only update that
can change the answer, since the flag depends on the position's kind and
nothing else. Ending or reopening an assignment leaves it correct and the
constraint does its own work.

`Position.save()` now also refuses a change of `kind`. Re-kinding a
position would re-point every assignment ever made against it — someone
recorded as the office's Encoder in 2024 would become its Head — and
would leave those rows' flags describing a kind that no longer applies.
Deactivate and create the position you need instead.

Eight tests cover it: bulk-create against an existing head, two heads in
one bulk call with neither pre-existing, a bulk update moving a row onto a
head position, reopening an ended head assignment in bulk, that the flag
is actually written rather than left stale, that encoders are still
unrestricted, and that re-kinding is refused.

### The transitional review allowance

`IsQmsReviewer` — a current IMR or Custodian assignment, **or** (for now)
`role == 'admin'`. `list_revisions` and `review_revision` moved to it.

"Current" is computed by date on every request rather than cached on the
user: the point of dated assignments is that *who holds this now* is
derived and cannot go stale. An assignment ending today still authorises
today — its last day is a day they held it.

`tests_transitional_review.py` imports `TRANSITIONAL_ADMIN_REVIEW` at
module level, so deleting the flag at 1c makes the module fail to import
rather than quietly pass. The allowance cannot outlive 1c unnoticed, and
it cannot be removed while a green suite still claims it is there.

### The migration, on a copy

Three migrations, each reversible on its own:

| | | |
|---|---|---|
| `0017_organisation_tables` | M1 | additive only |
| `0018_map_accounts_to_system_roles` | M2 | six rows |
| `0019_no_cascade_from_the_organisation` | M3′ | the PROTECT change |

M2 derives from `role`, not from a list of usernames, so it produces the
same result on a teammate's checkout or a database rebuilt from the master
copies. It reads no departments — starting empty is not quietly undone.

**Trial on a copy of the real database:**

```
api_department        7 ->   7      api_office              absent -> 0
api_customuser        6 ->   6      api_position            absent -> 0
api_manual           20 ->  20      api_positionassignment  absent -> 0
api_manualsection   203 -> 203      api_manualoffice        absent -> 0
api_sectionhistory    3 ->   3
api_manualrevision    6 ->   6      role=admin -> system_admin   1
api_announcement      3 ->   3      role=staff -> user           5
api_recentlyopened    3 ->   3
api_revisionpreassessment 1 -> 1    20 of 20 manuals unassigned
```

**No existing row count changed. The four organisation tables were created
empty.** Reversing to 0016 drops all four tables and the new columns and
leaves every existing count untouched — so "additive only" is tested, not
asserted.

### Run for real — 2026-09-22

Backup at `Backend/db.sqlite3.bak-20260922-pre-v4-phase1a`. All three
migrations applied. **The result is identical to the trial**: every
existing row count unchanged, the four organisation tables created empty,
1 account to `system_admin` and 5 to `user`, 20 of 20 manuals unassigned.

Smoke-checked live afterwards: the admin reaches the dashboard, the
revision queue and the manual list; a staff account reaches its dashboard
and sees its 5 department manuals. `check_setup.py` reports **Ready** and
the pipeline was not touched.

### Test state

**182 API tests pass.** 39 are new (`tests_organisation.py`,
`tests_transitional_review.py`), covering cycle prevention in both
directions, a merged office still existing, one current Head with
succession still possible, several encoders, dated assignments at their
boundaries, PROTECT on people and offices, and that the access refactor
preserved every v3 answer — including that an admin still cannot propose
across departments.

One phase-3 test changed meaning rather than breaking: deleting a
department used to assert 403 (permitted, guarded by re-authentication)
and now asserts 409, because the action was withdrawn rather than
protected. A second case asserts that a correct password is not a way back
to the cascade.

`check_setup.py` reports **Ready**; the pipeline was not touched.

---

## Migration shape — Phase 1a

Split in three so the risky part is separable:

- **M1 — additive only.** `Office`, `Position`, `PositionAssignment`,
  `ManualOffice`; `Manual.owning_office` (nullable); `CustomUser.
  system_role` and `full_name`. Touches no existing column, deletes
  nothing, reversible by dropping the new tables. **Organisation tables
  ship empty** — no import from the old departments.
- **M2 — data, six rows.** `system_role` for the existing accounts. Reads
  no departments.
- **M3 — retirement, at 1c only**, once nothing reads `Department`.

Constraints in M1: cycle guard on `Office.parent` (application-level —
SQL cannot express an ancestor check); `owning_office` must be an
approving-level office (model validation, since the flag lives on the other
row); **exactly one current Head per office** as a real partial unique
index; `ManualOffice` unique per (manual, office).

> **Corrected during 1a.** The head constraint could not be written the way
> this paragraph first described it — not because of SQLite, which would
> have accepted the index, but because Django refuses a constraint
> condition that crosses a relationship. See *Where the design changed
> under testing* above.

---

# ════════════════════════════════════════════════════════
# v3 LOG — the single-department tool (tagged v3.0.0)
# ════════════════════════════════════════════════════════

## Status

| Phase | State |
|---|---|
| 0 — Explore and report | **Done** (CHECKPOINT 0 approved) |
| 1 — Prereq fixes + Layer 1 rules | **Done** (CHECKPOINT 1 approved) |
| 2 — Layer 2 context model | **Done** (CHECKPOINT 2 approved) |
| 3 — Layer 3 fusion + Layer 4 explanation | **Done** (CHECKPOINT 3 approved) |
| 4 — Dataset creation | **Done** (CHECKPOINT 4 approved after two rebuilds and a blind audit) |
| 5 — Train and evaluate | **Done** — verdicts 0.978 fused, issues 0.854 (both means of five folds); rules-only 0.791 with the clause 6.3 check excluded from scoring; final model trained on Kaggle and in place; CPU training measured at ~2 h for the full split |
| 6 — Wire into the app | **Done** (CHECKPOINT 6 approved) |
| 7 — Repo hygiene, setup, README | Started: compiled Python untracked, size check written |

---

## Phase 0 findings (measured, 2026-09-16)

**Data model.** A DB `Manual` is **one document** (e.g. `FAM 6.02`), not a whole
manual. `ManualSection` mixes both levels: 100 rows are `N.0`, 102 are `N.M`, and
only 2 of 202 have `parent` set, so the hierarchy is effectively flat. Section
text lives in `ManualSection.content`. Group-split by document = split by
`Manual.title`.

**Corpus.** 20 `Manual` rows, 202 sections, 20,913 words.
Families: FAM 10, HRM 4, SDM 4, ASM 1, COE 1.

**Usable revision units (A1 folding rule, >= 15 words): 115.**
Not the ~250 assumed in A9.

**Current assessment.** `ai_assessment_view` (views.py:1538) calls
`ml.distilbert_model.assess_revision(change_type, original_text, revised_text)`
and returns `{overall_verdict, issue_tags, findings, explanation, disclaimer}`.
Nothing is persisted. `train.csv` has 202 rows, binary verdicts
(`Appropriate` / `Needs Revision`), and 12 issue tags that do not overlap the
spec's 10 labels.

**Real revisions.** 2 total (1 rejected, 1 pending), both on FAM 6.02, both by
`eugene_l`.

**Known bugs — both confirmed present.**
- `reviewed_by` does not exist on `ManualRevision`; `review_revision` sets
  `reviewed_at` only.
- `UploadRevision.jsx` posts to `/api/upload/<manualId>/`, which does not
  exist, with no auth header — and the component is imported nowhere. The live
  path is `StaffSections.jsx` -> `/api/revisions/upload/<section_id>/` and
  `/api/revisions/propose-text/<section_id>/`.

---

## Approved decisions

| # | Decision |
|---|---|
| 1 | Dataset size: widen what counts as a unit (A3 linearised table rows), keep the 25/unit cap, accept ~2,000-2,400 examples, and document the shortfall against the 3,000 target in `DATASET_CARD.md`. |
| 2 | **Exclude `COE`** from dataset building — byte-identical MD5 to `HRM 4.02` (same PDF uploaded twice). Leaving it in would leak the same text across split groups. |
| 3 | **No department hard-fail rule** in Layer 1. FAM documents are parked in the CAS/CME test departments, so the check would reject legitimate revisions. Not part of the plan. |
| 4 | **Drop the clause 7.5.2 check.** `Manual` stores no document-no, revision-no or effectivity-date, so there is nothing to read. No new metadata fields. |
| 5 | **Exclude real revisions** from the dataset. Drop `--include-real` and `test_real.jsonl`; one usable row is not an evaluation. |
| 6 | Add `pytest` and `sentence-transformers` to `requirements.txt`. |
| 7 | Clause **7.5.2 is covered by the system, not the model** — document no., revision no. and effectivity date are entered manually and handled by the audit/document-control features. The ISO map for this build is 6.3, 7.5.3, 5.3. |
| 8 | Dataset size (final form of decision 1): widen units with the A3 table rows, keep the 25/unit cap, accept ~2,000–2,400 examples, document the shortfall against 3,000 in the dataset card. |
| 9 | **"List of Forms" (5.0) sections are not revision units.** No dataset examples are generated from them, and the AI assessment returns *"not assessed — manual admin review"* instead of a verdict. Form **names** are still mined from them for `entities.json`, because Layer 1 uses them to detect deletions inside procedures. The A6 "delete a form from 5.0" contradiction generator is dropped. Cost: 1 usable unit (110 → 109). |

---

## Phase 2 — what was built

- `retrieval.py` — per-document TF-IDF index (optional MiniLM backend), disk +
  memory cache, `get_context()` and `related_texts()`. Knows about decision 9:
  a List of Forms section is retrievable **as context** but is never a query.
- `layer2_model.py` — one DistilBERT encoder, two heads. Verdict head uses
  weighted cross-entropy; issue head uses BCE with per-label `pos_weight`
  capped at 20. Rows with `issues_labeled=false` are masked out of the issue
  loss. `save()`/`load()` write an encoder folder, `heads.pt`,
  `label_config.json` (with the pipeline fingerprint) and `thresholds.json`.
- `data.py` — JSONL loader (accepts `.gz`), multi-hot conversion, and a
  `RevisionDataset` that rebuilds context via `retrieval.py` rather than
  reading it from the dataset file.
- `scripts/train_layer2.py` — all the required args, early stopping on
  *verdict macro-F1 + issues micro-F1*, per-label threshold tuning on the
  validation split, per-epoch CSV log, and `--estimate-first` for a 20-step
  timing run.

### Smoke test (60 synthetic examples, CPU, 2 epochs)

Trains: loss 1.69 → 0.76, verdict macro-F1 1.0. ~55 s/epoch on 45 examples at
batch size 4. Save/load round-trips, the fingerprint matches, and a held-out
role swap predicts `reject` at 0.94. Artifacts deleted afterwards (the encoder
alone is 254 MB).

### Bugs the smoke test caught

| Bug | Fix |
|---|---|
| `_window_around_change` sliced by **words** while the budget was in **tokens**, so an oversized change stayed over the limit and `only_second` had nothing left to truncate — the tokenizer raised *"Sequence to truncate too short"* | Window on token ids |
| A long deletion put the window's midpoint inside the deleted span, so **neither** `[DEL]` nor `[INS]` survived and the model could not see what changed | Keep head **and** tail with a marked gap between |
| Retrieval returned the query's own subsection (`4.0` retrieved `4.5`) | Parent/descendant exclusion; siblings still allowed |
| Threshold tuning collapsed to 0.05 for **every** label, so all ten issues fired on every example. Labels with no validation positives score F1 = 0 at every cut-off, so the search kept whichever value it tried first | Labels with no positives keep the 0.5 default; the search runs high-to-low so ties keep the more conservative cut |
| `float(out.loss)` on a tensor that still required grad | `.detach().item()` |

---

## Phase 3 — what was built

- `layer3_fusion.py` — feature assembly, issue merging with a `source` of
  `rule` / `model` / `both`, a fusion model that fits both LogisticRegression
  and HistGradientBoosting and keeps whichever cross-validates better (recorded
  in `fusion_config.json`), coefficients exposed for `ai_trace`, and a
  rules-only fallback.
- `layer4_explain.py` — deterministic template writer seeded by revision id.
  Three or more phrasings per label, hedging by confidence
  (>0.85 "clearly", >0.65 "likely", else "may"), varied connectors with
  high-severity variants, a six-sentence cap that summarises the remainder,
  and the decision-9 "not assessed" message.
- `pipeline.py` — `assess_revision(revision)` and `assess_texts(...)`, models
  cached per process, torch imported lazily so a Django worker that never
  assesses anything does not pay for it. Missing Layer 2 weights degrade to
  rules-only with `trace.layer2 = "unavailable"` rather than failing.
- `scripts/train_fusion.py` — trains from the saved fold predictions, on the
  **validation** split only.

**Two overrides are deliberately not learned:** a Layer 1 hard fail forces
`reject` (the objection is procedural, not the model's call), and a
high-severity issue that *both* sources flag forces at least `needs_revision`.

34 new tests, 112 total, all passing.

### Bugs found while wiring the layers together

| Bug | Fix |
|---|---|
| Numeric evidence read `30, 30 days, 60, 60 days` — the bare number and the duration containing it were both counted, inflating `numeric_changed_count` | Drop a token contained in a longer matched phrase |
| Role evidence listed `accounting staff` and `accounting staff-4` for one mention, because the entity list holds both forms | Keep only the longest matching phrase |

---

## Training budget and the fold decision

**Hardware of record: i3-1215U (2 performance + 4 efficiency cores), 8 GB RAM
with roughly 1 GB usually free.** Local training is a **fallback only**.

Measured on this machine, DistilBERT at batch size 8:

| Setting | ms/example | min/fold (2,180 ex × 3 epochs) |
|---|---|---|
| threads 6 (torch default), max_length 384 | 1547 | 169 |
| threads 8, max_length 384 | 1412 | 154 |
| **threads 8, max_length 256** | **830** | **90** |
| threads 8, max_length 256, short context | 791 | 86 |

**`max_length` is the lever, not padding.** Dynamic padding was measured at
**0.88× — slightly slower**, because `truncation="only_second"` expands the
retrieved context to fill whatever budget is left, so every batch already hits
the cap. It is kept anyway: once Phase 4 produces short units (linearised table
rows), sequences will vary and it will start to pay. Using all 8 cores rather
than torch's default 6 is worth ~9%.

**Token lengths** across 109 real section-sized examples: the full pair is
p50 381 / p95 1321 tokens, so **`max_length=256` covers only 3.7%** of whole
pairs — nowhere near 95%. The more useful figure is the change alone
(`text_a`, which must not be truncated): p50 131, p75 266, p90 569. At
`max_length=256` the change survives whole for **73.4%** of examples; at 384,
82.6%. These are measured on *whole sections*; real revision units will be
smaller, so re-measure after Phase 4 before lowering the default.

**Fold decision: Colab.** The best local figure, 86 min/fold, is over the
~1 hour bar. `MAX_LENGTH` stays **384** — the CPU compromise is unnecessary
on a GPU.

### How the Colab run is organised

- **Google Drive is mounted**, and each fold's `metrics.json`,
  `predictions.jsonl`, `thresholds.json` and `training_log.csv` are copied
  there as soon as that fold finishes. Re-running skips any fold already
  present in Drive, so a disconnect costs one fold rather than the run.
- **Fold weights are never saved.** Folds exist to measure performance, so
  `--no-save-weights` keeps the metrics and predictions and discards the
  encoder: **18 KB per fold instead of 254 MB**.
- **Fusion trains from the saved prediction files**, so it runs in Colab or
  locally after downloading `folds/` — it never needs a fold model.
- **One final model** is trained afterwards on every document, holding out 8%
  purely so **early stopping** has something to watch. Only that model —
  encoder, tokenizer, `heads.pt`, `thresholds.json`, `label_config.json` — is
  zipped to Drive.
- **The final model's per-issue thresholds are the median across the five
  folds** (`--thresholds-from`), not tuned on the 8% slice. That slice is far
  too small for a rare label such as `contradicts_manual`: a couple of examples
  either way would swing the cut-off. Each fold tuned on a proper validation
  split, so their median is the more honest estimate.
- Colab clones from **GitHub**, so whatever is being trained must be pushed
  first. The Phase 7 size check runs before that push.

### Local fallback

`train_layer2.py` now takes `--grad-accum` (effective batch unchanged while
the resident batch shrinks), defaults to **batch 4 on CPU** and 16 on CUDA,
and `--estimate-first` prints peak RSS with a warning past 3 GB. Measured
1,410 MB at batch 2 × 128 tokens, so batch 4 × 384 needs watching on a machine
with 1 GB free. TF-IDF stays the default retrieval backend — no model
download, no extra memory.

---

## Phase 4 — design (agreed before building)

### Unit vs. submission unit

The app submits **whole stored sections** — revision 12 was the entirety of
`4.0 PROCEDURES`, not one row. So:

- **Table rows are where edits are applied**, per A3.
- **`old_text` / `new_text` are the whole stored section**, exactly as the app
  would submit it.
- **1–3 edited rows per example**, so a revision can carry several small
  changes the way a real one does.
- Report the **token-length distribution on the built dataset** — the earlier
  measurements were on whole sections without edits and will not transfer.

### Sampling

- **Stratify by section type** (Objectives / Scope / Policies / Procedures) so
  procedures — which hold all 487 table rows — do not swamp the rest. Report
  counts per type.
- **Minimum 150 positive examples per issue label.** Adjust the generator mix
  to reach it and raise the total above 3,000 if needed; training runs on
  Colab, so size is cheap. Report per-label counts and name any label that
  cannot reach the floor.

All earlier Phase 4 rules stand: the quality bar below, the borderline-match
discard rule, and decision 9.

---

## Phase 4 — dataset quality bar (agreed before building)

**Treat every generated example as if a real staff member submitted it and a
real admin will judge it.** A dataset of mechanical edits teaches the model to
spot mechanical edits, which is not the task.

- **Readability.** Every example must read like something staff would actually
  write: grammatical, in the manual's style, no broken sentences, no leftover
  markers, no obviously mechanical edits (random words, doubled spaces,
  nonsense substitutions).
- **Label correctness.** Every label must be right as a real admin would judge
  it. Where a generator produces an edit whose correct verdict is unclear,
  **discard it rather than guess**.
- **Realistic edit patterns.** Mix them: several small edits in one revision,
  a good change combined with a bad one, a whole sentence reworded rather than
  one word swapped, and legitimate edits that look suspicious.
- **Change reasons.** Every revision carries a realistic `change_reason` in
  staff language ("Updated to reflect the new collection schedule"), including
  some vague or misleading ones on bad revisions. A few have none, to exercise
  the clause 6.3 hard fail.
- **Quality gate in `build_dataset.py`.** Validate each example - markers,
  grammar sanity, label consistency against the Layer 1 flags where applicable
  - and report rejection counts per generator.
- **Report borderline sentence matches.** The 0.6 similarity cut-off in
  `sentences_removed` decides whether an edit is a rewrite or a removal, and so
  whether the example carries `requirement_removed`. Report how many pairs
  scored **0.5-0.7**, with a few examples, using
  `diffing.sentence_match_report()`. A count creeping up means the threshold is
  carrying more weight than it should.
- **At CHECKPOINT 4:** show 5 random examples per generator, plus the 10 the
  quality check scored most borderline, for review as a real admin before any
  training.

---

## Phase 4 — what was built

### Files

| File | What it holds |
|---|---|
| `revision_pipeline/section_doc.py` | A stored section parsed into the places an edit can land: table rows, prose sentences. Edits one; renders the whole section back. |
| `revision_pipeline/generators.py` | 22 edit generators across approve / needs_revision / reject, plus the change-reason pools. |
| `revision_pipeline/quality.py` | The gate. Judges each candidate as an admin would and discards rather than guesses. |
| `scripts/build_dataset.py` | The build: first pass, top-up passes, dedup, balancing, splits, dataset card, Checkpoint 4 samples. |
| `scripts/report_token_lengths.py` | Token-length distribution on the built dataset (design point 3). |
| `scripts/report_rule_coverage.py` | Measures the rule-hard share instead of trusting the declared set. |
| `tests/test_unit_alignment.py` | The unit-level comparison described below. |

### What the build does

1. **Parse once.** Every usable section is parsed and its context assembled up
   front; generation then runs more than once over the same jobs.
2. **First pass** — every generator, `--per-section` attempts each.
3. **Issue top-ups** — for each label still under the floor, re-run only the
   generators that can produce it. A uniform `--per-section` cannot reach the
   floor for a rare label: 156 units in the whole corpus carry an obligation
   modal, so raising it for everything mostly produces more of what is already
   plentiful.
4. **Approve top-ups** — the issue top-ups only run generators that produce an
   issue, so each round pushes the approve share down. Without its own rounds
   the build came out 8% approve.
5. **Quality gate** on every candidate, counted by reason.
6. **Balancing** (see below), then a document-grouped 5-fold split, the
   dataset card, and the samples.

### Balancing, in priority order

The three goals conflict, and the order matters — getting it wrong cost two
full builds:

1. **Per-label floor** (150). Never traded away.
2. **Verdict balance.** No verdict class is trimmed below `--verdict-floor-share`
   (0.2). A dataset that is 8% approve teaches the model to say no.
3. **Section type.** No type may exceed `--type-max-share` (0.45), trimmed
   weakest-first, and only from examples that are spare under 1 and 2. A type
   that cannot be trimmed that far stays over its share and the report says so.

The first attempt capped each type at 2.5× the smallest with no regard for the
other two, and took its whole surplus out of the approve class: 1,225 examples,
102 of them approve, and not one from `typo_fix`, `whitespace_format`,
`benign_reorder`, `redundant_removal` or `equivalent_synonym`.

### Finding that changed Phase 1: the rules could not see a step change hands

Layer 1 compared roles, key terms and figures as **whole-section sets**. Give
step 4 to an officer who already owns step 7 and the set of roles present is
identical, so the rules reported nothing — and the quality gate then discarded
the example for claiming `responsibility_changed` when Layer 1 could not see
it. 64 examples went that way in the first probe build.

`diffing.aligned_units()` now pairs the units that are the same step before and
after the edit (a table row is matched on its step text, so a changed
Responsibility cell still matches the same step), and Layer 1 compares roles,
key terms and figures **again on each matched pair**, unioning the result with
the section-wide view. Nothing the old view caught is lost; reordering rows
still reports nothing.

Identical units are paired first and only the leftovers go through the
pairwise scan, so the common case — one to three units edited out of twenty —
stays close to linear.

**`RULE_HARD` is now measured, not declared.** The unit-level comparison made
role reassignment visible to the rules, so the declared set drifted.
`report_rule_coverage.py` counts non-approve examples on which Layer 1 raises
no flag at all.

### Generators added during the build

- **`bulk_deletion`** — `mass_deletion` only worked on tables, and half a table
  often falls short of the deletion threshold, so `excessive_deletion` reached
  a fifth of the floor. This cuts a run out of a table *or* a prose section and
  keeps the example only when the cut is genuinely large but not a replacement.
- **`key_term_vagueing`** — the commonest way a named control disappears from a
  procedure is not deletion but genericisation ("attach the Disbursement
  Voucher" → "attach the document"), and it leaves a readable step, which
  straight deletion often does not.

Six generators that only ever looked at table rows now edit prose sentences
too (`modal_weaken_single`, `negation_flip`, `numeric_change`,
`non_equivalent_swap`, `partial_key_term_delete`, `contradiction_from_context`).
63 of the 104 usable sections have no table at all, so those generators had
been returning `None` for Objectives, Scope and most Policies — exactly the
section types the dataset was thinnest in. `numeric_change` went from 16
produced to 55 on the same probe.

### Build result (2026-09-17, `--per-section 5`)

**2,637 examples, 19 documents, 22 generators.** 3,238 candidates generated,
75 rejected by the gate, 0 duplicates, 526 trimmed by the type cap.

| | |
|---|---|
| approve | 663 (25%) |
| needs_revision | 667 (25%) |
| reject | 1,307 (50%) |
| Procedures / Policies / Objectives / Scope | 1,423 / 919 / 191 / 104 |
| files | `all.jsonl` 9.3 MB, splits 9.3 MB, ~2.3 MB packed |

Nine of the ten issue labels reach the 150 floor. `negation_changed` reaches
**110** and cannot go higher on this corpus: only about 110 units contain
"shall" and 79 contain a negation word, and 15 further flips were generated
but rejected because they reverse the sense without changing a negation word
("before" → "after"), which Layer 1 does not count.

**Borderline matches:** 69 examples (2.6%) contain a sentence pair scoring in
the 0.5-0.7 band around the 0.6 removal cut-off; 10 more scored 0.5 as hard
negatives that trip a rule by design. Everything else scored 1.0.

**Edited units:** 2,336 examples edit one unit, 162 edit two, 26 edit three.
The 51 above three are `bulk_deletion` and `mass_deletion`, which are bulk cuts
by definition - a deliberate exception to the 1-3 rule.

**Token lengths** (`report_token_lengths.py`): p50 207, p75 477, p90 759,
p99 1,871. `max_length=384` keeps the change whole for **70%** of examples,
512 for 77%. The Phase 2 figure of 83.5% was measured on whole sections with
no edit applied; the markers an edit inserts push it down.

### The 40% rule-hard target is not met

The build report's own figure (43%) is computed from the **declared**
`generators.RULE_HARD` set, which went stale the moment the unit-level
comparison made role reassignment visible to the rules. Measured on the built
dataset:

| Measure | Result |
|---|---|
| Layer 1 raises no flag at all (non-approve) | 136 / 1,974 = **7%** |
| Layer 1 alone reaches the wrong verdict (all) | 833 / 2,637 = **32%** |
| Layer 1 alone reaches the wrong verdict (non-approve) | 417 / 1,974 = **21%** |

The two requirements pull against each other: the quality gate *requires*
Layer 1 to confirm six of the ten labels, which by construction makes those
examples rule-visible. What is left for Layer 2 is where the rules see
something and still reach the wrong answer - all 368 `clarifying_addition`
examples (rules say needs_revision, truth is approve), all 227
`contradiction_from_context` (rules see only a changed figure, truth is
reject), all 111 `step_reorder_dependent` (rules see nothing), and the hard
negatives.

### Deviation: no examples with a missing change reason

The quality bar asks for a few examples with no `change_reason`, to exercise
the clause 6.3 hard fail. They are **not** in the dataset, deliberately:

- A missing reason is a Layer 1 hard fail, so Layer 2 never sees the example —
  the pipeline short-circuits before the model runs.
- Training on them would teach the model to reject content that is fine, since
  the text itself carries no defect.
- The gate would reject them anyway: a reject example with no issue label, and
  there is no issue label for a missing reason.

The hard fail is covered by `tests/test_layer1_rules.py` instead.

### Second sweep of extraction glue (2026-09-17)

The reviewed glue table caught two-word fusions. A sweep of the re-extracted
sections found **17 occurrences of longer runs** the table did not cover —
`itempurchasesintherecords`, `organizationadviseraswitnessesinthe`,
`BUR Sinthe'Utilization'columnoftheRBUD`, `JE Vusing`, `OS Dandfurthersecure`
and ten more. All are written out explicitly in `_LOWER_GLUE`, no segmentation.
Applied to the stored sections with `clean_section_content --apply`
(17 sections; database backed up to `db.sqlite3.bak-2026-09-17-glue` first).
Glue occurrences: **17 → 0**.

Re-cleaning also exposed a latent bug: `_render_table` emitted `|  |` for an
empty cell and only the *storage* path collapsed it to `| |`, so re-cleaning
reported 41 sections as changed when 17 had really changed. The renderer now
collapses the spaces itself, which makes a second cleaning pass a no-op.

---

## Checkpoint 4 — rejected, and what the rebuild changed

The first build was reviewed example by example and **not approved**. Nine
faults were found; all are fixed below. Two of them were faults in the *rule
layer*, not the generators, and would have mislabelled real revisions too.

### 1. Renumbering was being read as a changed figure

The worst of them. Layer 1 treated every digit as a quantity, so changing
"3.15" to "1.15" counted as a changed figure - and where a sibling section
still carried the old number, as a contradiction.

**Measured on the rejected build:**

| Generator | Renumbering only | A real quantity |
|---|---:|---:|
| `contradiction_from_context` | **216 of 227 (95%)** | 11 |
| `numeric_change` | **152 of 160 (95%)** | 8 |

- `layer1_rules._strip_item_numbers` blanks an item or step number at the start
  of a line, a cell or a clause before numeric tokens are read.
- `generators._quantity_spans` finds only real figures: a number with a unit
  ("15 days", "30%"), the house-style "three (3)" pair, or an amount of money.
- `contradiction_from_context` now needs a fact **a sibling section still
  states**. Durations are compared in days, so "1 year" here and "365 days"
  there are recognised as the same fact - which is the example given in the
  review. Only **2 sections in the whole corpus** restate a fact that way, so
  this generator is capacity-limited to 3 examples and `contradicts_manual` is
  carried by `step_reorder_dependent`.

### 2. `benign_reorder` was swapping dependent steps

It now refuses any section that is a procedure table, any pair where either row
opens with a step number, and any pair mentioning a sequence ("Return to step
4", "thereafter", "once"). It is left with genuinely unordered lists, which is
6 examples - small, and correct.

### 3. `redundant_removal` was deleting distinct entries — generator removed

It duplicated a row into `old_text` and then removed it, which made `old_text` a
section the manual never had, and read exactly like deleting a real bank account
row. The corpus was searched for genuine duplicates: the only repeats are the
same step text in **different sub-procedures** of one section, where deleting
one is not approve either. So the generator is gone, replaced by two honest
hard negatives:

- `row_merge_reformat` - joins two rows that are one step, keeping every word.
- `benign_reorder` - as above.

**Why Layer 1 flagged `negation_changed` on the bank rows:** the negation test
was a prefix regex, `(un|non|dis|in)[a-z]{3,}`, which matched **"university"**,
"information", "internal", "inspection" and "disbursement". Deleting any row
containing one of those changed the count. Replaced by an explicit
`config.NEGATED_FORMS` list.

### 4. The approve class was thin and repetitive

`clarifying_addition` was 55% of approvals, reused two sentences, and one of
them ("Copies are retained by the office concerned") added a requirement. It is
deleted. Seven approve generators now work from the section's own content:

| Generator | What it does |
|---|---|
| `typo_fix` | corrects a misspelling the submitted text carries |
| `whitespace_format` | spacing and punctuation only |
| `equivalent_synonym` | a curated phrase swap, grammar-aware |
| `acronym_expansion` | spells an acronym out on first use, from the corpus's own definitions |
| `spell_out_figure` | "15 days" becomes "fifteen (15) days", the manual's house style |
| `legal_reference_format` | "R.A. 9184" becomes "Republic Act No. 9184" - same statute |
| `cross_reference_addition` | adds a pointer to a real sibling section |

`equivalent_synonym` no longer draws from the glossary, which produced "as
mandatory", "Once accomplish" and "all office", and renamed documents ("Form"
became "Template"). It uses a curated list of phrases with their inflections,
skips any span inside a Title-Case run, and is checked by the grammar gate.

A **strategy cap** (`--strategy-max-share`, default 0.07) stops any single
phrasing filling the dataset: no one typo, synonym pair or added clause may
hold more than that share.

### 5. Change reasons now match the edit

`_REASONS` is keyed by the kind of edit - typo, format, term, clarify, merge,
reorder - and each approve generator draws from its own pool. "Fixed spelling"
can no longer appear on a deletion. Revisions that are not approvals draw from
the plausible and vague pools, which fit any edit.

### 6. Broken generators

- **Sentence splitter**: `diffing.sentences` joins a fragment back when the one
  before it ends in an abbreviation. "governed by E.O. No. 2, series of 2016"
  was three sentences, so an edit near it looked like several sentences
  appearing and disappearing.
- **`key_term_vagueing`**: only terms that really name a document are eligible,
  and the replacement is the generic noun for *that kind* of document, with the
  article and any bracketed acronym handled as one unit.
- **`partial_key_term_delete`**: takes the article and the acronym with the
  term, so "submits the Disbursement Voucher (DV) to" no longer leaves "submits
  the to".
- **`non_equivalent_swap`**: modal pairs, sense-reversal pairs and
  strengthening are all excluded. "should" becoming "shall" is not an issue.
- **`negation_flip`**: rebuilt on `config.SENSE_REVERSALS`. with/without is
  only applied where the following word keeps it grammatical, so "without first
  exhausting" is never turned into "with first exhausting".
- **`foreign_insertion`**: a table section takes a row of the matching column
  count, a prose section takes a sentence.
- **Role generators**: `_role_rows` requires a Responsibility/Activity table and
  a role the rule layer itself recognises. The frequency column ("Quarterly",
  "First Week of the Year") is excluded by name.

### 7. A grammar and format gate

`quality.grammar_faults` rejects an example when the **edit introduces**
repeated function words, a determiner before a determiner ("each the"), an
article before a verb or a preposition ("submits the to"), a dangling
preposition, "with" followed by a gerund, unbalanced parentheses, table rows of
differing column counts, or a row that stops mid-phrase. Faults already present
in the master copy do not count against the edit.

### 8. Extraction, third pass

- **Glue**, found by segmenting every rare token against the corpus's own
  vocabulary and then written out by hand: `itreceives`, `overthe`,
  `purchaseditems`, `renderthe`, `Providersif`, `asnecessary`,
  `bidsfromprospective`, `otherSDs`, `supportingdocuments`, `theCGMC`,
  `theVPSDto`, `Fillout`, `backto`, `LNUIGO`, and the
  `BUR Sinthe'Utilization'columnoftheRBUD` run. **Count now 0.**
- **Acronym over-splitting**: the rule split `CGMCreleasinglogbook` into
  "CGM Creleasinglogbook". Its second half is now length-bounded, and both
  spellings are repaired explicitly.
- **Step numbers stranded in the Responsibility cell**: the source writes
  "Student<br>1.", so FAM 6.01 4.4 read "| Student 1. | Pays ... |" and every
  role in the table looked like a different person.
  `_move_stranded_step_numbers` puts the number back at the front of its step.
- **Rows wrapped across two lines**: "(see FAM" / "9.02 Receiving of
  Deliveries)" and "List of Scholars/" / "Grantees per Scholarship Grant" were
  each one step split by the PDF's line wrapping. `_join_wrapped_rows` merges
  them, and is off entirely in tables with no step numbers, so the bank and
  calendar tables are untouched.
- A **final glue pass** runs over the assembled text, because the per-fragment
  repair happens before a cell's line breaks are joined.
- `_render_table` now collapses its own doubled spaces, so re-cleaning stored
  content is a no-op. It reported 41 changed sections when 17 had changed.

New command **`api/management/commands/reextract_manuals.py`** re-extracts from
the master-copy files and updates sections **in place**, matched by section
number. The previous re-extraction used a script that was never committed.
203 sections matched, 0 unmatched, nothing deleted; 2 revisions and 3 history
rows still attached. Backups: `db.sqlite3.bak-2026-09-17-glue`,
`db.sqlite3.bak-2026-09-17-cp4fixes`.

### 9. Sensitive data

- Bank account numbers are replaced in the dataset with the fixed placeholder
  `0000-0000-00` (`build_dataset.redact`). 14 distinct numbers in the corpus, 21
  examples carry the placeholder, none survive unredacted. The pattern requires
  two or more hyphens so a year range like "2016-2017" is left alone.
- `CHECKPOINT4_REVIEW.html` is gitignored.
- **The repository is public and the master copies are already in it.** See
  "Known issues" below.

### Decisions applied

- **Rule-hard**: verdict disagreement accepted as the measure, re-measured
  below.
- **Negation**: `config.SENSE_REVERSALS` added (21 pairs), detected on matched
  units, reported under `negation_changed` with the pair as evidence, and
  reported once - never also as a term swap. 32 tests in
  `tests/test_sense_and_numbers.py`.
- **`MAX_LENGTH` was set to 512** at Checkpoint 4, and **reverted to 384 on
  2026-09-17** once it emerged that the notebook had been training at 384
  all along. See "MAX_LENGTH settled at 384" below.

---

## Phase 4 — final dataset (2026-09-17, third round)

**2,811 examples, 19 documents, 25 generators.** 3,962 candidates, 143 discarded
by the gate, 510 by the strategy cap, 498 by the section-type cap.

| | |
|---|---|
| approve / needs_revision / reject | 1,002 (36%) / 661 (24%) / 1,148 (41%) |
| Procedures / Policies / Objectives / Scope | 1,441 / 1,109 / 150 / 111 |
| labels at the 150 floor | 9 of 10 (`key_term_deleted` 123) |
| borderline sentence matches | 64 |
| hard negatives | 21 |
| distinct generator strategies | 116 |
| cross-references | 161 = 16% of approvals |

### Third round of fixes

1. **Grammar gate discards** rather than rewrites: a dangling tail ("of.",
   "using."), a fragment opening ("No. 2, series of ..."), an item number lost
   from a **surviving** line, a truncated row, padded empty columns. Discards
   are reported per generator. The item-number rule had to be narrowed once:
   comparing the sets of numbers flagged every legitimate deletion, 607 of
   them, because removing a step removes its number too.
2. **Synonyms are one-directional.** The plain word is the one these manuals
   use, so "use" never becomes "utilize", "forwards" never becomes "endorses".
   `verify | check` is out of the glossary - in this register it is not a
   change of meaning. A swap can no longer land inside a named document
   ("Transcript of Record"), which needed a pattern that runs through the
   lowercase connectors rather than one that checks the immediate neighbours.
3. **Negation flips are discarded** inside an already-negative clause (which
   would produce a double negative) and where the result is a past participle
   used attributively ("disapproved policies").
4. **Role spacing** is normalised at extraction and in Layer 1, so
   "Accounting Staff -3" and "Accounting Staff-3" are one person and a spacing
   difference is never an issue. (`db.sqlite3.bak-2026-09-17-rolespacing`.)
5. **Empty Responsibility cells inherit the role above** before Layer 1
   compares units (A3). A blank cell means the same person is still working,
   not that nobody is.
6. **Cross-references** point only at sections with TF-IDF cosine similarity
   >= 0.08 (the 75th percentile of within-document similarity: median 0.042,
   p75 0.079, p90 0.120), sit at the end of a sentence, never in a table cell
   holding a value and never after a semicolon, and are capped at 15% of the
   approve class after stratification - 16% as shipped.

### Blind label audit

`scripts/export_label_audit.py` writes `label_audit.csv` (50 examples, seeded,
stratified by verdict, with the diff and empty columns to fill in) and
`label_audit_key.csv` (the labels, generator and strategy). The labels are not
in the first file, so the audit measures agreement rather than recognition.

Accepted limitations are recorded in `DATASET_CARD.md`: thin cross-section
contradictions, out-of-sequence steps only as swaps, narrow typo variety, 21
hard negatives, `key_term_deleted` below the floor.

---

## Blind label audit — result (2026-09-17)

50 examples, seeded and stratified by verdict, judged without the labels.

| | |
|---|---|
| verdict agreement | **44 / 50 = 88%** |
| issue set exact | **47 / 50 = 94%** |
| both | 44 / 50 |

Confusion: 18 approve and 18 reject agreed outright, 8 needs_revision agreed;
2 needs_revision judged approve, 2 needs_revision judged reject, 2 reject judged
needs_revision.

### The six disagreements, and what changed

| # | Generator | Disagreement | Outcome |
|---|---|---|---|
| 6, 16 | `step_reorder_dependent` | reject vs needs_revision | **Relabelled needs_revision.** A swapped sequence is a slip a reviewer sends back, not a control removed or reversed. 143 examples. |
| 22 | `non_equivalent_swap` | "any records" -> "all records" labelled an issue | **Fixed.** Widening a scope is strengthening, and strengthening is not an issue - the same rule that keeps "should" -> "shall" out. The `any -> all` direction is no longer generated. |
| 30 | `non_equivalent_swap` | "computer file" -> "computer record" labelled an issue | **Fixed.** The glossary pair separates two *verbs*. A pair whose words are noun/verb ambiguous is now only applied in verb position - the start of a step, or after a modal or conjunction. |
| 32 | `numeric_change` | "365 days or 1 year" -> "730 days or 1 year", labelled only a changed figure | **Fixed.** A figure the same unit restates another way is left alone; changing it makes the sentence contradict itself, which is a different finding. |
| 49 | `combo` | needs_revision vs reject on weights that no longer total 100% | Follows from the #32 fix: the generator no longer produces that shape. |

The auditor also flagged, without disputing the label: `acronym_expansion`
dropping an article ("by Commission on Higher Education" - **fixed**, a body's
name now takes "the"), and "settlement of any their" reaching the dataset
(**fixed**, the gate now rejects "any" before a possessive; "all their" is
still fine English and is left alone).

`verify | check` was removed from the glossary in the same pass - in this
register it is not a change of meaning. Three tests that used it as their
example of a non-equivalent swap now use `approve | review`.

---

## Phase 4 — dataset after the audit (2026-09-17)

**2,762 examples, 19 documents, 25 generators.** 3,934 candidates, 143 discarded
by the gate, 534 by the strategy cap, 495 by the section-type cap.

| | |
|---|---|
| approve / needs_revision / reject | 1,019 (37%) / 730 (26%) / 1,013 (37%) |
| Procedures / Policies / Objectives / Scope | 1,402 / 1,084 / 155 / 121 |
| labels at the 150 floor | 8 of 10 (`key_term_deleted` 126, `non_equivalent_term` 89) |
| cross-references | 166 = 16% of approvals |

The verdict mix is now within a point of the planned 40/25/35.
`non_equivalent_term` fell from 150 to 89 as the direct cost of the two audit
fixes, which was the right trade: both cut examples whose label a reviewer
disputed.

A second audit pair is exported as `label_audit_r2.csv` /
`label_audit_r2_key.csv` (the first pair is left untouched).

---

## Phase 5 — Colab training results (2026-09-17)

Five folds on a T4, about 4 minutes each. Fusion fitted on each fold's val
predictions and scored on that fold's test predictions; rules-only and
model-only scored on the same rows. Averaged over the five folds:

| System | Verdict accuracy | Verdict macro-F1 | Issue micro-F1 |
|---|---:|---:|---:|
| rules only | 0.791 | 0.788 | 0.667 |
| model only | 0.951 | 0.946 | **0.853** |
| fusion | 0.975 *(as Colab reported it)* | 0.974 | 0.695 |

**The official figure is 0.978**, not the 0.975 in this table - see "The
official figures" below. The two numbers come from the same predictions; the
difference was the fusion estimator selection, which has since been removed.

**The verdict result is what Phase 2 was for.** The rules alone get 79% of
verdicts right; Layer 2 takes that to 95%, and fusion to 97.8%. The 28%
verdict-disagreement measured on the dataset was a fair prediction of how much
work was left for the model, and the model did it.

**The issue result was a regression, and it came from Layer 3.** Layer 2 alone
scored 0.853 on issue micro-F1; fusion dropped it to 0.695 - below even the
rules. Fusion reported the **union** of the rule flags and the model's issues,
so every rule false positive was added to a set the model had right. The union
was chosen before there was anything to measure it against.

**Fixed: `ISSUE_POLICY = "rules_precise"`, and fusion now scores 0.854.**
Verdict accuracy is untouched at **0.978** - the verdict is fusion's under
every policy, only the issue set changes.

| Policy | Issue micro-F1 | Labels it never reports |
|---|---:|---|
| model | 0.853 | - |
| union (was) | 0.695 | - |
| **rules_precise** | **0.854** | - |
| agree | 0.858 | `contradicts_manual`, `out_of_scope_content` |

**`agree` has the best average and is not usable.** It can only report a label
the rules also raised, and the rules raise neither of those two - a reordered
step sequence and inserted foreign content are exactly what Layer 1 is blind to
and Layer 2 exists to catch. Per label it scores 0.000 on both. Micro-F1 does
not show this: it is dominated by the frequent labels, so a policy can silence
a fifth of the categories and still come top. Its lead also rests on one fold -
`agree` wins folds 1 and 4 and loses 0, 2 and 3.

`evaluate_folds.py` now refuses to recommend a policy that never reports a
label that appears in the truth, so this cannot be re-derived by accident.

`rules_precise` adds a rule flag only for labels the rules are precise about,
measured per fold on the validation predictions. The same three cleared the
0.90 floor in all five folds - `excessive_deletion`, `modal_weakened`,
`non_equivalent_term` - so they are pinned in `config.PRECISE_RULE_LABELS`.
Without that list the policy would have no labels to add at inference time and
would silently behave as `model`.

Per-label F1 under the chosen policy against the old union, worst first:
`numeric_changed` 0.460 -> 0.966, `responsibility_changed` 0.596 -> 0.966,
`requirement_removed` 0.637 -> 0.783, `key_term_deleted` 0.694 -> 0.782,
`negation_changed` 0.765 -> 0.951.

### The official figures: 0.978 verdict, 0.854 issues (means of five folds)

**The official numbers are the ones in `Backend/ml/reports/fold_evaluation.md`:
verdict accuracy 0.978, issue micro-F1 0.854.** They come from the committed
code, the committed dataset and the pinned seed, over the same fold predictions
Colab produced, and can be reproduced with one command. The Colab run reported
0.975 for the verdict; that environment is not pinned anywhere.

The difference is not in the model. The fold predictions are the same files,
and Layer 1's features are recomputed deterministically from the text. What
moves is which estimator `FusionModel.train` picks: it fits logistic regression
and gradient boosting and keeps whichever validates better, and that decision
is close enough to flip between scikit-learn versions.

Forcing one estimator across all five folds:

| Fusion estimator | Per fold | Mean |
|---|---|---:|
| logistic only | 0.985, 0.946, 0.971, 0.977, 0.979 | 0.9715 |
| boosting only | 0.981, 0.985, 0.965, 0.979, 0.981 | 0.9782 |
| as selected (boost, boost, logistic, boost, boost) | | 0.9794 |

Fold 1 alone swings 4 points on that choice - 0.946 with logistic, 0.985 with
boosting. One fold selecting differently under Colab's scikit-learn accounts
for the 0.4 points exactly.

**Resolved 2026-09-18: fusion is pinned to gradient boosting.** The selection
step is gone. `FusionModel.train` fits one estimator, so the same predictions
give the same result wherever they are fitted, and the official verdict figure
is now **0.978** - the "boosting only" row above, as expected. Boosting was
kept because it was better on four of the five folds and on the average.
A result that depends on which scikit-learn fitted it is not a result. Local
scikit-learn is 1.9.0.

### The shipped Layer 3 model

Trained locally from `folds_from_drive`, on **all five folds' validation
predictions** (2,762 rows), into `Backend/ml/saved_models/context_v2/` as
`fusion.pkl` and `fusion_config.json`. That is a different object from the
per-fold models `evaluate_folds.py` fits to measure: those see one fold's val
predictions each and are thrown away.

`Backend/ml/saved_models/` is gitignored, so this is a local artefact. It has
to travel with the Layer 2 weights - a clone will not have it.

**The Kaggle archive cannot overwrite it.** The archive is built from
`context_v2/final/`, which holds Layer 2 only, so unzipping into `context_v2/`
adds `encoder/`, `tokenizer/`, `heads.pt` and `label_config.json` beside
`fusion.pkl` rather than over it. Verified by unzipping a mock archive over the
real directory: `fusion.pkl` came out byte-identical (sha256 unchanged). The
packaging cell now also refuses to write an archive containing `fusion.pkl` or
`fusion_config.json`, so it cannot start happening later.

### The issue policy was chosen on the test folds, and holds on validation too

`ISSUE_POLICY` was selected on each fold's **test** predictions, which is the
same data the reported figures come from. Checked the other way round - the
precise-label set taken from the test rows and the policies scored on the
validation rows, the mirror of what was done - the ranking is identical:

| Policy | Scored on val | Scored on test |
|---|---:|---:|
| model | 0.8534 | 0.8526 |
| union | 0.6955 | 0.6952 |
| rules_precise | **0.8546** | **0.8535** |
| agree | 0.8573 | 0.8577 |

Same order, same margins, and `agree` still unusable for the reason above. The
choice is not an artefact of which split it was measured on.

### Two faults in the Colab run

- **The final-model cell trained on the CPU.** GPU memory sat at 0.0 GB for
  thirty-plus minutes while the folds had taken four minutes each on the same
  runtime. The cell already passed `--device cuda`, the same as the fold cell,
  so the cause is not visible from the arguments. `pick_device` now refuses to
  run at all when a CUDA device is available and the run would not use it, and
  the reverse, so the next run reports the cause instead of being slow about
  it. It also prints the GPU name and per-epoch progress, flushed, since
  thirty minutes of silence reads as a hang.
- **`MAX_LENGTH` was pinned at 384 in the notebook** while `config.MAX_LENGTH`
  said 512. The folds were trained at the wrong length. The notebook now reads
  it from config, so the two cannot drift again. **The reported results above
  were produced at 384.**
- Cell 2 could not be rerun: it deleted the directory it was standing in. It
  now steps out to `/content` first and stops with a clear message if the clone
  fails, rather than letting every later cell fail for an unrelated reason.

### MAX_LENGTH settled at 384

The five folds trained at 384 because the notebook pinned it there while
`config.MAX_LENGTH` said 512. Rather than retrain, `config.MAX_LENGTH` is now
**384**, so the final model and the app run at the length the reported numbers
were measured at. The notebook reads the value from config, so the two can no
longer disagree in either direction.

What it costs: at 512 the marked change fits whole for 75% of examples, at 384
for 68%. The other 32% are not lost - `_window_around_change` keeps a window
around the markers with the head and tail of the section, so the change itself
is always in the input. It is context that is trimmed, not the edit.

The numbers in "Colab training results" above therefore describe the
configuration that is now in force. Raising `MAX_LENGTH` again invalidates
them and means retraining the folds.

---

---

## Phase 6 — wired into the app

### The model is in place and verified

`check_setup.py` reports Ready: packages, entity lists, dataset, all five model
pieces, and the pipeline loads with no warnings. The fingerprint in
`label_config.json` is `6a6a5c667a3c4d11`, which matches the code - so the
weights were trained by this pipeline at this `max_length`. `fusion.pkl` came
through the unzip byte-identical (`cb0fe399966fb5bb`), as designed.

**Revision 13 smoke test** (FAM 6.02 :: 1.0 OBJECTIVES, no change reason):

```
verdict     reject   confidence 1.0
hard fail   no_change_reason, clause 6.3
explanation "This revision cannot be accepted in its current form. No reason
             for the change was recorded, which clause 6.3 requires."
status      pending - unchanged
```

Two observations from it, both since addressed:

- The hard fail was only in `trace.layer1.hard_fails`. **Fixed:** the result now
  carries `hard_fails: [{label, clause, evidence}]` beside `verdict` and
  `issues`, the view passes it through, and the review panel shows it as the
  blocking reason. The trace is unchanged.
- The edit is `accounts` -> `payments`. With a change reason supplied the
  pipeline rejects it and labels it `out_of_scope_content`, where
  `non_equivalent_term` fits better. **Recorded as a known limitation** here and
  in `DATASET_CARD.md`: `non_equivalent_term` is 74 of its 89 examples
  `all -> any/some`, so the model has seen little else under that label. The
  verdict is the reliable part; the label points at where to look.

### Second smoke test — with a change reason, so the model actually runs

Revision 13 only exercised the Layer 1 hard fail: a missing reason short-circuits
the pipeline before Layer 2. **Revision 14** was created for this - FAM 6.04 ::
3.0 POLICIES, a real obligation weakened the way a staff member might, with a
plausible reason.

```
edit         "...shall be handled in accordance with Republic Act 10173..."
          -> "...may be handled in accordance with Republic Act 10173..."
reason       "Updated to match how the office actually works."

verdict      needs_revision    confidence 1.0
change type  substantive
hard fails   none
issue        modal_weakened  [source: both]  clause 7.5.3  medium severity
             evidence: "shall" became "may"
layer 2      ran
fusion       boosting, confidence_source "fusion"
explanation  "Some points need addressing before this revision is approved. The
              word "shall" became "may", so an obligation became a permission.
              Please check these points before approving."
```

The `both` source is the interesting part: the rules and the model independently
found the same thing, which is the case fusion is meant to be most confident
about, and it was.

**Timing on the laptop** (i3-1215U, 8 logical cores, CPU only - no GPU):

| | |
|---|---|
| first assessment after the server starts | **7.6 s** |
| every assessment after that | **0.3 - 0.5 s** |

`load_models` caches the model per process, so only the first admin to press the
button waits; the encoder is being read from disk in that 7.6 s. A cold start per
request would make the feature unusable, which is why the cache exists.

Revision 14 is kept as a test entry, like 12 and 13. It sits in the pending
queue - delete it if that is in the way.

### What was wired

- `REVISION_AI_PIPELINE` in `settings.py`, default `"v2"`. `"v1"` keeps the two
  older DistilBERT models, which are untouched.
- `ai_assessment_view` runs `pipeline.assess_revision()` on v2 and stores
  `ai_verdict`, `ai_issues`, `ai_explanation` and `ai_trace` on the revision, so
  the screen can show it again without re-running the model and a decision can
  be reviewed later beside the advice that was on screen at the time. The
  response is flat for v2 and says which pipeline produced it.
- `list_revisions` returns `ai_trace` alongside the fields it already returned.
- `AiPanelV2` on the admin review screen: verdict badge, confidence meter,
  change type, the explanation, and each concern with its clause, severity,
  source and evidence. A "Details" button opens the raw trace. Marked
  **advisory only**, twice - a chip in the header and a line at the foot
  saying the decision is the admin's and nothing here changes the status.
- v1 still renders through the original panel; the screen picks by
  `data.pipeline`.

Verified: the endpoint returns 200 with the verdict, issues and trace; the
fields are stored on the revision; the revision's status is untouched; and the
frontend builds.

### The crash at the end of the Kaggle run

`train_layer2.py` opened `test.jsonl` without checking it exists. The final
model trains on everything and keeps only a slice for early stopping, so its
data directory has no test split - and the run died *after* the whole GPU
training had finished. The call site checks now and says it is skipping.

The Kaggle notebook also hard-coded one mount path for the fold dataset;
Kaggle's actual path depends on how the dataset was added. It searches
`/kaggle/input` for `fold_*/thresholds.json` instead.

---

## Clause 6.3 — the change reason, in two tiers

The reviewer could not see the reason at all. `list_revisions` had always
returned `change_reason`, the model stored it, all three submission endpoints
saved it — and the admin review card simply never rendered it. So the panel
could say "no reason was recorded" with nothing on screen to check it against,
and a reason that *was* given was equally invisible. It now sits above the
action buttons, with the clause named, and a submission carrying no reason
shows a red **not provided** badge rather than a blank space.

Behind that, the reason was only enforced in the browser: the three endpoints
did `(request.data.get('change_reason') or '').strip()` and accepted whatever
came back, including nothing. The merge form did not check at all. That is how
revision 13 exists.

### The two tiers

`ml/revision_pipeline/change_reason.py` grades a reason, and **both the API and
Layer 1 call the same function**, so a revision cannot be accepted by one and
hard-failed by the other.

| tier | test | API | pipeline |
|---|---|---|---|
| `missing` | empty | **400** | hard fail, clause 6.3 |
| `invalid` | under 15 characters, under 3 words, no letters, fewer than 3 distinct characters, or identical to the section title | **400** | hard fail, clause 6.3 |
| `weak` | passes the above but carries under 2 content words once filler and boilerplate are removed | accepted | **advisory**, low severity |
| `ok` | everything else | accepted | nothing |

Tier 1 blocks. Tier 2 never does: the edit itself may be perfectly good, and
refusing it would punish a submitter for prose rather than for the change. It
becomes an advisory that the reviewer sees and that pushes an otherwise-clean
`approve` to `needs_revision`.

Demonstrated on one edit, changing only the reason:

```
"The Cashier shall prepare the report and submit it to the Dean."
"The Cashier shall prepare the report, and submit it to the Dean."

reason "Reworded after the June 2026 training."  -> approve
reason "Minor changes as discussed"              -> needs_revision
                                                    advisory vague_change_reason
                                                    override "advisory"
```

### Why the advisory is not an issue label

`vague_change_reason` is deliberately **not** in `ISSUE_LABELS`. That list is
the trained label space: adding to it would change the issues head's output
dimension and the fusion feature vector, invalidating the shipped Layer 2
weights and the 0.978 figure. Advisories travel in their own field on
`Layer1Result` and `FusionResult`, surface at the top level of the result
beside `hard_fails`, and never touch Layer 2 or the fusion features. The
override can only tighten a verdict — it turns `approve` into
`needs_revision` and nothing else.

### The reason is never an input to Layer 2

Worth stating plainly, because the two tiers above could suggest otherwise.
The change reason is **traceability under clause 6.3** — it is required so the
change is planned and recorded, and it is shown to the reviewer so they can
judge it themselves. It is **not** a feature of the model. Layer 2 sees the
old text, the new text and the surrounding document context; it does not see
the reason. So the verdict depends only on the textual change and its context,
and cannot be talked into approving a bad edit by a well-written justification.

The one thing nothing checks is whether the reason actually *describes* the
edit — a submitter can write "updated the retention period" and change a bank
account instead. Checking reason-against-edit consistency is **future work**;
it needs a labelled corpus of reason/edit pairs that does not exist yet, and
the generators would have to produce mismatched pairs as a new negative class.

### Tests

`ml/revision_pipeline/tests/test_change_reason.py` (39) covers both tiers, the
title check, the advisory staying out of the label space, and the override in
both directions. `api/tests.py` (7, Django's runner) covers all three
endpoints returning 400 with a usable message, nothing being stored when they
do, and a weak reason being accepted and reaching the reviewer.

Fixtures in four existing test modules used placeholder reasons — `"policy
update"`, `"document review"`, `"x"` — which the new rule correctly refuses.
Replaced with reasons a submitter would actually write.

**Revision 13 was left exactly as it is**, so the "not provided" path stays
testable end to end.

```
pipeline   227 passed
api          7 passed
```

---

## Queued — to do after Phase 2, before Phase 4

1. ~~Re-extract the manuals with the new A3 table format.~~ **Done** — see
   "Re-extraction" below.
2. **Extend `clean_section_content` to clean subtitles too.** It currently
   cleans `content` only, which is why `FAM 8.02` still stores
   `'5.0 LIST OF FORMS <!-- End of picture text -->'`. Decision 9 matches on
   that title, so the artifact has to go.
3. **`role_swap` must handle combined roles.** Reducing `"X/Y"` or `"X or Y"`
   to a single party is `responsibility_changed` — never an approve example.
   30 such entries exist in `entities.json` (e.g. `BAC Chairperson/ University
   President`, `Accounting Staff-1 or 6`).
4. **`DATASET_CARD.md` must report example counts per section type**
   (Objectives / Scope / Policies / Procedures).
5. **Before Phase 5:** run the Phase 7 size check (`scripts/check_repo_size.py`)
   and prepare a safe first push — Colab clones from GitHub, so the dataset and
   pipeline have to be on the remote before any training can start.
6. **Phase 7 README must cover** how to fetch the final model from Drive and
   where to unzip it: `Backend/ml/saved_models/context_v2/`, so the folder ends
   up holding `encoder/`, `tokenizer/`, `heads.pt`, `thresholds.json` and
   `label_config.json`. Also: creating and activating the venv.

---

## Re-extraction (done, 2026-09-17)

Ran **in place**, matching stored sections to fresh ones by document + section
number. All **197 stored sections matched**, zero orphans, so no row was ever
deleted and `on_delete=CASCADE` never fired. One section was created
(`SDM 3.06 :: 5.1 Certificate of Good Moral Character`, 0 words, and a forms
subsection so not a revision unit under decision 9).

Verified afterwards: **198 sections** in the 19 documents, **2 revisions** and
**3 history rows** still attached to their original section ids, and sections
carrying a `| --- |` separator row went **1 → 46**.

Safety copy taken first:
`Backend/ml/exports/revisions_and_history_20260917-083912.json`, plus
`db.sqlite3.bak-prereextract-20260917-085407`.

**On the "1 → 46" figure.** 46 sections contained pipe characters before, but
only **one** had a real separator row (`| --- | --- |`, the line that declares
the column count and marks the header) — SDM 3.03, which had been updated by
hand during testing. The other 45 had pipes only as cell delimiters in
flattened rows. The two numbers matching at 46 is a coincidence.

**COE** is a `Manual` row pointing at `HRM_4_MoGMsSE.02.pdf`, MD5-identical to
`HRM_4.02.pdf` — the same document uploaded twice, into the COE department.
It is excluded from entity mining and from the dataset via
`_corpus.EXCLUDED_DOCUMENTS`; `load_documents()` returns 19 documents with COE
absent.

### Extraction artefacts — cleaning pass added

These are damage from the PDF text layer, **not mistakes anyone wrote**.

| Artefact | Before | After |
|---|---:|---:|
| Glued words (`theBookkeeper`) | 18 | **0** |
| Digit glue (`3.Undergraduate`) | 30 | **0** |
| Colon glue (`Undergraduate:If`) | 4 | **0** |
| Merged steps in one cell (`1. … 2. …`) | 17 | **0** |
| Stray backtick (`Responsibility\``) | 1 | **0** |
| Stray punctuation lines | 0 | **0** |

`ocr_engine.repair_artefacts()` handles the glue; merged steps are split into
one row per step with the role inherited from the row above (Appendix A3).
Two ordering bugs were found doing this: the repair originally ran *before*
Markdown stripping, so `3.**Undergraduate:**If` showed an asterisk where the
patterns expected a letter; and the step splitter required a full stop, so a
step ending `…(VPSDAS) 2. Checks…` was missed.

**A7 correction:** these artefacts must **never** be used as `real_typo_fix`
examples. They are extraction damage, not human error, so "correcting" one is
not a revision a person would ever submit. `real_typo_fix` may only use
genuine spelling and grammar errors present in the source document.

**Revision 12's `diff_text` is deliberately left unchanged.** Its baseline
section content changed, so the stored diff no longer reproduces against the
current text. Rewriting a historical record to match a later extraction is
worse than a stale diff; the original is in the export either way.

### Recomputed after cleaning

- **Entities:** 129 roles, 27 offices, 67 systems, 53 forms (was 168/31/73/53).
  The drop is the cleaning working — glued and merged variants no longer mined
  as separate entities.
- **Usable units: 562** (75 prose + 487 table rows), counting each table row as
  a unit per A3. Previously 109 prose-only.
- **`--per-section`:** 3.6 reaches 2,000; **5.3 reaches the 3,000 target**,
  far below the 25/unit cap (ceiling 14,050). **This supersedes decision 8** —
  the 3,000 target is now comfortably reachable and the shortfall note is no
  longer needed.
- **Retrieval re-verified:** `4.0` no longer returns its own `4.5`; `4.5` gets
  sibling `4.4` but not parent `4.0`.
- **Token lengths** (whole sections, 109 measured): text_a p50 140, p95 727.
  `max_length=384` keeps the change whole for 83.5%. Phase 4 units are mostly
  single table rows and will be much shorter — **re-measure on the dataset
  itself before settling `max_length`.**

---

## Known issues / deviations

### Definition of done — Layer 2 on CPU, measured

The spec asks that Layer 2 "trains on CPU within a reasonable time using
`--max-examples`". It had never been run. It has now, on the i3-1215U, writing
to a scratch directory (the shipped `heads.pt` hashed `ca9f62ff9dc2974f`
before and after - unchanged):

```
--max-examples 200 --device cpu    batch 4 (CPU default; the T4 used 16)

epoch 1/3  loss 2.3953  191.3 s  peak 1150 MB  val_acc 0.335
epoch 2/3  loss 1.9695  232.5 s  peak 1347 MB  val_acc 0.565
epoch 3/3  loss 1.3531  227.9 s  peak 1222 MB  val_acc 0.705
total 943 s (15.7 min)
```

Loss falls monotonically and accuracy is still climbing at epoch 3, so the CPU
path genuinely trains. Scaled to the full 1,561-row training split (7.8x):
**~28 min/epoch, ~1.4 h for three epochs**, nearer two hours with the full
validation pass, peaking at **1.35 GB**.

**Answer to "can it be retrained without a GPU?": yes, in about two hours,
needing roughly 1.4 GB.** Practical once, impractical to iterate with. Memory
is the real obstacle, not time - 1.35 GB on a machine that often has ~1 GB
free would page unless other applications are closed.

Caveat recorded in `EVALUATION.md` 8: this measures throughput, not
attainable accuracy. 0.705 on 200 examples says nothing about whether a
CPU-trained model would reach the shipped 0.951.

---

### The rule layer's figure: three numbers, one of them the ablation's

`rules_only` is **0.791**, scored with the clause 6.3 change-reason check
excluded. The same rows can be given three figures, so all three are stated:

| figure | what it measures |
|---|---|
| **0.791** | before the clause 6.3 validation existed |
| **0.730** | with the validation applied to the corpus's generated reasons |
| **0.791** | the ablation's figure: validation deliberately excluded from scoring |

The first and third agree to three decimals, which is the evidence that the
entire 0.730 was the reason check.

**Why exclude it.** The ablation asks how much of the verdict is decidable
from the textual change alone. The clause 6.3 check examines the submission's
metadata rather than the change, and in the live system it fires at the API
before an assessment is requested, so anything reaching Layer 2 has passed it
already. Leaving it in measured the generators' placeholder reasons instead of
the rules: **579 of 2,762 rows** carry filler such as `"Per instruction."`
that tier 1 rejects, and rows with no reason were handed the literal string
`"recorded"`, also rejected. Every one hard-failed, and `rules_only_verdict`
returns `reject` on any hard fail, so a fifth of the corpus scored `reject`
regardless of content.

Excluded for all three ablation systems so the comparison is like-for-like,
though only `rules_only` can notice: `model_only` reads Layer 2's
probabilities and fusion reads a feature vector with no reason-derived column.
Confirmed by re-running - **fusion held at 0.978 / 0.854**, `model_only` at
0.951, unchanged to three decimals.

This was not caused by the citation rule. The clause 6.3 validation shipped in
`ee69160` and the folds were never re-evaluated afterwards, so 0.791 had been
stale since then; the 0.730 run was simply the first honest measurement of the
code as it stood.

---

## The assessment moved to the staff side, before submission

Previously a reviewer pressed a button and got a verdict. Now the submitter
runs the check before submitting, reads the result, and confirms; the result is
stored and the reviewer reads the same assessment. **There is only ever one
verdict for a revision**, which is the point of the change.

### How the snapshot is kept honest

`POST /api/revisions/pre-assess/<section_id>/` assesses unsaved text and
returns the result plus an opaque `assessment_id`. At submit the client sends
only that id; the server loads its own row, **recomputes** the content hash
from what is actually being submitted, and compares. Nothing about the result
is ever accepted from the client, and the hash is never computed in the
browser - a second implementation would be free to drift, and a client-posted
verdict would be a snapshot of whatever the client felt like claiming.

`content_hash = sha256(section_id, section.content, proposed, change_reason)`,
each part normalised (NFC, CRLF to LF, trailing spaces per line, blank runs).
Aggressive on purpose: being sent back to re-check over a pasted CRLF teaches
people the check is broken. The reason is in the hash because Layer 1 judges
it under clause 6.3, so changing it means the revision genuinely has not been
assessed. The section's own text is in the hash because an assessment is about
a *comparison*, not a string.

### Mandatory, and never a gate

The check is required; the verdict is not. A submitter may submit a `reject`.
Enforced on both sides, because frontend-only enforcement is not enforcement:
the Confirm button stays disabled until a check has run for the current text,
and the endpoint returns 400 when no valid assessment exists for exactly the
content submitted.

Two mismatches, two messages - they are not the submitter's fault in the same
way, and one generic "please re-check" makes the innocent case read as a bug:

| cause | message |
|---|---|
| edited after checking | "You have changed the text since the AI check..." |
| the section moved underneath | "This section was updated by someone else while you were working..." |

### What the reviewer gets

Stored on the revision: verdict, confidence, change type, issues, hard fails,
advisories, **both wording variants**, trace, `assessed_at`, model fingerprint,
content hash and the section's hash at check time. From those the review screen
shows where the assessment came from, how long the submitter waited before
submitting, and whether the section has changed since.

`ai_source` distinguishes `staff_precheck` from `admin_legacy` from `none`,
backfilled in migration `0013`. A result a reviewer generated under the old
workflow is never shown as something the submitter read. The reviewer's assess
button survives **only** for `ai_source = "none"`, labelled as a reviewer-side
assessment under the old workflow; anything already assessed returns 409.

### Layer 4 addresses two audiences

`explain(..., audience=...)` renders the same findings, evidence and clause
numbers for both, changing only the opening and closing:

```
reviewer : This revision should be sent back for adjustment. The word "shall"
           became "may", so an obligation became a permission. Please check
           these points before approving.
submitter: A reviewer would probably ask for changes before approving this.
           The word "shall" became "may", so an obligation became a
           permission. You can still submit - the reviewer decides, not this
           check.
```

The stored label is the same word in both cases; the softer wording is display
only. Phrasing is seeded by the **content hash** rather than the revision id,
which did not exist at check time - so the submitter and the reviewer read
word-for-word the same sentences, and re-checking identical content produces an
identical result rather than a reworded one.

### Measured on the live database (revision 17)

```
check   HTTP 200  14.8 s   needs_revision  modal_weakened  "shall" became "may"
        (14.8 s is the cold model load; warm checks are ~0.3 s)
edited after check   HTTP 400   "You have changed the text since the AI check"
no check at all      HTTP 400   "Please run the AI check before submitting"
submit  HTTP 201   0.01 s   ai_source staff_precheck
reviewer re-assess   HTTP 409   already carries an assessment
```

**Submission is now 0.01 s**: the model cost has moved entirely into the check,
where the submitter is expecting to wait.

### All three submission paths, not just text

Text, upload and merge each require a check for exactly the content being
submitted. The two non-text paths differ in a way that matters: **the
submitter is agreeing to content they did not type.**

- **Upload.** The revision is judged on whatever `extract_text` pulls out of
  the file, which is not always what the submitter believes is in it. The
  check returns the extracted text alongside the verdict, so they can see what
  the system actually read before committing to it. The hash is taken over the
  extracted text rather than the file's bytes - that is what the assessment saw
  and what the reviewer will read, and it means re-uploading the same file
  after a check is not treated as a change.
- **Merge.** The merged text is derived on the server, by the same helper
  `propose_merge` uses, so what was checked is what would be stored. It comes
  back with the result for the same reason.

`section_content_hash` is variadic for this: a merge rests on the target *and*
each source. Hashing only the target would tell a submitter they had changed
the text when someone else had edited a source - so the "updated by someone
else" message is now correct for either, and the reviewer's "section changed
since this check" flag asks the same question about all of them.

### Pre-warming

`PREWARM_MODEL=1` loads the encoder on a **background thread** at WSGI startup.
Measured: `import backend.wsgi` returns in 0.49 s and the model is ready about
6 s later, so startup is not delayed at all - the server accepts requests
immediately and a check arriving during that window blocks on the same lock it
would have blocked on anyway.

Off by default, deliberately. `runserver` restarts on every file save, and
paying the load per save would make development miserable; it is meant for the
demo and for production, where processes are long-lived. It is in `wsgi.py`
rather than `AppConfig.ready()` because `ready()` runs for every management
command, so `migrate`, `test` and `makemigrations` would each load a 700 MB
model they never use.

**The trade-off if it were loaded inline instead:** startup would block for the
full load - roughly 14 s cold - and gunicorn's `--preload` would pay it once
before forking, which is fine in production and wrong for development. The
background thread avoids having to choose.

### Housekeeping, wired rather than declared

Both are exercised by tests through the endpoint that applies them, because a
constant that nothing reads looks identical to a working limit:

- **Rate limit**, 60 checks per user per hour, returning 429. Tested that it
  fires, that it is per user rather than global, and that checks outside the
  window do not count.
- **Retention**, 7 days, swept opportunistically whenever a check runs -
  nothing in this deployment runs a scheduler. Consumed rows are never touched:
  they belong to a revision's record. `py manage.py sweep_pre_assessments
  [--dry-run] [--days N]` does the same on demand, for cron or before a backup.

### Consequences worth recording

**Revision 13's `no_change_reason` path is unreachable for new revisions.**
The clause 6.3 tier-1 check now runs at the pre-assess endpoint as well as at
submit, so a revision cannot reach the reviewer without a usable reason.
Revision 13 stays as the only live example of that hard fail.

**The population of submitted revisions is now selected.** A submitter who
reads "this would likely be rejected" may simply not submit. Whatever reaches
the reviewer is therefore biased towards changes the submitter believed would
pass, and any future evaluation against real submitted revisions measures that
filtered population rather than the work staff actually attempt. This is a
methodological consequence of the design, not a defect, and it is better named
than discovered later. Recorded in `EVALUATION.md` 9.

**The load profile changed.** Assessment moved from a handful of reviewers
pressing a button to every staff member on every submission, plus re-checks
after edits. The measured numbers are unchanged - three concurrent assessments
in 0.61 s, ~740 MB shared across a process - but the arrival rate is not, which
brings the task queue in `DEPLOYMENT.md` 8 forward from a distant scaling note
to a real requirement. The endpoint is rate-limited to 60 checks per user per
hour, and unconsumed pre-assessments are swept after 7 days.

**Pre-warming is now required rather than advisable.** The 13.6 s cold start
used to land on a reviewer who had chosen to press a button. It now lands on a
staff member mid-task, on their first submission of the day.

---

## Rebuilding the database on a new machine

Untracking `db.sqlite3` had a consequence nobody had thought through: `git
pull` **deletes** a file that has stopped being tracked, so a teammate who
already had a working copy lost it and every request started failing with
`no such table: api_customuser`. The README still said the database was
committed, which sent them looking in the wrong place.

Three management commands now cover the rebuild, and README section 2 is
written around them:

- **`import_mastercopies`** - reads every PDF in `media/mastercopies/`,
  creates a manual, splits it into sections and tags them. Reuses
  `upload_manual`'s extraction path rather than reimplementing it, so a
  rebuilt checkout matches everyone else's instead of quietly diverging.
  Department comes from the filename prefix, which is reproducible; the
  mapping in one person's database is not. 19 manuals, ~210 sections.
- **`make_admin <username>`** - sets `role='admin'` and `is_approved`.
  `createsuperuser` grants Django-admin access, which is a different thing:
  a fresh superuser can reach `/admin/` and nothing else, and that reads as
  a broken login rather than a missing flag.
- **`seed_test_users`** - one approved staff account per department, so the
  first thing on a new machine is not approving yourself.

### Two bugs found by actually running it

**The importer polluted the directory it read from.** `Manual.file` has
`upload_to='mastercopies/'` - the same directory being scanned - so handing
Django a `File` object wrote a second copy beside each original, and because
the name was taken it appended a random suffix. Twenty PDFs became
forty-eight, and the mangled names (`FAM_4_2s7frgp.01.pdf`) then parsed as
different documents: 24 manuals from 20 files, with titles like "FAM 4". The
bytes were already in the right place; only the reference was missing, so it
now sets `manual.file.name` directly and writes nothing.

**Title parsing split on the wrong thing.** `HRM_4_MoGMsSE.02.pdf` has its
number broken across underscores, so taking the second part gave "HRM 4" - a
different document. The number now has to contain a dot.

Both were only visible by running the command against a throwaway database
and looking at the result; neither would have shown up in a dry run.

### Also fixed: tests were writing into the working tree

`MEDIA_ROOT` is the real media directory during tests, so every run of the
upload tests left a `revision*.txt` behind and git slowly filled with
debris. The upload tests now override `MEDIA_ROOT` to a temporary directory.

---

## Admin portal — phase 1 (announcements and navigation)

### What was already there

- The admin had **six** nav items and no Dashboard, Announcements or
  Calendar. It lands on Users.
- **Manual cards had no click handler at all**, so the drill-down was
  net-new, exactly as "Sections" had been on the staff side. `Sections` has
  its own manual picker and is otherwise self-contained.
- Announcements had the model and a Django-admin form but **no API**: the
  staff banner could be read and never written.

### Announcements

Full CRUD under `/api/admin/announcements/`, admin only. `shows_as` is
**computed, not stored** - dated is Upcoming, undated is the banner - so the
admin list and the staff dashboard cannot disagree about which a row is.

The form says which it will be *as you type*, because an optional date field
silently deciding between two very different placements is invisible
otherwise. It also shows reach ("visible to 2 staff in CAS"), counting only
**approved** staff, since someone who cannot sign in cannot read it.

Deleting confirms and offers "deactivate instead": deactivating keeps the
record of what was posted, and the staff side already hides inactive rows.

Tests cover the round trip end to end - post a banner here and it appears on
the staff dashboard; post a dated one and it lands under Upcoming and not as
a banner; target a department and the others do not see it.

### Navigation

A fourth nav group, **Content** rather than Communication: these are notices
posted to a portal, not messaging, and a calendar or a staff help page would
belong in the same group later.

The drill-down makes the section count a button. `Sections` keeps its picker
with the arriving manual selected, so the screen behaves identically however
it was reached - the only difference is that one choice has been made for
you. `handleManualChange` was split into `clearManual` / `selectManual` so
the picker and the drill-down share one path; two paths would drift and the
drill-down would quietly skip whichever reset the picker does.

### Future work — there is no router

Navigation in **both** portals is `useState`, not routing. Consequences:

- The browser back button only works for the manual → sections drill-down,
  where it is wired with the History API (`pushState` plus a `popstate`
  listener). Back from anywhere else leaves the application.
- **URLs are not shareable or bookmarkable.** Every screen is the same URL,
  so "look at this revision" cannot be sent to anyone.
- Reloading always returns to the default page for the role.

Adding a router touches both portals and every navigation path already
tested, which is why it was not done here. Recorded rather than attempted.

---

## Admin portal — phase 2 (the dashboard)

### What was already there

- **No dashboard and no endpoint for one.** The admin landed on Users.
- The shell was firing **two list requests on every tab change** purely for
  their `.length` - `pending-users/` and `revisions/?status=pending` - to
  put counts on the nav badges.
- `RevisionReview` opens on the Pending tab and takes no props.
- The real database has **6 revisions across 4 distinct days**, which is
  the whole reason the chart needs a fallback: the fallback is what that
  database actually renders.

### One endpoint

`/api/admin/dashboard/` returns all six areas. Same reasoning as the staff
dashboard - the widgets read the same few tables and the first screen after
signing in is the worst one to make slow - plus one the staff side did not
have: the nav badges now come from it too. A badge and a dashboard that
claim the same thing from two sources will eventually disagree.

**Nothing on this screen re-runs an assessment.** The verdicts beside recent
decisions are the ones stored at submission, which are the ones the reviewer
acted on. A test patches the pipeline to raise and expects the dashboard not
to notice.

### The six areas

1. **Needs attention** - full width above everything else, and only rows
   that are not zero. Pending revisions (with the oldest wait, mentioned
   only once it is two days or more, so it is a fact about the queue rather
   than about today), accounts awaiting approval, revisions whose section
   was edited after the assessment, untagged sections. When all four are
   zero the strip says so in one line instead of showing four zeroes.
2. **Activity** - submissions and decisions per day over 30 days.
3. **By department** - grouped through the *document's* department, not the
   submitter's: people move between departments and the document is the
   thing being changed.
4. **Recent decisions** - and whether each matched the stored assessment.
   Worth showing because a run of overrules is worth noticing; it says
   nothing about who was right, which is the one thing it cannot say.
5. **Upcoming** - unfiltered, unlike the staff version. This is the desk the
   notices are posted from.
6. **System** - what is installed, and how the assessments on file were
   produced. A non-zero `none` count explains why some review screens show
   less: those revisions predate the pre-check.

### The chart, and when not to draw one

A line through four points spread over a month invites the reader to see a
slope that is really the gaps between submissions. So the endpoint counts
**days that carry activity** and reports `enough_for_chart`; below five, the
same numbers are printed as a table with the empty days dropped, which
claims nothing about shape.

Deciding it in the endpoint rather than the component puts the rule in one
place and makes it testable, which it now is in both directions - including
the case that looks like plenty of data and is not: twenty submissions in
one afternoon is still one day.

The chart is hand-drawn SVG. Three series over thirty points does not
justify a charting library and a second set of theme rules, and SVG text
inherits nothing, so every colour is named from the tokens or it renders
browser-default black on a paper ground. The three series are distinguished
by dash pattern as well as hue - same lesson as the diff marks: colour that
collapses in greyscale is not carrying the distinction.

### Looking at the chart, and what that changed

The chart could not be seen: the real database takes the table path, which
is the point of the fallback but leaves the other branch unexamined until a
presentation. `seed_activity` writes demonstration revisions across a
fortnight and `--clear` removes exactly them - every row it creates is
tagged in `change_reason`, so the undo is exact rather than a guess at which
revisions were real. It touches nothing else, so clearing returns the
database to what it was.

Rendering it showed something the numbers could not. **Three lines of equal
weight overlap exactly at the zero baseline**, which is most of a quiet
fortnight, so the only series visible there is whichever was drawn last.
Submitted is now a filled area: it differs in *form*, which survives both
the overlap and a greyscale printout, and the two decision lines read
clearly on top of it.

One thing that pass got wrong first time round: the dashes looked solid in
the rasterised image, and the obvious conclusion - "too fine to read" - was
about the renderer, not the chart. PyMuPDF ignores `stroke-dasharray`
altogether. The patterns were coarsened anyway, since that costs nothing,
but the lesson is that a rasteriser is not a browser and only the browser
settles how a dash renders.

### The wording on a decision that differs from the assessment

First draft said **"overruled the assessment"**. Wrong: "overruled" casts
the assessment as a ruling that was struck down, which frames the reviewer
and the pipeline as a contest with a right answer. It reads as a scorecard.

It now states what the assessment said - **"assessment said reject"** - with
"the reviewer's decision stands" on hover. No verb is applied to the person
at all. The reviewer has context the pipeline does not, disagreeing is a
normal part of the job, and the only reason to surface it is that a run of
differences is worth a second look at *the model*.

### Opening one revision from the dashboard

A decision row jumps to `RevisionReview`, which needed a prop it never had.
It carries the **status as well as the id**: the queue opens on Pending, and
a decided revision is by definition not in that list, so an id alone would
land on a tab that cannot show it. The card is highlighted and scrolled to,
not expanded - the reviewer asked to look at it, not to have a panel opened
on their behalf.

---

## Admin portal — phase 3 (safeguards and attribution)

Three changes that look unrelated and answer one question: afterwards, can
anyone tell what happened and on whose authority?

### What was already there

- **Every destructive action had `window.confirm` and nothing else** - seven
  of them, across Departments, Manuals (single and bulk), Sections and
  Users. `confirm` asks whether you meant it, which is the wrong question
  when the laptop has been signed in and left open in a shared office.
- **Section edits were already snapshotted.** Both `update_section` and
  `review_revision` wrote `SectionHistory`, so "log direct edits" was not
  the gap it sounded like.
- Reviewer notes were a **placeholder**, not a label, and the staff side
  already called the same text "the reviewer's feedback".

### Re-authentication

`POST /api/auth/confirm-password/` exchanges the account's password for a
short-lived signed token; the destructive endpoints require it in
`X-Reauth-Token`.

A token rather than the password itself, for three reasons. The password
never travels with the destructive request. One confirmation covers a bulk
delete instead of a password per manual. And `TimestampSigner` keeps the
expiry in the signature, so there is no session or cache row to go stale -
a token still verifies after a restart, which matters because one that
silently died on deploy would read to the admin as a rejected password.

The three failures are told apart on purpose. **Expired has to be
distinguishable from wrong**, or someone who took five minutes over a
confirmation is told their own password is incorrect, and the next thing
they do is try to reset it.

### The guard that would not have guarded anything

`delete_section` was the obvious route to protect. But the admin Sections
screen called **`review-delete` first** and only fell back to it - so
guarding the admin route alone would have secured the path nothing took,
and every deletion would have gone through the other one unchallenged.

Both are guarded now, and the screen calls the admin route directly. The
stale comment on the fallback said "so staff can delete during review";
no staff screen calls that endpoint, and its permission was left as it was
rather than narrowed on a guess about who it was for.

### What is *not* guarded, deliberately

Approving a user, reviewing a revision, deactivating an announcement.
Asking for a password on a reversible action is not extra safety - it is
what teaches people to type the password without reading the prompt. On
announcements the prompt still offers "deactivate instead", because that
keeps the record of what was posted.

### Attribution: why a version exists

`SectionHistory` gains `source`, `change_reason` and a link back to the
revision. An approved revision and an admin typing into the edit box used
to produce identical rows.

- **`source`** is set at the write, not inferred from whether a revision
  happens to exist - a revision can be deleted, and the history has to
  stay true afterwards.
- **The reason is copied, not referenced**, for the same reason. The link
  is kept too, for as long as it resolves.
- **Old rows default to `unknown`, not `direct`.** Defaulting them would
  record a guess as a fact, and an honest gap is better in an audit trail.

The direct edit is the only path with no submission behind it - no
submitter, no reason, no review - so it is the only place a reason can be
asked for, and the edit form now asks. **Recorded, not enforced**: an admin
fixing a typo mid-audit should not be blocked by a form, and a required
field would be full of "." within a week.

### Reviewer notes are feedback to the submitter

Renamed, and promoted from a placeholder to a real label - a placeholder
disappears the moment you start typing, which is exactly when it matters
that the person who submitted will read this. The hint says where it
appears and that returning a revision without one leaves them nothing to
act on.

---

## Staff portal — phase 3 (Help, and the visual pass)

The manuals themselves are the aesthetic. Everything below answers one
question: would it look right printed and filed in an office?

### The type split

There was no serif in the system at all - Instrument Sans did display and
body both. Added `--font-doc: "Source Serif 4"`. Chosen over Spectral and
the bookish faces because it was drawn for screen text and reads as
*official* rather than *literary*: a more characterful face would have read
as a design layer on top of the manuals instead of a continuation of them.

The rule, applied across all five staff screens:

| voice | face | where |
|---|---|---|
| the application talking | sans | buttons, labels, navigation, filters |
| the manual talking | serif | clause text, section and document names, excerpts, diffs, the change reason |
| an identifier | mono | document numbers, version tags, header-block values |

### Editing inks, and the one channel that must not depend on colour

Deliberately not the semantic `--danger` / `--success`, which are interface
states in a saturated register. These are pen and stamp colours: struck
`#8c3a2e`, inserted `#1f6b4f`.

**Colour cannot carry the diff, and was never going to.** In greyscale the
two inks collapse to `0x54` and `0x5f` - eleven values apart, effectively
identical. What actually distinguishes them is geometry: `line-through` for
a deletion, `underline` for an insertion, a rule in the margin for a
touched line, and semantic `<del>` / `<ins>` so a screen reader says which
is which. Colour is the redundant channel here, not the primary one.

**The margin rule was therefore raised from `#c7c3b5` to `#8a8474`:
1.69:1 to 3.57:1 against paper.** It is the only signal in the diff that
carries no colour information at all, so it has to be visible on its own -
and at 1.69:1 it was faint enough to miss entirely. 3.57:1 clears the 3:1 a
non-text marker needs while still reading as a pencil line rather than a
border. **Do not lighten it back**: it will look tidier and will quietly
remove the one channel that survives colour being taken away.

### Stamps where there is a decision, marks where there is a list

A decision on a controlled document is a rubber stamp: outline, letter-spaced
caps, muted ink, one to one and a half degrees off square, `opacity: 0.82`.
Rotation is dropped under `prefers-reduced-motion`.

But only in the **detail view**, where there is one decision and it is the
point of the page. Repeated down a list a stamp stops reading as a stamp and
becomes a badge at an odd angle, so rows use `.status-mark` - the same inks
set as a quiet label with a dot, no border, no rotation.

**Status pills survive where they report interface state** - an upload
result, an AI check verdict, a filter chip. Stamps mark a decision about a
document; pills report what the application is doing. Fourteen of them
remain on the staff side on purpose.

### Header-block motif

Every page of a real manual carries a bordered header: document no.,
revision no., effectivity date. A simplified version now sits above section
content and above a revision's detail, values in mono. It is what makes a
section on screen read as part of a controlled document rather than a record
in an application.

### Reading measure

Prose capped near 68ch - past that the eye loses its place returning to the
left margin, and a manual is read rather than skimmed. **Tables are
deliberately exempt**: a responsibility table is a grid, and squeezing it
into a reading column only makes it wrap.

### Help

Static, no backend. Leads with the thing people most need to hear - running
the check is required, passing it is not - because a check people believe is
a gate becomes something they try to game rather than read. Also states that
the reason for change is never an input to the model, so a well-written
reason cannot talk the check into approving something and a plain one cannot
count against them.

---

## Staff portal — phase 1 (navigation, Sections, My Revisions)

Five tabs: Dashboard, My Manuals, Sections, My Revisions, Help. Dashboard and
Help are honest placeholders until phases 2 and 3 - a page that says "not
built yet" and points somewhere useful beats a blank one, which reads as
broken.

### What was already there, before changing anything

Worth recording because the brief assumed more existed than did:

- **"Sections" was a dead nav item.** `StaffDashboard` rendered
  `selectedManualId ? <StaffSections/> : <StaffManuals/>`, so clicking it
  with nothing selected showed My Manuals. It was really "the selected
  manual's sections". Cross-manual browsing did not exist, so this was
  net-new rather than an extension.
- **`StaffRevision.jsx` existed and was never imported** - 165 lines already
  titled "My Revisions" with an all/pending/approved/rejected filter. Revived
  and extended rather than replaced.
- **`list_sections` already supported `search`** over subtitle and content,
  and a `tag` filter - but only within one manual. The new endpoint reuses
  the same predicate so a search means the same thing from either route.

### Built

`GET /api/staff/sections/` - every manual in the department, with `search`
(title and content), `manual` and `tag`. `staff_my_revisions` gained
`scope=mine|office`, `status=`, and the stored assessment fields
(`ai_source`, `ai_verdict`, `ai_issues`, `ai_explanation_staff`,
`ai_assessed_at`). Read-only: a test asserts that listing revisions never
produces an assessment, because the snapshot is a record of what the
submitter read and re-running it would manufacture a second verdict.

Per-section revisions stay inside the section view for context, but no
longer show `reviewer_notes` - two copies of feedback drift apart and
neither is the record. Each row links across to the detail view instead.

### Three decisions worth keeping

**One write endpoint was added**, against the brief's "read-only" list:
`POST /api/staff/revisions/<id>/seen/` setting `feedback_seen_at`. Without
it the badge could only ever count upward, never clear, which trains people
to ignore it. Only the submitter can mark their own, and nothing but a
timestamp changes.

**Status is filtered in the browser** so the counts on the filter row stay
true for the whole scope; a filter whose numbers move as you filter cannot
be read. Noted in the code that this stops paying at roughly a few hundred
revisions in one scope, and that the endpoint already accepts `?status=`
when it does.

**`.stat-card.is-selected` was only a background tint** - identical to
`:hover`, so the card under the cursor looked as chosen as the chosen one.
Selected now takes the 3px gold underline (the system's active marker), an
un-muted label, a distinct hover and `aria-pressed`.

### Roadmap — "returned for changes" is not a state

A revision sent back is `rejected` with notes; there is no separate state.
My Revisions filters on "rejected and carrying notes" to tell *act on this*
apart from *refused*, which is the question a submitter is actually asking,
but that is a presentation trick over a workflow that cannot express it.

The gap is worth naming: **the assessment is more expressive than the
workflow it feeds.** Layer 3 distinguishes `needs_revision` from `reject` -
send it back versus do not accept this - and the review flow collapses both
into `rejected`. So the system can tell a submitter their change needs
adjusting and then record the reviewer's identical judgement as a refusal.

Adding a `returned` state means new transitions, a second review round, and
deciding whether a returned revision is edited in place or resubmitted -
which is the dispute flow the staff spec explicitly deferred. Recorded, not
built.

---

### Future work — PRECISE_RULE_LABELS serves two purposes

`PRECISE_RULE_LABELS` does two unrelated jobs, and that is the underlying
problem:

1. **With Layer 2 present**, it filters which rule flags are worth adding to
   the model's labels. Here a label earns inclusion only if the model's recall
   for it is below 1.000 — otherwise the rule contributes false positives and
   nothing else.
2. **With Layer 2 absent**, it *is* the issue output. `keep = rule_labels &
   precise`, so a label missing from the list is not merely unfiltered, it is
   unreportable.

The two jobs pull in opposite directions: job 1 wants the list short, job 2
wants it to cover everything the rules can reliably say. **A configuration
choice here therefore cannot be judged on micro-F1**, because micro-F1 is
measured with the model present and is blind to job 2 entirely. That is not a
hypothetical — it is why `excessive_deletion` stays in the list despite
scoring +0.0006 against it.

The fix is to separate them: a filter list used when Layer 2's labels are
available, and the full set of rule flags when they are not. Rules-only mode
would then report everything the rules found, which is what a degraded mode
should do, and the filter list could be tuned on micro-F1 honestly. It needs a
second config entry, a branch in `merge_issues` on whether issue
probabilities arrived, and tests for both paths — small, but a design change
rather than a setting, so it is recorded here rather than made.

Measured while deciding whether to drop `excessive_deletion` from the list
(`EVALUATION.md` 4). Dropping it raises pooled issue micro-F1 from 0.8436 to
0.8442 and removes the only issue a reviewer sees in rules-only mode - on a
69% deletion, `"69% of the wording was removed"` becomes an empty issue list.
Kept, and the shipped configuration is unchanged.

---

### Deviation from spec 7a — train/val/test.jsonl stay committed

Spec 7a lists `Backend/ml/datasets/context_v2/train.jsonl`, `val.jsonl` and
`test.jsonl` as **not** to be committed, on the grounds that they duplicate
`all.jsonl` and are regenerated by `make_splits.py`. They are still tracked:
**11.1 MB across the three**, against `all.jsonl`'s 11.1 MB.

Verified they really are redundant - identical key sets to `all.jsonl`, no
extra `context` field, pure partitions by document fold. So the spec's reason
is sound.

**Kept anyway, deliberately**, because the spec's premise is not quite right:
`make_splits.py` writes `fold_N/train|val|test.jsonl`, **not** the top-level
three. Those come from `build_dataset.py`, which takes about 25 minutes.
Untracking them today would mean anyone cloning the repository - including the
panel, if they check - cannot reproduce the default split without a full
dataset rebuild.

Making this free is about fifteen minutes of work: a `--top-level` flag on
`make_splits.py` that writes fold 0's split to the dataset root, then untrack
the three files. Deferred rather than done because the defence is the near-term
priority and 11 MB in a repository that already carries an 11 MB `all.jsonl`
costs nothing operationally.

**Not a size risk:** the largest single file is 7.1 MB, well under GitHub's
50 MB warning and 100 MB limit. `check_repo_size.py` reports the current total.

---

### The GitHub repository is public and holds the master copies

Verified 2026-09-17 by anonymous request: `https://github.com/Doculan/DocuRoute1`
returns 200 to a request with no credentials (a non-existent repository returns
404), and `raw.githubusercontent.com` serves the files.

Already on `origin/main`:

- all **19 master-copy PDFs** under `Backend/media/mastercopies/`, pushed in
  commit `66406da` on 2026-09-13;
- two revision PDFs and one upload under `Backend/media/`;
- **`Backend/db.sqlite3`**, which holds the extracted section text - including
  the bank account numbers the dataset now redacts.

Redacting the dataset does nothing about any of this. The options are to make
the repository private, to remove the files from history and force-push, or to
decide the manuals are public documents. Note that making it private does not
retract copies already taken, and a force-push invalidates every existing
clone.

**Decided 2026-09-17: the repository stays public for now.** Eugene does not
have admin access and the repository owner is unavailable, so neither making it
private nor rewriting history is possible at the moment. This is a deferral,
not a resolution - it should be revisited when the owner is reachable.

What follows from that, for now:

- Colab clones the repository **without a token** (the prompt in cell 2 is left
  blank), which is what a public repository allows.
- `Backend/db.sqlite3` is no longer tracked as of commit `0f377fd`, so it will
  not appear in future commits - but **it is still reachable in the history**
  and served by `raw.githubusercontent.com` at earlier commits. Verified: the
  blob at `291744e` still returns 200 to an anonymous request. Untracking
  stops the bleeding; it does not undo it.
- Nothing further should be pushed while training runs.
- **Added 2026-09-23: personal names in template properties.** Three
  committed template files carried names in their document properties -
  the legacy DCR `.doc` (author, last saved by) and `MANUAL_BLANK.docx`
  with its `.bak` (creator, last modified by, company). Cleared in the
  working tree in phase 3b, and the `.bak` removed from the repository;
  the earlier versions are **still in the public history**. Same
  deferral: part of the history cleanup that needs the repository owner.



- **PyPI unreachable from the agent sandbox** (GitHub 200, PyPI times out).
  Dependency installs must be run by the user.
- **Two Python environments exist.** `venv/` has everything including pytest and
  sentence-transformers; the global interpreter does not. Eugene's `py` resolves
  to the venv because it is activated in his shell; an agent shell must call
  `venv/Scripts/python.exe` explicitly. **The venv is the environment of record.**
- **The 2 revisions and 3 history rows are test entries, not real-world data.**
  They must not be treated as an admin-decided evaluation set.
  **Revision 13 is kept as a Phase 6 smoke test:** pending, on
  `FAM 6.02 :: 1.0 OBJECTIVES`, with no `change_reason`. Expected assessment —
  a hard fail for the missing reason (clause 6.3), plus a flag for
  `"accounts"` → `"payments"`.
- **Known gap (clause 7.5.3): admins can edit sections directly**, through the
  Sections screen, bypassing the revision flow entirely. Such an edit gets no
  AI assessment, no `change_reason` and no approval step - only a
  `SectionHistory` row. The controlled-change path is therefore only as strong
  as the convention that admins use it.
- `ml/datasets/train_manual_augmented.csv` has mixed label encodings in one
  column: `['1', 'Appropriate', 'Needs Revision']`. Pre-existing, owned by a
  teammate, not touched by this overhaul.
- ISO clause map for this build is **6.3, 7.5.3, 5.3** (7.5.2 dropped, see #4).

---

## Corpus section structure (all 19 documents)

Every document has exactly the same five top-level sections. There are **no
References, Definitions or Annexes sections anywhere in the corpus** — the only
reference-only section is List of Forms.

| Top-level title | Documents |
|---|---|
| `N.0 OBJECTIVES` (2 as `OBJECTIVE`) | 19 |
| `N.0 SCOPE` | 19 |
| `N.0 POLICIES` | 19 |
| `N.0 PROCEDURES` (2 as `PROCEDURE`) | 19 |
| `5.0 LIST OF FORMS` | 19 |

The forms section is titled `5.0 LIST OF FORMS` in all 19, so decision 9 can
match on that string plus the singular/plural variants above.

**One extraction artifact found:** `FAM 8.02` stores its section as
`'5.0 LIST OF FORMS <!-- End of picture text -->'`. The `clean_section_content`
command cleans `content` but never `subtitle`, so HTML comments in headings
survived. One row affected; worth extending that command.

---

## Phase 1 — what was built

**1a. Prerequisite fixes**
- `ManualRevision` gained `reviewed_by`, `change_reason`, `ai_verdict`,
  `ai_issues`, `ai_explanation`, `ai_trace` (migration `0011`).
- `review_revision` now records `reviewed_by = request.user`.
- All three revision-creating views (`upload_revision`, `propose_text_revision`,
  `propose_merge`) accept and store `change_reason`.
- `list_revisions` returns the new fields.
- **Reason for change** is now a required field on the live staff paths in
  `StaffSections.jsx` (file upload and text edit).
- `UploadRevision.jsx` corrected: it posted to `/api/upload/<manualId>/`, which
  does not exist, with no auth header. It is still mounted nowhere — the live
  path is `StaffSections.jsx` — but it is no longer a broken example to copy.

**1b–1d. Pipeline package** (`Backend/ml/revision_pipeline/`)
- `config.py` — labels, clauses, severities, thresholds, feature order,
  special tokens, `PIPELINE_VERSION` and a fingerprint hash.
- `diffing.py` — line/word diffs, `marked_text`, ratios, sentence removal.
- `glossary.txt` (63 seeded pairs) + `glossary.py`.
- `entities.py` + `scripts/build_entities_draft.py` — mines roles, offices,
  systems and forms from the master copies.
- `layer1_rules.py` — hard fails, 14 features, 9 rule flags, change types.
- `tests/` — **62 tests, all passing.**

### Bugs the tests and smoke runs caught

| Bug | Fix |
|---|---|
| A *replaced* line counted as a deletion, so `excessive_deletion` fired on any single-line edit | Ratios use pure deletions only |
| Every edited sentence counted as removed, so a typo fix reported a removed requirement | Near matches count as surviving |
| One surviving sentence vouched for every deleted sibling (they share a skeleton) | One-to-one sentence matching |
| Reordering two list items read as a large deletion | `excessive_deletion` uses a bag-of-words net ratio |
| Short mined entity phrases ("Office") matched everything | Minimum phrase length of 5 |
| Stripping punctuation left a stray space, so a moved full stop read as substantive | Re-collapse whitespace after stripping |

### Open items for Phase 1

- `entities.json` has been produced by `scripts/clean_entities.py` from the
  mined draft: **171 roles, 34 offices, 73 systems, 54 forms**. Headings, bare
  category words and near-duplicates removed; SIAS and eNGAS added by hand.
  Still worth a human read before the Phase 4 dataset build. Role quality is
  limited by the legacy flattened tables and should improve once the manuals
  are re-extracted with the new table format.
- `scripts/build_glossary_draft.py` (TF-IDF term mining) is **not yet written**;
  `glossary.txt` is seeded by hand and sufficient for the pipeline to run.

---

## Resume commands

```bash
# corpus stats
cd Backend && py -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');django.setup();from api.models import Manual,ManualSection;print(Manual.objects.count(),ManualSection.objects.count())"

# tests  (venv must be active, or call venv/Scripts/python.exe directly)
cd Backend && py -m pytest ml/revision_pipeline/tests -q

# re-mine the entity draft from the master copies
cd Backend && py ml/revision_pipeline/scripts/build_entities_draft.py
```
