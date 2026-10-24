import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import Icon from "../Icon";
import NeedsAction from "../NeedsAction";
import DeadlinesPage from "../DeadlinesPage";
import DeadlineTag from "../DeadlineTag";

// Relative, so the browser sends it to whichever host served the page and
// Vite's proxy forwards it. See StaffManuals for the full reasoning.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * The landing page: what needs doing, and a way back to what you were reading.
 *
 * One request for the whole thing. Six widgets reading the same few tables do
 * not need six round trips, and the landing page is the worst place to be
 * slow.
 */
export default function StaffHome({ onGo, onOpenSection, onOpenManual, onOpenProposal }) {
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

  const { proposals_mine: proposalsMine, recently_opened: recent, stats } = data;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            A way back to what you were reading, and anything waiting for you.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}><Icon name="refresh" />Refresh</button>
      </header>

      <NeedsAction onOpenProposal={onOpenProposal} onGo={onGo} />

      <div className="dash-grid">
        <div className="col" style={{ gap: "1.5rem", minWidth: 0 }}>
          <RecentlyOpened
            rows={recent}
            onOpenSection={onOpenSection}
            onOpenManual={onOpenManual}
          />
        </div>

        <div className="col" style={{ gap: "1.5rem", minWidth: 0 }}>
          <DeadlinesPage limit={5} onShowAll={() => onGo("deadlines")}
                         onOpenManual={onOpenManual} />
          <AtAGlance stats={stats} proposalsMine={proposalsMine} />
        </div>
      </div>
    </div>
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
              {row.deadline && <> <DeadlineTag tag={row.deadline} /></>}
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
