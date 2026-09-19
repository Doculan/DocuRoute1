/**
 * Placeholder. Phase 3 writes the content: how a revision travels from draft
 * to approval, what the AI check is and is not, what the verdicts mean in
 * plain language, and why a reason for change is required.
 *
 * Saying "not written yet" beats an empty page, which reads as broken.
 */
export default function StaffHelp() {
  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Help</h1>
          <p className="page-subtitle">
            How the revision process works, and what the AI check means.
          </p>
        </div>
      </header>

      <div className="empty-state">
        <p className="empty-title">Not written yet</p>
        <p className="empty-text">
          This page is coming. In the meantime, the short version: you edit a
          section, run the AI check, and submit. The check is advice — you can
          submit whatever it says, and a reviewer makes the decision.
        </p>
      </div>
    </div>
  );
}
