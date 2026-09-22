# DocuRoute — project direction (v4 rebuild)

*Read this at the start of every session. It is the standing direction for the rebuild; detailed specs come per phase. When a spec and this file disagree, stop and ask.*

---

## What is happening

DocuRoute is moving from a **one-staff-to-one-admin revision tool** to a **multi-office document-control system** that follows the university's official **Document Change Request (F-QMS-001)** process. Treat it as a **new foundation (v4)**, not a patch: the organisation, roles, database and drafting model are rebuilt. The AI pipeline is kept exactly as it is.

**Signatures stay on paper.** The university has not yet adopted PNPKI e-signatures, so the system does not sign anything: it routes, records, notifies, generates the documents to be signed, and stores the signed scans. It must still work unchanged if e-signatures arrive later — keep signing a separate step, not woven into other logic.

Reference documents in the repo:
- `MULTI_OFFICE_WORKFLOW_PLAN.md` — the full design and its open decisions
- `PHASE1_ORGANISATION_SPEC.md` — the current build spec (later phases get their own)
- `PROGRESS.md` — what has been done and decided
- `EVALUATION.md`, `MODEL_EXPLAINED.md` — the AI pipeline and its published figures
- **The official DCR form** — `Backend/media/templates/F-QMS-001-Document-Change-Request-Rev.1-01-05-26.doc` (F-QMS-001, Rev. 1, 01-05-26) — the template the system pre-fills. Note the filename reads `Rev.1`, with a dot. It is a legacy `.doc`; generation in P3 needs it converted to `.docx` first, since the fields cannot be filled in the old binary format. **The IMR's printed name has been removed from section 3.**
- `ORG_STRUCTURE_REFERENCE.md` — the university's offices (no names), for the system admin's data entry. **Reference only — never seed or hardcode it.**
- `Backend/media/MANUAL_BLANK_FORMAT/MANUAL_BLANK.docx` — the blank document template (currently untracked), filled with approved revisions for printing. Its structure:
  - **Header, every page:** Version No. · Manual Title · Document No. · Document Name · Revision No. · Effectivity Date · Page No., with the LNU seal. One template serves every document. **Decided: generated drafts leave these header fields blank** for hand-filling — extraction never labelled them reliably, and the revision number and effectivity date are only known after approval (DCR section 5). Only the page numbering is automatic.
  - **Body:** empty — the document's sections go here.
  - **Footer, every page:** the confidentiality notice and **two unlabelled bordered boxes** at bottom right (presumed approval spaces). **[open]** confirm what they are for and whether generated copies print position titles under them.
  - **Page number** is a `PAGE` field only; real documents show *"1 of 4"*, so generation must add the total-pages field.
- **Before committing either template to the repo**, remove any printed personal names (the DCR's section 3 carries the IMR's name). Generated documents print position titles, never names.

---

## Keep / replace / new

| Keep unchanged | Replace | New |
|---|---|---|
| The four-layer AI pipeline (HMRAP), its weights, thresholds, fusion model | Flat `Department` model | Office hierarchy entered by the superadmin |
| The mandatory AI check before submission | One admin role | Three roles: system admin, QMS staff, users |
| Stored snapshots — never re-run for display | Section-by-section revisions | Whole-manual proposals, checked per section |
| Content hashing and the staleness guard | Admin reviews every revision | Concurrence, IMR decision, custodian, signing |
| Re-authentication tokens (in memory, per request) | Fixed departments in code | Pre-filled DCR and manual pages for printing |
| Evaluation figures: **0.978** verdict, **0.854** issue micro-F1 | | In-app notifications |

---

## Design principles — how the system is actually used

**Reading comes first.** Revisions are rare — they happen when administration or offices change. **Day to day, DocuRoute is for reading, finding and storing manuals.** Every screen should be designed for that:
- **Lead with finding:** search, recently opened, and the manual list come first. Revision counts and queues appear only when something is actually pending.
- **Comfortable reading:** a table of contents within each manual, moving between sections easily, search inside a manual, and each section showing its current revision and effectivity date so readers know it is current.
- **Revision tools stay out of the way:** "Propose a change" is a secondary action on a section, never the centre of the screen.

**The AI explanation earns its words; everything else is sparse.**

*The AI explanation* is the one place where substance matters — it tells the reader *why* a change matters, not just *that* it happened.
- For each concern: **what changed, where, and why it matters to the document** — e.g. *"'shall' became 'may' in section 3.1, so an obligation to issue receipts becomes optional."*
- A few complete sentences, written for competent adults. Not a one-line label, not a lecture.
- No coaching on routine actions, and no repeated disclaimers — the advisory nature of the check is stated once, in Help.

