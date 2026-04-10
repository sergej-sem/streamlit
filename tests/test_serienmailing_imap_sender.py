import email as _email_mod
import imaplib
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import MagicMock, patch

from serienmailing.imap_sender import (
    MailConfig,
    SerienMail,
    _build_message,
    _friendly_imap_error,
    create_serienmailing_drafts,
)


def _make_config(**overrides) -> MailConfig:
    defaults = dict(
        host="mail.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        drafts_folder="Drafts",
        use_ssl=True,
    )
    defaults.update(overrides)
    return MailConfig(**defaults)


def _make_mail(**overrides) -> SerienMail:
    defaults = dict(
        to_email="recipient@example.com",
        vorname="Alice",
        firma="Acme GmbH",
        subject="Test Subject",
        html_body="<p>Hello <b>World</b></p>",
    )
    defaults.update(overrides)
    return SerienMail(**defaults)


# ── _friendly_imap_error ──────────────────────────────────────────────────────

class FriendlyImapErrorTests(unittest.TestCase):

    def test_authentication_failed(self):
        result = _friendly_imap_error("[AUTHENTICATIONFAILED] Authentication failed.")
        self.assertIn("Passwort", result)
        self.assertNotIn("AUTHENTICATIONFAILED", result)

    def test_authentication_failed_variant(self):
        result = _friendly_imap_error("authentication failed")
        self.assertIn("Passwort", result)

    def test_invalid_credentials(self):
        result = _friendly_imap_error("Invalid credentials")
        self.assertIn("Passwort", result)

    def test_nonexistent_mailbox(self):
        result = _friendly_imap_error("[NONEXISTENT] Mailbox does not exist.")
        self.assertIn("Ordner", result)

    def test_no_such_mailbox(self):
        result = _friendly_imap_error("No such mailbox")
        self.assertIn("Ordner", result)

    def test_connection_refused(self):
        result = _friendly_imap_error("Connection refused")
        self.assertIn("Mailserver", result)

    def test_timed_out(self):
        result = _friendly_imap_error("timed out")
        self.assertIn("Mailserver", result)

    def test_errno(self):
        result = _friendly_imap_error("[Errno 111] Connection refused")
        self.assertIn("Mailserver", result)

    def test_unknown_error_passthrough(self):
        raw = "Einige unbekannte Fehlermeldung"
        result = _friendly_imap_error(raw)
        self.assertIn("Entwurfsordner", result)
        self.assertIn("Technischer Hinweis:", result)

    def test_case_insensitive(self):
        result = _friendly_imap_error("TIMED OUT")
        self.assertIn("Mailserver", result)


# ── _html_to_plain_text ───────────────────────────────────────────────────────

# ── _build_message ────────────────────────────────────────────────────────────

