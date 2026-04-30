from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from sponsor_deadline_mails.parser import build_sponsor_row, normalize_text
from shared.mail_message import MailAttachment
from shared.mail_rich_text import render_final_mail_html
from serienmailing.imap_sender import SerienMail
from serienmailing.mail_builder import build_subject


DEFAULT_SHEET_NAME = "Deals"
SUPPORTED_PACKAGES = {"premium": "Premium", "gold": "Gold", "platin": "Platin"}
PREMIUM_KEY = "premium"
GOLD_KEY = "gold"
PLATIN_KEY = "platin"

_TRANSLITERATION_MAP = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
    }
)


@dataclass(frozen=True)
class UploadedAttachmentFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class EventEndSponsorPlan:
    row_number: int
    sponsor_name: str
    package: str
    language: str
    to_email: str
    cc_email: str
    contact_first_name: str
    contact_last_name: str
    attachments: tuple[MailAttachment, ...]
    status: str
    details: str

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def attachment_names(self) -> tuple[str, ...]:
        return tuple(attachment.filename for attachment in self.attachments)


@dataclass(frozen=True)
class EventEndAssemblyResult:
    sponsors: tuple[EventEndSponsorPlan, ...]
    ready_count: int
    blocked_count: int
    skipped_count: int


def normalize_attachment_key(value: str) -> str:
    text = normalize_text(value).translate(_TRANSLITERATION_MAP)
    text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _file_ext(name: str) -> str:
    return Path(name).suffix.lower()


def _file_stem_key(name: str) -> str:
    return normalize_attachment_key(Path(name).stem)


def _package_key(value: str) -> str:
    return normalize_text(value).casefold()


def _expected_stem(sponsor_name: str, suffix: str) -> str:
    return normalize_attachment_key(f"{sponsor_name}_{suffix}")


def _resolve_named_attachment(
    sponsor_name: str,
    suffix: str,
    files: tuple[UploadedAttachmentFile, ...],
    allowed_exts: tuple[str, ...],
    label: str,
) -> tuple[MailAttachment | None, str | None]:
    expected = _expected_stem(sponsor_name, suffix)
    matches = [
        file
        for file in files
        if _file_ext(file.name) in allowed_exts and _file_stem_key(file.name) == expected
    ]
    if not matches:
        allowed_text = ", ".join(ext.lstrip(".") for ext in allowed_exts)
        return None, f"{label} fehlt ({sponsor_name}_{suffix}.{allowed_text})."
    if len(matches) > 1:
        names = ", ".join(file.name for file in matches)
        return None, f"{label} ist nicht eindeutig: {names}."
    match = matches[0]
    return MailAttachment(filename=match.name, content=match.content), None


