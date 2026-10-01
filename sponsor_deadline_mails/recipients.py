from __future__ import annotations

import re
from email import utils as email_utils
from email.headerregistry import HeaderRegistry

from shared.email_validation import is_valid_email_address, normalize_email_address


_HEADER_REGISTRY = HeaderRegistry()
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def _recipient_tokens(value: object) -> list[str]:
    """Split Excel address lists without splitting quoted names or comments."""
    text = str(value or "").strip()
    tokens: list[str] = []
    start = 0
    quoted = False
    escaped = False
    angles = 0
    comments = 0
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\" and (quoted or comments):
            escaped = True
        elif character == '"' and not comments:
            quoted = not quoted
        elif not quoted:
            if character == "(" and not angles:
                comments += 1
            elif character == ")" and comments:
                comments -= 1
            elif not comments:
                if character == "<":
                    angles += 1
                elif character == ">" and angles:
                    angles -= 1
                elif character in ",;\r\n" and not angles:
                    token = text[start:index].strip()
                    if token:
                        tokens.append(token)
                    start = index + 1
    token = text[start:].strip()
    if token:
        tokens.append(token)
    return tokens


def _parsed_recipient(token: str) -> tuple[str, str] | None:
    if _CONTROL_CHARACTERS.search(token):
        return None
    try:
        header = _HEADER_REGISTRY("To", token)
        if header.defects or len(header.addresses) != 1:
            return None
        if any(group.display_name is not None for group in header.groups):
            return None
        address = header.addresses[0]
        mailbox = normalize_email_address(address.addr_spec)
        if not is_valid_email_address(mailbox):
            return None
        return address.display_name, mailbox
    except (ValueError, IndexError):
        return None


def normalize_recipient_cell(value: object) -> str:
    """Canonicalize separators while retaining malformed tokens for validation."""
    normalized: list[str] = []
    for token in _recipient_tokens(value):
        parsed = _parsed_recipient(token)
        if parsed is None:
            normalized.append(token)
        else:
            display_name, mailbox = parsed
            normalized.append(
                email_utils.formataddr((display_name, mailbox)) if display_name else mailbox
            )
    return ", ".join(normalized)


def invalid_recipient_addresses(value: object, *, required: bool = False) -> list[str]:
    tokens = _recipient_tokens(value)
    if required and not tokens:
        return [""]
    return [token for token in tokens if _parsed_recipient(token) is None]


def recipient_mailboxes(value: object, *, required: bool = False) -> list[str]:
    """Return every mailbox; never silently discard an invalid list entry."""
    tokens = _recipient_tokens(value)
    parsed = [_parsed_recipient(token) for token in tokens]
    if (required and not tokens) or any(address is None for address in parsed):
        raise ValueError("Ungültige E-Mail-Empfängerliste. Bitte alle Adressen prüfen.")
    return [address[1] for address in parsed if address is not None]
