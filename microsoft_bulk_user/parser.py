import io
import re
import unicodedata
from typing import Callable, Optional, Tuple

import pandas as pd

FIRST_ALIASES = {
    "firstname",
    "first",
    "givenname",
    "given",
    "vorname",
    "prename",
    "namefirst",
    "forename",
}
LAST_ALIASES = {
    "lastname",
    "last",
    "surname",
    "familyname",
    "family",
    "nachname",
    "namelast",
}
FULL_ALIASES = {
    "fullname",
    "name",
    "displayname",
    "kontaktname",
    "contactname",
    "benutzer",
    "mitarbeiter",
    "teilnehmer",
}
UPN_ALIASES = {
    "userprincipalname",
    "upn",
    "email",
    "mail",
    "username",
    "login",
    "signinname",
}

NAME_PARTICLES = {"von", "van", "de", "del", "da", "der", "den", "di", "la", "le", "du", "st", "st."}


def norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[_\-/\.]", "", s)
    return s


def detect_delimiter(sample: str) -> str:
    candidates = [";", ",", "\t", "|"]
    counts = {d: sample.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ";"


def decode_bytes_auto(raw: bytes) -> Tuple[str, str]:
    """Return (text, encoding_name) with simple BOM + fallback strategy."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16", errors="replace"), "utf-16-le(bom)"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace"), "utf-16-be(bom)"

    txt = raw.decode("utf-8", errors="replace")
    has_replacement = "\ufffd" in txt
    has_c1 = bool(re.search(r"[\x80-\x9f]", txt))
    if has_replacement or has_c1:
        return raw.decode("cp1252", errors="replace"), "cp1252"
    return txt, "utf-8"


def looks_like_headerless(cols) -> bool:
    col0 = str(cols[0]) if len(cols) > 0 else ""
    col1 = str(cols[1]) if len(cols) > 1 else ""
    generic = {"firstname", "lastname", "vorname", "nachname", "name", "fullname", "email", "upn"}
    return (
        bool(re.search(r"[A-Za-zÄÖÜäöüß]", col0 + col1))
        and norm_key(col0) not in generic
        and norm_key(col1) not in generic
        and len(cols) >= 2
    )


def has_any_alias_columns(cols) -> bool:
    keys = {norm_key(c) for c in cols}
    return bool(keys & (FIRST_ALIASES | LAST_ALIASES | FULL_ALIASES | UPN_ALIASES))


def find_col(cols, aliases: set) -> Optional[str]:
    for c in cols:
        if norm_key(c) in aliases:
            return c
    return None


def split_fullname(fullname: str) -> Optional[Tuple[str, str]]:
    if not fullname or not str(fullname).strip():
        return None
    x = re.sub(r"\s+", " ", str(fullname).strip())
    parts = [p for p in x.split(" ") if p]
    if len(parts) < 2:
        return None

    last = parts[-1]
    i = len(parts) - 2
    while i >= 0 and parts[i].lower() in NAME_PARTICLES:
        last = parts[i] + " " + last
        i -= 1
    first = " ".join(parts[: i + 1]).strip()
    if not first or not last:
        return None
    return first, last


def normalize_name_part(s: str) -> str:
    """Normalization for UPN parts."""
    if not s:
        return ""
    s = str(s).strip()
    s = (
        s.replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _fallback_columns(column_count: int) -> list[str]:
    return ["FirstName", "LastName"] + [f"Col{idx}" for idx in range(3, column_count + 1)]


def _apply_headerless_fallback(
    df: pd.DataFrame,
    fallback_loader: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    if has_any_alias_columns(df.columns) or not looks_like_headerless(df.columns):
        return df

    fallback_df = fallback_loader()
    if fallback_df.shape[1] < 2:
        return df

    fallback_df.columns = _fallback_columns(fallback_df.shape[1])
    return fallback_df


def _read_excel_bytes(raw: bytes, worksheet_number: int, *, header: int | None = 0) -> pd.DataFrame:
    bio = io.BytesIO(raw)
    return pd.read_excel(
        bio,
        sheet_name=max(0, worksheet_number - 1),
        header=header,
        dtype=str,
        engine="openpyxl",
    ).fillna("")


def _read_csv_bytes_or_text(
    raw: bytes,
    text: str,
    delim: str,
    enc: str,
    *,
    header: int | None = 0,
) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(raw), sep=delim, dtype=str, encoding=enc, header=header).fillna("")
    except Exception:
        return pd.read_csv(io.StringIO(text), sep=delim, dtype=str, header=header).fillna("")


def read_table(uploaded_file, worksheet_number: int = 1) -> Tuple[pd.DataFrame, str]:
    name = uploaded_file.name.lower()
    raw = uploaded_file.getvalue()

    if name.endswith(".xlsx"):
        df = _read_excel_bytes(raw, worksheet_number)
        df = _apply_headerless_fallback(
            df,
            lambda: _read_excel_bytes(raw, worksheet_number, header=None),
        )
        return df, "xlsx"

    text, enc = decode_bytes_auto(raw)
    lines = [ln for ln in re.split(r"\r?\n", text) if ln.strip() != ""]
    if not lines:
        return pd.DataFrame(), f"csv({enc})"

    delim = detect_delimiter(lines[0])
    df = _read_csv_bytes_or_text(raw, text, delim, enc)
    df = _apply_headerless_fallback(
        df,
        lambda: _read_csv_bytes_or_text(raw, text, delim, enc, header=None),
    )

    return df, f"csv({enc}, Trennzeichen='{delim}')"
