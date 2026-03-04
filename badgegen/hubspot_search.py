# badgegen/hubspot_search.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import requests

HUBSPOT_BASE = "https://api.hubapi.com"

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


def hs_post(token: str, path: str, json: dict | None = None) -> dict:
    r = requests.post(
        f"{HUBSPOT_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json,
        timeout=60,
    )
    if r.status_code >= 400:
        raise HubSpotAPIError(r.status_code, f"HubSpot POST {path} failed: {r.status_code} {r.text[:800]}")
    return r.json()


def _search_contacts_paged(
    token: str,
    *,
    filter_groups: List[dict],
    properties: List[str],
    max_results: Optional[int] = None,  # None = unbegrenzt
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    after: Optional[str] = None

    while True:
        if max_results is not None:
            remaining = max_results - len(out)
            if remaining <= 0:
                break
            limit = min(100, remaining)
        else:
            limit = 100  # HubSpot page size (keine Ergebnis-Begrenzung, nur Paging)

        payload: Dict[str, Any] = {
            "limit": limit,
            "properties": properties,
        }
        if filter_groups:
            payload["filterGroups"] = filter_groups
        if after:
            payload["after"] = after

        data = hs_post(token, "/crm/v3/objects/contacts/search", json=payload)
        batch = data.get("results", []) or []
        out.extend(batch)

        after = data.get("paging", {}).get("next", {}).get("after")
        if not after or not batch:
            break

    return out


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
        return _search_contacts_paged(token, filter_groups=filter_groups, properties=properties, max_results=max_results)
    except HubSpotAPIError as e:
        if e.status_code == 400 and len(filter_groups) > 1:
            mid = len(filter_groups) // 2
            left = search_contacts_auto_split(
                token,
                filter_groups=filter_groups[:mid],
                properties=properties,
                max_results=max_results,
            )
            right = search_contacts_auto_split(
                token,
                filter_groups=filter_groups[mid:],
                properties=properties,
                max_results=max_results,
            )

            by_id: Dict[str, Dict[str, Any]] = {}
            for item in left + right:
                cid = item.get("id")
                if cid:
                    by_id[cid] = item
            return list(by_id.values())
        raise
