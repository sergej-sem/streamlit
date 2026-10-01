from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

from openpyxl import load_workbook

from .recipients import normalize_recipient_cell


NAME_COL = "B"
PACKAGE_COL = "E"
LANG_COL = "K"
CONTACT1_FIRST_COL = "L"
CONTACT1_LAST_COL = "M"
CONTACT1_EMAIL_COL = "N"
CONTACT2_FIRST_COL = "O"
CONTACT2_LAST_COL = "P"
CONTACT2_EMAIL_COL = "Q"
DEAL_ACTIVE_COL = "D"

ENGLISH_LANG_VALUES = {"ENG", "EN", "ENGLISH", "ENGLISCH", "EN-GB", "EN-US"}
ACTIVE_MARKERS = {
    "check", "x", "ja", "yes", "true", "ok", "done", "erhalten",
    "1", "1.0", "✓", "✔", "✅", "☑",
}

# Used only by the compatibility path for headerless worksheets. Real workbook
# layouts are always resolved from their headers, including optional fields.
LEGACY_COLUMNS = {
    "sponsor_name": NAME_COL,
    "package": PACKAGE_COL,
    "language": LANG_COL,
    "contact1_first": CONTACT1_FIRST_COL,
    "contact1_last": CONTACT1_LAST_COL,
    "contact1_email": CONTACT1_EMAIL_COL,
    "contact2_first": CONTACT2_FIRST_COL,
    "contact2_last": CONTACT2_LAST_COL,
    "contact2_email": CONTACT2_EMAIL_COL,
    "deal_active": DEAL_ACTIVE_COL,
    "logo": "S",
    "team_on_site": "T",
    "handout": "V",
    "booklet": "W",
    "talk_info": "X",
    "onboarding": "Y",
    "target_accounts": "Z",
    "led_wall": "AA",
    "posting_published": "AF",
    "presentation": "AG",
    "meeting_selection": "AH",
}

HEADER_ALIASES = {
    "sponsor_name": ("Name", "Sponsor", "Sponsorenname", "Unternehmen", "Firma", "Sponsor name", "Company name"),
    "package": ("Paket", "Sponsorenpaket", "Sponsoringpaket", "Package", "Sponsorship package"),
    "language": ("Sprache", "Language"),
    "contact1_first": ("ASP 1 Vorname", "AP 1 Vorname", "Ansprechpartner 1 Vorname", "Kontakt 1 Vorname", "Contact 1 first name"),
    "contact1_last": ("ASP 1 Nachname", "AP 1 Nachname", "Ansprechpartner 1 Nachname", "Kontakt 1 Nachname", "Contact 1 last name"),
    "contact1_email": ("ASP 1 E-Mail Adresse", "ASP 1 E-Mail", "AP 1 E-Mail", "Ansprechpartner 1 E-Mail", "Kontakt 1 E-Mail", "Contact 1 email", "Contact 1 email address"),
    "contact2_first": ("ASP 2 Vorname", "AP 2 Vorname", "Ansprechpartner 2 Vorname", "Kontakt 2 Vorname", "Contact 2 first name"),
    "contact2_last": ("ASP 2 Nachname", "AP 2 Nachname", "Ansprechpartner 2 Nachname", "Kontakt 2 Nachname", "Contact 2 last name"),
    "contact2_email": ("ASP 2 E-Mail Adresse", "ASP 2 E-Mail", "AP 2 E-Mail", "Ansprechpartner 2 E-Mail", "Kontakt 2 E-Mail", "Contact 2 email", "Contact 2 email address"),
    "deal_active": ("Deal liegt vor", "Deal aktiv", "Aktiver Deal", "Deal active", "Deal received"),
    "logo": ("Logo", "Logo liegt vor", "Logo erhalten", "Company logo", "Logo received"),
    "team_on_site": ("Sponsoren Vor Ort", "Team vor Ort", "Team Kontaktdaten", "Kontaktdaten Team", "On-site team", "Team contact details"),
    "handout": ("Handout", "Handout/Whitepaper", "Handout Whitepaper", "Handout erhalten", "Whitepaper"),
    "booklet": ("Booklet Informationen", "Bookletinformationen", "Bookletinformationen liegen vor", "Booklet information", "Booklet received"),
    "talk_info": ("Vortragsinformationen", "Vortragsinformationen erhalten", "Vortragsinformationen liegen vor", "Talk information", "Talk information received"),
    "onboarding": ("Onboarding", "Onboarding Meeting", "Onboarding gebucht", "Onboarding meeting booked"),
    "target_accounts": ("Wunschteilnehmerliste erhalten", "Wunschteilnehmerliste", "Target Account Liste", "Target Account Liste erhalten", "Target Accounts", "Target account list", "Target account list received"),
    "led_wall": ("LED Wand Design", "LED-Wand-Design", "LED Wand Design erhalten", "LED wall design", "LED wall design received"),
    "posting_published": ("Posting gepostet", "Posting veröffentlicht", "LinkedIn Posting veröffentlicht", "Posting published", "LinkedIn post published"),
    "presentation": ("Präsentation erhalten", "Vortragspräsentation erhalten", "Vortragspräsentation", "Presentation received", "Presentation slides received"),
    "meeting_selection": ("Teilnehmerliste Gesprächswünsche erhalten", "Gesprächswünsche erhalten", "Gesprächswünsche", "Meetingauswahl erhalten", "Meeting selection", "Meeting selection received"),
}


