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


# ── PDF ───────────────────────────────────────────────────────

def _extract_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages_text = []

    for page_num, page in enumerate(doc, start=1):
        page_width = page.rect.width
        tag_col_x = page_width * 0.70
        col_split_x = page_width * 0.50  # Split for two columns

        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip() and b[0] <= tag_col_x]

        # Split into left and right columns
        left_blocks = [b for b in text_blocks if b[0] < col_split_x]
        right_blocks = [b for b in text_blocks if b[0] >= col_split_x]

        # Match left and right blocks by vertical position (y-coordinate)
        lines = []
        used_right = set()

        for left_block in sorted(left_blocks, key=lambda b: b[1]):
            left_y = left_block[1]  # Top of left block
            left_text = left_block[4].strip()

            # Find right block at similar vertical position (tolerance ~20 points)
            matching_right = None
            for idx, right_block in enumerate(right_blocks):
                if idx not in used_right:
                    right_y = right_block[1]
                    if abs(right_y - left_y) < 20:
                        matching_right = idx
                        break

            if matching_right is not None:
                right_text = right_blocks[matching_right][4].strip()
                lines.append(f"{left_text} | {right_text}")
                used_right.add(matching_right)
            else:
                lines.append(left_text)

        # Add remaining unmatched right blocks
        for idx, right_block in enumerate(right_blocks):
            if idx not in used_right:
                lines.append(right_block[4].strip())

        pages_text.append(f"##PAGE_HEADER {page_num} FOR page##\n" + "\n".join(lines))

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
    while i < len(lines):
        s = lines[i].strip()

        # Always keep PAGE_HEADER markers
        if s.startswith('##PAGE_HEADER'):
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
