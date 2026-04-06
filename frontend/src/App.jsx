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
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"100vh", backgroundColor:"#f0f2f5", flexDirection:"column", gap:"1rem" }}>
      <div style={{ backgroundColor:"#fff", padding:"2rem 3rem", borderRadius:"12px", boxShadow:"0 4px 16px rgba(0,0,0,0.08)", textAlign:"center" }}>
        <h2 style={{ color:"#090749", margin:"0 0 0.5rem" }}>Account Pending Approval</h2>
        <p style={{ color:"#718096", margin:"0 0 1.5rem" }}>Your account is waiting for admin approval. Please check back later.</p>
        <button
          style={{ padding:"0.6rem 1.5rem", backgroundColor:"#e53e3e", color:"#fff", border:"none", borderRadius:"8px", cursor:"pointer", fontWeight:"600" }}
          onClick={handleLogout}
        >
          Logout
        </button>
      </div>
    </div>
  );
}