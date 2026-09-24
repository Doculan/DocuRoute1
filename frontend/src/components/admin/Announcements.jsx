import { useCallback, useEffect, useState } from "react";
import axios from "axios";

// Relative, so the browser sends it to whichever host served the page and
// Vite's proxy forwards it. See StaffManuals for the full reasoning.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const EMPTY = {
  title: "", body: "", date: "", office_id: "", active: true,
};

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * Announcement management.
 *
 * One model, two presentations: a dated item goes under Upcoming on the
 * staff dashboard, an undated one is the banner. That distinction is
 * invisible in a form with an optional date field, so the form says which
 * it will be as you type — otherwise the only way to find out is to post it
 * and go and look.
 */
export default function Announcements() {
  const [rows, setRows] = useState([]);
  const [offices, setOffices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, org] = await Promise.all([
        axios.get(`${BASE_URL}/api/admin/announcements/`, getAuth()),
        axios.get(`${BASE_URL}/api/org/offices/`, getAuth()),
      ]);
      setRows(list.data);
      setOffices(org.data.offices || []);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load announcements.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const startEdit = (row) => {
    setEditingId(row.id);
    setForm({
      title: row.title,
      body: row.body || "",
      date: row.date || "",
      office_id: row.office_id || "",
      active: row.active,
    });
    setMessage("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(EMPTY);
  };

  const save = async (event) => {
    event.preventDefault();
    if (!form.title.trim()) {
      setError("Give the announcement a title.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editingId) {
        await axios.patch(
          `${BASE_URL}/api/admin/announcements/${editingId}/`, form, getAuth()
        );
        setMessage("Announcement updated.");
      } else {
        await axios.post(
          `${BASE_URL}/api/admin/announcements/`, form, getAuth()
        );
        setMessage("Announcement posted.");
      }
      cancelEdit();
      load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not save that.");
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (row) => {
    try {
      await axios.patch(
        `${BASE_URL}/api/admin/announcements/${row.id}/`,
        { active: !row.active }, getAuth()
      );
      load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not change that.");
    }
  };

  const remove = async (row) => {
    try {
      await axios.delete(
        `${BASE_URL}/api/admin/announcements/${row.id}/`, getAuth()
      );
      setConfirmDelete(null);
      setMessage(`Deleted "${row.title}".`);
      load();
    } catch (err) {
      setError(err.response?.data?.error || "Could not delete that.");
    }
  };

  // The whole point of the form: say which of the two things this will be,
  // now, rather than after it is posted.
  const willBe = form.date
    ? {
        label: "Dated — this shows under Upcoming",
        detail: "It appears in the Upcoming list until the day passes, then drops off.",
        tone: "badge-info",
      }
    : {
        label: "No date — this shows as a banner",
        detail: "It sits across the top of the staff dashboard until each person dismisses it.",
        tone: "badge-warning",
      };

  const audience = form.office_id
    ? offices.find((o) => String(o.id) === String(form.office_id))?.name
    : null;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Announcements</h1>
          <p className="page-subtitle">
            Notices for the staff dashboard. A dated notice goes under
            Upcoming; an undated one is the banner.
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>↻ Refresh</button>
      </header>

      {error && <div className="alert alert-danger" style={{ marginBottom: "1rem" }}>{error}</div>}
      {message && <div className="alert alert-success" style={{ marginBottom: "1rem" }}>{message}</div>}

      <form onSubmit={save} className="card card-pad" style={{ marginBottom: "2rem" }}>
        <h2 className="section-title" style={{ marginTop: 0 }}>
          {editingId ? "Edit announcement" : "Post an announcement"}
        </h2>

        <div className="field">
          <label className="label" htmlFor="ann-title">
            Title <span style={{ color: "var(--danger)" }}>*</span>
          </label>
          <input
            id="ann-title"
            className="input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Internal quality audit, week of 6 October"
            required
          />
        </div>

        <div className="field">
          <label className="label" htmlFor="ann-body">Body</label>
          <textarea
            id="ann-body"
            className="textarea"
            style={{ minHeight: "70px" }}
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            placeholder="One line of detail. Optional."
          />
        </div>

        <div className="row-wrap" style={{ gap: "1rem" }}>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label className="label" htmlFor="ann-date">Date</label>
            <input
              id="ann-date"
              className="input"
              type="date"
              value={form.date || ""}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
            />
            <span className="subtle text-xs">Leave empty to post a banner.</span>
          </div>

          <div className="field" style={{ flex: "1 1 200px" }}>
            <label className="label" htmlFor="ann-office">Who sees it</label>
            <select
              id="ann-office"
              className="select"
              value={form.office_id || ""}
              onChange={(e) => setForm({ ...form, office_id: e.target.value })}
            >
              <option value="">Everyone</option>
              {offices.map((o) => (
                <option key={o.id} value={o.id}>{o.name} only</option>
              ))}
            </select>
          </div>
        </div>

        {/* Live, because the date field silently decides which of two very
            different things this is. */}
        <div className="alert" style={{ marginTop: "0.5rem" }}>
          <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
            <span className={`badge ${willBe.tone}`}>{willBe.label}</span>
            <span className="text-xs" style={{ color: "var(--n-700)" }}>
              {willBe.detail}
            </span>
          </div>
          <p className="text-xs" style={{ margin: "0.4rem 0 0", color: "var(--n-700)" }}>
            {audience ? `Visible to people holding a position in ${audience}.` : "Visible to everyone."}
          </p>
        </div>

        <label className="row" style={{ gap: "0.5rem", alignItems: "center", marginTop: "0.9rem" }}>
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          <span className="text-sm">Active — staff can see it</span>
        </label>

        <div className="row-wrap" style={{ gap: "0.5rem", marginTop: "1rem" }}>
          <button className="btn btn-deep" type="submit" disabled={saving}>
            {saving
              ? <><span className="spinner spinner-light" /> Saving…</>
              : editingId ? "Save changes" : "Post announcement"}
          </button>
          {editingId && (
            <button className="btn btn-ghost" type="button" onClick={cancelEdit}>
              Cancel
            </button>
          )}
        </div>
      </form>

      <h2 className="section-title">Posted</h2>

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing posted yet</p>
          <p className="empty-text">
            Anything you post here appears on the staff dashboard — as a
            banner, or under Upcoming if you give it a date.
          </p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.6rem" }}>
          {rows.map((row) => (
            <article
              key={row.id}
              className="card card-pad"
              style={{ opacity: row.active ? 1 : 0.62 }}
            >
              <div className="row" style={{ justifyContent: "space-between", gap: "1rem", alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="row-wrap" style={{ gap: "0.4rem", alignItems: "center", marginBottom: "0.3rem" }}>
                    <span className={`badge ${row.shows_as === "upcoming" ? "badge-info" : "badge-warning"}`}>
                      {row.shows_as === "upcoming" ? "Upcoming" : "Banner"}
                    </span>
                    {row.shows_as === "upcoming" && (
                      <span className="subtle text-xs">{formatDate(row.date)}</span>
                    )}
                    <span className="badge badge-neutral">
                      {row.office || "Everyone"}
                    </span>
                    {!row.active && <span className="badge badge-neutral">inactive</span>}
                  </div>

                  <div className="doc-name">{row.title}</div>
                  {row.body && <p className="doc-excerpt">{row.body}</p>}

                  <p className="subtle text-xs" style={{ marginTop: "0.4rem" }}>
                    Visible to {row.reach} staff
                    {row.office ? ` in ${row.office}` : ""}
                    {row.shows_as === "banner" && row.dismissals > 0
                      ? ` · ${row.dismissals} dismissed it`
                      : ""}
                    {row.created_by ? ` · posted by ${row.created_by}` : ""}
                  </p>
                </div>

                <div className="row-wrap" style={{ gap: "0.4rem", flexShrink: 0 }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => startEdit(row)}>
                    Edit
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => toggleActive(row)}>
                    {row.active ? "Deactivate" : "Reactivate"}
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ color: "var(--danger)" }}
                    onClick={() => setConfirmDelete(row.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Deactivating is the usual move and is one click; deleting
                  throws away the record of what was posted, so it asks. */}
              {confirmDelete === row.id && (
                <div className="alert alert-danger" style={{ marginTop: "0.75rem" }}>
                  <p className="text-sm" style={{ margin: "0 0 0.6rem" }}>
                    Delete &ldquo;{row.title}&rdquo; permanently? Deactivating
                    hides it from staff and keeps the record.
                  </p>
                  <div className="row-wrap" style={{ gap: "0.5rem" }}>
                    <button className="btn btn-sm" style={{ background: "var(--danger)", color: "#fff" }}
                            onClick={() => remove(row)}>
                      Delete it
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setConfirmDelete(null)}>
                      Keep it
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => { setConfirmDelete(null); toggleActive(row); }}>
                      Deactivate instead
                    </button>
                  </div>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
