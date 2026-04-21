import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from teilnehmerliste_generator import pdf_render
from teilnehmerliste_generator.pdf_render import (
    CAP_PAGE1,
    COLUMN_GAP_PADDING,
    MIN_ROW_FONT_SIZE,
    P1_COMPANY_X,
    P1_JOB_X,
    P2_COMPANY_X,
    P2_JOB_X,
    ROW_FONT_SIZE,
    collect_shrunk_company_names,
)


class CollectShrunkCompanyNamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.font_dir = Path(__file__).resolve().parents[1] / "fonts"

    def test_returns_empty_when_no_company_hits_min_size(self) -> None:
        df = pd.DataFrame(
            [
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Beta AG", "Jobbezeichnung": "Fachbereich"},
            ]
        )

        with patch("teilnehmerliste_generator.pdf_render.fit_text", side_effect=lambda txt, font, base, max_width, min_size=MIN_ROW_FONT_SIZE: (txt, ROW_FONT_SIZE)):
            result = collect_shrunk_company_names(df, self.font_dir)

        self.assertEqual([], result)

    def test_returns_unique_company_names_and_ignores_blank_values(self) -> None:
        df = pd.DataFrame(
            [
                {"Unternehmensname": "Lange Firma GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": None, "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "", "Jobbezeichnung": "Fachbereich"},
                {"Unternehmensname": "Lange Firma GmbH", "Jobbezeichnung": "Fachbereich"},
                {"Unternehmensname": "Kurze AG", "Jobbezeichnung": "Fachbereich"},
            ]
        )

        def fake_fit_text(txt, font, base, max_width, min_size=MIN_ROW_FONT_SIZE):
            if txt == "Lange Firma GmbH":
                return txt, MIN_ROW_FONT_SIZE
            return txt, ROW_FONT_SIZE

        with patch("teilnehmerliste_generator.pdf_render.fit_text", side_effect=fake_fit_text):
            result = collect_shrunk_company_names(df, self.font_dir)

        self.assertEqual(["Lange Firma GmbH"], result)

    def test_respects_different_company_widths_on_first_and_follow_up_pages(self) -> None:
        rows = [{"Unternehmensname": "Erste Seite GmbH", "Jobbezeichnung": "C-Level"}]
        for index in range(CAP_PAGE1 - 1):
            rows.append({"Unternehmensname": f"Filler {index:02d}", "Jobbezeichnung": "Fachbereich"})
        rows.append({"Unternehmensname": "Zweite Seite GmbH", "Jobbezeichnung": "Fachbereich"})
        df = pd.DataFrame(rows)

        page1_width = (P1_JOB_X - P1_COMPANY_X) - COLUMN_GAP_PADDING
        page2_width = (P2_JOB_X - P2_COMPANY_X) - COLUMN_GAP_PADDING

        def fake_fit_text(txt, font, base, max_width, min_size=MIN_ROW_FONT_SIZE):
            if txt == "Erste Seite GmbH":
                size = MIN_ROW_FONT_SIZE if max_width == page1_width else ROW_FONT_SIZE
                return txt, size
            if txt == "Zweite Seite GmbH":
                size = MIN_ROW_FONT_SIZE if max_width == page2_width else ROW_FONT_SIZE
                return txt, size
            return txt, ROW_FONT_SIZE

        with patch("teilnehmerliste_generator.pdf_render.fit_text", side_effect=fake_fit_text):
            result = collect_shrunk_company_names(df, self.font_dir)

        self.assertEqual(["Erste Seite GmbH", "Zweite Seite GmbH"], result)


if __name__ == "__main__":
    unittest.main()
