from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_searchbox import st_searchbox

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
from shared.config import ConfigError, load_imap_draft_settings

st.set_page_config(page_title="Serienmailing", layout="wide")

_CONFIRM_WORD = "ENTWÜRFE"
_SEVERIN_ADDR = "severin.wagner@mysecurityevent.de"



def _search_sender_emails(searchterm: str) -> list[str]:
    term = (searchterm or "").strip().lower()
    if not term:
        return SENDER_EMAIL_SUGGESTIONS
    startswith = [e for e in SENDER_EMAIL_SUGGESTIONS if e.lower().startswith(term)]
    contains   = [e for e in SENDER_EMAIL_SUGGESTIONS if term in e.lower() and e not in startswith]
    return startswith + contains


def _init_state() -> None:
    st.session_state.setdefault("sm_contacts", None)
    st.session_state.setdefault("sm_draft_result", None)


def _load_imap_defaults() -> tuple[str, int, str, bool]:
    """Return (host, port, drafts_folder, use_ssl) from secrets or empty defaults."""
    try:
        s = load_imap_draft_settings(st.secrets)
        return s.host, s.port, s.drafts_folder, s.use_ssl
    except ConfigError:
        return "", 993, "Drafts", True


@st.cache_data(show_spinner="HubSpot-Listen laden …")
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


# ──────────────────────────────────────────────────────────────────────────────
_init_state()

st.title("Serienmailing")

# ── 1. IMAP-Zugangsdaten ──────────────────────────────────────────────────────
# host/port/folder/ssl kommen aus st.secrets ([mse_imap_mail_drafts]) — unsichtbar für den Benutzer
imap_host, imap_port, imap_folder, imap_ssl = _load_imap_defaults()

col_cred_a, col_cred_b = st.columns(2)
with col_cred_a:
    imap_user = st_searchbox(
        _search_sender_emails,
        key="sm_sender_email",
        label="E-Mail-Adresse (Absender)",
        placeholder="vorname.nachname@mysecurityevent.de",
        default="",
        default_use_searchterm=True,
        default_options=SENDER_EMAIL_SUGGESTIONS,
        edit_after_submit="option",
    )
    imap_user = imap_user or ""
with col_cred_b:
    imap_pass = st.text_input("Passwort", type="password")

st.divider()

# ── 2. Kontakte ───────────────────────────────────────────────────────────────
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
            for w in warns:
                st.warning(w)
            if st.button("Diese Kontakte übernehmen", key="btn_excel"):
                st.session_state["sm_contacts"] = contacts
                st.session_state["sm_draft_result"] = None
                st.rerun()
        except Exception as exc:
            st.error(f"Fehler beim Lesen der Datei: {exc}")

with tab_hs:
    try:
        lists = _cached_contact_lists()
        if not lists:
            st.info("Keine HubSpot-Listen gefunden.")
        else:
            list_options = {l.get("name") or str(l.get("listId", "?")): l.get("listId") for l in lists}
            selected_label = st.selectbox(
                "Liste auswählen",
                options=list(list_options.keys()),
                index=None,
                placeholder="Bitte Liste auswählen …",
            )
            if st.button("Liste laden", key="btn_hs_load", disabled=selected_label is None):
                with st.spinner("Kontakte werden geladen …"):
                    try:
                        contacts = _load_hubspot_contacts(list_options[selected_label])
                        st.session_state["sm_contacts"] = contacts
                        st.session_state["sm_draft_result"] = None
                        st.rerun()
                    except Exception as exc:
                        st.error(f"HubSpot-Fehler: {exc}")
    except Exception as exc:
        st.warning(f"HubSpot nicht verfügbar: {exc}")

with tab_manual:
    manual_template = pd.DataFrame({"vorname": [""], "firma": [""], "email": [""]})
    edited = st.data_editor(
        manual_template,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="sm_manual_editor",
    )
    if st.button("Diese Kontakte übernehmen", key="btn_manual"):
        contacts, warns = contacts_from_manual(edited)
        for w in warns:
            st.warning(w)
        st.session_state["sm_contacts"] = contacts
        st.session_state["sm_draft_result"] = None
        st.rerun()

# ── Kontakt-Vorschau ──────────────────────────────────────────────────────────
contacts_df: pd.DataFrame | None = st.session_state["sm_contacts"]

if contacts_df is not None and not contacts_df.empty:
    errors = validate_contacts(contacts_df)
    for e in errors:
        st.warning(e)
    st.caption(f"{len(contacts_df)} Kontakt(e) geladen")
    st.dataframe(contacts_df, use_container_width=True, hide_index=True)
