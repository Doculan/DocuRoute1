import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import useServerData from "../useServerData";
import Icon from "../Icon";
import { dueText, freezeText } from "../deadlineText";
import DeadlineTag from "../DeadlineTag";
import ConfirmDestructive, { reauthHeader } from "./ConfirmDestructive";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const DEFAULT_REMINDERS = "30, 14, 7, 3, 1";

/**
 * Deadlines & announcements: two kinds, one screen (spec §6.1).
 *
 * Deadlines first - they are obligations, tracked office by office -
 * then announcements, which are information. Each opens on counts and
 * pages its rows on the server.
 */
export default function Notices() {
  const [tab, setTab] = useState("deadlines");
  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Deadlines & announcements</h1>
          <p className="page-subtitle">Deadlines are tracked until each office meets them. Announcements inform.</p>
        </div>
      </header>
      <div className="tabs">
        <button className={`tab${tab === "deadlines" ? " is-active" : ""}`} onClick={() => setTab("deadlines")}>
          Deadlines
        </button>
        <button className={`tab${tab === "announcements" ? " is-active" : ""}`} onClick={() => setTab("announcements")}>
          Announcements
        </button>
        <button className={`tab${tab === "freeze" ? " is-active" : ""}`} onClick={() => setTab("freeze")}>
          Change freeze
        </button>
      </div>
      {tab === "deadlines" ? <Deadlines /> : tab === "freeze" ? <Freezes /> : <Announcements />}
    </div>
  );
}

// ─── Change freeze (3D) ─────────────────────────────────────────

const SCOPES = [["all", "Everything"], ["offices", "Selected offices"], ["series", "Selected series"]];

function reauthHeaders(token) {
  return { headers: { ...getAuth().headers, ...reauthHeader(token) } };
}

/**
 * "Do not revise now" - a separate control from a deadline. While a
 * freeze is in force, new proposals, sending to the Head, submitting and
 * making effective wait within its scope; drafts stay editable and nothing
 * is hidden. Every change here asks for the password.
 */
function Freezes() {
  const { data, error, reload: load } = useServerData("/api/admin/freezes/", null,
                                                      "Could not load freezes.");
  const [starting, setStarting] = useState(false);
  const [pending, setPending] = useState(null);   // {title, body, label, run}
  const [message, setMessage] = useState("");

  const confirm = (spec) => setPending(spec);
  const run = async (token) => {
    await pending.run(token);
    setMessage(pending.done);
    setPending(null);
    load();
  };

  if (starting) {
    return <FreezeForm onCancel={() => setStarting(false)} confirm={confirm}
                       onDone={() => { setStarting(false); setMessage("Freeze started. The offices were told."); load(); }}
                       pending={pending} run={run} cancel={() => setPending(null)} />;
  }

  return (
    <div>
      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}
      <div className="row-wrap" style={{ gap: "0.5rem", marginBottom: "0.75rem" }}>
        <button className="btn btn-primary btn-sm" onClick={() => { setMessage(""); setStarting(true); }}>
          Start a freeze
        </button>
      </div>
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.in_force.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No freeze in force</p>
          <p className="empty-text">Start one before an audit to hold revisions.</p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.75rem" }}>
          {data.in_force.map((f) => (
            <FreezeCard key={f.id} freeze={f} confirm={confirm} />
          ))}
        </div>
      )}
      {data?.lifted.length > 0 && (
        <details style={{ marginTop: "1.25rem" }}>
          <summary className="subtle text-sm">Lifted ({data.lifted.length})</summary>
          <div className="col" style={{ gap: "0.2rem", marginTop: "0.5rem" }}>
            {data.lifted.map((f) => (
              <div key={f.id} className="text-sm">
                {f.reason} <span className="subtle">· {scopeText(f)} · lifted {new Date(f.lifted_at).toLocaleDateString("en-PH")}</span>
              </div>
            ))}
          </div>
        </details>
      )}
      {pending && (
        <ConfirmDestructive title={pending.title} body={pending.body} confirmLabel={pending.label}
                            passwordHint="Asked because this changes what offices can do."
                            onConfirm={run} onCancel={() => setPending(null)} />
      )}
    </div>
  );
}

