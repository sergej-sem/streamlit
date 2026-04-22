# serienmailing/contacts.py

from __future__ import annotations

import pandas as pd
from shared.email_validation import is_valid_email_address, normalize_email_address

# Internal column names used throughout this module
COLS = ["vorname", "firma", "email"]

# Column aliases recognized on import (all lowercase)
_VORNAME_ALIASES = {"vorname", "firstname", "first name", "first_name", "vorname"}
_FIRMA_ALIASES   = {"firma", "company", "organisation", "organization", "unternehmen"}
_EMAIL_ALIASES   = {"email", "e-mail", "e_mail", "mail"}


def _detect_col(df_cols: list[str], aliases: set[str]) -> str | None:
    for col in df_cols:
        if col.strip().lower() in aliases:
            return col
    return None


def _normalize(df: pd.DataFrame, col_vorname: str | None, col_firma: str | None, col_email: str | None) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    out: dict[str, pd.Series] = {}

    if col_vorname and col_vorname in df.columns:
        out["vorname"] = df[col_vorname].fillna("").astype(str).str.strip()
    else:
        warnings.append("Spalte 'Vorname' nicht gefunden – Feld bleibt leer.")
        out["vorname"] = pd.Series([""] * len(df), dtype=str)

    if col_firma and col_firma in df.columns:
        out["firma"] = df[col_firma].fillna("").astype(str).str.strip()
    else:
        warnings.append("Spalte 'Firma' nicht gefunden – Feld bleibt leer.")
        out["firma"] = pd.Series([""] * len(df), dtype=str)

    if col_email and col_email in df.columns:
        out["email"] = df[col_email].fillna("").astype(str).str.strip()
    else:
        warnings.append("Spalte 'E-Mail' nicht gefunden – keine Kontakte importiert.")
        out["email"] = pd.Series([""] * len(df), dtype=str)

    result = pd.DataFrame(out, columns=COLS)

    before = len(result)
    result = result[result["email"] != ""].reset_index(drop=True)
    removed = before - len(result)
    if removed:
        warnings.append(f"{removed} Zeile(n) ohne E-Mail-Adresse wurden entfernt.")

    return result, warnings


def contacts_from_excel(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normalize a DataFrame read from an Excel/CSV upload."""
    cols = list(df.columns)
    col_v = _detect_col(cols, _VORNAME_ALIASES)
    col_f = _detect_col(cols, _FIRMA_ALIASES)
    col_e = _detect_col(cols, _EMAIL_ALIASES)
    return _normalize(df, col_v, col_f, col_e)


def contacts_from_hubspot_raw(raw: list[dict]) -> pd.DataFrame:
    """Convert get_contacts_by_ids() results to internal DataFrame."""
    rows = []
    for item in raw:
        props = item.get("properties") or {}
        rows.append({
            "vorname": (props.get("firstname") or "").strip(),
            "firma":   (props.get("company")   or "").strip(),
            "email":   (props.get("email")     or "").strip(),
        })
    df = pd.DataFrame(rows, columns=COLS)
    return df[df["email"] != ""].reset_index(drop=True)


def contacts_from_manual(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normalize a DataFrame coming directly from st.data_editor."""
    warnings: list[str] = []
    result = pd.DataFrame({
        "vorname": df.get("vorname", pd.Series(dtype=str)).fillna("").astype(str).str.strip(),
        "firma":   df.get("firma",   pd.Series(dtype=str)).fillna("").astype(str).str.strip(),
        "email":   df.get("email",   pd.Series(dtype=str)).fillna("").astype(str).str.strip(),
    }, columns=COLS)

    before = len(result)
    result = result[result["email"] != ""].reset_index(drop=True)
    removed = before - len(result)
    if removed:
        warnings.append(f"{removed} Zeile(n) ohne E-Mail-Adresse wurden entfernt.")

    return result, warnings


def validate_contacts(df: pd.DataFrame) -> list[str]:
    """Return a list of validation error strings (empty = all good)."""
    errors: list[str] = []

    if df.empty or "email" not in df.columns:
        errors.append("Keine Kontakte vorhanden.")
        return errors

    emails = df["email"].fillna("").astype(str).map(normalize_email_address)

    empty = (emails == "").sum()
    if empty:
        errors.append(f"{empty} Kontakt(e) ohne E-Mail-Adresse.")

    invalid_mask = (emails != "") & ~emails.map(is_valid_email_address)
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        errors.append(f"{invalid_count} Kontakt(e) mit ungültiger E-Mail-Adresse.")

    dupes = emails[~invalid_mask]
    dupes = dupes[dupes != ""].str.casefold()
    dup_count = dupes.duplicated().sum()
    if dup_count:
        errors.append(f"{dup_count} doppelte E-Mail-Adresse(n) gefunden.")

    return errors
