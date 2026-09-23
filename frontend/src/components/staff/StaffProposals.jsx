import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "../admin/ConfirmDestructive";
// DocDiff, not DiffView: this is the submitter's view of their own
// change, marked the way a person with a red pen would mark it.
// DiffView is the reviewer's technical diff.
import DocDiff from "../DocDiff";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const confirmed = (token) => ({
  headers: { ...getAuth().headers, ...reauthHeader(token) },
});

const STATUS_LABEL = {
  draft: "Draft",
  concurrence: "Out for concurrence",
  locked: "Locked",
  withdrawn: "Withdrawn",
};

const VERDICT_WORDS = {
  approve: "no concerns",
  needs_revision: "needs revision",
  reject: "serious concerns",
};

function when(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * Proposals: a change to a whole document, agreed by the offices that
 * work on it.
 *
 * Three screens behind one tab — the list, the editor, and the detail
 * view — because they are three states of one thing and moving between
 * them should not feel like navigating.
 *
 * Reading comes first everywhere: the editor shows the whole document
 * with every section collapsed, and opening one is what starts an edit.
 */
export default function StaffProposals({ startManualId, onDone }) {
  const [tab, setTab] = useState("mine");
  const [mine, setMine] = useState([]);
  const [awaiting, setAwaiting] = useState([]);
  const [open, setOpen] = useState(null);       // proposal id
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ours, theirs] = await Promise.all([
        axios.get(`${BASE_URL}/api/proposals/`, getAuth()),
        axios.get(`${BASE_URL}/api/proposals/awaiting/`, getAuth()),
      ]);
      setMine(ours.data.proposals);
      setAwaiting(theirs.data.proposals);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load proposals.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Arriving from a section's "Propose changes".
  useEffect(() => {
    if (!startManualId) return;
    (async () => {
      try {
        const { data } = await axios.post(
          `${BASE_URL}/api/proposals/`, { manual_id: startManualId },
          getAuth()
        );
        setOpen(data.id);
      } catch (err) {
        const body = err.response?.data;
        if (body?.reason === "already_open") setOpen(body.proposal_id);
        else setError(body?.error || "Could not start a proposal.");
      } finally {
        onDone?.();
        load();
      }
    })();
  }, [startManualId, onDone, load]);

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 6000);
  };

  if (open != null) {
    return (
      <Proposal
        proposalId={open}
        onBack={() => { setOpen(null); load(); }}
        onSay={say}
      />
    );
  }

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const rows = tab === "mine" ? mine : awaiting;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Proposals</h1>
          <p className="page-subtitle">
            Changes to a whole document, agreed by the offices that work on it.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      <div className="tabs">
        <button className={`tab${tab === "mine" ? " is-active" : ""}`}
                onClick={() => setTab("mine")}>
          From my office{mine.length > 0 ? ` (${mine.length})` : ""}
        </button>
        <button className={`tab${tab === "awaiting" ? " is-active" : ""}`}
                onClick={() => setTab("awaiting")}>
          Awaiting my office{awaiting.length > 0 ? ` (${awaiting.length})` : ""}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">
            {tab === "mine" ? "No proposals yet" : "Nothing waiting on you"}
          </p>
          <p className="empty-text">
            {tab === "mine"
              ? "Open a document, find the section you want to change, and choose Propose changes."
              : "Proposals needing your office's agreement will appear here."}
          </p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.15rem" }}>
          {rows.map((p) => (
            <button key={p.id} className="series-row" onClick={() => setOpen(p.id)}>
              <span className="series-code">{p.manual}</span>
              <span className="series-title">
                {p.changed_sections} section{p.changed_sections === 1 ? "" : "s"}
                {p.version > 1 ? ` · version ${p.version}` : ""}
              </span>
              <span className={`status-mark is-${
                p.status === "locked" ? "approved"
                  : p.status === "withdrawn" ? "returned" : "pending"}`}>
                {STATUS_LABEL[p.status]}
              </span>
              {tab === "awaiting" && (
                <span className="subtle text-xs">from {p.initiating_office}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** One proposal: the document, its participants, and what has happened. */
function Proposal({ proposalId, onBack, onSay }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(null);
  const [decision, setDecision] = useState(null);   // "concur" | "return"
  const [feedback, setFeedback] = useState("");
  const [feedbackSection, setFeedbackSection] = useState("");

  const load = useCallback(async () => {
    try {
      const { data: full } = await axios.get(
        `${BASE_URL}/api/proposals/${proposalId}/full/`, getAuth()
      );
      setData(full);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load this proposal.");
    }
  }, [proposalId]);

  useEffect(() => { load(); }, [load]);

  if (error && !data) {
    return (
      <div>
        <button className="link-btn" onClick={onBack}>← Proposals</button>
        <div className="alert alert-danger" style={{ marginTop: "1rem" }}>{error}</div>
      </div>
    );
  }
  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const act = async (token) => {
    const { url, body, success } = pending;
    setPending(null);
    try {
      await axios.post(`${BASE_URL}${url}`, body || {}, confirmed(token));
      onSay(success);
      setDecision(null);
      setFeedback("");
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    }
  };

  const editable = data.status === "draft" && data.can_submit !== undefined;

  return (
    <div>
      <button className="link-btn" onClick={onBack}>← Proposals</button>

      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h1 className="page-title">{data.manual}</h1>
          <p className="page-subtitle">
            {STATUS_LABEL[data.status]} · version {data.version} ·
            {" "}from {data.initiating_office}
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      {data.status === "locked" && (
        <div className="alert alert-success">
          Every office has agreed and the content is frozen. The document
          itself changes once the paperwork is signed and the custodian
          records it.
        </div>
      )}

      {data.status === "draft" && data.blockers.length > 0 && (
        <div className="alert alert-warning">
          <div className="strong">Not ready to submit</div>
          <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.1rem" }}>
            {data.blockers.map((b) => <li key={b}>{b}</li>)}
          </ul>
        </div>
      )}

      <Editor
        proposalId={proposalId}
        data={data}
        editable={data.status === "draft"}
        onChanged={load}
        onError={setError}
      />

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">Offices</h2>
        <Participants rows={data.participants} />
      </section>

      {data.versions.some((v) => v.decisions.length > 0) && (
        <section style={{ marginTop: "1.75rem" }}>
          <h2 className="section-title">What has been said</h2>
          <History versions={data.versions} />
        </section>
      )}

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">History</h2>
        <div className="col" style={{ gap: "0.2rem" }}>
          {data.events.map((e, i) => (
            <div key={i} className="row" style={{ gap: "0.6rem", alignItems: "baseline" }}>
              <span className="text-sm">{e.label}</span>
              <span className="subtle text-xs">{e.office} · {when(e.at)}</span>
              {e.detail && <span className="subtle text-xs">— {e.detail}</span>}
            </div>
          ))}
        </div>
      </section>

      <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "1.75rem" }}>
        {data.can_submit && (
          <button
            className="btn btn-primary"
            disabled={!data.ready_to_submit}
            onClick={() => setPending({
              url: `/api/proposals/${proposalId}/submit/`,
              success: "Submitted.",
              title: "Submit for concurrence?",
              body: data.participants.filter((p) => p.role === "concurring").length
                ? `${data.participants.filter((p) => p.role === "concurring").length} office(s) will be asked to agree. The document is locked to further editing once they all do.`
                : "No other office concurs on this document, so it locks immediately.",
              confirmLabel: "Submit",
            })}
          >
            Submit for concurrence
          </button>
        )}

        {data.can_decide && (
          <>
            <button className="btn btn-primary" onClick={() => setDecision("concur")}>
              Concur
            </button>
            <button className="btn btn-ghost" onClick={() => setDecision("return")}>
              Return with feedback
            </button>
          </>
        )}

        {(data.status === "draft" || data.status === "concurrence")
          && data.can_submit && (
          <button
            className="btn btn-ghost"
            onClick={() => setDecision("withdraw")}
          >
            Withdraw
          </button>
        )}
      </div>

      {decision === "concur" && (
        <ConfirmDestructive
          title={`Concur on ${data.manual}?`}
          body="Your office agrees to this text. If every other office agrees too, the content locks and can no longer be amended."
          confirmLabel="Concur"
          onConfirm={(token) => {
            setPending({
              url: `/api/proposals/${proposalId}/decide/`,
              body: { decision: "concur" },
              success: "Recorded.",
            });
            setDecision(null);
            return act(token);
          }}
          onCancel={() => setDecision(null)}
        />
      )}

      {decision === "return" && (
        <FeedbackForm
          data={data}
          feedback={feedback}
          onFeedback={setFeedback}
          section={feedbackSection}
          onSection={setFeedbackSection}
          onCancel={() => { setDecision(null); setFeedback(""); }}
          onSend={(token) => {
            setPending({
              url: `/api/proposals/${proposalId}/decide/`,
              body: {
                decision: "return", feedback,
                section_id: feedbackSection || undefined,
              },
              success: "Returned with your feedback.",
            });
            setDecision(null);
            return act(token);
          }}
        />
      )}

      {decision === "withdraw" && (
        <WithdrawForm
          onCancel={() => setDecision(null)}
          onSend={(reason, token) => {
            setPending({
              url: `/api/proposals/${proposalId}/withdraw/`,
              body: { reason },
              success: "Withdrawn. The record stays.",
            });
            setDecision(null);
            return act(token);
          }}
        />
      )}

      {pending && !decision && (
        <ConfirmDestructive
          title={pending.title}
          body={pending.body}
          confirmLabel={pending.confirmLabel}
          onConfirm={act}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

/** The whole document, collapsed. Opening a section is what starts an edit. */
function Editor({ proposalId, data, editable, onChanged, onError }) {
  const [sections, setSections] = useState(null);
  const [openSection, setOpenSection] = useState(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState(data.overall_reason || "");

  const loadSections = useCallback(async () => {
    const { data: full } = await axios.get(
      `${BASE_URL}/api/proposals/${proposalId}/`, getAuth()
    );
    setSections(full.all_sections);
  }, [proposalId]);

  useEffect(() => { loadSections().catch(() => setSections([])); }, [loadSections]);

  if (!sections) {
    return <div className="loading-row"><span className="spinner" /> Loading the document…</div>;
  }

  const saveReason = async () => {
    try {
      await axios.patch(`${BASE_URL}/api/proposals/${proposalId}/`,
                        { overall_reason: reason }, getAuth());
      onChanged();
    } catch (err) {
      onError(err.response?.data?.error || "Could not save the reason.");
    }
  };

  const saveSection = async (section) => {
    setBusy(true);
    try {
      await axios.put(
        `${BASE_URL}/api/proposals/${proposalId}/sections/${section.section_id}/`,
        { new_text: draft }, getAuth()
      );
      await loadSections();
      onChanged();
    } catch (err) {
      onError(err.response?.data?.error || "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const check = async (section) => {
    setBusy(true);
    try {
      await axios.post(
        `${BASE_URL}/api/proposals/${proposalId}/sections/${section.section_id}/check/`,
        {}, getAuth()
      );
      await loadSections();
      onChanged();
    } catch (err) {
      onError(err.response?.data?.error || "The check could not run.");
    } finally {
      setBusy(false);
    }
  };

  const revert = async (section) => {
    setBusy(true);
    try {
      await axios.delete(
        `${BASE_URL}/api/proposals/${proposalId}/sections/${section.section_id}/`,
        getAuth()
      );
      setOpenSection(null);
      await loadSections();
      onChanged();
    } catch (err) {
      onError(err.response?.data?.error || "Could not undo that.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {editable && (
        <section style={{ marginTop: "1.5rem" }}>
          <div className="field">
            <label className="label" htmlFor="overall-reason">
              Why this change is being made
            </label>
            <textarea
              id="overall-reason"
              className="textarea"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onBlur={saveReason}
              placeholder="What changed and why — this is the reason printed on the change request."
            />
            <p className="subtle text-xs" style={{ margin: 0 }}>
              One reason for the whole proposal. Each section can carry its
              own note as well.
            </p>
          </div>
        </section>
      )}

      <section style={{ marginTop: "1.5rem" }}>
        <h2 className="section-title">
          The document
          <span className="subtle text-xs" style={{ marginLeft: "0.5rem" }}>
            {data.changed_sections} of {sections.length} changed
          </span>
        </h2>

        <div className="col" style={{ gap: "0.2rem" }}>
          {sections.map((s) => {
            const change = s.change;
            const isOpen = openSection === s.section_id;
            return (
              <div key={s.section_id} className="proposal-section">
                <button
                  className="proposal-section-head"
                  onClick={() => {
                    setOpenSection(isOpen ? null : s.section_id);
                    setDraft(change?.new_text ?? s.current_text ?? "");
                  }}
                >
                  <span className="office-twisty">{isOpen ? "▾" : "▸"}</span>
                  <span className="doc-ref">{s.subtitle}</span>
                  {change?.has_changed && (
                    <>
                      <span className="badge badge-info">changed</span>
                      {change.check_is_current ? (
                        <span className="subtle text-xs">
                          checked — {VERDICT_WORDS[change.assessment?.verdict]
                            || change.assessment?.verdict}
                        </span>
                      ) : (
                        <span className="badge badge-warning">needs a check</span>
                      )}
                    </>
                  )}
                </button>

                {isOpen && (
                  <div className="proposal-section-body">
                    {editable ? (
                      <>
                        <textarea
                          className="textarea textarea-doc"
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          rows={10}
                        />
                        <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "0.6rem" }}>
                          <button className="btn btn-primary btn-sm" disabled={busy}
                                  onClick={() => saveSection(s)}>
                            Save this section
                          </button>
                          {change?.has_changed && (
                            <>
                              <button className="btn btn-ghost btn-sm" disabled={busy}
                                      onClick={() => check(s)}>
                                {change.check_is_current ? "Check again" : "Run the check"}
                              </button>
                              <button className="btn btn-ghost btn-sm" disabled={busy}
                                      onClick={() => revert(s)}>
                                Undo this change
                              </button>
                            </>
                          )}
                        </div>
                      </>
                    ) : change?.has_changed ? (
                      <DocDiff diffText={change.diff_text} />
                    ) : (
                      <p className="doc-body" style={{ whiteSpace: "pre-wrap" }}>
                        {s.current_text}
                      </p>
                    )}

                    {change?.assessment && (
                      <Assessment
                        assessment={change.assessment}
                        stale={!change.check_is_current}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}

/** The one place on these screens where substance beats brevity. */
function Assessment({ assessment, stale }) {
  return (
    <div className="card card-pad" style={{ marginTop: "0.8rem" }}>
      <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "baseline" }}>
        <span className="label">Check</span>
        <span className="strong">
          {VERDICT_WORDS[assessment.verdict] || assessment.verdict}
        </span>
        {stale && (
          <span className="badge badge-warning">
            this section changed since
          </span>
        )}
      </div>

      {assessment.explanation && (
        <p className="text-sm" style={{ marginTop: "0.5rem", color: "var(--n-700)" }}>
          {assessment.explanation}
        </p>
      )}

      {assessment.coordinated_change && (
        <p className="subtle text-sm" style={{ marginTop: "0.5rem" }}>
          {assessment.coordinated_change}
        </p>
      )}

      {assessment.hard_fails?.length > 0 && (
        <ul className="text-sm" style={{ marginTop: "0.5rem", paddingLeft: "1.1rem" }}>
          {assessment.hard_fails.map((f, i) => (
            <li key={i}>{f.evidence || f.label}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Participants({ rows }) {
  const concurring = rows.filter((r) => r.role === "concurring");
  const approving = rows.filter((r) => r.role === "approving");

  return (
    <div className="col" style={{ gap: "0.9rem" }}>
      <div>
        <div className="label">Must agree</div>
        {concurring.length === 0 ? (
          <p className="subtle text-sm" style={{ margin: 0 }}>
            No other office concurs on this document.
          </p>
        ) : (
          <div className="col" style={{ gap: "0.25rem" }}>
            {concurring.map((r) => (
              <div key={r.office_id} className="row" style={{ gap: "0.6rem", alignItems: "baseline" }}>
                <span className="text-sm">{r.office}</span>
                {r.decision === "concur" && (
                  <span className="status-mark is-approved">Concurred</span>
                )}
                {r.decision === "return" && (
                  <span className="status-mark is-returned">Returned</span>
                )}
                {!r.decision && <span className="subtle text-xs">waiting</span>}
                {r.recorded_by && (
                  <span className="subtle text-xs">
                    {r.recorded_by} · {when(r.recorded_at)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {approving.length > 0 && (
        <div>
          <div className="label">Signs, on paper</div>
          <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
            {approving.map((r) => r.office).join(" → ")}
          </p>
        </div>
      )}
    </div>
  );
}

function History({ versions }) {
  return (
    <div className="col" style={{ gap: "0.9rem" }}>
      {versions.filter((v) => v.decisions.length > 0).map((v) => (
        <div key={v.number}>
          <div className="label">Version {v.number}</div>
          <div className="col" style={{ gap: "0.35rem" }}>
            {v.decisions.map((d, i) => (
              <div key={i}>
                <span className="text-sm">
                  <span className="strong">{d.office}</span>{" "}
                  {d.decision === "concur" ? "concurred" : "returned it"}
                </span>
                {d.feedback && (
                  <p className="text-sm" style={{ margin: "0.15rem 0 0", color: "var(--n-700)" }}>
                    {d.feedback}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function FeedbackForm({ data, feedback, onFeedback, section, onSection, onCancel, onSend }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    if (busy || !feedback.trim() || !password) return;
    setBusy(true);
    try {
      const { data: token } = await axios.post(
        `${BASE_URL}/api/auth/confirm-password/`, { password }, getAuth()
      );
      setPassword("");
      await onSend(token.token);
    } catch (err) {
      setError(err.response?.data?.error || "Could not confirm your password.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "520px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title">Return {data.manual}?</h3>
          </div>
          <div className="modal-body col" style={{ gap: "1rem" }}>
            <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
              It goes back to {data.initiating_office} as a new version, and
              every office&apos;s agreement resets — they agreed to text that
              will no longer exist.
            </p>

            <div className="field">
              <label className="label" htmlFor="return-feedback">
                What needs changing
              </label>
              <textarea
                id="return-feedback"
                className="textarea"
                autoFocus
                value={feedback}
                onChange={(e) => onFeedback(e.target.value)}
              />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                Every office involved sees this, which saves them raising the
                same point again.
              </p>
            </div>

            <div className="field">
              <label className="label" htmlFor="return-section">
                About a particular section <span className="subtle">(optional)</span>
              </label>
              <select id="return-section" className="select" value={section}
                      onChange={(e) => onSection(e.target.value)}>
                <option value="">the proposal as a whole</option>
                {data.sections.map((s) => (
                  <option key={s.section_id} value={s.section_id}>{s.subtitle}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="label" htmlFor="return-password">
                Confirm with your password
              </label>
              <input id="return-password" className="input" type="password"
                     autoComplete="current-password" value={password}
                     onChange={(e) => { setPassword(e.target.value); setError(""); }} />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                You are recording this on behalf of your office.
              </p>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn btn-danger"
                    disabled={busy || !feedback.trim() || !password}>
              {busy ? "Working…" : "Return it"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function WithdrawForm({ onCancel, onSend }) {
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    if (busy || !reason.trim() || !password) return;
    setBusy(true);
    try {
      const { data } = await axios.post(
        `${BASE_URL}/api/auth/confirm-password/`, { password }, getAuth()
      );
      setPassword("");
      await onSend(reason, data.token);
    } catch (err) {
      setError(err.response?.data?.error || "Could not confirm your password.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "460px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title">Withdraw this proposal?</h3>
          </div>
          <div className="modal-body col" style={{ gap: "1rem" }}>
            <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
              It stops here and the sections are free for someone else to
              propose against. The record of it stays.
            </p>
            <div className="field">
              <label className="label" htmlFor="withdraw-reason">Why</label>
              <input id="withdraw-reason" className="input" autoFocus value={reason}
                     onChange={(e) => setReason(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="withdraw-password">
                Confirm with your password
              </label>
              <input id="withdraw-password" className="input" type="password"
                     autoComplete="current-password" value={password}
                     onChange={(e) => { setPassword(e.target.value); setError(""); }} />
            </div>
            {error && <div className="alert alert-danger">{error}</div>}
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn btn-danger"
                    disabled={busy || !reason.trim() || !password}>
              {busy ? "Working…" : "Withdraw"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
