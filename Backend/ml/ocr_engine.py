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

        # -- Normalize whitespace but KEEP everything else --
        # Multiple spaces → single space (preserves readability)
        s = re.sub(r'\s{2,}', ' ', s).strip()
        
        if s:
            out.append(s)

        i += 1

    # Collapse excessive blank lines (4+ → 2-3)
    result = '\n'.join(out)
    result = re.sub(r'\n{4,}', '\n\n\n', result)
    return result.strip()


# ── PUBLIC API ───────────────────────────────────────────────

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