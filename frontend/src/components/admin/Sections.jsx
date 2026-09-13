import React, { useState, useEffect } from "react";
import axios from "axios";
import DocTable from "../DocTable";

const formatOCRContent = (content = "") => {
  return content
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(//g, "•")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
};

const TAG_CLASS = {
  POLICY:                "badge-info",
  PROCEDURE:             "badge-success",
  RESPONSIBILITY:        "badge-danger",
  "WORKING INSTRUCTION": "badge-warning",
  UNTAGGED:              "badge-neutral",
};

const tagClass = (tag) => TAG_CLASS[tag] || "badge-neutral";

const INLINE_TAG_TONE = {
  POLICY:                "is-info",
  PROCEDURE:             "is-success",
  RESPONSIBILITY:        "is-danger",
  "WORKING INSTRUCTION": "is-warning",
  "PREPARED BY":         "is-violet",
  "APPROVED BY":         "is-violet",
  "NOTED BY":            "is-violet",
  "REVIEWED BY":         "is-violet",
};

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

// Align two line arrays by longest common subsequence, so inserted or deleted
// lines shift the alignment instead of knocking every later line out of sync.
function alignLines(oldLines, newLines) {
  const n = oldLines.length;
  const m = newLines.length;
  const width = m + 1;

  // lcs[i][j] = length of the longest common subsequence of old[i..] and new[j..]
  const lcs = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i * width + j] =
        oldLines[i] === newLines[j]
          ? lcs[(i + 1) * width + (j + 1)] + 1
          : Math.max(lcs[(i + 1) * width + j], lcs[i * width + (j + 1)]);
    }
  }

  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) {
      ops.push({ op: "same", old: oldLines[i], new: newLines[j] });
      i++;
      j++;
    } else if (lcs[(i + 1) * width + j] >= lcs[i * width + (j + 1)]) {
      ops.push({ op: "removed", old: oldLines[i] });
      i++;
    } else {
      ops.push({ op: "added", new: newLines[j] });
      j++;
    }
  }
  while (i < n) ops.push({ op: "removed", old: oldLines[i++] });
  while (j < m) ops.push({ op: "added", new: newLines[j++] });

  return ops;
}

