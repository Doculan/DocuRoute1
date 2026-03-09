import { useState } from "react";
import Login from "./components/Login";
import Signup from "./components/Signup";
import AdminDashboard from "./components/admin/AdminDashboard";

export default function App() {
  const token = localStorage.getItem("access_token");
  const savedRole = localStorage.getItem("role") || "";

  const getInitialPage = () => {
    if (!token) return "login";
    if (savedRole === "admin") return "admin";
    return "app";
  };

  const [page, setPage] = useState(getInitialPage);
  const [role, setRole] = useState(savedRole);

  const handleLoginSuccess = (roleOrPage) => {
    if (roleOrPage === "signup") {
      setPage("signup");
    } else {
      setRole(roleOrPage);
      setPage(roleOrPage === "admin" ? "admin" : "app");
    }
  }; // ✅ closing brace was missing before

  const handleLogout = () => {
    localStorage.clear();
    setPage("login");
  };

  if (page === "login") return <Login onLoginSuccess={handleLoginSuccess} />;
  if (page === "signup") return <Signup onBackToLogin={() => setPage("login")} />;
  if (page === "admin") return <AdminDashboard onLogout={handleLogout} />;

  return (
    <div>
      <nav style={styles.nav}>
        <span style={styles.navTitle}>DocuRoute</span>
        <div style={styles.navRight}>
          <span style={styles.navUser}>
            {localStorage.getItem("username")} ({role})
          </span>
          <button style={styles.logoutBtn} onClick={handleLogout}>
            Logout
          </button>
        </div>
      </nav>
    </div>
  );
}

const styles = {
  nav: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", padding: "1rem 2rem",
    backgroundColor: "#1a1a2e", color: "#fff",
  },
  navTitle: { fontSize: "1.2rem", fontWeight: "700" },
  navRight: { display: "flex", alignItems: "center", gap: "1rem" },
  navUser: { fontSize: "0.85rem", color: "#ccc" },
  logoutBtn: {
    padding: "0.4rem 0.9rem", backgroundColor: "#e53e3e",
    color: "#fff", border: "none", borderRadius: "6px",
    cursor: "pointer", fontWeight: "600",
  },
};
