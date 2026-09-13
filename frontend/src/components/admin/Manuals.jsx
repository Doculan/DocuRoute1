import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_BASE_URL = "http://127.0.0.1:8000";

export default function Manuals() {
  const [manuals, setManuals] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState({ title: "", department_id: "", file: null });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  // Preview state (review sectioning before finalizing)
  const [previewManual, setPreviewManual] = useState(null);
  const [previewSections, setPreviewSections] = useState([]);
  const [previewFileUrl, setPreviewFileUrl] = useState(null);
  const [previewFileName, setPreviewFileName] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [mergeSourceIndex, setMergeSourceIndex] = useState(null);

  // QMS version editing (admin only)
  const [manualVersionEdits, setManualVersionEdits] = useState({});

  // Pagination & Filters
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [searchBy, setSearchBy] = useState("all");
  const [selectedManualIds, setSelectedManualIds] = useState([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [filters, setFilters] = useState({
    department: "",
    author: "",
    version: "",
    minSections: "",
    dateFrom: "",
    dateTo: "",
    sortBy: "newest",
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    const token = localStorage.getItem("access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      const params = new URLSearchParams();
      if (searchQuery.trim()) {
        params.append('search', searchQuery.trim());
        params.append('searchBy', searchBy);
      }
      if (filters.department) params.append('department', filters.department);
      if (filters.author.trim()) params.append('author', filters.author.trim());
      if (filters.version) params.append('version', filters.version);
      if (filters.minSections) params.append('minSections', filters.minSections);
      if (filters.sortBy) params.append('sortBy', filters.sortBy);

      const [manualsRes, deptsRes] = await Promise.all([
        axios.get(`/api/manuals/?${params.toString()}`, authHeaders),
        axios.get(`/api/departments/`, authHeaders),
      ]);
      setManuals(manualsRes.data);
      setDepartments(deptsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, searchBy, filters.department, filters.author, filters.version, filters.minSections, filters.sortBy]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 4000);
  };

  const handleManualVersionChange = (manualId, value) => {
    setManualVersionEdits((prev) => ({ ...prev, [manualId]: parseInt(value, 10) }));
  };

  const updateManualVersion = async (manualId, currentValue) => {
    const newVersion = manualVersionEdits[manualId] || currentValue;
    if (newVersion === currentValue) {
      showMessage("🔎 Version unchanged.");
      return;
    }

    try {
      const token = localStorage.getItem("access_token");
      await axios.patch(
        `/api/manuals/${manualId}/set-version/`,
        { version: newVersion },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      showMessage(`✅ Manual version set to v${newVersion}.`);
      setManualVersionEdits((prev) => ({ ...prev, [manualId]: newVersion }));
      fetchData();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to set manual version.");
    }
  };

  const reindexParentIndices = (sections, removedIndex, removedParentIndex) => {
    return sections.map((sec) => {
      if (sec?.parent_index === removedIndex) {
        return { ...sec, parent_index: removedParentIndex };
      }
      if (typeof sec?.parent_index === "number" && sec.parent_index > removedIndex) {
        return { ...sec, parent_index: sec.parent_index - 1 };
      }
      return sec;
    });
  };

  const cancelMerge = () => setMergeSourceIndex(null);

  const handleMerge = (targetIndex) => {
    if (mergeSourceIndex === null || mergeSourceIndex === targetIndex) {
      setMergeSourceIndex(null);
      return;
    }

    const source = previewSections[mergeSourceIndex];
    const target = previewSections[targetIndex];
    if (!source || !target) {
      setMergeSourceIndex(null);
      return;
    }

    // Merge source into target (keep the source title as part of the merged section)
    const separator = source.content && target.content ? "\n\n" : "";
    const sourceHeader = source.subtitle ? `\n\n${source.subtitle}\n\n` : "";
    const mergedContent = `${target.content || ""}${separator}${sourceHeader}${source.content || ""}`;

    // Keep tag/title as target; this is a preview edit stage.
    const updated = [...previewSections];
    const removedParentIndex = source.parent_index ?? null;

    // Remove the source row first (so indices shift correctly)
    updated.splice(mergeSourceIndex, 1);

    // Determine where the target landed after removal
    const adjustedTargetIndex = mergeSourceIndex < targetIndex ? targetIndex - 1 : targetIndex;

    const mergedTarget = {
      ...updated[adjustedTargetIndex],
      content: mergedContent,
    };

    updated[adjustedTargetIndex] = mergedTarget;

    // Reindex any parent_index references after removal
    const reindexed = reindexParentIndices(updated, mergeSourceIndex, removedParentIndex);

    setPreviewSections(reindexed);
    showMessage(`✅ Merged section into "${mergedTarget.subtitle || "Untitled"}".`);
    setMergeSourceIndex(null);
  };

  const startMerge = (index) => {
    if (mergeSourceIndex === index) {
      setMergeSourceIndex(null);
    } else {
      setMergeSourceIndex(index);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!form.title || !form.department_id || !form.file) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    setUploading(true);

    const formData = new FormData();
    formData.append("title", form.title);
    formData.append("department_id", form.department_id);
    formData.append("file", form.file);

    try {
      // Use the preview endpoint so user can review/edit sectioning before finalizing
      const res = await axios.post(
        "/api/manuals/upload-preview/",
        formData,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setPreviewManual({ id: res.data.manual_id, title: res.data.title });
      setPreviewFileUrl(res.data.file_url ? `${BACKEND_BASE_URL}${res.data.file_url}` : null);
      setPreviewFileName(res.data.file_name || null);

      const sections = Array.isArray(res.data.sections_preview)
        ? res.data.sections_preview
        : [];

      setPreviewSections(
        sections.map((s) => ({
          ...s,
          subtitle: s.subtitle,
          content: s.content,
          tag: s.tag,
        }))
      );
      showMessage(`✅ Preview ready — review before confirming.`);
      setForm({ title: "", department_id: "", file: null });
    } catch (err) {
      console.error("Upload preview error", err);
      showMessage(err.response?.data?.error || err.message || "❌ Upload preview failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id, title) => {
    if (!confirm(`Delete "${title}"? All its sections and revisions will be deleted too.`)) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      await axios.delete(`/api/manuals/${id}/delete/`, authHeaders);
      showMessage(`🗑️ "${title}" deleted.`);
      fetchData();
    } catch { showMessage("❌ Failed to delete."); }
  };

  const toggleManualSelection = (manualId) => {
    setSelectedManualIds((prev) =>
      prev.includes(manualId)
        ? prev.filter((id) => id !== manualId)
        : [...prev, manualId]
    );
  };

  const toggleSelectAll = (isChecked) => {
    if (isChecked) {
      setSelectedManualIds(paginatedManuals.map((m) => m.id));
    } else {
      setSelectedManualIds([]);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedManualIds.length === 0) {
      showMessage("❌ Select at least one manual first.");
      return;
    }
    if (!confirm(`Delete ${selectedManualIds.length} selected manual(s)? This cannot be undone.`)) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

    try {
      await Promise.all(
        selectedManualIds.map((id) => axios.delete(`/api/manuals/${id}/delete/`, authHeaders))
      );
      showMessage(`🗑️ Deleted ${selectedManualIds.length} manuals.`);
      setSelectedManualIds([]);
      fetchData();
    } catch (err) {
      console.error(err);
      showMessage("❌ Failed to delete selected manuals.");
    }
  };

  const getDepth = (index) => {
    const visited = new Set();
    let depth = 0;
    let current = previewSections[index];
    while (current && current.parent_index !== null && !visited.has(current.parent_index)) {
      visited.add(current.parent_index);
      depth += 1;
      current = previewSections[current.parent_index];
    }
    return depth;
  };

  const handleConfirmSections = async () => {
    if (!previewManual) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    setConfirming(true);
    try {
      await axios.post(
        `/api/manuals/${previewManual.id}/confirm-sections/`,
        { sections: previewSections },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      showMessage("✅ Sections confirmed. You can now review them in the Sections tab.");
      setPreviewManual(null);
      setPreviewSections([]);
      setPreviewFileUrl(null);
      setPreviewFileName(null);
      setMergeSourceIndex(null);
      fetchData();
    } catch (err) {
      showMessage(err.response?.data?.error || "❌ Failed to confirm sections.");
    } finally {
      setConfirming(false);
    }
  };

  const handleCancelPreview = async () => {
    if (!previewManual) return;
    if (!confirm("Cancel preview and remove the uploaded manual?")) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    try {
      await axios.delete(
        `/api/manuals/${previewManual.id}/delete/`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
    } catch (err) {
      console.error(err);
    }
    setPreviewManual(null);
    setPreviewSections([]);
    setPreviewFileUrl(null);
    setPreviewFileName(null);
    setMergeSourceIndex(null);
    showMessage("Preview canceled.");
  };

  // Toggle expanded row
  const toggleExpandRow = (id) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedRows(newExpanded);
  };

  // Filter and sort manuals
  const getFilteredAndSortedManuals = () => {
    let filtered = manuals.filter((m) => {
      // Department filter
      if (filters.department) {
        const selectedDeptId = parseInt(filters.department, 10);
        const manualDeptId = m.department_id ? parseInt(m.department_id, 10) : null;
        if (manualDeptId !== selectedDeptId) {
          return false;
        }
      }
      // Date range filter
      const uploadDate = new Date(m.uploaded_at);
      if (filters.dateFrom) {
        const fromDate = new Date(filters.dateFrom);
        if (uploadDate < fromDate) return false;
      }
      if (filters.dateTo) {
        const toDate = new Date(filters.dateTo);
        toDate.setHours(23, 59, 59, 999);
        if (uploadDate > toDate) return false;
      }
      return true;
    });

    // Sort
    filtered.sort((a, b) => {
      if (filters.sortBy === "newest") {
        return new Date(b.uploaded_at) - new Date(a.uploaded_at);
      } else if (filters.sortBy === "oldest") {
        return new Date(a.uploaded_at) - new Date(b.uploaded_at);
      } else if (filters.sortBy === "recentEdit") {
        // Fall back to uploaded_at since updated_at isn't available
        return new Date(b.uploaded_at) - new Date(a.uploaded_at);
      }
      return 0;
    });

    return filtered;
  };

  const filteredManuals = getFilteredAndSortedManuals();
  const totalPages = Math.ceil(filteredManuals.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const paginatedManuals = filteredManuals.slice(startIndex, startIndex + itemsPerPage);

  const hasActiveFilters =
    searchQuery || filters.department || filters.author ||
    filters.version || filters.dateFrom || filters.dateTo;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Manuals</h1>
          <p className="page-subtitle">Upload master copies, review extracted sections and manage versions.</p>
        </div>
      </header>

      {/* ── Upload ── */}
      <div className="card card-pad" style={{ marginBottom: "1.5rem" }}>
        <h3 className="section-title" style={{ marginBottom: "1rem" }}>Upload master copy</h3>

        <form onSubmit={handleUpload} className="col">
          <div className="form-row">
            <div className="field">
              <label className="label">Manual title</label>
              <input
                className="input"
                type="text"
                placeholder="e.g. Business Affairs Manual"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label className="label">Department</label>
              <select
                className="select"
                value={form.department_id}
                onChange={(e) => setForm({ ...form, department_id: e.target.value })}
                required
              >
                <option value="">Select department</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label className="label">Source file (PDF, TXT or image)</label>
            <input
              className="input-file"
              type="file"
              accept=".pdf,.txt,.png,.jpg,.jpeg"
              onChange={(e) => setForm({ ...form, file: e.target.files[0] })}
              required
            />
          </div>

          <button className="btn btn-primary" type="submit" disabled={uploading} style={{ alignSelf: "flex-start" }}>
            {uploading ? <><span className="spinner spinner-light" /> Extracting &amp; previewing…</> : "Upload & preview"}
          </button>
        </form>

        {previewManual && (
          <div className="preview-panel anim-scale-in">
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "0.75rem" }}>
              <div>
                <span className="label">Preview for</span>
                <div className="strong">{previewManual.title}</div>
              </div>
              <div className="row" style={{ gap: "0.5rem" }}>
                <button className="btn btn-ghost btn-sm" onClick={handleCancelPreview}>Cancel preview</button>
                <button className="btn btn-success btn-sm" onClick={handleConfirmSections} disabled={confirming}>
                  {confirming ? <><span className="spinner spinner-light" /> Confirming…</> : "Confirm sections"}
                </button>
              </div>
            </div>

            {mergeSourceIndex !== null && (
              <div className="alert alert-success" style={{ marginTop: "0.85rem" }}>
                <strong>Merge mode:</strong> pick a target section below to merge into.
                <button className="btn btn-ghost btn-sm" style={{ marginLeft: "0.75rem" }} onClick={cancelMerge}>
                  Cancel
                </button>
              </div>
            )}

            <div style={{ marginTop: "1rem" }}>
              {previewSections.length === 0 ? (
                <p className="muted text-sm">No sections detected in preview.</p>
              ) : (
                <div className="preview-split">
                  <div className="preview-list">
                    {previewSections.map((s, idx) => {
                      const depth = getDepth(idx);
                      return (
                        <div key={idx} className="card card-pad preview-card" style={{ marginLeft: depth * 18 }}>
                          <div className="row" style={{ justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                            <input
                              className="input"
                              style={{ flex: 1, minWidth: "180px" }}
                              value={s.subtitle}
                              onChange={(e) => {
                                const updated = [...previewSections];
                                updated[idx] = { ...updated[idx], subtitle: e.target.value };
                                setPreviewSections(updated);
                              }}
                            />
                            {s.is_chapter && <span className="badge badge-info">CHAPTER</span>}
                            <div className="row" style={{ gap: "0.4rem" }}>
                              {mergeSourceIndex !== null && mergeSourceIndex !== idx && (
                                <button className="btn btn-success btn-sm" onClick={() => handleMerge(idx)}>
                                  Merge into this
                                </button>
                              )}
                              <button
                                className={`btn btn-sm ${mergeSourceIndex === idx ? "btn-danger-soft" : "btn-ghost"}`}
                                onClick={() => startMerge(idx)}
                              >
                                {mergeSourceIndex === idx ? "Cancel" : "Merge"}
                              </button>
                            </div>
                          </div>

                          <div className="row-wrap" style={{ gap: "0.9rem", margin: "0.6rem 0" }}>
                            <label className="row text-sm" style={{ gap: "0.45rem" }}>
                              <span className="label">Tag</span>
                              <input
                                className="input"
                                style={{ width: "160px", padding: "0.35rem 0.6rem" }}
                                value={s.tag}
                                onChange={(e) => {
                                  const updated = [...previewSections];
                                  updated[idx] = { ...updated[idx], tag: e.target.value };
                                  setPreviewSections(updated);
                                }}
                              />
                            </label>
                            <span className="muted text-sm">Page: {s.page_number ?? "—"}</span>
                          </div>

                          <textarea
                            className="textarea"
                            value={s.content}
                            onChange={(e) => {
                              const updated = [...previewSections];
                              updated[idx] = { ...updated[idx], content: e.target.value };
                              setPreviewSections(updated);
                            }}
                          />
                        </div>
                      );
                    })}
                  </div>

                  <div className="preview-viewer">
                    <div className="preview-viewer-head">
                      <strong>Original file</strong> <span className="muted">({previewFileName})</span>
                    </div>
                    {previewFileUrl ? (
                      previewFileUrl.toLowerCase().endsWith(".pdf") ? (
                        <iframe src={previewFileUrl} title="Original PDF" />
                      ) : previewFileUrl.match(/\.(png|jpe?g|gif)$/i) ? (
                        <img src={previewFileUrl} alt="Original" />
                      ) : (
                        <div className="empty-state" style={{ border: "none" }}>
                          <p className="empty-text">Preview not available for this file type.</p>
                          <a className="btn btn-ghost btn-sm" href={previewFileUrl} target="_blank" rel="noreferrer">
                            Download file
                          </a>
                        </div>
                      )
                    ) : (
                      <p className="muted text-sm" style={{ padding: "1rem" }}>No file available.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {message && <div className="toast">{message}</div>}

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading manuals…</div>
      ) : (
        <div>
          {/* ── Filters ── */}
          <div className="filter-panel">
            <div className="filter-row">
              <div className="field" style={{ flex: 2, minWidth: "260px" }}>
                <label className="label">Search</label>
                <div className="row" style={{ gap: "0.5rem" }}>
                  <select
                    className="select"
                    style={{ maxWidth: "150px" }}
                    value={searchBy}
                    onChange={(e) => { setSearchBy(e.target.value); setCurrentPage(1); }}
                  >
                    <option value="all">Search all</option>
                    <option value="title">By title</option>
                    <option value="department">By department</option>
                    <option value="author">By author</option>
                  </select>
                  <input
                    className="input"
                    type="text"
                    placeholder={
                      searchBy === "all" ? "Search title, department, or author…"
                        : searchBy === "title" ? "Search manual titles…"
                        : searchBy === "department" ? "Search departments…"
                        : "Search author names…"
                    }
                    value={searchQuery}
                    onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
                  />
                </div>
              </div>

              <button
                className={`btn btn-sm ${showAdvanced ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                {showAdvanced ? "Hide" : "Show"} advanced
                <span className={`chevron${showAdvanced ? " is-open" : ""}`}>▾</span>
              </button>
            </div>

            {showAdvanced && (
              <div className="filter-row filter-row-nested">
                <div className="field">
                  <label className="label">Author</label>
                  <input
                    className="input"
                    type="text"
                    placeholder="Filter by uploader…"
                    value={filters.author}
                    onChange={(e) => { setFilters({ ...filters, author: e.target.value }); setCurrentPage(1); }}
                  />
                </div>
                <div className="field">
                  <label className="label">Version</label>
                  <input
                    className="input"
                    type="number"
                    placeholder="e.g. 1, 2, 3"
                    value={filters.version}
                    onChange={(e) => { setFilters({ ...filters, version: e.target.value }); setCurrentPage(1); }}
                  />
                </div>
                <div className="field">
                  <label className="label">Min sections</label>
                  <input
                    className="input"
                    type="number"
                    placeholder="Minimum sections…"
                    value={filters.minSections}
                    onChange={(e) => { setFilters({ ...filters, minSections: e.target.value }); setCurrentPage(1); }}
                  />
                </div>
              </div>
            )}

            <div className="filter-row">
              <div className="field">
                <label className="label">Department</label>
                <select
                  className="select"
                  value={filters.department}
                  onChange={(e) => { setFilters({ ...filters, department: e.target.value }); setCurrentPage(1); }}
                >
                  <option value="">All departments</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="label">From date</label>
                <input
                  className="input"
                  type="date"
                  value={filters.dateFrom}
                  onChange={(e) => { setFilters({ ...filters, dateFrom: e.target.value }); setCurrentPage(1); }}
                />
              </div>
              <div className="field">
                <label className="label">To date</label>
                <input
                  className="input"
                  type="date"
                  value={filters.dateTo}
                  onChange={(e) => { setFilters({ ...filters, dateTo: e.target.value }); setCurrentPage(1); }}
                />
              </div>
              <div className="field">
                <label className="label">Sort by</label>
                <select
                  className="select"
                  value={filters.sortBy}
                  onChange={(e) => { setFilters({ ...filters, sortBy: e.target.value }); setCurrentPage(1); }}
                >
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                  <option value="recentEdit">Recently edited</option>
                </select>
              </div>
            </div>

            <div className="filter-summary">
              <span className="muted text-sm">
                Showing {filteredManuals.length === 0 ? 0 : startIndex + 1}–
                {Math.min(startIndex + itemsPerPage, filteredManuals.length)} of {filteredManuals.length} manuals
              </span>

              <div className="row-wrap" style={{ gap: "0.75rem" }}>
                <label className="row text-sm" style={{ gap: "0.4rem" }}>
                  <input
                    type="checkbox"
                    checked={selectedManualIds.length === paginatedManuals.length && paginatedManuals.length > 0}
                    onChange={(e) => toggleSelectAll(e.target.checked)}
                  />
                  Select all on page
                </label>
                <button
                  className="btn btn-danger-soft btn-sm"
                  onClick={handleBulkDelete}
                  disabled={selectedManualIds.length === 0}
                >
                  Delete selected ({selectedManualIds.length})
                </button>
                {hasActiveFilters && (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setSearchQuery("");
                      setSearchBy("all");
                      setShowAdvanced(false);
                      setFilters({ department: "", author: "", version: "", minSections: "", dateFrom: "", dateTo: "", sortBy: "newest" });
                      setCurrentPage(1);
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* ── List ── */}
          {manuals.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📚</div>
              <p className="empty-title">No manuals yet</p>
              <p className="empty-text">Upload a master copy above to get started.</p>
            </div>
          ) : filteredManuals.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">🔍</div>
              <p className="empty-title">No results</p>
              <p className="empty-text">No manuals match your current filters.</p>
            </div>
          ) : (
            <div>
              <div className="card" style={{ overflow: "hidden", marginBottom: "1.5rem" }}>
                {paginatedManuals.map((m) => (
                  <div key={m.id} className="list-row">
                    <div className="list-row-head" onClick={() => toggleExpandRow(m.id)}>
                      <input
                        type="checkbox"
                        checked={selectedManualIds.includes(m.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleManualSelection(m.id)}
                      />
                      <span className={`chevron${expandedRows.has(m.id) ? " is-open" : ""}`}>▾</span>

                      <div className="row-wrap" style={{ flex: 1, gap: "0.65rem" }}>
                        <strong>{m.title}</strong>
                        <span className="badge">{m.department}</span>
                        <span className="badge badge-warning">{m.section_count} sections</span>
                        <span className="subtle text-xs">
                          Uploaded {new Date(m.uploaded_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>

                    {expandedRows.has(m.id) && (
                      <div className="list-row-body">
                        <dl className="detail-grid">
                          <dt>QMS status</dt>
                          <dd><span className="badge badge-warning">v{m.version} rev{m.revision || 0}</span></dd>

                          <dt>Change version</dt>
                          <dd className="row" style={{ gap: "0.5rem" }}>
                            <select
                              className="select"
                              style={{ width: "110px", padding: "0.35rem 2rem 0.35rem 0.6rem" }}
                              value={manualVersionEdits[m.id] ?? m.version}
                              onChange={(e) => handleManualVersionChange(m.id, e.target.value)}
                            >
                              {[...Array(10)].map((_, idx) => (
                                <option key={idx + 1} value={idx + 1}>v{idx + 1}</option>
                              ))}
                            </select>
                            <button className="btn btn-primary btn-sm" onClick={() => updateManualVersion(m.id, m.version)}>
                              Save
                            </button>
                          </dd>

                          <dt>Uploaded by</dt>
                          <dd>{m.uploaded_by}</dd>

                          <dt>Upload date</dt>
                          <dd>{new Date(m.uploaded_at).toLocaleString()}</dd>

                          <dt>Sections</dt>
                          <dd>{m.section_count}</dd>
                        </dl>

                        <div className="row" style={{ gap: "0.5rem", paddingTop: "0.9rem", borderTop: "1px solid var(--border-soft)" }}>
                          <button className="btn btn-ghost btn-sm" onClick={() => toggleExpandRow(m.id)}>
                            ◀ Collapse
                          </button>
                          <button className="btn btn-danger-soft btn-sm" onClick={() => handleDelete(m.id, m.title)}>
                            Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {totalPages > 1 && (
                <div className="pagination">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setCurrentPage(currentPage - 1)}
                    disabled={currentPage === 1}
                  >
                    ◀ Prev
                  </button>

                  <div className="row" style={{ gap: "0.25rem" }}>
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                      <button
                        key={page}
                        className={`page-num${page === currentPage ? " is-active" : ""}`}
                        onClick={() => setCurrentPage(page)}
                      >
                        {page}
                      </button>
                    ))}
                  </div>

                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => setCurrentPage(currentPage + 1)}
                    disabled={currentPage === totalPages}
                  >
                    Next ▶
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

