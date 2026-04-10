import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

if "msal" not in sys.modules:
    fake_msal = types.ModuleType("msal")
    fake_msal.ConfidentialClientApplication = object
    sys.modules["msal"] = fake_msal

from sponsor_deadline_mails.core import GeneratedMail
from sponsor_deadline_mails.graph import (
    GraphDraftConfig,
    _get_access_token,
    create_graph_drafts,
)


def _make_config(**overrides) -> GraphDraftConfig:
    defaults = dict(
        tenant_id="tenant-id",
        client_id="client-id",
        client_secret="client-secret",
        mailbox_user="sender@example.com",
    )
    defaults.update(overrides)
    return GraphDraftConfig(**defaults)


def _make_mail(**overrides) -> GeneratedMail:
    defaults = dict(
        row_number=1,
        sponsor_name="Acme GmbH",
        language="DE",
        package="Gold",
        to_email="sponsor@example.com",
        cc_email="",
        subject="Test Betreff",
        html_body="<p>Hallo</p>",
        html_file_name="001_acme.html",
        green_count=2,
        red_count=1,
        yellow_count=0,
        white_count=0,
    )
    defaults.update(overrides)
    return GeneratedMail(**defaults)


class GetAccessTokenTests(unittest.TestCase):
    @patch("sponsor_deadline_mails.graph.msal.ConfidentialClientApplication")
    def test_missing_token_raises_friendly_runtime_error(self, mock_app_cls):
        app = MagicMock()
        app.acquire_token_silent.return_value = None
        app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "secret invalid",
        }
        mock_app_cls.return_value = app

        with self.assertRaises(RuntimeError) as ctx:
            _get_access_token(_make_config())

        self.assertIn("Microsoft Graph", str(ctx.exception))
        self.assertIn("Technischer Hinweis:", str(ctx.exception))


class CreateGraphDraftsTests(unittest.TestCase):
    @patch("sponsor_deadline_mails.graph.requests.post")
    @patch("sponsor_deadline_mails.graph._get_access_token", return_value="token")
    def test_request_exception_is_mapped_to_friendly_record_detail(self, mock_token, mock_post):
        mock_post.side_effect = Exception("bad gateway")

        results = create_graph_drafts([_make_mail()], _make_config())

        self.assertEqual(1, len(results))
        self.assertEqual("error", results[0].result)
        self.assertIn("Microsoft 365", results[0].details)
        self.assertIn("Technischer Hinweis:", results[0].details)

    @patch("sponsor_deadline_mails.graph.requests.post")
    @patch("sponsor_deadline_mails.graph._get_access_token", return_value="token")
    def test_non_201_response_is_mapped_to_friendly_record_detail(self, mock_token, mock_post):
        response = MagicMock()
        response.status_code = 500
        response.reason = "Server Error"
        response.json.return_value = {"error": {"message": "failed"}}
        mock_post.return_value = response

        results = create_graph_drafts([_make_mail()], _make_config())

        self.assertEqual("error", results[0].result)
        self.assertIn("Microsoft 365", results[0].details)
        self.assertIn("Technischer Hinweis:", results[0].details)


if __name__ == "__main__":
    unittest.main()
