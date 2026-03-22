import unittest
from unittest.mock import Mock, patch

from microsoft_bulk_user.graph_ops import (
    GraphConfig,
    _escape_odata_string,
    assign_licenses,
    create_user_graph,
    get_access_token,
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
            {"value": [{"skuPartNumber": "FLOW_FREE", "skuId": "sku-1"}, {"skuPartNumber": "POWER_BI_STANDARD"}]},
        )
        self.assertEqual(get_subscribed_sku_map("token"), {"FLOW_FREE": "sku-1"})

    @patch("microsoft_bulk_user.graph_ops.requests.get")
    def test_get_subscribed_sku_map_raises_on_bad_response(self, mock_get):
        mock_get.return_value = response(500, text="boom")
        with self.assertRaisesRegex(RuntimeError, "subscribedSkus"):
            get_subscribed_sku_map("token")

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
