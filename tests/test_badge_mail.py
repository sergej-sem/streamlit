import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
from PIL import Image as _PilImage

from badgegen.badge_mail import (
    _safe_filename,
    build_badge_mails,
    build_badge_notification_mails,
)
from badgegen.category import ALLOWED_CATEGORIES


def _make_tpl_map(tmpdir: str) -> dict:
    """Create a minimal valid tpl_map with one white 10×10 PNG per category."""
    path = os.path.join(tmpdir, "dummy.png")
    img = _PilImage.new("RGB", (10, 10), color=(255, 255, 255))
    img.save(path, format="PNG")
    return {cat: path for cat in ALLOWED_CATEGORIES}


def _row(
    firstname="Max",
    lastname="Mustermann",
    company="ACME",
    jobtitle="Manager",
    email="max@example.com",
    kategorie="TN",
    id="001",
    historie="",
) -> dict:
    return dict(
        firstname=firstname, lastname=lastname, company=company,
        jobtitle=jobtitle, email=email, kategorie=kategorie,
        id=id, historie=historie,
    )


class SafeFilenameTests(unittest.TestCase):

    def test_basic(self):
        result = _safe_filename("Max", "Mustermann")
        self.assertEqual(result, "Badge_Max_Mustermann.pdf")

    def test_spaces_replaced(self):
        result = _safe_filename("Anna Maria", "von Trapp")
        self.assertNotIn(" ", result)
        self.assertTrue(result.endswith(".pdf"))

    def test_special_chars_sanitized(self):
        result = _safe_filename("Björn", "Müller")
        self.assertFalse(result.startswith("_"))
        self.assertTrue(result.endswith(".pdf"))


class BuildBadgeMailsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._tpl_map = _make_tpl_map(cls._tmpdir)

    def _df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    # ── skip logic ─────────────────────────────────────────────────────────

    def test_skips_row_without_email(self):
        df = self._df([_row(email="")])
        mails, skipped = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(len(mails), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn("E-Mail", skipped[0]["reason"])

    def test_skips_row_with_whitespace_only_email(self):
        df = self._df([_row(email="   ")])
        mails, skipped = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(len(mails), 0)
        self.assertEqual(len(skipped), 1)

    def test_skips_row_with_unknown_category(self):
        df = self._df([_row(kategorie="UNBEKANNT")])
        mails, skipped = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(len(mails), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn("UNBEKANNT", skipped[0]["reason"])

    def test_skips_row_with_empty_category(self):
        df = self._df([_row(kategorie="")])
        mails, skipped = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(len(mails), 0)
        self.assertEqual(len(skipped), 1)

    # ── valid rows ──────────────────────────────────────────────────────────

    def test_valid_row_produces_serien_mail(self):
        df = self._df([_row()])
        mails, skipped = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(len(mails), 1)
        self.assertEqual(len(skipped), 0)

    def test_attachment_bytes_is_pdf(self):
        df = self._df([_row()])
        mails, _ = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertIsNotNone(mails[0].attachment_bytes)
        self.assertTrue(mails[0].attachment_bytes.startswith(b"%PDF"))

    def test_attachment_filename_ends_with_pdf(self):
        df = self._df([_row(firstname="Anna", lastname="Schmidt")])
        mails, _ = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertTrue(mails[0].attachment_filename.endswith(".pdf"))
        self.assertIn("Anna", mails[0].attachment_filename)

    def test_to_email_matches_row(self):
        df = self._df([_row(email="test@example.com")])
        mails, _ = build_badge_mails(df, "Subj", "Body", "", self._tpl_map)
        self.assertEqual(mails[0].to_email, "test@example.com")

    def test_subject_placeholder_replaced(self):
        df = self._df([_row(firstname="Eva", company="Corp")])
        mails, _ = build_badge_mails(df, "{vorname} von {firma}", "Body", "", self._tpl_map)
        self.assertEqual(mails[0].subject, "Eva von Corp")

    def test_rich_text_body_template_is_rendered_without_hidden_signature(self):
        df = self._df([_row(firstname="Eva", company="Corp")])
        mails, _ = build_badge_mails(
            df,
            "Betreff",
            "",
            "",
            self._tpl_map,
            body_html_template="<p><strong>Hallo {vorname}</strong></p><p><br></p><p>Beste Grüße,</p>",
        )
        self.assertIn("<strong>Hallo Eva</strong>", mails[0].html_body)
        self.assertNotIn("Severin Wagner", mails[0].html_body)

    def test_rich_text_body_template_appends_sender_signature_once(self):
        df = self._df([_row(firstname="Eva", company="Corp")])
        mails, _ = build_badge_mails(
            df,
            "Betreff",
            "",
            "",
            self._tpl_map,
            body_html_template="<p><strong>Hallo {vorname}</strong></p><p><br></p><p>Beste Grüße,</p>",
            sender_email="severin.wagner@mysecurityevent.de",
        )
        self.assertEqual(1, mails[0].html_body.count("Severin Wagner"))

    def test_rich_text_body_template_keeps_links(self):
        df = self._df([_row(firstname="Eva", company="Corp")])
        mails, _ = build_badge_mails(
            df,
            "Betreff",
            "",
            "",
            self._tpl_map,
            body_html_template=(
                '<p><a href="https://mysecurityevent.de" style="color:#0078D4">'
                "Zum Event"
                "</a></p>"
            ),
        )
        self.assertIn('href="https://mysecurityevent.de"', mails[0].html_body)
        self.assertIn(">Zum Event</a>", mails[0].html_body)

    # ── mixed input ─────────────────────────────────────────────────────────

    def test_returns_correct_counts_mixed(self):
        rows = [
            _row(email="a@x.com", kategorie="TN"),          # valid
            _row(email="", kategorie="TN"),                  # skip: no email
            _row(email="b@x.com", kategorie="GHOST"),        # skip: unknown cat
            _row(email="c@x.com", kategorie="Sponsor"),      # valid
        ]
        df = self._df(rows)
        mails, skipped = build_badge_mails(df, "S", "B", "", self._tpl_map)
        self.assertEqual(len(mails), 2)
        self.assertEqual(len(skipped), 2)

    def test_all_categories_produce_mails(self):
        rows = [_row(kategorie=cat, email=f"{cat}@x.com", id=cat) for cat in ALLOWED_CATEGORIES]
        df = self._df(rows)
        mails, skipped = build_badge_mails(df, "S", "B", "", self._tpl_map)
        self.assertEqual(len(mails), len(ALLOWED_CATEGORIES))
        self.assertEqual(len(skipped), 0)

    def test_empty_dataframe_returns_empty_lists(self):
        df = pd.DataFrame(columns=["firstname", "lastname", "company", "jobtitle", "email", "kategorie", "id", "historie"])
        mails, skipped = build_badge_mails(df, "S", "B", "", self._tpl_map)
        self.assertEqual(mails, [])
        self.assertEqual(skipped, [])


class BuildBadgeNotificationMailsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._tpl_map = _make_tpl_map(cls._tmpdir)

    def _df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_notification_subject_contains_full_name(self):
        df = self._df([_row(firstname="Eva", lastname="Schmidt")])
        mails, skipped = build_badge_notification_mails(df, "notify@example.com", self._tpl_map)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(mails[0].subject, "Neues Badge erstellt für: Eva Schmidt")

    def test_notification_attachment_bytes_is_pdf(self):
        df = self._df([_row()])
        mails, _ = build_badge_notification_mails(df, "notify@example.com", self._tpl_map)
        self.assertTrue(mails[0].attachment_bytes.startswith(b"%PDF"))

    def test_notification_uses_configured_recipient(self):
        df = self._df([_row(email="participant@example.com")])
        mails, _ = build_badge_notification_mails(df, "notify@example.com", self._tpl_map)
        self.assertEqual("notify@example.com", mails[0].to_email)

    def test_notification_does_not_require_participant_email(self):
        df = self._df([_row(email="")])
        mails, skipped = build_badge_notification_mails(df, "notify@example.com", self._tpl_map)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(1, len(mails))
        self.assertEqual("notify@example.com", mails[0].to_email)

    def test_notification_skips_unknown_category(self):
        df = self._df([_row(kategorie="UNBEKANNT")])
        mails, skipped = build_badge_notification_mails(df, "notify@example.com", self._tpl_map)
        self.assertEqual(mails, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("UNBEKANNT", skipped[0]["reason"])


if __name__ == "__main__":
    unittest.main()
