"""
Packliste – Streamlit page
==========================

Single authoritative truth: st.session_state["pl_df"]

Architecture (optimised for fluid checkbox UX)
───────────────────────────────────────────────
  • Checkbox click  → @st.fragment reruns (fast, ~50-100 ms)
                    → NO full-app rerun triggered per click
                    → NO widget remount, NO scroll reset
  • on_change callback fires BEFORE the fragment body re-executes:
      _sync_edits / _sync_verladen
        → pl_df updated
        → _auto_save()  (sidecar sync + async Excel)
        → pl_version NOT bumped  ← key stays stable, widget stays alive
  • Fragment body runs with the SAME pl_version:
      → SAME key → SAME widget instance → SAME frozen_base
      → edited_rows preserved intact by Streamlit
      → visual = frozen_base + edited_rows = pl_df  ✓

State layers
────────────
  pl_df         sole authoritative truth; only _sync_edits/_sync_verladen write here
  frozen_base   stable view-basis for st.data_editor; NEVER modified between
                undo/load events; created once per (tab, session/version)
  edited_rows   Streamlit's in-flight delta from frozen_base; accumulates across
                all clicks on the same widget instance; never discarded as long as
                the base and key stay the same
  pl_version    bumped ONLY on undo and file-load (intentional full rebuilds)

Why the visual stays correct without per-click version bumps:
  The editor renders frozen_base + edited_rows.  After each commit:
    frozen_base[row] = initial value (unchanged)
    edited_rows[row] = user's latest value
    → visual = user's latest value = pl_df value  ✓
  As long as the key and base are stable, Streamlit preserves edited_rows
  across fragment reruns, so every accumulated click remains visible.
  There is no race condition because there is no full-app rerun per click —
  the only scenario where edited_rows could be lost by Streamlit is when the
  base DataFrame changes or a new key is used, neither of which happens here.

Why this did NOT regress the old "UI empty, model correct" bug:
  That bug required a full-app rerun (which could reset edited_rows via a
  stale browser delta).  With no full-app rerun per click, that race cannot
  occur.  On browser-refresh the sidecar is loaded, pl_version resets to 1,
  and a fresh frozen_base is built from the restored pl_df — both start from
  the same committed state, so the visual is immediately correct.

Global metrics live in the separate "Übersicht" tab, decoupled from the
fast click path.

Persistence (two-stage save)
─────────────────────────────
  Stage 1 – Sidecar (sync, ~1 ms, atomic pickle next to the Excel file)
      Written synchronously inside the on_change callback.
      Data survives any browser-refresh from this point on.
      File: <excel_stem>_autosave.pkl

  Stage 2 – Excel (async background thread, generation-tracked)
      Only the LATEST generation snapshot reaches the file.
      Near-atomic: writes to <stem>.tmp.xlsx first, then renames.
      No st.* calls inside the worker thread.

Startup / browser-refresh
──────────────────────────
  1. Read .packliste_meta.json → last-active Excel path.
  2. restore_state_for_path(path):
       sidecar newer than Excel → load from sidecar + kick off Excel sync.
       otherwise               → load from Excel directly.
  3. Session-state populated, page renders – user sees previous state instantly.

Row identity
────────────
  Packen/Ersetzen/Definitionen: frozen_base.index[pos] is the original pandas
  integer index (0-based from pd.read_excel), preserved through sort/filter.
  Maps 1-to-1 to pl_df rows regardless of how the view is filtered/sorted.
  Verladen: content-based matching (Bereich + Kategorie) via groupby aggregation.
  Both strategies are stable; no separate row-ID column is needed.
"""

import logging
import threading
import time
from functools import partial
from pathlib import Path

import pandas as pd
import streamlit as st
from packliste.editor_sync import (
    flush_full_rerun_after_editor_commit,
    get_frozen_base,
    make_callback,
)
from packliste.export import download_filename as _download_filename
from packliste.export import to_excel_bytes as _to_excel_bytes
from packliste.overview import build_overview_stats as _build_overview_stats
from packliste.state import (
    apply_redo,
    apply_undo,
    drop_fully_empty_editor_rows,
    init_session_state,
    normalize_editor_mode_df,
    push_history,
)
from packliste.storage import (
    _write_sidecar,
    load_df as _load_df_impl,
    load_last_active_path as _load_last_active_path_impl,
    restore_state_for_path as _restore_state_for_path_impl,
    save_df as _save_df_impl,
    save_last_active_path as _save_last_active_path_impl,
)
from streamlit_ui import apply_page_title_style, page_title_html

st.set_page_config(page_title="Packliste", layout="wide")

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
_log = logging.getLogger("packliste")

# ── Constants ──────────────────────────────────────────────────────────────────

