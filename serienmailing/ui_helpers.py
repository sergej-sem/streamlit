from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from serienmailing.imap_sender import SerienMailResult

MAIL_MODE_DRAFT = "Entw\u00fcrfe"
MAIL_MODE_SEND = "Senden"

_CONFIRM_WORD_DRAFT = "ENTW\u00dcRFE"
_CONFIRM_WORD_SEND = "SENDEN"


def default_mail_text() -> str:
    return "\n\nBeste Gr\u00fc\u00dfe,"


def reset_confirmation_state(state: MutableMapping[str, Any]) -> None:
    state["sm_confirm_input"] = ""
    state["sm_confirm_expected"] = ""


def apply_contacts_state(state: MutableMapping[str, Any], contacts: Any) -> None:
    current_mode = state.get("sm_mail_mode", MAIL_MODE_DRAFT)
    current_text = state.get("sm_mail_text", default_mail_text())
    state["sm_contacts"] = contacts
    state["sm_mail_mode"] = current_mode
    state["sm_mail_text"] = current_text
    state["sm_mail_result"] = None
    reset_confirmation_state(state)


def build_confirmation_phrase(mode: str, count: int) -> str:
    confirm_word = _CONFIRM_WORD_SEND if mode == MAIL_MODE_SEND else _CONFIRM_WORD_DRAFT
    return f"{confirm_word} {count}"


def summarize_mail_results(results: list[SerienMailResult], mode: str) -> tuple[str, str, str, bool]:
    success_status = "sent" if mode == MAIL_MODE_SEND else "draft_created"
    success_label = "Gesendet" if mode == MAIL_MODE_SEND else "Entwurf gespeichert"
    summary_label = "E-Mail(s) gesendet" if mode == MAIL_MODE_SEND else "Entwurf/Entwuerfe gespeichert"

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
