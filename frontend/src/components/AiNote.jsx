/**
 * The AI check's note, rendered from the plain-text format Layer 4 writes
 * (Backend/ml/revision_pipeline/layer4_explain.py):
 *
 *   - parts are separated by a blank line, and open with a heading line;
 *   - "- " opens an item;
 *   - two leading spaces continue the item above;
 *   - anything else is a paragraph.
 *
 * Notes stored before this format are a single paragraph, and render as one.
 */

const HEADINGS = new Set([
  "What you changed",
  "What changed",
  "What to look at",
  "What looks fine",
  "What this check can't tell you",
]);

function parse(text) {
  const parts = [];
  for (const block of text.split(/\n\s*\n/)) {
    const lines = block.split("\n");
    const heading = HEADINGS.has(lines[0].trim()) ? lines.shift().trim() : null;
    const body = [];
    for (const line of lines) {
      if (line.startsWith("- ")) {
        body.push({ kind: "item", text: line.slice(2), details: [] });
      } else if (line.startsWith("  ") && body.length && body.at(-1).kind === "item") {
        body.at(-1).details.push(line.trim());
      } else if (line.trim()) {
        body.push({ kind: "para", text: line.trim() });
      }
    }
    parts.push({ heading, body });
  }
  return parts;
}

export default function AiNote({ text }) {
  if (!text) return null;
  const parts = parse(text);

  return (
    <div className="ai-note">
      {parts.map((part, i) => {
        const items = part.body.filter((b) => b.kind === "item");
        const paras = part.body.filter((b) => b.kind === "para");
        return (
          <div key={i} className="ai-note-part">
            {part.heading && <div className="ai-note-heading">{part.heading}</div>}
            {paras.map((p, j) => <p key={j} className="ai-note-para">{p.text}</p>)}
            {items.length > 0 && (
              <ul className="ai-note-items">
                {items.map((item, j) => (
                  <li key={j}>
                    {item.text}
                    {item.details.map((d, k) => (
                      <div key={k} className="ai-note-detail">{d}</div>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
