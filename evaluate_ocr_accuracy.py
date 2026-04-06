"""
OCR Accuracy Evaluation Script
Measures the accuracy of text extraction from the OCR engine using standard metrics.
"""

import sys
import os
import io
from PIL import Image, ImageDraw, ImageFont
import pytesseract
import numpy as np
from difflib import SequenceMatcher
import re
from collections import Counter
import argparse

# Add Backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'Backend'))
from ml.ocr_engine import extract_text


def calculate_cer(ground_truth, extracted):
    """
    Calculate Character Error Rate (CER)
    CER = (insertions + deletions + substitutions) / len(ground_truth)
    """
    if not ground_truth:
        return 0.0 if not extracted else 1.0

    # Use dynamic programming to calculate edit distance
    gt = list(ground_truth)
    ext = list(extracted)

    # Create distance matrix
    m, n = len(gt), len(ext)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # Initialize first row and column
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    # Fill the matrix
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if gt[i-1] == ext[j-1] else 1
            dp[i][j] = min(
                dp[i-1][j] + 1,      # deletion
                dp[i][j-1] + 1,      # insertion
                dp[i-1][j-1] + cost  # substitution
            )

    edit_distance = dp[m][n]
    return edit_distance / len(gt) if gt else 0.0


def calculate_wer(ground_truth, extracted):
    """
    Calculate Word Error Rate (WER)
    WER = (insertions + deletions + substitutions) / number_of_words_in_ground_truth
    """
    gt_words = ground_truth.split()
    ext_words = extracted.split()

    if not gt_words:
        return 0.0 if not ext_words else 1.0

    # Use dynamic programming for word-level edit distance
    m, n = len(gt_words), len(ext_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if gt_words[i-1].lower() == ext_words[j-1].lower() else 1
            dp[i][j] = min(
                dp[i-1][j] + 1,
                dp[i][j-1] + 1,
                dp[i-1][j-1] + cost
            )

    edit_distance = dp[m][n]
    return edit_distance / len(gt_words)


def normalize_text(text):
    """Normalize text for comparison by removing extra whitespace and normalizing case"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Normalize quotes and apostrophes
    text = text.replace('"', '"').replace('"', '"').replace(''', "'").replace(''', "'")
    return text


def create_synthetic_image(text, font_size=20, image_width=800):
    """
    Create a synthetic image with the given text for OCR testing
    """
    # Try to use a system font, fallback to default if not available
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except:
            font = ImageFont.load_default()

    # Calculate image height needed
    lines = text.split('\n')
    line_height = font_size + 4
    image_height = len(lines) * line_height + 20

    # Create image
    img = Image.new('RGB', (image_width, image_height), color='white')
    draw = ImageDraw.Draw(img)

    # Draw text
    y = 10
    for line in lines:
        draw.text((10, y), line, fill='black', font=font)
        y += line_height

    return img


def evaluate_ocr_accuracy():
    """
    Main evaluation function using real PDF documents
    """
    print("=" * 80)
    print("OCR ACCURACY EVALUATION - PDF DOCUMENTS")
    print("=" * 80)
    print()

    # Test cases with real PDF documents and expected text patterns
    test_cases = [
        {
            'file_path': 'Backend/media/mastercopies/test2.pdf',
            'expected_patterns': [
                'VERSION NO',
                'MANUAL TITLE',
                'DOCUMENT NO',
                'PROCUREMENT MANAGEMENT',
                'OBJECTIVES',
                'SCOPE',
                'POLICIES'
            ],
            'name': 'Test PDF Document'
        }
    ]

    results = []

    for i, test_case in enumerate(test_cases, 1):
        print(f"Test Case {i}: {test_case['name']}")
        print("-" * 40)

        file_path = test_case['file_path']
        expected_patterns = test_case['expected_patterns']

        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue

        # Read file
        with open(file_path, 'rb') as f:
            file_bytes = f.read()

        # Extract text using OCR engine
        filename = os.path.basename(file_path)
        extracted = extract_text(file_bytes, filename)

        print(f"Extracted text length: {len(extracted)} characters")
        print()

        # Check for expected patterns
        found_patterns = []
        missing_patterns = []

        for pattern in expected_patterns:
            if pattern.upper() in extracted.upper():
                found_patterns.append(pattern)
            else:
                missing_patterns.append(pattern)

        # Calculate pattern recognition accuracy
        pattern_accuracy = len(found_patterns) / len(expected_patterns) * 100

        print(f"Expected patterns: {len(expected_patterns)}")
        print(f"Found patterns: {len(found_patterns)}")
        print(f"Pattern recognition accuracy: {pattern_accuracy:.1f}%")
        print()

        if found_patterns:
            print("Found patterns:")
            for pattern in found_patterns:
                print(f"  ✓ {pattern}")
        print()

        if missing_patterns:
            print("Missing patterns:")
            for pattern in missing_patterns:
                print(f"  ✗ {pattern}")
        print()

        # Basic text quality metrics
        # Count words and characters
        words = extracted.split()
        word_count = len(words)

        # Check for common OCR errors (basic heuristics)
        error_indicators = ['|', '||', '||TABLE_START||', '||TABLE_END||']
        error_count = sum(extracted.count(indicator) for indicator in error_indicators)

        print("Text Quality Metrics:")
        print(f"  Total words: {word_count}")
        print(f"  Potential formatting artifacts: {error_count}")
        print()

        results.append({
            'test_case': test_case['name'],
            'pattern_accuracy': pattern_accuracy,
            'word_count': word_count,
            'error_count': error_count,
            'found_patterns': len(found_patterns),
            'total_patterns': len(expected_patterns)
        })

    # Summary
    print("=" * 80)
    print("SUMMARY RESULTS")
    print("=" * 80)

    if results:
        avg_pattern_acc = np.mean([r['pattern_accuracy'] for r in results])
        total_words = sum(r['word_count'] for r in results)
        total_errors = sum(r['error_count'] for r in results)

        print(f"Average pattern recognition accuracy: {avg_pattern_acc:.1f}%")
        print(f"Total words extracted: {total_words}")
        print(f"Total formatting artifacts: {total_errors}")
        print()

        print("Detailed Results:")
        print("Test Case".ljust(25), "Pattern Acc".rjust(12), "Words".rjust(8), "Errors".rjust(8))
        print("-" * 61)
        for result in results:
            print(
                result['test_case'].ljust(25),
                f"{result['pattern_accuracy']:.1f}%".rjust(12),
                str(result['word_count']).rjust(8),
                str(result['error_count']).rjust(8)
            )

    return results


def evaluate_real_document(file_path, ground_truth_text=None):
    """
    Evaluate OCR accuracy on a real document
    If ground_truth_text is None, will prompt for manual verification
    """
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None

    print(f"Evaluating real document: {os.path.basename(file_path)}")
    print("-" * 50)

    # Read file
    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    # Extract text
    filename = os.path.basename(file_path)
    extracted = extract_text(file_bytes, filename)

    print("Extracted Text (first 500 chars):")
    print(extracted[:500] + "..." if len(extracted) > 500 else extracted)
    print()

    if ground_truth_text:
        # Calculate metrics
        gt_norm = normalize_text(ground_truth_text)
        ext_norm = normalize_text(extracted)

        cer = calculate_cer(gt_norm, ext_norm)
        wer = calculate_wer(gt_norm, ext_norm)
        char_accuracy = (1 - cer) * 100
        word_accuracy = (1 - wer) * 100

        print(f"Character Error Rate: {cer:.4f}")
        print(f"Word Error Rate: {wer:.4f}")
        print(f"Character Accuracy: {char_accuracy:.2f}%")
        print(f"Word Accuracy: {word_accuracy:.2f}%")

        return {
            'cer': cer,
            'wer': wer,
            'char_accuracy': char_accuracy,
            'word_accuracy': word_accuracy
        }
    else:
        print("No ground truth provided. Manual verification required.")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Evaluate OCR accuracy')
    parser.add_argument('--synthetic', action='store_true', help='Run synthetic tests')
    parser.add_argument('--file', type=str, help='Path to real document to evaluate')
    parser.add_argument('--ground-truth', type=str, help='Ground truth text for real document evaluation')

    args = parser.parse_args()

    if args.file:
        evaluate_real_document(args.file, args.ground_truth)
    else:
        # Default to synthetic evaluation
        evaluate_ocr_accuracy()
        evaluate_ocr_accuracy()
