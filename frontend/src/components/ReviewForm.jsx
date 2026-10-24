import { useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./admin/ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * "Reviewed, no change" (spec §6.5): the Head attests the document needs
 * no revision. An optional note, then the password, since it commits the
 * office: its open deadlines on the document are met.
 */
export default function ReviewForm({ manualId, onCancel, onDone }) {
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  const record = async (token) => {
    setConfirming(false);
    try {
      const { data } = await axios.post(
        `/api/manuals/${manualId}/reviewed-no-change/`, { note },
        { headers: { ...getAuth().headers, ...reauthHeader(token) } },
      );
      onDone(data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not record the review.");
    }
  };

  return (
    <div className="card card-pad col" style={{ gap: "0.75rem", marginBottom: "1rem" }}>
      <h3 className="card-title" style={{ margin: 0 }}>Reviewed, no change</h3>
      <p className="subtle text-sm" style={{ margin: 0 }}>
        Your office has read this document and it needs no revision.
      </p>
      <textarea className="textarea" rows={3} maxLength={1000} value={note}
                placeholder="Note (optional)" aria-label="Note"
                onChange={(e) => setNote(e.target.value)} />
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="row" style={{ gap: "0.5rem" }}>
        <button className="btn btn-primary btn-sm" onClick={() => setConfirming(true)}>
          Record review
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
      {confirming && (
        <ConfirmDestructive
          title="Record Reviewed, no change?"
          body="It meets your office's open deadlines on this document and sets its next review date."
          confirmLabel="Record review"
          passwordHint="Asked because this commits your office."
          onConfirm={record}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
}
