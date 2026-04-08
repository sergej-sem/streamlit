from __future__ import annotations

import pandas as pd
import streamlit as st

from serienmailing.contacts import (
    COLS,
    contacts_from_excel,
    contacts_from_hubspot_raw,
    contacts_from_manual,
    validate_contacts,
)
from serienmailing.imap_sender import MailConfig, SerienMail, create_serienmailing_drafts
from serienmailing.mail_builder import (
    SENDER_EMAIL_SUGGESTIONS,
    SIGNATURE_SEVERIN_HTML,
    build_html_body,
    build_subject,
)
from serienmailing.smtp_sender import send_serienmailing_messages
from serienmailing.ui_helpers import (
    MAIL_MODE_SEND,
    apply_contacts_state,
    build_confirmation_phrase,
    default_mail_text,
    reset_confirmation_state,
    summarize_mail_results,
)
from shared.config import (
    ConfigError,
    load_imap_draft_settings,
    load_smtp_send_settings,
)
from shared.imap_append import ImapAppendConfig
from shared.smtp_sender import SmtpSendConfig
from streamlit_ui import render_email_selectbox

st.set_page_config(page_title="Serienmailing", layout="wide")

_SEVERIN_ADDR = "severin.wagner@mysecurityevent.de"
_MAIL_MODE_OPTIONS = ("Entw\u00fcrfe", "Senden")


def _init_state() -> None:
    st.session_state.setdefault("sm_contacts", None)
    st.session_state.setdefault("sm_mail_mode", _MAIL_MODE_OPTIONS[0])
    st.session_state.setdefault("sm_mail_result", None)
    st.session_state.setdefault("sm_mail_text", default_mail_text())
    st.session_state.setdefault("sm_confirm_input", "")
    st.session_state.setdefault("sm_confirm_expected", "")


def _reset_confirmation_input() -> None:
    reset_confirmation_state(st.session_state)


def _apply_contacts(contacts: pd.DataFrame) -> None:
    apply_contacts_state(st.session_state, contacts)


def _load_imap_defaults() -> tuple[str, int, str, str, bool]:
    try:
        settings = load_imap_draft_settings(st.secrets)
        return settings.host, settings.port, settings.drafts_folder, settings.sent_folder, settings.use_ssl
    except ConfigError:
        return "", 993, "Drafts", "INBOX.Sent", True


def _load_smtp_defaults() -> tuple[str, int, bool, bool, int]:
    try:
        settings = load_smtp_send_settings(st.secrets)
        return (
            settings.host,
            settings.port,
            settings.use_ssl,
            settings.use_starttls,
            settings.timeout_seconds,
        )
    except ConfigError:
        return "", 465, True, False, 30


@st.cache_data(show_spinner="HubSpot-Listen laden ...")
def _cached_contact_lists() -> list[dict]:
    from teilnehmerliste_generator.hubspot_client import get_contact_lists

    return get_contact_lists()


def _load_hubspot_contacts(list_id: str) -> pd.DataFrame:
    from teilnehmerliste_generator.hubspot_client import get_contacts_by_ids, get_list_members

    ids = get_list_members(list_id)
    if not ids:
        return pd.DataFrame(columns=COLS)
    raw = get_contacts_by_ids(ids, ["firstname", "email", "company"])
    return contacts_from_hubspot_raw(raw)


_init_state()

st.title("Serienmailing")

imap_host, imap_port, imap_folder, imap_sent_folder, imap_ssl = _load_imap_defaults()
smtp_host, smtp_port, smtp_use_ssl, smtp_use_starttls, smtp_timeout = _load_smtp_defaults()

col_cred_a, col_cred_b = st.columns(2)
with col_cred_a:
    sender_email = render_email_selectbox(
        "E-Mail-Adresse (Absender)",
        key="sm_sender_email",
        suggestions=SENDER_EMAIL_SUGGESTIONS,
        placeholder="vorname.nachname@mysecurityevent.de",
    )
with col_cred_b:
    sender_password = st.text_input("Passwort", type="password")

st.divider()

st.subheader("Kontakte")

tab_excel, tab_hs, tab_manual = st.tabs(["Excel / CSV", "HubSpot", "Manuell"])

