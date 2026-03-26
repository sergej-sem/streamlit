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
from shared.config import ConfigError, get_hubspot_token
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
) -> bytes:
    return render_badges_pdf_bytes(
        rows=df_out.to_dict("records"),
        template_by_category=tpl_map,
        uppercase_names=uppercase_names,
        uppercase_company=uppercase_company,
    )


col_filters, col_settings = st.columns([0.68, 0.32], gap="large")

with col_settings:
    st.markdown("### Einstellungen")
    enable_autofill = st.checkbox("Autofill-Vorschläge", value=True)

    st.divider()
    st.markdown("### Event / Kategorie")
    event_tag = st.text_input("Event-Tag (für Kategorie-Ermittlung)", value="26DOR")

    st.divider()
    st.markdown("### Ausgabe")
    uppercase_names = st.checkbox("Vor-/Nachname in GROSSBUCHSTABEN", value=True)
    uppercase_company = st.checkbox("Firma in GROSSBUCHSTABEN", value=True)

    with st.expander("Templates (optional)", expanded=False):
        tpl_map = {
            "TN": st.text_input("Template: TN", value=DEFAULT_TEMPLATES["TN"]),
            "VIP/REF": st.text_input("Template: VIP/REF", value=DEFAULT_TEMPLATES["VIP/REF"]),
            "Sponsor": st.text_input("Template: Sponsor", value=DEFAULT_TEMPLATES["Sponsor"]),
            "BEO": st.text_input("Template: BEO", value=DEFAULT_TEMPLATES["BEO"]),
            "Team": st.text_input("Template: Team", value=DEFAULT_TEMPLATES["Team"]),
        }

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


st.subheader("1) Kontakte suchen")

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

st.subheader("2) Vorschau & Prüfung")

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

st.subheader("3) PDF erzeugen")

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
