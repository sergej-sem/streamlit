from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from .events import DEFAULT_EVENT_END, DEFAULT_EVENT_START
from .parser import (
    HEADER_ALIASES,
    WorksheetLayout,
    _normalize_header,
    build_sponsor_row,
    cell_value,
    normalize_text,
)
from .planner import COMPLETED_MARKERS, is_talk_package, is_truthy_marker


# Only current detail sheets are evidence. Archives and copies of Deals may
# describe a different event and must never fill current completion statuses.
COMPANION_SHEETS = {
    "bookletinformationen": "booklet",
    "vortragsinformationen": "talk",
}
TALK_DETAIL_ALIASES = {
    "talk_title": ("Vortragstitel", "Vortrag Titel", "Talk title", "Presentation title"),
    "talk_bullets": ("Vortrag Bullet Points", "Vortrag Bulletpoints", "Vortragsbulletpoints", "Talk bullet points"),
    "speaker_first": ("Vortrag Speaker Vorname", "Speaker Vorname", "Referent Vorname", "Speaker first name"),
    "speaker_last": ("Vortrag Speaker Nachname", "Speaker Nachname", "Referent Nachname", "Speaker last name"),
    "speaker_job": ("Vortrag Speaker Jobtitel", "Speaker Jobtitel", "Referent Jobtitel", "Speaker job title"),
    "speaker_photo": ("Foto Vortragsspeaker", "Foto Vortrag Speaker", "Speakerfoto", "Foto Speaker", "Speaker photo", "Speaker photo received"),
    "talk_date": ("Vortragsdatum", "Vortrag Datum", "Talk date", "Presentation date", "Date of talk"),
}
TALK_CONTENT_KEYS = ("talk_title", "talk_bullets", "speaker_first", "speaker_last", "speaker_job")
PLACEHOLDERS = {
    "", "-", "--", "—", "–", ".", "...", "…", "?", "tbd", "tba", "tbc", "n/a", "na",
    "folgt", "offen", "pending", "ausstehend", "noch offen", "to be determined",
    "to be announced", "wird nachgereicht", "wird noch nachgereicht", "noch nicht vorhanden",
    "fehlt", "nicht vorhanden", "coming soon", "nicht verfügbar", "noch ausstehend",
}


@dataclass(frozen=True)
class _CompanionLayout:
    header_row: int
    columns: Mapping[str, str]


def _company_key(value: object) -> str:
    # Preserve punctuation and accents: near-matching companies are not enough
    # to transfer completion evidence between independently maintained sheets.
    return " ".join(normalize_text(value).casefold().split())


def _cached_value(source_ws, values_ws, column: str, row: int) -> object:
    coordinate = f"{column}{row}"
    source_cell = source_ws[coordinate]
    value_cell = values_ws[coordinate]
    if value_cell.data_type == "e":
        raise ValueError(f"Excel-Fehler in {source_ws.title}!{coordinate}: {value_cell.value}")
    if (
        source_cell.data_type == "f"
        and value_cell.value is None
        and value_cell.data_type not in {"str", "s", "inlineStr"}
    ):
        raise ValueError(
            f"Formel in {source_ws.title}!{coordinate} hat kein gespeichertes Ergebnis. "
            "Bitte die Datei in Excel neu berechnen und speichern."
        )
    return value_cell.value


def _resolve_companion_layout(ws, kind: str) -> _CompanionLayout | None:
    keys = ("sponsor_name", "logo", "booklet") if kind == "booklet" else (
        "sponsor_name", "logo", "presentation",
    )
    alias_groups = {key: HEADER_ALIASES[key] for key in keys}
    if kind == "talk":
        alias_groups.update(TALK_DETAIL_ALIASES)
    aliases = {
        _normalize_header(alias): key
        for key, names in alias_groups.items()
        for alias in names
    }
    best_layout = None
    best_duplicates: list[str] = []
    for row_number, cells in enumerate(
        ws.iter_rows(min_row=1, max_row=min(ws.max_row or 30, 30)), start=1
    ):
        columns: dict[str, str] = {}
        duplicates: list[str] = []
        for cell in cells:
            key = aliases.get(_normalize_header(cell.value))
            if key is None:
                continue
            if key in columns:
                duplicates.append(key)
            else:
                columns[key] = cell.column_letter
        if "sponsor_name" not in columns or len(columns) < 2:
            continue
        if best_layout is None or len(columns) > len(best_layout.columns):
            best_layout = _CompanionLayout(row_number, columns)
            best_duplicates = duplicates
    if best_duplicates:
        raise ValueError(
            f"Mehrdeutige Statusspalten im Zusatzblatt '{ws.title}': "
            + ", ".join(alias_groups[key][0] for key in sorted(set(best_duplicates)))
        )
    return best_layout


