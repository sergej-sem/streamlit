import unittest

import pandas as pd

from serienmailing.import_reader import read_csv_table


class ReadCsvTableTests(unittest.TestCase):

    def test_reads_comma_separated_utf8_csv(self):
        data = (
            "Sponsor,An,CC\n"
            "ACME,primary@example.com,copy@example.com\n"
        ).encode("utf-8")

        result = read_csv_table(data)

        self.assertEqual(["Sponsor", "An", "CC"], list(result.columns))
        self.assertEqual("primary@example.com", result.iloc[0]["An"])

    def test_reads_semicolon_separated_excel_csv(self):
        data = (
            "Sponsor;ASP 1 E-Mail Adresse;ASP 2 E-Mail Adresse\r\n"
            "ACME;primary@example.com;copy@example.com\r\n"
        ).encode("utf-8-sig")

        result = read_csv_table(data)

        self.assertEqual(3, len(result.columns))
        self.assertEqual("copy@example.com", result.iloc[0]["ASP 2 E-Mail Adresse"])

    def test_falls_back_to_windows_1252(self):
        data = (
            "Firma;Vorname;E-Mail;CC\r\n"
            "Müller GmbH;Jörg;joerg@example.com;copy@example.com\r\n"
        ).encode("cp1252")

        result = read_csv_table(data)

        self.assertEqual("Müller GmbH", result.iloc[0]["Firma"])
        self.assertEqual("Jörg", result.iloc[0]["Vorname"])

    def test_empty_input_raises_empty_data_error(self):
        with self.assertRaises(pd.errors.EmptyDataError):
            read_csv_table(b"")


if __name__ == "__main__":
    unittest.main()
