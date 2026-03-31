from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BADGE_NOTIFICATION_RECIPIENT = "severin.wagner@mysecurityevent.de"
_REPLACE_RETRIES = 8
_RETRY_DELAY_SECONDS = 0.05


@dataclass(frozen=True)
class BadgeNotificationSettings:
    email_enabled: bool = False
    sender_email: str = ""
    recipient_email: str = DEFAULT_BADGE_NOTIFICATION_RECIPIENT


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def load_badge_notification_settings(path: Path) -> BadgeNotificationSettings:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return BadgeNotificationSettings(
                email_enabled=_as_bool(data.get("email_enabled")),
                sender_email=str(data.get("sender_email") or "").strip(),
                recipient_email=str(data.get("recipient_email") or "").strip() or DEFAULT_BADGE_NOTIFICATION_RECIPIENT,
            )
    except Exception:
        pass
    return BadgeNotificationSettings()


def _replace_file_with_retry(tmp_path: Path, target_path: Path) -> None:
    last_error: PermissionError | None = None

    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp_path, target_path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == _REPLACE_RETRIES - 1:
                break
            time.sleep(_RETRY_DELAY_SECONDS)

    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass

    assert last_error is not None
    raise last_error


def save_badge_notification_settings(path: Path, settings: BadgeNotificationSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "email_enabled": bool(settings.email_enabled),
        "sender_email": (settings.sender_email or "").strip(),
        "recipient_email": (settings.recipient_email or "").strip(),
    }
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        text=True,
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_file_with_retry(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
