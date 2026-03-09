import { useState, useEffect } from "react";
import axios from "axios";

const STATUS_COLORS = {
  pending: { bg: "#fffff0", color: "#744210" },
  approved: { bg: "#f0fff4", color: "#276749" },
  rejected: { bg: "#fff5f5", color: "#c53030" },
};

export default function RevisionReview() {
  const [revisions, setRevisions] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [selectedRevision, setSelectedRevision] = useState(null);
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchRevisions = async () => {
    setLoading(true);
    try {
      const res = await axios.get(
        `http://127.0.0.1:8000/api/admin/revisions/?status=${statusFilter}`,
        authHeaders
      );
      setRevisions(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRevisions(); }, [statusFilter]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleReview = async (revisionId, status) => {
    try {
      await axios.patch(
        `http://127.0.0.1:8000/api/admin/revisions/${revisionId}/review/`,
        { status, reviewer_notes: notes },
        authHeaders
      );
      showMessage(`✅ Revision ${status}.`);
      setSelectedRevision(null);
      setNotes("");
      fetchRevisions();
    } catch { showMessage("❌ Failed to review."); }
  };

  return (
    <div>
      <h2 style={styles.pageTitle}>Revision Review</h2>

      {/* Filter Tabs */}
      <div style={styles.tabs}>
        {["pending", "approved", "rejected"].map((s) => (
          <button
            key={s}
            style={statusFilter === s ? styles.tabActive : styles.tab}
            onClick={() => setStatusFilter(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {message && <div style={styles.toast}>{message}</div>}

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : revisions.length === 0 ? (
        <div style={styles.empty}>No {statusFilter} revisions.</div>
      ) : (
        revisions.map((r) => (
          <div key={r.id} style={styles.revisionCard}>
            <div style={styles.revisionHeader}>
              <div>
                <span style={styles.sectionName}>{r.section}</span>
                <span style={styles.manualName}> — {r.manual} ({r.department})</span>
              </div>
              <span style={{
                ...styles.statusBadge,
                backgroundColor: STATUS_COLORS[r.status]?.bg,
                color: STATUS_COLORS[r.status]?.color,
              }}>
                {r.status.toUpperCase()}
              </span>
            </div>

            <div style={styles.meta}>
              <span>👤 {r.submitted_by}</span>
              <span>📅 {new Date(r.submitted_at).toLocaleString()}</span>
            </div>

            {/* Diff Preview */}
            <div style={styles.diffBox}>
              <p style={styles.diffLabel}>Diff Preview:</p>
              <pre style={styles.diffContent}>
                {r.diff_preview || "No changes detected."}
              </pre>
            </div>

            {/* Review Actions (only for pending) */}
            {r.status === "pending" && (
              <div style={styles.reviewSection}>
                {selectedRevision === r.id ? (
                  <div style={styles.reviewForm}>
                    <textarea
                      style={styles.notesInput}
                      placeholder="Reviewer notes (optional)"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                    />
                    <div style={styles.reviewButtons}>
                      <button
                        style={styles.approveBtn}
                        onClick={() => handleReview(r.id, "approved")}
                      >
                        ✅ Approve
                      </button>
                      <button
                        style={styles.rejectBtn}
                        onClick={() => handleReview(r.id, "rejected")}
                      >
                        ❌ Reject
                      </button>
                      <button
                        style={styles.cancelBtn}
                        onClick={() => setSelectedRevision(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    style={styles.reviewBtn}
                    onClick={() => setSelectedRevision(r.id)}
                  >
                    Review
                  </button>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

const styles = {
  pageTitle: { margin: "0 0 1.5rem 0", color: "#1a1a2e" },
  tabs: { display: "flex", gap: "0.5rem", marginBottom: "1.5rem" },
  tab: {
    padding: "0.5rem 1.2rem", border: "2px solid #ddd",
    borderRadius: "8px", backgroundColor: "#fff",
    cursor: "pointer", fontWeight: "600", color: "#666",
  },
  tabActive: {
    padding: "0.5rem 1.2rem", border: "2px solid #4f46e5",
    borderRadius: "8px", backgroundColor: "#4f46e5",
    cursor: "pointer", fontWeight: "600", color: "#fff",
  },
  toast: {
    backgroundColor: "#ebf8ff", border: "1px solid #bee3f8",
    borderRadius: "8px", padding: "0.75rem 1rem",
    marginBottom: "1rem", color: "#2b6cb0", fontWeight: "500",
  },
  revisionCard: {
    backgroundColor: "#fff", borderRadius: "10px",
    padding: "1.5rem", marginBottom: "1rem",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
  },
  revisionHeader: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", marginBottom: "0.5rem",
  },
  sectionName: { fontWeight: "700", color: "#1a1a2e" },
  manualName: { color: "#666", fontSize: "0.9rem" },
  statusBadge: {
    padding: "0.25rem 0.7rem", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "700",
  },
  meta: {
    display: "flex", gap: "1.5rem", color: "#888",
    fontSize: "0.85rem", marginBottom: "1rem",
  },
  diffBox: {
    backgroundColor: "#f7f8fc", borderRadius: "8px",
    padding: "1rem", marginBottom: "1rem",
  },
  diffLabel: { margin: "0 0 0.5rem 0", fontWeight: "600", color: "#444", fontSize: "0.85rem" },
  diffContent: {
    margin: 0, fontSize: "0.8rem", color: "#333",
    whiteSpace: "pre-wrap", wordBreak: "break-word",
    maxHeight: "150px", overflowY: "auto",
  },
  reviewSection: { marginTop: "0.5rem" },
  reviewForm: { display: "flex", flexDirection: "column", gap: "0.75rem" },
  notesInput: {
    padding: "0.7rem 1rem", borderRadius: "8px",
    border: "1px solid #ddd", fontSize: "0.9rem",
    resize: "vertical", minHeight: "80px", outline: "none",
  },
  reviewButtons: { display: "flex", gap: "0.75rem" },
  reviewBtn: {
    padding: "0.5rem 1.2rem", backgroundColor: "#4f46e5",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  approveBtn: {
    padding: "0.5rem 1.2rem", backgroundColor: "#38a169",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  rejectBtn: {
    padding: "0.5rem 1.2rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  cancelBtn: {
    padding: "0.5rem 1.2rem", backgroundColor: "#eee",
    color: "#333", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  empty: {
    textAlign: "center", padding: "3rem", color: "#888",
    backgroundColor: "#fff", borderRadius: "10px",
  },
  loading: { textAlign: "center", color: "#888", padding: "2rem" },
};
