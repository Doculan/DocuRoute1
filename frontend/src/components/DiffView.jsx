// Renders a unified diff with added/removed lines colored, so the actual
// change stands out instead of hiding among look-alike monospace lines.
export default function DiffView({ diffText, emptyText = "No changes detected." }) {
  if (!diffText) {
    return <p className="muted text-sm" style={{ padding: "0.75rem" }}>{emptyText}</p>;
  }

  return (
    <div className="diff-view">
      {diffText.split("\n").map((line, idx) => {
        const key = `${idx}-${line.slice(0, 12)}`;

        if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) {
          return <div key={key} className="diff-line is-meta">{line}</div>;
        }
        if (line.startsWith("-")) {
          return (
            <div key={key} className="diff-line is-removed">
              <span className="diff-sign">−</span><span>{line.slice(1)}</span>
            </div>
          );
        }
        if (line.startsWith("+")) {
          return (
            <div key={key} className="diff-line is-added">
              <span className="diff-sign">+</span><span>{line.slice(1)}</span>
            </div>
          );
        }
        return (
          <div key={key} className="diff-line">
            <span className="diff-sign" />
            <span>{line.startsWith(" ") ? line.slice(1) : line}</span>
          </div>
        );
      })}
    </div>
  );
}
