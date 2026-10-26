import useServerData from "../useServerData";
import OfficesChart from "../OfficesChart";

/**
 * The QMS landing (spec §7.7): your queue as counts only - the IMR's and
 * the Custodian's differ, from their positions - then the offices chart,
 * overdue and stalled across the institution, and Advised revisions.
 * Each count opens its list: queues on Requests, the rest in Monitoring.
 */
export default function QmsHome({ me, onRequests, onMonitoring }) {
  const { data: queue } = useServerData("/api/qms/queue/");
  const { data: overview } = useServerData("/api/monitoring/overview/");
  const totals = queue?.totals || {};
  const counts = overview?.counts || {};

  const mine = [
    me?.is_imr && ["Ready for your decision", totals.imr, "imr"],
    me?.is_imr && ["Signed DCR to upload", totals.approval, "approval"],
    me?.is_custodian && ["With you to make effective", totals.custodian, "custodian"],
  ].filter(Boolean);

  const institution = [
    ["Overdue", counts.overdue, "deadline obligations past their due date", "is-danger", { bucket: "overdue" }],
    ["Stalled", counts.stalled, "past their stage limit, as of now", "is-warning", { bucket: "stalled" }],
    ["Advised revisions", counts.advised, "still open", "", { lens: "advised" }],
  ];

  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Your queue, then the whole institution.</p>
        </div>
      </header>

      {mine.length > 0 && (
        <section>
          <h2 className="section-title">Your queue</h2>
          <div className="stat-grid monitor-tiles">
            {mine.map(([label, n, key]) => (
              <button key={key} type="button" className={`stat-card ${n ? "is-warning" : ""}`}
                      onClick={onRequests}>
                <div className="stat-value">{queue ? n : "…"}</div>
                <div className="stat-label">{label}</div>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="monitor-section">
        <h2 className="section-title">Across the institution</h2>
        <div className="stat-grid monitor-tiles">
          {institution.map(([label, n, note, tone, open]) => (
            <button key={label} type="button" className={`stat-card ${n ? tone : ""}`}
                    disabled={!n} onClick={() => onMonitoring(open)}>
              <div className="stat-value">{overview ? n : "…"}</div>
              <div className="stat-label">{label}</div>
              <div className="subtle text-xs">{note}</div>
            </button>
          ))}
        </div>
      </section>

      <OfficesChart title="Requests by office"
                    onOpen={(bar) => onMonitoring({ bucket: "open", office: bar.office_id,
                                                    officeName: bar.office })} />
    </div>
  );
}
