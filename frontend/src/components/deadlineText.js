// How a deadline's timing is said, in words - never colour alone (§6.7).
// Shared by the action row, the Deadlines panel and page, and the admin.

function day(value) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric" });
}

/** When, in words - never colour alone. */
export function dueText(item) {
  if (item.urgency === "overdue") {
    const late = -item.days;
    return `Overdue · was due ${day(item.due_on)} (${late} day${late === 1 ? "" : "s"})`;
  }
  if (item.urgency === "today") return "Due today";
  if (item.urgency === "soon") return `Due ${day(item.due_on)} · ${item.days} day${item.days === 1 ? "" : "s"}`;
  return `Due ${day(item.due_on)}`;
}

/** A change freeze (3D): why an action waits, and until when. */
export function freezeText(freeze) {
  const until = new Date(`${freeze.expected_end_on}T00:00:00`)
    .toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
  return `Frozen for audit until ${until}`;
}

export { day };
