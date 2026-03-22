import unittest

import pandas as pd

from packliste.editor_sync import (
    flush_full_rerun_after_editor_commit,
    get_frozen_base,
    make_callback,
    sync_edits,
    sync_verladen,
)


def _push_history_stub_factory(calls: dict[str, int]):
    def _push_history(session_state, max_history: int) -> None:
        calls["push_history"] += 1
        session_state.setdefault("pl_redo_stack", [])
        session_state["pl_redo_stack"] = []
        history = session_state.setdefault("pl_history", [])
        history.append(session_state["pl_df"].copy())
        if len(history) > max_history:
            history.pop(0)

    return _push_history


def _autosave_stub_factory(calls: dict[str, int]):
    def _autosave() -> None:
        calls["autosave"] += 1

    return _autosave


class PacklisteEditorSyncTests(unittest.TestCase):
    def test_get_frozen_base_initializes_from_initial_df(self) -> None:
        session_state = {}
        initial = pd.DataFrame([{"Bereich": "Bar"}], index=[7])

        frozen_base = get_frozen_base(session_state, "b_def_1", initial)

        self.assertEqual(list(session_state.keys()), ["b_def_1"])
        pd.testing.assert_frame_equal(frozen_base, initial)
        self.assertIsNot(frozen_base, initial)

    def test_get_frozen_base_reuses_existing_base(self) -> None:
        existing = pd.DataFrame([{"Bereich": "Existing"}])
        session_state = {"b_def_1": existing}
        initial = pd.DataFrame([{"Bereich": "New"}])

        frozen_base = get_frozen_base(session_state, "b_def_1", initial)

        self.assertIs(frozen_base, existing)
        self.assertEqual(frozen_base.loc[0, "Bereich"], "Existing")

    def test_get_frozen_base_evicts_stale_keys_with_same_prefix(self) -> None:
        session_state = {
            "b_def_1": pd.DataFrame([{"Bereich": "Old"}]),
            "b_def_2": pd.DataFrame([{"Bereich": "Older"}]),
            "other_key": "keep",
        }

        frozen_base = get_frozen_base(
            session_state,
            "b_def_3",
            pd.DataFrame([{"Bereich": "Fresh"}]),
        )

        self.assertEqual(set(session_state.keys()), {"b_def_3", "other_key"})
        self.assertEqual(session_state["other_key"], "keep")
        self.assertEqual(frozen_base.loc[0, "Bereich"], "Fresh")

    def test_sync_edits_applies_changes_pushes_history_once_and_sets_flag(self) -> None:
        df = pd.DataFrame(
            [
                {"Gegenstand": "Alt-1", "Verpackt": False},
                {"Gegenstand": "Alt-2", "Verpackt": False},
            ],
            index=[10, 20],
        )
        frozen_base = df.loc[[20], ["Gegenstand", "Verpackt"]].copy()
        session_state = {
            "pl_df": df.copy(),
            "pl_history": [],
            "pl_redo_stack": [],
            "pl_version": 5,
            "editor": {
                "edited_rows": {
                    "0": {
                        "Gegenstand": "Neu-2",
                        "Verpackt": True,
                    }
                }
            },
        }
        calls = {"push_history": 0, "autosave": 0}

        changed = sync_edits(
            session_state,
            "editor",
            frozen_base,
            push_history=_push_history_stub_factory(calls),
            max_history=5,
            autosave=_autosave_stub_factory(calls),
        )

        self.assertTrue(changed)
        self.assertEqual(calls["push_history"], 1)
        self.assertEqual(calls["autosave"], 1)
        self.assertTrue(session_state["_pl_rerun_after_commit"])
        self.assertEqual(session_state["pl_df"].loc[10, "Gegenstand"], "Alt-1")
        self.assertEqual(session_state["pl_df"].loc[20, "Gegenstand"], "Neu-2")
        self.assertTrue(bool(session_state["pl_df"].loc[20, "Verpackt"]))
        self.assertEqual(session_state["pl_history"][0].loc[20, "Gegenstand"], "Alt-2")

    def test_sync_edits_returns_false_when_no_state_or_no_actual_change(self) -> None:
        base_df = pd.DataFrame([{"Gegenstand": "Alt", "Verpackt": False}], index=[10])

        for session_state in [
            {"pl_df": base_df.copy()},
            {
                "pl_df": base_df.copy(),
                "editor": {"edited_rows": {}},
            },
            {
                "pl_df": base_df.copy(),
                "editor": {"edited_rows": {"0": {"Gegenstand": "Alt"}}},
            },
        ]:
            calls = {"push_history": 0, "autosave": 0}
            changed = sync_edits(
                session_state,
                "editor",
                base_df.copy(),
                push_history=_push_history_stub_factory(calls),
                max_history=5,
                autosave=_autosave_stub_factory(calls),
            )

            self.assertFalse(changed)
            self.assertEqual(calls["push_history"], 0)
            self.assertEqual(calls["autosave"], 0)
            self.assertNotIn("_pl_rerun_after_commit", session_state)

    def test_sync_verladen_propagates_group_and_triggers_commit_once(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": False},
                {"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": False},
                {"Bereich": "Bar", "Kategorie": "Licht", "Verladen": False},
            ]
        )
        frozen_base = pd.DataFrame(
            [
                {"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": False},
                {"Bereich": "Bar", "Kategorie": "Licht", "Verladen": False},
            ]
        )
        session_state = {
            "pl_df": df.copy(),
            "pl_history": [],
            "pl_redo_stack": [],
            "pl_version": 2,
            "editor": {"edited_rows": {"0": {"Verladen": True}}},
        }
        calls = {"push_history": 0, "autosave": 0}

        changed = sync_verladen(
            session_state,
            "editor",
            frozen_base,
            push_history=_push_history_stub_factory(calls),
            max_history=5,
            autosave=_autosave_stub_factory(calls),
        )

        self.assertTrue(changed)
        self.assertEqual(calls["push_history"], 1)
        self.assertEqual(calls["autosave"], 1)
        self.assertTrue(session_state["_pl_rerun_after_commit"])
        self.assertEqual(session_state["pl_df"]["Verladen"].tolist(), [True, True, False])

    def test_sync_verladen_returns_false_when_group_already_matches(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": True},
                {"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": True},
            ]
        )
        frozen_base = pd.DataFrame(
            [{"Bereich": "Bar", "Kategorie": "Kisten", "Verladen": True}]
        )
        session_state = {
            "pl_df": df.copy(),
            "editor": {"edited_rows": {"0": {"Verladen": True}}},
        }
        calls = {"push_history": 0, "autosave": 0}

        changed = sync_verladen(
            session_state,
            "editor",
            frozen_base,
            push_history=_push_history_stub_factory(calls),
            max_history=5,
            autosave=_autosave_stub_factory(calls),
        )

        self.assertFalse(changed)
        self.assertEqual(calls["push_history"], 0)
        self.assertEqual(calls["autosave"], 0)
        self.assertNotIn("_pl_rerun_after_commit", session_state)

    def test_flush_full_rerun_after_editor_commit_calls_rerun_once(self) -> None:
        calls = {"rerun": 0}
        session_state = {"_pl_rerun_after_commit": True}

        changed = flush_full_rerun_after_editor_commit(
            session_state,
            rerun=lambda: calls.__setitem__("rerun", calls["rerun"] + 1),
        )

        self.assertTrue(changed)
        self.assertEqual(calls["rerun"], 1)
        self.assertNotIn("_pl_rerun_after_commit", session_state)

    def test_make_callback_returns_callable_that_uses_expected_sync_path(self) -> None:
        df = pd.DataFrame(
            [
                {"Gegenstand": "Alt-1", "Verpackt": False},
                {"Gegenstand": "Alt-2", "Verpackt": False},
            ],
            index=[10, 20],
        )
        frozen_base = df.loc[[20], ["Gegenstand", "Verpackt"]].copy()
        session_state = {
            "pl_df": df.copy(),
            "pl_history": [],
            "pl_redo_stack": [],
            "pl_version": 5,
            "editor": {"edited_rows": {"0": {"Verpackt": True}}},
        }
        calls = {"push_history": 0, "autosave": 0}

        callback = make_callback(
            session_state,
            "editor",
            frozen_base,
            push_history=_push_history_stub_factory(calls),
            max_history=5,
            autosave=_autosave_stub_factory(calls),
        )
        callback()

        self.assertEqual(calls["push_history"], 1)
        self.assertEqual(calls["autosave"], 1)
        self.assertTrue(bool(session_state["pl_df"].loc[20, "Verpackt"]))
        self.assertTrue(session_state["_pl_rerun_after_commit"])


if __name__ == "__main__":
    unittest.main()
