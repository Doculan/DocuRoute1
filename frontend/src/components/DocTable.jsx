import { normalizeTableRows } from "../docTable";

// Renders a table block from section content.
//
// `declaredWidth` is the column count the source stated in its "| --- |"
// separator row. When present it is authoritative — an empty header cell is a
// real column, not something to tidy away. When absent the content predates the
// extraction fix and the width has to be inferred; see docTable.js.

export default function DocTable({ rows, declaredWidth = null }) {
  const { colCount, rows: normalized } = normalizeTableRows(rows, declaredWidth);
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
