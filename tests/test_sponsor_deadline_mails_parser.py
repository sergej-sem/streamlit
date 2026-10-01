from __future__ import annotations

import io
import unittest

from openpyxl import Workbook, load_workbook

from sponsor_deadline_mails.parser import (
    build_sponsor_row,
    list_workbook_sheets,
    normalize_lang,
    normalize_package,
    resolve_workbook_layout,
    slugify,
)


def _workbook_bytes_with_sheets(*sheet_names: str) -> bytes:
    workbook = Workbook()
    workbook.active.title = sheet_names[0]
    for name in sheet_names[1:]:
        workbook.create_sheet(name)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _make_sponsor_sheet():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Deals"
    return workbook, worksheet


class SponsorDeadlineMailParserTests(unittest.TestCase):
    def test_list_workbook_sheets_reads_sheet_names(self) -> None:
        excel_bytes = _workbook_bytes_with_sheets("Deals", "Archive", "Extra")

        self.assertEqual(list_workbook_sheets(excel_bytes), ["Deals", "Archive", "Extra"])

    def test_normalize_lang_maps_english_values(self) -> None:
        self.assertEqual(normalize_lang("ENG"), "EN")
        self.assertEqual(normalize_lang("ENGLISH"), "EN")
        self.assertEqual(normalize_lang("en"), "EN")
        self.assertEqual(normalize_lang("DE"), "DE")
        self.assertEqual(normalize_lang(""), "DE")

    def test_normalize_package_only_trims(self) -> None:
        self.assertEqual(normalize_package("  Gold  "), "Gold")

    def test_slugify_normalizes_and_falls_back(self) -> None:
        self.assertEqual(slugify("Alpha & Beta"), "alpha_beta")
        self.assertEqual(slugify("   "), "sponsor")

    def test_build_sponsor_row_returns_active_valid_sponsor(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "Acme GmbH"
        worksheet["D2"] = "ja"
        worksheet["E2"] = "Gold"
        worksheet["K2"] = "ENG"
        worksheet["L2"] = "Alice"
        worksheet["M2"] = "Smith"
        worksheet["N2"] = "alice@example.com"
        worksheet["Q2"] = "copy@example.com"

        sponsor = build_sponsor_row(worksheet, 2)

        self.assertIsNotNone(sponsor)
        self.assertEqual(sponsor.sponsor_name, "Acme GmbH")
        self.assertEqual(sponsor.language, "EN")
        self.assertEqual(sponsor.package, "Gold")
        self.assertEqual(sponsor.to_email, "alice@example.com")
        self.assertEqual(sponsor.cc_email, "copy@example.com")
        self.assertEqual(sponsor.contact_first_name, "Alice")

    def test_build_sponsor_row_falls_back_to_second_contact(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "Fallback AG"
        worksheet["D2"] = "yes"
        worksheet["E2"] = "Platinum"
        worksheet["K2"] = "DE"
        worksheet["O2"] = "Bernd"
        worksheet["P2"] = "Beispiel"
        worksheet["Q2"] = "bernd@example.com"

        sponsor = build_sponsor_row(worksheet, 2)

        self.assertIsNotNone(sponsor)
        self.assertEqual(sponsor.to_email, "bernd@example.com")
        self.assertEqual(sponsor.cc_email, "")
        self.assertEqual(sponsor.contact_first_name, "Bernd")
        self.assertEqual(sponsor.contact_last_name, "Beispiel")

    def test_build_sponsor_row_ignores_sponsor_without_mail(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "No Mail GmbH"
        worksheet["D2"] = "ja"

        self.assertIsNone(build_sponsor_row(worksheet, 2))

    def test_build_sponsor_row_ignores_inactive_deal(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "Inactive GmbH"
        worksheet["D2"] = "no"
        worksheet["N2"] = "inactive@example.com"

        self.assertIsNone(build_sponsor_row(worksheet, 2))

    def test_layout_resolves_shifted_columns_and_header_row(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["A1"] = "Sponsoren für ein weiteres Event"
        headers = [
            "Präsentation erhalten", "ASP 2 E-Mail Adresse", "Onboarding",
            "ASP 1 E-Mail Adresse", "ASP 1 Nachname", "ASP 1 Vorname",
            "Sprache", "Paket", "Deal liegt vor", " Name ",
            "Teilnehmerliste Gesprächswünsche erhalten", "Posting erhalten",
            "Posting gepostet", "Logo", "Sponsoren Vor Ort", "Handout",
            "Booklet Informationen", "Vortragsinformationen",
            "Wunschteilnehmerliste erhalten", "LED Wand Design",
        ]
        for column, header in enumerate(headers, start=1):
            worksheet.cell(3, column, header)
        for column, value in {
            2: "copy@example.com", 4: "primary@example.com", 5: "Example",
            6: "Alex", 7: "ENG", 8: "Gold", 9: "Check", 10: "Acme GmbH",
        }.items():
            worksheet.cell(4, column, value)

        layout = resolve_workbook_layout(worksheet, strict=True)
        sponsor = build_sponsor_row(worksheet, 4, layout)

        self.assertEqual(layout.header_row, 3)
        self.assertEqual(layout.columns["sponsor_name"], "J")
        self.assertEqual(layout.columns["presentation"], "A")
        self.assertEqual(layout.columns["meeting_selection"], "K")
        self.assertEqual(layout.columns["posting_published"], "M")
        self.assertEqual(layout.columns["onboarding"], "C")
        self.assertEqual(sponsor.to_email, "primary@example.com")
        self.assertEqual(sponsor.cc_email, "copy@example.com")
        self.assertEqual(sponsor.sponsor_name, "Acme GmbH")
        self.assertEqual(sponsor.package, "Gold")
        self.assertEqual(sponsor.language, "EN")
        self.assertEqual(sponsor.contact_first_name, "Alex")

    def test_layout_normalizes_case_whitespace_punctuation_and_accents(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append([
            "  NAME  ", "PAKET", "Deal\nliegt vor", "ASP 1 E–Mail-Adresse",
            "pra\u0308sentation erhalten", "LED-Wand-Design",
            "TEILNEHMERLISTE GESPRÄCHSWÜNSCHE ERHALTEN",
        ])

        layout = resolve_workbook_layout(worksheet, strict=True)

        self.assertEqual(layout.columns["contact1_email"], "D")
        self.assertEqual(layout.columns["presentation"], "E")
        self.assertEqual(layout.columns["led_wall"], "F")
        self.assertEqual(layout.columns["meeting_selection"], "G")

    def test_layout_reports_missing_required_headers(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append(["Name", "Paket", "ASP 1 E-Mail Adresse"])

        with self.assertRaisesRegex(ValueError, "Pflichtspalten.*Deal liegt vor"):
            resolve_workbook_layout(worksheet, strict=True)

    def test_layout_requires_an_email_header(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append(["Name", "Paket", "Deal liegt vor"])

        with self.assertRaisesRegex(ValueError, "E-Mail Adresse"):
            resolve_workbook_layout(worksheet, strict=True)

    def test_layout_keeps_missing_optional_headers_absent(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append(["Name", "Paket", "Deal liegt vor", "ASP 2 E-Mail Adresse"])
        worksheet.append(["Acme GmbH", "Gold", "Check", "second@example.com"])

        layout = resolve_workbook_layout(worksheet, strict=True)
        sponsor = build_sponsor_row(worksheet, 2, layout)

        self.assertNotIn("contact1_email", layout.columns)
        self.assertNotIn("language", layout.columns)
        self.assertNotIn("logo", layout.columns)
        self.assertNotIn("onboarding", layout.columns)
        self.assertEqual(sponsor.to_email, "second@example.com")
        self.assertEqual(sponsor.cc_email, "")
        self.assertEqual(sponsor.language, "DE")
        self.assertEqual(sponsor.contact_first_name, "")

    def test_layout_rejects_duplicate_semantic_headers(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append(["Name", "Paket", "Deal liegt vor", "ASP 1 E-Mail Adresse", "Logo", "Logo erhalten"])

        with self.assertRaisesRegex(ValueError, "Mehrdeutige.*Logo"):
            resolve_workbook_layout(worksheet, strict=True)

    def test_strict_layout_rejects_headerless_worksheet(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "Acme GmbH"
        worksheet["N2"] = "primary@example.com"

        with self.assertRaisesRegex(ValueError, "Kopfzeile"):
            resolve_workbook_layout(worksheet, strict=True)
        self.assertEqual(resolve_workbook_layout(worksheet).columns["sponsor_name"], "B")

    def test_layout_works_with_read_only_worksheet_and_blank_first_column(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B1"] = "Name"
        worksheet["D1"] = "Deal liegt vor"
        worksheet["E1"] = "Paket"
        worksheet["N1"] = "ASP 1 E-Mail Adresse"
        buffer = io.BytesIO()
        workbook.save(buffer)
        readonly_workbook = load_workbook(io.BytesIO(buffer.getvalue()), read_only=True)
        self.addCleanup(readonly_workbook.close)
        readonly_workbook.active.reset_dimensions()

        layout = resolve_workbook_layout(readonly_workbook.active, strict=True)

        self.assertEqual(layout.header_row, 1)
        self.assertEqual(layout.columns["sponsor_name"], "B")

    def test_build_sponsor_row_resolves_reordered_contact_fallback(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append([
            "Contact 2 email", "Contact 2 last name", "Contact 2 first name",
            "Company name", "Package", "Deal active", "Language",
            "Contact 1 email",
        ])
        worksheet.append(["second@example.com", "Example", "Alex", "Acme GmbH", "Gold", "Check", "EN", None])

        sponsor = build_sponsor_row(worksheet, 2)

        self.assertEqual(sponsor.to_email, "second@example.com")
        self.assertEqual(sponsor.cc_email, "")
        self.assertEqual(sponsor.contact_first_name, "Alex")
        self.assertEqual(sponsor.contact_last_name, "Example")

    def test_build_sponsor_row_ignores_header_row(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet.append(["Name", "Paket", "Deal liegt vor", "ASP 1 E-Mail Adresse"])

        self.assertIsNone(build_sponsor_row(worksheet, 1))

    def test_deal_checks_accept_excel_boolean_numeric_and_unicode_markers(self) -> None:
        workbook, worksheet = _make_sponsor_sheet()
        self.addCleanup(workbook.close)
        worksheet["B2"] = "Acme GmbH"
        worksheet["N2"] = "primary@example.com"
        for value in [True, 1, 1.0, "✓", "✔", "✔️", "✅", "☑"]:
            with self.subTest(value=value):
                worksheet["D2"] = value
                self.assertIsNotNone(build_sponsor_row(worksheet, 2))
        for value in [False, 0, "nein", "no", "false"]:
            with self.subTest(value=value):
                worksheet["D2"] = value
                self.assertIsNone(build_sponsor_row(worksheet, 2))


if __name__ == "__main__":
    unittest.main()
