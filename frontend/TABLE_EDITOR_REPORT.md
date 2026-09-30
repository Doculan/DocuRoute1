# Proposal table editing — 1 October 2026

## Completed plan

1. Add an editing parser that retains source offsets, original line endings,
   empty cells, numbered columns and uneven legacy rows.
2. Render existing tables as editable grids between the section's text blocks.
   Add row/column controls, confirmation before deletion and an undo action.
3. Integrate with proposal saving and AI-check status, then verify the data
   operations and actual proposal screen in a browser.

## Behavior

Open a section in a draft proposal. Pipe-delimited tables appear as grids;
click a cell to edit it and use Tab/Shift+Tab to move between cells. Long text
wraps, cell height grows with content, and wide tables scroll horizontally.
Paragraphs before, between and after tables remain editable text areas.

Row and column controls act relative to the selected cell. Removing either
requires confirmation. The latest structural action can be undone until the
next content edit. Header rows and a minimum of two columns are retained.

Opening a section does not rewrite it or enable Save. An ordinary cell edit
changes its source span only; focus-session source retention prevents clearing
and retyping from redistributing padding. Structural changes normalize pipe
spacing within the affected table, preserving its cell values, header alignment,
line-ending style and surrounding text. No reader-side column-merging heuristics
are used by the editor.

Unsaved edits are labelled, mark the existing AI note as stale, and disable
checking until the section is saved. Save still sends the existing `new_text`
payload. Switching or closing sections asks before discarding unsaved text.

## Verification

- `cd frontend; npm test`: 14 tests pass, covering exact source reconstruction,
  unchanged cells, precise edits, prose/table boundaries, CRLF, repeated typing,
  empty and numeric columns, ragged rows, row/column operations, deletion guards,
  invalid cell characters and multiple tables.
- `npm run build`: passes.
- ESLint on the new parser and component: passes. Repository-wide lint retains
  11 errors and 2 warnings. The two existing `StaffProposals.jsx` errors were
  compared against HEAD: same rules and code, shifted by the new import.
- Headless Chrome using a temporary Playwright harness: actual `StaffProposals`
  screen with mocked API responses, no live database writes. Verified no-op
  opening, Tab navigation, multiword typing, exact save payload, stale-note and
  recheck behavior, unsaved-discard cancellation, row/column insertion, row
  removal confirmation/cancellation, undo and invalid-character rejection.
- Desktop (1200px) and narrow (390px) screenshots inspected; verified horizontal
  table scrolling. Browser page errors: none.

The browser run caught a padding issue after clearing a cell before retyping;
the source-retention fix and regression coverage were added before the passing
run. Screenshot review also prompted smaller prose boxes and wrapping section
status badges.

## Boundaries

This is the draft-proposal editor. Storage, backend APIs, AI layers and document
generation are unchanged. No production dependencies or database migrations
were added. Refresh the Vite frontend, or deploy the rebuilt frontend bundle.

The existing text format cannot represent merged cells, embedded pipe characters,
tabs or line breaks inside a cell. Such cell input is rejected with an explanation;
ordinary long text wraps visually. Spreadsheet-range paste and inserting a new
table into plain prose are not implemented. Ambiguous malformed tables remain
plain text so their contents are not discarded. Browser validation uses synthetic
proposals, not a saved edit to a live manual.
