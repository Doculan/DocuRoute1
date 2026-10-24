import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import StaffManuals from "../staff/StaffManuals";
import StaffSections from "../staff/StaffSections";
import QmsRequests from "./QmsRequests";
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
  manuals: "Manuals", requests: "Requests", account: "My account",
  notifications: "Notifications",
};

/**
 * The QMS portal: the IMR and the Document Custodian.
 *
 * Reading comes first here too - the custodian keeps every document and
 * both read them daily - so it opens on the manuals, read only. Requests
 * sit beside them, with a count only when something is actually waiting.
 * What someone may *decide* comes from the position they hold, which the
 * server checks; this portal only shows the way.
 */
export default function QmsDashboard({ onLogout }) {
  const [activePage, setActivePage] = useState("manuals");
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
        setWaiting(queue.imr.length + (queue.approval?.length || 0) + queue.custodian.length);
      } catch {
        // The pages report their own errors; the sidebar can do without.
      }
    })();
  }, []);

  const onCount = useCallback((n) => setWaiting(n), []);

  const go = (page) => {
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
    if (activePage === "requests") {
      return <QmsRequests onCount={onCount} openId={openRequest} onOpen={setOpenRequest} />;
    }
    return manualId ? (
      <StaffSections manualId={manualId} onBack={() => setManualId(null)} readOnly />
    ) : (
      <>
        {/* Reading comes first: this shows only when something is waiting. */}
        <NeedsAction compact onGo={() => go("requests")} />
        <StaffManuals onSelectManual={(id) => setManualId(id)} />
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
