import unittest

import pandas as pd

from packliste.state import (
    apply_redo,
    apply_undo,
    drop_fully_empty_editor_rows,
    init_session_state,
    normalize_editor_mode_df,
    push_history,
)


class PacklisteStateTests(unittest.TestCase):
    def test_init_session_state_sets_missing_defaults(self) -> None:
        session_state = {}

        init_session_state(session_state, "")

        self.assertEqual(
            session_state,
            {
                "pl_df": None,
                "pl_path": "",
                "pl_version": 0,
                "pl_history": [],
                "pl_redo_stack": [],
            },
        )

    def test_init_session_state_keeps_existing_values(self) -> None:
        existing_df = pd.DataFrame([{"Bereich": "Bar"}])
        session_state = {
            "pl_df": existing_df,
            "pl_path": "keep.xlsx",
            "pl_version": 7,
            "pl_history": ["old"],
            "pl_redo_stack": ["redo"],
        }

        init_session_state(session_state, "new.xlsx")

        self.assertIs(session_state["pl_df"], existing_df)
        self.assertEqual(session_state["pl_path"], "keep.xlsx")
        self.assertEqual(session_state["pl_version"], 7)
        self.assertEqual(session_state["pl_history"], ["old"])
        self.assertEqual(session_state["pl_redo_stack"], ["redo"])

    def test_push_history_appends_copy_and_clears_redo(self) -> None:
        df = pd.DataFrame([{"Bereich": "Bar"}])
        session_state = {"pl_df": df, "pl_history": [], "pl_redo_stack": ["stale"]}

        push_history(session_state, 3)
        df.loc[0, "Bereich"] = "Changed"

        self.assertEqual(session_state["pl_redo_stack"], [])
        self.assertEqual(session_state["pl_history"][0].loc[0, "Bereich"], "Bar")

    def test_push_history_enforces_cap(self) -> None:
        session_state = {"pl_history": [], "pl_redo_stack": []}
        for value in ["A", "B", "C"]:
            session_state["pl_df"] = pd.DataFrame([{"Bereich": value}])
            push_history(session_state, 2)

        history_values = [frame.loc[0, "Bereich"] for frame in session_state["pl_history"]]
        self.assertEqual(history_values, ["B", "C"])

    def test_apply_undo_moves_current_to_redo_and_increments_version(self) -> None:
        current = pd.DataFrame([{"Bereich": "Current"}])
        previous = pd.DataFrame([{"Bereich": "Previous"}])
        session_state = {
            "pl_df": current,
            "pl_history": [previous],
            "pl_redo_stack": [],
            "pl_version": 2,
        }

        changed = apply_undo(session_state, 5)

        self.assertTrue(changed)
        self.assertEqual(session_state["pl_df"].loc[0, "Bereich"], "Previous")
        self.assertEqual(session_state["pl_redo_stack"][0].loc[0, "Bereich"], "Current")
        self.assertEqual(session_state["pl_version"], 3)

    def test_apply_undo_returns_false_without_history(self) -> None:
        session_state = {
            "pl_df": pd.DataFrame([{"Bereich": "Only"}]),
            "pl_history": [],
            "pl_redo_stack": [],
            "pl_version": 1,
        }

        changed = apply_undo(session_state, 5)

        self.assertFalse(changed)
        self.assertEqual(session_state["pl_version"], 1)

    def test_apply_redo_moves_current_to_history_and_increments_version(self) -> None:
        current = pd.DataFrame([{"Bereich": "Current"}])
        redone = pd.DataFrame([{"Bereich": "Redo"}])
        session_state = {
            "pl_df": current,
            "pl_history": [],
            "pl_redo_stack": [redone],
            "pl_version": 4,
        }

        changed = apply_redo(session_state, 5)

        self.assertTrue(changed)
        self.assertEqual(session_state["pl_df"].loc[0, "Bereich"], "Redo")
        self.assertEqual(session_state["pl_history"][0].loc[0, "Bereich"], "Current")
        self.assertEqual(session_state["pl_version"], 5)

    def test_apply_redo_returns_false_without_redo(self) -> None:
        session_state = {
            "pl_df": pd.DataFrame([{"Bereich": "Only"}]),
            "pl_history": [],
            "pl_redo_stack": [],
            "pl_version": 1,
        }

        changed = apply_redo(session_state, 5)

        self.assertFalse(changed)
        self.assertEqual(session_state["pl_version"], 1)

    def test_normalize_editor_mode_df_coerces_checkbox_and_text_columns(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": None, "Verpackt": None, "Verladen": True},
                {"Bereich": " Bar ", "Verpackt": True, "Verladen": None},
            ]
        )

        normalized = normalize_editor_mode_df(
            df,
            pd.Index(["Bereich", "Verpackt", "Verladen"]),
            ("Verpackt", "Verladen"),
        )

        expected = pd.DataFrame(
            [
                {"Bereich": "", "Verpackt": False, "Verladen": True},
                {"Bereich": " Bar ", "Verpackt": True, "Verladen": False},
            ]
        )
        pd.testing.assert_frame_equal(normalized, expected)

    def test_drop_fully_empty_editor_rows_removes_only_empty_rows(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": "", "Notizen": "", "Verpackt": False},
                {"Bereich": "Bar", "Notizen": "", "Verpackt": False},
                {"Bereich": "", "Notizen": "", "Verpackt": True},
            ]
        )

        filtered = drop_fully_empty_editor_rows(df, ("Verpackt",))

        expected = pd.DataFrame(
            [
                {"Bereich": "Bar", "Notizen": "", "Verpackt": False},
                {"Bereich": "", "Notizen": "", "Verpackt": True},
            ]
        ).reset_index(drop=True)
        pd.testing.assert_frame_equal(filtered, expected)


if __name__ == "__main__":
    unittest.main()
