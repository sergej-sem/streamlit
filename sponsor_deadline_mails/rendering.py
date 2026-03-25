from __future__ import annotations

import html
from datetime import date
from typing import Iterable

import pandas as pd


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
    "green": "Bereits erhalten",
    "red": "Handlungsbedarf",
    "yellow": "Ausstehend",
    "white": "Zu empfehlen",
}
STATUS_LABEL_EN = {
    "green": "Already received",
    "red": "Action required",
    "yellow": "Pending",
    "white": "Recommended",
}
HTML_FONT_FAMILY = "Calibri, Arial, Helvetica, sans-serif"
HTML_FONT_SIZE = "11pt"
HTML_BASE_STYLE = f"font-family:{HTML_FONT_FAMILY}; font-size:{HTML_FONT_SIZE};"
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


def _colored_status_word(word: str, status: str) -> str:
    return (
        f'<span style="{HTML_BASE_STYLE} color:{COLOR_TEXT[status]}; font-weight:700;">'
        f"{html.escape(word)}</span>"
    )


def build_subject(language: str, sponsor_name: str) -> str:
    if language == "EN":
        return f"Important Information // mysecurityevent // Deadlines // {sponsor_name}"
    return f"Wichtige Informationen // mysecurityevent // Deadlines // {sponsor_name}"


def format_event_date(value: date, language: str) -> str:
    return value.strftime("%d/%m/%Y") if language == "EN" else value.strftime("%d.%m.%Y")


def build_intro(
    sponsor,
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
            "heute sende ich Dir einen Reminder für die anstehenden Deadlines des mysecurityevent in "
            f"{html.escape(event_city)} vom {html.escape(start_text)} bis zum {html.escape(end_text)}."
        )
        explainer = (
            "Du findest hier eine Übersicht aller Unterlagen, die ich in der Eventvorbereitung noch von Dir benötige. "
            "Bitte beachte unbedingt die entsprechenden Deadlines für eine optimale Vorbereitung und ein erfolgreiches Event."
        )

    return salutation, intro, explainer


def legend_html(language: str) -> str:
    if language == "EN":
        lines = [
            (
                f'All items marked in {_colored_status_word("green", "green")} require no further action, '
                "as the necessary information or documents have already been received."
            ),
            f'All items marked in {_colored_status_word("red", "red")} require your action.',
            (
                f'Items marked in {_colored_status_word("yellow", "yellow")} are still pending '
                "and will become relevant in the coming weeks."
            ),
            "Items marked in white are recommended for optimal event preparation.",
        ]
    else:
        lines = [
            (
                f'Bei allen {_colored_status_word("grün", "green")} markierten Punkten besteht kein Handlungsbedarf, '
                "da wir die Informationen bzw. Unterlagen bereits erhalten haben."
            ),
            f'Bei allen {_colored_status_word("rot", "red")} markierten Punkten besteht Handlungsbedarf Deinerseits.',
            (
                f'Alle {_colored_status_word("gelb", "yellow")} markierten Punkte sind noch ausstehend '
                "und werden in den kommenden Wochen relevant."
            ),
            "Alle weiß markierten Punkte sind für eine optimale Eventvorbereitung zu empfehlen.",
        ]
    return "".join(f"<li>{line}</li>" for line in lines)


def render_deadline_rows(items: Iterable, language: str) -> str:
    rows = []
    for item in items:
        due_date = item.due_date_en if language == "EN" else item.due_date_de
        text = item.text_en if language == "EN" else item.text_de
        status_label = STATUS_LABEL_EN[item.status] if language == "EN" else STATUS_LABEL_DE[item.status]
        rows.append(
            f"""
            <tr>
                <td style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top; white-space:nowrap;"><strong>{html.escape(due_date)}</strong></td>
                <td style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top;">{html.escape(text)}</td>
                <td style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; vertical-align:top;">
                    <span style="{HTML_BASE_STYLE} display:inline-block; padding:4px 10px; border-radius:999px; border:1px solid {COLOR_BORDER[item.status]}; background:{COLOR_BG[item.status]}; color:{COLOR_TEXT[item.status]}; font-weight:600;">
                        {html.escape(status_label)}
                    </span>
                </td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_html_body(
    sponsor,
    items: list,
    event_city: str,
    event_start: date,
    event_end: date,
    signature_html: str = "",
) -> str:
    salutation, intro, explainer = build_intro(sponsor, event_city, event_start, event_end)
    overview_head = "Deadline Overview" if sponsor.language == "EN" else "Deadlines auf einen Blick"
    closing_note = (
        "Please feel free to contact me if you have any questions or comments regarding the deadlines."
        if sponsor.language == "EN"
        else "Melde Dich gerne bei mir, solltest Du zu den Deadlines Fragen oder Anmerkungen haben."
    )
    footer = "Best regards," if sponsor.language == "EN" else "Beste Grüße,"
    signature_block = f'\n  <div style="margin-top:16px;">{signature_html}</div>' if signature_html else ""

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(build_subject(sponsor.language, sponsor.sponsor_name))}</title>
</head>
<body style="{HTML_BASE_STYLE} color:#222; line-height:1.5;">
  <p style="{HTML_BASE_STYLE} margin:0 0 12px 0;">{salutation}</p>
  <p style="{HTML_BASE_STYLE} margin:0 0 12px 0;">{intro}</p>
  <p style="{HTML_BASE_STYLE} margin:0 0 12px 0;">{explainer}</p>
  <ul style="{HTML_BASE_STYLE} margin:0 0 12px 20px; padding:0;">
    {legend_html(sponsor.language)}
  </ul>
  <p style="{HTML_BASE_STYLE} margin:0 0 12px 0;"><strong>{html.escape(overview_head)}</strong></p>
  <table style="{HTML_BASE_STYLE} border-collapse:collapse; width:100%; max-width:1100px;">
    <thead>
      <tr>
        <th style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">Deadline</th>
        <th style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">{'Task' if sponsor.language == 'EN' else 'Aufgabe'}</th>
        <th style="{HTML_BASE_STYLE} padding:10px 12px; border:1px solid #d9d9d9; background:#f3f3f3; text-align:left;">Status</th>
      </tr>
    </thead>
    <tbody>
      {render_deadline_rows(items, sponsor.language)}
    </tbody>
  </table>
  <p style="{HTML_BASE_STYLE} margin:12px 0 12px 0;">{html.escape(closing_note)}</p>
  <p style="{HTML_BASE_STYLE} margin:0;">{html.escape(footer)}</p>{signature_block}
</body>
</html>
""".strip()


def _summary_row_from_mail(mail) -> dict:
    return {
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


def build_summary_rows(result) -> list[dict]:
    return [_summary_row_from_mail(mail) for mail in result.mails]


def build_summary_dataframe(result) -> pd.DataFrame:
    rows = build_summary_rows(result)
    return pd.DataFrame(rows, columns=SUMMARY_FIELDNAMES)
