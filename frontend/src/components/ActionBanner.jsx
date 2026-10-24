import { useEffect, useState } from "react";
import axios from "axios";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const EXPANDED_KEY = "action_banner_expanded";

function readExpanded() {
  try { return localStorage.getItem(EXPANDED_KEY) === "1"; } catch { return false; }
}

function writeExpanded(value) {
  try { localStorage.setItem(EXPANDED_KEY, value ? "1" : "0"); } catch { /* per-viewer only */ }
}

/**
 * The action banner: work returned to your office, on every page.
 *
 * It cannot be dismissed - it goes away only when the work is sent on.
 * One line by default, naming the latest; "Show all" opens the list.
 * Read from the data on every navigation, so it is never stale and never
 * missing. Deadlines join this same row in Phase 3; announcements keep
 * their own, dismissible row.
 */
export default function ActionBanner({ onOpenProposal, refreshKey }) {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(readExpanded);

  useEffect(() => {
    let cancelled = false;
    axios.get("/api/action-banner/", getAuth())
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (!data || data.total === 0) return null;

  const toggle = () => {
    writeExpanded(!expanded);
    setExpanded(!expanded);
  };
  const [first] = data.items;
  const summary = data.total === 1
    ? `Returned to your office: ${first.manual}, by ${first.by}`
    : `${data.total} returned to your office · latest: ${first.manual}, by ${first.by}`;

  return (
    <div className={`action-banner${expanded ? "" : " is-collapsed"}`} role="status">
      <div className="action-banner-line">
        <strong>Action needed</strong>
        <button type="button" className="action-banner-link"
                onClick={() => onOpenProposal(first.proposal_id)}>
          {summary}
        </button>
        {data.total > 1 && (
          <button type="button" className="action-banner-toggle" onClick={toggle}
                  aria-expanded={expanded}>
            {expanded ? "Hide list" : "Show all"}
          </button>
        )}
      </div>
      {expanded && data.total > 1 && (
        <ul className="action-banner-list">
          {data.items.map((item) => (
            <li key={item.proposal_id}>
              <button type="button" className="action-banner-link"
                      onClick={() => onOpenProposal(item.proposal_id)}>
                {item.manual}, returned by {item.by} — redraft
              </button>
            </li>
          ))}
          {data.total > data.items.length && (
            <li className="subtle text-xs">{data.total - data.items.length} more in Proposals</li>
          )}
        </ul>
      )}
    </div>
  );
}
