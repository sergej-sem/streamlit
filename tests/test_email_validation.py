import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.email_validation import is_valid_email_address, normalize_email_address


class NormalizeEmailAddressTests(unittest.TestCase):
    def test_normalizes_display_name_and_domain(self):
        self.assertEqual(
            "karine.peters@t.capital",
            normalize_email_address("Karine Peters <karine.peters@T.CAPITAL>"),
        )


class IsValidEmailAddressTests(unittest.TestCase):
    def test_accepts_modern_domain_and_dotted_local_part(self):
        self.assertTrue(is_valid_email_address("karine.peters@t.capital"))

    def test_accepts_plus_aliases(self):
        self.assertTrue(is_valid_email_address("first.last+tag@example.com"))

    def test_accepts_subdomains(self):
        self.assertTrue(is_valid_email_address("user@mail.sub.example.com"))

    def test_rejects_double_at(self):
        self.assertFalse(is_valid_email_address("bad@@example.com"))

    def test_rejects_missing_at_sign(self):
        self.assertFalse(is_valid_email_address("no-at-sign"))

    def test_rejects_domain_without_dot(self):
        self.assertFalse(is_valid_email_address("x@y"))

    def test_rejects_localhost_domain(self):
        self.assertFalse(is_valid_email_address("user@localhost"))


if __name__ == "__main__":
    unittest.main()
