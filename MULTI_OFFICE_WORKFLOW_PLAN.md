# Multi-office revision workflow — planning document (v3)

*Background design document. Where it differs from `CLAUDE.md` or a phase spec, **those win** — they record later decisions (nominal VP ownership, owner/concurring/reader relationships, starting empty, one Head per office, reading-first design).*

*Planning only. Nothing here is to be built yet. Items marked **[decide]** need an answer, ideally confirmed with the QMS office, before building starts.*
*Built around the university's official form, **F-QMS-001 Document Change Request (Rev. 1, 01-05-26)**. v3 makes the organisation fully data-driven: the structure is code, the content is entered by the superadmin.*

---

## 0. What the official form tells us

The Document Change Request (DCR) is the paper process the system must support. Its structure:

| Form part | Contents | Who |
|---|---|---|
| **Header** | Date · **DCR No.** · To/For: **Document Custodian** · From | Requesting office |
| **Type** | Amend document · **New document** · **Delete document** | Requesting office |
| **1. Details of document** | Document number · title · revision status · *"Please attach draft copy of the document"* | Requesting office |
| **2. Change(s) requested / Reason for the change** | Free text · signed by **Requested by** and **Department/Unit Head** | Requesting office |
| **3. Integrated Management Representative's comments** | **Request Accepted / Request Denied** · signature and date | IMR |
| **4. Approving authority** | Signature over printed name, date | VP / President |
| **5. Document status** | New document no. · version · revision · **effectivity date** · date updated in the IDS · updated by | Document Custodian |

### Six consequences

1. **The IMR can deny.** v1 said the QMS should only return defective packages, never reject content. The form says otherwise: section 3 is an explicit Accept/Deny decision, and it comes **before** the approving authority signs. The workflow is corrected accordingly (§2).

2. **The two-person office model is confirmed by the form.** Section 2 is signed by **"Requested by"** (the person who drafts — typically the secretary) **and** the **"Department/Unit Head"**. That is exactly the two-position split used here: an **Encoder** and a **Head** position per office, each held by named, approved people (§3).

3. **One DCR covers a document, not a section.** Section 1 identifies a *document* (e.g. FAM 6.02). A single request may therefore change several sections of the same document. That makes **multi-section proposals** (roadmap A1) a requirement of the official process, not a nice-to-have — and brings its retrieval problem with it (§6).

4. **The form covers new and deleted documents too.** The system currently handles amendments only. **[decide]** — keep the system amendment-only for now and note new/delete as later scope, or plan for all three.

5. **Section 5 is the clause 7.5.2 metadata.** New document number, version, revision, and effectivity date are recorded by the Document Custodian *after* approval. This is exactly the loop the AI never assesses and nothing currently updates. The system should set these when the change becomes effective — which also gives the calendar real dates for the first time.

6. **There is no concurrence section on the form.** Nothing on the DCR records other offices agreeing. So multi-office concurrence is either informal practice or something the system introduces. **[decide — the single most important question for the QMS office]** If it is real practice, the system's concurrence record should be printed and attached to the DCR as an annex, so the paper trail reflects it.

**Terminology from here on uses the form's roles:** *Requested by*, *Department/Unit Head*, *Document Custodian*, *IMR*, *Approving Authority*.

