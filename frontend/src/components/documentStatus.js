// How a document's official status reads on screen: DCR section 5, as the
// custodian recorded it. One copy for every reader screen.

// A revision is stored as written. A plain number reads "Rev. 3"; anything
// else ("Rev. 2", "A") is shown exactly as the custodian typed it.
export function formatRevision(revision) {
  if (revision == null || revision === "") return "";
  return /^\d+$/.test(String(revision).trim()) ? `Rev. ${revision}` : String(revision);
}

export function formatDate(value) {
  if (!value) return "";
  // A bare date: read it as a local day, not UTC midnight, which would
  // show the day before west of Greenwich.
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
  });
}

// "Rev. 3 · effective 24 Sep 2026" - a section's own line, or a document's.
export function revisionLine(entry) {
  if (!entry) return "";
  return `${formatRevision(entry.revision)} · effective ${formatDate(entry.effective_on)}`;
}
