# badgegen/historie_options.py
from typing import List, Tuple
import requests

from badgegen.hubspot_search import HubSpotAPIError

HUBSPOT_BASE = "https://api.hubapi.com"


def hs_get(token: str, path: str) -> dict:
    r = requests.get(
        f"{HUBSPOT_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HubSpotAPIError(r.status_code, f"HubSpot GET {path} failed: {r.status_code} {r.text[:800]}")
    return r.json()

def fetch_historie_options(token: str, historie_property: str = "historie") -> List[Tuple[str, str]]:
    """
    Liefert [(label, value), ...] aus der HubSpot Property-Definition.
    Wie in deiner Excel-Export-Page.
    Falls keine Options vorhanden / Scope fehlt -> [].
    """
    try:
        data = hs_get(token, f"/crm/v3/properties/contacts/{historie_property}")
        options = data.get("options", []) or []
        out: List[Tuple[str, str]] = []
        for o in options:
            if o.get("hidden"):
                continue
            label = (o.get("label") or "").strip()
            value = (o.get("value") or "").strip()
            if label and value:
                out.append((label, value))
        return out
    except Exception:
        return []

def parse_free_text_tokens(raw: str) -> List[str]:
    """
    Fallback: Nutzer kann mehrere Tokens per Komma/Zeilenumbruch eingeben.
    """
    if not raw:
        return []
    seps = [",", "\n", ";"]
    for s in seps:
        raw = raw.replace(s, "\n")
    vals = [x.strip() for x in raw.split("\n") if x.strip()]
    # unique, order-preserving
    seen = set()
    out = []
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
