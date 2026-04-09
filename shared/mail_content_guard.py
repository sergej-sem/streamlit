from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from serienmailing.mail_builder import html_to_plain_text

_GENERIC_TEST_TERMS = {
    "123",
    "hallo",
    "hi",
    "mail",
    "probe",
    "test",
}
_GREETING_RE = re.compile(r"\b(hallo|hi|guten tag|liebe?r?|dear)\b", re.IGNORECASE)
_CLOSING_RE = re.compile(
    r"\b(beste gr(?:u|ue|ü)(?:sse|ße)|freundliche gr(?:u|ue|ü)(?:sse|ße)|best regards|kind regards|viele gr(?:u|ue|ü)(?:sse|ße))\b",
    re.IGNORECASE,
)
_LINK_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class MailContentAssessment:
    risk_level: str
    score: int
    blocked: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MailBatchAssessment:
    risk_level: str
    score: int
    blocked: bool
    reasons: tuple[str, ...]
    total_count: int
    flagged_count: int
    blocked_count: int


@dataclass(frozen=True)
class MailGuardFeedback:
    blocked: bool
    level: str
    message: str
    reasons: tuple[str, ...]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).strip()


def _lower_text(value: str) -> str:
    return _normalize_text(value).casefold()


def _add_reason(reasons: list[str], text: str) -> None:
    if text not in reasons:
        reasons.append(text)


def _risk_level_for_score(score: int) -> str:
    if score >= 7:
        return "hoch"
    if score >= 4:
        return "mittel"
    return "niedrig"


def assess_mail_content(subject: str, body_text: str) -> MailContentAssessment:
    normalized_subject = _normalize_text(subject)
    normalized_body = _normalize_text(body_text)
    subject_lower = normalized_subject.casefold()
    body_lower = normalized_body.casefold()
    subject_words = _WORD_RE.findall(normalized_subject)
    body_words = _WORD_RE.findall(normalized_body)
    non_empty_lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
    letter_chars = [char for char in normalized_body if char.isalpha()]
    upper_ratio = (
        sum(1 for char in letter_chars if char.isupper()) / len(letter_chars)
        if letter_chars
        else 0.0
    )
    special_chars = [char for char in normalized_body if not char.isalnum() and not char.isspace()]
    special_ratio = (
        len(special_chars) / max(len(normalized_body), 1)
        if normalized_body
        else 0.0
    )
    sentence_markers = sum(normalized_body.count(marker) for marker in ".!?")
    link_count = len(_LINK_RE.findall(normalized_body))
    reasons: list[str] = []
    score = 0

    if subject_lower in _GENERIC_TEST_TERMS:
        score += 5
        _add_reason(reasons, "Betreff ist zu generisch oder testartig.")
    elif len(subject_words) <= 1 and len(normalized_subject) < 6:
        score += 3
        _add_reason(reasons, "Betreff ist zu kurz.")
    elif len(normalized_subject) < 10:
        score += 2
        _add_reason(reasons, "Betreff ist wenig aussagekraeftig.")

    if not normalized_body:
        score += 7
        _add_reason(reasons, "Text ist leer.")
    elif body_lower in _GENERIC_TEST_TERMS:
        score += 7
        _add_reason(reasons, "Text wirkt wie eine reine Testnachricht.")
    elif len(body_words) <= 2:
        score += 6
        _add_reason(reasons, "Text ist extrem kurz.")
    elif len(body_words) <= 5:
        score += 4
        _add_reason(reasons, "Text wirkt sehr knapp.")
    elif len(body_words) <= 10 and len(non_empty_lines) <= 1:
        score += 2
        _add_reason(reasons, "Text ist fuer eine normale Geschaeftsmail sehr knapp.")

    if normalized_body and len(non_empty_lines) <= 1 and len(normalized_body) < 24:
        score += 2
        _add_reason(reasons, "Text besteht praktisch nur aus einer Kurzzeile.")

    if normalized_body and sentence_markers == 0 and len(body_words) < 8:
        score += 2
        _add_reason(reasons, "Text hat kaum erkennbare Satzstruktur.")

    if (
        normalized_body
        and len(body_words) < 14
        and sentence_markers == 0
        and not (_GREETING_RE.search(normalized_body) or _CLOSING_RE.search(normalized_body))
    ):
        score += 1
        _add_reason(reasons, "Text wirkt ungewoehnlich knapp und ohne normale Grussstruktur.")

    if normalized_body.count("!") >= 4:
        score += 1
        _add_reason(reasons, "Text enthaelt auffaellig viele Ausrufezeichen.")

    if len(letter_chars) >= 10 and upper_ratio >= 0.45:
        score += 2
        _add_reason(reasons, "Text enthaelt ungewoehnlich viel Grossschreibung.")

    if link_count >= 3:
        score += 2
        _add_reason(reasons, "Text enthaelt ungewoehnlich viele Links.")
    elif link_count == 2:
        score += 1
        _add_reason(reasons, "Text enthaelt mehrere Links.")

    if len(normalized_body) >= 20 and special_ratio >= 0.2:
        score += 1
        _add_reason(reasons, "Text enthaelt ungewoehnlich viele Sonderzeichen.")

    blocked = (
        body_lower in _GENERIC_TEST_TERMS
        or (subject_lower in _GENERIC_TEST_TERMS and len(body_words) <= 5)
        or (len(body_words) <= 2 and len(subject_words) <= 1)
        or (score >= 10 and len(body_words) <= 5)
    )

    return MailContentAssessment(
        risk_level=_risk_level_for_score(score),
        score=score,
        blocked=blocked,
        reasons=tuple(reasons),
    )


