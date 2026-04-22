import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_signatures import SIGNATURE_SEVERIN_HTML
from shared.mail_rich_text import (
    _quill_ui_bridge_html,
    default_mail_body_html,
    default_mail_body_text,
    editor_html_is_meaningful,
    plain_text_to_editor_html,
    quill_toolbar_config,
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

    def test_quill_toolbar_contains_link_and_list_tools(self):
        toolbar = str(quill_toolbar_config())
        self.assertIn("link", toolbar)
        self.assertIn("ordered", toolbar)
        self.assertIn("bullet", toolbar)

    def test_quill_ui_bridge_contains_german_labels_and_link_handler_override(self):
        bridge_html = _quill_ui_bridge_html()
        self.assertIn("Link eingeben:", bridge_html)
        self.assertIn("Speichern", bridge_html)
        self.assertIn("Serifenlos", bridge_html)
        self.assertIn("Klein", bridge_html)
        self.assertIn("Groß", bridge_html)
        self.assertIn("Riesig", bridge_html)
        self.assertIn("container.__quill", bridge_html)
        self.assertIn('getModule("toolbar")', bridge_html)
        self.assertIn('toolbar.addHandler("link"', bridge_html)
        self.assertIn('tooltip.edit("link", existingLink || "")', bridge_html)
        self.assertIn("__mseLinkHandlerPatched", bridge_html)
        self.assertIn("clearNonUrlPrefill", bridge_html)
        self.assertIn("!isUrlLike(trimmed)", bridge_html)
        self.assertIn('input.value = ""', bridge_html)
        self.assertIn("requestAnimationFrame", bridge_html)
        self.assertIn("setTimeout", bridge_html)
        self.assertIn('data-mse-link-editing', bridge_html)
        self.assertNotIn('data-mse-link-state', bridge_html)


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

    def test_sanitize_editor_html_keeps_links_and_safe_attributes(self):
        cleaned = sanitize_editor_html(
            '<p><a href="https://mysecurityevent.de" target="_blank" rel="noopener" '
            'title="MSE" style="color:#0078D4;font-size:1.25em">Link</a></p>'
        )
        self.assertIn("<a ", cleaned)
        self.assertIn('href="https://mysecurityevent.de"', cleaned)
        self.assertIn('target="_blank"', cleaned)
        self.assertIn('rel="noopener"', cleaned)
        self.assertIn('title="MSE"', cleaned)
        self.assertIn("color", cleaned)
        self.assertIn("font-size", cleaned)

    def test_sanitize_editor_html_normalizes_outlook_b_and_i_tags(self):
        cleaned = sanitize_editor_html('<p class="MsoNormal"><b>Hallo</b> <i>Welt</i><o:p></o:p></p>')
        self.assertIn("<strong>Hallo</strong>", cleaned)
        self.assertIn("<em>Welt</em>", cleaned)
        self.assertNotIn("<o:p>", cleaned)

    def test_sanitize_editor_html_converts_font_tags_to_span_styles(self):
        cleaned = sanitize_editor_html('<p><font color="#1F497D" face="Calibri" size="4">Hallo</font></p>')
        self.assertIn("<span", cleaned)
        self.assertIn("color:#1F497D", cleaned)
        self.assertIn("font-family:Calibri", cleaned)
        self.assertIn("font-size:1.125em", cleaned)

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

    def test_render_final_mail_html_keeps_links(self):
        rendered = render_final_mail_html(
            '<p><a href="https://mysecurityevent.de" style="color:#0078D4">Link</a></p>',
            sender_email="severin.wagner@mysecurityevent.de",
        )
        self.assertIn('href="https://mysecurityevent.de"', rendered)
        self.assertIn(">Link</a>", rendered)
        self.assertEqual(1, rendered.count("Severin Wagner"))

    def test_render_final_mail_html_keeps_lists(self):
        rendered = render_final_mail_html(
            "<p>Agenda:</p><ul><li><strong>Punkt 1</strong></li><li>Punkt 2</li></ul>",
            sender_email="severin.wagner@mysecurityevent.de",
        )
        self.assertIn("<ul>", rendered)
        self.assertIn("<li><strong>Punkt 1</strong></li>", rendered)
        self.assertIn("<li>Punkt 2</li>", rendered)


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
