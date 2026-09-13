import { useState } from "react";
import Login from "./components/Login";
import Signup from "./components/Signup";
import AdminDashboard from "./components/admin/AdminDashboard";
import StaffDashboard from "./components/staff/StaffDashboard";
import PublicSVMEvaluation from "./components/PublicSVMEvaluation";

export default function App() {
  const token     = localStorage.getItem("access_token");
  const savedRole = localStorage.getItem("role") || "";

  const getInitialPage = () => {
    // Check if user wants to access public evaluation
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('page') === 'evaluation') {
      return "evaluation";
    }

    if (!token) return "login";
    if (savedRole === "admin") return "admin";
    if (savedRole === "staff") return "staff";
    return "login";
  };

  const [page, setPage] = useState(getInitialPage());

  const handleLoginSuccess = (roleOrPage) => {
    if (roleOrPage === "signup") {
      setPage("signup");
    } else {
      if (roleOrPage === "admin") setPage("admin");
      else if (roleOrPage === "staff") setPage("staff");
      else setPage("login");
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