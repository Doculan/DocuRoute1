import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";

// Relative, so the browser sends it to whichever host served the page and
// Vite's proxy forwards it. See StaffManuals for the full reasoning.
const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const TAGS = [
  { value: "", label: "All types" },
  { value: "POLICY", label: "Policies" },
  { value: "PROCEDURE", label: "Procedures" },
  { value: "RESPONSIBILITY", label: "Responsibilities" },
  { value: "WORKING INSTRUCTION", label: "Working instructions" },
];

/**
 * Sections across every manual, with search.
 *
 * My Manuals navigates by document, which is right when you know where a
 * thing lives. This is the other habit: you remember the wording but not
 * which manual holds it. Search is what makes it the faster route rather
 * than the same list one level down, so it searches content as well as
 * titles - matching a phrase inside a clause is the whole point.
 *
 * Opening a section here leads to exactly the view the My Manuals
 * drill-down reaches. One view, two routes.
 */
export default function StaffSectionSearch({ onOpenSection }) {
  const [query, setQuery] = useState("");
  const [manualFilter, setManualFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [sections, setSections] = useState([]);
  const [manuals, setManuals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const debounce = useRef(null);

  useEffect(() => {
    axios.get(`${BASE_URL}/api/staff/manuals/`, getAuth())
      .then((res) => setManuals(res.data))
      .catch(() => setManuals([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.append("search", query.trim());
      if (manualFilter) params.append("manual", manualFilter);
      if (tagFilter) params.append("tag", tagFilter);
      const res = await axios.get(
        `${BASE_URL}/api/staff/sections/?${params.toString()}`, getAuth()
      );
      setSections(res.data.results || []);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load sections.");
      setSections([]);
    } finally {
      setLoading(false);
    }
  }, [query, manualFilter, tagFilter]);

  // Typing a phrase should not fire a query per keystroke against a
  // content-wide LIKE.
  useEffect(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(load, query ? 300 : 0);
    return () => clearTimeout(debounce.current);
  }, [load, query]);

  const grouped = useMemo(() => {
    const byManual = new Map();
    for (const section of sections) {
      if (!byManual.has(section.manual)) byManual.set(section.manual, []);
      byManual.get(section.manual).push(section);
    }
    return [...byManual.entries()];
  }, [sections]);

  const filtering = Boolean(query.trim() || manualFilter || tagFilter);

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Sections</h1>
          <p className="page-subtitle">
            Search across every manual your offices work with — by section title,
            number, or the words inside it.
          </p>
        </div>
      </header>

      <div className="toc-filters" style={{ marginBottom: "1.25rem" }}>
        <input
          className="input"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search sections and their content…"
          aria-label="Search sections"
        />
        <select
          className="select"
          value={manualFilter}
          onChange={(e) => setManualFilter(e.target.value)}
          aria-label="Filter by manual"
        >
          <option value="">All manuals</option>
          {manuals.map((m) => (
            <option key={m.id} value={m.id}>{m.title}</option>
          ))}
        </select>
        <select
          className="select"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          aria-label="Filter by section type"
        >
          {TAGS.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {filtering && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => { setQuery(""); setManualFilter(""); setTagFilter(""); }}
          >
            Clear
          </button>
        )}
      </div>

      {error && <div className="alert alert-danger" style={{ marginBottom: "1.25rem" }}>{error}</div>}

      {loading ? (
        <div className="loading-row"><span className="spinner" /> Searching…</div>
      ) : sections.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">
            {filtering ? "Nothing matched that" : "No sections yet"}
          </p>
          <p className="empty-text">
            {filtering
              ? "Try fewer words, or widen the manual and type filters."
              : "No manuals are linked to your offices yet. Your administrator sets this up."}
          </p>
        </div>
      ) : (
        <>
          <p className="subtle text-xs" style={{ marginBottom: "0.75rem" }}>
            {sections.length} section{sections.length === 1 ? "" : "s"}
            {filtering ? " matched" : ""}
          </p>
          <div className="col" style={{ gap: "1.5rem" }}>
            {grouped.map(([manualTitle, rows]) => (
              <section key={manualTitle}>
                <h2 className="section-title">{manualTitle}</h2>
                <div className="col" style={{ gap: "0.5rem" }}>
                  {rows.map((section) => (
                    <button
                      key={section.id}
                      className="card card-pad card-interactive"
                      style={{ textAlign: "left", width: "100%" }}
                      onClick={() => onOpenSection(section)}
                    >
                      <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "baseline", marginBottom: "0.3rem" }}>
                        {/* A section heading is the document speaking. */}
                        <span className="doc-name">{section.subtitle}</span>
                        {section.tag && section.tag !== "UNTAGGED" && (
                          <span className="badge badge-neutral">{section.tag.toLowerCase()}</span>
                        )}
                        {section.page_number != null && (
                          <span className="subtle text-xs">p. {section.page_number}</span>
                        )}
                      </div>
                      {section.content_preview && (
                        <p className="doc-excerpt">
                          {section.content_preview}
                          {section.content_preview.length >= 220 ? "…" : ""}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
