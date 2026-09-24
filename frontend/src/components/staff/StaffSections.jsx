import { useState, useEffect, useRef } from "react";
import axios from "axios";
import DiffView from "../DiffView";
import DocTable from "../DocTable";
import { parseTableRow, isTableSeparator } from "../../docTable";
import BaselineForm from "../qms/BaselineForm";
import { formatDate, formatRevision, revisionLine } from "../documentStatus";

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

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const TAG_CLASS = {
  POLICY:                "badge-info",
  PROCEDURE:             "badge-success",
  RESPONSIBILITY:        "badge-danger",
  "WORKING INSTRUCTION": "badge-warning",
  UNTAGGED:              "badge-neutral",
};

const tagClass = (tag) => TAG_CLASS[tag] || "badge-neutral";

const STATUS_CLASS = {
  pending:  { mark: "is-pending",  tone: "is-warning" },
  approved: { mark: "is-approved", tone: "is-success" },
  rejected: { mark: "is-rejected", tone: "is-danger" },
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

const VERDICT_TONE = {
  approve: { badge: "badge-success", label: "Looks fine" },
  needs_revision: { badge: "badge-warning", label: "Would likely need changes" },
  reject: { badge: "badge-danger", label: "Would likely be rejected" },
};

const SEVERITY_TONE = {
  high: "badge-danger",
  medium: "badge-warning",
  low: "badge-neutral",
};

/**
 * What the submitter sees before deciding whether to submit.
 *
 * Deliberately not a gate. The verdict is advice and the submit button stays
 * live whatever it says - the only thing that is required is having read it.
 * The reviewer will see this same assessment, so it is also a preview of what
 * they will be looking at.
 */
function AiCheckPanel({ result, loading }) {
  if (loading) {
    return (
      <div className="card card-pad" style={{ margin: "0.9rem 0" }}>
        <div className="row" style={{ gap: "0.6rem", alignItems: "center" }}>
          <span className="spinner" />
          <span className="text-sm">
            Checking this change… the first check after the server starts takes
            a few seconds longer.
          </span>
        </div>
      </div>
    );
  }
  if (!result) return null;

  const tone = VERDICT_TONE[result.verdict] || VERDICT_TONE.needs_revision;
  const issues = result.issues || [];
  const hardFails = result.hard_fails || [];
  const advisories = result.advisories || [];

  return (
    <div className="card card-pad" style={{ margin: "0.9rem 0" }}>
      <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center", marginBottom: "0.6rem" }}>
        <span className="subtle text-xs strong">AI CHECK</span>
        <span className={`badge ${tone.badge}`}>{tone.label}</span>
        {typeof result.confidence === "number" && (
          <span className="badge badge-neutral">
            confidence {Math.round(result.confidence * 100)}%
          </span>
        )}
        <span className="badge badge-info">advisory only</span>
      </div>

      {hardFails.length > 0 && (
        <div style={{ marginBottom: "0.7rem" }}>
          <div className="label" style={{ marginBottom: "0.35rem" }}>
            A document-control rule was not met
          </div>
          <div className="col" style={{ gap: "0.35rem" }}>
            {hardFails.map((fail) => (
              <div key={fail.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
                <span className="badge badge-danger">{(fail.label || "").replaceAll("_", " ")}</span>
                {fail.clause && <span className="badge badge-info">clause {fail.clause}</span>}
                {fail.evidence && <span className="text-xs" style={{ color: "var(--n-700)" }}>{fail.evidence}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {result.explanation && (
        <p className="text-sm" style={{ color: "var(--n-700)", marginBottom: "0.7rem" }}>
          {result.explanation}
        </p>
      )}

      {issues.length > 0 && (
        <div className="col" style={{ gap: "0.45rem", marginBottom: "0.6rem" }}>
          {issues.map((issue) => (
            <div key={issue.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
              <span className={`badge ${SEVERITY_TONE[issue.severity] || "badge-neutral"}`}>
                {(issue.label || "").replaceAll("_", " ")}
              </span>
              {issue.clause && <span className="badge badge-info">clause {issue.clause}</span>}
              {issue.evidence && (
                <span className="text-xs" style={{ color: "var(--n-700)" }}>{issue.evidence}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {advisories.length > 0 && (
        <div className="col" style={{ gap: "0.35rem", marginBottom: "0.6rem" }}>
          {advisories.map((note) => (
            <div key={note.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
              <span className="badge badge-warning">{(note.label || "").replaceAll("_", " ")}</span>
              {note.evidence && (
                <span className="text-xs" style={{ color: "var(--n-700)" }}>{note.evidence}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="subtle text-xs" style={{ margin: 0 }}>
        The reviewer will see this same assessment. You can submit whatever it
        says - the decision is theirs, not this check's.
      </p>
    </div>
  );
}


export default function StaffSections({
  manualId, onBack, focusSectionId, onOpenRevision,
  // Set once access is scoped by position. A change is then proposed for
  // the whole document rather than one section at a time, so this screen
  // hands off instead of carrying its own submission form.
  byPosition = false, onPropose,
  // Reading only: QMS staff read every document but neither edit nor
  // propose, so none of the controls that would are shown.
  readOnly = false,
}) {
  const [manual, setManual]           = useState(null);
  const [reloadKey, setReloadKey]     = useState(0);
  const [recordingBaseline, setRecordingBaseline] = useState(false);
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
  // The AI check is required before submitting, and its result belongs to
  // exactly the text that was checked - editing anything clears it, because
  // the reviewer is going to read the assessment of what was submitted.
  const [aiCheck, setAiCheck]         = useState(null);
  const [aiChecking, setAiChecking]   = useState(false);
  // Upload and merge get their own check state: they are separate forms, and
  // the content each is agreeing to is produced by the server rather than
  // typed, so each shows what was actually read before it is submitted.
  const [uploadCheck, setUploadCheck] = useState(null);
  const [mergeCheck, setMergeCheck]   = useState(null);

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
        // The document's official status, as the custodian recorded it.
        // v3's version counters are not shown to readers.
        setManual({
          status: res.data.status,
          canRecordBaseline: res.data.can_record_baseline,
          canCorrectBaseline: res.data.can_correct_baseline,
        });
        if (res.data.sections?.length > 0) {
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
  }, [manualId, tagFilter, searchQuery, reloadKey]);

  // Arriving from the Sections tab: open the section that was clicked, once
  // the list has loaded. Both routes land on this same view - that is what
  // keeps the two tabs from being two different section screens.
  useEffect(() => {
    if (!focusSectionId || !sections.length) return;
    const wanted = sections.find((s) => s.id === focusSectionId);
    if (wanted) handleSelectSection(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSectionId, sections]);

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

  const runUploadCheck = async () => {
    if (!revFile) { setRevMsg("Select a file first."); setRevMsgType("error"); return; }
    if (!changeReason.trim()) {
      setRevMsg("Please give a reason for this change - a short sentence saying what changed and why.");
      setRevMsgType("error"); return;
    }
    setAiChecking(true);
    setRevMsg("");
    const formData = new FormData();
    formData.append("file", revFile);
    formData.append("change_reason", changeReason.trim());
    try {
      const res = await axios.post(
        `${BASE_URL}/api/revisions/pre-assess/${activeSection.id}/`,
        formData,
        { headers: { ...getAuth().headers, "Content-Type": "multipart/form-data" } }
      );
      setUploadCheck(res.data);
    } catch (err) {
      setUploadCheck(null);
      setRevMsg(err.response?.data?.error || "The AI check could not be completed.");
      setRevMsgType("error");
    } finally {
      setAiChecking(false);
    }
  };

  const runMergeCheck = async () => {
    if (!mergeSource || !mergeTarget) {
      setMergeMsg("Select both source and target sections first."); setMergeMsgType("error"); return;
    }
    if (!changeReason.trim()) {
      setMergeMsg("Please give a reason for this change - a short sentence saying what changed and why.");
      setMergeMsgType("error"); return;
    }
    setAiChecking(true);
    setMergeMsg("");
    try {
      const res = await axios.post(
        `${BASE_URL}/api/revisions/pre-assess-merge/`,
        {
          source_section_id: mergeSource.id,
          target_section_id: mergeTarget.id,
          change_reason: changeReason.trim(),
        },
        getAuth()
      );
      setMergeCheck(res.data);
    } catch (err) {
      setMergeCheck(null);
      setMergeMsg(err.response?.data?.error || "The AI check could not be completed.");
      setMergeMsgType("error");
    } finally {
      setAiChecking(false);
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
    if (uploadCheck?.assessment_id) {
      formData.append("assessment_id", uploadCheck.assessment_id);
    }
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
      if (err.response?.data?.field === "assessment_id") setUploadCheck(null);
      setRevMsg(msg);
      setRevMsgType("error");
    } finally {
      setRevLoading(false);
    }
  };

  const runAiCheck = async () => {
    if (!editedContent.trim()) {
      setRevMsg("Enter the revised content before checking."); setRevMsgType("error"); return;
    }
    if (!changeReason.trim()) {
      setRevMsg("Please give a reason for this change - a short sentence saying what changed and why.");
      setRevMsgType("error"); return;
    }
    setAiChecking(true);
    setRevMsg("");
    try {
      const res = await axios.post(
        `${BASE_URL}/api/revisions/pre-assess/${activeSection.id}/`,
        { proposed_content: editedContent, change_reason: changeReason.trim() },
        getAuth()
      );
      setAiCheck(res.data);
    } catch (err) {
      setAiCheck(null);
      setRevMsg(err.response?.data?.error || "The AI check could not be completed.");
      setRevMsgType("error");
    } finally {
      setAiChecking(false);
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
        {
          proposed_content: editedContent,
          change_reason: changeReason.trim(),
          // The server re-checks that this assessment was made of exactly
          // what is being submitted, and refuses otherwise.
          assessment_id: aiCheck?.assessment_id,
        },
        getAuth()
      );
      setRevMsg("Text revision proposed successfully. An admin will review it.");
      setRevMsgType("success");
      setIsEditing(false);
      setEditedContent("");
      setChangeReason("");
      setAiCheck(null);
      loadSectionRevisions(activeSection.id);
    } catch (err) {
      const msg = err.response?.data?.error || "Submission failed. Try again.";
      // A stale or missing check is recoverable: clear the result so the
      // button says what to do instead of failing silently.
      if (err.response?.data?.field === "assessment_id") setAiCheck(null);
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
          assessment_id: mergeCheck?.assessment_id,
        },
        getAuth()
      );
      setMergeCheck(null);
      setMergeMsg("✅ Merge proposal submitted successfully.");
      setMergeSource(null);
      setMergeTarget(null);
      setMergeMsgType("success");
      loadSectionRevisions(activeSection.id);
    } catch (err) {
      const msg = err.response?.data?.error || "Merge proposal failed.";
      if (err.response?.data?.field === "assessment_id") setMergeCheck(null);
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
            {manual?.status && (
              <div className="toc-head-meta">
                {manual.status.document_number} · {revisionLine(manual.status)}
              </div>
            )}
            {manual?.canRecordBaseline && !recordingBaseline && (
              <button className="link-btn text-xs" onClick={() => setRecordingBaseline(true)}>
                Record starting status
              </button>
            )}
            {manual?.canCorrectBaseline && !recordingBaseline && (
              <button className="link-btn text-xs" onClick={() => setRecordingBaseline(true)}>
                Correct starting status
              </button>
            )}
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
          {recordingBaseline && (
            <BaselineForm
              manualId={manualId}
              current={manual?.canCorrectBaseline ? manual.status : null}
              onCancel={() => setRecordingBaseline(false)}
              onDone={() => { setRecordingBaseline(false); setReloadKey((k) => k + 1); }}
            />
          )}
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
                  {s.revision && <p className="subtle text-xs" style={{ margin: "-0.35rem 0 0.6rem" }}>{revisionLine(s.revision)}</p>}
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
              {/* The bordered block every page of the printed manual carries.
                  Reproducing a simplified version here is what makes a
                  section on screen read as part of a controlled document
                  rather than a record in an application. */}
              <div className="doc-header">
                <div className="doc-header-field">
                  <span className="doc-header-label">Section</span>
                  <span className="doc-header-value">{activeSection.subtitle}</span>
                </div>
                {manual?.status && (
                  <>
                    <div className="doc-header-field">
                      <span className="doc-header-label">Document no.</span>
                      <span className="doc-header-value">{manual.status.document_number}</span>
                    </div>
                    <div className="doc-header-field">
                      <span className="doc-header-label">Revision</span>
                      <span className="doc-header-value">{formatRevision(manual.status.revision)}</span>
                    </div>
                    <div className="doc-header-field">
                      <span className="doc-header-label">Effective</span>
                      <span className="doc-header-value">{formatDate(manual.status.effective_on)}</span>
                    </div>
                  </>
                )}
                {activeSection.page_number && (
                  <div className="doc-header-field">
                    <span className="doc-header-label">Page</span>
                    <span className="doc-header-value">{activeSection.page_number}</span>
                  </div>
                )}
                <div className="doc-header-field">
                  <span className="doc-header-label">Type</span>
                  <span className="doc-header-value">{(activeTag || "").toLowerCase()}</span>
                </div>
              </div>

              <div className="page-head" style={{ marginBottom: "1.25rem" }}>
                <div>
                  <h2 className="doc-title">{activeSection.subtitle}</h2>
                  {activeSection.revision && (
                    <p className="subtle text-xs" style={{ margin: "0.2rem 0 0" }}>
                      {revisionLine(activeSection.revision)}
                    </p>
                  )}
                </div>

                {!readOnly && (
                <div className="row-wrap" style={{ gap: "0.5rem" }}>
                  {byPosition ? (
                    /* Secondary, not the centre of the screen: reading a
                       document is the common case and proposing a change
                       to it is the rare one. */
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => onPropose?.(manualId)}
                      title="Changes are proposed for the whole document"
                    >
                      Propose changes
                    </button>
                  ) : (
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => { setShowRevForm((v) => !v); setRevMsg(""); }}
                    >
                      {showRevForm ? "✕ Cancel" : "📤 Submit revision"}
                    </button>
                  )}
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
                )}
              </div>

              {/* Merge workflow grouped as one tool rather than scattered buttons */}
              {!readOnly && (
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
                    className="btn btn-subtle btn-sm"
                    onClick={runMergeCheck}
                    disabled={aiChecking || !mergeSource || !mergeTarget || mergeSource.id === mergeTarget?.id}
                  >
                    {aiChecking
                      ? <><span className="spinner" /> Checking…</>
                      : mergeCheck ? "✨ Check again" : "✨ Check with AI"}
                  </button>
                  <button
                    className="btn btn-success btn-sm"
                    onClick={handleProposeMerge}
                    disabled={!mergeCheck || aiChecking || !mergeSource || !mergeTarget || mergeSource.id === mergeTarget?.id}
                    title={mergeCheck ? "" : "Run the AI check first"}
                  >
                    Confirm merge
                  </button>
                </div>

                {mergeCheck?.merged_content && (
                  <div className="field" style={{ marginTop: "0.6rem" }}>
                    <p className="label" style={{ marginBottom: "0.35rem" }}>
                      The merged section this would create
                    </p>
                    <div className="content-box content-box-scroll mono text-xs">
                      {mergeCheck.merged_content}
                    </div>
                  </div>
                )}
                <AiCheckPanel result={mergeCheck} loading={aiChecking} />
              </div>
              )}

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
                        onChange={(e) => { setRevFile(e.target.files[0]); setUploadCheck(null); }}
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
                        onChange={(e) => { setChangeReason(e.target.value); setUploadCheck(null); }}
                        required
                      />
                      <span className="subtle text-xs">
                        Required. A sentence or more: what changed and why. At least 15 characters and 3 words. Recorded against the revision for document control.
                      </span>
                    </div>

                    {uploadCheck?.extracted_text && (
                      <div className="field">
                        <p className="label" style={{ marginBottom: "0.35rem" }}>
                          What the system read from your file
                        </p>
                        <div className="content-box content-box-scroll mono text-xs">
                          {uploadCheck.extracted_text}
                        </div>
                        <span className="subtle text-xs">
                          The assessment below is of this text. If it does not match your
                          document, the file did not extract cleanly.
                        </span>
                      </div>
                    )}

                    <AiCheckPanel result={uploadCheck} loading={aiChecking} />

                    <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
                      <button
                        type="button"
                        className="btn btn-subtle"
                        onClick={runUploadCheck}
                        disabled={aiChecking || revLoading}
                      >
                        {aiChecking
                          ? <><span className="spinner" /> Checking…</>
                          : uploadCheck ? "✨ Check again" : "✨ Check with AI"}
                      </button>
                      <button
                        type="submit"
                        className="btn btn-success"
                        disabled={revLoading || aiChecking || !uploadCheck}
                        title={uploadCheck ? "" : "Run the AI check first"}
                      >
                        {revLoading ? <><span className="spinner spinner-light" /> Submitting…</> : "Confirm and submit"}
                      </button>
                      {!uploadCheck && !aiChecking && (
                        <span className="subtle text-xs">
                          Run the check before submitting. Whatever it says, you can still submit.
                        </span>
                      )}
                    </div>
                  </form>
                </div>
              )}

              {/* A reader who submits nothing has no revisions of their own,
                  and a single "Content" tab would be noise. */}
              {!readOnly && (
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
              )}

              {revTab === "content" ? (
                isEditing ? (
                  <div className="col anim-fade-up">
                    <textarea
                      className="textarea textarea-doc mono"
                      value={editedContent}
                      onChange={(e) => { setEditedContent(e.target.value); setAiCheck(null); }}
                      placeholder="Enter the revised content…"
                    />
                    <div className="field">
                      <label className="label">Reason for change <span style={{ color: "var(--danger)" }}>*</span></label>
                      <textarea
                        className="textarea"
                        style={{ minHeight: "70px" }}
                        placeholder="Why is this change needed? e.g. the approving role changed in August 2026."
                        value={changeReason}
                        onChange={(e) => { setChangeReason(e.target.value); setAiCheck(null); }}
                        required
                      />
                      <span className="subtle text-xs">
                        Required. A sentence or more: what changed and why. At least 15 characters and 3 words. Recorded against the revision for document control.
                      </span>
                    </div>

                    <AiCheckPanel result={aiCheck} loading={aiChecking} />

                    <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
                      <button
                        type="button"
                        className="btn btn-subtle"
                        onClick={runAiCheck}
                        disabled={aiChecking || revLoading}
                      >
                        {aiChecking
                          ? <><span className="spinner" /> Checking…</>
                          : aiCheck ? "✨ Check again" : "✨ Check with AI"}
                      </button>
                      <button
                        className="btn btn-success"
                        onClick={handleSubmitTextRevision}
                        disabled={revLoading || aiChecking || !aiCheck}
                        title={aiCheck ? "" : "Run the AI check first"}
                      >
                        {revLoading ? <><span className="spinner spinner-light" /> Submitting…</> : "Confirm and submit"}
                      </button>
                      <button className="btn btn-ghost" onClick={() => { setIsEditing(false); setEditedContent(""); setChangeReason(""); setAiCheck(null); }}>
                        Cancel
                      </button>
                      {!aiCheck && !aiChecking && (
                        <span className="subtle text-xs">
                          Run the check before submitting. Whatever it says, you can still submit.
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="doc-body">
                      <SectionContent content={formatOCRContent(activeSection.content)} />
                    </div>
                    <SectionChanges changes={activeSection.changes} />
                  </>
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
                          <span className={`status-mark ${st.mark || ""}`}>
                            {r.status}
                          </span>
                          <span className="subtle text-xs">{new Date(r.submitted_at).toLocaleString()}</span>
                        </div>
                        {r.diff_preview && (
                          <div className="diff-wrap">
                            <div className="diff-wrap-head">Your proposed changes</div>
                            <div className="diff-scroll">
                              <DiffView diffText={r.diff_preview} />
                            </div>
                          </div>
                        )}
                        {/* Feedback lives in one place. Showing the notes here
                            too meant two copies drifting apart, and no single
                            screen that could be called the record. */}
                        {onOpenRevision && (
                          <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center", marginTop: "0.6rem" }}>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => onOpenRevision(r.id)}
                            >
                              {r.reviewer_notes ? "Read the reviewer's feedback" : "Open in My Revisions"}
                            </button>
                            {r.reviewer_notes && (
                              <span className="badge badge-info">feedback</span>
                            )}
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


/**
 * The requests that changed this section, newest first. Collapsed: reading
 * comes first, and most readers never need to open it.
 */
function SectionChanges({ changes }) {
  if (!changes || changes.length === 0) return null;
  return (
    <details style={{ marginTop: "1.5rem" }}>
      <summary className="subtle text-sm" style={{ cursor: "pointer" }}>
        History
      </summary>
      <div className="col" style={{ gap: "0.9rem", marginTop: "0.75rem" }}>
        {changes.map((c, i) => (
          <div key={i} className="text-sm">
            <div>
              <span className="strong">{c.dcr_number}</span>
              {c.revision && <span className="subtle">{` · ${revisionLine(c)}`}</span>}
            </div>
            {c.reason && <p style={{ margin: "0.25rem 0 0", whiteSpace: "pre-wrap" }}>{c.reason}</p>}
            <details style={{ marginTop: "0.35rem" }}>
              <summary className="subtle text-xs" style={{ cursor: "pointer" }}>Text before</summary>
              <div className="doc-body" style={{ marginTop: "0.5rem" }}>
                <SectionContent content={formatOCRContent(c.text_before)} />
              </div>
            </details>
          </div>
        ))}
      </div>
    </details>
  );
}
