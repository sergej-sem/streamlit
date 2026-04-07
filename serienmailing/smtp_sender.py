from __future__ import annotations

from serienmailing.imap_sender import SerienMail, SerienMailResult
from shared.mail_message import build_email_message
from shared.smtp_sender import (
    PreparedEmailMessage,
    SmtpSendConfig,
    send_email_messages,
)


def send_serienmailing_messages(
    mails: list[SerienMail],
    config: SmtpSendConfig,
) -> list[SerienMailResult]:
    prepared_messages = [
        PreparedEmailMessage(
            to_email=mail.to_email,
            subject=mail.subject,
            message=build_email_message(
                from_email=config.username,
                to_email=mail.to_email,
                subject=mail.subject,
                html_body=mail.html_body,
                attachment_bytes=mail.attachment_bytes,
                attachment_filename=mail.attachment_filename,
            ),
        )
        for mail in mails
    ]

    smtp_results = send_email_messages(prepared_messages, config)
    return [
        SerienMailResult(
            to_email=mail.to_email,
            vorname=mail.vorname,
            firma=mail.firma,
            subject=mail.subject,
            status=result.status,
            details=result.details,
        )
        for mail, result in zip(mails, smtp_results)
    ]
