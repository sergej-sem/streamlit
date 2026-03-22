from typing import Any, Callable, MutableMapping

import pandas as pd


def _log_debug(logger: Any, message: str, *args: Any) -> None:
    if logger is not None:
        logger.debug(message, *args)


def _log_info(logger: Any, message: str, *args: Any) -> None:
    if logger is not None:
        logger.info(message, *args)


def _get_edited_rows(session_state: MutableMapping[str, Any], editor_key: str) -> dict[Any, Any]:
    state = session_state.get(editor_key)
    if not isinstance(state, dict):
        return {}

    edited_rows = state.get("edited_rows", {})
    if not isinstance(edited_rows, dict):
        return {}
    return edited_rows


def _finalize_commit(
    session_state: MutableMapping[str, Any],
    *,
    autosave: Callable[[], None],
    rerun_flag_key: str,
) -> None:
    autosave()
    session_state[rerun_flag_key] = True


def get_frozen_base(
    session_state: MutableMapping[str, Any],
    key: str,
    initial_df: pd.DataFrame,
    *,
    logger: Any = None,
) -> pd.DataFrame:
    if key not in session_state:
        prefix = key.rsplit("_", 1)[0] + "_"
        stale_keys = [name for name in session_state if name.startswith(prefix) and name != key]
        for stale_key in stale_keys:
            _log_debug(logger, "Evicting stale frozen base: %s", stale_key)
            del session_state[stale_key]
        session_state[key] = initial_df.copy()
        _log_debug(logger, "Created frozen base %s (%d rows)", key, len(initial_df))
    return session_state[key]


def sync_edits(
    session_state: MutableMapping[str, Any],
    editor_key: str,
    frozen_base: pd.DataFrame,
    *,
    push_history: Callable[[MutableMapping[str, Any], int], None],
    max_history: int,
    autosave: Callable[[], None],
    logger: Any = None,
    rerun_flag_key: str = "_pl_rerun_after_commit",
) -> bool:
    edited_rows = _get_edited_rows(session_state, editor_key)
    if not edited_rows:
        return False

    df = session_state["pl_df"]
    history_pushed = False
    changed_cells: list[tuple[Any, Any, Any, Any]] = []

    for pos_key, changes in edited_rows.items():
        if not isinstance(changes, dict):
            continue
        pos = int(pos_key)
        if pos >= len(frozen_base):
            continue
        df_idx = frozen_base.index[pos]
        for col, new_val in changes.items():
            if col not in df.columns:
                continue
            old_val = df.at[df_idx, col]
            if old_val != new_val:
                if not history_pushed:
                    push_history(session_state, max_history)
                    history_pushed = True
                df.at[df_idx, col] = new_val
                changed_cells.append((df_idx, col, old_val, new_val))

    if not history_pushed:
        return False

    _log_info(
        logger,
        "Commit %s: ver=%d, cells=%s",
        editor_key,
        session_state["pl_version"],
        [(idx, col, f"{old_val!r}→{new_val!r}") for idx, col, old_val, new_val in changed_cells],
    )
    _finalize_commit(
        session_state,
        autosave=autosave,
        rerun_flag_key=rerun_flag_key,
    )
    return True


def sync_verladen(
    session_state: MutableMapping[str, Any],
    editor_key: str,
    frozen_base: pd.DataFrame,
    *,
    push_history: Callable[[MutableMapping[str, Any], int], None],
    max_history: int,
    autosave: Callable[[], None],
    logger: Any = None,
    rerun_flag_key: str = "_pl_rerun_after_commit",
) -> bool:
    edited_rows = _get_edited_rows(session_state, editor_key)
    if not edited_rows:
        return False

    df = session_state["pl_df"]
    history_pushed = False
    changed_groups: list[tuple[Any, Any, bool]] = []

    for pos_key, changes in edited_rows.items():
        if not isinstance(changes, dict):
            continue
        pos = int(pos_key)
        if pos >= len(frozen_base):
            continue
        bereich = frozen_base.iloc[pos]["Bereich"]
        kategorie = frozen_base.iloc[pos]["Kategorie"]
        new_val = bool(changes.get("Verladen", frozen_base.iloc[pos]["Verladen"]))
        mask = (df["Bereich"] == bereich) & (df["Kategorie"] == kategorie)
        if not (df.loc[mask, "Verladen"] == new_val).all():
            if not history_pushed:
                push_history(session_state, max_history)
                history_pushed = True
            df.loc[mask, "Verladen"] = new_val
            changed_groups.append((bereich, kategorie, new_val))

    if not history_pushed:
        return False

    _log_info(
        logger,
        "Commit %s: ver=%d, verladen groups=%s",
        editor_key,
        session_state["pl_version"],
        [(bereich, kategorie, new_val) for bereich, kategorie, new_val in changed_groups],
    )
    _finalize_commit(
        session_state,
        autosave=autosave,
        rerun_flag_key=rerun_flag_key,
    )
    return True


def flush_full_rerun_after_editor_commit(
    session_state: MutableMapping[str, Any],
    *,
    rerun: Callable[[], None],
    rerun_flag_key: str = "_pl_rerun_after_commit",
) -> bool:
    if session_state.pop(rerun_flag_key, False):
        rerun()
        return True
    return False


def make_callback(
    session_state: MutableMapping[str, Any],
    editor_key: str,
    frozen_base: pd.DataFrame,
    *,
    push_history: Callable[[MutableMapping[str, Any], int], None],
    max_history: int,
    autosave: Callable[[], None],
    logger: Any = None,
    verladen: bool = False,
    rerun_flag_key: str = "_pl_rerun_after_commit",
) -> Callable[[], None]:
    def _cb() -> None:
        if verladen:
            sync_verladen(
                session_state,
                editor_key,
                frozen_base,
                push_history=push_history,
                max_history=max_history,
                autosave=autosave,
                logger=logger,
                rerun_flag_key=rerun_flag_key,
            )
        else:
            sync_edits(
                session_state,
                editor_key,
                frozen_base,
                push_history=push_history,
                max_history=max_history,
                autosave=autosave,
                logger=logger,
                rerun_flag_key=rerun_flag_key,
            )

    return _cb
