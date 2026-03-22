import unittest

import pandas as pd

from packliste.overview import build_overview_stats


class PacklisteOverviewTests(unittest.TestCase):
    def test_build_overview_stats_groups_counts_and_adds_total_row(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": "Bar", "Verpackt": True},
                {"Bereich": "Bar", "Verpackt": False},
                {"Bereich": "Lager", "Verpackt": True},
            ]
        )

        stats = build_overview_stats(
            df,
            done_mask=df["Verpackt"].astype(bool),
            value_label="Verpackt",
        )

        expected = pd.DataFrame(
            [
                {"Bereich": "Bar", "Verpackt": 1, "Gesamt": 2, "Fortschritt": 50},
                {"Bereich": "Lager", "Verpackt": 1, "Gesamt": 1, "Fortschritt": 100},
                {"Bereich": "Gesamt", "Verpackt": 2, "Gesamt": 3, "Fortschritt": 67},
            ]
        )
        pd.testing.assert_frame_equal(stats.reset_index(drop=True), expected)

    def test_build_overview_stats_respects_total_mask(self) -> None:
        df = pd.DataFrame(
            [
                {"Bereich": "Bar", "Intakt": True, "Nachfuellen": False},
                {"Bereich": "Bar", "Intakt": False, "Nachfuellen": True},
                {"Bereich": "Lager", "Intakt": True, "Nachfuellen": False},
            ]
        )
        total_mask = ~df["Nachfuellen"].astype(bool)

        stats = build_overview_stats(
            df,
            done_mask=df["Intakt"].astype(bool) & total_mask,
            total_mask=total_mask,
            value_label="Intakt",
        )

        expected = pd.DataFrame(
            [
                {"Bereich": "Bar", "Intakt": 1, "Gesamt": 1, "Fortschritt": 100},
                {"Bereich": "Lager", "Intakt": 1, "Gesamt": 1, "Fortschritt": 100},
                {"Bereich": "Gesamt", "Intakt": 2, "Gesamt": 2, "Fortschritt": 100},
            ]
        )
        pd.testing.assert_frame_equal(stats.reset_index(drop=True), expected)

    def test_build_overview_stats_returns_empty_frame_without_bereich(self) -> None:
        stats = build_overview_stats(
            pd.DataFrame([{"Kategorie": "Bar"}]),
            done_mask=pd.Series([True]),
            value_label="Verpackt",
        )

        self.assertEqual(
            list(stats.columns),
            ["Bereich", "Verpackt", "Gesamt", "Fortschritt"],
        )
        self.assertTrue(stats.empty)

    def test_build_overview_stats_returns_empty_frame_for_empty_filtered_base(self) -> None:
        df = pd.DataFrame([{"Bereich": "Bar", "Verpackt": True}])

        stats = build_overview_stats(
            df,
            done_mask=df["Verpackt"].astype(bool),
            total_mask=pd.Series([False], index=df.index),
            value_label="Verpackt",
        )

        self.assertEqual(
            list(stats.columns),
            ["Bereich", "Verpackt", "Gesamt", "Fortschritt"],
        )
        self.assertTrue(stats.empty)


if __name__ == "__main__":
    unittest.main()
