# The change process, as built

*State at the end of Phase 3 (tag `v4.2.0-p3`, 26 October 2026). Written
from the code, not the plans: where the build differs from `CLAUDE.md` or
the specs, it says so under **Differences from the design**.*

DocuRoute routes, records, notifies, generates the documents to be signed
and stores the signed scans. It does not sign anything and does not verify
signatures: the QMS checks scans against the physical copies.

**Who is who.** The process names positions, never people.

| Position | Held by | Form field |
|---|---|---|
| Encoder (of an office) | office staff who draft; several per office | *Requested by* |
| Head (of an office) | exactly one current Head per office; may be acting/OIC | *Department/Unit Head* |
| IMR | QMS staff | Section 3 |
| Document Custodian | QMS staff | To/For, section 5 |

The system admin configures the system and takes no part in deciding or
filing requests.

**The password** ("re-authentication") is asked again before an action that
commits an office, decides a request, changes a controlled document or
changes who must agree. It buys a short-lived token held in memory, never
stored.

---

## The stages at a glance

| # | Status (as shown) | Who acts | Button | Password | Moves to |
|---|---|---|---|---|---|
| 1 | Draft | Encoder or Head of a concurring office | Propose changes (start) | yes, to start | — |
| | | Encoder | Send to Head | no | With the Head |
| | | Head | Submit for concurrence | yes | Out for concurrence (or Locked) |
| | | Head | Withdraw | yes, with a reason | Withdrawn |
| 1a | With the Head | Head | Submit for concurrence | yes | Out for concurrence (or Locked) |
| | | Head | Return to Encoder | no; a note is required | Draft |
| | | Encoder | Recall | no | Draft |
| 2 | Out for concurrence | Head of each concurring office | Concur | yes | Locked, when the last one concurs |
| | | Head of each concurring office | Return with feedback | yes; feedback required | Draft (new version) |
| | | Head of the requesting office | Withdraw | yes, with a reason | Withdrawn |
| 3 | Locked → Awaiting signature | the system, on the last concurrence | — | — | Awaiting signature |
| 4 | Awaiting signature | Encoder or Head of the requesting office | Upload (each signed copy) | no; **yes to replace** | Ready for the IMR, once both are in |
| 5 | Ready for the IMR | IMR | Accept / Deny | yes; comments required to deny | Awaiting the approving authority / Denied by the IMR |
| 6 | Awaiting the approving authority | IMR, or Encoder or Head of the requesting office | Upload the signed DCR | no; **yes to replace** | With the Document Custodian |
| 7 | With the Document Custodian | Document Custodian | Make effective | yes | Effective |
| | | Document Custodian | Return (names the defective copies) | no; comments required | Returned for package defects |
| 7a | Returned for package defects | whoever may upload the copy returned | Replace | yes, with a reason | With the Document Custodian, once every returned copy is replaced |

Closed: **Effective**, **Denied by the IMR**, **Withdrawn**. Nothing
further happens to a closed request.

---

## 1. Draft

- **Starting.** An Encoder or Head of an office that *concurs* on the
  document starts a proposal for the **whole document**, with the password
  (reopening an open draft does not ask). Refused when:
  - the person holds no position (`no_position`);
  - they hold posts in several offices and named none (`office_required`);
  - their office does not concur on the document (`not_concurring`);
  - the office already has an open proposal on it (`already_open`);
  - a change freeze covers it (`frozen`).

  The owner (an approving office) and readers do not propose.
- **Editing.** Anyone in the requesting office edits. Each changed section
  is its own box with its own mandatory AI check; editing a section
  clears only that section's check. A section held by another office's
  open request cannot be changed (`section_in_another_proposal`). One
  overall reason is required; per-section notes are optional. The AI
  check is rate-limited per person and per proposal.
- **Ready to send** means at least one changed section, a reason that is
  not a throwaway, and every changed section checked on its current text
  (`not_ready`, `reason_rejected`, `stale_checks`).
- **The Encoder sends to the Head** (no password). A Head who drafted it
  submits directly (`head_submits_directly` if they try to send).

## 1a. With the Head

- The text is frozen while it is with the Head, so the Head reads exactly
  what was sent. The Encoder may **Recall** it to draft (no password).
- The Head **submits** (password) or **returns it to the Encoder** with a
  note (no password).
- If the office has **no current Head**, sending still works. The notice
  goes to the Head of the office above and the system admin, who fills
  posts.

## 2. Out for concurrence

- On submission the **participants are frozen**: the concurring offices
  (minus the requester), the owner and the approving levels above it. A
  reorganisation mid-request changes nothing.
- With no other concurring office, the proposal **locks at once**.
- Each concurring office's **Head** concurs or returns on the whole
  proposal, with the password (`not_head`, `not_participating`,
  `already_decided`). A return needs feedback (`feedback_required`), may
  name a section, and is seen by every office involved.
- **Any return** makes a new version back in Draft, carrying the text but
  not the checks. **Every concurrence resets**: an office concurs with
  particular text.
