from __future__ import annotations

from typing import Any, Sequence


def normalize_email_widget_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("result") or value.get("search") or ""
    return str(value or "").strip()


def build_email_select_options(
    suggestions: Sequence[str],
    current_value: Any = "",
) -> list[str]:
    current = normalize_email_widget_value(current_value)
    options: list[str] = []
    seen: set[str] = set()

    def _append(raw: Any) -> None:
        email = normalize_email_widget_value(raw)
        if not email:
            return
        email_key = email.casefold()
        if email_key in seen:
            return
        seen.add(email_key)
        options.append(email)

    _append(current)
    for suggestion in suggestions:
        _append(suggestion)

    return options
