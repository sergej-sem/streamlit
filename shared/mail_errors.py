from __future__ import annotations

import re

_FRIENDLY_MAIL_PREFIXES = (
    "Anmeldung fehlgeschlagen.",
    "Die gesicherte Verbindung zum Mailserver ist fehlgeschlagen.",
    "Verbindung zum SMTP-Server fehlgeschlagen.",
    "Verbindung zum Mailserver fehlgeschlagen.",
    "Mindestens ein Empfänger wurde vom Mailserver abgelehnt.",
    "Der sichtbare Absender muss mit der SMTP-Anmeldung übereinstimmen.",
    "Es konnte kein gültiger Empfänger für den Versand ermittelt werden.",
    "Der Entwurfs-Ordner konnte im Postfach nicht geöffnet werden.",
    "Der Entwurf konnte nicht im Postfach gespeichert werden.",
    "Sent-Kopie konnte nicht gespeichert werden.",
    "Beim Senden ist ein unerwarteter SMTP-Fehler aufgetreten.",
    "Beim Speichern im Entwurfsordner ist ein unerwarteter Fehler aufgetreten.",
)


def compact_technical_detail(exc_or_detail: object | None) -> str:
    text = str(exc_or_detail or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def looks_like_friendly_mail_message(value: object | None) -> bool:
    text = compact_technical_detail(value)
    if not text:
        return False
    if "Technischer Hinweis:" in text:
        return True
    return any(text.startswith(prefix) for prefix in _FRIENDLY_MAIL_PREFIXES)


def friendly_with_technical_hint(user_message: str, exc_or_detail: object | None) -> str:
    user_text = compact_technical_detail(user_message)
    detail = compact_technical_detail(exc_or_detail)
    if not detail:
        return user_text
    if detail == user_text or detail.startswith(user_text + " "):
        return detail
    if looks_like_friendly_mail_message(detail):
        return f"{user_text} {detail}"
    return f"{user_text} Technischer Hinweis: {detail}"


def friendly_config_issue(user_message: str, technical_detail: object | None = None) -> str:
    return friendly_with_technical_hint(user_message, technical_detail)


def friendly_smtp_transport_error(raw: str) -> str:
    text = compact_technical_detail(raw)
    lowered = text.lower()
    if not text:
        return "Beim Senden ist ein unerwarteter SMTP-Fehler aufgetreten."
    if looks_like_friendly_mail_message(text):
        return text
    if (
        "authentication failed" in lowered
        or "auth failed" in lowered
        or "invalid credentials" in lowered
        or "smtp authentication error" in lowered
        or "5.7.8" in lowered
    ):
        return "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen."
    if "starttls" in lowered or "tls" in lowered or "ssl" in lowered:
        return "Die gesicherte Verbindung zum Mailserver ist fehlgeschlagen. Bitte die SMTP-Konfiguration prüfen."
    if (
        "connection refused" in lowered
        or "timed out" in lowered
        or "getaddrinfo failed" in lowered
        or "errno" in lowered
    ):
        return "Verbindung zum SMTP-Server fehlgeschlagen. Bitte Netzwerk und Serveradresse prüfen."
    if "refused" in lowered or "rejected" in lowered:
        return "Mindestens ein Empfänger wurde vom Mailserver abgelehnt."
    return friendly_with_technical_hint("Beim Senden ist ein unerwarteter SMTP-Fehler aufgetreten.", text)


def friendly_imap_draft_error(raw: str) -> str:
    text = compact_technical_detail(raw)
    lowered = text.lower()
    if not text:
        return "Beim Speichern im Entwurfsordner ist ein unerwarteter Fehler aufgetreten."
    if looks_like_friendly_mail_message(text):
        return text
    if "authenticationfailed" in lowered or "authentication failed" in lowered or "invalid credentials" in lowered:
        return "Anmeldung fehlgeschlagen. Bitte E-Mail-Adresse und Passwort prüfen."
    if "nonexistent" in lowered or "mailbox does not exist" in lowered or "no such mailbox" in lowered:
        return "Der Entwurfs-Ordner konnte im Postfach nicht geöffnet werden. Bitte den Ordnernamen in den Einstellungen prüfen."
    if "connection refused" in lowered or "timed out" in lowered or "errno" in lowered:
        return "Verbindung zum Mailserver fehlgeschlagen. Bitte Netzwerk und Serveradresse prüfen."
    return friendly_with_technical_hint("Beim Speichern im Entwurfsordner ist ein unerwarteter Fehler aufgetreten.", text)


def friendly_imap_append_error(raw: str) -> str:
    text = compact_technical_detail(raw)
    lowered = text.lower()
    if not text:
        return "Sent-Kopie konnte nicht gespeichert werden."
    if looks_like_friendly_mail_message(text):
        return text
    if "authenticationfailed" in lowered or "authentication failed" in lowered or "invalid credentials" in lowered:
        return "Sent-Kopie konnte nicht gespeichert werden: Anmeldung am Postfach fehlgeschlagen."
    if "nonexistent" in lowered or "mailbox does not exist" in lowered or "no such mailbox" in lowered:
        return "Sent-Kopie konnte nicht gespeichert werden: Gesendet-Ordner nicht gefunden."
    if "connection refused" in lowered or "timed out" in lowered or "errno" in lowered:
        return "Sent-Kopie konnte nicht gespeichert werden: Verbindung zum Mailserver fehlgeschlagen."
    return friendly_with_technical_hint("Sent-Kopie konnte nicht gespeichert werden.", text)
