from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import msal
import pandas as pd
import requests

from .core import GeneratedMail


GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class GraphDraftConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox_user: str


@dataclass(frozen=True)
class GraphDraftRecord:
    row_number: int
    sponsor_name: str
    to_email: str
    cc_email: str
    subject: str
    mailbox_user: str
    result: str
    details: str
    message_id: str
    web_link: str


def _get_access_token(config: GraphDraftConfig) -> str:
    authority = f"https://login.microsoftonline.com/{config.tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=config.client_id,
        authority=authority,
        client_credential=config.client_secret,
    )
    result = app.acquire_token_silent(GRAPH_SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    token = result.get("access_token")
    if token:
        return token
    raise RuntimeError(
        f"Graph-Token konnte nicht abgerufen werden: {result.get('error')} - {result.get('error_description')}"
    )


def _recipient(address: str) -> dict:
    return {"emailAddress": {"address": address}}


def _build_payload(mail: GeneratedMail) -> dict:
    payload = {
        "subject": mail.subject,
        "body": {
            "contentType": "HTML",
            "content": mail.html_body,
        },
        "toRecipients": [_recipient(mail.to_email)],
    }
    if mail.cc_email:
        payload["ccRecipients"] = [_recipient(mail.cc_email)]
    return payload


def create_graph_drafts(
    mails: list[GeneratedMail],
    config: GraphDraftConfig,
) -> list[GraphDraftRecord]:
    if not config.mailbox_user.strip():
        raise ValueError("mailbox_user darf nicht leer sein")

    token = _get_access_token(config)
    mailbox = quote(config.mailbox_user.strip(), safe="@._-")
    url = f"{GRAPH_BASE_URL}/users/{mailbox}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    records: list[GraphDraftRecord] = []
    for mail in mails:
        try:
            response = requests.post(
                url,
                headers=headers,
                json=_build_payload(mail),
                timeout=60,
            )
            if response.status_code != 201:
                try:
                    payload = response.json()
                except Exception:
                    payload = response.text
                raise RuntimeError(f"{response.status_code} {response.reason}: {payload}")

            data = response.json()
            records.append(
                GraphDraftRecord(
                    row_number=mail.row_number,
                    sponsor_name=mail.sponsor_name,
                    to_email=mail.to_email,
                    cc_email=mail.cc_email,
                    subject=mail.subject,
                    mailbox_user=config.mailbox_user,
                    result="draft_created",
                    details="",
                    message_id=str(data.get("id", "")),
                    web_link=str(data.get("webLink", "")),
                )
            )
        except Exception as exc:
            records.append(
                GraphDraftRecord(
                    row_number=mail.row_number,
                    sponsor_name=mail.sponsor_name,
                    to_email=mail.to_email,
                    cc_email=mail.cc_email,
                    subject=mail.subject,
                    mailbox_user=config.mailbox_user,
                    result="error",
                    details=str(exc),
                    message_id="",
                    web_link="",
                )
            )

    return records


def build_graph_draft_log_dataframe(records: list[GraphDraftRecord]) -> pd.DataFrame:
    rows = [
        {
            "Sponsor": record.sponsor_name,
            "To": record.to_email,
            "CC": record.cc_email,
            "Postfach": record.mailbox_user,
            "Ergebnis": record.result,
            "Details": record.details,
            "Message ID": record.message_id,
            "Web Link": record.web_link,
        }
        for record in records
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "Sponsor",
            "To",
            "CC",
            "Postfach",
            "Ergebnis",
            "Details",
            "Message ID",
            "Web Link",
        ],
    )
