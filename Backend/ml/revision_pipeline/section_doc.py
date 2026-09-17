"""A stored section, parsed into the places an edit can land.

The app submits **whole sections**, so an example's ``old_text`` and
``new_text`` are the entire stored section. But edits land on individual table
rows or sentences, the way a person would change one step rather than rewrite
a procedure. This module holds that distinction: parse a section into blocks,
change one or two of them, render the section back out unchanged elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SEP_RE = re.compile(r"^\|?\s*:?-{2,}")
_ROW_RE = re.compile(r"^\|.*\|\s*$")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


@dataclass
class Row:
    """One table row. ``cells`` excludes the delimiting pipes."""

    cells: list
    index: int

    def render(self) -> str:
        # Collapse runs of spaces, because _split_into_sections does the same
        # before storing. An empty cell would otherwise render "|  |" against a
        # stored "| |", and every generated example would carry that as a
        # spurious change.
        return re.sub(r"\s{2,}", " ", "| " + " | ".join(self.cells) + " |")

    @property
    def body(self) -> str:
        """The last cell - the step text in a Responsibility/Activity table."""
        return self.cells[-1] if self.cells else ""

    @property
    def role(self) -> str:
        return self.cells[0] if self.cells else ""


@dataclass
class Block:
    """A run of the section: prose, a table header, or a table body."""

    kind: str              # "prose" | "separator" | "header" | "row"
    text: str = ""
    row: Row = None


@dataclass
class SectionDoc:
    subtitle: str = ""
    blocks: list = field(default_factory=list)

    # -- parsing ----------------------------------------------

    @classmethod
    def parse(cls, subtitle: str, content: str) -> "SectionDoc":
        blocks, seen_separator, row_index = [], False, 0
        lines = (content or "").splitlines()

        for position, raw in enumerate(lines):
            line = raw.strip()
            if not line:
                continue
            if _SEP_RE.match(line):
                blocks.append(Block("separator", line))
                seen_separator = True
                continue
            if _ROW_RE.match(line):
                cells = [c.strip() for c in line.strip("|").split("|")]
                # The row before the separator is the header.
                next_is_sep = (
                    position + 1 < len(lines)
                    and _SEP_RE.match(lines[position + 1].strip())
                )
                if next_is_sep or (not seen_separator and not blocks):
                    blocks.append(Block("header", line, Row(cells, -1)))
                else:
                    blocks.append(Block("row", line, Row(cells, row_index)))
                    row_index += 1
                continue
            blocks.append(Block("prose", line))

        return cls(subtitle=subtitle, blocks=blocks)

    # -- access -----------------------------------------------

    @property
    def rows(self) -> list:
        return [b.row for b in self.blocks if b.kind == "row"]

    @property
    def prose_lines(self) -> list:
        return [b.text for b in self.blocks if b.kind == "prose"]

    def sentences(self) -> list:
        """(block_position, sentence_index, text) for every prose sentence."""
        out = []
        for position, block in enumerate(self.blocks):
            if block.kind != "prose":
                continue
            for index, sentence in enumerate(_SENT_SPLIT_RE.split(block.text)):
                if sentence.strip():
                    out.append((position, index, sentence.strip()))
        return out

    def render(self) -> str:
        return "\n".join(b.text if b.kind != "row" else b.row.render()
                         for b in self.blocks)

    def copy(self) -> "SectionDoc":
        return SectionDoc(
            subtitle=self.subtitle,
            blocks=[
                Block(b.kind, b.text,
                      Row(list(b.row.cells), b.row.index) if b.row else None)
                for b in self.blocks
            ],
        )

    # -- editing ----------------------------------------------

    def set_row_body(self, row_index: int, text: str) -> None:
        for block in self.blocks:
            if block.kind == "row" and block.row.index == row_index:
                block.row.cells[-1] = text
                block.text = block.row.render()
                return

    def set_row_role(self, row_index: int, role: str) -> None:
        for block in self.blocks:
            if block.kind == "row" and block.row.index == row_index and block.row.cells:
                block.row.cells[0] = role
                block.text = block.row.render()
                return

    def delete_row(self, row_index: int) -> None:
        self.blocks = [
            b for b in self.blocks
            if not (b.kind == "row" and b.row.index == row_index)
        ]

    def swap_rows(self, first: int, second: int) -> None:
        positions = {b.row.index: i for i, b in enumerate(self.blocks) if b.kind == "row"}
        if first not in positions or second not in positions:
            return
        i, j = positions[first], positions[second]
        self.blocks[i], self.blocks[j] = self.blocks[j], self.blocks[i]

    def insert_row_after(self, row_index: int, cells: list) -> None:
        for position, block in enumerate(self.blocks):
            if block.kind == "row" and block.row.index == row_index:
                width = len(block.row.cells)
                padded = (list(cells) + [""] * width)[:width]
                self.blocks.insert(position + 1, Block("row", "", Row(padded, -2)))
                self.blocks[position + 1].text = self.blocks[position + 1].row.render()
                return

    def set_prose(self, block_position: int, text: str) -> None:
        if 0 <= block_position < len(self.blocks):
            self.blocks[block_position].text = text

    def append_prose(self, text: str) -> None:
        self.blocks.append(Block("prose", text))

    def delete_prose(self, block_position: int) -> None:
        if 0 <= block_position < len(self.blocks):
            self.blocks.pop(block_position)

    # -- description ------------------------------------------

    @property
    def has_table(self) -> bool:
        return any(b.kind == "row" for b in self.blocks)

    def unit_count(self) -> int:
        """Editable units: table rows, or prose sentences when there is no table."""
        return len(self.rows) if self.has_table else len(self.sentences())


def section_type(subtitle: str) -> str:
    """Objectives / Scope / Policies / Procedures / Forms / Other.

    Used to stratify sampling: all 487 table rows live in Procedures, so
    without this the dataset would be almost entirely procedures.
    """
    text = (subtitle or "").upper()
    for name in ("OBJECTIVE", "SCOPE", "POLIC", "PROCEDURE", "FORM"):
        if name in text:
            return {
                "OBJECTIVE": "Objectives", "SCOPE": "Scope", "POLIC": "Policies",
                "PROCEDURE": "Procedures", "FORM": "Forms",
            }[name]
    return "Other"
