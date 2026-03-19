from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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


st.set_page_config(page_title="Sponsoren Deadline Mails", layout="wide")

SUMMARY_COLUMNS = [
    "Ausgewaehlt",
    "Sponsor",
    "Sprache",
    "Paket",
    "To",
    "CC",
    "Gruen",
    "Rot",
    "Gelb",
    "Weiss",
]
SUMMARY_SCHEMA_VERSION = 2


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


def _load_base_imap_config() -> ImapDraftConfig | None:
    if "mse_imap_mail_drafts" not in st.secrets:
        return None

    section = st.secrets["mse_imap_mail_drafts"]
    required_keys = ("host", "port", "username", "password")
    if not all(key in section for key in required_keys):
        return None

    return ImapDraftConfig(
        host=str(section["host"]).strip(),
        port=int(section["port"]),
        username=str(section["username"]).strip(),
        password=str(section["password"]),
        drafts_folder=str(section.get("drafts_folder", "Drafts")).strip() or "Drafts",
        from_address=str(section.get("from_address", section["username"])).strip(),
        use_ssl=_secret_bool(section, "use_ssl", True),
    )


def _selected_mail_numbers(summary_df) -> set[int]:
    if summary_df is None or summary_df.empty:
        return set()
    mask = summary_df["Ausgewaehlt"].fillna(False).astype(bool)
    return {int(mail_number) for mail_number in summary_df.index[mask].tolist()}


def _mail_label(mail_number: int, mail) -> str:
    return f"{mail_number} - {mail.sponsor_name} ({mail.to_email})"


def _build_summary_editor_df(result):
    summary_df = build_summary_dataframe(result).reset_index(drop=True)
    summary_df.index = pd.RangeIndex(start=1, stop=len(summary_df) + 1, step=1)
    summary_df.index.name = "MailNr"
    summary_df.insert(0, "Ausgewaehlt", True)
    summary_df = summary_df.rename(
        columns={
            "sponsor_name": "Sponsor",
            "language": "Sprache",
            "package": "Paket",
            "to_email": "To",
            "cc_email": "CC",
            "green_count": "Gruen",
            "red_count": "Rot",
            "yellow_count": "Gelb",
            "white_count": "Weiss",
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
        if "Ausgewaehlt" not in changes:
            continue
        new_value = bool(changes["Ausgewaehlt"])
        if bool(summary_df.at[mail_number, "Ausgewaehlt"]) != new_value:
            summary_df.at[mail_number, "Ausgewaehlt"] = new_value
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
            "Ausgewaehlt": st.column_config.CheckboxColumn("Ausgewaehlt"),
            "Sponsor": st.column_config.TextColumn("Sponsor", width="medium"),
            "Sprache": st.column_config.TextColumn("Sprache", width="small"),
            "Paket": st.column_config.TextColumn("Paket", width="small"),
            "To": st.column_config.TextColumn("To", width="medium"),
            "CC": st.column_config.TextColumn("CC", width="medium"),
            "Gruen": st.column_config.NumberColumn("Gruen", format="%d", width="small"),
            "Rot": st.column_config.NumberColumn("Rot", format="%d", width="small"),
            "Gelb": st.column_config.NumberColumn("Gelb", format="%d", width="small"),
            "Weiss": st.column_config.NumberColumn("Weiss", format="%d", width="small"),
        },
        disabled=["Sponsor", "Sprache", "Paket", "To", "CC", "Gruen", "Rot", "Gelb", "Weiss"],
    )


_init_state()

base_imap_config = _load_base_imap_config()

st.title("Sponsoren Deadline Mails")
st.caption(
    "Excel hochladen, Mails generieren, HTML pruefen und serverseitige Entwuerfe "
    "per IMAP direkt im Drafts-Ordner des cPanel-Postfachs anlegen."
)

if base_imap_config is None:
    st.error(
        "IMAP ist fuer diese Seite noch nicht konfiguriert. "
        "Erwartet wird ein Secret-Block `mse_imap_mail_drafts` mit `host`, `port`, "
        "`username`, `password` und optional `drafts_folder`, `from_address`, `use_ssl`."
    )
    st.stop()

