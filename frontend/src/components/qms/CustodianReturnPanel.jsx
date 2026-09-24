import { useEffect, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * Return the package for defects in it: a missing signature, an
 * unreadable scan. Never for its content, which was frozen at the lock
 * and judged by the IMR - so the choice is only among the signed copies,
 * and only those named can be replaced.
 *
 * No password: a return commits no office and changes no document.
 */
export default function CustodianReturnPanel({ proposalId, onReturned }) {
  const [copies, setCopies] = useState([]);
  const [chosen, setChosen] = useState([]);
  const [comments, setComments] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await axios.get(`/api/proposals/${proposalId}/package/`, getAuth());
        setCopies(Object.entries(data.scans)
          .filter(([, scan]) => scan.current)
          .map(([kind, scan]) => ({ kind, label: scan.label })));
      } catch {
        setError("Could not load the signed copies.");
      }
    })();
  }, [proposalId]);

  const toggle = (kind) => {
    setChosen((c) => (c.includes(kind) ? c.filter((k) => k !== kind) : [...c, kind]));
    setError("");
  };

  const send = async () => {
    if (!chosen.length) { setError("Name the signed copies that are defective."); return; }
    if (!comments.trim()) { setError("Say what is wrong, so the office knows what to fix."); return; }
    setBusy(true);
    try {
      await axios.post(`/api/proposals/${proposalId}/custodian/return/`,
                       { kinds: chosen, comments }, getAuth());
      onReturned();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div style={{ marginTop: "1.25rem" }}>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>
          Return for defects…
        </button>
      </div>
    );
  }

  return (
    <section className="card" style={{ marginTop: "1.25rem", padding: "1.1rem 1.25rem" }}>
      <h2 className="section-title" style={{ marginTop: 0 }}>Return for defects</h2>
      <div className="col" style={{ gap: "0.9rem" }}>
        <div className="col" style={{ gap: "0.35rem" }}>
          {copies.map((copy) => (
            <label key={copy.kind} className="text-sm row" style={{ gap: "0.5rem", alignItems: "center" }}>
              <input type="checkbox" id={`return-${copy.kind}`}
                     checked={chosen.includes(copy.kind)} onChange={() => toggle(copy.kind)} />
              {copy.label}
            </label>
          ))}
        </div>
        <div className="field">
          <label className="label" htmlFor="return-comments">What is wrong</label>
          <textarea id="return-comments" className="input" rows={3} value={comments}
                    placeholder="e.g. the Head's signature is missing on page 1"
                    onChange={(e) => { setComments(e.target.value); setError(""); }} />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="row-wrap" style={{ gap: "0.5rem" }}>
          <button className="btn btn-primary" disabled={busy} onClick={send}>
            {busy ? "Working…" : "Return to the office"}
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
        </div>
      </div>
    </section>
  );
}
