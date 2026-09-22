import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const confirmedAuth = (token) => ({
  headers: { ...getAuth().headers, ...reauthHeader(token) },
});

const KINDS = [
  { value: "encoder", label: "Encoder", hint: "Drafts and runs the check — the form's “Requested by”" },
  { value: "head", label: "Head", hint: "Commits the office — the form's “Department/Unit Head”" },
  { value: "imr", label: "Integrated Management Representative", hint: "Accepts or denies requests — section 3" },
  { value: "document_custodian", label: "Document Custodian", hint: "Records document status — section 5" },
];

const kindLabel = (value) =>
  KINDS.find((k) => k.value === value)?.label || value;

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * People, and the posts they hold.
 *
 * The process never names a person — it names a position and asks who
 * holds it. So the screen's job is to keep those two things visibly
 * separate: a person has posts, a post has holders, and both carry dates.
 *
 * Nobody is deleted here. Someone who leaves is deactivated, which ends
 * their current posts and keeps the record of what they did.
 */
export default function People() {
  const [tab, setTab] = useState("people");
  const [data, setData] = useState(null);
  const [positions, setPositions] = useState(null);
  const [offices, setOffices] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [assigning, setAssigning] = useState(null);   // person
  const [pending, setPending] = useState(null);       // a guarded action

  const load = useCallback(async () => {
    try {
      const [people, posts, tree] = await Promise.all([
        axios.get(`${BASE_URL}/api/org/people/`, getAuth()),
        axios.get(`${BASE_URL}/api/org/positions/`, getAuth()),
        axios.get(`${BASE_URL}/api/org/offices/`, getAuth()),
      ]);
      setData(people.data);
      setPositions(posts.data);
      setOffices(tree.data.offices);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load people.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 4500);
  };

  const approve = async (person) => {
    try {
      await axios.post(
        `${BASE_URL}/api/org/people/${person.id}/approve/`, {}, getAuth()
      );
      say(`${person.username} approved. They hold no post yet.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not approve.");
    }
  };

  /** Every guarded action goes through one path, so the password prompt
   *  and the error handling are written once. */
  const runGuarded = async (token) => {
    const { url, body, success } = pending;
    setPending(null);
    try {
      await axios.post(`${BASE_URL}${url}`, body || {}, confirmedAuth(token));
      say(success);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    }
  };

  const assign = async (form, token) => {
    setAssigning(null);
    try {
      const { data: created } = await axios.post(
        `${BASE_URL}/api/org/people/${form.personId}/assign/`,
        {
          office_id: form.officeId, kind: form.kind,
          starts_on: form.startsOn || undefined,
          is_acting: form.isActing,
        },
        confirmedAuth(token)
      );
      say(`${kindLabel(created.kind)} at ${created.office}${created.is_acting ? " (acting)" : ""}.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not assign the post.");
    }
  };

  if (!data || !positions) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const pendingSignups = data.people.filter((p) => !p.is_approved);
  const active = data.people.filter((p) => p.is_approved && p.is_active);
  const inactive = data.people.filter((p) => p.is_approved && !p.is_active);
  const awaiting = active.filter((p) => p.current_positions.length === 0);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">People and positions</h1>
          <p className="page-subtitle">
            The process refers to positions; this is who holds them, and when.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      <div className="tabs">
        {[
          ["people", `People (${active.length})`],
          ["positions", "By office"],
          pendingSignups.length > 0 && ["pending", `Awaiting approval (${pendingSignups.length})`],
        ].filter(Boolean).map(([key, label]) => (
          <button key={key} className={`tab${tab === key ? " is-active" : ""}`}
                  onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "pending" && (
        <div className="col" style={{ gap: "0.5rem" }}>
          {pendingSignups.map((p) => (
            <div key={p.id} className="card card-pad row"
                 style={{ justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
              <div>
                <div className="strong">{p.full_name || p.username}</div>
                <div className="subtle text-xs">
                  {p.username}{p.email ? ` · ${p.email}` : ""}
                </div>
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => approve(p)}>
                Approve
              </button>
            </div>
          ))}
        </div>
      )}

      {tab === "people" && (
        <>
          {awaiting.length > 0 && (
            <div className="alert alert-warning" style={{ marginBottom: "1.25rem" }}>
              <strong>{awaiting.length}</strong>{" "}
              approved {awaiting.length === 1 ? "person holds" : "people hold"} no
              post, so {awaiting.length === 1 ? "they can" : "they can"} sign in and do
              nothing: {awaiting.map((p) => p.username).join(", ")}.
            </div>
          )}

          <div className="col" style={{ gap: "0.5rem" }}>
            {active.map((p) => (
              <PersonCard
                key={p.id}
                person={p}
                onAssign={() => setAssigning(p)}
                onEnd={(a) => setPending({
                  url: `/api/org/assignments/${a.id}/end/`,
                  success: `${kindLabel(a.kind)} at ${a.office} ended.`,
                  title: `End ${p.username} as ${kindLabel(a.kind)}?`,
                  body: `The appointment is closed with today's date. `
                      + `${a.office} will have no current ${kindLabel(a.kind)} `
                      + `until somebody else is assigned. The record stays.`,
                  confirmLabel: "End appointment",
                })}
                onDeactivate={() => setPending({
                  url: `/api/org/people/${p.id}/deactivate/`,
                  success: `${p.username} deactivated.`,
                  title: `Deactivate ${p.full_name || p.username}?`,
                  body: "Every post they currently hold is ended with today's "
                      + "date, and they can no longer sign in. Nothing is "
                      + "deleted — what they did stays on the record.",
                  confirmLabel: "Deactivate",
                })}
              />
            ))}
          </div>

          {inactive.length > 0 && (
            <section style={{ marginTop: "1.75rem" }}>
              <h2 className="section-title">No longer active</h2>
              <div className="col" style={{ gap: "0.35rem" }}>
                {inactive.map((p) => (
                  <div key={p.id} className="row" style={{ gap: "0.75rem", alignItems: "baseline" }}>
                    <span className="subtle">{p.full_name || p.username}</span>
                    <span className="subtle text-xs">
                      {p.past_positions.length} past post
                      {p.past_positions.length === 1 ? "" : "s"}
                    </span>
                    <button
                      className="link-btn"
                      onClick={() => setPending({
                        url: `/api/org/people/${p.id}/reactivate/`,
                        success: `${p.username} reactivated. Assign their posts again.`,
                        title: `Reactivate ${p.full_name || p.username}?`,
                        body: "They can sign in again. The posts they held are "
                            + "not restored — those ended on a date, and "
                            + "re-opening them would rewrite the record. "
                            + "Assign them again.",
                        confirmLabel: "Reactivate",
                      })}
                    >
                      Reactivate
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {tab === "positions" && <ByOffice positions={positions} />}

      {assigning && (
        <AssignForm
          person={assigning}
          offices={offices.filter((o) => o.is_active)}
          onSave={assign}
          onCancel={() => setAssigning(null)}
        />
      )}

      {pending && (
        <ConfirmDestructive
          title={pending.title}
          body={pending.body}
          confirmLabel={pending.confirmLabel}
          onConfirm={runGuarded}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

function PersonCard({ person, onAssign, onEnd, onDeactivate }) {
  const [showPast, setShowPast] = useState(false);

  return (
    <div className="card card-pad">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
        <div style={{ minWidth: 0 }}>
          <div className="strong">{person.full_name || person.username}</div>
          <div className="subtle text-xs">{person.username}</div>
        </div>
        <div className="row-wrap" style={{ gap: "0.5rem" }}>
          <button className="btn btn-ghost btn-sm" onClick={onAssign}>Assign a post</button>
          <button className="btn btn-ghost btn-sm" onClick={onDeactivate}>Deactivate</button>
        </div>
      </div>

      {person.current_positions.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: "0.6rem 0 0" }}>
          No post yet.
        </p>
      ) : (
        <div className="col" style={{ gap: "0.3rem", marginTop: "0.7rem" }}>
          {person.current_positions.map((a) => (
            <div key={a.id} className="row" style={{ gap: "0.6rem", alignItems: "baseline" }}>
              <span className="text-sm">
                {a.kind_label} — {a.office}
              </span>
              {a.is_acting && <span className="badge badge-warning">acting</span>}
              <span className="subtle text-xs">since {formatDate(a.starts_on)}</span>
              <button className="link-btn" onClick={() => onEnd(a)}>End</button>
            </div>
          ))}
        </div>
      )}

      {person.past_positions.length > 0 && (
        <>
          <button className="link-btn" style={{ marginTop: "0.5rem" }}
                  onClick={() => setShowPast((v) => !v)}>
            {showPast ? "Hide" : `${person.past_positions.length} past post${person.past_positions.length === 1 ? "" : "s"}`}
          </button>
          {showPast && (
            <div className="col" style={{ gap: "0.25rem", marginTop: "0.4rem" }}>
              {person.past_positions.map((a) => (
                <span key={a.id} className="subtle text-xs">
                  {a.kind_label} — {a.office}
                  {a.is_acting ? " (acting)" : ""}
                  {" · "}{formatDate(a.starts_on)} to {formatDate(a.ends_on)}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ByOffice({ positions }) {
  return (
    <div>
      {positions.qms.length > 0 && (
        <section style={{ marginBottom: "1.75rem" }}>
          <h2 className="section-title">Quality management</h2>
          <div className="col" style={{ gap: "0.3rem" }}>
            {positions.qms.map((row, i) => (
              <span key={i} className="text-sm">
                {row.kind_label} — {row.user}
                {row.is_acting ? " (acting)" : ""}
                <span className="subtle text-xs"> · {row.office}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <div className="col" style={{ gap: "1.25rem" }}>
        {positions.offices.map((office) => (
          <section key={office.office_id}>
            <h2 className="section-title">
              {office.office}
              {!office.has_current_head && (
                <span className="badge badge-warning" style={{ marginLeft: "0.5rem" }}>
                  no current head
                </span>
              )}
            </h2>
            {office.positions.length === 0 ? (
              <p className="subtle text-sm" style={{ margin: 0 }}>
                No positions here yet.
              </p>
            ) : (
              <div className="col" style={{ gap: "0.45rem" }}>
                {office.positions.map((p) => (
                  <div key={p.id}>
                    <span className="text-sm">
                      <span className="label" style={{ marginRight: "0.5rem" }}>
                        {p.kind_label}
                      </span>
                      {p.held_by.length === 0 ? (
                        <span className="subtle">vacant</span>
                      ) : (
                        p.held_by.map((h) => (
                          <span key={h.assignment_id}>
                            {h.full_name || h.user}
                            {h.is_acting ? " (acting)" : ""}
                            <span className="subtle text-xs"> since {formatDate(h.since)}</span>
                          </span>
                        ))
                      )}
                    </span>
                    {p.previously.length > 0 && (
                      <div className="subtle text-xs" style={{ marginLeft: "0.3rem" }}>
                        previously:{" "}
                        {p.previously.map((h, i) => (
                          <span key={i}>
                            {i > 0 && ", "}
                            {h.user}{h.is_acting ? " (acting)" : ""}{" "}
                            ({formatDate(h.from)}–{formatDate(h.to)})
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

function AssignForm({ person, offices, onSave, onCancel }) {
  const [form, setForm] = useState({
    personId: person.id,
    officeId: offices[0]?.id ?? null,
    kind: "encoder",
    startsOn: "",
    isActing: false,
  });
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const guarded = form.kind !== "encoder";
  const hint = KINDS.find((k) => k.value === form.kind)?.hint;

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      let token = null;
      if (guarded) {
        const { data } = await axios.post(
          `${BASE_URL}/api/auth/confirm-password/`, { password }, getAuth()
        );
        token = data.token;
      }
      setPassword("");
      await onSave(form, token);
    } catch (err) {
      setError(err.response?.data?.error || "Could not confirm your password.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "480px" }}>
        <form onSubmit={submit}>
          <div className="modal-head">
            <h3 className="modal-title">
              Assign {person.full_name || person.username}
            </h3>
          </div>

          <div className="modal-body col" style={{ gap: "1rem" }}>
            <div className="field">
              <label className="label" htmlFor="assign-office">Office</label>
              <select
                id="assign-office"
                className="select"
                value={form.officeId ?? ""}
                onChange={(e) => setForm({ ...form, officeId: Number(e.target.value) })}
              >
                {offices.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="label" htmlFor="assign-kind">Position</label>
              <select
                id="assign-kind"
                className="select"
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
              >
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </select>
              {hint && <p className="subtle text-xs" style={{ margin: 0 }}>{hint}</p>}
            </div>

            <div className="field">
              <label className="label" htmlFor="assign-start">
                From <span className="subtle">(today if left blank)</span>
              </label>
              <input
                id="assign-start"
                className="input"
                type="date"
                value={form.startsOn}
                onChange={(e) => setForm({ ...form, startsOn: e.target.value })}
              />
            </div>

            <label className="row" style={{ gap: "0.55rem", alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={form.isActing}
                onChange={(e) => setForm({ ...form, isActing: e.target.checked })}
              />
              <span>
                <span className="strong">Acting / officer-in-charge</span>
                <span className="subtle text-xs" style={{ display: "block" }}>
                  They do everything the post allows. This records that the
                  appointment was temporary.
                </span>
              </span>
            </label>

            {guarded && (
              <div className="field">
                <label className="label" htmlFor="assign-password">
                  Confirm with your password
                </label>
                <input
                  id="assign-password"
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(""); }}
                />
                <p className="subtle text-xs" style={{ margin: 0 }}>
                  Asked because this post commits an office or decides requests.
                </p>
              </div>
            )}

            {error && <div className="alert alert-danger">{error}</div>}
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !form.officeId || (guarded && !password)}
            >
              {busy ? "Working…" : "Assign"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
