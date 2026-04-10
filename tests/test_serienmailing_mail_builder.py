import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serienmailing.mail_builder import (
    SIGNATURE_SEVERIN_HTML,
    SENDER_EMAIL_SUGGESTIONS,
    build_html_body,
    build_subject,
    html_to_plain_text,
)
from shared.email_input import build_email_select_options, normalize_email_widget_value


class BuildHtmlBodyTests(unittest.TestCase):

    def _body(self, vorname="Max", text="Hier ist der Text.", sig=SIGNATURE_SEVERIN_HTML):
        return build_html_body(vorname, text, sig)

    def test_signature_present(self):
        body = self._body()
        self.assertIn("Severin Wagner", body)

    def test_text_present(self):
        body = self._body(text="Wichtige Info")
        self.assertIn("Wichtige Info", body)

    def test_firma_placeholder_in_body(self):
        body = build_html_body("Max", "Hallo {firma}!", "", firma="ACME GmbH")
        self.assertIn("ACME GmbH", body)
        self.assertNotIn("{firma}", body)

    def test_email_placeholder_in_body(self):
        body = build_html_body("Max", "Ihre E-Mail: {email}", "", email="max@example.com")
        self.assertIn("max@example.com", body)
        self.assertNotIn("{email}", body)

    def test_vorname_placeholder_in_body(self):
        body = build_html_body("Anna", "Hallo {vorname}, wie geht's?", "")
        self.assertIn("Hallo Anna, wie geht&#x27;s?", body)
        self.assertNotIn("{vorname}", body)

    def test_newlines_converted_to_br(self):
        body = self._body(text="Zeile 1\nZeile 2")
        self.assertIn("<br>", body)
        # The <br> tag must appear between "Zeile 1" and "Zeile 2"
        br_pos = body.find("<br>")
        z1_pos = body.find("Zeile 1")
        z2_pos = body.find("Zeile 2")
        self.assertGreater(br_pos, z1_pos)
        self.assertGreater(z2_pos, br_pos)

    def test_html_special_chars_escaped(self):
        body = self._body(vorname="Klaus", text="<b>bold</b>")
        self.assertNotIn("<b>bold</b>", body)
        self.assertIn("&lt;b&gt;", body)

    def test_custom_signature(self):
        body = build_html_body("Anna", "Hi", "<p>Custom Sig</p>")
        self.assertIn("Custom Sig", body)

    def test_returns_string(self):
        self.assertIsInstance(self._body(), str)

    def test_default_closing_is_present(self):
        body = self._body(text="Mailtext")
        self.assertIn("Beste Gr", body)

    def test_closing_text_can_be_disabled_with_empty_string(self):
        body = build_html_body("Anna", "Text", "", closing_text="")
        self.assertNotIn("Beste Gr", body)

    def test_closing_text_can_be_disabled_with_none(self):
        body = build_html_body("Anna", "Text", "", closing_text=None)
        self.assertNotIn("Beste Gr", body)

    def test_signature_after_text(self):
        body = self._body(text="Mailtext")
        text_pos = body.find("Mailtext")
        sig_pos = body.find("Severin Wagner")
        self.assertGreater(text_pos, 0)
        self.assertGreater(sig_pos, text_pos)
        self.assertNotIn("<hr>", body)

    def test_no_signature_when_empty(self):
        body = build_html_body("Anna", "Text", "")
        self.assertNotIn("Severin", body)
        self.assertNotIn("<br>", body.split("Text")[1])  # no trailing <br> after text block


class BuildSubjectTests(unittest.TestCase):

    def test_vorname_placeholder_replaced(self):
        result = build_subject("Hallo {vorname}", "Anna", "ACME")
        self.assertEqual(result, "Hallo Anna")

    def test_firma_placeholder_replaced(self):
        result = build_subject("Re: {firma}", "Bob", "Corp GmbH")
        self.assertEqual(result, "Re: Corp GmbH")

    def test_both_placeholders(self):
        result = build_subject("{vorname} von {firma}", "Eva", "MSE")
        self.assertEqual(result, "Eva von MSE")

    def test_email_placeholder_replaced(self):
        result = build_subject("An: {email}", "X", "Y", "x@example.com")
        self.assertEqual(result, "An: x@example.com")

    def test_no_placeholder(self):
        result = build_subject("Einladung", "X", "Y")
        self.assertEqual(result, "Einladung")

    def test_empty_template(self):
        result = build_subject("", "A", "B")
        self.assertEqual(result, "")

    def test_returns_string(self):
        self.assertIsInstance(build_subject("x", "y", "z"), str)


