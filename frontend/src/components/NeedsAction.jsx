import { useEffect, useState } from "react";
import axios from "axios";

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
 */
export default function NeedsAction({ onOpenProposal, onGo, refreshKey }) {
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
      <div className="col" style={{ gap: "1rem" }}>
        {data.sections.map((section) => (
          <div key={section.key}>
            {section.items.length === 0 ? (
              <button className="card card-pad card-interactive row"
                      style={{ gap: "0.75rem", alignItems: "center", width: "100%", textAlign: "left" }}
                      onClick={() => onGo?.(section.go)}>
                <span className="badge badge-warning">{section.total}</span>
                <span className="text-sm">{section.title}</span>
              </button>
            ) : (
              <>
                <div className="subtle text-xs" style={{ marginBottom: "0.3rem" }}>
                  {section.title} · {section.total}
                </div>
                <div className="col" style={{ gap: "0.15rem" }}>
                  {section.items.map((item) => (
                    <button key={`${section.key}-${item.proposal_id}-${item.office}`}
                            className="series-row"
                            onClick={() => onOpenProposal?.(item.proposal_id)}>
                      <span className="series-code">{item.manual}</span>
                      <span className="series-title">
                        {item.dcr_number ? `${item.dcr_number} · ` : ""}{item.office}
                      </span>
                      <span className={`status-mark is-${item.severity === "action" ? "pending" : "approved"}`}>
                        {item.label}
                      </span>
                      <span className="subtle text-xs">{since(item.since)}</span>
                    </button>
                  ))}
                </div>
                {section.total > section.items.length && (
                  <span className="subtle text-xs">
                    {section.total - section.items.length} more
                  </span>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
