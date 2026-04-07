from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphBulkUserSettings:
    tenant_id: str
    client_id: str
    client_secret: str
    enable_live_user_creation: bool = False


@dataclass(frozen=True)
class ImapDraftSettings:
    host: str
    port: int
    drafts_folder: str = "Drafts"
    use_ssl: bool = True


@dataclass(frozen=True)
class SmtpSendSettings:
    host: str
    port: int = 465
    use_ssl: bool = True
    use_starttls: bool = False
    timeout_seconds: int = 30


_MISSING = object()
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}


def _mapping_get(mapping_like: Any, key: str, default: Any = None) -> Any:
    if mapping_like is None:
        return default

    getter = getattr(mapping_like, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            try:
                return getter(key)
            except Exception:
                pass
        except Exception:
            pass

    try:
        return mapping_like[key]
    except Exception:
        return default


def _mapping_has(mapping_like: Any, key: str) -> bool:
    if mapping_like is None:
        return False

    try:
        return key in mapping_like
    except Exception:
        return _mapping_get(mapping_like, key, _MISSING) is not _MISSING


def _mapping_section(mapping_like: Any, key: str) -> Any:
    if not _mapping_has(mapping_like, key):
        return None
    return _mapping_get(mapping_like, key)


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, PathLike):
        value = str(value)
    return str(value).strip()


def _require_section(secrets: Any, section_name: str) -> Any:
    section = _mapping_section(secrets, section_name)
    if section is None:
        raise ConfigError(f"Missing config section: {section_name}")
    return section


def _require_value(section: Any, dotted_name: str, key: str) -> str:
    value = _clean_str(_mapping_get(section, key))
    if not value:
        raise ConfigError(f"Missing required config value: {dotted_name}.{key}")
    return value


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0

    text = _clean_str(value).lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return default


def get_hubspot_token(secrets: Any = None, environ: Any = None) -> str:
    for source in (secrets, environ):
        for key in ("HUBSPOT_TOKEN", "HUBSPOT_ACCESS_TOKEN"):
            value = _clean_str(_mapping_get(source, key))
            if value:
                return value
    raise ConfigError("Missing required config value: HUBSPOT_TOKEN or HUBSPOT_ACCESS_TOKEN")


def load_graph_bulk_user_settings(secrets: Any = None) -> GraphBulkUserSettings:
    section_name = "mse_graph_bulk_user"
    section = _require_section(secrets, section_name)

    return GraphBulkUserSettings(
        tenant_id=_require_value(section, section_name, "tenant_id"),
        client_id=_require_value(section, section_name, "client_id"),
        client_secret=_require_value(section, section_name, "client_secret"),
        enable_live_user_creation=parse_bool(
            _mapping_get(section, "enable_live_user_creation"),
            default=False,
        ),
    )


def is_live_user_creation_enabled(secrets: Any = None) -> bool:
    section = _mapping_section(secrets, "mse_graph_bulk_user")
    if section is None:
        return False
    return parse_bool(_mapping_get(section, "enable_live_user_creation"), default=False)


def load_imap_draft_settings(secrets: Any = None) -> ImapDraftSettings:
    section_name = "mse_imap_mail_drafts"
    section = _require_section(secrets, section_name)

    host = _require_value(section, section_name, "host")
    port_raw = _require_value(section, section_name, "port")

    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config value: {section_name}.port") from exc

    drafts_folder = _clean_str(_mapping_get(section, "drafts_folder")) or "Drafts"
    use_ssl = parse_bool(_mapping_get(section, "use_ssl"), default=True)

    return ImapDraftSettings(
        host=host,
        port=port,
        drafts_folder=drafts_folder,
        use_ssl=use_ssl,
    )


def load_smtp_send_settings(secrets: Any = None) -> SmtpSendSettings:
    section_name = "mse_smtp_mail_send"
    section = _require_section(secrets, section_name)

    host = _require_value(section, section_name, "host")
    port_raw = _mapping_get(section, "port", 465)
    timeout_raw = _mapping_get(section, "timeout_seconds", 30)

    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config value: {section_name}.port") from exc

    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config value: {section_name}.timeout_seconds") from exc

    if timeout_seconds <= 0:
        raise ConfigError(f"Invalid config value: {section_name}.timeout_seconds")

    use_ssl = parse_bool(_mapping_get(section, "use_ssl"), default=True)
    use_starttls = parse_bool(_mapping_get(section, "use_starttls"), default=False)
    if use_ssl and use_starttls:
        raise ConfigError(f"Invalid config combination: {section_name}.use_ssl and {section_name}.use_starttls")

    return SmtpSendSettings(
        host=host,
        port=port,
        use_ssl=use_ssl,
        use_starttls=use_starttls,
        timeout_seconds=timeout_seconds,
    )
