import { useState, useEffect } from "react";
import axios from "axios";
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

export default function StaffSections({
  // A change is proposed for the whole document, so this screen hands off
  // to Proposals rather than carrying a submission form of its own.
  manualId, onBack, focusSectionId, onPropose,
  // Reading only: QMS staff read every document but do not propose, so
  // the control that would is not shown.
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
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading sections…</div>;
  }

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
                onClick={() => { setIsFullDoc(true); setActive(null); }}
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
                  /* Secondary, not the centre of the screen: reading a
                     document is the common case and proposing a change to
                     it is the rare one. */
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => onPropose?.(manualId)}
                    title="Changes are proposed for the whole document"
                  >
                    Propose changes
                  </button>
                )}
              </div>

              <div className="doc-body">
                <SectionContent content={formatOCRContent(activeSection.content)} />
              </div>
              <SectionChanges changes={activeSection.changes} />
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
