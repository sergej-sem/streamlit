from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .events import (
    DEFAULT_CHECKIN_END,
    DEFAULT_CHECKIN_START,
    DEFAULT_EVENT_START,
    DeadlineSchedule,
)
from .parser import HEADER_ALIASES, WorksheetLayout, cell_value, resolve_workbook_layout


# Retained for callers using the historical workbook layout. The planner itself
# reads the resolved headers, so reordered sheets use their actual status columns.
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
    "meeting_selection": "AH",
}

TALK_PACKAGES = {"gold", "platin", "platinum"}
COMPLETED_MARKERS = {
    "check", "x", "✓", "✔", "☑", "✅", "true", "1", "done", "erhalten",
    "received", "ja", "yes", "ok", "erledigt", "gebucht", "booked",
    "bestätigt", "confirmed", "completed", "complete",
}


@dataclass(frozen=True)
class DeadlineItem:
    due_date_de: str
    due_date_en: str
    text_de: str
    text_en: str
    status: str
    key: str = ""
    link_url: str = ""
    link_label_de: str = ""
    link_label_en: str = ""


def is_truthy_marker(value: object) -> bool:
    """Only explicit completion markers or dates count as received."""
    if isinstance(value, bool):
        return value
    if isinstance(value, date):
        return True
    if isinstance(value, (int, float)):
        return value == 1
    if value is None:
        return False
    text = str(value).strip().casefold().replace("\ufe0f", "")
    if text in COMPLETED_MARKERS:
        return True
    for date_format in ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            datetime.strptime(text, date_format)
        except ValueError:
            continue
        return True
    return False


def is_talk_package(package: str) -> bool:
    return bool(TALK_PACKAGES.intersection(re.findall(r"\w+", package.casefold())))


def is_premium_package(package: str) -> bool:
    return "premium" in package.strip().casefold()


def status_from_column(ws, row: int, col: str) -> str:
    return "green" if is_truthy_marker(cell_value(ws, col, row)) else "red"


