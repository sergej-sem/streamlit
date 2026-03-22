from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from sponsor_deadline_mails.core import DeadlineItem, GeneratedMail, GenerationResult, SponsorRow
from sponsor_deadline_mails.rendering import (
    build_html_body,
    build_intro,
    build_subject,
    build_summary_dataframe,
    format_event_date,
    render_deadline_rows,
)


class SponsorDeadlineMailRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sponsor_de = SponsorRow(
            row_number=7,
            sponsor_name="Acme GmbH",
            package="Gold",
            language="DE",
            to_email="kontakt@example.com",
            cc_email="cc@example.com",
            contact_first_name="Jörg",
            contact_last_name="",
        )
        self.sponsor_en = SponsorRow(
            row_number=8,
            sponsor_name="Alpha & Beta",
            package="Platinum",
            language="EN",
            to_email="english@example.com",
            cc_email="",
            contact_first_name="Alice & Bob",
            contact_last_name="",
        )
        self.items = [
            DeadlineItem(
                due_date_de="26.03.2026",
                due_date_en="26/03/2026",
                text_de="Sende das LED-Wand-Design.",
                text_en="Send the LED wall design.",
                status="red",
            ),
            DeadlineItem(
                due_date_de="20.04.2026",
                due_date_en="20/04/2026",
                text_de="Sende das Handout.",
                text_en="Send the handout.",
                status="green",
            ),
        ]

    def test_build_subject_returns_language_specific_text(self) -> None:
        self.assertEqual(
            build_subject("EN", "Acme"),
            "Important Information // mysecurityevent // Deadlines // Acme",
        )
        self.assertEqual(
            build_subject("DE", "Acme"),
            "Wichtige Informationen // mysecurityevent // Deadlines // Acme",
        )

    def test_format_event_date_uses_language_specific_format(self) -> None:
        value = date(2026, 5, 7)

        self.assertEqual(format_event_date(value, "DE"), "07.05.2026")
        self.assertEqual(format_event_date(value, "EN"), "07/05/2026")

    def test_build_intro_escapes_content_and_formats_dates(self) -> None:
        salutation, intro, explainer = build_intro(
            self.sponsor_en,
            "New York & Partners",
            date(2026, 5, 5),
            date(2026, 5, 7),
        )

        self.assertIn("Alice &amp; Bob", salutation)
        self.assertIn("New York &amp; Partners", intro)
        self.assertIn("05/05/2026", intro)
        self.assertIn("07/05/2026", intro)
        self.assertIn("overview", explainer.lower())

    def test_render_deadline_rows_contains_due_dates_tasks_and_labels(self) -> None:
        html_rows = render_deadline_rows(self.items, "DE")

        self.assertIn("26.03.2026", html_rows)
        self.assertIn("Sende das LED-Wand-Design.", html_rows)
        self.assertIn("Handlungsbedarf", html_rows)
        self.assertIn("Bereits erhalten", html_rows)

    def test_build_html_body_contains_core_sections(self) -> None:
        html_body = build_html_body(
            self.sponsor_en,
            self.items,
            "Berlin & Brandenburg",
            date(2026, 5, 5),
            date(2026, 5, 7),
        )

        self.assertIn("<!DOCTYPE html>", html_body)
        self.assertIn("Alpha &amp; Beta", html_body)
        self.assertIn("Deadline Overview", html_body)
        self.assertIn("Berlin &amp; Brandenburg", html_body)
        self.assertIn("Send the LED wall design.", html_body)
        self.assertIn("Action required", html_body)

    def test_build_summary_dataframe_uses_expected_columns_and_values(self) -> None:
        result = GenerationResult(
            sheet_name="Deals",
            event_city="Berlin",
            event_start=date(2026, 5, 5),
            event_end=date(2026, 5, 7),
            mails=(
                GeneratedMail(
                    row_number=7,
                    sponsor_name="Acme GmbH",
                    language="DE",
                    package="Gold",
                    to_email="kontakt@example.com",
                    cc_email="cc@example.com",
                    subject="Test Subject",
                    html_body="<html></html>",
                    html_file_name="007_acme.html",
                    green_count=2,
                    red_count=3,
                    yellow_count=1,
                    white_count=4,
                ),
            ),
            processed_count=1,
            skipped_count=0,
        )

        summary_df = build_summary_dataframe(result)

        self.assertEqual(
            list(summary_df.columns),
            [
                "row_number",
                "sponsor_name",
                "language",
                "package",
                "to_email",
                "cc_email",
                "subject",
                "html_file_name",
                "green_count",
                "red_count",
                "yellow_count",
                "white_count",
                "outlook_result",
            ],
        )
        expected = pd.DataFrame(
            [
                {
                    "row_number": 7,
                    "sponsor_name": "Acme GmbH",
                    "language": "DE",
                    "package": "Gold",
                    "to_email": "kontakt@example.com",
                    "cc_email": "cc@example.com",
                    "subject": "Test Subject",
                    "html_file_name": "007_acme.html",
                    "green_count": 2,
                    "red_count": 3,
                    "yellow_count": 1,
                    "white_count": 4,
                    "outlook_result": "not_requested",
                }
            ]
        )
        pd.testing.assert_frame_equal(summary_df.reset_index(drop=True), expected)


if __name__ == "__main__":
    unittest.main()
