from __future__ import annotations

import unittest
from datetime import date

from openpyxl import Workbook

from sponsor_deadline_mails.parser import SponsorRow
from sponsor_deadline_mails.planner import (
    STATUS_COLS,
    build_deadlines,
    is_premium_package,
    is_talk_package,
    is_truthy_marker,
    status_from_column,
)


def _make_sheet():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Deals"
    return workbook, worksheet


def _make_sponsor(package: str, *, row_number: int = 2) -> SponsorRow:
    return SponsorRow(
        row_number=row_number,
        sponsor_name="Acme",
        package=package,
        language="DE",
        to_email="kontakt@example.com",
        cc_email="",
        contact_first_name="Alex",
        contact_last_name="",
    )


class SponsorDeadlineMailPlannerTests(unittest.TestCase):
    def test_is_truthy_marker_handles_empty_and_filled_values(self) -> None:
        self.assertFalse(is_truthy_marker(None))
        self.assertFalse(is_truthy_marker(""))
        self.assertTrue(is_truthy_marker(True))
        self.assertTrue(is_truthy_marker(1))
        self.assertTrue(is_truthy_marker("x"))
        self.assertTrue(is_truthy_marker(date(2026, 5, 5)))

    def test_package_helpers_detect_talk_and_premium(self) -> None:
        self.assertTrue(is_talk_package("gold"))
        self.assertTrue(is_talk_package("platin"))
        self.assertTrue(is_talk_package("platinum"))
        self.assertFalse(is_talk_package("bronze"))

        self.assertTrue(is_premium_package("Premium"))
        self.assertTrue(is_premium_package("super premium plus"))
        self.assertFalse(is_premium_package("gold"))

    def test_status_from_column_maps_empty_to_red_and_content_to_green(self) -> None:
        workbook, worksheet = _make_sheet()
        self.addCleanup(workbook.close)
        worksheet[f"{STATUS_COLS['logo']}2"] = ""
        worksheet[f"{STATUS_COLS['booklet']}2"] = "received"

        self.assertEqual(status_from_column(worksheet, 2, STATUS_COLS["logo"]), "red")
        self.assertEqual(status_from_column(worksheet, 2, STATUS_COLS["booklet"]), "green")

    def test_build_deadlines_for_non_talk_package_keeps_talk_tasks_white(self) -> None:
        workbook, worksheet = _make_sheet()
        self.addCleanup(workbook.close)
        sponsor = _make_sponsor("Bronze")

        items = build_deadlines(worksheet, sponsor)
        by_text = {item.text_de: item for item in items}

        self.assertIn("Sende uns die Vortragsinformationen zu.", by_text)
        self.assertIn("Sende uns die Vortragspräsentation zu.", by_text)
        self.assertEqual(by_text["Sende uns die Vortragsinformationen zu."].status, "white")
        self.assertEqual(by_text["Sende uns die Vortragspräsentation zu."].status, "white")

    def test_build_deadlines_for_talk_package_reads_talk_statuses_from_excel(self) -> None:
        workbook, worksheet = _make_sheet()
        self.addCleanup(workbook.close)
        sponsor = _make_sponsor("Gold")
        worksheet[f"{STATUS_COLS['talk_info']}2"] = "done"
        worksheet[f"{STATUS_COLS['presentation']}2"] = ""

        items = build_deadlines(worksheet, sponsor)
        by_text = {item.text_de: item for item in items}

        self.assertEqual(by_text["Sende uns die Vortragsinformationen zu."].status, "green")
        self.assertEqual(by_text["Sende uns die Vortragspräsentation zu."].status, "red")

    def test_build_deadlines_for_premium_package_excludes_talk_tasks(self) -> None:
        workbook, worksheet = _make_sheet()
        self.addCleanup(workbook.close)
        sponsor = _make_sponsor("Premium")
        worksheet[f"{STATUS_COLS['logo']}2"] = "received"
        worksheet[f"{STATUS_COLS['target_accounts']}2"] = ""
        worksheet[f"{STATUS_COLS['led_wall']}2"] = "done"

        items = build_deadlines(worksheet, sponsor)
        texts = {item.text_de for item in items}
        statuses = {item.status for item in items}

        self.assertNotIn("Sende uns die Vortragsinformationen zu.", texts)
        self.assertNotIn("Sende uns die Vortragspräsentation zu.", texts)
        self.assertIn("red", statuses)
        self.assertIn("green", statuses)
        self.assertIn("yellow", statuses)
        self.assertIn("white", statuses)


if __name__ == "__main__":
    unittest.main()
