# pages/03_Badge-Generator.py

import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from badgegen.hubspot_search import (
    P_HISTORIE,
    search_compiled_groups,
)
from badgegen.historie_options import fetch_historie_options
from badgegen.category import derive_kategorie_from_historie, ALLOWED_CATEGORIES, EVENT_TAGS
from badgegen.render_pdf import badge_font_cache_token, render_badges_pdf_bytes
from badgegen.filter_builder import render_filter_builder
from serienmailing.imap_sender import MailConfig, create_serienmailing_drafts
from serienmailing.mail_builder import (
    SENDER_EMAIL_SUGGESTIONS,
    SIGNATURE_SEVERIN_HTML,
    build_html_body,
    build_subject,
)
from serienmailing.smtp_sender import send_serienmailing_messages
from badgegen.badge_mail import build_badge_mails, build_badge_notification_mails
from shared.config import (
    ConfigError,
    get_hubspot_token,
    load_imap_draft_settings,
    load_smtp_send_settings,
)
from shared.smtp_sender import SmtpSendConfig
from badgegen.notification_settings import (
    BadgeNotificationSettings,
    DEFAULT_BADGE_NOTIFICATION_RECIPIENT,
    load_badge_notification_settings,
    save_badge_notification_settings,
)
from streamlit_ui import render_email_selectbox, render_page_title

st.set_page_config(page_title="Badge Generator (HubSpot)", layout="wide")
render_page_title("Badge Generator (HubSpot)")

try:
    token = get_hubspot_token(st.secrets)
except ConfigError:
    st.error("❌ HUBSPOT_TOKEN fehlt. Lege ihn in .streamlit/secrets.toml ab.")
    st.stop()

ROOT = Path(__file__).resolve().parents[1]
BADGES_DIR = ROOT / "assets" / "badges"
_BG_NOTIFY_SETTINGS_PATH = ROOT / ".streamlit" / "badge_generator_notification_settings.json"

DEFAULT_TEMPLATES = {
    "TN": str(BADGES_DIR / "tn.png"),
    "VIP/REF": str(BADGES_DIR / "vipref.png"),
    "Sponsor": str(BADGES_DIR / "sponsor.png"),
    "BEO": str(BADGES_DIR / "beo.png"),
    "Team": str(BADGES_DIR / "team.png"),
}


_BG_SEVERIN_ADDR  = "severin.wagner@mysecurityevent.de"
_BG_CONFIRM_WORD  = "ENTWÜRFE"
_BG_DEFAULT_SUBJECT = "Dein Badge – {vorname}"
_BG_DEFAULT_BODY    = "anbei finden Sie Ihren persönlichen Badge für die Veranstaltung."
_BG_DEFAULT_EVENT_TAG = "26BER"
_BG_NOTIFY_SAVED_EMAIL_ENABLED_KEY = "_bg_notify_saved_email_enabled"
_BG_NOTIFY_SAVED_SENDER_KEY = "_bg_notify_saved_sender_email"
_BG_NOTIFY_SAVED_RECIPIENT_KEY = "_bg_notify_saved_recipient_email"
_BG_CONFIRM_WORD_DRAFT = "ENTW\u00dcRFE"
_BG_CONFIRM_WORD_SEND = "SENDEN"
_BG_MAIL_MODE_OPTIONS = ("Entw\u00fcrfe", "Senden")

def _bg_load_imap_defaults() -> tuple[str, int, str, bool]:
    try:
        s = load_imap_draft_settings(st.secrets)
        return s.host, s.port, s.drafts_folder, s.use_ssl
    except ConfigError:
        return "", 993, "Drafts", True


def _bg_load_smtp_defaults() -> tuple[str, int, bool, bool, int]:
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


def _bg_init_notification_settings() -> None:
    if st.session_state.get("_bg_notify_settings_loaded"):
        return

    settings = load_badge_notification_settings(_BG_NOTIFY_SETTINGS_PATH)
    st.session_state.setdefault(_BG_NOTIFY_SAVED_EMAIL_ENABLED_KEY, settings.email_enabled)
    st.session_state.setdefault(_BG_NOTIFY_SAVED_SENDER_KEY, settings.sender_email)
    st.session_state.setdefault(_BG_NOTIFY_SAVED_RECIPIENT_KEY, settings.recipient_email)
    st.session_state["_bg_notify_settings_loaded"] = True


