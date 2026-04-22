import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_preview import missing_preview_requirements, preview_ready


class MailPreviewRequirementTests(unittest.TestCase):
    def test_series_preview_lists_missing_fields_with_umlauts(self):
        missing = missing_preview_requirements(
            sender_email="",
            sender_password="",
            require_password=True,
            has_recipients=False,
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

    def test_badge_preview_does_not_require_password(self):
        missing = missing_preview_requirements(
            sender_email="sender@example.com",
            has_recipients=True,
            subject="Betreff",
            body_html="<p><br></p><p><br></p><p>Beste Grüße,</p>",
            require_password=False,
        )
        self.assertEqual(tuple(), missing)

    def test_preview_requires_valid_sender_address(self):
        missing = missing_preview_requirements(
            sender_email="bad@@example.com",
            has_recipients=True,
            subject="Betreff",
            body_html="<p><br></p><p><br></p><p>Beste Grüße,</p>",
            require_password=False,
        )
        self.assertEqual(("gültige Absenderadresse",), missing)

    def test_preview_ready_returns_true_when_all_required_inputs_exist(self):
        self.assertTrue(
            preview_ready(
                sender_email="sender@example.com",
                sender_password="secret",
                require_password=True,
                has_recipients=True,
                subject="Betreff",
                body_html="<p><br></p><p><br></p><p>Beste Grüße,</p>",
            )
        )


if __name__ == "__main__":
    unittest.main()
