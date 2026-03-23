import unittest
from datetime import datetime
from unittest.mock import patch

from teilnehmerliste_generator.output_naming import (
    build_pdf_filename,
    extract_segment_code_and_year,
    normalize_segment_year,
)


class NormalizeSegmentYearTests(unittest.TestCase):
    def test_normalizes_two_digit_year(self) -> None:
        self.assertEqual("2026", normalize_segment_year("26"))

    def test_keeps_four_digit_year(self) -> None:
        self.assertEqual("2026", normalize_segment_year("2026"))


class ExtractSegmentCodeAndYearTests(unittest.TestCase):
    def test_extracts_from_code_year_token(self) -> None:
        self.assertEqual(("BER", "2026"), extract_segment_code_and_year("BER26"))

    def test_extracts_from_year_code_token(self) -> None:
        self.assertEqual(("BER", "2026"), extract_segment_code_and_year("26BER"))

    def test_extracts_from_split_tokens(self) -> None:
        self.assertEqual(
            ("BER", "2026"),
            extract_segment_code_and_year("MSE BER 26 Teilnehmer"),
        )

    def test_extracts_from_year_before_code_tokens(self) -> None:
        self.assertEqual(
            ("DOR", "2026"),
            extract_segment_code_and_year("2026 DOR Executive"),
        )

    def test_returns_empty_values_when_no_known_segment_is_found(self) -> None:
        self.assertEqual(("", ""), extract_segment_code_and_year("ohne bekannten code"))


class BuildPdfFilenameTests(unittest.TestCase):
    @patch("teilnehmerliste_generator.output_naming.datetime")
    def test_builds_filename_with_segment_language_and_date(self, mock_datetime) -> None:
        mock_datetime.now.return_value = datetime(2026, 3, 23)

        result = build_pdf_filename("MSE BER 26 Teilnehmer", "de", encrypt=False)

        self.assertEqual("mse_Teilnehmerliste_BER2026_DE_23032026.pdf", result)

    @patch("teilnehmerliste_generator.output_naming.datetime")
    def test_builds_filename_without_segment_when_none_can_be_extracted(self, mock_datetime) -> None:
        mock_datetime.now.return_value = datetime(2026, 3, 23)

        result = build_pdf_filename("Allgemeine Liste", "en", encrypt=False)

        self.assertEqual("mse_Teilnehmerliste_EN_23032026.pdf", result)

    @patch("teilnehmerliste_generator.output_naming.datetime")
    def test_appends_pw_suffix_for_encrypted_files(self, mock_datetime) -> None:
        mock_datetime.now.return_value = datetime(2026, 3, 23)

        result = build_pdf_filename("26DOR", "de", encrypt=True)

        self.assertEqual("mse_Teilnehmerliste_DOR2026_DE_23032026_PW.pdf", result)


if __name__ == "__main__":
    unittest.main()