_ERROR_TOAST_CSS = """<style>
div[data-testid="stToast"] {
    background-color: #F1C40F !important;
    border: none !important;
}
div[data-testid="stToast"] p,
div[data-testid="stToast"] span,
div[data-testid="stToast"] div {
    color: #000000 !important;
}
</style>"""

_CRITICAL_TOAST_CSS = """<style>
div[data-testid="stToast"] {
    background-color: #C0392B !important;
    border: none !important;
}
div[data-testid="stToast"] p,
div[data-testid="stToast"] span,
div[data-testid="stToast"] div {
    color: white !important;
}
</style>"""

_SUCCESS_TOAST_CSS = """<style>
div[data-testid="stToast"] {
    background-color: #27AE60 !important;
    border: none !important;
}
div[data-testid="stToast"] p,
div[data-testid="stToast"] span,
div[data-testid="stToast"] div {
    color: white !important;
}
</style>"""

SHEET_NAME        = "Packliste"
HEADER_ROW_IDX    = 2
DATA_START_XL_ROW = 4
CHECKED           = "☒"
UNCHECKED         = "☐"
CHECKBOX_COLS     = [
    "Verpackt", "Nachfüllen", "Reinigung",
    "kurz vor Event packen", "Verladen",
]
DEFAULT_PATH = ""
MAX_HISTORY  = 30

REQUIRED_COLS = [
    "Bereich", "Gegenstand", "Beschreibung", "Menge",
    "Kategorie", "Notizen", "Verpackt", "Nachfüllen",
    "Reinigung", "kurz vor Event packen",
]

# Persists last-active Excel path across browser refreshes
_META_FILE = Path(__file__).parent / ".packliste_meta.json"

# ── Thread-shared state (persisted via cache_resource across reruns) ──────────
#
# Streamlit re-executes the entire script on every rerun.  A plain module-level
# assignment like `_excel_result = {...}` would therefore RESET the dict to
# {"status": "ok"} on every rerun — the background thread's "error" result
# would be lost immediately and the save button would always show "Gespeichert".
# The same reset would zero out _save_gen, causing the gen-check inside the
# worker to fail (thread gen ≠ 0) and skip the write entirely.
#
# st.cache_resource returns the SAME object on every rerun, so the background
# thread and the current script run always share the identical dict / list /
# Lock instances.

@st.cache_resource
def _get_thread_state() -> dict:
    return {
        "save_lock":     threading.Lock(),
        "save_gen_lock": threading.Lock(),
        "save_gen":      [0],
        "excel_result_lock": threading.Lock(),
        "excel_result":  {
            "status": "idle",
            "error": None,
            "active_gen": 0,
            "completed_gen": 0,
            "updated_at": 0.0,
        },
    }

_ts            = _get_thread_state()
_ts.setdefault("excel_result_lock", threading.Lock())
_ts.setdefault("excel_result", {})
_ts["excel_result"].setdefault("status", "idle")
_ts["excel_result"].setdefault("error", None)
_ts["excel_result"].setdefault("active_gen", 0)
_ts["excel_result"].setdefault("completed_gen", 0)
_ts["excel_result"].setdefault("updated_at", 0.0)
_save_lock     = _ts["save_lock"]
_save_gen_lock = _ts["save_gen_lock"]
_save_gen      = _ts["save_gen"]
_excel_result_lock = _ts["excel_result_lock"]
_excel_result  = _ts["excel_result"]

# -- Meta-file helpers (last-active path) -------------------------------

save_last_active_path = partial(_save_last_active_path_impl, _META_FILE, logger=_log)

load_last_active_path = partial(_load_last_active_path_impl, _META_FILE, logger=_log)


# -- State restoration ---------------------------------------------------

restore_state_for_path = partial(
    _restore_state_for_path_impl,
    sheet_name=SHEET_NAME,
    required_cols=REQUIRED_COLS,
    checkbox_cols=CHECKBOX_COLS,
    checked_value=CHECKED,
    logger=_log,
)


# -- Excel I/O ----------------------------------------------------------

load_df = partial(
    _load_df_impl,
    sheet_name=SHEET_NAME,
    required_cols=REQUIRED_COLS,
    checkbox_cols=CHECKBOX_COLS,
    checked_value=CHECKED,
)


save_df = partial(
    _save_df_impl,
    sheet_name=SHEET_NAME,
    required_cols=REQUIRED_COLS,
    checkbox_cols=CHECKBOX_COLS,
    checked_value=CHECKED,
    unchecked_value=UNCHECKED,
)


def _cc_text(label: str, width: str = "medium") -> st.column_config.TextColumn:
    return st.column_config.TextColumn(label, width=width)


def _cc_number_left(label: str, width: str | None = None, fmt: str = "%d") -> dict:
    cfg = st.column_config.NumberColumn(label, width=width, format=fmt)
    cfg["alignment"] = "left"
    return cfg

def _cc_check(label: str) -> st.column_config.CheckboxColumn:
    return st.column_config.CheckboxColumn(label)


