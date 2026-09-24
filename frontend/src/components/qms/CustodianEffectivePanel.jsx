import { useEffect, useState } from "react";
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

const FIELDS = [
  { key: "document_number", label: "Document number" },
  { key: "version", label: "Version" },
  { key: "revision", label: "Revision" },
];

/**
 * Section 5 of the form: the custodian records the document's new status
 * and the change becomes effective - the locked text goes into the
 * document. Starts from the current entry with the revision one higher;
 * the custodian types over it. The password again.
 */
export default function CustodianEffectivePanel({ proposalId, onDone }) {
  const [entry, setEntry] = useState(null);
  const [current, setCurrent] = useState(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await axios.get(
          `/api/proposals/${proposalId}/custodian/effective/`, getAuth());
        setEntry(data.suggested);
        setCurrent(data.current);
      } catch (err) {
        setError(err.response?.data?.error || "Could not load the document's status.");
      }
    })();
  }, [proposalId]);

  const set = (key) => (e) => { setEntry((v) => ({ ...v, [key]: e.target.value })); setError(""); };

  const send = async () => {
    if (busy) return;
    if (!password) { setError("Confirm with your password."); return; }
    setBusy(true);
    setError("");
    try {
      const { data: confirmation } = await axios.post(
        "/api/auth/confirm-password/", { password }, getAuth());
      setPassword("");
      await axios.post(
        `/api/proposals/${proposalId}/custodian/effective/`, entry,
        { headers: { ...getAuth().headers, ...reauthHeader(confirmation.token) } });
      onDone(entry);
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
      setBusy(false);
    }
  };

  if (!entry) {
    return error ? <div className="alert alert-danger" style={{ marginTop: "1.25rem" }}>{error}</div> : null;
  }

  return (
    <section className="card" style={{ marginTop: "1.25rem", padding: "1.1rem 1.25rem" }}>
      <h2 className="section-title" style={{ marginTop: 0 }}>Document status</h2>
      {current && (
        <p className="subtle text-xs" style={{ margin: "-0.25rem 0 0.9rem" }}>
          Now {current.document_number} · version {current.version} · revision {current.revision}
        </p>
      )}
      <div className="col" style={{ gap: "0.9rem" }}>
        <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
          {FIELDS.map((f) => (
            <div className="field" key={f.key}>
              <label className="label" htmlFor={`status-${f.key}`}>{f.label}</label>
              <input id={`status-${f.key}`} className="input" value={entry[f.key]}
                     onChange={set(f.key)} />
            </div>
          ))}
          <div className="field">
            <label className="label" htmlFor="status-effective_on">Effectivity date</label>
            <input id="status-effective_on" className="input" type="date" max={today()}
                   value={entry.effective_on} onChange={set("effective_on")} />
          </div>
          <div className="field">
            <label className="label" htmlFor="status-updated_in_ids_on">Updated in the IDS</label>
            <input id="status-updated_in_ids_on" className="input" type="date" max={today()}
                   value={entry.updated_in_ids_on} onChange={set("updated_in_ids_on")} />
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="effective-password">Confirm with your password</label>
          <input id="effective-password" className="input" type="password"
                 autoComplete="current-password" value={password}
                 onChange={(e) => { setPassword(e.target.value); setError(""); }} />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div>
          <button className="btn btn-primary" disabled={busy} onClick={send}>
            {busy ? "Working…" : "Make effective"}
          </button>
        </div>
      </div>
    </section>
  );
}