def build_deadlines(
    ws,
    sponsor,
    *,
    event_start: date = DEFAULT_EVENT_START,
    schedule: DeadlineSchedule | None = None,
    layout: WorksheetLayout | None = None,
    onboarding_url: str = "",
    venue: str = "",
    checkin_start: str = DEFAULT_CHECKIN_START,
    checkin_end: str = DEFAULT_CHECKIN_END,
    today: date | None = None,
    supplemental_received: frozenset[str] = frozenset(),
) -> list[DeadlineItem]:
    schedule = schedule or DeadlineSchedule.relative_to(event_start)
    schedule.validate(event_start)
    layout = layout or resolve_workbook_layout(ws)
    today = today or datetime.now(ZoneInfo("Europe/Berlin")).date()
    talk_relevant = is_talk_package(sponsor.package)

    required_keys = {
        "logo", "team_on_site", "handout", "booklet", "target_accounts",
        "led_wall", "posting_published",
    }
    if talk_relevant:
        required_keys.update({"talk_info", "presentation"})
    missing = required_keys.difference(layout.columns)
    if missing:
        raise ValueError(
            "Statusspalten fehlen für folgende Aufgaben: "
            + ", ".join(HEADER_ALIASES[key][0] for key in sorted(missing))
            + ". Bitte die Spaltenüberschriften der Sponsorenliste prüfen."
        )

    def task_status(key: str, *, incomplete: str = "red") -> str:
        if key in supplemental_received:
            return "green"
        col = layout.columns.get(key)
        if not col:
            # Without evidence, do not assert that an optional task is pending.
            return "white"
        return "green" if is_truthy_marker(cell_value(ws, col, sponsor.row_number)) else incomplete

    def item(key: str, due: date | None, de: str, en: str, status: str, **kwargs) -> DeadlineItem:
        return DeadlineItem(
            due_date_de=due.strftime("%d.%m.%Y") if due else "ASAP",
            due_date_en=due.strftime("%d/%m/%Y") if due else "ASAP",
            text_de=de,
            text_en=en,
            status=status,
            key=key,
            **kwargs,
        )

    items = [
        item(
            "onboarding", None,
            "Buche das virtuelle 1:1 Onboarding-Meeting. "
            f"(Buche das Meeting im Idealfall in dem Zeitraum "
            f"{schedule.onboarding_start:%d.%m.%Y} – {schedule.onboarding_end:%d.%m.%Y})",
            "Book the virtual 1:1 onboarding meeting. "
            f"(Ideally schedule it between {schedule.onboarding_start:%d/%m/%Y} "
            f"and {schedule.onboarding_end:%d/%m/%Y})",
            task_status("onboarding"),
            link_url=onboarding_url.strip(),
            link_label_de="1:1 Onboarding Meeting",
            link_label_en="1:1 Onboarding Meeting",
        ),
        item(
            "logo", None,
            "Sende das Unternehmenslogo, falls dies noch nicht erfolgt ist.",
            "Send your company logo, if you have not already done so.",
            task_status("logo"),
        ),
        item(
            "target_accounts", None,
            "Sende deine Target Account Liste, damit wir Deine wichtigsten Ansprechpartner "
            "für Dich zu dem Event einladen können (Wunschteilnehmer).",
            "Send your target account list so that we can invite your most important "
            "contacts to the event (preferred attendees).",
            task_status("target_accounts"),
        ),
        item(
            "posting_published", None,
            "Poste das individuelle Visual zur Veranstaltung auf LinkedIn; gerne unterstützt "
            "das mysecurityevent Team bei der Erstellung.",
            "Post the individual event visual on LinkedIn; the mysecurityevent team "
            "is happy to help create it.",
            task_status("posting_published"),
        ),
        item(
            "hotel", None,
            "Buche Dein Team vor Ort in das Eventhotel ein.",
            "Book your on-site team into the event hotel.",
            "white",
        ),
        item(
            "led_wall", schedule.materials,
            "Sende das LED-Wand-Design.", "Send the LED wall design.",
            task_status("led_wall"),
        ),
        item(
            "booklet", schedule.materials,
            "Sende die Informationen für das Booklet.", "Send the information for the booklet.",
            task_status("booklet"),
        ),
        item(
            "team_on_site", schedule.materials,
            "Sende die Kontaktdaten Deines Teams.", "Send the contact details of your on-site team.",
            task_status("team_on_site"),
        ),
    ]
    if talk_relevant:
        items.append(item(
            "talk_info", schedule.materials,
            "Sende als Gold- oder Platin-Sponsor die Vortragsinformationen.",
            "As a Gold or Platinum sponsor, send the talk information.",
            task_status("talk_info"),
        ))
    items.append(item(
        "handout", schedule.materials,
        "Sende das Handout/Whitepaper.", "Send the handout / whitepaper.",
        task_status("handout"),
    ))
    if talk_relevant:
        items.append(item(
            "presentation", schedule.presentation,
            "Sende als Gold- oder Platin-Sponsor die Vortragspräsentation.",
            "As a Gold or Platinum sponsor, send the presentation slides.",
            task_status("presentation"),
        ))
    items.extend([
        item(
            "participant_list", schedule.participant_list,
            "Severin sendet Dir die Kontaktdatenliste aller Teilnehmer zur Vorauswahl "
            "der individuellen 1:1-Meetings.",
            "Severin will send you the contact details list of all participants for "
            "the pre-selection of individual 1:1 meetings.",
            "yellow",
        ),
        item(
            "meeting_selection", schedule.meeting_selection,
            "Sende Severin die Auswahl der Gesprächswünsche für die individuellen 1:1-Meetings "
            f"spätestens am {schedule.meeting_selection:%d.%m.%Y} auf Basis der "
            f"Kontaktdatenliste vom {schedule.participant_list:%d.%m.%Y} "
            "für eine optimale Vorbereitung der Meetings zu.",
            "Send Severin your preferred selections for individual 1:1 meetings "
            f"by {schedule.meeting_selection:%d/%m/%Y}, based on the contact details list "
            f"from {schedule.participant_list:%d/%m/%Y}, for optimal meeting preparation.",
            # Future preparation remains yellow until the actual submission deadline.
            task_status("meeting_selection", incomplete=(
                "red" if today >= schedule.meeting_selection else "yellow"
            )),
        ),
        item(
            "event_start", event_start,
            (f"Eventstart im {venue.strip()}. " if venue.strip() else "Eventstart. ")
            + f"Sponsoren Check-In zwischen {checkin_start} und {checkin_end} Uhr.",
            (f"Event starts at {venue.strip()}. " if venue.strip() else "Event starts. ")
            + f"Sponsor check-in between {checkin_start} and {checkin_end}.",
            "white",
        ),
    ])
    return items
