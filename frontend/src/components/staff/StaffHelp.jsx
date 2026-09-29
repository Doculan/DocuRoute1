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
          It reads each changed section against the rest of the document and
          writes a short note: what you changed, what the offices reviewing
          it are likely to look at, and why.
        </p>
        <p>
          <strong>It is advice, not a decision.</strong> Three things follow
          from that:
        </p>
        <ul className="help-list">
          <li>
            <strong>Running it is required; what it says is not.</strong> Each
            changed section needs a current check before the proposal can be
            submitted. Nothing in the note stops you submitting.
          </li>
          <li>
            <strong>It never changes anything.</strong> People decide: the
            concurring offices, the IMR and the approving authority.
          </li>
          <li>
            <strong>Everyone reads the same check.</strong> It is saved when it
            runs and never re-run, so the offices reviewing your proposal read
            the findings you read, addressed to them.
          </li>
        </ul>
        <p>
          If you edit a section after checking it, check it again: the old
          note no longer describes the text.
        </p>
      </section>

      <section>
        <h2 className="section-title">Reading the note</h2>
        <dl className="help-defs">
          <dt>What you changed</dt>
          <dd>
            The edit itself: where it is, how large, and the exact words when
            they are short.
          </dd>

          <dt>What to look at</dt>
          <dd>
            Each concern, most significant first: what changed, why it matters
            to the people who use the document, what you are likely to be
            asked, and the ISO 9001 clause it touches. A concern the check&rsquo;s
            own rules could not confirm says so, and may be a false lead.
          </dd>

          <dt>What looks fine</dt>
          <dd>
            What the check counted and found unchanged, such as the figures or
            the roles named.
          </dd>

          <dt>What this check can&rsquo;t tell you</dt>
          <dd>
            The questions only people can answer, such as whether a new figure
            matches its memorandum, or whether an office has agreed to take on
            a step.
          </dd>
        </dl>
        <p>
          There is no pass or fail. Treat each concern as <strong>a pointer to
          check</strong>, not a ruling; the wording says how firm it is.
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
          reason cannot talk it out of a concern — and a plain one
          cannot count against you.
        </p>
      </section>
    </div>
  );
}
