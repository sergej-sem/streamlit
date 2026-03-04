# Dashboard.py
import re
from pathlib import Path

import streamlit as st
from streamlit_searchbox import st_searchbox  # pip install streamlit-searchbox

st.set_page_config(page_title="Dashboard", layout="wide")

ROOT = Path(__file__).parent
PAGES_DIR = ROOT / "pages"
ROOT_CATEGORY = "__root__"  # interne Kategorie für Root-Pages (wird nicht angezeigt)


# ---------- Styling (UX) ----------
st.markdown(
    """
    <style>
      .stButton > button {
        width: 100%;
        padding: 1.05rem 1rem;
        border-radius: 16px;
        font-size: 1.05rem;
        font-weight: 600;
      }
      div.block-container { padding-top: 2.2rem; }
      .muted { opacity: 0.7; font-size: 0.95rem; }
      .stCaption { margin-top: -0.25rem; }
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


def _go_to(item: dict):
    # Zuletzt geöffnet merken
    recent = st.session_state.get("recent_pages", [])
    recent = [x for x in recent if x["path"] != item["path"]]
    recent.insert(0, {"path": item["path"], "title": item["title"]})
    st.session_state["recent_pages"] = recent[:6]

    # Navigation
    if hasattr(st, "switch_page"):
        st.switch_page(item["path"])
    else:
        st.page_link(item["path"], label=item["title"])


def _render_grid(items: list[dict], key_prefix: str, cols_max: int = 4):
    if not items:
        return

    n_cols = min(cols_max, max(2, len(items))) if len(items) > 1 else 1
    cols = st.columns(n_cols)

    for i, item in enumerate(items):
        with cols[i % n_cols]:
            if st.button(item["title"], key=f"{key_prefix}_{item['path']}"):
                _go_to(item)
            if item["category"] != ROOT_CATEGORY:
                st.caption(item["category"])


# ---------- UI ----------
st.title("Dashboard")
st.markdown('<div class="muted">Seite suchen oder direkt auswählen.</div>', unsafe_allow_html=True)

pages_all = _collect_pages_cached(str(ROOT), str(PAGES_DIR))
if not pages_all:
    st.info("Aktuell sind keine Seiten verfügbar.")
    st.stop()

# Titel-Duplikate erkennen (damit Dropdown sauber bleibt)
title_counts = {}
for p in pages_all:
    title_counts[p["title"]] = title_counts.get(p["title"], 0) + 1

# Default-Vorschläge (zuletzt geöffnet + Fallback)
recent = st.session_state.get("recent_pages", [])
recent_paths = [r["path"] for r in recent]
recent_items = [p for p in pages_all if p["path"] in recent_paths]
fallback_items = pages_all[:8]

default_items = []
seen = set()
for p in recent_items + fallback_items:
    if p["path"] not in seen:
        default_items.append(p)
        seen.add(p["path"])
    if len(default_items) >= 8:
        break

def _label_for_dropdown(p: dict) -> str:
    # Standard: nur Titel (ohne Kategorie)
    # Wenn Titel mehrfach vorkommt: Titel + Kategorie zur Unterscheidung
    if title_counts.get(p["title"], 0) > 1 and p["category"] != ROOT_CATEGORY:
        return f"{p['title']} · {p['category']}"
    return p["title"]

default_options = [(_label_for_dropdown(p), p) for p in default_items]

# Search-Funktion: liefert nur Top-N Treffer (UX: schnell, "echte" Suche)
def search_pages(searchterm: str):
    term = (searchterm or "").strip().lower()
    if not term:
        return []

    results = []
    for p in pages_all:
        hay = f"{p['title']} {p['category']}".lower()
        if term in hay:
            # Ranking: startswith im Titel vor contains
            score = 0
            if p["title"].lower().startswith(term):
                score -= 20
            elif p["category"].lower().startswith(term):
                score -= 10
            score += len(p["title"])  # leicht: kürzer = besser
            results.append((score, p))

    results.sort(key=lambda x: x[0])
    top = [p for _, p in results[:10]]
    return [(_label_for_dropdown(p), p) for p in top]

# --- Searchbox (Autocomplete Dropdown beim Tippen) ---
selected = st_searchbox(
    search_pages,
    placeholder="Seite suchen …",
    label=None,
    clear_on_submit=True,
    default=None,
    default_options=default_options,
    debounce=120,
)

# Sofort weiterleiten, wenn ausgewählt
if selected:
    _go_to(selected)

# Luft statt Linien
st.markdown("<div style='height: 1.2rem'></div>", unsafe_allow_html=True)

# ---- Zuletzt geöffnet ----
recent = st.session_state.get("recent_pages", [])
if recent:
    st.subheader("Zuletzt geöffnet")
    recent_items = []
    for r in recent:
        item = next((p for p in pages_all if p["path"] == r["path"]), None)
        if item:
            recent_items.append(item)
    _render_grid(recent_items, key_prefix="recent", cols_max=4)
    st.markdown("<div style='height: 1.2rem'></div>", unsafe_allow_html=True)

# ---- Alle Seiten (Root zuerst ohne Überschrift, dann Kategorien) ----
root_items = sorted([p for p in pages_all if p["category"] == ROOT_CATEGORY], key=lambda x: x["title"])
other_cats = sorted({p["category"] for p in pages_all if p["category"] != ROOT_CATEGORY})

# Root-Pages: ohne Überschrift
if root_items:
    _render_grid(root_items, key_prefix="nav_root", cols_max=4)
    if other_cats:
        st.markdown("<div style='height: 1.0rem'></div>", unsafe_allow_html=True)

# Kategorien
for cat in other_cats:
    st.subheader(cat)
    items = sorted([p for p in pages_all if p["category"] == cat], key=lambda x: x["title"])
    _render_grid(items, key_prefix=f"nav_{cat}", cols_max=4)
    st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)