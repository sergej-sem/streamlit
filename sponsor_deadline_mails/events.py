from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


DEFAULT_EVENT_CITY = "München"
DEFAULT_EVENT_START = date(2026, 11, 17)
DEFAULT_EVENT_END = date(2026, 11, 19)
DEFAULT_ONBOARDING_URL = (
    "https://calendly.com/mysecurityevent/1-1-meeting-sponsoren-mysecurityevent-munich"
)
DEFAULT_EVENT_VENUE = "Business Club der Allianz Arena"
DEFAULT_CHECKIN_START = "14:00"
DEFAULT_CHECKIN_END = "16:00"


@dataclass(frozen=True)
class DeadlineSchedule:
    """Event deadlines, derived from the event date unless explicitly configured."""

    onboarding_start: date
    onboarding_end: date
    materials: date
    presentation: date
    participant_list: date
    meeting_selection: date

    @classmethod
    def relative_to(cls, event_start: date) -> DeadlineSchedule:
        return cls(
            onboarding_start=event_start - timedelta(days=91),
            onboarding_end=event_start - timedelta(days=78),
            materials=event_start - timedelta(days=33),
            presentation=event_start - timedelta(days=19),
            participant_list=event_start - timedelta(days=14),
            meeting_selection=event_start - timedelta(days=7),
        )

    def validate(self, event_start: date) -> None:
        values = (
            self.onboarding_start,
            self.onboarding_end,
            self.materials,
            self.presentation,
            self.participant_list,
            self.meeting_selection,
            event_start,
        )
        if not all(isinstance(value, date) for value in values):
            raise ValueError("Eventdatum und alle Deadlines müssen Datumswerte sein.")
        if self.onboarding_start > self.onboarding_end:
            raise ValueError(
                "Der Beginn des Onboarding-Zeitraums muss vor oder auf dessen Enddatum liegen."
            )
        if any(value >= event_start for value in values[:-1]):
            raise ValueError("Alle Deadlines müssen vor dem Eventstart liegen.")
        if self.participant_list > self.meeting_selection:
            raise ValueError(
                "Die Teilnehmerliste muss spätestens am Tag der Deadline "
                "für die Gesprächswünsche bereitstehen."
            )
