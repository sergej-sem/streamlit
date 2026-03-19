from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

import pandas as pd
from openpyxl import load_workbook


DEFAULT_SHEET_NAME = "Deals"
DEFAULT_EVENT_CITY = "Berlin"
DEFAULT_EVENT_START = date(2026, 5, 5)
DEFAULT_EVENT_END = date(2026, 5, 7)

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

STATUS_COLS = {
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
}

ENGLISH_LANG_VALUES = {"ENG", "EN", "ENGLISH"}
TALK_PACKAGES = {"gold", "platin", "platinum"}
ACTIVE_MARKERS = {"check", "x", "ja", "yes", "true", "ok", "done", "erhalten"}

COLOR_BG = {
    "green": "#E7F6EC",
    "red": "#FDECEC",
    "yellow": "#FFF7D6",
    "white": "#FFFFFF",
}
COLOR_BORDER = {
    "green": "#7DBE8A",
    "red": "#E39A9A",
    "yellow": "#D3B03C",
    "white": "#D9D9D9",
}
COLOR_TEXT = {
    "green": "#1F6B3A",
    "red": "#A13131",
    "yellow": "#8A6A00",
    "white": "#333333",
}
STATUS_LABEL_DE = {
    "green": "Gruen - bereits erhalten",
    "red": "Rot - Handlungsbedarf",
    "yellow": "Gelb - ausstehend",
    "white": "Ohne Markierung",
}
STATUS_LABEL_EN = {
    "green": "Green - already received",
    "red": "Red - action required",
    "yellow": "Yellow - pending",
    "white": "No highlight",
}
SUMMARY_FIELDNAMES = [
    "row_number",
    "sponsor_name",
    "language",
    "package",
    "to_email",
    "cc_email",
    "subject",
    "html_file_name",
    "green_count",
    "red_count",
    "yellow_count",
    "white_count",
    "outlook_result",
]


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


@dataclass(frozen=True)
class DeadlineItem:
    due_date_de: str
    due_date_en: str
    text_de: str
    text_en: str
    status: str


@dataclass(frozen=True)
class GeneratedMail:
    row_number: int
    sponsor_name: str
    language: str
    package: str
    to_email: str
    cc_email: str
    subject: str
    html_body: str
    html_file_name: str
    green_count: int
    red_count: int
    yellow_count: int
    white_count: int
    outlook_result: str = "not_requested"


@dataclass(frozen=True)
class GenerationResult:
    sheet_name: str
    event_city: str
    event_start: date
    event_end: date
    mails: tuple[GeneratedMail, ...]
    processed_count: int
    skipped_count: int


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


