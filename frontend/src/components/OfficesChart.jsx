import { useState } from "react";
import useServerData from "./useServerData";

const TOP = 15;
const PERIODS = [["month", "This month"], ["year", "This year"], ["last_year", "Last year"]];
const STAGE_WORDS = {
  drafting: "Drafting", with_head: "With the Head", in_concurrence: "In concurrence",
  returned: "Returned", awaiting_signatures: "Awaiting signatures", with_qms: "With QMS",
};

/**
 * Offices bar chart (spec §7.6): one bar per office in the viewer's scope,
 * highest first, the value printed on each. Pending counts open requests
 * by the office that made them; Approved, changes made effective in the
 * period. Top 15, then "Show more"; offices with none are one line.
 * A click on a bar hands the office and the mode back.
 */
export default function OfficesChart({ onOpen, title = "Offices" }) {
  const [mode, setMode] = useState("pending");
  const [period, setPeriod] = useState("month");
  const [all, setAll] = useState(false);
  const { data, error } = useServerData("/api/monitoring/offices-chart/",
                                        mode === "approved" ? { mode, period } : { mode },
                                        "Could not load the chart.");
  const bars = data?.bars || [];
  const shown = all ? bars : bars.slice(0, TOP);
  const top = bars[0]?.value || 1;

  return (
    <section className="monitor-section">
      <div className="row-wrap" style={{ gap: "0.75rem", alignItems: "center", marginBottom: "0.6rem" }}>
        <h2 className="section-title" style={{ margin: 0 }}>{title}</h2>
        <div className="segmented" role="group" aria-label="Pending or approved">
          {[["pending", "Pending"], ["approved", "Approved"]].map(([value, label]) => (
            <button key={value} type="button" aria-pressed={mode === value}
                    className={`segmented-item${mode === value ? " is-active" : ""}`}
                    onClick={() => { setMode(value); setAll(false); }}>{label}</button>
          ))}
        </div>
        {mode === "approved" && (
          <select className="select" style={{ width: "auto" }} aria-label="Period"
                  value={period} onChange={(e) => { setPeriod(e.target.value); setAll(false); }}>
            {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        )}
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : bars.length === 0 ? (
        <p className="subtle text-sm">
          {mode === "pending" ? "No open requests." : "Nothing made effective in this period."}
        </p>
      ) : (
        <>
          <div className="monitor-bars">
            {shown.map((bar) => (
              <button key={bar.office_id} type="button" className="monitor-bar"
                      onClick={() => onOpen?.(bar, mode)}
                      title={Object.entries(bar.stages).filter(([, n]) => n)
                        .map(([b, n]) => `${STAGE_WORDS[b]}: ${n}`).join(" · ") || undefined}>
                <span className="monitor-bar-label">{bar.office}</span>
                <span className="monitor-bar-track">
                  <span className="monitor-bar-fill" style={{ width: `${Math.max(3, (bar.value / top) * 100)}%` }} />
                </span>
                <span className="monitor-bar-value">{bar.value}</span>
              </button>
            ))}
          </div>
          <p className="subtle text-xs" style={{ margin: "0.5rem 0 0" }}>
            {bars.length > TOP && (
              <button type="button" className="link-btn text-xs" onClick={() => setAll(!all)}>
                {all ? "Show the top 15" : `Show more (${bars.length - TOP} offices)`}
              </button>
            )}
            {bars.length > TOP && data.none > 0 && " · "}
            {data.none > 0 && `${mode === "pending" ? "No open requests" : "None made effective"} · ${data.none} offices`}
          </p>
        </>
      )}
    </section>
  );
}