def _render_excel_download(
    df: pd.DataFrame,
    *,
    slug: str,
    key: str,
    label: str = "Liste als Excel herunterladen",
    sheet_name: str = "Liste",
    use_container_width: bool = False,
    help: str | None = None,
) -> None:
    st.download_button(
        label,
        data=_to_excel_bytes(df, sheet_name=sheet_name, checkbox_cols=CHECKBOX_COLS),
        file_name=_download_filename(st.session_state.get("pl_path"), slug),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
        use_container_width=use_container_width,
        help=help,
    )


def _build_editor_mode_column_config(df: pd.DataFrame) -> dict[str, object]:
    known_text = {
        "Bereich": _cc_text("Bereich", width="small"),
        "Gegenstand": _cc_text("Gegenstand", width="medium"),
        "Beschreibung": _cc_text("Beschreibung", width="large"),
        "Menge": _cc_text("Menge", width="small"),
        "Kategorie": _cc_text("Kategorie", width="small"),
        "Notizen": _cc_text("Notizen", width="large"),
    }
    cfg: dict[str, object] = {}
    for col in df.columns:
        if col in CHECKBOX_COLS or col == "Verladen":
            cfg[col] = _cc_check(str(col))
        else:
            cfg[col] = known_text.get(str(col), _cc_text(str(col), width="medium"))
    return cfg


def _table_height_for_rows(
    row_count: int,
    *,
    min_rows: int,
    max_rows: int,
    header_px: int = 38,
    row_px: int = 35,
) -> int:
    visible_rows = min(max(row_count, 1), max_rows)
    return header_px + visible_rows * row_px