def is_truthy_marker(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip()
    if not text:
        return False
    # Every non-empty text, comment, or date counts as "received", matching the CLI script.
    return True


def is_talk_package(package: str) -> bool:
    return package.strip().lower() in TALK_PACKAGES


def cell_value(ws, col: str, row: int) -> object:
    return ws[f"{col}{row}"].value


def list_workbook_sheets(excel_bytes: bytes) -> list[str]:
    workbook = load_workbook(io.BytesIO(excel_bytes), read_only=True, data_only=False)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def build_sponsor_row(ws, row: int) -> Optional[SponsorRow]:
    sponsor_name = normalize_text(cell_value(ws, NAME_COL, row))
    if not sponsor_name:
        return None

    deal_active = normalize_text(cell_value(ws, DEAL_ACTIVE_COL, row)).lower()
    if deal_active and deal_active not in ACTIVE_MARKERS:
        return None

    package = normalize_package(cell_value(ws, PACKAGE_COL, row))
    language = normalize_lang(cell_value(ws, LANG_COL, row))

    first_name = normalize_text(cell_value(ws, CONTACT1_FIRST_COL, row))
    last_name = normalize_text(cell_value(ws, CONTACT1_LAST_COL, row))
    to_email = normalize_text(cell_value(ws, CONTACT1_EMAIL_COL, row))
    cc_email = normalize_text(cell_value(ws, CONTACT2_EMAIL_COL, row))

    if not to_email and cc_email:
        to_email = cc_email
        cc_email = ""
        first_name = normalize_text(cell_value(ws, CONTACT2_FIRST_COL, row))
        last_name = normalize_text(cell_value(ws, CONTACT2_LAST_COL, row))

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


def status_from_column(ws, row: int, col: str) -> str:
    return "green" if is_truthy_marker(cell_value(ws, col, row)) else "red"


def build_deadlines(ws, sponsor: SponsorRow) -> list[DeadlineItem]:
    talk_relevant = is_talk_package(sponsor.package)
    talk_info_status = (
        status_from_column(ws, sponsor.row_number, STATUS_COLS["talk_info"])
        if talk_relevant
        else "white"
    )
    presentation_status = (
        status_from_column(ws, sponsor.row_number, STATUS_COLS["presentation"])
        if talk_relevant
        else "white"
    )

    return [
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Buche das virtuelle Onboarding-Meeting. (Buche das Meeting im Idealfall in dem Zeitraum vom 09.03.2026 bis zum 13.03.2026)",
            text_en="Book the virtual onboarding meeting. (Ideally schedule it between 09/03/2026 and 13/03/2026)",
            status="white",
        ),
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Sende das Unternehmenslogo, falls dies noch nicht erfolgt ist.",
            text_en="Send your company logo, if you have not already done so.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["logo"]),
        ),
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Sende deine Target Account Liste, damit wir diese zu dem Event einladen koennen (Wunschteilnehmer).",
            text_en="Send your target account list so that we can invite them to the event (preferred attendees).",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["target_accounts"]),
        ),
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Poste das individuelle Visual zur Veranstaltung auf LinkedIn; gerne unterstuetze ich bei der Erstellung.",
            text_en="Post the individual event visual on LinkedIn; I am happy to support you with its creation.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["posting_published"]),
        ),
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Buche Dein Team vor Ort in das Eventhotel ein.",
            text_en="Book your on-site team into the event hotel.",
            status="white",
        ),
        DeadlineItem(
            due_date_de="26.03.2026",
            due_date_en="26/03/2026",
            text_de="Sende das LED-Wand-Design.",
            text_en="Send the LED wall design.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["led_wall"]),
        ),
        DeadlineItem(
            due_date_de="26.03.2026",
            due_date_en="26/03/2026",
            text_de="Sende die Informationen fuer das Booklet.",
            text_en="Send the information for the booklet.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["booklet"]),
        ),
        DeadlineItem(
            due_date_de="26.03.2026",
            due_date_en="26/03/2026",
            text_de="Sende die Kontaktdaten Deines Teams.",
            text_en="Send the contact details of your on-site team.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["team_on_site"]),
        ),
        DeadlineItem(
            due_date_de="26.03.2026",
            due_date_en="26/03/2026",
            text_de="Sende als Gold- oder Platin-Sponsor die Vortragsinformationen.",
            text_en="As a Gold or Platinum sponsor, send your talk information.",
            status=talk_info_status,
        ),
        DeadlineItem(
            due_date_de="26.03.2026",
            due_date_en="26/03/2026",
            text_de="Sende das Handout/Whitepaper.",
            text_en="Send the handout / whitepaper.",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["handout"]),
        ),
        DeadlineItem(
            due_date_de="20.04.2026",
            due_date_en="20/04/2026",
            text_de="Sende als Gold- oder Platin-Sponsor die Vortragspraesentation.",
            text_en="As a Gold or Platinum sponsor, send your presentation slides.",
            status=presentation_status,
        ),
        DeadlineItem(
            due_date_de="20.04.2026",
            due_date_en="20/04/2026",
            text_de="Severin sendet Dir die Kontaktdatenliste aller Teilnehmer zur Vorauswahl der individuellen 1:1-Meetings.",
            text_en="Severin will send you the contact details list of all participants for the pre-selection of individual 1:1 meetings.",
            status="yellow",
        ),
        DeadlineItem(
            due_date_de="27.04.2026",
            due_date_en="27/04/2026",
            text_de="Sende Severin die Auswahl der Gespraechswuensche auf Basis der Kontaktdatenliste (vom 20.04.2026) fuer eine optimale Vorbereitung der Meetings.",
            text_en="Send Severin your preferred meeting selections based on the contact details list (from 20/04/2026) for optimal meeting preparation.",
            status="yellow",
        ),
    ]


