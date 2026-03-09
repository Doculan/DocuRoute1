import { useState, useEffect } from "react";
import axios from "axios";

const TAG_COLORS = {
  POLICY: { bg: "#ebf8ff", color: "#2b6cb0" },
  PROCEDURE: { bg: "#f0fff4", color: "#276749" },
  RESPONSIBILITY: { bg: "#fff5f5", color: "#c53030" },
  "WORKING INSTRUCTION": { bg: "#fffff0", color: "#744210" },
  UNTAGGED: { bg: "#f7f8fc", color: "#666" },
};

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function computeDiff(oldText, newText) {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const result = [];
  const maxLen = Math.max(oldLines.length, newLines.length);
  for (let i = 0; i < maxLen; i++) {
    const o = oldLines[i] ?? null;
    const n = newLines[i] ?? null;
    if (o === n) {
      result.push({ type: "same", text: o });
    } else {
      if (o !== null) result.push({ type: "removed", text: o });
      if (n !== null) result.push({ type: "added", text: n });
    }
  }
  return result;
}

export default function Sections() {
  const [manuals, setManuals] = useState([]);
  const [selectedManual, setSelectedManual] = useState(null);
  const [sections, setSections] = useState([]);
  const [activeSection, setActiveSection] = useState(null);
  const [isFullDoc, setIsFullDoc] = useState(false); // ✅ full doc mode
  const [form, setForm] = useState({ subtitle: "", content: "", page_number: "", order: "" });
  const [showForm, setShowForm] = useState(false);
  const [editingSection, setEditingSection] = useState(null);
  const [editForm, setEditForm] = useState({ subtitle: "", content: "", page_number: "", order: "", tag: "" });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [diffLines, setDiffLines] = useState([]);
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    axios.get("http://127.0.0.1:8000/api/manuals/", getAuth())
      .then((res) => setManuals(res.data))
      .catch(console.error);
  }, []);

  const fetchSections = async (manualId) => {
    setLoading(true);
    setActiveSection(null);
    setIsFullDoc(false);
    setHistory([]);
    setShowDiff(false);
    try {
      const res = await axios.get(
        `http://127.0.0.1:8000/api/manuals/${manualId}/sections/`,
        getAuth()
      );
      setSections(res.data);
      // ✅ Default to full doc view on load
      if (res.data.length > 0) setIsFullDoc(true);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchHistory = async (sectionId) => {
    try {
      const res = await axios.get(
        `http://127.0.0.1:8000/api/sections/${sectionId}/history/`,
        getAuth()
      );
      setHistory(res.data);
      setSelectedVersion(res.data[res.data.length - 1]);
      setShowDiff(false);
      setDiffLines([]);
    } catch (err) {
      console.error(err);
      setHistory([]);
    }
  };

  const handleManualChange = (e) => {
    const id = e.target.value;
    if (!id) {
      setSelectedManual(null);
      setSections([]);
      setActiveSection(null);
      setIsFullDoc(false);
      return;
    }
    const manual = manuals.find((m) => m.id === parseInt(id));
    setSelectedManual(manual);
    fetchSections(id);
    setShowForm(false);
    setEditingSection(null);
  };

  const handleSectionClick = (s) => {
    setActiveSection(s);
    setIsFullDoc(false);
    setEditingSection(null);
    setShowDiff(false);
    setDiffLines([]);
    fetchHistory(s.id);
  };

  const handleVersionChange = (e) => {
    const ver = parseInt(e.target.value);
    const selected = history.find((h) => h.version === ver);
    setSelectedVersion(selected);
    const idx = history.indexOf(selected);
    if (idx > 0) {
      const prev = history[idx - 1];
      setDiffLines(computeDiff(prev.content, selected.content));
      setShowDiff(true);
    } else {
      setDiffLines([]);
      setShowDiff(false);
    }
  };

  const showMsg = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleCreateSection = async (e) => {
    e.preventDefault();
    if (!selectedManual) return;
    try {
      const res = await axios.post(
        `http://127.0.0.1:8000/api/manuals/${selectedManual.id}/sections/create/`,
        {
          subtitle: form.subtitle,
          content: form.content,
          page_number: form.page_number || null,
          order: form.order || 0,
        },
        getAuth()
      );
      showMsg(`✅ "${res.data.subtitle}" added — Tagged: ${res.data.tag}`);
      setForm({ subtitle: "", content: "", page_number: "", order: "" });
      setShowForm(false);
      await fetchSections(selectedManual.id);
    } catch (err) {
      showMsg(err.response?.data?.error || "❌ Failed to create section.");
    }
  };

  const handleEditClick = (section) => {
    setEditingSection(section.id);
    setEditForm({
      subtitle: section.subtitle,
      content: section.content,
      page_number: section.page_number || "",
      order: section.order,
      tag: section.tag,
    });
    setShowForm(false);
    setShowDiff(false);
    setIsFullDoc(false);
  };

  const handleEditSave = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.patch(
        `http://127.0.0.1:8000/api/sections/${editingSection}/update/`,
        {
          subtitle: editForm.subtitle,
          content: editForm.content,
          page_number: editForm.page_number || null,
          order: editForm.order,
        },
        getAuth()
      );
      showMsg(`✅ Section updated — v${res.data.version} — Re-tagged: ${res.data.tag}`);
      setEditingSection(null);
      await fetchSections(selectedManual.id);
    } catch (err) {
      showMsg(err.response?.data?.error || "❌ Failed to update section.");
    }
  };

  const handleDeleteSection = async (id, subtitle) => {
    if (!confirm(`Delete section "${subtitle}"?`)) return;
    try {
      await axios.delete(`http://127.0.0.1:8000/api/sections/${id}/delete/`, getAuth());
      showMsg("🗑️ Section deleted.");
      if (activeSection?.id === id) { setActiveSection(null); setIsFullDoc(true); }
      await fetchSections(selectedManual.id);
    } catch {
      showMsg("❌ Failed to delete.");
    }
  };

  return (
    <div style={styles.wrapper}>

      {/* ── Top Bar ── */}
      <div style={styles.topBar}>
        <h2 style={styles.pageTitle}>Manual Sections</h2>
        <div style={styles.topControls}>
          <select style={styles.select} onChange={handleManualChange} defaultValue="">
            <option value="">— Select a Manual —</option>
            {manuals.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title} ({m.department})
              </option>
            ))}
          </select>
          {selectedManual && (
            <button style={styles.addBtn} onClick={() => { setShowForm(!showForm); setEditingSection(null); }}>
              {showForm ? "✕ Cancel" : "+ Add Section"}
            </button>
          )}
        </div>
      </div>

      {/* ── Add Section Form ── */}
      {showForm && (
        <div style={styles.formCard}>
          <h4 style={{ margin: "0 0 1rem 0" }}>New Section for "{selectedManual?.title}"</h4>
          <form onSubmit={handleCreateSection} style={styles.form}>
            <input style={styles.input} placeholder="Section subtitle (e.g. 1.1 Purpose)"
              value={form.subtitle} onChange={(e) => setForm({ ...form, subtitle: e.target.value })} required />
            <textarea style={{ ...styles.input, minHeight: "120px", resize: "vertical" }}
              placeholder="Section content" value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })} />
            <div style={styles.formRow}>
              <input style={styles.input} type="number" placeholder="Page number (optional)"
                value={form.page_number} onChange={(e) => setForm({ ...form, page_number: e.target.value })} />
              <input style={styles.input} type="number" placeholder="Order (default 0)"
                value={form.order} onChange={(e) => setForm({ ...form, order: e.target.value })} />
            </div>
            <button style={styles.addBtn} type="submit">Save Section</button>
          </form>
        </div>
      )}

      {message && <div style={styles.toast}>{message}</div>}

      {/* ── Split View ── */}
      {!selectedManual ? (
        <div style={styles.empty}>Select a manual above to start reading or managing its sections.</div>
      ) : (
        <div style={styles.splitView}>

          {/* ── Left: TOC ── */}
          <div style={styles.toc}>
            <div style={styles.manualCard}>
              <div style={styles.manualTitle}>{selectedManual.title}</div>
              <div style={styles.manualDept}>🏢 {selectedManual.department}</div>
            </div>

            <div style={styles.tocLabel}>TABLE OF CONTENTS</div>

            {/* ✅ Full Document entry — always first */}
            {sections.length > 0 && (
              <div
                style={{
                  ...styles.tocItem,
                  backgroundColor: isFullDoc ? "#4f46e5" : "#f0f4ff",
                  color: isFullDoc ? "#fff" : "#4f46e5",
                  border: "1px solid #c7d2fe",
                  fontWeight: "700",
                }}
                onClick={() => { setIsFullDoc(true); setActiveSection(null); setEditingSection(null); setShowDiff(false); }}
              >
                <div style={styles.tocSubtitle}>📄 Full Document</div>
                <div style={{ fontSize: "0.75rem", marginTop: "0.2rem", opacity: 0.8 }}>
                  {sections.length} sections · scroll view
                </div>
              </div>
            )}

            {loading ? (
              <p style={styles.loadingText}>Loading...</p>
            ) : sections.length === 0 ? (
              <p style={styles.emptyToc}>No sections yet.</p>
            ) : (
              sections.map((s) => {
                const tc = TAG_COLORS[s.tag] || TAG_COLORS.UNTAGGED;
                const isActive = !isFullDoc && activeSection?.id === s.id;
                return (
                  <div key={s.id}
                    style={{ ...styles.tocItem, backgroundColor: isActive ? "#4f46e5" : "#fff", color: isActive ? "#fff" : "#333" }}
                    onClick={() => handleSectionClick(s)}
                  >
                    <div style={styles.tocSubtitle}>{s.subtitle}</div>
                    <div style={styles.tocMeta}>
                      <span style={{ ...styles.tag, backgroundColor: isActive ? "rgba(255,255,255,0.2)" : tc.bg, color: isActive ? "#fff" : tc.color }}>
                        {s.tag}
                      </span>
                      {s.version > 1 && (
                        <span style={{ ...styles.versionBadge, backgroundColor: isActive ? "rgba(255,255,255,0.2)" : "#fefcbf", color: isActive ? "#fff" : "#b7791f", border: isActive ? "1px solid rgba(255,255,255,0.4)" : "1px solid #f6e05e" }}>
                          v{s.version}
                        </span>
                      )}
                      {s.page_number && <span style={styles.pageNum}>p.{s.page_number}</span>}
                      <button style={styles.editBtn} onClick={(e) => { e.stopPropagation(); handleEditClick(s); setActiveSection(s); }} title="Edit">✏️</button>
                      <button style={styles.deleteBtn} onClick={(e) => { e.stopPropagation(); handleDeleteSection(s.id, s.subtitle); }} title="Delete">🗑️</button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* ── Right Panel ── */}
          <div style={styles.content}>

            {/* ✅ Full Document View */}
            {isFullDoc ? (
              <div>
                <div style={styles.contentHeader}>
                  <div>
                    <h3 style={styles.contentTitle}>📄 {selectedManual.title}</h3>
                    <p style={{ color: "#888", fontSize: "0.82rem", margin: "0.25rem 0 0 0" }}>
                      Full document · {sections.length} sections
                    </p>
                  </div>
                  <span style={{ ...styles.tag, backgroundColor: "#f0f4ff", color: "#4f46e5", fontSize: "0.8rem", padding: "0.3rem 0.8rem", border: "1px solid #c7d2fe" }}>
                    Read Only
                  </span>
                </div>
                <div style={styles.fullDocBody}>
                  {sections.map((s, idx) => (
                    <div key={s.id} style={styles.fullDocSection}>
                      {/* Section heading */}
                      <div style={styles.fullDocHeading}>
                        <span>{s.subtitle}</span>
                        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                          <span style={{ ...styles.tag, backgroundColor: (TAG_COLORS[s.tag] || TAG_COLORS.UNTAGGED).bg, color: (TAG_COLORS[s.tag] || TAG_COLORS.UNTAGGED).color }}>
                            {s.tag}
                          </span>
                          {s.version > 1 && (
                            <span style={styles.versionBadge2}>v{s.version}</span>
                          )}
                        </div>
                      </div>
                      {/* Section content */}
                      <div style={styles.fullDocContent}>
                        {s.content.split("\n").filter(l => l.trim()).map((line, i) => (
                          <p key={i} style={styles.contentParagraph}>{line}</p>
                        ))}
                      </div>
                      {idx < sections.length - 1 && <hr style={styles.sectionDivider} />}
                    </div>
                  ))}
                </div>
              </div>

            ) : editingSection ? (
              // ── Edit Form ──
              <div>
                <div style={styles.contentHeader}>
                  <h3 style={styles.contentTitle}>✏️ Editing Section</h3>
                  <button style={{ ...styles.addBtn, backgroundColor: "#718096" }} onClick={() => setEditingSection(null)}>✕ Cancel</button>
                </div>
                <form onSubmit={handleEditSave} style={{ ...styles.form, marginTop: "1rem" }}>
                  <div style={styles.inputGroup}>
                    <label style={styles.label}>Subtitle</label>
                    <input style={styles.input} value={editForm.subtitle}
                      onChange={(e) => setEditForm({ ...editForm, subtitle: e.target.value })} required />
                  </div>
                  <div style={styles.inputGroup}>
                    <label style={styles.label}>Content</label>
                    <textarea style={{ ...styles.input, minHeight: "300px", resize: "vertical" }}
                      value={editForm.content} onChange={(e) => setEditForm({ ...editForm, content: e.target.value })} />
                  </div>
                  <div style={styles.formRow}>
                    <div style={styles.inputGroup}>
                      <label style={styles.label}>Page Number</label>
                      <input style={styles.input} type="number" value={editForm.page_number}
                        onChange={(e) => setEditForm({ ...editForm, page_number: e.target.value })} />
                    </div>
                    <div style={styles.inputGroup}>
                      <label style={styles.label}>Order</label>
                      <input style={styles.input} type="number" value={editForm.order}
                        onChange={(e) => setEditForm({ ...editForm, order: e.target.value })} />
                    </div>
                  </div>
                  <p style={{ fontSize: "0.8rem", color: "#888", margin: "0" }}>
                    💡 Tag will be automatically re-assigned by the SVM model on save.
                  </p>
                  <button style={styles.addBtn} type="submit">💾 Save Changes</button>
                </form>
              </div>

            ) : !activeSection ? (
              <div style={styles.contentEmpty}>
                <div style={{ fontSize: "3rem" }}>👈</div>
                <p>Select a section from the table of contents to read it.</p>
              </div>

            ) : (
              // ── Single Section Read + Diff View ──
              <div>
                <div style={styles.contentHeader}>
                  <div>
                    <h3 style={styles.contentTitle}>{activeSection.subtitle}</h3>
                    {activeSection.version > 1 && (
                      <div style={styles.versionBanner}>
                        📝 This section has been revised — <strong>Version {activeSection.version}</strong>
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ ...styles.tag, backgroundColor: (TAG_COLORS[activeSection.tag] || TAG_COLORS.UNTAGGED).bg, color: (TAG_COLORS[activeSection.tag] || TAG_COLORS.UNTAGGED).color, fontSize: "0.85rem", padding: "0.3rem 0.8rem" }}>
                      {activeSection.tag}
                    </span>
                    {activeSection.version > 1 && (
                      <span style={styles.versionBadgeLarge}>v{activeSection.version}</span>
                    )}
                    <button style={styles.addBtn} onClick={() => handleEditClick(activeSection)}>✏️ Edit</button>
                  </div>
                </div>

                {history.length > 1 && (
                  <div style={styles.versionBar}>
                    <label style={styles.versionLabel}>🕓 View Version:</label>
                    <select style={styles.versionSelect} value={selectedVersion?.version ?? ""} onChange={handleVersionChange}>
                      {history.map((h) => (
                        <option key={h.version} value={h.version}>
                          {h.version === activeSection.version
                            ? `v${h.version} — Current`
                            : `v${h.version} — ${h.edited_by} (${h.edited_at ? new Date(h.edited_at).toLocaleDateString() : ""})`
                          }
                        </option>
                      ))}
                    </select>
                    {showDiff && (
                      <button style={{ ...styles.addBtn, backgroundColor: "#718096", fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
                        onClick={() => { setShowDiff(false); setSelectedVersion(history[history.length - 1]); }}>
                        ✕ Clear Diff
                      </button>
                    )}
                  </div>
                )}

                {activeSection.page_number && !showDiff && (
                  <p style={styles.pageLabel}>Page {activeSection.page_number}</p>
                )}

                {showDiff ? (
                  <div style={styles.diffContainer}>
                    <div style={styles.diffLegend}>
                      <span style={styles.diffAdded}>■ Added</span>
                      <span style={styles.diffRemoved}>■ Removed</span>
                      <span style={styles.diffSame}>■ Unchanged</span>
                    </div>
                    <div style={styles.diffBody}>
                      {diffLines.map((line, i) => (
                        <p key={i} style={{
                          ...styles.diffLine,
                          backgroundColor: line.type === "added" ? "#f0fff4" : line.type === "removed" ? "#fff5f5" : "transparent",
                          color: line.type === "added" ? "#276749" : line.type === "removed" ? "#c53030" : "#333",
                          textDecoration: line.type === "removed" ? "line-through" : "none",
                          borderLeft: line.type === "added" ? "3px solid #48bb78" : line.type === "removed" ? "3px solid #fc8181" : "3px solid transparent",
                        }}>
                          <span style={styles.diffMarker}>
                            {line.type === "added" ? "+" : line.type === "removed" ? "−" : " "}
                          </span>
                          {line.text}
                        </p>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div style={styles.contentBody}>
                    {(selectedVersion?.content ?? activeSection.content)
                      .split("\n").filter(l => l.trim()).map((line, i) => (
                        <p key={i} style={styles.contentParagraph}>{line}</p>
                      ))}
                  </div>
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
  wrapper: { display: "flex", flexDirection: "column", height: "100%" },
  topBar: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem", flexWrap: "wrap", gap: "0.75rem" },
  pageTitle: { margin: 0, color: "#1a1a2e", fontSize: "1.4rem", fontWeight: "700" },
  topControls: { display: "flex", gap: "0.75rem", alignItems: "center" },
  select: { padding: "0.6rem 1rem", borderRadius: "8px", border: "1px solid #ddd", fontSize: "0.95rem", minWidth: "280px", outline: "none" },
  addBtn: { padding: "0.6rem 1.2rem", backgroundColor: "#4f46e5", color: "#fff", border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "0.9rem" },
  formCard: { backgroundColor: "#fff", borderRadius: "10px", padding: "1.5rem", marginBottom: "1rem", boxShadow: "0 2px 8px rgba(0,0,0,0.07)" },
  form: { display: "flex", flexDirection: "column", gap: "0.75rem" },
  formRow: { display: "flex", gap: "0.75rem" },
  inputGroup: { display: "flex", flexDirection: "column", gap: "0.3rem", flex: 1 },
  label: { fontSize: "0.82rem", fontWeight: "600", color: "#555" },
  input: { padding: "0.7rem 1rem", borderRadius: "8px", border: "1px solid #ddd", fontSize: "0.95rem", outline: "none", width: "100%", boxSizing: "border-box" },
  toast: { backgroundColor: "#ebf8ff", border: "1px solid #bee3f8", borderRadius: "8px", padding: "0.75rem 1rem", marginBottom: "1rem", color: "#2b6cb0", fontWeight: "500" },
  empty: { textAlign: "center", padding: "4rem", color: "#888", backgroundColor: "#fff", borderRadius: "10px" },
  splitView: { display: "flex", gap: "1rem", flex: 1, minHeight: "500px" },
  toc: { width: "280px", minWidth: "280px", display: "flex", flexDirection: "column", gap: "0.5rem", overflowY: "auto" },
  manualCard: { backgroundColor: "#1a1a2e", borderRadius: "10px", padding: "1rem", marginBottom: "0.5rem" },
  manualTitle: { color: "#fff", fontWeight: "700", fontSize: "1rem" },
  manualDept: { color: "#8888aa", fontSize: "0.8rem", marginTop: "0.25rem" },
  tocLabel: { fontSize: "0.7rem", fontWeight: "700", color: "#aaa", letterSpacing: "1px", padding: "0.25rem 0" },
  tocItem: { padding: "0.75rem 1rem", borderRadius: "8px", cursor: "pointer", border: "1px solid #eee", transition: "all 0.15s" },
  tocSubtitle: { fontWeight: "600", fontSize: "0.88rem", marginBottom: "0.35rem" },
  tocMeta: { display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" },
  tag: { padding: "0.2rem 0.5rem", borderRadius: "20px", fontSize: "0.72rem", fontWeight: "600" },
  versionBadge: { padding: "0.2rem 0.5rem", borderRadius: "20px", fontSize: "0.72rem", fontWeight: "700" },
  versionBadge2: { padding: "0.2rem 0.5rem", borderRadius: "20px", fontSize: "0.72rem", fontWeight: "700", backgroundColor: "#fefcbf", color: "#b7791f", border: "1px solid #f6e05e" },
  versionBadgeLarge: { padding: "0.3rem 0.8rem", borderRadius: "20px", fontSize: "0.82rem", fontWeight: "700", backgroundColor: "#fefcbf", color: "#b7791f", border: "1px solid #f6e05e" },
  versionBanner: { marginTop: "0.35rem", fontSize: "0.8rem", color: "#b7791f", backgroundColor: "#fffff0", border: "1px solid #f6e05e", borderRadius: "6px", padding: "0.35rem 0.75rem", display: "inline-block" },
  pageNum: { fontSize: "0.75rem", color: "#aaa" },
  editBtn: { background: "none", border: "none", cursor: "pointer", fontSize: "0.85rem", padding: "0", marginLeft: "auto" },
  deleteBtn: { background: "none", border: "none", cursor: "pointer", fontSize: "0.85rem", padding: "0" },
  loadingText: { color: "#888", textAlign: "center", padding: "1rem" },
  emptyToc: { color: "#aaa", fontSize: "0.85rem", textAlign: "center", padding: "1rem" },
  content: { flex: 1, backgroundColor: "#fff", borderRadius: "10px", padding: "1.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", overflowY: "auto" },
  contentEmpty: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "#aaa", textAlign: "center" },
  contentHeader: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "0.5rem", flexWrap: "wrap", gap: "0.5rem" },
  contentTitle: { margin: 0, color: "#1a1a2e", fontSize: "1.2rem" },
  pageLabel: { color: "#aaa", fontSize: "0.8rem", margin: "0 0 1rem 0" },
  // ✅ Full doc styles
  fullDocBody: { marginTop: "1rem", overflowY: "auto" },
  fullDocSection: { marginBottom: "1.5rem" },
  fullDocHeading: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.6rem 0.75rem", backgroundColor: "#f7f8fc", borderRadius: "6px", marginBottom: "0.75rem", fontWeight: "700", fontSize: "0.95rem", color: "#1a1a2e", border: "1px solid #e2e8f0" },
  fullDocContent: { paddingLeft: "0.5rem" },
  sectionDivider: { border: "none", borderTop: "1px dashed #e2e8f0", margin: "1.5rem 0" },
  versionBar: { display: "flex", alignItems: "center", gap: "0.75rem", margin: "0.75rem 0", padding: "0.75rem 1rem", backgroundColor: "#f7f8fc", borderRadius: "8px", border: "1px solid #e2e8f0", flexWrap: "wrap" },
  versionLabel: { fontSize: "0.85rem", fontWeight: "600", color: "#555" },
  versionSelect: { padding: "0.4rem 0.8rem", borderRadius: "6px", border: "1px solid #ddd", fontSize: "0.85rem", outline: "none", cursor: "pointer" },
  diffContainer: { marginTop: "1rem" },
  diffLegend: { display: "flex", gap: "1.5rem", marginBottom: "0.75rem", fontSize: "0.8rem", fontWeight: "600" },
  diffAdded: { color: "#276749" },
  diffRemoved: { color: "#c53030" },
  diffSame: { color: "#aaa" },
  diffBody: { fontFamily: "monospace", fontSize: "0.9rem", lineHeight: "1.8", borderRadius: "8px", border: "1px solid #e2e8f0", overflow: "hidden" },
  diffLine: { margin: 0, padding: "0.2rem 1rem", wordBreak: "break-word" },
  diffMarker: { display: "inline-block", width: "1.2rem", fontWeight: "700" },
  contentBody: { fontSize: "0.95rem", lineHeight: "1.9", color: "#333", borderTop: "1px solid #f0f0f0", paddingTop: "1rem", maxWidth: "720px" },
  contentParagraph: { margin: "0 0 1rem 0", textAlign: "justify", wordBreak: "break-word" },
};
