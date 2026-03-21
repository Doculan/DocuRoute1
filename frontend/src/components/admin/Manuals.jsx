import { useState, useEffect } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";

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

  const fetchData = async () => {
    setLoading(true);
    const token = localStorage.getItem("access_token");
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      const [manualsRes, deptsRes] = await Promise.all([
        axios.get(`${BASE_URL}/api/manuals/`, authHeaders),
        axios.get(`${BASE_URL}/api/departments/`, authHeaders),
      ]);
      setManuals(manualsRes.data);
      setDepartments(deptsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 4000);
  };

  const reindexParentIndices = (sections, removedIndex, removedParentIndex) => {
    return sections.map((sec, idx) => {
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
    setUploading(true);
    const token = localStorage.getItem("access_token");

    const formData = new FormData();
    formData.append("title", form.title);
    formData.append("department_id", form.department_id);
    formData.append("file", form.file);

    try {
      // Use the preview endpoint so user can review/edit sectioning before finalizing
      const res = await axios.post(
        "http://127.0.0.1:8000/api/manuals/upload-preview/",
        formData,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setPreviewManual({ id: res.data.manual_id, title: res.data.title });
      setPreviewFileUrl(res.data.file_url ? `${BASE_URL}${res.data.file_url}` : null);
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
    const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
    try {
      await axios.delete(`http://127.0.0.1:8000/api/manuals/${id}/delete/`, authHeaders);
      showMessage(`🗑️ "${title}" deleted.`);
      fetchData();
    } catch { showMessage("❌ Failed to delete."); }
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
    setConfirming(true);
    const token = localStorage.getItem("access_token");
    try {
      await axios.post(
        `http://127.0.0.1:8000/api/manuals/${previewManual.id}/confirm-sections/`,
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
    try {
      await axios.delete(
        `http://127.0.0.1:8000/api/manuals/${previewManual.id}/delete/`,
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
      ) : manuals.length === 0 ? (
        <div style={styles.empty}>No manuals yet. Upload one above.</div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Title</th>
              <th style={styles.th}>Department</th>
              <th style={styles.th}>Sections</th>
              <th style={styles.th}>Version</th>
              <th style={styles.th}>Uploaded By</th>
              <th style={styles.th}>Date</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {manuals.map((m) => (
              <tr key={m.id} style={styles.tr}>
                <td style={styles.td}>{m.title}</td>
                <td style={styles.td}>{m.department}</td>
                <td style={styles.td}>
                  <span style={styles.badge}>{m.section_count} sections</span>
                </td>
                {/* ✅ Document version column */}
                <td style={styles.td}>
                  <span style={styles.versionBadge}>v{m.version}</span>
                </td>
                <td style={styles.td}>{m.uploaded_by}</td>
                <td style={styles.td}>
                  {new Date(m.uploaded_at).toLocaleDateString()}
                </td>
                <td style={styles.td}>
                  <button
                    style={styles.deleteBtn}
                    onClick={() => handleDelete(m.id, m.title)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
  table: {
    width: "100%", borderCollapse: "collapse", backgroundColor: "#fff",
    borderRadius: "10px", overflow: "hidden",
    boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
  },
  th: {
    padding: "0.85rem 1rem", backgroundColor: "#f7f8fc",
    textAlign: "left", fontSize: "0.8rem",
    fontWeight: "700", color: "#444", textTransform: "uppercase",
  },
  tr: { borderBottom: "1px solid #f0f0f0" },
  td: { padding: "0.85rem 1rem", fontSize: "0.9rem", color: "#333" },
  badge: {
    padding: "0.25rem 0.6rem", backgroundColor: "#ebf4ff",
    color: "#4f46e5", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "600",
  },
  // ✅ NEW
  versionBadge: {
    padding: "0.25rem 0.6rem", backgroundColor: "#fefcbf",
    color: "#b7791f", borderRadius: "20px",
    fontSize: "0.78rem", fontWeight: "700",
    border: "1px solid #f6e05e",
  },
  deleteBtn: {
    padding: "0.35rem 0.85rem", backgroundColor: "#e53e3e",
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
  empty: {
    textAlign: "center", padding: "3rem", color: "#888",
    backgroundColor: "#fff", borderRadius: "10px",
  },
  loading: { textAlign: "center", color: "#888", padding: "2rem" },
};
