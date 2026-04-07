import smtplib
import unittest
from unittest.mock import MagicMock, patch

from shared.mail_message import build_email_message
from shared.smtp_sender import (
    PreparedEmailMessage,
    SmtpSendConfig,
    _friendly_smtp_error,
    send_email_messages,
)


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


def _make_prepared(**overrides) -> PreparedEmailMessage:
    to_email = overrides.pop("to_email", "recipient@example.com")
    subject = overrides.pop("subject", "Test Subject")
    message = build_email_message(
        from_email="sender@example.com",
        to_email=to_email,
        subject=subject,
        html_body="<p>Hello</p>",
    )
    return PreparedEmailMessage(to_email=to_email, subject=subject, message=message)


class FriendlySmtpErrorTests(unittest.TestCase):
    def test_authentication_error(self):
        self.assertIn("Passwort", _friendly_smtp_error("SMTP Authentication Error"))

    def test_tls_error(self):
        self.assertIn("gesicherte Verbindung", _friendly_smtp_error("STARTTLS failed"))

    def test_connection_error(self):
        self.assertIn("SMTP-Server", _friendly_smtp_error("Connection refused"))

    def test_refused_error(self):
        self.assertIn("Empfaenger", _friendly_smtp_error("Recipient refused"))


class SendEmailMessagesTests(unittest.TestCase):
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_successful_ssl_send(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        results = send_email_messages([_make_prepared()], _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("sent", results[0].status)
        connection.login.assert_called_once_with("sender@example.com", "secret")
        connection.send_message.assert_called_once()

    @patch("shared.smtp_sender.smtplib.SMTP")
    def test_starttls_path(self, mock_smtp):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp.return_value = connection

        results = send_email_messages(
            [_make_prepared()],
            _make_config(use_ssl=False, use_starttls=True, port=587),
        )

        self.assertEqual("sent", results[0].status)
        connection.starttls.assert_called_once()
        self.assertGreaterEqual(connection.ehlo.call_count, 2)

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_login_failure_raises_runtime_error(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
        mock_smtp_ssl.return_value = connection

        with self.assertRaises(RuntimeError) as ctx:
            send_email_messages([_make_prepared()], _make_config())

        self.assertIn("Passwort", str(ctx.exception))

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_connection_error_raises_runtime_error(self, mock_smtp_ssl):
        mock_smtp_ssl.side_effect = OSError("Connection refused")

        with self.assertRaises(RuntimeError) as ctx:
            send_email_messages([_make_prepared()], _make_config())

        self.assertIn("SMTP-Server", str(ctx.exception))

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_refused_recipient_records_error(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {"recipient@example.com": (550, b"rejected")}
        mock_smtp_ssl.return_value = connection

        results = send_email_messages([_make_prepared()], _make_config())

        self.assertEqual("error", results[0].status)
        self.assertIn("Empfaenger", results[0].details)

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_multiple_messages_continue_after_one_error(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.side_effect = [
            smtplib.SMTPRecipientsRefused({"first@example.com": (550, b"no")}),
            {},
        ]
        mock_smtp_ssl.return_value = connection

        results = send_email_messages(
            [
                _make_prepared(to_email="first@example.com", subject="First"),
                _make_prepared(to_email="second@example.com", subject="Second"),
            ],
            _make_config(),
        )

        self.assertEqual(["error", "sent"], [item.status for item in results])

    def test_invalid_ssl_starttls_combo_raises_value_error(self):
        with self.assertRaises(ValueError):
            send_email_messages(
                [_make_prepared()],
                _make_config(use_ssl=True, use_starttls=True),
            )
