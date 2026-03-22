from __future__ import annotations

from dataclasses import dataclass

from .parser import cell_value


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

TALK_PACKAGES = {"gold", "platin", "platinum"}


@dataclass(frozen=True)
class DeadlineItem:
    due_date_de: str
    due_date_en: str
    text_de: str
    text_en: str
    status: str


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


def is_premium_package(package: str) -> bool:
    return "premium" in package.strip().lower()


def status_from_column(ws, row: int, col: str) -> str:
    return "green" if is_truthy_marker(cell_value(ws, col, row)) else "red"


def build_deadlines(ws, sponsor) -> list[DeadlineItem]:
    talk_relevant = is_talk_package(sponsor.package)
    premium_package = is_premium_package(sponsor.package)
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

    items = [
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
            text_de="Sende deine Target Account Liste, damit wir diese zu dem Event einladen können (Wunschteilnehmer).",
            text_en="Send your target account list so that we can invite them to the event (preferred attendees).",
            status=status_from_column(ws, sponsor.row_number, STATUS_COLS["target_accounts"]),
        ),
        DeadlineItem(
            due_date_de="ASAP",
            due_date_en="ASAP",
            text_de="Poste das individuelle Visual zur Veranstaltung auf LinkedIn; gerne unterstütze ich bei der Erstellung.",
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
            text_de="Sende die Informationen für das Booklet.",
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
            text_de="Sende uns die Vortragsinformationen zu.",
            text_en="Send us the talk information.",
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
            text_de="Sende uns die Vortragspräsentation zu.",
            text_en="Send us the presentation slides.",
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
            text_de="Sende Severin die Auswahl der Gesprächswünsche auf Basis der Kontaktdatenliste (vom 20.04.2026) für eine optimale Vorbereitung der Meetings.",
            text_en="Send Severin your preferred meeting selections based on the contact details list (from 20/04/2026) for optimal meeting preparation.",
            status="yellow",
        ),
    ]

    if premium_package:
        excluded_tasks = {
            "Sende uns die Vortragsinformationen zu.",
            "Sende uns die Vortragspräsentation zu.",
            "Send us the talk information.",
            "Send us the presentation slides.",
        }
        return [
            item
            for item in items
            if item.text_de not in excluded_tasks and item.text_en not in excluded_tasks
        ]

    return items