def assess_html_mail_content(subject: str, html_body: str) -> MailContentAssessment:
    return assess_mail_content(subject, html_to_plain_text(html_body))


def assess_mail_batch(items: Iterable[tuple[str, str]]) -> MailBatchAssessment:
    assessments = [assess_mail_content(subject, body_text) for subject, body_text in items]
    if not assessments:
        return MailBatchAssessment(
            risk_level="niedrig",
            score=0,
            blocked=False,
            reasons=tuple(),
            total_count=0,
            flagged_count=0,
            blocked_count=0,
        )

    risk_rank = {"niedrig": 0, "mittel": 1, "hoch": 2}
    worst = max(assessments, key=lambda item: (risk_rank[item.risk_level], item.score, item.blocked))
    flagged_count = sum(item.risk_level != "niedrig" for item in assessments)
    blocked_count = sum(item.blocked for item in assessments)
    return MailBatchAssessment(
        risk_level=worst.risk_level,
        score=worst.score,
        blocked=blocked_count > 0,
        reasons=worst.reasons,
        total_count=len(assessments),
        flagged_count=flagged_count,
        blocked_count=blocked_count,
    )


def assess_html_mail_batch(items: Iterable[tuple[str, str]]) -> MailBatchAssessment:
    return assess_mail_batch((subject, html_to_plain_text(html_body)) for subject, html_body in items)


def evaluate_send_guard(mode: str, assessment: MailContentAssessment | MailBatchAssessment) -> MailGuardFeedback:
    reasons = assessment.reasons
    if assessment.risk_level == "niedrig":
        return MailGuardFeedback(
            blocked=False,
            level="none",
            message="",
            reasons=reasons,
        )

    if mode == "Senden" and assessment.blocked:
        return MailGuardFeedback(
            blocked=True,
            level="error",
            message="Spam-Risiko: hoch. Der Versand ist blockiert, weil der Inhalt testartig oder deutlich zu duenn wirkt.",
            reasons=reasons,
        )

    if assessment.risk_level == "hoch":
        return MailGuardFeedback(
            blocked=False,
            level="error",
            message="Spam-Risiko: hoch",
            reasons=reasons,
        )

    if assessment.risk_level == "mittel":
        return MailGuardFeedback(
            blocked=False,
            level="warning",
            message="Spam-Risiko: mittel",
            reasons=reasons,
        )

    return MailGuardFeedback(
        blocked=False,
        level="none",
        message="",
        reasons=reasons,
    )
