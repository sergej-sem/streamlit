import unittest
from unittest.mock import patch

from sponsor_deadline_mails.core import GeneratedMail
from sponsor_deadline_mails.smtp_sender import (
    SmtpSendRecord,
    build_smtp_send_log_dataframe,
    create_smtp_sends,
)
from shared.imap_append import ImapAppendConfig
from shared.smtp_sender import SmtpSendConfig, SmtpSendResult


def _make_config(**overrides) -> SmtpSendConfig:
    defaults = dict(
        host="smtp.example.com",
        port=465,
        username="sender@example.com",
        password="secret",
        use_ssl=True,
        use_starttls=False,
        timeout_seconds=30,
    )
    defaults.update(overrides)
    return SmtpSendConfig(**defaults)


def _make_mail(**overrides) -> GeneratedMail:
    defaults = dict(
        row_number=1,
        sponsor_name="Acme GmbH",
        language="DE",
        package="Gold",
        to_email="sponsor@example.com",
        cc_email="",
        subject="Test Betreff",
        html_body="<p>Hallo</p>",
        html_file_name="001_acme.html",
        green_count=2,
        red_count=1,
        yellow_count=0,
        white_count=0,
    )
    defaults.update(overrides)
    return GeneratedMail(**defaults)


class CreateSmtpSendsTests(unittest.TestCase):
    @patch("sponsor_deadline_mails.smtp_sender.send_email_messages")
    def test_maps_sent_results(self, mock_send):
        mock_send.return_value = [
            SmtpSendResult(
                to_email="sponsor@example.com",
                subject="Test Betreff",
                status="sent",
                details="",
            )
        ]

        results = create_smtp_sends([_make_mail()], _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("sent", results[0].result)
        self.assertEqual("Acme GmbH", results[0].sponsor_name)
        self.assertEqual("sender@example.com", results[0].mailbox)

    @patch("sponsor_deadline_mails.smtp_sender.send_email_messages")
    def test_preserves_cc_email(self, mock_send):
        mock_send.return_value = [
            SmtpSendResult(
                to_email="sponsor@example.com",
                subject="Test Betreff",
                status="sent",
                details="",
            )
        ]

        create_smtp_sends([_make_mail(cc_email="cc@example.com")], _make_config())
        prepared_messages = mock_send.call_args[0][0]
        self.assertIn("Cc: cc@example.com", prepared_messages[0].message.as_string())

    @patch("sponsor_deadline_mails.smtp_sender.send_email_messages")
    def test_passes_sent_copy_config_through(self, mock_send):
        mock_send.return_value = []

        sent_copy_config = ImapAppendConfig(
            host="imap.example.com",
            port=993,
            username="sender@example.com",
            password="secret",
            mailbox="INBOX.Sent",
            use_ssl=True,
        )
        create_smtp_sends(
            [_make_mail()],
            _make_config(),
            sent_copy_config=sent_copy_config,
        )

        self.assertEqual(sent_copy_config, mock_send.call_args.kwargs["sent_copy_config"])

    @patch("sponsor_deadline_mails.smtp_sender.send_email_messages")
    def test_passes_progress_callback_through(self, mock_send):
        mock_send.return_value = []
        progress_callback = lambda progress: None

        create_smtp_sends(
            [_make_mail()],
            _make_config(),
            progress_callback=progress_callback,
        )

        self.assertIs(progress_callback, mock_send.call_args.kwargs["progress_callback"])


class BuildSmtpSendLogDataframeTests(unittest.TestCase):
    def _make_record(self, **overrides) -> SmtpSendRecord:
        defaults = dict(
            sponsor_name="Acme GmbH",
            to_email="sponsor@example.com",
            cc_email="",
            subject="Betreff",
            mailbox="sender@example.com",
            result="sent",
            details="",
        )
        defaults.update(overrides)
        return SmtpSendRecord(**defaults)

    def test_sent_maps_to_german_label(self):
        df = build_smtp_send_log_dataframe([self._make_record(result="sent")])
        self.assertIn("Gesendet", df["Status"].values)

    def test_error_maps_to_german_label(self):
        df = build_smtp_send_log_dataframe([self._make_record(result="error")])
        self.assertIn("Fehler", df["Status"].values)

    def test_optional_columns_behave_like_draft_log(self):
        df = build_smtp_send_log_dataframe(
            [
                self._make_record(cc_email="cc@example.com", details="Hinweis"),
            ]
        )
        self.assertEqual(["Sponsor", "E-Mail", "Kopie", "Status", "Hinweis"], list(df.columns))
