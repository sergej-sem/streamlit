import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_signatures import (
    SIGNATURE_SEVERIN_HTML,
    known_signature_html_values,
    signature_html_for_sender,
)


class MailSignaturesTests(unittest.TestCase):
    def test_signature_html_for_known_sender(self):
        self.assertIn("Severin Wagner", signature_html_for_sender("severin.wagner@mysecurityevent.de"))

    def test_signature_lookup_is_case_insensitive(self):
        self.assertEqual(
            SIGNATURE_SEVERIN_HTML,
            signature_html_for_sender("Severin.Wagner@mysecurityevent.de"),
        )

    def test_unknown_sender_has_no_signature(self):
        self.assertEqual("", signature_html_for_sender("unknown@example.com"))

    def test_known_signature_values_are_unique(self):
        values = known_signature_html_values()
        self.assertEqual(len(values), len(set(values)))
        self.assertIn(SIGNATURE_SEVERIN_HTML, values)


if __name__ == "__main__":
    unittest.main()
