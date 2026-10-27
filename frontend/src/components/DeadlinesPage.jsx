import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { dueText } from "./deadlineText";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * What your office still owes, most urgent first. `limit` makes it the
 * Home panel (top few, "Show all"); without it, the full page, paged.
 */
export default function DeadlinesPage({ limit, onShowAll, onOpenManual, onOpenProposal }) {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    try {
      const res = await axios.get("/api/my-deadlines/", { ...getAuth(), params: { page } });
      setData(res.data);
    } catch {
      setData({ count: 0, deadlines: [] });
    }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  if (!data) return null;
  const panel = Boolean(limit);
  if (panel && data.count === 0) return null;
  const rows = panel ? data.deadlines.slice(0, limit) : data.deadlines;

  const body = (
    <div className="col" style={{ gap: "0.5rem" }}>
      {rows.map((d) => (
        <div key={`${d.deadline_id}-${d.office}`} className={`deadline-row is-${d.urgency}`}>
          <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "baseline" }}>
            <strong className="text-sm">{dueText(d)}</strong>
            <span className="text-sm">{d.title}</span>
            <span className="subtle text-xs">{d.type} · {d.office}</span>
          </div>
          {d.manuals.length > 0 ? (
            <div className="row-wrap" style={{ gap: "0.4rem", marginTop: "0.2rem" }}>
              {d.manuals.slice(0, panel ? 3 : 50).map((m) => (
                <button key={m.id} type="button" className="link-btn text-xs"
                        onClick={() => (m.proposal_id && onOpenProposal
                          ? onOpenProposal(m.proposal_id) : onOpenManual?.(m.id))}>
                  {m.priority && <span className="badge badge-warning">Priority</span>} {m.title}
                  {m.status && <span className="subtle"> · {m.status}</span>}
                </button>
              ))}
              {panel && d.manuals.length > 3 && (
                <span className="subtle text-xs">+{d.manuals.length - 3}</span>
              )}
            </div>
          ) : (
            <div className="subtle text-xs" style={{ marginTop: "0.2rem" }}>
              Any proposal your office submits will count.
            </div>
          )}
          {!panel && d.note && <p className="subtle text-xs" style={{ margin: "0.3rem 0 0" }}>{d.note}</p>}
        </div>
      ))}
    </div>
  );

  if (panel) {
    return (
      <section>
        <h2 className="section-title">Deadlines</h2>
        {body}
        {data.count > rows.length && (
          <button className="link-btn text-xs" onClick={onShowAll}>
            Show all {data.count}
          </button>
        )}
      </section>
    );
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Deadlines</h1>
          <p className="page-subtitle">What your office still owes, most urgent first.</p>
        </div>
      </header>
      {data.count === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing owed</p>
          <p className="empty-text">Deadlines the admin sets for your office appear here.</p>
        </div>
      ) : body}
      {data.pages > 1 && (
        <div className="row" style={{ gap: "0.75rem", alignItems: "center", marginTop: "1rem" }}>
          <button className="btn btn-ghost btn-sm" disabled={page <= 1}
                  onClick={() => setPage(page - 1)}>Previous</button>
          <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages}
                  onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
