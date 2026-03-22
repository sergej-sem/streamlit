from typing import MutableMapping, Sequence

import pandas as pd


def init_session_state(session_state: MutableMapping, default_path: str) -> None:
    defaults = [
        ("pl_df", None),
        ("pl_path", default_path),
        ("pl_version", 0),
        ("pl_history", []),
        ("pl_redo_stack", []),
    ]
    for key, value in defaults:
        if key not in session_state:
            session_state[key] = value


def push_history(session_state: MutableMapping, max_history: int) -> None:
    session_state["pl_redo_stack"] = []
    history = session_state.setdefault("pl_history", [])
    history.append(session_state["pl_df"].copy())
    if len(history) > max_history:
        history.pop(0)


def apply_undo(session_state: MutableMapping, max_history: int) -> bool:
    history = session_state.get("pl_history", [])
    if not history:
        return False

    redo = session_state.setdefault("pl_redo_stack", [])
    redo.append(session_state["pl_df"].copy())
    if len(redo) > max_history:
        redo.pop(0)

    session_state["pl_df"] = history.pop()
    session_state["pl_version"] = session_state.get("pl_version", 0) + 1
    return True


def apply_redo(session_state: MutableMapping, max_history: int) -> bool:
    redo = session_state.get("pl_redo_stack", [])
    if not redo:
        return False

    history = session_state.setdefault("pl_history", [])
    history.append(session_state["pl_df"].copy())
    if len(history) > max_history:
        history.pop(0)

    session_state["pl_df"] = redo.pop()
    session_state["pl_version"] = session_state.get("pl_version", 0) + 1
    return True


def normalize_editor_mode_df(
    df: pd.DataFrame,
    columns: pd.Index,
    checkbox_cols: Sequence[str],
) -> pd.DataFrame:
    normalized = df.copy().reindex(columns=columns)
    checkbox_set = set(checkbox_cols)

    for col in normalized.columns:
        if col in checkbox_set:
            normalized[col] = normalized[col].fillna(False).astype(bool)
        else:
            normalized[col] = normalized[col].where(normalized[col].notna(), "")

    return normalized.reset_index(drop=True)


def drop_fully_empty_editor_rows(
    df: pd.DataFrame,
    checkbox_cols: Sequence[str],
) -> pd.DataFrame:
    if df.empty:
        return df.reset_index(drop=True)

    checkbox_set = set(checkbox_cols)
    present_checkbox_cols = [col for col in df.columns if col in checkbox_set]
    text_cols = [col for col in df.columns if col not in checkbox_set]

    keep_mask = pd.Series(False, index=df.index)
    if text_cols:
        keep_mask = df[text_cols].apply(
            lambda row: any(bool(pd.notna(value) and str(value).strip()) for value in row),
            axis=1,
        )
    if present_checkbox_cols:
        keep_mask = keep_mask | df[present_checkbox_cols].fillna(False).astype(bool).any(axis=1)

    return df.loc[keep_mask].reset_index(drop=True)
