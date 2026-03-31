# serienmailing/mail_builder.py

from __future__ import annotations

import html as _html_mod
import re
from html import unescape as _unescape

def html_to_plain_text(html_body: str) -> str:
    """Convert an HTML email body to a plain-text fallback.

    Removes script/style blocks, converts <br> and </p> to newlines,
    strips remaining tags, unescapes HTML entities, and collapses excess blank lines.
    """
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html_body)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?s)<.*?>", "", text)
    text = _unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "Please use an HTML-capable email client."


SENDER_EMAIL_SUGGESTIONS: list[str] = [
    "severin.wagner@mysecurityevent.de",
    "alexander.christoph@mysecurityevent.de",
    "arya.ghaderi@mysecurityevent.de",
    "luisa.lutzenburg@mysecurityevent.de",
    "marc.plewnia@mysecurityevent.de",
    "melvyn.kraeusel@mysecurityevent.de",
    "milena.rusczyk@mysecurityevent.de",
    "robert.duske@mysecurityevent.de",
]


SIGNATURE_SEVERIN_HTML: str = (
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '<b><span style="color:#212121;">Severin Wagner | Operations Manager</span></b></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">&nbsp;</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '<a href="tel:+491793922128" style="color:#0078D4;">+49 179 3922 128</a></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    '<br>mysecurityevent GmbH</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    'Office: Novalisstra\u00dfe 11</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '10115 Berlin\u00a0|\u00a0<a href="tel:+493052284088" style="color:#0078D4;">+49 30 52284088</a></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    'Amtsgericht Charlottenburg | HRB244080B</p>'
)


def build_html_body(vorname: str, text: str, signature_html: str, firma: str = "", email: str = "") -> str:
    """Build personalized HTML email body.

    Placeholders {vorname}, {firma}, {email} in `text` are replaced before HTML-escaping.

    Structure:
        {text — plain text, newlines → <br>}
        Beste Grüße,
        [signature_html, only if signature_html is non-empty]
    """
    # Replace placeholders first, then escape and convert newlines
    personalized = text.replace("{vorname}", vorname).replace("{firma}", firma).replace("{email}", email)
    escaped_text = _html_mod.escape(personalized).replace("\n", "<br>\n")

    sig_block = f"{signature_html}" if signature_html.strip() else ""

    body = (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;">'
        f"<p>{escaped_text}</p>"
        "<p>Beste Grüße,</p>"
        f"{sig_block}"
        "</div>"
    )
    return body


def build_subject(template: str, vorname: str, firma: str, email: str = "") -> str:
    """Replace {vorname}, {firma} and {email} placeholders in subject template."""
    return (
        template
        .replace("{vorname}", vorname)
        .replace("{firma}", firma)
        .replace("{email}", email)
    )
