import sys
import os
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serienmailing.contacts import (
    contacts_from_excel,
    contacts_from_hubspot_raw,
    contacts_from_manual,
    validate_contacts,
    COLS,
)


class ContactsFromExcelTests(unittest.TestCase):

    def _df(self, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(kwargs)

    # ── column aliases ───────────────────────────────────────────────────────

    def test_standard_german_columns(self):
        df = self._df(vorname=["Anna"], firma=["ACME"], email=["anna@example.com"])
        result, warns = contacts_from_excel(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["vorname"], "Anna")
        self.assertEqual(result.iloc[0]["firma"], "ACME")
        self.assertEqual(result.iloc[0]["email"], "anna@example.com")
        self.assertEqual(warns, [])

    def test_english_column_names(self):
        df = self._df(firstname=["Bob"], company=["Corp"], email=["bob@example.com"])
        result, warns = contacts_from_excel(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["vorname"], "Bob")
        self.assertEqual(result.iloc[0]["firma"], "Corp")

    def test_email_alias_with_hyphen(self):
        df = pd.DataFrame({"vorname": ["C"], "firma": ["F"], "e-mail": ["c@x.com"]})
        result, _ = contacts_from_excel(df)
        self.assertEqual(result.iloc[0]["email"], "c@x.com")

    def test_case_insensitive_column_detection(self):
        df = pd.DataFrame({"Vorname": ["D"], "Firma": ["G"], "Email": ["d@x.com"]})
        result, _ = contacts_from_excel(df)
        self.assertEqual(result.iloc[0]["email"], "d@x.com")

    # ── missing columns ──────────────────────────────────────────────────────

    def test_missing_vorname_column_gives_warning(self):
        df = self._df(firma=["F"], email=["e@x.com"])
        result, warns = contacts_from_excel(df)
        self.assertEqual(len(result), 1)
        self.assertTrue(any("Vorname" in w for w in warns))
        self.assertEqual(result.iloc[0]["vorname"], "")

    def test_missing_firma_column_gives_warning(self):
        df = self._df(vorname=["V"], email=["e@x.com"])
        result, warns = contacts_from_excel(df)
        self.assertTrue(any("Firma" in w for w in warns))

    def test_missing_email_column_gives_warning_and_empty_result(self):
        df = self._df(vorname=["V"], firma=["F"])
        result, warns = contacts_from_excel(df)
        self.assertEqual(len(result), 0)
        self.assertTrue(any("E-Mail" in w for w in warns))

    # ── empty email filtering ────────────────────────────────────────────────

    def test_empty_emails_removed(self):
        df = self._df(
            vorname=["A", "B", "C"],
            firma=["F", "F", "F"],
            email=["a@x.com", "", "c@x.com"],
        )
        result, warns = contacts_from_excel(df)
        self.assertEqual(len(result), 2)
        self.assertTrue(any("entfernt" in w for w in warns))

    def test_whitespace_only_email_removed(self):
        df = self._df(vorname=["A"], firma=["F"], email=["   "])
        result, _ = contacts_from_excel(df)
        self.assertEqual(len(result), 0)

    def test_result_columns_always_match_cols(self):
        df = self._df(vorname=["A"], firma=["F"], email=["a@x.com"])
        result, _ = contacts_from_excel(df)
        self.assertEqual(list(result.columns), COLS)


class ContactsFromHubspotRawTests(unittest.TestCase):

    def test_basic_extraction(self):
        raw = [
            {"properties": {"firstname": "Eva", "company": "Corp", "email": "eva@x.com"}},
            {"properties": {"firstname": "Tom", "company": "Inc",  "email": "tom@x.com"}},
        ]
        result = contacts_from_hubspot_raw(raw)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["vorname"], "Eva")
        self.assertEqual(result.iloc[1]["firma"], "Inc")

    def test_missing_email_is_filtered(self):
        raw = [
            {"properties": {"firstname": "X", "company": "Y", "email": ""}},
            {"properties": {"firstname": "A", "company": "B", "email": "a@x.com"}},
        ]
        result = contacts_from_hubspot_raw(raw)
        self.assertEqual(len(result), 1)

    def test_missing_properties_key(self):
        raw = [{"id": "123"}]
        result = contacts_from_hubspot_raw(raw)
        self.assertEqual(len(result), 0)

    def test_none_values_become_empty_string(self):
        raw = [{"properties": {"firstname": None, "company": None, "email": "a@x.com"}}]
        result = contacts_from_hubspot_raw(raw)
        self.assertEqual(result.iloc[0]["vorname"], "")
        self.assertEqual(result.iloc[0]["firma"], "")

    def test_empty_input(self):
        result = contacts_from_hubspot_raw([])
        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), COLS)


class ContactsFromManualTests(unittest.TestCase):

    def test_basic_passthrough(self):
        df = pd.DataFrame({"vorname": ["Z"], "firma": ["Q"], "email": ["z@x.com"]})
        result, warns = contacts_from_manual(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(warns, [])

    def test_empty_email_removed_with_warning(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "F"], "email": ["", "b@x.com"]})
        result, warns = contacts_from_manual(df)
        self.assertEqual(len(result), 1)
        self.assertTrue(len(warns) > 0)


class ValidateContactsTests(unittest.TestCase):

    def test_clean_contacts_no_errors(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "G"], "email": ["a@x.com", "b@x.com"]})
        errors = validate_contacts(df)
        self.assertEqual(errors, [])

    def test_empty_df_returns_error(self):
        errors = validate_contacts(pd.DataFrame(columns=COLS))
        self.assertTrue(len(errors) > 0)

    def test_duplicate_email_detected(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "G"], "email": ["same@x.com", "same@x.com"]})
        errors = validate_contacts(df)
        self.assertTrue(any("doppelte" in e.lower() for e in errors))

    def test_empty_email_detected(self):
        df = pd.DataFrame({"vorname": ["A"], "firma": ["F"], "email": [""]})
        errors = validate_contacts(df)
        self.assertTrue(any("E-Mail" in e or "email" in e.lower() or "Kontakt" in e for e in errors))

    def test_duplicate_case_insensitive(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "G"], "email": ["Test@X.com", "test@x.com"]})
        errors = validate_contacts(df)
        self.assertTrue(any("doppelte" in e.lower() for e in errors))


if __name__ == "__main__":
    unittest.main()
