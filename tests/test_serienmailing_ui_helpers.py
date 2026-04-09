import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from serienmailing.imap_sender import SerienMailResult
from serienmailing.ui_helpers import (
    MAIL_MODE_DRAFT,
    MAIL_MODE_SEND,
    apply_contacts_state,
    build_confirmation_phrase,
    default_mail_body_html_value,
    default_mail_text,
    default_subject_template,
    missing_preview_requirements,
    preview_ready,
    reset_confirmation_state,
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
    def test_default_subject_template_is_empty(self):
        self.assertEqual("", default_subject_template())

    def test_default_mail_text_contains_only_visible_closing(self):
        self.assertEqual("\n\nBeste Grüße,", default_mail_text())

    def test_default_mail_body_html_contains_visible_closing(self):
        self.assertIn("Beste Grüße,", default_mail_body_html_value())

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


class SerienmailingStateHelperTests(unittest.TestCase):
    def test_reset_confirmation_state_clears_both_fields(self):
        state = {"sm_confirm_input": "SENDEN 1", "sm_confirm_expected": "SENDEN 1"}
        reset_confirmation_state(state)
        self.assertEqual("", state["sm_confirm_input"])
        self.assertEqual("", state["sm_confirm_expected"])

    def test_apply_contacts_state_preserves_mode_subject_and_body_html(self):
        contacts = object()
        state = {
            "sm_mail_mode": MAIL_MODE_SEND,
            "sm_subject_tpl": "Eigener Betreff",
            "sm_mail_body_html": "<p>Eigener Text</p><p><br></p><p>Beste Grüße,</p>",
            "sm_mail_result": {"mode": MAIL_MODE_SEND, "results": []},
            "sm_confirm_input": "SENDEN 1",
            "sm_confirm_expected": "SENDEN 1",
        }

        apply_contacts_state(state, contacts)

        self.assertIs(contacts, state["sm_contacts"])
        self.assertEqual(MAIL_MODE_SEND, state["sm_mail_mode"])
        self.assertEqual("Eigener Betreff", state["sm_subject_tpl"])
        self.assertIn("Eigener Text", state["sm_mail_body_html"])
        self.assertIsNone(state["sm_mail_result"])
        self.assertEqual("", state["sm_confirm_input"])
        self.assertEqual("", state["sm_confirm_expected"])


class SerienmailingPreviewHelperTests(unittest.TestCase):
    def test_missing_preview_requirements_lists_missing_fields(self):
        missing = missing_preview_requirements(
            sender_email="",
            sender_password="",
            contacts=None,
            subject="",
            body_html="",
        )
        self.assertEqual(
            (
                "Absenderadresse",
                "Passwort",
                "mindestens ein Empfänger",
                "Betreff",
                "Nachrichtenbody",
            ),
            missing,
        )

    def test_preview_ready_when_all_inputs_present(self):
        contacts = pd.DataFrame([{"vorname": "Anna", "firma": "ACME", "email": "anna@example.com"}])
        self.assertTrue(
            preview_ready(
                sender_email="sender@example.com",
                sender_password="secret",
                contacts=contacts,
                subject="Betreff",
                body_html="<p><br></p><p><br></p><p>Beste Grüße,</p>",
            )
        )


if __name__ == "__main__":
    unittest.main()
