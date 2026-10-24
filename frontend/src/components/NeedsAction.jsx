import { useEffect, useState } from "react";
import axios from "axios";
import DeadlineTag from "./DeadlineTag";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

function since(value) {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value)) / 86400000);
  if (days < 1) return "today";
  return days === 1 ? "1 day" : `${days} days`;
}

/**
 * Needs your action: what is waiting on this person, read from the data.
 *
 * Shared by every portal. Derived on the server from the state of
 * proposals and posts, not from notifications, so nothing missed or marked
 * read can hide here. Shows nothing at all when nothing is waiting.
 *
 * `compact` shows each section as a count that opens its screen, for a
 * landing where reading must not be pushed down the page (the QMS portal);
 * the lists themselves live on that screen.
 *
 * Otherwise, by the spec's density rules (§11.1): a section lists rows only
 * where this person can act, and only the first few; one where they can
 * only wait - an Encoder whose Head must act - is a count.
 */
const ROWS = 5;

export default function NeedsAction({ onOpenProposal, onGo, refreshKey, compact = false }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get("/api/needs-action/", getAuth())
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (!data || data.total === 0) return null;

  return (
    <section style={{ marginBottom: "1.75rem" }}>
      <h2 className="section-title">Needs your action</h2>
      <div className={compact ? "row-wrap" : "col"} style={{ gap: compact ? "0.6rem" : "1rem" }}>
        {data.sections.map((section) => {
          const actionable = section.items.filter((i) => i.severity === "action").slice(0, ROWS);
          return (
          <div key={section.key}>
            {compact || actionable.length === 0 ? (
              <button className="card card-pad card-interactive row"
                      style={{ gap: "0.75rem", alignItems: "center", textAlign: "left",
                               width: compact ? "auto" : "100%" }}
                      onClick={() => onGo?.(section.go || "proposals")}>
                <span className="badge badge-warning">{section.total}</span>
                <span className="text-sm">{section.title}</span>
              </button>
            ) : (
              <>
                <div className="subtle text-xs" style={{ marginBottom: "0.3rem" }}>
                  {section.title} · {section.total}
                </div>
                <div className="col" style={{ gap: "0.15rem" }}>
                  {actionable.map((item) => (
                    <button key={`${section.key}-${item.proposal_id}-${item.office}`}
                            className="series-row"
                            onClick={() => onOpenProposal?.(item.proposal_id)}>
                      <span className="series-code">{item.manual}</span>
                      <span className="series-title">
                        {item.dcr_number ? `${item.dcr_number} · ` : ""}{item.office}
                        {item.deadline && <> <DeadlineTag tag={item.deadline} /></>}
                      </span>
                      <span className={`status-mark is-${item.severity === "action" ? "pending" : "approved"}`}>
                        {item.label}
                      </span>
                      <span className="subtle text-xs">{since(item.since)}</span>
                    </button>
                  ))}
                </div>
                {section.total > actionable.length && (
                  <button className="link-btn text-xs" onClick={() => onGo?.(section.go || "proposals")}>
                    {section.total - actionable.length} more
                  </button>
                )}
              </>
            )}
          </div>
          );
        })}
      </div>
    </section>
  );
}
