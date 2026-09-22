# Phase 1 — dynamic organisation: build spec

*Hand this to Claude Code together with `MULTI_OFFICE_WORKFLOW_PLAN.md`. Stop at every checkpoint.*

---

## 0. Scope and rules

**Goal:** replace the flat, fixed `Department` model with an organisation the superadmin builds and maintains through screens — offices, higher offices, manuals, people and positions — starting from empty tables.

**This phase changes structure and access, not the workflow.** Revisions are still proposed, AI-checked and reviewed exactly as today. Requests, concurrence, signing and the IMR/custodian stages are later phases.

**Rules:**

1. **Report before changing.** Before writing any migration, report the current data model: what `Department` is, what references it, how staff access to manuals is scoped today, and every place in the code that reads it.
2. **Never migrate the real database first.** Test every migration on a copy, report before/after counts, and wait for approval before touching the real one.
3. **Back up** `db.sqlite3` before any migration that runs for real.
4. **Nothing is deleted from the organisation.** Offices are deactivated or merged, never removed. People are deactivated, never removed. History must always read correctly.
5. **No university structure in code.** No office names, manual codes or hierarchy anywhere except data the superadmin enters (and tests' own fixtures).
6. **The model and pipeline are untouched.** Confirm `check_setup.py` still reports Ready and the fingerprint is unchanged, and re-run `evaluate_folds.py` only if something unexpectedly touches submissions.
7. **Tag a release before starting**, so the current state is recoverable.

---

## 1. Data model

Names below are suggestions; adapt to the codebase's conventions and explain any change.

### `Office`
| Field | Notes |
|---|---|
| `name` | Full name, e.g. "Accounting Services Office" |
| `abbreviation` | e.g. "ASO"; optional |
| `parent` | Nullable FK to `Office` — builds the hierarchy |
| `is_approving_level` | Marks higher offices (VP, President, COO, CAO) |
| `is_active` | Deactivate instead of delete |
| `merged_into` | Nullable FK to `Office`; set when merged |
| `created_at`, `updated_at` | |

Guard against cycles (an office cannot become its own ancestor).

### Name history
Renames must not rewrite the past. Either record `OfficeNameHistory` (office, name, valid_from, valid_to), or store the office name at the time on each record that needs it. **Report which is simpler here before choosing.**

### `Position`
| Field | Notes |
|---|---|
| `office` | FK to `Office` |
| `kind` | `encoder`, `head`, `imr`, `document_custodian` |
| `is_active` | |

IMR and Document Custodian are positions like any other, attached to whichever office the superadmin chooses (normally the QMS office) — no hardcoded QMS office.

### `PositionAssignment`
| Field | Notes |
|---|---|
| `user` | FK to the user |
| `position` | FK to `Position` |
| `starts_on`, `ends_on` | `ends_on` null while current |
| `assigned_by` | The superadmin who made it |

This is what answers *"who held this position on a given date"*. **Decided:** exactly one current Head per office; several Encoders allowed.

### Manual links — owner, concurring, reader

Manuals are **officially owned by an approving-level office** (e.g. the VP), but that ownership is **approval authority, not drafting**: the owner signs on paper and does not take part in proposing or concurring. The offices that actually work with a manual propose and agree to changes. An office may relate to many manuals, and a manual to many offices.

| Relationship | Who | Can read | Can propose | Must concur | Signs |
|---|---|---|---|---|---|
| **Owner** — exactly one per manual | An **approving-level** office (VP, President, COO…) | yes | no | no | **yes, on paper** |
| **Concurring** | Offices that work with the manual | yes | yes | yes, unless it initiated | no |
| **Reader** | Offices that only use it | yes | no | no | no |

| Change | Notes |
|---|---|
| `Manual.owning_office` | Nullable FK to `Office` — null means *unassigned*. **Must be an approving-level office.** |
| `ManualOffice` | Manual ↔ Office with `relationship` = `concurring` or `reader`. Unique per (manual, office). The owner is not duplicated here. |

**Rules (enforced now, used by later phases):**
- The owner must be an approving-level office; the system refuses an ordinary office.
- A manual needs **at least one concurring office** before proposals can be made against it; otherwise it shows as *"no office can propose changes yet"*.
- The **concurrence list** for a proposal = all concurring offices **minus the initiating office**. If that is empty, concurrence is skipped.
- The **approval route** = the owner, then any approving-level offices above it in the hierarchy (e.g. VP → President, matching the blank manual's two approval spaces). **[decide]** — confirm that the route always continues upward, or stops at the owner for some manuals.
- Readers never block a proposal.

### Users and the three system roles
- Add the fields the sign-up needs (full name, if not already present).
- A **system role** on each user, one of three:

| System role | Portal | Notes |
|---|---|---|
| **System admin** | Organisation screens (§3) | Configures the system. Does **not** decide or file requests unless also given a QMS position. |
| **QMS staff** | The QMS area | Holds an IMR and/or Document Custodian position. |
| **User** | The staff portal | Holds office positions (Encoder / Head). |

- **Roles decide the portal; positions decide what someone can do within it.** A user is only QMS staff in practice while holding a current QMS position.
- Report how admin rights are expressed today (`is_staff`, `is_superuser`, a custom flag) and **propose how existing admin accounts map** to the new roles before migrating.

---

## 2. Migration off `Department`

**Report first:** every model, view, serializer, query and frontend screen that uses `Department`, and how staff are currently limited to their department's manuals.

**Then propose, don't run:**
- **Decided: start genuinely empty.** No automatic or one-click import of the current departments. The system admin enters every office, higher office, manual link and position by hand.
- Existing manuals get `owning_office = null` and appear in an **Unassigned manuals** list.
- Existing users keep their accounts and appear in an **Awaiting position** list until assigned.
- **Staff access switches** from "my department" to "offices where I currently hold a position". A user with no current position sees an explanatory message, not an empty screen.
- `Department` is retired only once nothing reads it. Keep it until the switchover is verified.

**Checkpoint A** — report the current model and the proposed migration, run it on a copy, show before/after counts. Nothing runs for real without approval.

---

## 3. Superadmin screens

A new nav group — **Organisation** — visible to the superadmin only.

### 3.1 Offices
- **Tree view** of the hierarchy, expandable, with approving levels marked.
- **Create / edit:** name, abbreviation, parent, approving-level flag.
- **Move** an office under a different parent (cycle-safe).
- **Deactivate** — with a warning listing its manuals, positions and open items.
- **Merge into…** — choose the surviving office; preview what moves (manuals, positions, concurrence links), then confirm. The merged office stays, inactive, with `merged_into` set.
- Inactive and merged offices are hidden by default, shown with a toggle.

### 3.2 Manuals
- List with owning office, counts of concurring and reader offices, and a filter for **Unassigned**.
- **Assign / change** the owner (approving-level offices only), and add offices as **concurring** or **reader**, with the difference explained on screen.
- **From the office side too:** each office's page lists every manual it owns, concurs on, or reads — so an office with access to many manuals can be reviewed in one place.
- Show the **derived approval route** for a manual (the owner, then approving levels above it), so the superadmin can see the effect of the hierarchy immediately.
- Flag manuals with **no concurring office**, since nobody can propose changes to them yet.

### 3.3 People and positions
- **Pending sign-ups** — approve or decline (extends the existing user approval).
- **People** — name, current positions, active/inactive.
- **Assign to a position** — office + kind, with a start date; ending an assignment sets its end date.
- **Awaiting position** list for approved people with none.
- **Positions by office** view — who holds each position now, and the history of past holders.
- **Deactivate** a person — ends their current assignments; never deletes.

### 3.4 Re-authentication
Password confirmation (the existing re-auth token — in memory, never stored) on:
- **Organisation:** merging, deactivating or moving an office; changing a manual's owner or its office relationships (concurring / reader); assigning or ending Head, IMR or Custodian positions; deactivating a person.
- **Manual content:** **any direct edit to a manual's content outside a proposal** — today this asks only for a reason; add the password as well — plus deleting a manual or section (already guarded; keep it).

Not on creating offices, viewing, drafting, or running the AI check.

---

## 4. Sign-up and personal data

- Sign-up asks for **full name**, the office they belong to (a requested office — the superadmin confirms), and credentials. Nothing else.
- A short **purpose statement** on the sign-up page: why the name is collected, who can see it.
- The full people list is **superadmin-only**. Other users see names only where the process needs them.
- People who leave are deactivated; their history stays. **[decide]** retention period — record as an open question, do not implement deletion.

---

## 5. Transitional arrangement — who reviews during Phase 1

The workflow does not change in this phase, so revisions are still reviewed on the existing review screen. That screen moves from "admin" to **QMS staff** (anyone holding a current IMR or Document Custodian position). The system admin loses review rights unless given a QMS position. Report which screens each existing admin account can reach before and after, so nobody is locked out of work in progress.

## 6. Staff side after this phase

- **My Manuals** and **Sections** show every manual linked to any office where the user **currently holds a position** — concurring, reader, or owner — so a person whose office relates to several manuals sees all of them. Show the relationship beside each manual (e.g. *Concurring*, *Read only*, *Owner — approves*).
- Proposing a revision is offered only on manuals where the office is **concurring**; reader access is view-only. Users in an owning (approving-level) office see the manual read-only.
- The dashboard's "at a glance" counts follow the same rule.
- A user with no current position sees: *"Your account is approved but not yet assigned to an office. The system administrator will assign you."*
- Everything else — the AI check, submitting, My Revisions — works exactly as before.

---

## 7. Phases within Phase 1

**1a — Report and model** — the report from §2, the new models, migrations tested on a copy. **Checkpoint A.**

**1b — Superadmin screens** — offices (tree, create, move, deactivate, merge), manuals (assign owner, concurring and reader offices, derived route), people and positions (approve, assign, end, history). **Checkpoint B.**

**1c — Switchover** — staff access scoped by current positions, the no-position message, retirement of `Department` once nothing reads it. **Checkpoint C.**

---

## 8. Definition of done

- Organisation tables start empty, with no import from the old departments; every office, higher office, manual link and position assignment is entered through screens.
- Offices can be renamed, moved, merged and deactivated; nothing is deleted; history shows past names correctly.
- Manuals show their owner (an approving-level office), concurring and reader offices, and derived approval route; manuals with no concurring office are flagged; unassigned manuals are listed; each office's page lists all its manuals by relationship.
- Staff see every manual linked to their offices, and can propose only where their office is concurring.
- People sign up with their name, are approved by the superadmin, and are assigned to dated positions; past holders of a position are visible.
- Staff see exactly the manuals of offices where they hold a current position.
- No university structure appears in code.
- The three system roles exist and route to the right portal; existing admin accounts are mapped across with nobody locked out.
- The existing review screen is available to QMS staff, not to the system admin by default.
- Destructive or route-changing actions, and direct edits to manual content, require re-authentication.
- The existing revision flow, AI check and review work unchanged; `check_setup.py` Ready, fingerprint unchanged; all existing tests pass, with new tests for the hierarchy (including cycle prevention), merging, dated assignments, manual scoping, and the migration.
