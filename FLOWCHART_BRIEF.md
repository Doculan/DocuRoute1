# Brief for Claude Design: QMS CDMS flowcharts

*Paste this into Claude Design. It describes four diagrams that show how QMS CDMS works and how a revision moves through it. It follows the system as built (`WORKFLOW_AS_BUILT.md`), so show nothing that is not in it.*

---

## What to make

Four diagrams on one canvas or four pages, readable on A4 and on a projected slide:

1. **System overview**: who uses QMS CDMS and for what.
2. **Revision process**: a swimlane chart of one revision, from draft to the manual being updated.
3. **Request statuses**: a compact state diagram of every status.
4. **Deadlines and escalation**: how a missed deadline climbs the ladder.

---

## Style

- Flat, clean and professional. No gradients, shadows or 3D.
- Off-white background, dark navy text and lines, one accent colour for decisions.
- Sentence case. Short labels, at most five words per box.
- **Position titles only, never personal names.**
- Rounded rectangles for steps, diamonds for decisions, a document shape for generated or signed documents, a cylinder for stored records.
- Arrows run one way (top to bottom or left to right). Loops go around the side, never through boxes.
- A small legend on each diagram.
- Use this key on diagrams 2 and 3: a **padlock** means the password is asked again; a **gear** means an automatic system step; a **page** means on paper.

---

## Diagram 1: System overview

**Centre:** *QMS CDMS*, "Read, revise and record controlled manuals".

**Three groups of users:**

| Group | Does |
| --- | --- |
| **Office staff** (Encoder, Head) | Read manuals; propose changes; agree to other offices' changes |
| **QMS staff** (IMR, Document Custodian) | Accept or deny requests; make changes effective |
| **System admin** | Sets up offices, manuals, people, deadlines and the change freeze |

**Also connected to the centre:**
- **AI check (HMRAP)**: "Advises on each changed section"
- **Official documents**: "DCR form, draft copy, concurrence record"
- **Paper signatures**: "Signed offline, scans uploaded"
- **Notifications and banners**: "Bell, action row, announcements"
- **Records** (cylinder): "Manuals, history, decisions, audit trail"

Caption: *Most daily use is reading. Revisions happen when offices or policies change.*

---

## Diagram 2: Revision process (swimlanes)

**Five lanes, top to bottom:**
1. Requesting office, Encoder
2. Requesting office, Head
3. Concurring offices, Heads
4. QMS, IMR
5. QMS, Document Custodian

Add thin side bands labelled **AI check**, **System** and **On paper**.

**Steps, in order:**

| # | Lane | Step | Notes |
| --- | --- | --- | --- |
| 1 | Encoder | Propose changes (padlock) | Whole document opens, each section its own box |
| 2 | Encoder | Edit sections, write one reason | |
| 3 | Encoder to AI band | Check each changed section | "Check required; advice never blocks" |
| 4 | Encoder | **Send to Head** | Needs every changed section checked |
| 5 | Head | Submit or return? **(decision)** | |
| 5a | Head to Encoder | *Return with a note*, back to step 2 | No password. Encoder may also **Recall** |
| 6 | Head | **Submit for concurrence** (padlock) | Participants are frozen here |
| 6b | Head | *Withdraw* (padlock, reason) | Available until the lock; ends in History |
| 7 | Concurring Heads | Review changes and AI notes | |
| 8 | Concurring Heads | Concur or return? **(decision)** (padlock) | Pending offices keep it waiting |
| 8a | Concurring Heads to Encoder | *Return with feedback*: new version, back to step 2, all concurrences reset | |
| 8b | Head | *No other office must concur*: straight to step 9 | |
| 9 | System | **Lock** and number it (DCR-YYYY-NNN) | Gear. Refused if any text changed after a concurrence |
| 10 | System | Generate DCR, draft copy, concurrence record | Document shape |
| 11 | On paper | Requester and Head sign | |
| 12 | Encoder or Head | Upload both signed copies | Replace needs a reason and padlock |
| 13 | IMR | Accept or deny? **(decision)** (padlock) | |
| 13a | IMR | *Deny with a reason*: closed, every office told | End |
| 14 | On paper | IMR signs section 3, then the approving authority signs section 4 (VP, then President) | |
| 15 | IMR | Upload the signed DCR | The requesting office may as a fallback |
| 16 | Custodian | Package complete? **(decision)** | |
| 16a | Custodian to office | *Return naming the defective copies*; office replaces only those (padlock, reason), back to 16 | No password for the return |
| 17 | Custodian | Make effective (padlock) | Records DCR section 5 |
| 18 | System | Manual updated, old text kept in history | Cylinder, end |

