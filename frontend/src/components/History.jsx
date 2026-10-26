import { useState } from "react";
import axios from "axios";
import useServerData from "./useServerData";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

// Per person, not per browser: a shared demo browser changes hands.
const filtersKey = () => `history_filters:${localStorage.getItem("username") || ""}`;
const NO_FILTERS = { view: "mine", date_on: "closed", from: "", to: "", outcome: "", office: "", series: "", dcr: "" };
const OUTCOMES = [["effective", "Effective"], ["denied", "Denied"], ["withdrawn", "Withdrawn"],
                  ["reviewed", "Reviewed, no change"]];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December"];

function readFilters() {
  try { return { ...NO_FILTERS, ...JSON.parse(localStorage.getItem(filtersKey()) || "{}") }; }
  catch { return NO_FILTERS; }
}

const clean = (f) => Object.fromEntries(Object.entries(f).filter(([, v]) => v));
const iso = (d) => d.toLocaleDateString("en-CA");

function quick(range) {
  const today = new Date();
  if (range === "month") return { from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: "" };
  if (range === "year") return { from: `${today.getFullYear()}-01-01`, to: "" };
  return { from: `${today.getFullYear() - 1}-01-01`, to: `${today.getFullYear() - 1}-12-31` };
}

function outcomeLine(outcomes) {
  return OUTCOMES.filter(([k]) => outcomes[k]).map(([k, label]) => `${label} ${outcomes[k]}`).join(" · ");
}

/**
 * History (spec §8.4): what is done - closed requests and "Reviewed, no
 * change" - grouped by year, then month. The current year is open with
 * its months; earlier years are folded with their counts. A month's rows
 * load when it is opened. Read-only; a row opens the request's audit
 * trail. `offices` hides the Mine / Participated switch for the admin
 * and QMS, who see everything.
 */
export default function History({ onOpen, offices = true }) {
  const [filters, setFilters] = useState(readFilters);
  const [message, setMessage] = useState("");
  const params = clean(filters);
  const { data, error } = useServerData("/api/history/", params, "Could not load the history.");

  const change = (patch) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    try { localStorage.setItem(filtersKey(), JSON.stringify(next)); } catch { /* per viewer */ }
  };
  const filtered = ["from", "to", "outcome", "office", "series", "dcr"].some((k) => filters[k]);

  const exportAs = async (format) => {
    setMessage("");
    try {
      const res = await axios.post("/api/history/export/", { ...params, format },
                                   { ...getAuth(), responseType: "blob" });
      const name = (res.headers["content-disposition"] || "").match(/filename="(.+)"/)?.[1] || `history.${format}`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      URL.revokeObjectURL(url);
      setMessage("Exported.");
    } catch {
      setMessage("The export did not work.");
    }
  };

  const thisYear = new Date().getFullYear();
  const total = (data?.years || []).reduce((n, y) => n + y.total, 0);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">History</h1>
          <p className="page-subtitle">What is done: made effective, denied, withdrawn, or reviewed with no change.</p>
        </div>
        {total > 0 && (
          <div className="row" style={{ gap: "0.4rem" }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => exportAs("csv")}>Export CSV</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => exportAs("pdf")}>Export PDF</button>
          </div>
        )}
      </header>
      {message && <p className="subtle text-xs">{message}</p>}

      <div className="row-wrap" style={{ gap: "0.4rem", marginBottom: "0.5rem" }}>
        {offices && data?.scope !== "all" && (
          <div className="segmented" role="group" aria-label="Mine or participated">
            {[["mine", "Mine"], ["participated", "Participated"]].map(([v, label]) => (
              <button key={v} type="button" aria-pressed={filters.view === v}
                      className={`segmented-item${filters.view === v ? " is-active" : ""}`}
                      onClick={() => change({ view: v })}>{label}</button>
            ))}
          </div>
        )}
        <select className="select" style={{ width: "auto" }} aria-label="Date on"
                value={filters.date_on} onChange={(e) => change({ date_on: e.target.value })}>
          <option value="closed">Closed date</option>
          <option value="submitted">Submitted date</option>
        </select>
        {[["month", "This month"], ["year", "This year"], ["last_year", "Last year"]].map(([k, label]) => (
          <button key={k} type="button" className="btn btn-ghost btn-sm" onClick={() => change(quick(k))}>{label}</button>
        ))}
        <input className="input" type="date" aria-label="From" style={{ width: "auto" }}
               value={filters.from} onChange={(e) => change({ from: e.target.value })} />
        <input className="input" type="date" aria-label="To" style={{ width: "auto" }}
               value={filters.to} onChange={(e) => change({ to: e.target.value })} />
      </div>
      <div className="row-wrap" style={{ gap: "0.4rem", marginBottom: "1rem" }}>
        <select className="select" style={{ width: "auto" }} aria-label="Outcome"
                value={filters.outcome} onChange={(e) => change({ outcome: e.target.value })}>
          <option value="">Every outcome</option>
          {OUTCOMES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <select className="select" style={{ width: "auto" }} aria-label="Office"
                value={filters.office} onChange={(e) => change({ office: e.target.value })}>
          <option value="">Every office</option>
          {(data?.options?.offices || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className="select" style={{ width: "auto" }} aria-label="Series"
                value={filters.series} onChange={(e) => change({ series: e.target.value })}>
          <option value="">Every series</option>
          {(data?.options?.series || []).map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
        </select>
        <input className="input" type="search" aria-label="DCR number" placeholder="DCR number"
               style={{ width: "10rem" }} value={filters.dcr} onChange={(e) => change({ dcr: e.target.value })} />
        {filtered && <button type="button" className="btn btn-ghost btn-sm"
                             onClick={() => change({ ...NO_FILTERS, view: filters.view })}>Clear</button>}
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.years.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">{filtered ? "Nothing matches these filters" : "Nothing closed yet"}</p>
        </div>
      ) : data.years.map((y) => (
        <details key={`${y.year}-${JSON.stringify(params)}`} className="history-year" open={y.year === thisYear}>
          <summary>
            <strong>{y.year}</strong> <span className="tab-count">{y.total}</span>
            <span className="subtle text-xs"> {outcomeLine(y.outcomes)}</span>
          </summary>
          {y.months.map((m) => (
            <Month key={m.month} year={y.year} month={m} params={params} onOpen={onOpen} />
          ))}
        </details>
      ))}
    </div>
  );
}

