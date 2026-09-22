import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/** Flat rows in, ordered tree out.
 *
 *  The server sends the hierarchy flat with `parent_id`, because a nested
 *  payload would have to pick a shape for a tree of no fixed depth, and
 *  every picker on this screen wants the flat list anyway. Assembling it
 *  here keeps that choice in one place.
 *
 *  Offices whose parent is missing from the list — the usual case being an
 *  inactive parent while inactive rows are hidden — are shown at the top
 *  level rather than dropped. A row that vanishes because of its parent is
 *  worse than a row in the wrong place.
 */
function toTree(rows) {
  const byId = new Map(rows.map((r) => [r.id, { ...r, children: [] }]));
  const roots = [];
  for (const row of byId.values()) {
    const parent = row.parent_id != null ? byId.get(row.parent_id) : null;
    if (parent) parent.children.push(row);
    else roots.push(row);
  }
  const sort = (list) => {
    list.sort((a, b) => a.name.localeCompare(b.name));
    list.forEach((r) => sort(r.children));
  };
  sort(roots);
  return roots;
}

/**
 * The organisation's shape: offices, and who sits under whom.
 *
 * Nothing on this screen deletes anything, and there is no endpoint that
 * would. An office is deactivated or merged into the one that took its
 * work over; either way it stays, so a request from two years ago still
 * resolves to the office that made it.
 */
