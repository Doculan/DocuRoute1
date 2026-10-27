import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import StaffManuals from "../staff/StaffManuals";
import StaffSections from "../staff/StaffSections";
import QmsRequests from "./QmsRequests";
import Monitoring from "../Monitoring";
import QmsHome from "./QmsHome";
import History from "../History";
import { DeadlinesReadOnly } from "../admin/Notices";
import Topbar from "../Topbar";
import Account from "../Account";
import NeedsAction from "../NeedsAction";
import ActionBanner from "../ActionBanner";
import AnnouncementBanner from "../AnnouncementBanner";
import NotificationBell from "../NotificationBell";
import NotificationsPage from "../NotificationsPage";
import logo from "../../assets/QMS.png";
import manualsIcon from "../../assets/nav/manuals.svg";
import reviewIcon from "../../assets/nav/review.svg";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const CRUMBS = {
  dashboard: "Dashboard", manuals: "Manuals", requests: "Requests", monitoring: "Monitoring",
  history: "History",
  deadlines: "Deadlines",
  account: "My account",
  notifications: "Notifications",
};

/**
 * The QMS portal: the IMR and the Document Custodian.
 *
 * It opens on a Dashboard (v4.2 Phase 4, spec §7.7): the queue as counts,
 * then the institution's overdue, stalled and advised revisions and the
 * offices chart. Manuals, read only, stay one click away; Requests holds
 * the lists; Monitoring is read-only across the whole institution.
 * What someone may *decide* comes from the position they hold, which the
 * server checks; this portal only shows the way.
 */
export default function QmsDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("dashboard");
  // Where Monitoring opens when a dashboard count is clicked.
  const [monitorStart, setMonitorStart] = useState(null);
  const [manualId, setManualId] = useState(null);
  const [openRequest, setOpenRequest] = useState(null);
  const [waiting, setWaiting] = useState(0);
  const [me, setMe] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [{ data: who }, { data: queue }] = await Promise.all([
          axios.get("/api/auth/me/", getAuth()),
          axios.get("/api/qms/queue/", getAuth()),
        ]);
        setMe(who);
        const t = queue.totals || {};
        setWaiting((t.imr || 0) + (t.approval || 0) + (t.custodian || 0));
      } catch {
        // The pages report their own errors; the sidebar can do without.
      }
    })();
  }, []);

  const onCount = useCallback((n) => setWaiting(n), []);

  const go = (page) => {
    setMonitorStart(null);
    setActivePage(page);
    setManualId(null);
    setOpenRequest(null);
  };

  const openRequestFrom = (id) => {
    setActivePage("requests");
    setManualId(null);
    setOpenRequest(id);
  };
  const openNotice = (notice) => {
    if (notice.proposal_id) openRequestFrom(notice.proposal_id);
  };

  const renamed = (name) => {
    localStorage.setItem("display_name", name);
    setMe((prev) => ({ ...prev, name }));
  };

  const renderPage = () => {
    if (activePage === "account") return <Account onNameChange={renamed} />;
    if (activePage === "notifications") return <NotificationsPage onOpen={openNotice} />;
    if (activePage === "monitoring") {
      return <Monitoring key={JSON.stringify(monitorStart)} start={monitorStart} />;
    }
    if (activePage === "history") return <History offices={false} onOpen={openRequestFrom} />;
    if (activePage === "deadlines") return <DeadlinesReadOnly />;
    if (activePage === "dashboard") {
      return <QmsHome me={me} onRequests={() => go("requests")}
                      onMonitoring={(start) => { setMonitorStart(start); setActivePage("monitoring"); }} />;
    }
    if (activePage === "requests") {
      return <QmsRequests onCount={onCount} openId={openRequest} onOpen={setOpenRequest} />;
    }
    return manualId ? (
      <StaffSections manualId={manualId} onBack={() => setManualId(null)} readOnly />
    ) : (
      <>
        {/* Reading comes first: this shows only when something is waiting. */}
        <NeedsAction compact onGo={() => go("requests")} />
        <StaffManuals onSelectManual={(id) => setManualId(id)} title="Manuals"
                      subtitle="Every controlled document, by series." />
      </>
    );
  };

  const name = me?.name || localStorage.getItem("display_name")
    || localStorage.getItem("username") || "";
  // The role in a word or two; the full title is long, and the sidebar is
  // not where it is read.
  const role = [me?.is_imr && "IMR", me?.is_custodian && "Document Custodian"]
    .filter(Boolean).join(" · ") || "QMS staff";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={logo} alt="QMS" />
          <div className="sidebar-brand-sub">Document control</div>
        </div>
        <div className="sidebar-eyebrow">QMS Portal</div>
        <nav className="sidebar-nav">
          <button className={`nav-item${activePage === "dashboard" ? " is-active" : ""}`}
                  onClick={() => go("dashboard")}>
            <img className="nav-icon" src={reviewIcon} alt="" />
            <span>Dashboard</span>
          </button>
          <div className="nav-group">Read documents</div>
          <button className={`nav-item${activePage === "manuals" ? " is-active" : ""}`}
                  onClick={() => go("manuals")}>
            <img className="nav-icon" src={manualsIcon} alt="" />
            <span>Manuals</span>
          </button>
          <div className="nav-group">QMS workflow</div>
          <button className={`nav-item${activePage === "requests" ? " is-active" : ""}`}
                  onClick={() => go("requests")}>
            <img className="nav-icon" src={reviewIcon} alt="" />
            <span>Requests</span>
            {waiting > 0 && (
              <span className="nav-count" title="Waiting for your decision">{waiting}</span>
            )}
          </button>
          <button className={`nav-item${activePage === "monitoring" ? " is-active" : ""}`}
                  onClick={() => go("monitoring")}>
            <img className="nav-icon" src={reviewIcon} alt="" />
            <span>Monitoring</span>
          </button>
          <button className={`nav-item${activePage === "deadlines" ? " is-active" : ""}`}
                  onClick={() => go("deadlines")}>
            <img className="nav-icon" src={reviewIcon} alt="" />
            <span>Deadlines</span>
          </button>
          <button className={`nav-item${activePage === "history" ? " is-active" : ""}`}
                  onClick={() => go("history")}>
            <img className="nav-icon" src={reviewIcon} alt="" />
            <span>History</span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <button
            type="button"
            className={`sidebar-user${activePage === "account" ? " is-active" : ""}`}
            title="My account"
            onClick={() => go("account")}
          >
            <div className="sidebar-avatar">{name.slice(0, 2)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="sidebar-username">{name}</div>
              <div className="sidebar-role">{role}</div>
            </div>
          </button>
          <button className="btn-logout" onClick={onLogout}>Sign out</button>
        </div>
      </aside>
      <div className="app-main">
        <Topbar
          crumb={CRUMBS[activePage]}
          actions={
            <NotificationBell
              onOpen={openNotice}
              onSeeAll={() => go("notifications")}
              refreshKey={activePage}
            />
          }
        />
        {/* Two rows at most: the pinned action row, then announcements. */}
        <ActionBanner onOpenProposal={openRequestFrom} refreshKey={activePage} />
        <AnnouncementBanner refreshKey={activePage} />
        <main className="app-content">
          <div className="tab-panel" key={`${activePage}-${manualId ?? ""}-${openRequest ?? ""}`}>
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
