import { useState, useEffect } from "react";
import axios from "axios";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

export default function StaffManuals({ onSelectManual }) {
  const [manuals, setManuals]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");

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

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">My Manuals</h1>
          <p className="page-subtitle">
            Manuals assigned to your department — open one to read sections or submit a revision.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger" style={{ marginBottom: "1.5rem" }}>{error}</div>}

      {!error && manuals.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📂</div>
          <p className="empty-title">No manuals yet</p>
          <p className="empty-text">
            No manuals have been assigned to your department. Contact your administrator.
          </p>
        </div>
      ) : (
        <div className="grid-auto stagger">
          {manuals.map((manual) => (
            <article
              key={manual.id}
              className="card card-pad card-hover card-interactive card-rail"
              style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}
              onClick={() => onSelectManual(manual.id, manual.title)}
            >
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span style={{ fontSize: "1.6rem", lineHeight: 1 }}>📋</span>
                <span className="badge badge-id">v{manual.version}</span>
              </div>

              <h3 className="card-title" style={{ lineHeight: 1.4 }}>{manual.title}</h3>

              <dl className="col" style={{ gap: "0.35rem", margin: 0 }}>
                <MetaRow label="Department" value={manual.department} />
                <MetaRow label="Sections" value={manual.section_count} />
                <MetaRow label="Uploaded" value={new Date(manual.uploaded_at).toLocaleDateString()} />
                <MetaRow label="By" value={manual.uploaded_by} />
              </dl>

              <button
                className="btn btn-deep btn-block"
                style={{ marginTop: "auto" }}
                onClick={(e) => { e.stopPropagation(); onSelectManual(manual.id, manual.title); }}
              >
                View sections →
              </button>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function MetaRow({ label, value }) {
  return (
    <div className="row text-sm" style={{ justifyContent: "space-between", gap: "1rem" }}>
      <dt className="subtle" style={{ fontWeight: 600 }}>{label}</dt>
      <dd className="strong" style={{ margin: 0, textAlign: "right" }}>{value}</dd>
    </div>
  );
}
