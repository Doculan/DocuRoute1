import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import Login from "./components/Login";
import Signup from "./components/Signup";
import AdminDashboard from "./components/admin/AdminDashboard";
import StaffDashboard from "./components/staff/StaffDashboard";
import QmsDashboard from "./components/qms/QmsDashboard";
import PublicSVMEvaluation from "./components/PublicSVMEvaluation";

const PORTALS = ["admin", "qms", "staff"];

export default function App() {
  const token = localStorage.getItem("access_token");

  const getInitialPage = () => {
    // Check if user wants to access public evaluation
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('page') === 'evaluation') {
      return "evaluation";
    }
    // Signed in: which portal is the server's answer, asked below. The
    // role kept in browser storage is not consulted - anyone can edit it.
    return token ? "checking" : "login";
  };

  const [page, setPage] = useState(getInitialPage());

  const resolvePortal = useCallback(async () => {
    try {
      const { data } = await axios.get("/api/auth/me/", {
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
      });
      setPage(PORTALS.includes(data.portal) ? data.portal : "login");
    } catch {
      localStorage.clear();
      setPage("login");
    }
  }, []);

  useEffect(() => {
    if (page === "checking") resolvePortal();
  }, [page, resolvePortal]);

  const handleLoginSuccess = (roleOrPage) => {
    if (roleOrPage === "signup") {
      setPage("signup");
    } else {
      setPage("checking");
    }
  };

  const handleLogout = () => {
    localStorage.clear();
    setPage("login");
  };

  if (page === "login")  return <Login onLoginSuccess={handleLoginSuccess} />;
  if (page === "signup") return <Signup onBackToLogin={() => setPage("login")} />;
  if (page === "admin")  return <AdminDashboard onLogout={handleLogout} />;
  if (page === "staff")  return <StaffDashboard onLogout={handleLogout} />;
  if (page === "qms")    return <QmsDashboard onLogout={handleLogout} />;
  if (page === "checking") {
    return <div className="loading-row" style={{ padding: "2rem" }}><span className="spinner" /> Signing in…</div>;
  }
  if (page === "evaluation") return <PublicSVMEvaluation />;

  // Fallback — not approved or unknown role
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", padding: "1.5rem" }}>
      <div className="card card-pad anim-scale-in" style={{ maxWidth: "26rem", textAlign: "center" }}>
        <div className="empty-icon" style={{ margin: "0 auto 1rem" }}>⏳</div>
        <h2 className="auth-title">Account pending approval</h2>
        <p className="auth-subtitle">
          Your account is waiting for administrator approval. Please check back later.
        </p>
        <button className="btn btn-ghost btn-block" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </div>
  );
}