function scopeText(f) {
  if (f.scope === "all") return "Everything";
  const names = f.scope === "offices" ? f.offices : f.series.map((s) => `Series ${s}`);
  return names.length > 3 ? `${names.slice(0, 3).join(", ")} +${names.length - 3}` : names.join(", ");
}

function FreezeCard({ freeze, confirm }) {
  const [extending, setExtending] = useState(false);
  const [until, setUntil] = useState(freeze.expected_end_on);
  const [excepting, setExcepting] = useState(false);
  const [manual, setManual] = useState(null);
  const [reason, setReason] = useState("");

  return (
    <div className="card card-pad col" style={{ gap: "0.6rem" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", gap: "1rem" }}>
        <div>
          <div className="strong">{freezeText(freeze)}</div>
          <div className="text-sm">{freeze.reason}</div>
          <div className="subtle text-xs">{scopeText(freeze)}</div>
        </div>
        {freeze.past_expected_end && <span className="status-mark is-returned">Past its expected end</span>}
      </div>
      {freeze.exceptions.length > 0 && (
        <ul className="text-sm" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {freeze.exceptions.map((e, i) => (
            <li key={i}>Exception: {e.manual || e.proposal} <span className="subtle">— {e.reason}</span></li>
          ))}
        </ul>
      )}
      <div className="row-wrap" style={{ gap: "0.5rem" }}>
        <button className="btn btn-primary btn-sm" onClick={() => confirm({
          title: "Lift this freeze?",
          body: `${scopeText(freeze)}: proposals can be started, sent and submitted again, and changes made effective. Paused overdue notices resume on the next run. The offices are told.`,
          label: "Lift freeze", done: "Lifted. The offices were told.",
          run: (token) => axios.post(`/api/admin/freezes/${freeze.id}/lift/`, {}, reauthHeaders(token)),
        })}>Lift</button>
        <button className="btn btn-ghost btn-sm" onClick={() => setExtending(!extending)}>Extend</button>
        <button className="btn btn-ghost btn-sm" onClick={() => setExcepting(!excepting)}>Add an exception</button>
      </div>
      {extending && (
        <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "flex-end" }}>
          <div className="field">
            <label className="label" htmlFor={`fz-ext-${freeze.id}`}>Expected end</label>
            <input id={`fz-ext-${freeze.id}`} className="input" type="date" value={until}
                   onChange={(e) => setUntil(e.target.value)} />
          </div>
          <button className="btn btn-ghost btn-sm" disabled={!until} onClick={() => confirm({
            title: "Extend this freeze?", body: `It stays in force, now expected to end on ${until}.`,
            label: "Extend", done: "Extended.",
            run: (token) => axios.post(`/api/admin/freezes/${freeze.id}/extend/`,
                                       { expected_end_on: until }, reauthHeaders(token)),
          })}>Save</button>
        </div>
      )}
      {excepting && (
        <div className="col" style={{ gap: "0.5rem", maxWidth: "32rem" }}>
          {manual ? (
            <div className="text-sm">{manual.title}{" "}
              <button type="button" className="link-btn text-xs" onClick={() => setManual(null)}>change</button>
            </div>
          ) : <ManualPicker onPick={setManual} />}
          <div className="field">
            <label className="label" htmlFor={`fz-exc-${freeze.id}`}>Reason</label>
            <input id={`fz-exc-${freeze.id}`} className="input" maxLength={300} value={reason}
                   onChange={(e) => setReason(e.target.value)} />
          </div>
          <div>
            <button className="btn btn-ghost btn-sm" disabled={!manual || !reason.trim()} onClick={() => confirm({
              title: `Let ${manual.title} through?`,
              body: "Its proposals can be started, sent, submitted and made effective while the freeze stays in force for everything else.",
              label: "Grant exception", done: "Exception granted.",
              run: (token) => axios.post(`/api/admin/freezes/${freeze.id}/exceptions/`,
                                         { manual_id: manual.id, reason }, reauthHeaders(token)),
            })}>Grant</button>
          </div>
        </div>
      )}
    </div>
  );
}

