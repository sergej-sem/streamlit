from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .core import GeneratedMail
from shared.imap_append import ImapAppendConfig
from shared.mail_message import build_email_message
from shared.smtp_sender import (
    PreparedEmailMessage,
    SmtpSendConfig,
    send_email_messages,
)


@dataclass(frozen=True)
class SmtpSendRecord:
    sponsor_name: str
    to_email: str
    cc_email: str
    subject: str
    mailbox: str
    result: str
    details: str


def create_smtp_sends(
    mails: list[GeneratedMail],
    config: SmtpSendConfig,
    *,
    sent_copy_config: ImapAppendConfig | None = None,
) -> list[SmtpSendRecord]:
    prepared_messages = [
        PreparedEmailMessage(
            to_email=mail.to_email,
            subject=mail.subject,
            message=build_email_message(
                from_email=config.username,
                to_email=mail.to_email,
                cc_email=mail.cc_email,
                subject=mail.subject,
                html_body=mail.html_body,
            ),
        )
        for mail in mails
    ]

    smtp_results = send_email_messages(
        prepared_messages,
        config,
        sent_copy_config=sent_copy_config,
    )
    return [
        SmtpSendRecord(
            sponsor_name=mail.sponsor_name,
            to_email=mail.to_email,
            cc_email=mail.cc_email,
            subject=mail.subject,
            mailbox=config.username,
            result=result.status,
            details=result.details,
        )
        for mail, result in zip(mails, smtp_results)
    ]


def build_smtp_send_log_dataframe(records: list[SmtpSendRecord]) -> pd.DataFrame:
    result_labels = {
        "sent": "Gesendet",
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
