import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";
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
  const [expandedRevision, setExpandedRevision] = useState(null);
  const [showManualModal, setShowManualModal] = useState(false);
  const [manualSections, setManualSections] = useState([]);
  const [manualLoading, setManualLoading] = useState(false);

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchRevisions = useCallback(async () => {
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
  }, [statusFilter, token]);

  useEffect(() => { fetchRevisions(); }, [fetchRevisions]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const parseUnifiedDiff = (text) => {
    const lines = text.split("\n");
    const result = [];
    lines.forEach((line) => {
      if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) return;
      if (line.startsWith("-")) {
        result.push({ type: "removed", text: line.slice(1) });
      } else if (line.startsWith("+")) {
        result.push({ type: "added", text: line.slice(1) });
      } else {
        result.push({ type: "context", text: line.startsWith(" ") ? line.slice(1) : line });
      }
    });
    return result;
  };

  const renderSideBySide = (rev) => {
    const diffItems = parseUnifiedDiff(rev.diff_text || rev.diff_preview || "");
    
    return (
      <div style={styles.sideBySide} role="table" aria-label="Side-by-side diff view">
        <div style={styles.column}>
          <h4 style={styles.columnHeader}>Original</h4>
          <div style={styles.diffLines}>
            {diffItems.map((item, idx) => (
              <div
                key={`left-${idx}`}
                style={{
                  ...styles.diffLine,
                  backgroundColor: item.type === "removed" ? "#fee" : "#fff",
                  borderLeft: item.type === "removed" ? "3px solid #c53030" : "3px solid #ccc",
                }}
              >
                <span style={styles.lineNumber}>{idx + 1}</span>
                {item.type === "removed" ? (
                  <span style={{ color: "#c53030", fontWeight: "600" }}>🗑 {item.text}</span>
                ) : (
                  <span style={{ color: "#333" }}>{item.text}</span>
                )}
              </div>
            ))}
          </div>
        </div>
        <div style={styles.column}>
          <h4 style={styles.columnHeader}>Proposed</h4>
          <div style={styles.diffLines}>
            {diffItems.map((item, idx) => (
              <div
                key={`right-${idx}`}
                style={{
                  ...styles.diffLine,
                  backgroundColor: item.type === "added" ? "#efe" : "#fff",
                  borderLeft: item.type === "added" ? "3px solid #38a169" : "3px solid #ccc",
                }}
              >
                <span style={styles.lineNumber}>{idx + 1}</span>
                {item.type === "added" ? (
                  <span style={{ color: "#38a169", fontWeight: "600" }}>✚ {item.text}</span>
                ) : (
                  <span style={{ color: "#333" }}>{item.text}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  const renderColorizedDiff = (diffText) => {
    if (!diffText) return "No changes detected.";
    
    const lines = diffText.split("\n");
    return (
      <div style={styles.colorizedDiffContainer}>
        {lines.map((line, idx) => {
          if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) {
            return (
              <div key={idx} style={{ color: "#666", fontSize: "0.75rem", padding: "0.25rem" }}>
                {line}
              </div>
            );
          }
          if (line.startsWith("-")) {
            return (
              <div
                key={idx}
                style={{
                  backgroundColor: "#fee", color: "#c53030", fontWeight: "500",
                  padding: "0.35rem 0.5rem", borderLeft: "3px solid #c53030",
                  display: "flex", gap: "0.5rem"
                }}
              >
                <span style={{ flexShrink: 0 }}>🗑</span>
                <span>{line.slice(1)}</span>
              </div>
            );
          }
          if (line.startsWith("+")) {
            return (
              <div
                key={idx}
                style={{
                  backgroundColor: "#efe", color: "#38a169", fontWeight: "500",
                  padding: "0.35rem 0.5rem", borderLeft: "3px solid #38a169",
                  display: "flex", gap: "0.5rem"
                }}
              >
                <span style={{ flexShrink: 0 }}>✚</span>
                <span>{line.slice(1)}</span>
              </div>
            );
          }
          return (
            <div
              key={idx}
              style={{
                color: "#333", padding: "0.35rem 0.5rem", borderLeft: "3px solid #e2e8f0"
              }}
            >
              {line.startsWith(" ") ? line.slice(1) : line}
            </div>
          );
        })}
      </div>
    );
  };

  const handleViewManual = async (manualId) => {
    if (!manualId) return;
    setManualLoading(true);
    try {
      const res = await axios.get(`${BASE_URL}/api/manuals/${manualId}/sections/`, authHeaders);
      setManualSections(res.data.sections || []);
      setShowManualModal(true);
    } catch (err) {
      console.error(err);
      showMessage("❌ Failed to load manual sections.");
    } finally {
      setManualLoading(false);
    }
  };

  const handleReview = async (revisionId, status) => {
    console.log('handleReview called with:', revisionId, status);
    try {
      console.log('Making API call to:', `http://127.0.0.1:8000/api/admin/revisions/${revisionId}/review/`);
      const response = await axios.patch(
        `http://127.0.0.1:8000/api/admin/revisions/${revisionId}/review/`,
        { status, reviewer_notes: notes },
        authHeaders
      );
      console.log('API response:', response);
      showMessage(`✅ Revision ${status}.`);
      setSelectedRevision(null);
      setNotes("");
      fetchRevisions();
    } catch (error) {
      console.error('Error in handleReview:', error);
      console.error('Error response:', error.response);
      showMessage("❌ Failed to review.");
    }
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
            {/* Header: Manual & Section Info */}
            <div style={styles.revisionHeader}>
              <div>
                <div style={styles.manualInfo}>
                  <strong style={{ color: "#1a1a2e" }}>Manual:</strong>
                  <span style={{ color: "#0066cc", fontWeight: "600" }}>{r.manual}</span>
                  <span style={{ color: "#666", fontSize: "0.85rem" }}>({r.department})</span>
                </div>
                <div style={{ ...styles.manualInfo, marginTop: "0.35rem" }}>
                  <strong style={{ color: "#1a1a2e" }}>Section:</strong>
                  <span style={{ ...styles.sectionHighlight }}>
                    {r.section} [ID: {r.section_id}]
                  </span>
                  <span style={{ color: "#888", fontSize: "0.8rem", marginLeft: "0.5rem" }}>
                    {r.merge_type === 'merge' ? '🔗 MERGE' : '✏️ TEXT EDIT'}
                  </span>
                </div>
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
              <span>👤 Submitted by: {r.submitted_by}</span>
              <span>📅 {new Date(r.submitted_at).toLocaleString()}</span>
            </div>

            {/* Uploaded File */}
            {r.uploaded_file && (
              <div style={styles.fileInfo}>
                <strong style={{ color: "#1a1a2e" }}>📎 Uploaded File:</strong>
                <a
                  href={`${BASE_URL}${r.uploaded_file}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={styles.fileLink}
                >
                  View Original File
                </a>
              </div>
            )}

            {/* Quick Action Buttons */}
            <div style={styles.quickActions}>
              <button
                style={styles.viewManualBtn}
                onClick={() => handleViewManual(r.manual_id)}
              >
                📖 View Full Manual Context
              </button>
              <button
                style={styles.smallBtn}
                onClick={() => setExpandedRevision(expandedRevision === r.id ? null : r.id)}
              >
                {expandedRevision === r.id ? "▼ Hide Detailed Comparison" : "▶ Show Detailed Comparison"}
              </button>
            </div>

            {/* Diff Preview */}
            <div style={styles.diffBox}>
              <p style={styles.diffLabel}>📝 Changes in "{r.section}":</p>
              <div style={styles.diffContent}>
                {renderColorizedDiff(r.diff_preview || r.diff_text || "")}
              </div>
            </div>

            {expandedRevision === r.id && (
              <div style={{ marginTop: "0.85rem" }}>
                <div style={styles.contextMeta}>
                  <strong>Section text context</strong>
                  <span style={{ marginLeft: "1rem", fontSize: "0.85rem", color: "#555" }}>
                    Section ID: {r.section_id}
                  </span>
                </div>
                {renderSideBySide(r)}
                <div style={{ marginTop: "0.5rem", fontSize: "0.88rem", color: "#444" }}>
                  <strong>Current section content:</strong>
                  <pre style={styles.codeBlockSmall}>{r.section_content || "N/A"}</pre>
                  {r.proposed_content && (
                    <>
                      <strong>Proposed content:</strong>
                      <pre style={styles.codeBlockSmall}>{r.proposed_content}</pre>
                    </>
                  )}
                  {r.merge_type && (
                    <p>Merge operation proposed with section IDs: {JSON.stringify(r.merge_section_ids || [])}</p>
                  )}
                </div>
              </div>
            )}

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
                        onClick={() => {
                          console.log('Approve button clicked for revision:', r.id);
                          handleReview(r.id, "approved");
                        }}
                      >
                        ✅ Approve
                      </button>
                      <button
                        style={styles.rejectBtn}
                        onClick={() => {
                          console.log('Reject button clicked for revision:', r.id);
                          handleReview(r.id, "rejected");
                        }}
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

      {showManualModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <div style={styles.modalHeader}>
              <h3>Manual: section context</h3>
              <button style={styles.closeBtn} onClick={() => setShowManualModal(false)}>✕</button>
            </div>
            {manualLoading ? (
              <p>Loading manual sections…</p>
            ) : (
              <div style={styles.modalBody}>
                {manualSections.length === 0 ? (
                  <p>No sections found for this manual.</p>
                ) : (
                  manualSections.map((sec) => (
                    <div key={sec.id} style={styles.manualSectionItem}>
                      <div style={styles.manualSectionHeader}>
                        <strong>{sec.subtitle || "Untitled section"}</strong>
                        <span style={styles.manualSectionMeta}>#{sec.id} · tag: {sec.tag}</span>
                      </div>
                      <pre style={styles.codeBlockSmall}>{sec.content || "(empty)"}</pre>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
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
    borderLeft: "4px solid #4f46e5",
  },
  revisionHeader: {
    display: "flex", justifyContent: "space-between",
    alignItems: "flex-start", marginBottom: "0.75rem",
  },
  manualInfo: {
    display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.95rem"
  },
  sectionHighlight: {
    backgroundColor: "#fef3c7", color: "#92400e",
    padding: "0.25rem 0.5rem", borderRadius: "4px",
    fontWeight: "600", fontSize: "0.95rem"
  },
  sectionName: { fontWeight: "700", color: "#1a1a2e" },
  manualName: { color: "#666", fontSize: "0.9rem" },
  statusBadge: {
    padding: "0.35rem 0.9rem", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "700",
  },
  meta: {
    display: "flex", gap: "2rem", color: "#555",
    fontSize: "0.85rem", marginBottom: "1rem", paddingBottom: "0.5rem", borderBottom: "1px solid #e5e7eb"
  },
  quickActions: {
    display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap"
  },
  viewManualBtn: {
    padding: "0.6rem 1.2rem", backgroundColor: "#3b82f6",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600", fontSize: "0.9rem",
    flex: "1", minWidth: "180px"
  },
  diffBox: {
    backgroundColor: "#f7f8fc", borderRadius: "8px",
    padding: "1rem", marginBottom: "1rem", border: "1px solid #e2e8f0"
  },
  diffLabel: { margin: "0 0 0.75rem 0", fontWeight: "600", color: "#1a1a2e", fontSize: "0.9rem" },
  diffContent: {
    margin: 0, fontSize: "0.8rem", color: "#333",
    maxHeight: "250px", overflowY: "auto", fontFamily: "monospace",
    backgroundColor: "#fff", padding: "0.5rem", borderRadius: "6px", border: "1px solid #e2e8f0"
  },
  colorizedDiffContainer: {
    display: "flex", flexDirection: "column", gap: 0, fontFamily: "monospace",
    fontSize: "0.8rem", lineHeight: "1.5"
  },
  reviewSection: { marginTop: "0.75rem" },
  reviewForm: { display: "flex", flexDirection: "column", gap: "0.75rem" },
  notesInput: {
    padding: "0.7rem 1rem", borderRadius: "8px",
    border: "1px solid #ddd", fontSize: "0.9rem",
    resize: "vertical", minHeight: "80px", outline: "none",
  },
  reviewButtons: { display: "flex", gap: "0.75rem" },
  reviewBtn: {
    padding: "0.6rem 1.5rem", backgroundColor: "#4f46e5",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600", fontSize: "0.9rem",
  },
  approveBtn: {
    padding: "0.6rem 1.5rem", backgroundColor: "#38a169",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600", fontSize: "0.9rem",
  },
  rejectBtn: {
    padding: "0.6rem 1.5rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600", fontSize: "0.9rem",
  },
  cancelBtn: {
    padding: "0.6rem 1.5rem", backgroundColor: "#eee",
    color: "#333", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600", fontSize: "0.9rem",
  },
  empty: {
    textAlign: "center", padding: "3rem", color: "#888",
    backgroundColor: "#fff", borderRadius: "10px",
  },
  loading: { textAlign: "center", color: "#888", padding: "2rem" },
  smallBtn: {
    border: "1px solid #cbd5e0", borderRadius: "8px",
    padding: "0.5rem 1rem", backgroundColor: "#fff",
    color: "#1a202c", cursor: "pointer", fontSize: "0.85rem", fontWeight: "500"
  },
  contextMeta: {
    display: "flex", alignItems: "center", gap: "0.5rem",
    color: "#444", marginBottom: "0.75rem", fontSize: "0.9rem", fontWeight: "600"
  },
  sideBySide: {
    display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem",
    marginTop: "0.75rem", alignItems: "stretch"
  },
  column: {
    border: "1px solid #e2e8f0", borderRadius: "8px",
    padding: "0", backgroundColor: "#f8fafc", overflow: "hidden"
  },
  columnHeader: {
    margin: 0, padding: "0.6rem 0.75rem", backgroundColor: "#e2e8f0",
    fontSize: "0.9rem", fontWeight: "600", color: "#1a1a2e", borderBottom: "1px solid #cbd5e1"
  },
  diffLines: {
    maxHeight: "320px", overflowY: "auto", fontFamily: "monospace", fontSize: "0.8rem"
  },
  diffLine: {
    display: "flex", alignItems: "flex-start", gap: "0.75rem",
    padding: "0.45rem 0.75rem", borderBottom: "1px solid #e2e8f0",
    whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: "1.4"
  },
  lineNumber: {
    color: "#999", fontSize: "0.75rem", minWidth: "2.5rem",
    textAlign: "right", userSelect: "none", fontWeight: "500"
  },
  codeBlock: {
    whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "monospace",
    backgroundColor: "#fff", border: "1px solid #e2e8f0", borderRadius: "6px",
    padding: "0.6rem", maxHeight: "300px", overflowY: "auto", fontSize: "0.8rem"
  },
  codeBlockSmall: {
    whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "monospace",
    backgroundColor: "#f1f5f9", border: "1px solid #cbd5e1", borderRadius: "6px",
    padding: "0.5rem", maxHeight: "180px", overflowY: "auto", marginTop: "0.5rem", fontSize: "0.75rem"
  },
  fileInfo: {
    marginBottom: "1rem", padding: "0.75rem", backgroundColor: "#f0f9ff",
    border: "1px solid #bae6fd", borderRadius: "8px", display: "flex", alignItems: "center", gap: "0.75rem"
  },
  fileLink: {
    color: "#0369a1", textDecoration: "none", fontWeight: "600",
    padding: "0.4rem 0.8rem", backgroundColor: "#e0f2fe", borderRadius: "6px",
    border: "1px solid #0284c7", transition: "all 0.2s"
  },
  modalOverlay: {
    position: "fixed", inset: 0, backgroundColor: "rgba(0, 0, 0, 0.5)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
  },
  modal: {
    width: "min(95vw, 1000px)", maxHeight: "88vh", overflowY: "auto",
    backgroundColor: "#fff", borderRadius: "12px", padding: "1.5rem", boxShadow: "0 10px 40px rgba(0,0,0,0.3)"
  },
  modalHeader: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: "1rem", borderBottom: "2px solid #e5e7eb", paddingBottom: "0.75rem"
  },
  closeBtn: {
    border: "none", backgroundColor: "transparent", fontSize: "1.3rem",
    fontWeight: "700", cursor: "pointer", color: "#666"
  },
  modalBody: { display: "flex", flexDirection: "column", gap: "1rem" },
  manualSectionItem: {
    border: "1px solid #e2e8f0", borderRadius: "8px", padding: "0.75rem",
    backgroundColor: "#f9fafb", transition: "all 0.2s"
  },
  manualSectionHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" },
  manualSectionMeta: { color: "#666", fontSize: "0.8rem", fontWeight: "500" },
};