export default function Offices() {
  const [rows, setRows] = useState([]);
  const [inactiveTotal, setInactiveTotal] = useState(0);
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const [editing, setEditing] = useState(null);     // office being edited
  const [creatingUnder, setCreatingUnder] = useState(undefined); // parent id or null
  const [pendingMove, setPendingMove] = useState(null);
  const [pendingDeactivate, setPendingDeactivate] = useState(null);
  const [merging, setMerging] = useState(null);     // { office, into, preview }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(
        `${BASE_URL}/api/org/offices/?include_inactive=${showInactive}`,
        getAuth()
      );
      setRows(data.offices);
      setInactiveTotal(data.inactive_total);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load the organisation.");
    } finally {
      setLoading(false);
    }
  }, [showInactive]);

  useEffect(() => { load(); }, [load]);

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 4000);
  };

  const tree = useMemo(() => toTree(rows), [rows]);

  const save = async (form) => {
    try {
      if (form.id) {
        await axios.patch(
          `${BASE_URL}/api/org/offices/${form.id}/`,
          { name: form.name, abbreviation: form.abbreviation,
            is_approving_level: form.is_approving_level },
          getAuth()
        );
        say(`Saved ${form.name}.`);
      } else {
        await axios.post(
          `${BASE_URL}/api/org/offices/`,
          { name: form.name, abbreviation: form.abbreviation,
            parent_id: form.parent_id ?? null,
            is_approving_level: form.is_approving_level },
          getAuth()
        );
        say(`Added ${form.name}.`);
      }
      setEditing(null);
      setCreatingUnder(undefined);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not save.");
    }
  };

  const move = async (token) => {
    const { office, parentId } = pendingMove;
    setPendingMove(null);
    try {
      await axios.patch(
        `${BASE_URL}/api/org/offices/${office.id}/`,
        { parent_id: parentId },
        { headers: { ...getAuth().headers, ...reauthHeader(token) } }
      );
      say(`Moved ${office.name}.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not move the office.");
    }
  };

  const deactivate = async (token) => {
    const office = pendingDeactivate;
    setPendingDeactivate(null);
    try {
      await axios.post(
        `${BASE_URL}/api/org/offices/${office.id}/deactivate/`, {},
        { headers: { ...getAuth().headers, ...reauthHeader(token) } }
      );
      say(`${office.name} is no longer active. Its record stays.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not deactivate the office.");
    }
  };

  const previewMerge = async (office, intoId) => {
    try {
      const { data } = await axios.get(
        `${BASE_URL}/api/org/offices/${office.id}/merge/?into=${intoId}`,
        getAuth()
      );
      setMerging({ office, into: data.into, preview: data.moves });
    } catch (err) {
      setError(err.response?.data?.error || "Could not preview the merge.");
    }
  };

  const doMerge = async (token) => {
    const { office, into } = merging;
    setMerging(null);
    try {
      await axios.post(
        `${BASE_URL}/api/org/offices/${office.id}/merge/`, { into: into.id },
        { headers: { ...getAuth().headers, ...reauthHeader(token) } }
      );
      say(`${office.name} merged into ${into.name}.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not merge.");
    }
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading the organisation…</div>;
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Offices</h1>
          <p className="page-subtitle">
            The units that own, propose and approve documents.
          </p>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={() => setCreatingUnder(null)}
        >
          + Add office
        </button>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      {rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No offices yet</p>
          <p className="empty-text">
            The organisation starts empty. Add the highest office first — a
            president or vice president — then the units that report to it.
          </p>
        </div>
      ) : (
        <div className="office-tree">
          {tree.map((office) => (
            <OfficeNode
              key={office.id}
              office={office}
              depth={0}
              allRows={rows}
              onEdit={setEditing}
              onAddUnder={setCreatingUnder}
              onMove={(o, parentId) => setPendingMove({ office: o, parentId })}
              onDeactivate={setPendingDeactivate}
              onMerge={previewMerge}
            />
          ))}
        </div>
      )}

      {inactiveTotal > 0 && (
        <button
          className="link-btn"
          style={{ marginTop: "1.25rem" }}
          onClick={() => setShowInactive((v) => !v)}
        >
          {showInactive
            ? "Hide inactive and merged offices"
            : `Show ${inactiveTotal} inactive or merged office${inactiveTotal === 1 ? "" : "s"}`}
        </button>
      )}

      {(editing || creatingUnder !== undefined) && (
        <OfficeForm
          office={editing}
          parentId={creatingUnder}
          offices={rows}
          onSave={save}
          onCancel={() => { setEditing(null); setCreatingUnder(undefined); }}
        />
      )}

      {pendingMove && (
        <ConfirmDestructive
          title={`Move ${pendingMove.office.name}?`}
          body={
            "Moving an office changes the approval route of every document it "
            + "owns — the documents themselves do not change, but who signs "
            + "them next time may."
          }
          confirmLabel="Move office"
          onConfirm={move}
          onCancel={() => setPendingMove(null)}
        />
      )}

      {pendingDeactivate && (
        <ConfirmDestructive
          title={`Deactivate ${pendingDeactivate.name}?`}
          body={
            "The office stays in the system with everything it holds, so past "
            + "requests still read correctly. It stops appearing in pickers "
            + "and can be reactivated."
          }
          confirmLabel="Deactivate"
          onConfirm={deactivate}
          onCancel={() => setPendingDeactivate(null)}
        />
      )}

      {merging && (
        <ConfirmDestructive
          title={`Merge ${merging.office.name} into ${merging.into.name}?`}
          body={<MergePreview preview={merging.preview} into={merging.into} />}
          confirmLabel="Merge"
          onConfirm={doMerge}
          onCancel={() => setMerging(null)}
        />
      )}
    </div>
  );
}

/** One office and everything under it. */
function OfficeNode({ office, depth, allRows, onEdit, onAddUnder, onMove,
                      onDeactivate, onMerge }) {
  const [open, setOpen] = useState(true);
  const [action, setAction] = useState(null);   // "move" | "merge" | null

  const others = allRows.filter((r) => r.id !== office.id);

  return (
    <div className="office-node" style={{ "--depth": depth }}>
      <div className={`office-row${office.is_active ? "" : " is-retired"}`}>
        <button
          className="office-twisty"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Collapse" : "Expand"}
          style={{ visibility: office.children.length ? "visible" : "hidden" }}
        >
          {open ? "▾" : "▸"}
        </button>

        <span className="office-name">{office.name}</span>
        {office.abbreviation && (
          <span className="office-abbr">{office.abbreviation}</span>
        )}
        {office.is_approving_level && (
          <span className="badge badge-info" title="Signs; does not propose or concur">
            approves
          </span>
        )}
        {!office.is_active && (
          <span className="badge badge-neutral">
            {office.merged_into ? `merged into ${office.merged_into}` : "inactive"}
          </span>
        )}

        {office.is_active && (
          <span className="office-actions">
            <button className="link-btn" onClick={() => onAddUnder(office.id)}>Add under</button>
            <button className="link-btn" onClick={() => onEdit(office)}>Edit</button>
            <button className="link-btn" onClick={() => setAction(action === "move" ? null : "move")}>Move</button>
            <button className="link-btn" onClick={() => setAction(action === "merge" ? null : "merge")}>Merge</button>
            <button className="link-btn" onClick={() => onDeactivate(office)}>Deactivate</button>
          </span>
        )}
      </div>

      {action && (
        <div className="office-picker">
          <label className="label" htmlFor={`pick-${office.id}`}>
            {action === "move" ? "Move under" : "Merge into"}
          </label>
          <select
            id={`pick-${office.id}`}
            className="select"
            defaultValue=""
            onChange={(e) => {
              const value = e.target.value;
              if (!value) return;
              setAction(null);
              if (action === "move") {
                onMove(office, value === "top" ? null : Number(value));
              } else {
                onMerge(office, Number(value));
              }
            }}
          >
            <option value="" disabled>Choose an office…</option>
            {action === "move" && <option value="top">(no parent — top level)</option>}
            {others.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
      )}

      {open && office.children.map((child) => (
        <OfficeNode
          key={child.id}
          office={child}
          depth={depth + 1}
          allRows={allRows}
          onEdit={onEdit}
          onAddUnder={onAddUnder}
          onMove={onMove}
          onDeactivate={onDeactivate}
          onMerge={onMerge}
        />
      ))}
    </div>
  );
}

function MergePreview({ preview, into }) {
  const lines = [
    [preview.owned_series, "series owned"],
    [preview.owned_documents, "documents owned"],
    [preview.series_links, "series links"],
    [preview.document_links, "document links"],
    [preview.positions, "positions"],
    [preview.children, "offices underneath"],
  ].filter(([n]) => n > 0);

  const dropped = (preview.series_links_already_held || 0)
    + (preview.document_links_already_held || 0);

  return (
    <>
      {lines.length === 0 ? (
        <>This office holds nothing, so nothing moves.</>
      ) : (
        <>
          Moving to {into.name}:{" "}
          {lines.map(([n, what]) => `${n} ${what}`).join(", ")}.
        </>
      )}
      {dropped > 0 && (
        <>
          {" "}
          <strong>{dropped}</strong> link{dropped === 1 ? " is" : "s are"} dropped
          because {into.name} already relates to the same document or series —
          its own relationship is the one that keeps applying.
        </>
      )}
      {preview.positions_already_held > 0 && (
        <>
          {" "}
          <strong>{preview.positions_already_held}</strong> position
          {preview.positions_already_held === 1 ? " is" : "s are"} retired
          rather than moved, because {into.name} already has one.
        </>
      )}
      {preview.holders_ending > 0 && (
        <>
          {" "}
          That ends{" "}
          {preview.holders_ending_detail
            .map((h) => `${h.user} as ${h.position}`)
            .join(", ")}
          , dated today. The record of who held the post stays.
        </>
      )}
      {" "}
      {into.name} keeps its own details. The merged office stays in the
      system, inactive, so past requests still resolve to it.
    </>
  );
}

function OfficeForm({ office, parentId, offices, onSave, onCancel }) {
  const [form, setForm] = useState({
    id: office?.id ?? null,
    name: office?.name ?? "",
    abbreviation: office?.abbreviation ?? "",
    parent_id: office ? office.parent_id : parentId,
    is_approving_level: office?.is_approving_level ?? false,
  });

  const parent = offices.find((o) => o.id === form.parent_id);

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "460px" }}>
        <form onSubmit={(e) => { e.preventDefault(); onSave(form); }}>
          <div className="modal-head">
            <h3 className="modal-title">{office ? "Edit office" : "Add office"}</h3>
          </div>

          <div className="modal-body col" style={{ gap: "1rem" }}>
            <div className="field">
              <label className="label" htmlFor="office-name">Name</label>
              <input
                id="office-name"
                className="input"
                autoFocus
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="office-abbr">
                Abbreviation <span className="subtle">(optional)</span>
              </label>
              <input
                id="office-abbr"
                className="input"
                value={form.abbreviation}
                onChange={(e) => setForm({ ...form, abbreviation: e.target.value })}
              />
            </div>

            {!office && (
              <p className="subtle text-xs" style={{ margin: 0 }}>
                {parent ? `Reports to ${parent.name}.` : "No parent — a top-level office."}
              </p>
            )}

            <label className="row" style={{ gap: "0.55rem", alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={form.is_approving_level}
                onChange={(e) => setForm({ ...form, is_approving_level: e.target.checked })}
              />
              <span>
                <span className="strong">Approving level</span>
                <span className="subtle text-xs" style={{ display: "block" }}>
                  Signs documents. Owns manual series, but never proposes or
                  concurs — a VP, a president.
                </span>
              </span>
            </label>

            {office && (
              <p className="subtle text-xs" style={{ margin: 0 }}>
                To change where this office sits, use Move — it changes the
                approval route of every document the office owns.
              </p>
            )}
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!form.name.trim()}>
              {office ? "Save" : "Add office"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
