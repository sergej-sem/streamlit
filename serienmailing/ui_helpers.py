from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from serienmailing.imap_sender import SerienMailResult
from shared.mail_preview import (
    missing_preview_requirements as shared_missing_preview_requirements,
    preview_ready as shared_preview_ready,
)
from shared.mail_rich_text import default_mail_body_html, default_mail_body_text

MAIL_MODE_DRAFT = "Entw\u00fcrfe"
MAIL_MODE_SEND = "Senden"

_CONFIRM_WORD_DRAFT = "ENTW\u00dcRFE"
_CONFIRM_WORD_SEND = "SENDEN"


def default_subject_template() -> str:
    return ""


def default_mail_text() -> str:
    return default_mail_body_text()


def default_mail_body_html_value() -> str:
    return default_mail_body_html()


def reset_confirmation_state(state: MutableMapping[str, Any]) -> None:
    state["sm_confirm_input"] = ""
    state["sm_confirm_expected"] = ""


def apply_contacts_state(state: MutableMapping[str, Any], contacts: Any) -> None:
    current_mode = state.get("sm_mail_mode", MAIL_MODE_DRAFT)
    current_subject = state.get("sm_subject_tpl", default_subject_template())
    current_body_html = state.get("sm_mail_body_html", default_mail_body_html_value())
    state["sm_contacts"] = contacts
    state["sm_mail_mode"] = current_mode
    state["sm_subject_tpl"] = current_subject
    state["sm_mail_body_html"] = current_body_html
    state["sm_mail_result"] = None
    reset_confirmation_state(state)


def missing_preview_requirements(
    *,
    sender_email: str,
    sender_password: str,
    contacts: Any,
    subject: str,
    body_html: str,
) -> tuple[str, ...]:
    has_contacts = getattr(contacts, "empty", True) is False if contacts is not None else False
    return shared_missing_preview_requirements(
        sender_email=sender_email,
        sender_password=sender_password,
        require_password=True,
        has_recipients=has_contacts,
        subject=subject,
        body_html=body_html,
    )


def preview_ready(
    *,
    sender_email: str,
    sender_password: str,
    contacts: Any,
    subject: str,
    body_html: str,
) -> bool:
    has_contacts = getattr(contacts, "empty", True) is False if contacts is not None else False
    return shared_preview_ready(
        sender_email=sender_email,
        sender_password=sender_password,
        require_password=True,
        has_recipients=has_contacts,
        subject=subject,
        body_html=body_html,
    )


def build_confirmation_phrase(mode: str, count: int) -> str:
    confirm_word = _CONFIRM_WORD_SEND if mode == MAIL_MODE_SEND else _CONFIRM_WORD_DRAFT
    return f"{confirm_word} {count}"


def summarize_mail_results(results: list[SerienMailResult], mode: str) -> tuple[str, str, str, bool]:
    success_status = "sent" if mode == MAIL_MODE_SEND else "draft_created"
    success_label = "Gesendet" if mode == MAIL_MODE_SEND else "Entwurf gespeichert"
    summary_label = "E-Mail(s) gesendet" if mode == MAIL_MODE_SEND else "Entwurf/Entwürfe gespeichert"

    ok = sum(1 for result in results if result.status == success_status)
    err = len(results) - ok
    warn = sum(1 for result in results if result.status == success_status and (result.details or "").strip())
    show_hint = any((result.details or "").strip() for result in results)

    message = (
        f"{ok} {summary_label}."
        + (f"  {warn} Hinweis(e)." if warn else "")
        + (f"  {err} Fehler." if err else "")
    )
    if err == 0:
        level = "success"
    elif ok > 0:
        level = "warning"
    else:
        level = "error"
    return level, message, success_label, show_hint
