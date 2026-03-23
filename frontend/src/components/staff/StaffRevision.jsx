import { useState, useEffect } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const STATUS_COLORS = {
  pending:  { bg: "#fffbeb", color: "#b45309", border: "#fcd34d", label: "Pending Review" },
  approved: { bg: "#f0fff4", color: "#276749", border: "#9ae6b4", label: "Approved" },
  rejected: { bg: "#fff5f5", color: "#c53030", border: "#feb2b2", label: "Rejected" },
};

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
    return (
      <div style={styles.center}>
        <div style={styles.spinner} />
        <p style={{ color: "#888", marginTop: "1rem" }}>Loading revisions...</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>My Revisions</h1>
          <p style={styles.subtitle}>Track revisions you've submitted for admin review.</p>
        </div>
        <button style={styles.refreshBtn} onClick={fetchRevisions}>↻ Refresh</button>
      </div>

      {/* Summary cards */}
      <div style={styles.summaryRow}>
        {[
          { key: "all",      label: "Total",    color: "#4a47a3", bg: "#eff2ff" },
          { key: "pending",  label: "Pending",  color: "#b45309", bg: "#fffbeb" },
          { key: "approved", label: "Approved", color: "#276749", bg: "#f0fff4" },
          { key: "rejected", label: "Rejected", color: "#c53030", bg: "#fff5f5" },
        ].map(({ key, label, color, bg }) => (
          <div
            key={key}
            style={{
              ...styles.summaryCard,
              backgroundColor: filter === key ? color : bg,
              color: filter === key ? "#fff" : color,
              cursor: "pointer",
            }}
            onClick={() => setFilter(key)}
          >
            <div style={{ fontSize: "1.8rem", fontWeight: "800" }}>{counts[key]}</div>
            <div style={{ fontSize: "0.82rem", fontWeight: "600", marginTop: "0.2rem" }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Revision list */}
      {filtered.length === 0 ? (
        <div style={styles.emptyState}>
          <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>📭</div>
          <p style={{ color: "#888", margin: 0 }}>
            {filter === "all" ? "You haven't submitted any revisions yet." : `No ${filter} revisions.`}
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {filtered.map((r) => {
            const sc = STATUS_COLORS[r.status] || STATUS_COLORS.pending;
            const isExpanded = expanded === r.id;
            return (
              <div key={r.id} style={{ ...styles.card, borderLeft: `4px solid ${sc.border}` }}>
                <div style={styles.cardHeader} onClick={() => setExpanded(isExpanded ? null : r.id)}>
                  <div style={{ flex: 1 }}>
                    <div style={styles.cardManual}>{r.manual}</div>
                    <div style={styles.cardSection}>Section: {r.section}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                    <div style={{ textAlign: "right" }}>
                      <span style={{
                        ...styles.statusBadge,
                        backgroundColor: sc.bg,
                        color: sc.color,
                        border: `1px solid ${sc.border}`,
                      }}>
                        {sc.label}
                      </span>
                      <div style={styles.cardDate}>
                        {new Date(r.submitted_at).toLocaleDateString("en-PH", {
                          year: "numeric", month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit"
                        })}
                      </div>
                    </div>
                    <span style={{ color: "#aaa", fontSize: "0.9rem" }}>{isExpanded ? "▲" : "▼"}</span>
                  </div>
                </div>

                {isExpanded && (
                  <div style={styles.cardBody}>
                    {r.reviewer_notes ? (
                      <div style={{
                        ...styles.notesBox,
                        backgroundColor: sc.bg,
                        border: `1px solid ${sc.border}`,
                        color: sc.color,
                      }}>
                        <strong>Admin Notes:</strong> {r.reviewer_notes}
                      </div>
                    ) : (
                      r.status === "pending" && (
                        <div style={styles.pendingNote}>
                          ⏳ Your revision is awaiting admin review. You'll see feedback here once it's processed.
                        </div>
                      )
                    )}
                    {r.reviewed_at && (
                      <p style={styles.reviewedAt}>
                        Reviewed on {new Date(r.reviewed_at).toLocaleString()}
                      </p>
                    )}
                    {r.diff_preview && (
                      <div>
                        <div style={styles.diffLabel}>Change Preview</div>
                        <pre style={styles.diffBox}>{r.diff_preview}</pre>
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

const styles = {
  container:   { maxWidth: "900px" },
  center:      { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh" },
  spinner:     { width: "36px", height: "36px", border: "3px solid #e2e8f0", borderTop: "3px solid #4a47a3", borderRadius: "50%", animation: "spin 0.8s linear infinite" },
  header:      { display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "1.5rem", flexWrap: "wrap", gap: "0.5rem" },
  title:       { fontSize: "1.8rem", fontWeight: "700", color: "#090749", margin: "0 0 0.25rem" },
  subtitle:    { color: "#718096", fontSize: "0.9rem", margin: 0 },
  refreshBtn:  { padding: "0.5rem 1rem", backgroundColor: "#e8eaf6", color: "#4a47a3", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "0.85rem", alignSelf: "flex-start" },
  summaryRow:  { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", marginBottom: "1.5rem" },
  summaryCard: { borderRadius: "10px", padding: "1rem", textAlign: "center", transition: "all 0.2s", border: "1px solid transparent" },
  emptyState:  { textAlign: "center", padding: "4rem 2rem", backgroundColor: "#fff", borderRadius: "12px", boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  card:        { backgroundColor: "#fff", borderRadius: "10px", overflow: "hidden", boxShadow: "0 1px 4px rgba(0,0,0,0.07)" },
  cardHeader:  { display: "flex", alignItems: "center", padding: "1rem 1.25rem", cursor: "pointer", gap: "1rem" },
  cardManual:  { fontWeight: "700", color: "#090749", fontSize: "0.95rem" },
  cardSection: { color: "#718096", fontSize: "0.82rem", marginTop: "0.2rem" },
  statusBadge: { display: "inline-block", padding: "0.25rem 0.75rem", borderRadius: "20px", fontSize: "0.75rem", fontWeight: "700" },
  cardDate:    { color: "#aaa", fontSize: "0.75rem", marginTop: "0.3rem", textAlign: "right" },
  cardBody:    { padding: "0 1.25rem 1.25rem", borderTop: "1px solid #f0f0f0" },
  notesBox:    { padding: "0.75rem 1rem", borderRadius: "8px", fontSize: "0.88rem", margin: "1rem 0 0.5rem" },
  pendingNote: { backgroundColor: "#fffbeb", color: "#b45309", border: "1px solid #fcd34d", borderRadius: "8px", padding: "0.75rem 1rem", fontSize: "0.88rem", margin: "1rem 0 0.5rem" },
  reviewedAt:  { color: "#aaa", fontSize: "0.78rem", margin: "0.25rem 0 0.75rem" },
  diffLabel:   { fontSize: "0.8rem", fontWeight: "600", color: "#555", marginBottom: "0.4rem" },
  diffBox:     { backgroundColor: "#1a1a2e", color: "#a5b4fc", padding: "0.75rem 1rem", borderRadius: "8px", fontSize: "0.78rem", overflow: "auto", maxHeight: "220px", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 },
};
