from __future__ import annotations

import ast
import io
import unittest
from datetime import date
from email import message_from_bytes
from email.policy import default
from email.utils import getaddresses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openpyxl import Workbook

from shared.smtp_sender import SmtpSendConfig
from sponsor_deadline_mails.core import generate_deadline_mails
from sponsor_deadline_mails.graph import _build_payload
from sponsor_deadline_mails.imap_drafts import ImapDraftConfig, create_imap_drafts
from sponsor_deadline_mails.parser import build_sponsor_row
from sponsor_deadline_mails.recipients import (
    invalid_recipient_addresses,
    normalize_recipient_cell,
    recipient_mailboxes,
)
from sponsor_deadline_mails.smtp_sender import create_smtp_sends


def _worksheet(primary: str | None, copy: str | None):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Deals"
    worksheet.append([
        "Name", "Paket", "Deal liegt vor", "ASP 1 Vorname", "ASP 1 Nachname",
        "ASP 1 E-Mail Adresse", "ASP 2 Vorname", "ASP 2 Nachname", "ASP 2 E-Mail Adresse",
        "Onboarding", "Logo", "Sponsoren Vor Ort", "Handout", "Booklet Informationen",
        "Vortragsinformationen", "Wunschteilnehmerliste erhalten", "LED Wand Design",
        "Posting gepostet", "Präsentation erhalten", "Teilnehmerliste Gesprächswünsche erhalten",
    ])
    worksheet.append(["Test Sponsor", "Gold", "check", "Alex", "Example", primary, "Robin", "Other", copy])
    return workbook, worksheet


def _generated_mail(primary: str | None, copy: str | None):
    workbook, _ = _worksheet(primary, copy)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return generate_deadline_mails(buffer.getvalue(), today=date(2026, 10, 1)).mails[0]


def _page_address_validator():
    """Exercise the actual page guard without executing Streamlit at import."""
    page = Path(__file__).resolve().parents[1] / "pages" / "Sponsoren_Deadline_Mails.py"
    tree = ast.parse(page.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_invalid_selected_mail_addresses"
    )
    namespace = {"invalid_recipient_addresses": invalid_recipient_addresses}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(page), "exec"), namespace)
    return namespace[function.name]


class SponsorRecipientTests(unittest.TestCase):
    def test_excel_separators_preserve_all_addresses(self):
        for separator in ("\n", "\r\n", "; ", ", "):
            with self.subTest(separator=separator):
                raw = f" first@example.com{separator}second@EXAMPLE.COM "
                self.assertEqual("first@example.com, second@example.com", normalize_recipient_cell(raw))
                self.assertEqual([], invalid_recipient_addresses(raw, required=True))
                self.assertEqual(["first@example.com", "second@example.com"], recipient_mailboxes(raw))

    def test_quoted_display_names_keep_commas_and_semicolons(self):
        raw = '"Example, Alex; Team" <first@example.com>\n"Other, Robin" <second@example.com>'
        canonical = normalize_recipient_cell(raw)
        self.assertEqual(
            '"Example, Alex; Team" <first@example.com>, "Other, Robin" <second@example.com>',
            canonical,
        )
        self.assertEqual([], invalid_recipient_addresses(canonical))
        self.assertEqual(["first@example.com", "second@example.com"], recipient_mailboxes(canonical))

    def test_bad_tokens_remain_visible_and_block_mixed_lists(self):
        for bad in (
            "invalid", "bad@", "bad@example..com", "good@example.com trailing",
            "good@example.com another@example.com", '"Broken <broken@example.com>',
            "Name <good@example.com> ignored", "Bcc: injected@example.com", "name\x00@example.com",
        ):
            with self.subTest(bad=bad):
                canonical = normalize_recipient_cell(f"valid@example.com\n{bad}")
                self.assertIn(bad, canonical)
                self.assertEqual([bad], invalid_recipient_addresses(canonical))
                with self.assertRaises(ValueError):
                    recipient_mailboxes(canonical)

    def test_empty_primary_is_invalid_but_empty_copy_is_allowed(self):
        self.assertEqual([""], invalid_recipient_addresses("", required=True))
        self.assertEqual([], invalid_recipient_addresses(None))
        self.assertEqual([], recipient_mailboxes(""))
        with self.assertRaises(ValueError):
            recipient_mailboxes("", required=True)

    def test_parser_keeps_all_to_and_copy_addresses_and_primary_name(self):
        workbook, worksheet = _worksheet("first@example.com; second@example.com", "copy1@example.com\ncopy2@example.com")
        self.addCleanup(workbook.close)
        sponsor = build_sponsor_row(worksheet, 2)
        self.assertEqual("first@example.com, second@example.com", sponsor.to_email)
        self.assertEqual("copy1@example.com, copy2@example.com", sponsor.cc_email)
        self.assertEqual(("Alex", "Example"), (sponsor.contact_first_name, sponsor.contact_last_name))

    def test_fallback_keeps_all_second_contact_addresses_and_second_name(self):
        workbook, worksheet = _worksheet(None, "copy1@example.com\ncopy2@example.com")
        self.addCleanup(workbook.close)
        sponsor = build_sponsor_row(worksheet, 2)
        self.assertEqual("copy1@example.com, copy2@example.com", sponsor.to_email)
        self.assertEqual("", sponsor.cc_email)
        self.assertEqual(("Robin", "Other"), (sponsor.contact_first_name, sponsor.contact_last_name))

    def test_generated_salutation_still_uses_the_selected_contact(self):
        primary = _generated_mail("first@example.com; second@example.com", "copy@example.com")
        fallback = _generated_mail(None, "copy1@example.com\ncopy2@example.com")
        self.assertIn("Hallo Alex,", primary.html_body)
        self.assertIn("Hallo Robin,", fallback.html_body)

    def test_page_guard_checks_each_address_in_to_and_copy(self):
        validator = _page_address_validator()
        mail = SimpleNamespace(sponsor_name="Test Sponsor", to_email="first@example.com, second@example.com", cc_email="copy1@example.com, copy2@example.com")
        self.assertEqual([], validator([mail]))
        mail.to_email += ", invalid-to"
        mail.cc_email += ", invalid-copy"
        self.assertEqual(
            ["Test Sponsor: invalid-to", "Test Sponsor (Kopie): invalid-copy"],
            validator([mail]),
        )

    def test_page_guard_rejects_junk_after_valid_address(self):
        validator = _page_address_validator()
        mail = SimpleNamespace(sponsor_name="Test Sponsor", to_email="first@example.com trailing", cc_email="")
        self.assertEqual(["Test Sponsor: first@example.com trailing"], validator([mail]))


