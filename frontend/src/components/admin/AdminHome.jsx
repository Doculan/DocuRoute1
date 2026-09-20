import { useCallback, useEffect, useState } from "react";
import axios from "axios";

// Relative, so the browser sends it to whichever host served the page and
// Vite's proxy forwards it. See StaffManuals for the full reasoning.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function formatDay(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-PH", {
    month: "short", day: "numeric",
  });
}

function timeAgo(value) {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.round(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Read back as English rather than as a stored value. "needs_revision" is a
// field name, and showing it to a reviewer makes the assessment sound like
// a system talking about itself.
const VERDICT_WORDS = {
  approve: "approve",
  needs_revision: "needs revision",
  reject: "reject",
};

/**
 * The admin landing page: what is waiting, and whether the queue is moving.
 *
 * One request for all six areas. They read the same few tables, and the
 * first screen after signing in is the worst one to make slow.
 *
 * Nothing here recomputes an assessment. The verdicts shown beside recent
 * decisions are the ones stored when the revision was submitted, which are
 * the ones the reviewer actually saw.
 */
export default function AdminHome({ onGo, onOpenRevision }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await axios.get(`${BASE_URL}/api/admin/dashboard/`, getAuth());
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load the dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading the dashboard…</div>;
  }
  if (error) {
    return (
      <div>
        <header className="page-head">
          <h1 className="page-title">Dashboard</h1>
        </header>
        <div className="alert alert-danger">{error}</div>
      </div>
    );
  }

  const { attention, activity, departments, decisions, upcoming,
          upcoming_total: upcomingTotal, system } = data;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            What is waiting for you, and whether the queue is moving.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>↻ Refresh</button>
      </header>

      <Attention counts={attention} onGo={onGo} />

      <div className="dash-grid" style={{ marginTop: "1.75rem" }}>
        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <Activity activity={activity} />
          <ByDepartment rows={departments} onGo={onGo} />
          <Decisions rows={decisions} onOpenRevision={onOpenRevision} />
        </div>

        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <Upcoming rows={upcoming} total={upcomingTotal} onGo={onGo} />
          <SystemState system={system} onGo={onGo} />
        </div>
      </div>
    </div>
  );
}

/* ── 1. Needs attention ─────────────────────────────────────────────── */

/** The only part of the page that asks you to do something, so it runs full
 *  width above everything else and shows nothing at all when there is
 *  nothing to do. A row of zeroes would be a wall you learn to skip. */
function Attention({ counts, onGo }) {
  const waited = counts.oldest_pending_days;
  const rows = [
    counts.pending_revisions > 0 && {
      key: "revisions",
      value: counts.pending_revisions,
      label: plural(counts.pending_revisions, "revision") + " awaiting review",
      // Only mentioned once it is old enough to be a fact about the queue
      // rather than about today.
      note: waited != null && waited >= 2
        ? `oldest has waited ${plural(waited, "day")}` : null,
      tone: "is-warning",
      go: "review",
    },
    counts.pending_users > 0 && {
      key: "users",
      value: counts.pending_users,
      label: plural(counts.pending_users, "account") + " awaiting approval",
      note: "they cannot sign in until approved",
      tone: "",
      go: "users",
    },
    counts.stale_assessments > 0 && {
      key: "stale",
      value: counts.stale_assessments,
      label: "with a section edited since assessment",
      note: "the advice on those describes older text",
      tone: "is-danger",
      go: "review",
    },
    counts.untagged_sections > 0 && {
      key: "untagged",
      value: counts.untagged_sections,
      label: plural(counts.untagged_sections, "section") + " untagged",
      note: "they still read and search normally",
      tone: "",
      go: "sections",
    },
  ].filter(Boolean);

  if (rows.length === 0) {
    return (
      <div className="card card-pad">
        <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
          Nothing is waiting. No revisions to review, no accounts to approve.
        </p>
      </div>
    );
  }

  return (
    <section>
      <h2 className="section-title">Needs your attention</h2>
      <div className="stat-grid">
        {rows.map((row) => (
          <button
            key={row.key}
            className={`stat-card ${row.tone}`}
            onClick={() => onGo(row.go)}
          >
            <div className="stat-value">{row.value}</div>
            <div className="stat-label">{row.label}</div>
            {row.note && (
              <div className="subtle text-xs" style={{ marginTop: "0.3rem" }}>
                {row.note}
              </div>
            )}
          </button>
        ))}
      </div>
    </section>
  );
}

