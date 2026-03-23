import re
import io
import fitz
from PIL import Image
import pytesseract
from docx import Document
import mammoth


HEADER_KEYS = {
    'MANUAL TITLE', 'DOCUMENT NO.', 'DOCUMENT NAME',
    'REVISION NO.', 'EFFECTIVITY DATE', 'PAGE NO.',
    'VERSION NO.', 'APPROVAL DATE'
}

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


# ── DOCX ──────────────────────────────────────────────────────

def _is_header_table(table):
    for row in table.rows:
        for cell in row.cells:
            if cell.text.strip().upper() in HEADER_KEYS:
                return True
    return False


def _extract_table_block(table):
    rows = []
    for row in table.rows:
        row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
        if row_text:
            rows.append(row_text)
    return "\n".join(rows)


def _extract_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    blocks = []
    page_num = 1
    header_buffer = []
    header_flushed_once = False

    def flush_header():
        nonlocal page_num, header_flushed_once
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
        blocks.append(f"##PAGE_HEADER {page_num} FOR {doc_name}##\n{fused}")
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
                blocks.append(_extract_table_block(table))
        elif tag == 'p':
            from docx.text.paragraph import Paragraph
            para = Paragraph(element, doc)
            text = para.text.strip()
            if text:
                flush_header()
                blocks.append(text)

    flush_header()
    return "\n".join(blocks)

# ── TABLE RECONSTRUCTION ──────────────────────────────────────

def _reconstruct_tables_from_blocks(blocks, page_width, tag_col_x):
    """Reconstruct tables from text blocks by detecting column patterns.
    For two-column tables: pair left column (Responsibility) with right column (Activity)."""
    
    col_split_x = page_width * 0.50
    left_blocks = []
    right_blocks = []
    
    for b in blocks:
        if b[0] < col_split_x:
            left_blocks.append((b[1], b[4].strip()))  # (y_position, text)
        else:
            right_blocks.append((b[1], b[4].strip()))
    
    # Sort by y-position
    left_blocks.sort()
    right_blocks.sort()
    
    # Pair blocks at similar y-positions
    paired_lines = []
    used_right = set()
    
    for left_y, left_text in left_blocks:
        if not left_text:
            continue
        
        # Find matching right block (within ~25 points vertically)
        matching_right_text = None
        for idx, (right_y, right_text) in enumerate(right_blocks):
            if idx not in used_right and abs(right_y - left_y) < 25:
                matching_right_text = right_text
                used_right.add(idx)
                break
        
        if matching_right_text:
            paired_lines.append(f"{left_text} | {matching_right_text}")
        else:
            paired_lines.append(left_text)
    
    # Add remaining right blocks
    for idx, (_, right_text) in enumerate(right_blocks):
        if idx not in used_right and right_text:
            paired_lines.append(right_text)
    
    return paired_lines
# ── PDF ───────────────────────────────────────────────────────

def _extract_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages_text = []

    for page_num, page in enumerate(doc, start=1):
        page_height = page.rect.height
        header_cutoff_y = page_height * 0.22  # top region heuristic for headers

        # Header keywords used to decide "real header" blocks.
        header_key_re = re.compile(
            r'(VERSION NO|DOCUMENT NO|DOCUMENT NAME|MANUAL TITLE|REVISION NO|EFFECTIVITY DATE|PAGE NO|APPROVAL DATE|FAM|PROCUREMENT MANAGEMENT|FINANCE AND ADMINISTRATION MANUAL|RECEIVES|ISSU|ISS)\b',
            re.IGNORECASE,
        )

        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]

        elements = []
        for b in text_blocks:
            x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
            t = str(b[4]).replace('\u200b', '').replace('\x00', '').strip()
            if not t:
                continue
            elements.append(("text", x0, y0, t))

        # Try to detect tables and insert them into the reading order.
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
                                if cell_text:
                                    cells.append(cell_text)
                        if cells:
                            table_lines.append(" | ".join(cells))
                    if table_lines:
                        elements.append(("table", x0, y0, "\n".join(table_lines)))
        except Exception:
            pass

        # Sort by reading order approximation: top-to-bottom, then left-to-right.
        elements.sort(key=lambda e: (e[2], e[1]))

        header_lines = []
        body_lines = []

        for kind, x0, y0, t in elements:
            # Treat as header if it's within the header region OR it looks like header metadata.
            is_header = (y0 <= header_cutoff_y) or bool(header_key_re.search(t))
            if is_header:
                header_lines.append(t)
            else:
                body_lines.append(t)

        # Fallback: if header detection failed, still keep the earliest blocks as "header".
        if not header_lines and elements:
            header_lines = [elements[0][3]]
            if len(elements) > 1:
                header_lines.append(elements[1][3])

        # Normalize header into label/value lines (keeps it editable and closer
        # to the way the PDF presents those fields).
        normalized_header_lines = []
        raw_header = " ".join(l.strip() for l in header_lines if l and l.strip())
        raw_header = re.sub(r'\s+', ' ', raw_header).strip()

        # Primary header labels we want in the output.
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

        # Fall back to raw header lines if normalization produced nothing.
        if normalized_header_lines:
            header_text = "\n".join(normalized_header_lines)
        else:
            header_text = "\n".join(l for l in header_lines if l.strip())
        body_text = "\n".join(l for l in body_lines if l.strip())

        pages_text.append(
            f"##PAGE_HEADER {page_num} FOR page##\n{header_text}\n##PAGE_HEADER_END##\n{body_text}"
        )

    doc.close()
    return "\n".join(pages_text)


