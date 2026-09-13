// Shared renderer for the pipe-delimited tables the OCR pipeline produces.
//
// Extracted text has ragged rows: a header may carry two cells while the rows
// under it carry three, because pymupdf4llm splits a numbered activity into its
// own cell ("OSD Staff | 1. | Provides the link..."). With table-layout: fixed
// and a colgroup sized from the header alone, the extra column was handed 0% of
// the width and its text vanished behind the wrapper's overflow: hidden — the
// content was in the database the whole time, just unrenderable.

// "1." / "2)" / "a." — a list marker that the extractor peeled into its own cell.
const NUMBER_CELL = /^(?:\d{1,3}|[a-z])[.)]?$/i;

function normalizeTableRows(rows) {
  // Fold a bare list marker back into the cell it belongs to, which usually
  // restores the document's real column count.
  const merged = rows.map((row) => {
    const cells = [];
    for (let i = 0; i < row.length; i++) {
      if (i < row.length - 1 && NUMBER_CELL.test(row[i])) {
        cells.push(`${row[i]} ${row[i + 1]}`.trim());
        i++; // the marker and the text it labels become one cell
      } else {
        cells.push(row[i]);
      }
    }
    return cells;
  });

  // Pad every row to the widest one so no column is ever left without a header
  // slot — a short row would otherwise skew the fixed layout.
  const colCount = merged.reduce((max, row) => Math.max(max, row.length), 0);
  return {
    colCount,
    rows: merged.map((row) => [
      ...row,
      ...Array(colCount - row.length).fill(""),
    ]),
  };
}

export default function DocTable({ rows }) {
  const { colCount, rows: normalized } = normalizeTableRows(rows);
  if (!colCount) return null;

  return (
    <div className="table-scroll doc-table-wrap">
      <table className="doc-table">
        <colgroup>
          {colCount === 2 ? (
            <>
              <col style={{ width: "25%" }} />
              <col style={{ width: "75%" }} />
            </>
          ) : (
            // Equal widths: every column is visible, whatever the count.
            Array.from({ length: colCount }, (_, i) => (
              <col key={i} style={{ width: `${100 / colCount}%` }} />
            ))
          )}
        </colgroup>
        <tbody>
          {normalized.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={ri === 0 ? "is-head" : ci === 0 ? "is-label" : ""}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
