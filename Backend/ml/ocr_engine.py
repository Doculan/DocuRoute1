import re
import io
import fitz
from PIL import Image
import pytesseract
from docx import Document
import mammoth
import pymupdf4llm


HEADER_KEYS = {
    'MANUAL TITLE', 'DOCUMENT NO.', 'DOCUMENT NAME',
    'REVISION NO.', 'EFFECTIVITY DATE', 'PAGE NO.',
    'VERSION NO.', 'APPROVAL DATE'
}

# FIX #1: _STRIP_RE is kept for footer/pure-tag-line detection only.
# It is NO LONGER applied to content lines so SVM can see POLICY/PROCEDURE/etc. keywords.
STRIP_TOKENS = [
    'WORKING INSTRUCTIONS', 'WORKING INSTRUCTION',
    'RESPONSIBILITIES', 'RESPONSIBILITY',
    'PROCEDURES', 'PROCEDURE',
    'POLICIES', 'POLICY',
    'PREPARED BY', 'APPROVED BY', 'NOTED BY', 'REVIEWED BY',
]

DROP_LINES = [
    'FAM 8.03', 'FINANCE AND ADMINISTRATION MANUAL', 'PROCUREMENT MANAGEMENT',
    'CLEMELLE L. MONTALLANA, DM', 'VICE PRESIDENT FOR'
]

# Used ONLY for full-line match detection (standalone tag-only lines like a bare "POLICY")
_STRIP_RE = re.compile(
    r'(?<!\w)(' + '|'.join(re.escape(t) for t in STRIP_TOKENS) + r')(?!\w)',
    flags=re.IGNORECASE
)

_FOOTER_RE = re.compile(
    r'(VP\s+for|University\s+President|Ph\.?D|D\.P\.A|D\.A\b'
    r'|Auxiliary\s+Services|Administration\s+and\s+Finance'
    r'|strictly\s+prohibited|the\s+use,\s+disclosure'
    r'|MYRNA|MACALINAO|JUDE|DUARTE|MAZO|AGUIRRE|GENEROSO|EVELYN)',
    flags=re.IGNORECASE
)

_META_RE = re.compile(
    r'(VERSION NO|DOCUMENT NO|REVISION NO|PAGE NO|EFFECTIVITY DATE'
    r'|MANUAL TITLE|DOCUMENT NAME|APPROVAL DATE)',
    flags=re.IGNORECASE
)

# Section detection patterns
_SECTION_RE = re.compile(
    r'^\s*(?:\[(\d+(?:\.\d+)*\.?)(?:\]|\.?\])|\d+(?:\.\d+)*\.?)\s+(.+)$',
    flags=re.IGNORECASE
)

# ── Markdown artifacts ───────────────────────────────────────
# The PDF path runs pymupdf4llm.to_markdown(), so its output carries Markdown
# syntax that must be stripped before the text is stored or shown to a user.

# pymupdf4llm emits <br> for a SOFT WRAP inside a table cell — the PDF simply
# ran out of column width mid-sentence. It is not a paragraph break, so it has
# to collapse to a space; turning it into a newline is what produced the
# "one word per line" cells.
_MD_BR_RE = re.compile(r'<br\s*/?>', flags=re.IGNORECASE)

# Other inline HTML pymupdf4llm emits — <mark> for highlighted source text,
# plus the usual styling tags. Only this fixed set is stripped, so genuine
# content like "value < 10" is left alone.
_INLINE_HTML_RE = re.compile(
    r'</?(?:mark|sup|sub|b|i|u|em|strong|span)\b[^>]*>',
    flags=re.IGNORECASE,
)

# A table separator row: |---|---| or |:--|--:| etc.
_MD_TABLE_SEP_RE = re.compile(r'^\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$')

_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', flags=re.DOTALL)

_MD_HEADING_RE = re.compile(r'^\s*#{1,6}\s*')
_MD_BULLET_RE = re.compile(r'^\s*[-*+]\s+')
_MD_EMPHASIS_RE = re.compile(r'\*{1,3}|(?<!_)__(?!_)')

# Header labels that identify a repeated page-header band.
# ── Extraction artefacts ─────────────────────────────────────
# These are damage from the PDF text layer, not mistakes anyone wrote. They
# must never be presented as real typos or used as typo-fix training examples.

