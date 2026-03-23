from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from sponsor_deadline_mails.core import GeneratedMail, GenerationResult
from sponsor_deadline_mails.summary_state import (
    SUMMARY_COLUMNS,
    SUMMARY_SCHEMA_VERSION,
    build_summary_editor_df,
    ensure_summary_state,
    flush_full_rerun_after_summary_commit,
    get_summary_frozen_base,
    make_summary_callback,
    selected_mail_numbers,
    summary_needs_rebuild,
    sync_summary_selection,
)


def _make_result(mail_count: int = 2) -> GenerationResult:
    mails = []
    for idx in range(1, mail_count + 1):
        mails.append(
            GeneratedMail(
                row_number=idx + 1,
                sponsor_name=f"Sponsor {idx}",
                language="DE" if idx % 2 else "EN",
                package="Gold",
                to_email=f"sponsor{idx}@example.com",
                cc_email="" if idx % 2 else f"copy{idx}@example.com",
                subject=f"Subject {idx}",
                html_body=f"<html><body>{idx}</body></html>",
                html_file_name=f"{idx:03d}_sponsor_{idx}.html",
                green_count=idx,
                red_count=idx + 1,
                yellow_count=0,
                white_count=2,
            )
        )
    return GenerationResult(
        sheet_name="Deals",
        event_city="Berlin",
        event_start=date(2026, 5, 5),
        event_end=date(2026, 5, 7),
        mails=tuple(mails),
        processed_count=mail_count,
        skipped_count=0,
    )


class SponsorDeadlineMailSummaryStateTests(unittest.TestCase):
    def test_build_summary_editor_df_builds_expected_shape(self) -> None:
        result = _make_result(2)

        summary_df = build_summary_editor_df(result)

        self.assertEqual(list(summary_df.columns), SUMMARY_COLUMNS)
        self.assertEqual(summary_df.index.name, "MailNr")
        self.assertEqual(summary_df.index.tolist(), [1, 2])
        self.assertEqual(summary_df["Ausgewählt"].tolist(), [True, True])

    def test_selected_mail_numbers_returns_checked_indices(self) -> None:
        summary_df = build_summary_editor_df(_make_result(3))
        summary_df.loc[2, "Ausgewählt"] = False

        self.assertEqual(selected_mail_numbers(summary_df), {1, 3})
        self.assertEqual(selected_mail_numbers(None), set())

    def test_summary_needs_rebuild_detects_missing_or_changed_state(self) -> None:
        result = _make_result(2)
        session_state = {}

        self.assertTrue(summary_needs_rebuild(session_state, result))

        session_state["sdm_summary_df"] = build_summary_editor_df(result)
        session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
        self.assertFalse(summary_needs_rebuild(session_state, result))

        session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION - 1
        self.assertTrue(summary_needs_rebuild(session_state, result))

        session_state["sdm_summary_schema_version"] = SUMMARY_SCHEMA_VERSION
        session_state["sdm_summary_df"] = session_state["sdm_summary_df"].rename(
            columns={"Sponsor": "Partner"}
        )
        self.assertTrue(summary_needs_rebuild(session_state, result))

        session_state["sdm_summary_df"] = build_summary_editor_df(result).reset_index(drop=True)
        self.assertTrue(summary_needs_rebuild(session_state, result))

    def test_ensure_summary_state_initializes_dataframe_schema_and_preview(self) -> None:
        result = _make_result(2)
        session_state = {
            "sdm_summary_df": None,
            "sdm_summary_schema_version": 0,
            "sdm_summary_view_version": 0,
            "sdm_preview_mail_number": None,
        }

        ensure_summary_state(session_state, result)

        self.assertIsInstance(session_state["sdm_summary_df"], pd.DataFrame)
        self.assertEqual(session_state["sdm_summary_schema_version"], SUMMARY_SCHEMA_VERSION)
        self.assertEqual(session_state["sdm_summary_view_version"], 1)
        self.assertEqual(session_state["sdm_preview_mail_number"], 1)

    def test_get_summary_frozen_base_reuses_key_and_cleans_stale_prefix_keys(self) -> None:
        initial = build_summary_editor_df(_make_result(2))
        session_state = {
            "sdm_summary_base_1": pd.DataFrame({"old": [1]}),
            "sdm_summary_base_2": pd.DataFrame({"older": [2]}),
        }

        frozen = get_summary_frozen_base(session_state, "sdm_summary_base_3", initial)

        self.assertIsNot(frozen, initial)
        pd.testing.assert_frame_equal(frozen, initial)
        self.assertIn("sdm_summary_base_3", session_state)
        self.assertNotIn("sdm_summary_base_1", session_state)
        self.assertNotIn("sdm_summary_base_2", session_state)
        self.assertIs(get_summary_frozen_base(session_state, "sdm_summary_base_3", initial), frozen)

    def test_sync_summary_selection_updates_dataframe_and_sets_flag_once(self) -> None:
        summary_df = build_summary_editor_df(_make_result(2))
        frozen_base = summary_df.copy()
        session_state = {
            "sdm_summary_df": summary_df,
            "summary_editor": {
                "edited_rows": {
                    "0": {"Ausgewählt": False},
                    "1": {"Ausgewählt": True},
                }
            },
        }

        changed = sync_summary_selection(session_state, "summary_editor", frozen_base)

        self.assertTrue(changed)
        self.assertFalse(bool(summary_df.at[1, "Ausgewählt"]))
        self.assertTrue(bool(summary_df.at[2, "Ausgewählt"]))
        self.assertTrue(session_state["_sdm_rerun_after_commit"])

    def test_sync_summary_selection_is_no_op_without_real_change(self) -> None:
        summary_df = build_summary_editor_df(_make_result(1))
        frozen_base = summary_df.copy()
        session_state = {
            "sdm_summary_df": summary_df,
            "summary_editor": {"edited_rows": {"0": {"Ausgewählt": True}}},
        }

        changed = sync_summary_selection(session_state, "summary_editor", frozen_base)

        self.assertFalse(changed)
        self.assertNotIn("_sdm_rerun_after_commit", session_state)

    def test_make_summary_callback_and_flush_rerun_flag(self) -> None:
        summary_df = build_summary_editor_df(_make_result(1))
        frozen_base = summary_df.copy()
        session_state = {
            "sdm_summary_df": summary_df,
            "summary_editor": {"edited_rows": {"0": {"Ausgewählt": False}}},
        }
        reruns: list[str] = []

        callback = make_summary_callback(session_state, "summary_editor", frozen_base)
        callback()

        self.assertTrue(session_state["_sdm_rerun_after_commit"])

        flushed = flush_full_rerun_after_summary_commit(
            session_state,
            rerun=lambda: reruns.append("rerun"),
        )
        self.assertTrue(flushed)
        self.assertEqual(reruns, ["rerun"])
        self.assertNotIn("_sdm_rerun_after_commit", session_state)

        flushed_again = flush_full_rerun_after_summary_commit(
            session_state,
            rerun=lambda: reruns.append("again"),
        )
        self.assertFalse(flushed_again)
        self.assertEqual(reruns, ["rerun"])


if __name__ == "__main__":
    unittest.main()
