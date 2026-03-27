from __future__ import annotations

import imaplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid
import pandas as pd

from .core import GeneratedMail
from serienmailing.mail_builder import html_to_plain_text


@dataclass(frozen=True)
class ImapDraftConfig:
    host: str
    port: int
    username: str
    password: str
    drafts_folder: str = "Drafts"
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


def _build_message(mail: GeneratedMail, config: ImapDraftConfig) -> bytes:
    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = config.username
    message["To"] = mail.to_email
    if mail.cc_email:
        message["Cc"] = mail.cc_email
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(html_to_plain_text(mail.html_body))
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
        raise ValueError("Der Postfach-Server darf nicht leer sein.")
    if not config.username.strip():
        raise ValueError("Die E-Mail-Adresse darf nicht leer sein.")
    if not config.password:
        raise ValueError("Das E-Mail-Passwort darf nicht leer sein.")
    if not config.drafts_folder.strip():
        raise ValueError("Der Ordner für Entwürfe darf nicht leer sein.")

    connection = _connect(config)
    records: list[ImapDraftRecord] = []

    try:
        login_status, login_data = connection.login(config.username, config.password)
        if login_status != "OK":
            raise RuntimeError(f"Die Anmeldung am Postfach ist fehlgeschlagen: {login_data}")

        select_status, select_data = connection.select(config.drafts_folder)
        if select_status != "OK":
            raise RuntimeError(
                f"Der Ordner '{config.drafts_folder}' konnte im Postfach nicht geöffnet werden: {select_data}"
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
    result_labels = {
        "draft_created": "Entwurf gespeichert",
        "error": "Fehler",
    }
    show_copy = any((record.cc_email or "").strip() for record in records)
    show_hint = any((record.details or "").strip() for record in records)

    rows = []
    for record in records:
        row = {
            "Sponsor": record.sponsor_name,
            "E-Mail": record.to_email,
            "Status": result_labels.get(record.result, record.result),
        }
        if show_copy:
            row["Kopie"] = record.cc_email or "-"
        if show_hint:
            row["Hinweis"] = (record.details or "").strip() or "-"
        rows.append(row)

    columns = ["Sponsor", "E-Mail"]
    if show_copy:
        columns.append("Kopie")
    columns.append("Status")
    if show_hint:
        columns.append("Hinweis")

    return pd.DataFrame(rows, columns=columns)
