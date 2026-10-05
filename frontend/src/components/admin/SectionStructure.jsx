import { useMemo, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * Merge with the next section, or split this one: correcting extraction
 * after upload. Not a revision.
 *
 * Shown only while the server allows it - before the document has a
 * recorded status, and for sections no request has touched. After that,
 * changes to the sections go through a request.
 */
export default function SectionStructure({ section, next, allowed, onDone }) {
  const [mode, setMode] = useState(null);          // "merge" | "split"
  const [reason, setReason] = useState("");
  const [at, setAt] = useState(null);
  const [useLine, setUseLine] = useState(true);
  const [title, setTitle] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  // Each line with the offset it starts at - where a split would begin.
  const lines = useMemo(() => (section.content || "").split("\n").reduce(
    (acc, text) => {
      const prev = acc[acc.length - 1];
      const offset = prev ? prev.offset + prev.text.length + 1 : 0;
      return [...acc, { text, offset }];
    }, []
  ), [section.content]);

  const canSplit = allowed.has(section.id);
  const canMerge = canSplit && next && allowed.has(next.id);
  if (!canSplit && !canMerge) return null;

  const reset = () => {
    setMode(null); setReason(""); setAt(null); setUseLine(true);
    setTitle(""); setError(""); setConfirming(false);
  };

  const ready = mode === "merge" || (at !== null && (useLine || title.trim()));

  const run = async (token) => {
    setConfirming(false);
    const config = { headers: { ...getAuth().headers, ...reauthHeader(token) } };
    try {
      const { data } = mode === "merge"
        ? await axios.post(`/api/sections/${section.id}/merge-next/`, { reason }, config)
        : await axios.post(`/api/sections/${section.id}/split/`, {
            at, reason,
            title_from_first_line: useLine,
            subtitle: useLine ? "" : title,
          }, config);
      const done = mode === "merge"
        ? `Merged "${next.subtitle}" into "${section.subtitle}".`
        : `Split off "${data.new_section.subtitle}".`;
      reset();
      onDone([done, ...(data.warnings || [])].join(" "));
    } catch (err) {
      setError(err.response?.data?.error || "Could not change the sections.");
    }
  };

  return (
    <div className="structure">
      {!mode && (
        <div className="row-wrap" style={{ gap: "0.5rem" }}>
          {canMerge && (
            <button className="btn btn-ghost btn-sm" onClick={() => setMode("merge")}>
              Merge with next
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => setMode("split")}>
            Split
          </button>
          <span className="account-hint">Fixes extraction. Not a revision.</span>
        </div>
      )}

      {mode && (
        <div className="structure-panel">
          {mode === "merge" ? (
            <p className="structure-lead">
              Joins <strong>{next.subtitle}</strong> into this section. Its
              heading stays in the text, and its sub-sections move here.
            </p>
          ) : (
            <>
              <p className="structure-lead">Choose the line the new section starts at.</p>
              <ol className="structure-lines">
                {lines.map((line, i) => (i === 0 || !line.text.trim()) ? null : (
                  <li key={line.offset}>
                    <button
                      type="button"
                      className={`structure-line${at === line.offset ? " is-picked" : ""}`}
                      onClick={() => setAt(line.offset)}
                    >
                      {line.text}
                    </button>
                  </li>
                ))}
              </ol>
              {at !== null && (
                <>
                  <label className="structure-check">
                    <input type="checkbox" checked={useLine}
                           onChange={(e) => setUseLine(e.target.checked)} />
                    Use this line as the new section's title
                  </label>
                  {!useLine && (
                    <label className="field">
                      <span className="label">New section title</span>
                      <input className="input" value={title} maxLength={255}
                             onChange={(e) => setTitle(e.target.value)} />
                    </label>
                  )}
                </>
              )}
            </>
          )}

          <label className="field">
            <span className="label">Reason <span className="muted">(optional)</span></span>
            <input className="input" value={reason}
                   placeholder="e.g. Extraction split one section in two"
                   onChange={(e) => setReason(e.target.value)} />
          </label>

          {error && <div className="alert alert-danger">{error}</div>}

          <div className="account-actions">
            <button className="btn btn-primary btn-sm" disabled={!ready}
                    onClick={() => setConfirming(true)}>
              {mode === "merge" ? "Merge" : "Split"}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={reset}>Cancel</button>
          </div>
        </div>
      )}

      {confirming && (
        <ConfirmDestructive
          title={mode === "merge" ? "Merge these sections?" : "Split this section?"}
          body={mode === "merge"
            ? `"${next.subtitle}" stops being a section of its own. Its text is kept here, and the change is recorded in this section's history.`
            : "The text from the chosen line on becomes a new section. The change is recorded in this section's history."}
          confirmLabel={mode === "merge" ? "Merge" : "Split"}
          onConfirm={run}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
}