def assemble_eventende_sponsors(
    *,
    excel_bytes: bytes,
    kontaktliste: UploadedAttachmentFile | None,
    gespraechsplan_files: tuple[UploadedAttachmentFile, ...],
    vortragsliste_files: tuple[UploadedAttachmentFile, ...],
    sheet_name: str = DEFAULT_SHEET_NAME,
) -> EventEndAssemblyResult:
    workbook = load_workbook(io.BytesIO(excel_bytes), data_only=False)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Blatt '{sheet_name}' nicht gefunden. Verfügbar: {', '.join(workbook.sheetnames)}"
            )

        ws = workbook[sheet_name]
        sponsors: list[EventEndSponsorPlan] = []
        candidate_rows = 0

        for row_number in range(2, ws.max_row + 1):
            sponsor_name = normalize_text(ws[f"B{row_number}"].value)
            if not sponsor_name:
                continue
            candidate_rows += 1
            sponsor = build_sponsor_row(ws, row_number)
            if sponsor is None:
                continue

            package_key = _package_key(sponsor.package)
            if package_key not in SUPPORTED_PACKAGES:
                continue

            issues: list[str] = []
            attachments: list[MailAttachment] = []

            if kontaktliste is None:
                issues.append("Kontaktliste fehlt.")
            else:
                attachments.append(
                    MailAttachment(filename=kontaktliste.name, content=kontaktliste.content)
                )

            if package_key == PREMIUM_KEY:
                attachment, issue = _resolve_named_attachment(
                    sponsor.sponsor_name,
                    "Gesprächsplan",
                    gespraechsplan_files,
                    (".xlsx", ".xls"),
                    "Gesprächsplan",
                )
                if issue:
                    issues.append(issue)
                elif attachment is not None:
                    attachments.append(attachment)
            elif package_key in {GOLD_KEY, PLATIN_KEY}:
                attachment, issue = _resolve_named_attachment(
                    sponsor.sponsor_name,
                    "Gesprächsplan",
                    gespraechsplan_files,
                    (".pdf",),
                    "Gesprächsplan",
                )
                if issue:
                    issues.append(issue)
                elif attachment is not None:
                    attachments.append(attachment)

                attachment, issue = _resolve_named_attachment(
                    sponsor.sponsor_name,
                    "Vortragsliste",
                    vortragsliste_files,
                    (".xlsx", ".xls"),
                    "Vortragsliste",
                )
                if issue:
                    issues.append(issue)
                elif attachment is not None:
                    attachments.append(attachment)

            sponsors.append(
                EventEndSponsorPlan(
                    row_number=sponsor.row_number,
                    sponsor_name=sponsor.sponsor_name,
                    package=SUPPORTED_PACKAGES[package_key],
                    language=sponsor.language,
                    to_email=sponsor.to_email,
                    cc_email=sponsor.cc_email,
                    contact_first_name=sponsor.contact_first_name,
                    contact_last_name=sponsor.contact_last_name,
                    attachments=tuple(attachments),
                    status="ready" if not issues else "blocked",
                    details=" ".join(issues).strip(),
                )
            )

        ready_count = sum(1 for sponsor in sponsors if sponsor.is_ready)
        blocked_count = sum(1 for sponsor in sponsors if not sponsor.is_ready)
        return EventEndAssemblyResult(
            sponsors=tuple(sponsors),
            ready_count=ready_count,
            blocked_count=blocked_count,
            skipped_count=max(candidate_rows - len(sponsors), 0),
        )
    finally:
        workbook.close()


def build_eventende_serienmails(
    sponsors: tuple[EventEndSponsorPlan, ...],
    *,
    subject_template: str,
    body_html_template: str,
    sender_email: str,
) -> list[SerienMail]:
    mails: list[SerienMail] = []
    for sponsor in sponsors:
        if not sponsor.is_ready:
            continue
        vorname = sponsor.contact_first_name or sponsor.sponsor_name
        mails.append(
            SerienMail(
                to_email=sponsor.to_email,
                cc_email=sponsor.cc_email,
                vorname=vorname,
                firma=sponsor.sponsor_name,
                subject=build_subject(
                    subject_template,
                    vorname,
                    sponsor.sponsor_name,
                    sponsor.to_email,
                ),
                html_body=render_final_mail_html(
                    body_html_template,
                    sender_email=sender_email.strip(),
                    vorname=vorname,
                    firma=sponsor.sponsor_name,
                    email=sponsor.to_email,
                ),
                attachments=sponsor.attachments,
            )
        )
    return mails


def build_eventende_summary_dataframe(
    sponsors: tuple[EventEndSponsorPlan, ...],
) -> pd.DataFrame:
    rows = [
        {
            "Sponsor": sponsor.sponsor_name,
            "Paket": sponsor.package,
            "E-Mail": sponsor.to_email,
            "Kopie": sponsor.cc_email or "-",
            "Anhänge": " | ".join(sponsor.attachment_names) or "-",
            "Status": "Bereit" if sponsor.is_ready else "Blockiert",
            "Hinweis": sponsor.details or "-",
        }
        for sponsor in sponsors
    ]
    return pd.DataFrame(
        rows,
        columns=["Sponsor", "Paket", "E-Mail", "Kopie", "Anhänge", "Status", "Hinweis"],
    )
