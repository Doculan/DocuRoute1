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

/**
 * The landing page: what needs doing, and a way back to what you were reading.
 *
 * One request for the whole thing. Six widgets reading the same few tables do
 * not need six round trips, and the landing page is the worst place to be
 * slow.
 */
export default function StaffHome({ onGo, onOpenSection, onOpenManual }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await axios.get(`${BASE_URL}/api/staff/dashboard/`, getAuth());
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load your dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const dismiss = async (id) => {
    setData((d) => ({ ...d, announcement: null }));
    try {
      await axios.post(
        `${BASE_URL}/api/staff/announcements/${id}/dismiss/`, {}, getAuth()
      );
    } catch {
      // Closing a banner is not worth an error if the note does not stick.
    }
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading your dashboard…</div>;
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

  const { proposals_awaiting: awaiting, proposals_mine: proposalsMine,
          recently_opened: recent, announcement,
          upcoming, upcoming_total: upcomingTotal, stats } = data;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            A way back to what you were reading, and anything waiting for you.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>↻ Refresh</button>
      </header>

      {announcement && (
        <div className="alert alert-warning" style={{ marginBottom: "1.5rem" }}>
          <div className="row" style={{ justifyContent: "space-between", gap: "1rem", alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <div className="doc-name" style={{ fontSize: "1rem" }}>{announcement.title}</div>
              {announcement.body && (
                <p className="doc-excerpt" style={{ marginTop: "0.25rem" }}>{announcement.body}</p>
              )}
            </div>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => dismiss(announcement.id)}
              aria-label="Dismiss this announcement"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="dash-grid">
        <div className="col" style={{ gap: "1.5rem", minWidth: 0 }}>
          <Attention awaiting={awaiting} onGo={onGo} />
          <RecentlyOpened
            rows={recent}
            onOpenSection={onOpenSection}
            onOpenManual={onOpenManual}
          />
        </div>

        <div className="col" style={{ gap: "1.5rem", minWidth: 0 }}>
          <Upcoming rows={upcoming} total={upcomingTotal} />
          <AtAGlance stats={stats} proposalsMine={proposalsMine} />
        </div>
      </div>
    </div>
  );
}

/** The one widget that is about doing something: proposals waiting for
 *  your office to decide. Not shown at all when nothing is. */
function Attention({ awaiting, onGo }) {
  if (!awaiting) return null;
  return (
    <section>
      <h2 className="section-title">Needs your attention</h2>
      <button
        className="card card-pad card-interactive row"
        style={{ gap: "0.75rem", alignItems: "center", textAlign: "left", width: "100%" }}
        onClick={() => onGo("proposals")}
      >
        <span className="badge badge-warning">•</span>
        <span className="text-sm">
          {awaiting} proposal{awaiting === 1 ? "" : "s"} waiting for your office to decide
        </span>
      </button>
    </section>
  );
}

/** A list, not a month grid: most weeks hold nothing, and a grid would be
 *  mostly empty boxes. A list works with zero items and becomes a calendar
 *  later without changing the data. */
function Upcoming({ rows, total }) {
  return (
    <section>
      <h2 className="section-title">Upcoming</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing scheduled. Announcements from the admin will appear here.
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
                {row.body && <div className="doc-excerpt">{row.body}</div>}
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

function RecentlyOpened({ rows, onOpenSection, onOpenManual }) {
  return (
    <section>
      <h2 className="section-title">Recently opened</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing yet. Manuals and sections you open will be listed here so you
          can get back to them.
        </p>
      ) : (
        <div className="col" style={{ gap: "0.35rem" }}>
          {rows.map((row) => (
            <button
              key={`${row.manual_id}-${row.section_id ?? "m"}`}
              className="link-btn"
              style={{ textAlign: "left" }}
              onClick={() => (row.section_id
                ? onOpenSection(row.manual_id, row.section_id)
                : onOpenManual(row.manual_id))}
            >
              <span className="doc-ref">{row.section || row.manual}</span>
              {row.section && <span className="subtle text-xs"> · {row.manual}</span>}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** Plain figures. A chart of 19 documents is decoration; one would only earn
 *  its place for something changing over time, and there is not enough
 *  history yet. */
function AtAGlance({ stats, proposalsMine }) {
  return (
    <section>
      <h2 className="section-title">At a glance</h2>
      <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
        <strong style={{ fontVariantNumeric: "tabular-nums" }}>{stats.manuals_total}</strong> manuals
        {" · "}
        <strong style={{ fontVariantNumeric: "tabular-nums" }}>{stats.manuals_mine}</strong>
        {" linked to your offices"}
        {proposalsMine > 0 && (
          <>
            {" · "}
            <strong style={{ fontVariantNumeric: "tabular-nums" }}>{proposalsMine}</strong>
            {" proposal"}{proposalsMine === 1 ? "" : "s"} from your offices
          </>
        )}
      </p>
    </section>
  );
}