class SponsorRecipientTransportTests(unittest.TestCase):
    def setUp(self):
        self.mail = _generated_mail("first@example.com; second@example.com", "copy1@example.com\ncopy2@example.com")

    def test_graph_creates_one_recipient_per_mailbox(self):
        payload = _build_payload(self.mail)
        self.assertEqual(
            [{"emailAddress": {"address": "first@example.com"}}, {"emailAddress": {"address": "second@example.com"}}],
            payload["toRecipients"],
        )
        self.assertEqual(
            [{"emailAddress": {"address": "copy1@example.com"}}, {"emailAddress": {"address": "copy2@example.com"}}],
            payload["ccRecipients"],
        )

    def test_graph_rejects_an_invalid_second_address(self):
        mail = _generated_mail("first@example.com", "copy1@example.com\ninvalid")
        with self.assertRaises(ValueError):
            _build_payload(mail)

    @patch("shared.smtp_sender._connect")
    def test_smtp_delivers_all_to_and_copy_recipients(self, connect):
        connection = MagicMock()
        connection.send_message.return_value = {}
        connect.return_value = connection
        config = SmtpSendConfig(host="test.invalid", port=465, username="sender@example.com", password="test", delay_between_messages_seconds=0)
        records = create_smtp_sends([self.mail], config)
        self.assertEqual("sent", records[0].result)
        sent_message = connection.send_message.call_args.args[0]
        self.assertEqual(
            ["first@example.com", "second@example.com", "copy1@example.com", "copy2@example.com"],
            connection.send_message.call_args.kwargs["to_addrs"],
        )
        self.assertEqual(["copy1@example.com", "copy2@example.com"], [address for _, address in getaddresses([str(sent_message["Cc"])])])
        self.assertEqual(["first@example.com", "second@example.com"], [address for _, address in getaddresses([str(sent_message["To"])])])

    @patch("sponsor_deadline_mails.imap_drafts._connect")
    def test_imap_draft_headers_keep_all_to_and_copy_recipients(self, connect):
        connection = MagicMock()
        connection.login.return_value = ("OK", [])
        connection.select.return_value = ("OK", [])
        connection.append.return_value = ("OK", [])
        connect.return_value = connection
        records = create_imap_drafts([self.mail], ImapDraftConfig(host="test.invalid", port=993, username="sender@example.com", password="test"))
        self.assertEqual("draft_created", records[0].result)
        draft = message_from_bytes(connection.append.call_args.args[3], policy=default)
        self.assertEqual(["copy1@example.com", "copy2@example.com"], [address for _, address in getaddresses([str(draft["Cc"])])])
        self.assertEqual(["first@example.com", "second@example.com"], [address for _, address in getaddresses([str(draft["To"])])])


if __name__ == "__main__":
    unittest.main()