def _bg_sync_notification_widget_defaults() -> None:
    st.session_state.setdefault(
        "bg_notify_email_enabled",
        bool(st.session_state.get(_BG_NOTIFY_SAVED_EMAIL_ENABLED_KEY, False)),
    )
    st.session_state.setdefault(
        "bg_notify_sender_email",
        (st.session_state.get(_BG_NOTIFY_SAVED_SENDER_KEY) or "").strip(),
    )
    st.session_state.setdefault(
        "bg_notify_recipient_email",
        (st.session_state.get(_BG_NOTIFY_SAVED_RECIPIENT_KEY) or "").strip() or DEFAULT_BADGE_NOTIFICATION_RECIPIENT,
    )


def _bg_reset_notification_widget_state() -> None:
    for key in (
        "bg_notify_email_enabled",
        "bg_notify_sender_email",
        "bg_notify_imap_pass",
        "bg_notify_recipient_email",
    ):
        st.session_state.pop(key, None)


def _bg_persist_notification_settings() -> None:
    email_enabled = bool(st.session_state.get("bg_notify_email_enabled"))
    sender_email = (st.session_state.get("bg_notify_sender_email") or "").strip()
    recipient_email = (st.session_state.get("bg_notify_recipient_email") or "").strip() or DEFAULT_BADGE_NOTIFICATION_RECIPIENT

    st.session_state[_BG_NOTIFY_SAVED_EMAIL_ENABLED_KEY] = email_enabled
    st.session_state[_BG_NOTIFY_SAVED_SENDER_KEY] = sender_email
    st.session_state[_BG_NOTIFY_SAVED_RECIPIENT_KEY] = recipient_email

    save_badge_notification_settings(
        _BG_NOTIFY_SETTINGS_PATH,
        BadgeNotificationSettings(
            email_enabled=email_enabled,
            sender_email=sender_email,
            recipient_email=recipient_email,
        ),
    )


@st.cache_data(ttl=3600)
def _cached_historie_options() -> List[tuple[str, str]]:
    return fetch_historie_options(token, historie_property=P_HISTORIE)


def _historie_value_to_label(raw: str, value_to_label: Dict[str, str]) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    parts = [p.strip() for p in re.split(r"[;\n,]+", s) if p.strip()]
    mapped = [value_to_label.get(p, p) for p in parts]
    return ";".join(mapped)


@st.cache_data(ttl=300)
def _build_pdf_cached(
    df_out: pd.DataFrame,
    tpl_map: Dict[str, str],
    uppercase_names: bool,
    uppercase_company: bool,
    render_cache_token: tuple[str, int, str, int],
) -> bytes:
    return render_badges_pdf_bytes(
        rows=df_out.to_dict("records"),
        template_by_category=tpl_map,
        uppercase_names=uppercase_names,
        uppercase_company=uppercase_company,
    )


# Feste Ausgabe-Einstellungen – nicht mehr über die UI steuerbar
enable_autofill = True
uppercase_names = True
uppercase_company = True
colored_qr = True
tpl_map = dict(DEFAULT_TEMPLATES)
_bg_init_notification_settings()

# Historie-Präfix: Dropdown oben, direkt vor den Filtern
st.markdown("**Historie-Präfix**")
event_tag = st.selectbox(
    "Historie-Präfix",
    options=EVENT_TAGS,
    index=EVENT_TAGS.index(_BG_DEFAULT_EVENT_TAG) if _BG_DEFAULT_EVENT_TAG in EVENT_TAGS else 0,
    label_visibility="collapsed",
)

col_filters, _ = st.columns([0.68, 0.32], gap="large")

with col_filters:
    historie_opts = _cached_historie_options()

    compiled_groups = render_filter_builder(
        token=token,
        historie_options=historie_opts,
        enable_autofill=enable_autofill,
    )

    has_any = bool(compiled_groups)
    if not has_any:
        st.warning("Bitte mindestens einen Filter setzen.")

needs_more_filters = any(
    (not (g.get("server_filters") or [])) and (g.get("local_contains") or [])
    for g in compiled_groups
)
if needs_more_filters:
    st.warning(
        "Diese Suche wäre zu breit (nur „enthält“ ohne einschränkenden Filter). "
        "Bitte setze zusätzlich z. B. „Historie“ oder einen „ist genau“-Filter."
    )

