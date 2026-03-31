import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serienmailing.mail_builder import (
    SIGNATURE_SEVERIN_HTML,
    build_html_body,
    build_subject,
    html_to_plain_text,
    search_sender_emails,
)


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


class SearchSenderEmailsTests(unittest.TestCase):

    def test_empty_search_returns_default_suggestions(self):
        result = search_sender_emails("")
        self.assertGreater(len(result), 0)
        self.assertEqual("severin.wagner@mysecurityevent.de", result[0])

    def test_prefix_matches_rank_before_contains(self):
        result = search_sender_emails("alex")
        self.assertEqual("alexander.christoph@mysecurityevent.de", result[0])

    def test_contains_matches_are_returned(self):
        result = search_sender_emails("duske")
        self.assertIn("robert.duske@mysecurityevent.de", result)


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

    def test_empty_html_returns_fallback(self):
        result = html_to_plain_text("")
        self.assertTrue(len(result) > 0)

    def test_whitespace_only_returns_fallback(self):
        result = html_to_plain_text("   ")
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
