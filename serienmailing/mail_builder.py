# serienmailing/mail_builder.py

from __future__ import annotations

import html as _html_mod

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


def build_html_body(vorname: str, text: str, signature_html: str) -> str:
    """Build personalized HTML email body.

    Structure:
        Hallo {vorname},
        <blank line>
        {text — plain text, newlines → <br>}
        <hr>
        {signature_html}
    """
    greeting = f"Hallo {_html_mod.escape(vorname)},"

    # Escape text content, then convert newlines to <br>
    escaped_text = _html_mod.escape(text).replace("\n", "<br>\n")

    body = (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;">'
        f"<p>{greeting}</p>"
        f"<p>{escaped_text}</p>"
        "<hr>"
        f"{signature_html}"
        "</div>"
    )
    return body


def build_subject(template: str, vorname: str, firma: str) -> str:
    """Replace {vorname} and {firma} placeholders in subject template."""
    return template.replace("{vorname}", vorname).replace("{firma}", firma)
