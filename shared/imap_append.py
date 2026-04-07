from __future__ import annotations

import imaplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP


@dataclass(frozen=True)
class ImapAppendConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str
    use_ssl: bool = True


def _connect(config: ImapAppendConfig):
    if config.use_ssl:
        return imaplib.IMAP4_SSL(config.host, config.port)
    return imaplib.IMAP4(config.host, config.port)


def _friendly_imap_append_error(raw: str) -> str:
    text = (raw or "").lower()
    if "authenticationfailed" in text or "authentication failed" in text or "invalid credentials" in text:
        return "Sent-Kopie konnte nicht gespeichert werden: Anmeldung am Postfach fehlgeschlagen."
    if "nonexistent" in text or "mailbox does not exist" in text or "no such mailbox" in text:
        return "Sent-Kopie konnte nicht gespeichert werden: Gesendet-Ordner nicht gefunden."
    if "connection refused" in text or "timed out" in text or "errno" in text:
        return "Sent-Kopie konnte nicht gespeichert werden: Verbindung zum Mailserver fehlgeschlagen."
    return f"Sent-Kopie konnte nicht gespeichert werden: {raw}"


def append_message_to_mailbox(
    message: EmailMessage,
    config: ImapAppendConfig,
    *,
    flags: str = "",
) -> None:
    if not config.host.strip():
        raise ValueError("Der Postfach-Server darf nicht leer sein.")
    if not config.username.strip():
        raise ValueError("Die E-Mail-Adresse darf nicht leer sein.")
    if not config.password:
        raise ValueError("Das Passwort darf nicht leer sein.")
    if not config.mailbox.strip():
        raise ValueError("Der Zielordner darf nicht leer sein.")

    raw_message = message.as_bytes(policy=SMTP)

    try:
        connection = _connect(config)
        connection.login(config.username, config.password)
        append_status, append_data = connection.append(
            config.mailbox,
            flags,
            imaplib.Time2Internaldate(time.time()),
            raw_message,
        )
        if append_status != "OK":
            raise RuntimeError(str(append_data))
    except (OSError, RuntimeError, imaplib.IMAP4.error) as exc:
        raise RuntimeError(_friendly_imap_append_error(str(exc))) from exc
    finally:
        try:
            connection.logout()
        except Exception:
            pass
