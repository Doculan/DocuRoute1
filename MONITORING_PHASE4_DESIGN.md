# Monitoring update (v4.2) — the Phase 4 design

*For approval before anything is built. Spec: `MONITORING_UPDATE_SPEC.md`
§7, §9, §11.1. In force: SQLite retained, the §11.1 density rules, the test
policy in `CLAUDE.md`. 26 October 2026, at `v4.2.0-p3`.*

> **Approved 26 October 2026 for steps 2–5 only.** Build in this order,
> with a checkpoint after each:
>
> 2. The scope helper (§1, Encoders their own office only), the read-only
>    endpoints, the Overview counts, and the By office tree with overdue
>    and stalled; the four monitor-only demo accounts (§7).
> 3. The admin offices bar chart: Pending / Approved, top 15, zeros
>    collapsed, a click opens that office's proposals.
> 4. The Advised revisions list.
> 5. A simple QMS dashboard: queue counts, the same chart, and read-only
>    Monitoring of the whole institution.
>
> **Everything else in this document is future work, not approved:**
> critical times, exports (§5), office timeliness columns, the By manual
> and By deadline views, saved views, the summary table (§3; counts are
> read live with `GROUP BY` instead), the Head Home timeline, and Phases
> 5 to 7. Also deferred: the generated draft copy holding the whole
> manual, and the error for scanned PDFs.

Phase 4 is **read-only**. It adds no stage and changes no rule of the
process. It shows who holds what, for how long, and against which
deadline, to the people entitled to see it.

---

## 1. Who sees what: one scope helper

`access.monitoring_scope(user)` returns either `ALL` or a set of office ids.

| Viewer | Scope |
|---|---|
| System admin, QMS staff (IMR, Custodian) | `ALL` |
| A Head, or a delegate while the delegation runs | the office, **and every office beneath it** |
| An Encoder | **their own office only** (Q-3) |
| No post | nothing (an empty Monitoring with one line saying so) |

A person with several posts gets the union: an Encoder of one office who
is Head of another sees the second office's branch and the first office
alone.

- **One pass, not per node.** The office tree is read in one query
  (`id, parent_id, is_active, merged_into`) and walked in memory. It is
  cached per request.
- **Beneath means the hierarchy**, not concurrence. An office never sees a
  sibling, a parent, or a branch beside it, even where it concurs on the
  same manuals.
- **Deactivated and merged offices** stay in scope for history. Their open
  items, if any, roll up under the office they were merged into.
- **One gate.** Every monitoring endpoint filters through the helper; none
  takes an office id at face value.

**Tests**, each failing without its code:
- Accounting sees itself and the units beneath it, never Budget (sibling),
  CAO-Finance (parent) or the CAO-Administration branch.
- CAO-Finance sees Accounting, Budget and Cash, and not HRMO.
- The VPAF sees both CAO branches. The President sees everything under the
  President's office.
- A concurrent Head of two offices sees both subtrees and nothing between
  them.
- A delegate sees the delegated branch only while the delegation runs.
- An Encoder of Accounting sees Accounting only, not the units beneath it.
- An office id outside scope is refused on every endpoint (`out_of_scope`,
  403), and a list never includes such a row.
- Admin and QMS get `ALL`; a user with no post gets nothing.

## 2. One status vocabulary (§7.2)

`monitoring_status(row)` is the single mapping, used by every screen and
export.

| Shown | From |
|---|---|
| Not started | an open deadline obligation with no proposal |
| Drafting | Draft |
| With Head | With the Head |
| In concurrence | Out for concurrence |
| Returned | Draft after a return; the row says by whom (an office, or the Head) |
| Awaiting signatures | Locked, Awaiting signature, Returned for package defects |
| With IMR | Ready for the IMR, Awaiting the approving authority |
| With custodian | With the Document Custodian |
| Effective | Effective |
| Reviewed, no change | an obligation met by "Reviewed, no change" |

- **Overdue** (a deadline overlay) and **Stalled** (the stage limits) are
  overlays, not statuses. **Frozen** shows as the existing chip.
