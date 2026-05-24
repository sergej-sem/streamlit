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
from teilnehmerliste_generator.output_naming import build_pdf_filename
from teilnehmerliste_generator.transform import build_teilnehmerliste
from teilnehmerliste_generator.pdf_render import collect_shrunk_company_names, generate_pdf_bytes
from streamlit_ui import render_page_title


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


def finalize_pdf_bytes(pdf_bytes: bytes, password: str = "") -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)

    for page in writer.pages:
        page.compress_content_streams(level=9)

    if writer.pages:
        # Open the first page at 75 % zoom in the PDF viewer.
        writer._root_object[NameObject("/OpenAction")] = ArrayObject([
            writer.pages[0].indirect_reference,
            NameObject("/XYZ"),
            NullObject(),
            NullObject(),
            FloatObject(0.75),
        ])

    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)

    if password:
        writer.encrypt(
            user_password=password,
            owner_password=password,
            algorithm="AES-256",
        )

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


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


def _reset_pdf_output_state() -> None:
    st.session_state.pdf_ready = False
    st.session_state.pdf_bytes = None
    st.session_state.pdf_row_count = 0
    st.session_state.pdf_shrunk_company_count = 0
    st.session_state.pdf_shrunk_company_examples = ()


def _render_pdf_ready_block(
    *,
    status_slot,
    hint_slot,
    action_slot,
    pdf_bytes: bytes,
    pdf_filename: str,
    row_count: int,
    shrunk_company_count: int,
    shrunk_company_examples: tuple[str, ...],
) -> None:
    status_slot.success(f"Fertig: {row_count} Zeilen (max. 2 pro Firma).")

    if shrunk_company_count:
        label = "Firmenname" if shrunk_company_count == 1 else "Firmennamen"
        verb = "musste" if shrunk_company_count == 1 else "mussten"
        examples = [str(name or "").strip() for name in shrunk_company_examples if str(name or "").strip()]
        examples_text = "\n".join(f"- `{name}`" for name in examples)
        examples_prefix = "Beispiel:" if len(examples) == 1 else "Beispiele:"
        message = f"{shrunk_company_count} {label} {verb} in der PDF wegen ihrer Länge verkleinert werden."
        if examples_text:
            message += f"\n\n{examples_prefix}\n{examples_text}"
        hint_slot.info(message)
    else:
        hint_slot.empty()

    action_slot.download_button(
        "Nochmal herunterladen",
        data=pdf_bytes,
        file_name=pdf_filename,
        mime="application/pdf",
    )


render_page_title("Teilnehmerliste Generator")

# --- Sprache ---
lang_label = st.radio("PDF Sprache", ["Deutsch", "English"], horizontal=True)
lang = "de" if lang_label == "Deutsch" else "en"

# --- Stadt ---
city_label = st.selectbox("Stadt", ["Berlin", "Dortmund", "München"], index=2)
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

if selected_name not in lists_map:
    st.warning("Das gewählte Segment ist nicht mehr verfügbar. Bitte die Seite neu laden.")
    st.stop()

list_id = lists_map[selected_name]

# --- Verschlüsselung ---
encrypt = st.checkbox("PDF verschlüsseln")
pdf_password = ""
if encrypt:
    pdf_password = st.text_input("Passwort", type="password", placeholder="Passwort eingeben...")
    if not pdf_password:
        st.warning("Bitte ein Passwort eingeben.")
        st.stop()

# --- Dateiname ---
pdf_filename = build_pdf_filename(selected_name, lang, encrypt)
_pdf_filename_js = pdf_filename.replace("'", "\\'").replace("\\", "\\\\")

# --- Session-State-Initialisierung ---
for _key, _default in [
    ("pdf_bytes", None),
    ("pdf_ready", False),
    ("pdf_row_count", 0),
    ("pdf_filename", "Teilnehmerliste.pdf"),
    ("pdf_shrunk_company_count", 0),
    ("pdf_shrunk_company_examples", ()),
    ("last_pdf_key", None),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

# Zurücksetzen wenn Liste, Stadt, Sprache, Verschlüsselung oder Passwort geändert wird
_current_pdf_key = (list_id, city_code, lang, encrypt, pdf_password)
if st.session_state.last_pdf_key != _current_pdf_key:
    st.session_state.last_pdf_key = _current_pdf_key
    _reset_pdf_output_state()

with st.container():
    status_slot = st.empty()
    hint_slot = st.empty()
    action_slot = st.empty()

if not st.session_state.pdf_ready and action_slot.button("PDF erstellen", type="primary"):
    with st.spinner("Mitglieder laden..."):
        ids = get_list_members(list_id)

    if not ids:
        st.warning("Diese Liste enthält 0 Kontakte.")
        st.stop()

    with st.spinner("Kontakte laden (company, jobtitle)..."):
        contacts = get_contacts_by_ids(ids, properties=["company", "jobtitle"])

    df_raw = pd.DataFrame([c.get("properties", {}) for c in contacts])

    if df_raw.empty:
        st.warning("Keine Kontakteigenschaften erhalten.")
        st.stop()

    with st.spinner("Regeln anwenden..."):
        df_out = build_teilnehmerliste(df_raw, lang=lang)

    if df_out.empty:
        st.warning("Keine Einträge nach Transformation – möglicherweise sind alle Firmenfelder leer.")
        st.stop()

    shrunk_company_names = collect_shrunk_company_names(df_out, font_dir=FONT_DIR)

    with st.spinner("PDF rendern..."):
        pdf_bytes = generate_pdf_bytes(
            df=df_out,
            template_p1=TEMPLATE_P1,
            template_p2=TEMPLATE_P2,
            font_dir=FONT_DIR,
            lang=lang,
        )

    with st.spinner("PDF finalisieren..."):
        pdf_bytes = finalize_pdf_bytes(
            pdf_bytes,
            password=pdf_password if encrypt else "",
        )

    st.session_state.pdf_bytes = pdf_bytes
    st.session_state.pdf_ready = True
    st.session_state.pdf_row_count = len(df_out)
    st.session_state.pdf_filename = pdf_filename
    st.session_state.pdf_shrunk_company_count = len(shrunk_company_names)
    st.session_state.pdf_shrunk_company_examples = tuple(shrunk_company_names[:5])

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
            a.download = '{_pdf_filename_js}';
            window.parent.document.body.appendChild(a);
            a.click();
            window.parent.document.body.removeChild(a);
            setTimeout(function() {{ URL.revokeObjectURL(url); }}, 2000);
          }})();
        </script>""",
        height=0,
    )

if st.session_state.pdf_ready:
    _render_pdf_ready_block(
        status_slot=status_slot,
        hint_slot=hint_slot,
        action_slot=action_slot,
        pdf_bytes=st.session_state.pdf_bytes,
        pdf_filename=st.session_state.pdf_filename,
        row_count=st.session_state.pdf_row_count,
        shrunk_company_count=st.session_state.pdf_shrunk_company_count,
        shrunk_company_examples=st.session_state.pdf_shrunk_company_examples,
    )
else:
    status_slot.empty()
    hint_slot.empty()
