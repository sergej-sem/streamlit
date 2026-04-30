from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from serienmailing.eventende import (
    UploadedAttachmentFile,
    assemble_eventende_sponsors,
    build_eventende_serienmails,
    build_eventende_summary_dataframe,
)
from serienmailing.imap_sender import MailConfig, create_serienmailing_drafts
from serienmailing.mail_builder import SENDER_EMAIL_SUGGESTIONS, build_subject
from serienmailing.smtp_sender import send_serienmailing_messages
from serienmailing.ui_helpers import (
    MAIL_MODE_SEND,
    build_confirmation_phrase,
    default_mail_body_html_value,
    default_subject_template,
    missing_preview_requirements,
    preview_ready,
    reset_confirmation_state,
    summarize_mail_results,
)
from shared.config import (
    ConfigError,
    load_imap_draft_settings,
    load_smtp_send_settings,
)
from shared.email_validation import is_valid_email_address
from shared.imap_append import ImapAppendConfig
from shared.mail_content_guard import (
    assess_html_mail_batch,
    assess_html_mail_content,
    evaluate_send_guard,
)
from shared.mail_errors import friendly_config_issue, friendly_with_technical_hint
from shared.mail_progress import create_streamlit_smtp_progress_reporter
from shared.mail_rich_text import (
    editor_html_is_meaningful,
    plain_text_to_editor_html,
    render_final_mail_html,
    render_mail_rich_text_editor,
)
from shared.smtp_sender import (
    DEFAULT_SEND_DELAY_MAX_SECONDS,
    DEFAULT_SEND_DELAY_MIN_SECONDS,
    SmtpSendConfig,
)
from streamlit_ui import render_email_selectbox, render_page_title, render_section_title

st.set_page_config(page_title="Serienmailing Eventende", layout="wide")

_MAIL_MODE_OPTIONS = ("Entwürfe", "Senden")


def _init_state() -> None:
    st.session_state.setdefault("sme_mail_mode", _MAIL_MODE_OPTIONS[0])
    st.session_state.setdefault("sme_mail_result", None)
    st.session_state.setdefault("sme_subject_tpl", default_subject_template())
    if "sme_mail_body_html" not in st.session_state:
        legacy_mail_text = st.session_state.get("sme_mail_text")
        st.session_state["sme_mail_body_html"] = (
            plain_text_to_editor_html(legacy_mail_text)
            if legacy_mail_text is not None
            else default_mail_body_html_value()
        )
    st.session_state.setdefault("sme_confirm_input", "")
    st.session_state.setdefault("sme_confirm_expected", "")
    st.session_state.setdefault("sme_selected_sponsor_rows", None)
    st.session_state.setdefault("sme_preview_sponsor_row", None)


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


def _reset_confirmation_input() -> None:
    reset_confirmation_state(st.session_state)


def _make_uploaded_attachment(uploaded_file) -> UploadedAttachmentFile | None:
    if uploaded_file is None:
        return None
    return UploadedAttachmentFile(name=uploaded_file.name, content=uploaded_file.getvalue())


def _make_uploaded_attachment_list(uploaded_files) -> tuple[UploadedAttachmentFile, ...]:
    return tuple(
        UploadedAttachmentFile(name=uploaded_file.name, content=uploaded_file.getvalue())
        for uploaded_file in (uploaded_files or [])
    )


def _preview_label(sponsor) -> str:
    status = "Bereit" if sponsor.is_ready else "Blockiert"
    return f"{sponsor.sponsor_name} ({sponsor.package}) - {sponsor.to_email} - {status}"


_init_state()

render_page_title("Serienmailing Eventende")
st.caption(
    "Sponsoren-Datei und Eventende-Unterlagen hochladen, Zuordnung prüfen und die Mails anschließend als Entwurf speichern oder senden."
)

imap_host, imap_port, imap_folder, imap_sent_folder, imap_ssl = _load_imap_defaults()
smtp_host, smtp_port, smtp_use_ssl, smtp_use_starttls, smtp_timeout = _load_smtp_defaults()

col_cred_a, col_cred_b = st.columns(2)
with col_cred_a:
    sender_email = render_email_selectbox(
        "E-Mail-Adresse (Absender)",
        key="sme_sender_email",
        suggestions=SENDER_EMAIL_SUGGESTIONS,
        placeholder="vorname.nachname@mysecurityevent.de",
    )
