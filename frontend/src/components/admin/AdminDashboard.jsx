import { useState } from "react";
import UserManagement from "./UserManagement";
import Departments from "./Departments";
import Manuals from "./Manuals";
import Sections from "./Sections";
import RevisionReview from "./RevisionReview";
import SVMEvaluation from "./SVMEvaluation";
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
  { key: "review",      icon: reviewIcon,      label: "Revision Review" },
  { key: "evaluation",  icon: reviewIcon,      label: "SVM Evaluation" },
];

export default function AdminDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("users");
  const username = localStorage.getItem("username") || "Admin";

  const renderPage = () => {
    switch (activePage) {
      case "users": return <UserManagement />;
      case "departments": return <Departments />;
      case "manuals": return <Manuals />;
      case "sections": return <Sections />;
      case "review": return <RevisionReview />;
      case "evaluation": return <SVMEvaluation />;
      default: return <UserManagement />;
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={logo} alt="DocuRoute" />
        </div>
        <div className="sidebar-eyebrow">Admin Panel</div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`nav-item${activePage === item.key ? " is-active" : ""}`}
              onClick={() => setActivePage(item.key)}
            >
              <img className="nav-icon" src={item.icon} alt="" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">{username.slice(0, 2)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="sidebar-username">{username}</div>
              <div className="sidebar-role">Administrator</div>
            </div>
          </div>
          <button className="btn-logout" onClick={onLogout}>Sign out</button>
        </div>
      </aside>

      <main className="app-content">
        {/* key forces a remount so each tab animates in */}
        <div className="tab-panel" key={activePage}>
          {renderPage()}
        </div>
      </main>
    </div>
  );
}
