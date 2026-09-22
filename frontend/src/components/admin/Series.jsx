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

/**
 * Manual series, the documents in them, and who relates to each.
 *
 * Everything the process later does — who is asked to concur, who signs,
 * who is notified — is decided by what is entered here. So the screen's
 * job is less data entry than making the consequences legible: what a
 * document inherits, what it overrides, and what a change here will not
 * reach.
 */
export default function Series() {
  const [rows, setRows] = useState([]);
  const [unassigned, setUnassigned] = useState(0);
  const [open, setOpen] = useState(null);        // series id being viewed
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${BASE_URL}/api/org/series/`, getAuth());
      setRows(data.series);
      setUnassigned(data.unassigned_documents);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load the series.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const say = (text) => {
    setMessage(text);
    setTimeout(() => setMessage(""), 4500);
  };

  const create = async (form) => {
    try {
      await axios.post(`${BASE_URL}/api/org/series/`, form, getAuth());
      setCreating(false);
      say(`Added ${form.code}.`);
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not add the series.");
    }
  };

  if (loading) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  if (open != null) {
    return (
      <SeriesDetail
        seriesId={open}
        onBack={() => { setOpen(null); load(); }}
        onSay={say}
      />
    );
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Manual series</h1>
          <p className="page-subtitle">
            A series owns its documents&apos; offices and approval route;
            a document may override either.
          </p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
          + Add series
        </button>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="toast">{message}</div>}

      {unassigned > 0 && (
        <div className="alert alert-warning" style={{ marginBottom: "1.25rem" }}>
          <strong>{unassigned}</strong> document{unassigned === 1 ? " is" : "s are"}{" "}
          not in a series yet, so nobody can propose changes to{" "}
          {unassigned === 1 ? "it" : "them"}.{" "}
          <UnassignedList onSay={say} onChanged={load} series={rows} />
        </div>
      )}

      {rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No series yet</p>
          <p className="empty-text">
            A series is a manual — “Finance and Administration Manual” — and
            its documents are the numbered procedures inside it.
          </p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.15rem" }}>
          {rows.map((s) => (
            <button key={s.id} className="series-row" onClick={() => setOpen(s.id)}>
              <span className="series-code">{s.code}</span>
              <span className="series-title">{s.title}</span>
              <span className="subtle text-xs">
                {s.document_count} document{s.document_count === 1 ? "" : "s"}
              </span>
              <span className="subtle text-xs">
                {s.owning_office
                  ? `owned by ${s.owning_office.abbreviation || s.owning_office.name}`
                  : "no owner yet"}
              </span>
              {s.concurring.length === 0 && (
                <span className="badge badge-warning">no concurring office</span>
              )}
              {s.overriding_documents.length > 0 && (
                <span className="badge badge-neutral">
                  {s.overriding_documents.length} overriding
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {creating && (
        <SeriesForm onSave={create} onCancel={() => setCreating(false)} />
      )}
    </div>
  );
}

/** The documents nobody has placed yet, and a one-step way to place them. */
function UnassignedList({ series, onSay, onChanged }) {
  const [shown, setShown] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [pending, setPending] = useState(null);

  const open = async () => {
    const { data } = await axios.get(
      `${BASE_URL}/api/org/documents/?unassigned=true`, getAuth()
    );
    setDocuments(data.documents);
    setShown(true);
  };

  const assign = async (token) => {
    const { document, seriesId } = pending;
    setPending(null);
    try {
      await axios.patch(
        `${BASE_URL}/api/org/documents/${document.id}/`,
        { series_id: seriesId },
        confirmedAuth(token)
      );
      onSay(`${document.title} placed.`);
      await open();
      onChanged();
    } catch (err) {
      onSay(err.response?.data?.error || "Could not place the document.");
    }
  };

  if (!shown) {
    return <button className="link-btn" onClick={open}>Show them</button>;
  }

  return (
    <div className="col" style={{ gap: "0.4rem", marginTop: "0.7rem" }}>
      {documents.map((d) => (
        <div key={d.id} className="row" style={{ gap: "0.6rem", alignItems: "center" }}>
          <span className="doc-ref">{d.title}</span>
          <span className="subtle text-xs">{d.section_count} sections</span>
          <select
            className="select"
            style={{ maxWidth: "16rem" }}
            defaultValue=""
            onChange={(e) => {
              if (!e.target.value) return;
              setPending({ document: d, seriesId: Number(e.target.value) });
              e.target.value = "";
            }}
          >
            <option value="">Place in a series…</option>
            {series.map((s) => (
              <option key={s.id} value={s.id}>{s.code} — {s.title}</option>
            ))}
          </select>
        </div>
      ))}
      {documents.length === 0 && (
        <span className="subtle text-sm">All documents are placed.</span>
      )}

      {pending && (
        <ConfirmDestructive
          title={`Place ${pending.document.title}?`}
          body={
            "It takes the series' owner, concurring offices and approval "
            + "route. Any of those can be overridden on the document "
            + "afterwards."
          }
          confirmLabel="Place document"
          onConfirm={assign}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

function SeriesDetail({ seriesId, onBack, onSay }) {
  const [data, setData] = useState(null);
  const [offices, setOffices] = useState([]);
  const [error, setError] = useState("");
  const [editingLinks, setEditingLinks] = useState(false);
  const [draftLinks, setDraftLinks] = useState([]);
  const [pendingLinks, setPendingLinks] = useState(null);
  const [pendingOwner, setPendingOwner] = useState(null);
  const [openDocument, setOpenDocument] = useState(null);

  const load = useCallback(async () => {
    const [detail, tree] = await Promise.all([
      axios.get(`${BASE_URL}/api/org/series/${seriesId}/`, getAuth()),
      axios.get(`${BASE_URL}/api/org/offices/`, getAuth()),
    ]);
    setData(detail.data);
    setOffices(tree.data.offices);
  }, [seriesId]);

  useEffect(() => { load(); }, [load]);

  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  if (openDocument) {
    return (
      <DocumentDetail
        documentId={openDocument}
        offices={offices}
        onBack={() => { setOpenDocument(null); load(); }}
        onSay={onSay}
      />
    );
  }

  const startEditingLinks = () => {
    setDraftLinks([
      ...data.concurring.map((o) => ({ office_id: o.id, relationship: "concurring" })),
      ...data.readers.map((o) => ({ office_id: o.id, relationship: "reader" })),
    ]);
    setEditingLinks(true);
  };

  const saveLinks = async (token) => {
    const rows = pendingLinks;
    setPendingLinks(null);
    try {
      const { data: updated } = await axios.put(
        `${BASE_URL}/api/org/series/${seriesId}/offices/`,
        { offices: rows },
        confirmedAuth(token)
      );
      setEditingLinks(false);
      const missed = updated.did_not_reach || [];
      onSay(
        missed.length === 0
          ? "Offices updated."
          : `Offices updated. ${missed.length} document${missed.length === 1 ? "" : "s"} `
            + `(${missed.map((d) => d.title).join(", ")}) override these and did not change.`
      );
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not save the offices.");
    }
  };

  const saveOwner = async (token) => {
    const officeId = pendingOwner;
    setPendingOwner(null);
    try {
      await axios.patch(
        `${BASE_URL}/api/org/series/${seriesId}/`,
        { owning_office_id: officeId },
        confirmedAuth(token)
      );
      onSay("Owner updated.");
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not set the owner.");
    }
  };

  const approving = offices.filter((o) => o.is_approving_level);

  return (
    <div>
      <button className="link-btn" onClick={onBack}>← All series</button>

      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h1 className="page-title">{data.code}</h1>
          <p className="page-subtitle">{data.title}</p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="dash-grid">
        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <section>
            <h2 className="section-title">Offices</h2>
            {editingLinks ? (
              <LinkEditor
                offices={offices.filter((o) => !o.is_approving_level)}
                value={draftLinks}
                onChange={setDraftLinks}
                onSave={() => setPendingLinks(draftLinks)}
                onCancel={() => setEditingLinks(false)}
              />
            ) : (
              <>
                <LinkList label="Concurring" offices={data.concurring}
                          empty="Nobody can propose changes to these documents yet." />
                <LinkList label="Readers" offices={data.readers}
                          empty="No reader offices." />
                <button className="btn btn-ghost btn-sm" onClick={startEditingLinks}>
                  Change offices
                </button>
                {data.overriding_documents.length > 0 && (
                  <p className="subtle text-xs" style={{ marginTop: "0.6rem" }}>
                    {data.overriding_documents.length} document
                    {data.overriding_documents.length === 1 ? "" : "s"} set their own
                    offices and will not follow a change here:{" "}
                    {data.overriding_documents.map((d) => d.title).join(", ")}.
                  </p>
                )}
              </>
            )}
          </section>

          <section>
            <h2 className="section-title">Documents</h2>
            {data.documents.length === 0 ? (
              <p className="subtle text-sm" style={{ margin: 0 }}>
                No documents in this series yet.
              </p>
            ) : (
              <div className="col" style={{ gap: "0.15rem" }}>
                {data.documents.map((d) => (
                  <button key={d.id} className="series-row"
                          onClick={() => setOpenDocument(d.id)}>
                    <span className="doc-ref">{d.title}</span>
                    <span className="subtle text-xs">{d.section_count} sections</span>
                    {d.offices_overridden && (
                      <span className="badge badge-neutral">own offices</span>
                    )}
                    {!d.owner_is_inherited && d.effective_owner && (
                      <span className="badge badge-neutral">own owner</span>
                    )}
                    {!d.can_be_proposed_against && (
                      <span className="badge badge-warning">nobody can propose</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="col" style={{ gap: "1.75rem", minWidth: 0 }}>
          <section>
            <h2 className="section-title">Owner and approval</h2>
            <div className="field">
              <label className="label" htmlFor="series-owner">Owning office</label>
              <select
                id="series-owner"
                className="select"
                value={data.owning_office?.id ?? ""}
                onChange={(e) => setPendingOwner(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— none yet —</option>
                {approving.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
              <p className="subtle text-xs" style={{ margin: 0 }}>
                Approving-level offices only. The owner signs; it does not
                propose or concur.
              </p>
            </div>

            <div style={{ marginTop: "1rem" }}>
              <h3 className="label">Approval route</h3>
              {data.approval_route.length === 0 ? (
                <p className="subtle text-sm" style={{ margin: 0 }}>
                  No owner, so no route yet.
                </p>
              ) : (
                <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
                  {data.approval_route.map((o) => o.abbreviation || o.name).join(" → ")}
                </p>
              )}
            </div>
          </section>
        </div>
      </div>

      {pendingLinks && (
        <ConfirmDestructive
          title="Change which offices relate to this series?"
          body={
            "This decides who must agree to future changes, and every "
            + "document that inherits picks it up at once. Documents with "
            + "their own offices are unaffected."
          }
          confirmLabel="Save offices"
          onConfirm={saveLinks}
          onCancel={() => setPendingLinks(null)}
        />
      )}

      {pendingOwner !== null && (
        <ConfirmDestructive
          title="Change the owning office?"
          body="The owner signs these documents, and the approval route is derived from where it sits in the hierarchy."
          confirmLabel="Set owner"
          onConfirm={saveOwner}
          onCancel={() => setPendingOwner(null)}
        />
      )}
    </div>
  );
}

function DocumentDetail({ documentId, offices, onBack, onSay }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState(null);
  const [pending, setPending] = useState(null);   // "links" | "inherit"

  const load = useCallback(async () => {
    const { data: detail } = await axios.get(
      `${BASE_URL}/api/org/documents/${documentId}/`, getAuth()
    );
    setData(detail);
  }, [documentId]);

  useEffect(() => { load(); }, [load]);

  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const startOverride = () => {
    setDraft([
      ...data.concurring.map((o) => ({ office_id: o.id, relationship: "concurring" })),
      ...data.readers.map((o) => ({ office_id: o.id, relationship: "reader" })),
    ]);
  };

  const save = async (token) => {
    const body = pending === "inherit" ? { inherit: true } : { offices: draft };
    const wasInherit = pending === "inherit";
    setPending(null);
    try {
      await axios.put(
        `${BASE_URL}/api/org/documents/${documentId}/offices/`,
        body, confirmedAuth(token)
      );
      setDraft(null);
      onSay(wasInherit
        ? "This document follows its series again."
        : "This document now sets its own offices.");
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not save.");
    }
  };

  return (
    <div>
      <button className="link-btn" onClick={onBack}>← Back to the series</button>

      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h1 className="page-title">{data.title}</h1>
          <p className="page-subtitle">
            {data.series_code
              ? `In series ${data.series_code} · ${data.section_count} sections`
              : `Not in a series · ${data.section_count} sections`}
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      {!data.can_be_proposed_against && (
        <div className="alert alert-warning">
          No concurring office, so nobody can propose a change to this
          document yet.
        </div>
      )}

      <section style={{ marginTop: "1.25rem" }}>
        <h2 className="section-title">
          Offices{" "}
          <span className="subtle text-xs">
            {data.offices_overridden ? "— set on this document" : "— inherited from the series"}
          </span>
        </h2>

        {draft ? (
          <LinkEditor
            offices={offices.filter((o) => !o.is_approving_level)}
            value={draft}
            onChange={setDraft}
            onSave={() => setPending("links")}
            onCancel={() => setDraft(null)}
          />
        ) : (
          <>
            <LinkList label="Concurring" offices={data.concurring}
                      empty="None." />
            <LinkList label="Readers" offices={data.readers} empty="None." />
            <div className="row-wrap" style={{ gap: "0.5rem" }}>
              <button className="btn btn-ghost btn-sm" onClick={startOverride}>
                {data.offices_overridden ? "Change these offices" : "Set offices for this document only"}
              </button>
              {data.offices_overridden && (
                <button className="btn btn-ghost btn-sm" onClick={() => setPending("inherit")}>
                  Follow the series again
                </button>
              )}
            </div>
            {!data.offices_overridden && (
              <p className="subtle text-xs" style={{ marginTop: "0.5rem" }}>
                Setting them here replaces the series&apos; offices for this
                document — it does not add to them — and later changes to the
                series will not reach it.
              </p>
            )}
          </>
        )}
      </section>

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">
          Approval{" "}
          <span className="subtle text-xs">
            {data.owner_is_inherited ? "— owner inherited" : "— owner set here"}
          </span>
        </h2>
        <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
          {data.approval_route.length === 0
            ? "No owner, so no route yet."
            : data.approval_route.map((o) => o.abbreviation || o.name).join(" → ")}
        </p>
      </section>

      {pending && (
        <ConfirmDestructive
          title={pending === "inherit"
            ? "Follow the series again?"
            : "Set this document's own offices?"}
          body={pending === "inherit"
            ? "The offices set here are removed and the series' offices apply again."
            : "These replace the series' offices for this document. Later changes to the series will not reach it."}
          confirmLabel={pending === "inherit" ? "Follow the series" : "Save offices"}
          onConfirm={save}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

function LinkList({ label, offices, empty }) {
  return (
    <div style={{ marginBottom: "0.9rem" }}>
      <div className="label">{label}</div>
      {offices.length === 0 ? (
        <p className="subtle text-sm" style={{ margin: 0 }}>{empty}</p>
      ) : (
        <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
          {offices.map((o) => o.name).join(", ")}
        </p>
      )}
    </div>
  );
}

/** Editing a set, so the whole set is on screen at once: every office with
 *  its relationship, or none. A row-at-a-time editor would let the screen
 *  and the database describe different sets between clicks. */
function LinkEditor({ offices, value, onChange, onSave, onCancel }) {
  const current = new Map(value.map((v) => [v.office_id, v.relationship]));

  const set = (officeId, relationship) => {
    const next = value.filter((v) => v.office_id !== officeId);
    if (relationship) next.push({ office_id: officeId, relationship });
    onChange(next);
  };

  return (
    <div className="card card-pad col" style={{ gap: "0.5rem" }}>
      {offices.map((o) => (
        <div key={o.id} className="row" style={{ gap: "0.75rem", alignItems: "center" }}>
          <span style={{ minWidth: "14rem" }}>{o.name}</span>
          <select
            className="select"
            style={{ maxWidth: "12rem" }}
            value={current.get(o.id) || ""}
            onChange={(e) => set(o.id, e.target.value || null)}
          >
            <option value="">not related</option>
            <option value="concurring">concurring</option>
            <option value="reader">reader</option>
          </select>
        </div>
      ))}
      <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "0.4rem" }}>
        <button className="btn btn-primary btn-sm" onClick={onSave}>Save offices</button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function SeriesForm({ onSave, onCancel }) {
  const [form, setForm] = useState({ code: "", title: "" });

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal" style={{ maxWidth: "460px" }}>
        <form onSubmit={(e) => { e.preventDefault(); onSave(form); }}>
          <div className="modal-head">
            <h3 className="modal-title">Add manual series</h3>
          </div>
          <div className="modal-body col" style={{ gap: "1rem" }}>
            <div className="field">
              <label className="label" htmlFor="series-code">Code</label>
              <input
                id="series-code"
                className="input"
                autoFocus
                placeholder="FAM"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                required
              />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                The prefix its documents carry — FAM 6.02, FAM 8.01.
              </p>
            </div>
            <div className="field">
              <label className="label" htmlFor="series-title">Manual title</label>
              <input
                id="series-title"
                className="input"
                placeholder="Finance and Administration Manual"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
              />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                As it appears in the document header, under MANUAL TITLE.
              </p>
            </div>
            <p className="subtle text-xs" style={{ margin: 0 }}>
              The owner and offices are set next, on the series itself.
            </p>
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn btn-primary"
                    disabled={!form.code.trim() || !form.title.trim()}>
              Add series
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
