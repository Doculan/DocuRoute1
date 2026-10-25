/**
 * The deadline tag (spec §6.7), the one component every screen that lists
 * or opens a manual uses. The server words the label for this viewer; this
 * only shows it. Text and colour together, never colour alone. The type,
 * and for the office that owes it the admin's note, show on hover.
 */
import { freezeText } from "./deadlineText";

export default function DeadlineTag({ tag }) {
  if (!tag) return null;

  const tone = tag.muted ? "is-muted"
    : tag.state === "overdue" ? "is-overdue"
    : tag.state === "soon" || tag.state === "today" ? "is-soon"
    : "is-upcoming";
  const detail = [
    tag.type,
    tag.view === "own" ? "Advised by admin" : null,
    tag.note || null,
  ].filter(Boolean).join(" · ");

  return (
    <span className={`deadline-tag ${tone}`} title={detail}
          aria-label={detail ? `${tag.label}. ${detail}` : tag.label}>
      {tag.label}
      {tag.more > 0 && <span className="deadline-tag-more">+{tag.more} more</span>}
      {tag.frozen && (
        <span className="deadline-tag-frozen"
              title={`${freezeText(tag.frozen)}: ${tag.frozen.reason}. Overdue notices are paused.`}>
          Frozen for audit
        </span>
      )}
    </span>
  );
}
