import { useState } from "react";
import useServerData from "../useServerData";

const GROUP_TITLES = {
  priority_or_near: "Priority or due within 30 days",
  overdue: "Overdue",
  stalled: "Stalled",
};

/**
 * Needs attention (spec §8.2), on top of the admin's Proposals list and
 * under the same filters: priority and nearing deadlines, then overdue,
 * then stalled. A request appears once. Folded to its counts when there
 * is nothing to read; hidden when empty.
 */
export default function NeedsAttention({ filters, onOpen, onOpenDeadlines }) {
  const [open, setOpen] = useState(true);
  const [page, setPage] = useState(1);
  const params = Object.fromEntries(Object.entries({ ...filters, page }).filter(([, v]) => v));
  const { data } = useServerData("/api/admin/proposals/attention/", params);
  if (!data || data.count === 0) return null;

  return (
    <section className="board-section" style={{ marginBottom: "1.5rem" }}>
      <button type="button" className="board-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="board-toggle">{open ? "▾" : "▸"}</span>
        <span className="board-title">Needs attention</span>
        <span className="tab-count">{data.count}</span>
        {Object.entries(data.groups).filter(([, n]) => n).map(([g, n]) => (
          <span key={g} className="subtle text-xs">{GROUP_TITLES[g]} {n}</span>
        ))}
      </button>
      {open && (
        <div className="board-rows">
          {data.rows.map((r, i) => {
            const heading = i === 0 || data.rows[i - 1].group !== r.group
              ? GROUP_TITLES[r.group] : null;
            return (
              <div key={r.proposal_id ? `p${r.proposal_id}` : `m${r.manual_id}-${r.office}`}>
                {heading && <div className="subtle text-xs board-group">{heading}</div>}
                <div className="board-row">
                  <button type="button" className="board-main" disabled={!r.proposal_id}
                          onClick={() => r.proposal_id && onOpen(r.proposal_id)}>
                    <span className="board-manual">{r.manual}
                      {r.series && <span className="subtle text-xs"> · {r.series}</span>}
                      <div className="subtle text-xs">{r.office}</div>
                    </span>
                    <span className="board-deadline">
                      {r.due ? (
                        <>
                          {r.due.days_late
                            ? <span className="status-mark is-returned">Overdue · {r.due.days_late} days</span>
                            : <span className="text-xs">Due {r.due.due_on}</span>}
                          {r.due.priority && <span className="subtle text-xs"> · priority</span>}
                          <div className="subtle text-xs">{r.due.title} · {r.due.type}</div>
                        </>
                      ) : <span className="subtle text-xs">No deadline</span>}
                    </span>
                    <span className="board-status">
                      {r.status}
                      {r.stalled && <span className="status-mark is-pending"> Stalled</span>}
                      <div className="subtle text-xs">
                        {r.waiting_on || r.holder}{r.days != null ? ` · ${r.days} day${r.days === 1 ? "" : "s"}` : ""}
                      </div>
                    </span>
                  </button>
                  <span className="board-action">
                    {r.action.kind === "open"
                      ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => onOpen(r.proposal_id)}>{r.action.label}</button>
                      : <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenDeadlines}>{r.action.label}</button>}
                  </span>
                </div>
              </div>
            );
          })}
          {data.pages > 1 && (
            <div className="pager">
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="subtle text-xs">Page {data.page} of {data.pages} · {data.count} in all</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