st.divider()
search_clicked = st.button(
    "Suchen",
    type="primary",
    use_container_width=True,
    disabled=(not has_any or needs_more_filters),
)


@st.cache_data(ttl=120)
def run_search_cached(compiled_groups: List[dict], token: str) -> pd.DataFrame:
    return search_compiled_groups(token, compiled_groups)



if search_clicked:
    if needs_more_filters:
        st.info(
            "Setze bitte mindestens einen einschränkenden Filter (z. B. Historie), "
            "dann funktioniert die Suche zuverlässig."
        )
        st.stop()

    try:
        df_new = run_search_cached(compiled_groups, token)
    except Exception as e:
        st.error(f"❌ Suche fehlgeschlagen: {e}")
        st.stop()

    if df_new.empty:
        st.warning("Keine Kontakte gefunden.")
        st.stop()

    value_to_label = {val: lbl for (lbl, val) in historie_opts} if historie_opts else {}

    df_new["historie_raw"] = df_new["historie"]
    df_new["historie"] = df_new["historie_raw"].apply(lambda s: _historie_value_to_label(s, value_to_label))

    df_new["kategorie"] = df_new["historie"].apply(lambda h: derive_kategorie_from_historie(h, event_tag.strip()))

    missing = df_new["kategorie"].isna() | (df_new["kategorie"].astype(str).str.strip() == "")
    if missing.any():
        df_new.loc[missing, "kategorie"] = df_new.loc[missing, "historie_raw"].apply(
            lambda h: derive_kategorie_from_historie(h, event_tag.strip())
        )

    df_new.drop(columns=["historie_raw"], inplace=True, errors="ignore")

    st.session_state["df_badges"] = df_new

    # WICHTIG: jede neue Suche bekommt eine neue Run-ID -> Button-Text reset
    st.session_state["df_badges_run_id"] = st.session_state.get("df_badges_run_id", 0) + 1
    st.session_state["badges_pdf_downloaded"] = False
    st.session_state.pop("badges_pdf_sig", None)


df: pd.DataFrame = st.session_state.get("df_badges", pd.DataFrame())
if df.empty:
    st.info("Noch keine Suche ausgeführt.")
    st.stop()


total_hits = len(df)
st.info(f"Treffer insgesamt: {total_hits}. Hinweis: Es werden nur die ersten 50 Kontakte angezeigt.")

display_cols = ["id", "firstname", "lastname", "company", "jobtitle", "kategorie", "historie"]
display_cols = [c for c in display_cols if c in df.columns]

df_display = df[display_cols].head(50).copy()
st.dataframe(df_display, use_container_width=True, height=420)

issues = False

missing_cat = df[df["kategorie"].isna() | (df["kategorie"].astype(str).str.strip() == "")]
if not missing_cat.empty:
    issues = True
    st.error(
        f"❌ Kategorie konnte NICHT ermittelt werden für {len(missing_cat)} Kontakt(e). "
        "Ohne Kategorie wird KEIN PDF erzeugt."
    )
    cols = ["id", "firstname", "lastname", "historie"]
    cols = [c for c in cols if c in missing_cat.columns]
    st.dataframe(missing_cat[cols].head(50), use_container_width=True, height=220)
    st.caption("Anzeige: erste 50 betroffene Kontakte.")

unknown_cats = sorted(set(df["kategorie"].dropna().unique()) - set(ALLOWED_CATEGORIES))
if unknown_cats:
    issues = True
    st.error("❌ Unerwartete Kategorie(n) gefunden:\n" + "\n".join(f"- {c}" for c in unknown_cats))

missing_files = [p for p in tpl_map.values() if not Path(p).exists()]
if missing_files:
    issues = True
    st.error("❌ Template-Dateien nicht gefunden:\n" + "\n".join(f"- {p}" for p in missing_files))

if issues:
    st.stop()


cats_present = sorted([c for c in df["kategorie"].dropna().unique().tolist() if str(c).strip()])
selected = st.multiselect("Kategorien auswählen", options=cats_present, default=cats_present)

if not selected:
    st.info("Bitte mindestens eine Kategorie auswählen.")
    st.stop()
