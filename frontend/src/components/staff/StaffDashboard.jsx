import { useState } from "react";
import StaffManuals from "./StaffManuals";
import StaffSections from "./StaffSections";
import Topbar from "../Topbar";
import logo from '../../assets/QMS.png';
import manualsIcon from '../../assets/nav/manuals.svg';
import sectionsIcon from '../../assets/nav/sections.svg';

const NAV_ITEMS = [
  { key: "manuals", icon: manualsIcon, label: "My Manuals" },
  { key: "sections", icon: sectionsIcon, label: "Sections" },
];

export default function StaffDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("manuals");
  const [selectedManualId, setSelectedManualId] = useState(null);
  const username = localStorage.getItem("username") || "Staff";
  // Which department you belong to is the useful fact here — "Staff" only
  // repeats what the portal heading already says. Stored at login.
  const department = localStorage.getItem("department");

  const handleSelectManual = (manualId) => {
    setSelectedManualId(manualId);
    setActivePage("sections");
  };

  const handleBackToManuals = () => {
    setActivePage("manuals");
    setSelectedManualId(null);
  };

  const renderPage = () => {
    switch (activePage) {
      case "manuals":
        return <StaffManuals onSelectManual={handleSelectManual} />;
      case "sections":
        return selectedManualId ? (
          <StaffSections manualId={selectedManualId} onBack={handleBackToManuals} />
        ) : (
          <StaffManuals onSelectManual={handleSelectManual} />
        );
      default:
        return <StaffManuals onSelectManual={handleSelectManual} />;
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={logo} alt="QMS" />
          <div className="sidebar-brand-sub">Document control</div>
        </div>
        <div className="sidebar-eyebrow">Staff Portal</div>

        <nav className="sidebar-nav">
          <div className="nav-group">Documents</div>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`nav-item${activePage === item.key ? " is-active" : ""}`}
              onClick={() => {
                if (item.key === "manuals") handleBackToManuals();
                else setActivePage(item.key);
              }}
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
              <div className="sidebar-role">{department || "Staff"}</div>
            </div>
          </div>
          <button className="btn-logout" onClick={onLogout}>Sign out</button>
        </div>
      </aside>

      <div className="app-main">
        <Topbar crumb={activePage === "manuals" ? "My Manuals" : "Sections"} />

        <main className="app-content">
          <div className="tab-panel" key={`${activePage}-${selectedManualId ?? ""}`}>
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
