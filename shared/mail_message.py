from __future__ import annotations

from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid

from serienmailing.mail_builder import html_to_plain_text

_MIME_MAP = {
    "pdf": ("application", "pdf"),
    "png": ("image", "png"),
    "jpg": ("image", "jpeg"),
    "jpeg": ("image", "jpeg"),
    "xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


def _attachment_mime_type(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_MAP.get(ext, ("application", "octet-stream"))


def build_email_message(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str | None = None,
    cc_email: str = "",
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    if cc_email.strip():
        message["Cc"] = cc_email.strip()
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()

    message.set_content(plain_body or html_to_plain_text(html_body))
    message.add_alternative(html_body, subtype="html")

    if attachment_bytes and attachment_filename:
        maintype, subtype = _attachment_mime_type(attachment_filename)
        message.add_attachment(
            attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=attachment_filename,
        )

    return message


def build_email_message_bytes(**kwargs) -> bytes:
    return build_email_message(**kwargs).as_bytes(policy=SMTP)
