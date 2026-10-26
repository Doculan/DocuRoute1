import { useState } from "react";
import useServerData from "./useServerData";

/**
 * Monitoring (v4.2 Phase 4): read-only, scoped by the server.
 *
 * Counts first; every count opens its list. Below them, open requests by
 * office, and the office tree rolled up from beneath - most overdue first.
 * The admin and QMS see the whole institution, a Head their branch, an
 * Encoder their own office.
 */

const TILES = [
  ["overdue", "Overdue", "deadline obligations past their due date", "is-danger"],
  ["stalled", "Stalled", "past their stage limit, as of now", "is-warning"],
  ["returned", "Returned", "back with the office to redraft", ""],
  ["in_concurrence", "In concurrence", "waiting on other offices", ""],
  ["awaiting_signatures", "Awaiting signatures", "signed copies to upload", ""],
  ["with_qms", "With QMS", "with the IMR or the custodian", ""],
];

const LIST_TITLES = {
  overdue: "Overdue deadline obligations", stalled: "Stalled requests", returned: "Returned requests",
  in_concurrence: "In concurrence", awaiting_signatures: "Awaiting signatures",
  with_qms: "With QMS", drafting: "Drafting", with_head: "With the Head",
  owed: "Deadline obligations", unmet: "Unmet deadline obligations", open: "Open requests",
};

const OPEN_BUCKETS = ["drafting", "with_head", "in_concurrence", "returned", "awaiting_signatures", "with_qms"];
const openOf = (c) => OPEN_BUCKETS.reduce((n, b) => n + (c[b] || 0), 0);

export default function Monitoring({ title = "Monitoring" }) {
  const [list, setList] = useState(null);   // {bucket, office, officeName}
  const { data, error } = useServerData("/api/monitoring/overview/", null, "Could not load monitoring.");

  if (list) return <ItemList {...list} onBack={() => setList(null)} />;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-subtitle">
            {data?.scope === "all" ? "The whole institution." : data?.scope === "offices"
              ? `Your office${data.offices_in_scope > 1 ? " and the offices beneath it" : ""}.` : ""}
          </p>
        </div>
      </header>
      {error && <div className="alert alert-danger">{error}</div>}
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.scope === "none" ? (
        <div className="empty-state"><p className="empty-title">Nothing to monitor</p>
          <p className="empty-text">You hold no post in an office.</p></div>
      ) : (
        <>
          <div className="stat-grid monitor-tiles">
            {TILES.map(([key, label, note, tone]) => (
              <button key={key} type="button" className={`stat-card ${data.counts[key] ? tone : ""}`}
                      onClick={() => setList({ bucket: key })} disabled={!data.counts[key]}>
                <div className="stat-value">{data.counts[key]}</div>
                <div className="stat-label">{label}</div>
                <div className="subtle text-xs">{note}</div>
              </button>
            ))}
          </div>
          <OfficesChart chart={data.chart} onOpen={(bar) => setList({
            bucket: "open", office: bar.office_id, officeName: bar.office })} />
          <OfficeTree onOpen={(office, bucket) => setList({
            bucket, office: office.id, officeName: office.name, subtree: true })} />
        </>
      )}
    </div>
  );
}

function OfficesChart({ chart, onOpen }) {
  if (!chart || chart.bars.length === 0) return null;
  const top = chart.bars[0].open;
  return (
    <section className="monitor-section">
      <h2 className="section-title">Open requests by office</h2>
      <div className="monitor-bars">
        {chart.bars.map((bar) => (
          <button key={bar.office_id} type="button" className="monitor-bar" onClick={() => onOpen(bar)}
                  title={OPEN_BUCKETS.filter((b) => bar.stages[b]).map((b) => `${LIST_TITLES[b]}: ${bar.stages[b]}`).join(" · ")}>
            <span className="monitor-bar-label">{bar.office}</span>
            <span className="monitor-bar-track">
              <span className="monitor-bar-fill" style={{ width: `${Math.max(4, (bar.open / top) * 100)}%` }} />
            </span>
            <span className="monitor-bar-value">{bar.open}</span>
          </button>
        ))}
      </div>
      {(chart.more > 0 || chart.none > 0) && (
        <p className="subtle text-xs" style={{ margin: "0.5rem 0 0" }}>
          {chart.more > 0 && `${chart.more} more offices with open requests. `}
          {chart.none > 0 && `No open requests · ${chart.none} offices.`}
        </p>
      )}
    </section>
  );
}

