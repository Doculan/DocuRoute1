/**
 * A diff marked up the way an editor marks a proof.
 *
 * `DiffView` renders the same unified diff as coloured monospace bands,
 * which is the right thing when you are reading a change as data. This is
 * for reading it as a document: serif, struck-through removals and
 * underlined insertions in ink, and a rule down the margin where the page
 * was touched — the mark a person makes, rather than a highlight a machine
 * computes.
 *
 * Both exist on purpose. The reviewer's screen keeps the technical view;
 * the staff side reads its own manual.
 */
export default function DocDiff({ diffText, emptyText = "No changes recorded." }) {
  if (!diffText) {
    return <p className="muted text-sm" style={{ padding: "0.75rem" }}>{emptyText}</p>;
  }

  const lines = diffText.split("\n").filter(
    (line) => !(line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@"))
  );

  return (
    <div className="doc-diff">
      {lines.map((line, idx) => {
        const key = `${idx}-${line.slice(0, 12)}`;

        if (line.startsWith("-")) {
          return (
            <div key={key} className="diff-line is-changed">
              <del>{line.slice(1) || " "}</del>
            </div>
          );
        }
        if (line.startsWith("+")) {
          return (
            <div key={key} className="diff-line is-changed">
              <ins>{line.slice(1) || " "}</ins>
            </div>
          );
        }
        // Unchanged context: present, but not competing for attention.
        return (
          <div key={key} className="diff-line">
            {line.startsWith(" ") ? line.slice(1) : line}
          </div>
        );
      })}
    </div>
  );
}
