import { useState } from "react";
import axios from "axios";
import { reauthHeader } from "../admin/ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const today = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/**
 * Where a document stands on paper before any request touches it - its
 * number, version, revision and effectivity date. Recorded once, by the
 * Document Custodian; after that, its status changes through requests.
 */
export default function BaselineForm({ manualId, onDone, onCancel }) {
  const [entry, setEntry] = useState({
    document_number: "", version: "", revision: "", effective_on: "",
  });
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (key) => (e) => { setEntry((v) => ({ ...v, [key]: e.target.value })); setError(""); };

  const send = async () => {
    if (busy) return;
    if (!password) { setError("Confirm with your password."); return; }
    setBusy(true);
    try {
      const { data: confirmation } = await axios.post(
        "/api/auth/confirm-password/", { password }, getAuth());
      setPassword("");
      await axios.post(`/api/manuals/${manualId}/status/baseline/`, entry,
        { headers: { ...getAuth().headers, ...reauthHeader(confirmation.token) } });
      onDone();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ marginBottom: "1.5rem", padding: "1.1rem 1.25rem" }}>
      <h2 className="section-title" style={{ marginTop: 0 }}>Starting status</h2>
      <div className="col" style={{ gap: "0.9rem" }}>
        <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
          <div className="field">
            <label className="label" htmlFor="baseline-number">Document number</label>
            <input id="baseline-number" className="input" value={entry.document_number}
                   onChange={set("document_number")} />
          </div>
          <div className="field">
            <label className="label" htmlFor="baseline-version">Version</label>
            <input id="baseline-version" className="input" value={entry.version}
                   onChange={set("version")} />
          </div>
          <div className="field">
            <label className="label" htmlFor="baseline-revision">Revision</label>
            <input id="baseline-revision" className="input" value={entry.revision}
                   onChange={set("revision")} />
          </div>
          <div className="field">
            <label className="label" htmlFor="baseline-effective">Effectivity date</label>
            <input id="baseline-effective" className="input" type="date" max={today()}
                   value={entry.effective_on} onChange={set("effective_on")} />
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="baseline-password">Confirm with your password</label>
          <input id="baseline-password" className="input" type="password"
                 autoComplete="current-password" value={password}
                 onChange={(e) => { setPassword(e.target.value); setError(""); }} />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="row-wrap" style={{ gap: "0.5rem" }}>
          <button className="btn btn-primary" disabled={busy} onClick={send}>
            {busy ? "Working…" : "Record"}
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </section>
  );
}
