# badgegen/badge_mail.py
"""
Pure business logic: build per-person SerienMail objects with badge PDF attachments.
No Streamlit imports — fully unit-testable.
"""
from __future__ import annotations

import html as _html_mod
import re
import pandas as pd

from badgegen.render_pdf import render_badges_pdf_bytes
from serienmailing.imap_sender import SerienMail
from serienmailing.mail_builder import build_html_body, build_subject


def _safe_filename(firstname: str, lastname: str) -> str:
    name = f"Badge_{firstname}_{lastname}".strip("_")
    name = re.sub(r"[^\w\-.]", "_", name)
    name = re.sub(r"_+", "_", name)
    return f"{name}.pdf"


def _notification_subject(firstname: str, lastname: str) -> str:
    full_name = f"{firstname} {lastname}".strip() or "(unbekannt)"
    return f"Neues Badge erstellt für: {full_name}"


def _notification_html_body(firstname: str, lastname: str) -> str:
    subject = _html_mod.escape(_notification_subject(firstname, lastname))
    return (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;">'
        f"<p>{subject}</p>"
        "<p>Das Badge ist als PDF angehängt.</p>"
        "</div>"
    )


def build_badge_mails(
    df_out: pd.DataFrame,
    subject_tpl: str,
    body_text: str,
    sig_html: str,
    tpl_map: dict,
    *,
    uppercase_names: bool = True,
    uppercase_company: bool = True,
    colored_qr: bool = False,
) -> tuple[list[SerienMail], list[dict]]:
    """Build one SerienMail per person with their badge PDF as attachment.

    Args:
        df_out:          Filtered badge DataFrame (must have columns from hubspot_search).
        subject_tpl:     Subject template (supports {vorname}, {firma}, {email}).
        body_text:       Plain-text body (supports {vorname}, {firma}, {email}).
        sig_html:        HTML signature (empty string = no signature).
        tpl_map:         Category → template-image-path dict (same as used for PDF generation).
        uppercase_names: Passed through to render_badges_pdf_bytes.
        uppercase_company: Passed through to render_badges_pdf_bytes.
        colored_qr:      Passed through to render_badges_pdf_bytes.

    Returns:
        (mails, skipped)
        mails:   list[SerienMail] ready for create_serienmailing_drafts
        skipped: list[dict] with keys 'name', 'email', 'reason' for each skipped contact
    """
    mails: list[SerienMail] = []
    skipped: list[dict] = []

    for _, row in df_out.iterrows():
        row_dict = row.to_dict()
        firstname = (row_dict.get("firstname") or "").strip()
        lastname  = (row_dict.get("lastname")  or "").strip()
        name      = f"{firstname} {lastname}".strip() or "(unbekannt)"
        email     = (row_dict.get("email")     or "").strip()
        company   = (row_dict.get("company")   or "").strip()
        kategorie = (row_dict.get("kategorie") or "").strip()

        if not email:
            skipped.append({"name": name, "email": "", "reason": "Keine E-Mail-Adresse vorhanden"})
            continue

        if not kategorie or kategorie not in tpl_map:
            skipped.append({
                "name": name,
                "email": email,
                "reason": f"Kategorie \"{kategorie}\" hat kein Badge-Template",
            })
            continue

        pdf_bytes = render_badges_pdf_bytes(
            rows=[row_dict],
            template_by_category=tpl_map,
            uppercase_names=uppercase_names,
            uppercase_company=uppercase_company,
            colored_qr=colored_qr,
        )

        mails.append(SerienMail(
            to_email=email,
            vorname=firstname,
            firma=company,
            subject=build_subject(subject_tpl, firstname, company, email),
            html_body=build_html_body(firstname, body_text, sig_html, company, email),
            attachment_bytes=pdf_bytes,
            attachment_filename=_safe_filename(firstname, lastname),
        ))

    return mails, skipped


def build_badge_notification_mails(
    df_out: pd.DataFrame,
    recipient_email: str,
    tpl_map: dict,
    *,
    uppercase_names: bool = True,
    uppercase_company: bool = True,
    colored_qr: bool = False,
) -> tuple[list[SerienMail], list[dict]]:
    """Build one notification draft per person with their badge PDF as attachment."""
    mails: list[SerienMail] = []
    skipped: list[dict] = []
    recipient_email = (recipient_email or "").strip()

    for _, row in df_out.iterrows():
        row_dict = row.to_dict()
        firstname = (row_dict.get("firstname") or "").strip()
        lastname = (row_dict.get("lastname") or "").strip()
        name = f"{firstname} {lastname}".strip() or "(unbekannt)"
        company = (row_dict.get("company") or "").strip()
        kategorie = (row_dict.get("kategorie") or "").strip()

        if not kategorie or kategorie not in tpl_map:
            skipped.append({
                "name": name,
                "email": recipient_email,
                "reason": f"Kategorie \"{kategorie}\" hat kein Badge-Template",
            })
            continue

        pdf_bytes = render_badges_pdf_bytes(
            rows=[row_dict],
            template_by_category=tpl_map,
            uppercase_names=uppercase_names,
            uppercase_company=uppercase_company,
            colored_qr=colored_qr,
        )

        mails.append(SerienMail(
            to_email=recipient_email,
            vorname=name,
            firma=company,
            subject=_notification_subject(firstname, lastname),
            html_body=_notification_html_body(firstname, lastname),
            attachment_bytes=pdf_bytes,
            attachment_filename=_safe_filename(firstname, lastname),
        ))

    return mails, skipped