# "theBookkeeper", "forStudent" - a word boundary the text layer lost. Two
# lowercase letters either side keeps genuine casing such as "eNGAS" and
# "PhilGEPS" intact.
_GLUED_WORD_RE = re.compile(r'(?<=[a-z]{2})(?=[A-Z][a-z]{2})')
# "3.Undergraduate" - a step number glued to its text.
_GLUED_NUMBER_RE = re.compile(r'(?<=\d\.)(?=[A-Za-z])')
# "Undergraduate:If" - a colon glued to the next word.
_GLUED_COLON_RE = re.compile(r'(?<=[a-z]):(?=[A-Z])')
# A line that is only a stray mark left by the extractor.
_STRAY_LINE_RE = re.compile(r'^\s*[^\w\s]{1,3}\s*$')
# A backtick the text layer invented: "Responsibility`".
_STRAY_BACKTICK_RE = re.compile(r'`')

# Two or more numbered steps crammed into one table cell:
# "1. Receives the Clearances. 2. Checks the ledger."
_STEP_SPLIT_RE = re.compile(r'(?<=[.;)])\s+(?=\d{1,2}\.\s*[A-Z])')

_HEADER_LABEL_RE = re.compile(
    r'(VERSION\s*NO|DOCUMENT\s*NO|DOCUMENT\s*NAME|MANUAL\s*TITLE|REVISION\s*NO'
    r'|EFFECTIVITY\s*DATE|PAGE\s*NO|APPROVAL\s*DATE)',
    flags=re.IGNORECASE,
)

# Spacing the PDF text layer loses around punctuation, e.g. "Committee(BAC)as".
_SPACE_FIXES = (
    (re.compile(r'(?<=[a-z0-9])\((?=[A-Za-z])'), ' ('),
    (re.compile(r'(?<=\))(?=[A-Za-z])'), ' '),
    (re.compile(r'(?<=[–—])(?=[A-Za-z0-9])'), ' '),
    (re.compile(r'(?<=[A-Za-z0-9])(?=[–—])'), ' '),
)


def repair_artefacts(s):
    """Undo damage the PDF text layer did to a fragment.

    Separate from Markdown stripping because these are not syntax - they are
    lost spaces and stray marks, and the same repairs are needed inside table
    cells as in running prose.
    """
    s = _STRAY_BACKTICK_RE.sub('', s or '')
    s = _GLUED_COLON_RE.sub(': ', s)
    s = _GLUED_NUMBER_RE.sub(' ', s)
    s = _GLUED_WORD_RE.sub(' ', s)
    return s


def _strip_inline(s):
    """Remove inline Markdown/HTML from a fragment, preserving its text.

    Used for both whole lines and individual table cells, so it must not know
    anything about pipes.
    """
    s = _MD_BR_RE.sub(' ', s)
    s = _INLINE_HTML_RE.sub('', s)
    # Word's Symbol-font bullet survives extraction as a private-use codepoint.
    s = s.replace('', '•').replace('&nbsp;', ' ')
    s = _MD_HEADING_RE.sub('', s)
    s = _MD_EMPHASIS_RE.sub('', s)
    s = _MD_BULLET_RE.sub('', s)

    # After the Markdown is gone, not before: the source writes
    # "3.**Undergraduate:**If", so with the bold markers still in place the
    # repair patterns saw an asterisk where they expected a letter.
    s = repair_artefacts(s)

    for pattern, repl in _SPACE_FIXES:
        s = pattern.sub(repl, s)

    return re.sub(r'\s{2,}', ' ', s).strip()


def _strip_markdown_line(s):
    """Remove Markdown syntax from one non-table line."""
    return _strip_inline(s)


def _split_row(line):
    """Split one Markdown table row into its cells.

    Strips exactly one delimiting pipe from each end - not all of them. The
    header row of these manuals is "|Responsibility||Activity|", whose middle
    cell is deliberately empty (the step-number column has no heading), and
    "||VERSION NO.|..." opens with an empty cell. Using strip('|') would eat
    those and silently change the column count.
    """
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [_strip_inline(c) for c in s.split('|')]


