import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import DiffView from "../DiffView";

const BASE_URL = "";

const getAuth = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
});

const STATUS_LABEL = {
  draft: "Draft",
  concurrence: "Out for concurrence",
  locked: "Locked",
  withdrawn: "Withdrawn",
};

function when(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * Every proposal, read only.
 *
 * The system admin and QMS staff watch the process; they do not take part
 * in it. So there is nothing to click here but a proposal — no submit, no
 * concur, no withdraw. Those belong to the offices, and putting them on
 * this screen would blur which of the two jobs somebody was doing.
 *
 * The reviewer's technical diff, not the submitter's marked-up one: this
 * audience is checking what changed, not reading the document.
 */
export default function Proposals() {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("open");

  const load = useCallback(async () => {
    try {
      // The dashboard summary already carries the recent ones; this asks
      // for the list a watcher actually wants.
      const { data } = await axios.get(
        `${BASE_URL}/api/admin/dashboard/`, getAuth()
      );
      setRows(data.proposals || []);
      setError("");
    } catch (err) {
      setError(err.response?.data?.error || "Could not load proposals.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (open != null) {
    return <ProposalDetail proposalId={open} onBack={() => setOpen(null)} />;
  }

  if (!rows) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  const shown = filter === "all"
    ? rows
    : rows.filter((r) => r.status === "draft" || r.status === "concurrence");

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Proposals</h1>
          <p className="page-subtitle">
            What the offices are changing, and how far each has got.
          </p>
        </div>
      </header>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="tabs">
        <button className={`tab${filter === "open" ? " is-active" : ""}`}
                onClick={() => setFilter("open")}>
          In progress
        </button>
        <button className={`tab${filter === "all" ? " is-active" : ""}`}
                onClick={() => setFilter("all")}>
          All
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">
            {filter === "open" ? "Nothing in progress" : "No proposals yet"}
          </p>
          <p className="empty-text">
            Offices draft proposals against the documents they concur on.
          </p>
        </div>
      ) : (
        <div className="col" style={{ gap: "0.15rem" }}>
          {shown.map((p) => (
            <button key={p.id} className="series-row" onClick={() => setOpen(p.id)}>
              <span className="series-code">{p.manual}</span>
              <span className="series-title">from {p.office}</span>
              <span className="subtle text-xs">
                {p.status === "concurrence"
                  ? `${p.concurred} of ${p.of} concurred`
                  : `version ${p.version}`}
              </span>
              <span className={`status-mark is-${
                p.status === "locked" ? "approved"
                  : p.status === "withdrawn" ? "returned" : "pending"}`}>
                {STATUS_LABEL[p.status]}
              </span>
              <span className="subtle text-xs">{when(p.updated_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalDetail({ proposalId, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data: full } = await axios.get(
          `${BASE_URL}/api/proposals/${proposalId}/full/`, getAuth()
        );
        setData(full);
      } catch (err) {
        setError(err.response?.data?.error || "Could not load this proposal.");
      }
    })();
  }, [proposalId]);

  if (error) {
    return (
      <div>
        <button className="link-btn" onClick={onBack}>← Proposals</button>
        <div className="alert alert-danger" style={{ marginTop: "1rem" }}>{error}</div>
      </div>
    );
  }
  if (!data) {
    return <div className="loading-row"><span className="spinner" /> Loading…</div>;
  }

  return (
    <div>
      <button className="link-btn" onClick={onBack}>← Proposals</button>

      <header className="page-head" style={{ marginTop: "0.6rem" }}>
        <div>
          <h1 className="page-title">{data.manual}</h1>
          <p className="page-subtitle">
            {STATUS_LABEL[data.status]} · version {data.version} ·
            {" "}from {data.initiating_office}
          </p>
        </div>
      </header>

      <section>
        <h2 className="section-title">Reason for the change</h2>
        <p className="text-sm" style={{ margin: 0, color: "var(--n-700)" }}>
          {data.overall_reason || <span className="subtle">Not given yet.</span>}
        </p>
      </section>

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">
          Changed sections
          <span className="subtle text-xs" style={{ marginLeft: "0.5rem" }}>
            {data.changed_sections}
          </span>
        </h2>
        <div className="col" style={{ gap: "1.1rem" }}>
          {data.sections.filter((s) => s.has_changed).map((s) => (
            <div key={s.section_id}>
              <div className="row-wrap" style={{ gap: "0.5rem", alignItems: "baseline" }}>
                <span className="doc-ref">{s.subtitle}</span>
                {s.assessment && (
                  <span className="subtle text-xs">
                    check: {s.assessment.verdict}
                    {s.assessment.stale && " — section changed since" }
                  </span>
                )}
              </div>
              <DiffView diffText={s.diff_text} />
              {s.assessment?.coordinated_change && (
                <p className="subtle text-xs" style={{ marginTop: "0.3rem" }}>
                  {s.assessment.coordinated_change}
                </p>
              )}
            </div>
          ))}
        </div>
      </section>

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">Offices</h2>
        <div className="col" style={{ gap: "0.25rem" }}>
          {data.participants.map((p) => (
            <div key={`${p.office_id}-${p.role}`} className="row"
                 style={{ gap: "0.6rem", alignItems: "baseline" }}>
              <span className="text-sm">{p.office}</span>
              <span className="subtle text-xs">
                {p.role === "approving" ? "signs" : "must agree"}
              </span>
              {p.decision === "concur" && (
                <span className="status-mark is-approved">Concurred</span>
              )}
              {p.decision === "return" && (
                <span className="status-mark is-returned">Returned</span>
              )}
            </div>
          ))}
        </div>
      </section>

      <section style={{ marginTop: "1.75rem" }}>
        <h2 className="section-title">History</h2>
        <div className="col" style={{ gap: "0.2rem" }}>
          {data.events.map((e, i) => (
            <div key={i} className="row" style={{ gap: "0.6rem", alignItems: "baseline" }}>
              <span className="text-sm">{e.label}</span>
              <span className="subtle text-xs">
                {e.office} · {e.actor} · {when(e.at)}
              </span>
              {e.detail && <span className="subtle text-xs">— {e.detail}</span>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
