import time
from pathlib import Path

import pandas as pd
import streamlit as st

from teilnehmerliste_generator.hubspot_client import (
    get_contact_lists,
    get_list_members,
    get_contacts_by_ids,
)
from teilnehmerliste_generator.transform import build_teilnehmerliste
from teilnehmerliste_generator.pdf_render import generate_pdf_bytes


st.set_page_config(
    page_title="Teilnehmerliste Generator",
    page_icon="📄",
    layout="wide",
)

# Wenn Datei in /pages liegt, ist Projekt-Root eine Ebene höher
ROOT_DIR = Path(__file__).resolve().parents[1]

FONT_DIR = ROOT_DIR / "fonts"
TEMPLATE_DIR = ROOT_DIR / "assets" / "vorlagen_teilnehmerlisten"

LISTS_TTL_SECONDS = 300  # auto-refresh alle 5 Minuten (ohne Button)


def pick_existing(*candidates: Path) -> Path:
    """Return first existing path; otherwise return first candidate (for clear error message)."""
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def template_candidates(prefix: str, city_code: str, lang: str) -> list[Path]:
    return [
        TEMPLATE_DIR / f"{prefix}_{city_code}_{lang}.png",
        TEMPLATE_DIR / f"{prefix}_{city_code.lower()}_{lang}.png",
        TEMPLATE_DIR / f"{prefix}_{city_code}_{lang.lower()}.png",
        TEMPLATE_DIR / f"{prefix}_{city_code.lower()}_{lang.lower()}.png",
    ]


def fetch_lists_map() -> dict[str, str]:
    lists = get_contact_lists()
    return {
        (l.get("name") or f"Liste {l.get('listId')}"): str(l.get("listId"))
        for l in lists
        if l.get("listId") is not None
    }


def get_lists_map_autorefresh(ttl_seconds: int = LISTS_TTL_SECONDS) -> dict[str, str]:
    now = time.time()
    loaded_at = st.session_state.get("lists_loaded_at", 0)
    lists_map = st.session_state.get("lists_map")

    needs_refresh = (lists_map is None) or ((now - loaded_at) > ttl_seconds)

    if needs_refresh:
        with st.spinner("Listen werden geladen..."):
            st.session_state["lists_map"] = fetch_lists_map()
            st.session_state["lists_loaded_at"] = now

    return st.session_state["lists_map"]


st.title("📄 Teilnehmerliste Generator")
st.caption("HubSpot Segment → Regeln → PDF")

# --- Sprache ---
lang_label = st.radio("PDF Sprache", ["Deutsch", "English"], horizontal=True)
lang = "de" if lang_label == "Deutsch" else "en"

# --- Stadt ---
city_label = st.selectbox("Stadt", ["Berlin", "Dortmund", "München"])
city_code = {"Berlin": "BER", "Dortmund": "DOR", "München": "MUC"}[city_label]

# --- Templates je Stadt + Sprache ---
if not TEMPLATE_DIR.exists():
    st.error(f"Template-Ordner fehlt: {TEMPLATE_DIR}")
    st.stop()

TEMPLATE_P1 = pick_existing(*template_candidates("t1", city_code, lang))
TEMPLATE_P2 = pick_existing(*template_candidates("t2", city_code, lang))

if not TEMPLATE_P1.exists() or not TEMPLATE_P2.exists():
    st.error(
        "Templates fehlen:\n"
        f"- {TEMPLATE_P1}\n"
        f"- {TEMPLATE_P2}\n\n"
        f"Erwartet im Ordner: {TEMPLATE_DIR}"
    )
    st.stop()

# --- Listen automatisch laden (ohne Button) ---
try:
    lists_map = get_lists_map_autorefresh()
except Exception as e:
    st.error(f"Fehler beim Laden der Listen: {e}")
    st.stop()

if not lists_map:
    st.error("Keine Listen aus der API erhalten. Prüfe Portal/Token/Scopes.")
    st.stop()

selected_name = st.selectbox("Segment auswählen", list(lists_map.keys()))
list_id = lists_map[selected_name]
st.caption(f"List ID: {list_id}")

if st.button("PDF erstellen", type="primary"):
    with st.spinner("Mitglieder laden..."):
        ids = get_list_members(list_id)

    if not ids:
        st.warning("Diese Liste enthält 0 Kontakte.")
        st.stop()

    with st.spinner("Kontakte laden (company, jobtitle)..."):
        contacts = get_contacts_by_ids(ids, properties=["company", "jobtitle"])

    df_raw = pd.DataFrame([c.get("properties", {}) for c in contacts])

    with st.spinner("Regeln anwenden..."):
        df_out = build_teilnehmerliste(df_raw, lang=lang)

    with st.spinner("PDF rendern..."):
        pdf_bytes = generate_pdf_bytes(
            df=df_out,
            template_p1=TEMPLATE_P1,
            template_p2=TEMPLATE_P2,
            font_dir=FONT_DIR,
            lang=lang,
        )

    st.success(f"Fertig: {len(df_out)} Zeilen (max. 2 pro Firma).")
    st.dataframe(df_out, use_container_width=True)

    st.download_button(
        "Teilnehmerliste.pdf herunterladen",
        data=pdf_bytes,
        file_name="Teilnehmerliste.pdf",
        mime="application/pdf",
    )