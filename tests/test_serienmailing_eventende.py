from __future__ import annotations

import io
import unittest

from openpyxl import Workbook

from serienmailing.eventende import (
    UploadedAttachmentFile,
    assemble_eventende_sponsors,
    build_eventende_serienmails,
    build_eventende_summary_dataframe,
)


def _make_workbook_bytes(rows: list[dict]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Deals"
    for index, row in enumerate(rows, start=2):
        worksheet[f"B{index}"] = row.get("sponsor_name", "")
        worksheet[f"D{index}"] = row.get("active", "")
        worksheet[f"E{index}"] = row.get("package", "")
        worksheet[f"K{index}"] = row.get("language", "")
        worksheet[f"L{index}"] = row.get("first_name", "")
        worksheet[f"M{index}"] = row.get("last_name", "")
        worksheet[f"N{index}"] = row.get("to_email", "")
        worksheet[f"O{index}"] = row.get("cc_first_name", "")
        worksheet[f"P{index}"] = row.get("cc_last_name", "")
        worksheet[f"Q{index}"] = row.get("cc_email", "")
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _kontaktliste() -> UploadedAttachmentFile:
    return UploadedAttachmentFile(name="Kontaktliste.xlsx", content=b"PKkontakt")


def _upload(name: str) -> UploadedAttachmentFile:
    return UploadedAttachmentFile(name=name, content=name.encode("utf-8"))


class AssembleEventEndSponsorsTests(unittest.TestCase):
    def test_includes_only_supported_active_packages(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Alpha Premium",
                    "active": "Check",
                    "package": "Premium",
                    "first_name": "Alice",
                    "to_email": "alice@example.com",
                },
                {
                    "sponsor_name": "Beta Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Bob",
                    "to_email": "bob@example.com",
                },
                {
                    "sponsor_name": "Gamma Bronze",
                    "active": "Check",
                    "package": "Bronze",
                    "first_name": "Cara",
                    "to_email": "cara@example.com",
                },
                {
                    "sponsor_name": "Delta Platin",
                    "active": "no",
                    "package": "Platin",
                    "first_name": "Dora",
                    "to_email": "dora@example.com",
                },
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(
                _upload("Alpha Premium_Gesprächsplan.xlsx"),
                _upload("Beta Gold_Gesprächsplan.pdf"),
            ),
            vortragsliste_files=(
                _upload("Beta Gold_Vortragsliste.xlsx"),
            ),
        )

        self.assertEqual(["Alpha Premium", "Beta Gold"], [sponsor.sponsor_name for sponsor in result.sponsors])
        self.assertEqual(2, result.ready_count)
        self.assertEqual(0, result.blocked_count)

    def test_falls_back_to_second_contact_when_first_email_missing(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Fallback Gold",
                    "active": "Check",
                    "package": "Gold",
                    "cc_first_name": "Bernd",
                    "cc_last_name": "Beispiel",
                    "cc_email": "bernd@example.com",
                }
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Fallback Gold_Gesprächsplan.pdf"),),
            vortragsliste_files=(_upload("Fallback Gold_Vortragsliste.xlsx"),),
        )

        sponsor = result.sponsors[0]
        self.assertEqual("bernd@example.com", sponsor.to_email)
        self.assertEqual("", sponsor.cc_email)
        self.assertTrue(sponsor.is_ready)

    def test_premium_requires_excel_gespraechsplan(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Müller & Söhne GmbH",
                    "active": "Check",
                    "package": "Premium",
                    "first_name": "Mila",
                    "to_email": "mila@example.com",
                }
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Müller & Söhne GmbH_Gespraechsplan.xlsx"),),
            vortragsliste_files=(),
        )

        sponsor = result.sponsors[0]
        self.assertTrue(sponsor.is_ready)
        self.assertEqual(
            ("Kontaktliste.xlsx", "Müller & Söhne GmbH_Gespraechsplan.xlsx"),
            sponsor.attachment_names,
        )

    def test_gold_requires_pdf_gespraechsplan_and_excel_vortragsliste(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Acme Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Gina",
                    "to_email": "gina@example.com",
                }
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Acme Gold_Gesprächsplan.pdf"),),
            vortragsliste_files=(_upload("Acme Gold_Vortragsliste.xls"),),
        )

        sponsor = result.sponsors[0]
        self.assertTrue(sponsor.is_ready)
        self.assertEqual(
            ("Kontaktliste.xlsx", "Acme Gold_Gesprächsplan.pdf", "Acme Gold_Vortragsliste.xls"),
            sponsor.attachment_names,
        )

    def test_missing_required_file_blocks_only_that_sponsor(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Ready Premium",
                    "active": "Check",
                    "package": "Premium",
                    "first_name": "Ria",
                    "to_email": "ria@example.com",
                },
                {
                    "sponsor_name": "Blocked Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Ben",
                    "to_email": "ben@example.com",
                },
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Ready Premium_Gesprächsplan.xlsx"),),
            vortragsliste_files=(),
        )

        self.assertEqual(1, result.ready_count)
        self.assertEqual(1, result.blocked_count)
        self.assertTrue(result.sponsors[0].is_ready)
        self.assertFalse(result.sponsors[1].is_ready)
        self.assertIn("Gesprächsplan fehlt", result.sponsors[1].details)
        self.assertIn("Vortragsliste fehlt", result.sponsors[1].details)

    def test_ambiguous_duplicate_matches_block_sponsor(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Acme Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Gina",
                    "to_email": "gina@example.com",
                }
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(
                _upload("Acme Gold_Gesprächsplan.pdf"),
                _upload("ACME_GOLD_Gespraechsplan.pdf"),
            ),
            vortragsliste_files=(_upload("Acme Gold_Vortragsliste.xlsx"),),
        )

        sponsor = result.sponsors[0]
        self.assertFalse(sponsor.is_ready)
        self.assertIn("nicht eindeutig", sponsor.details)

    def test_summary_dataframe_surfaces_readiness_and_attachments(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Ready Premium",
                    "active": "Check",
                    "package": "Premium",
                    "first_name": "Ria",
                    "to_email": "ria@example.com",
                },
                {
                    "sponsor_name": "Blocked Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Ben",
                    "to_email": "ben@example.com",
                },
            ]
        )

        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Ready Premium_Gesprächsplan.xlsx"),),
            vortragsliste_files=(),
        )
        summary_df = build_eventende_summary_dataframe(result.sponsors)

        self.assertEqual(["Bereit", "Blockiert"], summary_df["Status"].tolist())
        self.assertIn("Kontaktliste.xlsx", summary_df.loc[0, "Anhänge"])
        self.assertIn("Vortragsliste fehlt", summary_df.loc[1, "Hinweis"])


class BuildEventEndSerienmailsTests(unittest.TestCase):
    def test_builds_ready_serienmails_with_cc_and_attachments(self):
        excel_bytes = _make_workbook_bytes(
            [
                {
                    "sponsor_name": "Acme Gold",
                    "active": "Check",
                    "package": "Gold",
                    "first_name": "Gina",
                    "to_email": "gina@example.com",
                    "cc_email": "copy@example.com",
                }
            ]
        )
        result = assemble_eventende_sponsors(
            excel_bytes=excel_bytes,
            kontaktliste=_kontaktliste(),
            gespraechsplan_files=(_upload("Acme Gold_Gesprächsplan.pdf"),),
            vortragsliste_files=(_upload("Acme Gold_Vortragsliste.xlsx"),),
        )

        mails = build_eventende_serienmails(
            result.sponsors,
            subject_template="Unterlagen für {firma}",
            body_html_template="<p>Hallo {vorname}</p>",
            sender_email="sender@example.com",
        )

        self.assertEqual(1, len(mails))
        self.assertEqual("copy@example.com", mails[0].cc_email)
        self.assertEqual(3, len(mails[0].attachments))
        self.assertEqual("Unterlagen für Acme Gold", mails[0].subject)
