from __future__ import annotations

from shared.email_validation import is_valid_email_address
from shared.mail_rich_text import editor_html_is_meaningful


def missing_preview_requirements(
    *,
    sender_email: str,
    has_recipients: bool,
    subject: str,
    body_html: str,
    sender_password: str = "",
    require_password: bool = False,
    recipient_label: str = "mindestens ein Empfänger",
) -> tuple[str, ...]:
    missing: list[str] = []
    if not str(sender_email or "").strip():
        missing.append("Absenderadresse")
    elif not is_valid_email_address(sender_email):
        missing.append("gültige Absenderadresse")
    if require_password and not str(sender_password or "").strip():
        missing.append("Passwort")
    if not has_recipients:
        missing.append(recipient_label)
    if not str(subject or "").strip():
        missing.append("Betreff")
    if not editor_html_is_meaningful(body_html):
        missing.append("Nachrichtenbody")
    return tuple(missing)


def preview_ready(**kwargs) -> bool:
    return not missing_preview_requirements(**kwargs)
