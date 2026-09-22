# Phase 2 — whole-manual proposals and concurrence: build spec

*Hand this to Claude Code with `CLAUDE.md`. Stop at every checkpoint.*

---

## 0. Scope and rules

**Goal:** replace the one-section revision with the university's actual process up to agreement: an office drafts a **proposal for a whole manual**, each changed section carries its **own AI check**, the proposal goes to every **concurring office**, and it either comes back for redrafting or reaches full agreement and **locks**.

**Ends at "locked".** Generating the DCR and manual pages, signed scans (P3), and the IMR decision and custodian making it effective (P4) come after. **Until P4, a locked proposal does not change the manual.**

**Rules:**
1. All of `CLAUDE.md` applies — especially database first, report before changing, stop at checkpoints.
2. **Proposals only work with the access switch ON.** With it off, the existing single-section revision flow keeps working exactly as now. With it on, that flow is replaced by proposals. Both states must be tested.
3. **The AI pipeline is untouched.** Each changed section is checked through `assess_texts()` exactly as today. Anything that would change what Layer 2 receives stops for approval.
4. **Assessments are never re-run for display.** Every screen reads stored snapshots.
5. The database was cleared of development revisions, so **no revision data needs migrating.** Report what the old `ManualRevision` flow still depends on before deciding how to retire it.
6. Follow the design principles: reading first, sparse screens, AI explanations that say *what changed, where, and why it matters*.

---

## 1. The flow

```
DRAFT ──submit (Head, re-auth)──► CONCURRENCE ──all concur──► LOCKED
  ▲                                   │
  └──── any office returns ◄──────────┘   (new version; all concurrences reset)

DRAFT or CONCURRENCE ──withdraw (Head, re-auth)──► WITHDRAWN
```

If no other office must concur, submitting goes straight to **LOCKED**.

---

## 2. Drafting

