from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from shared.config import (
    ConfigError,
    load_imap_draft_settings,
    load_smtp_send_settings,
)
from shared.imap_append import ImapAppendConfig
from shared.mail_content_guard import (
    assess_html_mail_batch,
    assess_html_mail_content,
    evaluate_send_guard,
)
from shared.email_validation import is_valid_email_address
from shared.mail_errors import friendly_with_technical_hint
from shared.mail_errors import friendly_config_issue
from shared.mail_progress import create_streamlit_smtp_progress_reporter
from shared.mail_signatures import signature_html_for_sender
from shared.smtp_sender import (
    DEFAULT_SEND_DELAY_MAX_SECONDS,
    DEFAULT_SEND_DELAY_MIN_SECONDS,
    SmtpSendConfig,
)
from sponsor_deadline_mails import (
    DEFAULT_EVENT_CITY,
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    DEFAULT_SHEET_NAME,
    DeadlineSchedule,
    ImapDraftConfig,
    build_imap_draft_log_dataframe,
    build_smtp_send_log_dataframe,
    create_imap_drafts,
    create_smtp_sends,
    generate_deadline_mails,
    list_workbook_sheets,
)
from sponsor_deadline_mails.events import DEFAULT_EVENT_VENUE, DEFAULT_ONBOARDING_URL
from sponsor_deadline_mails.recipients import invalid_recipient_addresses
from sponsor_deadline_mails.summary_state import (
    SUMMARY_SCHEMA_VERSION,
    build_summary_editor_df,
    ensure_summary_state,
    flush_full_rerun_after_summary_commit,
    get_summary_frozen_base,
    make_summary_callback,
    selected_mail_numbers as get_selected_mail_numbers,
)
from streamlit_ui import render_email_selectbox, render_page_title, render_section_title

st.set_page_config(page_title="Deadline-E-Mails für Sponsoren", layout="wide")

SENDER_EMAIL_SUGGESTIONS = [
    "severin.wagner@mysecurityevent.de",
]
CONFIRM_WORD_DRAFTS = "DRAFTS"
CONFIRM_WORD_SEND = "SENDEN"
MAIL_MODE_OPTIONS = ("Entw\u00fcrfe", "Senden")


def _invalid_selected_mail_addresses(mails) -> list[str]:
    invalid: list[str] = []
    for mail in mails:
        to_email = (mail.to_email or "").strip()
        cc_email = (mail.cc_email or "").strip()
        for address in invalid_recipient_addresses(to_email, required=True):
            invalid.append(f"{mail.sponsor_name}: {address or '-'}")
        for address in invalid_recipient_addresses(cc_email):
            invalid.append(f"{mail.sponsor_name} (Kopie): {address}")
    return invalid


