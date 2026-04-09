from __future__ import annotations

import copy
import random
import re
import socket
import smtplib
import time
from collections.abc import Callable
from dataclasses import dataclass
from email import utils as email_utils
from email.message import EmailMessage

from shared.imap_append import ImapAppendConfig, append_message_to_mailbox

DEFAULT_SEND_DELAY_MIN_SECONDS = 3.0
DEFAULT_SEND_DELAY_MAX_SECONDS = 6.0


@dataclass(frozen=True)
class SmtpSendConfig:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    use_starttls: bool = False
    timeout_seconds: int = 30
    delay_between_messages_seconds: float = 0.75
    delay_between_messages_seconds_min: float | None = None
    delay_between_messages_seconds_max: float | None = None


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


@dataclass(frozen=True)
class SmtpSendProgress:
    phase: str
    current_index: int
    total_messages: int
    current_recipient: str
    remaining_messages: int
    completed_messages: int
    estimated_remaining_seconds: float
    current_delay_seconds: float | None = None


def _friendly_smtp_error(raw: str) -> str:
    text = (raw or "").lower()
    if (
        "authentication failed" in text
        or "auth failed" in text
        or "invalid credentials" in text
        or "smtp authentication error" in text
        or "5.7.8" in text
    ):
        return "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen."
    if "starttls" in text or "tls" in text or "ssl" in text:
        return "Die gesicherte Verbindung zum Mailserver ist fehlgeschlagen. Bitte die SMTP-Konfiguration prüfen."
    if "connection refused" in text or "timed out" in text or "getaddrinfo failed" in text or "errno" in text:
        return "Verbindung zum SMTP-Server fehlgeschlagen. Bitte Netzwerk und Serveradresse prüfen."
    if "refused" in text or "rejected" in text:
        return "Mindestens ein Empfänger wurde vom Mailserver abgelehnt."
    return raw


def _normalized_mailbox(value: str) -> str:
    _, addr = email_utils.parseaddr(str(value or ""))
    return (addr or "").strip().lower()


def _smtp_local_hostname() -> str | None:
    raw = (socket.gethostname() or "").strip()
    if not raw:
        return None
    short = raw.split(".", 1)[0].strip()
    if not short:
        return None
    sanitized = re.sub(r"[^A-Za-z0-9-]", "", short)
    return sanitized or None


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
    connect_kwargs = {"timeout": config.timeout_seconds}
    local_hostname = _smtp_local_hostname()
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


def _resolve_delay_range(config: SmtpSendConfig) -> tuple[float, float] | None:
    has_range = (
        config.delay_between_messages_seconds_min is not None
        or config.delay_between_messages_seconds_max is not None
    )
    if has_range:
        min_value = (
            float(config.delay_between_messages_seconds_min)
            if config.delay_between_messages_seconds_min is not None
            else float(config.delay_between_messages_seconds_max or 0)
        )
        max_value = (
            float(config.delay_between_messages_seconds_max)
            if config.delay_between_messages_seconds_max is not None
            else float(config.delay_between_messages_seconds_min or 0)
        )
    else:
        fixed_value = float(config.delay_between_messages_seconds)
        min_value = fixed_value
        max_value = fixed_value

    if min_value <= 0 and max_value <= 0:
        return None

    min_value = max(min_value, 0.0)
    max_value = max(max_value, 0.0)
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    return min_value, max_value


def _next_send_delay_seconds(config: SmtpSendConfig) -> float | None:
    delay_range = _resolve_delay_range(config)
    if delay_range is None:
        return None
    min_value, max_value = delay_range
    if max_value <= 0:
        return None
    if min_value == max_value:
        return max_value
    return random.uniform(min_value, max_value)


def _average_delay_seconds(config: SmtpSendConfig) -> float:
    delay_range = _resolve_delay_range(config)
    if delay_range is None:
        return 0.0
    min_value, max_value = delay_range
    return max((min_value + max_value) / 2.0, 0.0)


def _average_send_seconds(total_send_seconds: float, completed_messages: int) -> float:
    if completed_messages <= 0:
        return 1.0
    return max(total_send_seconds / completed_messages, 1.0)


