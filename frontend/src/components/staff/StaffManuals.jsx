import { useState, useEffect } from "react";
import axios from "axios";
import { formatDate, formatRevision } from "../documentStatus";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

// Past this many documents, a filter box earns its place.
const FILTER_FROM = 8;

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * The documents a person reads: one row each.
 *
 * A list rather than cards, so twenty documents fit on a screen. Each row
 * carries what a reader decides by - the title, its series, what it is to
 * their office, and which revision is in force. Upload details live with
 * the admin.
 */
export default function StaffManuals({ onSelectManual }) {
  const [manuals, setManuals]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [query, setQuery]       = useState("");

  useEffect(() => {
    fetchManuals();
  }, []);

  const fetchManuals = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await axios.get(`${BASE_URL}/api/staff/manuals/`, getAuth());
      setManuals(res.data);
    } catch (err) {
      const msg = err.response?.data?.error || "Failed to load manuals.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading your manuals…</div>;
  }

  const needle = query.trim().toLowerCase();
  const shown = needle
    ? manuals.filter((m) =>
        [m.title, m.series, m.series_title, m.owner]
          .some((v) => (v || "").toLowerCase().includes(needle)))
    : manuals;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">My Manuals</h1>
          <p className="page-subtitle">
            The documents your office works with — open one to read sections or propose a change.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger" style={{ marginBottom: "1.5rem" }}>{error}</div>}

      {!error && manuals.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📂</div>
          <p className="empty-title">No manuals yet</p>
          <p className="empty-text">
            No documents are linked to your office yet. The system
            administrator assigns them.
          </p>
        </div>
      ) : (
        <>
          {manuals.length > FILTER_FROM && (
            <input
              type="search"
              className="input manual-filter"
              placeholder="Filter by title, series or owner"
              aria-label="Filter manuals"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}

          {shown.length === 0 ? (
            <p className="subtle text-sm">No manuals match “{query}”.</p>
          ) : (
            <ul className="manual-list">
              {shown.map((manual) => (
                <li key={manual.id}>
                  <button
                    type="button"
                    className="manual-row"
                    onClick={() => onSelectManual(manual.id, manual.title)}
                  >
                    <span className="manual-row-main">
                      <span className="manual-row-title">{manual.title}</span>
                      <span className="manual-row-sub">
                        {[
                          manual.series && `${manual.series} — ${manual.series_title}`,
                          manual.owner && `Owner: ${manual.owner}`,
                        ].filter(Boolean).join(" · ") || "Not yet assigned to a series"}
                      </span>
                    </span>

                    <span className="manual-row-meta">
                      {manual.relationship && (
                        <span className="badge">{manual.relationship}</span>
                      )}
                      {manual.status && (
                        <span className="badge badge-id">
                          {formatRevision(manual.status.revision)}
                        </span>
                      )}
                      {manual.status && (
                        <span className="manual-row-fact">
                          Effective {formatDate(manual.status.effective_on)}
                        </span>
                      )}
                      <span className="manual-row-fact">
                        {manual.section_count} section{manual.section_count === 1 ? "" : "s"}
                      </span>
                      <span className="manual-row-go" aria-hidden="true">→</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
