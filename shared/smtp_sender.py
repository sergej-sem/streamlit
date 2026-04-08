from __future__ import annotations

import copy
import smtplib
from dataclasses import dataclass
from email import utils as email_utils
from email.message import EmailMessage

from shared.imap_append import ImapAppendConfig, append_message_to_mailbox


@dataclass(frozen=True)
class SmtpSendConfig:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    use_starttls: bool = False
    timeout_seconds: int = 30


@dataclass(frozen=True)
class PreparedEmailMessage:
    to_email: str
    subject: str
    message: EmailMessage


@dataclass(frozen=True)
class SmtpSendResult:
    to_email: str
    subject: str
    status: str
    details: str


def _friendly_smtp_error(raw: str) -> str:
    text = (raw or "").lower()
    if (
        "authentication failed" in text
        or "auth failed" in text
        or "invalid credentials" in text
        or "smtp authentication error" in text
        or "5.7.8" in text
    ):
        return "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort pruefen."
    if "starttls" in text or "tls" in text or "ssl" in text:
        return "Die gesicherte Verbindung zum Mailserver ist fehlgeschlagen. Bitte die SMTP-Konfiguration pruefen."
    if "connection refused" in text or "timed out" in text or "getaddrinfo failed" in text or "errno" in text:
        return "Verbindung zum SMTP-Server fehlgeschlagen. Bitte Netzwerk und Serveradresse pruefen."
    if "refused" in text or "rejected" in text:
        return "Mindestens ein Empfaenger wurde vom Mailserver abgelehnt."
    return raw


def _normalized_mailbox(value: str) -> str:
    _, addr = email_utils.parseaddr(str(value or ""))
    return (addr or "").strip().lower()


def _smtp_local_hostname(config: SmtpSendConfig) -> str | None:
    username_addr = _normalized_mailbox(config.username)
    if "@" in username_addr:
        return username_addr.rsplit("@", 1)[-1]
    return (config.host or "").strip() or None


def _envelope_recipients(message: EmailMessage) -> list[str]:
    header_values = [
        value
        for value in (
            str(message.get("To", "") or "").strip(),
            str(message.get("Cc", "") or "").strip(),
            str(message.get("Bcc", "") or "").strip(),
        )
        if value
    ]
    recipients = email_utils.getaddresses(header_values)
    normalized: list[str] = []
    seen: set[str] = set()
    for _, addr in recipients:
        mailbox = (addr or "").strip()
        if not mailbox:
            continue
        key = mailbox.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(mailbox)
    return normalized


def _message_for_transport(message: EmailMessage) -> EmailMessage:
    sanitized = copy.deepcopy(message)
    for header in ("Bcc", "Resent-Bcc"):
        if header in sanitized:
            del sanitized[header]
    return sanitized


def _connect(config: SmtpSendConfig):
    local_hostname = _smtp_local_hostname(config)
    connect_kwargs = {"timeout": config.timeout_seconds}
    if local_hostname:
        connect_kwargs["local_hostname"] = local_hostname
    if config.use_ssl:
        client = smtplib.SMTP_SSL(config.host, config.port, **connect_kwargs)
    else:
        client = smtplib.SMTP(config.host, config.port, **connect_kwargs)
    if local_hostname:
        client.ehlo(local_hostname)
    else:
        client.ehlo()
    if config.use_starttls:
        client.starttls()
        if local_hostname:
            client.ehlo(local_hostname)
        else:
            client.ehlo()
    return client


def send_email_messages(
    messages: list[PreparedEmailMessage],
    config: SmtpSendConfig,
    *,
    sent_copy_config: ImapAppendConfig | None = None,
) -> list[SmtpSendResult]:
    if not config.host.strip():
        raise ValueError("Der SMTP-Server darf nicht leer sein.")
    if not config.username.strip():
        raise ValueError("Die E-Mail-Adresse darf nicht leer sein.")
    if not config.password:
        raise ValueError("Das Passwort darf nicht leer sein.")
    if config.use_ssl and config.use_starttls:
        raise ValueError("SMTP kann nicht gleichzeitig SSL und STARTTLS verwenden.")

    try:
        connection = _connect(config)
        connection.login(config.username, config.password)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError(_friendly_smtp_error(str(exc))) from exc

    results: list[SmtpSendResult] = []
    login_mailbox = _normalized_mailbox(config.username)

    try:
        for item in messages:
            try:
                header_from = _normalized_mailbox(item.message.get("From", ""))
                if not header_from or header_from != login_mailbox:
                    raise RuntimeError(
                        "Der sichtbare Absender muss mit der SMTP-Anmeldung uebereinstimmen."
                    )

                recipients = _envelope_recipients(item.message)
                if not recipients:
                    raise RuntimeError("Es konnte kein gueltiger Empfaenger fuer den Versand ermittelt werden.")

                message_to_send = _message_for_transport(item.message)
                refused = connection.send_message(
                    message_to_send,
                    from_addr=login_mailbox or config.username.strip(),
                    to_addrs=recipients,
                )
                if refused:
                    raise RuntimeError("Mindestens ein Empfaenger wurde vom Mailserver abgelehnt.")
                details = ""
                if sent_copy_config is not None:
                    try:
                        append_message_to_mailbox(message_to_send, sent_copy_config)
                    except Exception as exc:
                        details = str(exc)
                results.append(
                    SmtpSendResult(
                        to_email=item.to_email,
                        subject=item.subject,
                        status="sent",
                        details=details,
                    )
                )
            except Exception as exc:
                results.append(
                    SmtpSendResult(
                        to_email=item.to_email,
                        subject=item.subject,
                        status="error",
                        details=_friendly_smtp_error(str(exc)),
                    )
                )
    finally:
        try:
            connection.quit()
        except Exception:
            pass

    return results