**People and positions are kept separate.** People sign up with their names and are approved by the superadmin; the *process* refers only to positions (an office's Encoder or Head, the IMR, the Document Custodian). Generated forms print position titles, never names. See §3.

---

## 1. The workflow in one paragraph

A requesting office drafts a change to a document, runs the mandatory AI check, and — if other offices use that document — circulates it for their concurrence. Once everyone concurs, the content **locks**, and the system produces the pre-filled DCR plus the revised draft pages. Those are signed on paper by the requester and their head, then decided by the IMR (accept or deny), then signed by the approving authority. The signed scans come back into the system, and on completion the Document Custodian's section 5 details are recorded and the change becomes effective. Signatures stay on paper until PNPKI e-signatures exist.

---

## 2. The workflow, stage by stage

```
 1. DRAFT ───────────► 2. CONCURRENCE ──────► 3. LOCKED — PRINT FOR SIGNING
  requester + head      concurring offices      system generates:
  AI check (every        Concur / Return        • pre-filled DCR (F-QMS-001)
  version)                  │                   • revised draft pages
       ▲                    │ any return        • concurrence record (annex)
       └────────────────────┘ new version,             │
                              concurrences reset       ▼
                                                4. REQUESTER & HEAD SIGN (paper)
                                                       │ scans uploaded
                                                       ▼
                                                5. IMR DECISION
                                                  Accept / Deny ── deny ──► CLOSED
                                                       │                    (with reason)
                                                       ▼
                                                6. APPROVING AUTHORITY SIGNS (paper)
                                                       │ signed scan uploaded
                                                       ▼
                                                7. DOCUMENT CUSTODIAN
                                                  records section 5
                                                  → EFFECTIVE
```

### 1. Draft — a whole-manual proposal, checked section by section
A proposal covers **one whole manual** — matching the DCR, which names a document, not a section. Inside it:

- **Every section is its own box**, with its own text and its **own mandatory AI check**.
- **Only changed sections** carry a change and a check result; unchanged sections are shown as unchanged.
- **Editing one section clears only that section's check**, not the whole manual's.
- **Submitting requires a valid check on every changed section**, each bound to its own content hash.
- **The overall verdict is the strictest of the changed sections**, but every section's own result stays visible, so a reviewer sees *which* section is the problem.
- One **required overall reason for the change** (the DCR's single reason field), plus an **optional note per section**. The clause 6.3 check applies to the overall reason. **[decide]**

Recipients — concurring offices, the IMR, the custodian — receive **one proposal**, with the changed sections highlighted, each carrying its own AI result: separate, but in one container.

**Every redraft is a new version** of the whole proposal, with a fresh check on any section changed in that redraft.

**[decide]** — can a proposal add a new section or delete one, or only change existing sections?

**Coordinated changes across sections.** Each section is currently checked against the manual's **current** text. If §3.6 and §4.5 are changed consistently in the same proposal, `contradicts_manual` can fire on both, flagging correct work.
- **Now (no model impact):** when a contradiction points at a section that is *also changed in this proposal*, show an advisory — *"This may be because section 3.6 is also being changed in this proposal."*
- **Later (proper fix):** check each section against the manual *as it will be after the other changes in the proposal*. This changes what Layer 2 receives, so it must be re-evaluated before the published figures can be claimed for it.

**Practical knock-ons:** the pre-check rate limit (60/hour per user) may need raising for whole-manual editing; existing single-section revisions become one-section proposals in the migration.

### 2. Concurrence *(only if the document concerns other offices)*
Each concurring office sees the whole proposal — the changed sections, each with its diff and AI result, and the reason — and either **Concurs** or **Returns with feedback**. Concurrence is on the **whole proposal** (the DCR is per document); feedback may point at a specific section. **[decide]**
- **Feedback is visible to every office in the request.** Offices often object for the same reason; seeing each other's feedback avoids repeated rounds and contradictory demands.
- **Any Return sends it back to Draft**, where the requester amends and re-runs the AI check.
- **All concurrences reset on a new version** — an office concurred with particular text, and that text no longer exists.

### 3. Locked — print for signing
When every concurring office has concurred, the content **locks**: its hash is frozen and no further amendment is possible. The system generates:
1. **The DCR (F-QMS-001), pre-filled:** date, a system-assigned DCR number, From, the type box, section 1 (document number, title, revision status) and section 2 (changes and reason). Sections 3–5 left blank for their signatories.
2. **The revised draft pages** — the blank manual format filled with the revision (the form's *"attach draft copy"*), with the approval spaces left for signing.
3. **The concurrence record** as an annex, if stage 2 happened.

The CAO, VP and President offices are **notified**, so they know a document is coming physically.

### 4. Requester and head sign
Offline. The signed scans are uploaded.

### 5. IMR decision
The IMR records **Accept** or **Deny**, with comments — mirroring section 3 of the form.
- **Deny closes the request**, with the reason visible to every office involved. Because the content was locked at stage 3, a denied change needs a *new* request, not an edit. **[decide]** — or should Deny return it to Draft? Returning is friendlier, but blurs whether the IMR's decision was final.
- **[decide]** Does the IMR act inside the system, or only on paper, with the scan uploaded afterwards? In-system is better: it records the decision properly and notifies the requester at once.

### 6. Approving authority signs
Offline. The signed scan is uploaded.

### 7. Document Custodian — effective
The custodian records section 5: new document number, version, revision, effectivity date, date updated, updated by. The system then:
- replaces the section text with the locked content
- stores the revision and effectivity metadata properly, as data
- files the complete package: locked content, AI snapshot, concurrence record, all signed scans, IMR decision

The physical originals go to the QMS office in parallel.

**Side exits:** *withdrawn* by the requesting office before stage 5; *lapsed* if concurrence stalls (see §6).

---

## 3. Accounts and roles

### People sign up; the superadmin assigns them to positions

Two separate things:

- **A person** — a named individual account. They sign up with their real name and request access; the **superadmin reviews and approves** them. (This extends the sign-up and approval flow the system already has.)
- **A position** — a role within an office that the *process* refers to. The superadmin assigns approved people to positions:

| Position | Matches form field | Can do |
|---|---|---|
| **[Office] — Encoder** | *Requested by* | Draft, run the AI check, prepare responses, upload scans |
| **[Office] — Head** | *Department/Unit Head* | Everything the encoder can, plus submit for the office and record the office's concurrence or return |

A person may hold positions in more than one office, and a position may be held by more than one person where the office needs it (e.g. two encoders). **[decide]** whether each office should have exactly one Head.

**When staff change**, the superadmin ends the old assignment and adds the new one. **No password is ever handed over** — nobody logs in with someone else's credentials.

**Why this is the most accountable option.** The log records both the person and the position:
*"Concurred by Accounting Services Office — Head (confirmed by [name])"*. Assignments are recorded with start and end dates, so *who held this position on a given date* answers itself. The DCR's signatures on paper remain the formal signature; the system's record corroborates it.

### Personal data

Names are personal data, and the university's own manuals cite the Data Privacy Act (RA 10173). So:
- collect only what the process needs: name, office, position, login credentials
- show a short purpose statement on the sign-up page (why the name is collected, who can see it)
- limit the full user list to the superadmin; other users see names only where the process needs them (e.g. who confirmed a concurrence)
- deactivate rather than delete people who leave, so the historical record stays intact, and decide a retention period **[decide]**

### System-wide positions

| Position | Matches form | Purpose |
|---|---|---|
| **Superadmin (system administrator)** | — | Approves sign-ups; adds offices and arranges the hierarchy; assigns people to positions and ends assignments; adds manuals and sets their owning and concurring offices; assigns the QMS positions below |
| **Document Custodian** | *To/For*, section 5 | Receives requests, records section 5, makes changes effective |
| **Integrated Management Representative (IMR)** | Section 3 | Accepts or denies requests |
| **Approving authority offices** *(optional)* | Section 4 | Read-only visibility of what is coming for signature — or notification only **[decide]** |
| **Office positions** | Section 2 | Encoder and Head, as above |

The IMR and Document Custodian are both QMS-side but separate positions — one decides, the other files and records. **[decide]** whether one person holds both in practice; one person can be assigned both positions without merging them.

---

## 4. A dynamic organisation — structure in code, content entered by the superadmin

### The principle

The system ships with **empty** organisation tables. The superadmin enters offices, higher offices, manuals and position assignments through screens. Nothing about the university's structure is written in code, so a reorganisation, a merged office or a new VP is **data entry, not a code change**.

### What the superadmin enters

| Screen | Enters |
|---|---|
| **Offices** | Name, abbreviation, parent office (optional). One table for every level. |
| **Higher offices** | Offices marked as an **approving level** — e.g. VP, President, Chief Operating Officer, CAO. Same table, with a flag. |
| **Manuals** | Code, title, owning office, and the offices that must concur. Optionally an approving-authority override. |
| **People and positions** | Approves sign-ups; assigns people to positions (Encoder, Head, IMR, Document Custodian) with start and end dates. |

### What the process derives from that data

- **Who concurs** — the manual's concurring offices. No concurring offices means the concurrence stage is skipped.
- **Who signs** — walk up the hierarchy from the requesting office to its approving levels, unless the manual sets an override.
- **Who can draft or confirm** — whoever currently holds that office's Encoder or Head position.
- **Who decides and files** — whoever holds the IMR and Document Custodian positions.

### Handling change — the reason for all this

| Change | How it is handled |
|---|---|
| **Office renamed or moved** | Edit it. Past requests still show the name it had at the time. |
| **Two offices merged** | Mark one as *merged into* the other. Its manuals and positions move across; the old office stays, inactive, so history still reads correctly. |
| **Office abolished** | Deactivate it. **Never delete** — past requests point to it. |
| **New VP, new approving level, restructure** | Change the parent. New requests follow the new route. |
| **Staff change** | End the old position assignment, start a new one. No passwords handed over. |

**Requests in progress are not affected by later changes.** When a request is submitted it **freezes** its list of concurring offices and signatories. A reorganisation mid-request must not silently change who has to agree.

### What stays fixed in code

**Make *who* flexible, not *what happens*.** The stages — draft, concurrence, signing, IMR, custodian — stay in code, because they mirror the official DCR form. A configurable workflow engine (the superadmin designing arbitrary stages) is a large project in itself and easy to configure into something broken. Configurable participants cover every change the university is likely to make.

A few stage behaviours are **switches**, not code:
- concurrence runs only if a manual has concurring offices
- the approving authority can be overridden per manual
- whether the IMR decides inside the system or on paper

### Existing data

The new organisation tables start empty, but the **existing 20 manuals and their sections stay**. Until the superadmin links them to offices they appear in an **"unassigned"** list. Existing user accounts likewise wait for position assignments. **Decided: start genuinely empty** — no import from the old departments.

---

## 5. Re-authentication

| Action | Why |
|---|---|
| **Head recording concurrence or return** | Without e-signatures, the nearest thing to a signature on the office's position |
| **Submitting for concurrence** | Commits the office |
| **IMR Accept / Deny** | Mirrors a signed section of the form |
| **Custodian making a change effective** | Changes the controlled document |
| **Direct edits to manual content** | Bypasses the whole process; already logged with a reason |
| **Changing offices, hierarchy, ownership or concurring offices** | Silently changes who must agree to future changes |

Not on drafting, commenting, or running the AI check.

---

## 6. Things still to plan

1. **Whole-manual proposals** — now the drafting model (§2, stage 1). The remaining open work is the proper fix for coordinated changes across sections: checking each section against the manual as it will be after the proposal, which needs re-evaluation.
2. **Silent offices.** Deadlines per stage, reminders, and an escalation path. **[decide]**
3. **Notifications.** In-app first (inbox, badges); email later, since it needs mail-server access.
4. **Two requests on the same document at once.** Recommended: block a second open request against the same sections, and show who holds them.
5. **DCR numbering.** The system should assign DCR numbers in the office's existing format. **[decide — ask for the current format]**
6. **Document generation — titles, not names.** The current DCR prints a named person in section 3; the system's version prints the **position title** ("Integrated Management Representative") and leaves the name for the signatory to write. Same for every signature block. Two templates: the DCR (convert the `.doc` to `.docx` and fill the defined fields) and the manual pages (the blank manual format). Long "changes requested" text may not fit the form's box — **[decide]** whether section 2 carries the full text or a summary with *"see attached draft"*.
7. **The audit trail.** Every transition: who, which office, when, which version by content hash.
8. **A research opportunity.** This process produces real revisions with real decisions — concurrences, returns, IMR accepts and denials, each with reasons. Over time, a genuine evaluation set. The selection effect from the mandatory AI check still applies.
9. **Possible later feature: an office changes its concurrence to a return before the lock.** Today an office decides once per version; a second decision is refused (`already_decided`), and a return opens a new version in which every office decides again. Allowing an office that has concurred to return the proposal before the last concurrence locks it would need its own rules - who may, until when, and how the other offices are told their agreement now rests on a version that is being redrafted. Recorded after Checkpoint 4C; not built.
10. **Merging sections returns with adding and deleting sections through proposals.** The admin's section merge was removed at v4.1.0: merging deletes a section, proposals cannot yet add or delete one, and the merge had been refusing every request since access went by position. It comes back as part of a proposal - reviewed, concurred, signed and made effective like any other change - rather than as a direct admin edit.

---

## 7. Suggested phases

| Phase | Contents | Risk |
|---|---|---|
| **P0 — confirm the process** | Process questions only (§8) — the organisation itself is now data entered later | Low |
| **P1 — dynamic organisation** | Empty organisation tables; superadmin screens for offices, higher offices, manuals, people and positions; merge/deactivate; unassigned lists; migration off `Department`. **No workflow changes yet.** Build spec: `PHASE1_ORGANISATION_SPEC.md` | **High** — replaces how access is scoped |
| **P2 — requests and concurrence** | Requests per document (one or more sections), versions, frozen participant lists, concurrence, visible feedback, reset on redraft, re-auth | Medium–high |
| **P3 — documents and signing** | Locking, the pre-filled DCR, draft pages, concurrence annex, scan uploads | Medium |
| **P4 — IMR and custodian** | IMR Accept/Deny, custodian's section 5, making changes effective with proper metadata | Medium |
| **P5 — notifications and polish** | Inbox, reminders, escalation, email | Low |

**Scope note.** This is larger than all the portal work so far, and it redefines "done". If the defence is close, P0 plus P1 working is a coherent and honest story: the designed process, and the dynamic foundation it runs on.

---

## 8. Questions for the QMS office

*The organisation itself (offices, manuals, who belongs where) no longer needs answering before building — it becomes data the superadmin enters. Only process questions remain.*

1. **Is multi-office concurrence actual practice?** The DCR has no section for it. If it happens, how is it recorded today?
2. When the IMR denies a request, is it closed, or returned for revision?
3. Does the IMR want to record decisions in the system, or only on paper?
4. Are the Document Custodian and the IMR the same person in practice?
5. Is the approving authority always found by going up the hierarchy, or does it vary by manual?
6. What is the DCR number format, and who assigns it today?
7. Who sets the effectivity date, and from what?
8. What happens today when an office does not respond?
9. Should the system handle new and deleted documents, or amendments only?
10. What is the "IDS" in section 5 — an existing system, or a register DocuRoute could become?
11. How long should records of people who have left be kept?
12. **May there be more than one IMR, or more than one Document Custodian,
    at the same time?** Each office has exactly one current Head by
    decision; nothing has said whether the two QMS positions are the same.
    Until answered they are unrestricted, which is the permissive choice:
    a wrong restriction blocks real work, a missing one can be added.
