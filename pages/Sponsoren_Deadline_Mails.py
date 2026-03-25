from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_searchbox import st_searchbox

from shared.config import ConfigError, load_imap_draft_settings

_SIGNATURES: dict[str, str] = {
    "severin.wagner@mysecurityevent.de": (
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
        '<b><span style="color:#212121;">Severin Wagner | Operations Manager</span></b></p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">&nbsp;</p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
        '<a href="tel:+491793922128" style="color:#0078D4;">+49 179 3922 128</a></p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
        '<br>mysecurityevent GmbH</p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
        'Office: Novalisstra\u00dfe 11</p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
        '10115 Berlin\u00a0|\u00a0<a href="tel:+493052284088" style="color:#0078D4;">+49 30 52284088</a></p>'
        '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
        'Amtsgericht Charlottenburg | HRB244080B</p>'
    ),
}
from sponsor_deadline_mails import (
    DEFAULT_EVENT_CITY,
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    DEFAULT_SHEET_NAME,
    ImapDraftConfig,
    build_imap_draft_log_dataframe,
    create_imap_drafts,
    generate_deadline_mails,
    list_workbook_sheets,
)
from sponsor_deadline_mails.summary_state import (
    SUMMARY_SCHEMA_VERSION,
    build_summary_editor_df,
    ensure_summary_state,
    flush_full_rerun_after_summary_commit,
    get_summary_frozen_base,
    make_summary_callback,
    selected_mail_numbers as get_selected_mail_numbers,
)
from streamlit_ui import render_page_title


st.set_page_config(page_title="Deadline-E-Mails für Sponsoren", layout="wide")

SENDER_EMAIL_SUGGESTIONS = [
    "severin.wagner@mysecurityevent.de",
]
CONFIRM_WORD_DRAFTS = "DRAFTS"


