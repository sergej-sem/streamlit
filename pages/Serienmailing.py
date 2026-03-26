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
from serienmailing.mail_builder import SIGNATURE_SEVERIN_HTML, build_html_body, build_subject
from shared.config import ConfigError, load_imap_draft_settings

st.set_page_config(page_title="Serienmailing", layout="wide")

_CONFIRM_WORD = "ENTWÜRFE"


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
default_host, default_port, default_folder, default_ssl = _load_imap_defaults()

with st.expander("IMAP-Zugangsdaten", expanded=True):
    col_a, col_b, col_c = st.columns([3, 1, 2])
    with col_a:
        imap_host = st.text_input("Server", value=default_host)
    with col_b:
        imap_port = st.number_input("Port", value=default_port, min_value=1, max_value=65535, step=1)
    with col_c:
        imap_folder = st.text_input("Entwurfs-Ordner", value=default_folder)

    col_d, col_e, col_f = st.columns([3, 3, 1])
    with col_d:
        imap_user = st.text_input("E-Mail-Adresse (Absender)")
    with col_e:
        imap_pass = st.text_input("Passwort", type="password")
    with col_f:
        imap_ssl = st.checkbox("SSL", value=default_ssl)

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
            list_options = {f"{l.get('name', l.get('listId', '?'))} ({l.get('listId', '?')})": l.get("listId") for l in lists}
            selected_label = st.selectbox("Liste auswählen", options=list(list_options.keys()))
            if st.button("Liste laden", key="btn_hs_load"):
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
    help="Platzhalter: {vorname}, {firma}",
)
mail_text = st.text_area(
    "Text",
    height=200,
    placeholder="Ihr Text hier …\n\nZeilenumbrüche werden korrekt übernommen.",
)

attachment_file = st.file_uploader("Anhang (optional)", key="sm_attachment")

# ── Vorschau ──────────────────────────────────────────────────────────────────
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
    preview_subject = build_subject(subject_tpl, preview_row["vorname"], preview_row["firma"])
    preview_body = build_html_body(preview_row["vorname"], mail_text, SIGNATURE_SEVERIN_HTML)
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
    and bool(imap_host.strip())
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
            subject=build_subject(subject_tpl, row["vorname"], row["firma"]),
            html_body=build_html_body(row["vorname"], mail_text, SIGNATURE_SEVERIN_HTML),
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_name,
        )
        for _, row in contacts_df.iterrows()
    ]

    config = MailConfig(
        host=imap_host.strip(),
        port=int(imap_port),
        username=imap_user.strip(),
        password=imap_pass,
        drafts_folder=imap_folder.strip() or "Drafts",
        use_ssl=imap_ssl,
    )

    with st.spinner("Entwürfe werden erstellt …"):
        try:
            results = create_serienmailing_drafts(mails, config)
            st.session_state["sm_draft_result"] = results
        except Exception as exc:
            st.error(f"Fehler: {exc}")

# ── Ergebnis-Tabelle ──────────────────────────────────────────────────────────
draft_result = st.session_state.get("sm_draft_result")
if draft_result:
    status_labels = {"draft_created": "Entwurf gespeichert", "error": "Fehler"}
    result_rows = [
        {
            "Vorname": r.vorname,
            "Firma": r.firma,
            "E-Mail": r.to_email,
            "Status": status_labels.get(r.status, r.status),
            "Hinweis": r.details or "",
        }
        for r in draft_result
    ]
    result_df = pd.DataFrame(result_rows)
    ok = sum(1 for r in draft_result if r.status == "draft_created")
    err = len(draft_result) - ok
    st.success(f"{ok} Entwurf/Entwürfe gespeichert." + (f"  {err} Fehler." if err else ""))
    st.dataframe(result_df, use_container_width=True, hide_index=True)