def build_subject(language: str, sponsor_name: str) -> str:
    if language == "EN":
        return f"Important Information // mysecurityevent // Deadlines // {sponsor_name}"
    return f"Wichtige Informationen // mysecurityevent // Deadlines // {sponsor_name}"


def parse_event_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    text = normalize_text(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Ungueltiges Datum: {value}")


def format_event_date(value: date, language: str) -> str:
    return value.strftime("%d/%m/%Y") if language == "EN" else value.strftime("%d.%m.%Y")


def build_intro(
    sponsor: SponsorRow,
    event_city: str,
    event_start: date,
    event_end: date,
) -> tuple[str, str, str]:
    start_text = format_event_date(event_start, sponsor.language)
    end_text = format_event_date(event_end, sponsor.language)
    salutation_name = sponsor.contact_first_name or sponsor.contact_last_name or ""

    if sponsor.language == "EN":
        salutation = f"Hi {html.escape(salutation_name)}," if salutation_name else "Hi,"
        intro = (
            "Today I am sending you a reminder regarding the upcoming deadlines for the "
            f"mysecurityevent in {html.escape(event_city)}, taking place from {html.escape(start_text)} to {html.escape(end_text)}."
        )
        explainer = (
            "Below you will find an overview of all documents and information that are still needed from you for the event preparation. "
            "Please make sure to observe the respective deadlines to ensure optimal preparation and a successful event."
        )
    else:
        salutation = f"Hallo {html.escape(salutation_name)}," if salutation_name else "Hallo,"
        intro = (
            "heute sende ich Dir einen Reminder fuer die anstehenden Deadlines des mysecurityevent in "
            f"{html.escape(event_city)} vom {html.escape(start_text)} bis zum {html.escape(end_text)}."
        )
        explainer = (
            "Du findest hier eine Uebersicht aller Unterlagen, die ich in der Eventvorbereitung noch von Dir benoetige. "
            "Bitte beachte unbedingt die entsprechenden Deadlines fuer eine optimale Vorbereitung und ein erfolgreiches Event."
        )

    return salutation, intro, explainer


def legend_html(language: str) -> str:
    if language == "EN":
        lines = [
            "All items marked in green require no further action, as the necessary information or documents have already been received.",
            "All items marked in red require your action.",
            "Items marked in yellow are still pending and will become relevant in the coming weeks.",
        ]
    else:
        lines = [
            "Bei allen gruen markierten Punkten besteht kein Handlungsbedarf, da wir die Informationen bzw. Unterlagen bereits erhalten haben.",
            "Bei allen rot markierten Punkten besteht Handlungsbedarf Deinerseits.",
            "Alle gelb markierten Punkte sind noch ausstehend und werden in den kommenden Wochen relevant.",
        ]
    return "".join(f"<li>{html.escape(line)}</li>" for line in lines)


def render_deadline_rows(items: Iterable[DeadlineItem], language: str) -> str:
    rows = []
    for item in items:
        due_date = item.due_date_en if language == "EN" else item.due_date_de
        text = item.text_en if language == "EN" else item.text_de
        status_label = STATUS_LABEL_EN[item.status] if language == "EN" else STATUS_LABEL_DE[item.status]
        rows.append(
            f"""
            <tr>
                <td style="padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top; white-space:nowrap;"><strong>{html.escape(due_date)}</strong></td>
                <td style="padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top;">{html.escape(text)}</td>
                <td style="padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top;">
                    <span style="display:inline-block; padding:4px 10px; border-radius:999px; border:1px solid {COLOR_BORDER[item.status]}; background:{COLOR_BG[item.status]}; color:{COLOR_TEXT[item.status]}; font-weight:600;">
                        {html.escape(status_label)}
                    </span>
                </td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_html_body(
    sponsor: SponsorRow,
    items: list[DeadlineItem],
    event_city: str,
    event_start: date,
    event_end: date,
) -> str:
    salutation, intro, explainer = build_intro(sponsor, event_city, event_start, event_end)
    overview_head = "Deadline Overview" if sponsor.language == "EN" else "Deadlines auf einen Blick"
    footer = "Best regards," if sponsor.language == "EN" else "Beste Gruesse,"

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(build_subject(sponsor.language, sponsor.sponsor_name))}</title>
</head>
<body style="font-family: Arial, Helvetica, sans-serif; color:#222; line-height:1.5;">
  <p>{salutation}</p>
  <p>{intro}</p>
  <p>{explainer}</p>
  <ul>
    {legend_html(sponsor.language)}
  </ul>
  <p><strong>{html.escape(overview_head)}</strong></p>
  <table style="border-collapse:collapse; width:100%; max-width:1100px;">
    <thead>
      <tr>
        <th style="padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">Deadline</th>
        <th style="padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">{'Task' if sponsor.language == 'EN' else 'Aufgabe'}</th>
        <th style="padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">Status</th>
      </tr>
    </thead>
    <tbody>
      {render_deadline_rows(items, sponsor.language)}
    </tbody>
  </table>
  <p>{html.escape(footer)}</p>
</body>
</html>
""".strip()


def build_summary_rows(result: GenerationResult) -> list[dict]:
    return [
        {
            "row_number": mail.row_number,
            "sponsor_name": mail.sponsor_name,
            "language": mail.language,
            "package": mail.package,
            "to_email": mail.to_email,
            "cc_email": mail.cc_email,
            "subject": mail.subject,
            "html_file_name": mail.html_file_name,
            "green_count": mail.green_count,
            "red_count": mail.red_count,
            "yellow_count": mail.yellow_count,
            "white_count": mail.white_count,
            "outlook_result": mail.outlook_result,
        }
        for mail in result.mails
    ]


def build_summary_dataframe(result: GenerationResult) -> pd.DataFrame:
    rows = build_summary_rows(result)
    return pd.DataFrame(rows, columns=SUMMARY_FIELDNAMES)


def generate_deadline_mails(
    excel_bytes: bytes,
    sheet_name: str = DEFAULT_SHEET_NAME,
    event_city: str = DEFAULT_EVENT_CITY,
    event_start: date | str = DEFAULT_EVENT_START,
    event_end: date | str = DEFAULT_EVENT_END,
) -> GenerationResult:
    start_date = parse_event_date(event_start)
    end_date = parse_event_date(event_end)
    workbook = load_workbook(io.BytesIO(excel_bytes), data_only=False)

    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Blatt '{sheet_name}' nicht gefunden. Verfuegbar: {', '.join(workbook.sheetnames)}"
            )

        ws = workbook[sheet_name]
        mails: list[GeneratedMail] = []
        candidate_rows = 0

        for row_number in range(2, ws.max_row + 1):
            sponsor_name = normalize_text(cell_value(ws, NAME_COL, row_number))
            if not sponsor_name:
                continue

            candidate_rows += 1
            sponsor = build_sponsor_row(ws, row_number)
            if sponsor is None:
                continue

            items = build_deadlines(ws, sponsor)
            subject = build_subject(sponsor.language, sponsor.sponsor_name)
            html_body = build_html_body(sponsor, items, event_city, start_date, end_date)
            html_file_name = f"{row_number:03d}_{slugify(sponsor.sponsor_name)}.html"
            green_count = sum(1 for item in items if item.status == "green")
            red_count = sum(1 for item in items if item.status == "red")
            yellow_count = sum(1 for item in items if item.status == "yellow")
            white_count = sum(1 for item in items if item.status == "white")

            mails.append(
                GeneratedMail(
                    row_number=sponsor.row_number,
                    sponsor_name=sponsor.sponsor_name,
                    language=sponsor.language,
                    package=sponsor.package,
                    to_email=sponsor.to_email,
                    cc_email=sponsor.cc_email,
                    subject=subject,
                    html_body=html_body,
                    html_file_name=html_file_name,
                    green_count=green_count,
                    red_count=red_count,
                    yellow_count=yellow_count,
                    white_count=white_count,
                )
            )

        return GenerationResult(
            sheet_name=sheet_name,
            event_city=event_city,
            event_start=start_date,
            event_end=end_date,
            mails=tuple(mails),
            processed_count=len(mails),
            skipped_count=max(candidate_rows - len(mails), 0),
        )
    finally:
        workbook.close()
