import unittest
from unittest.mock import patch

from serienmailing.imap_sender import SerienMail
from serienmailing.smtp_sender import send_serienmailing_messages
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


def _make_mail(**overrides) -> SerienMail:
    defaults = dict(
        to_email="recipient@example.com",
        vorname="Alice",
        firma="Acme GmbH",
        subject="Test Subject",
        html_body="<p>Hello</p>",
        attachment_bytes=None,
        attachment_filename=None,
    )
    defaults.update(overrides)
    return SerienMail(**defaults)


class SendSerienmailingMessagesTests(unittest.TestCase):
    @patch("serienmailing.smtp_sender.send_email_messages")
    def test_maps_successful_results(self, mock_send):
        mock_send.return_value = [
            SmtpSendResult(
                to_email="recipient@example.com",
                subject="Test Subject",
                status="sent",
                details="",
            )
        ]

        results = send_serienmailing_messages([_make_mail()], _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("sent", results[0].status)
        self.assertEqual("Alice", results[0].vorname)
        self.assertEqual("Acme GmbH", results[0].firma)

    @patch("serienmailing.smtp_sender.send_email_messages")
    def test_maps_error_details(self, mock_send):
        mock_send.return_value = [
            SmtpSendResult(
                to_email="recipient@example.com",
                subject="Test Subject",
                status="error",
                details="boom",
            )
        ]

        results = send_serienmailing_messages([_make_mail()], _make_config())

        self.assertEqual("error", results[0].status)
        self.assertEqual("boom", results[0].details)

    @patch("serienmailing.smtp_sender.send_email_messages")
    def test_passes_attachment_through_to_prepared_message(self, mock_send):
        mock_send.return_value = [
            SmtpSendResult(
                to_email="recipient@example.com",
                subject="Test Subject",
                status="sent",
                details="",
            )
        ]

        mail = _make_mail(
            attachment_bytes=b"%PDF-1.4",
            attachment_filename="badge.pdf",
        )
        send_serienmailing_messages([mail], _make_config())

        prepared_messages, config = mock_send.call_args[0]
        self.assertEqual("sender@example.com", config.username)
        self.assertEqual(1, len(prepared_messages))
        payload = prepared_messages[0].message.as_string()
        self.assertIn("badge.pdf", payload)

    @patch("serienmailing.smtp_sender.send_email_messages")
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
        send_serienmailing_messages(
            [_make_mail()],
            _make_config(),
            sent_copy_config=sent_copy_config,
        )

        self.assertEqual(sent_copy_config, mock_send.call_args.kwargs["sent_copy_config"])
