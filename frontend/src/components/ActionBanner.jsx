import { useEffect, useState } from "react";
import axios from "axios";
import { dueText, freezeText } from "./deadlineText";
import DeadlineTag from "./DeadlineTag";

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

const TONE = { overdue: "is-overdue", today: "is-soon", soon: "is-soon", returned: "is-soon", later: "is-calm" };

/**
 * The pinned action row: the top banner, above announcements.
 *
 * Deadlines the office owes, most urgent first (overdue, due today, due
 * soon), and work returned to it. It has no dismiss control: the one-line
 * summary always stays, only the list folds, and it disappears for an
 * office only when the office meets its deadlines and sends its returned
 * work on. Read from the data on every navigation.
 */
export default function ActionBanner({ onOpenProposal, onOpenDeadlines, refreshKey }) {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(readExpanded);

  useEffect(() => {
    let cancelled = false;
    axios.get("/api/action-banner/", getAuth())
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (!data) return null;
  const owed = data.deadlines?.items || [];
  const owedTotal = data.deadlines?.total || 0;
  const returned = data.items || [];
  const freeze = data.freeze;
  if (owedTotal === 0 && data.total === 0 && !freeze) return null;

  const toggle = () => {
    writeExpanded(!expanded);
    setExpanded(!expanded);
  };

  const parts = [];
  if (owedTotal === 1) {
    parts.push(`${owed[0].title} · ${dueText(owed[0])}`);
  } else if (owedTotal > 1) {
    parts.push(`${owedTotal} deadlines · next: ${owed[0].title}, ${dueText(owed[0])}`);
  }
  if (data.total === 1 && owedTotal === 0) {
    parts.push(`Returned to your office: ${returned[0].manual}, by ${returned[0].by}`);
  } else if (data.total > 0) {
    parts.push(`${data.total} returned to your office`);
  }
  const listed = owedTotal + data.total > 1;
  // A change freeze is one more clause on the same line, never a row of
  // its own: the banner stays at most two rows.
  const frozen = freeze && (
    <span className="action-banner-freeze" title={freeze.reason}>
      {freezeText(freeze)}{parts.length === 0 ? ` · ${freeze.reason}` : ""}
    </span>
  );
  const openFirst = () => (owedTotal > 0
    ? onOpenDeadlines?.()
    : onOpenProposal?.(returned[0].proposal_id));

  return (
    <div className={`action-banner ${TONE[data.urgency] || "is-calm"}${expanded ? "" : " is-collapsed"}${freeze ? " is-frozen" : ""}`}
         role="status">
      <div className="action-banner-line">
        <strong>{parts.length ? "Action needed" : "Change freeze"}</strong>
        {parts.length > 0 && (
          <button type="button" className="action-banner-link" onClick={openFirst}>
            {parts.join(" · ")}
          </button>
        )}
        {frozen}
        {listed && (
          <button type="button" className="action-banner-toggle" onClick={toggle}
                  aria-expanded={expanded}>
            {expanded ? "Hide list" : "Show all"}
          </button>
        )}
      </div>
      {expanded && listed && (
        <ul className="action-banner-list">
          {owed.map((item) => (
            <li key={`d-${item.deadline_id}-${item.office}`}>
              <button type="button" className="action-banner-link" onClick={() => onOpenDeadlines?.()}>
                <strong>{dueText(item)}</strong> — {item.title}
                <span className="subtle"> · {item.type} · {item.office}</span>
                {item.manuals.length > 0 && (
                  <span className="subtle">
                    {" "}· {item.manuals.length === 1 ? item.manuals[0].title : `${item.manuals.length} manuals`}
                  </span>
                )}
              </button>
            </li>
          ))}
          {owedTotal > owed.length && (
            <li className="subtle text-xs">{owedTotal - owed.length} more deadlines</li>
          )}
          {returned.map((item) => (
            <li key={`r-${item.proposal_id}`}>
              <button type="button" className="action-banner-link"
                      onClick={() => onOpenProposal?.(item.proposal_id)}>
                {item.manual}, returned by {item.by} — redraft
              </button>
              {item.deadline && <> <DeadlineTag tag={item.deadline} /></>}
            </li>
          ))}
          {data.total > returned.length && (
            <li className="subtle text-xs">{data.total - returned.length} more returned</li>
          )}
        </ul>
      )}
    </div>
  );
}
