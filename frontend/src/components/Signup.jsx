import { useState } from "react";
import axios from "axios";
import logo from '../assets/QMS.png';

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
  });
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
            <button className="btn btn-deep btn-lg btn-block" onClick={onBackToLogin}>
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

            <button className="btn btn-deep btn-lg btn-block" type="submit" disabled={loading}>
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
