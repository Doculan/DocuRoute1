import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./admin/ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function day(value) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Delegate while away (spec §5.5): one office's Head delegations - the
 * current and coming ones, one line each - and a folded form to name
 * someone for a period. Making or ending one asks for the password: it
 * changes who can commit the office. The Head's account page and the
 * admin's People screen both use it.
 */
export default function DelegationPanel({ officeId, officeName }) {
  const [data, setData] = useState(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ delegate_id: "", starts_on: "", ends_on: "", reason: "" });
  const [pending, setPending] = useState(null);     // {kind: "add"} | {kind: "end", id}
  const [error, setError] = useState("");

  const load = useCallback(() => {
    axios.get(`/api/offices/${officeId}/delegations/`, getAuth())
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.error || "Could not load the delegations."));
  }, [officeId]);
  useEffect(() => { load(); }, [load]);

  const confirmed = async (token) => {
    const action = pending;
    setPending(null);
    setError("");
    const headers = { headers: { ...getAuth().headers, ...reauthHeader(token) } };
    try {
      if (action.kind === "add") {
        await axios.post(`/api/offices/${officeId}/delegations/`, form, headers);
        setAdding(false);
        setForm({ delegate_id: "", starts_on: "", ends_on: "", reason: "" });
      } else {
        await axios.post(`/api/delegations/${action.id}/end/`, {}, headers);
      }
      load();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    }
  };

  if (!data) return error ? <div className="alert alert-danger">{error}</div> : null;
  const ready = form.delegate_id && form.starts_on && form.ends_on && form.reason.trim();

  return (
    <div className="col" style={{ gap: "0.5rem" }}>
      {data.delegations.length === 0 && !adding && (
        <p className="subtle text-sm" style={{ margin: 0 }}>No delegation set.</p>
      )}
      {data.delegations.map((d) => (
        <div key={d.id} className="row text-sm" style={{ gap: "0.6rem", alignItems: "baseline" }}>
          <span>
            <strong>{d.delegate}</strong> acts as Head, {day(d.starts_on)} – {day(d.ends_on)}
          </span>
          <span className={`status-mark is-${d.status === "current" ? "approved" : "pending"}`}>
            {d.status === "current" ? "Now" : "Upcoming"}
          </span>
          <button type="button" className="link-btn text-xs"
                  onClick={() => setPending({ kind: "end", id: d.id, name: d.delegate })}>
            End
          </button>
        </div>
      ))}
      {!adding ? (
        <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}
                onClick={() => setAdding(true)}>
          Delegate while away
        </button>
      ) : (
        <div className="card card-pad col" style={{ gap: "0.6rem", maxWidth: "30rem" }}>
          <select className="select" aria-label="Delegate" value={form.delegate_id}
                  onChange={(e) => setForm({ ...form, delegate_id: e.target.value })}>
            <option value="">Who acts as Head…</option>
            {data.candidates.map((c) => (
              <option key={c.id} value={c.id}>{c.name} — {c.post}</option>
            ))}
          </select>
          <div className="row" style={{ gap: "0.5rem" }}>
            <label className="text-sm subtle row" style={{ gap: "0.35rem" }}>From
              <input className="input" type="date" aria-label="From" value={form.starts_on}
                     onChange={(e) => setForm({ ...form, starts_on: e.target.value })} />
            </label>
            <label className="text-sm subtle row" style={{ gap: "0.35rem" }}>to
              <input className="input" type="date" aria-label="To" value={form.ends_on}
                     onChange={(e) => setForm({ ...form, ends_on: e.target.value })} />
            </label>
          </div>
          <input className="input" maxLength={300} placeholder="Reason (for example, annual leave)"
                 aria-label="Reason" value={form.reason}
                 onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <div className="row" style={{ gap: "0.5rem" }}>
            <button type="button" className="btn btn-primary btn-sm" disabled={!ready}
                    onClick={() => setPending({ kind: "add" })}>
              Delegate
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && <div className="alert alert-danger">{error}</div>}
      {pending && (
        <ConfirmDestructive
          title={pending.kind === "add" ? `Delegate the ${officeName} Head?`
            : `End ${pending.name}'s delegation?`}
          body={pending.kind === "add"
            ? "For the period, they can submit, concur or return, and receive the Head's notices. Their steps are recorded as theirs, acting for the Head."
            : "The Head acts again at once."}
          confirmLabel={pending.kind === "add" ? "Delegate" : "End delegation"}
          passwordHint="Asked because this changes who can commit the office."
          onConfirm={confirmed}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