class SignatureSeverinTests(unittest.TestCase):

    def test_constant_is_string(self):
        self.assertIsInstance(SIGNATURE_SEVERIN_HTML, str)

    def test_contains_name(self):
        self.assertIn("Severin Wagner", SIGNATURE_SEVERIN_HTML)

    def test_contains_phone(self):
        self.assertIn("+49", SIGNATURE_SEVERIN_HTML)

    def test_contains_company(self):
        self.assertIn("mysecurityevent", SIGNATURE_SEVERIN_HTML)


class EmailInputHelperTests(unittest.TestCase):

    def test_normalize_plain_string_strips_whitespace(self):
        self.assertEqual("custom@example.com", normalize_email_widget_value("  custom@example.com  "))

    def test_normalize_legacy_searchbox_dict_prefers_result(self):
        raw = {"result": "picked@example.com", "search": "typed@example.com"}
        self.assertEqual("picked@example.com", normalize_email_widget_value(raw))

    def test_normalize_legacy_searchbox_dict_falls_back_to_search(self):
        raw = {"result": "", "search": "typed@example.com"}
        self.assertEqual("typed@example.com", normalize_email_widget_value(raw))

    def test_empty_state_keeps_original_suggestions(self):
        result = build_email_select_options(SENDER_EMAIL_SUGGESTIONS, "")
        self.assertEqual(SENDER_EMAIL_SUGGESTIONS, result)

    def test_custom_email_is_added_first(self):
        result = build_email_select_options(SENDER_EMAIL_SUGGESTIONS, "custom@example.com")
        self.assertEqual("custom@example.com", result[0])
        self.assertIn("severin.wagner@mysecurityevent.de", result)

    def test_existing_suggestion_is_not_duplicated_case_insensitively(self):
        result = build_email_select_options(SENDER_EMAIL_SUGGESTIONS, "Severin.Wagner@mysecurityevent.de")
        lowered = [item.lower() for item in result]
        self.assertEqual(1, lowered.count("severin.wagner@mysecurityevent.de"))


class HtmlToPlainTextTests(unittest.TestCase):
    """Tests for html_to_plain_text (shared helper, now lives in mail_builder)."""

    def test_br_converted_to_newline(self):
        result = html_to_plain_text("<p>Line1</p><br>Line2")
        self.assertIn("Line1", result)
        self.assertIn("Line2", result)
        self.assertIn("\n", result)

    def test_br_selfclosing_with_space(self):
        result = html_to_plain_text("A<br />B")
        self.assertIn("\n", result)

    def test_br_selfclosing_no_space(self):
        result = html_to_plain_text("A<br/>B")
        self.assertIn("\n", result)

    def test_p_close_tag_adds_blank_line(self):
        result = html_to_plain_text("<p>Para1</p><p>Para2</p>")
        self.assertIn("Para1", result)
        self.assertIn("Para2", result)

    def test_html_tags_stripped(self):
        result = html_to_plain_text("<b>Bold</b> and <i>italic</i>")
        self.assertNotIn("<b>", result)
        self.assertIn("Bold", result)

    def test_script_tag_removed(self):
        result = html_to_plain_text("<script>alert('xss')</script>Text")
        self.assertNotIn("alert", result)
        self.assertIn("Text", result)

    def test_style_tag_removed(self):
        result = html_to_plain_text("<style>.foo { color: red; }</style>Text")
        self.assertNotIn("color", result)
        self.assertIn("Text", result)

    def test_html_entities_unescaped(self):
        result = html_to_plain_text("&lt;hello&gt; &amp; world")
        self.assertIn("<hello>", result)
        self.assertIn("& world", result)

    def test_excessive_newlines_collapsed(self):
        result = html_to_plain_text("<p>A</p>\n\n\n\n<p>B</p>")
        self.assertNotIn("\n\n\n", result)

    def test_anchor_with_label_keeps_target_in_parentheses(self):
        result = html_to_plain_text('<p><a href="https://mysecurityevent.de">Zum Event</a></p>')
        self.assertIn("Zum Event (https://mysecurityevent.de)", result)

    def test_anchor_with_same_url_text_is_not_duplicated(self):
        result = html_to_plain_text(
            '<p><a href="https://mysecurityevent.de/">https://mysecurityevent.de/</a></p>'
        )
        self.assertEqual(1, result.count("https://mysecurityevent.de/"))
        self.assertNotIn("(", result)

    def test_tel_anchor_with_same_visible_text_stays_readable(self):
        result = html_to_plain_text('<p><a href="tel:+493052284088">+49 30 52284088</a></p>')
        self.assertIn("+49 30 52284088", result)
        self.assertNotIn("tel:+493052284088", result)

    def test_empty_html_returns_fallback(self):
        result = html_to_plain_text("")
        self.assertTrue(len(result) > 0)

    def test_whitespace_only_returns_fallback(self):
        result = html_to_plain_text("   ")
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