def _has_content(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = _company_key(value).rstrip(".! ").replace("\ufe0f", "")
    return text not in PLACEHOLDERS and text not in COMPLETED_MARKERS


def _talk_date_matches_event(value: object, event_start: date, event_end: date) -> bool:
    if value is None or isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return event_start <= value <= event_end
    if isinstance(value, str):
        for date_format in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(value.strip(), date_format).date()
            except ValueError:
                continue
            return event_start <= parsed <= event_end
    return False


def _has_complete_talk_details(source_ws, values_ws, row: int, columns: Mapping[str, str]) -> bool:
    required = (*TALK_CONTENT_KEYS, "speaker_photo")
    if any(key not in columns for key in required):
        return False
    # A known missing field makes the other fields irrelevant. In particular,
    # uncached formulas elsewhere must not block an obviously incomplete row.
    for key in TALK_CONTENT_KEYS:
        source_cell = source_ws[f"{columns[key]}{row}"]
        if source_cell.data_type != "f" and not _has_content(source_cell.value):
            return False
    photo_cell = source_ws[f"{columns['speaker_photo']}{row}"]
    if photo_cell.data_type != "f" and not is_truthy_marker(photo_cell.value):
        return False
    for key in TALK_CONTENT_KEYS:
        if not _has_content(_cached_value(source_ws, values_ws, columns[key], row)):
            return False
    return is_truthy_marker(_cached_value(source_ws, values_ws, columns["speaker_photo"], row))


def _received_keys(
    source_ws, values_ws, row: int, layout: _CompanionLayout, kind: str,
    needed: set[str], event_start: date, event_end: date,
) -> set[str]:
    received = set()
    explicit = ("logo", "booklet") if kind == "booklet" else ("logo", "presentation")
    date_column = layout.columns.get("talk_date") if kind == "talk" else None
    known_old_talk = (
        date_column is not None
        and source_ws[f"{date_column}{row}"].data_type != "f"
        and not _talk_date_matches_event(cell_value(values_ws, date_column, row), event_start, event_end)
    )
    for key in explicit:
        if key == "presentation" and known_old_talk:
            continue
        column = layout.columns.get(key)
        if key in needed and column and is_truthy_marker(_cached_value(source_ws, values_ws, column, row)):
            received.add(key)
    if kind == "talk" and not known_old_talk and "talk_info" in needed and _has_complete_talk_details(
        source_ws, values_ws, row, layout.columns,
    ):
        received.add("talk_info")
    if date_column and received.intersection({"talk_info", "presentation"}) and not _talk_date_matches_event(
        _cached_value(source_ws, values_ws, date_column, row), event_start, event_end,
    ):
        received.difference_update({"talk_info", "presentation"})
    return received


def build_supplemental_received(
    source_workbook,
    values_workbook,
    *,
    sheet_name: str,
    layout: WorksheetLayout,
    event_start: date = DEFAULT_EVENT_START,
    event_end: date = DEFAULT_EVENT_END,
) -> dict[int, frozenset[str]]:
    """Collect completion evidence from unambiguous current detail sheets.

    Evidence only adds completed tasks; an empty secondary cell never resets a
    completed Deals status. Formula results are validated only where evidence
    is needed, and unrelated number, stand and archive formulas are ignored.
    """
    source_ws = source_workbook[sheet_name]
    values_ws = values_workbook[sheet_name]
    company_rows: dict[str, list[int]] = defaultdict(list)
    needed_by_row: dict[int, set[str]] = {}
    name_column = layout.columns["sponsor_name"]
    for row in range(layout.header_row + 1, values_ws.max_row + 1):
        company = _company_key(_cached_value(source_ws, values_ws, name_column, row))
        if not company:
            continue
        company_rows[company].append(row)
        sponsor = build_sponsor_row(values_ws, row, layout)
        if sponsor is None:
            continue
        possible_keys = {"logo", "booklet"}
        if is_talk_package(sponsor.package):
            possible_keys.update({"talk_info", "presentation"})
        needed_by_row[row] = {
            key for key in possible_keys
            if not is_truthy_marker(cell_value(values_ws, layout.columns.get(key), row))
        }
    if not any(needed_by_row.values()):
        return {}

    received_by_row: dict[int, set[str]] = defaultdict(set)
    for companion_source in source_workbook:
        kind = COMPANION_SHEETS.get(_normalize_header(companion_source.title))
        if kind is None or companion_source.title == sheet_name:
            continue
        companion_layout = _resolve_companion_layout(companion_source, kind)
        if companion_layout is None:
            continue
        supported_keys = {"logo", "booklet"} if kind == "booklet" else {"logo", "presentation"}
        supported_keys.intersection_update(companion_layout.columns)
        if kind == "talk" and all(
            key in companion_layout.columns for key in (*TALK_CONTENT_KEYS, "speaker_photo")
        ):
            supported_keys.add("talk_info")
        needed_keys = set().union(*needed_by_row.values())
        if not supported_keys.intersection(needed_keys):
            continue
        companion_values = values_workbook[companion_source.title]
        companion_rows: dict[str, list[int]] = defaultdict(list)
        for row in range(companion_layout.header_row + 1, companion_values.max_row + 1):
            company = _company_key(_cached_value(
                companion_source, companion_values, companion_layout.columns["sponsor_name"], row,
            ))
            if company in company_rows:
                companion_rows[company].append(row)
        for company, rows in companion_rows.items():
            deals_rows = company_rows[company]
            needed = set().union(*(needed_by_row.get(row, set()) for row in deals_rows))
            if not needed:
                continue
            evidence: set[str] = set()
            for row in rows:
                evidence.update(_received_keys(
                    companion_source, companion_values, row, companion_layout, kind, needed,
                    event_start, event_end,
                ))
            if not evidence:
                continue
            if len(deals_rows) != 1 or len(rows) != 1:
                raise ValueError(
                    "Mehrdeutige Sponsorzuordnung für Statusinformationen: "
                    f"'{sheet_name}' Zeilen {', '.join(map(str, deals_rows))}; "
                    f"'{companion_source.title}' Zeilen {', '.join(map(str, rows))}. "
                    "Bitte doppelte Sponsorzeilen prüfen."
                )
            received_by_row[deals_rows[0]].update(evidence)
    return {row: frozenset(keys) for row, keys in received_by_row.items()}