- A proposal belongs to **one manual (document)** and is initiated by **one office**, which must be **concurring** on that manual (the owner counts if it is also listed as concurring). A person holding positions in several offices chooses which office they are acting for.
- **Any position holder** (Encoder or Head) of that office can draft and edit.
- The editor shows the **whole manual**, every section as its own box — collapsed by default; editing one expands it.
- **Each changed section has its own mandatory AI check.** Editing a section clears only **that** section's check.
- **One required overall reason for the change** (the DCR's single reason field), checked by the existing clause 6.3 tiers. An **optional note per section**.
- **Scope for P2: changing existing sections only.** Adding or deleting sections is later work. **[confirm]**
- **Overall verdict = the strictest of the changed sections**, with every section's own result visible.
- A proposal with **no changed sections** cannot be submitted.

### Coordinated changes across sections
Each section is still checked against the manual's **current** text. When a `contradicts_manual` concern points at a section that is **also changed in this proposal**, attach an advisory: *"This may be because section 3.6 is also being changed in this proposal."* An advisory only — **no change to retrieval or the model.**

### One open proposal per section
A section already in an **open** proposal (draft or concurrence) cannot be added to another. The editor shows which office holds it. Sections in different proposals may proceed side by side. **[confirm]**

### Rate limit
The pre-check limit (60/hour per user) may be too tight for whole-manual editing. Report typical usage and propose a limit.

---

## 3. Submitting

- **Only the initiating office's Head** submits, with **re-authentication**. (On the DCR, the Head signs alongside the requester.)
- Submission requires a **valid check on every changed section**, each bound to its content hash — the existing staleness guard, per section.
- On submission the proposal **freezes its participants**:
  - the concurring offices at that moment (effective links, owner included if listed as concurring), **minus the initiator**
  - the approval route (owner, then approving levels above it — continuing above the owner if the owner initiated)
  - `office_name_at_time` for each
- **Later changes to the organisation never alter a submitted proposal.**

---

## 4. Concurrence

- Every participating office sees the whole proposal: the changed sections with their diffs and AI results, the reason, and each office's status.
- **Only an office's Head records its decision**, with **re-authentication**: **Concur**, or **Return with feedback**. An Encoder may prepare the feedback text for the Head to confirm.
- **Feedback is visible to the initiator and every participating office.** It may point at a specific section.
- **Any Return sends the proposal back to DRAFT.** The initiator edits, re-checks changed sections, and resubmits as a **new version**.
- **A new version resets every office's concurrence** — they agreed to specific text that no longer exists.
- When **every** participating office has concurred on the **current** version → **LOCKED**: the content is frozen, and no further edit is possible.

### Where each office sees what needs it
No notification system yet (that is P5). Instead, a derived **"Awaiting your office"** list — proposals currently in concurrence where the user's office has not decided — shown on the staff dashboard and in My Revisions. A count badge only when non-zero.

---

## 5. Withdrawal

The initiating office's Head may withdraw a proposal in DRAFT or CONCURRENCE, with re-authentication and a reason. Withdrawn proposals stay on record.

---

## 6. Data model

Propose exact fields after the report; direction:

| Entity | Holds |
|---|---|
| `Proposal` | manual, initiating office, status (draft, concurrence, locked, withdrawn), current version, created by, timestamps |
| `ProposalVersion` | proposal, number, overall reason, submitted by / at |
| `SectionChange` | version, section, **old text as of the version**, new text, optional note, **its own AI snapshot**, content hash |
| `ProposalParticipant` | proposal, office, `office_name_at_time`, role (concurring / approving), order in the approval route — **frozen at submission** |
| `Concurrence` | version, office, decision (concur / return), feedback, optional section, recorded by (person + position), when |
| `AuditEvent` | every transition: who, which position, which office, when, which version |

Reuse the existing pre-assessment and hashing machinery per `SectionChange` rather than rebuilding it.

---

## 7. Screens

**Staff:**
- **Section / manual view** — *"Propose changes"* as a secondary action, only where the user's office is concurring.
- **Proposal editor** — whole manual, collapsed section boxes, per-section AI check, the overall reason, a clear list of changed sections and their check state, and Submit (Heads only).
- **Proposal detail** — changed sections with diffs and AI results (details collapsed), the reason, participants and their decisions, feedback, and the version history. Head actions: Concur / Return / Withdraw.
- **My Revisions** — becomes **proposals**: *initiated by my offices*, and *awaiting my office*.

**System admin and QMS staff:** read-only view of all proposals and their status.

**Re-authentication** on: submit, concur, return, withdraw. **Not** on drafting, editing a section, running a check, or preparing feedback.

---

## 8. Sub-phases

**2a — report, model, drafting API**
Report on the old revision flow and what depends on it. The models, migration tested on a copy, and the drafting API: create a proposal, edit sections, per-section checks, the overall reason, the coordinated-change advisory, the one-open-proposal-per-section rule. **Checkpoint 2A.**

**2b — submission, concurrence, versions**
Submitting with frozen participants, concurrence, returns creating new versions with reset concurrences, locking, withdrawal, audit events, re-authentication. **Checkpoint 2B.**

**2c — screens**
The editor, the detail view, the awaiting list, My Revisions as proposals, the read-only admin/QMS view, and retiring the old single-section flow when the switch is on. **Checkpoint 2C.**

---

## 9. Definition of done

- With the switch **on**: an office drafts a whole-manual proposal, each changed section carries its own stored AI check, and submission requires every changed section's check to be current.
- Participants and the approval route are frozen at submission and unaffected by later organisation changes.
- Concurring offices concur or return; feedback is visible to everyone involved; a return creates a new version and resets all concurrences; full concurrence locks the proposal.
- The coordinated-change advisory appears where it applies; no change to retrieval or the model.
- With the switch **off**, the existing single-section flow works exactly as before.
- Re-authentication on submit, concur, return and withdraw; every transition in the audit trail.
- `check_setup.py` Ready, fingerprint unchanged; all existing tests pass; new tests cover frozen participants, reset on redraft, per-section staleness, the one-open-proposal rule, owner-initiated routing, and both switch states.
