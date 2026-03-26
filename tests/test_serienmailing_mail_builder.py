import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serienmailing.mail_builder import (
    SIGNATURE_SEVERIN_HTML,
    build_html_body,
    build_subject,
)


class BuildHtmlBodyTests(unittest.TestCase):

    def _body(self, vorname="Max", text="Hier ist der Text.", sig=SIGNATURE_SEVERIN_HTML):
        return build_html_body(vorname, text, sig)

    def test_greeting_line_present(self):
        body = self._body(vorname="Klaus")
        self.assertIn("Hallo Klaus,", body)

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
        body = self._body(vorname="<script>", text="<b>bold</b>")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        # text also escaped
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


if __name__ == "__main__":
    unittest.main()