def _render_overview_stats_table(
    title: str,
    stats: pd.DataFrame,
    *,
    value_label: str,
    row_color: str = "#3B82F6",
    total_color: str = "#0F766E",
    note: str | None = None,
) -> None:
    _render_overview_stats_df(title, stats, value_label=value_label, note=note)
    return

    st.subheader(title)
    if note:
        st.caption(note)
    if stats.empty:
        st.info("Keine Daten verfügbar.")
        return

    rows_html: list[str] = []
    for _, row in stats.iterrows():
        bereich = str(row["Bereich"])
        value = int(row[value_label])
        total = int(row["Gesamt"])
        progress = max(0, min(int(row["Fortschritt"]), 100))
        is_total = bereich == "Gesamt"
        bar_color = total_color if is_total else row_color
        weight = "700" if is_total else "500"
        border_top = "border-top:2px solid #CBD5E1;" if is_total else ""

        rows_html.append(
            f"""
            <tr style="font-weight:{weight};{border_top}">
                <td>{html.escape(bereich)}</td>
                <td style="text-align:right;">{value}</td>
                <td style="text-align:right;">{total}</td>
                <td>
                    <div style="display:flex;align-items:center;gap:12px;">
                        <div style="flex:1;height:10px;background:#E8EDF3;border-radius:999px;overflow:hidden;">
                            <div style="width:{progress}%;height:100%;background:{bar_color};border-radius:999px;"></div>
                        </div>
                        <span style="min-width:46px;text-align:right;color:#475569;">{progress} %</span>
                    </div>
                </td>
            </tr>
            """
        )

    st.markdown(
        f"""
        <div class="ov-stats-card" style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin-bottom:1rem;">
            <table class="ov-stats-table" style="width:100%;border-collapse:collapse;font-size:0.98rem;">
                <thead>
                    <tr style="background:#F8FAFC;color:#64748B;">
                        <th style="text-align:left;padding:12px 14px;border-bottom:1px solid #E5E7EB;">Bereich</th>
                        <th style="text-align:right;padding:12px 14px;border-bottom:1px solid #E5E7EB;">{html.escape(value_label)}</th>
                        <th style="text-align:right;padding:12px 14px;border-bottom:1px solid #E5E7EB;">Gesamt</th>
                        <th style="text-align:left;padding:12px 14px;border-bottom:1px solid #E5E7EB;">Fortschritt</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
        <style>
        .ov-stats-card .ov-stats-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid #EEF2F7;
            background: #FFFFFF;
        }}
        .ov-stats-card .ov-stats-table tbody tr:last-child td {{
            border-bottom: none;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── History ────────────────────────────────────────────────────────────────────

def _render_overview_stats_df(
    title: str,
    stats: pd.DataFrame,
    *,
    value_label: str,
    note: str | None = None,
) -> None:
    st.subheader(title)
    if note:
        st.caption(note)
    if stats.empty:
        st.info("Keine Daten verfuegbar.")
        return

    view = stats.loc[:, ["Bereich", value_label, "Gesamt", "Fortschritt"]].copy()
    view["Fortschritt"] = view["Fortschritt"].astype(int).clip(lower=0, upper=100)
    progress_cfg = st.column_config.ProgressColumn(
        "Fortschritt",
        format="%d%%",
        min_value=0,
        max_value=100,
    )
    progress_cfg["alignment"] = "left"

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        height=_table_height_for_rows(len(view), min_rows=4, max_rows=10),
        column_config={
            "Bereich": st.column_config.TextColumn("Bereich", width="medium"),
            value_label: _cc_number_left(value_label, fmt="%d"),
            "Gesamt": _cc_number_left("Gesamt", fmt="%d"),
            "Fortschritt": progress_cfg,
        },
    )


# ── Two-stage save pipeline ────────────────────────────────────────────────────

def _set_excel_result_saving(gen: int) -> None:
    with _excel_result_lock:
        _excel_result["status"] = "saving"
        _excel_result["error"] = None
        _excel_result["active_gen"] = gen
        _excel_result["updated_at"] = time.time()


def _set_excel_result_finished(gen: int, *, error: str | None = None) -> None:
    with _excel_result_lock:
        if gen != _excel_result.get("active_gen", 0):
            return
        _excel_result["status"] = "error" if error else "ok"
        _excel_result["error"] = error
        _excel_result["completed_gen"] = gen
        _excel_result["updated_at"] = time.time()


def _get_excel_result_snapshot() -> dict:
    with _excel_result_lock:
        return dict(_excel_result)


def _wait_for_excel_result(
    gen: int,
    *,
    timeout_s: float = 4.0,
    poll_s: float = 0.05,
) -> dict:
    deadline = time.monotonic() + timeout_s
    snapshot = _get_excel_result_snapshot()
    while snapshot.get("completed_gen", 0) < gen and time.monotonic() < deadline:
        time.sleep(poll_s)
        snapshot = _get_excel_result_snapshot()
    return snapshot


def _auto_save() -> int:
    """
    Stage 1 – Sidecar (sync, ~1 ms):
        Atomic pickle.  Data survives any refresh from this point on.
        Errors surfaced immediately via st.toast (no silent swallowing).

    Stage 2 – Excel (async background thread, generation-tracked):
        Only the latest generation writes; older snapshots are dropped.
        No st.* calls inside the worker.
    """
    df_snapshot = st.session_state["pl_df"].copy()
    path        = st.session_state["pl_path"]

    # Stage 1: synchronous sidecar ────────────────────────────────────────────
    try:
        _write_sidecar(df_snapshot, path)
        st.session_state.pop("pl_sidecar_err", None)
    except Exception as exc:
        msg = str(exc)
        _log.error("Sidecar write failed: %s", msg)
        st.session_state["pl_sidecar_err"] = msg
        st.toast(f"⚠️ Autosave-Fehler – Refresh könnte Daten verlieren: {msg}", icon="⚠️")

    # Stage 2: async Excel ────────────────────────────────────────────────────
    with _save_gen_lock:
        _save_gen[0] += 1
        my_gen = _save_gen[0]
    _set_excel_result_saving(my_gen)

    def _worker(df_copy: pd.DataFrame, p: str, gen: int) -> None:
        time.sleep(1.0)   # batch window – coalesces rapid edits
        with _save_gen_lock:
            if gen != _save_gen[0]:
                _log.info("Excel save gen %d superseded by %d – skipped",
                          gen, _save_gen[0])
                return
        with _save_lock:
            with _save_gen_lock:
                if gen != _save_gen[0]:
                    return
            try:
                save_df(df_copy, p)
                _set_excel_result_finished(gen)
                _log.info("Excel save gen %d complete", gen)
            except Exception as exc:
                _set_excel_result_finished(gen, error=str(exc))
                _log.error("Excel save gen %d failed: %s", gen, exc)

    threading.Thread(
        target=_worker, args=(df_snapshot, path, my_gen), daemon=True
    ).start()
    return my_gen


# ── Session-state init ─────────────────────────────────────────────────────────

init_session_state(st.session_state, DEFAULT_PATH)


# ── Auto-load on startup / browser-refresh ─────────────────────────────────────
# st.session_state is empty after a browser-refresh → restore transparently.

if st.session_state["pl_df"] is None:
    _path = load_last_active_path()
    if _path:
        try:
            _df, _src = restore_state_for_path(_path)
            st.session_state["pl_df"]      = _df
            st.session_state["pl_path"]    = _path
            st.session_state["pl_version"] = 1
            save_last_active_path(_path)
            if _src == "sidecar":
                st.session_state["_al_msg"] = "🔄 Stand aus Autosave wiederhergestellt."
                _auto_save()   # sync sidecar state back to Excel in background
        except Exception as _exc:
            st.session_state["_al_err"] = str(_exc)


# ── Header ─────────────────────────────────────────────────────────────────────
# Minimal: title + save status + undo.
# Global metrics are in the "Übersicht" tab → not part of the click flow.

_excel_result_snapshot = _get_excel_result_snapshot()
if _excel_result_snapshot["status"] == "error":
    st.session_state["pl_excel_err"] = _excel_result_snapshot["error"]
elif _excel_result_snapshot["status"] == "ok":
    st.session_state.pop("pl_excel_err", None)

apply_page_title_style()

hist_len = len(st.session_state.get("pl_history", []))
redo_len = len(st.session_state.get("pl_redo_stack", []))
title_col, btn_col = st.columns([6, 4])

with title_col:
    st.markdown(page_title_html("Packliste"), unsafe_allow_html=True)

with btn_col:
    st.markdown("<div style='margin-top:1.1rem'></div>", unsafe_allow_html=True)
    save_col, undo_col, redo_col, export_col = st.columns(4)
    with save_col:
        if st.button("💾", use_container_width=True, key="save_status_btn",
                     help="Speichern"):
            # Neuen Speicherversuch starten (Retry), damit ein zuvor fehlgeschlagener
            # Save nach Schließen der Excel-Datei erneut versucht wird.
            save_result = None
            if st.session_state.get("pl_df") is not None:
                save_gen = _auto_save()
                save_result = _wait_for_excel_result(save_gen)
            if save_result is not None:
                if st.session_state.get("pl_sidecar_err"):
                    st.markdown(_CRITICAL_TOAST_CSS, unsafe_allow_html=True)
                    st.toast("Autosave-Fehler!")
                elif save_result["completed_gen"] < save_gen or save_result["status"] == "saving":
                    st.toast("⏳ Speichern läuft noch…")
                elif save_result["status"] == "error":
                    st.session_state["pl_excel_err"] = save_result["error"]
                    st.markdown(_ERROR_TOAST_CSS, unsafe_allow_html=True)
                    st.toast("Excel nicht aktualisiert – Excel-Datei schließen und erneut speichern")
                else:
                    st.session_state.pop("pl_excel_err", None)
                    st.markdown(_SUCCESS_TOAST_CSS, unsafe_allow_html=True)
                    st.toast("Gespeichert")
    with undo_col:
        undo_label = "↩"
        if st.button(undo_label, disabled=(hist_len == 0),
                     use_container_width=True, key="undo_btn",
                     help="Letzte Änderung rückgängig machen"):
            if apply_undo(st.session_state, MAX_HISTORY):
                _auto_save()
                st.rerun()
    with redo_col:
        if st.button("↪", disabled=(redo_len == 0),
                     use_container_width=True, key="redo_btn",
                     help="Wiederherstellen"):
            if apply_redo(st.session_state, MAX_HISTORY):
                _auto_save()
                st.rerun()

    with export_col:
        if st.session_state.get("pl_df") is not None:
            _render_excel_download(
                st.session_state["pl_df"],
                slug="gesamt",
                key="dl_gesamt",
                label="Notfall-Export",
                sheet_name="Packliste",
                use_container_width=True,
                help="Gesamten aktuellen Arbeitsstand als Excel exportieren",
            )

# Fehler-Meldungen unterhalb des Headers, volle Breite
if st.session_state.get("pl_sidecar_err"):
    st.error(f"⚠️ Autosave-Fehler: {st.session_state['pl_sidecar_err']}")
elif st.session_state.get("pl_excel_err"):
    st.warning(
        f"⚠️ Excel nicht aktualisiert (Daten in Autosave gesichert): "
        f"{st.session_state['pl_excel_err']}"
    )
if msg := st.session_state.pop("_al_msg", None):
    st.info(msg)
if err := st.session_state.pop("_al_err", None):
    st.error(f"Fehler beim Auto-Laden: {err}")


if st.session_state.get("pl_df") is not None:
    editor_source = st.session_state["pl_df"].reset_index(drop=True)
    with st.expander("✏️ Editor-Modus", expanded=False):
        st.caption(
            "Nur hier koennen Zeilen hinzugefuegt oder entfernt werden. "
            "Aenderungen werden erst nach 'Aenderungen uebernehmen' aktiv; "
            "Undo bleibt global verfuegbar."
        )
        with st.form("pl_editor_mode_form"):
            editor_df = st.data_editor(
                editor_source,
                key=f"pl_editor_mode_table_{st.session_state['pl_version']}",
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                height=_table_height_for_rows(len(editor_source), min_rows=1, max_rows=18),
                column_config=_build_editor_mode_column_config(editor_source),
            )
            apply_editor_changes = st.form_submit_button(
                "Aenderungen uebernehmen",
                type="primary",
            )

        if apply_editor_changes:
            current_df = st.session_state["pl_df"].reset_index(drop=True)
            edited_df = normalize_editor_mode_df(editor_df, current_df.columns, CHECKBOX_COLS)
            edited_df = drop_fully_empty_editor_rows(edited_df, CHECKBOX_COLS)
            current_norm = normalize_editor_mode_df(current_df, current_df.columns, CHECKBOX_COLS)

            if edited_df.equals(current_norm):
                st.info("Keine Aenderungen zum Uebernehmen.")
            else:
                push_history(st.session_state, MAX_HISTORY)
                st.session_state["pl_df"] = edited_df
                st.session_state["pl_version"] += 1
                _auto_save()
                st.rerun()


# ── File loader ────────────────────────────────────────────────────────────────

with st.expander(
    "📂 Datei laden" if st.session_state["pl_df"] is None else "📂 Andere Datei laden",
    expanded=st.session_state["pl_df"] is None,
):
    path_input = st.text_input(
        "Dateipfad zur Excel-Datei",
        value=st.session_state["pl_path"],
        key="pl_path_input",
    )
    if st.button("Laden", key="load_btn", type="primary"):
        try:
            new_df = load_df(path_input)
            _write_sidecar(new_df, path_input)
            save_last_active_path(path_input)
            st.session_state["pl_df"]      = new_df
            st.session_state["pl_path"]    = path_input
            st.session_state["pl_version"] += 1
            st.session_state["pl_history"] = []
            st.session_state["pl_redo_stack"] = []
            st.rerun()   # full-app rerun intentional: resets all tab views
        except Exception as exc:
            st.error(f"Fehler beim Laden:\n{exc}")

if st.session_state["pl_df"] is None:
    st.stop()

# Achtung, wenn Gebrauchsgegenstände (Ersetzen) Notizen haben
df = st.session_state["pl_df"]
if "Nachfüllen" in df.columns and "Notizen" in df.columns:
    ers_df = df.loc[~df["Nachfüllen"].astype(bool), "Notizen"]
    hat_notizen = ers_df.apply(
        lambda v: bool(pd.notna(v) and str(v).strip())
    ).any()
    if hat_notizen:
        st.warning(
            "⚠️ Achtung: Es gibt offene Notizen bei den Gebrauchsgegenständen "
            "(Tab Ersetzen)."
        )

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_pack, tab_verl, tab_ers, tab_ueb, tab_def = st.tabs(
    ["📦 Packen", "🚚 Verladen", "🔄 Ersetzen", "📊 Übersicht", "📋 Definitionen"]
)


# ── Fragments ──────────────────────────────────────────────────────────────────
# Each fragment is self-contained: it reads pl_df, builds its frozen_base,
# renders its editor(s), and registers its on_change callback.
# Nach Commit setzen _sync_* ein Flag; Fragment startet mit
# _flush_full_rerun_after_editor_commit() (Rerun nur außerhalb Callback).

@st.fragment
def _frag_packen() -> None:
    flush_full_rerun_after_editor_commit(st.session_state, rerun=st.rerun)
    ver  = st.session_state["pl_version"]
    df   = st.session_state["pl_df"]
    pcfg = {
        "Bereich":    _cc_text("Bereich",    width="small"),
        "Gegenstand": _cc_text("Gegenstand", width="medium"),
        "Menge":      _cc_text("Menge",      width="small"),
        "Kategorie":  _cc_text("Kategorie",  width="small"),
        "Verpackt":   _cc_check("Verpackt"),
    }

    # ── Jetzt reinigen und packen ──────────────────────────────────────────────
    st.subheader("Jetzt reinigen und packen")
    cr     = ["Bereich", "Gegenstand", "Menge", "Kategorie", "Verpackt"]
    bk_r   = f"b_rein_{ver}"
    view_r = df.loc[df["Reinigung"].astype(bool), cr].sort_values("Bereich")
    base_r = get_frozen_base(
        st.session_state,
        bk_r,
        view_r,
        logger=_log,
    )
    ek_r = f"e_rein_{ver}"
    if base_r.empty:
        st.info("Keine Positionen mit angekreuztem Reinigung-Kästchen.")
    else:
        st.caption(f"{len(base_r)} Position(en)")
        st.data_editor(
            base_r, key=ek_r, use_container_width=True,
            hide_index=True, num_rows="fixed",
            height=_table_height_for_rows(len(base_r), min_rows=6, max_rows=14),
            on_change=make_callback(
                st.session_state,
                ek_r,
                base_r,
                push_history=push_history,
                max_history=MAX_HISTORY,
                autosave=_auto_save,
                logger=_log,
            ),
            column_config={k: v for k, v in pcfg.items() if k in cr},
        )
    st.divider()

    # ── Jetzt packen ──────────────────────────────────────────────────────────
    st.subheader("Jetzt packen – Verbrauchsgegenstände")
    cn     = ["Bereich", "Gegenstand", "Menge", "Kategorie", "Verpackt"]
    bk_n   = f"b_nach_{ver}"
    view_n = df.loc[df["Nachfüllen"].astype(bool), cn].sort_values("Bereich")
    base_n = get_frozen_base(
        st.session_state,
        bk_n,
        view_n,
        logger=_log,
    )
    ek_n = f"e_nach_{ver}"
    if base_n.empty:
        st.info("Keine Positionen mit angekreuztem Nachfüllen-Kästchen.")
    else:
        st.caption(f"{len(base_n)} Position(en)")
        st.data_editor(
            base_n, key=ek_n, use_container_width=True,
            hide_index=True, num_rows="fixed",
            height=_table_height_for_rows(len(base_n), min_rows=6, max_rows=14),
            on_change=make_callback(
                st.session_state,
                ek_n,
                base_n,
                push_history=push_history,
                max_history=MAX_HISTORY,
                autosave=_auto_save,
                logger=_log,
            ),
            column_config={k: v for k, v in pcfg.items() if k in cn},
        )
    st.divider()

    # ── Kurz vor Event packen ──────────────────────────────────────────────────
    st.subheader("Kurz vor Event packen")
    ce     = ["Bereich", "Gegenstand", "Menge", "Kategorie", "Verpackt"]
    bk_e   = f"b_event_{ver}"
    view_e = df.loc[df["kurz vor Event packen"].astype(bool), ce].sort_values("Bereich")
    base_e = get_frozen_base(
        st.session_state,
        bk_e,
        view_e,
        logger=_log,
    )
    ek_e = f"e_event_{ver}"
    if base_e.empty:
        st.info("Keine Positionen mit angekreuztem 'Kurz vor Event packen'-Kästchen.")
    else:
        st.caption(f"{len(base_e)} Position(en)")
        st.data_editor(
            base_e, key=ek_e, use_container_width=True,
            hide_index=True, num_rows="fixed",
            height=_table_height_for_rows(len(base_e), min_rows=6, max_rows=14),
            on_change=make_callback(
                st.session_state,
                ek_e,
                base_e,
                push_history=push_history,
                max_history=MAX_HISTORY,
                autosave=_auto_save,
                logger=_log,
            ),
            column_config={k: v for k, v in pcfg.items() if k in ce},
        )

@st.fragment
def _frag_verladen() -> None:
    flush_full_rerun_after_editor_commit(st.session_state, rerun=st.rerun)
    ver   = st.session_state["pl_version"]
    df    = st.session_state["pl_df"]
    view_v = (
        df.groupby(["Bereich", "Kategorie"], sort=True)["Verladen"].first().reset_index()
    )
    bk_v   = f"b_verl_{ver}"
    base_v = get_frozen_base(
        st.session_state,
        bk_v,
        view_v,
        logger=_log,
    )
    ek_v = f"e_verl_{ver}"
    st.data_editor(
        base_v, key=ek_v, use_container_width=True,
        hide_index=True, num_rows="fixed",
        height=_table_height_for_rows(len(base_v), min_rows=6, max_rows=14),
        on_change=make_callback(
            st.session_state,
            ek_v,
            base_v,
            push_history=push_history,
            max_history=MAX_HISTORY,
            autosave=_auto_save,
            logger=_log,
            verladen=True,
        ),
        column_config={
            "Bereich":   _cc_text("Bereich",   width="small"),
            "Kategorie": _cc_text("Kategorie", width="small"),
            "Verladen":  _cc_check("Verladen"),
        },
    )

@st.fragment
def _frag_ersetzen() -> None:
    flush_full_rerun_after_editor_commit(st.session_state, rerun=st.rerun)
    ver      = st.session_state["pl_version"]
    df       = st.session_state["pl_df"]
    st.subheader("Gebrauchsgegenstände")
    st.caption("In die Notizen das Problem reinschreiben.")
    cols_e   = ["Bereich", "Gegenstand", "Notizen"]
    bk_ers   = f"b_ers_{ver}"
    view_ers = df.loc[~df["Nachfüllen"].astype(bool), cols_e].sort_values("Bereich")
    base_ers = get_frozen_base(
        st.session_state,
        bk_ers,
        view_ers,
        logger=_log,
    )
    ek_ers = f"e_ers_{ver}"
    if base_ers.empty:
        st.info("Alle Positionen haben Nachfüllen angekreuzt.")
    else:
        st.caption(f"{len(base_ers)} Position(en)")
        st.data_editor(
            base_ers, key=ek_ers, use_container_width=True,
            hide_index=True, num_rows="fixed",
            height=_table_height_for_rows(len(base_ers), min_rows=6, max_rows=14),
            on_change=make_callback(
                st.session_state,
                ek_ers,
                base_ers,
                push_history=push_history,
                max_history=MAX_HISTORY,
                autosave=_auto_save,
                logger=_log,
            ),
            column_config={
                "Bereich":    _cc_text("Bereich",    width="small"),
                "Gegenstand": _cc_text("Gegenstand", width="medium"),
                "Notizen":    _cc_text("Notizen",    width="large"),
            },
        )

@st.fragment
def _frag_definitionen() -> None:
    flush_full_rerun_after_editor_commit(st.session_state, rerun=st.rerun)
    ver  = st.session_state["pl_version"]
    df   = st.session_state["pl_df"]
    cols = ["Gegenstand", "Beschreibung", "Bereich"]
    bk   = f"b_def_{ver}"
    view_def = df[cols].sort_values("Bereich")
    base = get_frozen_base(st.session_state, bk, view_def, logger=_log)
    ek   = f"e_def_{ver}"
    st.data_editor(
        base, key=ek, use_container_width=True,
        hide_index=True, num_rows="fixed",
        height=_table_height_for_rows(len(base), min_rows=6, max_rows=14),
        on_change=make_callback(
            st.session_state,
            ek,
            base,
            push_history=push_history,
            max_history=MAX_HISTORY,
            autosave=_auto_save,
            logger=_log,
        ),
        column_config={
            "Gegenstand":   _cc_text("Gegenstand",   width="medium"),
            "Beschreibung": _cc_text("Beschreibung", width="large"),
            "Bereich":      _cc_text("Bereich",      width="small"),
        },
    )

@st.fragment
def _frag_uebersicht() -> None:
    """
    Summary statistics and breakdowns, deliberately decoupled from the
    per-click fragment flow.

    Updates when:
      • The user clicks "Aktualisieren" (triggers a fragment rerun of this tab)
      • A full-app rerun occurs (undo, file load, browser refresh)

    Does NOT update on every checkbox click in the other tabs — that is
    intentional; it keeps those interactions fluid.
    """
    df   = st.session_state["pl_df"]
    path = st.session_state["pl_path"]

    path_col, refresh_col = st.columns([5, 1])
    with path_col:
        st.caption(f"Datei: `{path}`")
    with refresh_col:
        st.button(
            "🔄",
            key="ueb_refresh",
            help="Übersicht aktualisieren",
            use_container_width=True,
        )

    st.divider()

    # ── Top metrics ───────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    total = len(df)
    replace_col = next((col for col in df.columns if col.startswith("Nachf")), None)
    if "Verpackt" in df.columns:
        packed = int(df["Verpackt"].sum())
        m1.metric("Verpackt", f"{packed} / {total}")
    if "Notizen" in df.columns and replace_col is not None:
        replace_total = int((~df[replace_col].astype(bool)).sum())
        intact_count = int(
            (
                ~df["Notizen"].apply(lambda v: bool(pd.notna(v) and str(v).strip()))
                & ~df[replace_col].astype(bool)
            ).sum()
        )
        m2.metric("Intakt", f"{intact_count} / {replace_total}")
    if all(c in df.columns for c in ("Bereich", "Kategorie", "Verladen")):
        dedup      = df.drop_duplicates(["Bereich", "Kategorie"])
        verl_done  = int(dedup["Verladen"].sum())
        verl_total = len(dedup)
        m3.metric("Verladen", f"{verl_done} / {verl_total}")

    st.divider()

    # ── Verpackt nach Bereich ─────────────────────────────────────────────────
    if all(c in df.columns for c in ("Bereich", "Verpackt")):
        pack_stats = _build_overview_stats(
            df,
            done_mask=df["Verpackt"].astype(bool),
            value_label="Verpackt",
        )
        _render_overview_stats_df(
            "Packen",
            pack_stats,
            value_label="Verpackt",
        )

    if all(c in df.columns for c in ("Bereich", "Kategorie", "Verladen")):
        verl_df = df.drop_duplicates(["Bereich", "Kategorie"]).copy()
        verl_stats = _build_overview_stats(
            verl_df,
            done_mask=verl_df["Verladen"].astype(bool),
            value_label="Verladen",
        )
        _render_overview_stats_df(
            "Verladen",
            verl_stats,
            value_label="Verladen",
        )

    replace_col = next((col for col in df.columns if col.startswith("Nachf")), None)
    if all(c in df.columns for c in ("Bereich", "Notizen")) and replace_col is not None:
        replace_total_mask = ~df[replace_col].astype(bool)
        intact_mask = (
            ~df["Notizen"].apply(lambda v: bool(pd.notna(v) and str(v).strip()))
            & replace_total_mask
        )
        replace_stats = _build_overview_stats(
            df,
            done_mask=intact_mask,
            total_mask=replace_total_mask,
            value_label="Intakt",
        )
        _render_overview_stats_df(
            "Ersetzen",
            replace_stats,
            value_label="Intakt",
        )

    return



# ── Render ─────────────────────────────────────────────────────────────────────

with tab_pack:
    _frag_packen()
with tab_verl:
    _frag_verladen()
with tab_ers:
    _frag_ersetzen()
with tab_def:
    _frag_definitionen()
with tab_ueb:
    _frag_uebersicht()
