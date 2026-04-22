from __future__ import annotations

import re
import unicodedata
from email import utils as email_utils
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid

from serienmailing.mail_builder import html_to_plain_text
from shared.email_validation import is_valid_email_address, normalize_email_address

_MIME_MAP = {
    "pdf": ("application", "pdf"),
    "png": ("image", "png"),
    "jpg": ("image", "jpeg"),
    "jpeg": ("image", "jpeg"),
    "xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


def _attachment_mime_type(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_MAP.get(ext, ("application", "octet-stream"))


def _sanitize_attachment_filename(filename: str | None) -> str:
    raw = (filename or "").strip()
    if not raw:
        return "attachment"

    transliteration_map = str.maketrans({
        "ß": "ss",
        "ẞ": "SS",
        "æ": "ae",
        "Æ": "AE",
        "ø": "o",
        "Ø": "O",
    })
    raw = raw.translate(transliteration_map)

    if "." in raw:
        base, ext = raw.rsplit(".", 1)
        ext = "." + ext
    else:
        base, ext = raw, ""

    normalized_base = (
        unicodedata.normalize("NFKD", base)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    normalized_ext = (
        unicodedata.normalize("NFKD", ext)
        .encode("ascii", "ignore")
        .decode("ascii")
    )

    normalized_base = re.sub(r"\s+", "_", normalized_base)
    normalized_base = re.sub(r"[^A-Za-z0-9._-]", "_", normalized_base)
    normalized_base = re.sub(r"_+", "_", normalized_base).strip("._")
    normalized_ext = re.sub(r"[^A-Za-z0-9.]", "", normalized_ext)

    if not normalized_base:
        normalized_base = "attachment"

    return f"{normalized_base}{normalized_ext}"


def _normalize_address_header(value: str, *, allow_multiple: bool) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    addresses = email_utils.getaddresses([raw])
    formatted: list[str] = []
    invalid: list[str] = []
    for display_name, addr in addresses:
        normalized_addr = normalize_email_address(addr)
        normalized_name = (display_name or "").strip()
        if not normalized_addr:
            candidate = (addr or "").strip()
            if candidate:
                invalid.append(candidate)
            continue
        if not is_valid_email_address(normalized_addr):
            invalid.append((addr or "").strip() or normalized_addr)
            continue
        formatted.append(
            email_utils.formataddr((normalized_name, normalized_addr))
            if normalized_name
            else normalized_addr
        )

    if invalid:
        raise ValueError("Ungültige E-Mail-Adresse: " + ", ".join(invalid))
    if not formatted:
        normalized_raw = normalize_email_address(raw)
        if normalized_raw and is_valid_email_address(normalized_raw):
            return normalized_raw
        raise ValueError("Ungültige E-Mail-Adresse.")
    if allow_multiple:
        return ", ".join(formatted)
    return formatted[0]


def _message_id_for_sender(from_email: str) -> str:
    _, addr = email_utils.parseaddr(from_email)
    if "@" not in addr:
        return make_msgid()
    domain = addr.rsplit("@", 1)[-1].strip().lower()
    if not domain:
        return make_msgid()
    return make_msgid(domain=domain)


def build_email_message(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str | None = None,
    cc_email: str = "",
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
) -> EmailMessage:
    normalized_from = _normalize_address_header(from_email, allow_multiple=False)
    normalized_to = _normalize_address_header(to_email, allow_multiple=True)
    normalized_cc = _normalize_address_header(cc_email, allow_multiple=True)
    safe_attachment_filename = _sanitize_attachment_filename(attachment_filename) if attachment_filename else None

    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message["From"] = normalized_from or from_email.strip()
    message["To"] = normalized_to or to_email.strip()
    if normalized_cc:
        message["Cc"] = normalized_cc
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = _message_id_for_sender(message["From"])

    message.set_content(
        plain_body or html_to_plain_text(html_body),
        charset="utf-8",
        cte="quoted-printable",
    )
    message.add_alternative(
        html_body,
        subtype="html",
        charset="utf-8",
        cte="quoted-printable",
    )

    if attachment_bytes and safe_attachment_filename:
        maintype, subtype = _attachment_mime_type(safe_attachment_filename)
        message.add_attachment(
            attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=safe_attachment_filename,
        )

    return message


def build_email_message_bytes(**kwargs) -> bytes:
    return build_email_message(**kwargs).as_bytes(policy=SMTP)
