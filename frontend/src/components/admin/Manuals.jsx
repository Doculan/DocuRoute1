import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";
import { formatDate, formatRevision } from "../documentStatus";
import DeadlineTag from "../DeadlineTag";
import Pager from "../Pager";
import { seriesToOpen } from "../manualPicker";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BACKEND_BASE_URL = "";

export default function Manuals({ initialSearch = "", onOpenSections }) {
  // The summary (`/api/manuals/`): series with counts, the uploaders.
  const [summary, setSummary] = useState(null);
  // Bumped after an upload or a delete, so open lists load again.
  const [reloadKey, setReloadKey] = useState(0);
  const [form, setForm] = useState({ title: "", file: null });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  // The full-page loader is for the first load only. Replacing the page
  // (filters included) on every keystroke unmounted the search box and
  // dropped focus after each letter.
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Preview state (review sectioning before finalizing)
  const [previewManual, setPreviewManual] = useState(null);
  const [previewSections, setPreviewSections] = useState([]);
  const [previewFileUrl, setPreviewFileUrl] = useState(null);
  const [previewFileName, setPreviewFileName] = useState(null);
  const [previewQuality, setPreviewQuality] = useState(null);
  const [previewExtractionError, setPreviewExtractionError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [mergeSourceIndex, setMergeSourceIndex] = useState(null);

  // Pagination & Filters
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [selectedManualIds, setSelectedManualIds] = useState([]);
  const [needle, setNeedle] = useState(initialSearch.trim());
  // Uploading is occasional; reading the list is constant. The form stays
  // folded away so it costs nothing on the visits where you are not uploading.
  const [showUpload, setShowUpload] = useState(false);
  const [filters, setFilters] = useState({ series: "", uploader: "", from: "", to: "" });
  // Applies inside the series groups as well as to a filtered list.
  const [sort, setSort] = useState("title");

  const fetchData = useCallback(async () => {
    setLoading(true);
    const token = localStorage.getItem("access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const { data } = await axios.get(`/api/manuals/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSummary(data);
      setReloadKey((k) => k + 1);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setLoadedOnce(true);
    }
  }, []);

  // The server searches, a moment after typing stops.
  useEffect(() => {
    const timer = setTimeout(() => setNeedle(searchQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 4000);
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
    if (!form.title || !form.file) return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    setUploading(true);

    const formData = new FormData();
    formData.append("title", form.title);
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
      setPreviewQuality(res.data.extraction_quality || null);
      setPreviewExtractionError(res.data.extraction_error || null);

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
      setForm({ title: "", file: null });
    } catch (err) {
      console.error("Upload preview error", err);
      showMessage(err.response?.data?.error || err.message || "❌ Upload preview failed.");
    } finally {
      setUploading(false);
    }
  };

  // Single and bulk share one prompt: they destroy the same thing, and a
  // bulk delete is exactly the case a token is for - one confirmation
  // covering the whole set rather than a password per manual.
  const [pendingDelete, setPendingDelete] = useState(null);

  const runDelete = async (reauthToken) => {
    const target = pendingDelete;
    setPendingDelete(null);

    const token = localStorage.getItem("access_token");
    if (!token) {
      showMessage("❌ Please log in first.");
      return;
    }
    const headers = {
      Authorization: `Bearer ${token}`, ...reauthHeader(reauthToken),
    };

    try {
      await Promise.all(
        target.ids.map((id) => axios.delete(`/api/manuals/${id}/delete/`, { headers }))
      );
      showMessage(target.ids.length === 1
        ? `🗑️ "${target.label}" deleted.`
        : `🗑️ Deleted ${target.ids.length} manuals.`);
      setSelectedManualIds([]);
      fetchData();
    } catch (err) {
      console.error(err);
      showMessage(err.response?.data?.error || "❌ Failed to delete.");
    }
  };

  const toggleManualSelection = (manualId) => {
    setSelectedManualIds((prev) =>
      prev.includes(manualId)
        ? prev.filter((id) => id !== manualId)
        : [...prev, manualId]
    );
  };

  const handleBulkDelete = () => {
    if (selectedManualIds.length === 0) {
      showMessage("❌ Select at least one manual first.");
      return;
    }
    setPendingDelete({
      ids: [...selectedManualIds],
      label: `${selectedManualIds.length} manuals`,
    });
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
      setPreviewQuality(null);
      setPreviewExtractionError(null);
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
    setPreviewQuality(null);
    setPreviewExtractionError(null);
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

  const filtering = Boolean(needle || filters.series || filters.uploader || filters.from || filters.to);

  // One admin row: expands for its details, deletes, opens its sections.
  const renderRow = (m) => (
    <div key={m.id} className="list-row">
      <div className="list-row-head" onClick={() => toggleExpandRow(m.id)}>
        <input
          type="checkbox"
          checked={selectedManualIds.includes(m.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => toggleManualSelection(m.id)}
          aria-label={`Select ${m.title}`}
        />
        <span className={`chevron${expandedRows.has(m.id) ? " is-open" : ""}`}>▾</span>

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* The title is a document number, so it is set in mono
              and never mistaken for the sentence beneath it. */}
          <div className="list-row-title">{m.title}</div>
          <div className="list-row-sub">
            Uploaded {new Date(m.uploaded_at).toLocaleDateString()} by {m.uploaded_by}
          </div>
        </div>

        <DeadlineTag tag={m.deadline} />
        {m.series ? <span className="badge">{m.series}</span>
          : <span className="badge badge-warning">unassigned</span>}
        {/* The section count is the obvious way into a
            manual's sections, so it is the thing you click.
            stopPropagation because the row itself expands. */}
        {onOpenSections ? (
          <button
            className="badge badge-neutral"
            style={{ cursor: "pointer", border: "none" }}
            title={`Open the ${m.section_count} sections of ${m.title}`}
            onClick={(e) => { e.stopPropagation(); onOpenSections(m.id); }}
          >
            {m.section_count} sections →
          </button>
        ) : (
          <span className="badge badge-neutral">{m.section_count} sections</span>
        )}
        {m.status && <span className="badge badge-id">{formatRevision(m.status.revision)}</span>}
      </div>

      {expandedRows.has(m.id) && (
        <div className="list-row-body">
          <dl className="detail-grid">
            <dt>Document status</dt>
            <dd>
              {m.status
                ? `${m.status.document_number} · version ${m.status.version} · ${formatRevision(m.status.revision)} · effective ${formatDate(m.status.effective_on)}`
                : "Not recorded yet"}
            </dd>

            <dt>Uploaded by</dt>
            <dd>{m.uploaded_by}</dd>

            <dt>Upload date</dt>
            <dd>{new Date(m.uploaded_at).toLocaleString()}</dd>

            <dt>Sections</dt>
            <dd>{m.section_count}</dd>
          </dl>

          <div className="row" style={{ gap: "0.5rem", paddingTop: "0.9rem", borderTop: "1px solid var(--border-soft)" }}>
            {onOpenSections && (
              <button
                className="btn btn-primary btn-sm"
                onClick={() => onOpenSections(m.id)}
              >
                Open sections →
              </button>
            )}
            <button className="btn btn-ghost btn-sm" onClick={() => toggleExpandRow(m.id)}>
              ◀ Collapse
            </button>
            <button className="btn btn-danger-soft btn-sm" onClick={() => setPendingDelete({ ids: [m.id], label: m.title })}>
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Manuals</h1>
          <p className="page-subtitle">Upload master copies and review their extracted sections. New documents start unassigned; link them on Manual series.</p>
        </div>
        <button
          className={`btn ${showUpload ? "btn-ghost" : "btn-primary"}`}
          onClick={() => setShowUpload(!showUpload)}
        >
          {showUpload ? "Close upload" : "Upload master copy"}
        </button>
      </header>

      {/* ── Upload (folded away until asked for) ── */}
      {(showUpload || previewManual) && (
      <div className="card card-pad anim-fade-up" style={{ marginBottom: "1.25rem" }}>
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

            {(previewQuality?.needs_review || previewExtractionError) && (
              <div className="alert alert-warning" style={{ marginTop: "0.85rem" }}>
                <strong>Review extraction before confirming.</strong>
                {previewExtractionError && <div>{previewExtractionError}</div>}
                {previewQuality?.warnings?.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
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
      )}

      {message && <div className="toast">{message}</div>}

      {(loading && !loadedOnce) || !summary ? (
        <div className="loading-row"><span className="spinner" /> Loading manuals…</div>
      ) : (
        <div>
          {/* Filters read as a toolbar: search, series, uploader. With none
              set the list is the series, folded (spec §11.1). */}
          <div className="filter-panel">
            <div className="filter-row">
              <input
                className="input"
                style={{ width: "260px" }}
                type="search"
                placeholder="Search by title…"
                aria-label="Search manuals by title"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              <select
                className="select"
                style={{ width: "auto" }}
                aria-label="Filter by series"
                value={filters.series}
                onChange={(e) => setFilters({ ...filters, series: e.target.value })}
              >
                <option value="">All series</option>
                {summary.groups.map((g) => (
                  <option key={g.series_id ?? "none"} value={g.series_id ?? "none"}>
                    {g.code || "Not in a series"} ({g.count.toLocaleString()})
                  </option>
                ))}
              </select>
              <select
                className="select"
                style={{ width: "auto" }}
                aria-label="Filter by uploader"
                value={filters.uploader}
                onChange={(e) => setFilters({ ...filters, uploader: e.target.value })}
              >
                <option value="">Any uploader</option>
                {summary.uploaders.map((u) => (
                  <option key={u.id} value={u.id}>{u.username}</option>
                ))}
              </select>
              <select
                className="select"
                style={{ width: "auto" }}
                aria-label="Sort"
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                <option value="title">By title</option>
                <option value="series">By series</option>
                <option value="newest">Newest upload first</option>
                <option value="oldest">Oldest upload first</option>
                <option value="sections">Most sections first</option>
              </select>
              <label className="row text-sm subtle" style={{ gap: "0.4rem" }}>
                Uploaded from
                <input className="input" type="date" style={{ width: "auto" }} aria-label="Uploaded from"
                       value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} />
              </label>
              <label className="row text-sm subtle" style={{ gap: "0.4rem" }}>
                to
                <input className="input" type="date" style={{ width: "auto" }} aria-label="Uploaded to"
                       value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} />
              </label>
              {filtering && (
                <button
                  className="pill"
                  onClick={() => { setSearchQuery(""); setNeedle(""); setFilters({ series: "", uploader: "", from: "", to: "" }); }}
                >
                  Clear
                </button>
              )}
            </div>

            {selectedManualIds.length > 0 && (
              <div className="filter-summary">
                <button className="btn btn-danger-soft btn-sm" onClick={handleBulkDelete}>
                  Delete selected ({selectedManualIds.length})
                </button>
              </div>
            )}
          </div>

          <h3 className="section-title">Master copies · {summary.total.toLocaleString()}</h3>

          {summary.total === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📚</div>
              <p className="empty-title">No manuals yet</p>
              <p className="empty-text">Upload a master copy above to get started.</p>
            </div>
          ) : filtering ? (
            <AdminPaged key={`${needle}|${JSON.stringify(filters)}|${sort}|${reloadKey}`}
                        params={{ q: needle, series: filters.series, uploader: filters.uploader,
                                  uploaded_from: filters.from, uploaded_to: filters.to, sort }}
                        renderRow={renderRow} />
          ) : (
            <div className="col" style={{ gap: "0.5rem" }}>
              {summary.groups.map((g) => (
                <AdminGroup key={`${g.series_id ?? "none"}|${sort}|${reloadKey}`} group={g} sort={sort}
                            renderRow={renderRow} startOpen={g === seriesToOpen(summary.groups)} />
              ))}
            </div>
          )}
        </div>
      )}

      {pendingDelete && (
        <ConfirmDestructive
          title={pendingDelete.ids.length === 1
            ? `Delete ${pendingDelete.label}?`
            : `Delete ${pendingDelete.ids.length} manuals?`}
          body={pendingDelete.ids.length === 1
            ? "Its sections and every revision proposed against them are deleted with it. The master copy PDF stays on disk, so the document can be imported again - the extracted text, the tagging and the history cannot."
            : `Their sections and every revision proposed against them are deleted too. The master copy PDFs stay on disk; the extracted text and history do not.`}
          confirmLabel={pendingDelete.ids.length === 1
            ? "Delete manual" : `Delete ${pendingDelete.ids.length} manuals`}
          onConfirm={runDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}

/** One series, folded unless it has the most open deadlines; 50 a page inside. */
function AdminGroup({ group, sort, renderRow, startOpen }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <div className={`card accordion${group.open_deadlines > 0 ? " is-warning" : ""}`}>
      <button type="button" className="accordion-head" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <span style={{ flex: 1, minWidth: 0 }} className="list-row-title">
          {group.code ? `${group.code} — ${group.title}` : "Not in a series"}
        </span>
        {group.open_deadlines > 0 && (
          <span className="badge badge-warning">{group.open_deadlines} with a deadline</span>
        )}
        <span className="subtle text-xs">{group.count.toLocaleString()} manuals</span>
        <span className={`chevron${open ? " is-open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="accordion-body">
          <AdminPaged params={{ series: group.series_id ?? "none", sort }} renderRow={renderRow} />
        </div>
      )}
    </div>
  );
}

/** A page of the admin's manuals for these filters, with its pager. */
function AdminPaged({ params, renderRow }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const key = JSON.stringify(params);

  useEffect(() => {
    const wanted = Object.fromEntries(Object.entries(JSON.parse(key)).filter(([, v]) => v));
    axios.get(`/api/manuals/`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
      params: { ...wanted, page },
    }).then((res) => setData(res.data)).catch(() => setData({ results: [], pages: 1 }));
  }, [key, page]);

  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  if (data.results.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">No results</p>
        <p className="empty-text">No manuals match your current filters.</p>
      </div>
    );
  }
  return (
    <>
      <div>{data.results.map(renderRow)}</div>
      <Pager paging={data} onPage={setPage} />
    </>
  );
}
