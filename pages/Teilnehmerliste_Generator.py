import base64
import io
import time
from pathlib import Path

import pandas as pd
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject, NullObject
import streamlit as st
import streamlit.components.v1 as components

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

selected_name = st.selectbox(
    "Segment auswählen",
    list(lists_map.keys()),
    index=None,
    placeholder="Segment wählen...",
)

if selected_name is None:
    st.stop()

list_id = lists_map[selected_name]
st.caption(f"List ID: {list_id}")

# --- Dateiname ---
_safe_name = "".join(c if c not in r'\/:*?"<>|' else "_" for c in selected_name)
pdf_filename = f"{_safe_name}_Teilnehmerliste_{lang}.pdf"

# --- Verschlüsselung ---
encrypt = st.checkbox("PDF verschlüsseln")
pdf_password = ""
if encrypt:
    pdf_password = st.text_input("Passwort", type="password", placeholder="Passwort eingeben...")
    if not pdf_password:
        st.warning("Bitte ein Passwort eingeben.")
        st.stop()

# --- Session-State-Initialisierung ---
for _key, _default in [
    ("pdf_bytes", None),
    ("pdf_ready", False),
    ("pdf_row_count", 0),
    ("pdf_filename", "Teilnehmerliste.pdf"),
    ("last_pdf_key", None),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

# Zurücksetzen wenn Liste, Stadt, Sprache, Verschlüsselung oder Passwort geändert wird
_current_pdf_key = (list_id, city_code, lang, encrypt, pdf_password)
if st.session_state.last_pdf_key != _current_pdf_key:
    st.session_state.last_pdf_key = _current_pdf_key
    st.session_state.pdf_ready = False
    st.session_state.pdf_bytes = None

if not st.session_state.pdf_ready:
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

        with st.spinner("PDF finalisieren..."):
            _reader = PdfReader(io.BytesIO(pdf_bytes))
            _writer = PdfWriter()
            _writer.append(_reader)

            # Anfangszoom auf 75 % setzen
            _writer._root_object[NameObject("/OpenAction")] = ArrayObject([
                _writer.pages[0].indirect_reference,
                NameObject("/XYZ"),
                NullObject(),
                NullObject(),
                FloatObject(0.75),
            ])

            if encrypt:
                _writer.encrypt(
                    user_password=pdf_password,
                    owner_password=pdf_password,
                    algorithm="AES-256",
                )

            _out = io.BytesIO()
            _writer.write(_out)
            pdf_bytes = _out.getvalue()

        st.session_state.pdf_bytes = pdf_bytes
        st.session_state.pdf_ready = True
        st.session_state.pdf_row_count = len(df_out)
        st.session_state.pdf_filename = pdf_filename

        st.success(f"Fertig: {len(df_out)} Zeilen (max. 2 pro Firma).")

        # Automatischer Download via JS (Blob URL über window.parent, da data:-URLs aus iframes geblockt werden)
        b64 = base64.b64encode(pdf_bytes).decode()
        components.html(
            f"""<script>
              (function() {{
                var b64 = '{b64}';
                var byteChars = atob(b64);
                var byteArray = new Uint8Array(byteChars.length);
                for (var i = 0; i < byteChars.length; i++) {{
                  byteArray[i] = byteChars.charCodeAt(i);
                }}
                var blob = new Blob([byteArray], {{type: 'application/pdf'}});
                var url = URL.createObjectURL(blob);
                var a = window.parent.document.createElement('a');
                a.href = url;
                a.download = '{pdf_filename}';
                window.parent.document.body.appendChild(a);
                a.click();
                window.parent.document.body.removeChild(a);
                setTimeout(function() {{ URL.revokeObjectURL(url); }}, 100);
              }})();
            </script>""",
            height=0,
        )

        st.download_button(
            "Nochmal herunterladen",
            data=pdf_bytes,
            file_name=pdf_filename,
            mime="application/pdf",
        )
else:
    st.success(f"Fertig: {st.session_state.pdf_row_count} Zeilen (max. 2 pro Firma).")
    st.download_button(
        "Nochmal herunterladen",
        data=st.session_state.pdf_bytes,
        file_name=st.session_state.pdf_filename,
        mime="application/pdf",
    )