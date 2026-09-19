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

/**
 * The landing page: what needs doing, and a way back to what you were reading.
 *
 * One request for the whole thing. Six widgets reading the same few tables do
 * not need six round trips, and the landing page is the worst place to be
 * slow.
 */
export default function StaffHome({ onGo, onOpenSection, onOpenManual, onOpenRevision }) {
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

  const { attention, activity, recently_opened: recent, announcement,
          upcoming, upcoming_total: upcomingTotal, stats } = data;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            What needs your attention, and a way back to what you were reading.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>↻ Refresh</button>
      </header>

      {announcement && (
        <div className="alert alert-warning" style={{ marginBottom: "1.5rem" }}>
          <div className="row" style={{ justifyContent: "space-between", gap: "1rem", alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <div className="strong">{announcement.title}</div>
              {announcement.body && (
                <p className="text-sm" style={{ margin: "0.25rem 0 0" }}>{announcement.body}</p>
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
          <Attention counts={attention} onGo={onGo} />
          <Activity rows={activity} onOpenRevision={onOpenRevision} />
        </div>

        <div className="col" style={{ gap: "1.5rem", minWidth: 0 }}>
          <Upcoming rows={upcoming} total={upcomingTotal} />
          <RecentlyOpened
            rows={recent}
            onOpenSection={onOpenSection}
            onOpenManual={onOpenManual}
          />
          <AtAGlance stats={stats} />
        </div>
      </div>
    </div>
  );
}

/** The one widget that is about doing something, so it leads and only ever
 *  shows rows that are not zero. A wall of zeroes is noise. */
function Attention({ counts, onGo }) {
  const rows = [
    counts.awaiting_review > 0 && {
      key: "awaiting",
      text: `${counts.awaiting_review} revision${counts.awaiting_review === 1 ? "" : "s"} awaiting review`,
      tone: "badge-warning",
    },
    counts.new_feedback > 0 && {
      key: "feedback",
      text: `${counts.new_feedback} with feedback you have not read`,
      tone: "badge-info",
    },
    counts.returned > 0 && {
      key: "returned",
      text: `${counts.returned} returned for changes`,
      tone: "badge-danger",
    },
  ].filter(Boolean);

  return (
    <section>
      <h2 className="section-title">Needs your attention</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing needs your attention right now.
        </p>
      ) : (
        <div className="col" style={{ gap: "0.5rem" }}>
          {rows.map((row) => (
            <button
              key={row.key}
              className="card card-pad card-interactive row"
              style={{ gap: "0.75rem", alignItems: "center", textAlign: "left", width: "100%" }}
              onClick={() => onGo("revisions")}
            >
              <span className={`badge ${row.tone}`}>•</span>
              <span className="text-sm">{row.text}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** News about your submissions — distinct from Recently opened, which is
 *  navigation. */
function Activity({ rows, onOpenRevision }) {
  return (
    <section>
      <h2 className="section-title">Recent activity</h2>
      {rows.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Nothing has happened to your submissions yet. Decisions will show up here.
        </p>
      ) : (
        <div className="col" style={{ gap: "0.4rem" }}>
          {rows.map((row) => (
            <button
              key={row.revision_id}
              className="row-wrap"
              style={{
                gap: "0.4rem", alignItems: "baseline", textAlign: "left",
                background: "none", border: "none", padding: "0.35rem 0", width: "100%",
              }}
              onClick={() => onOpenRevision(row.revision_id)}
            >
              <span className="text-sm">
                Your revision to <strong>{row.manual}</strong> {row.section} was{" "}
                {row.returned ? "returned for changes" : row.status}
              </span>
              <span className="subtle text-xs">— {timeAgo(row.at)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** A list, not a month grid. There is no automatic date source - effectivity
 *  dates are not stored as dates and approving a revision does not set one -
 *  so a grid would be mostly empty boxes. A list works with zero items and
 *  becomes a calendar later without changing the data. */
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
                <div className="text-sm strong">{row.title}</div>
                {row.body && (
                  <div className="subtle text-xs">{row.body}</div>
                )}
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
              <span className="text-sm">{row.section || row.manual}</span>
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
function AtAGlance({ stats }) {
  return (
    <section>
      <h2 className="section-title">At a glance</h2>
      <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
        <strong style={{ fontVariantNumeric: "tabular-nums" }}>{stats.manuals_total}</strong> manuals
        {stats.department && (
          <>
            {" · "}
            <strong style={{ fontVariantNumeric: "tabular-nums" }}>{stats.manuals_mine}</strong>
            {" in "}{stats.department}
          </>
        )}
        {" · "}
        <strong style={{ fontVariantNumeric: "tabular-nums" }}>{stats.revisions_mine}</strong>
        {" revision"}{stats.revisions_mine === 1 ? "" : "s"} submitted by you
      </p>
    </section>
  );
}
