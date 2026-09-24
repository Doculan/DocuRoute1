import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import StaffManuals from "./StaffManuals";
import StaffSections from "./StaffSections";
import StaffSectionSearch from "./StaffSectionSearch";
import StaffHome from "./StaffHome";
import StaffHelp from "./StaffHelp";
import StaffProposals from "./StaffProposals";
import Topbar from "../Topbar";
import logo from '../../assets/QMS.png';
import manualsIcon from '../../assets/nav/manuals.svg';
import sectionsIcon from '../../assets/nav/sections.svg';

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

// Documents you read, then work you have submitted, then how it all works.
// Dashboard leads because it is the landing page; Help sits last because it
// is consulted once and then rarely.
const NAV_GROUPS = [
  {
    label: "Overview",
    items: [{ key: "dashboard", icon: manualsIcon, label: "Dashboard" }],
  },
  {
    label: "Documents",
    items: [
      { key: "manuals", icon: manualsIcon, label: "My Manuals" },
      { key: "sections", icon: sectionsIcon, label: "Sections" },
    ],
  },
  {
    label: "Your work",
    items: [
      { key: "proposals", icon: sectionsIcon, label: "Proposals" },
      { key: "help", icon: manualsIcon, label: "Help" },
    ],
  },
];

const CRUMBS = {
  dashboard: "Dashboard",
  manuals: "My Manuals",
  sections: "Sections",
  proposals: "Proposals",
  help: "Help",
};

export default function StaffDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("dashboard");
  const [selectedManualId, setSelectedManualId] = useState(null);
  // A section reached from the Sections tab rather than by drilling into a
  // manual. Both routes land on the same view - that is the point of keeping
  // the two tabs - so this just tells StaffSections where to open.
  const [focusSectionId, setFocusSectionId] = useState(null);
  const [awaiting, setAwaiting] = useState(0);
  // Set when a proposal is started from a section rather than from the tab.
  const [proposeForManual, setProposeForManual] = useState(null);

  const username = localStorage.getItem("username") || "Staff";

  // The badge is the only reason this lives up here: it has to be right on
  // the nav whichever page you are looking at. The dashboard already knows
  // how much is waiting, so the shell reads it from there.
  const refreshAwaiting = useCallback(async () => {
    try {
      const res = await axios.get("/api/staff/dashboard/", getAuth());
      setAwaiting(res.data.proposals_awaiting || 0);
    } catch {
      // A badge that cannot load is not worth an error message.
      setAwaiting(0);
    }
  }, []);

  useEffect(() => { refreshAwaiting(); }, [refreshAwaiting]);

  const openManual = (manualId) => {
    setSelectedManualId(manualId);
    setFocusSectionId(null);
    setActivePage("sections");
  };

  const openSection = (section) => {
    setSelectedManualId(section.manual_id);
    setFocusSectionId(section.id);
    setActivePage("sections");
  };

  const backToManuals = () => {
    setActivePage("manuals");
    setSelectedManualId(null);
    setFocusSectionId(null);
  };

  const handleNav = (key) => {
    if (key === "manuals") return backToManuals();
    if (key === "sections") {
      // Sections is a tab in its own right now: clicking it goes to the
      // cross-manual list, not to whichever manual happened to be open.
      setSelectedManualId(null);
      setFocusSectionId(null);
    }
    setActivePage(key);
  };

  const renderPage = () => {
    switch (activePage) {
      case "dashboard":
        return (
          <StaffHome
            onGo={handleNav}
            onOpenManual={openManual}
            onOpenSection={(manualId, sectionId) =>
              openSection({ manual_id: manualId, id: sectionId })}
          />
        );
      case "manuals":
        return <StaffManuals onSelectManual={openManual} />;
      case "sections":
        return selectedManualId ? (
          <StaffSections
            manualId={selectedManualId}
            focusSectionId={focusSectionId}
            onBack={() => handleNav("sections")}
            onPropose={(id) => {
              setProposeForManual(id);
              setActivePage("proposals");
            }}
          />
        ) : (
          <StaffSectionSearch onOpenSection={openSection} />
        );
      case "proposals":
        return (
          <StaffProposals
            startManualId={proposeForManual}
            onDone={() => { setProposeForManual(null); refreshAwaiting(); }}
          />
        );
      case "help":
        return <StaffHelp />;
      default:
        return <StaffManuals onSelectManual={openManual} />;
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
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="nav-group">{group.label}</div>
              {group.items.map((item) => (
                <button
                  key={item.key}
                  className={`nav-item${activePage === item.key ? " is-active" : ""}`}
                  onClick={() => handleNav(item.key)}
                >
                  <img className="nav-icon" src={item.icon} alt="" />
                  <span>{item.label}</span>
                  {item.key === "proposals" && awaiting > 0 && (
                    <span className="nav-count" title="Waiting for your office to decide">
                      {awaiting}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">{username.slice(0, 2)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="sidebar-username">{username}</div>
              <div className="sidebar-role">Staff</div>
            </div>
          </div>
          <button className="btn-logout" onClick={onLogout}>Sign out</button>
        </div>
      </aside>

      <div className="app-main">
        <Topbar crumb={CRUMBS[activePage] || "My Manuals"} />

        <main className="app-content">
          <div
            className="tab-panel"
            key={`${activePage}-${selectedManualId ?? ""}`}
          >
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
