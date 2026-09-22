import { useEffect, useState } from "react";
import axios from "axios";
import UserManagement from "./UserManagement";
import Departments from "./Departments";
import Manuals from "./Manuals";
import Sections from "./Sections";
import RevisionReview from "./RevisionReview";
import SVMEvaluation from "./SVMEvaluation";
import Announcements from "./Announcements";
import AdminHome from "./AdminHome";
import Offices from "./Offices";
import Topbar from "../Topbar";
import logo from '../../assets/QMS.png';
import usersIcon from '../../assets/nav/users.svg';
import departmentsIcon from '../../assets/nav/departments.svg';
import manualsIcon from '../../assets/nav/manuals.svg';
import sectionsIcon from '../../assets/nav/sections.svg';
import reviewIcon from '../../assets/nav/review.svg';
import dashboardIcon from '../../assets/nav/dashboard.svg';

// Six flat items is a list you read top to bottom every time. Three short
// groups is a structure you learn once — and the group label tells you what
// kind of work the items underneath do.
const NAV_GROUPS = [
  {
    // Ungrouped, because it is not one kind of work among others - it is
    // the way in, and the thing every other item is reached from.
    label: null,
    items: [
      { key: "home", icon: dashboardIcon, label: "Dashboard" },
    ],
  },
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
    // v4. Configuring the organisation is a different job from running
    // the document process, and only the system admin does it - so the
    // group is hidden rather than disabled for everyone else. A disabled
    // group is an invitation to wonder what you are missing.
    label: "Organisation",
    systemAdminOnly: true,
    items: [
      { key: "offices", icon: departmentsIcon, label: "Offices" },
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
  home: "Dashboard",
  offices: "Offices",
  users: "Users",
  departments: "Departments",
  manuals: "Manuals",
  sections: "Sections",
  review: "Revisions",
  announcements: "Announcements",
  evaluation: "Model health",
};

export default function AdminDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("home");
  const [search, setSearch] = useState("");
  const [manualQuery, setManualQuery] = useState("");
  // Set when Sections is reached by clicking a manual rather than by the
  // nav. Sections keeps its own picker either way - it should behave the
  // same however you arrive - this only says which manual to open on.
  const [drillManual, setDrillManual] = useState(null);
  // Set when Revisions is opened from a dashboard row rather than the nav,
  // so the queue can scroll to the one that was clicked.
  const [revisionToOpen, setRevisionToOpen] = useState(null);
  const [pending, setPending] = useState({ users: 0, revisions: 0 });
  const username = localStorage.getItem("username") || "Admin";
  const systemRole = localStorage.getItem("system_role") || "user";
  const navGroups = NAV_GROUPS.filter(
    (g) => !g.systemAdminOnly || systemRole === "system_admin"
  );

  // Counts ride along on the nav so waiting work is visible without opening
  // the page. They come from the dashboard summary rather than from two
  // list endpoints fetched for their length: the badge and the dashboard
  // are the same claim, and two sources for it will eventually disagree.
  // Re-read on every tab change, and best-effort only: a failed count must
  // never block the shell.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const auth = { headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } };
      try {
        const { data } = await axios.get("/api/admin/dashboard/", auth);
        if (cancelled) return;
        setPending({
          users: data.attention.pending_users,
          revisions: data.attention.pending_revisions,
        });
      } catch {
        // No badge is better than a wrong one.
      }
    })();

    return () => { cancelled = true; };
  }, [activePage]);

  const renderPage = () => {
    switch (activePage) {
      case "home":
        return <AdminHome onGo={goTo} onOpenRevision={openRevision} />;
      case "users": return <UserManagement />;
      case "departments": return <Departments />;
      case "manuals":
        return <Manuals initialSearch={manualQuery} onOpenSections={openSections} />;
      case "sections":
        return <Sections openManualId={drillManual} />;
      case "announcements": return <Announcements />;
      case "offices": return <Offices />;
      case "review": return <RevisionReview openRevision={revisionToOpen} />;
      case "evaluation": return <SVMEvaluation />;
      default: return <AdminHome onGo={goTo} onOpenRevision={openRevision} />;
    }
  };

  // The dashboard is a set of pointers at other screens, so it needs a way
  // to hand navigation back. Same reset the nav buttons do, for the same
  // reason: arriving at Sections from here is not a drill-down.
  const goTo = (page) => {
    if (page !== "sections") setDrillManual(null);
    setRevisionToOpen(null);
    setActivePage(page);
  };

  // Carries the status as well as the id: the queue opens on Pending, and
  // a decided revision is by definition not in that list, so sending only
  // an id would land on a tab that cannot show it.
  const openRevision = (revisionId, status) => {
    setDrillManual(null);
    setRevisionToOpen({ id: revisionId, status: status || "pending" });
    setActivePage("review");
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
          {navGroups.map((group) => (
            <div key={group.label ?? "top"}>
              {group.label && <div className="nav-group">{group.label}</div>}
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
                      setRevisionToOpen(null);
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
