# Dashboard.py
import re
from pathlib import Path

import streamlit as st
from streamlit_searchbox import st_searchbox  # pip install streamlit-searchbox

st.set_page_config(page_title="Dashboard", layout="wide")

ROOT = Path(__file__).parent
PAGES_DIR = ROOT / "pages"
ROOT_CATEGORY = "__root__"          # interne Kategorie für Root-Pages (wird nicht angezeigt)
SEARCHBOX_KEY = "page_searchbox"    # eigener Key zum sauberen Reset


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
      .section-title { font-size: 1.35rem; font-weight: 700; margin: 1.1rem 0 0.6rem 0; }
      .soft-divider { height: 1px; opacity: 0.12; margin: 1.25rem 0; background: currentColor; }
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


def _label_for_dropdown(p: dict, title_counts: dict[str, int]) -> str:
    # Nur Titel anzeigen – Kategorie nur, wenn Titel mehrfach vorkommt
    if title_counts.get(p["title"], 0) > 1 and p["category"] != ROOT_CATEGORY:
        return f"{p['title']} · {p['category']}"
    return p["title"]


# ---------- UI ----------
st.markdown("<div class='section-title'>Dashboard</div>", unsafe_allow_html=True)

pages_all = _collect_pages_cached(str(ROOT), str(PAGES_DIR))
if not pages_all:
    st.info("Aktuell sind keine Seiten verfügbar.")
    st.stop()

# Titel-Duplikate für saubere Labels
title_counts: dict[str, int] = {}
for p in pages_all:
    title_counts[p["title"]] = title_counts.get(p["title"], 0) + 1

# Default-Vorschläge: zuletzt geöffnet + Fallback
recent = _dedupe_recent(st.session_state.get("recent_pages", []))
st.session_state["recent_pages"] = recent  # ggf. alte Duplikate direkt bereinigen

recent_paths = [r["path"] for r in recent]
recent_items = [p for p in pages_all if p["path"] in recent_paths]
fallback_items = pages_all[:8]

default_items = []
seen = set()
for p in (recent_items + fallback_items):
    if p["path"] not in seen:
        default_items.append(p)
        seen.add(p["path"])
    if len(default_items) >= 8:
        break

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

# ---- Zuletzt geöffnet ----
recent = _dedupe_recent(st.session_state.get("recent_pages", []))
recent_items = []
for r in recent:
    item = next((p for p in pages_all if p["path"] == r["path"]), None)
    if item:
        recent_items.append(item)

if recent_items:
    st.markdown("<div class='soft-divider'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Zuletzt geöffnet</div>", unsafe_allow_html=True)
    _render_grid(recent_items, key_prefix="recent", cols_max=4)

# ---- Alle Bereiche ----
st.markdown("<div class='soft-divider'></div>", unsafe_allow_html=True)
st.markdown("<div class='section-title'>Alle Bereiche</div>", unsafe_allow_html=True)

root_items = sorted([p for p in pages_all if p["category"] == ROOT_CATEGORY], key=lambda x: x["title"])
other_cats = sorted({p["category"] for p in pages_all if p["category"] != ROOT_CATEGORY})

# Root-Pages (ohne Überschrift)
if root_items:
    _render_grid(root_items, key_prefix="nav_root", cols_max=4)

# Kategorien
for cat in other_cats:
    st.markdown(f"<div class='section-title' style='font-size:1.15rem; margin-top:1.0rem'>{cat}</div>", unsafe_allow_html=True)
    items = sorted([p for p in pages_all if p["category"] == cat], key=lambda x: x["title"])
    _render_grid(items, key_prefix=f"nav_{cat}", cols_max=4)