def _render_table(rows, header_rows=1):
    """Emit rows as a well-formed Markdown table.

    Every row is padded to the same width and a separator row is always
    written, so downstream readers never have to guess the column count.
    """
    width = max(len(r) for r in rows)
    padded = [r + [''] * (width - len(r)) for r in rows]
    out = ['| ' + ' | '.join(r) + ' |' for r in padded]
    out.insert(header_rows, '| ' + ' | '.join(['---'] * width) + ' |')
    return out


def _consume_table(lines, i):
    """Read the table block starting at lines[i].

    Returns (rendered_lines_or_None, next_index). None means the block was the
    repeated page-header band and should be dropped.
    """
    rows, sep_at = [], None
    while i < len(lines) and lines[i].strip().startswith('|'):
        raw = lines[i].strip()
        if _MD_TABLE_SEP_RE.match(raw):
            # The separator declares the real column count - keep it as the
            # width authority, but do not carry it into the data.
            if sep_at is None:
                sep_at = len(rows)
                rows.append(['---'] * len(_split_row(raw)))
        else:
            rows.append(_split_row(raw))
        i += 1

    width = 1
    if sep_at is not None:
        width = len(rows[sep_at])
        rows.pop(sep_at)
    if rows:
        width = max(width, max(len(r) for r in rows))
    rows = [r + [''] * (width - len(r)) for r in rows]

    # Drop rows that are entirely empty once stripped.
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return [], i

    # A cell holding several numbered steps becomes one row per step, with the
    # role inherited from the row it came from (Appendix A3). Without this a
    # whole procedure sits in a single cell and no individual step can be
    # revised, retrieved or reasoned about.
    if width >= 2:
        expanded = []
        for row in rows:
            parts = _STEP_SPLIT_RE.split(row[-1]) if row[-1] else [row[-1]]
            if len(parts) > 1:
                for idx, part in enumerate(parts):
                    lead = list(row[:-1]) if idx == 0 else [''] * (width - 1)
                    expanded.append(lead + [part.strip()])
            else:
                expanded.append(row)
        rows = expanded

    # The page-header band is itself a table in the source PDF.
    if _is_page_header_line(' '.join(c for r in rows for c in r if c)):
        return None, i

    # A single row with one cell was never a table.
    if len(rows) == 1 and width == 1:
        return [rows[0][0]], i

    header_rows = 1 if sep_at is None else max(sep_at, 1)
    return _render_table(rows, header_rows), i


def _mostly_upper(s):
    """True when the line's letters are overwhelmingly uppercase.

    Distinguishes a metadata band ("HUMAN RESOURCE MANUAL | HRM 4.01") from body
    prose, which is always mixed case. Section headings like "1.0 OBJECTIVES"
    are also uppercase, so this is only ever used together with a metadata cue.
    """
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7


def _is_page_header_line(s):
    """True for the repeated page-header band, in any of the forms it survives as.

    The band is a table in the source PDF, so depending on how its cells get
    merged it can arrive whole, split by label, or as a bare row of values.
    """
    # Whole band: several metadata labels run together on one line.
    if len(_HEADER_LABEL_RE.findall(s)) >= 2:
        return True

    # Split-off fragment: a short "LABEL value" line, e.g. "PAGE NO. 3 of 3".
    if len(s) <= 60 and _HEADER_LABEL_RE.match(s):
        return True

    # Value-only row: uppercase metadata carrying a label or a document code
    # such as "HRM 4.01". Body prose never looks like this.
    if _mostly_upper(s):
        if _HEADER_LABEL_RE.search(s):
            return True
        if re.search(r'\b[A-Z]{2,4}\s?\d+\.\d+\b', s):
            return True

    return False


# ── DOCX ──────────────────────────────────────────────────────

def _is_header_table(table):
    for row in table.rows:
        for cell in row.cells:
            if cell.text.strip().upper() in HEADER_KEYS:
                return True
    return False


def _extract_table_block(table):
    """Extract table content using only para.text (no double-counting via runs)."""
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            # FIX: Use cell.text directly — iterating runs separately duplicates text
            cell_text = cell.text.strip()
            if cell_text:
                cells.append(cell_text)
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows) if rows else ""


