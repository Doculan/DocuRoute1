import { Fragment, useState, useEffect, useCallback } from "react";
import axios from "axios";
import DiffView from "../DiffView";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const STATUS_BADGE = {
  pending:  "badge-warning",
  approved: "badge-success",
  rejected: "badge-danger",
};

const STATUS_TONE = {
  pending:  "is-warning",
  approved: "is-success",
  rejected: "is-danger",
};

function parseUnifiedDiff(text) {
  const items = [];
  let inHunk = false;

  for (const line of text.split("\n")) {
    // The --- / +++ banner only appears before the first hunk. Checking that
    // keeps a removed line whose own text starts with "--" from being eaten.
    if (!inHunk && (line.startsWith("---") || line.startsWith("+++"))) continue;

    if (line.startsWith("@@")) {
      inHunk = true;
      const m = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) items.push({ type: "hunk", oldStart: Number(m[1]), newStart: Number(m[2]) });
      continue;
    }

    if (line.startsWith("-")) items.push({ type: "removed", text: line.slice(1) });
    else if (line.startsWith("+")) items.push({ type: "added", text: line.slice(1) });
    else items.push({ type: "context", text: line.startsWith(" ") ? line.slice(1) : line });
  }

  return items;
}

// Turn a flat diff into aligned row pairs. Each side only ever carries its own
// lines: the original never shows an insertion, the proposal never shows a
// deletion, and the shorter side of an edit gets a blank filler cell.
function buildSideBySideRows(items) {
  const rows = [];
  let oldNo = 0;
  let newNo = 0;
  let i = 0;

  while (i < items.length) {
    const item = items[i];

    if (item.type === "hunk") {
      oldNo = item.oldStart - 1;
      newNo = item.newStart - 1;
      i++;
      continue;
    }

    if (item.type === "context") {
      rows.push({
        left: { no: ++oldNo, text: item.text },
        right: { no: ++newNo, text: item.text },
      });
      i++;
      continue;
    }

    const removed = [];
    const added = [];
    while (i < items.length && (items[i].type === "removed" || items[i].type === "added")) {
      if (items[i].type === "removed") removed.push(items[i].text);
      else added.push(items[i].text);
      i++;
    }

    for (let p = 0; p < Math.max(removed.length, added.length); p++) {
      rows.push({
        left: p < removed.length ? { no: ++oldNo, text: removed[p], changed: true } : null,
        right: p < added.length ? { no: ++newNo, text: added[p], changed: true } : null,
      });
    }
  }

  return rows;
}

function SideBySideDiff({ rev }) {
  const rows = buildSideBySideRows(parseUnifiedDiff(rev.diff_text || rev.diff_preview || ""));

  if (rows.length === 0) {
    return <p className="muted text-sm">No changes to compare.</p>;
  }

  const cell = (entry, tone) => (
    <div className={`diff-cell has-gutter${entry ? (entry.changed ? ` is-${tone}` : "") : " is-blank"}`}>
      {entry && (
        <>
          <span className="diff-gutter">{entry.no}</span>
          <span>{entry.text}</span>
        </>
      )}
    </div>
  );

  return (
    <div className="diff-grid">
      <div className="diff-grid-head">Original</div>
      <div className="diff-grid-head">Proposed</div>
      {rows.map((row, idx) => (
        <Fragment key={idx}>
          {cell(row.left, "removed")}
          {cell(row.right, "added")}
        </Fragment>
      ))}
    </div>
  );
}

const VERDICT_BADGE = {
  approve: "badge-success",
  needs_revision: "badge-warning",
  reject: "badge-danger",
};

const VERDICT_LABEL = {
  approve: "Approve",
  needs_revision: "Needs revision",
  reject: "Reject",
};

// The four-layer pipeline. `result` is the whole response, not just a verdict:
// the issue list carries the clause it comes from and the evidence it was
// raised on, because a reviewer who cannot see why will either trust it
// blindly or ignore it.
/** How long the submitter sat between reading the check and submitting. */
function checkGap(assessedAt, submittedAt) {
  if (!assessedAt || !submittedAt) return null;
  const seconds = Math.round(
    (new Date(submittedAt).getTime() - new Date(assessedAt).getTime()) / 1000
  );
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 90) return `${seconds} second${seconds === 1 ? "" : "s"}`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

