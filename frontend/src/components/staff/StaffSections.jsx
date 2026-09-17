import { useState, useEffect, useRef } from "react";
import axios from "axios";
import DiffView from "../DiffView";
import DocTable from "../DocTable";
import { parseTableRow, isTableSeparator } from "../../docTable";

// Must stay in sync with normalize_for_diff() in Backend/api/views.py - the
// server diffs submitted text against content normalized the same way.
const formatOCRContent = (content = "") => {
  return content
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(//g, "•")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
};

const BASE_URL = "http://127.0.0.1:8000";

const TAG_CLASS = {
  POLICY:                "badge-info",
  PROCEDURE:             "badge-success",
  RESPONSIBILITY:        "badge-danger",
  "WORKING INSTRUCTION": "badge-warning",
  UNTAGGED:              "badge-neutral",
};

const tagClass = (tag) => TAG_CLASS[tag] || "badge-neutral";

const STATUS_CLASS = {
  pending:  { badge: "badge-warning", tone: "is-warning" },
  approved: { badge: "badge-success", tone: "is-success" },
  rejected: { badge: "badge-danger",  tone: "is-danger" },
};

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function SectionContent({ content }) {
  const cleaned = (content || "")
    .replace(/\|\|TABLE_START\|\|/g, "")
    .replace(/\|\|TABLE_END\|\|/g, "");

  const lines = cleaned.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  const blocks = [];
  let tableRows = [];
  let inTable = false;
  let lastRow = null;
  let declaredWidth = null;

  const flushTable = () => {
    if (tableRows.length > 0) {
      blocks.push({ type: "table", rows: tableRows, declaredWidth });
      tableRows = [];
      lastRow = null;
    }
    declaredWidth = null;
    inTable = false;
  };

  lines.forEach((line) => {
    // The separator states the column count, then drops out.
    if (isTableSeparator(line)) {
      const spec = parseTableRow(line);
      if (spec) {
        declaredWidth = spec.length;
        inTable = true;
      }
      return;
    }

    const row = parseTableRow(line);
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
    <div className="prose">
      {blocks.map((block, idx) => {
        if (block.type === "table") {
          return <DocTable key={idx} rows={block.rows} declaredWidth={block.declaredWidth} />;
        }
        return <p key={idx}>{block.text}</p>;
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

  // Search and Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilter, setTagFilter]     = useState("");

  // Revision submit
  const [showRevForm, setShowRevForm] = useState(false);
  const [revFile, setRevFile]         = useState(null);
  const [revLoading, setRevLoading]   = useState(false);
  const [revMsg, setRevMsg]           = useState("");
  const [revMsgType, setRevMsgType]   = useState("success");
  // ISO 9001 clause 6.3 expects changes to be planned, so every revision has
  // to say why it is being made. Layer 1 treats an empty reason as a hard fail.
  const [changeReason, setChangeReason] = useState("");
  const fileInputRef                  = useRef();

  // Text edit
  const [isEditing, setIsEditing]     = useState(false);
  const [editedContent, setEditedContent] = useState("");

  // Merge proposal
  const [mergeSource, setMergeSource] = useState(null);
  const [mergeTarget, setMergeTarget] = useState(null);
  const [mergeMsg, setMergeMsg]       = useState("");
  const [mergeMsgType, setMergeMsgType] = useState("success");

  // My revisions for this section
  const [sectionRevisions, setSectionRevisions] = useState([]);
  const [revTab, setRevTab]           = useState("content"); // "content" | "revisions"

  useEffect(() => {
    const loadSections = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (tagFilter) params.append('tag', tagFilter);
        if (searchQuery.trim()) params.append('search', searchQuery.trim());

        const url = `${BASE_URL}/api/manuals/${manualId}/sections/?${params.toString()}`;
        const res = await axios.get(url, getAuth());

        setSections(res.data.sections || []);
        setFileUrl(res.data.file_url ? `${BASE_URL}${res.data.file_url}` : null);
        if (res.data.sections?.length > 0) {
          setManual({ version: res.data.manual_version });
          setIsFullDoc(true);
        }
      } catch (err) {
        console.error("Error loading sections:", err);
      } finally {
        setLoading(false);
      }
    };

    if (manualId) {
      loadSections();
    }
  }, [manualId, tagFilter, searchQuery]);

  const handleSelectSection = (s) => {
    setActive(s);
    setIsFullDoc(false);
    setShowRevForm(false);
    setRevMsg("");
    setRevFile(null);
    setRevTab("content");
    setIsEditing(false);
    setEditedContent("");
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
    if (!changeReason.trim()) {
      setRevMsg("Please give a reason for this change - a short sentence saying what changed and why."); setRevMsgType("error"); return;
    }
    setRevLoading(true);
    setRevMsg("");
    const formData = new FormData();
    formData.append("file", revFile);
    formData.append("change_reason", changeReason.trim());
    try {
      await axios.post(
        `${BASE_URL}/api/revisions/upload/${activeSection.id}/`,
        formData,
        { headers: { ...getAuth().headers, "Content-Type": "multipart/form-data" } }
      );
      setRevMsg("Revision submitted successfully. An admin will review it.");
      setRevMsgType("success");
      setRevFile(null);
      setChangeReason("");
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

  const handleSubmitTextRevision = async () => {
    if (!editedContent.trim()) {
      setRevMsg("Edited content cannot be empty.");
      setRevMsgType("error");
      return;
    }
    if (!changeReason.trim()) {
      setRevMsg("Please give a reason for this change - a short sentence saying what changed and why.");
      setRevMsgType("error");
      return;
    }
    setRevLoading(true);
    setRevMsg("");
    try {
      await axios.post(
        `${BASE_URL}/api/revisions/propose-text/${activeSection.id}/`,
        { proposed_content: editedContent, change_reason: changeReason.trim() },
        getAuth()
      );
      setRevMsg("Text revision proposed successfully. An admin will review it.");
      setRevMsgType("success");
      setIsEditing(false);
      setEditedContent("");
      setChangeReason("");
      loadSectionRevisions(activeSection.id);
    } catch (err) {
      const msg = err.response?.data?.error || "Submission failed. Try again.";
      setRevMsg(msg);
      setRevMsgType("error");
    } finally {
      setRevLoading(false);
    }
  };

  const handleProposeMerge = async () => {
    if (!mergeSource || !mergeTarget) {
      setMergeMsg("Select both source and target sections for merge.");
      return;
    }
    if (mergeSource.id === mergeTarget.id) {
      setMergeMsg("Source and target cannot be the same section.");
      return;
    }
    if (!changeReason.trim()) {
      setMergeMsg("Please give a reason for this change - a short sentence saying what changed and why.");
      setMergeMsgType("error");
      return;
    }

    try {
      setMergeMsg("Submitting merge proposal...");
      await axios.post(
        `${BASE_URL}/api/revisions/propose-merge/`,
        {
          source_section_id: mergeSource.id,
          target_section_id: mergeTarget.id,
          change_reason: changeReason.trim(),
        },
        getAuth()
      );
      setMergeMsg("✅ Merge proposal submitted successfully.");
      setMergeSource(null);
      setMergeTarget(null);
      setMergeMsgType("success");
      loadSectionRevisions(activeSection.id);
    } catch (err) {
      const msg = err.response?.data?.error || "Merge proposal failed.";
      setMergeMsg(msg);
      setMergeMsgType("error");
    }
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading sections…</div>;
  }

  const pendingCount = sectionRevisions.filter((r) => r.status === "pending").length;
  const activeTag = activeSection?.tag;

  return (
    <div className="reader">
      <div className="reader-bar">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back to manuals</button>
        {fileUrl && (
          <button
            className={`btn btn-sm ${showOriginal ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setShowOriginal((v) => !v)}
          >
            {showOriginal ? "Hide original" : "View original file"}
          </button>
        )}
      </div>

      <div className="reader-split">
        {/* ── Table of contents ── */}
        <aside className="reader-toc">
          <div className="toc-head">
            <div className="toc-head-title">Table of Contents</div>
            {manual && <div className="toc-head-meta">Document v{manual.version}</div>}
          </div>

          <div className="toc-filters">
            <input
              className="input"
              type="text"
              placeholder="Search sections…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <select
              className="select"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
            >
              <option value="">All types</option>
              <option value="POLICY">Policy</option>
              <option value="PROCEDURE">Procedure</option>
              <option value="RESPONSIBILITY">Responsibility</option>
              <option value="WORKING INSTRUCTION">Working Instruction</option>
              <option value="PAGE_HEADER">Page Header</option>
              <option value="UNTAGGED">Untagged</option>
            </select>
            {(searchQuery || tagFilter) && (
              <div className="row text-xs muted" style={{ justifyContent: "space-between" }}>
                <span>{sections.length} section{sections.length === 1 ? "" : "s"}</span>
                <button
                  className="link-btn text-xs"
                  onClick={() => { setSearchQuery(""); setTagFilter(""); }}
                >
                  Clear filters
                </button>
              </div>
            )}
          </div>

          <div className="toc-list">
            {sections.length > 0 && (
              <button
                className={`toc-item is-doc${isFullDoc ? " is-active" : ""}`}
                onClick={() => { setIsFullDoc(true); setActive(null); setShowRevForm(false); }}
              >
                <span className="toc-item-title">📄 Full document</span>
                <span className="toc-item-meta">{sections.length} sections</span>
              </button>
            )}

            {sections.length === 0 ? (
              <p className="muted text-sm" style={{ textAlign: "center", padding: "1.5rem 1rem" }}>
                No sections available.
              </p>
            ) : (
              sections.map((s) => {
                const isActive = !isFullDoc && activeSection?.id === s.id;
                return (
                  <button
                    key={s.id}
                    className={`toc-item${isActive ? " is-active" : ""}`}
                    onClick={() => handleSelectSection(s)}
                  >
                    <span className="toc-item-title">{s.subtitle}</span>
                    <span className="row" style={{ gap: "0.4rem" }}>
                      <span className={`badge ${tagClass(s.tag)}`}>{s.tag}</span>
                      {s.page_number && <span className="toc-item-meta">p.{s.page_number}</span>}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* ── Content panel ── */}
        <section className="reader-panel">
          {showOriginal && fileUrl ? (
            <div className="reader-frame">
              <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
                <strong>Original document</strong>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowOriginal(false)}>✕ Close</button>
              </div>
              <iframe src={fileUrl} title="Original document" />
            </div>
          ) : isFullDoc ? (
            <div className="anim-fade-up">
              <h2 className="page-title" style={{ fontSize: "1.35rem" }}>Full document</h2>
              <p className="page-subtitle" style={{ marginBottom: "1.75rem" }}>{sections.length} sections</p>
              {sections.map((s, idx) => (
                <div key={s.id} style={{ marginBottom: "2rem" }}>
                  <div className="doc-heading">
                    <span>{s.subtitle}</span>
                    <span className={`badge ${tagClass(s.tag)}`}>{s.tag}</span>
                  </div>
                  <SectionContent content={s.content} />
                  {idx < sections.length - 1 && <hr className="divider" />}
                </div>
              ))}
            </div>
          ) : !activeSection ? (
            <div className="empty-state" style={{ border: "none", background: "transparent" }}>
              <div className="empty-icon">👈</div>
              <p className="empty-title">Nothing selected</p>
              <p className="empty-text">Pick a section from the list to read its content.</p>
            </div>
          ) : (
            <div className="anim-fade-up" key={activeSection.id}>
              <div className="page-head" style={{ marginBottom: "1.25rem" }}>
                <div>
                  <h2 className="page-title" style={{ fontSize: "1.35rem" }}>{activeSection.subtitle}</h2>
                  <div className="row" style={{ gap: "0.6rem", marginTop: "0.45rem" }}>
                    <span className={`badge ${tagClass(activeTag)}`}>{activeTag}</span>
                    {activeSection.page_number && (
                      <span className="subtle text-xs">Page {activeSection.page_number}</span>
                    )}
                  </div>
                </div>

                <div className="row-wrap" style={{ gap: "0.5rem" }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => { setShowRevForm((v) => !v); setRevMsg(""); }}
                  >
                    {showRevForm ? "✕ Cancel" : "📤 Submit revision"}
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setIsEditing((v) => !v);
                      if (!isEditing) setEditedContent(formatOCRContent(activeSection.content));
                      setRevMsg("");
                    }}
                  >
                    {isEditing ? "✕ Cancel edit" : "✏️ Edit text"}
                  </button>
                </div>
              </div>

              {/* Merge workflow grouped as one tool rather than scattered buttons */}
              <div className="merge-bar">
                <span className="merge-bar-label">🔀 Merge sections</span>
                <div className="row-wrap" style={{ gap: "0.4rem" }}>
                  <button
                    className={`btn btn-sm ${mergeSource ? "btn-subtle" : "btn-ghost"}`}
                    onClick={() => {
                      setMergeSource(activeSection);
                      setMergeTarget(null);
                      setMergeMsg("Now open another section and set it as the merge target.");
                      setMergeMsgType("success");
                    }}
                  >
                    Set source{mergeSource ? " ✓" : ""}
                  </button>
                  <button
                    className={`btn btn-sm ${mergeTarget ? "btn-subtle" : "btn-ghost"}`}
                    onClick={() => {
                      if (mergeSource && activeSection && activeSection.id !== mergeSource.id) {
                        setMergeTarget(activeSection);
                        setMergeMsg(`Target set to "${activeSection.subtitle}". Ready to propose.`);
                        setMergeMsgType("success");
                      } else {
                        setMergeMsg("Choose a target section different from the source.");
                        setMergeMsgType("error");
                      }
                    }}
                  >
                    Set target{mergeTarget ? " ✓" : ""}
                  </button>
                  <button
                    className="btn btn-success btn-sm"
                    onClick={handleProposeMerge}
                    disabled={!mergeSource || !mergeTarget || mergeSource.id === mergeTarget?.id}
                  >
                    Propose merge
                  </button>
                </div>
              </div>

              {revMsg && (
                <div className={`toast ${revMsgType === "success" ? "toast-success" : "toast-danger"}`}>
                  {revMsg}
                </div>
              )}

              {mergeMsg && (
                <div className={`toast ${mergeMsgType === "success" ? "toast-success" : "toast-danger"}`}>
                  {mergeMsg}
                </div>
              )}

              {showRevForm && (
                <div
                  className="card card-pad anim-scale-in"
                  style={{ marginBottom: "1.25rem", background: "var(--brand-50)", borderColor: "var(--brand-200)" }}
                >
                  <h4 className="section-title">Submit a revision for {activeSection.subtitle}</h4>
                  <p className="muted text-sm" style={{ margin: "0.35rem 0 1rem" }}>
                    Upload a PDF or DOCX with your proposed changes. An admin will review and approve it.
                  </p>
                  <form onSubmit={handleSubmitRevision} className="col">
                    <div className="field">
                      <label className="label">Revised file (PDF or DOCX)</label>
                      <input
                        ref={fileInputRef}
                        className="input-file"
                        type="file"
                        accept=".pdf,.docx,.doc,.txt"
                        onChange={(e) => setRevFile(e.target.files[0])}
                        required
                      />
                    </div>
                    <div className="field">
                      <label className="label">Reason for change <span style={{ color: "var(--danger)" }}>*</span></label>
                      <textarea
                        className="textarea"
                        style={{ minHeight: "70px" }}
                        placeholder="Why is this change needed? e.g. the approving role changed in August 2026."
                        value={changeReason}
                        onChange={(e) => setChangeReason(e.target.value)}
                        required
                      />
                      <span className="subtle text-xs">
                        Required. A sentence or more: what changed and why. At least 15 characters and 3 words. Recorded against the revision for document control.
                      </span>
                    </div>
                    <button type="submit" className="btn btn-success" disabled={revLoading}>
                      {revLoading ? <><span className="spinner spinner-light" /> Submitting…</> : "Submit revision"}
                    </button>
                  </form>
                </div>
              )}

              <div className="tabs">
                <button
                  className={`tab${revTab === "content" ? " is-active" : ""}`}
                  onClick={() => setRevTab("content")}
                >
                  Content
                </button>
                <button
                  className={`tab${revTab === "revisions" ? " is-active" : ""}`}
                  onClick={() => setRevTab("revisions")}
                >
                  My revisions
                  {pendingCount > 0 && <span className="tab-count">{pendingCount}</span>}
                </button>
              </div>

              {revTab === "content" ? (
                isEditing ? (
                  <div className="col anim-fade-up">
                    <textarea
                      className="textarea textarea-doc mono"
                      value={editedContent}
                      onChange={(e) => setEditedContent(e.target.value)}
                      placeholder="Enter the revised content…"
                    />
                    <div className="field">
                      <label className="label">Reason for change <span style={{ color: "var(--danger)" }}>*</span></label>
                      <textarea
                        className="textarea"
                        style={{ minHeight: "70px" }}
                        placeholder="Why is this change needed? e.g. the approving role changed in August 2026."
                        value={changeReason}
                        onChange={(e) => setChangeReason(e.target.value)}
                        required
                      />
                      <span className="subtle text-xs">
                        Required. A sentence or more: what changed and why. At least 15 characters and 3 words. Recorded against the revision for document control.
                      </span>
                    </div>
                    <div className="row-wrap" style={{ gap: "0.5rem" }}>
                      <button className="btn btn-success" onClick={handleSubmitTextRevision} disabled={revLoading}>
                        {revLoading ? <><span className="spinner spinner-light" /> Submitting…</> : "Propose changes"}
                      </button>
                      <button className="btn btn-ghost" onClick={() => { setIsEditing(false); setEditedContent(""); setChangeReason(""); }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <SectionContent content={formatOCRContent(activeSection.content)} />
                )
              ) : sectionRevisions.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon">📝</div>
                  <p className="empty-title">No revisions yet</p>
                  <p className="empty-text">You haven&apos;t submitted any revisions for this section.</p>
                  <button
                    className="btn btn-primary btn-sm"
                    style={{ marginTop: "0.5rem" }}
                    onClick={() => { setShowRevForm(true); setRevTab("content"); }}
                  >
                    Submit your first revision
                  </button>
                </div>
              ) : (
                <div className="col stagger" style={{ gap: "0.75rem" }}>
                  {sectionRevisions.map((r) => {
                    const st = STATUS_CLASS[r.status] || STATUS_CLASS.pending;
                    return (
                      <div key={r.id} className={`card card-pad accordion ${st.tone}`}>
                        <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.6rem" }}>
                          <span className={`badge ${st.badge}`}>{r.status.toUpperCase()}</span>
                          <span className="subtle text-xs">{new Date(r.submitted_at).toLocaleString()}</span>
                        </div>
                        {r.reviewer_notes && (
                          <div className="alert" style={{ marginBottom: "0.6rem" }}>
                            <strong>Admin notes:</strong> {r.reviewer_notes}
                          </div>
                        )}
                        {r.diff_preview && (
                          <div className="diff-wrap">
                            <div className="diff-wrap-head">Your proposed changes</div>
                            <div className="diff-scroll">
                              <DiffView diffText={r.diff_preview} />
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