function FreezeForm({ onCancel, onDone, confirm, pending, run, cancel }) {
  const offices = useOffices();
  const [series, setSeries] = useState([]);
  const [form, setForm] = useState({ reason: "", expected_end_on: "", scope: "all" });
  const [picked, setPicked] = useState([]);   // offices or series: {id, name}
  const [error, setError] = useState("");

  useEffect(() => {
    axios.get("/api/org/series/", getAuth()).then((res) => setSeries(res.data.series || [])).catch(() => {});
  }, []);

  const change = (patch) => {
    if (patch.scope) setPicked([]);
    setForm({ ...form, ...patch });
    setError("");
  };
  const pick = (row) => setPicked((list) => list.some((p) => p.id === row.id) ? list : [...list, row]);

  const start = () => confirm({
    title: "Start this freeze?",
    body: `${form.scope === "all" ? "Every office" : `${picked.length} ${form.scope === "offices" ? "office" : "series"}${picked.length === 1 ? "" : form.scope === "offices" ? "s" : ""}`}: new proposals, sending to the Head, submitting and making effective wait until it is lifted. Drafts stay editable. The offices are told.`,
    label: "Start freeze", done: "Freeze started. The offices were told.",
    run: async (token) => {
      try {
        await axios.post("/api/admin/freezes/", {
          ...form,
          ...(form.scope === "offices" ? { office_ids: picked.map((p) => p.id) } : {}),
          ...(form.scope === "series" ? { series_ids: picked.map((p) => p.id) } : {}),
        }, reauthHeaders(token));
        onDone();
      } catch (err) {
        cancel();
        setError(err.response?.data?.error || "That did not work.");
        throw err;
      }
    },
  });

  const ready = form.reason.trim() && form.expected_end_on && (form.scope === "all" || picked.length > 0);

  return (
    <div className="card card-pad col" style={{ gap: "1rem", maxWidth: "46rem" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 className="section-title" style={{ margin: 0 }}>Start a freeze</h2>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}><Icon name="back" />Back</button>
      </div>
      <div className="field">
        <label className="label" htmlFor="fz-reason">Reason</label>
        <input id="fz-reason" className="input" maxLength={300} placeholder="e.g. External audit, ISO 9001 surveillance"
               value={form.reason} onChange={(e) => change({ reason: e.target.value })} />
      </div>
      <div className="row-wrap" style={{ gap: "0.75rem" }}>
        <div className="field" style={{ flex: "0 1 12rem" }}>
          <label className="label" htmlFor="fz-end">Expected end</label>
          <input id="fz-end" className="input" type="date" value={form.expected_end_on}
                 onChange={(e) => change({ expected_end_on: e.target.value })} />
        </div>
        <div className="field" style={{ flex: "0 1 14rem" }}>
          <label className="label" htmlFor="fz-scope">Covers</label>
          <select id="fz-scope" className="select" value={form.scope} onChange={(e) => change({ scope: e.target.value })}>
            {SCOPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </div>
      {form.scope !== "all" && (
        <div className="field">
          {picked.length > 0 && (
            <ul style={{ margin: "0 0 0.5rem", paddingLeft: "1.1rem" }}>
              {picked.map((p) => (
                <li key={p.id} className="text-sm">{p.name}{" "}
                  <button type="button" className="link-btn text-xs"
                          onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}>remove</button>
                </li>
              ))}
            </ul>
          )}
          {form.scope === "offices" ? (
            <OfficePicker offices={offices} below={false} onPick={(o) => pick({ id: o.id, name: o.name })} />
          ) : (
            <div className="col" style={{ gap: "0.1rem" }}>
              {series.map((s) => (
                <button key={s.id} type="button" className="link-btn text-sm" style={{ textAlign: "left" }}
                        onClick={() => pick({ id: s.id, name: `${s.code} — ${s.title}` })}>
                  {s.code} — {s.title}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {error && <div className="alert alert-danger">{error}</div>}
      <div>
        <button className="btn btn-primary" disabled={!ready} onClick={start}>Start freeze</button>
      </div>
      {pending && (
        <ConfirmDestructive title={pending.title} body={pending.body} confirmLabel={pending.label}
                            passwordHint="Asked because this changes what offices can do."
                            onConfirm={run} onCancel={cancel} />
      )}
    </div>
  );
}

// ─── Deadlines ──────────────────────────────────────────────────

function Deadlines() {
  const [status, setStatus] = useState("open");
  const [page, setPage] = useState(1);
  const { data, error, reload: load } = useServerData("/api/admin/deadlines/", { status, page },
                                                      "Could not load deadlines.");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState(null);

  if (openId) return <DeadlineDetail id={openId} onBack={() => { setOpenId(null); load(); }} />;
  if (creating) return <DeadlineForm onDone={() => { setCreating(false); load(); }} />;

  return (
    <div>
      {error && <div className="alert alert-danger">{error}</div>}
      {data && (
        <div className="stat-grid" style={{ marginBottom: "1.25rem" }}>
          {[["open", "open", ""], ["due_soon", "due within the reminder window", "is-warning"],
            ["overdue", "overdue", "is-danger"]].map(([key, label, tone]) => (
            <div key={key} className={`stat-card ${tone}`}>
              <div className="stat-value">{data.summary[key]}</div>
              <div className="stat-label">{label}</div>
            </div>
          ))}
        </div>
      )}
      <div className="row-wrap" style={{ gap: "0.5rem", marginBottom: "0.75rem" }}>
        <select className="select" style={{ width: "auto" }} aria-label="Which deadlines"
                value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="open">Open</option>
          <option value="past">Past, all met</option>
          <option value="inactive">Deactivated</option>
          <option value="all">All</option>
        </select>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>New deadline</button>
      </div>
      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.count === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No deadlines here</p>
          <p className="empty-text">Set one with New deadline.</p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.15rem" }}>
          {data.deadlines.map((d) => (
            <button key={d.id} className="series-row" onClick={() => setOpenId(d.id)}>
              <span className="series-code">{d.title}</span>
              <span className="series-title">{d.type}</span>
              <span className={`status-mark is-${d.urgency === "overdue" ? "returned" : d.urgency === "later" ? "approved" : "pending"}`}>
                {dueText(d)}
              </span>
              <span className="subtle text-xs">{d.unmet}</span>
            </button>
          ))}
        </div>
      )}
      <Pager data={data} page={page} setPage={setPage} />
    </div>
  );
}

function Pager({ data, page, setPage }) {
  if (!data || data.pages <= 1) return null;
  return (
    <div className="row" style={{ gap: "0.75rem", alignItems: "center", marginTop: "1rem" }}>
      <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
      <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
      <button className="btn btn-ghost btn-sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
    </div>
  );
}

/** Offices, searchable, for the target pickers. */
function useOffices() {
  const [offices, setOffices] = useState([]);
  useEffect(() => {
    axios.get("/api/org/offices/", getAuth())
      .then((res) => setOffices([...res.data.offices].sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setOffices([]));
  }, []);
  return offices;
}

function OfficePicker({ offices, onPick, below: allowBelow = true }) {
  const [query, setQuery] = useState("");
  const [below, setBelow] = useState(false);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (q ? offices.filter((o) => o.name.toLowerCase().includes(q)) : offices).slice(0, 30);
  }, [offices, query]);
  return (
    <div className="col" style={{ gap: "0.4rem" }}>
      <input className="input" type="search" placeholder="Search offices" value={query}
             onChange={(e) => setQuery(e.target.value)} aria-label="Search offices" />
      {allowBelow && (
        <label className="row text-sm" style={{ gap: "0.4rem", alignItems: "center" }}>
          <input type="checkbox" checked={below} onChange={(e) => setBelow(e.target.checked)} />
          and everything beneath it
        </label>
      )}
      <div className="col" style={{ gap: "0.1rem", maxHeight: "12rem", overflowY: "auto" }}>
        {shown.map((o) => (
          <button key={o.id} type="button" className="link-btn text-sm" style={{ textAlign: "left" }}
                  onClick={() => onPick(o, below)}>{o.name}</button>
        ))}
      </div>
    </div>
  );
}

function ManualPicker({ onPick }) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  useEffect(() => {
    if (!query.trim()) return undefined;
    const timer = setTimeout(() => {
      axios.get("/api/admin/manual-search/", { ...getAuth(), params: { q: query } })
        .then((res) => setRows(res.data.manuals)).catch(() => setRows([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);
  return (
    <div className="col" style={{ gap: "0.4rem" }}>
      <input className="input" type="search" placeholder="Search manuals by title or series" value={query}
             onChange={(e) => setQuery(e.target.value)} aria-label="Search manuals" />
      <div className="col" style={{ gap: "0.1rem", maxHeight: "12rem", overflowY: "auto" }}>
        {query.trim() && rows.map((m) => (
          <button key={m.id} type="button" className="link-btn text-sm" style={{ textAlign: "left" }}
                  onClick={() => onPick(m)}>
            {m.title}{m.deadline && <> <DeadlineTag tag={m.deadline} /></>}
          </button>
        ))}
      </div>
    </div>
  );
}

function targetLabel(t) {
  if (t.kind === "all") return "All offices";
  if (t.kind === "office") return `${t.name}${t.include_descendants ? ", and everything beneath it" : ""}`;
  if (t.kind === "series") return `Series ${t.name}`;
  return `Manual ${t.name}`;
}

function DeadlineForm({ onDone }) {
  const offices = useOffices();
  const [types, setTypes] = useState([]);
  const [series, setSeries] = useState([]);
  const [form, setForm] = useState({
    title: "", type_id: "", new_type: "", due_on: "", note: "", reminders: DEFAULT_REMINDERS,
  });
  const [targets, setTargets] = useState([]);
  const [adding, setAdding] = useState("office");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    axios.get("/api/deadline-types/", getAuth()).then((res) => setTypes(res.data.types)).catch(() => {});
    axios.get("/api/org/series/", getAuth()).then((res) => setSeries(res.data.series || [])).catch(() => {});
  }, []);

  // Any change makes the preview stale: saving needs a fresh one.
  const change = (patch) => { setForm({ ...form, ...patch }); setPreview(null); };
  const addTarget = (target) => {
    setTargets((list) => list.some((t) => t.key === target.key) ? list : [...list, target]);
    setPreview(null);
  };

  const body = () => ({
    title: form.title,
    ...(form.type_id === "new" ? { new_type: form.new_type } : { type_id: Number(form.type_id) || null }),
    due_on: form.due_on,
    note: form.note,
    reminder_days: form.reminders.split(",").map((d) => Number(d.trim())).filter((d) => d),
    targets: targets.map(({ kind, office_id, include_descendants, series_id, manual_id }) =>
      ({ kind, office_id, include_descendants, series_id, manual_id })),
  });

  const send = async (previewOnly) => {
    setBusy(true);
    setError("");
    try {
      const res = await axios.post("/api/admin/deadlines/", { ...body(), preview: previewOnly }, getAuth());
      if (previewOnly) setPreview(res.data);
      else onDone();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card card-pad col" style={{ gap: "1rem", maxWidth: "46rem" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 className="section-title" style={{ margin: 0 }}>New deadline</h2>
        <button className="btn btn-ghost btn-sm" onClick={onDone}><Icon name="back" />Back</button>
      </div>
      <div className="field">
        <label className="label" htmlFor="dl-title">Title</label>
        <input id="dl-title" className="input" value={form.title} onChange={(e) => change({ title: e.target.value })} />
      </div>
      <div className="row-wrap" style={{ gap: "0.75rem" }}>
        <div className="field" style={{ flex: "1 1 16rem" }}>
          <label className="label" htmlFor="dl-type">Type</label>
          <select id="dl-type" className="select" value={form.type_id}
                  onChange={(e) => change({ type_id: e.target.value })}>
            <option value="" disabled>Choose a type</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.name}{t.confirm_with_qms ? " (confirm with QMS)" : ""}</option>)}
            <option value="new">Add your own…</option>
          </select>
          {form.type_id === "new" && (
            <input className="input" placeholder="Name the new type" value={form.new_type}
                   onChange={(e) => change({ new_type: e.target.value })} style={{ marginTop: "0.4rem" }} />
          )}
        </div>
        <div className="field" style={{ flex: "0 1 12rem" }}>
          <label className="label" htmlFor="dl-due">Due</label>
          <input id="dl-due" className="input" type="date" value={form.due_on}
                 onChange={(e) => change({ due_on: e.target.value })} />
        </div>
      </div>
      <div className="field">
        <span className="label">Who owes it</span>
        {targets.length > 0 && (
          <ul style={{ margin: "0 0 0.5rem", paddingLeft: "1.1rem" }}>
            {targets.map((t) => (
              <li key={t.key} className="text-sm">
                {targetLabel(t)}{" "}
                <button type="button" className="link-btn text-xs"
                        onClick={() => { setTargets(targets.filter((x) => x.key !== t.key)); setPreview(null); }}>
                  remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <select className="select" style={{ width: "auto", marginBottom: "0.5rem" }} aria-label="Add"
                value={adding} onChange={(e) => setAdding(e.target.value)}>
          <option value="office">Add an office</option>
          <option value="series">Add a manual series</option>
          <option value="manual">Add a manual</option>
          <option value="all">Add all offices</option>
        </select>
        {adding === "office" && (
          <OfficePicker offices={offices} onPick={(o, below) => addTarget({
            key: `o${o.id}${below ? "+" : ""}`, kind: "office", office_id: o.id, include_descendants: below, name: o.name,
          })} />
        )}
        {adding === "series" && (
          <div className="col" style={{ gap: "0.1rem" }}>
            {series.map((s) => (
              <button key={s.id} type="button" className="link-btn text-sm" style={{ textAlign: "left" }}
                      onClick={() => addTarget({ key: `s${s.id}`, kind: "series", series_id: s.id, name: s.code })}>
                {s.code} — {s.title}
              </button>
            ))}
          </div>
        )}
        {adding === "manual" && (
          <ManualPicker onPick={(m) => addTarget({ key: `m${m.id}`, kind: "manual", manual_id: m.id, name: m.title })} />
        )}
        {adding === "all" && (
          <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}
                  onClick={() => addTarget({ key: "all", kind: "all" })}>
            Add all offices that concur on a document
          </button>
        )}
      </div>
      <div className="field">
        <label className="label" htmlFor="dl-note">Note to the offices <span className="subtle">(optional)</span></label>
        <textarea id="dl-note" className="textarea" rows={2} value={form.note}
                  onChange={(e) => change({ note: e.target.value })} />
      </div>
      <div className="field">
        <label className="label" htmlFor="dl-rem">Reminders, days before</label>
        <input id="dl-rem" className="input" value={form.reminders} style={{ maxWidth: "14rem" }}
               onChange={(e) => change({ reminders: e.target.value })} />
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      {preview && (
        <div className="alert alert-info">
          <div className="strong">
            This will notify {preview.offices} office{preview.offices === 1 ? "" : "s"}
            {" "}({preview.people} {preview.people === 1 ? "person" : "people"}).
          </div>
          {preview.warnings.map((w) => <div key={w} className="text-sm">{w}</div>)}
        </div>
      )}
      <div className="row" style={{ gap: "0.5rem" }}>
        <button className="btn btn-ghost" disabled={busy} onClick={() => send(true)}>Preview</button>
        <button className="btn btn-primary" disabled={busy || !preview} onClick={() => send(false)}
                title={preview ? "" : "Preview first"}>
          Save and notify
        </button>
      </div>
    </div>
  );
}

function DeadlineDetail({ id, onBack }) {
  const { data, reload: load } = useServerData(`/api/admin/deadlines/${id}/`);
  const [branch, setBranch] = useState(null);
  const [rows, setRows] = useState(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (branch == null) return;
    axios.get(`/api/admin/deadlines/${id}/obligations/`,
      { ...getAuth(), params: { branch, page } }).then((res) => setRows(res.data)).catch(() => {});
  }, [id, branch, page]);

  const deactivate = async () => {
    await axios.patch(`/api/admin/deadlines/${id}/`, { active: false }, getAuth());
    load();
  };

  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack}><Icon name="back" />Deadlines</button>
      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h2 className="page-title">{data.title}</h2>
          <p className="page-subtitle">{data.type} · {dueText(data)} · {data.unmet}</p>
        </div>
        {data.active && <button className="btn btn-ghost btn-sm" onClick={deactivate}>Deactivate</button>}
      </header>
      <p className="subtle text-sm">For: {data.targets.map((t) => targetLabel({
        ...t, name: t.office || t.series || t.manual })).join("; ")}</p>
      {data.active && <PriorityPanel deadlineId={id} onDone={() => { load(); setRows(null); setBranch(null); }} />}
      <h3 className="section-title">By branch</h3>
      <div className="col" style={{ gap: "0.15rem" }}>
        {data.by_branch.map((b) => (
          <div key={b.branch_id}>
            <button className="series-row" onClick={() => { setBranch(branch === b.branch_id ? null : b.branch_id); setPage(1); setRows(null); }}>
              <span className="series-code">{b.branch}</span>
              <span className="series-title">{b.open} not yet met · {b.met} met</span>
            </button>
            {branch === b.branch_id && rows && (
              <div className="col" style={{ gap: "0.1rem", padding: "0.4rem 0 0.6rem 1rem" }}>
                {rows.obligations.map((o) => (
                  <div key={o.id} className="row text-sm" style={{ gap: "0.6rem", alignItems: "baseline" }}>
                    <span>{o.office}</span>
                    <span className="subtle text-xs">{o.manual || "office-wide"}</span>
                    {o.priority && <span className="badge badge-warning">Priority</span>}
                    <span className={`status-mark is-${o.state === "open" ? "pending" : "approved"}`}>{o.state_label}</span>
                    {o.met_by && <span className="subtle text-xs">by {o.met_by.dcr_number || `proposal ${o.met_by.proposal_id}`}</span>}
                  </div>
                ))}
                <Pager data={rows} page={page} setPage={setPage} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Priority manuals for one office under this deadline (spec §6.4):
 *  choose the office, then documents it concurs on. Folded until asked. */
function PriorityPanel({ deadlineId, onDone }) {
  const offices = useOffices();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [office, setOffice] = useState(null);
  const [manuals, setManuals] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? offices.filter((o) => o.name.toLowerCase().includes(q)).slice(0, 20) : [];
  }, [offices, query]);

  const save = async () => {
    setError("");
    try {
      const { data } = await axios.post(`/api/admin/deadlines/${deadlineId}/priority/`,
        { office_id: office.id, manual_ids: manuals.map((m) => m.id) }, getAuth());
      setMessage(`${data.priority} priority manual${data.priority === 1 ? "" : "s"} for ${office.name}.`);
      setOffice(null); setManuals([]); setQuery(""); setOpen(false);
      onDone();
    } catch (err) {
      setError(err.response?.data?.error || "Could not set the priority manuals.");
    }
  };

  if (!open) {
    return (
      <div className="row" style={{ gap: "0.75rem", alignItems: "center" }}>
        <button className="btn btn-ghost btn-sm" onClick={() => { setOpen(true); setMessage(""); }}>
          Add priority manuals for an office
        </button>
        {message && <span className="subtle text-sm">{message}</span>}
      </div>
    );
  }
  return (
    <div className="card card-pad col" style={{ gap: "0.6rem", maxWidth: "36rem" }}>
      <h3 className="card-title" style={{ margin: 0 }}>Priority manuals</h3>
      {!office ? (
        <>
          <input className="input" type="search" placeholder="Search offices" value={query}
                 onChange={(e) => setQuery(e.target.value)} aria-label="Search offices for priority" />
          <div className="col" style={{ gap: "0.1rem", maxHeight: "10rem", overflowY: "auto" }}>
            {shown.map((o) => (
              <button key={o.id} type="button" className="link-btn text-sm" style={{ textAlign: "left" }}
                      onClick={() => setOffice(o)}>{o.name}</button>
            ))}
          </div>
        </>
      ) : (
        <>
          <p className="text-sm" style={{ margin: 0 }}>
            For <strong>{office.name}</strong>{" "}
            <button type="button" className="link-btn text-xs" onClick={() => setOffice(null)}>change</button>
          </p>
          {manuals.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {manuals.map((m) => (
                <li key={m.id} className="text-sm">
                  {m.title}{" "}
                  <button type="button" className="link-btn text-xs"
                          onClick={() => setManuals(manuals.filter((x) => x.id !== m.id))}>remove</button>
                </li>
              ))}
            </ul>
          )}
          <ManualPicker onPick={(m) => setManuals(manuals.some((x) => x.id === m.id) ? manuals : [...manuals, m])} />
        </>
      )}
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="row" style={{ gap: "0.5rem" }}>
        <button className="btn btn-primary btn-sm" disabled={!office || manuals.length === 0} onClick={save}>
          Mark priority and tell the office
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

// ─── Announcements ─────────────────────────────────────────────

function Announcements() {
  const offices = useOffices();
  const [status, setStatus] = useState("live");
  const [page, setPage] = useState(1);
  const { data, error: loadError, reload: load } = useServerData(
    "/api/admin/announcements/", { status, page }, "Could not load announcements.");
  const [form, setForm] = useState(null);
  const [saveError, setError] = useState("");
  const error = saveError || loadError;

  const save = async () => {
    try {
      await axios.post("/api/admin/announcements/", {
        title: form.title, body: form.body, expires_on: form.expires_on || null,
        audience: form.targets.length ? "offices" : "all",
        targets: form.targets.map(({ office_id, include_descendants }) => ({ office_id, include_descendants })),
      }, getAuth());
      setForm(null);
      setError("");
      load();
    } catch (err) {
      setError(err.response?.data?.error || "That did not work.");
    }
  };

  const deactivate = async (id) => {
    await axios.patch(`/api/admin/announcements/${id}/`, { active: false }, getAuth());
    load();
  };

  return (
    <div>
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="row-wrap" style={{ gap: "0.5rem", marginBottom: "0.75rem" }}>
        <select className="select" style={{ width: "auto" }} aria-label="Which announcements"
                value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="live">Live</option>
          <option value="expired">Expired</option>
          <option value="inactive">Deactivated</option>
          <option value="all">All</option>
        </select>
        {!form && (
          <button className="btn btn-primary btn-sm"
                  onClick={() => setForm({ title: "", body: "", expires_on: "", targets: [] })}>
            New announcement
          </button>
        )}
      </div>
      {form && (
        <div className="card card-pad col" style={{ gap: "0.75rem", maxWidth: "46rem", marginBottom: "1rem" }}>
          <input className="input" placeholder="Title" value={form.title}
                 onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <textarea className="textarea" rows={2} placeholder="Short text (optional)" value={form.body}
                    onChange={(e) => setForm({ ...form, body: e.target.value })} />
          <label className="label" htmlFor="an-exp">Expires <span className="subtle">(optional)</span></label>
          <input id="an-exp" className="input" type="date" style={{ maxWidth: "12rem" }} value={form.expires_on}
                 onChange={(e) => setForm({ ...form, expires_on: e.target.value })} />
          <span className="label">Who sees it</span>
          <p className="subtle text-sm" style={{ margin: 0 }}>
            {form.targets.length
              ? form.targets.map((t) => targetLabel({ ...t, kind: "office" })).join("; ")
              : "Everyone. Add offices to narrow it."}
          </p>
          <OfficePicker offices={offices} onPick={(o, below) => setForm({
            ...form, targets: [...form.targets.filter((t) => t.office_id !== o.id),
              { office_id: o.id, include_descendants: below, name: o.name }],
          })} />
          <div className="row" style={{ gap: "0.5rem" }}>
            <button className="btn btn-ghost" onClick={() => setForm(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={!form.title.trim()} onClick={save}>Post</button>
          </div>
        </div>
      )}
      {data && data.count === 0 ? (
        <div className="empty-state"><p className="empty-title">No announcements here</p></div>
      ) : data && (
        <div className="col" style={{ gap: "0.15rem" }}>
          {data.announcements.map((a) => (
            <div key={a.id} className="series-row" style={{ cursor: "default" }}>
              <span className="series-code">{a.title}</span>
              <span className="series-title">
                {a.audience === "all" ? "everyone" : a.targets.map((t) => t.office).join(", ")}
                {a.expires_on ? ` · until ${a.expires_on}` : ""}
              </span>
              <span className="subtle text-xs">{a.dismissals} dismissed</span>
              {a.active && !a.expired && (
                <button className="btn btn-ghost btn-sm" onClick={() => deactivate(a.id)}>Deactivate</button>
              )}
            </div>
          ))}
        </div>
      )}
      <Pager data={data} page={page} setPage={setPage} />
    </div>
  );
}
