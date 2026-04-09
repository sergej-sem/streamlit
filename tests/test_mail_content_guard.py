import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from badgegen.badge_mail import _notification_html_body, _notification_subject
from shared.mail_content_guard import (
    assess_html_mail_content,
    assess_mail_batch,
    assess_mail_content,
    evaluate_send_guard,
)


class AssessMailContentTests(unittest.TestCase):
    def test_test_subject_and_body_are_blocked(self):
        result = assess_mail_content("Test", "Test")
        self.assertTrue(result.blocked)
        self.assertEqual("hoch", result.risk_level)
        self.assertIn("testartig", " ".join(result.reasons).lower())

    def test_business_mail_is_allowed(self):
        result = assess_mail_content(
            "Informationen zum Event - ACME GmbH",
            (
                "Hallo Frau Beispiel,\n\n"
                "ich sende Ihnen die aktuellen Informationen zum Event in Berlin. "
                "Bitte geben Sie mir kurz Bescheid, falls noch Rückfragen offen sind.\n\n"
                "Beste Grüße,"
            ),
        )
        self.assertFalse(result.blocked)
        self.assertEqual("niedrig", result.risk_level)

    def test_borderline_short_mail_warns_but_does_not_block(self):
        result = assess_mail_content("Kurze Info", "Bitte kurz melden.")
        self.assertFalse(result.blocked)
        self.assertEqual("mittel", result.risk_level)

    def test_badge_notification_content_is_not_falsely_blocked(self):
        result = assess_html_mail_content(
            _notification_subject("Eva", "Schmidt"),
            _notification_html_body("Eva", "Schmidt"),
        )
        self.assertFalse(result.blocked)

    def test_link_heavy_call_to_action_message_is_flagged(self):
        result = assess_html_mail_content(
            "Jetzt klicken",
            (
                '<p>Klicke jetzt hier:</p>'
                '<p><a href="https://bit.ly/example">Link 1</a></p>'
                '<p><a href="https://bit.ly/example2">Link 2</a></p>'
            ),
        )
        self.assertIn(result.risk_level, {"mittel", "hoch"})
        self.assertTrue(any("Link" in reason or "Call-to-Action" in reason for reason in result.reasons))


class AssessMailBatchTests(unittest.TestCase):
    def test_batch_uses_worst_item(self):
        result = assess_mail_batch(
            [
                (
                    "Informationen zum Event - ACME GmbH",
                    "Hallo Team,\n\nanbei die aktuellen Infos zum Event.\n\nBeste Grüße,",
                ),
                ("Test", "Test"),
            ]
        )
        self.assertTrue(result.blocked)
        self.assertEqual(2, result.total_count)
        self.assertEqual(1, result.blocked_count)
        self.assertEqual("hoch", result.risk_level)


class EvaluateSendGuardTests(unittest.TestCase):
    def test_send_mode_blocks_test_message(self):
        assessment = assess_mail_content("Test", "Test")
        feedback = evaluate_send_guard("Senden", assessment)
        self.assertTrue(feedback.blocked)
        self.assertEqual("error", feedback.level)
        self.assertIn("Spam-Risiko: hoch", feedback.message)

    def test_draft_mode_remains_allowed_even_for_test_content(self):
        assessment = assess_mail_content("Test", "Test")
        feedback = evaluate_send_guard("Entw\u00fcrfe", assessment)
        self.assertFalse(feedback.blocked)
        self.assertEqual("error", feedback.level)

    def test_low_risk_has_no_visible_message(self):
        assessment = assess_mail_content(
            "Informationen zum Event - ACME GmbH",
            "Hallo Team,\n\nanbei die aktuellen Informationen.\n\nBeste Grüße,",
        )
        feedback = evaluate_send_guard("Senden", assessment)
        self.assertEqual("none", feedback.level)
        self.assertEqual("", feedback.message)

    def test_medium_risk_uses_warning_message(self):
        assessment = assess_mail_content("Kurze Info", "Bitte kurz melden.")
        feedback = evaluate_send_guard("Senden", assessment)
        self.assertFalse(feedback.blocked)
        self.assertEqual("warning", feedback.level)
        self.assertEqual("Spam-Risiko: mittel", feedback.message)


if __name__ == "__main__":
    unittest.main()
