import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSection, editCell, editTextBlock, changeTable, replaceRange } from './sectionEditor.js';

const original = '4.0 Procedure\r\n\r\n| Responsibility |  | Activity |\r\n| :--- | --- | ---: |\r\n| Cashier | 1. | Release the cheque. |\r\n| Office | 2. | Keep the record. |\r\n\r\nFollowing paragraph.\r\n';
const table = (text) => parseSection(text).find((b) => b.kind === 'table');

test('editing prose keeps the following table separate and retains CRLF', () => {
  const block = parseSection(original)[0];
  const edited = editTextBlock(original, block, 'New introduction\nSecond line');
  assert.equal(edited, 'New introduction\r\nSecond line\r\n' + original.slice(block.end));
  assert.equal(parseSection(edited).filter((b) => b.kind === 'table').length, 1);
  assert.equal(editTextBlock(original, block, ''), original.slice(block.end));
});
test('typing spaces between words does not accumulate cell padding', () => {
  let next = editCell(original, table(original), 1, 0, '');
  next = editCell(next, table(next), 1, 0, 'Central ');
  next = editCell(next, table(next), 1, 0, 'Central office ');
  next = editCell(next, table(next), 1, 0, 'Central office cashier');
  assert.equal(next, original.replace('Cashier', 'Central office cashier'));
});

test('parsing preserves every original character including CRLF and blank lines', () => {
  for (const text of [original, '', 'Plain text\n', '|A|B|', 'Text | prose\n', '\n|---|---|\n|A|B|\n']) {
    assert.equal(parseSection(text).map((b) => text.slice(b.start, b.end)).join(''), text);
  }
});
test('opening or re-entering an unchanged cell preserves the exact section', () => {
  assert.equal(editCell(original, table(original), 1, 2, 'Release the cheque.'), original);
});
test('a cell edit changes only its source span', () => {
  assert.equal(editCell(original, table(original), 1, 2, 'Retain the receipt.'),
    original.replace('Release the cheque.', 'Retain the receipt.'));
});
test('empty header cells and numbered columns remain separate', () => {
  const t = table(original);
  assert.equal(t.width, 3);
  assert.deepEqual(t.rows[0].cells.map((c) => c.value), ['Responsibility', '', 'Activity']);
  assert.deepEqual(t.rows[1].cells.map((c) => c.value), ['Cashier', '1.', 'Release the cheque.']);
});
test('legacy rows retain numeric columns without heuristic merging', () => {
  const source = 'Office | 1. | Check record\nTeam | 2. | File record';
  const t = table(source);
  assert.equal(t.width, 3);
  assert.equal(editCell(source, t, 0, 2, 'Review record'), source.replace('Check record', 'Review record'));
});
test('ragged rows do not lose extra columns beyond the separator width', () => {
  const source = '|A|B|\n|---|---|\n|1|2|DO NOT DROP|\n|3|4|';
  const t = table(source);
  assert.equal(t.width, 3);
  const edited = editCell(source, t, 2, 2, 'Added cell');
  assert.ok(edited.includes('DO NOT DROP'));
  assert.equal(table(edited).rows[2].cells[2].value, 'Added cell');
});
test('row insertion preserves surrounding text, header separator and column alignment', () => {
  const result = changeTable(original, table(original), 'addRow', 1);
  const t = table(result);
  assert.equal(t.rows.length, 4);
  assert.deepEqual(t.rows[2].cells.map((c) => c.value), ['', '', '']);
  assert.equal(t.separator.cells[0].value, ':---');
  assert.ok(result.startsWith('4.0 Procedure\r\n\r\n'));
  assert.ok(result.endsWith('\r\n\r\nFollowing paragraph.\r\n'));
});
test('column changes include every row and preserve separator alignment', () => {
  let result = changeTable(original, table(original), 'addColumn', 0);
  assert.equal(table(result).width, 4);
  assert.equal(table(result).rows[1].cells[2].value, '1.');
  result = changeTable(result, table(result), 'removeColumn', 1);
  assert.equal(table(result).width, 3);
  assert.deepEqual(table(result).separator.cells.map((c) => c.value), [':---', '---', '---:']);
});
test('header row and minimum two columns cannot be removed', () => {
  assert.equal(changeTable(original, table(original), 'removeRow', 0), original);
  const source = '|A|B|';
  assert.equal(changeTable(source, table(source), 'removeColumn', 0), source);
  assert.equal(changeTable(source, table(source), 'removeRow', 0), source);
});
test('removing a data row preserves the other rows', () => {
  const result = changeTable(original, table(original), 'removeRow', 1);
  assert.equal(table(result).rows.length, 2);
  assert.ok(!result.includes('Release the cheque.'));
  assert.ok(result.includes('Keep the record.'));
});
test('unsupported cell characters are rejected rather than corrupting columns', () => {
  for (const text of ['one|two', 'one\ntwo', 'one\rtwo', 'one\ttwo']) {
    assert.throws(() => editCell(original, table(original), 1, 1, text), /separate cell or row/);
  }
});
test('multiple tables and interleaved paragraphs stay independent', () => {
  const source = original + '\n|Other|Table|\n|Leave|Alone|';
  const tables = parseSection(source).filter((b) => b.kind === 'table');
  assert.equal(tables.length, 2);
  const result = editCell(source, tables[1], 1, 0, 'Changed');
  assert.ok(result.startsWith(original));
  const textBlock = parseSection(source)[0];
  assert.ok(replaceRange(source, textBlock.start, textBlock.end, 'New heading\n').endsWith('|Leave|Alone|'));
});
