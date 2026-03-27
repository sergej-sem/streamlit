# badgegen/hubspot_search.py
from typing import Dict, Any, List, Optional

import pandas as pd
import requests

from shared.hubspot import (
    _request_json,
    search_contacts as shared_search_contacts,
    search_contacts_with_auto_split as shared_search_contacts_with_auto_split,
)

# Contact properties (fix)
P_FIRSTNAME = "firstname"
P_LASTNAME = "lastname"
P_COMPANY = "company"
P_JOBTITLE = "jobtitle"
P_HISTORIE = "historie"
P_EMAIL = "email"
SEARCH_PROPERTIES = [P_FIRSTNAME, P_LASTNAME, P_COMPANY, P_JOBTITLE, P_HISTORIE, P_EMAIL]


class HubSpotAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _wrap_http_error(exc: requests.HTTPError) -> HubSpotAPIError:
    status_code = getattr(getattr(exc, "response", None), "status_code", None) or 0
    return HubSpotAPIError(int(status_code), str(exc))


def hs_post(token: str, path: str, json: dict | None = None) -> dict:
    try:
        return _request_json(
            "POST",
            path,
            token=token,
            json=json,
            timeout=60,
            include_content_type=True,
        )
    except requests.HTTPError as exc:
        raise _wrap_http_error(exc) from exc


def _search_contacts_paged(
    token: str,
    *,
    filter_groups: List[dict],
    properties: List[str],
    max_results: Optional[int] = None,  # None = unbegrenzt
) -> List[Dict[str, Any]]:
    try:
        return shared_search_contacts(
            filter_groups,
            properties,
            token=token,
            max_results=max_results,
        )
    except requests.HTTPError as exc:
        raise _wrap_http_error(exc) from exc


def search_contacts_auto_split(
    token: str,
    *,
    filter_groups: List[dict],
    properties: List[str],
    max_results: Optional[int] = None,  # None = unbegrenzt
) -> List[Dict[str, Any]]:
    """
    Robust: wenn HubSpot bei vielen filterGroups 400 liefert -> splitten und IDs deduplizieren.
    (Gleiche Idee wie in deiner Excel-Export-Page.)
    """
    try:
        return shared_search_contacts_with_auto_split(
            filter_groups,
            properties,
            token=token,
            max_results=max_results,
        )
    except requests.HTTPError as exc:
        raise _wrap_http_error(exc) from exc


def _match_substring(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _apply_local_contains_filters(
    contacts: List[Dict[str, Any]],
    local_contains: List[dict],
) -> List[Dict[str, Any]]:
    if not local_contains:
        return contacts

    out: List[Dict[str, Any]] = []
    for contact in contacts:
        properties = contact.get("properties", {}) or {}
        matches_all = True
        for condition in local_contains:
            property_name = condition.get("propertyName")
            needle = (condition.get("value") or "").strip()
            if not property_name or not needle:
                continue

            haystack = (properties.get(property_name) or "").strip()
            if not _match_substring(haystack, needle):
                matches_all = False
                break

        if matches_all:
            out.append(contact)

    return out


def _rows_from_contacts(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for contact in contacts:
        properties = contact.get("properties", {}) or {}
        rows.append(
            {
                "id": contact.get("id"),
                "firstname": (properties.get(P_FIRSTNAME) or "").strip(),
                "lastname": (properties.get(P_LASTNAME) or "").strip(),
                "company": (properties.get(P_COMPANY) or "").strip(),
                "jobtitle": (properties.get(P_JOBTITLE) or "").strip(),
                "historie": properties.get(P_HISTORIE) or "",
                "email": (properties.get(P_EMAIL) or "").strip(),
            }
        )
    return rows


def search_group(
    token: str,
    *,
    server_filters: List[dict],
    local_contains: List[dict],
    properties: List[str] | None = None,
) -> List[Dict[str, Any]]:
    requested_properties = list(properties or SEARCH_PROPERTIES)
    filter_groups = [{"filters": server_filters}] if server_filters else []

    contacts = search_contacts_auto_split(
        token,
        filter_groups=filter_groups,
        properties=requested_properties,
    )
    return _apply_local_contains_filters(contacts, local_contains)


def search_compiled_groups(
    token: str,
    compiled_groups: List[dict],
    *,
    properties: List[str] | None = None,
) -> pd.DataFrame:
    by_id: Dict[str, Dict[str, Any]] = {}

    for group in compiled_groups:
        server_filters = group.get("server_filters") or []
        local_contains = group.get("local_contains") or []

        if not server_filters and local_contains:
            continue

        for contact in search_group(
            token,
            server_filters=server_filters,
            local_contains=local_contains,
            properties=properties,
        ):
            contact_id = contact.get("id")
            if contact_id:
                by_id[str(contact_id)] = contact

    rows = _rows_from_contacts(list(by_id.values()))
    return pd.DataFrame(
        rows,
        columns=["id", "firstname", "lastname", "company", "jobtitle", "historie", "email"],
    )
