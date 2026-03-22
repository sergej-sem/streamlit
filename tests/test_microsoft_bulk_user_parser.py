import io
import unittest

import pandas as pd

from microsoft_bulk_user.parser import (
    FIRST_ALIASES,
    detect_delimiter,
    decode_bytes_auto,
    find_col,
    has_any_alias_columns,
    looks_like_headerless,
    normalize_name_part,
    read_table,
    split_fullname,
)


class UploadStub:
    def __init__(self, name: str, raw: bytes):
        self.name = name
        self._raw = raw

    def getvalue(self) -> bytes:
        return self._raw


class ParserHelpersTests(unittest.TestCase):
    def test_detect_delimiter_prefers_highest_count(self):
        self.assertEqual(detect_delimiter("a;b;c"), ";")
        self.assertEqual(detect_delimiter("a,b,c,d"), ",")
        self.assertEqual(detect_delimiter("a\tb\tc"), "\t")
        self.assertEqual(detect_delimiter("a|b|c"), "|")
        self.assertEqual(detect_delimiter("abc"), ";")

    def test_decode_bytes_auto_handles_utf8_bom(self):
        text, encoding = decode_bytes_auto(b"\xef\xbb\xbfVorname;Nachname")
        self.assertEqual(text, "Vorname;Nachname")
        self.assertEqual(encoding, "utf-8-sig")

    def test_decode_bytes_auto_handles_utf16_bom(self):
        raw = "Vorname;Nachname".encode("utf-16")
        text, encoding = decode_bytes_auto(raw)
        self.assertEqual(text, "Vorname;Nachname")
        self.assertEqual(encoding, "utf-16-le(bom)")

    def test_decode_bytes_auto_falls_back_to_cp1252(self):
        raw = "Jörg".encode("cp1252")
        text, encoding = decode_bytes_auto(raw)
        self.assertEqual(text, "Jörg")
        self.assertEqual(encoding, "cp1252")

    def test_looks_like_headerless(self):
        self.assertTrue(looks_like_headerless(["Max", "Mustermann"]))
        self.assertFalse(looks_like_headerless(["Vorname", "Nachname"]))

    def test_alias_detection_and_lookup(self):
        cols = ["Vorname", "Nachname", "E-Mail"]
        self.assertTrue(has_any_alias_columns(cols))
        self.assertEqual(find_col(cols, FIRST_ALIASES), "Vorname")

    def test_split_fullname_handles_particles(self):
        self.assertEqual(split_fullname("Max von Example"), ("Max", "von Example"))
        self.assertIsNone(split_fullname("Cher"))

    def test_normalize_name_part_handles_umlauts_accents_and_punctuation(self):
        self.assertEqual(normalize_name_part(" Jörg-Müller "), "joergmueller")
        self.assertEqual(normalize_name_part("Éléonore"), "eleonore")


class ReadTableTests(unittest.TestCase):
    def test_read_table_csv_with_headers(self):
        raw = "Vorname;Nachname\nMax;Mustermann\n".encode("utf-8")
        df, source = read_table(UploadStub("users.csv", raw))
        self.assertEqual(source, "csv(utf-8, Trennzeichen=';')")
        self.assertEqual(df.columns.tolist(), ["Vorname", "Nachname"])
        self.assertEqual(df.iloc[0].to_dict(), {"Vorname": "Max", "Nachname": "Mustermann"})

    def test_read_table_csv_without_headers_uses_fallback_columns(self):
        raw = "Max;Mustermann\nErika;Musterfrau\n".encode("utf-8")
        df, source = read_table(UploadStub("users.csv", raw))
        self.assertEqual(source, "csv(utf-8, Trennzeichen=';')")
        self.assertEqual(df.columns.tolist(), ["FirstName", "LastName"])
        self.assertEqual(df.iloc[0].to_dict(), {"FirstName": "Max", "LastName": "Mustermann"})

    def test_read_table_xlsx_with_headers(self):
        bio = io.BytesIO()
        pd.DataFrame({"Vorname": ["Max"], "Nachname": ["Mustermann"]}).to_excel(
            bio,
            index=False,
            engine="openpyxl",
        )
        df, source = read_table(UploadStub("users.xlsx", bio.getvalue()))
        self.assertEqual(source, "xlsx")
        self.assertEqual(df.columns.tolist(), ["Vorname", "Nachname"])
        self.assertEqual(df.iloc[0].to_dict(), {"Vorname": "Max", "Nachname": "Mustermann"})


if __name__ == "__main__":
    unittest.main()