with col_cred_b:
    sender_password = st.text_input("Passwort", type="password", key="sme_sender_password")
if sender_email and not is_valid_email_address(sender_email):
    st.warning("Bitte gib eine gültige Absenderadresse ein.")

st.divider()
render_section_title("Dateien")

workbook_upload = st.file_uploader(
    "Sponsoren-Excel hochladen",
    type=["xlsx"],
    key="sme_workbook_upload",
    help="Bitte die aktuelle 00_Master_Sponsoren_Infos.xlsx hochladen. Verarbeitet wird das Blatt `Deals`.",
)
kontaktliste_upload = st.file_uploader(
    "Kontaktliste hochladen",
    type=["xlsx", "xls"],
    key="sme_kontaktliste_upload",
    help="Diese Datei wird an alle Premium-, Gold- und Platin-Sponsoren angehängt.",
)
gespraechsplan_uploads = st.file_uploader(
    "Gesprächspläne hochladen",
    type=["xlsx", "xls", "pdf"],
    accept_multiple_files=True,
    key="sme_gespraechsplan_uploads",
    help="Erwartete Nomenklatur: Sponsorenname_Gesprächsplan.xlsx/.xls für Premium, Sponsorenname_Gesprächsplan.pdf für Gold/Platin.",
)
vortragsliste_uploads = st.file_uploader(
    "Vortragslisten hochladen",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key="sme_vortragsliste_uploads",
    help="Erwartete Nomenklatur: Sponsorenname_Vortragsliste.xlsx/.xls. Nur für Gold/Platin erforderlich.",
)

if workbook_upload is None:
    st.info("Bitte zuerst die Sponsoren-Excel hochladen.")
    st.stop()

try:
    assembly_result = assemble_eventende_sponsors(
        excel_bytes=workbook_upload.getvalue(),
        kontaktliste=_make_uploaded_attachment(kontaktliste_upload),
        gespraechsplan_files=_make_uploaded_attachment_list(gespraechsplan_uploads),
        vortragsliste_files=_make_uploaded_attachment_list(vortragsliste_uploads),
    )
except Exception as exc:
    st.error(
        friendly_with_technical_hint(
            "Die Sponsoren-Datei oder die Uploads konnten nicht verarbeitet werden.",
            exc,
        )
    )
    st.stop()

if not assembly_result.sponsors:
    st.warning("In der Datei wurden keine aktiven Sponsoren mit Paket Premium, Gold oder Platin und E-Mail-Adresse gefunden.")
    st.stop()

summary_df = build_eventende_summary_dataframe(assembly_result.sponsors)
sponsor_by_row = {sponsor.row_number: sponsor for sponsor in assembly_result.sponsors}
all_sponsor_rows = list(sponsor_by_row.keys())
ready_sponsor_rows = [sponsor.row_number for sponsor in assembly_result.sponsors if sponsor.is_ready]
ready_sponsor_set = set(ready_sponsor_rows)

st.caption(
    f"{len(assembly_result.sponsors)} relevante Sponsoren gefunden. "
    f"{assembly_result.ready_count} bereit, {assembly_result.blocked_count} blockiert, {assembly_result.skipped_count} übersprungen."
)
st.dataframe(summary_df, use_container_width=True, hide_index=True)

current_selection = st.session_state.get("sme_selected_sponsor_rows")
if current_selection is None:
    current_selection = ready_sponsor_rows
else:
    current_selection = [row for row in current_selection if row in ready_sponsor_set]
st.session_state["sme_selected_sponsor_rows"] = current_selection

current_preview_row = st.session_state.get("sme_preview_sponsor_row")
if current_preview_row not in sponsor_by_row and all_sponsor_rows:
    st.session_state["sme_preview_sponsor_row"] = all_sponsor_rows[0]

st.divider()
render_section_title("E-Mail")

subject_tpl = st.text_input(
    "Betreff",
    key="sme_subject_tpl",
    placeholder="z. B. Unterlagen zum Eventende - {firma}",
    help="Platzhalter: {vorname}, {firma}, {email}",
)
mail_body_html = render_mail_rich_text_editor(
    label="Text",
    key="sme_mail_body_html",
    value=st.session_state.get("sme_mail_body_html", default_mail_body_html_value()),
    placeholder="Ihr Text hier ... Platzhalter: {vorname}, {firma}, {email}",
)

