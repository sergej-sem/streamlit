from __future__ import annotations

from io import BytesIO

import pandas as pd

_CSV_ENCODINGS = ("utf-8-sig", "cp1252")


def read_csv_table(data: bytes) -> pd.DataFrame:
    """Read common CSV exports with automatic delimiter and encoding fallback."""

    if not data:
        raise pd.errors.EmptyDataError("Die CSV-Datei ist leer.")

    last_decode_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            return pd.read_csv(
                BytesIO(data),
                sep=None,
                engine="python",
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_decode_error = exc

    if last_decode_error is not None:
        raise last_decode_error
    raise ValueError("Die CSV-Datei konnte nicht gelesen werden.")