class BuildMessageTests(unittest.TestCase):

    def _parse(self, mail: SerienMail, config: MailConfig = None):
        config = config or _make_config()
        raw = _build_message(mail, config)
        return _email_mod.message_from_bytes(raw)

    def test_subject_header(self):
        msg = self._parse(_make_mail(subject="My Subject"))
        self.assertEqual("My Subject", msg["Subject"])

    def test_from_header(self):
        config = _make_config(username="sender@example.com")
        msg = self._parse(_make_mail(), config)
        self.assertEqual("sender@example.com", msg["From"])

    def test_to_header(self):
        msg = self._parse(_make_mail(to_email="dest@example.com"))
        self.assertEqual("dest@example.com", msg["To"])

    def test_date_header_present(self):
        msg = self._parse(_make_mail())
        self.assertIsNotNone(msg["Date"])

    def test_message_id_present(self):
        msg = self._parse(_make_mail())
        self.assertIsNotNone(msg["Message-ID"])

    def test_message_id_uses_sender_domain(self):
        config = _make_config(username="sender@example.com")
        msg = self._parse(_make_mail(), config)
        self.assertTrue(msg["Message-ID"].lower().endswith("@example.com>"))

    def test_multipart_with_html_and_plain(self):
        msg = self._parse(_make_mail(html_body="<p>Hello</p>"))
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("text/html", content_types)
        self.assertIn("text/plain", content_types)

    def test_no_attachment_when_not_provided(self):
        msg = self._parse(_make_mail())
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertNotIn("application/pdf", content_types)

    def test_pdf_attachment_mime_type(self):
        mail = _make_mail(
            attachment_bytes=b"%PDF-1.4 fake content",
            attachment_filename="badge.pdf",
        )
        msg = self._parse(mail)
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("application/pdf", content_types)

    def test_png_attachment_mime_type(self):
        mail = _make_mail(
            attachment_bytes=b"\x89PNG\r\n",
            attachment_filename="image.png",
        )
        msg = self._parse(mail)
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("image/png", content_types)

    def test_xlsx_attachment_mime_type(self):
        mail = _make_mail(
            attachment_bytes=b"PKfake",
            attachment_filename="data.xlsx",
        )
        msg = self._parse(mail)
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content_types,
        )

    def test_unknown_extension_falls_back_to_octet_stream(self):
        mail = _make_mail(
            attachment_bytes=b"binary",
            attachment_filename="file.xyz",
        )
        msg = self._parse(mail)
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("application/octet-stream", content_types)

    def test_returns_bytes(self):
        raw = _build_message(_make_mail(), _make_config())
        self.assertIsInstance(raw, bytes)

    def test_non_ascii_parts_use_quoted_printable_and_ascii_attachment_name(self):
        raw = _build_message(
            _make_mail(
                subject="Test – Badge für Jörg Müller",
                html_body="<p>Hallo Jörg Müller, beste Grüße!</p>",
                attachment_bytes=b"%PDF-1.4 fake content",
                attachment_filename="badge-Jörg-Müller.pdf",
            ),
            _make_config(username="sender@example.com"),
        )
        self.assertNotIn(b"Content-Transfer-Encoding: 8bit", raw)

        parsed = BytesParser(policy=SMTP).parsebytes(raw)
        text_parts = [
            part for part in parsed.walk()
            if part.get_content_type() in {"text/plain", "text/html"}
        ]
        for part in text_parts:
            self.assertEqual("quoted-printable", part["Content-Transfer-Encoding"])
        attachment = next(parsed.iter_attachments())
        self.assertEqual("badge-Jorg-Muller.pdf", attachment.get_filename())


# ── create_serienmailing_drafts — validation ──────────────────────────────────

class CreateDraftsValidationTests(unittest.TestCase):

    def test_raises_on_empty_host(self):
        config = _make_config(host="   ")
        with self.assertRaises((ValueError, RuntimeError)):
            create_serienmailing_drafts([], config)

    def test_raises_on_empty_username(self):
        config = _make_config(username="   ")
        with self.assertRaises((ValueError, RuntimeError)):
            create_serienmailing_drafts([], config)

    def test_raises_on_empty_password(self):
        config = _make_config(password="")
        with self.assertRaises((ValueError, RuntimeError)):
            create_serienmailing_drafts([], config)

    def test_raises_on_empty_folder(self):
        config = _make_config(drafts_folder="   ")
        with self.assertRaises((ValueError, RuntimeError)):
            create_serienmailing_drafts([], config)


# ── create_serienmailing_drafts — IMAP mocked ─────────────────────────────────