/**
 * Where this assessment came from.
 *
 * Worth its own block: an assessment the submitter read before choosing to
 * submit means something different from one a reviewer generated afterwards,
 * and a reject the submitter saw and submitted anyway is a deliberate act
 * rather than a system error.
 */
function AssessmentProvenance({ rev }) {
  const gap = checkGap(rev.ai_assessed_at, rev.submitted_at);

  if (rev.ai_source === "staff_precheck") {
    return (
      <div className="col" style={{ gap: "0.3rem", marginBottom: "0.7rem" }}>
        <div className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
          <span className="badge badge-info">checked by the submitter before submitting</span>
          {gap && <span className="badge badge-neutral">submitted {gap} later</span>}
          {rev.ai_section_changed && (
            <span className="badge badge-warning">section changed since this check</span>
          )}
        </div>
        {rev.ai_section_changed && (
          <span className="text-xs" style={{ color: "var(--n-700)" }}>
            This section has been edited since the check ran, so the assessment
            compares against an older version of it.
          </span>
        )}
      </div>
    );
  }

  if (rev.ai_source === "admin_legacy") {
    return (
      <div className="row-wrap" style={{ gap: "0.4rem", marginBottom: "0.7rem", alignItems: "center" }}>
        <span className="badge badge-neutral">
          assessed by a reviewer under the previous workflow
        </span>
        <span className="text-xs" style={{ color: "var(--n-700)" }}>
          The submitter did not see this before submitting.
        </span>
      </div>
    );
  }

  return null;
}

