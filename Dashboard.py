# Dashboard.py
import re
from pathlib import Path

import streamlit as st
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
      .sidebar-hint {
        display: flex; align-items: center; gap: 0.65rem;
        padding: 0.55rem 1.1rem; border-radius: 10px;
        background: rgba(0,0,0,0.04); border-left: 4px solid rgba(0,0,0,0.18);
        font-size: 1rem; font-weight: 500;
        margin: 0.1rem 0 1rem 0; width: fit-content;
      }
      .sidebar-hint-arrow { font-size: 1.7rem; line-height: 1; }
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
    # selectbox speichert direkt den ausgewählten Label-String unter dem key
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


def _selectbox_options_and_lookup(items: list[dict], title_counts: dict[str, int]) -> tuple[list[str], dict[str, dict]]:
    options: list[str] = []
    lookup: dict[str, dict] = {}
    for item in items:
        label = _label_for_dropdown(item, title_counts)
        options.append(label)
        lookup[label] = item
    return options, lookup


# ---------- UI ----------
render_page_title("Dashboard")

st.markdown(
    "<div class='sidebar-hint'>"
    "<span class='sidebar-hint-arrow'>⬅</span>"
    "<span>Weitere Seiten findest du in der <strong>Sidebar</strong> links</span>"
    "</div>",
    unsafe_allow_html=True,
)

pages_all = _collect_pages_cached(str(ROOT), str(PAGES_DIR))
if not pages_all:
    st.info("Aktuell sind keine Seiten verfügbar.")
    st.stop()

# Titel-Duplikate für saubere Labels
title_counts: dict[str, int] = {}
for p in pages_all:
    title_counts[p["title"]] = title_counts.get(p["title"], 0) + 1

search_options, search_lookup = _selectbox_options_and_lookup(
    sorted(pages_all, key=lambda p: (p["title"].lower(), p["category"].lower())),
    title_counts,
)


def _on_page_select() -> None:
    selected_label = st.session_state.get(SEARCHBOX_KEY)
    if not selected_label:
        return
    item = search_lookup.get(selected_label)
    if item:
        _go_to(item)


st.selectbox(
    "Seite suchen",
    options=search_options,
    key=SEARCHBOX_KEY,
    placeholder="Seite suchen …",
    index=None,
    label_visibility="collapsed",
    on_change=_on_page_select,
)

# ---- Alle Bereiche ----
st.markdown("<div class='soft-divider'></div>", unsafe_allow_html=True)
st.markdown("<div class='section-title'>Alle Bereiche</div>", unsafe_allow_html=True)

all_items = sorted(pages_all, key=lambda p: (p["title"].lower(), p["category"].lower()))
_render_dashboard_cards(all_items, key_prefix="nav_all")
