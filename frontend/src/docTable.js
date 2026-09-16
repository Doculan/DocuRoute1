// Parsing for the pipe-delimited tables stored in section content.
//
// Two formats are in circulation and both have to render:
//
//   NEW - a well-formed Markdown table written by ocr_engine.py, carrying a
//   "| --- | --- |" separator that declares the real column count and marks
//   the header row. Nothing has to be guessed.
//
//   LEGACY - rows flattened to "a | b | c" by the old extractor, which dropped
//   the separator and discarded empty cells. Column count has to be inferred,
//   and a bare list marker in its own cell may or may not have been a real
//   column. Sections extracted before the fix are still stored this way.
//
// Kept in a plain module rather than beside the component so both readers and
// the component share one implementation.

const SEPARATOR_RE = /^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$/;

// "1." / "2)" / "a." - a marker the legacy extractor peeled into its own cell.
const NUMBER_CELL = /^(?:\d{1,3}|[a-z])[.)]?$/i;

export function isTableSeparator(line) {
  const s = line.trim();
  return s.includes("-") && SEPARATOR_RE.test(s);
}

export function parseTableRow(line) {
  const s = line.trim();
  if (!s.includes("|")) return null;

  // Strip exactly one delimiting pipe from each end, never all of them: the
  // header row "| Responsibility |  | Activity |" has a deliberately empty
  // middle cell, and stripping greedily would change the column count.
  let body = s;
  if (body.startsWith("|")) body = body.slice(1);
  if (body.endsWith("|")) body = body.slice(0, -1);

  const cells = body.split("|").map((c) => c.trim());
  return cells.length >= 2 ? cells : null;
}

export function normalizeTableRows(rows, declaredWidth = null) {
  // When the source declared a width, trust it - the document really does have
  // that many columns, empty header cells included.
  if (declaredWidth) {
    return {
      colCount: declaredWidth,
      rows: rows.map((row) =>
        row.length >= declaredWidth
          ? row.slice(0, declaredWidth)
          : [...row, ...Array(declaredWidth - row.length).fill("")]
      ),
    };
  }

  // Legacy: fold a bare list marker back into the cell it labels, which
  // usually restores the column count the document actually had.
  const merged = rows.map((row) => {
    const cells = [];
    for (let i = 0; i < row.length; i++) {
      if (i < row.length - 1 && NUMBER_CELL.test(row[i])) {
        cells.push(`${row[i]} ${row[i + 1]}`.trim());
        i++;
      } else {
        cells.push(row[i]);
      }
    }
    return cells;
  });

  // Pad to the widest row so no column is left without a header slot - a short
  // row would otherwise be handed 0% width by the fixed layout and vanish.
  const colCount = merged.reduce((max, row) => Math.max(max, row.length), 0);
  return {
    colCount,
    rows: merged.map((row) => [
      ...row,
      ...Array(colCount - row.length).fill(""),
    ]),
  };
}
