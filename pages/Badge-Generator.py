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
from badgegen.category import derive_kategorie_from_historie, ALLOWED_CATEGORIES
from badgegen.render_pdf import render_badges_pdf_bytes
from badgegen.filter_builder import render_filter_builder
from streamlit_searchbox import st_searchbox
from serienmailing.imap_sender import MailConfig, create_serienmailing_drafts
from serienmailing.mail_builder import SIGNATURE_SEVERIN_HTML, build_html_body, build_subject
from badgegen.badge_mail import build_badge_mails
from shared.config import ConfigError, get_hubspot_token, load_imap_draft_settings
from streamlit_ui import render_page_title

st.set_page_config(page_title="Badge Generator (HubSpot)", layout="wide")
render_page_title("Badge Generator (HubSpot)")

try:
    token = get_hubspot_token(st.secrets)
except ConfigError:
    st.error("❌ HUBSPOT_TOKEN fehlt. Lege ihn in .streamlit/secrets.toml ab.")
    st.stop()

ROOT = Path(__file__).resolve().parents[1]
BADGES_DIR = ROOT / "assets" / "badges"

DEFAULT_TEMPLATES = {
    "TN": str(BADGES_DIR / "tn.png"),
    "VIP/REF": str(BADGES_DIR / "vipref.png"),
    "Sponsor": str(BADGES_DIR / "sponsor.png"),
    "BEO": str(BADGES_DIR / "beo.png"),
    "Team": str(BADGES_DIR / "team.png"),
}


_BG_SEVERIN_ADDR  = "severin.wagner@mysecurityevent.de"
_BG_CONFIRM_WORD  = "ENTWÜRFE"
_BG_DEFAULT_SUBJECT = "Ihr Badge – {vorname}"
_BG_DEFAULT_BODY    = "anbei finden Sie Ihren persönlichen Badge für die Veranstaltung."

_BG_SENDER_SUGGESTIONS = [
    "severin.wagner@mysecurityevent.de",
    "alexander.christoph@mysecurityevent.de",
    "arya.ghaderi@mysecurityevent.de",
    "luisa.lutzenburg@mysecurityevent.de",
    "marc.plewnia@mysecurityevent.de",
    "melvyn.kraeusel@mysecurityevent.de",
    "milena.rusczyk@mysecurityevent.de",
    "robert.duske@mysecurityevent.de",
]


def _bg_search_senders(searchterm: str) -> list[str]:
    term = (searchterm or "").strip().lower()
    if not term:
        return _BG_SENDER_SUGGESTIONS
    startswith = [e for e in _BG_SENDER_SUGGESTIONS if e.lower().startswith(term)]
    contains   = [e for e in _BG_SENDER_SUGGESTIONS if term in e.lower() and e not in startswith]
    return startswith + contains


def _bg_load_imap_defaults() -> tuple[str, int, str, bool]:
    try:
        s = load_imap_draft_settings(st.secrets)
        return s.host, s.port, s.drafts_folder, s.use_ssl
    except ConfigError:
        return "", 993, "Drafts", True


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
    colored_qr: bool,
) -> bytes:
    return render_badges_pdf_bytes(
        rows=df_out.to_dict("records"),
        template_by_category=tpl_map,
        uppercase_names=uppercase_names,
        uppercase_company=uppercase_company,
        colored_qr=colored_qr,
    )


# Feste Ausgabe-Einstellungen – nicht mehr über die UI steuerbar
enable_autofill = True
uppercase_names = True
uppercase_company = True
tpl_map = dict(DEFAULT_TEMPLATES)

# Historie-Präfix: Dropdown oben, direkt vor den Filtern
st.markdown("**Historie-Präfix**")
event_tag = st.selectbox(
    "Historie-Präfix",
    options=["26DOR", "26BER", "26MUC"],
    index=0,
    label_visibility="collapsed",
)

col_filters, col_settings = st.columns([0.68, 0.32], gap="large")

with col_settings:
    colored_qr = st.checkbox("Farbige QR-Codes", value=False)

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