/* ── 2. Activity over time ──────────────────────────────────────────── */

/** Submissions and decisions over the last month.
 *
 *  The backend decides whether there is enough history for a line, and this
 *  follows it. Drawing four points spread over a month as a trend line
 *  invites the reader to see a slope that is really the gaps between
 *  submissions; the table says exactly the same numbers and claims nothing
 *  about the shape.
 */
function Activity({ activity }) {
  const { days, enough_for_chart: enough, totals, window_days: window,
          active_days: activeDays, minimum_days: minimum } = activity;

  const summary = (
    <p className="subtle text-xs" style={{ margin: "0 0 0.75rem" }}>
      Last {window} days · {totals.submitted} submitted ·{" "}
      {totals.approved} approved · {totals.rejected} returned
    </p>
  );

  return (
    <section>
      <h2 className="section-title">Activity</h2>
      {summary}
      {totals.submitted + totals.approved + totals.rejected === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing has been submitted or decided in the last {window} days.
        </p>
      ) : enough ? (
        <ActivityChart days={days} />
      ) : (
        <ActivityTable days={days} activeDays={activeDays} minimum={minimum} />
      )}
    </section>
  );
}

/** Hand-drawn SVG rather than a charting library: three series over thirty
 *  points does not justify 200kB and a second set of theme rules. */
