import { useState } from "react";
import axios from "axios";

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
      const response = await axios.post("http://127.0.0.1:8000/api/auth/login/", {
        username,
        password,
      });

      localStorage.setItem("access_token", response.data.access);
      localStorage.setItem("refresh_token", response.data.refresh);
      localStorage.setItem("role", response.data.role);
      localStorage.setItem("username", response.data.username);

      onLoginSuccess(response.data.role);
    } catch (err) {
      const msg = err.response?.data?.error || "Something went wrong.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.page}>
      <div style={styles.left}>
        <div style={styles.brand}>
          <h1 style={styles.brandTitle}>DocuRoute</h1>
          <p style={styles.brandSub}>ML-Assisted Inter-Office Document Routing System</p>
        </div>
      </div>

      <div style={styles.right}>
        <div style={styles.card}>
          <h2 style={styles.title}>Welcome back</h2>
          <p style={styles.subtitle}>Sign in to your account</p>

          <form onSubmit={handleLogin} style={styles.form}>
            <div style={styles.inputGroup}>
              <label style={styles.label}>Username</label>
              <input
                style={styles.input}
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                required
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>Password</label>
              <input
                style={styles.input}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                required
              />
            </div>

            {error && <p style={styles.error}>{error}</p>}

            <button style={styles.button} type="submit" disabled={loading}>
              {loading ? "Signing in..." : "Login"}
            </button>
          </form>

          <p style={styles.registerText}>
            Don't have an account?{" "}
            <span style={styles.link} onClick={() => onLoginSuccess("signup")}>
              Sign up
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: {
    display: "flex",
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
  },
  left: {
    flex: 1,
    backgroundColor: "#1a1a2e",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "3rem",
  },
  brand: {
    textAlign: "center",
  },
  brandTitle: {
    color: "#fff",
    fontSize: "3rem",
    fontWeight: "800",
    margin: "0 0 1rem 0",
    letterSpacing: "-1px",
  },
  brandSub: {
    color: "#8888aa",
    fontSize: "1rem",
    lineHeight: "1.6",
    maxWidth: "300px",
    margin: "0 auto",
  },
  right: {
    width: "480px",
    minWidth: "480px",
    backgroundColor: "#f0f2f5",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "2rem",
  },
  card: {
    backgroundColor: "#fff",
    padding: "2.5rem",
    borderRadius: "16px",
    boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
    width: "100%",
  },
  title: {
    margin: "0 0 0.25rem 0",
    fontSize: "1.6rem",
    fontWeight: "700",
    color: "#1a1a2e",
  },
  subtitle: {
    color: "#888",
    marginBottom: "1.8rem",
    marginTop: 0,
    fontSize: "0.9rem",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem",
  },
  inputGroup: {
    display: "flex",
    flexDirection: "column",
    gap: "0.3rem",
  },
  label: {
    fontSize: "0.85rem",
    fontWeight: "600",
    color: "#333",
  },
  input: {
    padding: "0.75rem 1rem",
    borderRadius: "8px",
    border: "1px solid #ddd",
    fontSize: "0.95rem",
    outline: "none",
    transition: "border 0.2s",
  },
  button: {
    marginTop: "0.5rem",
    padding: "0.85rem",
    backgroundColor: "#4f46e5",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    fontSize: "1rem",
    fontWeight: "600",
    cursor: "pointer",
  },
  error: {
    color: "#e53e3e",
    fontSize: "0.85rem",
    textAlign: "center",
    margin: 0,
    padding: "0.5rem",
    backgroundColor: "#fff5f5",
    borderRadius: "8px",
    border: "1px solid #fed7d7",
  },
  registerText: {
    textAlign: "center",
    marginTop: "1.2rem",
    fontSize: "0.875rem",
    color: "#666",
  },
  link: {
    color: "#4f46e5",
    cursor: "pointer",
    fontWeight: "600",
  },
};