uploaded_file = st.file_uploader(
    "Sponsoren-Excel hochladen",
    type=["xlsx"],
    help="Erwartet dieselbe Struktur wie das Ursprungsskript mit dem Sheet 'Deals'.",
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
    drafts_folder = st.text_input(
        "Drafts-Ordner",
        value=base_imap_config.drafts_folder,
        help="Der exakte IMAP-Ordnername fuer Entwuerfe, z. B. `Drafts`, `Entwuerfe` oder `INBOX.Drafts`.",
    )
    st.caption(f"Konfiguriertes IMAP-Postfach: `{base_imap_config.username}`")
    st.markdown("<div style='margin-top: 1.7rem'></div>", unsafe_allow_html=True)
    generate_clicked = st.button("Generieren", type="primary", use_container_width=True)

if generate_clicked:
    if not isinstance(event_start, date) or not isinstance(event_end, date):
        st.error("Bitte gueltige Event-Daten angeben.")
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
    st.info("Mit 'Generieren' wird ein in-memory Snapshot fuer Vorschau und Draft-Erstellung erstellt.")
    st.stop()

if not result.mails:
    st.warning("Es wurden keine gueltigen Sponsoren mit Empfaenger-E-Mail gefunden.")
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
        "Sponsor auswaehlen",
        options=labels,
        index=labels.index(default_preview_label),
    )
    preview_mail_number = label_to_mail_number[preview_label]
    st.session_state["sdm_preview_mail_number"] = preview_mail_number

    preview_mail = mail_by_number[preview_mail_number]
    st.markdown(f"**Betreff:** {preview_mail.subject}")
    st.markdown(f"**To:** `{preview_mail.to_email}`")
    st.markdown(f"**CC:** `{preview_mail.cc_email or '-'}`")

with details_col:
    st.subheader("HTML-Vorschau")
    components.html(preview_mail.html_body, height=780, scrolling=True)

st.divider()
st.subheader("IMAP Drafts")

selected_mails = [
    mail_by_number[mail_number]
    for mail_number in sorted(selected_mail_numbers)
    if mail_number in mail_by_number
]
st.caption("Die Draft-Erstellung verarbeitet nur die aktuell in der Tabelle ausgewaehlten Sponsoren.")

if not drafts_folder.strip():
    st.warning("Bitte einen gueltigen Drafts-Ordner angeben.")
elif not selected_mails:
    st.warning("Bitte mindestens einen Sponsor in der Tabelle auswaehlen.")
else:
    st.info(
        "Die Entwuerfe werden per IMAP im Ordner "
        f"`{drafts_folder.strip()}` des Postfachs `{base_imap_config.username}` angelegt."
    )
    if st.button("Ausgewaehlte Drafts im Postfach anlegen", type="primary", use_container_width=True):
        try:
            records = create_imap_drafts(
                selected_mails,
                ImapDraftConfig(
                    host=base_imap_config.host,
                    port=base_imap_config.port,
                    username=base_imap_config.username,
                    password=base_imap_config.password,
                    drafts_folder=drafts_folder.strip(),
                    from_address=base_imap_config.from_address,
                    use_ssl=base_imap_config.use_ssl,
                ),
            )
        except Exception as exc:
            st.error(f"Draft-Erstellung fehlgeschlagen: {exc}")
        else:
            st.session_state["sdm_imap_log_records"] = records
            success_count = sum(record.result == "draft_created" for record in records)
            error_count = sum(record.result == "error" for record in records)
            if error_count:
                st.warning(f"Entwuerfe erstellt: {success_count}, Fehler: {error_count}")
            else:
                st.success(f"Entwuerfe erstellt: {success_count}")

imap_log_records = st.session_state.get("sdm_imap_log_records")
if imap_log_records:
    st.divider()
    st.subheader("Draft-Protokoll")
    st.dataframe(
        build_imap_draft_log_dataframe(imap_log_records),
        use_container_width=True,
        hide_index=True,
    )
