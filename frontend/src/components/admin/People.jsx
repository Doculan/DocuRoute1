import { useEffect, useState } from "react";
import axios from "axios";
import DelegationPanel from "../DelegationPanel";
import Pager from "../Pager";
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
  // Filtered and paged on the server: 50 a page (spec §11.1).
  const [filters, setFilters] = useState({ status: "active", office: "", position: "" });
  const [query, setQuery] = useState("");
  const [needle, setNeedle] = useState("");
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);

  const [assigning, setAssigning] = useState(null);   // person
  const [pending, setPending] = useState(null);       // a guarded action
  const [pendingApprove, setPendingApprove] = useState(null);

  // Asked of the server a moment after typing stops.
  useEffect(() => {
    const timer = setTimeout(() => { setNeedle(query.trim()); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    axios.get(`${BASE_URL}/api/org/offices/`, getAuth())
      .then((res) => setOffices(res.data.offices))
      .catch(() => setOffices([]));
  }, []);

  useEffect(() => {
    const params = { status: filters.status, page };
    if (needle) params.q = needle;
    if (filters.office) params[filters.office.startsWith("b") ? "branch" : "office"] = filters.office.slice(1);
    if (filters.position) params.position = filters.position;
    axios.get(`${BASE_URL}/api/org/people/`, { ...getAuth(), params })
      .then((res) => { setData(res.data); setError(""); })
      .catch((err) => setError(err.response?.data?.error || "Could not load people."));
  }, [filters, needle, page, reloadKey]);

  // The by-office view is the expensive one; it loads when opened.
  useEffect(() => {
    if (tab !== "positions") return;
    axios.get(`${BASE_URL}/api/org/positions/`, getAuth())
      .then((res) => setPositions(res.data))
      .catch((err) => setError(err.response?.data?.error || "Could not load positions."));
  }, [tab, reloadKey]);

  const load = () => setReloadKey((k) => k + 1);
  const filter = (change) => { setFilters({ ...filters, ...change }); setPage(1); };

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 4500);
  };

  const approve = async (token) => {
    const person = pendingApprove;
    setPendingApprove(null);
    try {
      const { data: done } = await axios.post(
        `${BASE_URL}/api/org/people/${person.id}/approve/`, {}, confirmedAuth(token)
      );
      // The office chosen at sign-up stands: approval makes them an
      // Encoder or Head there, unless placement needs manual resolution.
      say(`${done.message}${done.note ? ` ${done.note}` : ""}`);
      load();
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
      load();
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
      load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not assign the post.");
    }
  };

  if (!data) {
    return error
      ? <div className="alert alert-danger">{error}</div>
      : <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const counts = data.counts;
  const signups = filters.status === "pending" ? data.people : (data.pending_signups || []);
  const listed = filters.status === "pending" ? [] : data.people;
  const branches = offices.filter((o) => !o.parent_id && o.is_active);

  const endFor = (p) => (a) => setPending({
    url: `/api/org/assignments/${a.id}/end/`,
    success: `${kindLabel(a.kind)} at ${a.office} ended.`,
    title: `End ${p.username} as ${kindLabel(a.kind)}?`,
    body: `The appointment is closed with today's date. `
        + `${a.office} will have no current ${kindLabel(a.kind)} `
        + `until somebody else is assigned. The record stays.`,
    confirmLabel: "End appointment",
  });

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
        {[["people", "People"], ["positions", "By office"]].map(([key, label]) => (
          <button key={key} className={`tab${tab === key ? " is-active" : ""}`}
                  onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "people" && (
        <>
          {/* Counts first; each opens its list. */}
          <p className="queue-counts">
            {[["active", counts.active, "active"],
              ["pending", counts.pending, "awaiting approval"],
              ["awaiting_position", counts.awaiting_position, "holding no post"],
              ["inactive", counts.inactive, "no longer active"]]
              .filter(([, n]) => n > 0)
              .map(([key, n, label]) => (
                <button key={key} type="button" className="queue-count link-btn"
                        aria-pressed={filters.status === key}
                        onClick={() => filter({ status: key })}>
                  <strong>{n.toLocaleString()}</strong> {label}
                </button>
              ))}
          </p>

          {signups.length > 0 && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h2 className="section-title">Awaiting approval · {counts.pending.toLocaleString()}</h2>
              <div className="col" style={{ gap: "0.5rem" }}>
                {signups.map((p) => (
                  <SignupCard key={p.id} person={p} onApprove={() => setPendingApprove(p)} />
                ))}
              </div>
            </section>
          )}

          {filters.status !== "pending" && (
            <>
              <div className="filter-row" style={{ marginBottom: "1rem" }}>
                <input className="input" type="search" style={{ width: "240px" }}
                       placeholder="Search by name or username" aria-label="Search people"
                       value={query} onChange={(e) => setQuery(e.target.value)} />
                <select className="select" style={{ width: "auto" }} aria-label="Status"
                        value={filters.status} onChange={(e) => filter({ status: e.target.value })}>
                  <option value="active">Active</option>
                  <option value="awaiting_position">Holding no post</option>
                  <option value="inactive">No longer active</option>
                  <option value="all">Everyone</option>
                </select>
                <select className="select" style={{ width: "auto", maxWidth: "18rem" }}
                        aria-label="Office or branch" value={filters.office}
                        onChange={(e) => filter({ office: e.target.value })}>
                  <option value="">Any office</option>
                  <optgroup label="A branch and everything beneath it">
                    {branches.map((o) => <option key={`b${o.id}`} value={`b${o.id}`}>{o.name}</option>)}
                  </optgroup>
                  <optgroup label="One office">
                    {offices.filter((o) => o.is_active).map((o) => (
                      <option key={`o${o.id}`} value={`o${o.id}`}>{o.name}</option>
                    ))}
                  </optgroup>
                </select>
                <select className="select" style={{ width: "auto" }} aria-label="Position"
                        value={filters.position} onChange={(e) => filter({ position: e.target.value })}>
                  <option value="">Any position</option>
                  {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                  <option value="none">No post</option>
                </select>
              </div>

              {listed.length === 0 ? (
                <p className="subtle text-sm">Nobody matches.</p>
              ) : (
                <div className="col" style={{ gap: "0.5rem" }}>
                  {listed.map((p) => (!p.is_active ? (
                    <div key={p.id} className="row" style={{ gap: "0.75rem", alignItems: "baseline" }}>
                      <span className="subtle">{p.full_name || p.username}</span>
                      <span className="subtle text-xs">
                        {p.past_positions.length} past post{p.past_positions.length === 1 ? "" : "s"}
                      </span>
                      <button className="btn btn-subtle btn-sm" onClick={() => setPending({
                        url: `/api/org/people/${p.id}/reactivate/`,
                        success: `${p.username} reactivated. Assign their posts again.`,
                        title: `Reactivate ${p.full_name || p.username}?`,
                        body: "They can sign in again. The posts they held are "
                            + "not restored — those ended on a date, and "
                            + "re-opening them would rewrite the record. "
                            + "Assign them again.",
                        confirmLabel: "Reactivate",
                      })}>
                        Reactivate
                      </button>
                    </div>
                  ) : !p.is_approved ? (
                    <SignupCard key={p.id} person={p} onApprove={() => setPendingApprove(p)} />
                  ) : (
                    <PersonCard
                      key={p.id}
                      person={p}
                      onAssign={() => setAssigning(p)}
                      onEnd={endFor(p)}
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
                  )))}
                </div>
              )}
              <Pager paging={data} onPage={setPage} />
            </>
          )}
        </>
      )}

      {tab === "positions" && (positions
        ? <ByOffice positions={positions} />
        : <div className="loading-row"><span className="spinner" /> Loading…</div>)}

      {assigning && (
        <AssignForm
          person={assigning}
          offices={offices.filter((o) => o.is_active)}
          onSave={assign}
          onCancel={() => setAssigning(null)}
        />
      )}

      {pendingApprove && (
        <ConfirmDestructive
          title={`Approve ${pendingApprove.full_name || pendingApprove.username}?`}
          body={pendingApprove.approval_warning || (pendingApprove.requested_office
            ? `This grants access as ${pendingApprove.requested_position_label} at ${pendingApprove.requested_office.name}.`
            : "This approves system access. Assign their office and position afterwards.")}
          passwordHint="Confirm because accepting grants system access and may assign an office position."
          confirmLabel="Approve"
          onConfirm={approve}
          onCancel={() => setPendingApprove(null)}
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

/** One sign-up waiting on the admin: what they asked for, and Approve. */
function SignupCard({ person: p, onApprove }) {
  return (
    <div className="card card-pad row"
         style={{ justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
      <div>
        <div className="strong">{p.full_name || p.username}</div>
        <div className="subtle text-xs">
          {p.username}{p.email ? ` · ${p.email}` : ""}
        </div>
        <div className="text-xs" style={{ marginTop: "0.2rem" }}>
          {p.requested_office
            ? <>Requested <strong>{p.requested_position_label}</strong> at <strong>{p.requested_office.name}</strong></>
            : <span className="subtle">
                <strong>Office not listed</strong>
                {p.requested_office_name && <> — typed “{p.requested_office_name}”</>}
                . Assign an office after approving.
              </span>}
        </div>
        {p.approval_warning && <div className="text-xs" role="status">{p.approval_warning}</div>}
        {p.date_joined && (
          <div className="subtle text-xs">
            Signed up {new Date(p.date_joined).toLocaleString()}
          </div>
        )}
      </div>
      <button className="btn btn-primary btn-sm" onClick={onApprove}>
        Approve
      </button>
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
              <button className="btn btn-danger-soft btn-sm" onClick={() => onEnd(a)}>End</button>
            </div>
          ))}
        </div>
      )}

      {person.past_positions.length > 0 && (
        <>
          <button className="btn btn-ghost btn-sm" style={{ marginTop: "0.5rem" }}
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

/** The admin may set up a delegation too (Q-6), folded until asked. */
function DelegationToggle({ office }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button type="button" className="link-btn text-xs" style={{ marginBottom: "0.4rem" }}
              onClick={() => setOpen(true)}>
        Delegations…
      </button>
    );
  }
  return (
    <div style={{ marginBottom: "0.6rem" }}>
      <DelegationPanel officeId={office.office_id} officeName={office.office} />
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
            {office.delegations.map((d) => (
              <p key={d.id} className="text-sm" style={{ margin: "0 0 0.4rem" }}>
                <span className="badge badge-warning">{d.current ? "Head away" : "Head away soon"}</span>{" "}
                {d.delegate} acts as Head, {formatDate(d.starts_on)}–{formatDate(d.ends_on)}
              </p>
            ))}
            {office.has_current_head && <DelegationToggle office={office} />}
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