# ── CLEANING ─────────────────────────────────────────────────

def _clean(text):
    # First pass: collect known header values to drop
    header_values = set()
    for line in text.splitlines():
        s = line.strip()
        if _META_RE.search(s) and '|' in s:
            parts = [p.strip() for p in s.split('|')]
            for p in parts:
                if p and p.upper() not in HEADER_KEYS and not re.match(r'^\d+$', p):
                    header_values.add(p.upper())

    out = []
    lines = text.splitlines()
    i = 0
    in_page_header = False

    while i < len(lines):
        s = lines[i].strip()

        # Explicit marker to stop header capture for PDF extraction.
        if s.startswith('##PAGE_HEADER_END##'):
            in_page_header = False
            i += 1
            continue

        # Always keep PAGE_HEADER markers
        if s.startswith('##PAGE_HEADER'):
            out.append(s)
            in_page_header = True
            i += 1
            continue

        if in_page_header:
            # End page header capture as soon as we hit a section heading
            if re.match(r'^(CHAPTER\s+\d+(?:\.\d+)*)(?:\s*[:\.\-]?\s*(.*))?$', s, re.IGNORECASE) or \
               re.match(r'^(\d+(?:\.\d+)*\.?)(\s+\S+.*)?$', s):
                in_page_header = False
                # Fall through to section/content parsing for this line
            else:
                if s:
                    out.append(s)
                i += 1
                continue

        # Drop metadata lines
        if _META_RE.search(s):
            i += 1
            continue

        # Drop footer/signature lines
        if _FOOTER_RE.search(s):
            i += 1
            continue

        # Drop pure tag lines
        if _STRIP_RE.fullmatch(s):
            i += 1
            continue

        # Drop artifact-only lines
        if re.match(r'^[\s:|\-\.​\u200b]+$', s):
            i += 1
            continue

        # Drop "X of Y" page lines
        if re.match(r'^\d+\s+of\s+\d+$', s):
            i += 1
            continue

        # Drop known header values (manual title, doc name, etc.)
        if s.upper() in header_values:
            i += 1
            continue

        # Drop standalone version numbers like "1" or "0"
        if re.match(r'^\d{1,2}$', s):
            i += 1
            continue

        # Rejoin orphaned number line with next title line
        # e.g. "1.0\nOBJECTIVES" → "1.0 OBJECTIVES"
        num_only = re.match(r'^(\d+(\.\d+)*)$', s)
        if num_only and i + 1 < len(lines):
            next_s = lines[i + 1].strip()
            if (next_s
                    and not next_s.startswith('##')
                    and not _META_RE.search(next_s)
                    and next_s.upper() not in header_values
                    and not re.match(r'^[\s:|\-\.]+$', next_s)):
                out.append(f"{s} {next_s}")
                i += 2
                continue

        # Strip inline tags
        s = _STRIP_RE.sub('', s)
        s = re.sub(r'\s{2,}', ' ', s).strip()

        if s:
            out.append(s)
        i += 1

    return '\n'.join(out)


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
        return _clean(_extract_pdf(file_bytes))
    elif ext in ['jpg', 'jpeg', 'png']:
        img = Image.open(io.BytesIO(file_bytes))
        return _clean(pytesseract.image_to_string(img, config="--psm 6"))
    elif ext == 'txt':
        return _clean(file_bytes.decode('utf-8', errors='ignore'))
    else:
        raise ValueError("Unsupported file type")
