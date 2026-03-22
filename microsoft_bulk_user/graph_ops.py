from dataclasses import dataclass
from typing import Dict, List

import requests

try:
    import msal
except ModuleNotFoundError:  # pragma: no cover - exercised only in stripped test envs
    msal = None


@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str


def create_graph_app(cfg: GraphConfig):
    if msal is None:
        raise RuntimeError("MSAL ist nicht installiert.")
    authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=cfg.client_id,
        authority=authority,
        client_credential=cfg.client_secret,
    )


def get_access_token(cfg: GraphConfig, *, app=None) -> str:
    graph_app = app or create_graph_app(cfg)
    scopes = ["https://graph.microsoft.com/.default"]
    result = graph_app.acquire_token_silent(scopes, account=None)
    if not result:
        result = graph_app.acquire_token_for_client(scopes=scopes)
    if "access_token" not in result:
        raise RuntimeError(f"Token-Fehler: {result.get('error')} - {result.get('error_description')}")
    return result["access_token"]


def get_subscribed_sku_map(token: str) -> Dict[str, str]:
    """
    Liefert ein Mapping {SkuPartNumber -> skuId} aus Graph /subscribedSkus.
    """
    url = "https://graph.microsoft.com/v1.0/subscribedSkus"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"Graph-Abfrage (subscribedSkus) fehlgeschlagen ({response.status_code}): {response.text}"
        )
    data = response.json().get("value", [])
    out: Dict[str, str] = {}
    for item in data:
        part = item.get("skuPartNumber")
        sku_id = item.get("skuId")
        if part and sku_id:
            out[str(part)] = str(sku_id)
    return out


def assign_licenses(user_id: str, sku_ids: List[str], token: str) -> None:
    """
    Weist einem Benutzer Lizenzen zu (addLicenses). Entfernt nichts.
    """
    if not sku_ids:
        return
    url = f"https://graph.microsoft.com/v1.0/users/{user_id}/assignLicense"
    payload = {
        "addLicenses": [{"skuId": sid} for sid in sku_ids],
        "removeLicenses": [],
    }
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Lizenzzuweisung fehlgeschlagen ({response.status_code}): {response.text}")


def _escape_odata_string(s: str) -> str:
    return (s or "").replace("'", "''")


def upn_exists(upn: str, token: str) -> bool:
    url = "https://graph.microsoft.com/v1.0/users"
    params = {"$filter": f"userPrincipalName eq '{_escape_odata_string(upn)}'", "$top": "1"}
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if response.status_code == 200:
        data = response.json()
        return bool(data.get("value"))
    raise RuntimeError(f"Graph-Abfrage (UPN) fehlgeschlagen ({response.status_code}): {response.text}")


def name_exists(first: str, last: str, token: str) -> bool:
    """
    Prüft, ob bereits ein Benutzer mit identischem Vor- UND Nachnamen existiert.
    Primär über givenName + surname; falls nicht unterstützt, Fallback über displayName.
    """
    url = "https://graph.microsoft.com/v1.0/users"
    escaped_first = _escape_odata_string(first.strip())
    escaped_last = _escape_odata_string(last.strip())

    params = {
        "$filter": f"givenName eq '{escaped_first}' and surname eq '{escaped_last}'",
        "$top": "1",
        "$select": "id",
    }
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if response.status_code == 200:
        return bool(response.json().get("value"))
    if response.status_code not in (400, 501):
        raise RuntimeError(f"Graph-Abfrage (Name) fehlgeschlagen ({response.status_code}): {response.text}")

    display = _escape_odata_string(f"{first.strip()} {last.strip()}".strip())
    fallback_params = {"$filter": f"displayName eq '{display}'", "$top": "1", "$select": "id"}
    fallback_response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=fallback_params,
        timeout=30,
    )
    if fallback_response.status_code == 200:
        return bool(fallback_response.json().get("value"))
    raise RuntimeError(
        "Graph-Abfrage (displayName Fallback) fehlgeschlagen "
        f"({fallback_response.status_code}): {fallback_response.text}"
    )


def create_user_graph(payload: dict, token: str) -> Dict:
    url = "https://graph.microsoft.com/v1.0/users"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if response.status_code in (200, 201):
        return response.json()
    raise RuntimeError(f"Benutzer anlegen fehlgeschlagen ({response.status_code}): {response.text}")


def user_payload(
    display_name: str,
    upn: str,
    mail_nick: str,
    given: str,
    surname: str,
    password: str,
    *,
    usage_location: str = "DE",
    force_change_password: bool = False,
    disable_password_expiration: bool = True,
) -> dict:
    payload = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": mail_nick,
        "userPrincipalName": upn,
        "givenName": given,
        "surname": surname,
        "usageLocation": usage_location,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": bool(force_change_password),
            "password": password,
        },
    }
    if disable_password_expiration:
        payload["passwordPolicies"] = "DisablePasswordExpiration"
    return payload
