# serienmailing/imap_sender.py

from __future__ import annotations

import imaplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid
from html import unescape
import re


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    username: str
    password: str
    drafts_folder: str = "Drafts"
    use_ssl: bool = True


@dataclass(frozen=True)
class SerienMail:
    to_email: str
    vorname: str
    firma: str
    subject: str
    html_body: str
    attachment_bytes: bytes | None = None
    attachment_filename: str | None = None


@dataclass(frozen=True)
class SerienMailResult:
    to_email: str
    vorname: str
    firma: str
    subject: str
    status: str   # "draft_created" | "error"
    details: str


def _html_to_plain_text(html_body: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html_body)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?s)<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "Please use an HTML-capable email client."


def _build_message(mail: SerienMail, config: MailConfig) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = mail.subject
    msg["From"] = config.username
    msg["To"] = mail.to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    msg.set_content(_html_to_plain_text(mail.html_body))
    msg.add_alternative(mail.html_body, subtype="html")

    if mail.attachment_bytes and mail.attachment_filename:
        # Determine MIME type from filename extension
        filename = mail.attachment_filename
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime_map = {
            "pdf": ("application", "pdf"),
            "png": ("image", "png"),
            "jpg": ("image", "jpeg"),
            "jpeg": ("image", "jpeg"),
            "xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        maintype, subtype = mime_map.get(ext, ("application", "octet-stream"))
        msg.add_attachment(
            mail.attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return msg.as_bytes(policy=SMTP)


def _connect(config: MailConfig):
    if config.use_ssl:
        return imaplib.IMAP4_SSL(config.host, config.port)
    return imaplib.IMAP4(config.host, config.port)


def _friendly_imap_error(raw: str) -> str:
    """Translate raw IMAP/network error strings into user-friendly German messages."""
    s = raw.lower()
    if "authenticationfailed" in s or "authentication failed" in s or "invalid credentials" in s:
        return "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen."
    if "nonexistent" in s or "mailbox does not exist" in s or "no such mailbox" in s:
        return "Entwurfs-Ordner nicht gefunden. Bitte den Ordnernamen in den Einstellungen prüfen."
    if "connection refused" in s or "timed out" in s or "errno" in s:
        return "Verbindung zum Mailserver fehlgeschlagen. Bitte Netzwerk und Serveradresse prüfen."
    return raw


def create_serienmailing_drafts(
    mails: list[SerienMail],
    config: MailConfig,
) -> list[SerienMailResult]:
    if not config.host.strip():
        raise ValueError("Der Postfach-Server darf nicht leer sein.")
    if not config.username.strip():
        raise ValueError("Die E-Mail-Adresse darf nicht leer sein.")
    if not config.password:
        raise ValueError("Das Passwort darf nicht leer sein.")
    if not config.drafts_folder.strip():
        raise ValueError("Der Ordner für Entwürfe darf nicht leer sein.")

    try:
        connection = _connect(config)
        connection.login(config.username, config.password)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise RuntimeError(_friendly_imap_error(str(exc))) from exc

    results: list[SerienMailResult] = []

    try:
        select_status, select_data = connection.select(config.drafts_folder)
        if select_status != "OK":
            raise RuntimeError(
                _friendly_imap_error(f"nonexistent: {config.drafts_folder} {select_data}")
            )

        for mail in mails:
            try:
                append_status, _ = connection.append(
                    config.drafts_folder,
                    "(\\Draft)",
                    imaplib.Time2Internaldate(time.time()),
                    _build_message(mail, config),
                )
                if append_status != "OK":
                    raise RuntimeError(f"APPEND fehlgeschlagen: {append_status}")
                results.append(SerienMailResult(
                    to_email=mail.to_email,
                    vorname=mail.vorname,
                    firma=mail.firma,
                    subject=mail.subject,
                    status="draft_created",
                    details="",
                ))
            except Exception as exc:
                results.append(SerienMailResult(
                    to_email=mail.to_email,
                    vorname=mail.vorname,
                    firma=mail.firma,
                    subject=mail.subject,
                    status="error",
                    details=_friendly_imap_error(str(exc)),
                ))
    finally:
        try:
            connection.logout()
        except Exception:
            pass

    return results
