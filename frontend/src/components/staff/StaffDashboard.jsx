import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import StaffManuals from "./StaffManuals";
import StaffSections from "./StaffSections";
import StaffSectionSearch from "./StaffSectionSearch";
import StaffHome from "./StaffHome";
import StaffRevisions from "./StaffRevision";
import StaffHelp from "./StaffHelp";
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
      { key: "revisions", icon: sectionsIcon, label: "My Revisions" },
      { key: "help", icon: manualsIcon, label: "Help" },
    ],
  },
];

const CRUMBS = {
  dashboard: "Dashboard",
  manuals: "My Manuals",
  sections: "Sections",
  revisions: "My Revisions",
  help: "Help",
};

export default function StaffDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("dashboard");
  const [selectedManualId, setSelectedManualId] = useState(null);
  // A section reached from the Sections tab rather than by drilling into a
  // manual. Both routes land on the same view - that is the point of keeping
  // the two tabs - so this just tells StaffSections where to open.
  const [focusSectionId, setFocusSectionId] = useState(null);
  // Which revision to open in My Revisions, when something links across to it.
  const [focusRevisionId, setFocusRevisionId] = useState(null);
  const [unreadFeedback, setUnreadFeedback] = useState(0);

  const username = localStorage.getItem("username") || "Staff";
  // Which department you belong to is the useful fact here — "Staff" only
  // repeats what the portal heading already says. Stored at login.
  const department = localStorage.getItem("department");

  // The badge is the only reason this lives up here: it has to be right on
  // the nav whichever page you are looking at.
  const refreshFeedbackCount = useCallback(async () => {
    try {
      const res = await axios.get("/api/staff/revisions/?scope=mine", getAuth());
      setUnreadFeedback(res.data.filter((r) => r.has_unread_feedback).length);
    } catch {
      // A badge that cannot load is not worth an error message.
      setUnreadFeedback(0);
    }
  }, []);

  useEffect(() => { refreshFeedbackCount(); }, [refreshFeedbackCount]);

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

  const openRevision = (revisionId) => {
    setFocusRevisionId(revisionId);
    setActivePage("revisions");
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
    if (key === "revisions") setFocusRevisionId(null);
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
            onOpenRevision={openRevision}
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
            onOpenRevision={openRevision}
          />
        ) : (
          <StaffSectionSearch onOpenSection={openSection} />
        );
      case "revisions":
        return (
          <StaffRevisions
            focusRevisionId={focusRevisionId}
            onFeedbackRead={refreshFeedbackCount}
            onOpenSection={(manualId, sectionId) =>
              openSection({ manual_id: manualId, id: sectionId })}
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
                  {item.key === "revisions" && unreadFeedback > 0 && (
                    <span className="nav-count" title="Reviewer feedback you have not opened">
                      {unreadFeedback}
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
              <div className="sidebar-role">{department || "Staff"}</div>
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
            key={`${activePage}-${selectedManualId ?? ""}-${focusRevisionId ?? ""}`}
          >
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
