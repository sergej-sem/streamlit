from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import urlsplit

from openpyxl import load_workbook

from .events import (
    DEFAULT_EVENT_CITY,
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    DEFAULT_EVENT_VENUE,
    DEFAULT_ONBOARDING_URL,
    DeadlineSchedule,
)
from .parser import (
    ACTIVE_MARKERS,
    SponsorRow,
    build_sponsor_row,
    cell_value,
    list_workbook_sheets,
    normalize_text,
    resolve_workbook_layout,
    slugify,
)
from .planner import (
    STATUS_COLS,
    DeadlineItem,
    build_deadlines,
    is_talk_package,
)
from .rendering import build_html_body, build_subject, build_summary_dataframe
from .workbook_statuses import build_supplemental_received


DEFAULT_SHEET_NAME = "Deals"


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


def parse_event_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = normalize_text(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Datum: {value}")


def generate_deadline_mails(
    excel_bytes: bytes,
    sheet_name: str = DEFAULT_SHEET_NAME,
    event_city: str = DEFAULT_EVENT_CITY,
    event_start: date | str = DEFAULT_EVENT_START,
    event_end: date | str = DEFAULT_EVENT_END,
    signature_html: str = "",
    *,
    deadline_schedule: DeadlineSchedule | None = None,
    onboarding_url: str | None = None,
    venue: str | None = None,
    checkin_start: str = "14:00",
    checkin_end: str = "16:00",
    today: date | None = None,
) -> GenerationResult:
    start_date = parse_event_date(event_start)
    end_date = parse_event_date(event_end)
    if end_date < start_date:
        raise ValueError("Das Event-Ende darf nicht vor dem Event-Start liegen.")
    event_city = normalize_text(event_city)
    if not event_city:
        raise ValueError("Bitte eine Event-Stadt angeben.")
    schedule = deadline_schedule or DeadlineSchedule.relative_to(start_date)
    schedule.validate(start_date)
    is_current_munich_event = (
        start_date == DEFAULT_EVENT_START
        and event_city.casefold() in {"münchen", "muenchen", "munich"}
    )
    if onboarding_url is None:
        onboarding_url = DEFAULT_ONBOARDING_URL if is_current_munich_event else ""
    if venue is None:
        venue = DEFAULT_EVENT_VENUE if is_current_munich_event else ""
    onboarding_url = normalize_text(onboarding_url)
    if onboarding_url:
        parsed_url = urlsplit(onboarding_url)
        if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
            raise ValueError("Der Onboarding-Link muss eine gültige HTTPS- oder HTTP-Adresse sein.")
    try:
        checkin_from = time.fromisoformat(checkin_start)
        checkin_to = time.fromisoformat(checkin_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bitte gültige Check-in-Uhrzeiten im Format HH:MM angeben.") from exc
    if checkin_to <= checkin_from:
        raise ValueError("Das Ende des Sponsoren-Check-ins muss nach dem Beginn liegen.")
    workbook = load_workbook(io.BytesIO(excel_bytes), data_only=False)
    values_workbook = None

    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Blatt '{sheet_name}' nicht gefunden. Verfügbar: {', '.join(workbook.sheetnames)}"
            )

        source_ws = workbook[sheet_name]
        layout = resolve_workbook_layout(source_ws, strict=True)
        values_workbook = load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = values_workbook[sheet_name]
        supplemental_received = build_supplemental_received(
            workbook, values_workbook, sheet_name=sheet_name, layout=layout,
            event_start=start_date, event_end=end_date,
        )
        mails: list[GeneratedMail] = []
        candidate_rows = 0

        def validated_value(key: str, row_number: int) -> object:
            col = layout.columns.get(key)
            if col is None:
                return None
            coordinate = f"{col}{row_number}"
            source_cell = source_ws[coordinate]
            value_cell = ws[coordinate]
            if value_cell.data_type == "e":
                raise ValueError(f"Excel-Fehler in {sheet_name}!{coordinate}: {value_cell.value}")
            if (
                source_cell.data_type == "f"
                and value_cell.value is None
                # A formula's explicit string-result type survives data_only.
                # It identifies a valid empty-string cache, unlike the empty
                # numeric cache openpyxl writes for an uncalculated formula.
                and value_cell.data_type not in {"str", "s", "inlineStr"}
            ):
                raise ValueError(
                    f"Formel in {sheet_name}!{coordinate} hat kein gespeichertes Ergebnis. "
                    "Bitte die Datei in Excel neu berechnen und speichern."
                )
            return value_cell.value

        for row_number in range(layout.header_row + 1, ws.max_row + 1):
            sponsor_name = normalize_text(validated_value("sponsor_name", row_number))
            if not sponsor_name:
                continue

            candidate_rows += 1
            deal_active = normalize_text(validated_value("deal_active", row_number)).casefold().replace("\ufe0f", "")
            if deal_active and deal_active not in ACTIVE_MARKERS:
                continue

            primary_email = normalize_text(validated_value("contact1_email", row_number))
            second_email = normalize_text(validated_value("contact2_email", row_number))
            if not primary_email and not second_email:
                continue

            # Only the chosen recipient's names are used for the salutation.
            contact_prefix = "contact1" if primary_email else "contact2"
            for key in (f"{contact_prefix}_first", f"{contact_prefix}_last", "language", "package"):
                validated_value(key, row_number)

            sponsor = build_sponsor_row(ws, row_number, layout=layout)
            if sponsor is None:
                continue

            for key in STATUS_COLS:
                if key in {"talk_info", "presentation"} and not is_talk_package(sponsor.package):
                    continue
                validated_value(key, row_number)

            items = build_deadlines(
                ws, sponsor, event_start=start_date, schedule=schedule, layout=layout,
                onboarding_url=onboarding_url, venue=venue,
                checkin_start=checkin_start, checkin_end=checkin_end, today=today,
                supplemental_received=supplemental_received.get(row_number, frozenset()),
            )
            subject = build_subject(sponsor.language, sponsor.sponsor_name)
            html_body = build_html_body(sponsor, items, event_city, start_date, end_date, signature_html)
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
        if values_workbook is not None:
            values_workbook.close()