with tab_excel:
    uploaded = st.file_uploader("Excel- oder CSV-Datei hochladen", type=["xlsx", "xls", "csv"])
    if uploaded is not None:
        try:
            if uploaded.name.endswith(".csv"):
                raw_df = pd.read_csv(uploaded)
            else:
                raw_df = pd.read_excel(uploaded)
            contacts, warns = contacts_from_excel(raw_df)
            for warning in warns:
                st.warning(warning)
            if st.button("Diese Kontakte \u00fcbernehmen", key="btn_excel"):
                _apply_contacts(contacts)
                st.rerun()
        except Exception as exc:
            st.error(f"Fehler beim Lesen der Datei: {exc}")

with tab_hs:
    try:
        lists = _cached_contact_lists()
        if not lists:
            st.info("Keine HubSpot-Listen gefunden.")
        else:
            list_options = {item.get("name") or str(item.get("listId", "?")): item.get("listId") for item in lists}
            selected_label = st.selectbox(
                "Liste ausw\u00e4hlen",
                options=list(list_options.keys()),
                index=None,
                placeholder="Bitte Liste ausw\u00e4hlen ...",
            )
            if st.button("Liste laden", key="btn_hs_load", disabled=selected_label is None):
                with st.spinner("Kontakte werden geladen ..."):
                    try:
                        contacts = _load_hubspot_contacts(list_options[selected_label])
                        _apply_contacts(contacts)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"HubSpot-Fehler: {exc}")
    except Exception as exc:
        st.warning(f"HubSpot nicht verf\u00fcgbar: {exc}")

with tab_manual:
    manual_template = pd.DataFrame({"vorname": [""], "firma": [""], "email": [""]})
    edited = st.data_editor(
        manual_template,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="sm_manual_editor",
    )
    if st.button("Diese Kontakte \u00fcbernehmen", key="btn_manual"):
        contacts, warns = contacts_from_manual(edited)
        for warning in warns:
            st.warning(warning)
        _apply_contacts(contacts)
        st.rerun()

contacts_df: pd.DataFrame | None = st.session_state["sm_contacts"]

if contacts_df is not None and not contacts_df.empty:
    errors = validate_contacts(contacts_df)
    for error in errors:
        st.warning(error)
    st.caption(f"{len(contacts_df)} Kontakt(e) geladen")
    st.dataframe(contacts_df, use_container_width=True, hide_index=True)
else:
    st.info("Noch keine Kontakte geladen. Bitte einen Tab oben verwenden.")

st.divider()

st.subheader("E-Mail")

subject_tpl = st.text_input(
    "Betreff",
    placeholder="z. B. Einladung - {firma}",
    help="Platzhalter: {vorname}, {firma}, {email}",
)
mail_text = st.text_area(
    "Text",
    height=200,
    placeholder="Ihr Text hier ...\n\nZeilenumbrueche werden korrekt uebernommen.",
    help="Platzhalter: {vorname}, {firma}, {email}",
    key="sm_mail_text",
)

attachment_file = st.file_uploader("Anhang (optional)", key="sm_attachment")

signature_html = SIGNATURE_SEVERIN_HTML if sender_email.strip().lower() == _SEVERIN_ADDR else ""

if contacts_df is not None and not contacts_df.empty and subject_tpl and mail_text:
    st.markdown("**Vorschau**")
    preview_labels = [
        f"{row['vorname']} - {row['email']}" if row["vorname"] else row["email"]
        for _, row in contacts_df.iterrows()
    ]
    preview_idx = st.selectbox(
        "Vorschau fuer Kontakt",
        options=range(len(preview_labels)),
        format_func=lambda i: preview_labels[i],
        label_visibility="collapsed",
    )
    preview_row = contacts_df.iloc[preview_idx]
    preview_subject = build_subject(subject_tpl, preview_row["vorname"], preview_row["firma"], preview_row["email"])
    preview_body = build_html_body(
        preview_row["vorname"],
        mail_text,
        signature_html,
        preview_row["firma"],
        preview_row["email"],
        closing_text="",
    )
    st.caption(f"Betreff: {preview_subject}")
    st.html(preview_body)

st.divider()

st.subheader("Versand")

mail_mode = st.radio(
    "Modus",
    options=_MAIL_MODE_OPTIONS,
    index=0,
    horizontal=True,
    key="sm_mail_mode",
    on_change=_reset_confirmation_input,
)
is_send_mode = mail_mode == MAIL_MODE_SEND

