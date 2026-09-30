import { useLayoutEffect, useRef, useState } from "react";
import { changeTable, editCell, editTextBlock, parseSection } from "../sectionEditor";

function CellInput({ value, ...props }) {
  const input = useRef(null);
  useLayoutEffect(() => {
    input.current.style.height = "auto";
    input.current.style.height = `${input.current.scrollHeight}px`;
  }, [value]);
  return <textarea {...props} ref={input} value={value} rows={2} className="section-cell-input" />;
}

export default function SectionContentEditor({ value, onChange, disabled = false, label }) {
  const [selected, setSelected] = useState({ block: -1, row: 0, column: 0 });
  const [active, setActive] = useState(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(null);
  const [undo, setUndo] = useState(null);
  const blocks = parseSection(value);
  let tableNumber = 0;

  const edit = (next) => {
    setError("");
    setPending(null);
    setUndo(null);
    onChange(next);
  };
  const action = (blockIndex, kind, index) => {
    const next = changeTable(value, blocks[blockIndex], kind, index);
    if (next !== value) {
      setUndo(value);
      setActive(null);
      setSelected({ block: blockIndex, row: 0, column: 0 });
      onChange(next);
    }
    setPending(null);
    setError("");
  };

  return (
    <div className="section-content-editor">
      {blocks.map((block, bi) => {
        if (block.kind === "text") {
          const text = value.slice(block.start, block.end);
          if (text && !text.trim()) return null;
          return <textarea key={bi} className="textarea textarea-doc" disabled={disabled}
            aria-label={`${label}, text ${bi + 1}`} value={text}
            rows={Math.min(14, Math.max(3, text.split("\n").length))}
            onChange={(e) => edit(editTextBlock(value, block, e.target.value))} />;
        }
        const number = ++tableNumber;
        const row = selected.block === bi ? Math.min(selected.row, block.rows.length - 1) : 0;
        const column = selected.block === bi ? Math.min(selected.column, block.width - 1) : 0;
        return (
          <div key={bi} className="section-table-editor">
            <div className="table-scroll">
              <table className="section-edit-table" style={{ minWidth: `${block.width * 150}px` }}>
                <caption>Table {number}</caption>
                <tbody>
                  {block.rows.map((r, ri) => (
                    <tr key={ri}>
                      {Array.from({ length: block.width }, (_, ci) => {
                        const Cell = block.separator && ri === 0 ? "th" : "td";
                        const focused = active?.block === bi && active.row === ri && active.column === ci;
                        return (
                          <Cell key={ci} className={selected.block === bi && row === ri && column === ci ? "is-selected" : ""}>
                            <CellInput disabled={disabled}
                              aria-label={`${label}, table ${number}, row ${ri + 1}, column ${ci + 1}`}
                              value={focused ? active.text : r.cells[ci]?.value || ""}
                              onFocus={() => {
                                setSelected({ block: bi, row: ri, column: ci });
                                setActive({ block: bi, row: ri, column: ci, text: r.cells[ci]?.value || "",
                                  source: value, table: block });
                              }}
                              onBlur={() => setActive(null)}
                              onChange={(e) => {
                                try {
                                  const source = focused ? active.source : value;
                                  const table = focused ? active.table : block;
                                  const next = editCell(source, table, ri, ci, e.target.value);
                                  setActive({ block: bi, row: ri, column: ci, text: e.target.value, source, table });
                                  edit(next);
                                } catch (problem) { setError(problem.message); }
                              }} />
                          </Cell>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row-wrap section-table-actions" role="group" aria-label={`Table ${number} controls`}>
              <span className="subtle text-xs">Row {row + 1} · Column {column + 1}</span>
              <button type="button" className="btn btn-ghost btn-sm" disabled={disabled}
                onClick={() => action(bi, "addRow", row)}>Add row below</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={disabled || block.rows.length <= 1 || Boolean(block.separator && row === 0)}
                onClick={() => setPending({ block: bi, kind: "removeRow", index: row, name: `row ${row + 1}` })}>Remove row</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={disabled}
                onClick={() => action(bi, "addColumn", column)}>Add column right</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={disabled || block.width <= 2}
                onClick={() => setPending({ block: bi, kind: "removeColumn", index: column, name: `column ${column + 1}` })}>Remove column</button>
            </div>
            {pending?.block === bi && (
              <div className="row-wrap section-table-actions" role="group" aria-label="Confirm table deletion">
                <span>Remove {pending.name} and its contents?</span>
                <button type="button" className="btn btn-danger btn-sm" disabled={disabled}
                  onClick={() => action(bi, pending.kind, pending.index)}>Confirm removal</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPending(null)}>Cancel</button>
              </div>
            )}
          </div>
        );
      })}
      {error && <p role="alert" className="alert alert-warning">{error}</p>}
      {undo !== null && <button type="button" className="btn btn-ghost btn-sm" disabled={disabled}
        onClick={() => { onChange(undo); setUndo(null); setActive(null); setPending(null); }}>Undo table action</button>}
    </div>
  );
}