function ActivityChart({ days }) {
  const W = 620, H = 160, PAD_L = 28, PAD_R = 24, PAD_T = 12, PAD_B = 26;
  const peak = Math.max(1, ...days.map((d) =>
    Math.max(d.submitted, d.approved + d.rejected)));
  // A whole number of rows, so every gridline lands on a count that exists.
  const top = peak <= 4 ? peak : Math.ceil(peak / 4) * 4;
  const step = (W - PAD_L - PAD_R) / Math.max(1, days.length - 1);
  const y = (v) => PAD_T + (H - PAD_T - PAD_B) * (1 - v / top);
  const x = (i) => PAD_L + i * step;

  const line = (key) => days.map((d, i) =>
    `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join(" ");

  // Submitted is drawn as a filled area, not a third line. Three lines of
  // the same weight read as one tangle where they cross, and at the zero
  // baseline - which is most of a quiet fortnight - they overlap exactly,
  // so the only series visible is whichever was drawn last. A fill differs
  // in *form*, which survives both the overlap and a greyscale printout.
  const area = `${line("submitted")} L${x(days.length - 1).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`;

  const ticks = top <= 4
    ? Array.from({ length: top + 1 }, (_, i) => i)
    : [0, top / 4, top / 2, (top * 3) / 4, top];

  const labelEvery = Math.ceil(days.length / 6);

  return (
    <div className="chart-frame">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img"
           aria-label={`Revisions submitted and decided over the last ${days.length} days`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD_L - 6} y={y(t) + 3.5} className="chart-tick" textAnchor="end">{t}</text>
          </g>
        ))}

        {days.map((d, i) => (i % labelEvery === 0 || i === days.length - 1) && (
          <text key={d.date} x={x(i)} y={H - 8} className="chart-tick" textAnchor="middle">
            {formatDay(d.date)}
          </text>
        ))}

        <path d={area} className="chart-area" />
        <path d={line("submitted")} className="chart-line is-submitted" />
        <path d={line("approved")} className="chart-line is-approved" />
        <path d={line("rejected")} className="chart-line is-rejected" />

        {/* Single days show as dots; a lone point on a line is invisible. */}
        {days.map((d, i) => d.submitted > 0 && (
          <circle key={`s${d.date}`} cx={x(i)} cy={y(d.submitted)} r="2.6"
                  className="chart-dot is-submitted" />
        ))}
      </svg>

      <div className="chart-legend">
        <span className="chart-key is-submitted">Submitted</span>
        <span className="chart-key is-approved">Approved</span>
        <span className="chart-key is-rejected">Returned</span>
      </div>
    </div>
  );
}

/** The same numbers, with the empty days dropped — those are what make the
 *  line misleading, and in a table they are simply absent. */
function ActivityTable({ days, activeDays, minimum }) {
  const rows = days.filter((d) => d.submitted || d.approved || d.rejected)
                   .slice().reverse();
  return (
    <div>
      <p className="subtle text-xs" style={{ margin: "0 0 0.6rem" }}>
        Shown as a table: {plural(activeDays, "day")} with activity, and a line
        needs {minimum} before its shape means anything.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Day</th>
              <th style={{ textAlign: "right" }}>Submitted</th>
              <th style={{ textAlign: "right" }}>Approved</th>
              <th style={{ textAlign: "right" }}>Returned</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.date}>
                <td className="table-strong">{formatDay(d.date)}</td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{d.submitted || "—"}</td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{d.approved || "—"}</td>
                <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{d.rejected || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── 3. Revisions by department ─────────────────────────────────────── */

/** Where the work is coming from. A bar rather than a number because the
 *  comparison between departments is the whole point, and departments with
 *  nothing pending are still listed — an empty row is information. */
function ByDepartment({ rows, onGo }) {
  if (rows.length === 0) {
    return (
      <section>
        <h2 className="section-title">By department</h2>
        <p className="subtle text-sm" style={{ margin: 0 }}>
          No revisions have been submitted yet.
        </p>
      </section>
    );
  }

  const widest = Math.max(...rows.map((r) => r.total));

  return (
    <section>
      <h2 className="section-title">By department</h2>
      <div className="col" style={{ gap: "0.7rem" }}>
        {rows.map((row) => (
          <button
            key={row.department}
            className="dept-row"
            onClick={() => onGo("review")}
            title={`${row.pending} pending, ${row.approved} approved, ${row.rejected} returned`}
          >
            <span className="dept-name">{row.department}</span>
            <span className="dept-bar" aria-hidden="true">
              {["pending", "approved", "rejected"].map((key) => row[key] > 0 && (
                <span
                  key={key}
                  className={`dept-seg is-${key}`}
                  style={{ width: `${(row[key] / widest) * 100}%` }}
                />
              ))}
            </span>
            <span className="dept-count">
              {row.pending > 0
                ? <><strong>{row.pending}</strong> pending</>
                : <span className="subtle">{plural(row.total, "revision")}</span>}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

/* ── 4. Recent decisions ────────────────────────────────────────────── */

/** What has been decided lately, and what the assessment had said where the
 *  two differ.
 *
 *  Worded as a fact about the assessment, never as a verdict on the person:
 *  "assessment said reject", not "overruled". The reviewer has context the
 *  pipeline does not and disagreeing is a normal part of the job - a label
 *  that scores them would make this screen something to be defensive about,
 *  and the only reason to show it at all is that a run of differences is
 *  worth a second look at the model, not at the reviewer. */
function Decisions({ rows, onOpenRevision }) {
  return (
    <section>
      <h2 className="section-title">Recent decisions</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing has been reviewed yet. Decisions will be listed here.
        </p>
      ) : (
        <div className="col" style={{ gap: "0.15rem" }}>
          {rows.map((row) => (
            <button
              key={row.revision_id}
              className="decision-row"
              onClick={() => onOpenRevision(row.revision_id, row.status)}
            >
              <span className={`status-mark is-${row.status === "rejected" ? "returned" : row.status}`}>
                {row.status === "rejected" ? "Returned" : "Approved"}
              </span>
              <span className="decision-what">
                <span className="doc-ref">{row.section}</span>
                <span className="subtle text-xs"> · {row.manual}</span>
              </span>
              <span className="subtle text-xs decision-who">
                {row.submitted_by}
                {row.agreed === false && (
                  <span
                    className="badge badge-neutral"
                    style={{ marginLeft: "0.4rem" }}
                    title="What the pre-check had said when this was submitted. The reviewer's decision stands."
                  >
                    assessment said {VERDICT_WORDS[row.ai_verdict] || row.ai_verdict}
                  </span>
                )}
              </span>
              <span className="subtle text-xs decision-when">{timeAgo(row.at)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── 5. Upcoming ────────────────────────────────────────────────────── */

/** The same list the staff dashboard shows, except unfiltered: this is the
 *  desk the notices are posted from, so every department's are visible. */
function Upcoming({ rows, total, onGo }) {
  return (
    <section>
      <h2 className="section-title">Upcoming</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing scheduled.{" "}
          <button className="link-btn" onClick={() => onGo("announcements")}>
            Post an announcement
          </button>
          .
        </p>
      ) : (
        <div className="col" style={{ gap: "0.55rem" }}>
          {rows.map((row) => (
            <div key={row.id} className="row" style={{ gap: "0.7rem", alignItems: "baseline" }}>
              <span
                className={`badge ${row.is_today ? "badge-warning" : "badge-neutral"}`}
                style={{ flexShrink: 0, fontVariantNumeric: "tabular-nums" }}
              >
                {row.is_today ? "today" : formatDay(row.date)}
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="doc-name" style={{ fontSize: "0.95rem" }}>{row.title}</div>
                <div className="subtle text-xs">
                  {row.department ? `${row.department} only` : "everyone"}
                </div>
              </div>
            </div>
          ))}
          {total > rows.length && (
            <span className="subtle text-xs">{total - rows.length} more scheduled</span>
          )}
        </div>
      )}
    </section>
  );
}

/* ── 6. System state ────────────────────────────────────────────────── */

/** What is in the system. Plain figures, because none of these change often
 *  enough for a chart to say anything a number does not. */
function SystemState({ system, onGo }) {
  const sources = system.assessment_sources;
  return (
    <section>
      <h2 className="section-title">System</h2>
      <div className="col" style={{ gap: "0.45rem" }}>
        <Figure value={system.manuals} label="manuals" onGo={() => onGo("manuals")}
                note={`${system.sections} sections`} />
        <Figure value={system.departments} label="departments" onGo={() => onGo("departments")}
                note={system.empty_departments > 0
                  ? `${system.empty_departments} with no manuals`
                  : null} />
        <Figure value={system.staff} label="approved staff" onGo={() => onGo("users")}
                note={`${plural(system.admins, "admin")}`} />
        <Figure value={system.revisions_total} label="revisions all time"
                onGo={() => onGo("review")} />
      </div>

      {sources.none > 0 && (
        <p className="subtle text-xs" style={{ marginTop: "0.9rem" }}>
          {plural(sources.none, "revision")} predate the submitter's pre-check
          and carry no stored assessment, so their review screens show less.
        </p>
      )}
      {system.banners_live > 0 && (
        <p className="subtle text-xs" style={{ marginTop: "0.5rem" }}>
          {plural(system.banners_live, "banner")} showing on the staff
          dashboard right now.
        </p>
      )}
    </section>
  );
}

function Figure({ value, label, note, onGo }) {
  return (
    <button className="figure-row" onClick={onGo}>
      <span className="figure-value">{value}</span>
      <span className="figure-label">
        {label}
        {note && <span className="subtle text-xs"> · {note}</span>}
      </span>
    </button>
  );
}