def _extract_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    blocks = []
    page_num = 1
    header_buffer = []
    header_flushed_once = False
    last_header = None

    def flush_header():
        nonlocal page_num, header_flushed_once, last_header
        if not header_buffer:
            return
        doc_name = "UNKNOWN"
        all_parts = [p.strip() for p in header_buffer if p.strip()]
        for i, part in enumerate(all_parts):
            if part.upper() == 'DOCUMENT NAME' and i + 1 < len(all_parts):
                candidate = all_parts[i + 1]
                if candidate.upper() not in HEADER_KEYS:
                    doc_name = candidate.upper()
                    break
        if header_flushed_once:
            page_num += 1
        fused = " | ".join(all_parts)

        if fused != last_header:
            blocks.append(f"##PAGE_HEADER {page_num} FOR {doc_name}##\n{fused}")
            last_header = fused

        header_buffer.clear()
        header_flushed_once = True

    for element in doc.element.body:
        tag = element.tag.split('}')[-1]
        if tag == 'tbl':
            from docx.table import Table
            table = Table(element, doc)
            if _is_header_table(table):
                for row in table.rows:
                    for cell in row.cells:
                        t = cell.text.strip()
                        if t:
                            header_buffer.append(t)
            else:
                flush_header()
                table_content = _extract_table_block(table)
                if table_content:
                    blocks.append(table_content)
        elif tag == 'p':
            from docx.text.paragraph import Paragraph
            para = Paragraph(element, doc)
            text = para.text.strip()
            if text:
                flush_header()
                blocks.append(text)

    flush_header()
    return "\n".join(blocks)


# ── PDF ───────────────────────────────────────────────────────

