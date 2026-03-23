import unittest
from unittest.mock import patch

from badgegen.hubspot_search import (
    P_COMPANY,
    P_FIRSTNAME,
    P_HISTORIE,
    P_JOBTITLE,
    P_LASTNAME,
    SEARCH_PROPERTIES,
    _apply_local_contains_filters,
    _rows_from_contacts,
    search_compiled_groups,
    search_group,
)


class ApplyLocalContainsFiltersTests(unittest.TestCase):
    def test_filters_case_insensitively_and_ignores_invalid_conditions(self) -> None:
        contacts = [
            {
                "id": "1",
                "properties": {
                    P_FIRSTNAME: "Alice",
                    P_COMPANY: "Acme GmbH",
                },
            },
            {
                "id": "2",
                "properties": {
                    P_FIRSTNAME: "Bob",
                    P_COMPANY: "Beta AG",
                },
            },
        ]

        local_contains = [
            {"propertyName": P_COMPANY, "value": "acme"},
            {"propertyName": P_FIRSTNAME, "value": ""},
            {"propertyName": "", "value": "ignored"},
            {"value": "ignored"},
        ]

        result = _apply_local_contains_filters(contacts, local_contains)

        self.assertEqual(["1"], [contact["id"] for contact in result])


class SearchGroupTests(unittest.TestCase):
    @patch("badgegen.hubspot_search.search_contacts_auto_split")
    def test_search_group_uses_default_properties_and_filter_groups(self, mock_search) -> None:
        server_filters = [{"propertyName": P_HISTORIE, "operator": "EQ", "value": "26DOR"}]
        contacts = [{"id": "1", "properties": {P_FIRSTNAME: "Alice"}}]
        mock_search.return_value = contacts

        result = search_group(
            "token-123",
            server_filters=server_filters,
            local_contains=[],
        )

        mock_search.assert_called_once_with(
            "token-123",
            filter_groups=[{"filters": server_filters}],
            properties=SEARCH_PROPERTIES,
        )
        self.assertEqual(contacts, result)

    @patch("badgegen.hubspot_search.search_contacts_auto_split")
    def test_search_group_applies_local_contains_filters(self, mock_search) -> None:
        mock_search.return_value = [
            {"id": "1", "properties": {P_COMPANY: "Acme GmbH"}},
            {"id": "2", "properties": {P_COMPANY: "Beta AG"}},
        ]

        result = search_group(
            "token-123",
            server_filters=[],
            local_contains=[{"propertyName": P_COMPANY, "value": "acme"}],
        )

        self.assertEqual(["1"], [contact["id"] for contact in result])


class RowsFromContactsTests(unittest.TestCase):
    def test_rows_from_contacts_fills_missing_properties_with_empty_strings(self) -> None:
        rows = _rows_from_contacts(
            [
                {
                    "id": "1",
                    "properties": {
                        P_FIRSTNAME: " Alice ",
                        P_LASTNAME: " Brown ",
                    },
                }
            ]
        )

        self.assertEqual(
            [
                {
                    "id": "1",
                    "firstname": "Alice",
                    "lastname": "Brown",
                    "company": "",
                    "jobtitle": "",
                    "historie": "",
                }
            ],
            rows,
        )


class SearchCompiledGroupsTests(unittest.TestCase):
    @patch("badgegen.hubspot_search.search_group")
    def test_search_compiled_groups_skips_local_only_groups_and_dedupes_by_id(self, mock_search_group) -> None:
        mock_search_group.side_effect = [
            [
                {
                    "id": "1",
                    "properties": {
                        P_FIRSTNAME: "Alice",
                        P_LASTNAME: "One",
                    },
                },
                {
                    "id": "2",
                    "properties": {
                        P_COMPANY: "Beta AG",
                        P_JOBTITLE: "Manager",
                    },
                },
            ],
            [
                {
                    "id": "1",
                    "properties": {
                        P_FIRSTNAME: "Alicia",
                        P_COMPANY: "Acme GmbH",
                        P_HISTORIE: "26DOR",
                    },
                },
                {
                    "properties": {
                        P_FIRSTNAME: "No Id",
                    },
                },
            ],
        ]

        compiled_groups = [
            {
                "server_filters": [],
                "local_contains": [{"propertyName": P_COMPANY, "value": "acme"}],
            },
            {
                "server_filters": [{"propertyName": P_HISTORIE, "operator": "EQ", "value": "26DOR"}],
                "local_contains": [],
            },
            {
                "server_filters": [{"propertyName": P_COMPANY, "operator": "HAS_PROPERTY"}],
                "local_contains": [],
            },
        ]

        result = search_compiled_groups("token-123", compiled_groups)

        self.assertEqual(2, mock_search_group.call_count)
        self.assertEqual(
            ["id", "firstname", "lastname", "company", "jobtitle", "historie"],
            list(result.columns),
        )

        rows_by_id = {row["id"]: row for row in result.to_dict("records")}
        self.assertEqual(
            {
                "id": "1",
                "firstname": "Alicia",
                "lastname": "",
                "company": "Acme GmbH",
                "jobtitle": "",
                "historie": "26DOR",
            },
            rows_by_id["1"],
        )
        self.assertEqual(
            {
                "id": "2",
                "firstname": "",
                "lastname": "",
                "company": "Beta AG",
                "jobtitle": "Manager",
                "historie": "",
            },
            rows_by_id["2"],
        )


if __name__ == "__main__":
    unittest.main()
