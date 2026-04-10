# serienmailing/mail_builder.py

from __future__ import annotations

import html as _html_mod
import re
from html import unescape as _unescape

from shared.mail_signatures import SIGNATURE_SEVERIN_HTML


_ANCHOR_RE = re.compile(r"(?is)<a\b(?P<attrs>[^>]*)>(?P<text>.*?)</a>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_tags_to_inline_text(html_fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html_fragment)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?s)<.*?>", "", text)
    text = _unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _extract_href(attrs: str) -> str:
    match = re.search(
        r"""(?is)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attrs or "",
    )
    if not match:
        return ""
    return _unescape(next(group for group in match.groups() if group is not None)).strip()


def _display_link_target(href: str) -> str:
    normalized = (href or "").strip()
    lower = normalized.lower()
    if lower.startswith("mailto:"):
        return normalized[7:].strip()
    if lower.startswith("tel:"):
        return normalized[4:].strip()
    return normalized


def _normalized_link_value(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", _unescape(value or "")).strip()
    lower = normalized.lower()
    if lower.startswith(("http://", "https://")):
        return normalized.rstrip("/")
    return normalized


def _anchor_to_plain_text(match: re.Match[str]) -> str:
    href = _extract_href(match.group("attrs") or "")
    label = _strip_tags_to_inline_text(match.group("text") or "")
    display_target = _display_link_target(href)

    if not href:
        return label
    if not label:
        return display_target

    if _normalized_link_value(label) == _normalized_link_value(display_target):
        return label

    return f"{label} ({display_target})"


def html_to_plain_text(html_body: str) -> str:
    """Convert an HTML email body to a plain-text fallback."""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html_body)
    text = _ANCHOR_RE.sub(_anchor_to_plain_text, text)
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