function Month({ year, month, params, onOpen }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="board-section history-month">
      <button type="button" className="board-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="board-toggle">{open ? "▾" : "▸"}</span>
        <span className="board-title">{MONTHS[month.month - 1]}</span>
        <span className="tab-count">{month.total}</span>
        <span className="subtle text-xs">{outcomeLine(month.outcomes)}</span>
      </button>
      {open && <MonthRows year={year} month={month.month} params={params} onOpen={onOpen} />}
    </section>
  );
}

function MonthRows({ year, month, params, onOpen }) {
  const [page, setPage] = useState(1);
  const { data } = useServerData("/api/history/", { ...params, year, month, page });
  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  const day = (v) => (v ? new Date(v).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" }) : "—");
  return (
    <div className="table-wrap" style={{ marginBottom: "0.75rem" }}>
      <table className="table">
        <thead><tr><th>Outcome</th><th>Manual</th><th>Office</th><th>Opened → closed</th><th>Days open · returned</th></tr></thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={r.proposal_id ? `p${r.proposal_id}` : `r${i}`}>
              <td><span className={`status-mark is-${r.outcome === "effective" ? "approved" : r.outcome === "denied" ? "returned" : "pending"}`}>{r.outcome_label}</span>
                {r.dcr_number && <div className="subtle text-xs">{r.dcr_number}</div>}</td>
              <td>
                {r.proposal_id
                  ? <button type="button" className="link-btn" onClick={() => onOpen?.(r.proposal_id)}>{r.manual}</button>
                  : r.manual}
                {r.sections > 0 && <div className="subtle text-xs">{r.sections} section{r.sections === 1 ? "" : "s"}</div>}
              </td>
              <td>{r.office}</td>
              <td className="text-sm">{day(r.opened)} → {day(r.closed)}</td>
              <td className="text-sm">{r.kind === "request" ? `${r.days_open} days · ${r.times_returned} returned` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.pages > 1 && (
        <div className="pager">
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
