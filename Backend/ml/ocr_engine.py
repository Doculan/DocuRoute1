import re
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.split('.')[-1].lower()
    text = ""

    if ext == 'pdf':
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n"
        doc.close()

    elif ext in ['jpg', 'jpeg', 'png']:
        # Only used if Tesseract is installed
        img = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(img, config="--psm 6")

    elif ext == 'txt':
        text = file_bytes.decode('utf-8', errors='ignore')

    else:
        raise ValueError("Unsupported file type")

       # ── Clean up word-per-line artifact ──
    lines = text.splitlines()
    cleaned = []
    buffer = ""

    def is_heading(line):
        # Headings: ALL CAPS, or starts with Chapter/Section/number pattern
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.isupper():
            return True
        if re.match(r'^(CHAPTER|SECTION|ARTICLE|PART|APPENDIX)\s*\d*', stripped, re.IGNORECASE):
            return True
        if re.match(r'^\d+(\.\d+)*\s', stripped):  # e.g. "1.1 Purpose"
            return True
        return False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                cleaned.append(buffer.strip())
                buffer = ""
            cleaned.append("")
        elif is_heading(stripped):
            # Always flush buffer and keep heading on its own line
            if buffer:
                cleaned.append(buffer.strip())
                buffer = ""
            cleaned.append(stripped)
        elif len(stripped.split()) <= 3 and stripped[-1] not in ".?!:":
            buffer += " " + stripped
        else:
            if buffer:
                buffer += " " + stripped
                cleaned.append(buffer.strip())
                buffer = ""
            else:
                cleaned.append(stripped)

    if buffer:
        cleaned.append(buffer.strip())

    return "\n".join(cleaned).strip()
