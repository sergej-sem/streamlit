import smtplib
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import MagicMock, patch

from shared.imap_append import ImapAppendConfig
from shared.mail_message import build_email_message
from shared.smtp_sender import (
    PreparedEmailMessage,
    SmtpSendConfig,
    _friendly_smtp_error,
    _next_send_delay_seconds,
    _resolve_delay_range,
    _smtp_local_hostname,
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
        delay_between_messages_seconds=0.75,
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


def _make_sent_copy_config(**overrides) -> ImapAppendConfig:
    defaults = dict(
        host="imap.example.com",
        port=993,
        username="sender@example.com",
        password="secret",
        mailbox="INBOX.Sent",
        use_ssl=True,
    )
    defaults.update(overrides)
    return ImapAppendConfig(**defaults)


class FriendlySmtpErrorTests(unittest.TestCase):
    def test_authentication_error(self):
        self.assertIn("Passwort", _friendly_smtp_error("SMTP Authentication Error"))

    def test_tls_error(self):
        self.assertIn("gesicherte Verbindung", _friendly_smtp_error("STARTTLS failed"))

    def test_connection_error(self):
        self.assertIn("SMTP-Server", _friendly_smtp_error("Connection refused"))

    def test_refused_error(self):
        self.assertIn("Empfänger", _friendly_smtp_error("Recipient refused"))


class SmtpLocalHostnameTests(unittest.TestCase):
    @patch("shared.smtp_sender.socket.gethostname", return_value="Admin-PC")
    def test_keeps_short_valid_hostname(self, mock_hostname):
        self.assertEqual("Admin-PC", _smtp_local_hostname())

    @patch("shared.smtp_sender.socket.gethostname", return_value="Admin-PC.fritz.box")
    def test_shortens_fqdn_hostname(self, mock_hostname):
        self.assertEqual("Admin-PC", _smtp_local_hostname())

    @patch("shared.smtp_sender.socket.gethostname", return_value="@@@")
    def test_returns_none_for_invalid_hostname(self, mock_hostname):
        self.assertIsNone(_smtp_local_hostname())


class DelayResolutionTests(unittest.TestCase):
    def test_default_delay_uses_randomized_range(self):
        self.assertEqual((3.0, 6.0), _resolve_delay_range(_make_config()))

    def test_legacy_single_delay_value_remains_supported(self):
        self.assertEqual(
            (0.75, 0.75),
            _resolve_delay_range(
                _make_config(
                    delay_between_messages_seconds=0.75,
                    delay_between_messages_seconds_min=None,
                    delay_between_messages_seconds_max=None,
                )
            ),
        )

    def test_min_max_delay_range_is_used_when_present(self):
        self.assertEqual(
            (3.0, 6.0),
            _resolve_delay_range(
                _make_config(
                    delay_between_messages_seconds_min=3.0,
                    delay_between_messages_seconds_max=6.0,
                )
            ),
        )

    def test_delay_range_is_sorted_when_values_are_swapped(self):
        self.assertEqual(
            (3.0, 6.0),
            _resolve_delay_range(
                _make_config(
                    delay_between_messages_seconds_min=6.0,
                    delay_between_messages_seconds_max=3.0,
                )
            ),
        )

    def test_non_positive_delay_disables_sleep(self):
        self.assertIsNone(
            _resolve_delay_range(
                _make_config(
                    delay_between_messages_seconds=0,
                    delay_between_messages_seconds_min=0,
                    delay_between_messages_seconds_max=0,
                )
            )
        )

    @patch("shared.smtp_sender.random.uniform", return_value=4.25)
    def test_next_send_delay_uses_random_uniform_for_ranges(self, mock_uniform):
        delay_seconds = _next_send_delay_seconds(
            _make_config(
                delay_between_messages_seconds_min=3.0,
                delay_between_messages_seconds_max=6.0,
            )
        )

        self.assertEqual(4.25, delay_seconds)
        mock_uniform.assert_called_once_with(3.0, 6.0)


class BuildEmailMessageTests(unittest.TestCase):
    def test_message_id_uses_sender_domain(self):
        message = build_email_message(
            from_email="sender@mysecurityevent.de",
            to_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        self.assertTrue(message["Message-ID"].lower().endswith("@mysecurityevent.de>"))

    def test_headers_are_normalized(self):
        message = build_email_message(
            from_email=" Sender Name <sender@mysecurityevent.de> ",
            to_email=" recipient@example.com, Copy Two <second@example.com> ",
            cc_email="  copy@example.com  ",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        self.assertEqual("Sender Name <sender@mysecurityevent.de>", message["From"])
        self.assertEqual("recipient@example.com, Copy Two <second@example.com>", message["To"])
        self.assertEqual("copy@example.com", message["Cc"])

    def test_attachment_message_keeps_standard_mime_structure(self):
        message = build_email_message(
            from_email="sender@mysecurityevent.de",
            to_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            attachment_bytes=b"%PDF-1.4",
            attachment_filename="badge.pdf",
        )
        self.assertEqual("multipart/mixed", message.get_content_type())
        payload = message.get_payload()
        self.assertEqual("multipart/alternative", payload[0].get_content_type())
        nested_types = [part.get_content_type() for part in payload[0].walk()]
        self.assertIn("text/plain", nested_types)
        self.assertIn("text/html", nested_types)

    def test_non_ascii_text_parts_use_quoted_printable(self):
        message = build_email_message(
            from_email="sender@mysecurityevent.de",
            to_email="recipient@example.com",
            subject="Test – Badge für Jörg Müller",
            html_body="<p>Hallo Jörg Müller, beste Grüße!</p>",
        )
        raw = message.as_bytes(policy=SMTP)
        self.assertNotIn(b"Content-Transfer-Encoding: 8bit", raw)

        parsed = BytesParser(policy=SMTP).parsebytes(raw)
        text_parts = [
            part for part in parsed.walk()
            if part.get_content_type() in {"text/plain", "text/html"}
        ]
        self.assertEqual(2, len(text_parts))
        for part in text_parts:
            self.assertEqual("quoted-printable", part["Content-Transfer-Encoding"])

    def test_non_ascii_subject_is_rfc2047_encoded_in_raw_message(self):
        message = build_email_message(
            from_email="sender@mysecurityevent.de",
            to_email="recipient@example.com",
            subject="Test – Badge für Jörg Müller",
            html_body="<p>Hello</p>",
        )
        raw = message.as_bytes(policy=SMTP)
        self.assertIn(b"Subject: Test ", raw)
        self.assertIn(b"=?utf-8?", raw)

    def test_non_ascii_attachment_filename_is_ascii_sanitized(self):
        message = build_email_message(
            from_email="sender@mysecurityevent.de",
            to_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            attachment_bytes=b"%PDF-1.4",
            attachment_filename="badge-Jörg-Müller.pdf",
        )
        raw = message.as_bytes(policy=SMTP)
        self.assertNotIn(b"filename*=", raw)

        parsed = BytesParser(policy=SMTP).parsebytes(raw)
        attachment = next(parsed.iter_attachments())
        self.assertEqual("badge-Jorg-Muller.pdf", attachment.get_filename())


class SendEmailMessagesTests(unittest.TestCase):
    @patch("shared.smtp_sender.socket.gethostname", return_value="Admin-PC.fritz.box")
    @patch("shared.smtp_sender.append_message_to_mailbox")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_successful_ssl_send(self, mock_smtp_ssl, mock_append, mock_hostname):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        results = send_email_messages([_make_prepared()], _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("sent", results[0].status)
        mock_smtp_ssl.assert_called_once_with(
            "smtp.example.com",
            465,
            timeout=30,
            local_hostname="Admin-PC",
        )
        connection.ehlo.assert_called_once_with("Admin-PC")
        connection.login.assert_called_once_with("sender@example.com", "secret")
        connection.send_message.assert_called_once()
        self.assertEqual("sender@example.com", connection.send_message.call_args.kwargs["from_addr"])
        self.assertEqual(["recipient@example.com"], connection.send_message.call_args.kwargs["to_addrs"])
        mock_append.assert_not_called()

    @patch("shared.smtp_sender.append_message_to_mailbox")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_successful_send_with_sent_copy(self, mock_smtp_ssl, mock_append):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        results = send_email_messages(
            [_make_prepared()],
            _make_config(),
            sent_copy_config=_make_sent_copy_config(),
        )

        self.assertEqual("sent", results[0].status)
        self.assertEqual("", results[0].details)
        mock_append.assert_called_once()

    @patch("shared.smtp_sender.append_message_to_mailbox")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_sent_copy_failure_keeps_sent_status_with_warning(self, mock_smtp_ssl, mock_append):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection
        mock_append.side_effect = RuntimeError("Sent-Kopie konnte nicht gespeichert werden: Gesendet-Ordner nicht gefunden.")

        results = send_email_messages(
            [_make_prepared()],
            _make_config(),
            sent_copy_config=_make_sent_copy_config(),
        )

        self.assertEqual("sent", results[0].status)
        self.assertIn("Sent-Kopie", results[0].details)

    @patch("shared.smtp_sender.socket.gethostname", return_value="Admin-PC.fritz.box")
    @patch("shared.smtp_sender.smtplib.SMTP")
    def test_starttls_path(self, mock_smtp, mock_hostname):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp.return_value = connection

        results = send_email_messages(
            [_make_prepared()],
            _make_config(use_ssl=False, use_starttls=True, port=587),
        )

        self.assertEqual("sent", results[0].status)
        mock_smtp.assert_called_once_with(
            "smtp.example.com",
            587,
            timeout=30,
            local_hostname="Admin-PC",
        )
        connection.starttls.assert_called_once()
        self.assertGreaterEqual(connection.ehlo.call_count, 2)
        connection.ehlo.assert_any_call("Admin-PC")

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
        self.assertIn("Empfänger", results[0].details)

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_cc_recipients_are_included_in_envelope(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection
        prepared = PreparedEmailMessage(
            to_email="recipient@example.com",
            subject="Test Subject",
            message=build_email_message(
                from_email="sender@example.com",
                to_email="recipient@example.com",
                cc_email="copy@example.com",
                subject="Test Subject",
                html_body="<p>Hello</p>",
            ),
        )

        send_email_messages([prepared], _make_config())

        self.assertEqual(
            ["recipient@example.com", "copy@example.com"],
            connection.send_message.call_args.kwargs["to_addrs"],
        )

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_bcc_is_used_for_envelope_but_not_leaked_in_message_headers(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection
        prepared = _make_prepared()
        prepared.message["Bcc"] = "hidden@example.com"

        send_email_messages([prepared], _make_config())

        sent_message = connection.send_message.call_args.args[0]
        self.assertIsNone(sent_message["Bcc"])
        self.assertEqual(
            ["recipient@example.com", "hidden@example.com"],
            connection.send_message.call_args.kwargs["to_addrs"],
        )

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_mismatched_header_from_is_rejected(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection
        prepared = PreparedEmailMessage(
            to_email="recipient@example.com",
            subject="Test Subject",
            message=build_email_message(
                from_email="other@example.com",
                to_email="recipient@example.com",
                subject="Test Subject",
                html_body="<p>Hello</p>",
            ),
        )

        results = send_email_messages([prepared], _make_config())

        self.assertEqual("error", results[0].status)
        self.assertIn("sichtbare Absender", results[0].details)
        connection.send_message.assert_not_called()

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    @patch("shared.smtp_sender.append_message_to_mailbox")
    def test_multiple_messages_continue_after_one_error(self, mock_append, mock_smtp_ssl):
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
            sent_copy_config=_make_sent_copy_config(),
        )

        self.assertEqual(["error", "sent"], [item.status for item in results])
        mock_append.assert_called_once()

    @patch("shared.smtp_sender.append_message_to_mailbox")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_sent_copy_not_attempted_when_smtp_send_fails(self, mock_smtp_ssl, mock_append):
        connection = MagicMock()
        connection.send_message.side_effect = smtplib.SMTPRecipientsRefused({"recipient@example.com": (550, b"no")})
        mock_smtp_ssl.return_value = connection

        results = send_email_messages(
            [_make_prepared()],
            _make_config(),
            sent_copy_config=_make_sent_copy_config(),
        )

        self.assertEqual("error", results[0].status)
        mock_append.assert_not_called()

    @patch("shared.smtp_sender.append_message_to_mailbox")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_sent_copy_receives_same_message_with_attachment_and_cc(self, mock_smtp_ssl, mock_append):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection
        prepared = PreparedEmailMessage(
            to_email="recipient@example.com",
            subject="Test Subject",
            message=build_email_message(
                from_email="sender@example.com",
                to_email="recipient@example.com",
                cc_email="copy@example.com",
                subject="Test Subject",
                html_body="<p>Hello</p>",
                attachment_bytes=b"%PDF-1.4",
                attachment_filename="badge.pdf",
            ),
        )

        send_email_messages(
            [prepared],
            _make_config(),
            sent_copy_config=_make_sent_copy_config(),
        )

        archived_message = mock_append.call_args[0][0]
        raw = archived_message.as_string()
        self.assertIn("Cc: copy@example.com", raw)
        self.assertIn("badge.pdf", raw)

    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_multiple_messages_keep_send_order(self, mock_smtp_ssl):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        first = _make_prepared(to_email="first@example.com", subject="First")
        second = _make_prepared(to_email="second@example.com", subject="Second")

        results = send_email_messages([first, second], _make_config())

        self.assertEqual(["first@example.com", "second@example.com"], [item.to_email for item in results])
        self.assertEqual(2, connection.send_message.call_count)
        self.assertEqual("First", connection.send_message.call_args_list[0].args[0]["Subject"])
        self.assertEqual("Second", connection.send_message.call_args_list[1].args[0]["Subject"])

    @patch("shared.smtp_sender.random.uniform", return_value=4.25)
    @patch("shared.smtp_sender.time.sleep")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_multiple_messages_apply_delay_between_sends(self, mock_smtp_ssl, mock_sleep, mock_uniform):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        send_email_messages(
            [
                _make_prepared(to_email="first@example.com", subject="First"),
                _make_prepared(to_email="second@example.com", subject="Second"),
            ],
            _make_config(
                delay_between_messages_seconds_min=3.0,
                delay_between_messages_seconds_max=6.0,
            ),
        )

        mock_uniform.assert_called_once_with(3.0, 6.0)
        mock_sleep.assert_called_once_with(4.25)

    @patch("shared.smtp_sender.time.sleep")
    @patch("shared.smtp_sender.smtplib.SMTP_SSL")
    def test_single_message_does_not_sleep(self, mock_smtp_ssl, mock_sleep):
        connection = MagicMock()
        connection.send_message.return_value = {}
        mock_smtp_ssl.return_value = connection

        send_email_messages([_make_prepared()], _make_config(delay_between_messages_seconds=0.5))

        mock_sleep.assert_not_called()

    def test_invalid_ssl_starttls_combo_raises_value_error(self):
        with self.assertRaises(ValueError):
            send_email_messages(
                [_make_prepared()],
                _make_config(use_ssl=True, use_starttls=True),
            )