- Every row says **who holds it now**, **for how many days**, and **what
  it waits on**, e.g. "Concurrence: Budget Office, 9 days".
- Days in stage come from the event that entered the stage: the same
  `STAGES` table `run_monitoring` already uses for stalls, so the two
  never disagree.

## 3. Summary counts kept current (§9)

A new table, **`OfficeMonitoringCount`**: one row per office per bucket.

| Field | |
|---|---|
| `office` | FK, indexed |
| `bucket` | `drafting`, `with_head`, `in_concurrence`, `returned`, `awaiting_signatures`, `with_imr`, `with_custodian`, `stalled`, `overdue`, `due_soon`, `not_started`, `advised_open`, `effective_month` |
| `count` | integer |
| `updated_at` | |

Unique on (`office`, `bucket`). About 500 × 13 rows at full scale.

- **Kept current by each transition.** Every stage change already goes
  through `notifications.notify(event)`. It will call
  `summary.refresh_office(initiating_office)` in the same transaction,
  which is a few small `GROUP BY` queries for one office. Deadline changes
  (set, met, deactivated, Reviewed no change) refresh the offices they
  touch.
- **Kept honest by `run_monitoring`.** A new step, `summary`, rebuilds
  every row in batches of 200 offices, records any row it had to correct
  (`summary_drift` in the run's counts), and moves the date buckets
  (overdue, due soon) at midnight.
- **Rolled up at read time.** Branch totals are summed in memory over the
  scope's rows: 500 rows in one query, then one pass up the tree.
- **Never the source of truth.** Lists are always queried live, paged at
  50. The counts only drive tiles, the tree and the chart. A test compares
  the table with a live recount after every kind of transition.

**Migration `0051`:**
- creates the table, and fills it with a one-off data step from the live
  rows;
- adds one index on `Proposal` (`initiating_office`, `status`) for the
  live lists and the rebuild. Adding an index does not rebuild the table.

Backup and a copy first, compared before and after as in 0047–0050; the
full suite after it.

## 4. The endpoints

Read-only, scoped by §1, 50 rows a page, filters on indexed columns.

| Endpoint | Returns |
|---|---|
| `GET monitoring/overview/` | the §7.3.1 counts (on time, due soon, overdue, stalled, returned, waiting, advised revisions), each with the filter it opens; the offices chart data for the viewer's scope |
| `GET monitoring/offices/?parent=` | one level of the tree: the children of `parent` (default: the viewer's top offices) with rolled-up counts, most overdue first; top 15, then `page` |
| `GET monitoring/offices/<id>/items/?status=&overlay=` | that office's proposals and obligations, one row each in the §2 vocabulary |
| `GET monitoring/deadlines/?status=` and `monitoring/deadlines/<id>/` | deadlines in scope; for one, every targeted office in scope: status, who holds it, days late; grouped by branch, only the group needing attention open |
| `GET monitoring/manuals/?series=` | per series, then per manual: which offices are working on it and which have not started |
| `GET monitoring/advised/` | the Advised revisions lens (§7.3.6): manual, advised office, deadline and type, status, holder, days late |
| `GET monitoring/critical-times/?scope=all\|branch:<id>\|office:<id>` | the next 90 days: deadlines (date, type, days left, offices unmet of targeted, urgency) and freeze bands; clusters flagged; capped to scope |
| `GET monitoring/<view>/export.csv`, `…/export.pdf` | §5 |

- **The admin dashboard summary** gains `offices_chart` (one aggregate
  query) and `critical_times`. It loses the activity series,
  `enough_for_chart` and the table fallback.
- **Query budget** (§9, measured on `seed_scale` before and after):
  - summaries under 500 ms; a list page under 800 ms;
  - a fixed number of queries per endpoint, whatever the page size —
    tested as in 3B.
- **Where the design limits sit**, if a budget is missed: top 15 with
  "Show more"; a filter required above 200 rows; never a database change.

## 5. Export (§7.5)

- **CSV** for "spreadsheet". It is written with the standard library, so
  no new dependency.
  - **UTF-8 with a byte-order mark**, so Excel reads accented office
    names correctly.
  - **Formula-safe cells:** a cell beginning with `=`, `+`, `-`, `@`, a
    tab or a carriage return is prefixed with `'`, so no cell runs as a
    formula. A test covers each.
  - The first lines carry the view, its filters, the scope, the viewer's
    position and the date and time.
- **PDF** built with PyMuPDF, which is already installed for extraction:
  - a header block with the same facts;
  - the table, paged, with a page footer reading "Page n of N · printed
    …";
  - position titles, never names, as for the generated forms.
- **Size and logging:** an export is capped at 5,000 rows and says so if
  cut. Each export is recorded in the system log (`monitoring_exported`:
  who, view, filters, rows).

## 6. Screens

One **Monitoring** destination in each portal, with lenses rather than
tabs. Overdue and stalled are filters of it, not tabs (§7.3).

1. **Overview** (landing):
   - counts first, at most six tiles above the fold: overdue, stalled,
     due soon, returned, waiting, advised revisions;
   - every tile opens its filtered list;
   - below the tiles, the offices bar chart for the viewer's branch.
   - Empty tiles do not show.
2. **By office:**
   - the tree, collapsed, each node with rolled-up counts and the most
     overdue first;
   - opening a node loads only its children;
   - opening an office lists its items, 50 a page.
3. **By deadline:** the deadlines in scope. Opening one shows its offices
   grouped by branch, with only the branch that needs attention open.
4. **By manual:** series, then manuals: who is working on each and who has
   not started.
5. **Advised revisions:**
   - the lens of §7.3.6;
   - also a count on the Overview, and a column in By office and By
     deadline.

**Rows:**
- at most five columns by default: item, status, holder, days, waiting on;
- a details expander for the rest;
- the Overdue, Stalled and Frozen chips in words, never colour alone.

**Admin dashboard (§7.6):**
- **The offices bar chart replaces the activity chart:**
  - horizontal bars, highest first;
  - **Pending / Approved** toggle; Approved has a period (this month, this
    year, last year, custom);
  - filters for branch and series;
  - values printed on the bars;
  - top 15, then "Show more"; offices with none collapse into "No pending
    proposals · N offices";
  - hover gives the stage breakdown; a click opens Proposals for that
    office and status.
- **Critical times beside it:**
  - the next 90 days, with deadlines as marks and freezes as bands;
  - "7 of 12 not yet submitted";
  - clusters flagged;
  - a scope switch: all, a branch, or an office;
  - a click opens By deadline.

**QMS (§7.7):**
- **Dashboard landing:**
  1. the viewer's queue as counts only, which differ for the IMR and the
     Custodian, opening Requests;
  2. the offices chart;
  3. critical times;
  4. overdue and stalled counts;
  5. the advised revisions count.
- Monitoring, read-only, across the institution. Manuals stays in the
  navigation.

**Heads and Encoders:**
- **Office monitoring** in the navigation: the branch for Heads and their
  delegates, the own office for Encoders (Q-3);
- critical times for their own office on Home, without the switch.

## 7. Monitor-only demo accounts

There is **no new role.** "Monitor-only" falls out of the data: a Head of
an office that concurs on nothing and owns no series can neither propose
nor concur, and sees Monitoring for its branch. `seed_demo_org` gains four
fictional Heads, with the demo password and names invented like the
existing ones:

| Username | Office | Sees |
|---|---|---|
| `OP_Head` | Office of the President | everything beneath the President |
| `VPAF_Head` | VP for Administration and Finance | both CAO branches |
| `CAOF_Head` | CAO for Finance | Accounting, Budget, Cash |
| `CAOA_Head` | CAO for Administration | HRMO, QMS office |

**Note on the VPAF.** It owns FAM and HRM, so its Head signs on paper and
is on the approval route. It neither proposes nor concurs (principle 6),
so the account is monitor-only in DocuRoute.

**The seed's `--clear`** still removes exactly what the seed made. A test
checks each account can open Monitoring, sees exactly its branch, and is
refused (`not_concurring`, `not_participating`) when it tries to propose
or concur.

`DEMO_CHECKLIST.md` gains a monitoring walk-through with these four.

## 8. Sub-phases and checkpoints

| Sub-phase | Scope | Ends at |
|---|---|---|
| **4A** | scope helper; status vocabulary; `OfficeMonitoringCount` and migration 0051; refresh on transitions; `summary` step in `run_monitoring`; the endpoints; budgets measured | Checkpoint 4A |
| **4B** | the Monitoring screens (Overview, By office, By deadline, By manual, Advised revisions) for admin, QMS, Heads and Encoders | Checkpoint 4B |
| **4C** | admin dashboard chart and critical times; QMS dashboard; Head Home timeline; exports | Checkpoint 4C |
| **4D** | demo accounts, `DEMO_CHECKLIST.md`, drives at scale and on the demo data, the full suite | Checkpoint 4 (tag `v4.2.0-p4`) |

**Tests, run as the policy says:**
- every new test fails without its code;
- partial runs during each sub-phase;
- the full suite after 0051 (it touches `models.py`) and before the tag;
- screenshots of every main screen at scale for the five-second test
  (§11.1).

## 9. Questions before building (answered 26 Oct 2026; see §11)

| # | Question | Recommendation |
|---|---|---|
| Q-1 | "Spreadsheet" export: CSV, or `.xlsx`? `.xlsx` needs a new dependency (`openpyxl`) | **CSV**: no new dependency, opens in Excel |
| Q-2 | **Office timeliness** (§7.3.5: on-time rate, average days to concur, overdue count) is in the spec but not in your list. Build it in 4B, or later? | **As columns in By office** (two numbers per office from the summary table), not a separate lens |
| Q-3 | Encoders: Monitoring for their branch (spec §7.1, "position holders"), or Heads only? | **Both**, read-only, as the spec says |
| Q-4 | Approved-chart period "custom": a date range on `made effective` | a from/to pair, at most two years |
| Q-5 | Critical times when more than ~20 deadlines fall in 90 days | show the 10 most urgent, cluster the rest by week with counts |

## 10. Raised from the end of Phase 3, before Phase 4 starts

Both are in `WORKFLOW_AS_BUILT.md` under "Differences from the design".

1. **Defect: the text can change while out for concurrence.**
   - **Cause:** `Proposal.EDITABLE_STATUSES` includes Out for
     concurrence.
   - **Effect:** the requesting office can edit a section after
     submission. The edit is accepted, makes no new version, and leaves
     concurrences already given on the earlier text standing (probed on
     26 Oct 2026).
   - **Proposed fix:** refuse edits outside Draft (`not_open`). Changing
     the text after submission then means withdrawing, or being returned,
     which already makes a new version and resets every concurrence.
   - **How:** a small fix of its own, with a test failing without it.
2. **Locking tells only the requesting office.** `CLAUDE.md` says the
   signatory offices (the owner and the approving levels above) are told
   too, so they know documents are coming. **Proposed:** add them as info
   on the lock notice.

**Both fixed** after `v4.2.0-p3`, before Phase 4 (see `CHANGELOG.md`).

## 11. Answers (26 October 2026)

- **Q-1, export:** CSV and PDF. CSV in UTF-8 with a byte-order mark,
  with formula-safe cells (§5).
- **Q-2, office timeliness:**
  - **Where:** columns in By office (on-time rate, average days to
    concur, overdue count), not a lens of their own.
  - **Sorting:** by name or by overdue, **overdue by default**.
  - **How it's computed** shows beside the columns in one line, with the
    full definitions on a click:
    - *on-time* = obligations met by their due date, out of those due;
    - *days to concur* = from the concurrence request to the office's
      decision, over the last 12 months.
- **Q-3, who sees what:** an Encoder sees their own office's status.
  Heads, their delegates and the offices above see the branch (§1).
- **Q-4, a custom date range** (from and to, at most two years) for the
  Approved chart in Phase 4, and for History when Phase 5 builds it
  (§8.4).
- **Q-5, critical times:**
  - the 10 most urgent in the 90-day window, **overdue first**, grouped
    by week;
  - "and N more" for the rest, opening By deadline with the same window.
