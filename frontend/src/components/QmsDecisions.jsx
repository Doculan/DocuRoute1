function when(value) {
  return new Date(value).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

/**
 * What the IMR and the custodian decided. A denial leads, as an alert:
 * it closes the request, and every office involved should see why
 * without looking for it. Everything else is one quiet line.
 */
export default function QmsDecisions({ decisions, documentStatus }) {
  if (!decisions || decisions.length === 0) return null;
  const denial = decisions.find((d) => d.outcome === "deny");

  return (
    <section style={{ marginTop: "1.25rem" }}>
      {denial && (
        <div className="alert alert-danger">
          <div className="strong">Denied by the IMR</div>
          <p style={{ margin: "0.35rem 0 0" }}>{denial.comments}</p>
          <div className="text-xs" style={{ marginTop: "0.35rem" }}>
            {denial.by.position}{denial.by.name && ` · ${denial.by.name}`} · {when(denial.at)}
          </div>
        </div>
      )}
      {decisions.filter((d) => d !== denial).map((d, i) => (
        <p key={i} className="text-sm" style={{ margin: "0 0 0.35rem" }}>
          <span className="strong">{d.outcome_label}</span>
          <span className="subtle text-xs">
            {` · ${d.by.position}`}{d.by.name && ` · ${d.by.name}`} · {when(d.at)}
          </span>
          {d.outcome === "effective" && documentStatus && (
            <span className="subtle" style={{ display: "block" }}>
              {documentStatus.document_number} · version {documentStatus.version} ·
              revision {documentStatus.revision} · effective {when(documentStatus.effective_on)}
            </span>
          )}
          {d.comments && (
            <span className="subtle" style={{ display: "block" }}>{d.comments}</span>
          )}
        </p>
      ))}
    </section>
  );
}
