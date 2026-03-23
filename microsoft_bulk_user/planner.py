from typing import Callable

import pandas as pd

from microsoft_bulk_user.parser import (
    FIRST_ALIASES,
    FULL_ALIASES,
    LAST_ALIASES,
    UPN_ALIASES,
    find_col,
    normalize_name_part,
    split_fullname,
)


def _build_plan_row(
    *,
    row_number: int,
    display_name: str,
    first_name: str,
    last_name: str,
    planned_upn: str,
    status: str,
    details: str,
) -> dict:
    return {
        "row": row_number,
        "displayName": display_name,
        "firstName": first_name,
        "lastName": last_name,
        "plannedUPN": planned_upn,
        "status": status,
        "details": details,
    }


def build_plan(
    df: pd.DataFrame,
    domain: str,
    *,
    name_exists: Callable[[str, str], bool],
    upn_exists: Callable[[str], bool],
) -> pd.DataFrame:
    """
    Regeln:
      - Pro identischem Vorname+Nachname darf es nur 1 Benutzer geben.
      - Wenn Name in der Datei mehrfach vorkommt -> nur der erste bleibt, rest wird übersprungen.
      - Wenn Name in Entra bereits existiert -> überspringen (und explizit ausweisen).
      - UPN wird deterministisch gebaut: vorname.nachname@domain (ohne Suffix-Varianten).
      - Wenn UPN bereits existiert (aber Name nicht als Duplikat erkannt wurde) -> Fehler, weiterlaufen.
    """
    cols = df.columns.tolist()
    c_first = find_col(cols, FIRST_ALIASES)
    c_last = find_col(cols, LAST_ALIASES)
    c_full = find_col(cols, FULL_ALIASES)
    c_upn = find_col(cols, UPN_ALIASES)

    seen_names: set[tuple[str, str]] = set()
    rows: list[dict] = []

    for idx, row in df.iterrows():
        first_raw = str(row.get(c_first, "")).strip() if c_first else ""
        last_raw = str(row.get(c_last, "")).strip() if c_last else ""
        provided_upn = str(row.get(c_upn, "")).strip() if c_upn else ""

        if (not first_raw or not last_raw) and c_full:
            split = split_fullname(str(row.get(c_full, "")).strip())
            if split:
                if not first_raw:
                    first_raw = split[0]
                if not last_raw:
                    last_raw = split[1]

        if (not first_raw or not last_raw) and len(cols) >= 2:
            if not first_raw:
                first_raw = str(row.get(cols[0], "")).strip()
            if not last_raw:
                last_raw = str(row.get(cols[1], "")).strip()

        display = (first_raw + " " + last_raw).strip()

        if not first_raw or not last_raw:
            rows.append(
                _build_plan_row(
                    row_number=idx + 1,
                    display_name=display,
                    first_name=first_raw,
                    last_name=last_raw,
                    planned_upn="",
                    status="FEHLER",
                    details="Vorname/Nachname fehlt oder konnte nicht erkannt werden",
                )
            )
            continue

        name_key = (first_raw.casefold(), last_raw.casefold())
        if name_key in seen_names:
            rows.append(
                _build_plan_row(
                    row_number=idx + 1,
                    display_name=display,
                    first_name=first_raw,
                    last_name=last_raw,
                    planned_upn="",
                    status="ÜBERSPRUNGEN",
                    details="Duplikat in der Datei (gleicher Vor- und Nachname) – wird nicht angelegt",
                )
            )
            continue
        seen_names.add(name_key)

        if provided_upn:
            planned_upn = provided_upn if "@" in provided_upn else f"{provided_upn}@{domain}"
        else:
            first_norm = normalize_name_part(first_raw)
            last_norm = normalize_name_part(last_raw)
            if not first_norm or not last_norm:
                rows.append(
                _build_plan_row(
                    row_number=idx + 1,
                    display_name=display,
                    first_name=first_raw,
                    last_name=last_raw,
                    planned_upn="",
                    status="FEHLER",
                    details="Name kann nicht zu einem gültigen Login-Namen umgewandelt werden",
                )
            )
                continue
            planned_upn = f"{first_norm}.{last_norm}@{domain}"

        if name_exists(first_raw, last_raw):
            rows.append(
                _build_plan_row(
                    row_number=idx + 1,
                    display_name=display,
                    first_name=first_raw,
                    last_name=last_raw,
                    planned_upn=planned_upn,
                    status="ÜBERSPRUNGEN",
                    details="Benutzer existiert bereits in Entra (gleicher Vor- und Nachname) – wird nicht angelegt",
                )
            )
            continue

        if upn_exists(planned_upn):
            rows.append(
                _build_plan_row(
                    row_number=idx + 1,
                    display_name=display,
                    first_name=first_raw,
                    last_name=last_raw,
                    planned_upn=planned_upn,
                    status="FEHLER",
                    details="Login-Name (UPN) existiert bereits – kein automatisches Umbenennen erlaubt",
                )
            )
            continue

        rows.append(
            _build_plan_row(
                row_number=idx + 1,
                display_name=display,
                first_name=first_raw,
                last_name=last_raw,
                planned_upn=planned_upn,
                status="BEREIT",
                details="",
            )
        )

    return pd.DataFrame(rows)
