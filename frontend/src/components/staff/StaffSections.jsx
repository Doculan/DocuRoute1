import { useState, useEffect, useRef } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";

const TAG_COLORS = {
  POLICY:               { bg: "#ebf8ff", color: "#2b6cb0", border: "#90cdf4" },
  PROCEDURE:            { bg: "#f0fff4", color: "#276749", border: "#9ae6b4" },
  RESPONSIBILITY:       { bg: "#fff5f5", color: "#c53030", border: "#feb2b2" },
  "WORKING INSTRUCTION":{ bg: "#fffff0", color: "#744210", border: "#faf089" },
  UNTAGGED:             { bg: "#f7f8fc", color: "#718096", border: "#e2e8f0" },
};

const STATUS_COLORS = {
  pending:  { bg: "#fffbeb", color: "#b45309", border: "#fcd34d" },
  approved: { bg: "#f0fff4", color: "#276749", border: "#9ae6b4" },
  rejected: { bg: "#fff5f5", color: "#c53030", border: "#feb2b2" },
};

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function parseRow(line) {
  if (!line.includes("|")) return null;
  const cells = line.split("|").map((c) => c.trim()).filter((c) => c.length > 0);
  return cells.length >= 2 ? cells : null;
}

function SectionContent({ content }) {
  const cleaned = (content || "")
    .replace(/\|\|TABLE_START\|\|/g, "")
    .replace(/\|\|TABLE_END\|\|/g, "");

  const lines = cleaned.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  const blocks = [];
  let tableRows = [];
  let inTable = false;
  let lastRow = null;

  const flushTable = () => {
    if (tableRows.length > 0) {
      blocks.push({ type: "table", rows: tableRows });
      tableRows = [];
      lastRow = null;
    }
    inTable = false;
  };

  lines.forEach((line) => {
    const row = parseRow(line);
    if (row) {
      inTable = true;
      tableRows.push(row);
      lastRow = row;
      return;
    }
    if (inTable && lastRow && !row) {
      // continuation of last cell
      lastRow[lastRow.length - 1] = `${lastRow[lastRow.length - 1]} ${line}`.trim();
      return;
    }
    flushTable();
    blocks.push({ type: "text", text: line });
  });
  flushTable();

  return (
    <div style={{ fontSize: "0.93rem", lineHeight: "1.8", color: "#333" }}>
      {blocks.map((block, idx) => {
        if (block.type === "table") {
          return (
            <table key={idx} style={{ width: "100%", borderCollapse: "collapse", marginBottom: "1.2rem", tableLayout: "fixed", fontSize: "0.9rem" }}>
              <colgroup>
                {block.rows[0]?.length === 2 ? (
                  <><col style={{ width: "25%" }} /><col style={{ width: "75%" }} /></>
                ) : null}
              </colgroup>
              <tbody>
                {block.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td key={ci} style={{
                        border: "1px solid #d1d5db",
                        padding: "0.55rem 0.8rem",
                        verticalAlign: "top",
                        backgroundColor: ri === 0 ? "#e8eaf6" : ci === 0 ? "#f8f9ff" : "#fff",
                        fontWeight: ri === 0 ? "700" : ci === 0 ? "600" : "400",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        lineHeight: "1.6",
                      }}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        return (
          <p key={idx} style={{ margin: "0 0 0.6rem 0", textAlign: "justify", wordBreak: "break-word" }}>
            {block.text}
          </p>
        );
      })}
    </div>
  );
}

export default function StaffSections({ manualId, onBack }) {
  const [manual, setManual]           = useState(null);
  const [sections, setSections]       = useState([]);
  const [activeSection, setActive]    = useState(null);
  const [isFullDoc, setIsFullDoc]     = useState(false);
  const [loading, setLoading]         = useState(true);
  const [fileUrl, setFileUrl]         = useState(null);
  const [showOriginal, setShowOriginal] = useState(false);

  // Revision submit
  const [showRevForm, setShowRevForm] = useState(false);
  const [revFile, setRevFile]         = useState(null);
  const [revNote, setRevNote]         = useState("");
  const [revLoading, setRevLoading]   = useState(false);
  const [revMsg, setRevMsg]           = useState("");
  const [revMsgType, setRevMsgType]   = useState("success");
  const fileInputRef                  = useRef();

  // My revisions for this section
  const [sectionRevisions, setSectionRevisions] = useState([]);
  const [revTab, setRevTab]           = useState("content"); // "content" | "revisions"

  useEffect(() => {
    loadSections();
  }, [manualId]);

  const loadSections = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${BASE_URL}/api/manuals/${manualId}/sections/`, getAuth());
      setSections(res.data.sections || []);
      setFileUrl(res.data.file_url ? `${BASE_URL}${res.data.file_url}` : null);
      // Try to derive manual title from first section
      if (res.data.sections?.length > 0) {
        setManual({ version: res.data.manual_version });
      }
      if ((res.data.sections || []).length > 0) {
        setIsFullDoc(true);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectSection = (s) => {
    setActive(s);
    setIsFullDoc(false);
    setShowRevForm(false);
    setRevMsg("");
    setRevFile(null);
    setRevTab("content");
    loadSectionRevisions(s.id);
  };

  const loadSectionRevisions = async (sectionId) => {
    try {
      const res = await axios.get(`${BASE_URL}/api/staff/revisions/`, getAuth());
      const mine = res.data.filter((r) => r.section_id === sectionId);
      setSectionRevisions(mine);
    } catch {
      setSectionRevisions([]);
    }
  };

  const handleSubmitRevision = async (e) => {
    e.preventDefault();
    if (!revFile) { setRevMsg("Please select a file."); setRevMsgType("error"); return; }
    setRevLoading(true);
    setRevMsg("");
    const formData = new FormData();
    formData.append("file", revFile);
    try {
      await axios.post(
        `${BASE_URL}/api/revisions/upload/${activeSection.id}/`,
        formData,
        { headers: { ...getAuth().headers, "Content-Type": "multipart/form-data" } }
      );
      setRevMsg("Revision submitted successfully. An admin will review it.");
      setRevMsgType("success");
      setRevFile(null);
      setRevNote("");
      setShowRevForm(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      loadSectionRevisions(activeSection.id);
    } catch (err) {
      const msg = err.response?.data?.error || "Submission failed. Try again.";
      setRevMsg(msg);
      setRevMsgType("error");
    } finally {
      setRevLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={styles.loadingWrap}>
        <div style={styles.spinner} />
        <p style={{ color: "#888", marginTop: "1rem" }}>Loading sections...</p>
      </div>
    );
  }

  const pendingCount = sectionRevisions.filter((r) => r.status === "pending").length;

  return (
    <div style={styles.wrapper}>
      {/* ── Top bar ── */}
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>← Back to Manuals</button>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {fileUrl && (
            <button
              style={{ ...styles.actionBtn, backgroundColor: showOriginal ? "#4a47a3" : "#e8eaf6", color: showOriginal ? "#fff" : "#4a47a3" }}
              onClick={() => setShowOriginal((v) => !v)}
            >
              {showOriginal ? "Hide Original" : "View Original File"}
            </button>
          )}
        </div>
      </div>

      <div style={styles.splitView}>
        {/* ── Left: TOC ── */}
        <div style={styles.toc}>
          <div style={styles.manualCard}>
            <div style={styles.manualCardTitle}>Table of Contents</div>
            {manual && <div style={styles.manualCardMeta}>Document v{manual.version}</div>}
          </div>

          {/* Full document button */}
          {sections.length > 0 && (
            <div
              style={{
                ...styles.tocItem,
                backgroundColor: isFullDoc ? "#4a47a3" : "#eff2ff",
                color: isFullDoc ? "#fff" : "#4a47a3",
                fontWeight: "700",
                border: "1px solid #c7d2fe",
              }}
              onClick={() => { setIsFullDoc(true); setActive(null); setShowRevForm(false); }}
            >
              📄 Full Document
              <span style={{ fontSize: "0.75rem", opacity: 0.8, display: "block", marginTop: "0.1rem" }}>
                {sections.length} sections
              </span>
            </div>
          )}

          {/* Section list */}
          {sections.length === 0 ? (
            <p style={styles.emptyToc}>No sections available.</p>
          ) : (
            sections.map((s) => {
              const tc = TAG_COLORS[s.tag] || TAG_COLORS.UNTAGGED;
              const isActive = !isFullDoc && activeSection?.id === s.id;
              return (
                <div
                  key={s.id}
                  style={{
                    ...styles.tocItem,
                    backgroundColor: isActive ? "#4a47a3" : "#fff",
                    color: isActive ? "#fff" : "#1a1a2e",
                    borderLeft: isActive ? "3px solid #48bb78" : "3px solid transparent",
                  }}
                  onClick={() => handleSelectSection(s)}
                >
                  <div style={{ fontWeight: "600", fontSize: "0.87rem", marginBottom: "0.3rem" }}>
                    {s.subtitle}
                  </div>
                  <span style={{
                    ...styles.tag,
                    backgroundColor: isActive ? "rgba(255,255,255,0.25)" : tc.bg,
                    color: isActive ? "#fff" : tc.color,
                    border: `1px solid ${isActive ? "rgba(255,255,255,0.4)" : tc.border}`,
                  }}>
                    {s.tag}
                  </span>
                  {s.page_number && (
                    <span style={{ ...styles.pageNum, color: isActive ? "rgba(255,255,255,0.7)" : "#aaa" }}>
                      p.{s.page_number}
                    </span>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* ── Right: Content panel ── */}
        <div style={styles.contentPanel}>
          {showOriginal && fileUrl ? (
            <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                <strong style={{ color: "#1a1a2e" }}>Original Document</strong>
                <button style={{ ...styles.actionBtn, fontSize: "0.8rem", padding: "0.3rem 0.7rem" }} onClick={() => setShowOriginal(false)}>✕ Close</button>
              </div>
              <iframe src={fileUrl} style={{ flex: 1, border: "none", borderRadius: "8px" }} title="Original PDF" />
            </div>
          ) : isFullDoc ? (
            <div>
              <h2 style={styles.contentTitle}>Full Document</h2>
              <p style={styles.contentMeta}>{sections.length} sections</p>
              {sections.map((s, idx) => {
                const tc = TAG_COLORS[s.tag] || TAG_COLORS.UNTAGGED;
                return (
                  <div key={s.id} style={styles.fullDocSection}>
                    <div style={styles.fullDocHeading}>
                      <span>{s.subtitle}</span>
                      <span style={{ ...styles.tag, backgroundColor: tc.bg, color: tc.color, border: `1px solid ${tc.border}` }}>
                        {s.tag}
                      </span>
                    </div>
                    <div style={{ paddingLeft: "0.5rem" }}>
                      <SectionContent content={s.content} />
                    </div>
                    {idx < sections.length - 1 && <hr style={{ border: "none", borderTop: "1px dashed #e2e8f0", margin: "1.5rem 0" }} />}
                  </div>
                );
              })}
            </div>
          ) : !activeSection ? (
            <div style={styles.emptyContent}>
              <div style={{ fontSize: "3rem" }}>👈</div>
              <p>Select a section from the left to read its content.</p>
            </div>
          ) : (
            <div>
              {/* Section header */}
              <div style={styles.sectionHeader}>
                <div>
                  <h2 style={styles.contentTitle}>{activeSection.subtitle}</h2>
                  <span style={{
                    ...styles.tag,
                    backgroundColor: (TAG_COLORS[activeSection.tag] || TAG_COLORS.UNTAGGED).bg,
                    color: (TAG_COLORS[activeSection.tag] || TAG_COLORS.UNTAGGED).color,
                    border: `1px solid ${(TAG_COLORS[activeSection.tag] || TAG_COLORS.UNTAGGED).border}`,
                    fontSize: "0.82rem",
                    padding: "0.3rem 0.8rem",
                  }}>
                    {activeSection.tag}
                  </span>
                  {activeSection.page_number && (
                    <span style={{ color: "#aaa", fontSize: "0.8rem", marginLeft: "0.75rem" }}>
                      Page {activeSection.page_number}
                    </span>
                  )}
                </div>
                <button
                  style={{ ...styles.actionBtn, backgroundColor: "#4a47a3", color: "#fff" }}
                  onClick={() => { setShowRevForm((v) => !v); setRevMsg(""); }}
                >
                  {showRevForm ? "✕ Cancel" : "📤 Submit Revision"}
                </button>
              </div>

              {/* Revision success/error message */}
              {revMsg && (
                <div style={{
                  padding: "0.75rem 1rem",
                  borderRadius: "8px",
                  marginBottom: "1rem",
                  backgroundColor: revMsgType === "success" ? "#f0fff4" : "#fff5f5",
                  color: revMsgType === "success" ? "#276749" : "#c53030",
                  border: `1px solid ${revMsgType === "success" ? "#9ae6b4" : "#feb2b2"}`,
                  fontSize: "0.9rem",
                }}>
                  {revMsgType === "success" ? "✅ " : "❌ "}{revMsg}
                </div>
              )}

              {/* Revision submit form */}
              {showRevForm && (
                <div style={styles.revForm}>
                  <h4 style={{ margin: "0 0 0.75rem 0", color: "#1a1a2e", fontSize: "1rem" }}>
                    Submit a Revision for "{activeSection.subtitle}"
                  </h4>
                  <p style={{ color: "#666", fontSize: "0.85rem", margin: "0 0 1rem 0" }}>
                    Upload a PDF or DOCX file with your proposed changes. An admin will review and approve it.
                  </p>
                  <form onSubmit={handleSubmitRevision} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                    <div>
                      <label style={styles.formLabel}>Revised File (PDF or DOCX)</label>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".pdf,.docx,.doc,.txt"
                        onChange={(e) => setRevFile(e.target.files[0])}
                        style={styles.fileInput}
                        required
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={revLoading}
                      style={{ ...styles.actionBtn, backgroundColor: revLoading ? "#999" : "#276749", color: "#fff", padding: "0.65rem 1.2rem", fontSize: "0.95rem" }}
                    >
                      {revLoading ? "Submitting..." : "Submit Revision"}
                    </button>
                  </form>
                </div>
              )}

              {/* Content / Revisions tabs */}
              <div style={styles.tabBar}>
                <button
                  style={{ ...styles.tab, ...(revTab === "content" ? styles.tabActive : {}) }}
                  onClick={() => setRevTab("content")}
                >
                  Content
                </button>
                <button
                  style={{ ...styles.tab, ...(revTab === "revisions" ? styles.tabActive : {}) }}
                  onClick={() => setRevTab("revisions")}
                >
                  My Revisions
                  {pendingCount > 0 && (
                    <span style={styles.badge}>{pendingCount}</span>
                  )}
                </button>
              </div>

              {revTab === "content" ? (
                <div style={{ marginTop: "0.75rem" }}>
                  <SectionContent content={activeSection.content} />
                </div>
              ) : (
                <div style={{ marginTop: "0.75rem" }}>
                  {sectionRevisions.length === 0 ? (
                    <div style={styles.emptyRevisions}>
                      <p>No revisions submitted for this section yet.</p>
                      <button
                        style={{ ...styles.actionBtn, backgroundColor: "#4a47a3", color: "#fff", marginTop: "0.5rem" }}
                        onClick={() => { setShowRevForm(true); setRevTab("content"); }}
                      >
                        Submit your first revision
                      </button>
                    </div>
                  ) : (
                    sectionRevisions.map((r) => {
                      const sc = STATUS_COLORS[r.status] || STATUS_COLORS.pending;
                      return (
                        <div key={r.id} style={{ ...styles.revCard, borderLeft: `4px solid ${sc.border}` }}>
                          <div style={styles.revCardHeader}>
                            <span style={{ ...styles.statusBadge, backgroundColor: sc.bg, color: sc.color, border: `1px solid ${sc.border}` }}>
                              {r.status.toUpperCase()}
                            </span>
                            <span style={{ color: "#aaa", fontSize: "0.8rem" }}>
                              {new Date(r.submitted_at).toLocaleString()}
                            </span>
                          </div>
                          {r.reviewer_notes && (
                            <div style={styles.revNotes}>
                              <strong>Admin notes:</strong> {r.reviewer_notes}
                            </div>
                          )}
                          {r.diff_preview && (
                            <pre style={styles.diffPreview}>{r.diff_preview}</pre>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const styles = {
  wrapper:        { display: "flex", flexDirection: "column", height: "100%" },
  loadingWrap:    { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh" },
  spinner:        { width: "36px", height: "36px", border: "3px solid #e2e8f0", borderTop: "3px solid #4a47a3", borderRadius: "50%", animation: "spin 0.8s linear infinite" },
  topBar:         { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" },
  backBtn:        { padding: "0.5rem 1rem", backgroundColor: "#e8eaf6", color: "#4a47a3", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "0.9rem" },
  actionBtn:      { padding: "0.5rem 1rem", backgroundColor: "#e8eaf6", color: "#4a47a3", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "0.85rem" },
  splitView:      { display: "flex", gap: "1rem", flex: 1, minHeight: "0", overflow: "hidden" },
  toc:            { width: "270px", minWidth: "270px", display: "flex", flexDirection: "column", gap: "0.4rem", overflowY: "auto" },
  manualCard:     { backgroundColor: "#090749", borderRadius: "10px", padding: "1rem", marginBottom: "0.5rem" },
  manualCardTitle:{ color: "#fff", fontWeight: "700", fontSize: "0.95rem" },
  manualCardMeta: { color: "#a5b4fc", fontSize: "0.75rem", marginTop: "0.3rem" },
  tocItem:        { padding: "0.7rem 0.9rem", borderRadius: "8px", cursor: "pointer", border: "1px solid #eee", transition: "all 0.15s" },
  emptyToc:       { color: "#aaa", fontSize: "0.85rem", textAlign: "center", padding: "1rem" },
  tag:            { display: "inline-block", padding: "0.15rem 0.5rem", borderRadius: "20px", fontSize: "0.71rem", fontWeight: "600" },
  pageNum:        { fontSize: "0.73rem", marginLeft: "0.4rem" },
  contentPanel:   { flex: 1, backgroundColor: "#fff", borderRadius: "10px", padding: "1.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", overflowY: "auto" },
  emptyContent:   { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60%", color: "#aaa", textAlign: "center" },
  sectionHeader:  { display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" },
  contentTitle:   { margin: "0 0 0.3rem 0", color: "#1a1a2e", fontSize: "1.2rem", fontWeight: "700" },
  contentMeta:    { color: "#aaa", fontSize: "0.82rem", margin: "0 0 1.5rem 0" },
  revForm:        { backgroundColor: "#f8f9ff", borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem", border: "1px solid #c7d2fe" },
  formLabel:      { display: "block", fontSize: "0.82rem", fontWeight: "600", color: "#555", marginBottom: "0.4rem" },
  fileInput:      { width: "100%", padding: "0.5rem", border: "1px solid #ddd", borderRadius: "6px", fontSize: "0.9rem", boxSizing: "border-box" },
  tabBar:         { display: "flex", gap: "0.25rem", borderBottom: "2px solid #e2e8f0", marginBottom: "0.5rem" },
  tab:            { padding: "0.5rem 1rem", backgroundColor: "transparent", border: "none", cursor: "pointer", fontSize: "0.87rem", fontWeight: "500", color: "#718096", borderBottom: "2px solid transparent", marginBottom: "-2px" },
  tabActive:      { color: "#4a47a3", fontWeight: "700", borderBottom: "2px solid #4a47a3" },
  badge:          { display: "inline-block", marginLeft: "0.4rem", backgroundColor: "#e53e3e", color: "#fff", borderRadius: "20px", fontSize: "0.7rem", padding: "0.1rem 0.45rem", fontWeight: "700" },
  fullDocSection: { marginBottom: "2rem" },
  fullDocHeading: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.6rem 0.75rem", backgroundColor: "#f7f8fc", borderRadius: "6px", marginBottom: "0.75rem", fontWeight: "700", fontSize: "0.93rem", color: "#1a1a2e", border: "1px solid #e2e8f0" },
  revCard:        { backgroundColor: "#fff", borderRadius: "8px", padding: "1rem", marginBottom: "0.75rem", border: "1px solid #e2e8f0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" },
  revCardHeader:  { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" },
  statusBadge:    { padding: "0.2rem 0.7rem", borderRadius: "20px", fontSize: "0.75rem", fontWeight: "700" },
  revNotes:       { fontSize: "0.85rem", color: "#555", backgroundColor: "#f7f8fc", borderRadius: "6px", padding: "0.5rem 0.75rem", marginBottom: "0.5rem" },
  diffPreview:    { fontSize: "0.78rem", backgroundColor: "#1a1a2e", color: "#a5b4fc", padding: "0.75rem", borderRadius: "6px", overflow: "auto", maxHeight: "200px", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 },
  emptyRevisions: { textAlign: "center", padding: "2rem", color: "#888" },
};