*Everything else* — screens, dashboards, help, empty states, notifications — should feel uncrowded.
- Fewer elements per screen; generous whitespace; one clear primary action.
- Details collapsed by default and revealed on click.
- Labels and messages as short as they can be while still clear; no paragraphs where a line will do.
- Don't show counts, badges or panels that are empty or irrelevant to what the person came to do.

Layer 4 wording changes are templates only — no model change, figures unaffected.

---

## Principles — apply to every phase

1. **Database first.** Design and migrate the schema before building screens. Every phase starts with a report on the current data model and a proposed migration, **tested on a copy** of the database, before anything runs for real. Back up `db.sqlite3` first.
2. **Structure in code, content in data.** No office names, manual codes, hierarchy or people in code. Organisation tables start **empty** — no import from the old departments — and are filled by the system admin through screens.
3. **Nothing in the organisation is ever deleted.** Offices are deactivated or merged; people are deactivated; position assignments are ended with a date. History must always read correctly, including past office names.
4. **Flexible participants, fixed stages.** *Who* takes part is data (which offices concur, who approves, who holds which position). *What happens* — the stages — is code, because it mirrors the official form. Do not build a configurable workflow engine.
5. **Requests freeze their participants when submitted.** A reorganisation mid-request must never change who has to agree to it.
6. **Manuals are owned by an approving-level office in name; offices do the work.** The owner (e.g. the VP) signs on paper and neither proposes nor concurs. Other offices relate to a manual as **concurring** (can propose; must concur on others' proposals) or **reader** (read only, never blocks). An office can relate to many manuals. The approval route is the owner plus any approving levels above it (e.g. VP → President).
7. **People and positions are separate.** People sign up with their names and are approved; the process refers only to positions. Generated forms print **position titles, never names** — signatories write their own names on paper.
8. **Report before changing.** Survey what exists before modifying any screen or endpoint, and extend rather than replace where possible. Check what the UI actually calls before securing an endpoint.
9. **Stop at every checkpoint.** Do not start the next sub-phase without approval.

---

## Roles

Three system roles decide **which portal** a person uses. Positions decide **what they can do** within the process.

| System role | Who | Portal |
|---|---|---|
| **System admin** | Configures the system | Organisation: offices, hierarchy, manuals and their offices, people, positions, sign-up approval |
| **QMS staff** | Holds a QMS position | IMR (accepts or denies requests) and/or Document Custodian (records document status, makes changes effective) |
| **User** | Office staff | Drafts and tracks proposals for their offices |

| Position | Form field | Held by |
|---|---|---|
| **[Office] — Encoder** | *Requested by* | Office staff who draft (typically the secretary) |
| **[Office] — Head** | *Department/Unit Head* | The unit head; confirms the office's actions |
| **IMR** | Section 3 | QMS staff |
| **Document Custodian** | To/For, section 5 | QMS staff |

One person may hold several positions (the university has **concurrent heads** — one person heading two offices). Assignments carry start and end dates, and can be marked **acting / OIC**, since several offices are led by an officer-in-charge. **Exactly one current Head per office**; several Encoders allowed.

**QMS office:** the two QMS offices shown on the 2022 chart (administrative services / ISO, and academic services / accreditation) are reported to have **recently merged into a single QMS office** — to be confirmed with the QMS office, including its official name and parent. Design for **one** home for the IMR and Document Custodian positions; do not build per-series resolution. The model must not prevent it if the offices ever split again.

The system admin should not also be able to decide or file requests unless deliberately given a QMS position — configuring the system and controlling documents are separate responsibilities.

---

## Re-authentication

Require the password again (the existing short-lived re-auth token, held in memory and never stored) before any action that **commits an office, decides a request, changes a controlled document, or changes who must agree**:

| Area | Actions |
|---|---|
| **Proposals** | Submitting a proposal for concurrence; a Head recording the office's concurrence or return; withdrawing a proposal |
| **QMS** | IMR accept or deny; custodian making a change effective |
| **Manuals** | Any direct edit to manual content (outside a proposal); deleting a manual or section |
| **Organisation** | Merging, moving or deactivating an office; changing a manual's owner or its office relationships (concurring / reader); assigning or ending Head, IMR or Custodian positions |

**Not** on drafting, editing a section box, running the AI check, commenting, or viewing — prompts on routine actions teach people to type the password without reading.

---

## The process (fixed stages)

1. **Draft** — a proposal covers **one whole manual**. Each section is its own box with its **own mandatory AI check**; only changed sections carry changes and checks. Editing a section clears only that section's check. One required overall reason, optional per-section notes.
2. **Concurrence** — the concurring offices (minus the initiator) are **notified** when a proposal is submitted; the owner and readers are not asked. Skipped if no other office must concur. Each office concurs or returns with feedback on the whole proposal; feedback is visible to all offices involved. Any return → new version, all concurrences reset.
3. **Locked** — content frozen; no further amendment. The system generates the pre-filled DCR, the revised manual pages, and the concurrence record, and **notifies the requesting office and the signatory offices** (the manual's owner and the approving levels above it, e.g. VP → President) so they know documents are coming physically.
4. **Signing** — on paper, by requester and Head; scans uploaded.
5. **IMR** — accept or deny.
6. **Approving authority** — signs on paper; scan uploaded.
7. **Custodian** — receives the complete package (locked content, AI snapshots, concurrence record, signed scans) alongside the physical originals. Either **Accepts** — records document status (number, version, revision, effectivity date) and the change becomes effective — or **Returns for package defects only** (missing signature, unreadable scan), back to the uploading step. Content cannot be changed here; it was locked at stage 3.

Exact behaviour of each stage is decided in its phase spec.

---

## Terminology — manual vs document

What DocuRoute currently calls a **"manual"** is really a **document** (e.g. *FAM 6.02 — Monitoring of Accounts Receivables*) within a **manual series** (e.g. *Finance and Administration Manual*). The header block and the DCR both work at document level. **Decided and built (1b-i, 1b-ii):** `ManualSeries` holds the owner and the default concurring/reader offices, inherited by its documents with per-document overrides. An override **replaces** the series' set rather than adding to it, and the screen names the documents a series-level change will not reach.

Structured header metadata (version, revision number, effectivity date as real fields) is **not required** for now. Once the custodian records DCR section 5 in P4, those values exist going forward and could fill headers later.

---

## Database direction

The target entities, at a high level — detailed fields come in each phase spec:

| Entity | Purpose |
|---|---|
| `Office` | Hierarchy (parent), approving-level flag, active, merged-into; name history |
| `Position` | A role within an office: encoder, head, imr, document_custodian |
| `PositionAssignment` | Person ↔ position, with start and end dates |
| `User` | Named person, approved by the system admin; system role |
| `Manual` | Owning office — exactly one, and it must be an approving-level office; defines the approval route |
| `ManualOffice` | Manual ↔ office with a relationship: **concurring** or **reader** |
| `Proposal` | One manual; status; frozen participant list |
| `ProposalVersion` | One draft of the whole proposal |
| `SectionChange` | One changed section within a version: old text, new text, its own AI snapshot and content hash |
| `Concurrence` | An office's concur/return on a version, with feedback and who confirmed |
| `Attachment` | Signed scans and generated documents |
| `QmsDecision` | IMR accept/deny; custodian's document-status record |
| `Notification` | Per-user inbox entries |
| `AuditEvent` | Every stage transition: who, which position, which office, when, which version |

Existing single-section revisions migrate into one-section proposals. Existing manuals and sections stay; until linked to an office they appear as **unassigned**.

---

## The AI pipeline — do not disturb

- Layers 1–4, the dataset, thresholds and fusion model are **not modified** in this rebuild.
- The AI check is called per section, exactly as today, through `assess_texts()`.
- **Anything that would change what Layer 2 receives must stop for approval** — it invalidates the published figures.
- New findings become **advisories**, never new issue labels.
- After any change touching submissions, confirm `check_setup.py` reports Ready and the fingerprint is unchanged; re-run `evaluate_folds.py` if the rule layer is touched.
- **Known interim gap:** sections changed consistently in one proposal are each checked against the *current* manual, so `contradicts_manual` can fire on correct work. Handle it with an advisory naming the other changed section — not by changing retrieval — until a later, re-evaluated fix.

---

## Personal data

Names are personal data under the Data Privacy Act (RA 10173), which the university's own manuals cite. Collect only name, office, position and credentials; show a purpose statement at sign-up; limit the full people list to the system admin; deactivate rather than delete.

---

## Phases

| Phase | Scope |
|---|---|
| **P1** | Dynamic organisation, the three system roles, people and positions, manual links, re-auth on organisation changes and direct manual edits. **No workflow change** — the existing review screen moves from "admin" to QMS staff. |
| **P2** | Whole-manual proposals, per-section checks, versions, concurrence, re-auth on proposal actions |
| **P3** | Locking, generated DCR and manual pages, scan uploads |
| **P4** | IMR decisions, custodian and effective changes |
| **P5** | Notifications, reminders, escalation |

Tag a release before each phase. Keep `PROGRESS.md` updated after every checkpoint with decisions made and deviations from this file.