with st.spinner("PDF wird vorbereitet …"):
    try:
        pdf_bytes = _build_pdf_cached(
            df_out=df_out,
            tpl_map=tpl_map,
            uppercase_names=uppercase_names,
            uppercase_company=uppercase_company,
            colored_qr=colored_qr,
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

st.divider()

email_col = df_out["email"].str.strip() if "email" in df_out.columns else pd.Series([""] * len(df_out))
n_with_email    = int((email_col != "").sum())
n_without_email = len(df_out) - n_with_email

with st.expander("Badge-Mails als Entwürfe speichern", expanded=False):
    st.markdown(
        f"**{n_with_email}** Person(en) mit E-Mail-Adresse · "
        f"**{n_without_email}** ohne (werden übersprungen)"
    )

    if n_with_email == 0:
        st.warning("Keine Person hat eine E-Mail-Adresse hinterlegt. Entwurfs-Erstellung nicht möglich.")
    else:
        bg_imap_host, bg_imap_port, bg_imap_folder, bg_imap_ssl = _bg_load_imap_defaults()

        bg_sender = st_searchbox(
            _bg_search_senders,
            key="bg_sender_email",
            label="E-Mail-Adresse (Absender)",
            placeholder="vorname.nachname@mysecurityevent.de",
            default="",
            default_use_searchterm=True,
            default_options=_BG_SENDER_SUGGESTIONS,
            edit_after_submit="option",
        )
        bg_sender = bg_sender or ""
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

        # ── Vorschau ──────────────────────────────────────────────────────────
        df_preview = df_out[df_out["email"].str.strip() != ""].reset_index(drop=True)
        if not df_preview.empty and bg_subject.strip() and bg_body.strip():
            st.markdown("**Vorschau**")
            preview_labels = [
                f"{row['firstname']} {row['lastname']} – {row['email']}".strip(" –")
                if (row["firstname"] or row["lastname"])
                else row["email"]
                for _, row in df_preview.iterrows()
            ]
            preview_idx = st.selectbox(
                "Vorschau für Kontakt",
                options=range(len(preview_labels)),
                format_func=lambda i: preview_labels[i],
                label_visibility="collapsed",
                key="bg_preview_idx",
            )
            pr = df_preview.iloc[preview_idx]
            preview_subject = build_subject(bg_subject, pr.get("firstname", ""), pr.get("company", ""), pr.get("email", ""))
            preview_body    = build_html_body(pr.get("firstname", ""), bg_body, bg_sig, pr.get("company", ""), pr.get("email", ""))
            st.caption(f"Betreff: {preview_subject}")
            st.html(preview_body)

        bg_expected = f"{_BG_CONFIRM_WORD} {n_with_email}"
        bg_confirm = st.text_input(
            f"Zur Bestätigung eingeben: **{bg_expected}**",
            placeholder=bg_expected,
            key="bg_confirm",
        )
        bg_confirmed = bg_confirm.strip() == bg_expected

        bg_ready = (
            bg_confirmed
            and bool(bg_imap_host)
            and bool(bg_sender.strip())
            and bool(bg_pass)
            and bool(bg_subject.strip())
        )

        if st.button("Entwürfe erstellen", disabled=not bg_ready, type="primary", key="bg_draft_btn"):
            with st.spinner(f"Erstelle {n_with_email} Entwurf/Entwürfe …"):
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
                        config = MailConfig(
                            host=bg_imap_host,
                            port=bg_imap_port,
                            username=bg_sender.strip(),
                            password=bg_pass,
                            drafts_folder=bg_imap_folder or "Drafts",
                            use_ssl=bg_imap_ssl,
                        )
                        results = create_serienmailing_drafts(mails, config)
                    else:
                        results = []
                    st.session_state["bg_draft_result"] = {"results": results, "skipped": skipped}
                except Exception as exc:
                    st.error(str(exc))

        bg_result = st.session_state.get("bg_draft_result")
        if bg_result is not None:
            bg_results  = bg_result.get("results", [])
            bg_skipped  = bg_result.get("skipped", [])

            ok  = sum(1 for r in bg_results if r.status == "draft_created")
            err = len(bg_results) - ok

            if bg_results:
                st.success(f"{ok} Entwurf/Entwürfe gespeichert." + (f"  {err} Fehler." if err else ""))
                result_rows = [
                    {
                        "Vorname": r.vorname,
                        "Firma":   r.firma,
                        "E-Mail":  r.to_email,
                        "Status":  r.details if r.status == "error" and r.details else "Entwurf gespeichert",
                    }
                    for r in bg_results
                ]
                st.dataframe(pd.DataFrame(result_rows), use_container_width=True, hide_index=True)

            if bg_skipped:
                st.warning(f"{len(bg_skipped)} Person(en) übersprungen:")
                skip_rows = [
                    {"Name": s["name"], "E-Mail": s["email"], "Grund": s["reason"]}
                    for s in bg_skipped
                ]
                st.dataframe(pd.DataFrame(skip_rows), use_container_width=True, hide_index=True)
