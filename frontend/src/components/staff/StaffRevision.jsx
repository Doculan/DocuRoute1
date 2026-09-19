import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import DiffView from "../DiffView";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const STATUS = {
  pending:  { badge: "badge-warning", alert: "alert-warning", label: "Pending review", tone: "is-warning" },
  approved: { badge: "badge-success", alert: "alert-success", label: "Approved",       tone: "is-success" },
  rejected: { badge: "badge-danger",  alert: "alert-danger",  label: "Not approved",   tone: "is-danger" },
};

// "Returned" is not a stored state: a revision sent back is rejected with
// notes to act on. Surfacing it as its own filter is the difference between
// "this was refused" and "this needs your attention", which is the question
// a submitter is actually asking.
const FILTERS = [
  { key: "all",      label: "All",      tone: "" },
  { key: "pending",  label: "Pending",  tone: "is-warning" },
  { key: "approved", label: "Approved", tone: "is-success" },
  { key: "returned", label: "Returned", tone: "is-danger" },
  { key: "rejected", label: "Rejected", tone: "is-danger" },
];

const VERDICT_LABEL = {
  approve: "The check found nothing blocking",
  needs_revision: "The check expected changes to be needed",
  reject: "The check expected this to be refused",
};

function formatWhen(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function StaffRevisions({
  focusRevisionId, onFeedbackRead, onOpenSection,
}) {
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState("");
  const [scope, setScope]         = useState("mine");
  const [filter, setFilter]       = useState("all");
  const [expanded, setExpanded]   = useState(focusRevisionId ?? null);

  const fetchRevisions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Status is filtered in the browser rather than server-side so the
      // counts on the filter row stay true for the whole scope - a filter
      // that changes the numbers it is filtering is unreadable.
      //
      // That trade stops paying somewhere around a few hundred revisions in
      // one scope, when fetching them all to count them costs more than the
      // stable counts are worth. The endpoint already accepts ?status=, so
      // the fix is to pass it here and fetch the counts separately (one
      // aggregate query) rather than to change the API.
      const res = await axios.get(
        `${BASE_URL}/api/staff/revisions/?scope=${scope}`, getAuth()
      );
      setRevisions(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load your revisions.");
      setRevisions([]);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { fetchRevisions(); }, [fetchRevisions]);

  const isReturned = (r) => r.status === "rejected" && (r.reviewer_notes || "").trim();

  const counts = useMemo(() => ({
    all: revisions.length,
    pending:  revisions.filter((r) => r.status === "pending").length,
    approved: revisions.filter((r) => r.status === "approved").length,
    returned: revisions.filter(isReturned).length,
    rejected: revisions.filter((r) => r.status === "rejected").length,
  }), [revisions]);

  const filtered = useMemo(() => {
    if (filter === "all") return revisions;
    if (filter === "returned") return revisions.filter(isReturned);
    return revisions.filter((r) => r.status === filter);
  }, [revisions, filter]);

  // Opening a revision with unread feedback is what "reading" it means.
  const openRevision = async (revision) => {
    const next = expanded === revision.id ? null : revision.id;
    setExpanded(next);
    if (next && revision.has_unread_feedback && revision.is_mine) {
      try {
        await axios.post(
          `${BASE_URL}/api/staff/revisions/${revision.id}/seen/`, {}, getAuth()
        );
        setRevisions((rows) => rows.map((r) =>
          r.id === revision.id ? { ...r, has_unread_feedback: false } : r
        ));
        onFeedbackRead?.();
      } catch {
        // Failing to mark it read is not worth interrupting the reader.
      }
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">My Revisions</h1>
          <p className="page-subtitle">
            Every revision you have submitted, what the reviewer decided, and
            what the AI check said before you sent it.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={fetchRevisions}>↻ Refresh</button>
      </header>

      {/* Same columns either way, so widening the scope stays comparable
          with your own work rather than becoming a different report. */}
      <div className="row-wrap" style={{ gap: "0.4rem", marginBottom: "1rem", alignItems: "center" }}>
        <span className="subtle text-xs strong">SHOWING</span>
        <div className="tabs" style={{ margin: 0 }}>
          <button
            className={`tab${scope === "mine" ? " is-active" : ""}`}
            onClick={() => setScope("mine")}
          >
            Mine
          </button>
          <button
            className={`tab${scope === "office" ? " is-active" : ""}`}
            onClick={() => setScope("office")}
          >
            My office
          </button>
        </div>
      </div>

      {/* The filter row doubles as the counts. Marked with aria-pressed and a
          visible selected state so it reads as a control, not a stats strip. */}
      <div className="stat-grid" role="group" aria-label="Filter by status">
        {FILTERS.map(({ key, label, tone }) => (
          <button
            key={key}
            type="button"
            aria-pressed={filter === key}
            className={`stat-card ${tone}${filter === key ? " is-selected" : ""}`}
            style={{ textAlign: "left", cursor: "pointer" }}
            onClick={() => setFilter(key)}
          >
            <span className="stat-value">{counts[key]}</span>
            <span className="stat-label">{label}</span>
          </button>
        ))}
      </div>

      {error && <div className="alert alert-danger" style={{ marginBottom: "1.25rem" }}>{error}</div>}

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading revisions…</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing here yet</p>
          <p className="empty-text">
            {scope === "office" && filter === "all"
              ? "Nobody in your department has submitted a revision yet."
              : filter === "all"
                ? "You have not submitted a revision yet. Open a section from My Manuals and propose a change."
                : `No revisions are ${filter} right now.`}
          </p>
        </div>
      ) : (
        <div className="col stagger" style={{ gap: "0.75rem" }}>
          {filtered.map((r) => {
            const st = STATUS[r.status] || STATUS.pending;
            const returned = isReturned(r);
            const isExpanded = expanded === r.id;
            return (
              <div key={r.id} className={`card accordion ${st.tone}`}>
                <button className="accordion-head" onClick={() => openRevision(r)}>
                  <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                    <div className="strong">{r.manual}</div>
                    <div className="muted text-sm">{r.section}</div>
                    {scope === "office" && !r.is_mine && (
                      <div className="subtle text-xs">submitted by {r.submitted_by}</div>
                    )}
                  </div>

                  <div className="row" style={{ gap: "1rem", alignItems: "center" }}>
                    {r.has_unread_feedback && (
                      <span className="badge badge-info">new feedback</span>
                    )}
                    <div style={{ textAlign: "right" }}>
                      <span className={`badge ${st.badge}`}>
                        {returned ? "Returned for changes" : st.label}
                      </span>
                      <div className="subtle text-xs" style={{ marginTop: "0.3rem" }}>
                        {formatWhen(r.submitted_at)}
                      </div>
                    </div>
                    <span className={`chevron${isExpanded ? " is-open" : ""}`}>▾</span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="accordion-body">
                    <RevisionDetail revision={r} onOpenSection={onOpenSection} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * One revision, in the order a submitter reads it: what the reviewer said
 * first when there is something to act on, then what was submitted, then
 * what the check had warned.
 */
function RevisionDetail({ revision: r, onOpenSection }) {
  const st = STATUS[r.status] || STATUS.pending;
  const hasNotes = Boolean((r.reviewer_notes || "").trim());

  return (
    <div className="col" style={{ gap: "1rem" }}>
      {/* 1. Reviewer feedback - the actionable part, so it leads. */}
      {hasNotes ? (
        <div className={`alert ${st.alert}`}>
          <div className="strong" style={{ marginBottom: "0.3rem" }}>
            {r.status === "approved" ? "Reviewer's note" : "What the reviewer asked for"}
          </div>
          <p style={{ margin: 0 }}>{r.reviewer_notes}</p>
          <p className="text-xs" style={{ margin: "0.5rem 0 0", opacity: 0.85 }}>
            {r.reviewed_by ? `${r.reviewed_by} · ` : ""}{formatWhen(r.reviewed_at)}
          </p>
        </div>
      ) : r.status === "pending" ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          Waiting for a reviewer. Their decision and any notes will appear here.
        </p>
      ) : (
        <p className="subtle text-sm" style={{ margin: 0 }}>
          {st.label} on {formatWhen(r.reviewed_at)}
          {r.reviewed_by ? ` by ${r.reviewed_by}` : ""} — no note was left.
        </p>
      )}

      {/* 2. What was submitted. */}
      {(r.diff_text || r.diff_preview) && (
        <div className="diff-wrap">
          <div className="diff-wrap-head">What you proposed</div>
          <div className="diff-scroll">
            <DiffView diffText={r.diff_text || r.diff_preview} />
          </div>
        </div>
      )}

      {/* 3. The reason, under the clause that requires it. */}
      {r.change_reason && (
        <div>
          <p className="label" style={{ marginBottom: "0.3rem" }}>
            Reason for change · clause 6.3
          </p>
          <div className="content-box">{r.change_reason}</div>
        </div>
      )}

      {/* 4. The stored snapshot. Never re-run: this is the record of what
             was read before submitting, not a fresh opinion. */}
      {r.ai_source === "staff_precheck" && r.ai_verdict && (
        <div>
          <p className="label" style={{ marginBottom: "0.3rem" }}>
            What the AI check said before you submitted
          </p>
          <div className="card card-pad">
            <div className="row-wrap" style={{ gap: "0.4rem", alignItems: "center", marginBottom: "0.5rem" }}>
              <span className="badge badge-neutral">
                {VERDICT_LABEL[r.ai_verdict] || r.ai_verdict}
              </span>
              {r.ai_assessed_at && (
                <span className="subtle text-xs">checked {formatWhen(r.ai_assessed_at)}</span>
              )}
            </div>
            {r.ai_explanation_staff && (
              <p className="text-sm" style={{ color: "var(--n-700)", margin: "0 0 0.5rem" }}>
                {r.ai_explanation_staff}
              </p>
            )}
            {(r.ai_issues || []).length > 0 && (
              <div className="col" style={{ gap: "0.3rem" }}>
                {r.ai_issues.map((issue) => (
                  <div key={issue.label} className="row-wrap" style={{ gap: "0.4rem", alignItems: "center" }}>
                    <span className="badge badge-warning">
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
            <p className="subtle text-xs" style={{ margin: "0.6rem 0 0" }}>
              Advice recorded at the time you submitted. The reviewer&apos;s
              decision above is what counts.
            </p>
          </div>
        </div>
      )}

      {r.section_id && onOpenSection && (
        <div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => onOpenSection(r.manual_id, r.section_id)}
          >
            Open this section
          </button>
        </div>
      )}
    </div>
  );
}
