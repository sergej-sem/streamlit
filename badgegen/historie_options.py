# badgegen/historie_options.py
from typing import List, Tuple

from shared.hubspot import fetch_property_options

def fetch_historie_options(token: str, historie_property: str = "historie") -> List[Tuple[str, str]]:
    """
    Liefert [(label, value), ...] aus der HubSpot Property-Definition.
    Wie in deiner Excel-Export-Page.
    Falls keine Options vorhanden / Scope fehlt -> [].
    """
    try:
        return fetch_property_options(
            historie_property,
            token=token,
            object_type="contacts",
        )
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
