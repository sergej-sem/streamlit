import streamlit as st
import pandas as pd
from pathlib import Path

from hubspot_client import get_contact_lists, get_list_members, get_contacts_by_ids
from transform import build_teilnehmerliste
from pdf_render import generate_pdf_bytes

FONT_DIR = Path("fonts")

st.title("HubSpot → PDF Automation")

# --- Sprache ---
lang_label = st.radio("PDF Sprache", ["Deutsch", "English"], horizontal=True)
lang = "de" if lang_label == "Deutsch" else "en"

# --- Stadt ---
city_label = st.selectbox("Stadt", ["Berlin", "Dortmund", "München"])
city_code = {"Berlin": "BER", "Dortmund": "DOR", "München": "MUC"}[city_label]

# --- Templates je Stadt + Sprache ---
TEMPLATE_P1 = Path(f"t1_{city_code}_{lang}.png")
TEMPLATE_P2 = Path(f"t2_{city_code}_{lang}.png")

# Früh prüfen
if not TEMPLATE_P1.exists() or not TEMPLATE_P2.exists():
    st.error(f"Templates fehlen: {TEMPLATE_P1} / {TEMPLATE_P2}")
    st.stop()

# 1) Listen laden
if st.button("Listen laden"):
    lists = get_contact_lists()
    st.session_state["lists_map"] = {
        (l.get("name") or f"Liste {l.get('listId')}"): str(l.get("listId"))
        for l in lists
        if l.get("listId") is not None
    }

if "lists_map" not in st.session_state:
    st.info("Noch keine Listen geladen.")
    st.stop()

if not st.session_state["lists_map"]:
    st.error("Keine Listen aus der API erhalten. Prüfe Portal/Token/Scopes.")
    st.stop()

# 2) Segment auswählen
selected_name = st.selectbox("Segment auswählen", list(st.session_state["lists_map"].keys()))
list_id = st.session_state["lists_map"][selected_name]
st.caption(f"List ID: {list_id}")

# 3) PDF erstellen
if st.button("PDF erstellen"):
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