def _extract_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages_text = []
    last_header = None

    for page_num, page in enumerate(doc, start=1):
        page_height = page.rect.height

        # FIX #4 (revised): keyword match is authoritative; position is secondary.
        # Removed RECEIVES/ISSU/ISS — these matched procedure steps like
        # "12. Receives sealed bids" and "13. Issues Notice..." causing them to
        # be dropped as headers instead of kept as body content.
        header_key_re = re.compile(
            r'(VERSION NO|DOCUMENT NO|DOCUMENT NAME|MANUAL TITLE|REVISION NO'
            r'|EFFECTIVITY DATE|PAGE NO|APPROVAL DATE|FAM'
            r'|PROCUREMENT MANAGEMENT|FINANCE AND ADMINISTRATION MANUAL)\b',
            re.IGNORECASE,
        )

        # FIX: Pre-collect table bounding boxes so we can skip raw text blocks
        # that fall inside a detected table (avoids duplicating table content).
        table_bboxes = []
        try:
            _tables_check = page.find_tables()
            for _t in _tables_check:
                table_bboxes.append(_t.bbox)   # (x0, y0, x1, y1)
        except Exception:
            pass

        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]

        def _block_inside_table(bx0, by0, bx1, by1):
            """Return True if this text block's bbox overlaps significantly with
            any detected table — meaning the table extractor already captured it.
            We use a generous overlap threshold (50% of block area) to be safe."""
            b_area = max((bx1 - bx0) * (by1 - by0), 1)
            for tx0, ty0, tx1, ty1 in table_bboxes:
                ox = max(0, min(bx1, tx1) - max(bx0, tx0))
                oy = max(0, min(by1, ty1) - max(by0, ty0))
                overlap = ox * oy
                if overlap / b_area > 0.5:
                    return True
            return False

        elements = []
        for b in text_blocks:
            x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
            t = str(b[4]).replace('\u200b', '').replace('\x00', '').strip()
            if not t:
                continue
            # FIX (duplicate content): skip raw text blocks that are already
            # covered by a detected table — the structured table extractor
            # below will handle those cells more cleanly.
            if _block_inside_table(x0, y0, x1, y1):
                continue
            elements.append(("text", x0, y0, t))

        # Extract structured tables and insert them into the reading order.
        try:
            tables = page.find_tables()
            if tables:
                for table in tables:
                    x0, y0, x1, y1 = table.bbox
                    table_data = table.extract()
                    table_lines = []
                    for row in table_data:
                        cells = []
                        for cell in row:
                            if cell:
                                cell_text = str(cell).strip().replace('\u200b', '').replace('\x00', '')
                                if cell_text and not cell_text.lower().startswith(('image', 'pic', 'figure')):
                                    cells.append(cell_text)
                        if cells:
                            table_lines.append(" | ".join(cells))
                    if table_lines:
                        # No TABLE_START/END wrappers — they pass through into
                        # section titles and confuse the sectioning logic.
                        # Plain pipe-delimited rows are sufficient.
                        table_text = "\n".join(table_lines)
                        elements.append(("table", x0, y0, table_text))
        except Exception:
            pass

        # Sort by reading order: top-to-bottom, then left-to-right.
        elements.sort(key=lambda e: (e[2], e[1]))

        header_lines = []
        body_lines = []
        body_has_started = False

        for kind, x0, y0, t in elements:
            is_keyword_header = bool(header_key_re.search(t))

            # FIX: if a block starts with a section number like
            # "1.0 OBJECTIVES", "3.1", "4.0 LIST OF FORMS", "5.0" etc.
            # it is ALWAYS body content, NEVER a header.
            # This pattern matches: digit(s), optional decimal, optional digits, optional space, optional text
            starts_with_section_number = bool(
                re.match(r'^\d+(?:\.\d+)*\s*(?:\S|$)', t.strip())
            )

            # If it's a section number, it's always body content (highest priority)
            if starts_with_section_number:
                body_has_started = True
                body_lines.append(t)
            elif is_keyword_header:
                # Keyword headers (VERSION NO, DOCUMENT NO, etc.) always go to header
                header_lines.append(t)
            else:
                # Only apply Y-position check to non-section, non-keyword lines
                is_position_header = (
                    (y0 <= page_height * 0.10)
                    and not body_has_started
                )
                
                if is_position_header:
                    header_lines.append(t)
                else:
                    body_has_started = True
                    body_lines.append(t)

        # Fallback: if header detection failed, keep the earliest blocks as "header".
        if not header_lines and elements:
            header_lines = [elements[0][3]]
            if len(elements) > 1:
                header_lines.append(elements[1][3])

        # Normalize header into label/value lines.
        normalized_header_lines = []
        raw_header = " ".join(l.strip() for l in header_lines if l and l.strip())
        raw_header = re.sub(r'\s+', ' ', raw_header).strip()

        label_specs = [
            ("VERSION NO.", r'VERSION\s*NO\.?'),
            ("MANUAL TITLE", r'MANUAL\s*TITLE'),
            ("DOCUMENT NO.", r'DOCUMENT\s*NO\.?'),
            ("DOCUMENT NAME", r'DOCUMENT\s*NAME'),
            ("REVISION NO.", r'REVISION\s*NO\.?'),
            ("EFFECTIVITY DATE", r'EFFECTIVITY\s*DATE'),
            ("PAGE NO.", r'PAGE\s*NO\.?'),
        ]
        lookahead = "|".join(spec[1] for spec in label_specs)

        for label_text, label_re in label_specs:
            pattern = re.compile(
                rf'{label_re}\s*(.+?)(?={lookahead}|$)',
                flags=re.IGNORECASE,
            )
            m = pattern.search(raw_header)
            if not m:
                continue
            value = m.group(1).strip()
            value = re.sub(r'\s+', ' ', value).strip()
            value = value.strip(' :,-')
            if not value:
                continue
            normalized_header_lines.append(label_text)
            normalized_header_lines.append(value)

        if normalized_header_lines:
            header_text = "\n".join(normalized_header_lines)
        else:
            header_text = "\n".join(l for l in header_lines if l.strip())

        # Only include header if it's new (avoid duplicate headers across pages)
        if header_text and header_text != last_header:
            body_text = "\n".join(l for l in body_lines if l.strip())
            pages_text.append(
                f"##PAGE_HEADER {page_num} FOR page##\n{header_text}\n##PAGE_HEADER_END##\n{body_text}"
            )
            last_header = header_text
        else:
            body_text = "\n".join(l for l in body_lines if l.strip())
            pages_text.append(body_text)

    doc.close()
    return "\n".join(pages_text)


# ── CLEANING ─────────────────────────────────────────────────

