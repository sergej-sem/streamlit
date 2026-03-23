# pages/01_Excel_druckbereit_generieren.py
# Streamlit: HubSpot -> Excel (druckfertig) mit Template-Spaltenbreiten + Titel im Seitenkopf
# + Multi-Select (mehrere Historien)
# + Robust gegen HubSpot-Limits (auto split bei 400)
# + Seitenzahl unten (Footer): "Seite X von Y"

import os
import re
from typing import Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st

from excel_druckbereit_generator.export import (
    EXCEL_HEADERS,
    build_excel_bytes,
    read_widths_from_excel_bytes,
    sanitize_filename,
)
from excel_druckbereit_generator.hubspot_fetch import (
    fetch_contacts_by_historien,
    load_historie_options,
)
from shared.config import ConfigError, get_hubspot_token
from streamlit_ui import render_page_title


# ----------------------------
# HubSpot Helpers (Requests)
# ----------------------------
def get_access_token() -> str:
    try:
        return get_hubspot_token(getattr(st, "secrets", None), os.environ)
    except ConfigError as exc:
        raise RuntimeError(
            "Kein HubSpot Token gefunden. Bitte HUBSPOT_TOKEN (oder HUBSPOT_ACCESS_TOKEN) setzen."
        ) from exc


@st.cache_data(ttl=3600)
def fetch_historie_options() -> List[Tuple[str, str]]:
    """
    Liefert [(label, value), ...] für das Property 'historie' aus der Property-Definition.
    Wenn Scopes fehlen oder Property Freitext ist: []
    """
    try:
        return load_historie_options(token=get_access_token())
    except Exception:
        return []


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="HubSpot -> Druck-Excel", layout="wide")
render_page_title("HubSpot → Excel Export (druckfertig)")

options = fetch_historie_options()

historie_labels_selected: List[str] = []
historie_values_selected: List[str] = []

if not options:
    st.warning(
        "Ich konnte keine Dropdown-Optionen für 'historie' aus HubSpot laden.\n"
        "Entweder fehlen Scopes (crm.schemas.contacts.read) oder 'historie' ist ein Freitext-Feld.\n"
        "Gib mehrere Werte getrennt durch Komma/Zeilenumbruch ein."
    )
    raw = st.text_area(
        "Historie-Werte (mehrere möglich)",
        placeholder="z. B. 26DOR_TN, 26DOR_REF, ...",
    )
    historie_values_selected = [x.strip() for x in re.split(r"[,\n;]+", raw) if x.strip()]
    historie_labels_selected = historie_values_selected[:]
else:
    labels = [o[0] for o in options]
    label_to_value = {label: value for label, value in options}

    historie_labels_selected = st.multiselect(
        "Historie auswählen (mehrere möglich)",
        options=labels,
        default=[],
    )
    historie_values_selected = [label_to_value[lbl] for lbl in historie_labels_selected]

# Default Titel (aus den ersten 3 Historien)
if historie_labels_selected:
    default_title = ", ".join(historie_labels_selected[:3])
    if len(historie_labels_selected) > 3:
        default_title += f" (+{len(historie_labels_selected) - 3})"
else:
    default_title = ""

list_title_input = st.text_input(
    "Listentitel (optional, steht oben auf jedem gedruckten Blatt)",
    value=default_title,
)

template_file = st.file_uploader(
    "Excel-Template hochladen (optional) – Spaltenbreiten A–E werden übernommen",
    type=["xlsx"],
)

disabled_btn = len(historie_values_selected) == 0

if st.button("Excel erstellen", type="primary", disabled=disabled_btn):
    try:
        with st.spinner("Lade Daten aus HubSpot..."):
            contacts = fetch_contacts_by_historien(
                historie_values_selected,
                token=get_access_token(),
            )
    except requests.HTTPError as e:
        st.error("HubSpot API Fehler.\n\n" + str(e))
        st.stop()
    except Exception as e:
        st.error(f"Unerwarteter Fehler: {e}")
        st.stop()

    if not contacts:
        st.error("Keine Kontakte für diese Historie(n) gefunden.")
        st.stop()

    rows = []
    for c in contacts:
        p = c.get("properties", {}) or {}
        rows.append(
            {
                "Unternehmensname": (p.get("company") or "").strip(),
                "Vorname": (p.get("firstname") or "").strip(),
                "Nachname": (p.get("lastname") or "").strip(),
                "Expertenwissen": (p.get("expertenwissen") or "").strip(),
                "Herausforderung": (p.get("vorqualifizierung") or "").strip(),
            }
        )

    df = pd.DataFrame(rows, columns=EXCEL_HEADERS)

    # Sortierung nach Unternehmensname A-Z (case-insensitive)
    df["__sort_company"] = df["Unternehmensname"].fillna("").str.lower()
    df = df.sort_values("__sort_company", ascending=True).drop(columns=["__sort_company"])

    widths = {}
    if template_file is not None:
        widths = read_widths_from_excel_bytes(template_file.getvalue())

    excel_bytes = build_excel_bytes(df, list_title_input, widths)

    filename = f"{sanitize_filename(list_title_input or 'export')}.xlsx"
    st.success(f"Fertig. Kontakte: {len(df)}")
    st.download_button(
        label="Excel herunterladen",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.dataframe(df, use_container_width=True)