preview_contacts = pd.DataFrame(
    [{"vorname": sponsor.contact_first_name, "firma": sponsor.sponsor_name, "email": sponsor.to_email} for sponsor in assembly_result.sponsors if sponsor.is_ready]
)
preview_missing = missing_preview_requirements(
    sender_email=sender_email,
    sender_password=sender_password,
    contacts=preview_contacts,
    subject=subject_tpl,
    body_html=mail_body_html,
)

st.markdown("**Vorschau**")
preview_row_number = st.selectbox(
    "Sponsoren-Vorschau",
    options=all_sponsor_rows,
    key="sme_preview_sponsor_row",
    format_func=lambda row_number: _preview_label(sponsor_by_row[row_number]),
)
preview_sponsor = sponsor_by_row[preview_row_number]
preview_subject = ""
preview_body = ""
if preview_missing:
    st.info("Vorschau noch nicht verfügbar. Es fehlen: " + ", ".join(preview_missing) + ".")
else:
    preview_subject = build_subject(
        subject_tpl,
        preview_sponsor.contact_first_name or preview_sponsor.sponsor_name,
        preview_sponsor.sponsor_name,
        preview_sponsor.to_email,
    )
    preview_body = render_final_mail_html(
        mail_body_html,
        sender_email=sender_email.strip(),
        vorname=preview_sponsor.contact_first_name or preview_sponsor.sponsor_name,
        firma=preview_sponsor.sponsor_name,
        email=preview_sponsor.to_email,
    )
    st.caption(f"Betreff: {preview_subject}")

st.markdown(f"**Paket:** {preview_sponsor.package}")
st.markdown(f"**E-Mail:** `{preview_sponsor.to_email}`")
st.markdown(f"**Kopie:** `{preview_sponsor.cc_email or '-'}`")
attachment_text = "<br>".join(preview_sponsor.attachment_names) if preview_sponsor.attachment_names else "-"
st.markdown("**Anhänge:**  ")
st.markdown(attachment_text, unsafe_allow_html=True)
if preview_sponsor.is_ready:
    st.success("Sponsor ist versandbereit.")
else:
    st.error(preview_sponsor.details or "Sponsor ist nicht versandbereit.")

if preview_body:
    components.html(preview_body, height=420, scrolling=True)
    preview_assessment = assess_html_mail_content(preview_subject, preview_body)
    _show_guard_feedback(evaluate_send_guard(st.session_state.get("sme_mail_mode", _MAIL_MODE_OPTIONS[0]), preview_assessment))

st.divider()
render_section_title("Versand")

selected_sponsor_rows = st.multiselect(
    "Versandbereite Sponsoren auswählen",
    options=ready_sponsor_rows,
    default=st.session_state["sme_selected_sponsor_rows"],
    key="sme_selected_sponsor_rows",
    format_func=lambda row_number: _preview_label(sponsor_by_row[row_number]),
    help="Nur versandbereite Sponsoren erscheinen hier. Blockierte Sponsoren bleiben in der Zusammenfassung sichtbar.",
)
selected_sponsors = tuple(sponsor_by_row[row_number] for row_number in selected_sponsor_rows)

mail_mode = st.radio(
    "Modus",
    options=_MAIL_MODE_OPTIONS,
    index=0,
    horizontal=True,
    key="sme_mail_mode",
    on_change=_reset_confirmation_input,
)
is_send_mode = mail_mode == MAIL_MODE_SEND

expected_confirm = build_confirmation_phrase(mail_mode, len(selected_sponsors))
if st.session_state.get("sme_confirm_expected") != expected_confirm:
    st.session_state["sme_confirm_input"] = ""
    st.session_state["sme_confirm_expected"] = expected_confirm

confirm_input = st.text_input(
    f"Zur Bestätigung eingeben: **{expected_confirm}**",
    placeholder=expected_confirm,
    key="sme_confirm_input",
)
confirmed = confirm_input.strip() == expected_confirm and len(selected_sponsors) > 0

