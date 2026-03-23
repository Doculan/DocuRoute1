import { useState, useEffect } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";

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
    return (
      <div style={styles.center}>
        <div style={styles.spinner} />
        <p style={{ color: "#888", marginTop: "1rem" }}>Loading your manuals...</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>My Manuals</h1>
          <p style={styles.subtitle}>
            Manuals assigned to your department. Click one to read sections or submit a revision.
          </p>
        </div>
      </div>

      {error && (
        <div style={styles.errorBox}>{error}</div>
      )}

      {!error && manuals.length === 0 ? (
        <div style={styles.emptyState}>
          <div style={{ fontSize: "3rem", marginBottom: "0.75rem" }}>📂</div>
          <h3 style={{ color: "#1a1a2e", margin: "0 0 0.5rem" }}>No manuals yet</h3>
          <p style={{ color: "#888", margin: 0 }}>
            No manuals have been assigned to your department. Contact your administrator.
          </p>
        </div>
      ) : (
        <div style={styles.grid}>
          {manuals.map((manual) => (
            <div key={manual.id} style={styles.card}>
              <div style={styles.cardTop}>
                <div style={styles.cardIcon}>📋</div>
                <div style={styles.cardBadge}>v{manual.version}</div>
              </div>
              <h3 style={styles.cardTitle}>{manual.title}</h3>
              <div style={styles.cardMeta}>
                <div style={styles.metaRow}>
                  <span style={styles.metaLabel}>Department</span>
                  <span style={styles.metaValue}>{manual.department}</span>
                </div>
                <div style={styles.metaRow}>
                  <span style={styles.metaLabel}>Sections</span>
                  <span style={styles.metaValue}>{manual.section_count}</span>
                </div>
                <div style={styles.metaRow}>
                  <span style={styles.metaLabel}>Uploaded</span>
                  <span style={styles.metaValue}>{new Date(manual.uploaded_at).toLocaleDateString()}</span>
                </div>
                <div style={styles.metaRow}>
                  <span style={styles.metaLabel}>By</span>
                  <span style={styles.metaValue}>{manual.uploaded_by}</span>
                </div>
              </div>
              <button
                style={styles.viewBtn}
                onClick={() => onSelectManual(manual.id, manual.title)}
              >
                View Sections →
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  container: { maxWidth: "1200px" },
  center:    { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh" },
  spinner:   { width: "36px", height: "36px", border: "3px solid #e2e8f0", borderTop: "3px solid #4a47a3", borderRadius: "50%", animation: "spin 0.8s linear infinite" },
  header:    { marginBottom: "2rem" },
  title:     { fontSize: "1.8rem", fontWeight: "700", color: "#090749", margin: "0 0 0.25rem" },
  subtitle:  { color: "#718096", fontSize: "0.9rem", margin: 0 },
  errorBox:  { backgroundColor: "#fff5f5", color: "#c53030", border: "1px solid #feb2b2", borderRadius: "8px", padding: "1rem", marginBottom: "1.5rem" },
  emptyState:{ textAlign: "center", padding: "4rem 2rem", backgroundColor: "#fff", borderRadius: "12px", boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  grid:      { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "1.5rem" },
  card:      { backgroundColor: "#fff", borderRadius: "12px", padding: "1.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", display: "flex", flexDirection: "column", gap: "0.75rem", transition: "box-shadow 0.2s" },
  cardTop:   { display: "flex", justifyContent: "space-between", alignItems: "center" },
  cardIcon:  { fontSize: "1.8rem" },
  cardBadge: { backgroundColor: "#eff2ff", color: "#4a47a3", borderRadius: "20px", padding: "0.2rem 0.7rem", fontSize: "0.75rem", fontWeight: "700" },
  cardTitle: { fontSize: "1rem", fontWeight: "700", color: "#090749", margin: 0, lineHeight: "1.4" },
  cardMeta:  { display: "flex", flexDirection: "column", gap: "0.3rem" },
  metaRow:   { display: "flex", justifyContent: "space-between", fontSize: "0.83rem" },
  metaLabel: { color: "#aaa", fontWeight: "600" },
  metaValue: { color: "#333", fontWeight: "500" },
  viewBtn:   { marginTop: "auto", padding: "0.7rem", backgroundColor: "#090749", color: "#fff", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "0.9rem", transition: "background 0.2s" },
};
