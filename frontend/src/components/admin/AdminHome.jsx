import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { STATUS_LABEL, statusTone } from "../proposalStatus";
import Icon from "../Icon";
import NeedsAction from "../NeedsAction";
import DeadlineTag from "../DeadlineTag";
import OfficesChart from "../OfficesChart";

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

/**
 * The admin landing page: what is waiting, and whether the queue is moving.
 *
 * One request for every area. They read the same few tables, and the
 * first screen after signing in is the worst one to make slow.
 */
export default function AdminHome({ onGo, onOpenProposal, onOpenOffice }) {
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

  const { attention, proposals, upcoming,
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
        <button className="btn btn-ghost btn-sm" onClick={load}><Icon name="refresh" />Refresh</button>
      </header>

      <NeedsAction onGo={onGo} onOpenProposal={onOpenProposal} />

      <Attention counts={attention} onGo={onGo} />

      <div className="dash-grid" style={{ marginTop: "1.75rem" }}>
        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <OfficesChart title="Proposals by office"
                        onOpen={(bar, mode) => onOpenOffice?.(bar.office_id, mode)} />
          <RecentProposals rows={proposals} onGo={onGo} />
        </div>

        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <Upcoming rows={upcoming} total={upcomingTotal} onGo={onGo} />
          <SystemState system={system} onGo={onGo} />
        </div>
      </div>
    </div>
  );
}

/* ── 1. In progress ─────────────────────────────────────────────────── */

/** Where the work stands. What the admin must act on - sign-ups, vacant
 *  posts - is in Needs your action above, so this only describes. Zero
 *  rows are left out: a row of zeroes is a wall you learn to skip. */
function Attention({ counts, onGo }) {
  const rows = [
    counts.proposals_in_concurrence > 0 && {
      key: "concurrence",
      value: counts.proposals_in_concurrence,
      label: plural(counts.proposals_in_concurrence, "proposal") + " out for concurrence",
      note: "waiting on the offices that must agree",
      tone: "",
      go: "proposals",
    },
    counts.proposals_locked > 0 && {
      key: "locked",
      value: counts.proposals_locked,
      label: plural(counts.proposals_locked, "proposal") + " agreed and locked",
      note: "waiting for signing and the custodian",
      tone: "is-warning",
      go: "proposals",
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
          No proposals in progress.
        </p>
      </div>
    );
  }

  return (
    <section>
      <h2 className="section-title">In progress</h2>
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

/* ── 2. Recent proposals ───────────────────────────────────────────── */

function RecentProposals({ rows, onGo }) {
  if (!rows || rows.length === 0) return null;
  return (
    <section className="admin-dashboard-section">
      <h2 className="section-title">Recent proposals</h2>
      <div className="col" style={{ gap: "0.15rem" }}>
        {rows.map((row) => (
          <button key={row.id} className="decision-row" onClick={() => onGo("proposals")}>
            <span className={`status-mark is-${statusTone(row.status)}`}>
              {STATUS_LABEL[row.status] || row.status_label}
            </span>
            <span className="decision-what">
              <span className="doc-ref">{row.manual}</span>
              <span className="subtle text-xs"> · from {row.office}</span>
              {row.deadline && <> <DeadlineTag tag={row.deadline} /></>}
            </span>
            <span className="subtle text-xs decision-who">
              {row.of > 0 ? `${row.concurred} of ${row.of} concurred` : ""}
            </span>
            <span className="subtle text-xs decision-when">{timeAgo(row.updated_at)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

/* ── 3. Upcoming ────────────────────────────────────────────────────── */

/** The same list the staff dashboard shows, except unfiltered: this is the
 *  desk the notices are posted from, so every office's are visible. */
function Upcoming({ rows, total, onGo }) {
  return (
    <section className="admin-dashboard-section">
      <h2 className="section-title">Next deadlines</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          None set.{" "}
          <button className="link-btn" onClick={() => onGo("announcements")}>
            Set a deadline
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
                <div className="subtle text-xs">{row.type} · {row.unmet}</div>
              </div>
            </div>
          ))}
          {total > rows.length && (
            <button className="link-btn text-xs" onClick={() => onGo("announcements")}>
              {total - rows.length} more
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/* ── 4. System state ────────────────────────────────────────────────── */

/** What is in the system. Plain figures, because none of these change often
 *  enough for a chart to say anything a number does not. */
function SystemState({ system, onGo }) {
  return (
    <section className="admin-dashboard-section">
      <h2 className="section-title">System</h2>
      <div className="col" style={{ gap: "0.45rem" }}>
        <Figure value={system.manuals} label="manuals" onGo={() => onGo("manuals")}
                note={`${system.sections} sections`} />
        <Figure value={system.offices} label="offices" onGo={() => onGo("offices")} />
        <Figure value={system.staff} label="approved staff" onGo={() => onGo("users")}
                note={`${plural(system.admins, "admin")}`} />
        <Figure value={system.proposals_total} label="proposals all time"
                onGo={() => onGo("proposals")} />
      </div>

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