class CreateDraftsMockedTests(unittest.TestCase):

    def _mock_imap(self, select_status="OK", append_status="OK"):
        mock_conn = MagicMock()
        mock_conn.login.return_value = ("OK", [b"Logged in"])
        mock_conn.select.return_value = (select_status, [b""])
        mock_conn.append.return_value = (append_status, [b""])
        return mock_conn

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_successful_draft_creation(self, mock_imap4_ssl):
        mock_conn = self._mock_imap()
        mock_imap4_ssl.return_value = mock_conn

        mails = [_make_mail()]
        results = create_serienmailing_drafts(mails, _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("draft_created", results[0].status)

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_empty_mail_list_returns_empty_results(self, mock_imap4_ssl):
        mock_conn = self._mock_imap()
        mock_imap4_ssl.return_value = mock_conn

        results = create_serienmailing_drafts([], _make_config())
        self.assertEqual([], results)

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_login_failure_raises_runtime_error(self, mock_imap4_ssl):
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error(
            b"[AUTHENTICATIONFAILED] Authentication failed."
        )
        mock_imap4_ssl.return_value = mock_conn

        with self.assertRaises(RuntimeError) as ctx:
            create_serienmailing_drafts([_make_mail()], _make_config())
        self.assertIn("Passwort", str(ctx.exception))

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_select_failure_raises_runtime_error(self, mock_imap4_ssl):
        mock_conn = self._mock_imap(select_status="NO")
        mock_imap4_ssl.return_value = mock_conn

        with self.assertRaises(RuntimeError) as ctx:
            create_serienmailing_drafts([_make_mail()], _make_config())
        self.assertIn("Ordner", str(ctx.exception))

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_append_failure_records_error_status(self, mock_imap4_ssl):
        mock_conn = self._mock_imap(append_status="NO")
        mock_imap4_ssl.return_value = mock_conn

        results = create_serienmailing_drafts([_make_mail()], _make_config())
        self.assertEqual(1, len(results))
        self.assertEqual("error", results[0].status)
        self.assertIn("Entwurf", results[0].details)

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_connection_error_raises_runtime_error(self, mock_imap4_ssl):
        mock_imap4_ssl.side_effect = OSError("Connection refused")

        with self.assertRaises(RuntimeError) as ctx:
            create_serienmailing_drafts([_make_mail()], _make_config())
        self.assertIn("Mailserver", str(ctx.exception))

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_result_carries_correct_metadata(self, mock_imap4_ssl):
        mock_imap4_ssl.return_value = self._mock_imap()

        mail = _make_mail(
            to_email="bob@example.com",
            vorname="Bob",
            firma="Firma GmbH",
            subject="Betreff",
        )
        results = create_serienmailing_drafts([mail], _make_config())
        r = results[0]
        self.assertEqual("bob@example.com", r.to_email)
        self.assertEqual("Bob", r.vorname)
        self.assertEqual("Firma GmbH", r.firma)
        self.assertEqual("Betreff", r.subject)

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_logout_called_even_on_append_error(self, mock_imap4_ssl):
        mock_conn = self._mock_imap(append_status="NO")
        mock_imap4_ssl.return_value = mock_conn

        create_serienmailing_drafts([_make_mail()], _make_config())
        mock_conn.logout.assert_called_once()

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_plain_imap_used_when_ssl_false(self, mock_imap4_ssl):
        with patch("serienmailing.imap_sender.imaplib.IMAP4") as mock_imap4:
            mock_conn = self._mock_imap()
            mock_imap4.return_value = mock_conn

            config = _make_config(use_ssl=False)
            create_serienmailing_drafts([], config)

            mock_imap4.assert_called_once()
            mock_imap4_ssl.assert_not_called()

    @patch("serienmailing.imap_sender.imaplib.IMAP4_SSL")
    def test_multiple_mails_continue_after_one_error(self, mock_imap4_ssl):
        mock_conn = MagicMock()
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [])
        # First append raises, second succeeds
        mock_conn.append.side_effect = [
            Exception("Temporary error"),
            ("OK", [b""]),
        ]
        mock_imap4_ssl.return_value = mock_conn

        mails = [_make_mail(), _make_mail(to_email="other@example.com")]
        results = create_serienmailing_drafts(mails, _make_config())

        self.assertEqual(2, len(results))
        self.assertEqual("error", results[0].status)
        self.assertEqual("draft_created", results[1].status)


if __name__ == "__main__":
    unittest.main()