@dataclass(frozen=True)
class WorksheetLayout:
    header_row: int
    columns: Mapping[str, str]


def _normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", normalize_text(value).casefold())
    return "".join(character for character in text if character.isalnum())


def resolve_workbook_layout(ws, *, strict: bool = False) -> WorksheetLayout:
    """Find the sponsor header row and resolve semantic fields to columns.

    Optional fields are absent from ``columns`` when their header is absent.
    The legacy compatibility path accepts an empty first row; production callers
    can require a real header row with ``strict=True``.
    """
    aliases = {
        _normalize_header(alias): key
        for key, names in HEADER_ALIASES.items()
        for alias in names
    }
    best_row = 0
    best_columns: dict[str, str] = {}
    best_duplicates: list[str] = []
    for row_number, cells in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 30, 30)), start=1):
        columns: dict[str, str] = {}
        duplicates: list[str] = []
        for cell in cells:
            key = aliases.get(_normalize_header(cell.value))
            if key is None:
                continue
            if key in columns:
                duplicates.append(HEADER_ALIASES[key][0])
            else:
                columns[key] = cell.column_letter
        if len(columns) > len(best_columns):
            best_row = row_number
            best_columns = columns
            best_duplicates = duplicates

    if not best_columns:
        if not strict and all(cell.value is None for cell in ws[1]):
            return WorksheetLayout(header_row=1, columns=dict(LEGACY_COLUMNS))
        raise ValueError("Keine Sponsoren-Kopfzeile gefunden. Bitte die Spaltenüberschriften prüfen.")

    if best_duplicates:
        raise ValueError(
            "Mehrdeutige Sponsoren-Spaltenüberschriften: " + ", ".join(sorted(set(best_duplicates)))
        )

    required = ("sponsor_name", "package", "deal_active")
    missing = [HEADER_ALIASES[key][0] for key in required if key not in best_columns]
    if not {"contact1_email", "contact2_email"}.intersection(best_columns):
        missing.append("ASP 1 E-Mail Adresse oder ASP 2 E-Mail Adresse")
    if missing:
        raise ValueError("Pflichtspalten fehlen in der Sponsorenliste: " + ", ".join(missing))

    return WorksheetLayout(header_row=best_row, columns=best_columns)


@dataclass(frozen=True)
class SponsorRow:
    row_number: int
    sponsor_name: str
    package: str
    language: str
    to_email: str
    cc_email: str
    contact_first_name: str
    contact_last_name: str


def list_workbook_sheets(excel_bytes: bytes) -> list[str]:
    workbook = load_workbook(io.BytesIO(excel_bytes), read_only=True, data_only=False)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def cell_value(ws, col: str | None, row: int) -> object:
    if col is None:
        return None
    return ws[f"{col}{row}"].value


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lang(value: object) -> str:
    return "EN" if normalize_text(value).upper() in ENGLISH_LANG_VALUES else "DE"


def normalize_package(value: object) -> str:
    return normalize_text(value)


def slugify(value: str) -> str:
    text = normalize_text(value).casefold()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = text.strip("_")
    return text or "sponsor"


def build_sponsor_row(ws, row: int, layout: WorksheetLayout | None = None) -> SponsorRow | None:
    layout = layout or resolve_workbook_layout(ws)
    if row <= layout.header_row:
        return None

    def value(key: str) -> object:
        return cell_value(ws, layout.columns.get(key), row)

    sponsor_name = normalize_text(value("sponsor_name"))
    if not sponsor_name:
        return None

    deal_active = normalize_text(value("deal_active")).casefold().replace("\ufe0f", "")
    if deal_active and deal_active not in ACTIVE_MARKERS:
        return None

    package = normalize_package(value("package"))
    language = normalize_lang(value("language"))

    first_name = normalize_text(value("contact1_first"))
    last_name = normalize_text(value("contact1_last"))
    to_email = normalize_recipient_cell(value("contact1_email"))
    cc_email = normalize_recipient_cell(value("contact2_email"))

    if not to_email and cc_email:
        to_email = cc_email
        cc_email = ""
        first_name = normalize_text(value("contact2_first"))
        last_name = normalize_text(value("contact2_last"))

    if not to_email:
        return None

    return SponsorRow(
        row_number=row,
        sponsor_name=sponsor_name,
        package=package,
        language=language,
        to_email=to_email,
        cc_email=cc_email,
        contact_first_name=first_name,
        contact_last_name=last_name,
    )
