import sys
import os
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serienmailing.contacts import (
    ContactColumnMapping,
    apply_contact_editor_changes,
    contacts_from_excel,
    contacts_from_hubspot_raw,
    contacts_from_manual,
    normalize_cc_addresses,
    normalize_contact_editor_data,
    recipient_validation_issues,
    suggest_contact_column_mapping,
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

    def test_example_workbook_headers_are_suggested_as_to_and_multiple_cc(self):
        columns = [
            "Sponsor",
            "ASP 1 Vorname",
            "ASP 1 E-Mail Adresse",
            "ASP 2 E-Mail Adresse",
            "ASP 3 E-Mail Adresse",
            "ASP 4 E-Mail Adresse",
        ]

        mapping = suggest_contact_column_mapping(columns)

        self.assertEqual("ASP 1 E-Mail Adresse", mapping.email)
        self.assertEqual(
            (
                "ASP 2 E-Mail Adresse",
                "ASP 3 E-Mail Adresse",
                "ASP 4 E-Mail Adresse",
            ),
            mapping.cc_email,
        )
        self.assertEqual("ASP 1 Vorname", mapping.vorname)
        self.assertEqual("Sponsor", mapping.firma)

    def test_explicit_mapping_combines_multiple_cc_columns(self):
        df = pd.DataFrame(
            {
                "Sponsor": ["ACME"],
                "First": ["Anna"],
                "Primary": ["anna@example.com"],
                "Copy A": [" copy@example.com "],
                "Copy B": ["second@example.com; COPY@example.com"],
            }
        )

        result, warns = contacts_from_excel(
            df,
            mapping=ContactColumnMapping(
                email="Primary",
                cc_email=("Copy A", "Copy B"),
                vorname="First",
                firma="Sponsor",
            ),
        )

        self.assertEqual([], warns)
        self.assertEqual("copy@example.com, second@example.com", result.iloc[0]["cc_email"])

    def test_to_address_is_removed_from_cc_case_insensitively(self):
        df = pd.DataFrame(
            {
                "email": ["Anna@Example.com"],
                "cc": ["anna@example.com; other@example.com"],
            }
        )

        result, _ = contacts_from_excel(
            df,
            mapping=ContactColumnMapping(email="email", cc_email=("cc",)),
        )

        self.assertEqual("other@example.com", result.iloc[0]["cc_email"])

    def test_empty_cc_cells_do_not_become_nan_text(self):
        df = pd.DataFrame({"email": ["a@example.com"], "cc": [None]})

        result, _ = contacts_from_excel(
            df,
            mapping=ContactColumnMapping(email="email", cc_email=("cc",)),
        )

        self.assertEqual("", result.iloc[0]["cc_email"])


class NormalizeCcAddressesTests(unittest.TestCase):

    def test_supports_commas_semicolons_and_newlines(self):
        result = normalize_cc_addresses(
            ["one@example.com; two@example.com", "three@example.com\nfour@example.com"]
        )
        self.assertEqual(
            "one@example.com, two@example.com, three@example.com, four@example.com",
            result,
        )


class NormalizeContactEditorDataTests(unittest.TestCase):

    def test_keeps_incomplete_recipient_row_visible_for_correction(self):
        result = normalize_contact_editor_data(
            pd.DataFrame(
                [
                    {
                        "vorname": "Anna",
                        "firma": "ACME",
                        "email": "",
                        "cc_email": "copy@example.com",
                    }
                ]
            )
        )

        self.assertEqual(1, len(result))
        self.assertEqual("", result.iloc[0]["email"])

    def test_drops_only_fully_empty_dynamic_rows(self):
        result = normalize_contact_editor_data(
            pd.DataFrame(
                [
                    {"vorname": "", "firma": "", "email": "", "cc_email": ""},
                    {
                        "vorname": "Anna",
                        "firma": "ACME",
                        "email": "anna@example.com",
                        "cc_email": "",
                    },
                ]
            )
        )

        self.assertEqual(1, len(result))
        self.assertEqual(list(range(len(result))), list(result.index))
        self.assertEqual(COLS, list(result.columns))

    def test_normalizes_and_deduplicates_edited_cc_addresses(self):
        result = normalize_contact_editor_data(
            pd.DataFrame(
                [
                    {
                        "vorname": "Anna",
                        "firma": "ACME",
                        "email": "anna@example.com",
                        "cc_email": (
                            "copy@example.com; COPY@example.com; anna@example.com; "
                            "second@EXAMPLE.COM"
                        ),
                    }
                ]
            )
        )

        self.assertEqual(
            "copy@example.com, second@example.com",
            result.iloc[0]["cc_email"],
        )

    def test_applies_inline_recipient_correction(self):
        source = pd.DataFrame(
            [
                {
                    "vorname": "Umit",
                    "firma": "Cribl",
                    "email": "TBD",
                    "cc_email": "",
                }
            ]
        )

        result = apply_contact_editor_changes(
            source,
            {
                "edited_rows": {0: {"email": "umit@example.com"}},
                "deleted_rows": [],
                "added_rows": [],
            },
        )

        self.assertEqual("umit@example.com", result.iloc[0]["email"])
        self.assertEqual([], recipient_validation_issues(result))

    def test_applies_row_deletion_and_resets_index(self):
        source = pd.DataFrame(
            [
                {"vorname": "Umit", "firma": "Cribl", "email": "TBD", "cc_email": ""},
                {
                    "vorname": "Anna",
                    "firma": "ACME",
                    "email": "anna@example.com",
                    "cc_email": "",
                },
            ]
        )

        result = apply_contact_editor_changes(
            source,
            {"edited_rows": {}, "deleted_rows": [0], "added_rows": []},
        )

        self.assertEqual(1, len(result))
        self.assertEqual("anna@example.com", result.iloc[0]["email"])
        self.assertEqual([0], list(result.index))

    def test_applies_partial_added_row_without_hiding_it(self):
        source = pd.DataFrame(columns=COLS)

        result = apply_contact_editor_changes(
            source,
            {
                "edited_rows": {},
                "deleted_rows": [],
                "added_rows": [{"vorname": "Neue Person"}],
            },
        )

        self.assertEqual(1, len(result))
        self.assertEqual("Neue Person", result.iloc[0]["vorname"])
        self.assertEqual("(leer)", recipient_validation_issues(result)[0].value)


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
        self.assertEqual(result.iloc[0]["cc_email"], "")

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

    def test_cc_is_normalized_for_manual_contacts(self):
        df = pd.DataFrame(
            {
                "vorname": ["A"],
                "firma": ["F"],
                "email": ["a@example.com"],
                "cc_email": ["copy@example.com; second@example.com"],
            }
        )

        result, warns = contacts_from_manual(df)

        self.assertEqual([], warns)
        self.assertEqual("copy@example.com, second@example.com", result.iloc[0]["cc_email"])


class ValidateContactsTests(unittest.TestCase):

    def test_clean_contacts_no_errors(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "G"], "email": ["a@x.com", "b@x.com"]})
        errors = validate_contacts(df)
        self.assertEqual(errors, [])

    def test_modern_email_addresses_are_accepted(self):
        df = pd.DataFrame({"vorname": ["A"], "firma": ["F"], "email": ["karine.peters@t.capital"]})
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

    def test_invalid_email_detected(self):
        df = pd.DataFrame({"vorname": ["A"], "firma": ["F"], "email": ["bad@@example.com"]})
        errors = validate_contacts(df)
        self.assertTrue(any("ungültig" in e.lower() for e in errors))

    def test_empty_email_is_reported_with_contact_number(self):
        df = pd.DataFrame(
            [
                {
                    "vorname": "Anna",
                    "firma": "ACME",
                    "email": "",
                    "cc_email": "",
                }
            ]
        )

        issues = recipient_validation_issues(df)

        self.assertEqual(1, len(issues))
        self.assertEqual(1, issues[0].contact_number)
        self.assertEqual("An", issues[0].field)
        self.assertEqual("(leer)", issues[0].value)

    def test_duplicate_case_insensitive(self):
        df = pd.DataFrame({"vorname": ["A", "B"], "firma": ["F", "G"], "email": ["Test@X.com", "test@x.com"]})
        errors = validate_contacts(df)
        self.assertTrue(any("doppelte" in e.lower() for e in errors))

    def test_multiple_valid_cc_addresses_are_accepted(self):
        df = pd.DataFrame(
            {
                "vorname": ["A"],
                "firma": ["F"],
                "email": ["a@example.com"],
                "cc_email": ["copy@example.com, second@example.com"],
            }
        )
        self.assertEqual([], validate_contacts(df))

    def test_invalid_cc_address_is_reported_with_contact_number(self):
        df = pd.DataFrame(
            {
                "vorname": ["A"],
                "firma": ["F"],
                "email": ["a@example.com"],
                "cc_email": ["copy@example.com, not-an-email"],
            }
        )

        errors = validate_contacts(df)
        issues = recipient_validation_issues(df)

        self.assertTrue(any("CC-Adresse" in error for error in errors))
        self.assertEqual(1, len(issues))
        self.assertEqual(1, issues[0].contact_number)
        self.assertEqual("CC", issues[0].field)
        self.assertEqual("not-an-email", issues[0].value)


if __name__ == "__main__":
    unittest.main()