else:
    st.info("Noch keine Kontakte geladen. Bitte einen Tab oben verwenden.")

st.divider()

# ── 3. E-Mail-Formular ────────────────────────────────────────────────────────
st.subheader("E-Mail")

subject_tpl = st.text_input(
    "Betreff",
    placeholder="z. B. Einladung – {firma}",
    help="Platzhalter: {vorname}, {firma}, {email}",
)
mail_text = st.text_area(
    "Text",
    height=200,
    placeholder="Ihr Text hier …\n\nZeilenumbrüche werden korrekt übernommen.",
    help="Platzhalter: {vorname}, {firma}, {email}",
)

attachment_file = st.file_uploader("Anhang (optional)", key="sm_attachment")

# ── Vorschau ──────────────────────────────────────────────────────────────────
# Signatur nur für Severin
sig_html = SIGNATURE_SEVERIN_HTML if imap_user.strip().lower() == _SEVERIN_ADDR else ""

if contacts_df is not None and not contacts_df.empty and subject_tpl and mail_text:
    st.markdown("**Vorschau**")
    preview_labels = [
        f"{row['vorname']} – {row['email']}" if row["vorname"] else row["email"]
        for _, row in contacts_df.iterrows()
    ]
    preview_idx = st.selectbox(
        "Vorschau für Kontakt",
        options=range(len(preview_labels)),
        format_func=lambda i: preview_labels[i],
        label_visibility="collapsed",
    )
    preview_row = contacts_df.iloc[preview_idx]
    preview_subject = build_subject(subject_tpl, preview_row["vorname"], preview_row["firma"], preview_row["email"])
    preview_body = build_html_body(preview_row["vorname"], mail_text, sig_html, preview_row["firma"], preview_row["email"])
    st.caption(f"Betreff: {preview_subject}")
    st.html(preview_body)

st.divider()

# ── 4. Entwürfe erstellen ─────────────────────────────────────────────────────
st.subheader("Entwürfe erstellen")

n_contacts = len(contacts_df) if (contacts_df is not None and not contacts_df.empty) else 0
expected_confirm = f"{_CONFIRM_WORD} {n_contacts}"

confirm_input = st.text_input(
    f'Zur Bestätigung eingeben: **{expected_confirm}**',
    placeholder=expected_confirm,
)
confirmed = confirm_input.strip() == expected_confirm and n_contacts > 0

ready = (
    confirmed
    and bool(imap_host)
    and bool(imap_user.strip())
    and bool(imap_pass)
    and bool(subject_tpl.strip())
    and bool(mail_text.strip())
)

if st.button("Entwürfe erstellen", disabled=not ready, type="primary"):
    attachment_bytes = attachment_file.read() if attachment_file else None
    attachment_name = attachment_file.name if attachment_file else None

    mails = [
        SerienMail(
            to_email=row["email"],
            vorname=row["vorname"],
            firma=row["firma"],
            subject=build_subject(subject_tpl, row["vorname"], row["firma"], row["email"]),
            html_body=build_html_body(row["vorname"], mail_text, sig_html, row["firma"], row["email"]),
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_name,
        )
        for _, row in contacts_df.iterrows()
    ]

    config = MailConfig(
        host=imap_host,
        port=imap_port,
        username=imap_user.strip(),
        password=imap_pass,
        drafts_folder=imap_folder or "Drafts",
        use_ssl=imap_ssl,
    )

    with st.spinner("Entwürfe werden erstellt …"):
        try:
            results = create_serienmailing_drafts(mails, config)
            st.session_state["sm_draft_result"] = results
        except Exception as exc:
            st.error(str(exc))

# ── Ergebnis-Tabelle ──────────────────────────────────────────────────────────
draft_result = st.session_state.get("sm_draft_result")
if draft_result:
    result_rows = [
        {
            "Vorname": r.vorname,
            "Firma": r.firma,
            "E-Mail": r.to_email,
            "Status": r.details if r.status == "error" and r.details else "Entwurf gespeichert",
        }
        for r in draft_result
    ]
    result_df = pd.DataFrame(result_rows)
    ok = sum(1 for r in draft_result if r.status == "draft_created")
    err = len(draft_result) - ok
    st.success(f"{ok} Entwurf/Entwürfe gespeichert." + (f"  {err} Fehler." if err else ""))
    st.dataframe(result_df, use_container_width=True, hide_index=True)
