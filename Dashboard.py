# Dashboard.py
import re
from pathlib import Path

import streamlit as st
from streamlit_searchbox import st_searchbox  # pip install streamlit-searchbox
from streamlit_ui import render_page_title

st.set_page_config(page_title="Dashboard", layout="wide")

ROOT = Path(__file__).parent
PAGES_DIR = ROOT / "pages"
ROOT_CATEGORY = "__root__"          # interne Kategorie für Root-Pages (wird nicht angezeigt)
SEARCHBOX_KEY = "page_searchbox"    # eigener Key zum sauberen Reset


# ---------- Styling (UX) ----------
st.markdown(
    """
    <style>
      .stButton {
        width: 100%;
      }
      .stButton > button {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0.55rem 0.95rem;
        min-height: 3rem;
        border-radius: 16px;
        font-size: 1rem;
        font-weight: 600;
      }
      .stButton > button p {
        margin: 0;
        text-align: center;
      }
      .muted { opacity: 0.7; font-size: 0.95rem; }
      .stCaption { margin-top: -0.25rem; }
      .section-title { font-size: 1.35rem; font-weight: 700; margin: 1.1rem 0 0.6rem 0; }
      .soft-divider { height: 1px; opacity: 0.12; margin: 1.25rem 0; background: currentColor; }
      .st-key-dashboard-cards-grid [data-testid="stHorizontalBlock"] {
        gap: 0.75rem;
      }
      .st-key-dashboard-cards-grid .stButton > button {
        min-height: 3.25rem;
      }
      @media (max-width: 980px) {
        .st-key-dashboard-cards-grid [data-testid="stHorizontalBlock"] {
          flex-wrap: wrap;
        }
        .st-key-dashboard-cards-grid [data-testid="column"] {
          min-width: calc(50% - 0.375rem) !important;
          flex: 1 1 calc(50% - 0.375rem) !important;
        }
      }
      @media (max-width: 640px) {
        .st-key-dashboard-cards-grid [data-testid="column"] {
          min-width: 100% !important;
          flex: 1 1 100% !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Helpers ----------
def _pretty_part(s: str) -> str:
    s = re.sub(r"^\d+[_\- ]+", "", s)  # 01_ / 1- entfernen
    s = s.replace("_", " ").replace("-", " ").strip()
    s = re.sub(r"^[^A-Za-z0-9ÄÖÜäöüß]+", "", s).strip()  # leading Sonderzeichen/Emojis raus
    s = re.sub(r"\s+", " ", s)
    return s.title()


@st.cache_data(show_spinner=False)
def _collect_pages_cached(root_str: str, pages_dir_str: str):
    root = Path(root_str)
    pages_dir = Path(pages_dir_str)

    if not pages_dir.exists():
        return []

    files = sorted(
        p for p in pages_dir.rglob("*.py")
        if p.name != "__init__.py" and not any(part.startswith(".") for part in p.parts)
    )

    pages = []
    for p in files:
        rel = p.relative_to(pages_dir)
        parts = rel.parts

        category = _pretty_part(parts[0]) if len(parts) > 1 else ROOT_CATEGORY
        title = _pretty_part(rel.stem)

        pages.append(
            {
                "path": p.relative_to(root).as_posix(),
                "category": category,
                "title": title,
            }
        )
    return pages


def _dedupe_recent(recent_list: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in recent_list:
        path = r.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(r)
    return out


def _clear_searchbox_state():
    # searchbox speichert intern ein dict unter dem key
    st.session_state.pop(SEARCHBOX_KEY, None)


def _remember_recent(item: dict):
    recent = st.session_state.get("recent_pages", [])
    recent = _dedupe_recent(recent)

    # vorhandenen Eintrag entfernen
    recent = [x for x in recent if x.get("path") != item["path"]]
    # vorne einfügen
    recent.insert(0, {"path": item["path"], "title": item["title"]})
    # speichern
    st.session_state["recent_pages"] = recent[:6]


def _go_to(item: dict):
    _remember_recent(item)
    _clear_searchbox_state()

    if hasattr(st, "switch_page"):
        st.switch_page(item["path"])
    else:
        st.page_link(item["path"], label=item["title"])


def _render_page_button(item: dict, key_prefix: str):
    if st.button(item["title"], key=f"{key_prefix}_{item['path']}", use_container_width=True):
        _go_to(item)
    if item["category"] != ROOT_CATEGORY:
        st.caption(item["category"])


def _render_card_row(items: list[dict], key_prefix: str):
    if not items:
        return

    cols = st.columns(len(items), gap="small")
    for col, item in zip(cols, items):
        with col:
            _render_page_button(item, key_prefix=key_prefix)


def _render_dashboard_cards(items: list[dict], key_prefix: str):
    if not items:
        return

    with st.container(key="dashboard-cards-grid"):
        for start in range(0, len(items), 3):
            _render_card_row(items[start:start + 3], key_prefix=key_prefix)


def _label_for_dropdown(p: dict, title_counts: dict[str, int]) -> str:
    # Nur Titel anzeigen – Kategorie nur, wenn Titel mehrfach vorkommt
    if title_counts.get(p["title"], 0) > 1 and p["category"] != ROOT_CATEGORY:
        return f"{p['title']} · {p['category']}"
    return p["title"]


# ---------- UI ----------
render_page_title("Dashboard")

pages_all = _collect_pages_cached(str(ROOT), str(PAGES_DIR))
if not pages_all:
    st.info("Aktuell sind keine Seiten verfügbar.")
    st.stop()

# Titel-Duplikate für saubere Labels
title_counts: dict[str, int] = {}
for p in pages_all:
    title_counts[p["title"]] = title_counts.get(p["title"], 0) + 1

# Default-Vorschläge: alphabetisch
default_items = sorted(pages_all, key=lambda p: (p["title"].lower(), p["category"].lower()))[:8]

default_options = [(_label_for_dropdown(p, title_counts), p) for p in default_items]


def search_pages(searchterm: str):
    term = (searchterm or "").strip().lower()
    if not term:
        return []

    scored = []
    for p in pages_all:
        hay = f"{p['title']} {p['category']}".lower()
        if term in hay:
            # Ranking: Titel-startswith vor contains
            score = 0
            if p["title"].lower().startswith(term):
                score -= 20
            elif p["category"].lower().startswith(term):
                score -= 10
            score += len(p["title"])
            scored.append((score, p))

    scored.sort(key=lambda x: x[0])
    top = [p for _, p in scored[:10]]
    return [(_label_for_dropdown(p, title_counts), p) for p in top]


def _on_submit(selected_item):
    # Wird aufgerufen bei Auswahl (Click ODER Enter auf markiertem Vorschlag)
    if isinstance(selected_item, dict) and "path" in selected_item:
        _go_to(selected_item)


# Searchbox: Navigation direkt in submit_function (kein "sticky selected" mehr)
st_searchbox(
    search_pages,
    key=SEARCHBOX_KEY,
    placeholder="Seite suchen …",
    label=None,
    default=None,
    default_options=default_options,
    debounce=120,
    clear_on_submit=True,
    submit_function=_on_submit,
)

# ---- Alle Bereiche ----
st.markdown("<div class='soft-divider'></div>", unsafe_allow_html=True)
st.markdown("<div class='section-title'>Alle Bereiche</div>", unsafe_allow_html=True)

all_items = sorted(pages_all, key=lambda p: (p["title"].lower(), p["category"].lower()))
_render_dashboard_cards(all_items, key_prefix="nav_all")
