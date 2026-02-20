import requests
import streamlit as st

BASE = "https://api.hubapi.com"

def hs_headers() -> dict:
    return {
        "Authorization": f"Bearer {st.secrets['HUBSPOT_TOKEN']}",
        "Content-Type": "application/json",
    }

def get_contact_lists(count: int = 500) -> list[dict]:
    """
    POST /crm/v3/lists/search (offset/count)
    """
    url = f"{BASE}/crm/v3/lists/search"
    offset = 0
    all_lists: list[dict] = []

    while True:
        payload = {
            "offset": offset,
            "count": min(max(count, 1), 500),
            "objectTypeId": "0-1",  # Kontakte
            "query": ""
        }

        r = requests.post(url, headers=hs_headers(), json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()

        batch = data.get("lists", [])
        all_lists.extend(batch)

        if not data.get("hasMore", False):
            break

        offset = data.get("offset", offset + len(batch))

    return all_lists

def get_list_members(list_id: str) -> list[str]:
    """
    GET /crm/v3/lists/{listId}/memberships
    -> liefert recordId (Contact IDs)
    """
    url = f"{BASE}/crm/v3/lists/{list_id}/memberships"
    after = None
    ids: list[str] = []

    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after

        r = requests.get(url, headers=hs_headers(), params=params, timeout=60)
        r.raise_for_status()
        data = r.json()

        ids.extend([str(item["recordId"]) for item in data.get("results", [])])

        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break

    return ids

def get_contacts_by_ids(ids: list[str], properties: list[str]) -> list[dict]:
    """
    POST /crm/v3/objects/contacts/batch/read
    """
    url = f"{BASE}/crm/v3/objects/contacts/batch/read"
    out: list[dict] = []

    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        payload = {
            "properties": properties,
            "inputs": [{"id": str(cid)} for cid in chunk],
        }

        r = requests.post(url, headers=hs_headers(), json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()

        out.extend(data.get("results", []))

    return out