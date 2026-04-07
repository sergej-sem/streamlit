from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


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


def _connect(config: SmtpSendConfig):
    if config.use_ssl:
        client = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout_seconds)
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)
    client.ehlo()
    if config.use_starttls:
        client.starttls()
        client.ehlo()
    return client


def send_email_messages(
    messages: list[PreparedEmailMessage],
    config: SmtpSendConfig,
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

    try:
        for item in messages:
            try:
                refused = connection.send_message(item.message)
                if refused:
                    raise RuntimeError("Mindestens ein Empfaenger wurde vom Mailserver abgelehnt.")
                results.append(
                    SmtpSendResult(
                        to_email=item.to_email,
                        subject=item.subject,
                        status="sent",
                        details="",
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
