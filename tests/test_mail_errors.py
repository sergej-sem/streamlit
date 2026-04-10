import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_errors import (
    compact_technical_detail,
    friendly_config_issue,
    friendly_imap_append_error,
    friendly_imap_draft_error,
    friendly_smtp_transport_error,
    friendly_with_technical_hint,
)


class CompactTechnicalDetailTests(unittest.TestCase):
    def test_compacts_whitespace(self):
        self.assertEqual(
            "SMTP Error: auth failed",
            compact_technical_detail("  SMTP Error:\n auth failed  "),
        )


class FriendlyWithTechnicalHintTests(unittest.TestCase):
    def test_adds_technical_hint_for_raw_detail(self):
        message = friendly_with_technical_hint("Die Datei konnte nicht gelesen werden.", "Permission denied")
        self.assertIn("Die Datei konnte nicht gelesen werden.", message)
        self.assertIn("Technischer Hinweis: Permission denied", message)

    def test_keeps_existing_friendly_detail_without_second_hint_label(self):
        message = friendly_with_technical_hint(
            "Die E-Mails konnten nicht gesendet werden.",
            "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen.",
        )
        self.assertEqual(
            "Die E-Mails konnten nicht gesendet werden. Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen.",
            message,
        )

    def test_config_issue_uses_technical_hint_style(self):
        message = friendly_config_issue(
            "Das Speichern von Entwürfen ist aktuell nicht eingerichtet.",
            "Bitte `mse_imap_mail_drafts` in den Secrets prüfen.",
        )
        self.assertIn("Das Speichern von Entwürfen ist aktuell nicht eingerichtet.", message)
        self.assertIn("Technischer Hinweis:", message)
        self.assertIn("mse_imap_mail_drafts", message)


class FriendlyTransportFallbackTests(unittest.TestCase):
    def test_unknown_smtp_error_is_friendly(self):
        message = friendly_smtp_transport_error("Unexpected SMTP 451 greylisting issue")
        self.assertIn("SMTP-Fehler", message)
        self.assertIn("Technischer Hinweis:", message)

    def test_unknown_imap_draft_error_is_friendly(self):
        message = friendly_imap_draft_error("Temporary append failure")
        self.assertIn("Entwurfsordner", message)
        self.assertIn("Technischer Hinweis:", message)

    def test_unknown_imap_append_error_is_friendly(self):
        message = friendly_imap_append_error("Mailbox append failed")
        self.assertIn("Sent-Kopie", message)
        self.assertIn("Technischer Hinweis:", message)


if __name__ == "__main__":
    unittest.main()
