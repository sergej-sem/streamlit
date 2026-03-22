import unittest

from microsoft_bulk_user.executor import execute_plan_row


def ready_row(**overrides):
    row = {
        "row": 1,
        "displayName": "Max Mustermann",
        "firstName": "Max",
        "lastName": "Mustermann",
        "plannedUPN": "max.mustermann@example.com",
        "status": "BEREIT",
        "details": "",
    }
    row.update(overrides)
    return row


class ExecutePlanRowTests(unittest.TestCase):
    def test_passthrough_row_keeps_planner_result(self):
        calls = {"build": 0, "create": 0, "assign": 0}

        result = execute_plan_row(
            ready_row(status="ÜBERSPRUNGEN", details="Schon vorhanden"),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=[],
            selected_sku_ids=[],
            build_payload=lambda **kwargs: calls.__setitem__("build", calls["build"] + 1),
            create_user=lambda payload: calls.__setitem__("create", calls["create"] + 1),
            assign_user_licenses=lambda user_id, sku_ids: calls.__setitem__("assign", calls["assign"] + 1),
        )

        self.assertEqual(result["outcome"], "planner_passthrough")
        self.assertEqual(result["log_row"]["Ergebnis"], "ÜBERSPRUNGEN")
        self.assertEqual(result["log_row"]["Hinweis"], "Schon vorhanden")
        self.assertEqual(calls, {"build": 0, "create": 0, "assign": 0})

    def test_dry_run_includes_license_preview(self):
        result = execute_plan_row(
            ready_row(),
            dry_run=True,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=["Microsoft 365 Business Standard"],
            selected_sku_ids=["sku-1"],
            build_payload=lambda **kwargs: {},
            create_user=lambda payload: {},
            assign_user_licenses=lambda user_id, sku_ids: None,
        )

        self.assertEqual(result["outcome"], "dry_run")
        self.assertEqual(result["log_row"]["Ergebnis"], "TESTLAUF")
        self.assertIn("Nicht angelegt (Testlauf)", result["log_row"]["Hinweis"])
        self.assertIn("Microsoft 365 Business Standard", result["log_row"]["Hinweis"])

    def test_live_success_calls_payload_create_and_license_assignment(self):
        seen = {}

        def build_payload(**kwargs):
            seen["payload_args"] = kwargs
            return {"payload": True}

        def create_user(payload):
            seen["create_payload"] = payload
            return {"id": "user-1"}

        def assign_user_licenses(user_id, sku_ids):
            seen["assign_args"] = (user_id, sku_ids)

        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=["Microsoft 365 Business Standard"],
            selected_sku_ids=["sku-1"],
            build_payload=build_payload,
            create_user=create_user,
            assign_user_licenses=assign_user_licenses,
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["log_row"]["Ergebnis"], "ANGELEGT")
        self.assertEqual(result["log_row"]["Hinweis"], "Lizenzen zugewiesen")
        self.assertEqual(
            seen["payload_args"],
            {
                "display_name": "Max Mustermann",
                "upn": "max.mustermann@example.com",
                "mail_nick": "max.mustermann",
                "given": "Max",
                "surname": "Mustermann",
                "password": "Secret123!",
            },
        )
        self.assertEqual(seen["create_payload"], {"payload": True})
        self.assertEqual(seen["assign_args"], ("user-1", ["sku-1"]))

    def test_live_success_without_licenses_stays_success(self):
        assign_calls = []

        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=[],
            selected_sku_ids=[],
            build_payload=lambda **kwargs: {"payload": True},
            create_user=lambda payload: {"id": "user-1"},
            assign_user_licenses=lambda user_id, sku_ids: assign_calls.append((user_id, sku_ids)),
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["log_row"]["Ergebnis"], "ANGELEGT")
        self.assertEqual(result["log_row"]["Hinweis"], "")
        self.assertEqual(assign_calls, [])

    def test_create_user_failure_becomes_error_result(self):
        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=[],
            selected_sku_ids=["sku-1"],
            build_payload=lambda **kwargs: {"payload": True},
            create_user=lambda payload: (_ for _ in ()).throw(RuntimeError("Graph down")),
            assign_user_licenses=lambda user_id, sku_ids: None,
        )

        self.assertEqual(result["outcome"], "error")
        self.assertEqual(result["log_row"]["Ergebnis"], "FEHLER")
        self.assertEqual(result["log_row"]["Hinweis"], "Graph down")

    def test_license_assignment_failure_becomes_partial_success(self):
        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=["Microsoft 365 Business Standard"],
            selected_sku_ids=["sku-1"],
            build_payload=lambda **kwargs: {"payload": True},
            create_user=lambda payload: {"id": "user-1"},
            assign_user_licenses=lambda user_id, sku_ids: (_ for _ in ()).throw(RuntimeError("license boom")),
        )

        self.assertEqual(result["outcome"], "partial_success")
        self.assertTrue(result["user_created"])
        self.assertTrue(result["license_assignment_failed"])
        self.assertEqual(result["log_row"]["Ergebnis"], "TEILERFOLG")
        self.assertIn("Lizenzzuweisung fehlgeschlagen: license boom", result["log_row"]["Hinweis"])

    def test_live_mode_guard_becomes_error_result(self):
        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=False,
            password="Secret123!",
            selected_license_labels=[],
            selected_sku_ids=[],
            build_payload=lambda **kwargs: {"payload": True},
            create_user=lambda payload: {"id": "user-1"},
            assign_user_licenses=lambda user_id, sku_ids: None,
        )

        self.assertEqual(result["outcome"], "error")
        self.assertEqual(result["log_row"]["Ergebnis"], "FEHLER")
        self.assertIn("deaktiviert", result["log_row"]["Hinweis"])

    def test_missing_user_id_after_creation_does_not_become_partial_success(self):
        assign_calls = []

        result = execute_plan_row(
            ready_row(),
            dry_run=False,
            enable_live_user_creation=True,
            password="Secret123!",
            selected_license_labels=["Microsoft 365 Business Standard"],
            selected_sku_ids=["sku-1"],
            build_payload=lambda **kwargs: {"payload": True},
            create_user=lambda payload: {},
            assign_user_licenses=lambda user_id, sku_ids: assign_calls.append((user_id, sku_ids)),
        )

        self.assertEqual(result["outcome"], "success")
        self.assertFalse(result["license_assignment_failed"])
        self.assertEqual(result["log_row"]["Ergebnis"], "ANGELEGT")
        self.assertEqual(assign_calls, [])


if __name__ == "__main__":
    unittest.main()
