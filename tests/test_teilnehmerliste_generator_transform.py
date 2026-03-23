import unittest

import pandas as pd

from teilnehmerliste_generator.transform import build_teilnehmerliste


class BuildTeilnehmerlisteTests(unittest.TestCase):
    def test_accepts_supported_languages(self) -> None:
        df = pd.DataFrame([{"company": "Acme GmbH", "jobtitle": "Manager"}])

        de_result = build_teilnehmerliste(df, lang="de")
        en_result = build_teilnehmerliste(df, lang="en")

        self.assertEqual(
            [{"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "Fachbereich"}],
            de_result.to_dict("records"),
        )
        self.assertEqual(
            [{"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "Department"}],
            en_result.to_dict("records"),
        )

    def test_rejects_invalid_language(self) -> None:
        df = pd.DataFrame([{"company": "Acme GmbH", "jobtitle": "Manager"}])

        with self.assertRaisesRegex(ValueError, "lang must be 'de' or 'en'"):
            build_teilnehmerliste(df, lang="fr")

    def test_requires_company_and_jobtitle_columns(self) -> None:
        cases = [
            (pd.DataFrame([{"jobtitle": "Manager"}]), "company"),
            (pd.DataFrame([{"company": "Acme GmbH"}]), "jobtitle"),
        ]

        for frame, missing_column in cases:
            with self.subTest(missing_column=missing_column):
                with self.assertRaises(KeyError) as ctx:
                    build_teilnehmerliste(frame)

                self.assertIn("Missing required columns", str(ctx.exception))
                self.assertIn(missing_column, str(ctx.exception))

    def test_normalizes_values_and_filters_blank_companies(self) -> None:
        df = pd.DataFrame(
            [
                {"company": "\u00a0Acme GmbH\u00a0", "jobtitle": None},
                {"company": "   ", "jobtitle": "CEO"},
                {"company": None, "jobtitle": "Manager"},
                {"company": float("nan"), "jobtitle": "Manager"},
                {"company": "Beta AG", "jobtitle": "  Manager  "},
            ]
        )

        result = build_teilnehmerliste(df, lang="de")

        self.assertEqual(
            [
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "Fachbereich"},
                {"Unternehmensname": "Beta AG", "Jobbezeichnung": "Fachbereich"},
            ],
            result.to_dict("records"),
        )

    def test_maps_current_bucket_rules_for_de_and_en(self) -> None:
        df = pd.DataFrame(
            [
                {"company": "Acme GmbH", "jobtitle": "CEO"},
                {"company": "Beta AG", "jobtitle": "Vice President Sales"},
                {"company": "Gamma AG", "jobtitle": "Manager"},
            ]
        )

        de_result = build_teilnehmerliste(df, lang="de")
        en_result = build_teilnehmerliste(df, lang="en")

        self.assertEqual(
            [
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Beta AG", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Gamma AG", "Jobbezeichnung": "Fachbereich"},
            ],
            de_result.to_dict("records"),
        )
        self.assertEqual(
            [
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Beta AG", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Gamma AG", "Jobbezeichnung": "Department"},
            ],
            en_result.to_dict("records"),
        )

    def test_keeps_only_two_strongest_entries_per_company(self) -> None:
        df = pd.DataFrame(
            [
                {"company": "Acme GmbH", "jobtitle": "Intern"},
                {"company": "Acme GmbH", "jobtitle": "CEO"},
                {"company": "Acme GmbH", "jobtitle": "Vice President Sales"},
                {"company": "Acme GmbH", "jobtitle": "Manager"},
                {"company": "Beta AG", "jobtitle": "Manager"},
            ]
        )

        result = build_teilnehmerliste(df, lang="de")

        self.assertEqual(
            [
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Acme GmbH", "Jobbezeichnung": "C-Level"},
                {"Unternehmensname": "Beta AG", "Jobbezeichnung": "Fachbereich"},
            ],
            result.to_dict("records"),
        )

    def test_sorts_companies_case_insensitively(self) -> None:
        df = pd.DataFrame(
            [
                {"company": "zebra GmbH", "jobtitle": "Manager"},
                {"company": "Acme GmbH", "jobtitle": "Manager"},
                {"company": "beta AG", "jobtitle": "Manager"},
            ]
        )

        result = build_teilnehmerliste(df, lang="de")

        self.assertEqual(
            ["Acme GmbH", "beta AG", "zebra GmbH"],
            list(result["Unternehmensname"]),
        )


if __name__ == "__main__":
    unittest.main()