function computeDiff(oldText, newText) {
  // Normalize both sides first. Older versions still carry literal <br> markup
  // from OCR extraction while newer ones hold real newlines, so comparing them
  // raw reports every marked-up line as rewritten.
  const ops = alignLines(
    formatOCRContent(oldText).split("\n"),
    formatOCRContent(newText).split("\n")
  );
  const rows = [];

  let k = 0;
  while (k < ops.length) {
    if (ops[k].op === "same") {
      rows.push({ type: "same", old: ops[k].old, new: ops[k].new });
      k++;
      continue;
    }

    // Pair each run of removals with the insertions that replaced them, so an
    // edited line shows its old and new text on one row.
    const removed = [];
    const added = [];
    while (k < ops.length && ops[k].op !== "same") {
      if (ops[k].op === "removed") removed.push(ops[k].old);
      else added.push(ops[k].new);
      k++;
    }

    const paired = Math.min(removed.length, added.length);
    for (let p = 0; p < paired; p++) {
      rows.push({ type: "changed", old: removed[p], new: added[p] });
    }
    for (let p = paired; p < removed.length; p++) {
      rows.push({ type: "removed", old: removed[p], new: "" });
    }
    for (let p = paired; p < added.length; p++) {
      rows.push({ type: "added", old: "", new: added[p] });
    }
  }

  return rows;
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
      return <DocTable key={idx} rows={block.rows} />;
    }

    if (block.type === "inline-tagged") {
      return (
        <div key={idx} className={`callout ${INLINE_TAG_TONE[block.tag] || ""}`}>
          <strong className="callout-tag">{block.tag}</strong>
          <p>{block.content}</p>
        </div>
      );
    }

    return <p key={idx} className="doc-paragraph">{block.text}</p>;
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

  // Diff a version against the one immediately before it. The oldest version
  // has no predecessor, so there is nothing to compare it against.
  const compareWithPrevious = (versions, version) => {
    const idx = versions.findIndex((h) => h.version === version?.version);
    if (idx > 0) {
      setDiffLines(computeDiff(versions[idx - 1].content, version.content));
      setShowDiff(true);
    } else {
      setDiffLines([]);
      setShowDiff(false);
    }
  };

  const hasPreviousVersion =
    history.findIndex((h) => h.version === selectedVersion?.version) > 0;

  const handleVersionChange = (e) => {
    const ver = parseInt(e.target.value);
    const selected = history.find((h) => h.version === ver);
    setSelectedVersion(selected);
    compareWithPrevious(history, selected);
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

  const renderTocEntry = (section, isChild) => {
    const isActive = !isFullDoc && activeSection?.id === section.id;
    const childSections = isChild ? [] : getChildren(section.id, sections);
    const isExpanded = expandedSections.has(section.id);
    const hasChildrenFlag = childSections.length > 0;

    return (
      <div
        key={section.id}
        className={`toc-item${isActive ? " is-active" : ""}${isChild ? " is-child" : ""}`}
      >
        <div className="toc-item-main" onClick={() => handleSectionClick(section)}>
          <span className="toc-item-title">
            {hasChildrenFlag && (
              <span
                className={`chevron${isExpanded ? " is-open" : ""}`}
                style={{ marginRight: "0.4rem" }}
                onClick={(e) => { e.stopPropagation(); toggleExpandSection(section.id); }}
              >
                ▾
              </span>
            )}
            {isChild && "🔗 "}
            {section.subtitle}
          </span>
          <span className="row-wrap" style={{ gap: "0.35rem" }}>
            <span className={`badge ${tagClass(section.tag)}`}>{section.tag}</span>
            {section.version > 1 && <span className="badge badge-warning">v{section.version}</span>}
            {section.page_number && <span className="toc-item-meta">p.{section.page_number}</span>}
          </span>
        </div>

        <div className="toc-item-actions">
          <button
            className="icon-btn"
            title="Edit"
            onClick={(e) => { e.stopPropagation(); handleEditClick(section); setActiveSection(section); }}
          >
            ✏️
          </button>
          <button
            className="icon-btn"
            title="Delete"
            onClick={(e) => { e.stopPropagation(); handleDeleteSection(section.id, section.subtitle); }}
          >
            🗑️
          </button>
          <button
            className="icon-btn"
            title="Merge"
            onClick={(e) => { e.stopPropagation(); handleStartMerge(section); }}
          >
            🔀
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="reader">
      <div className="page-head" style={{ marginBottom: "1.15rem" }}>
        <div>
          <h1 className="page-title">Manual Sections</h1>
          <p className="page-subtitle">Read, edit, merge and version the sections of a manual.</p>
        </div>
        <div className="row-wrap" style={{ gap: "0.6rem" }}>
          <select className="select" style={{ width: "auto", minWidth: "260px" }} onChange={handleManualChange} defaultValue="">
            <option value="">— Select a manual —</option>
            {manuals.map((m) => (
              <option key={m.id} value={m.id}>{m.title} ({m.department})</option>
            ))}
          </select>
          {selectedManual && (
            <button
              className={`btn ${showForm ? "btn-ghost" : "btn-primary"}`}
              onClick={() => { setShowForm(!showForm); setEditingSection(null); }}
            >
              {showForm ? "✕ Cancel" : "+ Add section"}
            </button>
          )}
        </div>
      </div>

      {showForm && (
        <div className="card card-pad anim-scale-in" style={{ marginBottom: "1rem" }}>
          <h4 className="section-title" style={{ marginBottom: "1rem" }}>
            New section for {selectedManual?.title}
          </h4>
          <form onSubmit={handleCreateSection} className="col">
            <div className="field">
              <label className="label">Subtitle</label>
              <input
                className="input"
                placeholder="e.g. 1.1 Purpose"
                value={form.subtitle}
                onChange={(e) => setForm({ ...form, subtitle: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label className="label">Content</label>
              <textarea
                className="textarea"
                placeholder="Section content"
                value={form.content}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
              />
            </div>
            <div className="form-row">
              <div className="field">
                <label className="label">Page number</label>
                <input
                  className="input"
                  type="number"
                  placeholder="Optional"
                  value={form.page_number}
                  onChange={(e) => setForm({ ...form, page_number: e.target.value })}
                />
              </div>
              <div className="field">
                <label className="label">Order</label>
                <input
                  className="input"
                  type="number"
                  placeholder="Default 0"
                  value={form.order}
                  onChange={(e) => setForm({ ...form, order: e.target.value })}
                />
              </div>
            </div>
            <button className="btn btn-primary" type="submit" style={{ alignSelf: "flex-start" }}>
              Save section
            </button>
          </form>
        </div>
      )}

      {message && <div className="toast">{message}</div>}

      {!selectedManual ? (
        <div className="empty-state">
          <div className="empty-icon">📚</div>
          <p className="empty-title">No manual selected</p>
          <p className="empty-text">Choose a manual above to start reading or managing its sections.</p>
        </div>
      ) : (
        <div className="reader-split">
          {/* ── Table of contents ── */}
          <aside className="reader-toc">
            <div className="toc-head">
              <div className="toc-head-title">{selectedManual.title}</div>
              <div className="toc-head-meta">🏢 {selectedManual.department}</div>
              <div className="toc-head-meta">Document v{manualVersion} · Rev {manualRevision}</div>
            </div>

            <div className="toc-list">
              {sections.length > 0 && (
                <button
                  className={`toc-item is-doc${isFullDoc ? " is-active" : ""}`}
                  onClick={() => {
                    setIsFullDoc(true);
                    setActiveSection(null);
                    setEditingSection(null);
                    setShowDiff(false);
                    setShowOriginal(false);
                  }}
                >
                  <span className="toc-item-title">📄 Full document</span>
                  <span className="toc-item-meta">{sections.length} sections · v{manualVersion}</span>
                </button>
              )}

              {mergeSource && (
                <div className="card card-pad anim-scale-in" style={{ background: "var(--info-soft)", borderColor: "var(--azure-300)" }}>
                  <p className="label" style={{ marginBottom: "0.5rem" }}>
                    🔀 Merge “{mergeSource.subtitle}” into:
                  </p>
                  <select
                    className="select"
                    style={{ marginBottom: "0.6rem" }}
                    value={mergeTarget?.id || ""}
                    onChange={(e) => {
                      const target = sections.find((s) => s.id === parseInt(e.target.value));
                      setMergeTarget(target || null);
                    }}
                  >
                    <option value="">Select target section</option>
                    {sections
                      .filter((s) => s.id !== mergeSource.id)
                      .map((s) => <option key={s.id} value={s.id}>{s.subtitle}</option>)}
                  </select>
                  <div className="row" style={{ gap: "0.4rem" }}>
                    <button className="btn btn-success btn-sm" onClick={handleMergeConfirm}>Confirm merge</button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => { setMergeSource(null); setMergeTarget(null); }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {loading ? (
                <div className="loading-row" style={{ padding: "1.5rem" }}>
                  <span className="spinner" /> Loading…
                </div>
              ) : sections.length === 0 ? (
                <p className="muted text-sm" style={{ textAlign: "center", padding: "1.5rem 1rem" }}>
                  No sections yet.
                </p>
              ) : (
                sections
                  .filter((s) => !s.parent_id)
                  .map((parentSection) => {
                    const childSections = getChildren(parentSection.id, sections);
                    const isExpanded = expandedSections.has(parentSection.id);
                    return (
                      <div key={parentSection.id}>
                        {renderTocEntry(parentSection, false)}
                        {childSections.length > 0 && isExpanded && (
                          <div className="toc-children">
                            {childSections
                              .slice()
                              .sort((a, b) => a.order - b.order)
                              .map((child) => renderTocEntry(child, true))}
                          </div>
                        )}
                      </div>
                    );
                  })
              )}
            </div>
          </aside>

          {/* ── Content panel ── */}
          <section className="reader-panel">
            {isFullDoc ? (
              <div className="anim-fade-up">
                <div className="page-head" style={{ marginBottom: "1.25rem" }}>
                  <div>
                    <h2 className="page-title" style={{ fontSize: "1.3rem" }}>📄 {selectedManual.title}</h2>
                    <p className="page-subtitle">Full document · {sections.length} sections</p>
                  </div>
                  <div className="row-wrap" style={{ gap: "0.5rem" }}>
                    <span className="badge badge-warning">Document v{manualVersion}</span>
                    <span className="badge badge-neutral">Read only</span>
                    {manualFileUrl && (
                      <button
                        className={`btn btn-sm ${showOriginal ? "btn-ghost" : "btn-primary"}`}
                        onClick={() => setShowOriginal(!showOriginal)}
                      >
                        {showOriginal ? "📝 Extracted text" : "📎 Original file"}
                      </button>
                    )}
                  </div>
                </div>

                {showOriginal && manualFileUrl ? (
                  <div className="file-viewer">
                    {manualFileUrl.toLowerCase().includes(".pdf") ? (
                      <object data={manualFileUrl} type="application/pdf">
                        <div className="empty-state" style={{ border: "none" }}>
                          <p className="empty-text">Your browser can&apos;t preview this PDF inline.</p>
                          <a className="btn btn-ghost btn-sm" href={manualFileUrl} target="_blank" rel="noreferrer">
                            📥 Open PDF in new tab
                          </a>
                        </div>
                      </object>
                    ) : manualFileUrl.match(/\.(png|jpg|jpeg)$/i) ? (
                      <img src={manualFileUrl} alt="Original manual" />
                    ) : (
                      <div className="empty-state" style={{ border: "none" }}>
                        <p className="empty-text">This file type can&apos;t be previewed.</p>
                        <a className="btn btn-ghost btn-sm" href={manualFileUrl} target="_blank" rel="noreferrer">
                          📥 Download original file
                        </a>
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    {sections.map((s, idx) => (
                      <div key={s.id} style={{ marginBottom: "1.75rem" }}>
                        <div className="doc-heading">
                          <span>{s.subtitle}</span>
                          <span className="row" style={{ gap: "0.4rem" }}>
                            <span className={`badge ${tagClass(s.tag)}`}>{s.tag}</span>
                            {s.version > 1 && <span className="badge badge-warning">v{s.version}</span>}
                          </span>
                        </div>
                        <div className="prose">{renderSectionContent(s.content)}</div>
                        {idx < sections.length - 1 && <hr className="divider" />}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : editingSection ? (
              <div className="anim-fade-up">
                <div className="page-head" style={{ marginBottom: "1.25rem" }}>
                  <h2 className="page-title" style={{ fontSize: "1.3rem" }}>✏️ Editing section</h2>
                  <button className="btn btn-ghost btn-sm" onClick={() => setEditingSection(null)}>✕ Cancel</button>
                </div>

                <form onSubmit={handleEditSave} className="col">
                  <div className="field">
                    <label className="label">Subtitle</label>
                    <input
                      className="input"
                      value={editForm.subtitle}
                      onChange={(e) => setEditForm({ ...editForm, subtitle: e.target.value })}
                      required
                    />
                  </div>
                  <div className="field">
                    <label className="label">Content</label>
                    <textarea
                      className="textarea textarea-doc"
                      value={editForm.content}
                      onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                    />
                  </div>
                  <div className="form-row">
                    <div className="field">
                      <label className="label">Page number</label>
                      <input
                        className="input"
                        type="number"
                        value={editForm.page_number}
                        onChange={(e) => setEditForm({ ...editForm, page_number: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label className="label">Order</label>
                      <input
                        className="input"
                        type="number"
                        value={editForm.order}
                        onChange={(e) => setEditForm({ ...editForm, order: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="field">
                    <label className="label">Tag</label>
                    <select
                      className="select"
                      value={editForm.tag}
                      onChange={(e) => setEditForm({ ...editForm, tag: e.target.value })}
                    >
                      <option value="POLICY">POLICY</option>
                      <option value="PROCEDURE">PROCEDURE</option>
                      <option value="RESPONSIBILITY">RESPONSIBILITY</option>
                      <option value="WORKING INSTRUCTION">WORKING INSTRUCTION</option>
                      <option value="UNTAGGED">UNTAGGED</option>
                    </select>
                  </div>
                  <p className="subtle text-xs">
                    💡 Leave the tag auto-assigned, or select one manually to override.
                  </p>
                  <button className="btn btn-primary" type="submit" style={{ alignSelf: "flex-start" }}>
                    💾 Save changes
                  </button>
                </form>
              </div>
            ) : !activeSection ? (
              <div className="empty-state" style={{ border: "none", background: "transparent" }}>
                <div className="empty-icon">👈</div>
                <p className="empty-title">Nothing selected</p>
                <p className="empty-text">Pick a section from the table of contents to read it.</p>
              </div>
            ) : (
              <div className="anim-fade-up" key={activeSection.id}>
                <div className="page-head" style={{ marginBottom: "1rem" }}>
                  <div>
                    <h2 className="page-title" style={{ fontSize: "1.3rem" }}>{activeSection.subtitle}</h2>
                    {activeSection.page_number && !showDiff && (
                      <p className="page-subtitle">Page {activeSection.page_number}</p>
                    )}
                  </div>
                  <div className="row-wrap" style={{ gap: "0.5rem" }}>
                    <span className={`badge ${tagClass(activeSection.tag)}`}>{activeSection.tag}</span>
                    {activeSection.version > 1 && (
                      <span className="badge badge-warning">v{activeSection.version}</span>
                    )}
                    <button className="btn btn-primary btn-sm" onClick={() => handleEditClick(activeSection)}>
                      ✏️ Edit
                    </button>
                  </div>
                </div>

                {activeSection.version > 1 && (
                  <div className="alert alert-warning" style={{ marginBottom: "1rem" }}>
                    📝 This section has been revised — <strong>version {activeSection.version}</strong>
                  </div>
                )}

                {history.length > 1 && (
                  <div className="merge-bar">
                    <span className="merge-bar-label">🕓 View version</span>
                    {loadingHistory ? (
                      <span className="muted text-sm"><span className="spinner" /> Loading history…</span>
                    ) : (
                      <div className="row-wrap" style={{ gap: "0.5rem" }}>
                        <select
                          className="select"
                          style={{ width: "auto", minWidth: "220px" }}
                          value={selectedVersion?.version ?? ""}
                          onChange={handleVersionChange}
                        >
                          {history.map((h) => (
                            <option key={h.version} value={h.version}>
                              {h.version === activeSection.version
                                ? `v${h.version} — Current`
                                : `v${h.version} — ${h.edited_by} (${h.edited_at ? new Date(h.edited_at).toLocaleDateString() : ""})`}
                            </option>
                          ))}
                        </select>
                        {showDiff ? (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => { setShowDiff(false); setSelectedVersion(history[history.length - 1]); }}
                          >
                            ✕ Clear diff
                          </button>
                        ) : (
                          hasPreviousVersion && (
                            <button
                              className="btn btn-subtle btn-sm"
                              onClick={() => compareWithPrevious(history, selectedVersion)}
                            >
                              ⇄ Compare with previous
                            </button>
                          )
                        )}
                      </div>
                    )}
                  </div>
                )}

                {showDiff ? (
                  <div className="anim-fade-up">
                    <div className="diff-legend">
                      <span className="diff-key is-added">Added</span>
                      <span className="diff-key is-removed">Removed</span>
                      <span className="diff-key is-changed">Changed</span>
                      <span className="diff-key is-same">Unchanged</span>
                    </div>
                    <div className="diff-grid">
                      <div className="diff-grid-head">Previous</div>
                      <div className="diff-grid-head">Selected</div>
                      {diffLines.map((row, i) => (
                        <React.Fragment key={i}>
                          <div className={`diff-cell${row.type === "removed" ? " is-removed" : row.type === "changed" ? " is-changed-old" : ""}`}>
                            {row.old}
                          </div>
                          <div className={`diff-cell${row.type === "added" ? " is-added" : row.type === "changed" ? " is-changed-new" : ""}`}>
                            {row.new}
                          </div>
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="prose doc-body">
                    {renderSectionContent(
                      formatOCRContent(selectedVersion?.content ?? activeSection.content)
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}