if is_send_mode and not smtp_host:
    st.warning(
        friendly_config_issue(
            "E-Mail-Senden ist aktuell nicht eingerichtet.",
            "Bitte `mse_smtp_mail_send` in den Secrets prüfen.",
        )
    )
elif is_send_mode and not imap_host:
    st.warning(
        friendly_config_issue(
            "Die Sent-Kopie ist aktuell nicht eingerichtet.",
            "Bitte `mse_imap_mail_drafts` in den Secrets prüfen.",
        )
    )
elif (not is_send_mode) and not imap_host:
    st.warning(
        friendly_config_issue(
            "Das Speichern von Entwürfen ist aktuell nicht eingerichtet.",
            "Bitte `mse_imap_mail_drafts` in den Secrets prüfen.",
        )
    )

ready = (
    confirmed
    and is_valid_email_address(sender_email)
    and bool(sender_password)
    and bool(subject_tpl.strip())
    and editor_html_is_meaningful(mail_body_html)
    and bool(selected_sponsors)
    and bool(smtp_host if is_send_mode else imap_host)
    and bool(imap_host if is_send_mode else True)
)

button_label = "E-Mails senden" if is_send_mode else "Entwürfe erstellen"
spinner_label = "Entwürfe werden erstellt ..."

if st.button(button_label, disabled=not ready, type="primary"):
    st.session_state["sme_mail_result"] = None
    mails = build_eventende_serienmails(
        selected_sponsors,
        subject_template=subject_tpl,
        body_html_template=mail_body_html,
        sender_email=sender_email.strip(),
    )

    if is_send_mode:
        batch_assessment = assess_html_mail_batch((mail.subject, mail.html_body) for mail in mails)
        guard_feedback = evaluate_send_guard(mail_mode, batch_assessment)
        _show_guard_feedback(guard_feedback)
        if guard_feedback.blocked:
            mails = []

    if mails:
        try:
            if is_send_mode:
                progress_callback = create_streamlit_smtp_progress_reporter()
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
                        delay_between_messages_seconds_min=DEFAULT_SEND_DELAY_MIN_SECONDS,
                        delay_between_messages_seconds_max=DEFAULT_SEND_DELAY_MAX_SECONDS,
                    ),
                    sent_copy_config=ImapAppendConfig(
                        host=imap_host,
                        port=imap_port,
                        username=sender_email.strip(),
                        password=sender_password,
                        mailbox=imap_sent_folder or "INBOX.Sent",
                        use_ssl=imap_ssl,
                    ),
                    progress_callback=progress_callback,
                )
            else:
                with st.spinner(spinner_label):
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

            result_rows = []
            success_label = "Gesendet" if is_send_mode else "Entwurf gespeichert"
            for sponsor, result in zip(selected_sponsors, results):
                result_rows.append(
                    {
                        "Sponsor": sponsor.sponsor_name,
                        "Paket": sponsor.package,
                        "E-Mail": sponsor.to_email,
                        "Kopie": sponsor.cc_email or "-",
                        "Status": "Fehler" if result.status == "error" else success_label,
                        "Hinweis": (result.details or "").strip() or "-",
                    }
                )
            st.session_state["sme_mail_result"] = {
                "mode": mail_mode,
                "results": results,
                "rows": result_rows,
            }
        except Exception as exc:
            st.error(
                friendly_with_technical_hint(
                    "Die E-Mails konnten nicht gesendet werden."
                    if is_send_mode
                    else "Die Entwürfe konnten nicht erstellt werden.",
                    exc,
                )
            )

mail_result = st.session_state.get("sme_mail_result")
if mail_result:
    result_mode = mail_result.get("mode", _MAIL_MODE_OPTIONS[0])
    results = mail_result.get("results", [])
    result_rows = mail_result.get("rows", [])
    summary_level, summary_text, _, _ = summarize_mail_results(results, result_mode)
    result_df = pd.DataFrame(
        result_rows,
        columns=["Sponsor", "Paket", "E-Mail", "Kopie", "Status", "Hinweis"],
    )
    if summary_level == "success":
        st.success(summary_text)
    elif summary_level == "warning":
        st.warning(summary_text)
    else:
        st.error(summary_text)
    st.dataframe(result_df, use_container_width=True, hide_index=True)
