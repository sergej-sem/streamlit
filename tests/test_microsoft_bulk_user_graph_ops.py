import unittest
from unittest.mock import Mock, patch

from microsoft_bulk_user.graph_ops import (
    GraphConfig,
    _escape_odata_string,
    assign_licenses,
    create_user_graph,
    delete_user_graph,
    evaluate_license_selection,
    get_access_token,
    get_subscribed_sku_inventory,
    get_subscribed_sku_map,
    name_exists,
    upn_exists,
    user_payload,
)


def response(status_code, json_data=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json.return_value = json_data or {}
    return mock_response


class GraphOpsHelpersTests(unittest.TestCase):
    def test_escape_odata_string_doubles_single_quotes(self):
        self.assertEqual(_escape_odata_string("O'Neil"), "O''Neil")
        self.assertEqual(_escape_odata_string(""), "")

    def test_user_payload_uses_defaults(self):
        payload = user_payload(
            display_name="Max Mustermann",
            upn="max@example.com",
            mail_nick="max",
            given="Max",
            surname="Mustermann",
            password="Secret123!",
        )
        self.assertEqual(payload["usageLocation"], "DE")
        self.assertEqual(payload["passwordProfile"]["forceChangePasswordNextSignIn"], False)
        self.assertEqual(payload["passwordPolicies"], "DisablePasswordExpiration")

    def test_user_payload_can_override_password_flags(self):
        payload = user_payload(
            display_name="Max Mustermann",
            upn="max@example.com",
            mail_nick="max",
            given="Max",
            surname="Mustermann",
            password="Secret123!",
            force_change_password=True,
            disable_password_expiration=False,
        )
        self.assertEqual(payload["passwordProfile"]["forceChangePasswordNextSignIn"], True)
        self.assertNotIn("passwordPolicies", payload)

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_get_subscribed_sku_map_parses_mapping(self, mock_get):
        mock_get.return_value = response(
            200,
            {
                "value": [
                    {
                        "skuPartNumber": "FLOW_FREE",
                        "skuId": "sku-1",
                        "consumedUnits": 2,
                        "prepaidUnits": {"enabled": 5},
                        "capabilityStatus": "Enabled",
                        "appliesTo": "User",
                    },
                    {"skuPartNumber": "POWER_BI_STANDARD"},
                ]
            },
        )
        self.assertEqual(get_subscribed_sku_map("token"), {"FLOW_FREE": "sku-1"})

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_get_subscribed_sku_map_raises_on_bad_response(self, mock_get):
        mock_get.return_value = response(500, text="boom")
        with self.assertRaisesRegex(RuntimeError, "subscribedSkus"):
            get_subscribed_sku_map("token")

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_get_subscribed_sku_inventory_parses_available_units(self, mock_get):
        mock_get.return_value = response(
            200,
            {
                "value": [
                    {
                        "skuPartNumber": "O365_BUSINESS_PREMIUM",
                        "skuId": "sku-1",
                        "consumedUnits": 7,
                        "prepaidUnits": {"enabled": 10},
                        "capabilityStatus": "Enabled",
                        "appliesTo": "User",
                    },
                    {
                        "skuPartNumber": "POWER_BI_STANDARD",
                        "skuId": "sku-2",
                        "consumedUnits": 1,
                        "prepaidUnits": {"enabled": 50},
                        "capabilityStatus": "LockedOut",
                        "appliesTo": "User",
                    },
                ]
            },
        )

        inventory = get_subscribed_sku_inventory("token")

        self.assertEqual(inventory["O365_BUSINESS_PREMIUM"]["available_units"], 3)
        self.assertEqual(inventory["O365_BUSINESS_PREMIUM"]["enabled_units"], 10)
        self.assertEqual(inventory["O365_BUSINESS_PREMIUM"]["consumed_units"], 7)
        self.assertEqual(inventory["POWER_BI_STANDARD"]["available_units"], 0)

    def test_evaluate_license_selection_reports_missing_and_insufficient_parts(self):
        inventory = {
            "O365_BUSINESS_PREMIUM": {
                "sku_id": "sku-1",
                "available_units": 2,
                "consumed_units": 8,
                "enabled_units": 10,
                "capability_status": "Enabled",
                "applies_to": "User",
            }
        }

        result = evaluate_license_selection(
            ["O365_BUSINESS_PREMIUM", "POWER_BI_STANDARD"],
            inventory,
            required_units=3,
        )

        self.assertEqual(result["selected_sku_ids"], ["sku-1"])
        self.assertEqual(result["missing_parts"], ["POWER_BI_STANDARD"])
        self.assertEqual(
            result["insufficient_parts"],
            [
                {
                    "part": "O365_BUSINESS_PREMIUM",
                    "available_units": 2,
                    "required_units": 3,
                    "capability_status": "Enabled",
                    "applies_to": "User",
                }
            ],
        )

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_upn_exists_returns_true_when_value_present(self, mock_get):
        mock_get.return_value = response(200, {"value": [{"id": "1"}]})
        self.assertTrue(upn_exists("max@example.com", "token"))

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_upn_exists_returns_false_when_empty(self, mock_get):
        mock_get.return_value = response(200, {"value": []})
        self.assertFalse(upn_exists("max@example.com", "token"))

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_upn_exists_raises_on_bad_response(self, mock_get):
        mock_get.return_value = response(503, text="nope")
        with self.assertRaisesRegex(RuntimeError, "UPN"):
            upn_exists("max@example.com", "token")

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_name_exists_uses_given_and_surname_when_supported(self, mock_get):
        mock_get.return_value = response(200, {"value": [{"id": "1"}]})
        self.assertTrue(name_exists("Max", "Mustermann", "token"))

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_name_exists_falls_back_to_display_name(self, mock_get):
        mock_get.side_effect = [
            response(400, text="unsupported"),
            response(200, {"value": [{"id": "1"}]}),
        ]
        self.assertTrue(name_exists("Max", "Mustermann", "token"))
        self.assertEqual(mock_get.call_count, 2)

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_name_exists_raises_when_fallback_fails(self, mock_get):
        mock_get.side_effect = [
            response(501, text="unsupported"),
            response(500, text="still bad"),
        ]
        with self.assertRaisesRegex(RuntimeError, "displayName Fallback"):
            name_exists("Max", "Mustermann", "token")

    @patch("microsoft_bulk_user.graph_ops.requests.post")
    def test_create_user_graph_returns_json_on_success(self, mock_post):
        mock_post.return_value = response(201, {"id": "user-1"})
        self.assertEqual(create_user_graph({"a": 1}, "token"), {"id": "user-1"})

    @patch("microsoft_bulk_user.graph_ops.requests.post")
    def test_create_user_graph_raises_on_error(self, mock_post):
        mock_post.return_value = response(400, text="bad")
        with self.assertRaisesRegex(RuntimeError, "Benutzer anlegen fehlgeschlagen"):
            create_user_graph({"a": 1}, "token")

    @patch("microsoft_bulk_user.graph_ops.requests.post")
    def test_assign_licenses_noop_for_empty_skus(self, mock_post):
        assign_licenses("user-1", [], "token")
        mock_post.assert_not_called()

    @patch("microsoft_bulk_user.graph_ops.requests.post")
    def test_assign_licenses_raises_on_error(self, mock_post):
        mock_post.return_value = response(400, text="bad")
        with self.assertRaisesRegex(RuntimeError, "Lizenzzuweisung fehlgeschlagen"):
            assign_licenses("user-1", ["sku-1"], "token")

    @patch("microsoft_bulk_user.graph_ops.requests.delete")
    def test_delete_user_graph_succeeds_on_204(self, mock_delete):
        mock_delete.return_value = response(204)
        delete_user_graph("user-1", "token")
        mock_delete.assert_called_once()

    @patch("microsoft_bulk_user.graph_ops.requests.delete")
    def test_delete_user_graph_raises_on_error(self, mock_delete):
        mock_delete.return_value = response(400, text="bad")
        with self.assertRaisesRegex(RuntimeError, "Benutzer löschen fehlgeschlagen"):
            delete_user_graph("user-1", "token")

    def test_get_access_token_uses_silent_result(self):
        app = Mock()
        app.acquire_token_silent.return_value = {"access_token": "abc"}
        cfg = GraphConfig("tenant", "client", "secret")
        self.assertEqual(get_access_token(cfg, app=app), "abc")
        app.acquire_token_for_client.assert_not_called()

    def test_get_access_token_falls_back_to_client_credentials(self):
        app = Mock()
        app.acquire_token_silent.return_value = None
        app.acquire_token_for_client.return_value = {"access_token": "xyz"}
        cfg = GraphConfig("tenant", "client", "secret")
        self.assertEqual(get_access_token(cfg, app=app), "xyz")
        app.acquire_token_for_client.assert_called_once()

    def test_get_access_token_raises_when_missing_access_token(self):
        app = Mock()
        app.acquire_token_silent.return_value = None
        app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "client secret invalid",
        }
        cfg = GraphConfig("tenant", "client", "secret")
        with self.assertRaisesRegex(RuntimeError, "Token-Fehler: invalid_client - client secret invalid"):
            get_access_token(cfg, app=app)


if __name__ == "__main__":
    unittest.main()
