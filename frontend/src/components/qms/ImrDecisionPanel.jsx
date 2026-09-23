import { useState } from "react";
import axios from "axios";
import { reauthHeader } from "../admin/ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * The IMR's decision: Accept or Deny, with comments, and the password.
 *
 * Section 3 of the form, recorded in the system. A denial closes the
 * request and every office involved reads its reason, so a denial cannot
 * be sent without one. The paper still carries the IMR's signature.
 */
export default function ImrDecisionPanel({ proposalId, onDecided }) {
  const [comments, setComments] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");

  const decide = async (decision) => {
    if (busy) return;
    if (decision === "deny" && !comments.trim()) {
      setError("Say why it is denied. Every office involved will see it.");
      return;
    }
    if (!password) {
      setError("Confirm with your password.");
      return;
    }
    setBusy(decision);
    setError("");
    try {
      const { data: confirmation } = await axios.post(
        "/api/auth/confirm-password/", { password }, getAuth()
      );
      setPassword("");
      await axios.post(
        `/api/proposals/${proposalId}/imr/`, { decision, comments },
        { headers: { ...getAuth().headers, ...reauthHeader(confirmation.token) } }
      );
      onDecided(decision);
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
      setBusy(null);
    }
  };

  return (
    <section className="card" style={{ marginTop: "1.25rem", padding: "1.1rem 1.25rem" }}>
      <h2 className="section-title" style={{ marginTop: 0 }}>Your decision</h2>
      <div className="col" style={{ gap: "0.9rem" }}>
        <div className="field">
          <label className="label" htmlFor="imr-comments">Comments</label>
          <textarea id="imr-comments" className="input" rows={3} value={comments}
                    placeholder="Required to deny"
                    onChange={(e) => { setComments(e.target.value); setError(""); }} />
        </div>
        <div className="field">
          <label className="label" htmlFor="imr-password">Confirm with your password</label>
          <input id="imr-password" className="input" type="password"
                 autoComplete="current-password" value={password}
                 onChange={(e) => { setPassword(e.target.value); setError(""); }} />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="row-wrap" style={{ gap: "0.5rem" }}>
          <button className="btn btn-primary" disabled={!!busy} onClick={() => decide("accept")}>
            {busy === "accept" ? "Working…" : "Accept"}
          </button>
          <button className="btn btn-ghost" disabled={!!busy} onClick={() => decide("deny")}>
            {busy === "deny" ? "Working…" : "Deny"}
          </button>
        </div>
      </div>
    </section>
  );
}
