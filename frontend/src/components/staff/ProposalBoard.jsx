import { useState } from "react";
import useServerData from "../useServerData";

// Per person, not per browser: a shared demo browser changes hands.
const filtersKey = () => `staff_board_filters:${localStorage.getItem("username") || ""}`;
const NO_FILTERS = { deadline: "", series: "", manual: "", status: "", overdue: "" };
const STATUSES = [
  ["not_started", "Not started"], ["drafting", "Drafting"], ["returned", "Returned"],
  ["with_head", "With Head"], ["in_concurrence", "In concurrence"],
  ["awaiting_signatures", "Awaiting signatures"], ["with_qms", "With QMS"], ["closed", "Closed"],
];

function readFilters() {
  try { return { ...NO_FILTERS, ...JSON.parse(localStorage.getItem(filtersKey()) || "{}") }; }
  catch { return NO_FILTERS; }
}

function writeFilters(value) {
  try { localStorage.setItem(filtersKey(), JSON.stringify(value)); } catch { /* per viewer only */ }
}

const clean = (f) => Object.fromEntries(Object.entries(f).filter(([, v]) => v));

/**
 * Deadline-first Proposals (spec §8.3). Sections in a fixed order - Due
 * for submission, Awaiting your office, Returned to you, From my office,
 * Other offices' requests - each with its count; empty ones are left out.
 * Only the first is open; the others load their rows when opened, 50 a
 * page. Filters are remembered for this person on this browser.
 */
export default function ProposalBoard({ onOpen, onStart, refreshKey }) {
  const [filters, setFilters] = useState(readFilters);
  const params = { ...clean(filters), refresh: refreshKey };
  const { data, error } = useServerData("/api/proposals/board/", params, "Could not load proposals.");
  const options = data?.options;

  const change = (patch) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    writeFilters(next);
  };
  const filtered = Object.values(filters).some(Boolean);

  return (
    <div>
      <div className="row-wrap" style={{ gap: "0.4rem", marginBottom: "1rem" }}>
        <select className="select" style={{ width: "auto" }} aria-label="Deadline"
                value={filters.deadline} onChange={(e) => change({ deadline: e.target.value })}>
          <option value="">Every deadline</option>
          {(options?.deadlines || []).map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
        </select>
        <select className="select" style={{ width: "auto" }} aria-label="Series"
                value={filters.series} onChange={(e) => change({ series: e.target.value })}>
          <option value="">Every series</option>
          {(options?.series || []).map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
        </select>
        <input className="input" type="search" aria-label="Manual" placeholder="Manual"
               style={{ width: "10rem" }} value={filters.manual}
               onChange={(e) => change({ manual: e.target.value })} />
        <select className="select" style={{ width: "auto" }} aria-label="Status"
                value={filters.status} onChange={(e) => change({ status: e.target.value })}>
          <option value="">Every status</option>
          {STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <label className="row text-sm" style={{ gap: "0.35rem", alignItems: "center" }}>
          <input type="checkbox" checked={!!filters.overdue}
                 onChange={(e) => change({ overdue: e.target.checked ? "1" : "" })} />
          Overdue only
        </label>
        {filtered && <button type="button" className="btn btn-ghost btn-sm"
                             onClick={() => change(NO_FILTERS)}>Clear</button>}
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.sections.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">{filtered ? "Nothing matches these filters" : "Nothing here yet"}</p>
          <p className="empty-text">{filtered ? "Clear the filters to see everything."
            : "Open a document, find the section you want to change, and choose Propose changes."}</p>
        </div>
      ) : data.sections.map((section) => (
        <Section key={`${section.key}-${refreshKey}-${JSON.stringify(clean(filters))}`}
                 section={section} startOpen={section.key === data.open}
                 overdue={section.key === "due" ? data.overdue : 0}
                 filters={clean(filters)} onOpen={onOpen} onStart={onStart} />
      ))}
    </div>
  );
}

function Section({ section, startOpen, overdue, filters, onOpen, onStart }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <section className="board-section">
      <button type="button" className="board-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="board-toggle">{open ? "▾" : "▸"}</span>
        <span className="board-title">{section.title}</span>
        <span className="tab-count">{section.count}</span>
        {overdue > 0 && <span className="status-mark is-returned">{overdue} overdue</span>}
      </button>
      {open && <Rows sectionKey={section.key} filters={filters} onOpen={onOpen} onStart={onStart} />}
    </section>
  );
}

function Rows({ sectionKey, filters, onOpen, onStart }) {
  const [page, setPage] = useState(1);
  const { data, error } = useServerData("/api/proposals/board/",
                                        { ...filters, section: sectionKey, page }, "Could not load.");
  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  return (
    <div className="board-rows">
      {data.rows.map((r) => (
        <div key={r.proposal_id ? `p${r.proposal_id}` : `o${r.obligation_id}`} className="board-row">
          <button type="button" className="board-main" disabled={!r.proposal_id}
                  onClick={() => r.proposal_id && onOpen(r.proposal_id)}>
            <span className="board-manual">{r.manual || "Any document"}
              {r.series && <span className="subtle text-xs"> · {r.series}</span>}
              {sectionKey === "awaiting" || sectionKey === "involving"
                ? <span className="subtle text-xs"> · from {r.office}</span> : null}
            </span>
            <span className="board-deadline">
              {r.deadline ? (
                <>
                  {r.deadline.days_late
                    ? <span className="status-mark is-returned">Overdue · {r.deadline.days_late} days</span>
                    : <span className="text-xs">Due {r.deadline.due_on}</span>}
                  {r.deadline.priority && <span className="subtle text-xs"> · priority</span>}
                  <div className="subtle text-xs">{r.deadline.title} · {r.deadline.type}</div>
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
            {r.action && (r.action.kind === "start"
              ? <button type="button" className="btn btn-primary btn-sm" onClick={() => onStart(r.manual_id)}>Start</button>
              : <button type="button" className="btn btn-ghost btn-sm" onClick={() => onOpen(r.proposal_id)}>{r.action.label}</button>)}
          </span>
        </div>
      ))}
      {data.pages > 1 && (
        <div className="pager">
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="subtle text-xs">Page {data.page} of {data.pages} · {data.count} in all</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
