import sys
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def _load_filter_builder_under_fake_streamlit():
    module_name = "_tests_badgegen_filter_builder"
    module_path = Path(__file__).resolve().parents[1] / "badgegen" / "filter_builder.py"
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Konnte badgegen.filter_builder nicht laden.")

    fake_streamlit = ModuleType("streamlit")
    fake_streamlit.cache_data = lambda *args, **kwargs: (lambda func: func)
    fake_streamlit.session_state = {}

    previous_streamlit = sys.modules.get("streamlit")
    previous_isolated = sys.modules.get(module_name)
    try:
        sys.modules["streamlit"] = fake_streamlit
        isolated_module = module_from_spec(spec)
        sys.modules[module_name] = isolated_module
        spec.loader.exec_module(isolated_module)
        return isolated_module
    finally:
        sys.modules.pop(module_name, None)
        if previous_isolated is not None:
            sys.modules[module_name] = previous_isolated
        if previous_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = previous_streamlit


_filter_builder = _load_filter_builder_under_fake_streamlit()

P_COMPANY = _filter_builder.P_COMPANY
P_FIRSTNAME = _filter_builder.P_FIRSTNAME
P_HISTORIE = _filter_builder.P_HISTORIE
P_JOBTITLE = _filter_builder.P_JOBTITLE
P_LASTNAME = _filter_builder.P_LASTNAME
_as_list_values = _filter_builder._as_list_values
_build_context_filter_groups_for_group = _filter_builder._build_context_filter_groups_for_group
build_compiled_groups_from_model = _filter_builder.build_compiled_groups_from_model


class AsListValuesTests(unittest.TestCase):
    def test_trims_dedupes_and_removes_empty_list_entries(self) -> None:
        self.assertEqual(
            ["Alice", "Bob"],
            _as_list_values([" Alice ", "", "Bob", "Alice", "  "]),
        )

    def test_handles_scalar_values_and_empty_inputs(self) -> None:
        self.assertEqual(["Acme"], _as_list_values("  Acme  "))
        self.assertEqual([], _as_list_values(""))
        self.assertEqual([], _as_list_values(None))


class BuildContextFilterGroupsForGroupTests(unittest.TestCase):
    def test_excludes_active_filter_and_expands_multi_values(self) -> None:
        group_filters = [
            {"id": "f1", "property": P_FIRSTNAME, "op": "CONTAINS_TOKEN", "value": "Alice"},
            {"id": "f2", "property": P_COMPANY, "op": "EQ", "value": " Acme GmbH "},
            {"id": "f3", "property": P_HISTORIE, "op": "EQ", "value": ["26DOR_TN", "26DOR_REF"]},
            {"id": "f4", "property": "", "op": "EQ", "value": "ignored"},
            {"id": "f5", "property": P_LASTNAME, "op": "", "value": "ignored"},
            {"id": "f6", "property": P_JOBTITLE, "op": "EQ", "value": ""},
        ]

        result = _build_context_filter_groups_for_group(group_filters, exclude_filter_id="f1")

        self.assertEqual(
            [
                {
                    "filters": [
                        {"propertyName": P_COMPANY, "operator": "EQ", "value": "Acme GmbH"},
                        {"propertyName": P_HISTORIE, "operator": "EQ", "value": "26DOR_TN"},
                    ]
                },
                {
                    "filters": [
                        {"propertyName": P_COMPANY, "operator": "EQ", "value": "Acme GmbH"},
                        {"propertyName": P_HISTORIE, "operator": "EQ", "value": "26DOR_REF"},
                    ]
                },
            ],
            result,
        )

    def test_returns_empty_when_group_limit_would_be_exceeded(self) -> None:
        group_filters = [
            {"id": "f1", "property": P_COMPANY, "op": "EQ", "value": ["A", "B"]},
            {"id": "f2", "property": P_HISTORIE, "op": "EQ", "value": ["1", "2"]},
        ]

        with patch.object(_filter_builder, "SUGGEST_MAX_FILTERGROUPS", 3):
            result = _build_context_filter_groups_for_group(group_filters, exclude_filter_id="missing")

        self.assertEqual([], result)


class BuildCompiledGroupsFromModelTests(unittest.TestCase):
    def test_builds_compiled_groups_with_server_filters_and_local_contains(self) -> None:
        model = [
            {
                "id": "g1",
                "filters": [
                    {"id": "f1", "property": P_HISTORIE, "op": "CONTAINS_TOKEN", "value": ["26DOR_TN", "26DOR_REF"]},
                    {"id": "f2", "property": P_FIRSTNAME, "op": "CONTAINS_TOKEN", "value": " Alice "},
                    {"id": "f3", "property": P_COMPANY, "op": "EQ", "value": " Acme GmbH "},
                    {"id": "f4", "property": P_LASTNAME, "op": "EQ", "value": ""},
                    {"id": "f5", "property": "", "op": "EQ", "value": "ignored"},
                ],
            },
            {
                "id": "g2",
                "filters": [
                    {"id": "f6", "property": P_HISTORIE, "op": "EQ", "value": ["26DOR_BEO"]},
                    {"id": "f7", "property": P_JOBTITLE, "op": "CONTAINS_TOKEN", "value": "Manager"},
                ],
            },
            {
                "id": "g3",
                "filters": [
                    {"id": "f8", "property": P_FIRSTNAME, "op": "CONTAINS_TOKEN", "value": "   "},
                ],
            },
        ]

        result = build_compiled_groups_from_model(model)

        self.assertEqual(
            [
                {
                    "id": "g1",
                    "server_filters": [
                        {"propertyName": P_COMPANY, "operator": "EQ", "value": "Acme GmbH"},
                        {"propertyName": P_HISTORIE, "operator": "CONTAINS_TOKEN", "value": "26DOR_TN"},
                    ],
                    "local_contains": [{"propertyName": P_FIRSTNAME, "value": "Alice"}],
                },
                {
                    "id": "g1",
                    "server_filters": [
                        {"propertyName": P_COMPANY, "operator": "EQ", "value": "Acme GmbH"},
                        {"propertyName": P_HISTORIE, "operator": "CONTAINS_TOKEN", "value": "26DOR_REF"},
                    ],
                    "local_contains": [{"propertyName": P_FIRSTNAME, "value": "Alice"}],
                },
                {
                    "id": "g2",
                    "server_filters": [
                        {"propertyName": P_HISTORIE, "operator": "EQ", "value": "26DOR_BEO"},
                    ],
                    "local_contains": [{"propertyName": P_JOBTITLE, "value": "Manager"}],
                },
            ],
            result,
        )

    def test_ignores_fully_empty_groups(self) -> None:
        model = [
            {
                "id": "g-empty",
                "filters": [
                    {"id": "f1", "property": P_HISTORIE, "op": "EQ", "value": []},
                    {"id": "f2", "property": P_COMPANY, "op": "EQ", "value": ""},
                ],
            }
        ]

        self.assertEqual([], build_compiled_groups_from_model(model))


if __name__ == "__main__":
    unittest.main()
