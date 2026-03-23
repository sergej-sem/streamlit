from __future__ import annotations

import unittest
from unittest.mock import patch

from excel_druckbereit_generator.hubspot_fetch import (
    HISTORIE_PROPERTY,
    HS_PROPERTIES,
    fetch_contacts_by_historien,
    load_historie_options,
)


class LoadHistorieOptionsTests(unittest.TestCase):
    @patch("excel_druckbereit_generator.hubspot_fetch.fetch_property_options")
    def test_load_historie_options_uses_shared_hubspot_helper(self, mock_fetch_property_options) -> None:
        mock_fetch_property_options.return_value = [("Label", "value")]

        result = load_historie_options(token="secret-token")

        self.assertEqual(result, [("Label", "value")])
        mock_fetch_property_options.assert_called_once_with(
            HISTORIE_PROPERTY,
            token="secret-token",
            object_type="contacts",
        )


class FetchContactsByHistorienTests(unittest.TestCase):
    @patch("excel_druckbereit_generator.hubspot_fetch.search_contacts_with_auto_split")
    def test_fetch_contacts_by_historien_returns_empty_list_for_empty_normalized_input(self, mock_search) -> None:
        result = fetch_contacts_by_historien([" ", "", "\n"], token="abc")

        self.assertEqual(result, [])
        mock_search.assert_not_called()

    @patch("excel_druckbereit_generator.hubspot_fetch.search_contacts_with_auto_split")
    def test_fetch_contacts_by_historien_trims_and_deduplicates_input_preserving_order(self, mock_search) -> None:
        mock_search.return_value = [{"id": "1"}]

        fetch_contacts_by_historien(["  A  ", "B", "A", "  ", "B", "C  "], token="abc")

        mock_search.assert_called_once()
        filter_groups, properties = mock_search.call_args.args[:2]
        self.assertEqual(
            [group["filters"][0]["value"] for group in filter_groups],
            ["A", "B", "C"],
        )
        self.assertEqual(properties, HS_PROPERTIES)
        self.assertEqual(mock_search.call_args.kwargs["token"], "abc")

    @patch("excel_druckbereit_generator.hubspot_fetch.search_contacts_with_auto_split")
    def test_fetch_contacts_by_historien_builds_expected_filter_groups(self, mock_search) -> None:
        mock_search.return_value = [{"id": "1"}]

        fetch_contacts_by_historien(["26DOR_TN", "26DOR_REF"], token="abc")

        filter_groups, properties = mock_search.call_args.args[:2]
        self.assertEqual(len(filter_groups), 2)
        self.assertEqual(properties, HS_PROPERTIES)
        self.assertEqual(
            filter_groups,
            [
                {
                    "filters": [
                        {
                            "propertyName": HISTORIE_PROPERTY,
                            "operator": "CONTAINS_TOKEN",
                            "value": "26DOR_TN",
                        }
                    ]
                },
                {
                    "filters": [
                        {
                            "propertyName": HISTORIE_PROPERTY,
                            "operator": "CONTAINS_TOKEN",
                            "value": "26DOR_REF",
                        }
                    ]
                },
            ],
        )

    @patch("excel_druckbereit_generator.hubspot_fetch.search_contacts_with_auto_split")
    def test_fetch_contacts_by_historien_batches_requests(self, mock_search) -> None:
        mock_search.return_value = []

        fetch_contacts_by_historien(
            ["A", "B", "C"],
            token="abc",
            initial_filtergroups_per_request=2,
        )

        self.assertEqual(mock_search.call_count, 2)
        first_groups, _ = mock_search.call_args_list[0].args[:2]
        second_groups, _ = mock_search.call_args_list[1].args[:2]
        self.assertEqual([group["filters"][0]["value"] for group in first_groups], ["A", "B"])
        self.assertEqual([group["filters"][0]["value"] for group in second_groups], ["C"])

    @patch("excel_druckbereit_generator.hubspot_fetch.search_contacts_with_auto_split")
    def test_fetch_contacts_by_historien_deduplicates_contacts_by_id(self, mock_search) -> None:
        mock_search.side_effect = [
            [{"id": "1", "name": "first"}, {"id": "2", "name": "second"}],
            [{"id": "1", "name": "updated"}, {"id": "3", "name": "third"}, {"name": "no-id"}],
        ]

        result = fetch_contacts_by_historien(
            ["A", "B", "C"],
            token="abc",
            initial_filtergroups_per_request=2,
        )

        self.assertEqual(
            result,
            [
                {"id": "1", "name": "updated"},
                {"id": "2", "name": "second"},
                {"id": "3", "name": "third"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
