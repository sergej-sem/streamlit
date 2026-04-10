import email as _email_mod
import imaplib
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import MagicMock, patch

from sponsor_deadline_mails.core import GeneratedMail
from sponsor_deadline_mails.imap_drafts import (
    ImapDraftConfig,
    ImapDraftRecord,
    _build_message,
    build_imap_draft_log_dataframe,
    create_imap_drafts,
)
from serienmailing.mail_builder import html_to_plain_text as _html_to_plain_text


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_config(**overrides) -> ImapDraftConfig:
    defaults = dict(
        host="mail.example.com",
        port=993,
        username="sender@example.com",
        password="secret",
        drafts_folder="Drafts",
        use_ssl=True,
    )
    defaults.update(overrides)
    return ImapDraftConfig(**defaults)


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


def _make_record(**overrides) -> ImapDraftRecord:
    defaults = dict(
        sponsor_name="Acme GmbH",
        to_email="sponsor@example.com",
        cc_email="",
        subject="Betreff",
        mailbox="sender@example.com",
        drafts_folder="Drafts",
        result="draft_created",
        details="",
        server_response="",
    )
    defaults.update(overrides)
    return ImapDraftRecord(**defaults)


def _parse_message(mail: GeneratedMail, config: ImapDraftConfig = None):
    config = config or _make_config()
    raw = _build_message(mail, config)
    return _email_mod.message_from_bytes(raw)


# ── _html_to_plain_text — Regression (Bug-Fix-Tests) ─────────────────────────

class HtmlToPlainTextTests(unittest.TestCase):
    """Regression tests confirming the fixed regexes work correctly."""

    def test_br_self_closing_with_space_converted_to_newline(self):
        result = _html_to_plain_text("Line1<br />Line2")
        self.assertIn("\n", result)
        self.assertIn("Line1", result)
        self.assertIn("Line2", result)

    def test_br_self_closing_no_space_converted_to_newline(self):
        result = _html_to_plain_text("A<br/>B")
        self.assertIn("\n", result)

    def test_br_without_slash_converted_to_newline(self):
        result = _html_to_plain_text("A<br>B")
        self.assertIn("\n", result)

    def test_script_tag_removed(self):
        result = _html_to_plain_text("<script>alert('xss')</script>VisibleText")
        self.assertNotIn("alert", result)
        self.assertIn("VisibleText", result)

    def test_style_tag_removed(self):
        result = _html_to_plain_text("<style>.foo { color: red; }</style>VisibleText")
        self.assertNotIn("color", result)
        self.assertIn("VisibleText", result)

    def test_html_entities_unescaped(self):
        result = _html_to_plain_text("&lt;hello&gt; &amp; world")
        self.assertIn("<hello>", result)
        self.assertIn("& world", result)

    def test_excessive_newlines_collapsed(self):
        result = _html_to_plain_text("<p>A</p>\n\n\n\n<p>B</p>")
        self.assertNotIn("\n\n\n", result)

    def test_anchor_with_label_keeps_target_in_parentheses(self):
        result = _html_to_plain_text('<p><a href="https://mysecurityevent.de">Zum Event</a></p>')
        self.assertIn("Zum Event (https://mysecurityevent.de)", result)

    def test_mailto_anchor_with_same_visible_text_is_not_duplicated(self):
        result = _html_to_plain_text('<p><a href="mailto:info@mysecurityevent.de">info@mysecurityevent.de</a></p>')
        self.assertIn("info@mysecurityevent.de", result)
        self.assertNotIn("mailto:", result)

    def test_empty_input_returns_fallback(self):
        result = _html_to_plain_text("")
        self.assertTrue(len(result) > 0)


# ── _build_message ────────────────────────────────────────────────────────────

class BuildMessageTests(unittest.TestCase):

    def test_returns_bytes(self):
        raw = _build_message(_make_mail(), _make_config())
        self.assertIsInstance(raw, bytes)

    def test_subject_header(self):
        msg = _parse_message(_make_mail(subject="Mein Betreff"))
        self.assertEqual("Mein Betreff", msg["Subject"])

    def test_from_header(self):
        config = _make_config(username="absender@example.com")
        msg = _parse_message(_make_mail(), config)
        self.assertEqual("absender@example.com", msg["From"])

    def test_to_header(self):
        msg = _parse_message(_make_mail(to_email="empfaenger@example.com"))
        self.assertEqual("empfaenger@example.com", msg["To"])

    def test_cc_header_present_when_cc_email_set(self):
        msg = _parse_message(_make_mail(cc_email="kopie@example.com"))
        self.assertEqual("kopie@example.com", msg["Cc"])

    def test_cc_header_absent_when_cc_email_empty(self):
        msg = _parse_message(_make_mail(cc_email=""))
        self.assertIsNone(msg["Cc"])

    def test_date_header_present(self):
        msg = _parse_message(_make_mail())
        self.assertIsNotNone(msg["Date"])

    def test_message_id_present(self):
        msg = _parse_message(_make_mail())
        self.assertIsNotNone(msg["Message-ID"])

    def test_message_id_uses_sender_domain(self):
        config = _make_config(username="absender@example.com")
        msg = _parse_message(_make_mail(), config)
        self.assertTrue(msg["Message-ID"].lower().endswith("@example.com>"))

    def test_multipart_contains_html_and_plain(self):
        msg = _parse_message(_make_mail(html_body="<p>Text</p>"))
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("text/html", content_types)
        self.assertIn("text/plain", content_types)

    def test_no_attachment_in_message(self):
        # imap_drafts mails have no file attachments
        msg = _parse_message(_make_mail())
        content_types = [part.get_content_type() for part in msg.walk()]
        self.assertNotIn("application/pdf", content_types)

    def test_non_ascii_text_parts_use_quoted_printable(self):
        raw = _build_message(
            _make_mail(
                subject="Wichtige Informationen – Frist für Müller",
                html_body="<p>Hallo Jörg Müller, beste Grüße!</p>",
            ),
            _make_config(username="absender@example.com"),
        )
        self.assertNotIn(b"Content-Transfer-Encoding: 8bit", raw)

        parsed = BytesParser(policy=SMTP).parsebytes(raw)
        text_parts = [
            part for part in parsed.walk()
            if part.get_content_type() in {"text/plain", "text/html"}
        ]
        for part in text_parts:
            self.assertEqual("quoted-printable", part["Content-Transfer-Encoding"])