def _clean(text):
    """Clean extracted text - CONSERVATIVE approach.
    
    Only removes DEFINITIVELY metadata/page artifacts:
    - ##PAGE_HEADER## blocks (document metadata)
    - "X of Y" page numbers
    
    PRESERVES everything else including:
    - Content with photos/demos mentioned
    - Table formatting
    - All semantic keywords (POLICY, PROCEDURE, RESPONSIBILITY, etc.)
    - Footer signatures (last page seal)
    
    Rationale: Aggressive cleaning removes useful content. Better to keep
    and let ML classifier and users decide than to lose legitimate data.
    """
    out = []
    # pymupdf4llm marks image regions with HTML comments such as
    # "<!-- Start of picture text -->". Stripped on the whole text rather than
    # per line, since a comment may span lines.
    text = _HTML_COMMENT_RE.sub('', text)
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        s = lines[i].strip()

        if not s:
            i += 1
            continue

        # -- ONLY remove PAGE_HEADER metadata blocks --
        # These are document metadata (VERSION NO, DOCUMENT NO) repeated on every page
        # NOT body content
        if s.startswith('##PAGE_HEADER'):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('##PAGE_HEADER_END##'):
                i += 1  # skip metadata
            if i < len(lines) and lines[i].strip().startswith('##PAGE_HEADER_END##'):
                i += 1
            continue

        # -- Remove "X of Y" page number lines only --
        # These are pure page numbering, not content
        if re.match(r'^\d+\s+of\s+\d+$', s):
            i += 1
            continue

        # -- Remove common disclaimer/legal lines (very specific match) --
        if 'use, disclosure, reproduction' in s.lower() and 'strictly prohibited' in s.lower():
            i += 1
            continue

        # -- Remove legacy marker lines only --
        if s in ('||TABLE_START||', '||TABLE_END||'):
            i += 1
            continue

        # -- Tables are kept as tables --
        # pymupdf4llm emits real Markdown tables. Flattening them to
        # "a | b | c" threw away the column count and the header row, which
        # every reader downstream then had to guess at. Consume the whole
        # block here instead, where the separator row is still available to
        # say how wide it is.
        if s.startswith('|'):
            block, i = _consume_table(lines, i)
            if block:
                out.extend(block)
            continue

        # -- A stray separator row outside a table block carries no content --
        if _MD_TABLE_SEP_RE.match(s):
            i += 1
            continue

        # -- Strip Markdown syntax before any content checks --
        s = _strip_markdown_line(s)

        if not s:
            i += 1
            continue

        # -- Drop the page-header band repeated on every page --
        # Checked after stripping so "**VERSION NO. ... PAGE NO. 1 of 3**" is seen.
        if _is_page_header_line(s):
            i += 1
            continue

        # -- "X of Y" can survive as a tail once the header band is split --
        if re.match(r'^\d+\s+of\s+\d+$', s):
            i += 1
            continue

        out.append(s)
        i += 1

    # Collapse excessive blank lines (4+ → 2-3)
    result = '\n'.join(out)
    result = re.sub(r'\n{4,}', '\n\n\n', result)
    return result.strip()


# ── PUBLIC API ───────────────────────────────────────────────

def clean_extracted_text(text: str) -> str:
    """Apply the extraction cleanup rules to text that is already stored.

    Lets previously-extracted content be brought up to the current rules
    without re-running extraction, which would mean recreating sections and
    cascade-deleting their revision history.
    """
    return _clean(text or '')


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.split('.')[-1].lower()

    if ext == 'docx':
        return _clean(_extract_docx(file_bytes))
    elif ext == 'doc':
        with io.BytesIO(file_bytes) as f:
            result = mammoth.extract_raw_text(f)
        return _clean(result.value)
    elif ext == 'pdf':
        # Use pymupdf4llm for improved layout analysis
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            md_text = pymupdf4llm.to_markdown(doc)
            doc.close()
            return _clean(md_text)
        except Exception:
            # Fallback to old method if pymupdf4llm fails
            return _clean(_extract_pdf(file_bytes))
    elif ext in ['jpg', 'jpeg', 'png']:
        img = Image.open(io.BytesIO(file_bytes))
        return _clean(pytesseract.image_to_string(img, config="--psm 6"))
    elif ext == 'txt':
        return _clean(file_bytes.decode('utf-8', errors='ignore'))
    else:
        raise ValueError("Unsupported file type")