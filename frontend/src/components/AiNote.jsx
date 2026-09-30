import { useEffect, useMemo, useState } from "react";

/**
 * The AI check's note.
 *
 * Current notes are prose: paragraphs separated by a blank line
 * (Backend/ml/revision_pipeline/layer4_wording.yaml). Notes stored earlier
 * are still shown as they were written: the heading format of 2026-09-29
 * ("What you changed", items opened by "- "), or a single paragraph.
 *
 * `reveal`: stream the words in, the first time this viewer sees this note
 * (keyed by `noteId`). About 30 words a second, a "Show all" to skip, and
 * never under prefers-reduced-motion. Whether a note has been seen is a
 * per-browser convenience; if storage is unavailable the note just appears.
 */

const HEADINGS = new Set([
  "What you changed",
  "What changed",
  "What to look at",
  "What looks fine",
  "What this check can't tell you",
]);

const WORDS_PER_SECOND = 30;
const SEEN_KEY = "docuroute.seenNotes";

function parseHeadingFormat(text) {
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

function isHeadingFormat(text) {
  return HEADINGS.has(text.trimStart().split("\n", 1)[0].trim());
}

function seenNotes() {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function markSeen(id) {
  try {
    const seen = [...seenNotes(), id].slice(-500);
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  } catch {
    /* no storage: the note simply does not animate next time either */
  }
}

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function HeadingNote({ text }) {
  const parts = parseHeadingFormat(text);
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

export default function AiNote({ text, noteId, reveal = false }) {
  const paragraphs = useMemo(
    () => (text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean),
    [text],
  );
  const words = useMemo(() => paragraphs.map((p) => p.split(/\s+/)), [paragraphs]);
  const total = useMemo(() => words.reduce((n, w) => n + w.length, 0), [words]);

  // Decided once, when the note mounts (callers key AiNote by note id):
  // stream only if asked to, not seen before in this browser, and motion
  // is welcome.
  const [animate] = useState(
    () => Boolean(reveal && noteId && !seenNotes().has(noteId) && !prefersReducedMotion()),
  );
  const [shown, setShown] = useState(0);
  const [skipped, setSkipped] = useState(false);
  const streaming = animate && !skipped && shown < total;

  useEffect(() => {
    if (reveal && noteId) markSeen(noteId);
  }, [reveal, noteId]);

  useEffect(() => {
    if (!streaming) return undefined;
    const timer = setTimeout(() => setShown((n) => n + 1), 1000 / WORDS_PER_SECOND);
    return () => clearTimeout(timer);
  }, [streaming, shown]);

  if (!text) return null;
  if (isHeadingFormat(text)) return <HeadingNote text={text} />;

  const limit = streaming ? shown : total;
  const starts = words.map((_, i) => words.slice(0, i).reduce((n, w) => n + w.length, 0));
  return (
    <div className="ai-note" aria-live="off">
      {words.map((paragraphWords, i) => (
        starts[i] < limit ? (
          <p key={i} className="ai-note-para">
            {paragraphWords.slice(0, limit - starts[i]).join(" ")}
          </p>
        ) : null
      ))}
      {streaming && (
        <button
          type="button"
          className="btn btn-ghost btn-sm ai-note-skip"
          onClick={() => setSkipped(true)}
        >
          Show all
        </button>
      )}
      {/* The whole note for screen readers, whatever the animation shows. */}
      {streaming && <span className="sr-only">{paragraphs.join(" ")}</span>}
    </div>
  );
}