function AiPanelV2({ result }) {
  const [showTrace, setShowTrace] = useState(false);
  const issues = result.issues || [];
  const confidence = Math.round((result.confidence || 0) * 100);

  return (
    <div className="ai-panel anim-fade-up">
      <div className="ai-panel-head">
        <span className="ai-chip">AI</span>
        <h4 className="section-title">Preliminary assessment</h4>
        <span className="badge badge-neutral" style={{ marginLeft: "auto" }}>
          advisory only
        </span>
      </div>

      <div className="row-wrap" style={{ gap: "1.5rem", marginBottom: "0.9rem" }}>
        <div>
          <div className="label">Suggested verdict</div>
          <span className={`badge ${VERDICT_BADGE[result.verdict] || "badge-neutral"}`}>
            {VERDICT_LABEL[result.verdict] || result.verdict}
          </span>
        </div>
        <div style={{ minWidth: "160px", flex: 1 }}>
          <div className="metric-head">
            <span className="label">Confidence</span>
            <span className="metric-value">{confidence}%</span>
          </div>
          <div className="meter"><span className="meter-fill" style={{ width: `${confidence}%` }} /></div>
        </div>
        {result.change_type && (
          <div>
            <div className="label">Change type</div>
            <div className="strong">{result.change_type.replaceAll("_", " ")}</div>
          </div>
        )}
      </div>

      {(result.hard_fails || []).length > 0 && (
        <div style={{ marginBottom: "0.9rem" }}>
          <div className="label" style={{ marginBottom: "0.4rem" }}>
            Blocking — a document-control rule was not met
          </div>
          <div className="col" style={{ gap: "0.4rem" }}>
            {result.hard_fails.map((fail) => (
              <div key={fail.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
                <span className="badge badge-danger">
                  {(fail.label || "").replaceAll("_", " ")}
                </span>
                {fail.clause && (
                  <span className="badge badge-info">clause {fail.clause}</span>
                )}
                {fail.evidence && (
                  <span className="text-xs" style={{ color: "var(--n-700)" }}>
                    {fail.evidence}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Soft findings: real enough to mention, never enough to block. */}
      {(result.advisories || []).length > 0 && (
        <div style={{ marginBottom: "0.9rem" }}>
          <div className="label" style={{ marginBottom: "0.4rem" }}>
            Worth checking — not blocking
          </div>
          <div className="col" style={{ gap: "0.4rem" }}>
            {result.advisories.map((note) => (
              <div key={note.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
                <span className="badge badge-warning">
                  {(note.label || "").replaceAll("_", " ")}
                </span>
                {note.clause && (
                  <span className="badge badge-info">clause {note.clause}</span>
                )}
                {note.evidence && (
                  <span className="text-xs" style={{ color: "var(--n-700)" }}>
                    {note.evidence}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {result.explanation && (
        <p className="text-sm" style={{ color: "var(--n-700)", marginBottom: "0.9rem" }}>
          {result.explanation}
        </p>
      )}

      {issues.length > 0 && (
        <div style={{ marginBottom: "0.9rem" }}>
          <div className="label" style={{ marginBottom: "0.4rem" }}>
            {issues.length === 1 ? "1 concern" : `${issues.length} concerns`}
          </div>
          <div className="col" style={{ gap: "0.5rem" }}>
            {issues.map((issue) => (
              <div key={issue.label} className="card card-pad" style={{ padding: "0.6rem 0.75rem" }}>
                <div className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
                  <span className="badge badge-warning">
                    {issue.label.replaceAll("_", " ")}
                  </span>
                  {issue.clause && (
                    <span className="badge badge-info">clause {issue.clause}</span>
                  )}
                  {issue.severity && (
                    <span className="subtle text-xs">{issue.severity} severity</span>
                  )}
                  <span className="subtle text-xs" style={{ marginLeft: "auto" }}>
                    {issue.source === "rule"
                      ? "rule"
                      : `model ${Math.round((issue.confidence || 0) * 100)}%`}
                  </span>
                </div>
                {issue.evidence && (
                  <div className="text-xs" style={{ marginTop: "0.35rem", color: "var(--n-700)" }}>
                    {issue.evidence}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {result.trace && (
        <div>
          <button
            type="button"
            className="pill"
            onClick={() => setShowTrace((open) => !open)}
          >
            {showTrace ? "Hide details" : "Details"}
          </button>
          {showTrace && (
            <pre
              className="text-xs anim-fade-up"
              style={{
                marginTop: "0.6rem",
                maxHeight: "320px",
                overflow: "auto",
                background: "var(--paper-3)",
                borderRadius: "var(--r-md)",
                padding: "0.75rem",
                fontFamily: "var(--font-mono)",
              }}
            >
              {JSON.stringify(result.trace, null, 2)}
            </pre>
          )}
        </div>
      )}

      <p className="subtle text-xs" style={{ marginTop: "0.75rem", fontStyle: "italic" }}>
        This is a suggestion from an automated check. The decision is yours, and
        nothing here changes the revision's status.
      </p>
    </div>
  );
}

function AiPanel({ result }) {
  return (
    <div className="ai-panel anim-fade-up">
      <div className="ai-panel-head">
        <span className="ai-chip">AI</span>
        <h4 className="section-title">Preliminary assessment</h4>
      </div>

      <div className="row-wrap" style={{ gap: "1.5rem", marginBottom: "0.9rem" }}>
        <div>
          <div className="label">Assessment</div>
          <div className="strong">{result.assessment}</div>
        </div>
        <div style={{ minWidth: "160px", flex: 1 }}>
          <div className="metric-head">
            <span className="label">Confidence</span>
            <span className="metric-value">{result.confidence}%</span>
          </div>
          <div className="meter"><span className="meter-fill" style={{ width: `${result.confidence}%` }} /></div>
        </div>
      </div>

      {result.issue_tags?.length > 0 && (
        <div style={{ marginBottom: "0.9rem" }}>
          <div className="label" style={{ marginBottom: "0.4rem" }}>Detected concerns</div>
          <div className="row-wrap" style={{ gap: "0.4rem" }}>
            {result.issue_tags.map((item) => (
              <span key={item.tag} className="badge badge-warning">
                {item.tag.replaceAll("_", " ")} ({item.confidence}%)
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-sm" style={{ color: "var(--n-700)" }}>
        <strong>Explanation:</strong> {result.explanation}
      </p>

      {result.disclaimer && (
        <p className="subtle text-xs" style={{ marginTop: "0.6rem", fontStyle: "italic" }}>
          {result.disclaimer}
        </p>
      )}
    </div>
  );
}

/**
 * @param openRevision  `{ id, status }` when the queue was opened by clicking
 *   a specific revision on the dashboard, otherwise null. The status comes
 *   with it because the queue opens on Pending and a decided revision is by
 *   definition not in that list - an id alone would land on a tab that
 *   cannot show it.
 */
export default function RevisionReview({ openRevision = null }) {
  const [revisions, setRevisions] = useState([]);
  const [statusFilter, setStatusFilter] = useState(
    openRevision?.status || "pending"
  );
  // Cleared once it has been used, so changing tabs afterwards does not drag
  // the highlight around with you.
  const [highlighted, setHighlighted] = useState(openRevision?.id ?? null);
  const [selectedRevision, setSelectedRevision] = useState(null);
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [expandedRevision, setExpandedRevision] = useState(null);
  const [showManualModal, setShowManualModal] = useState(false);
  const [manualSections, setManualSections] = useState([]);
  const [manualLoading, setManualLoading] = useState(false);
  const [aiResults, setAiResults] = useState({});
  const [aiLoading, setAiLoading] = useState({});
  const [aiErrors, setAiErrors] = useState({});

  const token = localStorage.getItem("access_token");
  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchRevisions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(
        `${BASE_URL}/api/admin/revisions/?status=${statusFilter}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setRevisions(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, token]);

  useEffect(() => { fetchRevisions(); }, [fetchRevisions]);

  // Scroll the requested revision into view once its list has arrived.
  // Highlight rather than auto-expand: the reviewer asked to look at this
  // one, not to have a panel opened on their behalf.
  useEffect(() => {
    if (highlighted == null || loading) return;
    const card = document.getElementById(`revision-${highlighted}`);
    if (card) card.scrollIntoView({ block: "center", behavior: "smooth" });
    const timer = setTimeout(() => setHighlighted(null), 2200);
    return () => clearTimeout(timer);
  }, [highlighted, loading, revisions]);

  const showMessage = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const analyzeWithAI = async (revisionId, changeType) => {
    try {
      setAiLoading((prev) => ({ ...prev, [revisionId]: true }));
      setAiErrors((prev) => ({ ...prev, [revisionId]: "" }));

      const accessToken = localStorage.getItem("access_token");
      if (!accessToken) throw new Error("You are not logged in. Please log in again.");

      const response = await fetch(
        `${BASE_URL}/api/revisions/${revisionId}/ai-assessment/?change_type=${changeType}`,
        { method: "GET", headers: { Authorization: `Bearer ${accessToken}` } }
      );

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "AI assessment could not be completed.");

      // v2 returns the assessment at the top level; v1 nests it under
      // ai_assessment. Keep whichever came back, tagged with its pipeline.
      setAiResults((prev) => ({ ...prev, [revisionId]: data }));
    } catch (error) {
      console.error("AI revision assessment failed:", error);
      setAiErrors((prev) => ({ ...prev, [revisionId]: error.message }));
    } finally {
      setAiLoading((prev) => ({ ...prev, [revisionId]: false }));
    }
  };

  const handleViewManual = async (manualId) => {
    if (!manualId) return;
    setManualLoading(true);
    try {
      const res = await axios.get(`${BASE_URL}/api/manuals/${manualId}/sections/`, authHeaders);
      setManualSections(res.data.sections || []);
      setShowManualModal(true);
    } catch (err) {
      console.error(err);
      showMessage("❌ Failed to load manual sections.");
    } finally {
      setManualLoading(false);
    }
  };

  const handleReview = async (revisionId, status) => {
    try {
      await axios.patch(
        `${BASE_URL}/api/admin/revisions/${revisionId}/review/`,
        { status, reviewer_notes: notes },
        authHeaders
      );
      showMessage(`✅ Revision ${status}.`);
      setSelectedRevision(null);
      setNotes("");
      fetchRevisions();
    } catch (error) {
      console.error("Error in handleReview:", error);
      showMessage("❌ Failed to review.");
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Revisions</h1>
          <p className="page-subtitle">Compare proposed changes against the master copy before approving.</p>
        </div>
      </header>

      <div className="tabs">
        {["pending", "approved", "rejected"].map((s) => (
          <button
            key={s}
            className={`tab${statusFilter === s ? " is-active" : ""}`}
            onClick={() => { setHighlighted(null); setStatusFilter(s); }}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {message && <div className="toast">{message}</div>}

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading revisions…</div>
      ) : revisions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">🗂️</div>
          <p className="empty-title">No {statusFilter} revisions</p>
          <p className="empty-text">Revisions with this status will appear here.</p>
        </div>
      ) : (
        <div className="col stagger" style={{ gap: "1.15rem" }}>
          {revisions.map((r) => (
            <article
              key={r.id}
              id={`revision-${r.id}`}
              className={`card card-pad rev-card ${STATUS_TONE[r.status] || ""}`
                + (highlighted === r.id ? " is-highlighted" : "")}
            >
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                <div className="col" style={{ gap: "0.35rem", minWidth: 0 }}>
                  <div className="row-wrap" style={{ gap: "0.5rem" }}>
                    <span className="subtle text-xs strong">MANUAL</span>
                    <span className="strong">{r.manual}</span>
                    <span className="badge badge-neutral">{r.department}</span>
                  </div>
                  <div className="row-wrap" style={{ gap: "0.5rem" }}>
                    <span className="subtle text-xs strong">SECTION</span>
                    <span className="badge badge-warning">{r.section} · ID {r.section_id}</span>
                    <span className="badge badge-info">
                      {r.merge_type === "merge" ? "🔗 Merge" : "✏️ Text edit"}
                    </span>
                  </div>
                </div>
                <span className={`badge ${STATUS_BADGE[r.status] || "badge-neutral"}`}>
                  {r.status.toUpperCase()}
                </span>
              </div>

              <div className="rev-meta">
                <span>👤 {r.submitted_by}</span>
                <span>📅 {new Date(r.submitted_at).toLocaleString()}</span>
                {r.uploaded_file && (
                  <a href={`${BASE_URL}${r.uploaded_file}`} target="_blank" rel="noopener noreferrer">
                    📎 View original file
                  </a>
                )}
              </div>

              {/* Clause 6.3 asks for a reason, the pipeline hard-fails without one,
                  and the admin approving the change is the person who needs to
                  read it. It was in the payload but never on the screen. */}
              <div style={{ marginBottom: "1rem" }}>
                <p className="label" style={{ marginBottom: "0.35rem" }}>
                  Reason for change · clause 6.3
                </p>
                {(r.change_reason || "").trim() ? (
                  <div className="content-box">{r.change_reason}</div>
                ) : (
                  <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
                    <span className="badge badge-danger">not provided</span>
                    <span className="text-sm" style={{ color: "var(--n-700)" }}>
                      No reason was recorded with this submission.
                    </span>
                  </div>
                )}
              </div>

              <div className="row-wrap" style={{ gap: "0.5rem", marginBottom: "1rem" }}>
                <button className="btn btn-ghost btn-sm" onClick={() => handleViewManual(r.manual_id)}>
                  📖 Full manual context
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setExpandedRevision(expandedRevision === r.id ? null : r.id)}
                >
                  {expandedRevision === r.id ? "Hide detailed comparison" : "Show detailed comparison"}
                  <span className={`chevron${expandedRevision === r.id ? " is-open" : ""}`}>▾</span>
                </button>
                {/* The assessment now happens before submission, so there is
                    nothing to press for: the result is already on the
                    revision. The button survives only for revisions that
                    predate the change and carry no assessment at all, so a
                    reviewer is not left with nothing to go on. */}
                {r.ai_source === "none" && (
                  <button
                    type="button"
                    className="btn btn-subtle btn-sm"
                    onClick={() => analyzeWithAI(r.id, "modified")}
                    disabled={Boolean(aiLoading[r.id])}
                    title="This revision predates the pre-submission check"
                  >
                    {aiLoading[r.id]
                      ? <><span className="spinner" /> Analyzing…</>
                      : "✨ Assess (reviewer-side, old workflow)"}
                  </button>
                )}
              </div>

              <div className="diff-wrap">
                <div className="diff-wrap-head">
                  Changes in <strong>{r.section}</strong>
                </div>
                <div className="diff-scroll">
                  {/* diff_text is the full diff; diff_preview is only a trimmed fallback */}
                  <DiffView diffText={r.diff_text || r.diff_preview || ""} />
                </div>
              </div>

              {expandedRevision === r.id && (
                <div className="accordion-body" style={{ padding: 0, border: "none" }}>
                  <p className="label">Section text context · ID {r.section_id}</p>
                  <SideBySideDiff rev={r} />

                  <div className="col" style={{ gap: "0.75rem" }}>
                    <div>
                      <p className="label" style={{ marginBottom: "0.35rem" }}>Current section content</p>
                      <div className="content-box content-box-scroll">{r.section_content || "N/A"}</div>
                    </div>
                    {r.proposed_content && (
                      <div>
                        <p className="label" style={{ marginBottom: "0.35rem" }}>Proposed content</p>
                        <div className="content-box content-box-scroll">{r.proposed_content}</div>
                      </div>
                    )}
                    {r.merge_type && (
                      <p className="muted text-sm">
                        Merge proposed with section IDs: {JSON.stringify(r.merge_section_ids || [])}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {aiErrors[r.id] && (
                <div className="alert alert-danger" style={{ marginTop: "1rem" }}>{aiErrors[r.id]}</div>
              )}

              {/* Stored at submission: what the submitter read, shown without
                  anyone pressing anything. */}
              {!aiResults[r.id] && r.ai_source !== "none" && r.ai_verdict && (
                <div style={{ marginTop: "1rem" }}>
                  <AssessmentProvenance rev={r} />
                  <AiPanelV2
                    result={{
                      verdict: r.ai_verdict,
                      confidence: r.ai_confidence,
                      change_type: r.ai_change_type,
                      issues: r.ai_issues || [],
                      hard_fails: r.ai_hard_fails || [],
                      advisories: r.ai_advisories || [],
                      explanation: r.ai_explanation,
                      trace: r.ai_trace || {},
                    }}
                  />
                  {r.ai_source === "staff_precheck" && r.ai_explanation_staff && (
                    <details style={{ marginTop: "0.5rem" }}>
                      <summary className="text-xs" style={{ cursor: "pointer", color: "var(--n-700)" }}>
                        What the submitter was told
                      </summary>
                      <p className="text-sm" style={{ color: "var(--n-700)", marginTop: "0.4rem" }}>
                        {r.ai_explanation_staff}
                      </p>
                    </details>
                  )}
                </div>
              )}

              {!aiResults[r.id] && r.ai_source === "none" && (
                <p className="subtle text-xs" style={{ marginTop: "0.9rem" }}>
                  No assessment — this revision was submitted before the
                  pre-submission check was introduced.
                </p>
              )}

              {aiResults[r.id] &&
                (aiResults[r.id].pipeline === "v2" ? (
                  <AiPanelV2 result={aiResults[r.id]} />
                ) : (
                  <AiPanel result={aiResults[r.id].ai_assessment || aiResults[r.id]} />
                ))}

              {r.status === "pending" && (
                <div style={{ marginTop: "1rem" }}>
                  {selectedRevision === r.id ? (
                    <div className="col anim-fade-up">
                      <textarea
                        className="textarea"
                        placeholder="Reviewer notes (optional)"
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                      />
                      <div className="row-wrap" style={{ gap: "0.5rem" }}>
                        <button className="btn btn-success" onClick={() => handleReview(r.id, "approved")}>
                          Approve
                        </button>
                        <button className="btn btn-danger" onClick={() => handleReview(r.id, "rejected")}>
                          Reject
                        </button>
                        <button className="btn btn-ghost" onClick={() => setSelectedRevision(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button className="btn btn-primary" onClick={() => setSelectedRevision(r.id)}>
                      Review this revision
                    </button>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      {showManualModal && (
        <div className="modal-overlay" onClick={() => setShowManualModal(false)}>
          <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3 className="modal-title">Manual — section context</h3>
              <button className="modal-close" onClick={() => setShowManualModal(false)}>✕</button>
            </div>

            <div className="modal-body">
              {manualLoading ? (
                <div className="loading-row"><span className="spinner" /> Loading manual sections…</div>
              ) : manualSections.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon">📄</div>
                  <p className="empty-title">No sections found</p>
                  <p className="empty-text">This manual doesn&apos;t have any sections yet.</p>
                </div>
              ) : (
                <div className="col" style={{ gap: "1rem" }}>
                  {manualSections.map((sec) => (
                    <div key={sec.id}>
                      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.4rem" }}>
                        <strong>{sec.subtitle || "Untitled section"}</strong>
                        <span className="badge badge-neutral">#{sec.id} · {sec.tag}</span>
                      </div>
                      <div className="content-box content-box-scroll">{sec.content || "(empty)"}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
