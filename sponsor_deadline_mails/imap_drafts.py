from __future__ import annotations

import imaplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid
from html import unescape
import re

import pandas as pd

from .core import GeneratedMail


@dataclass(frozen=True)
class ImapDraftConfig:
    host: str
    port: int
    username: str
    password: str
    drafts_folder: str = "Drafts"
    from_address: str = ""
    use_ssl: bool = True


@dataclass(frozen=True)
class ImapDraftRecord:
    sponsor_name: str
    to_email: str
    cc_email: str
    subject: str
    mailbox: str
    drafts_folder: str
    result: str
    details: str
    server_response: str


def _html_to_plain_text(html_body: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", html_body)
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?s)<.*?>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "Please use an HTML-capable email client."


def _build_message(mail: GeneratedMail, config: ImapDraftConfig) -> bytes:
    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = config.from_address or config.username
    message["To"] = mail.to_email
    if mail.cc_email:
        message["Cc"] = mail.cc_email
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(_html_to_plain_text(mail.html_body))
    message.add_alternative(mail.html_body, subtype="html")
    return message.as_bytes(policy=SMTP)


def _connect(config: ImapDraftConfig):
    if config.use_ssl:
        return imaplib.IMAP4_SSL(config.host, config.port)
    return imaplib.IMAP4(config.host, config.port)


def create_imap_drafts(
    mails: list[GeneratedMail],
    config: ImapDraftConfig,
) -> list[ImapDraftRecord]:
    if not config.host.strip():
        raise ValueError("IMAP host darf nicht leer sein")
    if not config.username.strip():
        raise ValueError("IMAP username darf nicht leer sein")
    if not config.password:
        raise ValueError("IMAP password darf nicht leer sein")
    if not config.drafts_folder.strip():
        raise ValueError("drafts_folder darf nicht leer sein")

    connection = _connect(config)
    records: list[ImapDraftRecord] = []

    try:
        login_status, login_data = connection.login(config.username, config.password)
        if login_status != "OK":
            raise RuntimeError(f"IMAP login fehlgeschlagen: {login_data}")

        select_status, select_data = connection.select(config.drafts_folder)
        if select_status != "OK":
            raise RuntimeError(
                f"Drafts-Ordner '{config.drafts_folder}' konnte nicht geoeffnet werden: {select_data}"
            )

        for mail in mails:
            try:
                append_status, append_data = connection.append(
                    config.drafts_folder,
                    "(\\Draft)",
                    imaplib.Time2Internaldate(time.time()),
                    _build_message(mail, config),
                )
                if append_status != "OK":
                    raise RuntimeError(str(append_data))

                response_text = ""
                if append_data:
                    response_text = " ".join(
                        part.decode("utf-8", errors="replace") if isinstance(part, bytes) else str(part)
                        for part in append_data
                    )

                records.append(
                    ImapDraftRecord(
                        sponsor_name=mail.sponsor_name,
                        to_email=mail.to_email,
                        cc_email=mail.cc_email,
                        subject=mail.subject,
                        mailbox=config.username,
                        drafts_folder=config.drafts_folder,
                        result="draft_created",
                        details="",
                        server_response=response_text,
                    )
                )
            except Exception as exc:
                records.append(
                    ImapDraftRecord(
                        sponsor_name=mail.sponsor_name,
                        to_email=mail.to_email,
                        cc_email=mail.cc_email,
                        subject=mail.subject,
                        mailbox=config.username,
                        drafts_folder=config.drafts_folder,
                        result="error",
                        details=str(exc),
                        server_response="",
                    )
                )
    finally:
        try:
            connection.logout()
        except Exception:
            pass

    return records


def build_imap_draft_log_dataframe(records: list[ImapDraftRecord]) -> pd.DataFrame:
    rows = [
        {
            "Sponsor": record.sponsor_name,
            "To": record.to_email,
            "CC": record.cc_email,
            "Postfach": record.mailbox,
            "Ordner": record.drafts_folder,
            "Ergebnis": record.result,
            "Details": record.details,
            "Server-Antwort": record.server_response,
        }
        for record in records
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "Sponsor",
            "To",
            "CC",
            "Postfach",
            "Ordner",
            "Ergebnis",
            "Details",
            "Server-Antwort",
        ],
    )
