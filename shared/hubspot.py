from __future__ import annotations

import time
from typing import Any

import requests

from shared.config import ConfigError, get_hubspot_token

HUBSPOT_BASE = "https://api.hubapi.com"
PAGE_SIZE = 100
PAGING_DELAY_SECONDS = 0.08


def _normalize_path(path: str) -> tuple[str, str]:
    raw_path = (path or "").strip()
    if raw_path.startswith(("http://", "https://")):
        return raw_path, raw_path
    normalized = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    return f"{HUBSPOT_BASE}{normalized}", normalized


def _format_error_details(response: requests.Response) -> str:
    try:
        details = response.json()
    except Exception:
        details = getattr(response, "text", "")
    return str(details)[:800]


def _resolve_token(*, token: str | None = None, secrets: Any = None, environ: Any = None) -> str:
    explicit = str(token).strip() if token is not None else ""
    if explicit:
        return explicit
    return get_hubspot_token(secrets=secrets, environ=environ)


def build_headers(
    *,
    token: str | None = None,
    secrets: Any = None,
    environ: Any = None,
    include_content_type: bool = True,
) -> dict[str, str]:
    resolved_token = _resolve_token(token=token, secrets=secrets, environ=environ)
    headers = {"Authorization": f"Bearer {resolved_token}"}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _request_json(
    method: str,
    path: str,
    *,
    token: str | None = None,
    secrets: Any = None,
    environ: Any = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int = 60,
    include_content_type: bool | None = None,
) -> dict[str, Any]:
    method_upper = method.upper()
    if include_content_type is None:
        include_content_type = method_upper != "GET"

    url, display_path = _normalize_path(path)
    response = requests.request(
        method_upper,
        url,
        headers=build_headers(
            token=token,
            secrets=secrets,
            environ=environ,
            include_content_type=include_content_type,
        ),
        params=params,
        json=json,
        timeout=timeout,
    )

    if response.status_code >= 400:
        details = _format_error_details(response)
        message = f"HubSpot {method_upper} {display_path} failed: {response.status_code}"
        if details:
            message += f" {details}"
        raise requests.HTTPError(message, response=response)

    return response.json()


def fetch_property_options(
    property_name: str,
    *,
    token: str | None = None,
    secrets: Any = None,
    environ: Any = None,
    object_type: str = "contacts",
) -> list[tuple[str, str]]:
    data = _request_json(
        "GET",
        f"/crm/v3/properties/{object_type}/{property_name}",
        token=token,
        secrets=secrets,
        environ=environ,
        timeout=30,
        include_content_type=False,
    )
    options = data.get("options", []) or []
    out: list[tuple[str, str]] = []
    for option in options:
        if option.get("hidden"):
            continue
        label = str(option.get("label") or "").strip()
        value = str(option.get("value") or "").strip()
        if label and value:
            out.append((label, value))
    return out


def search_contacts(
    filter_groups: list[dict],
    properties: list[str],
    *,
    token: str | None = None,
    secrets: Any = None,
    environ: Any = None,
    max_results: int | None = None,
) -> list[dict]:
    out: list[dict] = []
    after: str | None = None

    while True:
        if max_results is not None:
            remaining = max_results - len(out)
            if remaining <= 0:
                break
            limit = min(PAGE_SIZE, remaining)
        else:
            limit = PAGE_SIZE

        payload: dict[str, Any] = {
            "limit": limit,
            "properties": properties,
        }
        if filter_groups:
            payload["filterGroups"] = filter_groups
        if after:
            payload["after"] = after

        data = _request_json(
            "POST",
            "/crm/v3/objects/contacts/search",
            token=token,
            secrets=secrets,
            environ=environ,
            json=payload,
            timeout=60,
        )
        batch = data.get("results", []) or []
        out.extend(batch)

        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after or not batch:
            break

        time.sleep(PAGING_DELAY_SECONDS)

    return out


def search_contacts_with_auto_split(
    filter_groups: list[dict],
    properties: list[str],
    *,
    token: str | None = None,
    secrets: Any = None,
    environ: Any = None,
    max_results: int | None = None,
) -> list[dict]:
    try:
        return search_contacts(
            filter_groups,
            properties,
            token=token,
            secrets=secrets,
            environ=environ,
            max_results=max_results,
        )
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 400 and len(filter_groups) > 1:
            mid = len(filter_groups) // 2
            left = search_contacts_with_auto_split(
                filter_groups[:mid],
                properties,
                token=token,
                secrets=secrets,
                environ=environ,
                max_results=max_results,
            )
            right = search_contacts_with_auto_split(
                filter_groups[mid:],
                properties,
                token=token,
                secrets=secrets,
                environ=environ,
                max_results=max_results,
            )

            by_id: dict[str, dict] = {}
            extras: list[dict] = []
            for item in left + right:
                contact_id = item.get("id")
                if contact_id:
                    by_id[contact_id] = item
                else:
                    extras.append(item)
            return list(by_id.values()) + extras
        raise
