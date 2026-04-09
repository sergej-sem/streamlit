from __future__ import annotations

import math
from collections.abc import Callable

from shared.smtp_sender import SmtpSendProgress


def _mail_label(count: int) -> str:
    return "Mail" if count == 1 else "Mails"


def format_estimated_seconds(seconds: float | None) -> int:
    return max(0, int(math.ceil(float(seconds or 0.0))))


def smtp_progress_percent(progress: SmtpSendProgress) -> int:
    if progress.total_messages <= 0:
        return 100
    if progress.phase == "finished":
        return 100
    if progress.phase == "waiting":
        ratio = progress.completed_messages / progress.total_messages
    else:
        ratio = (progress.completed_messages + 0.5) / progress.total_messages
    return max(0, min(100, int(round(ratio * 100))))


def describe_smtp_progress(progress: SmtpSendProgress) -> str:
    if progress.phase == "finished":
        return "Versand abgeschlossen."

    recipient = progress.current_recipient or "unbekannten Empfänger"
    remaining = max(progress.remaining_messages, 0)
    remaining_label = _mail_label(remaining)
    eta_seconds = format_estimated_seconds(progress.estimated_remaining_seconds)

    return (
        f"E-Mail an {recipient} wird verarbeitet. "
        f"Noch {remaining} {remaining_label}. "
        f"Insgesamt voraussichtlich {eta_seconds} Sekunden."
    )


def create_streamlit_smtp_progress_reporter() -> Callable[[SmtpSendProgress], None]:
    import streamlit as st

    status_box = st.empty()
    progress_bar = st.progress(0)
    status_box.info("Versand wird vorbereitet ...")

    def _report(progress: SmtpSendProgress) -> None:
        progress_bar.progress(smtp_progress_percent(progress))
        message = describe_smtp_progress(progress)
        if progress.phase == "finished":
            status_box.success(message)
        else:
            status_box.info(message)

    return _report
