/**
 * Static page, no backend.
 *
 * Written for someone who has just been told the AI check is mandatory and
 * wants to know whether it can stop them. It cannot, and saying so plainly
 * is most of the job: a check people believe is a gate becomes something
 * they try to game rather than read.
 */
export default function StaffHelp() {
  return (
    <div className="prose-col">
      <header className="page-head">
        <div>
          <h1 className="page-title">Help</h1>
          <p className="page-subtitle">
            How a revision travels from your edit to an approved document, and
            what the AI check is for.
          </p>
        </div>
      </header>

      <section>
        <h2 className="section-title">How a revision travels</h2>
        <ol className="help-steps">
          <li>
            <strong>You edit a section.</strong> Open a manual from My Manuals,
            or find the section directly from Sections, and propose a change —
            edited text, an uploaded file, or a merge of two sections.
          </li>
          <li>
            <strong>You give a reason.</strong> A sentence saying what changed
            and why. This is required before anything else happens.
          </li>
          <li>
            <strong>You run the AI check</strong> and read what it says. This
            is required too — but only running it is required, not agreeing
            with it.
          </li>
          <li>
            <strong>You submit.</strong> Whatever the check said. The result is
            stored with your revision, so the reviewer reads exactly what you
            read.
          </li>
          <li>
            <strong>A reviewer decides.</strong> Approved, or sent back with a
            note explaining what to change. You will see it in My Revisions,
            and the tab shows a count when there is feedback you have not
            opened.
          </li>
        </ol>
      </section>

      <section>
        <h2 className="section-title">What the AI check is</h2>
        <p>
          It reads your change against the rest of the document and points at
          things a reviewer is likely to ask about — an obligation that became
          optional, a figure that moved, a role that changed, wording that
          conflicts with another section.
        </p>
        <p>
          <strong>It is advice, not a decision.</strong> Three things follow
          from that, and they are worth being precise about:
        </p>
        <ul className="help-list">
          <li>
            <strong>Running it is required; passing it is not.</strong> The
            submit button stays locked until you have run the check, and then
            unlocks whatever the verdict was. You can submit a change the
            check would reject.
          </li>
          <li>
            <strong>It never changes anything.</strong> It does not approve,
            reject, or alter your revision. A person decides.
          </li>
          <li>
            <strong>The reviewer sees the same result you did.</strong> It is
            saved at the moment you submit and never re-run afterwards, so
            there is only ever one assessment of a revision — no second
            opinion appearing behind you.
          </li>
        </ul>
        <p>
          If you edit after checking, the result no longer describes what you
          are submitting, so you will be asked to check again. That is the
          only reason it ever blocks you.
        </p>
      </section>

      <section>
        <h2 className="section-title">What the verdicts mean</h2>
        <dl className="help-defs">
          <dt>Looks fine</dt>
          <dd>
            Nothing stood out. Submit it. This is not a guarantee of approval —
            the reviewer may know something the check cannot.
          </dd>

          <dt>Would likely need changes</dt>
          <dd>
            Something in the change is the kind of thing reviewers usually send
            back. Worth a second look before you submit, but if you are
            confident, submit and say why in your reason.
          </dd>

          <dt>Would likely be rejected</dt>
          <dd>
            The change looks like it removes or weakens something the document
            relies on. Read the concerns before deciding. You can still submit.
          </dd>
        </dl>
        <p>
          Each concern names a clause and quotes the words it is about. Treat a
          concern as <strong>a pointer to check</strong>, not a ruling — it is
          telling you where to look, and it can be pointing at the wrong thing.
          The verdict is more reliable than the label attached to it.
        </p>
      </section>

      <section>
        <h2 className="section-title">Why a reason for change is required</h2>
        <p>
          ISO 9001 clause 6.3 expects changes to a controlled document to be
          planned, and the record of that plan is your reason. It is what a
          reviewer reads first and what an auditor looks for later, which is
          why a placeholder like &ldquo;update&rdquo; is refused: it records
          that something happened without recording what or why.
        </p>
        <p>
          Write what changed and why, in a sentence. Naming a date, a
          memorandum or a person is what makes it useful a year from now.
        </p>
        <p className="subtle">
          The reason is never given to the AI check as evidence. It judges the
          text of your change and the document around it, so a well-written
          reason cannot talk it into approving a change — and a plain one
          cannot count against you.
        </p>
      </section>
    </div>
  );
}