- The Head of the requesting office may **withdraw** (password, reason)
  while it is in Draft, With the Head or Out for concurrence.

## 3. Locked, then Awaiting signature

When the last concurring office concurs, in **one transaction**, the system:

1. numbers the request (`DCR-YYYY-NNN`, counted per year from the numbers
   already issued);
2. locks the content;
3. generates the pre-filled DCR, the revised manual pages and the
   concurrence record.

A generator that fails takes the lock with it, so a proposal is never
frozen with nothing to sign. Generated documents print **position titles,
never names**.

Locked content cannot be amended. Its sections stay **held** until the
request is effective, denied or withdrawn.

## 4. Awaiting signature — the signed copies

| Copy | Who uploads | When | Replace |
|---|---|---|---|
| Signed DCR (requester and Head) | Encoder or Head of the requesting office | Awaiting signature, Ready for the IMR | password and reason; refused once the IMR has decided |
| Signed draft copy (manual pages) | the same | the same | the same |
| DCR signed by the approving authority | **the current IMR** (decided 11 Oct 2026), or Encoder or Head of the requesting office | Awaiting the approving authority | password and reason, only if the custodian returned it |

- A first upload asks no password; it is ordinary work on paper already
  signed. **Replacing** changes the evidence record, so it asks for the
  password and a reason. The old file stays as a superseded row and is
  never overwritten.
- Each upload records who, when, the file name, the type, and the
  **uploader's actual position** (an IMR upload is recorded as the IMR's).
  PDF or image only, within a size limit; empty or corrupt files are
  refused.
- When both signed copies are in, the request becomes **Ready for the
  IMR**.
- The screen says plainly that the system stores and records, and does not
  verify.

## 5. Ready for the IMR

- The **IMR** accepts or denies, with the password. Comments are required
  to deny (`comments_required`).
- An IMR who holds any position in the requesting office is refused
  (`conflict_of_interest`).
- **Accept** → Awaiting the approving authority. **Deny** → Denied (closed).
  The sections are released and every office involved can read the
  reason.

## 6. Awaiting the approving authority

- The approving authority (the owner and the levels above, e.g. VP →
  President) signs on paper.
- The completed signed DCR is uploaded by the **current IMR**, or by the
  requesting office as a fallback. Upload sends the package to the
  custodian. The request stays in the IMR's signed-DCR queue until then.

## 7. With the Document Custodian

- The custodian receives the complete package: locked content, AI
  snapshots, concurrence record and signed scans.
- **Make effective** (password): records the document status (number,
  version, revision, effectivity date, date updated in the IDS). In one
  transaction it writes the locked text into the document, keeps the old
  text in each section's history, and closes the request.
  - Refused if a changed section no longer reads as the offices saw it
    (`section_changed`).
  - Refused for a future effectivity date, or a lower revision.
- **Return** names which signed copies are defective, with comments (no
  password): **Returned for package defects**. Content cannot be changed
  here.
- When every returned copy is replaced, the request is back **With the
  Document Custodian**. The IMR may replace a returned DCR signed by the
  approving authority.
- A custodian who holds a position in the requesting office is refused
  (`conflict_of_interest`).

---

## Who is told

Notices go to **posts**, not people. A notice is **action** (clears when
the thing is done, by anyone entitled to do it) or **info** (clears when
read). The person who acted is not told of their own act.

| Event | Who is told | Severity |
|---|---|---|
| Sent to the Head | the Head (no Head: the office above's Head and the system admin) | action |
| Returned to the Encoder | the Encoders (no Encoder: the Head) | action |
| Recalled | the Head | info |
| Submitted (or resubmitted) | each concurring office | Head action, Encoder info |
| Concurred | the requesting office | info |
| Returned by an office | the requesting office | action |
| Locked | the requesting office | action: print, sign, upload |
| Both signed copies in | the IMR | action |
| IMR accepts | the requesting office | info |
| IMR denies | the requesting office and every participating office | info |
| Signed DCR uploaded | the requesting office; the Document Custodian | info; action |
| Package returned | the requesting office (and the IMR, if the approved DCR is named) | action |
| Returned copies all replaced | the Document Custodian | action |
| Made effective | the requesting office and every participating office | info |
| Withdrawn | the requesting office, and the concurring offices once submitted | info |
| **Stalled** (from `run_monitoring`) | whoever holds the step (Heads action, Encoders info); the requesting office | action; info |
| **Post vacant** (Head, IMR, Custodian) | the Head of the office above, and the system admin | action |

**Stall limits** (days a request may sit before it is flagged; editable by
the system admin): with the Head 3; out for concurrence 7; awaiting signed
copies (or returned) 14; with the IMR, including awaiting the approving
authority, 7; with the Document Custodian 10.

## The banners, top to bottom

1. **The action row**, pinned:
   - **Contents:**
     - deadlines the person's offices owe, most urgent first (overdue,
       due today, due soon);
     - work returned to the office;
     - a change freeze in force, as one more clause on the same line.
   - **Behaviour:**
     - one line, with "Show all" folding out the list, so at most two
       rows;
     - no dismiss: it clears only when the office meets its deadlines
       and sends returned work on;
     - the admin and QMS staff see the freeze clause too.
