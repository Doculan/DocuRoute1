import React, { useState, useEffect } from "react";
import axios from "axios";

const formatOCRContent = (content = "") => {
  return content
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&nbsp;/gi, " ")
    .replace(//g, "•")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
};

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
    const o = oldLines[i] ?? "";
    const n = newLines[i] ?? "";
    if (o === n) {
      result.push({ type: "same", old: o, new: n });
    } else if (o && !n) {
      result.push({ type: "removed", old: o, new: "" });
    } else if (!o && n) {
      result.push({ type: "added", old: "", new: n });
    } else {
      result.push({ type: "changed", old: o, new: n });
    }
  }
  return result;
}

function parseRow(line) {
  // Parse a pipe-delimited table row like "Cell A | Cell B | Cell C"
  // Returns an array of non-empty cell strings, or null if not a valid table row.
  if (!line.includes("|")) return null;
  const cells = line.split("|").map((c) => c.trim()).filter((c) => c.length > 0);
  // Must have at least 2 real cells (guards against ||TABLE_START|| style markers)
  return cells.length >= 2 ? cells : null;
}

function renderSectionContent(content) {
  // Strip legacy TABLE_START/TABLE_END markers from old extractions
  const cleaned = content
    .replace(/\|\|TABLE_START\|\|/g, "")
    .replace(/\|\|TABLE_END\|\|/g, "");

  const lines = cleaned
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

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

  const isTableHeaderLine = (line) => /^(responsibility\s*\|\s*activity|activity|responsibility)$/i.test(line.replace(/\|/g, "").trim());

  // Regex to detect inline tags like "POLICY:", "PROCEDURE:", "RESPONSIBILITY:", etc
  const inlineTagRegex = /^(POLICY|PROCEDURE|RESPONSIBILITY|WORKING\s+INSTRUCTION|PREPARED\s+BY|APPROVED\s+BY|NOTED\s+BY|REVIEWED\s+BY)[\s:]*(.*)$/i;

  lines.forEach((line) => {
    const normalizedLine = line.replace(/\s+/g, " ").trim();

    if (isTableHeaderLine(normalizedLine)) {
      inTable = true;
      const headerRow = parseRow(normalizedLine);
      if (headerRow) {
        tableRows.push(headerRow);
        lastRow = headerRow;
      }
      return;
    }

    if (inTable) {
      const row = parseRow(line);
      if (row) {
        tableRows.push(row);
        lastRow = row;
        return;
      }

      if (lastRow) {
        // Append continuation to the second cell at least
        lastRow[1] = `${lastRow[1]} ${line}`.trim();
        return;
      }

      flushTable();
    }

    // If a line looks like it can be the start of a table row even if we were not in table yet
    const potentialRow = parseRow(line);
    if (potentialRow) {
      inTable = true;
      tableRows.push(potentialRow);
      lastRow = potentialRow;
      return;
    }

    flushTable();
    // Check if line has inline tag and render with special formatting
    const tagMatch = line.match(inlineTagRegex);
    if (tagMatch) {
      const tag = tagMatch[1];
      const content = tagMatch[2];
      blocks.push({ 
        type: "inline-tagged", 
        tag: tag.toUpperCase(),
        content: content.trim() 
      });
    } else {
      blocks.push({ type: "text", text: line });
    }
  });

  flushTable();

  return blocks.map((block, idx) => {
    if (block.type === "table") {
      return (
        <table
          key={idx}
          style={{
            width: "100%",
            borderCollapse: "collapse",
            marginBottom: "1.5rem",
            tableLayout: "fixed",
            fontSize: "0.9rem",
          }}
        >
          <colgroup>
            {block.rows[0] && block.rows[0].length === 2 ? (
              <>
                <col style={{ width: "25%" }} />
                <col style={{ width: "75%" }} />
              </>
            ) : null}
          </colgroup>
          <tbody>
            {block.rows.map((row, rIndex) => (
              <tr key={rIndex}>
                {row.map((cell, cIndex) => (
                  <td
                    key={cIndex}
                    style={{
                      border: "1px solid #d1d5db",
                      padding: "0.6rem 0.8rem",
                      verticalAlign: "top",
                      backgroundColor: rIndex === 0 ? "#e8eaf6" : cIndex === 0 ? "#f8f9ff" : "#fff",
                      fontWeight: rIndex === 0 ? "700" : cIndex === 0 ? "600" : "400",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      lineHeight: "1.6",
                      color: rIndex === 0 ? "#1a1a2e" : "#333",
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    if (block.type === "inline-tagged") {
      // Render inline tagged sections with visual emphasis
      const tagColors = {
        POLICY: { bg: "#ebf8ff", color: "#2b6cb0", border: "#0084d4" },
        PROCEDURE: { bg: "#f0fff4", color: "#276749", border: "#10b981" },
        RESPONSIBILITY: { bg: "#fff5f5", color: "#c53030", border: "#f87171" },
        "WORKING INSTRUCTION": { bg: "#fffff0", color: "#744210", border: "#d97706" },
        "PREPARED BY": { bg: "#f5f3ff", color: "#6b21a8", border: "#d946ef" },
        "APPROVED BY": { bg: "#f5f3ff", color: "#6b21a8", border: "#d946ef" },
        "NOTED BY": { bg: "#f5f3ff", color: "#6b21a8", border: "#d946ef" },
        "REVIEWED BY": { bg: "#f5f3ff", color: "#6b21a8", border: "#d946ef" },
      };
      const colors = tagColors[block.tag] || { bg: "#f9fafb", color: "#374151", border: "#d1d5db" };
      
      return (
        <div
          key={idx}
          style={{
            marginBottom: "0.75rem",
            paddingLeft: "1rem",
            borderLeft: `4px solid ${colors.border}`,
            backgroundColor: colors.bg,
            padding: "0.75rem",
            borderRadius: "0.25rem",
          }}
        >
          <strong style={{ color: colors.color, display: "block", marginBottom: "0.25rem" }}>
            📌 {block.tag}
          </strong>
          <p style={{ margin: "0.5rem 0", lineHeight: "1.7", fontSize: "0.96rem", color: "#111827" }}>
            {block.content}
          </p>
        </div>
      );
    }

    return (
      <p key={idx} style={{ margin: "0.5rem 0", lineHeight: "1.7", fontSize: "0.96rem", color: "#111827" }}>
        {block.text}
      </p>
    );
  });
}

export default function Sections() {
  const [manuals, setManuals] = useState([]);
  const [selectedManual, setSelectedManual] = useState(null);
  const [sections, setSections] = useState([]);
  const [manualVersion, setManualVersion] = useState(1);
  const [manualRevision, setManualRevision] = useState(0);
  const [manualFileUrl, setManualFileUrl] = useState(null);
  const [showOriginal, setShowOriginal] = useState(false);
  const [activeSection, setActiveSection] = useState(null);
  const [isFullDoc, setIsFullDoc] = useState(false);
  const [form, setForm] = useState({ subtitle: "", content: "", page_number: "", order: "" });
  const [showForm, setShowForm] = useState(false);
  const [editingSection, setEditingSection] = useState(null);
  const [editForm, setEditForm] = useState({ subtitle: "", content: "", page_number: "", order: "", tag: "" });
  const [mergeSource, setMergeSource] = useState(null);
  const [mergeTarget, setMergeTarget] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [history, setHistory] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [diffLines, setDiffLines] = useState([]);
  const [showDiff, setShowDiff] = useState(false);
  const [expandedSections, setExpandedSections] = useState(new Set());  // ← NEW: Track expanded parent sections

  // Helper: Get all children for a parent section
  const getChildren = (parentId, allSections) => {
    return allSections.filter(s => s.parent_id === parentId);
  };

  const toggleExpandSection = (sectionId) => {
    setExpandedSections(prev => {
      const newSet = new Set(prev);
      if (newSet.has(sectionId)) {
        newSet.delete(sectionId);
      } else {
        newSet.add(sectionId);
      }
      return newSet;
    });
  };

  useEffect(() => {
    axios.get(`/api/manuals/`, getAuth())
      .then((res) => setManuals(res.data))
      .catch(console.error);
  }, []);

  const BACKEND_BASE_URL = "http://127.0.0.1:8000";

  const fetchSections = async (manualId) => {
    setLoading(true);
    setActiveSection(null);
    setIsFullDoc(false);
    setHistory([]);
    setShowDiff(false);
    setShowOriginal(false);
    try {
      const res = await axios.get(
        `/api/manuals/${manualId}/sections/`,
        getAuth()
      );
      const sectionList = res.data.sections;
      const docVersion = res.data.manual_version;
      const docRevision = res.data.manual_revision || 0;
      setSections(sectionList);
      setManualVersion(docVersion);
      setManualRevision(docRevision);
      setManualFileUrl(res.data.file_url ? `${BACKEND_BASE_URL}${res.data.file_url}` : null);
      if (sectionList.length > 0) setIsFullDoc(true);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchHistory = async (sectionId) => {
    setLoadingHistory(true);  // ← NEW: Show loading indicator
    try {
      const res = await axios.get(
        `/api/sections/${sectionId}/history/`,
        getAuth()
      );
      setHistory(res.data);
      setSelectedVersion(res.data[res.data.length - 1]);
      setShowDiff(false);
      setDiffLines([]);
    } catch (err) {
      console.error(err);
      setHistory([]);
      showMsg("❌ Failed to load section history.");
    } finally {
      setLoadingHistory(false);  // ← NEW: Clear loading state
    }
  };

  const handleManualChange = (e) => {
    const id = e.target.value;
    if (!id) {
      setSelectedManual(null);
      setSections([]);
      setManualVersion(1);
      setManualFileUrl(null);
      setActiveSection(null);
      setIsFullDoc(false);
      return;
    }
    const manual = manuals.find((m) => m.id === parseInt(id));
    setSelectedManual(manual);
    fetchSections(id);
    setShowForm(false);
    setEditingSection(null);
    setMergeSource(null);
    setMergeTarget(null);
  };

  const handleSectionClick = (s) => {
    setActiveSection(s);
    setIsFullDoc(false);
    setEditingSection(null);
    setShowDiff(false);
    setDiffLines([]);
    setMergeSource(null);
    setMergeTarget(null);
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
        `/api/manuals/${selectedManual.id}/sections/create/`,
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
      content: formatOCRContent(section.content),
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
        `/api/sections/${editingSection}/update/`,
        {
          subtitle: editForm.subtitle,
          content: editForm.content,
          page_number: editForm.page_number || null,
          order: editForm.order,
          tag: editForm.tag,
        },
        getAuth()
      );
      showMsg(`✅ Section updated — Section v${res.data.version} · Document v${res.data.manual_version} — Tag: ${res.data.tag}`);
      setEditingSection(null);
      await fetchSections(selectedManual.id);
    } catch (err) {
      showMsg(err.response?.data?.error || "❌ Failed to update section.");
    }
  };

  const handleDeleteSection = async (id, subtitle) => {
    if (!confirm(`Delete section "${subtitle}"?`)) return;
    try {
      // Prefer review-delete endpoint so staff can delete during review.
      await axios.delete(`/api/sections/${id}/review-delete/`, getAuth());
      showMsg("🗑️ Section deleted.");
      if (activeSection?.id === id) { setActiveSection(null); setIsFullDoc(true); }
      await fetchSections(selectedManual.id);
    } catch {
      try {
        // Fallback to admin delete endpoint
        await axios.delete(`/api/sections/${id}/delete/`, getAuth());
        showMsg("🗑️ Section deleted.");
        if (activeSection?.id === id) { setActiveSection(null); setIsFullDoc(true); }
        await fetchSections(selectedManual.id);
      } catch {
        showMsg("❌ Failed to delete.");
      }
    }
  };

  const handleStartMerge = (sourceSection) => {
    setMergeSource(sourceSection);
    setMergeTarget(null);
  };

  const handleMergeConfirm = async () => {
    if (!mergeSource || !mergeTarget) {
      showMsg("❌ Select both source and target sections to merge.");
      return;
    }

    if (!confirm(`Merge "${mergeSource.subtitle}" into "${mergeTarget.subtitle}"?`)) return;

    try {
      const res = await axios.post(
        `/api/sections/${mergeSource.id}/merge/`,
        { target_id: mergeTarget.id },
        getAuth()
      );
      showMsg(`✅ Merged: ${res.data.message}`);
      setMergeSource(null);
      setMergeTarget(null);
      await fetchSections(selectedManual.id);
    } catch (err) {
      showMsg(err.response?.data?.error || "❌ Merge failed.");
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
              <div style={styles.manualVersion}>Document v{manualVersion} (Rev {manualRevision})</div>
            </div>

            <div style={styles.tocLabel}>TABLE OF CONTENTS</div>

            {sections.length > 0 && (
              <div
                style={{
                  ...styles.tocItem,
                  backgroundColor: isFullDoc ? "#4f46e5" : "#f0f4ff",
                  color: isFullDoc ? "#fff" : "#4f46e5",
                  border: "1px solid #c7d2fe",
                  fontWeight: "700",
                }}
                onClick={() => {
                  setIsFullDoc(true);
                  setActiveSection(null);
                  setEditingSection(null);
                  setShowDiff(false);
                  setShowOriginal(false);
                }}
              >
                <div style={styles.tocSubtitle}>📄 Full Document</div>
                <div style={{ fontSize: "0.75rem", marginTop: "0.2rem", opacity: 0.8 }}>
                  {sections.length} sections · v{manualVersion}
                </div>
              </div>
            )}

            {mergeSource && (
              <div style={{ ...styles.tocItem, borderColor: "#60a5fa", backgroundColor: "#eff6ff" }}>
                <div style={{ fontWeight: 700, marginBottom: "0.5rem" }}>
                  🔀 Merge "{mergeSource.subtitle}" into:
                </div>
                <select
                  style={{ ...styles.input, marginBottom: "0.5rem" }}
                  value={mergeTarget?.id || ""}
                  onChange={(e) => {
                    const target = sections.find((s) => s.id === parseInt(e.target.value));
                    setMergeTarget(target || null);
                  }}
                >
                  <option value="">Select target section</option>
                  {sections
                    .filter((s) => s.id !== mergeSource.id)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.subtitle}
                      </option>
                    ))}
                </select>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button style={styles.mergeBtn} onClick={handleMergeConfirm}>
                    Confirm merge
                  </button>
                  <button
                    style={styles.deleteBtn}
                    onClick={() => {
                      setMergeSource(null);
                      setMergeTarget(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {loading ? (
              <p style={styles.loadingText}>Loading...</p>
            ) : sections.length === 0 ? (
              <p style={styles.emptyToc}>No sections yet.</p>
            ) : (
              (() => {
                // Group sections: find all parent sections (parent_id == null or no children relationship)
                const topLevelSections = sections.filter(s => !s.parent_id);
                
                return topLevelSections.map(parentSection => {
                  const tc = TAG_COLORS[parentSection.tag] || TAG_COLORS.UNTAGGED;
                  const isActive = !isFullDoc && activeSection?.id === parentSection.id;
                  const childSections = getChildren(parentSection.id, sections);
                  const isExpanded = expandedSections.has(parentSection.id);
                  const hasChildrenFlag = childSections.length > 0;

                  return (
                    <div key={parentSection.id}>
                      {/* Parent Section */}
                      <div
                        style={{
                          ...styles.tocItem,
                          backgroundColor: isActive ? "#4f46e5" : "#fff",
                          color: isActive ? "#fff" : "#333",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          paddingRight: "0.5rem",
                        }}
                      >
                        <div
                          style={{ flex: 1, cursor: "pointer" }}
                          onClick={() => handleSectionClick(parentSection)}
                        >
                          <div style={styles.tocSubtitle}>
                            {hasChildrenFlag && (
                              <span
                                style={{
                                  marginRight: "0.5rem",
                                  fontWeight: "bold",
                                  fontSize: "1.2rem",
                                  cursor: "pointer",
                                  color: isActive ? "#fff" : "#333",
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleExpandSection(parentSection.id);
                                }}
                              >
                                {isExpanded ? "▼" : "▶"}
                              </span>
                            )}
                            {parentSection.subtitle}
                          </div>
                          <div style={styles.tocMeta}>
                            <span
                              style={{
                                ...styles.tag,
                                backgroundColor: isActive ? "rgba(255,255,255,0.2)" : tc.bg,
                                color: isActive ? "#fff" : tc.color,
                              }}
                            >
                              {parentSection.tag}
                            </span>
                            {parentSection.version > 1 && (
                              <span
                                style={{
                                  ...styles.versionBadge,
                                  backgroundColor: isActive ? "rgba(255,255,255,0.2)" : "#fefcbf",
                                  color: isActive ? "#fff" : "#b7791f",
                                  border: isActive ? "1px solid rgba(255,255,255,0.4)" : "1px solid #f6e05e",
                                }}
                              >
                                v{parentSection.version}
                              </span>
                            )}
                            {parentSection.page_number && (
                              <span style={styles.pageNum}>p.{parentSection.page_number}</span>
                            )}
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: "0.3rem" }}>
                          <button
                            style={styles.editBtn}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleEditClick(parentSection);
                              setActiveSection(parentSection);
                            }}
                            title="Edit"
                          >
                            ✏️
                          </button>
                          <button
                            style={styles.deleteBtn}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteSection(parentSection.id, parentSection.subtitle);
                            }}
                            title="Delete"
                          >
                            🗑️
                          </button>
                          <button
                            style={styles.mergeBtn}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartMerge(parentSection);
                            }}
                            title="Merge"
                          >
                            🔀
                          </button>
                        </div>
                      </div>

                      {/* Child Sections (subsections) */}
                      {hasChildrenFlag && isExpanded && (
                        <div>
                          {childSections.sort((a, b) => a.order - b.order).map(childSection => {
                            const ctc = TAG_COLORS[childSection.tag] || TAG_COLORS.UNTAGGED;
                            const cIsActive = !isFullDoc && activeSection?.id === childSection.id;
                            return (
                              <div
                                key={childSection.id}
                                style={{
                                  ...styles.tocItem,
                                  backgroundColor: cIsActive ? "#4f46e5" : "#f9fafb",
                                  color: cIsActive ? "#fff" : "#333",
                                  marginLeft: "1.5rem",
                                  borderLeft: "2px solid #e5e7eb",
                                  paddingLeft: "1rem",
                                }}
                                onClick={() => handleSectionClick(childSection)}
                              >
                                <div style={styles.tocSubtitle}>
                                  🔗 {childSection.subtitle}
                                </div>
                                <div style={styles.tocMeta}>
                                  <span
                                    style={{
                                      ...styles.tag,
                                      backgroundColor: cIsActive ? "rgba(255,255,255,0.2)" : ctc.bg,
                                      color: cIsActive ? "#fff" : ctc.color,
                                    }}
                                  >
                                    {childSection.tag}
                                  </span>
                                  {childSection.version > 1 && (
                                    <span
                                      style={{
                                        ...styles.versionBadge,
                                        backgroundColor: cIsActive ? "rgba(255,255,255,0.2)" : "#fefcbf",
                                        color: cIsActive ? "#fff" : "#b7791f",
                                        border: cIsActive ? "1px solid rgba(255,255,255,0.4)" : "1px solid #f6e05e",
                                      }}
                                    >
                                      v{childSection.version}
                                    </span>
                                  )}
                                  {childSection.page_number && (
                                    <span style={styles.pageNum}>p.{childSection.page_number}</span>
                                  )}
                                  <button
                                    style={styles.editBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleEditClick(childSection);
                                      setActiveSection(childSection);
                                    }}
                                    title="Edit"
                                  >
                                    ✏️
                                  </button>
                                  <button
                                    style={styles.deleteBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleDeleteSection(childSection.id, childSection.subtitle);
                                    }}
                                    title="Delete"
                                  >
                                    🗑️
                                  </button>
                                  <button
                                    style={styles.mergeBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleStartMerge(childSection);
                                    }}
                                    title="Merge"
                                  >
                                    🔀
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                });
              })()
            )}
          </div>

          {/* ── Right Panel ── */}
          <div style={styles.content}>

            {/* ── Full Document View ── */}
            {isFullDoc ? (
              <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                <div style={styles.contentHeader}>
                  <div>
                    <h3 style={styles.contentTitle}>📄 {selectedManual.title}</h3>
                    <p style={{ color: "#888", fontSize: "0.82rem", margin: "0.25rem 0 0 0" }}>
                      Full document · {sections.length} sections
                    </p>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                    <span style={styles.versionBadgeLarge}>Document v{manualVersion}</span>
                    {manualFileUrl && (
                      <button
                        style={{
                          ...styles.addBtn,
                          backgroundColor: showOriginal ? "#718096" : "#2d6a4f",
                          fontSize: "0.85rem",
                          padding: "0.4rem 0.9rem",
                        }}
                        onClick={() => setShowOriginal(!showOriginal)}
                      >
                        {showOriginal ? "📝 View Extracted Text" : "📎 View Original File"}
                      </button>
                    )}
                    <span style={{ ...styles.tag, backgroundColor: "#f0f4ff", color: "#4f46e5", fontSize: "0.8rem", padding: "0.3rem 0.8rem", border: "1px solid #c7d2fe" }}>
                      Read Only
                    </span>
                  </div>
                </div>

                {/* ✅ File Viewer — uses <object> to bypass X-Frame-Options */}
                {showOriginal && manualFileUrl ? (
                  <div style={styles.fileViewerWrapper}>
                    {manualFileUrl.toLowerCase().includes('.pdf') ? (
                      <object
                        data={manualFileUrl}
                        type="application/pdf"
                        style={styles.pdfViewer}
                      >
                        <div style={styles.unsupportedFile}>
                          <p>⚠️ Browser cannot preview this PDF inline.</p>
                          <a href={manualFileUrl} target="_blank" rel="noreferrer" style={{ color: "#4f46e5", fontWeight: "600" }}>
                            📥 Open PDF in New Tab
                          </a>
                        </div>
                      </object>
                    ) : manualFileUrl.match(/\.(png|jpg|jpeg)$/i) ? (
                      <img
                        src={manualFileUrl}
                        alt="Original Manual"
                        style={styles.imageViewer}
                      />
                    ) : (
                      <div style={styles.unsupportedFile}>
                        <p>⚠️ Cannot preview this file type.</p>
                        <a href={manualFileUrl} target="_blank" rel="noreferrer" style={{ color: "#4f46e5", fontWeight: "600" }}>
                          📥 Download Original File
                        </a>
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={styles.fullDocBody}>
                    {sections.map((s, idx) => (
                      <div key={s.id} style={styles.fullDocSection}>
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
                        <div style={styles.fullDocContent}>
                          {renderSectionContent(s.content)}
                        </div>
                        {idx < sections.length - 1 && <hr style={styles.sectionDivider} />}
                      </div>
                    ))}
                  </div>
                )}
              </div>

            ) : editingSection ? (
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
                  <div style={styles.inputGroup}>
                    <label style={styles.label}>Tag</label>
                    <select style={styles.input} value={editForm.tag}
                      onChange={(e) => setEditForm({ ...editForm, tag: e.target.value })}>
                      <option value="POLICY">POLICY</option>
                      <option value="PROCEDURE">PROCEDURE</option>
                      <option value="RESPONSIBILITY">RESPONSIBILITY</option>
                      <option value="WORKING INSTRUCTION">WORKING INSTRUCTION</option>
                      <option value="UNTAGGED">UNTAGGED</option>
                    </select>
                  </div>
                  <p style={{ fontSize: "0.8rem", color: "#888", margin: "0" }}>
                    💡 Leave tag as auto-assigned, or select manually to override.
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
                    {loadingHistory ? (
                      <span style={{ color: "#888", fontSize: "0.85rem" }}>⏳ Loading history...</span>
                    ) : (
                      <>
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
                      </>
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
                      <span style={styles.diffChanged}>■ Changed</span>
                      <span style={styles.diffSame}>■ Unchanged</span>
                    </div>
                    <div style={styles.diffTable}>
                      <div style={styles.diffHeader}>Previous</div>
                      <div style={styles.diffHeader}>Selected</div>
                      {diffLines.map((row, i) => (
                        <React.Fragment key={i}>
                          <div style={{
                            ...styles.diffCell,
                            ...(row.type === "removed" ? styles.diffRemovedCell : {}),
                            ...(row.type === "changed" ? styles.diffChangedOldCell : {}),
                            ...(row.type === "same" ? styles.diffSameCell : {}),
                          }}>
                            {row.old}
                          </div>
                          <div style={{
                            ...styles.diffCell,
                            ...(row.type === "added" ? styles.diffAddedCell : {}),
                            ...(row.type === "changed" ? styles.diffChangedNewCell : {}),
                            ...(row.type === "same" ? styles.diffSameCell : {}),
                          }}>
                            {row.new}
                          </div>
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div style={styles.contentBody}>
                    {renderSectionContent(
                    formatOCRContent(selectedVersion?.content ?? activeSection.content)
                    )}
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
  manualVersion: { color: "#a5b4fc", fontSize: "0.75rem", fontWeight: "600", marginTop: "0.4rem" },
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
  mergeBtn: { background: "none", border: "none", cursor: "pointer", fontSize: "0.85rem", padding: "0", marginLeft: "0.25rem" },
  loadingText: { color: "#888", textAlign: "center", padding: "1rem" },
  emptyToc: { color: "#aaa", fontSize: "0.85rem", textAlign: "center", padding: "1rem" },
  content: { flex: 1, backgroundColor: "#fff", borderRadius: "10px", padding: "1.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", overflowY: "auto" },
  contentEmpty: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "#aaa", textAlign: "center" },
  contentHeader: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "0.5rem", flexWrap: "wrap", gap: "0.5rem" },
  contentTitle: { margin: 0, color: "#1a1a2e", fontSize: "1.2rem" },
  pageLabel: { color: "#aaa", fontSize: "0.8rem", margin: "0 0 1rem 0" },
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
  diffChanged: { color: "#b7791f" },
  diffSame: { color: "#aaa" },
  diffTable: { display: "grid", gridTemplateColumns: "1fr 1fr", borderRadius: "8px", border: "1px solid #e2e8f0", overflow: "hidden", fontFamily: "monospace", fontSize: "0.9rem" },
  diffHeader: { padding: "0.75rem 1rem", backgroundColor: "#f7f8fc", borderBottom: "1px solid #e2e8f0", fontWeight: "700", color: "#1a1a2e" },
  diffCell: { padding: "0.45rem 0.75rem", borderBottom: "1px solid #f0f0f0", whiteSpace: "pre-wrap", wordBreak: "break-word", minHeight: "1.4rem" },
  diffAddedCell: { backgroundColor: "#f0fff4", color: "#22543d" },
  diffRemovedCell: { backgroundColor: "#fff5f5", color: "#742a2a" },
  diffChangedOldCell: { backgroundColor: "#fffbeb", color: "#975a16" },
  diffChangedNewCell: { backgroundColor: "#ecfdf5", color: "#22543d" },
  diffSameCell: { backgroundColor: "transparent", color: "#333" },
  diffBody: { fontFamily: "monospace", fontSize: "0.9rem", lineHeight: "1.8", borderRadius: "8px", border: "1px solid #e2e8f0", overflow: "hidden" },
  diffLine: { margin: 0, padding: "0.2rem 1rem", wordBreak: "break-word" },
  diffMarker: { display: "inline-block", width: "1.2rem", fontWeight: "700" },
  contentBody: { fontSize: "0.95rem", lineHeight: "1.9", color: "#333", borderTop: "1px solid #f0f0f0", paddingTop: "1rem", maxWidth: "720px" },
  contentParagraph: { margin: "0 0 1rem 0", textAlign: "justify", wordBreak: "break-word" },
  fileViewerWrapper: { marginTop: "1rem", borderRadius: "8px", overflow: "hidden", border: "1px solid #e2e8f0", height: "72vh", display: "flex", flexDirection: "column" },
  pdfViewer: { width: "100%", height: "100%", border: "none", flex: 1 },
  imageViewer: { width: "100%", height: "auto", display: "block", objectFit: "contain" },
  unsupportedFile: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: "1rem", color: "#888", fontSize: "0.95rem" },
};