n_contacts = len(contacts_df) if contacts_df is not None and not contacts_df.empty else 0
expected_confirm = build_confirmation_phrase(mail_mode, n_contacts)
if st.session_state.get("sm_confirm_expected") != expected_confirm:
    st.session_state["sm_confirm_input"] = ""
    st.session_state["sm_confirm_expected"] = expected_confirm

confirm_input = st.text_input(
    f"Zur Bestaetigung eingeben: **{expected_confirm}**",
    placeholder=expected_confirm,
    key="sm_confirm_input",
)
confirmed = confirm_input.strip() == expected_confirm and n_contacts > 0

if is_send_mode and not smtp_host:
    st.warning("SMTP-Konfiguration fehlt. Bitte `mse_smtp_mail_send` in den Secrets pruefen.")
elif is_send_mode and not imap_host:
    st.warning("IMAP-Konfiguration fuer die Sent-Kopie fehlt. Bitte `mse_imap_mail_drafts` in den Secrets pruefen.")
elif (not is_send_mode) and not imap_host:
    st.warning("IMAP-Draft-Konfiguration fehlt. Bitte `mse_imap_mail_drafts` in den Secrets pruefen.")

ready = (
    confirmed
    and bool(sender_email.strip())
    and bool(sender_password)
    and bool(subject_tpl.strip())
    and bool(mail_text.strip())
    and bool(smtp_host if is_send_mode else imap_host)
    and bool(imap_host if is_send_mode else True)
)

button_label = "E-Mails senden" if is_send_mode else "Entwuerfe erstellen"
spinner_label = "E-Mails werden gesendet ..." if is_send_mode else "Entwuerfe werden erstellt ..."

if st.button(button_label, disabled=not ready, type="primary"):
    attachment_bytes = attachment_file.read() if attachment_file else None
    attachment_name = attachment_file.name if attachment_file else None
    mails = [
        SerienMail(
            to_email=row["email"],
            vorname=row["vorname"],
            firma=row["firma"],
            subject=build_subject(subject_tpl, row["vorname"], row["firma"], row["email"]),
            html_body=build_html_body(
                row["vorname"],
                mail_text,
                signature_html,
                row["firma"],
                row["email"],
                closing_text="",
            ),
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_name,
        )
        for _, row in contacts_df.iterrows()
    ]

    with st.spinner(spinner_label):
        try:
            if is_send_mode:
                results = send_serienmailing_messages(
                    mails,
                    SmtpSendConfig(
                        host=smtp_host,
                        port=smtp_port,
                        username=sender_email.strip(),
                        password=sender_password,
                        use_ssl=smtp_use_ssl,
                        use_starttls=smtp_use_starttls,
                        timeout_seconds=smtp_timeout,
                    ),
                    sent_copy_config=ImapAppendConfig(
                        host=imap_host,
                        port=imap_port,
                        username=sender_email.strip(),
                        password=sender_password,
                        mailbox=imap_sent_folder or "INBOX.Sent",
                        use_ssl=imap_ssl,
                    ),
                )
            else:
                results = create_serienmailing_drafts(
                    mails,
                    MailConfig(
                        host=imap_host,
                        port=imap_port,
                        username=sender_email.strip(),
                        password=sender_password,
                        drafts_folder=imap_folder or "Drafts",
                        use_ssl=imap_ssl,
                    ),
                )
            st.session_state["sm_mail_result"] = {"mode": mail_mode, "results": results}
        except Exception as exc:
            st.error(str(exc))

mail_result = st.session_state.get("sm_mail_result")
if mail_result:
    result_mode = mail_result.get("mode", "Entwuerfe")
    results = mail_result.get("results", [])
    summary_level, summary_text, success_label, show_hint = summarize_mail_results(results, result_mode)

    result_rows = []
    for result in results:
        row = {
            "Vorname": result.vorname,
            "Firma": result.firma,
            "E-Mail": result.to_email,
            "Status": "Fehler" if result.status == "error" else success_label,
        }
        if show_hint:
            row["Hinweis"] = (result.details or "").strip() or "-"
        result_rows.append(row)
    result_df = pd.DataFrame(result_rows)
    if summary_level == "success":
        st.success(summary_text)
    elif summary_level == "warning":
        st.warning(summary_text)
    else:
        st.error(summary_text)
    st.dataframe(result_df, use_container_width=True, hide_index=True)
