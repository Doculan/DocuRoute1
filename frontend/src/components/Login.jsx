import { useState } from "react";
import axios from "axios";
import logo from '../assets/QMS.png';

export default function Login({ onLoginSuccess }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await axios.post("/api/auth/login/", {
        username,
        password,
      });

      localStorage.setItem("access_token", response.data.access);
      localStorage.setItem("refresh_token", response.data.refresh);
      localStorage.setItem("role", response.data.role);
      // Decides which nav groups appear, not what the API allows -
      // every endpoint checks the role itself. Server-side routing
      // replaces this at 1c.
      localStorage.setItem("system_role", response.data.system_role || "user");
      localStorage.setItem("username", response.data.username);
      // The sidebar names the department a user belongs to, not just "Staff".
      if (response.data.department) {
        localStorage.setItem("department", response.data.department);
      } else {
        localStorage.removeItem("department");
      }

      onLoginSuccess(response.data.role);
    } catch (err) {
      const msg = err.response?.data?.error || "Something went wrong.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-brand">
        <div className="auth-brand-inner">
          <img src={logo} alt="DocuRoute" />
          <p className="auth-brand-text">
            <strong>Quality Management System on Administrative Services</strong>
            Controlled Document Management System
          </p>
        </div>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2 className="auth-title">Welcome back</h2>
          <p className="auth-subtitle">Sign in to continue to your workspace</p>

          <form onSubmit={handleLogin} className="auth-form">
            <div className="field">
              <label className="label" htmlFor="login-username">Username</label>
              <input
                id="login-username"
                className="input"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                autoComplete="username"
                required
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                required
              />
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            <button className="btn btn-deep btn-lg btn-block" type="submit" disabled={loading}>
              {loading ? <><span className="spinner spinner-light" /> Signing in…</> : "Sign in"}
            </button>
          </form>

          <p className="auth-foot">
            Don&apos;t have an account?{" "}
            <button type="button" className="link-btn" onClick={() => onLoginSuccess("signup")}>
              Create one
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
