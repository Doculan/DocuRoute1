import { useState } from "react";
import UserManagement from "./UserManagement";
import Departments from "./Departments";
import Manuals from "./Manuals";
import Sections from "./Sections";
import RevisionReview from "./RevisionReview";
import logo from '../../assets/QMS.png';
import usersIcon from '../../assets/nav/users.svg';
import departmentsIcon from '../../assets/nav/departments.svg';
import manualsIcon from '../../assets/nav/manuals.svg';
import sectionsIcon from '../../assets/nav/sections.svg';
import reviewIcon from '../../assets/nav/review.svg';

const NAV_ITEMS = [
  { key: "users",       icon: usersIcon,       label: "User Management" },
  { key: "departments", icon: departmentsIcon, label: "Departments" },
  { key: "manuals",     icon: manualsIcon,     label: "Manuals" },
  { key: "sections",    icon: sectionsIcon,    label: "Sections" },
  { key: "review",   icon: reviewIcon,   label: "Revision Review" },
];

export default function AdminDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("users");

  const renderPage = () => {
    switch (activePage) {
      case "users": return <UserManagement />;
      case "departments": return <Departments />;
      case "manuals": return <Manuals />;
      case "sections": return <Sections />;
      case "revisions": return <RevisionReview />;
      default: return <UserManagement />;
    }
  };

  return (
    <div style={styles.wrapper}>
      {/* Sidebar */}
      <div style={styles.sidebar}>
        <div style={styles.sidebarTitle}>
          <img src={logo} alt="DocuRoute logo" style={{ height: '80px', width: 'auto' }} />
          </div>

        <div style={styles.sidebarSubtitle}>Admin Panel</div>
        <nav style={styles.nav}>
  {NAV_ITEMS.map((item) => (
    <button
      key={item.key}
      style={activePage === item.key ? styles.navItemActive : styles.navItem}
      onClick={() => setActivePage(item.key)}
    >
      <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <img
          src={item.icon}
          alt=""
          style={{
            width: "25px",
            height: "25px",
            filter: "brightness(0) invert(1)", // makes dark SVG appear white
          }}
        />
        <span>{item.label}</span>
      </span>
    </button>
  ))}
</nav>
        <div style={styles.sidebarBottom}>
          <span style={styles.adminName}>
            {localStorage.getItem("username")}
          </span>
          <button style={styles.logoutBtn} onClick={onLogout}>
            Logout
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div style={styles.content}>
        {renderPage()}
      </div>
    </div>
  );
}

const styles = {
  wrapper: {
    display: "flex",
    height: "100vh",
    backgroundColor: "#f0f2f5",
    overflow: "hidden",
    width: '100vw'
  },
  sidebar: {
    width: "240px",
    minWidth: "240px",
    backgroundColor: "#080552",
    display: "flex",
    flexDirection: "column",
    padding: "1.5rem 0",
  },
  sidebarTitle: {
    color: "#fff",
    fontSize: "1.3rem",
    fontWeight: "700",
    padding: "0 1.5rem",
    marginBottom: "0.2rem",
  },
  sidebarSubtitle: {
    color: "#8888aa",
    fontSize: "0.75rem",
    padding: "0 1.5rem",
    marginBottom: "2rem",
    textTransform: "uppercase",
    letterSpacing: "1px",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "0.25rem",
    flex: 1,
  },
  navItem: {
    background: "none",
    border: "none",
    color: "#aaa",
    padding: "0.75rem 1.5rem",
    textAlign: "left",
    cursor: "pointer",
    fontSize: "0.9rem",
    fontWeight: "500",
    transition: "all 0.2s",
    height: "60px",
  },
  navItemActive: {
    background: "rgba(79, 70, 229, 0.2)",
    border: "none",
    borderLeftWidth: "3px",
    borderLeftStyle: "solid",
    borderLeftColor: "#48bb78",
    color: "#fff",
    padding: "0.75rem 1.5rem",
    textAlign: "left",
    cursor: "pointer",
    fontSize: "0.9rem",
    fontWeight: "600",
    height: "60px",
  },
  sidebarBottom: {
    padding: "1rem 1.5rem",
    borderTop: "1px solid #2a2a4a",
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem",
  },
  adminName: {
    color: "#aaa",
    fontSize: "0.85rem",
  },
  logoutBtn: {
    padding: "0.5rem",
    backgroundColor: "#e53e3e",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "600",
    fontSize: "0.85rem",
  },
  content: {
    flex: 1,
    overflowY: "auto",
    padding: "2rem",
  },
};
