import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

// Often enough that a concurrence shows up while someone is working,
// rarely enough to be no load at all.
const POLL_MS = 60000;

function ago(value) {
  const minutes = Math.round((Date.now() - new Date(value)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(value).toLocaleDateString("en-PH", {
    month: "short", day: "numeric",
  });
}

/**
 * The inbox: what other offices have done on proposals that involve yours.
 *
 * The bell shows a count only while something is unread. Opening a notice
 * opens its proposal and marks that proposal's notices read; the count is
 * then fetched again, so it is always the server's, never guessed here.
 */
export default function NotificationBell({ onOpenProposal, refreshKey }) {
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
    onOpenProposal?.(notice.proposal_id);
    try {
      await axios.post(
        "/api/notifications/read/", { proposal_id: notice.proposal_id }, getAuth()
      );
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
        aria-label={unread ? `${unread} unread notifications` : "Notifications"}
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
            {unread > 0 && (
              <button type="button" className="notif-link" onClick={markAll}>
                Mark all read
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="notif-empty">Nothing yet.</p>
          ) : (
            <ul className="notif-list">
              {notifications.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    className={`notif-item${n.read ? "" : " is-unread"}`}
                    onClick={() => pick(n)}
                  >
                    <span className="notif-msg">{n.message}</span>
                    {n.detail && <span className="notif-detail">“{n.detail}”</span>}
                    <span className="notif-at">{ago(n.at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
