import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import DeadlineTag from "./DeadlineTag";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

// Often enough that a request shows up while someone is working, rarely
// enough to be no load at all. Also re-read on every navigation.
const POLL_MS = 60000;

function ago(value) {
  const minutes = Math.round((Date.now() - new Date(value)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(value).toLocaleDateString("en-PH", { month: "short", day: "numeric" });
}

/**
 * The bell, in every portal.
 *
 * The count is the server's: unread info, plus action not yet done. An
 * action notice stays counted after it is read, until someone does the
 * thing - so the number means "still to do", not "not yet seen". Opening a
 * notice marks it read and hands its target to the portal.
 */
export default function NotificationBell({ onOpen, onSeeAll, refreshKey }) {
  const [data, setData] = useState({ unread: 0, notifications: [] });
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await axios.get("/api/notifications/", getAuth());
      setData(res.data);
    } catch {
      // A bell that cannot load stays quiet rather than raising an error.
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load, refreshKey]);

  // Close on a click outside, or Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const markAll = async () => {
    try {
      await axios.post("/api/notifications/read/", {}, getAuth());
    } finally {
      load();
    }
  };

  const pick = async (notice) => {
    setOpen(false);
    onOpen?.(notice);
    try {
      await axios.post("/api/notifications/read/", { ids: [notice.id] }, getAuth());
    } finally {
      load();
    }
  };

  const { unread, notifications } = data;

  return (
    <div className="notif" ref={wrap}>
      <button
        className="topbar-btn"
        type="button"
        title="Notifications"
        aria-label={unread ? `${unread} notifications to see or do` : "Notifications"}
        aria-expanded={open}
        onClick={() => { setOpen((v) => !v); if (!open) load(); }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round"
             strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="topbar-dot">{unread > 99 ? "99+" : unread}</span>
        )}
      </button>

      {open && (
        <div className="notif-panel" role="dialog" aria-label="Notifications">
          <div className="notif-head">
            <strong>Notifications</strong>
            <span className="row" style={{ gap: "0.75rem" }}>
              {notifications.some((n) => !n.read) && (
                <button type="button" className="notif-link" onClick={markAll}>
                  Mark all read
                </button>
              )}
              {onSeeAll && (
                <button type="button" className="notif-link"
                        onClick={() => { setOpen(false); onSeeAll(); }}>
                  See all
                </button>
              )}
            </span>
          </div>
          {notifications.length === 0 ? (
            <p className="notif-empty">Nothing yet.</p>
          ) : (
            <ul className="notif-list">
              {notifications.slice(0, 8).map((n) => (
                <li key={n.id}>
                  <NoticeButton notice={n} onPick={pick} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** One notice. Action required is marked in words, not colour alone, and
 *  says Done once someone has done it. */
export function NoticeButton({ notice, onPick }) {
  const pending = notice.severity === "action" && !notice.acted;
  return (
    <button
      type="button"
      className={`notif-item${notice.read && !pending ? "" : " is-unread"}`}
      onClick={() => onPick(notice)}
    >
      {notice.severity === "action" && (
        <span className={`status-mark is-${notice.acted ? "approved" : "pending"}`}>
          {notice.acted ? "Done" : "Action required"}
        </span>
      )}
      <span className="notif-msg">{notice.title}</span>
      {notice.body && <span className="notif-detail">{notice.body}</span>}
      {/* A deadline notice already says the date; the tag would repeat it. */}
      {notice.kind !== "deadline_set" && <DeadlineTag tag={notice.deadline} />}
      <span className="notif-at">{ago(notice.created_at)}</span>
    </button>
  );
}
