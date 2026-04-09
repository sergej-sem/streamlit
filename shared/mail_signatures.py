from __future__ import annotations

SIGNATURE_SEVERIN_HTML: str = (
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '<b><span style="color:#212121;">Severin Wagner | Operations Manager</span></b></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">&nbsp;</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '<a href="tel:+491793922128" style="color:#0078D4;">+49 179 3922 128</a></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    '<br>mysecurityevent GmbH</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    'Office: Novalisstraße 11</p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;">'
    '10115 Berlin&nbsp;|&nbsp;<a href="tel:+493052284088" style="color:#0078D4;">+49 30 52284088</a></p>'
    '<p style="font-family:Calibri,Arial,sans-serif;font-size:11pt;margin:0;color:#212121;">'
    'Amtsgericht Charlottenburg | HRB244080B</p>'
)

_SIGNATURES_BY_SENDER: dict[str, str] = {
    "severin.wagner@mysecurityevent.de": SIGNATURE_SEVERIN_HTML,
}


def signature_html_for_sender(sender_email: str) -> str:
    return _SIGNATURES_BY_SENDER.get((sender_email or "").strip().lower(), "")


def known_signature_html_values() -> tuple[str, ...]:
    seen: set[str] = set()
    values: list[str] = []
    for signature_html in _SIGNATURES_BY_SENDER.values():
        if not signature_html.strip() or signature_html in seen:
            continue
        seen.add(signature_html)
        values.append(signature_html)
    return tuple(values)
