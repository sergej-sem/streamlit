# serienmailing/contacts.py

from __future__ import annotations

import re
import unicodedata
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from shared.email_validation import is_valid_email_address, normalize_email_address

# Internal column names used throughout this module
COLS = ["vorname", "firma", "email", "cc_email"]

_EMAIL_LIST_SEPARATOR_RE = re.compile(r"[;,\r\n]+")
_EMAIL_HEADER_RE = re.compile(r"\b(?:e mail|email|mail)\b")
_ASP_HEADER_RE = re.compile(r"\basp\s*(\d+)\b")


def _normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _normalized_aliases(*values: str) -> set[str]:
    return {_normalize_header(value) for value in values}


# Column aliases recognized on import. Header normalization makes matching
# insensitive to case, umlauts, underscores, hyphens and repeated whitespace.
_VORNAME_ALIASES = _normalized_aliases(
    "vorname",
    "firstname",
    "first name",
    "first_name",
    "ASP 1 Vorname",
)
_FIRMA_ALIASES = _normalized_aliases(
    "firma",
    "company",
    "organisation",
    "organization",
    "unternehmen",
    "sponsor",
)
_EMAIL_ALIASES = _normalized_aliases(
    "email",
    "e-mail",
    "e_mail",
    "mail",
    "an",
    "an email",
    "an e-mail",
    "to",
    "to email",
    "empfaenger",
    "empfaenger email",
    "ASP 1 E-Mail Adresse",
)
_CC_ALIASES = _normalized_aliases(
    "cc",
    "cc email",
    "cc e-mail",
    "cc_email",
    "kopie",
    "kopie email",
    "kopie e-mail",
)


@dataclass(frozen=True)
class ContactColumnMapping:
    """Source columns used to create the internal contact table."""

    email: Hashable | None
    cc_email: tuple[Hashable, ...] = ()
    vorname: Hashable | None = None
    firma: Hashable | None = None


@dataclass(frozen=True)
class RecipientValidationIssue:
    """One invalid recipient value in a normalized contact table."""

    contact_number: int
    field: str
    value: str


def _detect_col(df_cols: Sequence[Hashable], aliases: set[str]) -> Hashable | None:
    for col in df_cols:
        if _normalize_header(col) in aliases:
            return col
    return None


def _looks_like_email_header(column: Hashable) -> bool:
    return bool(_EMAIL_HEADER_RE.search(_normalize_header(column)))


def _asp_number(column: Hashable) -> int | None:
    match = _ASP_HEADER_RE.search(_normalize_header(column))
    return int(match.group(1)) if match else None


def _looks_like_cc_header(column: Hashable) -> bool:
    normalized = _normalize_header(column)
    asp_number = _asp_number(column)
    return (
        normalized in _CC_ALIASES
        or (bool(_EMAIL_HEADER_RE.search(normalized)) and "cc" in normalized.split())
        or (bool(_EMAIL_HEADER_RE.search(normalized)) and "kopie" in normalized.split())
        or (bool(_EMAIL_HEADER_RE.search(normalized)) and asp_number is not None and asp_number >= 2)
    )


def suggest_contact_column_mapping(columns: Sequence[Hashable]) -> ContactColumnMapping:
    """Suggest an editable import mapping from common and numbered headers."""

    cols = list(columns)
    vorname = _detect_col(cols, _VORNAME_ALIASES)
    firma = _detect_col(cols, _FIRMA_ALIASES)
    email = _detect_col(cols, _EMAIL_ALIASES)

    if email is None:
        email = next(
            (col for col in cols if _looks_like_email_header(col) and _asp_number(col) == 1),
            None,
        )

    cc_email = tuple(
        col
        for col in cols
        if col != email and _looks_like_cc_header(col)
    )

    if email is None:
        remaining_email_columns = [
            col
            for col in cols
            if col not in cc_email and _looks_like_email_header(col)
        ]
        if len(remaining_email_columns) == 1:
            email = remaining_email_columns[0]

    return ContactColumnMapping(
        email=email,
        cc_email=cc_email,
        vorname=vorname,
        firma=firma,
    )


def split_email_addresses(value: Any) -> tuple[str, ...]:
    """Split a spreadsheet cell containing comma/semicolon/newline-separated addresses."""

    if value is None or (not isinstance(value, (list, tuple, dict, set)) and pd.isna(value)):
        return ()
    raw = str(value or "").strip()
    if not raw:
        return ()
    return tuple(part.strip() for part in _EMAIL_LIST_SEPARATOR_RE.split(raw) if part.strip())


