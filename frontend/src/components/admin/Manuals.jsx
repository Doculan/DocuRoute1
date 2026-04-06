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

  return (
    <div>
      <h2 style={styles.pageTitle}>Manuals</h2>

      <div style={styles.card}>
        <h3 style={styles.cardTitle}>Upload Master Copy</h3>
        <form onSubmit={handleUpload} style={styles.form}>
          <input
            style={styles.input}
            type="text"
            placeholder="Manual title (e.g. Business Affairs Manual)"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            required
          />
          <select
            style={styles.input}
            value={form.department_id}
            onChange={(e) => setForm({ ...form, department_id: e.target.value })}
            required
          >
            <option value="">Select Department</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <input
            style={styles.input}
            type="file"
            accept=".pdf,.txt,.png,.jpg,.jpeg"
            onChange={(e) => setForm({ ...form, file: e.target.files[0] })}
            required
          />
          <button style={styles.uploadBtn} type="submit" disabled={uploading}>
            {uploading ? "⏳ Extracting & previewing..." : "Upload & Preview"}
          </button>
        </form>

        {previewManual && (
          <div style={{ marginTop: "1rem", padding: "1rem", background: "#f7fafc", borderRadius: "10px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong>Preview for:</strong> {previewManual.title}
              </div>
              <div>
                <button style={styles.cancelButton} onClick={handleCancelPreview}>
                  Cancel preview
                </button>
                <button style={styles.confirmButton} onClick={handleConfirmSections} disabled={confirming}>
                  {confirming ? "Confirming..." : "Confirm sections"}
                </button>
              </div>
            </div>
            {mergeSourceIndex !== null && (
              <div style={{ marginTop: "0.75rem", padding: "0.75rem", background: "#f0fdf4", borderRadius: "8px", border: "1px solid #a7f3d0" }}>
                <strong>Merge mode:</strong> Select a target section below to merge into.
                <button
                  style={{
                    marginLeft: "0.75rem",
                    padding: "0.25rem 0.6rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    background: "#fff",
                    cursor: "pointer",
                  }}
                  onClick={cancelMerge}
                >
                  Cancel
                </button>
              </div>
            )}

            <div style={{ marginTop: "1rem" }}>
              {previewSections.length === 0 ? (
                <p style={{ margin: 0 }}>No sections detected in preview.</p>
              ) : (
                <div style={styles.previewSplit}>
                  <div style={styles.previewList}>
                    {previewSections.map((s, idx) => {
                      const depth = getDepth(idx);
                      return (
                        <div key={idx} style={{ ...styles.sectionCard, marginLeft: depth * 18 }}>
                          <div style={styles.previewRow}>
                            <input
                              style={styles.previewInput}
                              value={s.subtitle}
                              onChange={(e) => {
                                const updated = [...previewSections];
                                updated[idx] = { ...updated[idx], subtitle: e.target.value };
                                setPreviewSections(updated);
                              }}
                            />
                            {s.is_chapter && <span style={styles.chapterBadge}>CHAPTER</span>}
                            <div style={styles.mergeActions}>
                              {mergeSourceIndex !== null && mergeSourceIndex !== idx && (
                                <button
                                  style={styles.mergeTargetBtn}
                                  onClick={() => handleMerge(idx)}
                                >
                                  Merge into this
                                </button>
                              )}
                              <button
                                style={{
                                  ...styles.mergeBtn,
                                  backgroundColor: mergeSourceIndex === idx ? "#f97316" : "#38bdf8",
                                  color: "#0f172a",
                                }}
                                onClick={() => startMerge(idx)}
                              >
                                {mergeSourceIndex === idx ? "Cancel" : "Merge"}
                              </button>
                            </div>
                          </div>
                          <div style={styles.previewMeta}>
                            <label style={styles.metaLabel}>
                              Tag:
                              <input
                                style={styles.previewMetaInput}
                                value={s.tag}
                                onChange={(e) => {
                                  const updated = [...previewSections];
                                  updated[idx] = { ...updated[idx], tag: e.target.value };
                                  setPreviewSections(updated);
                                }}
                              />
                            </label>
                            <span>Page: {s.page_number ?? "—"}</span>
                          </div>
                          <textarea
                            style={styles.previewTextarea}
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

                  <div style={styles.previewViewer}>
                    <div style={styles.previewViewerHeader}>
                      <strong>Original file</strong> ({previewFileName})
                    </div>
                    {previewFileUrl ? (
                      previewFileUrl.toLowerCase().endsWith(".pdf") ? (
                        <iframe
                          src={previewFileUrl}
                          style={styles.pdfViewer}
                          title="Original PDF"
                        />
                      ) : (previewFileUrl.match(/\.(png|jpe?g|gif)$/i) ? (
                        <img src={previewFileUrl} style={styles.imageViewer} alt="Original" />
                      ) : (
                        <div style={styles.unsupportedFile}>
                          <p>Preview not available for this file type.</p>
                          <a href={previewFileUrl} target="_blank" rel="noreferrer">
                            Download file
                          </a>
                        </div>
                      ))
                    ) : (
                      <p style={{ margin: 0 }}>No file available.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {message && <div style={styles.toast}>{message}</div>}

      {loading ? (
        <p style={styles.loading}>Loading...</p>
      ) : (
        <div>
          {/* Filter Controls - Always Show */}
          <div style={styles.filterPanel}>
            {/* Search Row with Search By Selector */}
            <div style={styles.filterRow}>
              <div style={{ ...styles.filterGroup, flex: 2 }}>
                <label style={styles.filterLabel}>Search:</label>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <select
                    style={{ ...styles.filterSelect, flex: 0.8, minWidth: "100px" }}
                    value={searchBy}
                    onChange={(e) => {
                      setSearchBy(e.target.value);
                      setCurrentPage(1);
                    }}
                  >
                    <option value="all">Search All</option>
                    <option value="title">By Title</option>
                    <option value="department">By Department</option>
                    <option value="author">By Author</option>
                  </select>
                  <input
                    type="text"
                    style={{ ...styles.filterInput, flex: 2 }}
                    placeholder={
                      searchBy === "all"
                        ? "Search title, department, or author..."
                        : searchBy === "title"
                        ? "Search manual titles..."
                        : searchBy === "department"
                        ? "Search departments..."
                        : "Search author names..."
                    }
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setCurrentPage(1);
                    }}
                  />
                </div>
              </div>
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                style={{
                  padding: "0.5rem 1rem",
                  backgroundColor: showAdvanced ? "#4a47a3" : "#e8eaf6",
                  color: showAdvanced ? "#fff" : "#4a47a3",
                  border: "1px solid #c7d2fe",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontWeight: "600",
                  fontSize: "0.85rem",
                  alignSelf: "flex-end",
                }}
              >
                {showAdvanced ? "Hide" : "Show"} Advanced
              </button>
            </div>

            {/* Advanced Filters */}
            {showAdvanced && (
              <div style={{ ...styles.filterRow, backgroundColor: "#f8f9fa", padding: "0.75rem", borderRadius: "8px", marginTop: "0.5rem" }}>
                <div style={styles.filterGroup}>
                  <label style={styles.filterLabel}>Author:</label>
                  <input
                    type="text"
                    style={styles.filterInput}
                    placeholder="Filter by uploader..."
                    value={filters.author}
                    onChange={(e) => {
                      setFilters({ ...filters, author: e.target.value });
                      setCurrentPage(1);
                    }}
                  />
                </div>

                <div style={styles.filterGroup}>
                  <label style={styles.filterLabel}>Version:</label>
                  <input
                    type="number"
                    style={styles.filterInput}
                    placeholder="e.g., 1, 2, 3"
                    value={filters.version}
                    onChange={(e) => {
                      setFilters({ ...filters, version: e.target.value });
                      setCurrentPage(1);
                    }}
                  />
                </div>

                <div style={styles.filterGroup}>
                  <label style={styles.filterLabel}>Min Sections:</label>
                  <input
                    type="number"
                    style={styles.filterInput}
                    placeholder="Minimum sections..."
                    value={filters.minSections}
                    onChange={(e) => {
                      setFilters({ ...filters, minSections: e.target.value });
                      setCurrentPage(1);
                    }}
                  />
                </div>
              </div>
            )}

            <div style={styles.filterRow}>
              <div style={styles.filterGroup}>
                <label style={styles.filterLabel}>Department:</label>
                <select
                  style={styles.filterSelect}
                  value={filters.department}
                  onChange={(e) => {
                    setFilters({ ...filters, department: e.target.value });
                    setCurrentPage(1);
                  }}
                >
                  <option value="">All Departments</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>

              <div style={styles.filterGroup}>
                <label style={styles.filterLabel}>From Date:</label>
                <input
                  type="date"
                  style={styles.filterInput}
                  value={filters.dateFrom}
                  onChange={(e) => {
                    setFilters({ ...filters, dateFrom: e.target.value });
                    setCurrentPage(1);
                  }}
                />
              </div>

              <div style={styles.filterGroup}>
                <label style={styles.filterLabel}>To Date:</label>
                <input
                  type="date"
                  style={styles.filterInput}
                  value={filters.dateTo}
                  onChange={(e) => {
                    setFilters({ ...filters, dateTo: e.target.value });
                    setCurrentPage(1);
                  }}
                />
              </div>

              <div style={styles.filterGroup}>
                <label style={styles.filterLabel}>Sort By:</label>
                <select
                  style={styles.filterSelect}
                  value={filters.sortBy}
                  onChange={(e) => {
                    setFilters({ ...filters, sortBy: e.target.value });
                    setCurrentPage(1);
                  }}
                >
                  <option value="newest">Newest First</option>
                  <option value="oldest">Oldest First</option>
                  <option value="recentEdit">Recently Edited</option>
                </select>
              </div>
            </div>

            <div style={styles.filterSummary}>
              <span>Showing {filteredManuals.length === 0 ? 0 : startIndex + 1}–{Math.min(startIndex + itemsPerPage, filteredManuals.length)} of {filteredManuals.length} manuals</span>
              <div style={styles.bulkControls}>
                <label style={styles.bulkLabel}>
                  <input
                    type="checkbox"
                    checked={selectedManualIds.length === paginatedManuals.length && paginatedManuals.length > 0}
                    onChange={(e) => toggleSelectAll(e.target.checked)}
                    style={styles.bulkCheckbox}
                  />
                  Select all page
                </label>
                <button
                  onClick={handleBulkDelete}
                  style={styles.bulkDeleteBtn}
                  disabled={selectedManualIds.length === 0}
                >
                  Delete selected ({selectedManualIds.length})
                </button>
              </div>
              {(searchQuery || filters.department || filters.author || filters.version || filters.dateFrom || filters.dateTo) && (
                <button
                  onClick={() => {
                    setSearchQuery("");
                    setSearchBy("all");
                    setShowAdvanced(false);
                    setFilters({ department: "", author: "", version: "", minSections: "", dateFrom: "", dateTo: "", sortBy: "newest" });
                    setCurrentPage(1);
                  }}
                  style={{
                    marginLeft: "1rem",
                    padding: "0.4rem 0.8rem",
                    backgroundColor: "#e53e3e",
                    color: "#fff",
                    border: "none",
                    borderRadius: "6px",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                  }}
                >
                  Clear Filters
                </button>
              )}
            </div>
          </div>

          {/* Manuals List or Empty State */}
          {manuals.length === 0 ? (
            <div style={styles.empty}>No manuals yet. Upload one above.</div>
          ) : filteredManuals.length === 0 ? (
            <div style={styles.empty}>No results match your filters.</div>
          ) : (
            <div>
              {/* Collapsible List */}
              <div style={styles.collapsibleList}>
            {paginatedManuals.map((m) => (
              <div key={m.id} style={styles.collapsibleItem}>
                <div
                  style={styles.collapsibleHeader}
                  onClick={() => toggleExpandRow(m.id)}
                >
                  <input
                    type="checkbox"
                    checked={selectedManualIds.includes(m.id)}
                    onChange={(e) => {
                      e.stopPropagation();
                      toggleManualSelection(m.id);
                    }}
                    style={styles.manualCheckbox}
                  />
                  <span style={styles.expandIcon}>
                    {expandedRows.has(m.id) ? "▼" : "▶"} 
                  </span>
                  <div style={styles.headerContent}>
                    <strong style={styles.manualTitle}>{m.title}</strong>
                    <span style={styles.departmentTag}>{m.department}</span>
                    <span style={styles.dateTag}>
                      Uploaded: {new Date(m.uploaded_at).toLocaleDateString()}
                    </span>
                    <span style={styles.sectionTag}>
                      {m.section_count} sections
                    </span>
                  </div>
                </div>

                {expandedRows.has(m.id) && (
                  <div style={styles.collapsibleContent}>
                    <div style={styles.detailRow}>
                      <span style={styles.detailLabel}>QMS Status:</span>
                      <span style={styles.versionBadgeExpanded}>v{m.version} rev{m.revision || 0}</span>
                    </div>
                    <div style={styles.detailRow}>
                      <span style={styles.detailLabel}>Change Version:</span>
                      <select
                        value={manualVersionEdits[m.id] ?? m.version}
                        onChange={(e) => handleManualVersionChange(m.id, e.target.value)}
                        style={styles.versionSelectAdmin}
                      >
                        {[...Array(10)].map((_, idx) => (
                          <option key={idx + 1} value={idx + 1}>v{idx + 1}</option>
                        ))}
                      </select>
                      <button
                        style={styles.actionBtn}
                        onClick={() => updateManualVersion(m.id, m.version)}
                      >Save</button>
                    </div>
                    <div style={styles.detailRow}>
                      <span style={styles.detailLabel}>Uploaded By:</span>
                      <span>{m.uploaded_by}</span>
                    </div>
                    <div style={styles.detailRow}>
                      <span style={styles.detailLabel}>Upload Date:</span>
                      <span>{new Date(m.uploaded_at).toLocaleString()}</span>
                    </div>
                    <div style={styles.detailRow}>
                      <span style={styles.detailLabel}>Sections:</span>
                      <span>{m.section_count}</span>
                    </div>
                    <div style={styles.detailActions}>
                      <button
                        style={styles.backBtn}
                        onClick={() => toggleExpandRow(m.id)}
                      >
                        ◀ Back
                      </button>
                      <button
                        style={styles.deleteBtn}
                        onClick={() => handleDelete(m.id, m.title)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div style={styles.pagination}>
              <button
                style={styles.pageBtn}
                onClick={() => setCurrentPage(currentPage - 1)}
                disabled={currentPage === 1}
              >
                ◀ Prev
              </button>

              <div style={styles.pageNumbers}>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                  <button
                    key={page}
                    style={{
                      ...styles.pageNumber,
                      ...(page === currentPage ? styles.pageNumberActive : {}),
                    }}
                    onClick={() => setCurrentPage(page)}
                  >
                    {page}
                  </button>
                ))}
              </div>

              <button
                style={styles.pageBtn}
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

const styles = {
  pageTitle: { margin: "0 0 1.5rem 0", color: "#1a1a2e" },
  card: {
    backgroundColor: "#fff", borderRadius: "10px",
    padding: "1.5rem", marginBottom: "1.5rem",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
  },
  cardTitle: { margin: "0 0 1rem 0", color: "#333", fontSize: "1rem" },
  form: { display: "flex", flexDirection: "column", gap: "0.75rem" },
  input: {
    padding: "0.7rem 1rem", borderRadius: "8px",
    border: "1px solid #ddd", fontSize: "0.95rem", outline: "none",
  },
  uploadBtn: {
    padding: "0.75rem", backgroundColor: "#4f46e5",
    color: "#fff", border: "none", borderRadius: "8px",
    cursor: "pointer", fontWeight: "600",
  },
  toast: {
    backgroundColor: "#ebf8ff", border: "1px solid #bee3f8",
    borderRadius: "8px", padding: "0.75rem 1rem",
    marginBottom: "1rem", color: "#2b6cb0", fontWeight: "500",
  },

  // Filter Panel Styles
  filterPanel: {
    backgroundColor: "#f8fafc", borderRadius: "10px",
    padding: "1rem", marginBottom: "1.5rem",
    border: "1px solid #e2e8f0",
  },
  filterRow: {
    display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "0.75rem",
    alignItems: "flex-end",
  },
  filterGroup: {
    display: "flex", flexDirection: "column", gap: "0.35rem",
  },
  filterLabel: {
    fontSize: "0.8rem", fontWeight: "600", color: "#475569",
    textTransform: "uppercase",
  },
  filterSelect: {
    padding: "0.5rem 0.75rem", borderRadius: "6px",
    border: "1px solid #cbd5e1", fontSize: "0.9rem",
    backgroundColor: "#fff", cursor: "pointer", minWidth: "150px",
  },
  filterInput: {
    padding: "0.5rem 0.75rem", borderRadius: "6px",
    border: "1px solid #cbd5e1", fontSize: "0.9rem",
    backgroundColor: "#fff", minWidth: "140px",
  },
  filterSummary: {
    fontSize: "0.85rem", color: "#64748b", fontStyle: "italic",
    display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap"
  },
  bulkControls: {
    display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap"
  },
  bulkLabel: {
    display: "flex", alignItems: "center", gap: "0.4rem",
    fontSize: "0.85rem", color: "#334155"
  },
  bulkCheckbox: {
    width: "16px", height: "16px"
  },
  bulkDeleteBtn: {
    padding: "0.45rem 0.8rem",
    backgroundColor: "#ef4444",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.85rem",
    fontWeight: "600"
  },
  manualCheckbox: {
    width: "18px",
    height: "18px",
    marginRight: "0.75rem",
    cursor: "pointer"
  },

  // Collapsible List Styles
  collapsibleList: {
    backgroundColor: "#fff", borderRadius: "10px",
    overflow: "hidden", boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
    marginBottom: "1.5rem",
  },
  collapsibleItem: {
    borderBottom: "1px solid #f0f0f0",
  },
  collapsibleHeader: {
    padding: "1rem 1.5rem", display: "flex",
    alignItems: "center", gap: "1rem", cursor: "pointer",
    backgroundColor: "#fff", transition: "background-color 0.2s",
    userSelect: "none",
  },
  expandIcon: {
    fontSize: "1rem", color: "#4f46e5", fontWeight: "bold",
    minWidth: "1rem",
  },
  headerContent: {
    display: "flex", alignItems: "center", gap: "0.75rem", flex: 1,
    flexWrap: "wrap",
  },
  manualTitle: {
    fontSize: "0.95rem", color: "#1a1a2e",
  },
  departmentTag: {
    fontSize: "0.75rem", backgroundColor: "#e0e7ff",
    color: "#4f46e5", padding: "0.25rem 0.6rem", borderRadius: "4px",
    fontWeight: "500",
  },
  dateTag: {
    fontSize: "0.75rem", color: "#666",
  },
  sectionTag: {
    fontSize: "0.75rem", backgroundColor: "#fef3c7",
    color: "#b7791f", padding: "0.25rem 0.6rem", borderRadius: "4px",
    fontWeight: "500",
  },
  collapsibleContent: {
    backgroundColor: "#f8fafc", padding: "1rem 1.5rem",
    borderTop: "1px solid #e2e8f0",
  },
  detailRow: {
    display: "flex", gap: "1rem", marginBottom: "0.75rem", fontSize: "0.9rem",
  },
  detailLabel: {
    fontWeight: "600", color: "#475569", minWidth: "120px",
  },
  detailActions: {
    marginTop: "1rem", paddingTop: "0.75rem",
    borderTop: "1px solid #e2e8f0", display: "flex", gap: "0.5rem",
  },
  versionBadgeExpanded: {
    padding: "0.25rem 0.6rem", backgroundColor: "#fefcbf",
    color: "#b7791f", borderRadius: "4px",
    fontSize: "0.85rem", fontWeight: "700",
    border: "1px solid #f6e05e",
  },
  versionSelectAdmin: {
    border: "1px solid #cbd5e1",
    borderRadius: "6px",
    padding: "0.25rem 0.5rem",
    fontSize: "0.85rem",
    marginRight: "0.5rem",
    backgroundColor: "#fff",
    color: "#1f2937",
  },

  // Pagination Styles
  pagination: {
    display: "flex", justifyContent: "center", alignItems: "center",
    gap: "0.5rem", marginTop: "1.5rem", flexWrap: "wrap",
  },
  pageBtn: {
    padding: "0.5rem 0.75rem", border: "1px solid #cbd5e1",
    backgroundColor: "#fff", borderRadius: "6px", cursor: "pointer",
    fontSize: "0.9rem", fontWeight: "500", color: "#333",
    transition: "all 0.2s",
  },
  pageNumbers: {
    display: "flex", gap: "0.25rem",
  },
  pageNumber: {
    padding: "0.4rem 0.65rem", border: "1px solid #cbd5e1",
    backgroundColor: "#fff", borderRadius: "6px", cursor: "pointer",
    fontSize: "0.85rem", fontWeight: "500", color: "#333",
    transition: "all 0.2s",
  },
  pageNumberActive: {
    backgroundColor: "#4f46e5", color: "#fff", borderColor: "#4f46e5",
  },

  // Other Styles
  loading: { textAlign: "center", color: "#666", padding: "2rem" },
  empty: {
    textAlign: "center", padding: "2rem", color: "#999",
    backgroundColor: "#f8fafc", borderRadius: "10px",
  },
  deleteBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  backBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#f59e0b",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  confirmButton: {
    marginLeft: "0.5rem",
    padding: "0.35rem 0.85rem", backgroundColor: "#22c55e",
    color: "#0f172a", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  cancelButton: {
    padding: "0.35rem 0.85rem", backgroundColor: "#fbbf24",
    color: "#0f172a", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
  mergeActions: { display: "flex", gap: "0.5rem", alignItems: "center" },
  mergeBtn: {
    padding: "0.35rem 0.85rem",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "600",
  },
  mergeTargetBtn: {
    padding: "0.35rem 0.85rem",
    backgroundColor: "#22c55e",
    color: "#0f172a",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "600",
  },
  previewSplit: { display: "flex", gap: "1rem", alignItems: "flex-start" },
  previewList: { flex: 1, maxHeight: "65vh", overflowY: "auto" },
  previewViewer: { flex: 1, minWidth: "320px", maxHeight: "65vh", overflow: "hidden", borderRadius: "10px", border: "1px solid #e2e8f0", backgroundColor: "#fff" },
  previewViewerHeader: { padding: "0.75rem 1rem", borderBottom: "1px solid #e2e8f0", backgroundColor: "#f7f8fc", fontWeight: "700" },
  pdfViewer: { width: "100%", height: "100%", border: "none" },
  imageViewer: { width: "100%", height: "100%", objectFit: "contain" },
  unsupportedFile: { padding: "1rem", textAlign: "center", color: "#666", fontSize: "0.9rem" },
  sectionCard: {
    padding: "0.9rem",
    marginBottom: "0.8rem",
    backgroundColor: "#fff",
    borderRadius: "10px",
    border: "1px solid #e2e8f0",
  },
  previewRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: "0.5rem",
  },
  previewMeta: {
    fontSize: "0.85rem",
    color: "#555",
    display: "flex",
    gap: "1rem",
    marginTop: "0.35rem",
    alignItems: "center",
  },
  metaLabel: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    fontSize: "0.85rem",
    color: "#555",
  },
  previewMetaInput: {
    padding: "0.25rem 0.5rem",
    borderRadius: "6px",
    border: "1px solid #cbd5e1",
    fontSize: "0.85rem",
  },
  previewInput: {
    width: "60%",
    padding: "0.35rem 0.6rem",
    borderRadius: "8px",
    border: "1px solid #cbd5e1",
    fontSize: "0.95rem",
  },
  previewTextarea: {
    width: "100%",
    minHeight: "120px",
    marginTop: "0.6rem",
    borderRadius: "8px",
    border: "1px solid #cbd5e1",
    padding: "0.6rem",
    fontFamily: "inherit",
  },
  chapterBadge: {
    backgroundColor: "#f1f5f9",
    color: "#1e3a8a",
    borderRadius: "12px",
    padding: "0.2rem 0.6rem",
    fontSize: "0.75rem",
    fontWeight: "700",
  },
};
