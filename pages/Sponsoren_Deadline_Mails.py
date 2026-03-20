from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_searchbox import st_searchbox

from sponsor_deadline_mails import (
    DEFAULT_EVENT_CITY,
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    DEFAULT_SHEET_NAME,
    ImapDraftConfig,
    build_imap_draft_log_dataframe,
    build_summary_dataframe,
    create_imap_drafts,
    generate_deadline_mails,
    list_workbook_sheets,
)


st.set_page_config(page_title="Deadline-E-Mails für Sponsoren", layout="wide")

SUMMARY_COLUMNS = [
    "Ausgewählt",
    "Sponsor",
    "Sprache",
    "Paket",
    "E-Mail",
    "Kopie",
    "Erhalten",
    "Offen",
    "Ausstehend",
    "Empfohlen",
]
SUMMARY_SCHEMA_VERSION = 4
SENDER_EMAIL_SUGGESTIONS = [
    "severin.wagner@mysecurityevent.de",
]


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


@st.cache_data(show_spinner=False)
def _cached_sheet_names(excel_bytes: bytes) -> list[str]:
    return list_workbook_sheets(excel_bytes)


def _make_file_token(file_name: str, excel_bytes: bytes) -> str:
    digest = hashlib.sha1(excel_bytes).hexdigest()
    return f"{file_name}:{len(excel_bytes)}:{digest}"


def _secret_bool(section, key: str, default: bool) -> bool:
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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
    if "mse_imap_mail_drafts" not in st.secrets:
        return None

    section = st.secrets["mse_imap_mail_drafts"]
    required_keys = ("host", "port")
    if not all(key in section for key in required_keys):
        return None

    return ImapDraftConfig(
        host=str(section["host"]).strip(),
        port=int(section["port"]),
        username="",
        password="",
        drafts_folder=str(section.get("drafts_folder", "Drafts")).strip() or "Drafts",
        use_ssl=_secret_bool(section, "use_ssl", True),
    )


def _selected_mail_numbers(summary_df) -> set[int]:
    if summary_df is None or summary_df.empty:
        return set()
    mask = summary_df["Ausgewählt"].fillna(False).astype(bool)
    return {int(mail_number) for mail_number in summary_df.index[mask].tolist()}


def _mail_label(mail_number: int, mail) -> str:
    return f"{mail_number} - {mail.sponsor_name} ({mail.to_email})"


def _build_summary_editor_df(result):
    summary_df = build_summary_dataframe(result).reset_index(drop=True)
    summary_df.index = pd.RangeIndex(start=1, stop=len(summary_df) + 1, step=1)
    summary_df.index.name = "MailNr"
    summary_df.insert(0, "Ausgewählt", True)
    summary_df = summary_df.rename(
        columns={
            "sponsor_name": "Sponsor",
            "language": "Sprache",
            "package": "Paket",
            "to_email": "E-Mail",
            "cc_email": "Kopie",
            "green_count": "Erhalten",
            "red_count": "Offen",
            "yellow_count": "Ausstehend",
            "white_count": "Empfohlen",
        }
    )
    return summary_df[SUMMARY_COLUMNS].copy()


def _summary_needs_rebuild(result) -> bool:
    df = st.session_state.get("sdm_summary_df")
    if not isinstance(df, pd.DataFrame):
        return True
    if st.session_state.get("sdm_summary_schema_version") != SUMMARY_SCHEMA_VERSION:
        return True
    if list(df.columns) != SUMMARY_COLUMNS:
        return True
    expected_index = list(range(1, len(result.mails) + 1))
    if df.index.tolist() != expected_index:
        return True
    return len(df) != len(result.mails)


def _ensure_summary_state(result) -> None:
    if _summary_needs_rebuild(result):
        st.session_state["sdm_summary_df"] = _build_summary_editor_df(result)
        st.session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
        st.session_state["sdm_summary_view_version"] += 1
        if result.mails:
            st.session_state["sdm_preview_mail_number"] = 1


def _get_summary_frozen_base(key: str, initial: pd.DataFrame) -> pd.DataFrame:
    if key not in st.session_state:
        prefix = key.rsplit("_", 1)[0] + "_"
        stale_keys = [candidate for candidate in st.session_state if candidate.startswith(prefix) and candidate != key]
        for candidate in stale_keys:
            del st.session_state[candidate]
        st.session_state[key] = initial.copy()
    return st.session_state[key]


def _sync_summary_selection(editor_key: str, frozen_base: pd.DataFrame) -> None:
    state = st.session_state.get(editor_key)
    if not isinstance(state, dict):
        return

    edited_rows = state.get("edited_rows", {})
    if not edited_rows:
        return

    summary_df = st.session_state["sdm_summary_df"]
    changed = False

    for pos_key, changes in edited_rows.items():
        pos = int(pos_key)
        if pos >= len(frozen_base):
            continue
        mail_number = frozen_base.index[pos]
        if "Ausgewählt" not in changes:
            continue
        new_value = bool(changes["Ausgewählt"])
        if bool(summary_df.at[mail_number, "Ausgewählt"]) != new_value:
            summary_df.at[mail_number, "Ausgewählt"] = new_value
            changed = True

    if changed:
        st.session_state["_sdm_rerun_after_commit"] = True


