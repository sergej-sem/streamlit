from __future__ import annotations

import hashlib
from io import BytesIO

import pandas as pd
import streamlit as st

from serienmailing.contacts import (
    COLS,
    ContactColumnMapping,
    apply_contact_editor_changes,
    contacts_from_excel,
    contacts_from_hubspot_raw,
    contacts_from_manual,
    normalize_contact_editor_data,
    recipient_validation_issues,
    split_email_addresses,
    suggest_contact_column_mapping,
    validate_contacts,
)
from serienmailing.imap_sender import MailConfig, SerienMail, create_serienmailing_drafts
from serienmailing.import_reader import read_csv_table
from serienmailing.mail_builder import (
    SENDER_EMAIL_SUGGESTIONS,
    build_subject,
)
from serienmailing.smtp_sender import send_serienmailing_messages
from serienmailing.ui_helpers import (
    MAIL_MODE_SEND,
    apply_contacts_state,
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
from shared.mail_errors import friendly_with_technical_hint
from shared.mail_errors import friendly_config_issue
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

st.set_page_config(page_title="Serienmailing", layout="wide")

_MAIL_MODE_OPTIONS = ("Entw\u00fcrfe", "Senden")


def _init_state() -> None:
    st.session_state.setdefault("sm_contacts", None)
    st.session_state.setdefault("sm_mail_mode", _MAIL_MODE_OPTIONS[0])
    st.session_state.setdefault("sm_mail_result", None)
    st.session_state.setdefault("sm_subject_tpl", default_subject_template())
    if "sm_mail_body_html" not in st.session_state:
        legacy_mail_text = st.session_state.get("sm_mail_text")
        st.session_state["sm_mail_body_html"] = (
            plain_text_to_editor_html(legacy_mail_text)
            if legacy_mail_text is not None
            else default_mail_body_html_value()
        )
    st.session_state.setdefault("sm_confirm_input", "")
    st.session_state.setdefault("sm_confirm_expected", "")
    st.session_state.setdefault("sm_mail_editor_instance", 0)
    st.session_state.setdefault("sm_contacts_editor_instance", 0)
    st.session_state.setdefault("sm_contacts_source", None)
    st.session_state.setdefault("sm_contacts_edited", False)
    st.session_state.setdefault("sm_contacts_edit_notice", None)


def _reset_confirmation_input() -> None:
    reset_confirmation_state(st.session_state)


def _apply_contacts(
    contacts: pd.DataFrame,
    *,
    source: str,
    edited: bool = False,
) -> None:
    apply_contacts_state(st.session_state, contacts)
    st.session_state["sm_contacts_source"] = source
    st.session_state["sm_contacts_edited"] = edited
    st.session_state["sm_contacts_editor_instance"] = (
        int(st.session_state.get("sm_contacts_editor_instance", 0)) + 1
    )
    st.session_state["sm_mail_editor_instance"] = (
        int(st.session_state.get("sm_mail_editor_instance", 0)) + 1
    )


def _sync_contact_editor(editor_key: str, editor_source: pd.DataFrame) -> None:
    updated_contacts = apply_contact_editor_changes(
        editor_source,
        st.session_state.get(editor_key),
    )
    current_contacts = normalize_contact_editor_data(editor_source)
    if updated_contacts.equals(current_contacts):
        return

    current_source = st.session_state.get("sm_contacts_source") or "edited"
    _apply_contacts(
        updated_contacts,
        source=current_source,
        edited=True,
    )
    st.session_state["sm_contacts_edit_notice"] = (
        f"Änderung automatisch übernommen: "
        f"{_count_text(len(updated_contacts), 'Kontakt', 'Kontakte')}."
    )


def _count_text(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _show_import_notice(message: str) -> None:
    if "wurden entfernt" in message:
        st.info(message)
    else:
        st.warning(message)


def _show_recipient_issues(
    contacts: pd.DataFrame,
    *,
    prefix: str,
    correction_hint: str = "Bitte Zuordnung oder Quelldatei korrigieren.",
) -> int:
    issues = recipient_validation_issues(contacts)
    if not issues:
        return 0

    examples = ", ".join(
        f"Kontakt {issue.contact_number}, {issue.field}: {issue.value}"
        for issue in issues[:4]
    )
    suffix = f"; weitere {len(issues) - 4}" if len(issues) > 4 else ""
    st.error(f"{prefix}: {examples}{suffix}. {correction_hint}")
    return len(issues)


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

render_page_title("Serienmailing")

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
if sender_email and not is_valid_email_address(sender_email):
    st.warning("Bitte gib eine gültige Absenderadresse ein.")

st.divider()

render_section_title("Kontakte")

tab_excel, tab_hs, tab_manual = st.tabs(["Excel / CSV", "HubSpot", "Manuell"])

with tab_excel:
    uploaded = st.file_uploader(
        "XLSX- oder CSV-Datei hochladen",
        type=["xlsx", "csv"],
        help="Nach dem Upload kannst du die Spalten für An, CC, Vorname und Firma prüfen und ändern.",
    )
    if uploaded is not None:
        try:
            upload_bytes = uploaded.getvalue()
            upload_key = hashlib.sha256(upload_bytes).hexdigest()[:12]
            if uploaded.name.lower().endswith(".csv"):
                selected_sheet = "CSV"
                raw_df = read_csv_table(upload_bytes)
            else:
                with pd.ExcelFile(BytesIO(upload_bytes)) as workbook:
                    sheet_names = workbook.sheet_names
                default_sheet_index = sheet_names.index("Deals") if "Deals" in sheet_names else 0
                selected_sheet = st.selectbox(
                    "Tabellenblatt",
                    options=sheet_names,
                    index=default_sheet_index,
                    key=f"sm_excel_sheet_{upload_key}",
                    help="Wähle das Tabellenblatt, das die Empfänger- und CC-Spalten enthält.",
                )
                raw_df = pd.read_excel(BytesIO(upload_bytes), sheet_name=selected_sheet)

            columns = list(raw_df.columns)
            if not columns:
                st.warning("Die Datei enthält keine Spalten.")
            else:
                mapping_key = hashlib.sha256(
                    f"{upload_key}|{selected_sheet}".encode("utf-8")
                ).hexdigest()[:12]
                suggested = suggest_contact_column_mapping(columns)

                st.markdown("**Spalten zuordnen**")
                st.caption(
                    "Die Vorschläge wurden aus den Überschriften ermittelt. "
                    "Bitte prüfe sie vor dem Übernehmen."
                )

                col_to, col_cc = st.columns([1, 2])
                with col_to:
                    to_index = columns.index(suggested.email) if suggested.email in columns else None
                    to_column = st.selectbox(
                        "An (erforderlich)",
                        options=columns,
                        index=to_index,
                        placeholder="An-Spalte auswählen ...",
                        key=f"sm_excel_to_{mapping_key}",
                        format_func=str,
                        help="Aus dieser Spalte wird pro Zeile der direkte Empfänger übernommen.",
                    )
                with col_cc:
                    cc_options = [column for column in columns if column != to_column]
                    cc_defaults = [column for column in suggested.cc_email if column in cc_options]
                    cc_state_key = f"sm_excel_cc_{mapping_key}"
                    if cc_state_key in st.session_state:
                        st.session_state[cc_state_key] = [
                            column
                            for column in st.session_state[cc_state_key]
                            if column in cc_options
                        ]
                    cc_columns = st.multiselect(
                        "CC (optional)",
                        options=cc_options,
                        default=cc_defaults,
                        key=cc_state_key,
                        format_func=str,
                        placeholder="Keine CC-Spalte ausgewählt",
                        help=(
                            "Adressen aus allen gewählten Spalten werden pro Zeile zusammengeführt. "
                            "Mehrere Adressen in einer Zelle können mit Komma oder Semikolon getrennt sein. "
                            "CC-Empfänger sind für alle Empfänger sichtbar."
                        ),
                    )
                    if cc_columns:
                        st.caption(
                            "CC-Spalten: "
                            + ", ".join(str(column) for column in cc_columns)
                            + ". CC-Empfänger sind für alle Empfänger sichtbar."
                        )
                    else:
                        st.caption("Keine CC-Spalte ausgewählt.")

                col_firstname, col_company = st.columns(2)
                with col_firstname:
                    firstname_options = [None, *columns]
                    firstname_index = (
                        firstname_options.index(suggested.vorname)
                        if suggested.vorname in firstname_options
                        else 0
                    )
                    firstname_column = st.selectbox(
                        "Vorname (optional)",
                        options=firstname_options,
                        index=firstname_index,
                        key=f"sm_excel_firstname_{mapping_key}",
                        format_func=lambda value: "Nicht zuordnen" if value is None else str(value),
                    )
                with col_company:
                    company_options = [None, *columns]
                    company_index = (
                        company_options.index(suggested.firma)
                        if suggested.firma in company_options
                        else 0
                    )
                    company_column = st.selectbox(
                        "Firma (optional)",
                        options=company_options,
                        index=company_index,
                        key=f"sm_excel_company_{mapping_key}",
                        format_func=lambda value: "Nicht zuordnen" if value is None else str(value),
                    )

                if to_column is not None:
                    contacts, warns = contacts_from_excel(
                        raw_df,
                        mapping=ContactColumnMapping(
                            email=to_column,
                            cc_email=tuple(cc_columns),
                            vorname=firstname_column,
                            firma=company_column,
                        ),
                    )
                    contacts_with_cc = int(
                        contacts["cc_email"].fillna("").astype(str).str.strip().ne("").sum()
                    )
                    cc_address_count = sum(
                        len(split_email_addresses(value))
                        for value in contacts["cc_email"]
                    )
                    mapping_issues = recipient_validation_issues(contacts)
                    invalid_to_count = sum(issue.field == "An" for issue in mapping_issues)
                    invalid_cc_count = sum(issue.field == "CC" for issue in mapping_issues)
                    mapping_signature = hashlib.sha256(
                        repr(
                            (
                                mapping_key,
                                to_column,
                                tuple(cc_columns),
                                firstname_column,
                                company_column,
                            )
                        ).encode("utf-8")
                    ).hexdigest()[:16]
                    mapping_source = f"excel:{mapping_key}:{mapping_signature}"
                    mapping_is_applied = (
                        st.session_state.get("sm_contacts_source") == mapping_source
                    )

                    if mapping_is_applied:
                        applied_contacts = st.session_state.get("sm_contacts")
                        applied_count = (
                            len(applied_contacts)
                            if isinstance(applied_contacts, pd.DataFrame)
                            else len(contacts)
                        )
                        contact_label = "Kontakt" if applied_count == 1 else "Kontakte"
                        edited_suffix = (
                            " und anschließend bearbeitet"
                            if st.session_state.get("sm_contacts_edited")
                            else ""
                        )
                        st.success(
                            f"{applied_count} {contact_label} aus dieser Zuordnung "
                            f"übernommen{edited_suffix}."
                        )
                        if st.session_state.get("sm_contacts_edited") and st.button(
                            "Bearbeitungen verwerfen und erneut aus Datei übernehmen",
                            key=f"btn_excel_reset_{mapping_key}_{mapping_signature}",
                            help="Stellt die Kontaktliste wieder aus der aktuellen Spaltenzuordnung her.",
                        ):
                            _apply_contacts(contacts, source=mapping_source)
                            st.session_state["sm_contacts_edit_notice"] = (
                                "Die Kontaktliste wurde wieder aus der Datei hergestellt."
                            )
                            st.rerun()
                    else:
                        for warning in warns:
                            _show_import_notice(warning)

                        st.caption(
                            " · ".join(
                                (
                                    _count_text(len(contacts), "E-Mail", "E-Mails"),
                                    _count_text(
                                        contacts_with_cc,
                                        "Kontakt mit CC",
                                        "Kontakte mit CC",
                                    ),
                                    _count_text(
                                        cc_address_count,
                                        "CC-Adresse",
                                        "CC-Adressen",
                                    ),
                                    _count_text(
                                        invalid_to_count,
                                        "ungültige An-Adresse",
                                        "ungültige An-Adressen",
                                    ),
                                    _count_text(
                                        invalid_cc_count,
                                        "ungültige CC-Adresse",
                                        "ungültige CC-Adressen",
                                    ),
                                )
                            )
                        )
                        _show_recipient_issues(
                            contacts,
                            prefix="Die Zuordnung enthält ungültige Empfängerwerte",
                        )

                        preview_columns = contacts.rename(
                            columns={
                                "vorname": "Vorname",
                                "firma": "Firma",
                                "email": "An",
                                "cc_email": "CC",
                            }
                        )
                        st.dataframe(
                            preview_columns.head(5),
                            width="stretch",
                            hide_index=True,
                        )
                        if len(contacts) > 5:
                            st.caption("Vorschau: erste 5 Kontakte")

                        apply_button_label = (
                            f"Diese {len(contacts)} Kontakte trotz Empfängerfehler übernehmen"
                            if mapping_issues
                            else f"Diese {len(contacts)} Kontakte übernehmen"
                        )
                        if st.button(
                            apply_button_label,
                            key=f"btn_excel_{mapping_key}_{mapping_signature}",
                            disabled=contacts.empty,
                            help=(
                                "Du kannst den Mailtext vorbereiten; Entwurf und Versand bleiben "
                                "bis zur Korrektur der ungültigen Adresse blockiert."
                                if mapping_issues
                                else None
                            ),
                        ):
                            _apply_contacts(contacts, source=mapping_source)
                            st.rerun()
        except Exception as exc:
            st.error(
                friendly_with_technical_hint(
                    "Die Datei konnte nicht gelesen werden. Bitte prüfe Format und Inhalt.",
                    exc,
                )
            )

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
                        _apply_contacts(
                            contacts,
                            source=f"hubspot:{list_options[selected_label]}",
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(
                            friendly_with_technical_hint(
                                "Die Kontakte aus HubSpot konnten nicht geladen werden.",
                                exc,
                            )
                        )
    except Exception as exc:
        st.warning(friendly_with_technical_hint("HubSpot ist aktuell nicht erreichbar.", exc))

with tab_manual:
    manual_template = pd.DataFrame(
        {"vorname": [""], "firma": [""], "email": [""], "cc_email": [""]}
    )
    edited = st.data_editor(
        manual_template,
        width="stretch",
        num_rows="dynamic",
        hide_index=True,
        key="sm_manual_editor",
        column_config={
            "vorname": st.column_config.TextColumn("Vorname"),
            "firma": st.column_config.TextColumn("Firma"),
            "email": st.column_config.TextColumn("An", required=True),
            "cc_email": st.column_config.TextColumn(
                "CC (optional)",
                help="Mehrere sichtbare CC-Adressen mit Komma oder Semikolon trennen.",
            ),
        },
    )
    if st.button("Diese Kontakte \u00fcbernehmen", key="btn_manual"):
        contacts, warns = contacts_from_manual(edited)
        for warning in warns:
            _show_import_notice(warning)
        _apply_contacts(contacts, source="manual")
        st.rerun()

contacts_df: pd.DataFrame | None = st.session_state["sm_contacts"]
invalid_contact_count = 0

if contacts_df is not None:
    contact_issues = recipient_validation_issues(contacts_df)
    if not contacts_df.empty:
        errors = validate_contacts(contacts_df)
        for error in errors:
            normalized_error = error.casefold()
            if "ungültig" not in normalized_error and "ohne an-adresse" not in normalized_error:
                st.warning(error)
        invalid_contact_count = _show_recipient_issues(
            contacts_df,
            prefix="Diese Kontakte sind noch nicht versandbereit",
            correction_hint="Bitte unten direkt korrigieren oder die betroffene Zeile löschen.",
        )

    edit_notice = st.session_state.pop("sm_contacts_edit_notice", None)
    if edit_notice:
        st.success(edit_notice)

    contacts_with_cc = int(
        contacts_df.get("cc_email", pd.Series(index=contacts_df.index, dtype=str))
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
        .sum()
    )
    cc_address_count = sum(
        len(split_email_addresses(value))
        for value in contacts_df.get("cc_email", pd.Series(index=contacts_df.index, dtype=str))
    )
    st.caption(
        " · ".join(
            (
                _count_text(len(contacts_df), "Kontakt geladen", "Kontakte geladen"),
                _count_text(
                    contacts_with_cc,
                    "Kontakt mit CC",
                    "Kontakte mit CC",
                ),
                _count_text(cc_address_count, "CC-Adresse", "CC-Adressen"),
            )
        )
    )

    with st.expander(
        f"Kontakte prüfen und bearbeiten ({len(contacts_df)})",
        expanded=(
            bool(contact_issues)
            or contacts_df.empty
            or bool(st.session_state.get("sm_contacts_edited"))
        ),
    ):
        st.caption(
            "Zellen direkt bearbeiten. Zum Löschen Zeilen links markieren und das "
            "Papierkorb-Symbol wählen. Neue Kontakte können in der letzten Zeile ergänzt werden. "
            "Änderungen werden automatisch übernommen."
        )
        editor_instance = int(st.session_state.get("sm_contacts_editor_instance", 0))
        editor_key = f"sm_contacts_editor_{editor_instance}"
        editor_source = normalize_contact_editor_data(contacts_df)
        editor_source.insert(0, "contact_number", range(1, len(editor_source) + 1))
        st.data_editor(
            editor_source,
            width="stretch",
            height=min(500, max(220, 38 * (len(editor_source) + 2))),
            num_rows="dynamic",
            hide_index=True,
            disabled=("contact_number",),
            key=editor_key,
            on_change=_sync_contact_editor,
            args=(editor_key, editor_source),
            column_order=("contact_number", *COLS),
            column_config={
                "contact_number": st.column_config.NumberColumn("Nr.", width="small"),
                "vorname": st.column_config.TextColumn("Vorname", width="small"),
                "firma": st.column_config.TextColumn("Firma", width="medium"),
                "email": st.column_config.TextColumn(
                    "An (erforderlich)",
                    width="medium",
                    help="Direkte Empfängeradresse. Ungültige oder leere Werte blockieren den Versand.",
                ),
                "cc_email": st.column_config.TextColumn(
                    "CC (optional)",
                    width="large",
                    help="Mehrere sichtbare CC-Adressen mit Komma oder Semikolon trennen.",
                ),
            },
        )
else:
    st.info("Noch keine Kontakte geladen. Bitte einen Tab oben verwenden.")

st.divider()

render_section_title("E-Mail")

subject_tpl = st.text_input(
    "Betreff",
    key="sm_subject_tpl",
    placeholder="z. B. Einladung - {firma}",
    help="Platzhalter: {vorname}, {firma}, {email}",
)
mail_body_html = render_mail_rich_text_editor(
    label="Text",
    key="sm_mail_body_html",
    value=st.session_state.get("sm_mail_body_html", default_mail_body_html_value()),
    placeholder="Ihr Text hier ... Platzhalter: {vorname}, {firma}, {email}",
    instance_id=st.session_state.get("sm_mail_editor_instance", 0),
)

attachment_file = st.file_uploader("Anhang (optional)", key="sm_attachment")

current_mail_mode = st.session_state.get("sm_mail_mode", _MAIL_MODE_OPTIONS[0])
preview_missing = missing_preview_requirements(
    sender_email=sender_email,
    sender_password=sender_password,
    contacts=contacts_df,
    subject=subject_tpl,
    body_html=mail_body_html,
)
if preview_missing:
    st.info("Vorschau noch nicht verfügbar. Es fehlen: " + ", ".join(preview_missing) + ".")
elif preview_ready(
    sender_email=sender_email,
    sender_password=sender_password,
    contacts=contacts_df,
    subject=subject_tpl,
    body_html=mail_body_html,
):
    st.markdown("**Vorschau**")
    preview_labels = [
        (
            f"{row['vorname']} - {row['email'] or '(An-Adresse fehlt)'}"
            if row["vorname"]
            else (row["email"] or "(An-Adresse fehlt)")
        )
        for _, row in contacts_df.iterrows()
    ]
    preview_idx = st.selectbox(
        "Vorschau für Kontakt",
        options=range(len(preview_labels)),
        format_func=lambda i: preview_labels[i],
        label_visibility="collapsed",
        key=f"sm_preview_contact_{st.session_state.get('sm_contacts_editor_instance', 0)}",
    )
    preview_row = contacts_df.iloc[preview_idx]
    preview_subject = build_subject(subject_tpl, preview_row["vorname"], preview_row["firma"], preview_row["email"])
    preview_body = render_final_mail_html(
        mail_body_html,
        sender_email=sender_email.strip(),
        vorname=preview_row["vorname"],
        firma=preview_row["firma"],
        email=preview_row["email"],
    )
    preview_cc = str(preview_row.get("cc_email", "") or "").strip()
    st.caption(f"An: {preview_row['email']} · CC: {preview_cc or '—'}")
    st.caption(f"Betreff: {preview_subject}")
    with st.container(border=True):
        st.html(preview_body)
    preview_assessment = assess_html_mail_content(preview_subject, preview_body)
    _show_guard_feedback(evaluate_send_guard(current_mail_mode, preview_assessment))

st.divider()

render_section_title("Versand")

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
    f"Zur Bestätigung eingeben: **{expected_confirm}**",
    placeholder=expected_confirm,
    key="sm_confirm_input",
)
confirmed = confirm_input.strip() == expected_confirm and n_contacts > 0

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
    and bool(smtp_host if is_send_mode else imap_host)
    and bool(imap_host if is_send_mode else True)
    and invalid_contact_count == 0
)

remaining_requirements: list[str] = []
if n_contacts == 0:
    remaining_requirements.append("Kontakte übernehmen")
elif invalid_contact_count:
    remaining_requirements.append(
        _count_text(
            invalid_contact_count,
            "ungültigen Empfänger korrigieren",
            "ungültige Empfänger korrigieren",
        )
    )
if not is_valid_email_address(sender_email):
    remaining_requirements.append("gültige Absenderadresse eingeben")
if not sender_password:
    remaining_requirements.append("Passwort eingeben")
if not subject_tpl.strip():
    remaining_requirements.append("Betreff eingeben")
if not editor_html_is_meaningful(mail_body_html):
    remaining_requirements.append("Mailtext eingeben")
if n_contacts > 0 and not confirmed:
    remaining_requirements.append(f"Bestätigung „{expected_confirm}“ eingeben")
if is_send_mode and not smtp_host:
    remaining_requirements.append("SMTP-Konfiguration ergänzen")
if not imap_host:
    remaining_requirements.append(
        "Postfach-Konfiguration für Sent-Kopie ergänzen"
        if is_send_mode
        else "Postfach-Konfiguration für Entwürfe ergänzen"
    )

if remaining_requirements:
    st.caption("Noch offen: " + "; ".join(remaining_requirements) + ".")

button_label = "E-Mails senden" if is_send_mode else "Entwürfe erstellen"
spinner_label = "Entwürfe werden erstellt ..."

if st.button(button_label, disabled=not ready, type="primary"):
    st.session_state["sm_mail_result"] = None
    attachment_bytes = attachment_file.read() if attachment_file else None
    attachment_name = attachment_file.name if attachment_file else None
    mails = [
        SerienMail(
            to_email=row["email"],
            cc_email=str(row.get("cc_email", "") or "").strip(),
            vorname=row["vorname"],
            firma=row["firma"],
            subject=build_subject(subject_tpl, row["vorname"], row["firma"], row["email"]),
            html_body=render_final_mail_html(
                mail_body_html,
                sender_email=sender_email.strip(),
                vorname=row["vorname"],
                firma=row["firma"],
                email=row["email"],
            ),
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_name,
        )
        for _, row in contacts_df.iterrows()
    ]

    if is_send_mode:
        batch_assessment = assess_html_mail_batch(
            (mail.subject, mail.html_body)
            for mail in mails
        )
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
            st.session_state["sm_mail_result"] = {"mode": mail_mode, "results": results}
        except Exception as exc:
            st.error(
                friendly_with_technical_hint(
                    "Die E-Mails konnten nicht gesendet werden."
                    if is_send_mode
                    else "Die Entwürfe konnten nicht erstellt werden.",
                    exc,
                )
            )

mail_result = st.session_state.get("sm_mail_result")
if mail_result:
    result_mode = mail_result.get("mode", "Entwürfe")
    results = mail_result.get("results", [])
    summary_level, summary_text, success_label, show_hint = summarize_mail_results(results, result_mode)

    result_rows = []
    for result in results:
        row = {
            "Vorname": result.vorname,
            "Firma": result.firma,
            "An": result.to_email,
            "CC": getattr(result, "cc_email", "") or "—",
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
    st.dataframe(result_df, width="stretch", hide_index=True)
