# badgegen/hubspot_search.py
from typing import Dict, Any, List, Optional
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
