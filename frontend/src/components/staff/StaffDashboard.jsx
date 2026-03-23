import { useState } from "react";
import StaffManuals from "./StaffManuals";
import StaffSections from "./StaffSections";
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
    <div style={styles.wrapper}>
      {/* Sidebar */}
      <div style={styles.sidebar}>
        <div style={styles.sidebarTitle}>
          <img src={logo} alt="DocuRoute logo" style={{ height: '80px', width: 'auto' }} />
        </div>

        <div style={styles.sidebarSubtitle}>Staff Portal</div>
        <nav style={styles.nav}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              style={activePage === item.key ? styles.navItemActive : styles.navItem}
              onClick={() => {
                if (item.key === "manuals") {
                  handleBackToManuals();
                } else {
                  setActivePage(item.key);
                }
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <img
                  src={item.icon}
                  alt=""
                  style={{
                    width: "25px",
                    height: "25px",
                    filter: "brightness(0) invert(1)",
                  }}
                />
                <span>{item.label}</span>
              </span>
            </button>
          ))}
        </nav>
        <div style={styles.sidebarBottom}>
          <span style={styles.staffName}>
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
    backgroundColor: "#090749",
    display: "flex",
    flexDirection: "column",
    padding: "1.5rem 0",
  },
  sidebarTitle: {
    paddingLeft: "1rem",
    marginBottom: "1rem",
  },
  sidebarSubtitle: {
    color: "#ccc",
    fontSize: "0.85rem",
    textTransform: "uppercase",
    paddingLeft: "1.5rem",
    marginBottom: "1.5rem",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem",
    paddingLeft: "0.5rem",
    paddingRight: "0.5rem",
    flex: 1,
  },
  navItem: {
    padding: "0.75rem 1rem",
    backgroundColor: "transparent",
    color: "#aaa",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
    fontSize: "0.9rem",
    transition: "all 0.2s",
  },
  navItemActive: {
    padding: "0.75rem 1rem",
    backgroundColor: "#4a47a3",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "600",
    fontSize: "0.9rem",
  },
  sidebarBottom: {
    padding: "1.5rem",
    borderTop: "1px solid #333",
  },
  staffName: {
    color: "#aaa",
    fontSize: "0.85rem",
    display: "block",
    marginBottom: "1rem",
  },
  logoutBtn: {
    width: "100%",
    padding: "0.5rem",
    backgroundColor: "#e53e3e",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "600",
  },
  content: {
    flex: 1,
    overflow: "auto",
    padding: "2rem",
  },
};
