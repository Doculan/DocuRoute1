import { useEffect, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function when(value) {
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * My account: the few things a person may change about themselves.
 *
 * Name and email are edited in place. The password form stays closed
 * until asked for. Username, offices and positions are shown but not
 * editable: the username is the login, and posts are assigned by the
 * system admin.
 *
 * Shared by all three portals; `onNameChange` lets the sidebar follow.
 */
export default function Account({ onNameChange }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    axios.get("/api/auth/profile/", getAuth())
      .then((res) => setProfile(res.data))
      .catch(() => setError("Could not load your account."));
  }, []);

  if (error && !profile) return <div className="alert alert-danger">{error}</div>;
  if (!profile) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  return (
    <div className="account">
      <header className="page-head">
        <div>
          <h1 className="page-title">My account</h1>
          <p className="page-subtitle">
            Signed in as <strong>{profile.username}</strong> ·{" "}
            {profile.system_role_label}
          </p>
        </div>
      </header>

      <Details
        profile={profile}
        onSaved={(next) => {
          setProfile(next);
          onNameChange?.(next.full_name || next.username);
        }}
      />
      <Password />
      <Positions positions={profile.positions} />
    </div>
  );
}

function Details({ profile, onSaved }) {
  const [name, setName] = useState(profile.full_name);
  const [email, setEmail] = useState(profile.email);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const dirty = name !== profile.full_name || email !== profile.email;

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const { data } = await axios.patch(
        "/api/auth/profile/", { full_name: name, email }, getAuth()
      );
      setName(data.full_name);
      setEmail(data.email);
      onSaved(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err.response?.data?.error || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="card card-pad account-card" onSubmit={save}>
      <h2 className="account-heading">Your details</h2>
      <div className="form-row">
        <label className="field">
          <span className="label">Full name</span>
          <input className="input" value={name} maxLength={255}
                 autoComplete="name"
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span className="label">Email <span className="muted">(optional)</span></span>
          <input className="input" type="email" value={email} maxLength={254}
                 autoComplete="email"
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
      </div>
      <p className="account-hint">
        Shown to the offices you work with. Forms print position titles, never names.
      </p>
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="account-actions">
        <button className="btn btn-primary" type="submit" disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && <span className="account-ok">Saved</span>}
      </div>
    </form>
  );
}

function Password() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const reset = () => {
    setCurrent(""); setNext(""); setAgain(""); setError("");
  };

  const submit = async (e) => {
    e.preventDefault();
    if (next !== again) {
      setError("The new passwords do not match.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await axios.post("/api/auth/password/", {
        current_password: current, new_password: next,
      }, getAuth());
      reset();
      setOpen(false);
      setDone(true);
    } catch (err) {
      setError(err.response?.data?.error || "Could not change the password.");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <div className="card card-pad account-card account-row">
        <div>
          <h2 className="account-heading">Password</h2>
          {done && <span className="account-ok">Password changed.</span>}
        </div>
        <button className="btn btn-ghost" type="button"
                onClick={() => { setOpen(true); setDone(false); }}>
          Change password
        </button>
      </div>
    );
  }

  return (
    <form className="card card-pad account-card" onSubmit={submit}>
      <h2 className="account-heading">Change password</h2>
      <label className="field">
        <span className="label">Current password</span>
        <input className="input" type="password" value={current} required
               autoComplete="current-password"
               onChange={(e) => setCurrent(e.target.value)} />
      </label>
      <div className="form-row">
        <label className="field">
          <span className="label">New password</span>
          <input className="input" type="password" value={next} required
                 autoComplete="new-password"
                 onChange={(e) => setNext(e.target.value)} />
        </label>
        <label className="field">
          <span className="label">New password again</span>
          <input className="input" type="password" value={again} required
                 autoComplete="new-password"
                 onChange={(e) => setAgain(e.target.value)} />
        </label>
      </div>
      <p className="account-hint">At least 8 characters, not all numbers.</p>
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="account-actions">
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Changing…" : "Change password"}
        </button>
        <button className="btn btn-ghost" type="button"
                onClick={() => { reset(); setOpen(false); }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function Positions({ positions }) {
  return (
    <div className="card card-pad account-card">
      <h2 className="account-heading">Positions</h2>
      {positions.length === 0 ? (
        <p className="account-hint">None yet.</p>
      ) : (
        <ul className="account-positions">
          {positions.map((p) => (
            <li key={p.title}>
              <span>{p.title}{p.is_acting && <span className="muted"> · acting</span>}</span>
              <span className="muted">since {when(p.since)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="account-hint">Assigned by the system admin.</p>
    </div>
  );
}
