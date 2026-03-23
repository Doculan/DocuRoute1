import sys
sys.path.insert(0, 'Backend')
from ml.ocr_engine import extract_text

with open('Backend/media/mastercopies/test2.pdf', 'rb') as f:
    text = extract_text(f.read(), 'test2.pdf')

print("=== EXTRACTED TEXT ===")
print(text[:4000])
