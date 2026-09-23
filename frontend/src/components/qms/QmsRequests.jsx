import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { ProposalDetail } from "../admin/Proposals";
import ImrDecisionPanel from "./ImrDecisionPanel";
import { STATUS_LABEL } from "../proposalStatus";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function when(value) {
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * What is waiting on this person's QMS positions, and the request itself.
 *
 * Groups appear only when they hold something: an IMR who is not also a
 * custodian never sees an empty "custodian" heading.
 */
export default function QmsRequests({ onCount, openId, onOpen }) {
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get("/api/qms/queue/", getAuth());
      setQueue(data);
      onCount?.(data.imr.length + data.custodian.length);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load the requests.");
    }
  }, [onCount]);

  useEffect(() => { load(); }, [load]);

  if (openId != null) {
    return (
      <ProposalDetail
        proposalId={openId}
        backLabel="Requests"
        onBack={() => { onOpen(null); load(); }}
        renderActions={(data, reload) => data.can_imr_decide && (
          <ImrDecisionPanel
            proposalId={openId}
            onDecided={(decision) => {
              setMessage(decision === "accept"
                ? "Accepted. It goes to the approving authority next."
                : "Denied. Every office involved can read your reason.");
              reload();
              load();
            }}
          />
        )}
      />
    );
  }

  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!queue) return <div className="loading-row"><span className="spinner" /> Loading…</div>;

  const groups = [
    { key: "imr", title: "Waiting for your decision", rows: queue.imr },
    { key: "custodian", title: "With you as Document Custodian", rows: queue.custodian },
  ].filter((g) => g.rows.length > 0);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Requests</h1>
        </div>
      </header>

      {message && <div className="alert alert-success">{message}</div>}

      {groups.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing is waiting for you</p>
        </div>
      ) : groups.map((group) => (
        <section key={group.key} style={{ marginBottom: "1.5rem" }}>
          <h2 className="section-title">{group.title}</h2>
          <div className="col" style={{ gap: "0.15rem" }}>
            {group.rows.map((r) => (
              <button key={r.id} className="series-row" onClick={() => { setMessage(""); onOpen(r.id); }}>
                <span className="series-code">{r.dcr_number}</span>
                <span className="series-title">{r.manual} · from {r.office}</span>
                <span className="subtle text-xs">{STATUS_LABEL[r.status]}</span>
                <span className="subtle text-xs">{when(r.since)}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
