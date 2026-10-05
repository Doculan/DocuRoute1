import { useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function when(value) {
  return new Date(value).toLocaleString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function fileName(disposition, fallback) {
  const match = /filename="([^"]+)"/.exec(disposition || "");
  return match ? match[1] : fallback;
}

/**
 * The audit trail report: one button, and the list of earlier reports
 * collapsed beneath it.
 *
 * Shown only to those the server says may generate it. A system admin is
 * asked why first; the reason is logged with the report.
 */
export default function TrailReport({ proposalId, access }) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [serial, setSerial] = useState("");
  const [log, setLog] = useState(null);

  if (!access?.can_generate) return null;

  const loadLog = async () => {
    try {
      const { data } = await axios.get(
        `/api/proposals/${proposalId}/trail-report/log/`, getAuth()
      );
      setLog(data.reports);
    } catch {
      setLog([]);
    }
  };

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await axios.post(
        `/api/proposals/${proposalId}/trail-report/`,
        access.needs_reason ? { reason } : {},
        { ...getAuth(), responseType: "blob" }
      );
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName(
        res.headers["content-disposition"], `Audit trail ${proposalId}.docx`
      );
      link.click();
      URL.revokeObjectURL(url);
      setSerial(res.headers["x-report-serial"] || "");
      setAsking(false);
      setReason("");
      if (log) loadLog();
    } catch (err) {
      // The error body arrives as a blob too.
      let message = "Could not generate the report.";
      try {
        message = JSON.parse(await err.response.data.text()).error || message;
      } catch { /* keep the generic message */ }
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="trail-report">
      <div className="trail-report-row">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => (access.needs_reason ? setAsking(true) : generate())}
        >
          {busy ? "Generating…" : "Audit trail report"}
        </button>
        {serial && (
          <span className="trail-report-ok">Generated · serial {serial}</span>
        )}
      </div>

      {asking && (
        <div className="trail-report-ask">
          <label className="field">
            <span className="label">Why are you generating this?</span>
            <input className="input" value={reason} autoFocus
                   placeholder="e.g. Requested by the external auditor"
                   onChange={(e) => setReason(e.target.value)} />
          </label>
          <p className="account-hint">Recorded with the report.</p>
          <div className="account-actions">
            <button type="button" className="btn btn-primary"
                    disabled={busy || !reason.trim()} onClick={generate}>
              Generate
            </button>
            <button type="button" className="btn btn-ghost"
                    onClick={() => { setAsking(false); setReason(""); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <div className="alert alert-danger">{error}</div>}

      <details className="trail-report-log"
               onToggle={(e) => { if (e.currentTarget.open && !log) loadLog(); }}>
        <summary>Reports generated</summary>
        {log === null ? null : log.length === 0 ? (
          <p className="account-hint">None yet.</p>
        ) : (
          <ul>
            {log.map((r) => (
              <li key={r.serial}>
                <span className="mono">{r.serial}</span>
                <span>{when(r.generated_at)} · {r.generated_as}</span>
                <span className="muted">{r.stamp}{r.reason ? ` · “${r.reason}”` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
