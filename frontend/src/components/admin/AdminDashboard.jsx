import { useEffect, useState } from "react";
import axios from "axios";
import UserManagement from "./UserManagement";
import Departments from "./Departments";
import Manuals from "./Manuals";
import Sections from "./Sections";
import RevisionReview from "./RevisionReview";
import SVMEvaluation from "./SVMEvaluation";
import Announcements from "./Announcements";
import Topbar from "../Topbar";
import logo from '../../assets/QMS.png';
import usersIcon from '../../assets/nav/users.svg';
import departmentsIcon from '../../assets/nav/departments.svg';
import manualsIcon from '../../assets/nav/manuals.svg';
import sectionsIcon from '../../assets/nav/sections.svg';
import reviewIcon from '../../assets/nav/review.svg';

// Six flat items is a list you read top to bottom every time. Three short
// groups is a structure you learn once — and the group label tells you what
// kind of work the items underneath do.
const NAV_GROUPS = [
  {
    label: "Access",
    items: [
      { key: "users",       icon: usersIcon,       label: "Users",       badge: "users" },
      { key: "departments", icon: departmentsIcon, label: "Departments" },
    ],
  },
  {
    label: "Documents",
    items: [
      { key: "manuals",  icon: manualsIcon,  label: "Manuals" },
      { key: "sections", icon: sectionsIcon, label: "Sections" },
      { key: "review",   icon: reviewIcon,   label: "Revisions", badge: "revisions" },
    ],
  },
  {
    // Notices posted to the portal, not messaging. A calendar or a staff
    // help page would belong here too.
    label: "Content",
    items: [
      { key: "announcements", icon: reviewIcon, label: "Announcements" },
    ],
  },
  {
    label: "System",
    items: [
      { key: "evaluation", icon: reviewIcon, label: "Model health" },
    ],
  },
];

const CRUMBS = {
  users: "Users",
  departments: "Departments",
  manuals: "Manuals",
  sections: "Sections",
  review: "Revisions",
  announcements: "Announcements",
  evaluation: "Model health",
};

export default function AdminDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("users");
  const [search, setSearch] = useState("");
  const [manualQuery, setManualQuery] = useState("");
  // Set when Sections is reached by clicking a manual rather than by the
  // nav. Sections keeps its own picker either way - it should behave the
  // same however you arrive - this only says which manual to open on.
  const [drillManual, setDrillManual] = useState(null);
  const [pending, setPending] = useState({ users: 0, revisions: 0 });
  const username = localStorage.getItem("username") || "Admin";

  // Counts ride along on the nav so waiting work is visible without opening
  // the page. Re-read on every tab change, and best-effort only: a failed
  // count must never block the shell.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const auth = { headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } };
      const [users, revisions] = await Promise.allSettled([
        axios.get("/api/admin/pending-users/", auth),
        axios.get("/api/admin/revisions/?status=pending", auth),
      ]);
      if (cancelled) return;
      setPending({
        users: users.status === "fulfilled" ? users.value.data.length : 0,
        revisions: revisions.status === "fulfilled" ? revisions.value.data.length : 0,
      });
    })();

    return () => { cancelled = true; };
  }, [activePage]);

  const renderPage = () => {
    switch (activePage) {
      case "users": return <UserManagement />;
      case "departments": return <Departments />;
      case "manuals":
        return <Manuals initialSearch={manualQuery} onOpenSections={openSections} />;
      case "sections":
        return <Sections openManualId={drillManual} />;
      case "announcements": return <Announcements />;
      case "review": return <RevisionReview />;
      case "evaluation": return <SVMEvaluation />;
      default: return <UserManagement />;
    }
  };

  // Global search hands the query to the one page that can answer it.
  const runSearch = (query) => {
    setManualQuery(query);
    setActivePage("manuals");
  };

  // Drilling from a manual into its sections is the one place a Back is
  // genuinely expected, because it reads as going *into* something rather
  // than switching tabs. This app has no router - navigation is state - so
  // the History API is used directly rather than pulling one in for a
  // single transition.
  const openSections = (manualId) => {
    setDrillManual(manualId);
    setActivePage("sections");
    window.history.pushState(
      { adminPage: "sections", manualId }, "", window.location.href
    );
  };

  useEffect(() => {
    const onPop = (event) => {
      // Anything that is not our own drill-down entry means the user has
      // gone back past it; returning to Manuals is the honest answer, since
      // that is where they came from.
      const state = event.state;
      if (state && state.adminPage === "sections") {
        setDrillManual(state.manualId ?? null);
        setActivePage("sections");
      } else {
        setDrillManual(null);
        setActivePage("manuals");
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={logo} alt="QMS" />
          <div className="sidebar-brand-sub">Document control</div>
        </div>
        <div className="sidebar-eyebrow">Admin Panel</div>

        <nav className="sidebar-nav">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="nav-group">{group.label}</div>
              {group.items.map((item) => {
                const count = item.badge ? pending[item.badge] : 0;
                return (
                  <button
                    key={item.key}
                    className={`nav-item${activePage === item.key ? " is-active" : ""}`}
                    onClick={() => {
                      // Reaching Sections from the nav is not a drill-down,
                      // so it opens on whatever the picker last had rather
                      // than on a manual chosen three clicks ago.
                      if (item.key !== "sections") setDrillManual(null);
                      setActivePage(item.key);
                    }}
                  >
                    <img className="nav-icon" src={item.icon} alt="" />
                    <span>{item.label}</span>
                    {count > 0 && <span className="nav-count">{count}</span>}
                  </button>
                );
              })}
            </div>
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

      <div className="app-main">
        <Topbar
          crumb={CRUMBS[activePage]}
          search={search}
          onSearchChange={setSearch}
          onSearchSubmit={runSearch}
          searchPlaceholder="Search manuals by title, department or author"
          pendingCount={pending.users + pending.revisions}
          pendingTitle="items waiting for review"
          onPendingClick={() => setActivePage(pending.revisions > 0 ? "review" : "users")}
        />

        <main className="app-content">
          {/* key forces a remount so each tab animates in */}
          <div className="tab-panel" key={`${activePage}-${manualQuery}`}>
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
