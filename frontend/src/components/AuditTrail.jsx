import { useMemo, useState } from "react";
import axios from "axios";
import useServerData from "./useServerData";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function when(value) {
  return value ? new Date(value).toLocaleString("en-PH", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }) : "";
}

/**
 * The audit block (spec §10, no hash chain): a summary, then the timeline
 * grouped by version - the current version open, earlier ones folded.
 * Position first with the person's full name; feedback, notes and reasons
 * verbatim; the AI checks from their stored results. Filters narrow the
 * timeline and the export alike.
 */
export default function AuditTrail({ proposalId }) {
  const { data, error } = useServerData(`/api/proposals/${proposalId}/trail/`, null,
                                        "Could not load the audit trail.");
  const [filters, setFilters] = useState({ action: "", office: "", version: "", from: "", to: "" });
  const [message, setMessage] = useState("");

  const all = useMemo(() => (data?.versions || []).flatMap((v) => v.items), [data]);
  const actions = useMemo(() => [...new Map(all.map((i) => [i.event, i.label])).entries()], [all]);
  const offices = useMemo(() => [...new Set(all.map((i) => i.office))].sort(), [all]);
  const set = (key) => (e) => setFilters({ ...filters, [key]: e.target.value });
  const keep = (i, version) => {
    const day = new Date(i.at).toLocaleDateString("en-CA");
    return (!filters.action || i.event === filters.action)
      && (!filters.office || i.office === filters.office)
      && (!filters.version || String(version) === filters.version)
      && (!filters.from || day >= filters.from) && (!filters.to || day <= filters.to);
  };
  const filtered = Object.values(filters).some(Boolean);

  const exportAs = async (format, reason = "") => {
    setMessage("");
    try {
      const res = await axios.post(`/api/proposals/${proposalId}/trail/export/`,
        { format, reason, filters }, { ...getAuth(), responseType: "blob" });
      const name = (res.headers["content-disposition"] || "").match(/filename="(.+)"/)?.[1]
        || `audit-trail.${format}`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      URL.revokeObjectURL(url);
      setMessage(`Exported, serial ${res.headers["x-report-serial"]}.`);
    } catch (err) {
      const body = err.response?.data instanceof Blob
        ? JSON.parse(await err.response.data.text()) : err.response?.data;
      if (body?.reason === "reason_required") {
        const given = window.prompt("Say why you are exporting this. It is recorded with the export.");
        if (given) exportAs(format, given);
        return;
      }
      setMessage(body?.error || "The export did not work.");
    }
  };

  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!data) return <div className="loading-row"><span className="spinner" /> Loading the audit trail…</div>;
  const s = data.summary;
  const latest = data.versions[data.versions.length - 1]?.number;

  return (
    <section className="audit-trail" style={{ marginTop: "1.75rem" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h2 className="section-title" style={{ margin: 0 }}>Audit trail</h2>
        <div className="row" style={{ gap: "0.4rem" }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => exportAs("csv")}>Export CSV</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => exportAs("pdf")}>Export PDF</button>
        </div>
      </div>
      {message && <p className="subtle text-xs" style={{ margin: "0.4rem 0 0" }}>{message}</p>}

      <dl className="audit-summary">
        <div><dt>Started by</dt><dd>{s.initiated_by.position}{s.initiated_by.name && ` · ${s.initiated_by.name}`}
          <span className="subtle"> · {when(s.initiated_at)}</span></dd></div>
        <div><dt>Stage</dt><dd>{s.stage}{s.holder && <span className="subtle"> · {s.holder.waiting_on}, {s.holder.days} days</span>}</dd></div>
        <div><dt>Days open</dt><dd>{s.days_open}{s.closed_at && <span className="subtle"> · closed {when(s.closed_at)}</span>}</dd></div>
        <div><dt>Versions</dt><dd>{s.versions}</dd></div>
        <div><dt>Returned</dt><dd>{s.times_returned
          ? `${s.times_returned} · ${s.returned_by.map((r) => r.by).join(", ")}` : "never"}</dd></div>
        {s.due && <div><dt>Deadline</dt><dd>{s.due.title}
          <span className="subtle"> · {s.due.type} · due {s.due.due_on}</span></dd></div>}
      </dl>

      <div className="row-wrap" style={{ gap: "0.4rem", margin: "0.9rem 0 0.6rem" }}>
        <select className="select" style={{ width: "auto" }} aria-label="Step" value={filters.action} onChange={set("action")}>
          <option value="">Every step</option>
          {actions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select className="select" style={{ width: "auto" }} aria-label="Office" value={filters.office} onChange={set("office")}>
          <option value="">Every office</option>
          {offices.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {data.versions.length > 1 && (
          <select className="select" style={{ width: "auto" }} aria-label="Version" value={filters.version} onChange={set("version")}>
            <option value="">Every version</option>
            {data.versions.map((v) => <option key={v.number} value={String(v.number)}>Version {v.number}</option>)}
          </select>
        )}
        <input className="input" type="date" aria-label="From" style={{ width: "auto" }} value={filters.from} onChange={set("from")} />
        <input className="input" type="date" aria-label="To" style={{ width: "auto" }} value={filters.to} onChange={set("to")} />
        {filtered && <button type="button" className="btn btn-ghost btn-sm"
                             onClick={() => setFilters({ action: "", office: "", version: "", from: "", to: "" })}>Clear</button>}
      </div>

      {data.versions.map((v) => {
        const items = v.items.filter((i) => keep(i, v.number));
        if (filtered && items.length === 0) return null;
        return (
          <details key={v.number} className="audit-version" open={filtered || v.number === latest}>
            <summary>
              <strong>Version {v.number}</strong>
              <span className="subtle text-xs"> · {items.length} steps{v.submitted_at ? ` · submitted ${when(v.submitted_at)}` : ""}</span>
            </summary>
            <ol className="audit-steps">
              {items.map((i, n) => (
                <li key={n} className={i.kind === "ai_check" ? "is-check" : ""}>
                  <div className="audit-step-head">
                    <span className="audit-step-label">{i.label}</span>
                    <span className="text-sm">{i.by.position}{i.by.name && ` · ${i.by.name}`}</span>
                    <span className="subtle text-xs">{when(i.at)}</span>
                  </div>
                  {i.to && (
                    <div className="subtle text-xs">
                      {i.from ? `${i.from} → ${i.to}` : i.to}
                      {i.time_in_previous && ` · after ${i.time_in_previous} ${i.from ? `in ${i.from}` : ""}`}
                    </div>
                  )}
                  {i.detail && <div className="audit-detail">{i.detail}</div>}
                </li>
              ))}
            </ol>
          </details>
        );
      })}
      <p className="subtle text-xs" style={{ marginTop: "0.6rem" }}>
        Section edits are not listed; each AI check is shown from its stored result.
      </p>
    </section>
  );
}
