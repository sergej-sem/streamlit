from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta

from openpyxl import Workbook

from sponsor_deadline_mails.events import (
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    DEFAULT_EVENT_VENUE,
    DEFAULT_ONBOARDING_URL,
    DeadlineSchedule,
)
from sponsor_deadline_mails.parser import SponsorRow, WorksheetLayout
from sponsor_deadline_mails.planner import (
    STATUS_COLS,
    build_deadlines,
    is_premium_package,
    is_talk_package,
    is_truthy_marker,
    status_from_column,
)


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


class DeadlineScheduleTests(unittest.TestCase):
    def test_munich_schedule_matches_all_supplied_deadlines(self) -> None:
        self.assertEqual(DEFAULT_EVENT_START, date(2026, 11, 17))
        self.assertEqual(DEFAULT_EVENT_END, date(2026, 11, 19))
        schedule = DeadlineSchedule.relative_to(DEFAULT_EVENT_START)
        self.assertEqual(schedule, DeadlineSchedule(
            onboarding_start=date(2026, 8, 18),
            onboarding_end=date(2026, 8, 31),
            materials=date(2026, 10, 15),
            presentation=date(2026, 10, 29),
            participant_list=date(2026, 11, 3),
            meeting_selection=date(2026, 11, 10),
        ))
        schedule.validate(DEFAULT_EVENT_START)

    def test_future_event_uses_same_offsets_across_year_boundary(self) -> None:
        event_start = date(2027, 1, 12)
        schedule = DeadlineSchedule.relative_to(event_start)
        self.assertEqual(schedule.materials, date(2026, 12, 10))
        self.assertEqual(schedule.presentation, date(2026, 12, 24))
        self.assertEqual(schedule.participant_list, date(2026, 12, 29))
        self.assertEqual(schedule.meeting_selection, date(2027, 1, 5))
        schedule.validate(event_start)

    def test_validation_rejects_reversed_or_post_event_deadlines(self) -> None:
        schedule = DeadlineSchedule.relative_to(DEFAULT_EVENT_START)
        for invalid in (
            replace(schedule, onboarding_end=schedule.onboarding_start - timedelta(days=1)),
            replace(schedule, materials=DEFAULT_EVENT_START),
            replace(schedule, presentation=DEFAULT_EVENT_START + timedelta(days=1)),
            replace(schedule, meeting_selection=DEFAULT_EVENT_START),
            replace(schedule, onboarding_end=DEFAULT_EVENT_START),
            replace(schedule, meeting_selection=schedule.participant_list - timedelta(days=1)),
        ):
            with self.subTest(schedule=invalid), self.assertRaises(ValueError):
                invalid.validate(DEFAULT_EVENT_START)

    def test_validation_allows_shared_deadlines_and_independent_task_order(self) -> None:
        schedule = DeadlineSchedule.relative_to(DEFAULT_EVENT_START)
        for valid in (
            replace(schedule, materials=schedule.presentation),
            replace(schedule, presentation=schedule.participant_list),
            replace(schedule, presentation=schedule.meeting_selection),
            replace(schedule, materials=schedule.meeting_selection),
            replace(schedule, meeting_selection=schedule.participant_list),
            replace(schedule, onboarding_end=schedule.onboarding_start),
        ):
            with self.subTest(schedule=valid):
                valid.validate(DEFAULT_EVENT_START)

    def test_validation_rejects_non_date_values(self) -> None:
        schedule = DeadlineSchedule.relative_to(DEFAULT_EVENT_START)
        with self.assertRaisesRegex(ValueError, "Datumswerte"):
            replace(schedule, materials="2026-10-15").validate(DEFAULT_EVENT_START)


class SponsorDeadlineMailPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        workbook = Workbook()
        self.addCleanup(workbook.close)
        self.ws = workbook.active
        self.ws.title = "Deals"
        self.layout = WorksheetLayout(header_row=1, columns=dict(STATUS_COLS))

    def deadlines(self, package: str = "Gold", **kwargs):
        options = {"layout": self.layout, "today": date(2026, 10, 1)}
        options.update(kwargs)
        return {item.key: item for item in build_deadlines(self.ws, _make_sponsor(package), **options)}

    def test_explicit_completion_markers_and_dates_are_green(self) -> None:
        completed = (
            True, 1, 1.0, " Check ", "x", "✓", "✔", "☑", "✅", "✔️", "TRUE", "1",
            "done", "erhalten", "received", "ja", "yes", "ok", "gebucht",
            date(2026, 9, 5), datetime(2026, 9, 5, 10, 30), "05.09.2026",
            "2026-09-05", "05/09/2026",
        )
        for value in completed:
            with self.subTest(value=value):
                self.assertTrue(is_truthy_marker(value))

    def test_negative_markers_and_unknown_notes_do_not_count_as_received(self) -> None:
        incomplete = (
            None, "", "  ", False, 0, 2, "false", "0", "nein", "no", "offen",
            "ausstehend", "kein Check", "noch nicht erhalten", "in Bearbeitung",
            "bitte nachfragen", "31.02.2026", "=TRUE()",
        )
        for value in incomplete:
            with self.subTest(value=value):
                self.assertFalse(is_truthy_marker(value))

    def test_package_helpers_detect_talk_and_premium(self) -> None:
        for package in ("gold", "platin", "platinum", "Gold Sponsor", "Platin-Sponsor"):
            with self.subTest(package=package):
                self.assertTrue(is_talk_package(package))
        for package in ("bronze", "Premium", "Silver", "golden"):
            with self.subTest(package=package):
                self.assertFalse(is_talk_package(package))
        self.assertTrue(is_premium_package("Premium"))
        self.assertTrue(is_premium_package("super premium plus"))
        self.assertFalse(is_premium_package("gold"))

    def test_status_from_column_maps_explicit_markers(self) -> None:
        self.ws["S2"] = ""
        self.ws["W2"] = "received"
        self.assertEqual(status_from_column(self.ws, 2, "S"), "red")
        self.assertEqual(status_from_column(self.ws, 2, "W"), "green")
        self.ws["S2"] = "false"
        self.assertEqual(status_from_column(self.ws, 2, "S"), "red")

    def test_non_talk_packages_omit_irrelevant_tasks(self) -> None:
        for package in ("Bronze", "Silber", "Premium"):
            with self.subTest(package=package):
                items = self.deadlines(package)
                self.assertNotIn("talk_info", items)
                self.assertNotIn("presentation", items)

    def test_talk_package_reads_talk_statuses_from_excel(self) -> None:
        self.ws["X2"] = "done"
        self.ws["AG2"] = ""
        items = self.deadlines()
        self.assertEqual(items["talk_info"].status, "green")
        self.assertEqual(items["presentation"].status, "red")

    def test_onboarding_and_meeting_selection_checks_are_green(self) -> None:
        self.ws["Y2"] = "Check"
        self.ws["AH2"] = "Check"
        items = self.deadlines()
        self.assertEqual(items["onboarding"].status, "green")
        self.assertEqual(items["meeting_selection"].status, "green")
        self.assertEqual(self.deadlines(today=date(2026, 11, 20))["meeting_selection"].status, "green")

    def test_meeting_selection_is_yellow_until_deadline_and_red_from_deadline(self) -> None:
        for day, expected in (
            (date(2026, 11, 2), "yellow"),
            (date(2026, 11, 3), "yellow"),
            (date(2026, 11, 9), "yellow"),
            (date(2026, 11, 10), "red"),
            (date(2026, 11, 11), "red"),
        ):
            with self.subTest(day=day):
                self.assertEqual(self.deadlines(today=day)["meeting_selection"].status, expected)

    def test_posting_received_is_distinct_from_posting_published(self) -> None:
        self.ws["AE2"] = "Check"
        items = self.deadlines()
        self.assertEqual(items["posting_published"].status, "red")
        self.ws["AF2"] = "Check"
        self.assertEqual(self.deadlines()["posting_published"].status, "green")

    def test_reordered_status_columns_use_resolved_layout(self) -> None:
        columns = dict(STATUS_COLS)
        columns.update({"onboarding": "C", "meeting_selection": "D", "logo": "E"})
        layout = WorksheetLayout(header_row=1, columns=columns)
        self.ws["C2"] = "Check"
        self.ws["D2"] = "Check"
        self.ws["E2"] = "Check"
        self.ws["Y2"] = "offen"
        self.ws["AH2"] = "offen"
        self.ws["S2"] = "offen"
        items = self.deadlines(layout=layout)
        for key in ("onboarding", "meeting_selection", "logo"):
            with self.subTest(key=key):
                self.assertEqual(items[key].status, "green")

    def test_missing_required_status_header_stops_generation(self) -> None:
        columns = dict(STATUS_COLS)
        del columns["booklet"]
        with self.assertRaisesRegex(ValueError, "Statusspalten.*Booklet"):
            self.deadlines(layout=WorksheetLayout(header_row=1, columns=columns))

    def test_missing_optional_status_headers_are_neutral(self) -> None:
        columns = dict(STATUS_COLS)
        del columns["onboarding"]
        del columns["meeting_selection"]
        items = self.deadlines(
            layout=WorksheetLayout(header_row=1, columns=columns),
            today=date(2026, 11, 20),
        )
        self.assertEqual(items["onboarding"].status, "white")
        self.assertEqual(items["meeting_selection"].status, "white")

    def test_missing_talk_headers_only_affect_talk_packages(self) -> None:
        columns = dict(STATUS_COLS)
        del columns["talk_info"]
        del columns["presentation"]
        layout = WorksheetLayout(header_row=1, columns=columns)
        self.deadlines("Bronze", layout=layout)
        with self.assertRaisesRegex(ValueError, "Präsentation erhalten.*Vortragsinformationen"):
            self.deadlines("Gold", layout=layout)

    def test_munich_text_dates_link_venue_and_checkin(self) -> None:
        items = self.deadlines(onboarding_url=DEFAULT_ONBOARDING_URL, venue=DEFAULT_EVENT_VENUE)
        self.assertIn("18.08.2026 – 31.08.2026", items["onboarding"].text_de)
        self.assertEqual(items["onboarding"].link_url, DEFAULT_ONBOARDING_URL)
        self.assertEqual(items["onboarding"].link_label_en, "1:1 Onboarding Meeting")
        for key in ("led_wall", "booklet", "team_on_site", "talk_info", "handout"):
            with self.subTest(key=key):
                self.assertEqual(items[key].due_date_de, "15.10.2026")
        self.assertEqual(items["presentation"].due_date_de, "29.10.2026")
        self.assertEqual(items["participant_list"].due_date_de, "03.11.2026")
        self.assertEqual(items["meeting_selection"].due_date_de, "10.11.2026")
        self.assertIn("03.11.2026", items["meeting_selection"].text_de)
        self.assertEqual(items["event_start"].due_date_de, "17.11.2026")
        self.assertEqual(items["event_start"].due_date_en, "17/11/2026")
        self.assertIn(DEFAULT_EVENT_VENUE, items["event_start"].text_de)
        self.assertIn("14:00 und 16:00", items["event_start"].text_de)
        self.assertEqual(items["event_start"].status, "white")

    def test_future_event_updates_all_dates_and_references(self) -> None:
        event_start = date(2027, 1, 12)
        items = self.deadlines(event_start=event_start, today=date(2026, 9, 1))
        self.assertEqual(items["led_wall"].due_date_de, "10.12.2026")
        self.assertEqual(items["presentation"].due_date_de, "24.12.2026")
        self.assertEqual(items["participant_list"].due_date_de, "29.12.2026")
        self.assertIn("29.12.2026", items["meeting_selection"].text_de)
        self.assertIn("29/12/2026", items["meeting_selection"].text_en)
        self.assertEqual(items["meeting_selection"].due_date_de, "05.01.2027")
        self.assertEqual(items["event_start"].due_date_de, "12.01.2027")
        self.assertNotIn("2026", items["event_start"].text_de)
        self.assertNotIn("Allianz", items["event_start"].text_de)
        self.assertEqual(items["onboarding"].link_url, "")

    def test_explicitly_empty_venue_and_link_stay_empty_even_for_munich_date(self) -> None:
        items = self.deadlines(onboarding_url="", venue="")
        self.assertEqual(items["onboarding"].link_url, "")
        self.assertNotIn("Allianz", items["event_start"].text_de)

    def test_custom_event_schedule_overrides_all_dates_consistently(self) -> None:
        custom = replace(
            DeadlineSchedule.relative_to(DEFAULT_EVENT_START),
            materials=date(2026, 10, 13),
            participant_list=date(2026, 11, 2),
            meeting_selection=date(2026, 11, 9),
        )
        items = self.deadlines(schedule=custom, today=date(2026, 11, 9))
        self.assertEqual(items["booklet"].due_date_de, "13.10.2026")
        self.assertEqual(items["participant_list"].due_date_de, "02.11.2026")
        self.assertIn("02.11.2026", items["meeting_selection"].text_de)
        self.assertEqual(items["meeting_selection"].due_date_de, "09.11.2026")
        self.assertEqual(items["meeting_selection"].status, "red")


if __name__ == "__main__":
    unittest.main()