def _estimate_remaining_seconds_for_sending(
    *,
    total_messages: int,
    current_index: int,
    total_send_seconds: float,
    completed_messages: int,
    average_delay_seconds: float,
) -> float:
    remaining_after_current = max(total_messages - current_index, 0)
    average_send_seconds = _average_send_seconds(total_send_seconds, completed_messages)
    return (
        average_send_seconds
        + (remaining_after_current * average_send_seconds)
        + (remaining_after_current * average_delay_seconds)
    )


def _estimate_remaining_seconds_for_waiting(
    *,
    total_messages: int,
    current_index: int,
    total_send_seconds: float,
    completed_messages: int,
    current_delay_seconds: float,
    average_delay_seconds: float,
) -> float:
    remaining_after_current = max(total_messages - current_index, 0)
    average_send_seconds = _average_send_seconds(total_send_seconds, completed_messages)
    future_delays_after_sleep = max(remaining_after_current - 1, 0)
    return (
        max(current_delay_seconds, 0.0)
        + (remaining_after_current * average_send_seconds)
        + (future_delays_after_sleep * average_delay_seconds)
    )


def _emit_progress(
    progress_callback: Callable[[SmtpSendProgress], None] | None,
    progress: SmtpSendProgress,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress)
    except Exception:
        # Progress reporting is best-effort and must not break the actual send run.
        return


def send_email_messages(
    messages: list[PreparedEmailMessage],
    config: SmtpSendConfig,
    *,
    sent_copy_config: ImapAppendConfig | None = None,
    progress_callback: Callable[[SmtpSendProgress], None] | None = None,
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
    average_delay_seconds = _average_delay_seconds(config)
    total_send_seconds = 0.0

    try:
        total_messages = len(messages)
        for index, item in enumerate(messages):
            current_index = index + 1
            _emit_progress(
                progress_callback,
                SmtpSendProgress(
                    phase="sending",
                    current_index=current_index,
                    total_messages=total_messages,
                    current_recipient=item.to_email,
                    remaining_messages=max(total_messages - current_index, 0),
                    completed_messages=index,
                    estimated_remaining_seconds=_estimate_remaining_seconds_for_sending(
                        total_messages=total_messages,
                        current_index=current_index,
                        total_send_seconds=total_send_seconds,
                        completed_messages=index,
                        average_delay_seconds=average_delay_seconds,
                    ),
                    current_delay_seconds=None,
                ),
            )
            send_started_at = time.perf_counter()
            try:
                header_from = _normalized_mailbox(item.message.get("From", ""))
                if not header_from or header_from != login_mailbox:
                    raise RuntimeError(
                        "Der sichtbare Absender muss mit der SMTP-Anmeldung übereinstimmen."
                    )

                recipients = _envelope_recipients(item.message)
                if not recipients:
                    raise RuntimeError("Es konnte kein gültiger Empfänger für den Versand ermittelt werden.")

                message_to_send = _message_for_transport(item.message)
                refused = connection.send_message(
                    message_to_send,
                    from_addr=login_mailbox or config.username.strip(),
                    to_addrs=recipients,
                )
                if refused:
                    raise RuntimeError("Mindestens ein Empfänger wurde vom Mailserver abgelehnt.")
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
            total_send_seconds += max(time.perf_counter() - send_started_at, 0.0)
            if index < total_messages - 1:
                delay_seconds = _next_send_delay_seconds(config)
                if delay_seconds is not None:
                    _emit_progress(
                        progress_callback,
                        SmtpSendProgress(
                            phase="waiting",
                            current_index=current_index,
                            total_messages=total_messages,
                            current_recipient=item.to_email,
                            remaining_messages=max(total_messages - current_index, 0),
                            completed_messages=current_index,
                            estimated_remaining_seconds=_estimate_remaining_seconds_for_waiting(
                                total_messages=total_messages,
                                current_index=current_index,
                                total_send_seconds=total_send_seconds,
                                completed_messages=current_index,
                                current_delay_seconds=delay_seconds,
                                average_delay_seconds=average_delay_seconds,
                            ),
                            current_delay_seconds=delay_seconds,
                        ),
                    )
                    time.sleep(delay_seconds)
        _emit_progress(
            progress_callback,
            SmtpSendProgress(
                phase="finished",
                current_index=total_messages,
                total_messages=total_messages,
                current_recipient="",
                remaining_messages=0,
                completed_messages=total_messages,
                estimated_remaining_seconds=0.0,
                current_delay_seconds=None,
            ),
        )
    finally:
        try:
            connection.quit()
        except Exception:
            pass

    return results