def normalize_cc_addresses(values: Sequence[Any], *, to_email: Any = "") -> str:
    """Combine, normalize and case-insensitively deduplicate CC cell values."""

    normalized_to = normalize_email_address(str(to_email or "")).casefold()
    addresses: list[str] = []
    seen: set[str] = set()

    for value in values:
        for raw_address in split_email_addresses(value):
            normalized = normalize_email_address(raw_address)
            address = normalized or raw_address.strip()
            key = address.casefold()
            if not address or key in seen or (normalized_to and key == normalized_to):
                continue
            seen.add(key)
            addresses.append(address)

    return ", ".join(addresses)


def is_valid_cc_address_list(value: Any) -> bool:
    """Return True for an empty CC value or a list containing only valid addresses."""

    addresses = split_email_addresses(value)
    return not addresses or all(is_valid_email_address(address) for address in addresses)


def _empty_series(df: pd.DataFrame) -> pd.Series:
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _text_series(df: pd.DataFrame, column: Hashable | None) -> pd.Series:
    if column is None or column not in df.columns:
        return _empty_series(df)
    return df[column].fillna("").astype(str).str.strip()


def _normalize(
    df: pd.DataFrame,
    mapping: ContactColumnMapping,
) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []

    vorname = _text_series(df, mapping.vorname)
    if mapping.vorname is None or mapping.vorname not in df.columns:
        warnings.append("Spalte 'Vorname' nicht zugeordnet – Feld bleibt leer.")

    firma = _text_series(df, mapping.firma)
    if mapping.firma is None or mapping.firma not in df.columns:
        warnings.append("Spalte 'Firma' nicht zugeordnet – Feld bleibt leer.")

    email = _text_series(df, mapping.email)
    if mapping.email is None or mapping.email not in df.columns:
        warnings.append("Spalte 'An (E-Mail)' nicht zugeordnet – keine Kontakte importiert.")

    cc_columns = tuple(
        column
        for column in mapping.cc_email
        if column in df.columns and column != mapping.email
    )
    if cc_columns:
        cc_email = pd.Series(
            (
                normalize_cc_addresses(
                    [df.at[index, column] for column in cc_columns],
                    to_email=email.at[index],
                )
                for index in df.index
            ),
            index=df.index,
            dtype=str,
        )
    else:
        cc_email = _empty_series(df)

    result = pd.DataFrame(
        {
            "vorname": vorname,
            "firma": firma,
            "email": email,
            "cc_email": cc_email,
        },
        columns=COLS,
    )

    before = len(result)
    result = result[result["email"] != ""].reset_index(drop=True)
    removed = before - len(result)
    if removed:
        warnings.append(f"{removed} Zeile(n) ohne An-Adresse wurden entfernt.")

    return result, warnings


