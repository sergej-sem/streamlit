import unittest

from serienmailing.mail_builder import html_to_plain_text as _html_to_plain_text


class HtmlToPlainTextTests(unittest.TestCase):
    """Regression tests for the _html_to_plain_text helper in imap_drafts."""

    def test_br_self_closing_with_space_converted_to_newline(self):
        # Regression: r"<br\\s*/?>`` did not match whitespace inside the tag.
        result = _html_to_plain_text("Line1<br />Line2")
        self.assertIn("\n", result)
        self.assertIn("Line1", result)
        self.assertIn("Line2", result)

    def test_br_self_closing_no_space_converted_to_newline(self):
        result = _html_to_plain_text("A<br/>B")
        self.assertIn("\n", result)

    def test_br_without_slash_converted_to_newline(self):
        result = _html_to_plain_text("A<br>B")
        self.assertIn("\n", result)

    def test_script_tag_removed(self):
        # Regression: r"</\\1>" did not correctly backreference group 1.
        result = _html_to_plain_text("<script>alert('xss')</script>VisibleText")
        self.assertNotIn("alert", result)
        self.assertIn("VisibleText", result)

    def test_style_tag_removed(self):
        result = _html_to_plain_text("<style>.foo { color: red; }</style>VisibleText")
        self.assertNotIn("color", result)
        self.assertIn("VisibleText", result)

    def test_p_close_tag_adds_blank_line(self):
        result = _html_to_plain_text("<p>Para1</p><p>Para2</p>")
        self.assertIn("Para1", result)
        self.assertIn("Para2", result)

    def test_html_entities_unescaped(self):
        result = _html_to_plain_text("&lt;hello&gt; &amp; world")
        self.assertIn("<hello>", result)
        self.assertIn("& world", result)

    def test_excessive_newlines_collapsed(self):
        result = _html_to_plain_text("<p>A</p>\n\n\n\n<p>B</p>")
        self.assertNotIn("\n\n\n", result)

    def test_empty_input_returns_fallback(self):
        result = _html_to_plain_text("")
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
