// Editing uses source offsets, never the reader's heuristic column merging.
// Parsing alone never rewrites source; a cell edit touches only that cell.
function rowOf(line) {
  const raw = line.text;
  const left = raw.length - raw.trimStart().length;
  const right = raw.trimEnd().length;
  const bounded = raw[left] === "|" && raw[right - 1] === "|";
  let start = raw[left] === "|" ? left + 1 : 0;
  const end = raw[right - 1] === "|" ? right - 1 : raw.length;
  if (!raw.includes("|")) return null;
  const cells = [];
  for (let i = start; i <= end; i++) {
    if (i !== end && raw[i] !== "|") continue;
    const text = raw.slice(start, i);
    cells.push({ value: text.trim(), start: line.start + start, end: line.start + i });
    start = i + 1;
  }
  if (cells.length < 2) return null;
  return { ...line, cells, bounded,
    separator: cells.every((c) => /^:?-{2,}:?$/.test(c.value)) };
}

export function parseSection(source) {
  const lines = [];
  const regex = /([^\r\n]*)(\r\n|\n|\r|$)/g;
  for (const match of source.matchAll(regex)) {
    if (!match[0]) continue;
    lines.push({ text: match[1], eol: match[2], start: match.index,
      end: match.index + match[1].length, after: match.index + match[0].length });
  }
  const blocks = [];
  let textStart = 0;
  for (let i = 0; i < lines.length;) {
    const rows = [];
    let j = i;
    while (j < lines.length) {
      const row = rowOf(lines[j]);
      if (!row) break;
      rows.push(row);
      j++;
    }
    // An isolated unbounded pipe in prose isn't necessarily a table.
    if (!rows.length || (rows.length === 1 && !rows[0].bounded) || rows.every((r) => r.separator)) {
      i++;
      continue;
    }
    if (lines[i].start > textStart) {
      blocks.push({ kind: "text", start: textStart, end: lines[i].start });
    }
    const separator = rows.length > 1 && rows[1].separator ? rows[1] : null;
    // Ambiguous separators remain editable as ordinary text rather than lost.
    if (rows.some((r) => r.separator && r !== separator)) {
      textStart = lines[i].start;
      i = j;
      continue;
    }
    blocks.push({ kind: "table", start: rows[0].start, end: rows.at(-1).after,
      rows: rows.filter((r) => !r.separator), separator,
      width: Math.max(...rows.map((r) => r.cells.length)),
      eol: rows.find((r) => r.eol)?.eol || "\n", trailing: rows.at(-1).eol });
    textStart = rows.at(-1).after;
    i = j;
  }
  if (textStart < source.length || !blocks.length) {
    blocks.push({ kind: "text", start: textStart, end: source.length });
  }
  return blocks;
}

export function replaceRange(source, start, end, replacement) {
  return source.slice(0, start) + replacement + source.slice(end);
}

export function editTextBlock(source, block, value) {
  const original = source.slice(block.start, block.end);
  const eol = original.match(/\r\n|\n|\r/)?.[0] || "\n";
  let next = value.replace(/\r\n|\n|\r/g, eol);
  // Keep the following table on its own line, even if prose is replaced.
  if (block.end < source.length && next && !/[\r\n]$/.test(next)) next += eol;
  return replaceRange(source, block.start, block.end, next);
}

export function editCell(source, table, rowIndex, column, value) {
  if (/[|\r\n\t]/.test(value)) throw new Error("Use a separate cell or row for additional entries; pipes and line breaks cannot be stored inside a cell.");
  value = value.trim();
  const row = table.rows[rowIndex];
  const cell = row.cells[column];
  if (cell && value === cell.value) return source;
  if (cell) {
    const old = source.slice(cell.start, cell.end);
    const split = Math.ceil(old.length / 2);
    const before = old.trim() ? old.match(/^\s*/)[0] : old.slice(0, split);
    const after = old.trim() ? old.match(/\s*$/)[0] : old.slice(split);
    return replaceRange(source, cell.start, cell.end, before + value + after);
  }
  if (!value) return source;
  const cells = Array.from({ length: table.width }, (_, i) => row.cells[i]?.value || "");
  cells[column] = value;
  return replaceRange(source, row.start, row.end, "| " + cells.join(" | ") + " |");
}

export function changeTable(source, table, action, index) {
  const rows = table.rows.map((row) => Array.from({ length: table.width }, (_, i) => row.cells[i]?.value || ""));
  let separators = table.separator?.cells.map((c) => c.value);
  if (separators) separators = Array.from({ length: table.width }, (_, i) => separators[i] || "---");
  if (action === "addRow") rows.splice(index + 1, 0, Array(table.width).fill(""));
  else if (action === "removeRow") {
    if (rows.length <= 1 || (table.separator && index === 0)) return source;
    rows.splice(index, 1);
  } else if (action === "addColumn") {
    rows.forEach((r) => r.splice(index + 1, 0, ""));
    separators?.splice(index + 1, 0, "---");
  } else if (action === "removeColumn") {
    if (table.width <= 2) return source;
    rows.forEach((r) => r.splice(index, 1));
    separators?.splice(index, 1);
  } else throw new Error("Unknown table action.");
  const lines = rows.map((row) => "| " + row.join(" | ") + " |");
  if (separators) lines.splice(1, 0, "| " + separators.join(" | ") + " |");
  return replaceRange(source, table.start, table.end, lines.join(table.eol) + table.trailing);
}