def contacts_from_excel(
    df: pd.DataFrame,
    *,
    mapping: ContactColumnMapping | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Normalize a DataFrame read from an Excel/CSV upload."""

    resolved_mapping = mapping or suggest_contact_column_mapping(list(df.columns))
    return _normalize(df, resolved_mapping)


def contacts_from_hubspot_raw(raw: list[dict]) -> pd.DataFrame:
    """Convert get_contacts_by_ids() results to internal DataFrame."""

    rows = []
    for item in raw:
        props = item.get("properties") or {}
        rows.append({
            "vorname": (props.get("firstname") or "").strip(),
            "firma": (props.get("company") or "").strip(),
            "email": (props.get("email") or "").strip(),
            "cc_email": "",
        })
    df = pd.DataFrame(rows, columns=COLS)
    return df[df["email"] != ""].reset_index(drop=True)


def contacts_from_manual(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normalize a DataFrame coming directly from st.data_editor."""

    return _normalize(
        df,
        ContactColumnMapping(
            email="email",
            cc_email=("cc_email",),
            vorname="vorname",
            firma="firma",
        ),
    )


def normalize_contact_editor_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the editable contact list without hiding incomplete rows.

    Unlike the import helpers, this keeps rows with an empty recipient so the
    user can finish correcting them or delete them explicitly. Fully empty rows
    (for example an untouched dynamic editor row) are discarded.
    """

    source = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    for column in COLS:
        if column not in source.columns:
            source[column] = ""

    result = source.loc[:, COLS].copy()
    for column in COLS:
        result[column] = result[column].map(
            lambda value: "" if value is None or pd.isna(value) else str(value).strip()
        )

    result = result[result.ne("").any(axis=1)].reset_index(drop=True)
    result["email"] = result["email"].map(normalize_email_address)
    result["cc_email"] = pd.Series(
        (
            normalize_cc_addresses([row["cc_email"]], to_email=row["email"])
            for _, row in result.iterrows()
        ),
        index=result.index,
        dtype=str,
    )
    return result


def apply_contact_editor_changes(
    df: pd.DataFrame,
    editing_state: Mapping[str, Any] | None,
) -> pd.DataFrame:
    """Apply a Streamlit data-editor delta to a contact table."""

    result = normalize_contact_editor_data(df)
    if not isinstance(editing_state, Mapping):
        return result

    edited_rows = editing_state.get("edited_rows", {})
    if isinstance(edited_rows, Mapping):
        for position_value, changes in edited_rows.items():
            if not isinstance(changes, Mapping):
                continue
            try:
                position = int(position_value)
            except (TypeError, ValueError):
                continue
            if position < 0 or position >= len(result):
                continue
            for column, value in changes.items():
                if column in COLS:
                    result.iat[position, result.columns.get_loc(column)] = value

    deleted_rows = editing_state.get("deleted_rows", [])
    if isinstance(deleted_rows, Sequence) and not isinstance(deleted_rows, (str, bytes)):
        deleted_positions: set[int] = set()
        for position_value in deleted_rows:
            try:
                position = int(position_value)
            except (TypeError, ValueError):
                continue
            if 0 <= position < len(result):
                deleted_positions.add(position)
        if deleted_positions:
            result = result.iloc[
                [position for position in range(len(result)) if position not in deleted_positions]
            ]

    added_rows = editing_state.get("added_rows", [])
    if isinstance(added_rows, Sequence) and not isinstance(added_rows, (str, bytes)):
        additions = [
            {column: row.get(column, "") for column in COLS}
            for row in added_rows
            if isinstance(row, Mapping)
        ]
        if additions:
            result = pd.concat(
                [result, pd.DataFrame(additions, columns=COLS)],
                ignore_index=True,
            )

    return normalize_contact_editor_data(result)


def recipient_validation_issues(df: pd.DataFrame) -> list[RecipientValidationIssue]:
    """Return row-level invalid To/CC values for UI feedback and send guards."""

    issues: list[RecipientValidationIssue] = []
    if df.empty or "email" not in df.columns:
        return issues

    for contact_number, (_, row) in enumerate(df.iterrows(), start=1):
        to_email = str(row.get("email", "") or "").strip()
        if not to_email:
            issues.append(RecipientValidationIssue(contact_number, "An", "(leer)"))
        elif not is_valid_email_address(to_email):
            issues.append(RecipientValidationIssue(contact_number, "An", to_email))

        for cc_email in split_email_addresses(row.get("cc_email", "")):
            if not is_valid_email_address(cc_email):
                issues.append(RecipientValidationIssue(contact_number, "CC", cc_email))

    return issues


def validate_contacts(df: pd.DataFrame) -> list[str]:
    """Return a list of validation error strings (empty = all good)."""

    errors: list[str] = []

    if df.empty or "email" not in df.columns:
        errors.append("Keine Kontakte vorhanden.")
        return errors

    emails = df["email"].fillna("").astype(str).map(normalize_email_address)

    empty = (emails == "").sum()
    if empty:
        errors.append(f"{empty} Kontakt(e) ohne An-Adresse.")

    invalid_mask = (emails != "") & ~emails.map(is_valid_email_address)
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        errors.append(f"{invalid_count} Kontakt(e) mit ungültiger An-Adresse.")

    cc_values = (
        df["cc_email"].fillna("").astype(str)
        if "cc_email" in df.columns
        else _empty_series(df)
    )
    invalid_cc_count = sum(
        not is_valid_email_address(address)
        for value in cc_values
        for address in split_email_addresses(value)
    )
    if invalid_cc_count:
        errors.append(f"{invalid_cc_count} ungültige CC-Adresse(n) gefunden.")

    dupes = emails[~invalid_mask]
    dupes = dupes[dupes != ""].str.casefold()
    dup_count = dupes.duplicated().sum()
    if dup_count:
        errors.append(f"{dup_count} doppelte An-Adresse(n) gefunden.")

    return errors
