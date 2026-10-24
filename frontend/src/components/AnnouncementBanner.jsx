import { useEffect, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/** One announcement, with its own Dismiss. */
function Item({ item, onDismiss }) {
  return (
    <div className="announcement-item">
      <div style={{ minWidth: 0 }}>
        <strong>{item.title}</strong>
        {item.body && <span className="announcement-body"> — {item.body}</span>}
      </div>
      <button type="button" className="announcement-dismiss" onClick={() => onDismiss(item.id)}
              aria-label={`Dismiss "${item.title}"`}>
        Dismiss
      </button>
    </div>
  );
}

/**
 * The announcement row: beneath the pinned action row, neutral, and
 * dismissible per person. The newest shows, with "n more" opening the
 * rest; each closes on its own.
 */
export default function AnnouncementBanner({ refreshKey }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get("/api/announcement-banner/", getAuth())
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (!data || data.items.length === 0) return null;

  const dismiss = async (id) => {
    setData((d) => ({ ...d, total: d.total - 1, items: d.items.filter((a) => a.id !== id) }));
    try {
      await axios.post(`/api/staff/announcements/${id}/dismiss/`, {}, getAuth());
    } catch {
      // Closing a banner is not worth an error if the note does not stick.
    }
  };

  const [first, ...rest] = data.items;
  const more = data.total - 1;

  return (
    <div className="announcement-banner" role="note">
      <Item item={first} onDismiss={dismiss} />
      {more > 0 && !open && (
        <button type="button" className="announcement-more" onClick={() => setOpen(true)}>
          {more} more
        </button>
      )}
      {open && rest.map((item) => <Item key={item.id} item={item} onDismiss={dismiss} />)}
    </div>
  );
}
