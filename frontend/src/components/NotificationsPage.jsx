import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { NoticeButton } from "./NotificationBell";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const FILTERS = [
  ["action", "Action required"],
  ["info", "Info"],
  ["all", "All"],
];

/**
 * Every notification, filtered and paged on the server. The same page in
 * every portal; what opening one does is the portal's business (`onOpen`).
 */
export default function NotificationsPage({ onOpen }) {
  const [filter, setFilter] = useState("action");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await axios.get("/api/notifications/",
        { ...getAuth(), params: { filter, page } });
      setData(res.data);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load notifications.");
    }
  }, [filter, page]);

  useEffect(() => { load(); }, [load]);

  const pick = async (notice) => {
    onOpen?.(notice);
    try {
      await axios.post("/api/notifications/read/", { ids: [notice.id] }, getAuth());
    } catch {
      // Opening still works if the read mark does not stick.
    }
  };

  const markAll = async () => {
    try {
      await axios.post("/api/notifications/read/", {}, getAuth());
    } finally {
      load();
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Notifications</h1>
          <p className="page-subtitle">Action required stays here until it is done.</p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={markAll}>Mark all read</button>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="tabs">
        {FILTERS.map(([key, label]) => (
          <button key={key} className={`tab${filter === key ? " is-active" : ""}`}
                  onClick={() => { setFilter(key); setPage(1); }}>
            {label}
          </button>
        ))}
      </div>

      {!data ? (
        <div className="loading-row"><span className="spinner" /> Loading…</div>
      ) : data.count === 0 ? (
        <div className="empty-state">
          <p className="empty-title">
            {filter === "action" ? "Nothing to do" : "No notifications"}
          </p>
          <p className="empty-text">
            Requests, returns and decisions on your offices' work appear here.
          </p>
        </div>
      ) : (
        <>
          <ul className="notif-list notif-page">
            {data.notifications.map((n) => (
              <li key={n.id}><NoticeButton notice={n} onPick={pick} /></li>
            ))}
          </ul>
          {data.pages > 1 && (
            <div className="row" style={{ gap: "0.75rem", alignItems: "center", marginTop: "1rem" }}>
              <button className="btn btn-ghost btn-sm" disabled={page <= 1}
                      onClick={() => setPage(page - 1)}>Previous</button>
              <span className="subtle text-xs">Page {data.page} of {data.pages}</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= data.pages}
                      onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