**Small grey notes beside steps:**
- Step 3: *Check required; recommendation advisory.*
- Step 9: *Content frozen from here.*
- Steps 11 and 14: *Signatures stay on paper.*
- Steps 6, 8, 13 and 17: *Password required.*
- Whole chart: *A change freeze can pause starting, sending, submitting and making effective. Reading never stops.*

---

## Diagram 3: Request statuses

A compact state diagram. Each status is a rounded box; arrows say what moves it.

```
Draft -> With the Head              (Encoder sends)
With the Head -> Draft              (Head returns, or Encoder recalls)
With the Head -> Out for concurrence (Head submits)
Draft -> Out for concurrence        (a Head who drafted submits directly)
Out for concurrence -> Draft        (an office returns it: new version)
Out for concurrence -> Awaiting signature   (last office concurs; locked)
Draft or With the Head -> Awaiting signature (no other office must concur)
Draft, With the Head or Out for concurrence -> Withdrawn
Awaiting signature -> Ready for the IMR     (both signed copies in)
Ready for the IMR -> Denied by the IMR      (IMR denies)
Ready for the IMR -> Awaiting the approving authority (IMR accepts)
Awaiting the approving authority -> With the Document Custodian (signed DCR uploaded)
With the Document Custodian -> Returned for package defects (custodian returns)
Returned for package defects -> With the Document Custodian (every returned copy replaced)
With the Document Custodian -> Effective    (made effective)
```

**Three closed states**, drawn with a double border: **Effective**, **Denied by the IMR**, **Withdrawn**.

Mark the **automatic** transitions with a gear: *Locked → Awaiting signature*, *Awaiting signature → Ready for the IMR*, *Awaiting the approving authority → With the Document Custodian*, *Returned for package defects → With the Document Custodian*.

Colour each status by who acts next (legend): requesting office, concurring offices, QMS (IMR or Custodian), closed.

---

## Diagram 4: Deadlines and escalation

A short ladder, drawn as five steps on a timeline from the due date.

| Rung | When | Who is told |
| --- | --- | --- |
| Reminder | each reminder day before (default 30, 14, 7, 3, 1) | the office's Head and Encoders |
| Due | the due date | the same |
| Overdue | from the next day | the same, plus the Head of the office above |
| Escalated | 7 days after | the nearest approving office's Head, the IMR and the Custodian |
| Weekly | from 14 days after, once each week | the same as escalation |

Beside the ladder, three small boxes:
- **Met by:** submitting a proposal, or a Head recording "Reviewed, no change".
- **Fallbacks:** no approving office above goes to the President's office; an approving office with no Head goes to the system admin.
- **A change freeze pauses the overdue, escalated and weekly rungs**, which are caught up after it lifts.

The deadline banner is the **pinned top row** on every page for offices that owe it. It cannot be dismissed.

---

## Wording to use exactly

- "Document Change Request (DCR)" on first mention, then "DCR".
- "IMR" is Integrated Management Representative; spell it out once in the legend.
- "Concur" and "Return" for offices; "Accept" and "Deny" for the IMR; "Make effective" for the Custodian.
- Status names exactly as in Diagram 3.
- "AI check", never "AI approval": it advises, it does not decide.
- Never show a verdict. The system does not show one to anyone.
