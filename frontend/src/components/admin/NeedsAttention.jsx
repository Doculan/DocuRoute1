import { useState } from "react";
import useServerData from "../useServerData";

const GROUP_TITLES = {
  priority_or_near: "Priority or due within 30 days",
  overdue: "Overdue",
  stalled: "Stalled",
};
const GROUPS = Object.keys(GROUP_TITLES);
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v));

/**
 * Needs attention (spec §8.2), on top of the admin's Proposals list and
 * under the same filters: priority and nearing deadlines, then overdue,
 * then stalled. A request appears once. Each part shows its count and its
 * first 10 rows; "Show more" pages through the rest of that part. Hidden
 * when there is nothing.
 */
export default function NeedsAttention({ filters, onOpen, onOpenDeadlines }) {
  const [open, setOpen] = useState(true);
  const { data } = useServerData("/api/admin/proposals/attention/", clean(filters));
  if (!data || data.count === 0) return null;

  return (
    <section className="board-section" style={{ marginBottom: "1.5rem" }}>
      <button type="button" className="board-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="board-toggle">{open ? "▾" : "▸"}</span>
        <span className="board-title">Needs attention</span>
        <span className="tab-count">{data.count}</span>
      </button>
      {open && GROUPS.filter((g) => data.groups[g]).map((g) => (
        <Part key={g} group={g} total={data.groups[g]} filters={filters}
              top={data.rows.filter((r) => r.group === g)}
              onOpen={onOpen} onOpenDeadlines={onOpenDeadlines} />
      ))}
    </section>
  );
}

function Part({ group, total, top, filters, onOpen, onOpenDeadlines }) {
  const [more, setMore] = useState(false);
  return (
    <div className="board-rows">
      <div className="board-group subtle text-xs">{GROUP_TITLES[group]} · {total}</div>
      {more ? <MoreRows group={group} filters={filters} onOpen={onOpen} onOpenDeadlines={onOpenDeadlines} />
        : top.map((r) => <Row key={key(r)} r={r} onOpen={onOpen} onOpenDeadlines={onOpenDeadlines} />)}
      {total > top.length && (
        <button type="button" className="link-btn text-xs" style={{ margin: "0.4rem 0.15rem" }}
                onClick={() => setMore(!more)}>
          {more ? "Show the first 10" : `Show more (${total - top.length} more)`}
        </button>
      )}
    </div>
  );
}

function MoreRows({ group, filters, onOpen, onOpenDeadlines }) {
  const [page, setPage] = useState(1);
  const { data } = useServerData("/api/admin/proposals/attention/", { ...clean(filters), group, page });
  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  return (
    <>
      {data.rows.map((r) => <Row key={key(r)} r={r} onOpen={onOpen} onOpenDeadlines={onOpenDeadlines} />)}
      {data.pages > 1 && (
        <div className="pager">
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </>
  );
}

const key = (r) => (r.proposal_id ? `p${r.proposal_id}` : `m${r.manual_id}-${r.office}`);

function Row({ r, onOpen, onOpenDeadlines }) {
  return (
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
  );
}