df_out = df[df["kategorie"].isin(selected)]
if df_out.empty:
    st.warning("Keine Kontakte in den ausgewählten Kategorien.")
    st.stop()

run_id = st.session_state.get("df_badges_run_id", 0)

current_sig = (
    run_id,
    tuple(selected),
    int(len(df_out)),
    event_tag.strip(),
    bool(uppercase_names),
    bool(uppercase_company),
    bool(colored_qr),
    tuple(sorted(tpl_map.items())),
)

if st.session_state.get("badges_pdf_sig") != current_sig:
    st.session_state["badges_pdf_sig"] = current_sig
    st.session_state["badges_pdf_downloaded"] = False
    _bg_reset_notification_widget_state()
    st.session_state["bg_notify_result"] = None
    st.session_state["bg_draft_result"] = None

with st.spinner("PDF wird vorbereitet …"):
    try:
        pdf_bytes = _build_pdf_cached(
            df_out=df_out,
            tpl_map=tpl_map,
            uppercase_names=uppercase_names,
            uppercase_company=uppercase_company,
            render_cache_token=badge_font_cache_token(),
        )
    except Exception as e:
        st.error(f"❌ PDF-Erstellung fehlgeschlagen: {e}")
        st.stop()


def _mark_downloaded() -> None:
    st.session_state["badges_pdf_downloaded"] = True


label = "Nochmal herunterladen" if st.session_state.get("badges_pdf_downloaded") else "PDF erstellen"

st.download_button(
    label,
    data=pdf_bytes,
    file_name=f"Badges_{event_tag.strip()}.pdf",
    mime="application/pdf",
    type="primary",
    on_click=_mark_downloaded,
)

# ── Badge-Mails als Entwürfe speichern ───────────────────────────────────────
st.session_state.setdefault("bg_draft_result", None)
st.session_state.setdefault("bg_notify_result", None)

st.divider()

email_col = df_out["email"].str.strip() if "email" in df_out.columns else pd.Series([""] * len(df_out))
n_with_email = int((email_col != "").sum())
n_without_email = len(df_out) - n_with_email
n_badge_notifications = len(df_out)

st.subheader("Badge-Benachrichtigung per E-Mail")
if not st.session_state.get("badges_pdf_downloaded"):
    st.info(
        "Nach dem Klick auf `PDF erstellen` stehen hier E-Mail-Aktionen fuer die "
        "aktuell ausgewaehlten Teilnehmer zur Verfuegung."
    )
