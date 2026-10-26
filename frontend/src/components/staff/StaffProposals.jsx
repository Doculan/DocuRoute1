import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "../admin/ConfirmDestructive";
import ProposalPackage from "../ProposalPackage";
import QmsDecisions from "../QmsDecisions";
import TrailReport from "../TrailReport";
import { STATUS_LABEL, WITH_PACKAGE } from "../proposalStatus";
// DocDiff, not DiffView: this is the submitter's view of their own
// change, marked the way a person with a red pen would mark it.
// DiffView is the reviewer's technical diff.
import DocDiff from "../DocDiff";
import AiNote from "../AiNote";
import SectionContentEditor from "../SectionContentEditor";
import Icon from "../Icon";
import DeadlineTag from "../DeadlineTag";
import AuditTrail from "../AuditTrail";
import { freezeText } from "../deadlineText";
import ProposalBoard from "./ProposalBoard";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const confirmed = (token) => ({
  headers: { ...getAuth().headers, ...reauthHeader(token) },
});

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
export default function StaffProposals({ startManualId, onDone, openRequest, onOpened }) {
  const [open, setOpen] = useState(null);       // proposal id
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  // Bumped after anything that changes the list, so it reloads.
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  // The document a new proposal is waiting on the password for.
  const [confirmStart, setConfirmStart] = useState(null);

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
        // Starting a new one asks for the password; reopening does not,
        // which is why the first try goes without it.
        else if (body?.reason === "reauth_required") setConfirmStart(startManualId);
        else setError(body?.error || "Could not start a proposal.");
      } finally {
        onDone?.();
        reload();
      }
    })();
  }, [startManualId, onDone, reload]);

  const start = async (token) => {
    const manualId = confirmStart;
    setConfirmStart(null);
    try {
      const { data } = await axios.post(
        `${BASE_URL}/api/proposals/`, { manual_id: manualId }, confirmed(token)
      );
      setOpen(data.id);
    } catch (err) {
      const body = err.response?.data;
      if (body?.reason === "already_open") setOpen(body.proposal_id);
      else setError(body?.error || "Could not start a proposal.");
    }
  };

  // Arriving from a notification.
  useEffect(() => {
    if (!openRequest) return;
    setOpen(openRequest.id);
    onOpened?.();
  }, [openRequest, onOpened]);

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 6000);
  };

  if (open != null) {
    return (
      <Proposal
        key={open}
        proposalId={open}
        onBack={() => { setOpen(null); reload(); onDone?.(); }}
        onSay={say}
      />
    );
  }

  return (
    <div>
      {confirmStart && (
        <ConfirmDestructive
          title="Start a proposal?"
          body="Your office takes on a change to this document. You can withdraw it later; the record stays."
          confirmLabel="Start proposal"
          onConfirm={start}
          onCancel={() => setConfirmStart(null)}
        />
      )}

      <header className="page-head">
        <div>
          <h1 className="page-title">Proposals</h1>
          <p className="page-subtitle">
            What your office owes first, then what waits on it, then the rest.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      <ProposalBoard refreshKey={refresh} onOpen={setOpen} onStart={setConfirmStart} />
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
        <button className="btn btn-ghost btn-sm" onClick={onBack}><Icon name="back" />Proposals</button>
        <div className="alert alert-danger" style={{ marginTop: "1rem" }}>{error}</div>
      </div>
    );
  }
  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  // The action comes as an argument where it is chosen in the same click:
  // `pending` set a moment earlier is not visible to this call yet, and
  // reading it there sent nothing - no concurrence, return or withdrawal
  // ever reached the server from this screen.
  const act = async (token, action = pending) => {
    const { url, body, success } = action;
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

  // Moves inside the office, with no password: Send to Head, Recall and
  // Return to Encoder commit nothing outside it.
  const move = async (url, body, success) => {
    try {
      await axios.post(`${BASE_URL}${url}`, body || {}, getAuth());
      onSay(success);
      setDecision(null);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    }
  };

  // Whose turn it is inside the office, from the latest step that says so.
  const lastTurn = [...data.events].reverse().find((e) => [
    "sent_to_head", "recalled", "returned_to_encoder", "submitted", "redrafted", "created",
  ].includes(e.event));

  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack}><Icon name="back" />Proposals</button>

      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h1 className="page-title">{data.manual}</h1>
          <p className="page-subtitle">
            {STATUS_LABEL[data.status]} · version {data.version} ·
            {" "}from {data.initiating_office}
            {data.deadline && <> <DeadlineTag tag={data.deadline} /></>}
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

      <TrailReport proposalId={proposalId} access={data.trail_report} />

      <QmsDecisions decisions={data.qms_decisions} documentStatus={data.document_status} />

      {WITH_PACKAGE.includes(data.status) && (
        <ProposalPackage key={data.status} proposalId={proposalId} onChanged={load} />
      )}

      {data.status === "with_head" && (
        <div className="alert alert-info">
          {data.can_return_to_encoder
            ? "Sent to you by the Encoder. Submit it, or return it with a note."
            : `With the Head since ${when(lastTurn?.at)}. Recall it to change anything.`}
        </div>
      )}

      {data.status === "draft" && lastTurn?.event === "returned_to_encoder" && (
        <div className="alert alert-warning">
          <div className="strong">
            {data.can_send_to_head ? "Returned by your Head" : "Returned to the Encoder"}
          </div>
          {lastTurn.detail && <p style={{ margin: "0.3rem 0 0" }}>“{lastTurn.detail}”</p>}
        </div>
      )}

      {data.status === "draft" && data.blockers.length > 0 && (
        <div className="alert alert-warning">
          <div className="strong">Not ready yet</div>
          <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.1rem" }}>
            {data.blockers.map((b) => <li key={b}>{b}</li>)}
          </ul>
        </div>
      )}

      {data.proposal_note && (
        <ProposalNote note={data.proposal_note} forReviewers={data.viewer_is_initiator === false}
                      noteId={`proposal-${proposalId}-v${data.version}`} />
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

      {data.freeze && (data.can_send_to_head || data.can_submit) && (
        <p className="subtle text-sm" style={{ margin: "1.75rem 0 -1rem" }}>
          {freezeText(data.freeze)}: {data.freeze.reason}. Keep editing; sending waits.
        </p>
      )}
      <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "1.75rem" }}>
        {data.can_send_to_head && (
          <button
            className="btn btn-primary"
            disabled={!data.ready_to_submit || !!data.freeze}
            title={data.freeze ? freezeText(data.freeze) : undefined}
            onClick={() => move(`/api/proposals/${proposalId}/send-to-head/`, null,
                                "Sent to your Head.")}
          >
            Send to Head
          </button>
        )}

        {data.can_recall && (
          <button className="btn btn-ghost"
                  onClick={() => move(`/api/proposals/${proposalId}/recall/`, null,
                                      "Recalled. It is back in draft.")}>
            Recall
          </button>
        )}

        {data.can_return_to_encoder && (
          <button className="btn btn-ghost" onClick={() => setDecision("to_encoder")}>
            Return to Encoder
          </button>
        )}

        {data.can_submit && (
          <button
            className="btn btn-primary"
            disabled={!data.ready_to_submit || !!data.freeze}
            title={data.freeze ? freezeText(data.freeze) : undefined}
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

        {data.can_withdraw && (
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
            setDecision(null);
            return act(token, {
              url: `/api/proposals/${proposalId}/decide/`,
              body: { decision: "concur" },
              success: "Recorded.",
            });
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
            setDecision(null);
            return act(token, {
              url: `/api/proposals/${proposalId}/decide/`,
              body: {
                decision: "return", feedback,
                section_id: feedbackSection || undefined,
              },
              success: "Returned with your feedback.",
            });
          }}
        />
      )}

      {decision === "to_encoder" && (
        <ReturnToEncoderForm
          onCancel={() => setDecision(null)}
          onSend={(note) => move(`/api/proposals/${proposalId}/return-to-encoder/`,
                                 { note }, "Returned to the Encoder with your note.")}
        />
      )}

      {decision === "withdraw" && (
        <WithdrawForm
          onCancel={() => setDecision(null)}
          onSend={(reason, token) => {
            setDecision(null);
            return act(token, {
              url: `/api/proposals/${proposalId}/withdraw/`,
              body: { reason },
              success: "Withdrawn. The record stays.",
            });
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

      <AuditTrail key={`${data.status}-${data.events.length}`} proposalId={proposalId} />
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
            const dirty = isOpen && draft !== (change?.new_text ?? s.current_text ?? "");
            return (
              <div key={s.section_id} className="proposal-section">
                <button
                  className="proposal-section-head"
                  disabled={busy}
                  onClick={() => {
                    const current = sections.find((section) => section.section_id === openSection);
                    if (current && draft !== (current.change?.new_text ?? current.current_text ?? "") &&
                        !window.confirm("Discard unsaved edits to this section?")) return;
                    setOpenSection(isOpen ? null : s.section_id);
                    setDraft(change?.new_text ?? s.current_text ?? "");
                  }}
                >
                  <span className="office-twisty">{isOpen ? "▾" : "▸"}</span>
                  <span className="doc-ref">{s.subtitle}</span>
                  {change?.has_changed && (
                    <>
                      <span className="badge badge-info">changed</span>
                      {change.check_is_current && !dirty ? (
                        <span className="subtle text-xs">checked</span>
                      ) : (
                        <span className="badge badge-warning">needs a check</span>
                      )}
                    </>
                  )}
                  {dirty && <span className="badge badge-warning">unsaved edits</span>}
                </button>

                {isOpen && (
                  <div className="proposal-section-body">
                    {editable ? (
                      <>
                        <SectionContentEditor
                          key={s.section_id}
                          label={s.subtitle}
                          value={draft}
                          onChange={setDraft}
                          disabled={busy}
                        />
                        <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "0.6rem" }}>
                          <button className="btn btn-primary btn-sm" disabled={busy || !dirty}
                                  onClick={() => saveSection(s)}>
                            Save this section
                          </button>
                          {change?.has_changed && (
                            <>
                              <button className="btn btn-ghost btn-sm" disabled={busy || dirty}
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
                        {dirty && <p className="subtle text-xs">Save this section before running the AI check.</p>}
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
                        stale={!change.check_is_current || dirty}
                        forReviewers={data.viewer_is_initiator === false}
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

/**
 * The proposal-level note: composed once at submission from the stored
 * section checks, and frozen with the version.
 */
function ProposalNote({ note, forReviewers, noteId }) {
  const text = forReviewers ? note.reader : note.drafter;
  if (!text) return null;
  return (
    <section className="card card-pad" style={{ marginBottom: "1.25rem" }}>
      <span className="label" style={{ display: "block", marginBottom: "0.6rem" }}>
        AI check — the proposal as a whole
      </span>
      <AiNote key={noteId} text={text} noteId={noteId} reveal={!forReviewers} />
    </section>
  );
}

/**
 * The AI check's note on one section. No verdict: the note says what
 * changed, what to look at and why, in words. The drafting office reads it
 * addressed to them, streamed in the first time they see it; everyone else
 * reads it addressed to them, all at once.
 */
function Assessment({ assessment, stale, forReviewers }) {
  const text = forReviewers
    ? assessment.explanation_reviewer || assessment.explanation
    : assessment.explanation;
  return (
    <div className="card card-pad" style={{ marginTop: "0.8rem" }}>
      <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "baseline", marginBottom: "0.6rem" }}>
        <span className="label">AI check</span>
        {stale && (
          <span className="badge badge-warning">
            this section changed since
          </span>
        )}
      </div>

      <AiNote key={`${assessment.id}-${forReviewers ? "reader" : "drafter"}`}
              text={text} noteId={`${assessment.id}-${forReviewers ? "reader" : "drafter"}`}
              reveal={!forReviewers && assessment.note_format === "prose"} />

      {assessment.coordinated_change && (
        <p className="subtle text-sm" style={{ marginTop: "0.6rem" }}>
          {assessment.coordinated_change}
        </p>
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
                    {r.recorded_by.position}
                    {r.recorded_by.name && ` · ${r.recorded_by.name}`}
                    {` · ${when(r.recorded_at)}`}
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

/** The Head's note to the Encoder. No password: it stays inside the office. */
function ReturnToEncoderForm({ onCancel, onSend }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (busy || !note.trim()) return;
    setBusy(true);
    await onSend(note);
    setBusy(false);
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "460px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title">Return to the Encoder?</h3>
          </div>
          <div className="modal-body col" style={{ gap: "1rem" }}>
            <div className="field">
              <label className="label" htmlFor="to-encoder-note">What needs changing</label>
              <textarea id="to-encoder-note" className="textarea" rows={3} autoFocus
                        value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy || !note.trim()}>
              {busy ? "Working…" : "Return"}
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
