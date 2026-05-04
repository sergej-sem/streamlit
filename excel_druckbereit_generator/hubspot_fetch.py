from __future__ import annotations

from typing import Iterable

from shared.hubspot import fetch_property_options, search_contacts_with_auto_split

HISTORIE_PROPERTY = "historie"
DEFAULT_HS_PROPERTIES = ["company", "firstname", "lastname", "expertenwissen", "vorqualifizierung"]
HS_PROPERTIES = DEFAULT_HS_PROPERTIES
INITIAL_FILTERGROUPS_PER_REQUEST = 5


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _normalize_historie_values(historie_values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for value in historie_values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)

    return normalized


def _build_historie_filter_groups(historie_values: list[str]) -> list[dict]:
    return [
        {
            "filters": [
                {
                    "propertyName": HISTORIE_PROPERTY,
                    "operator": "CONTAINS_TOKEN",
                    "value": historie_value,
                }
            ]
        }
        for historie_value in historie_values
    ]


def _update_results_by_id(results_by_id: dict[str, dict], results: list[dict]) -> None:
    for item in results:
        contact_id = item.get("id")
        if contact_id:
            results_by_id[contact_id] = item


def load_historie_options(*, token: str) -> list[tuple[str, str]]:
    return fetch_property_options(
        HISTORIE_PROPERTY,
        token=token,
        object_type="contacts",
    )


def fetch_contacts_by_historien(
    historie_values: list[str],
    *,
    properties: list[str],
    token: str,
    initial_filtergroups_per_request: int = INITIAL_FILTERGROUPS_PER_REQUEST,
) -> list[dict]:
    normalized_values = _normalize_historie_values(historie_values)
    if not normalized_values:
        return []

    results_by_id: dict[str, dict] = {}

    for batch in _chunks(normalized_values, initial_filtergroups_per_request):
        filter_groups = _build_historie_filter_groups(batch)
        results = search_contacts_with_auto_split(
            filter_groups,
            properties,
            token=token,
        )
        _update_results_by_id(results_by_id, results)

    return list(results_by_id.values())