else:
    _bg_sync_notification_widget_defaults()

    st.markdown(
        f"Diese Aktion bezieht sich auf die aktuelle Badge-Auswahl: "
        f"**{n_badge_notifications}** Teilnehmer-Badge(s)."
    )

    bg_notify_imap_host, bg_notify_imap_port, bg_notify_imap_folder, bg_notify_imap_ssl = _bg_load_imap_defaults()
    bg_notify_smtp_host, bg_notify_smtp_port, bg_notify_smtp_ssl, bg_notify_smtp_starttls, bg_notify_smtp_timeout = _bg_load_smtp_defaults()
    bg_notify_enabled = st.checkbox(
        "E-Mail",
        key="bg_notify_email_enabled",
        on_change=_bg_persist_notification_settings,
    )

    if bg_notify_enabled:
        bg_notify_mode = st.radio(
            "Modus",
            options=_BG_MAIL_MODE_OPTIONS,
            index=0,
            horizontal=True,
            key="bg_notify_mode",
        )
        bg_notify_is_send_mode = bg_notify_mode == "Senden"

        bg_notify_sender = render_email_selectbox(
            "E-Mail-Adresse (Postfach / Absender)",
            key="bg_notify_sender_email",
            suggestions=SENDER_EMAIL_SUGGESTIONS,
            placeholder="vorname.nachname@mysecurityevent.de",
            on_change=_bg_persist_notification_settings,
        )
        bg_notify_pass = st.text_input("Passwort", type="password", key="bg_notify_imap_pass")
        bg_notify_recipient = render_email_selectbox(
            "E-Mail-Adresse (Empfaenger)",
            key="bg_notify_recipient_email",
            suggestions=SENDER_EMAIL_SUGGESTIONS,
            placeholder=DEFAULT_BADGE_NOTIFICATION_RECIPIENT,
            on_change=_bg_persist_notification_settings,
        )

        if bg_notify_is_send_mode and not bg_notify_smtp_host:
            st.warning("SMTP-Konfiguration fehlt. Bitte `mse_smtp_mail_send` in den Secrets pruefen.")
        elif (not bg_notify_is_send_mode) and not bg_notify_imap_host:
            st.warning("IMAP-Draft-Konfiguration fehlt. Bitte `mse_imap_mail_drafts` in den Secrets pruefen.")

        bg_notify_expected = f"{_BG_CONFIRM_WORD_SEND} {n_badge_notifications}"
        bg_notify_confirmed = True
        if bg_notify_is_send_mode:
            bg_notify_confirm = st.text_input(
                f"Zur Bestaetigung eingeben: **{bg_notify_expected}**",
                placeholder=bg_notify_expected,
                key="bg_notify_send_confirm",
            )
            bg_notify_confirmed = bg_notify_confirm.strip() == bg_notify_expected

        bg_notify_ready = (
            n_badge_notifications > 0
            and bool(bg_notify_sender)
            and bool(bg_notify_recipient)
            and bool(bg_notify_pass)
            and bool(bg_notify_smtp_host if bg_notify_is_send_mode else bg_notify_imap_host)
            and bg_notify_confirmed
        )

        bg_notify_button_label = "E-Mails senden" if bg_notify_is_send_mode else "E-Mail-Entwuerfe erzeugen"
        bg_notify_spinner_label = (
            f"Sende {n_badge_notifications} Benachrichtigungs-E-Mail(s) ..."
            if bg_notify_is_send_mode
            else f"Erstelle {n_badge_notifications} Benachrichtigungs-Entwurf/Entwuerfe ..."
        )

        if st.button(bg_notify_button_label, disabled=not bg_notify_ready, type="primary", key="bg_notify_btn"):
            with st.spinner(bg_notify_spinner_label):
                try:
                    mails, skipped = build_badge_notification_mails(
                        df_out=df_out,
                        recipient_email=bg_notify_recipient,
                        tpl_map=tpl_map,
                        uppercase_names=uppercase_names,
                        uppercase_company=uppercase_company,
                        colored_qr=colored_qr,
                    )
                    if mails:
                        if bg_notify_is_send_mode:
                            results = send_serienmailing_messages(
                                mails,
                                SmtpSendConfig(
                                    host=bg_notify_smtp_host,
                                    port=bg_notify_smtp_port,
                                    username=bg_notify_sender,
                                    password=bg_notify_pass,
                                    use_ssl=bg_notify_smtp_ssl,
                                    use_starttls=bg_notify_smtp_starttls,
                                    timeout_seconds=bg_notify_smtp_timeout,
                                ),
                            )
                        else:
                            results = create_serienmailing_drafts(
                                mails,
                                MailConfig(
                                    host=bg_notify_imap_host,
                                    port=bg_notify_imap_port,
                                    username=bg_notify_sender,
                                    password=bg_notify_pass,
                                    drafts_folder=bg_notify_imap_folder or "Drafts",
                                    use_ssl=bg_notify_imap_ssl,
                                ),
                            )
                    else:
                        results = []
                    st.session_state["bg_notify_result"] = {
                        "mode": bg_notify_mode,
                        "results": results,
                        "skipped": skipped,
                    }
                except Exception as exc:
                    st.error(str(exc))

    bg_notify_result = st.session_state.get("bg_notify_result")
    if bg_notify_result is not None:
        bg_notify_mode = bg_notify_result.get("mode", "Entwuerfe")
        bg_notify_results = bg_notify_result.get("results", [])
        bg_notify_skipped = bg_notify_result.get("skipped", [])
        bg_notify_success_status = "sent" if bg_notify_mode == "Senden" else "draft_created"
        bg_notify_success_label = "Gesendet" if bg_notify_mode == "Senden" else "Entwurf gespeichert"
        bg_notify_summary_label = (
            "Benachrichtigungs-E-Mail(s) gesendet"
            if bg_notify_mode == "Senden"
            else "Benachrichtigungs-Entwurf/Entwuerfe gespeichert"
        )

        ok = sum(1 for result in bg_notify_results if result.status == bg_notify_success_status)
        err = len(bg_notify_results) - ok

        if bg_notify_results:
            st.success(f"{ok} {bg_notify_summary_label}." + (f"  {err} Fehler." if err else ""))
            notify_rows = [
                {
                    "Teilnehmer": result.vorname,
                    "Firma": result.firma,
                    "Empfaenger": result.to_email,
                    "Status": result.details if result.status == "error" and result.details else bg_notify_success_label,
                }
                for result in bg_notify_results
            ]
            st.dataframe(pd.DataFrame(notify_rows), use_container_width=True, hide_index=True)

        if bg_notify_skipped:
            st.warning(f"{len(bg_notify_skipped)} Person(en) uebersprungen:")
            skip_rows = [
                {"Teilnehmer": item["name"], "Empfaenger": item["email"], "Grund": item["reason"]}
                for item in bg_notify_skipped
            ]
            st.dataframe(pd.DataFrame(skip_rows), use_container_width=True, hide_index=True)

