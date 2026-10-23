import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import logo from '../assets/QMS.png';

const NOT_LISTED = "not_listed";

/**
 * Offices grouped by their parent branch, narrowed by a search. Hundreds of
 * offices do not fit a flat list; a branch heading tells two similarly
 * named units apart. The chosen office stays visible while filtered out,
 * so a search never silently changes the answer.
 */
function groupOffices(offices, query, selectedId) {
  const needle = query.trim().toLowerCase();
  const groups = new Map();
  for (const o of offices) {
    const matches = !needle
      || o.name.toLowerCase().includes(needle)
      || (o.group || "").toLowerCase().includes(needle)
      || String(o.id) === selectedId;
    if (!matches) continue;
    const key = o.group || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(o);
  }
  // Top-level offices first, then branches alphabetically.
  return [...groups.entries()].sort(([a], [b]) =>
    a === "" ? -1 : b === "" ? 1 : a.localeCompare(b));
}

function BrandPanel() {
  return (
    <div className="auth-brand">
      <div className="auth-brand-inner">
        <img src={logo} alt="DocuRoute" />
        <p className="auth-brand-text">
          <strong>Quality Management System on Administrative Services</strong>
          Controlled Document Management System
        </p>
      </div>
    </div>
  );
}

export default function Signup({ onBackToLogin }) {
  const [formData, setFormData] = useState({
    full_name: "",
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
    requested_office_id: "",
    requested_office_name: "",
    requested_position_kind: "encoder",
  });
  // Active offices, for the application. Best-effort: if the list cannot
  // load, only "Office not listed" remains and the admin assigns the office.
  const [offices, setOffices] = useState([]);
  const [officeQuery, setOfficeQuery] = useState("");

  useEffect(() => {
    axios.get("/api/auth/offices/")
      .then((res) => setOffices(res.data))
      .catch(() => setOffices([]));
  }, []);

  const officeGroups = useMemo(
    () => groupOffices(offices, officeQuery, formData.requested_office_id),
    [offices, officeQuery, formData.requested_office_id],
  );
  const notListed = formData.requested_office_id === NOT_LISTED;
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setError("");

    if (formData.password !== formData.confirmPassword) {
      return setError("Passwords do not match.");
    }
    if (formData.password.length < 8) {
      return setError("Password must be at least 8 characters.");
    }

    setLoading(true);
    try {
      await axios.post("/api/auth/register/", {
        full_name: formData.full_name,
        username: formData.username,
        email: formData.email,
        password: formData.password,
        requested_office_id: notListed ? null : (formData.requested_office_id || null),
        requested_office_name: notListed ? formData.requested_office_name : "",
        requested_position_kind: formData.requested_position_kind,
      });
      setSuccess(true);
    } catch (err) {
      const msg = err.response?.data?.error || "Registration failed.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="auth-page">
        <BrandPanel />
        <div className="auth-panel">
          <div className="auth-card" style={{ textAlign: "center" }}>
            <div className="empty-icon" style={{ margin: "0 auto 1rem" }}>✓</div>
            <h2 className="auth-title">Registration sent</h2>
            <p className="auth-subtitle">
              Your account is pending admin approval. You&apos;ll be able to sign in
              once an administrator approves it.
            </p>
            <button className="btn btn-primary btn-lg btn-block" onClick={onBackToLogin}>
              Back to sign in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <BrandPanel />

      <div className="auth-panel">
        <div className="auth-card">
          <h2 className="auth-title">Create account</h2>
          <p className="auth-subtitle">Fill in your details to request access</p>

          {/* Names are personal data under RA 10173, which the university's
              own manuals cite. Stated once, here, where it is collected —
              not repeated on every screen afterwards. */}
          <p className="subtle text-xs" style={{ marginBottom: "1.1rem" }}>
            Your name, office and email are used to route document change
            requests and to record who acted on them. The full list of people
            is visible only to the system administrator. Accounts of people
            who leave are deactivated, not deleted, so the record of past
            requests stays correct.
          </p>

          <form onSubmit={handleSignup} className="auth-form">
            <div className="field">
              <label className="label" htmlFor="su-fullname">Full name</label>
              <input
                id="su-fullname"
                className="input"
                type="text"
                name="full_name"
                value={formData.full_name}
                onChange={handleChange}
                placeholder="As you would sign it"
                autoComplete="name"
                required
              />
              <p className="subtle text-xs" style={{ margin: 0 }}>
                The system administrator needs it to know who is asking for
                access. Documents print position titles, never names.
              </p>
            </div>

            <div className="field">
              <label className="label" htmlFor="su-office">Your office</label>
              {offices.length > 0 && (
                <input
                  className="input"
                  type="search"
                  value={officeQuery}
                  onChange={(e) => setOfficeQuery(e.target.value)}
                  placeholder="Search offices"
                  aria-label="Search offices"
                  aria-controls="su-office"
                />
              )}
              <select
                id="su-office"
                className="select"
                name="requested_office_id"
                value={formData.requested_office_id}
                onChange={handleChange}
                required
              >
                <option value="" disabled>
                  {officeGroups.length ? "Choose your office" : "No office matches"}
                </option>
                {officeGroups.map(([group, list]) => (
                  <optgroup key={group || "top"} label={group || "Top level"}>
                    {list.map((o) => (
                      <option key={o.id} value={o.id}>{o.name}</option>
                    ))}
                  </optgroup>
                ))}
                <option value={NOT_LISTED}>Office not listed</option>
              </select>
              <p className="subtle text-xs" style={{ margin: 0 }}>
                Approval places you in this office. If yours is missing,
                choose Office not listed.
              </p>
            </div>

            {notListed && (
              <div className="field">
                <label className="label" htmlFor="su-office-name">
                  Office name <span className="subtle">(optional)</span>
                </label>
                <input
                  id="su-office-name"
                  className="input"
                  type="text"
                  name="requested_office_name"
                  value={formData.requested_office_name}
                  onChange={handleChange}
                  maxLength={60}
                />
              </div>
            )}
            <div className="field">
              <label className="label" htmlFor="su-position">Your position</label>
              <select id="su-position" className="select" name="requested_position_kind"
                value={formData.requested_position_kind} onChange={handleChange}>
                <option value="encoder">Encoder</option>
                <option value="head">Head</option>
              </select>
              <p className="subtle text-xs" style={{ margin: 0 }}>
                An office can have only one Head. Your administrator confirms your application.
              </p>
            </div>

            <div className="field">
              <label className="label" htmlFor="su-username">Username</label>
              <input
                id="su-username"
                className="input"
                type="text"
                name="username"
                value={formData.username}
                onChange={handleChange}
                placeholder="Choose a username"
                autoComplete="username"
                required
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="su-email">Email</label>
              <input
                id="su-email"
                className="input"
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="you@example.com"
                autoComplete="email"
                required
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="su-password">Password</label>
              <input
                id="su-password"
                className="input"
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="At least 8 characters"
                autoComplete="new-password"
                required
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="su-confirm">Confirm password</label>
              <input
                id="su-confirm"
                className="input"
                type="password"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleChange}
                placeholder="Repeat your password"
                autoComplete="new-password"
                required
              />
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            <button className="btn btn-primary btn-lg btn-block" type="submit" disabled={loading}>
              {loading ? <><span className="spinner spinner-light" /> Creating account…</> : "Create account"}
            </button>
          </form>

          <p className="auth-foot">
            Already have an account?{" "}
            <button type="button" className="link-btn" onClick={onBackToLogin}>
              Sign in
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
