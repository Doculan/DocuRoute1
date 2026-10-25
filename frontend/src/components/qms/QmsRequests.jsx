import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { ProposalDetail } from "../admin/Proposals";
import ImrDecisionPanel from "./ImrDecisionPanel";
import CustodianReturnPanel from "./CustodianReturnPanel";
import CustodianEffectivePanel from "./CustodianEffectivePanel";
import { STATUS_LABEL } from "../proposalStatus";
import DeadlineTag from "../DeadlineTag";
import Pager from "../Pager";

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
      const t = data.totals || {};
      onCount?.((t.imr || 0) + (t.approval || 0) + (t.custodian || 0));
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
        onPackageChanged={load}
        renderActions={(data, reload) => (
          <>
            {data.can_imr_decide && (
              <ImrDecisionPanel
                proposalId={openId}
                onDecided={(decision) => {
                  setMessage(decision === "accept"
                    ? "Accepted. Once the approving authority has signed the DCR, upload the completed copy here."
                    : "Denied. Every office involved can read your reason.");
                  reload();
                  load();
                }}
              />
            )}
            {data.can_make_effective && (
              <CustodianEffectivePanel
                proposalId={openId}
                freeze={data.freeze}
                onDone={(entry) => {
                  setMessage(`Effective. Readers now see revision ${entry.revision}.`);
                  reload();
                  load();
                }}
              />
            )}
            {data.can_custodian_return && (
              <CustodianReturnPanel
                proposalId={openId}
                onReturned={() => {
                  setMessage("Returned. The office replaces the copies you named.");
                  reload();
                  load();
                }}
              />
            )}
          </>
        )}
      />
    );
  }

  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!queue) return <div className="loading-row"><span className="spinner" /> Loading…</div>;

  // Counts first (spec §11.1), then each queue a page of 50 at a time.
  const totals = queue.totals || {};
  const groups = [
    { key: "imr", title: "Waiting for your decision", count: "for your decision",
      rows: queue.imr },
    { key: "approval", title: "Awaiting signed DCR", count: "awaiting the signed DCR",
      rows: queue.approval || [] },
    { key: "custodian", title: "With you as Document Custodian", count: "with you as custodian",
      rows: queue.custodian },
  ].filter((g) => (totals[g.key] || 0) > 0);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Requests</h1>
        </div>
      </header>

      {message && <div className="alert alert-success">{message}</div>}

      {groups.length > 0 && (
        <p className="queue-counts">
          {groups.map((g) => (
            <a key={g.key} href={`#queue-${g.key}`} className="queue-count">
              <strong>{totals[g.key].toLocaleString()}</strong> {g.count}
            </a>
          ))}
        </p>
      )}

      {groups.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing is waiting for you</p>
        </div>
      ) : groups.map((group) => (
        <QueueGroup key={group.key} group={group} total={totals[group.key]}
                    onOpen={(id) => { setMessage(""); onOpen(id); }} />
      ))}
    </div>
  );
}

/** One queue: its first page came with the counts; later pages on asking. */
function QueueGroup({ group, total, onOpen }) {
  const [page, setPage] = useState(null);     // null: the first page we have

  const turn = async (n) => {
    const { data } = await axios.get("/api/qms/queue/", {
      ...getAuth(), params: { queue: group.key, page: n },
    });
    setPage(data);
  };

  const rows = page ? page.results : group.rows;
  const paging = page || { count: total, page: 1, page_size: 50,
                           pages: Math.max(1, Math.ceil(total / 50)) };
  return (
    <section id={`queue-${group.key}`} style={{ marginBottom: "1.5rem" }}>
      <h2 className="section-title">{group.title} · {total.toLocaleString()}</h2>
      <div className="col" style={{ gap: "0.15rem" }}>
        {rows.map((r) => (
          <button key={r.id} className="series-row" onClick={() => onOpen(r.id)}>
            <span className="series-code">{r.dcr_number}</span>
            <span className="series-title">
              {r.manual} · from {r.office}
              {r.deadline && <> <DeadlineTag tag={r.deadline} /></>}
            </span>
            <span className="subtle text-xs">{STATUS_LABEL[r.status]}</span>
            <span className="subtle text-xs">{when(r.since)}</span>
          </button>
        ))}
      </div>
      <Pager paging={paging} onPage={turn} />
    </section>
  );
}