def _make_summary_callback(editor_key: str, frozen_base: pd.DataFrame):
    def _cb() -> None:
        _sync_summary_selection(editor_key, frozen_base)
    return _cb


def _flush_full_rerun_after_summary_commit() -> None:
    if st.session_state.pop("_sdm_rerun_after_commit", False):
        st.rerun()


@st.fragment
def _frag_summary() -> None:
    _flush_full_rerun_after_summary_commit()
    view_version = st.session_state["sdm_summary_view_version"]
    summary_df = st.session_state["sdm_summary_df"]
    base_key = f"sdm_summary_base_{view_version}"
    editor_key = f"sdm_summary_editor_{view_version}"
    frozen_base = _get_summary_frozen_base(base_key, summary_df)
    st.data_editor(
        frozen_base,
        key=editor_key,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        on_change=_make_summary_callback(editor_key, frozen_base),
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

st.title("Deadline-E-Mails für Sponsoren")
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
    drafts_folder = st.text_input(
        "Ordner für Entwürfe",
        value=base_imap_config.drafts_folder,
        help="Diesen Wert bitte normalerweise nicht ändern. Nur anpassen, wenn Deine Entwürfe in einem anderen Ordner gespeichert werden.",
    )
    st.caption("Die Verbindung zum Postfach ist bereits eingerichtet.")
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
            )
        except Exception as exc:
            st.error(f"Generierung fehlgeschlagen: {exc}")
        else:
            st.session_state["sdm_result"] = result
            st.session_state["sdm_generation_id"] += 1
            st.session_state["sdm_summary_df"] = _build_summary_editor_df(result)
            st.session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
            st.session_state["sdm_summary_view_version"] += 1
            st.session_state["sdm_preview_mail_number"] = 1 if result.mails else None
            st.session_state["sdm_imap_log_records"] = None

result = st.session_state["sdm_result"]
if result is None:
    st.info("Klicke auf 'Generieren', um die E-Mails zu erstellen und vorab zu prüfen.")
    st.stop()

if not result.mails:
    st.warning("In der Datei wurden keine Sponsoren mit E-Mail-Adresse gefunden.")
    st.stop()

_ensure_summary_state(result)
summary_df = st.session_state["sdm_summary_df"]

st.subheader("Zusammenfassung")
_frag_summary()
summary_df = st.session_state["sdm_summary_df"]
selected_mail_numbers = _selected_mail_numbers(summary_df)

st.divider()
preview_col, details_col = st.columns([1.1, 2], gap="large")

mail_by_number = {
    mail_number: mail
    for mail_number, mail in enumerate(result.mails, start=1)
}
label_to_mail_number = {
    _mail_label(mail_number, mail): mail_number
    for mail_number, mail in mail_by_number.items()
}
labels = list(label_to_mail_number.keys())
default_preview_mail_number = st.session_state.get("sdm_preview_mail_number")
if default_preview_mail_number not in mail_by_number:
    default_preview_mail_number = 1
    st.session_state["sdm_preview_mail_number"] = default_preview_mail_number
default_preview_label = next(
    (
        label
        for label, mail_number in label_to_mail_number.items()
        if mail_number == default_preview_mail_number
    ),
    labels[0],
)

with preview_col:
    st.subheader("Vorschau")
    preview_label = st.selectbox(
        "Sponsor auswählen",
        options=labels,
        index=labels.index(default_preview_label),
    )
    preview_mail_number = label_to_mail_number[preview_label]
    st.session_state["sdm_preview_mail_number"] = preview_mail_number

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
st.caption("Es werden nur die aktuell ausgewählten Sponsoren berücksichtigt.")
imap_username = imap_username.strip()

if not imap_username:
    st.warning("Bitte gib Deine E-Mail-Adresse ein.")
elif not imap_password:
    st.warning("Bitte gib Dein E-Mail-Passwort ein.")
elif not drafts_folder.strip():
    st.warning("Bitte gib einen gültigen Ordner für Entwürfe an.")
elif not selected_mails:
    st.warning("Bitte mindestens einen Sponsor in der Tabelle auswählen.")
else:
    st.info(
        "Die Entwürfe werden im Ordner "
        f"`{drafts_folder.strip()}` in Deinem Postfach gespeichert."
    )
    if st.button("Ausgewählte Entwürfe speichern", type="primary", use_container_width=True):
        try:
            records = create_imap_drafts(
                selected_mails,
                ImapDraftConfig(
                    host=base_imap_config.host,
                    port=base_imap_config.port,
                    username=imap_username,
                    password=imap_password,
                    drafts_folder=drafts_folder.strip(),
                    use_ssl=base_imap_config.use_ssl,
                ),
            )
        except Exception as exc:
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
if imap_log_records:
    st.divider()
    st.subheader("Ergebnis")
    st.dataframe(
        build_imap_draft_log_dataframe(imap_log_records),
        use_container_width=True,
        hide_index=True,
    )
