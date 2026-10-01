from __future__ import annotations

import io
import unittest
from contextlib import ExitStack
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

from shared.config import ConfigError, ImapDraftSettings, SmtpSendSettings
from sponsor_deadline_mails.imap_drafts import ImapDraftRecord
from sponsor_deadline_mails.smtp_sender import SmtpSendRecord


def _sponsor_workbook_bytes(
    sponsor_name: str = "Test Sponsor", second_sponsor_name: str | None = None
) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Deals"
    headers = {
        "B": " Name",
        "D": "Deal liegt vor",
        "E": "Paket ",
        "K": "Sprache",
        "L": "ASP 1 Vorname",
        "M": "ASP 1 Nachname",
        "N": "ASP 1 E-Mail Adresse",
        "O": "ASP 2 Vorname",
        "P": "ASP 2 Nachname",
        "Q": "ASP 2 E-Mail Adresse",
        "S": "Logo",
        "T": "Sponsoren Vor Ort",
        "V": "Handout",
        "W": "Booklet Informationen",
        "X": "Vortragsinformationen",
        "Y": "Onboarding",
        "Z": "Wunschteilnehmerliste erhalten",
        "AA": "LED Wand Design",
        "AE": "Posting erhalten",
        "AF": "Posting gepostet",
        "AG": "Präsentation erhalten",
        "AH": "Teilnehmerliste Gesprächswünsche erhalten",
    }
    for column, header in headers.items():
        worksheet[f"{column}1"] = header
    for column, value in {
        "B": sponsor_name,
        "D": "check",
        "E": "Gold",
        "K": "DE",
        "L": "Alex",
        "M": "Example",
        "N": "sponsor@example.com",
        "S": "check",
        "Y": "check",
    }.items():
        worksheet[f"{column}2"] = value
    if second_sponsor_name:
        for column in headers:
            worksheet[f"{column}3"] = worksheet[f"{column}2"].value
        worksheet["B3"] = second_sponsor_name
        worksheet["N3"] = "second.sponsor@example.com"
    archive = workbook.copy_worksheet(worksheet)
    archive.title = "Archive"
    archive["B2"] = "Archive Sponsor"
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


class SponsorDeadlineMailsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        excel_bytes = _sponsor_workbook_bytes()
        uploaded_file = SimpleNamespace(
            name="sponsor_test.xlsx",
            getvalue=lambda: excel_bytes,
        )
        self.upload = self.patches.enter_context(
            patch("streamlit.file_uploader", return_value=uploaded_file)
        )
        self.imap_settings = self.patches.enter_context(
            patch(
                "shared.config.load_imap_draft_settings",
                return_value=ImapDraftSettings(host="test.invalid", port=993),
            )
        )
        self.smtp_settings = self.patches.enter_context(
            patch(
                "shared.config.load_smtp_send_settings",
                return_value=SmtpSendSettings(host="test.invalid", port=465),
            )
        )
        self.smtp = self.patches.enter_context(
            patch("sponsor_deadline_mails.create_smtp_sends", return_value=[])
        )
        self.imap = self.patches.enter_context(
            patch("sponsor_deadline_mails.create_imap_drafts", return_value=[])
        )

    def _app(self) -> AppTest:
        app = AppTest.from_file("pages/Sponsoren_Deadline_Mails.py", default_timeout=20)
        app.session_state["sdm_sender_email"] = "sender@example.com"
        app.run()
        self.assertEqual([], [exception.message for exception in app.exception])
        return app

    def _generate(self, app: AppTest) -> None:
        next(widget for widget in app.button if widget.label == "Generieren").click().run()
        self.assertEqual([], [exception.message for exception in app.exception])

    def test_upload_and_generation_smoke(self) -> None:
        app = self._app()

        self._generate(app)

        result = app.session_state["sdm_result"]
        self.assertEqual(1, result.processed_count)
        self.assertEqual("Test Sponsor", result.mails[0].sponsor_name)
        self.assertEqual("sponsor@example.com", result.mails[0].to_email)
        self.assertEqual(1, len(app.dataframe))
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_missing_upload_requests_workbook_without_generating_or_sending(self) -> None:
        self.upload.return_value = None

        app = self._app()

        self.assertIsNone(app.session_state["sdm_result"])
        self.assertTrue(any("XLSX-Datei hochladen" in element.value for element in app.info))
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_munich_defaults_generate_current_deadlines_and_event_details(self) -> None:
        app = self._app()
        self.assertEqual("München", app.text_input(key="sdm_event_city").value)
        self.assertEqual(date(2026, 11, 17), app.date_input(key="sdm_event_start").value)
        self.assertEqual(date(2026, 11, 19), app.date_input(key="sdm_event_end").value)

        self._generate(app)

        result = app.session_state["sdm_result"]
        body = result.mails[0].html_body
        for expected in (
            "München",
            "17.11.2026",
            "19.11.2026",
            "18.08.2026",
            "31.08.2026",
            "15.10.2026",
            "29.10.2026",
            "03.11.2026",
            "10.11.2026",
            "https://calendly.com/mysecurityevent/1-1-meeting-sponsoren-mysecurityevent-munich",
            "Allianz Arena",
            "14:00",
            "16:00",
        ):
            self.assertIn(expected, body)
        for obsolete in ("26.03.2026", "20.04.2026", "27.04.2026", "09.03.2026"):
            self.assertNotIn(obsolete, body)
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_new_event_start_updates_deadlines_and_generated_mail(self) -> None:
        app = self._app()
        start = date(2027, 2, 16)
        app.date_input(key="sdm_event_start").set_value(start)
        app.date_input(key="sdm_event_end").set_value(date(2027, 2, 18))
        app.run()

        expected_dates = {
            "sdm_onboarding_start": date(2026, 11, 17),
            "sdm_onboarding_end": date(2026, 11, 30),
            "sdm_materials": date(2027, 1, 14),
            "sdm_presentation": date(2027, 1, 28),
            "sdm_participant_list": date(2027, 2, 2),
            "sdm_meeting_selection": date(2027, 2, 9),
        }
        for key, expected in expected_dates.items():
            self.assertEqual(expected, app.date_input(key=key).value)
        app.text_input(key="sdm_event_city").input("Hamburg").run()
        app.text_input(key="sdm_onboarding_url").input("https://example.com/hamburg-onboarding")
        app.text_input(key="sdm_event_venue").input("Testhalle Hamburg")
        app.time_input(key="sdm_checkin_start").set_value(time(12, 0))
        app.time_input(key="sdm_checkin_end").set_value(time(13, 30))
        app.run()

        self._generate(app)

        result = app.session_state["sdm_result"]
        self.assertEqual(start, result.event_start)
        body = result.mails[0].html_body
        for expected in (
            "Hamburg",
            "16.02.2027",
            "18.02.2027",
            "14.01.2027",
            "28.01.2027",
            "02.02.2027",
            "09.02.2027",
            "https://example.com/hamburg-onboarding",
            "Testhalle Hamburg",
            "12:00",
            "13:30",
        ):
            self.assertIn(expected, body)
        self.assertNotIn("Allianz Arena", body)
        self.assertNotIn("1-1-meeting-sponsoren-mysecurityevent-munich", body)
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_content_configuration_changes_invalidate_generated_mails(self) -> None:
        changes = (
            ("text_input", "sdm_event_city", "Hamburg"),
            ("date_input", "sdm_event_start", date(2026, 11, 18)),
            ("date_input", "sdm_event_end", date(2026, 11, 20)),
            ("date_input", "sdm_materials", date(2026, 10, 16)),
            ("text_input", "sdm_onboarding_url", "https://example.com/new-onboarding"),
            ("text_input", "sdm_event_venue", "Neuer Veranstaltungsort"),
            ("time_input", "sdm_checkin_start", time(13, 0)),
            ("time_input", "sdm_checkin_end", time(17, 0)),
            ("selectbox", "sdm_sheet_name", "Archive"),
            ("selectbox", "sdm_sender_email", "severin.wagner@mysecurityevent.de"),
        )
        for widget_type, key, value in changes:
            with self.subTest(key=key):
                app = self._app()
                self._generate(app)
                self.assertIsNotNone(app.session_state["sdm_result"])

                getattr(app, widget_type)(key=key).set_value(value).run()

                self.assertEqual([], [exception.message for exception in app.exception])
                self.assertIsNone(app.session_state["sdm_result"])
                self.assertFalse(
                    any(widget.label.startswith("Ausgewählte") for widget in app.button)
                )
                self.smtp.assert_not_called()
                self.imap.assert_not_called()

    def test_replacing_workbook_resets_generated_mail_and_frozen_summary(self) -> None:
        app = self._app()
        self._generate(app)
        self.assertEqual(["Test Sponsor"], app.dataframe[0].value["Sponsor"].tolist())
        excel_bytes = _sponsor_workbook_bytes("Replacement Sponsor")
        self.upload.return_value = SimpleNamespace(
            name="sponsor_test.xlsx", getvalue=lambda: excel_bytes
        )

        app.run()

        self.assertIsNone(app.session_state["sdm_result"])
        self._generate(app)
        self.assertEqual(["Replacement Sponsor"], app.dataframe[0].value["Sponsor"].tolist())
        self.assertEqual("Replacement Sponsor", app.session_state["sdm_result"].mails[0].sponsor_name)
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_mail_preview_is_available_without_mail_transport_configuration(self) -> None:
        self.imap_settings.side_effect = ConfigError("IMAP is not configured")
        self.smtp_settings.side_effect = ConfigError("SMTP is not configured")
        app = self._app()

        self._generate(app)

        self.assertEqual(1, len(app.session_state["sdm_result"].mails))
        self.assertFalse(any(widget.label.startswith("Ausgewählte") for widget in app.button))
        self.smtp.assert_not_called()
        self.imap.assert_not_called()

    def test_mocked_draft_run_uses_selected_mails_and_keeps_result_log(self) -> None:
        excel_bytes = _sponsor_workbook_bytes(second_sponsor_name="Second Sponsor")
        self.upload.return_value = SimpleNamespace(
            name="two_sponsors.xlsx", getvalue=lambda: excel_bytes
        )
        app = self._app()
        next(widget for widget in app.text_input if widget.label == "E-Mail-Passwort").input(
            "test-password"
        ).run()
        self._generate(app)
        original_result = app.session_state["sdm_result"]
        summary_df = app.session_state["sdm_summary_df"].copy()
        summary_df.loc[1, "Ausgewählt"] = False
        app.session_state["sdm_summary_df"] = summary_df
        app.run()
        expected_mail = original_result.mails[1]
        self.imap.return_value = [
            ImapDraftRecord(
                sponsor_name=expected_mail.sponsor_name,
                to_email=expected_mail.to_email,
                cc_email=expected_mail.cc_email,
                subject=expected_mail.subject,
                mailbox="sender@example.com",
                drafts_folder="Drafts",
                result="draft_created",
                details="",
                server_response="OK",
            )
        ]
        confirmation = next(widget for widget in app.text_input if widget.label.startswith("Bestätigung:"))
        self.assertIn("DRAFTS 1", confirmation.label)
        self.assertTrue(
            next(
                widget for widget in app.button if widget.label == "Ausgewählte Entwürfe speichern"
            ).disabled
        )
        confirmation.input("DRAFTS 1").run()

        next(
            widget for widget in app.button if widget.label == "Ausgewählte Entwürfe speichern"
        ).click().run()

        self.assertEqual([], [exception.message for exception in app.exception])
        self.imap.assert_called_once()
        mails, config = self.imap.call_args.args
        self.assertEqual([expected_mail], mails)
        self.assertEqual("sender@example.com", config.username)
        self.assertEqual("Drafts", config.drafts_folder)
        self.smtp.assert_not_called()
        run_context = app.session_state["sdm_mail_run_context"]
        self.assertEqual(1, run_context["Ausgewählte Mails"])
        self.assertEqual("Deals", run_context["Sheet"])
        self.assertEqual("München | 2026-11-17 bis 2026-11-19", run_context["Event"])
        self.assertEqual(["Second Sponsor"], app.dataframe[1].value["Sponsor"].tolist())
        self.assertEqual(["Entwurf gespeichert"], app.dataframe[1].value["Status"].tolist())

        app.run()
        self.imap.assert_called_once()
        self.assertEqual(["Second Sponsor"], app.dataframe[1].value["Sponsor"].tolist())
        app.date_input(key="sdm_materials").set_value(date(2026, 10, 16)).run()
        self.assertIsNone(app.session_state["sdm_result"])
        self.assertIsNone(app.session_state["sdm_mail_log_records"])
        self._generate(app)
        self.assertIn("16.10.2026", app.session_state["sdm_result"].mails[0].html_body)
        confirmation = next(widget for widget in app.text_input if widget.label.startswith("Bestätigung:"))
        self.assertEqual("", confirmation.value)
        self.imap.assert_called_once()

    def test_mocked_smtp_run_records_sent_copy_warning_without_retrying(self) -> None:
        app = self._app()
        next(widget for widget in app.text_input if widget.label == "E-Mail-Passwort").input(
            "test-password"
        ).run()
        self._generate(app)
        mail = app.session_state["sdm_result"].mails[0]
        app.radio(key="sdm_mail_mode").set_value("Senden").run()
        self.smtp.return_value = [
            SmtpSendRecord(
                sponsor_name=mail.sponsor_name,
                to_email=mail.to_email,
                cc_email=mail.cc_email,
                subject=mail.subject,
                mailbox="sender@example.com",
                result="sent",
                details="Sent copy could not be saved",
            )
        ]
        next(
            widget for widget in app.text_input if widget.label.startswith("Bestätigung:")
        ).input("SENDEN 1").run()

        next(widget for widget in app.button if widget.label == "Ausgewählte E-Mails senden").click().run()

        self.assertEqual([], [exception.message for exception in app.exception])
        self.smtp.assert_called_once()
        self.imap.assert_not_called()
        sent_mails, smtp_config = self.smtp.call_args.args
        self.assertEqual([mail], sent_mails)
        self.assertEqual("sender@example.com", smtp_config.username)
        self.assertEqual("INBOX.Sent", self.smtp.call_args.kwargs["sent_copy_config"].mailbox)
        self.assertEqual(["Gesendet"], app.dataframe[1].value["Status"].tolist())
        self.assertEqual(
            ["Sent copy could not be saved"], app.dataframe[1].value["Hinweis"].tolist()
        )
        self.assertTrue(any("Gesendet: 1, Hinweise: 1" in element.value for element in app.success))

        app.run()
        self.smtp.assert_called_once()
        self.assertEqual(["Gesendet"], app.dataframe[1].value["Status"].tolist())


if __name__ == "__main__":
    unittest.main()
