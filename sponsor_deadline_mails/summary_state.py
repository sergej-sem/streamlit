from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

import pandas as pd

from .rendering import build_summary_dataframe


SUMMARY_COLUMNS = [
    "Ausgewählt",
    "Sponsor",
    "Sprache",
    "Paket",
    "E-Mail",
    "Kopie",
    "Erhalten",
    "Offen",
    "Ausstehend",
    "Empfohlen",
]
SUMMARY_SCHEMA_VERSION = 4


def selected_mail_numbers(summary_df) -> set[int]:
    if summary_df is None or summary_df.empty:
        return set()
    mask = summary_df["Ausgewählt"].fillna(False).astype(bool)
    return {int(mail_number) for mail_number in summary_df.index[mask].tolist()}


def build_summary_editor_df(result) -> pd.DataFrame:
    summary_df = build_summary_dataframe(result).reset_index(drop=True)
    summary_df.index = pd.RangeIndex(start=1, stop=len(summary_df) + 1, step=1)
    summary_df.index.name = "MailNr"
    summary_df.insert(0, "Ausgewählt", True)
    summary_df = summary_df.rename(
        columns={
            "sponsor_name": "Sponsor",
            "language": "Sprache",
            "package": "Paket",
            "to_email": "E-Mail",
            "cc_email": "Kopie",
            "green_count": "Erhalten",
            "red_count": "Offen",
            "yellow_count": "Ausstehend",
            "white_count": "Empfohlen",
        }
    )
    return summary_df[SUMMARY_COLUMNS].copy()


def summary_needs_rebuild(session_state: MutableMapping[str, Any], result) -> bool:
    df = session_state.get("sdm_summary_df")
    if not isinstance(df, pd.DataFrame):
        return True
    if session_state.get("sdm_summary_schema_version") != SUMMARY_SCHEMA_VERSION:
        return True
    if list(df.columns) != SUMMARY_COLUMNS:
        return True
    expected_index = list(range(1, len(result.mails) + 1))
    if df.index.tolist() != expected_index:
        return True
    return len(df) != len(result.mails)


def ensure_summary_state(session_state: MutableMapping[str, Any], result) -> None:
    if summary_needs_rebuild(session_state, result):
        session_state["sdm_summary_df"] = build_summary_editor_df(result)
        session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
        session_state["sdm_summary_view_version"] += 1
        if result.mails:
            session_state["sdm_preview_mail_number"] = 1


def get_summary_frozen_base(
    session_state: MutableMapping[str, Any],
    key: str,
    initial: pd.DataFrame,
) -> pd.DataFrame:
    if key not in session_state:
        prefix = key.rsplit("_", 1)[0] + "_"
        stale_keys = [
            candidate
            for candidate in session_state
            if candidate.startswith(prefix) and candidate != key
        ]
        for candidate in stale_keys:
            del session_state[candidate]
        session_state[key] = initial.copy()
    return session_state[key]


def sync_summary_selection(
    session_state: MutableMapping[str, Any],
    editor_key: str,
    frozen_base: pd.DataFrame,
    *,
    rerun_flag_key: str = "_sdm_rerun_after_commit",
) -> bool:
    state = session_state.get(editor_key)
    if not isinstance(state, dict):
        return False

    edited_rows = state.get("edited_rows", {})
    if not edited_rows:
        return False

    summary_df = session_state.get("sdm_summary_df")
    if not isinstance(summary_df, pd.DataFrame):
        return False

    changed = False
    for pos_key, changes in edited_rows.items():
        pos = int(pos_key)
        if pos >= len(frozen_base):
            continue
        mail_number = frozen_base.index[pos]
        if "Ausgewählt" not in changes:
            continue
        new_value = bool(changes["Ausgewählt"])
        if bool(summary_df.at[mail_number, "Ausgewählt"]) != new_value:
            summary_df.at[mail_number, "Ausgewählt"] = new_value
            changed = True

    if changed:
        session_state[rerun_flag_key] = True
    return changed


def make_summary_callback(
    session_state: MutableMapping[str, Any],
    editor_key: str,
    frozen_base: pd.DataFrame,
    *,
    rerun_flag_key: str = "_sdm_rerun_after_commit",
) -> Callable[[], None]:
    def _cb() -> None:
        sync_summary_selection(
            session_state,
            editor_key,
            frozen_base,
            rerun_flag_key=rerun_flag_key,
        )

    return _cb


def flush_full_rerun_after_summary_commit(
    session_state: MutableMapping[str, Any],
    *,
    rerun: Callable[[], None],
    rerun_flag_key: str = "_sdm_rerun_after_commit",
) -> bool:
    if session_state.pop(rerun_flag_key, False):
        rerun()
        return True
    return False
