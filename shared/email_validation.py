from __future__ import annotations

import re
from email import utils as email_utils

_CONTROL_OR_SPACE_RE = re.compile(r"[\s\x00-\x1f\x7f]")
_LOCAL_PART_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


def normalize_email_address(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    display_name, parsed_addr = email_utils.parseaddr(raw)
    candidate = parsed_addr.strip() if parsed_addr and (display_name or raw != parsed_addr) else raw
    if "@" not in candidate:
        return candidate

    local_part, domain = candidate.rsplit("@", 1)
    return f"{local_part}@{domain.lower()}"


def is_valid_email_address(value: str) -> bool:
    candidate = normalize_email_address(value)
    if not candidate:
        return False
    if _CONTROL_OR_SPACE_RE.search(candidate):
        return False
    if candidate.count("@") != 1:
        return False

    local_part, domain = candidate.rsplit("@", 1)
    if not local_part or not domain:
        return False
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        return False
    if not _LOCAL_PART_RE.fullmatch(local_part):
        return False

    if "." not in domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False

    labels = domain.split(".")
    return all(label and _DOMAIN_LABEL_RE.fullmatch(label) for label in labels)
