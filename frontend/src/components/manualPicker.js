/**
 * A `?picker=1` list of manuals (id, title, series_code, ordered by series)
 * as [series, rows] pairs for <optgroup>s: a drop-down of thousands is
 * only usable grouped (spec §11.1).
 */
export function bySeries(manuals) {
  const groups = new Map();
  for (const manual of manuals) {
    const code = manual.series_code || "Not in a series";
    if (!groups.has(code)) groups.set(code, []);
    groups.get(code).push(manual);
  }
  return [...groups.entries()];
}

/**
 * The one series group to open first: the one with the most open
 * deadlines, or none. Only one, so the page still starts as a list of
 * series (spec §11.1) even for QMS staff, who see every office's.
 */
export function seriesToOpen(groups) {
  return groups.reduce((best, g) => (
    g.open_deadlines > (best?.open_deadlines || 0) ? g : best), null);
}
