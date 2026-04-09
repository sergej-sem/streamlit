import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_signatures import SIGNATURE_SEVERIN_HTML
from shared.mail_rich_text import (
    default_mail_body_html,
    default_mail_body_text,
    editor_html_is_meaningful,
    plain_text_to_editor_html,
    render_final_mail_html,
    render_personalized_rich_text_html,
    sanitize_editor_html,
)


class MailRichTextDefaultsTests(unittest.TestCase):
    def test_default_mail_body_text_contains_visible_closing(self):
        self.assertEqual("\n\nBeste Grüße,", default_mail_body_text())

    def test_default_mail_body_html_contains_visible_closing(self):
        self.assertIn("Beste Grüße,", default_mail_body_html())

    def test_plain_text_to_editor_html_preserves_newlines(self):
        html = plain_text_to_editor_html("\n\nBeste Grüße,")
        self.assertIn("Beste Grüße,", html)


class MailRichTextSanitizationTests(unittest.TestCase):
    def test_sanitize_editor_html_keeps_allowed_formatting_and_inlines_known_quill_classes(self):
        cleaned = sanitize_editor_html(
            '<p><span class="ql-size-large ql-font-serif" style="color:#ff0000">Hallo</span></p>'
            '<script>alert(1)</script>'
        )
        self.assertIn("font-size", cleaned)
        self.assertIn("font-family", cleaned)
        self.assertIn("color", cleaned)
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("ql-size-large", cleaned)

    def test_render_personalized_rich_text_html_replaces_placeholders_and_escapes_values(self):
        rendered = render_personalized_rich_text_html(
            "<p>Hallo {vorname}, willkommen bei {firma} ({email}).</p>",
            vorname="Jörg",
            firma="ACME & Co",
            email="joerg@example.com",
        )
        self.assertIn("Jörg", rendered)
        self.assertIn("ACME &amp; Co", rendered)
        self.assertIn("joerg@example.com", rendered)
        self.assertNotIn("{vorname}", rendered)

    def test_editor_html_is_meaningful_detects_empty_editor_markup(self):
        self.assertFalse(editor_html_is_meaningful("<p><br></p>"))
        self.assertTrue(editor_html_is_meaningful(default_mail_body_html()))

    def test_render_final_mail_html_appends_sender_signature(self):
        rendered = render_final_mail_html(
            "<p>Hallo {vorname}</p><p><br></p><p>Beste Grüße,</p>",
            sender_email="severin.wagner@mysecurityevent.de",
            vorname="Jörg",
        )
        self.assertIn("Severin Wagner", rendered)
        self.assertEqual(1, rendered.count("Severin Wagner"))

    def test_render_final_mail_html_does_not_duplicate_existing_signature(self):
        rendered = render_final_mail_html(
            (
                "<p>Hallo {vorname}</p><p><br></p><p>Beste Grüße,</p>"
                f"{SIGNATURE_SEVERIN_HTML}"
            ),
            sender_email="severin.wagner@mysecurityevent.de",
            vorname="Jörg",
        )
        self.assertEqual(1, rendered.count("Severin Wagner"))


    def test_render_final_mail_html_normalizes_paragraph_spacing(self):
        rendered = render_final_mail_html(
            "<p>Hallo</p><p><br></p><div>Welt</div>",
            vorname="Joerg",
        )
        self.assertIn('<p style="margin:0; line-height:inherit">Hallo</p>', rendered)
        self.assertIn('<p style="margin:0; line-height:inherit"><br></p>', rendered)
        self.assertIn('<div style="margin:0; line-height:inherit">Welt</div>', rendered)


class StreamlitQuillImportTests(unittest.TestCase):
    def test_streamlit_quill_can_be_imported(self):
        from streamlit_quill import st_quill

        self.assertTrue(callable(st_quill))


if __name__ == "__main__":
    unittest.main()
