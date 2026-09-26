from django.test import SimpleTestCase

from api.views import extraction_quality


class ExtractionQualityTests(SimpleTestCase):

    def test_empty_extraction_is_blocking(self):
        result = extraction_quality('', [])

        self.assertTrue(result['blocking'])
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['detected_sections'], 0)

    def test_readable_sections_are_allowed(self):
        result = extraction_quality(
            '1.0 POLICY\nThe office shall retain the record.',
            [{'subtitle': '1.0 POLICY', 'content': 'The office shall retain the record.'}],
        )

        self.assertFalse(result['blocking'])
        self.assertFalse(result['needs_review'])

    def test_suspicious_single_section_is_warning_only(self):
        result = extraction_quality(
            ' '.join(['word'] * 500),
            [{'subtitle': 'Full Document', 'content': ' '.join(['word'] * 500)}],
        )

        self.assertFalse(result['blocking'])
        self.assertTrue(result['needs_review'])
        self.assertTrue(result['warnings'])