import { useEffect, useState } from "react";
import axios from "axios";
import { formatDate, formatRevision } from "../documentStatus";
import DeadlineTag from "../DeadlineTag";
import Pager from "../Pager";
import { seriesToOpen } from "../manualPicker";
import StaffSectionSearch from "./StaffSectionSearch";

// Empty on purpose: every request goes out as a relative path, so the
// browser sends it to whatever host served the page and Vite's proxy
// (vite.config.js) forwards it to Django. That is what lets a second
// device on the LAN work - "127.0.0.1" would mean *that* device - and it
// keeps the browser on one origin, so CORS never enters into it.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

/**
 * The documents a person reads (My Manuals; the QMS Manuals list).
 *
 * Reading first (spec §11.1): what they opened last is on top, one click
 * away. Below it the series, each with its count, folded except where
 * their office owes a deadline; a series opens on its first 50. Searching
 * asks the server, so it finds a document on any page.
 */
export default function StaffManuals({
  onSelectManual, onSelectSection, title = "My Manuals",
  subtitle = "The documents your office works with — open one to read sections or propose a change.",
}) {
  const [summary, setSummary] = useState(null);
  const [error, setError]     = useState("");
  const [query, setQuery]     = useState("");
  const [needle, setNeedle]   = useState("");
  const [inSections, setInSections] = useState(false);

  useEffect(() => {
    axios.get(`${BASE_URL}/api/staff/manuals/`, getAuth())
      .then((res) => setSummary(res.data))
      .catch((err) => setError(err.response?.data?.error || "Failed to load manuals."));
  }, []);

  // Asked of the server a moment after typing stops, not on every key.
  useEffect(() => {
    const timer = setTimeout(() => setNeedle(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  if (error) {
    return <div className="alert alert-danger">{error}</div>;
  }
  if (!summary) {
    return <div className="loading-row"><span className="spinner" /> Loading your manuals…</div>;
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-subtitle">{subtitle}</p>
        </div>
      </header>

      {summary.total === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📂</div>
          <p className="empty-title">No manuals yet</p>
          <p className="empty-text">
            No documents are linked to your office yet. The system
            administrator assigns them.
          </p>
        </div>
      ) : (
        <>
          {onSelectSection && (
            <button type="button" className="link-btn text-sm" style={{ marginBottom: "0.5rem" }}
                    onClick={() => setInSections(!inSections)}>
              {inSections ? "Search manuals instead" : "Search inside sections"}
            </button>
          )}
          {inSections ? (
            <StaffSectionSearch embedded
                                onOpenSection={(s) => onSelectSection(s.manual_id, s.id)} />
          ) : (<>
          <input
            type="search"
            className="input manual-filter"
            placeholder={`Search ${summary.total.toLocaleString()} manuals by title or series…`}
            aria-label="Search manuals by title or series"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          {needle ? (
            <Paged key={needle} params={{ q: needle }} onSelectManual={onSelectManual}
                   empty={`No manuals match “${needle}”.`} />
          ) : (
            <>
              <RecentlyOpened rows={summary.recently_opened || []}
                              onSelectManual={onSelectManual} onSelectSection={onSelectSection} />
              <h2 className="section-title">By series</h2>
              <div className="col" style={{ gap: "0.5rem" }}>
                {summary.groups.map((group) => (
                  <SeriesGroup key={group.series_id ?? "none"} group={group}
                               startOpen={group === seriesToOpen(summary.groups)}
                               onSelectManual={onSelectManual} />
                ))}
              </div>
            </>
          )}
          </>)}
        </>
      )}
    </div>
  );
}

function RecentlyOpened({ rows, onSelectManual, onSelectSection }) {
  if (rows.length === 0) return null;
  return (
    <section>
      <h2 className="section-title">Recently opened</h2>
      <div className="col" style={{ gap: "0.35rem" }}>
        {rows.map((row) => (
          <button
            key={`${row.manual_id}-${row.section_id ?? "m"}`}
            type="button"
            className="link-btn"
            style={{ textAlign: "left" }}
            onClick={() => (row.section_id && onSelectSection
              ? onSelectSection(row.manual_id, row.section_id)
              : onSelectManual(row.manual_id, row.manual))}
          >
            <span className="doc-ref">{row.section || row.manual}</span>
            {row.section && <span className="subtle text-xs"> · {row.manual}</span>}
            {row.deadline && <> <DeadlineTag tag={row.deadline} /></>}
          </button>
        ))}
      </div>
    </section>
  );
}

/** One series: its count on the fold, its documents 50 at a time inside.
 *  Open from the start where the reader's office owes the most deadlines. */
function SeriesGroup({ group, startOpen, onSelectManual }) {
  const [open, setOpen] = useState(startOpen);
  const name = group.code ? `${group.code} — ${group.title}` : "Not yet in a series";
  return (
    <div className={`card accordion${group.open_deadlines > 0 ? " is-warning" : ""}`}>
      <button type="button" className="accordion-head" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span className="manual-row-title">{name}</span>
        </span>
        {group.open_deadlines > 0 && (
          <span className="badge badge-warning">
            {group.open_deadlines} with a deadline
          </span>
        )}
        <span className="subtle text-xs">
          {group.count.toLocaleString()} manual{group.count === 1 ? "" : "s"}
        </span>
        <span className={`chevron${open ? " is-open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="accordion-body">
          <Paged params={{ series: group.series_id ?? "none" }} onSelectManual={onSelectManual} />
        </div>
      )}
    </div>
  );
}

/** A page of manuals for these filters, with its pager. */
function Paged({ params, onSelectManual, empty = "Nothing here." }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const key = JSON.stringify(params);

  useEffect(() => {
    axios.get(`${BASE_URL}/api/staff/manuals/`, {
      ...getAuth(), params: { ...JSON.parse(key), page },
    })
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.error || "Failed to load manuals."));
  }, [key, page]);

  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!data) return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  if (data.results.length === 0) return <p className="subtle text-sm">{empty}</p>;
  return (
    <>
      <ManualRows rows={data.results} onSelectManual={onSelectManual} />
      <Pager paging={data} onPage={setPage} />
    </>
  );
}

function ManualRows({ rows, onSelectManual }) {
  return (
    <ul className="manual-list">
      {rows.map((manual) => (
        <li key={manual.id}>
          <button
            type="button"
            className="manual-row"
            onClick={() => onSelectManual(manual.id, manual.title)}
          >
            <span className="manual-row-main">
              <span className="manual-row-title">{manual.title}</span>
              <span className="manual-row-sub">
                {[
                  manual.series && `${manual.series} — ${manual.series_title}`,
                  manual.owner && `Owner: ${manual.owner}`,
                ].filter(Boolean).join(" · ") || "Not yet assigned to a series"}
              </span>
            </span>

            <span className="manual-row-meta">
              <DeadlineTag tag={manual.deadline} />
              {manual.relationship && (
                <span className="badge">{manual.relationship}</span>
              )}
              {manual.status && (
                <span className="badge badge-id">
                  {formatRevision(manual.status.revision)}
                </span>
              )}
              {manual.status && (
                <span className="manual-row-fact">
                  Effective {formatDate(manual.status.effective_on)}
                </span>
              )}
              <span className="manual-row-fact">
                {manual.section_count} section{manual.section_count === 1 ? "" : "s"}
              </span>
              <span className="manual-row-go" aria-hidden="true">→</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
