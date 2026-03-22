import unittest
from unittest.mock import patch

import requests

from shared.config import ConfigError
from shared.hubspot import (
    build_headers,
    fetch_property_options,
    search_contacts,
    search_contacts_with_auto_split,
)


class MappingLike:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", reason="Bad Request", json_exception=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.reason = reason
        self._json_exception = json_exception

    def json(self):
        if self._json_exception is not None:
            raise self._json_exception
        return self._json_data


class BuildHeadersTests(unittest.TestCase):
    def test_uses_explicit_token_and_trims_whitespace(self):
        headers = build_headers(token="  direct-token  ")
        self.assertEqual(headers["Authorization"], "Bearer direct-token")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_can_skip_content_type(self):
        headers = build_headers(token="direct-token", include_content_type=False)
        self.assertEqual(headers, {"Authorization": "Bearer direct-token"})

    def test_uses_token_from_mapping_like_secrets(self):
        secrets = MappingLike({"HUBSPOT_TOKEN": "secret-token"})
        headers = build_headers(secrets=secrets)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")

    def test_whitespace_token_falls_back_to_environment(self):
        headers = build_headers(token="   ", environ={"HUBSPOT_ACCESS_TOKEN": "env-token"})
        self.assertEqual(headers["Authorization"], "Bearer env-token")

    def test_missing_token_raises_config_error(self):
        with self.assertRaises(ConfigError):
            build_headers()


class FetchPropertyOptionsTests(unittest.TestCase):
    @patch("shared.hubspot.requests.request")
    def test_fetch_property_options_parses_visible_pairs(self, mock_request):
        mock_request.return_value = FakeResponse(
            status_code=200,
            json_data={
                "options": [
                    {"label": "Visible", "value": "visible"},
                    {"label": "Hidden", "value": "hidden", "hidden": True},
                    {"label": "", "value": "blank-label"},
                    {"label": "BlankValue", "value": " "},
                ]
            },
        )

        options = fetch_property_options("historie", token="abc")

        self.assertEqual(options, [("Visible", "visible")])
        _, args, kwargs = mock_request.mock_calls[0]
        self.assertEqual(args[0], "GET")
        self.assertIn("/crm/v3/properties/contacts/historie", args[1])
        self.assertNotIn("Content-Type", kwargs["headers"])

    @patch("shared.hubspot.requests.request")
    def test_fetch_property_options_uses_shared_config_token_resolution(self, mock_request):
        mock_request.return_value = FakeResponse(status_code=200, json_data={"options": []})

        fetch_property_options("historie", secrets={"HUBSPOT_TOKEN": "secret-token"})

        _, _, kwargs = mock_request.mock_calls[0]
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")

    @patch("shared.hubspot.requests.request")
    def test_fetch_property_options_raises_http_error_on_bad_response(self, mock_request):
        response = FakeResponse(
            status_code=403,
            text="forbidden",
            json_exception=ValueError("no json"),
        )
        mock_request.return_value = response

        with self.assertRaises(requests.HTTPError) as ctx:
            fetch_property_options("historie", token="abc")

        self.assertIs(ctx.exception.response, response)


class SearchContactsTests(unittest.TestCase):
    @patch("shared.hubspot.time.sleep")
    @patch("shared.hubspot.requests.request")
    def test_search_contacts_pages_results(self, mock_request, _mock_sleep):
        mock_request.side_effect = [
            FakeResponse(
                status_code=200,
                json_data={"results": [{"id": "1"}], "paging": {"next": {"after": "A"}}},
            ),
            FakeResponse(
                status_code=200,
                json_data={"results": [{"id": "2"}]},
            ),
        ]

        results = search_contacts(
            [{"filters": [{"propertyName": "historie", "operator": "EQ", "value": "X"}]}],
            ["firstname"],
            token="abc",
        )

        self.assertEqual([item["id"] for item in results], ["1", "2"])
        first_payload = mock_request.call_args_list[0].kwargs["json"]
        second_payload = mock_request.call_args_list[1].kwargs["json"]
        self.assertEqual(first_payload["limit"], 100)
        self.assertEqual(second_payload["after"], "A")

    @patch("shared.hubspot.time.sleep")
    @patch("shared.hubspot.requests.request")
    def test_search_contacts_honors_max_results(self, mock_request, _mock_sleep):
        mock_request.return_value = FakeResponse(
            status_code=200,
            json_data={"results": [{"id": "1"}, {"id": "2"}], "paging": {"next": {"after": "A"}}},
        )

        results = search_contacts(
            [{"filters": [{"propertyName": "historie", "operator": "EQ", "value": "X"}]}],
            ["firstname"],
            token="abc",
            max_results=2,
        )

        self.assertEqual([item["id"] for item in results], ["1", "2"])
        self.assertEqual(mock_request.call_count, 1)
        self.assertEqual(mock_request.call_args.kwargs["json"]["limit"], 2)

    @patch("shared.hubspot.requests.request")
    def test_search_contacts_with_auto_split_deduplicates_ids(self, mock_request):
        def side_effect(method, url, **kwargs):
            payload = kwargs["json"]
            filter_groups = payload.get("filterGroups", [])
            values = [group["filters"][0]["value"] for group in filter_groups]
            if len(filter_groups) == 4:
                return FakeResponse(
                    status_code=400,
                    text="too many groups",
                    json_exception=ValueError("no json"),
                )
            if values == ["A", "B"]:
                return FakeResponse(status_code=200, json_data={"results": [{"id": "1"}, {"id": "2"}]})
            if values == ["C", "D"]:
                return FakeResponse(status_code=200, json_data={"results": [{"id": "2"}, {"id": "3"}]})
            raise AssertionError(f"Unexpected payload: {payload}")

        mock_request.side_effect = side_effect

        results = search_contacts_with_auto_split(
            [
                {"filters": [{"propertyName": "historie", "operator": "EQ", "value": "A"}]},
                {"filters": [{"propertyName": "historie", "operator": "EQ", "value": "B"}]},
                {"filters": [{"propertyName": "historie", "operator": "EQ", "value": "C"}]},
                {"filters": [{"propertyName": "historie", "operator": "EQ", "value": "D"}]},
            ],
            ["firstname"],
            token="abc",
        )

        self.assertEqual([item["id"] for item in results], ["1", "2", "3"])

    @patch("shared.hubspot.requests.request")
    def test_search_contacts_with_auto_split_reraises_single_group_400(self, mock_request):
        response = FakeResponse(
            status_code=400,
            text="bad request",
            json_exception=ValueError("no json"),
        )
        mock_request.return_value = response

        with self.assertRaises(requests.HTTPError) as ctx:
            search_contacts_with_auto_split(
                [{"filters": [{"propertyName": "historie", "operator": "EQ", "value": "A"}]}],
                ["firstname"],
                token="abc",
            )

        self.assertIs(ctx.exception.response, response)


if __name__ == "__main__":
    unittest.main()