st.divider()

with st.expander("Badge-Mails speichern oder senden", expanded=False):
    st.markdown(
        f"**{n_with_email}** Person(en) mit E-Mail-Adresse · "
        f"**{n_without_email}** ohne (werden uebersprungen)"
    )

    if n_with_email == 0:
        st.warning("Keine Person hat eine E-Mail-Adresse hinterlegt. Mail-Erstellung nicht moeglich.")
    else:
        bg_imap_host, bg_imap_port, bg_imap_folder, bg_imap_ssl = _bg_load_imap_defaults()
        bg_smtp_host, bg_smtp_port, bg_smtp_ssl, bg_smtp_starttls, bg_smtp_timeout = _bg_load_smtp_defaults()

        bg_mail_mode = st.radio(
            "Modus",
            options=_BG_MAIL_MODE_OPTIONS,
            index=0,
            horizontal=True,
            key="bg_mail_mode",
        )
        bg_is_send_mode = bg_mail_mode == "Senden"

        bg_sender = render_email_selectbox(
            "E-Mail-Adresse (Absender)",
            key="bg_sender_email",
            suggestions=SENDER_EMAIL_SUGGESTIONS,
            placeholder="vorname.nachname@mysecurityevent.de",
        )
        bg_pass = st.text_input("Passwort", type="password", key="bg_imap_pass")

        bg_subject = st.text_input(
            "Betreff",
            value=_BG_DEFAULT_SUBJECT,
            help="Platzhalter: {vorname}, {firma}, {email}",
            key="bg_subject",
        )
        bg_body = st.text_area(
            "Text",
            value=_BG_DEFAULT_BODY,
            height=100,
            help="Platzhalter: {vorname}, {firma}, {email}",
            key="bg_body",
        )

        bg_sig = SIGNATURE_SEVERIN_HTML if bg_sender.strip().lower() == _BG_SEVERIN_ADDR else ""

        df_preview = df_out[df_out["email"].str.strip() != ""].reset_index(drop=True)
        if not df_preview.empty and bg_subject.strip() and bg_body.strip():
            st.markdown("**Vorschau**")
            preview_labels = [
                f"{row['firstname']} {row['lastname']} - {row['email']}".strip(" -")
                if (row["firstname"] or row["lastname"])
                else row["email"]
                for _, row in df_preview.iterrows()
            ]
            preview_idx = st.selectbox(
                "Vorschau fuer Kontakt",
                options=range(len(preview_labels)),
                format_func=lambda i: preview_labels[i],
                label_visibility="collapsed",
                key="bg_preview_idx",
            )
            preview_row = df_preview.iloc[preview_idx]
            preview_subject = build_subject(
                bg_subject,
                preview_row.get("firstname", ""),
                preview_row.get("company", ""),
                preview_row.get("email", ""),
            )
            preview_body = build_html_body(
                preview_row.get("firstname", ""),
                bg_body,
                bg_sig,
                preview_row.get("company", ""),
                preview_row.get("email", ""),
            )
            st.caption(f"Betreff: {preview_subject}")
            st.html(preview_body)

        bg_confirm_word = _BG_CONFIRM_WORD_SEND if bg_is_send_mode else _BG_CONFIRM_WORD_DRAFT
        bg_expected = f"{bg_confirm_word} {n_with_email}"
        bg_confirm = st.text_input(
            f"Zur Bestaetigung eingeben: **{bg_expected}**",
            placeholder=bg_expected,
            key="bg_confirm",
        )
        bg_confirmed = bg_confirm.strip() == bg_expected

        if bg_is_send_mode and not bg_smtp_host:
            st.warning("SMTP-Konfiguration fehlt. Bitte `mse_smtp_mail_send` in den Secrets pruefen.")
        elif (not bg_is_send_mode) and not bg_imap_host:
            st.warning("IMAP-Draft-Konfiguration fehlt. Bitte `mse_imap_mail_drafts` in den Secrets pruefen.")

        bg_ready = (
            bg_confirmed
            and bool(bg_sender.strip())
            and bool(bg_pass)
            and bool(bg_subject.strip())
            and bool(bg_smtp_host if bg_is_send_mode else bg_imap_host)
        )

        bg_button_label = "E-Mails senden" if bg_is_send_mode else "Entwuerfe erstellen"
        bg_spinner_label = (
            f"Sende {n_with_email} E-Mail(s) ..."
            if bg_is_send_mode
            else f"Erstelle {n_with_email} Entwurf/Entwuerfe ..."
        )

        if st.button(bg_button_label, disabled=not bg_ready, type="primary", key="bg_draft_btn"):
            with st.spinner(bg_spinner_label):
                try:
                    mails, skipped = build_badge_mails(
                        df_out=df_out,
                        subject_tpl=bg_subject,
                        body_text=bg_body,
                        sig_html=bg_sig,
                        tpl_map=tpl_map,
                        uppercase_names=uppercase_names,
                        uppercase_company=uppercase_company,
                        colored_qr=colored_qr,
                    )
                    if mails:
                        if bg_is_send_mode:
                            results = send_serienmailing_messages(
                                mails,
                                SmtpSendConfig(
                                    host=bg_smtp_host,
                                    port=bg_smtp_port,
                                    username=bg_sender.strip(),
                                    password=bg_pass,
                                    use_ssl=bg_smtp_ssl,
                                    use_starttls=bg_smtp_starttls,
                                    timeout_seconds=bg_smtp_timeout,
                                ),
                            )
                        else:
                            results = create_serienmailing_drafts(
                                mails,
                                MailConfig(
                                    host=bg_imap_host,
                                    port=bg_imap_port,
                                    username=bg_sender.strip(),
                                    password=bg_pass,
                                    drafts_folder=bg_imap_folder or "Drafts",
                                    use_ssl=bg_imap_ssl,
                                ),
                            )
                    else:
                        results = []
                    st.session_state["bg_draft_result"] = {
                        "mode": bg_mail_mode,
                        "results": results,
                        "skipped": skipped,
                    }
                except Exception as exc:
                    st.error(str(exc))

        bg_result = st.session_state.get("bg_draft_result")
        if bg_result is not None:
            bg_mode = bg_result.get("mode", "Entwuerfe")
            bg_results = bg_result.get("results", [])
            bg_skipped = bg_result.get("skipped", [])
            bg_success_status = "sent" if bg_mode == "Senden" else "draft_created"
            bg_success_label = "Gesendet" if bg_mode == "Senden" else "Entwurf gespeichert"
            bg_summary_label = "E-Mail(s) gesendet" if bg_mode == "Senden" else "Entwurf/Entwuerfe gespeichert"

            ok = sum(1 for result in bg_results if result.status == bg_success_status)
            err = len(bg_results) - ok

            if bg_results:
                st.success(f"{ok} {bg_summary_label}." + (f"  {err} Fehler." if err else ""))
                result_rows = [
                    {
                        "Vorname": result.vorname,
                        "Firma": result.firma,
                        "E-Mail": result.to_email,
                        "Status": result.details if result.status == "error" and result.details else bg_success_label,
                    }
                    for result in bg_results
                ]
                st.dataframe(pd.DataFrame(result_rows), use_container_width=True, hide_index=True)

            if bg_skipped:
                st.warning(f"{len(bg_skipped)} Person(en) uebersprungen:")
                skip_rows = [
                    {"Name": item["name"], "E-Mail": item["email"], "Grund": item["reason"]}
                    for item in bg_skipped
                ]
                st.dataframe(pd.DataFrame(skip_rows), use_container_width=True, hide_index=True)