2. **The announcement row**, beneath it: the newest announcement, with
   "n more", each dismissible per person.

---

## Deadlines and the escalation ladder

The system admin sets a deadline on offices, branches, series, manuals or
all offices, with reminder days (default 30, 14, 7, 3, 1). The unit is
**one office's open obligations on one deadline**: one notice names
everything owed, priority manuals first.

| Rung | When | Who | Severity |
|---|---|---|---|
| reminder | each reminder day before the due date | the office's Head and Encoders | action |
| due | the due date | the same | action |
| overdue | from the day after | the same, and the Head of the office above | action; info above |
| escalated | from 7 days after | the Head of the nearest approving office above, the IMR and the Custodian | info |
| weekly | from 14 days after, once each ISO week | the escalation's recipients | info |

- **Fallbacks:**
  - no approving office above: the root approving offices (the
    President's);
  - an approving office with no Head: the system admin.
- **Each rung is sent once.**
  - A run that missed a day sends what it missed.
  - A reminder whose day fell before the obligation existed is skipped.
- **Clearing.** All the unit's notices clear when the office owes nothing
  more: submitting a proposal meets it, and so does a Head recording
  **"Reviewed, no change"** on the document. That needs the password and
  a Head of a concurring office. It sets the document's last and next
  review dates.
- **Periodic review.** An optional monthly step gathers documents past
  review into a deadline. It is **off by default**.
- **Where it runs.** `run_monitoring` runs the ladder. A dashboard runs one
  capped batch itself if the scheduler has not run for 15 minutes.
  `--dry-run [--as-of]` prints what would be sent and writes nothing.

## Delegation and maker-checker

- **Who names a delegate:** a Head on leave, in their own post, or the
  system admin, with the password.
- **Who may be named:** a current post holder in the office, or the Head
  of the office above. A delegate cannot delegate further.
- **The period:** a start date, an end date and a reason. Periods never
  overlap. Ending early asks for the password, and nothing is deleted.
- **During the period the delegate:**
  - holds the Head post for every Head action (submit, concur, return,
    return to the Encoder, withdraw, Reviewed no change);
  - works for the office;
  - receives the Head's notices instead of the Head.
- **The record:** each step is the delegate's, with `acting_for` set to
  the Head, and is shown as "… — Head (delegated)". Forms still print
  titles only.
- **Maker-checker:** a delegate may not submit, concur on or return a
  proposal they drafted or sent to the Head (`maker_checker`). The Head is
  not bound by it.

## The change freeze

- **Who:** the system admin.
- **What it takes:** a reason, an expected end and a scope: everything,
  selected offices, or selected manual series.
- **Changes to it:** starting, lifting, extending and granting an
  exception (one manual or one proposal) each ask for the password.
  Several freezes may be in force, and any one that covers an action
  blocks it.

| During a freeze | |
|---|---|
| Starting a proposal, Send to Head, Submit, Make effective | refused, `frozen`: "Frozen for audit until … — … waits until the freeze is lifted." |
| The admin's direct writes: edit text, add, delete, merge or split sections, delete a manual | refused, `frozen`; a per-manual exception lets them through |
| `reextract_manuals`, `clean_section_content`, `import_mastercopies --replace` | frozen manuals skipped and named, unless `--ignore-freeze` |
| Editing and checking drafts; concurring and returning; signing, scans, the IMR's decision | allowed |
| Reading anything | never blocked |

- **Scope:**
  - For a proposal: everything, the proposing office, or the document's
    series.
  - For a direct write, which has no proposing office: everything, the
    document's series, or an office that concurs on it.
- **Deadlines:** overdue, escalation and weekly notices pause for what a
  freeze covers, and are caught up on the first run after it lifts.
  Reminders and the due day continue. Tags show "Frozen for audit".
- **Notices:**
  - the covered offices, at start and at lift;
  - the admin, once a freeze passes its expected end (until it is lifted
    or extended);
  - the admin, once per deadline that falls inside a freeze.
- **On screen:** blocked buttons stay visible but disabled, saying why and
  until when.

---

## Differences from the design

- **Locking tells only the requesting office.** `CLAUDE.md` says it also
  tells the signatory offices (the owner and the approving levels above),
  so they know documents are coming. The built notice goes to the
  requesting office alone.
- **Defect: the text can change while out for concurrence.** The
  requesting office can still edit a section after submission.
  `EDITABLE_STATUSES` includes *Out for concurrence*. The edit:
  - is accepted;
  - makes no new version;
  - leaves concurrences already given on the earlier text standing.

  This contradicts "an office concurs with particular text". Confirmed by
  a probe on 26 Oct 2026; not yet fixed.
- **The proposal audit trail is not hash-chained.** Only the system log
  (`SystemEvent`) is chained. Phase 6 adds a per-proposal chain; until
  then, no document calls the proposal trail tamper-evident.
- **The DCR number format** `DCR-YYYY-NNN` is provisional, pending the QMS
  office.