function OfficeTree({ onOpen }) {
  return (
    <section className="monitor-section">
      <h2 className="section-title">By office</h2>
      <p className="subtle text-xs" style={{ margin: "-0.25rem 0 0.6rem" }}>
        Each office with everything beneath it. Owed, unmet and overdue are deadline obligations;
        stalled is computed now from each request's stage limit.
      </p>
      <div className="table-wrap">
        <table className="table monitor-tree">
          <thead>
            <tr><th>Office</th><th>Open</th><th>Stalled</th><th>Owed</th><th>Unmet</th><th>Overdue</th></tr>
          </thead>
          <TreeLevel parent={null} depth={0} onOpen={onOpen} />
        </table>
      </div>
    </section>
  );
}

function TreeLevel({ parent, depth, onOpen }) {
  const [page, setPage] = useState(1);
  const { data } = useServerData("/api/monitoring/offices/",
                                 parent ? { parent, page } : { page });
  if (!data) {
    return <tbody><tr><td colSpan={6} className="subtle text-xs" style={{ paddingLeft: `${depth * 1.2 + 0.15}rem` }}>Loading…</td></tr></tbody>;
  }
  return (
    <>
      {data.offices.map((office) => (
        <TreeRow key={office.id} office={office} depth={depth} onOpen={onOpen} />
      ))}
      {data.pages > page && (
        <tbody><tr><td colSpan={6} style={{ paddingLeft: `${depth * 1.2 + 0.15}rem` }}>
          <button type="button" className="link-btn text-xs" onClick={() => setPage(page + 1)}>
            Show more ({data.count - page * 50} more offices)
          </button>
        </td></tr></tbody>
      )}
    </>
  );
}

function TreeRow({ office, depth, onOpen }) {
  const [open, setOpen] = useState(false);
  const c = office.counts;
  const cell = (n, bucket, tone) => (n ? (
    <button type="button" className={`link-btn monitor-count ${tone || ""}`}
            onClick={() => onOpen(office, bucket)}>{n}</button>
  ) : <span className="subtle">0</span>);
  return (
    <>
      <tbody>
        <tr>
          <td style={{ paddingLeft: `${depth * 1.2 + 0.15}rem` }}>
            {office.has_children ? (
              <button type="button" className="link-btn monitor-toggle" aria-expanded={open}
                      onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</button>
            ) : <span className="monitor-toggle" />}
            <button type="button" className="link-btn" onClick={() => onOpen(office, "open")}>
              {office.name}
            </button>
            {!office.active && <span className="subtle text-xs"> (inactive)</span>}
          </td>
          <td>{cell(openOf(c), "open")}</td>
          <td>{cell(c.stalled, "stalled", "is-warning")}</td>
          <td>{cell(c.owed, "owed")}</td>
          <td>{cell(c.unmet, "unmet")}</td>
          <td>{cell(c.overdue, "overdue", "is-danger")}</td>
        </tr>
      </tbody>
      {open && <TreeLevel parent={office.id} depth={depth + 1} onOpen={onOpen} />}
    </>
  );
}

function ItemList({ bucket, office, officeName, subtree, onBack }) {
  const [page, setPage] = useState(1);
  const params = { bucket, page, ...(office ? { office } : {}), ...(subtree ? { subtree: 1 } : {}) };
  const { data, error } = useServerData("/api/monitoring/items/", params, "Could not load the list.");
  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack}>← Monitoring</button>
      <h1 className="page-title" style={{ marginTop: "0.75rem" }}>
        {LIST_TITLES[bucket]}{officeName ? ` · ${officeName}${subtree ? " and beneath" : ""}` : ""}
      </h1>
      {error && <div className="alert alert-danger">{error}</div>}
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.count === 0 ? (
        <div className="empty-state"><p className="empty-title">Nothing here</p></div>
      ) : (
        <>
          <p className="subtle text-xs">{data.count} in all</p>
          <div className="table-wrap">
            {data.kind === "obligations" ? (
              <table className="table">
                <thead><tr><th>Deadline</th><th>Office</th><th>Manual</th><th>Due</th><th>State</th></tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.obligation_id}>
                      <td>{r.deadline}<div className="subtle text-xs">{r.type}</div></td>
                      <td>{r.office}</td>
                      <td>{r.manual || <span className="subtle">Any proposal</span>}</td>
                      <td>{r.due_on}</td>
                      <td>{r.met ? r.state : r.days_late
                        ? <span className="status-mark is-returned">Overdue · {r.days_late} days</span>
                        : r.state}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="table">
                <thead><tr><th>Manual</th><th>Status</th><th>Holder</th><th>Days</th><th>Waiting on</th></tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.proposal_id}>
                      <td>{r.manual}<div className="subtle text-xs">{r.office}</div></td>
                      <td>{r.status}</td>
                      <td>{r.holder}</td>
                      <td>
                        {r.days}
                        {r.stalled && <span className="status-mark is-pending" title={`Limit ${r.limit} days ${r.stage}`}> Stalled</span>}
                      </td>
                      <td>{r.waiting_on}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {data.pages > 1 && (
            <div className="pager">
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