def _init_state() -> None:
    defaults = {
        "sdm_file_token": None,
        "sdm_result": None,
        "sdm_generation_id": 0,
        "sdm_generation_config": None,
        "sdm_summary_df": None,
        "sdm_summary_view_version": 0,
        "sdm_summary_schema_version": 0,
        "sdm_preview_mail_number": None,
        "sdm_mail_log_records": None,
        "sdm_mail_run_context": None,
        "sdm_mail_run_error": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_generation_state(file_token: str | None = None) -> None:
    st.session_state["sdm_file_token"] = file_token
    st.session_state["sdm_result"] = None
    st.session_state["sdm_generation_id"] = 0
    st.session_state["sdm_generation_config"] = None
    st.session_state["sdm_summary_df"] = None
    st.session_state["sdm_summary_view_version"] = 0
    st.session_state["sdm_summary_schema_version"] = 0
    st.session_state["sdm_preview_mail_number"] = None
    st.session_state["sdm_mail_log_records"] = None
    st.session_state["sdm_mail_run_context"] = None
    st.session_state["sdm_mail_run_error"] = None
    for key in list(st.session_state):
        if key.startswith(("sdm_summary_base_", "sdm_summary_editor_", "sdm_confirmation_")):
            del st.session_state[key]
    st.session_state.pop("_sdm_rerun_after_commit", None)


def _event_start_changed() -> None:
    st.session_state["sdm_event_end"] = st.session_state["sdm_event_start"] + timedelta(days=2)


def _sync_event_settings(event_city: str, event_start: date) -> None:
    schedule = DeadlineSchedule.relative_to(event_start)
    previous_anchor = st.session_state.get("sdm_schedule_anchor")
    for field_name in (
        "onboarding_start", "onboarding_end", "materials", "presentation", "participant_list", "meeting_selection"
    ):
        key = f"sdm_{field_name}"
        if previous_anchor != event_start or key not in st.session_state:
            st.session_state[key] = getattr(schedule, field_name)
    st.session_state["sdm_schedule_anchor"] = event_start

    details_anchor = (event_city.strip().casefold(), event_start)
    is_munich = details_anchor[0] in {"münchen", "muenchen", "munich"} and event_start == DEFAULT_EVENT_START
    detail_defaults = {
        "sdm_onboarding_url": DEFAULT_ONBOARDING_URL if is_munich else "",
        "sdm_event_venue": DEFAULT_EVENT_VENUE if is_munich else "",
        "sdm_checkin_start": time(14, 0),
        "sdm_checkin_end": time(16, 0),
    }
    for key, value in detail_defaults.items():
        if st.session_state.get("sdm_details_anchor") != details_anchor or key not in st.session_state:
            st.session_state[key] = value
    st.session_state["sdm_details_anchor"] = details_anchor


@st.cache_data(show_spinner=False)
def _cached_sheet_names(excel_bytes: bytes) -> list[str]:
    return list_workbook_sheets(excel_bytes)


def _make_file_token(file_name: str, excel_bytes: bytes) -> str:
    digest = hashlib.sha1(excel_bytes).hexdigest()
    return f"{file_name}:{len(excel_bytes)}:{digest}"


def _load_base_imap_config() -> ImapDraftConfig | None:
    try:
        settings = load_imap_draft_settings(st.secrets)
    except ConfigError:
        return None

    return ImapDraftConfig(
        host=settings.host,
        port=settings.port,
        username="",
        password="",
        drafts_folder=settings.drafts_folder,
        use_ssl=settings.use_ssl,
    )


def _load_base_sent_folder() -> str | None:
    try:
        settings = load_imap_draft_settings(st.secrets)
    except ConfigError:
        return None
    return settings.sent_folder


def _load_base_smtp_config() -> SmtpSendConfig | None:
    try:
        settings = load_smtp_send_settings(st.secrets)
    except ConfigError:
        return None

    return SmtpSendConfig(
        host=settings.host,
        port=settings.port,
        username="",
        password="",
        use_ssl=settings.use_ssl,
        use_starttls=settings.use_starttls,
        timeout_seconds=settings.timeout_seconds,
        delay_between_messages_seconds_min=DEFAULT_SEND_DELAY_MIN_SECONDS,
        delay_between_messages_seconds_max=DEFAULT_SEND_DELAY_MAX_SECONDS,
    )


def _mail_label(mail_number: int, mail) -> str:
    return f"{mail_number} - {mail.sponsor_name} ({mail.to_email})"


def _show_guard_feedback(feedback) -> None:
    if not getattr(feedback, "message", "").strip():
        return
    text = feedback.message
    if feedback.reasons:
        text += " Gründe: " + "; ".join(feedback.reasons[:3])
    if feedback.level == "error":
        st.error(text)
    elif feedback.level == "warning":
        st.warning(text)
    elif feedback.level == "info":
        st.info(text)
    else:
        st.caption(text)


@st.fragment
def _frag_summary() -> None:
    flush_full_rerun_after_summary_commit(st.session_state, rerun=st.rerun)
    view_version = st.session_state["sdm_summary_view_version"]
    summary_df = st.session_state["sdm_summary_df"]
    base_key = f"sdm_summary_base_{view_version}"
    editor_key = f"sdm_summary_editor_{view_version}"
    frozen_base = get_summary_frozen_base(st.session_state, base_key, summary_df)
    selection_col = frozen_base.columns[0]
    st.data_editor(
        frozen_base,
        key=editor_key,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        on_change=make_summary_callback(st.session_state, editor_key, frozen_base),
        column_config={
            selection_col: st.column_config.CheckboxColumn(selection_col),
            "Sponsor": st.column_config.TextColumn("Sponsor", width="medium"),
            "Sprache": st.column_config.TextColumn("Sprache", width="small"),
            "Paket": st.column_config.TextColumn("Paket", width="small"),
            "E-Mail": st.column_config.TextColumn("E-Mail", width="medium"),
            "Kopie": st.column_config.TextColumn("Kopie", width="medium"),
            "Erhalten": st.column_config.NumberColumn("Erhalten", format="%d", width="small"),
            "Offen": st.column_config.NumberColumn("Offen", format="%d", width="small"),
            "Ausstehend": st.column_config.NumberColumn("Ausstehend", format="%d", width="small"),
            "Empfohlen": st.column_config.NumberColumn("Empfohlen", format="%d", width="small"),
        },
        disabled=["Sponsor", "Sprache", "Paket", "E-Mail", "Kopie", "Erhalten", "Offen", "Ausstehend", "Empfohlen"],
    )


_init_state()

base_imap_config = _load_base_imap_config()
base_sent_folder = _load_base_sent_folder()
base_smtp_config = _load_base_smtp_config()

render_page_title("Deadline-E-Mails für Sponsoren")
st.caption(
    "Sponsoren-Datei hochladen, E-Mails erstellen, Vorschau prüfen und wahlweise als Entwurf speichern oder senden."
)

if base_imap_config is None and base_smtp_config is None:
    st.error(
        friendly_config_issue(
            "Die Mail-Funktion ist aktuell nicht eingerichtet.",
            "Weder IMAP-Drafts noch SMTP-Senden sind konfiguriert.",
        )
    )

uploaded_file = st.file_uploader(
    "Sponsoren-Excel hochladen",
    type=["xlsx"],
    help="Bitte die Sponsoren-Datei im XLSX-Format hochladen. Sie sollte das Blatt `Deals` enthalten.",
)

if uploaded_file is None:
    st.info("Bitte zuerst eine XLSX-Datei hochladen.")
    st.stop()

excel_bytes = uploaded_file.getvalue()
file_token = _make_file_token(uploaded_file.name, excel_bytes)
if st.session_state["sdm_file_token"] != file_token:
    _reset_generation_state(file_token=file_token)

try:
    sheet_names = _cached_sheet_names(excel_bytes)
except Exception as exc:
    st.error(friendly_with_technical_hint("Die Excel-Datei konnte nicht gelesen werden.", exc))
    st.stop()

default_sheet_index = sheet_names.index(DEFAULT_SHEET_NAME) if DEFAULT_SHEET_NAME in sheet_names else 0

config_col, date_col, cred_col = st.columns([2, 2, 1.6], gap="large")
with config_col:
    sheet_name = st.selectbox("Excel-Blatt", sheet_names, index=default_sheet_index, key="sdm_sheet_name")
    event_city = st.text_input("Event-Stadt", value=DEFAULT_EVENT_CITY, key="sdm_event_city")

with date_col:
    event_start = st.date_input(
        "Event-Start", value=DEFAULT_EVENT_START, key="sdm_event_start", on_change=_event_start_changed
    )
    event_end = st.date_input("Event-Ende", value=DEFAULT_EVENT_END, key="sdm_event_end")

with cred_col:
    sender_email = render_email_selectbox(
        "E-Mail-Adresse",
        help="Mit dieser Adresse werden Entwürfe gespeichert oder E-Mails versendet.",
        key="sdm_sender_email",
        suggestions=SENDER_EMAIL_SUGGESTIONS,
        placeholder="vorname.nachname@mysecurityevent.de",
    )
    sender_password = st.text_input(
        "E-Mail-Passwort",
        type="password",
        help="Das Passwort für dieses Postfach.",
    )
    st.markdown("<div style='margin-top: 1.7rem'></div>", unsafe_allow_html=True)
    generate_clicked = st.button("Generieren", type="primary", use_container_width=True)

_sync_event_settings(event_city, event_start)
with st.expander("Deadlines und Eventdetails", expanded=True):
    st.caption(
        "Die Deadlines werden beim Ändern des Eventstarts automatisch verschoben. "
        "Hier kannst Du abweichende Termine, den Onboarding-Link und den Veranstaltungsort festlegen."
    )
    onboarding_col, materials_col, meetings_col = st.columns(3)
    with onboarding_col:
        onboarding_start = st.date_input("Onboarding von", key="sdm_onboarding_start")
        onboarding_end = st.date_input("Onboarding bis", key="sdm_onboarding_end")
        onboarding_url = st.text_input("Onboarding-Link", key="sdm_onboarding_url")
    with materials_col:
        materials = st.date_input(
            "Unterlagen", key="sdm_materials",
            help="LED-Wand-Design, Booklet, Teamkontakte, Vortragsinformationen und Handout/Whitepaper.",
        )
        presentation = st.date_input("Vortragspräsentation", key="sdm_presentation")
        venue = st.text_input("Veranstaltungsort", key="sdm_event_venue")
    with meetings_col:
        participant_list = st.date_input("Teilnehmerliste", key="sdm_participant_list")
        meeting_selection = st.date_input("Gesprächswünsche", key="sdm_meeting_selection")
        checkin_from_col, checkin_to_col = st.columns(2)
        with checkin_from_col:
            checkin_from = st.time_input("Sponsoren-Check-in von", key="sdm_checkin_start")
        with checkin_to_col:
            checkin_to = st.time_input("Sponsoren-Check-in bis", key="sdm_checkin_end")

deadline_schedule = DeadlineSchedule(
    onboarding_start=onboarding_start, onboarding_end=onboarding_end,
    materials=materials, presentation=presentation,
    participant_list=participant_list, meeting_selection=meeting_selection,
)
generation_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
generation_config = (
    file_token, sheet_name, event_city.strip(), event_start, event_end,
    deadline_schedule, onboarding_url.strip(), venue.strip(), checkin_from, checkin_to,
    sender_email.strip().casefold(), generation_date,
)
if (
    st.session_state["sdm_result"] is not None
    and st.session_state["sdm_generation_config"] != generation_config
):
    _reset_generation_state(file_token=file_token)
    st.info("Die Einstellungen wurden geändert. Bitte die E-Mails mit den aktuellen Angaben neu generieren.")

if generate_clicked:
    if not isinstance(event_start, date) or not isinstance(event_end, date):
        st.error("Bitte gültige Event-Daten angeben.")
    elif event_end < event_start:
        st.error("Das Event-Ende darf nicht vor dem Event-Start liegen.")
    elif checkin_to <= checkin_from:
        st.error("Das Ende des Sponsoren-Check-ins muss nach dem Beginn liegen.")
    else:
        try:
            result = generate_deadline_mails(
                excel_bytes=excel_bytes,
                sheet_name=sheet_name,
                event_city=event_city.strip(),
                event_start=event_start,
                event_end=event_end,
                signature_html=signature_html_for_sender(sender_email),
                deadline_schedule=deadline_schedule,
                onboarding_url=onboarding_url.strip(),
                venue=venue.strip(),
                checkin_start=checkin_from.strftime("%H:%M"),
                checkin_end=checkin_to.strftime("%H:%M"),
                today=generation_date,
            )
        except Exception as exc:
            st.error(friendly_with_technical_hint("Die Sponsoren-E-Mails konnten nicht generiert werden.", exc))
        else:
            st.session_state["sdm_result"] = result
            st.session_state["sdm_generation_config"] = generation_config
            st.session_state["sdm_generation_id"] += 1
            st.session_state["sdm_summary_df"] = build_summary_editor_df(result)
            st.session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
            st.session_state["sdm_summary_view_version"] += 1
            st.session_state["sdm_preview_mail_number"] = 1 if result.mails else None
            st.session_state["sdm_mail_log_records"] = None
            st.session_state["sdm_mail_run_context"] = None
            st.session_state["sdm_mail_run_error"] = None

result = st.session_state["sdm_result"]
if result is None:
    st.info("Klicke auf 'Generieren', um die E-Mails zu erstellen und vorab zu prüfen.")
    st.stop()

if not result.mails:
    st.warning("In der Datei wurden keine Sponsoren mit E-Mail-Adresse gefunden.")
    st.stop()

ensure_summary_state(st.session_state, result)
summary_df = st.session_state["sdm_summary_df"]

render_section_title("Zusammenfassung")
st.caption(
    "Die Statusprüfung berücksichtigt auch eindeutig zugeordnete Booklet- und Vortragsinformationen aus den Detailblättern."
)
_frag_summary()
summary_df = st.session_state["sdm_summary_df"]
selected_mail_numbers = get_selected_mail_numbers(summary_df)

st.divider()
preview_col, details_col = st.columns([1.1, 2], gap="large")

mail_by_number = {
    mail_number: mail
    for mail_number, mail in enumerate(result.mails, start=1)
}
preview_options = list(mail_by_number.keys())
default_preview_mail_number = st.session_state.get("sdm_preview_mail_number")
if default_preview_mail_number not in mail_by_number and preview_options:
    st.session_state["sdm_preview_mail_number"] = preview_options[0]

with preview_col:
    render_section_title("Vorschau")
    preview_mail_number = st.selectbox(
        "Sponsor auswählen",
        options=preview_options,
        key="sdm_preview_mail_number",
        format_func=lambda mail_number: _mail_label(mail_number, mail_by_number[mail_number]),
    )

    preview_mail = mail_by_number[preview_mail_number]
    st.markdown(f"**Betreff:** {preview_mail.subject}")
    st.markdown(f"**E-Mail:** `{preview_mail.to_email}`")
    st.markdown(f"**Kopie:** `{preview_mail.cc_email or '-'}`")

with details_col:
    render_section_title("Vorschau der E-Mail")
    components.html(preview_mail.html_body, height=780, scrolling=True)

st.divider()
render_section_title("Versand")

selected_mails = [
    mail_by_number[mail_number]
    for mail_number in sorted(selected_mail_numbers)
    if mail_number in mail_by_number
]
selected_count = len(selected_mails)
st.caption("Es werden nur die aktuell ausgewählten Sponsoren berücksichtigt.")

mail_mode = st.radio(
    "Modus",
    options=MAIL_MODE_OPTIONS,
    index=0,
    horizontal=True,
    key="sdm_mail_mode",
)
is_send_mode = mail_mode == "Senden"
expected_confirmation = f"{CONFIRM_WORD_SEND if is_send_mode else CONFIRM_WORD_DRAFTS} {selected_count}"

sender_email = sender_email.strip()
invalid_selected_addresses = _invalid_selected_mail_addresses(selected_mails)

if not sender_email:
    st.warning("Bitte gib Deine E-Mail-Adresse ein.")
elif not is_valid_email_address(sender_email):
    st.warning("Bitte gib eine gültige E-Mail-Adresse ein.")
elif not sender_password:
    st.warning("Bitte gib Dein E-Mail-Passwort ein.")
elif is_send_mode and base_smtp_config is None:
    st.error(
        friendly_config_issue(
            "Das direkte Senden ist aktuell nicht eingerichtet.",
            "Bitte `mse_smtp_mail_send` in den Secrets prüfen.",
        )
    )
elif is_send_mode and base_imap_config is None:
    st.error(
        friendly_config_issue(
            "Die Sent-Kopie ist aktuell nicht eingerichtet.",
            "Bitte `mse_imap_mail_drafts` in den Secrets prüfen.",
        )
    )
elif (not is_send_mode) and base_imap_config is None:
    st.error(
        friendly_config_issue(
            "Das Speichern von Entwürfen ist aktuell nicht eingerichtet.",
            "Bitte `mse_imap_mail_drafts` in den Secrets prüfen.",
        )
    )
elif (not is_send_mode) and not base_imap_config.drafts_folder.strip():
    st.error(
        friendly_config_issue(
            "Der Entwurfsordner ist aktuell nicht korrekt eingerichtet.",
            "Bitte die IMAP-Draft-Konfiguration prüfen.",
        )
    )
elif not selected_mails:
    st.warning("Bitte mindestens einen Sponsor in der Tabelle auswählen.")
elif invalid_selected_addresses:
    preview = "; ".join(invalid_selected_addresses[:3])
    suffix = f" Beispiele: {preview}" if preview else ""
    st.warning(
        f"Die Auswahl enthält {len(invalid_selected_addresses)} ungültige E-Mail-Adresse(n).{suffix}"
    )
else:
    if is_send_mode:
        st.info("Die ausgewählten E-Mails werden direkt per SMTP versendet.")
    else:
        st.info("Die Entwürfe werden in Deinem Postfach gespeichert.")

    preview_assessment = assess_html_mail_content(preview_mail.subject, preview_mail.html_body)
    _show_guard_feedback(evaluate_send_guard(mail_mode, preview_assessment))

    confirm_text = st.text_input(
        f"Bestätigung: Bitte exakt {expected_confirmation} eintippen",
        value="",
        help=f"Erwartet wird exakt: {expected_confirmation}",
        key=f"sdm_confirmation_{st.session_state['sdm_generation_id']}_{mail_mode}_{selected_count}",
    )
    allow_run = confirm_text.strip() == expected_confirmation
    if not allow_run:
        st.warning(f"Zum Ausführen bitte exakt {expected_confirmation} eingeben.")

    button_label = "Ausgewählte E-Mails senden" if is_send_mode else "Ausgewählte Entwürfe speichern"
    if st.button(
        button_label,
        type="primary",
        use_container_width=True,
        disabled=not allow_run,
    ):
        st.session_state["sdm_mail_log_records"] = None
        st.session_state["sdm_mail_run_context"] = None
        st.session_state["sdm_mail_run_error"] = None
        run_started_utc = datetime.now(timezone.utc)
        if is_send_mode:
            batch_assessment = assess_html_mail_batch(
                (mail.subject, mail.html_body)
                for mail in selected_mails
            )
            batch_feedback = evaluate_send_guard(mail_mode, batch_assessment)
            _show_guard_feedback(batch_feedback)
        else:
            batch_feedback = None

        if not (batch_feedback and batch_feedback.blocked):
            run_context = {
                "Run-ID": f"SDM-{run_started_utc.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
                "Modus": "SENDEN" if is_send_mode else "DRAFTS",
                "Zeitpunkt UTC": run_started_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "Ausgewählte Mails": selected_count,
                "Sheet": result.sheet_name,
                "Event": f"{result.event_city} | {result.event_start.isoformat()} bis {result.event_end.isoformat()}",
                "Sender": sender_email,
            }
            st.session_state["sdm_mail_run_context"] = run_context
            try:
                if is_send_mode:
                    records = create_smtp_sends(
                        selected_mails,
                        SmtpSendConfig(
                            host=base_smtp_config.host,
                            port=base_smtp_config.port,
                            username=sender_email,
                            password=sender_password,
                            use_ssl=base_smtp_config.use_ssl,
                            use_starttls=base_smtp_config.use_starttls,
                            timeout_seconds=base_smtp_config.timeout_seconds,
                            delay_between_messages_seconds_min=base_smtp_config.delay_between_messages_seconds_min,
                            delay_between_messages_seconds_max=base_smtp_config.delay_between_messages_seconds_max,
                        ),
                        sent_copy_config=ImapAppendConfig(
                            host=base_imap_config.host,
                            port=base_imap_config.port,
                            username=sender_email,
                            password=sender_password,
                            mailbox=base_sent_folder or "INBOX.Sent",
                            use_ssl=base_imap_config.use_ssl,
                        ),
                        progress_callback=create_streamlit_smtp_progress_reporter(),
                    )
                else:
                    records = create_imap_drafts(
                        selected_mails,
                        ImapDraftConfig(
                            host=base_imap_config.host,
                            port=base_imap_config.port,
                            username=sender_email,
                            password=sender_password,
                            drafts_folder=base_imap_config.drafts_folder,
                            use_ssl=base_imap_config.use_ssl,
                        ),
                    )
            except Exception as exc:
                error_message = friendly_with_technical_hint(
                    "Die E-Mails konnten nicht gesendet werden."
                    if is_send_mode
                    else "Die Entwürfe konnten nicht gespeichert werden.",
                    exc,
                )
                st.session_state["sdm_mail_run_error"] = error_message
                st.error(error_message)
            else:
                st.session_state["sdm_mail_log_records"] = records
                success_status = "sent" if is_send_mode else "draft_created"
                success_count = sum(record.result == success_status for record in records)
                error_count = sum(record.result == "error" for record in records)
                warning_count = sum(
                    record.result == success_status and bool((record.details or "").strip())
                    for record in records
                )
                if error_count:
                    st.warning(
                        f"{'Gesendet' if is_send_mode else 'Entwürfe gespeichert'}: {success_count}, Hinweise: {warning_count}, Fehler: {error_count}"
                    )
                else:
                    st.success(
                        f"{'Gesendet' if is_send_mode else 'Entwürfe gespeichert'}: {success_count}"
                        + (f", Hinweise: {warning_count}" if warning_count else "")
                    )

mail_log_records = st.session_state.get("sdm_mail_log_records")
mail_run_context = st.session_state.get("sdm_mail_run_context")
mail_run_error = st.session_state.get("sdm_mail_run_error")
if mail_log_records or mail_run_error:
    st.divider()
    render_section_title("Ergebnis")

    mode_label = (mail_run_context or {}).get("Modus", "DRAFTS")
    success_status = "sent" if mode_label == "SENDEN" else "draft_created"
    if mail_log_records:
        total_count = len(mail_log_records)
        success_count = sum(record.result == success_status for record in mail_log_records)
        error_count = total_count - success_count
    else:
        total_count = int((mail_run_context or {}).get("Ausgewählte Mails", 0))
        success_count = 0
        error_count = total_count

    st.write(
        f"Ergebnisübersicht: Gesamt: **{total_count}** · "
        f"Erfolgreich: **{success_count}** · "
        f"Fehler: **{error_count}**"
    )

    if mail_log_records:
        if mode_label == "SENDEN":
            result_df = build_smtp_send_log_dataframe(mail_log_records)
        else:
            result_df = build_imap_draft_log_dataframe(mail_log_records)
        for column, value in (mail_run_context or {}).items():
            result_df[column] = value
    else:
        error_row = {
            "Status": "Fehler",
            "Hinweis": mail_run_error or "-",
        }
        for column, value in (mail_run_context or {}).items():
            error_row[column] = value
        result_df = pd.DataFrame([error_row])

    st.dataframe(result_df, use_container_width=True, hide_index=True)
