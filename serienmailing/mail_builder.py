# serienmailing/mail_builder.py

from __future__ import annotations

import html as _html_mod
import re
from html import unescape as _unescape

from shared.mail_signatures import SIGNATURE_SEVERIN_HTML


def html_to_plain_text(html_body: str) -> str:
    """Convert an HTML email body to a plain-text fallback."""
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

def build_html_body(
    vorname: str,
    text: str,
    signature_html: str,
    firma: str = "",
    email: str = "",
    closing_text: str | None = "Beste Gr\u00fc\u00dfe,",
) -> str:
    """Build a personalized HTML email body with an optional closing line."""
    personalized = text.replace("{vorname}", vorname).replace("{firma}", firma).replace("{email}", email)
    escaped_text = _html_mod.escape(personalized).replace("\n", "<br>\n")

    sig_block = f"{signature_html}" if signature_html.strip() else ""
    closing_block = ""
    if closing_text is not None and closing_text.strip():
        escaped_closing = _html_mod.escape(closing_text).replace("\n", "<br>\n")
        closing_block = f"<p>{escaped_closing}</p>"

    body = (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;">'
        f"<p>{escaped_text}</p>"
        f"{closing_block}"
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