def _init_state() -> None:
    defaults = {
        "sdm_file_token": None,
        "sdm_result": None,
        "sdm_generation_id": 0,
        "sdm_summary_df": None,
        "sdm_summary_view_version": 0,
        "sdm_summary_schema_version": 0,
        "sdm_preview_mail_number": None,
        "sdm_imap_log_records": None,
        "sdm_imap_run_context": None,
        "sdm_imap_run_error": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_generation_state(file_token: str | None = None) -> None:
    st.session_state["sdm_file_token"] = file_token
    st.session_state["sdm_result"] = None
    st.session_state["sdm_generation_id"] = 0
    st.session_state["sdm_summary_df"] = None
    st.session_state["sdm_summary_view_version"] = 0
    st.session_state["sdm_summary_schema_version"] = 0
    st.session_state["sdm_preview_mail_number"] = None
    st.session_state["sdm_imap_log_records"] = None
    st.session_state["sdm_imap_run_context"] = None
    st.session_state["sdm_imap_run_error"] = None


@st.cache_data(show_spinner=False)
def _cached_sheet_names(excel_bytes: bytes) -> list[str]:
    return list_workbook_sheets(excel_bytes)


def _make_file_token(file_name: str, excel_bytes: bytes) -> str:
    digest = hashlib.sha1(excel_bytes).hexdigest()
    return f"{file_name}:{len(excel_bytes)}:{digest}"


def _search_sender_emails(searchterm: str) -> list[str]:
    term = (searchterm or "").strip().lower()
    if not term:
        return SENDER_EMAIL_SUGGESTIONS

    startswith_matches = [
        email for email in SENDER_EMAIL_SUGGESTIONS
        if email.lower().startswith(term)
    ]
    contains_matches = [
        email for email in SENDER_EMAIL_SUGGESTIONS
        if term in email.lower() and email not in startswith_matches
    ]
    return startswith_matches + contains_matches


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


def _mail_label(mail_number: int, mail) -> str:
    return f"{mail_number} - {mail.sponsor_name} ({mail.to_email})"


@st.fragment
def _frag_summary() -> None:
    flush_full_rerun_after_summary_commit(st.session_state, rerun=st.rerun)
    view_version = st.session_state["sdm_summary_view_version"]
    summary_df = st.session_state["sdm_summary_df"]
    base_key = f"sdm_summary_base_{view_version}"
    editor_key = f"sdm_summary_editor_{view_version}"
    frozen_base = get_summary_frozen_base(st.session_state, base_key, summary_df)
    st.data_editor(
        frozen_base,
        key=editor_key,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        on_change=make_summary_callback(st.session_state, editor_key, frozen_base),
        column_config={
            "Ausgewählt": st.column_config.CheckboxColumn("Ausgewählt"),
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

render_page_title("Deadline-E-Mails für Sponsoren")
st.caption(
    "Sponsoren-Datei hochladen, E-Mails erstellen, Vorschau prüfen und Entwürfe direkt im Postfach speichern."
)

if base_imap_config is None:
    st.error(
        "Die Verbindung zum Postfach ist für diese Seite noch nicht eingerichtet. "
        "Bitte lass die technische Konfiguration prüfen."
    )
    st.stop()

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
    st.error(f"Die Datei konnte nicht als Excel-Workbook gelesen werden: {exc}")
    st.stop()

default_sheet_index = sheet_names.index(DEFAULT_SHEET_NAME) if DEFAULT_SHEET_NAME in sheet_names else 0

config_col, date_col, imap_col = st.columns([2, 2, 1.6], gap="large")
with config_col:
    sheet_name = st.selectbox("Excel-Blatt", sheet_names, index=default_sheet_index)
    event_city = st.text_input("Event-Stadt", value=DEFAULT_EVENT_CITY)

with date_col:
    event_start = st.date_input("Event-Start", value=DEFAULT_EVENT_START)
    event_end = st.date_input("Event-Ende", value=DEFAULT_EVENT_END)

with imap_col:
    imap_username = st_searchbox(
        _search_sender_emails,
        help="Mit dieser Adresse werden die Entwürfe in Deinem Postfach gespeichert.",
        key="sdm_sender_email",
        label="E-Mail-Adresse",
        placeholder="vorname.nachname@mysecurityevent.de",
        default="",
        default_use_searchterm=True,
        default_options=SENDER_EMAIL_SUGGESTIONS,
        edit_after_submit="option",
    )
    if imap_username is None:
        imap_username = ""
    imap_password = st.text_input(
        "E-Mail-Passwort",
        type="password",
        help="Das Passwort für dieses Postfach.",
    )
    st.markdown("<div style='margin-top: 1.7rem'></div>", unsafe_allow_html=True)
    generate_clicked = st.button("Generieren", type="primary", use_container_width=True)

if generate_clicked:
    if not isinstance(event_start, date) or not isinstance(event_end, date):
        st.error("Bitte gültige Event-Daten angeben.")
    elif event_end < event_start:
        st.error("Das Event-Ende darf nicht vor dem Event-Start liegen.")
    else:
        try:
            result = generate_deadline_mails(
                excel_bytes=excel_bytes,
                sheet_name=sheet_name,
                event_city=event_city.strip() or DEFAULT_EVENT_CITY,
                event_start=event_start,
                event_end=event_end,
                signature_html=_SIGNATURES.get(imap_username.strip().lower(), ""),
            )
        except Exception as exc:
            st.error(f"Generierung fehlgeschlagen: {exc}")
        else:
            st.session_state["sdm_result"] = result
            st.session_state["sdm_generation_id"] += 1
            st.session_state["sdm_summary_df"] = build_summary_editor_df(result)
            st.session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
            st.session_state["sdm_summary_view_version"] += 1
            st.session_state["sdm_preview_mail_number"] = 1 if result.mails else None
            st.session_state["sdm_imap_log_records"] = None
            st.session_state["sdm_imap_run_context"] = None
            st.session_state["sdm_imap_run_error"] = None

result = st.session_state["sdm_result"]
if result is None:
    st.info("Klicke auf 'Generieren', um die E-Mails zu erstellen und vorab zu prüfen.")
    st.stop()

if not result.mails:
    st.warning("In der Datei wurden keine Sponsoren mit E-Mail-Adresse gefunden.")
    st.stop()

ensure_summary_state(st.session_state, result)
summary_df = st.session_state["sdm_summary_df"]

st.subheader("Zusammenfassung")
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
    st.subheader("Vorschau")
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
    st.subheader("Vorschau der E-Mail")
    components.html(preview_mail.html_body, height=780, scrolling=True)

st.divider()
st.subheader("Entwürfe im Postfach")

selected_mails = [
    mail_by_number[mail_number]
    for mail_number in sorted(selected_mail_numbers)
    if mail_number in mail_by_number
]
selected_count = len(selected_mails)
st.caption("Es werden nur die aktuell ausgewählten Sponsoren berücksichtigt.")
imap_username = imap_username.strip()
drafts_folder = base_imap_config.drafts_folder.strip()
expected_draft_confirmation = f"{CONFIRM_WORD_DRAFTS} {selected_count}"

if not imap_username:
    st.warning("Bitte gib Deine E-Mail-Adresse ein.")
elif not imap_password:
    st.warning("Bitte gib Dein E-Mail-Passwort ein.")
elif not drafts_folder.strip():
    st.error("Der Ordner für Entwürfe ist aktuell nicht richtig eingerichtet. Bitte lass die Konfiguration prüfen.")
elif not selected_mails:
    st.warning("Bitte mindestens einen Sponsor in der Tabelle auswählen.")
else:
    st.info("Die Entwürfe werden in Deinem Postfach gespeichert.")
    draft_confirm_text = st.text_input(
        f"Bestätigung: Bitte exakt {expected_draft_confirmation} eintippen",
        value="",
        help=(
            "Damit nicht versehentlich Entwürfe erzeugt werden. "
            f"Erwartet wird exakt: {expected_draft_confirmation}"
        ),
    )
    allow_draft_run = draft_confirm_text.strip() == expected_draft_confirmation
    if not allow_draft_run:
        st.warning(f"Zum Speichern bitte exakt {expected_draft_confirmation} eingeben.")

    if st.button(
        "Ausgewählte Entwürfe speichern",
        type="primary",
        use_container_width=True,
        disabled=not allow_draft_run,
    ):
        run_started_utc = datetime.now(timezone.utc)
        run_context = {
            "Run-ID": f"SDM-{run_started_utc.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
            "Modus": "DRAFTS",
            "Zeitpunkt UTC": run_started_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "Ausgewählte Mails": selected_count,
            "Sheet": sheet_name,
            "Event": f"{event_city.strip() or DEFAULT_EVENT_CITY} | {event_start.isoformat()} bis {event_end.isoformat()}",
            "Sender": imap_username,
        }
        st.session_state["sdm_imap_log_records"] = None
        st.session_state["sdm_imap_run_context"] = run_context
        st.session_state["sdm_imap_run_error"] = None
        try:
            records = create_imap_drafts(
                selected_mails,
                ImapDraftConfig(
                    host=base_imap_config.host,
                    port=base_imap_config.port,
                    username=imap_username,
                    password=imap_password,
                    drafts_folder=drafts_folder,
                    use_ssl=base_imap_config.use_ssl,
                ),
            )
        except Exception as exc:
            st.session_state["sdm_imap_run_error"] = str(exc)
            st.error(f"Die Entwürfe konnten nicht gespeichert werden: {exc}")
        else:
            st.session_state["sdm_imap_log_records"] = records
            success_count = sum(record.result == "draft_created" for record in records)
            error_count = sum(record.result == "error" for record in records)
            if error_count:
                st.warning(f"Entwürfe gespeichert: {success_count}, Fehler: {error_count}")
            else:
                st.success(f"Entwürfe gespeichert: {success_count}")

imap_log_records = st.session_state.get("sdm_imap_log_records")
imap_run_context = st.session_state.get("sdm_imap_run_context")
imap_run_error = st.session_state.get("sdm_imap_run_error")
if imap_log_records or imap_run_error:
    st.divider()
    st.subheader("Ergebnis")

    if imap_log_records:
        total_count = len(imap_log_records)
        success_count = sum(record.result == "draft_created" for record in imap_log_records)
        error_count = total_count - success_count
    else:
        total_count = int((imap_run_context or {}).get("Ausgewählte Mails", 0))
        success_count = 0
        error_count = total_count

    st.write(
        f"Ergebnisübersicht: Gesamt: **{total_count}** · "
        f"Erfolgreich: **{success_count}** · "
        f"Fehler: **{error_count}**"
    )

    if imap_log_records:
        result_df = build_imap_draft_log_dataframe(imap_log_records)
        for column, value in (imap_run_context or {}).items():
            result_df[column] = value
    else:
        error_row = {
            "Status": "Fehler",
            "Hinweis": imap_run_error or "-",
        }
        for column, value in (imap_run_context or {}).items():
            error_row[column] = value
        result_df = pd.DataFrame([error_row])

    st.dataframe(result_df, use_container_width=True, hide_index=True)