# ── create_imap_drafts — validation ──────────────────────────────────────────

class CreateImapDraftsValidationTests(unittest.TestCase):

    def test_raises_on_empty_host(self):
        with self.assertRaises(ValueError):
            create_imap_drafts([], _make_config(host="   "))

    def test_raises_on_empty_username(self):
        with self.assertRaises(ValueError):
            create_imap_drafts([], _make_config(username="   "))

    def test_raises_on_empty_password(self):
        with self.assertRaises(ValueError):
            create_imap_drafts([], _make_config(password=""))

    def test_raises_on_empty_folder(self):
        with self.assertRaises(ValueError):
            create_imap_drafts([], _make_config(drafts_folder="   "))


# ── create_imap_drafts — IMAP mocked ─────────────────────────────────────────

class CreateImapDraftsMockedTests(unittest.TestCase):

    def _mock_conn(self, login_status="OK", select_status="OK", append_status="OK"):
        conn = MagicMock()
        conn.login.return_value = (login_status, [b"OK"])
        conn.select.return_value = (select_status, [b"1"])
        conn.append.return_value = (append_status, [b"[APPENDUID 1 2]"])
        return conn

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_successful_draft_creates_draft_created_record(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn()
        results = create_imap_drafts([_make_mail()], _make_config())
        self.assertEqual(1, len(results))
        self.assertEqual("draft_created", results[0].result)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_empty_mail_list_returns_empty_list(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn()
        results = create_imap_drafts([], _make_config())
        self.assertEqual([], results)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_login_returns_non_ok_raises_runtime_error(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn(login_status="NO")
        with self.assertRaises(RuntimeError) as ctx:
            create_imap_drafts([_make_mail()], _make_config())
        self.assertIn("Anmeldung", str(ctx.exception))

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_select_returns_non_ok_raises_runtime_error(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn(select_status="NO")
        with self.assertRaises(RuntimeError) as ctx:
            create_imap_drafts([_make_mail()], _make_config())
        self.assertIn("Ordner", str(ctx.exception))

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_append_non_ok_records_error_status(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn(append_status="NO")
        results = create_imap_drafts([_make_mail()], _make_config())
        self.assertEqual(1, len(results))
        self.assertEqual("error", results[0].result)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_connection_error_propagates(self, mock_ssl):
        mock_ssl.side_effect = OSError("Connection refused")
        with self.assertRaises(OSError):
            create_imap_drafts([_make_mail()], _make_config())

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_logout_called_even_after_append_error(self, mock_ssl):
        conn = self._mock_conn(append_status="NO")
        mock_ssl.return_value = conn
        create_imap_drafts([_make_mail()], _make_config())
        conn.logout.assert_called_once()

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4")
    def test_plain_imap_used_when_ssl_false(self, mock_imap, ):
        conn = self._mock_conn()
        mock_imap.return_value = conn
        create_imap_drafts([], _make_config(use_ssl=False))
        mock_imap.assert_called_once()

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_record_carries_correct_metadata(self, mock_ssl):
        mock_ssl.return_value = self._mock_conn()
        mail = _make_mail(
            sponsor_name="Beta AG",
            to_email="beta@example.com",
            cc_email="cc@example.com",
            subject="Betreff Beta",
        )
        config = _make_config(username="absender@example.com", drafts_folder="Entwürfe")
        results = create_imap_drafts([mail], config)
        r = results[0]
        self.assertEqual("Beta AG", r.sponsor_name)
        self.assertEqual("beta@example.com", r.to_email)
        self.assertEqual("cc@example.com", r.cc_email)
        self.assertEqual("Betreff Beta", r.subject)
        self.assertEqual("absender@example.com", r.mailbox)
        self.assertEqual("Entwürfe", r.drafts_folder)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_multiple_mails_continue_after_one_error(self, mock_ssl):
        conn = MagicMock()
        conn.login.return_value = ("OK", [])
        conn.select.return_value = ("OK", [])
        conn.append.side_effect = [
            Exception("Temporary failure"),
            ("OK", [b"[APPENDUID 1 3]"]),
        ]
        mock_ssl.return_value = conn
        results = create_imap_drafts(
            [_make_mail(), _make_mail(to_email="second@example.com")],
            _make_config(),
        )
        self.assertEqual(2, len(results))
        self.assertEqual("error", results[0].result)
        self.assertEqual("draft_created", results[1].result)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_server_response_decoded_on_success(self, mock_ssl):
        conn = self._mock_conn()
        conn.append.return_value = ("OK", [b"[APPENDUID 100 200]"])
        mock_ssl.return_value = conn
        results = create_imap_drafts([_make_mail()], _make_config())
        self.assertIn("APPENDUID", results[0].server_response)

    @patch("sponsor_deadline_mails.imap_drafts.imaplib.IMAP4_SSL")
    def test_error_record_has_empty_server_response(self, mock_ssl):
        conn = self._mock_conn(append_status="NO")
        mock_ssl.return_value = conn
        results = create_imap_drafts([_make_mail()], _make_config())
        self.assertEqual("", results[0].server_response)


# ── build_imap_draft_log_dataframe ────────────────────────────────────────────

class BuildImapDraftLogDataframeTests(unittest.TestCase):

    def test_empty_records_returns_empty_dataframe(self):
        df = build_imap_draft_log_dataframe([])
        self.assertEqual(0, len(df))

    def test_draft_created_maps_to_german_label(self):
        records = [_make_record(result="draft_created")]
        df = build_imap_draft_log_dataframe(records)
        self.assertIn("Entwurf gespeichert", df["Status"].values)

    def test_error_maps_to_german_label(self):
        records = [_make_record(result="error")]
        df = build_imap_draft_log_dataframe(records)
        self.assertIn("Fehler", df["Status"].values)

    def test_unknown_result_value_passes_through(self):
        records = [_make_record(result="unknown_status")]
        df = build_imap_draft_log_dataframe(records)
        self.assertIn("unknown_status", df["Status"].values)

    def test_kopie_column_absent_when_all_cc_empty(self):
        records = [_make_record(cc_email=""), _make_record(cc_email="")]
        df = build_imap_draft_log_dataframe(records)
        self.assertNotIn("Kopie", df.columns)

    def test_kopie_column_present_when_any_cc_set(self):
        records = [_make_record(cc_email=""), _make_record(cc_email="cc@example.com")]
        df = build_imap_draft_log_dataframe(records)
        self.assertIn("Kopie", df.columns)

    def test_kopie_shows_dash_for_empty_cc(self):
        records = [_make_record(cc_email=""), _make_record(cc_email="cc@example.com")]
        df = build_imap_draft_log_dataframe(records)
        self.assertEqual("-", df["Kopie"].iloc[0])

    def test_hinweis_column_absent_when_no_details(self):
        records = [_make_record(details=""), _make_record(details="")]
        df = build_imap_draft_log_dataframe(records)
        self.assertNotIn("Hinweis", df.columns)

    def test_hinweis_column_present_when_any_details(self):
        records = [_make_record(details=""), _make_record(details="Fehler XY")]
        df = build_imap_draft_log_dataframe(records)
        self.assertIn("Hinweis", df.columns)

    def test_hinweis_shows_dash_for_empty_details(self):
        records = [_make_record(details=""), _make_record(details="Fehler XY")]
        df = build_imap_draft_log_dataframe(records)
        self.assertEqual("-", df["Hinweis"].iloc[0])

    def test_base_columns_always_present(self):
        records = [_make_record()]
        df = build_imap_draft_log_dataframe(records)
        for col in ["Sponsor", "E-Mail", "Status"]:
            self.assertIn(col, df.columns)

    def test_column_order_without_optional_columns(self):
        records = [_make_record(cc_email="", details="")]
        df = build_imap_draft_log_dataframe(records)
        self.assertEqual(["Sponsor", "E-Mail", "Status"], list(df.columns))

    def test_column_order_with_kopie_and_hinweis(self):
        records = [_make_record(cc_email="cc@example.com", details="Hinweis hier")]
        df = build_imap_draft_log_dataframe(records)
        self.assertEqual(["Sponsor", "E-Mail", "Kopie", "Status", "Hinweis"], list(df.columns))

    def test_sponsor_and_email_values_correct(self):
        records = [_make_record(sponsor_name="Firma X", to_email="x@example.com")]
        df = build_imap_draft_log_dataframe(records)
        self.assertEqual("Firma X", df["Sponsor"].iloc[0])
        self.assertEqual("x@example.com", df["E-Mail"].iloc[0])

    def test_whitespace_only_details_treated_as_empty(self):
        # details with only whitespace → show_hint should be False
        records = [_make_record(details="   ")]
        df = build_imap_draft_log_dataframe(records)
        self.assertNotIn("Hinweis", df.columns)


if __name__ == "__main__":
    unittest.main()
