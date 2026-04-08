import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from serienmailing.imap_sender import SerienMailResult
from serienmailing.ui_helpers import (
    MAIL_MODE_DRAFT,
    MAIL_MODE_SEND,
    build_confirmation_phrase,
    default_mail_text,
    summarize_mail_results,
)


def _result(status: str, details: str = "") -> SerienMailResult:
    return SerienMailResult(
        to_email="recipient@example.com",
        vorname="Alice",
        firma="Acme GmbH",
        subject="Test",
        status=status,
        details=details,
    )


class BuildConfirmationPhraseTests(unittest.TestCase):
    def test_default_mail_text_contains_visible_closing(self):
        self.assertEqual("Beste Grüße,", default_mail_text())

    def test_draft_mode_uses_entwuerfe(self):
        self.assertEqual("ENTWÜRFE 3", build_confirmation_phrase(MAIL_MODE_DRAFT, 3))

    def test_send_mode_uses_senden(self):
        self.assertEqual("SENDEN 3", build_confirmation_phrase(MAIL_MODE_SEND, 3))


class SummarizeMailResultsTests(unittest.TestCase):
    def test_success_summary_stays_success_when_all_sent(self):
        level, message, success_label, show_hint = summarize_mail_results([_result("sent")], MAIL_MODE_SEND)
        self.assertEqual("success", level)
        self.assertIn("1 E-Mail(s) gesendet.", message)
        self.assertEqual("Gesendet", success_label)
        self.assertFalse(show_hint)

    def test_partial_failure_summary_uses_warning(self):
        level, message, _, show_hint = summarize_mail_results(
            [_result("sent"), _result("error", "SMTP refused")],
            MAIL_MODE_SEND,
        )
        self.assertEqual("warning", level)
        self.assertIn("1 Fehler.", message)
        self.assertTrue(show_hint)

    def test_all_error_summary_uses_error(self):
        level, message, success_label, show_hint = summarize_mail_results(
            [_result("error", "SMTP refused")],
            MAIL_MODE_SEND,
        )
        self.assertEqual("error", level)
        self.assertIn("0 E-Mail(s) gesendet.", message)
        self.assertEqual("Gesendet", success_label)
        self.assertTrue(show_hint)
