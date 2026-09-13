import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BASE_URL = "http://127.0.0.1:8000";

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
  return text.split("\n").reduce((acc, line) => {
    if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) return acc;
    if (line.startsWith("-")) acc.push({ type: "removed", text: line.slice(1) });
    else if (line.startsWith("+")) acc.push({ type: "added", text: line.slice(1) });
    else acc.push({ type: "context", text: line.startsWith(" ") ? line.slice(1) : line });
    return acc;
  }, []);
}

function ColorizedDiff({ diffText }) {
  if (!diffText) return <p className="muted text-sm" style={{ padding: "0.75rem" }}>No changes detected.</p>;

  return (
    <div className="diff-view">
      {diffText.split("\n").map((line, idx) => {
        const key = `${idx}-${line.slice(0, 12)}`;
        if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) {
          return <div key={key} className="diff-line is-meta">{line}</div>;
        }
        if (line.startsWith("-")) {
          return (
            <div key={key} className="diff-line is-removed">
              <span className="diff-sign">−</span><span>{line.slice(1)}</span>
            </div>
          );
        }
        if (line.startsWith("+")) {
          return (
            <div key={key} className="diff-line is-added">
              <span className="diff-sign">+</span><span>{line.slice(1)}</span>
            </div>
          );
        }
        return (
          <div key={key} className="diff-line">
            <span className="diff-sign" />
            <span>{line.startsWith(" ") ? line.slice(1) : line}</span>
          </div>
        );
      })}
    </div>
  );
}

function SideBySideDiff({ rev }) {
  const items = parseUnifiedDiff(rev.diff_text || rev.diff_preview || "");

  const renderColumn = (side) => {
    const highlight = side === "left" ? "removed" : "added";
    return (
      <div className="diff-pane">
        <div className="diff-pane-head">{side === "left" ? "Original" : "Proposed"}</div>
        <div className="diff-view">
          {items.map((item, idx) => (
            <div
              key={`${side}-${idx}`}
              className={`diff-line${item.type === highlight ? ` is-${highlight}` : ""}`}
            >
              <span className="diff-gutter">{idx + 1}</span>
              <span>{item.text}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="diff-split">
      {renderColumn("left")}
      {renderColumn("right")}
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

export default function RevisionReview() {
  const [revisions, setRevisions] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
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

      setAiResults((prev) => ({ ...prev, [revisionId]: data.ai_assessment }));
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
          <h1 className="page-title">Revision Review</h1>
          <p className="page-subtitle">Compare proposed changes against the master copy before approving.</p>
        </div>
      </header>

      <div className="tabs">
        {["pending", "approved", "rejected"].map((s) => (
          <button
            key={s}
            className={`tab${statusFilter === s ? " is-active" : ""}`}
            onClick={() => setStatusFilter(s)}
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
            <article key={r.id} className={`card card-pad rev-card ${STATUS_TONE[r.status] || ""}`}>
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
                <button
                  type="button"
                  className="btn btn-subtle btn-sm"
                  onClick={() => analyzeWithAI(r.id, "modified")}
                  disabled={Boolean(aiLoading[r.id])}
                >
                  {aiLoading[r.id] ? <><span className="spinner" /> Analyzing…</> : "✨ AI revision assessment"}
                </button>
              </div>

              <div className="diff-wrap">
                <div className="diff-wrap-head">
                  Changes in <strong>{r.section}</strong>
                </div>
                <div className="diff-scroll">
                  <ColorizedDiff diffText={r.diff_preview || r.diff_text || ""} />
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

              {aiResults[r.id] && <AiPanel result={aiResults[r.id]} />}

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
