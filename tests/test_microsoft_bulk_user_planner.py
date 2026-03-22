import unittest

import pandas as pd

from microsoft_bulk_user.planner import build_plan


def make_name_exists(existing_names):
    normalized = {(first.casefold(), last.casefold()) for first, last in existing_names}

    def _name_exists(first: str, last: str) -> bool:
        return (first.casefold(), last.casefold()) in normalized

    return _name_exists


def make_upn_exists(existing_upns):
    normalized = {upn.casefold() for upn in existing_upns}

    def _upn_exists(upn: str) -> bool:
        return upn.casefold() in normalized

    return _upn_exists


class BuildPlanTests(unittest.TestCase):
    def test_missing_name_data_produces_error(self):
        df = pd.DataFrame([{"Vorname": "", "Nachname": ""}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["status"], "FEHLER")
        self.assertEqual(plan.iloc[0]["plannedUPN"], "")
        self.assertEqual(plan.iloc[0]["details"], "Vorname/Nachname fehlt oder konnte nicht erkannt werden")

    def test_fullname_splitting_works(self):
        df = pd.DataFrame([{"Name": "Max von Beispiel"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        row = plan.iloc[0]
        self.assertEqual(row["firstName"], "Max")
        self.assertEqual(row["lastName"], "von Beispiel")
        self.assertEqual(row["plannedUPN"], "max.vonbeispiel@example.com")
        self.assertEqual(row["status"], "BEREIT")

    def test_duplicate_in_uploaded_file_is_skipped(self):
        df = pd.DataFrame(
            [
                {"Vorname": "Max", "Nachname": "Mustermann"},
                {"Vorname": "Max", "Nachname": "Mustermann"},
            ]
        )
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["status"], "BEREIT")
        self.assertEqual(plan.iloc[1]["status"], "ÜBERSPRUNGEN")
        self.assertIn("Duplikat in der Datei", plan.iloc[1]["details"])

    def test_generated_upn_is_built_from_normalized_name(self):
        df = pd.DataFrame([{"Vorname": "Jörg", "Nachname": "Müller"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["plannedUPN"], "joerg.mueller@example.com")

    def test_provided_upn_without_domain_gets_domain_appended(self):
        df = pd.DataFrame([{"Vorname": "Max", "Nachname": "Mustermann", "UPN": "max.mustermann"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["plannedUPN"], "max.mustermann@example.com")

    def test_provided_upn_with_domain_is_kept(self):
        df = pd.DataFrame([{"Vorname": "Max", "Nachname": "Mustermann", "UPN": "max@other.example"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["plannedUPN"], "max@other.example")

    def test_invalid_generated_login_name_produces_error(self):
        df = pd.DataFrame([{"Vorname": "!!!", "Nachname": "***"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["status"], "FEHLER")
        self.assertEqual(plan.iloc[0]["details"], "Name kann nicht zu einem gültigen Login-Namen umgewandelt werden")

    def test_existing_name_case_is_skipped(self):
        df = pd.DataFrame([{"Vorname": "Max", "Nachname": "Mustermann"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists({("Max", "Mustermann")}),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(plan.iloc[0]["status"], "ÜBERSPRUNGEN")
        self.assertIn("existiert bereits in Entra", plan.iloc[0]["details"])

    def test_existing_upn_case_is_error(self):
        df = pd.DataFrame([{"Vorname": "Max", "Nachname": "Mustermann"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists({"max.mustermann@example.com"}),
        )
        self.assertEqual(plan.iloc[0]["status"], "FEHLER")
        self.assertIn("Login-Name (UPN) existiert bereits", plan.iloc[0]["details"])

    def test_output_contract_columns_and_statuses(self):
        df = pd.DataFrame([{"Vorname": "Max", "Nachname": "Mustermann"}])
        plan = build_plan(
            df,
            "example.com",
            name_exists=make_name_exists(set()),
            upn_exists=make_upn_exists(set()),
        )
        self.assertEqual(
            plan.columns.tolist(),
            ["row", "displayName", "firstName", "lastName", "plannedUPN", "status", "details"],
        )
        self.assertIn(plan.iloc[0]["status"], {"BEREIT", "ÜBERSPRUNGEN", "FEHLER"})


if __name__ == "__main__":
    unittest.main()
