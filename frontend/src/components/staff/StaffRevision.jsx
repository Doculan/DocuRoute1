import { useState, useEffect } from "react";
import axios from "axios";
import DiffView from "../DiffView";

const BASE_URL = "http://127.0.0.1:8000";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const STATUS = {
  pending:  { badge: "badge-warning", alert: "alert-warning", label: "Pending review", tone: "is-warning" },
  approved: { badge: "badge-success", alert: "alert-success", label: "Approved",       tone: "is-success" },
  rejected: { badge: "badge-danger",  alert: "alert-danger",  label: "Rejected",       tone: "is-danger" },
};

const FILTERS = [
  { key: "all",      label: "Total",    tone: "" },
  { key: "pending",  label: "Pending",  tone: "is-warning" },
  { key: "approved", label: "Approved", tone: "is-success" },
  { key: "rejected", label: "Rejected", tone: "is-danger" },
];

export default function StaffRevisions() {
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [filter, setFilter]       = useState("all");
  const [expanded, setExpanded]   = useState(null);

  useEffect(() => {
    fetchRevisions();
  }, []);

  const fetchRevisions = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${BASE_URL}/api/staff/revisions/`, getAuth());
      setRevisions(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const filtered = filter === "all"
    ? revisions
    : revisions.filter((r) => r.status === filter);

  const counts = {
    all: revisions.length,
    pending:  revisions.filter((r) => r.status === "pending").length,
    approved: revisions.filter((r) => r.status === "approved").length,
    rejected: revisions.filter((r) => r.status === "rejected").length,
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading revisions…</div>;
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">My Revisions</h1>
          <p className="page-subtitle">Track the revisions you&apos;ve submitted for admin review.</p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={fetchRevisions}>↻ Refresh</button>
      </header>

      <div className="stat-grid">
        {FILTERS.map(({ key, label, tone }) => (
          <button
            key={key}
            className={`stat-card ${tone}${filter === key ? " is-selected" : ""}`}
            style={{ textAlign: "left", cursor: "pointer" }}
            onClick={() => setFilter(key)}
          >
            <span className="stat-value">{counts[key]}</span>
            <span className="stat-label">{label}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <p className="empty-title">Nothing here yet</p>
          <p className="empty-text">
            {filter === "all" ? "You haven't submitted any revisions yet." : `No ${filter} revisions.`}
          </p>
        </div>
      ) : (
        <div className="col stagger" style={{ gap: "0.75rem" }}>
          {filtered.map((r) => {
            const st = STATUS[r.status] || STATUS.pending;
            const isExpanded = expanded === r.id;
            return (
              <div key={r.id} className={`card accordion ${st.tone}`}>
                <button
                  className="accordion-head"
                  onClick={() => setExpanded(isExpanded ? null : r.id)}
                >
                  <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                    <div className="strong">{r.manual}</div>
                    <div className="muted text-sm">Section: {r.section}</div>
                  </div>

                  <div className="row" style={{ gap: "1rem" }}>
                    <div style={{ textAlign: "right" }}>
                      <span className={`badge ${st.badge}`}>{st.label}</span>
                      <div className="subtle text-xs" style={{ marginTop: "0.3rem" }}>
                        {new Date(r.submitted_at).toLocaleDateString("en-PH", {
                          year: "numeric", month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </div>
                    </div>
                    <span className={`chevron${isExpanded ? " is-open" : ""}`}>▾</span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="accordion-body">
                    {r.reviewer_notes ? (
                      <div className={`alert ${st.alert}`}>
                        <strong>Admin notes:</strong> {r.reviewer_notes}
                      </div>
                    ) : (
                      r.status === "pending" && (
                        <div className="alert alert-warning">
                          ⏳ Your revision is awaiting admin review. Feedback will appear here once processed.
                        </div>
                      )
                    )}

                    {r.reviewed_at && (
                      <p className="subtle text-xs">
                        Reviewed on {new Date(r.reviewed_at).toLocaleString()}
                      </p>
                    )}

                    {r.diff_preview && (
                      <div className="diff-wrap">
                        <div className="diff-wrap-head">Your proposed changes</div>
                        <div className="diff-scroll">
                          <DiffView diffText={r.diff_preview} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
