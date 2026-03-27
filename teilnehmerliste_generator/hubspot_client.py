from __future__ import annotations

import streamlit as st

from shared.hubspot import (
    get_contact_lists as _get_contact_lists,
    get_contacts_by_ids as _get_contacts_by_ids,
    get_list_members as _get_list_members,
)


def get_contact_lists(count: int = 500) -> list[dict]:
    return _get_contact_lists(secrets=st.secrets, count=count)


def get_list_members(list_id: str) -> list[str]:
    return _get_list_members(list_id, secrets=st.secrets)


def get_contacts_by_ids(ids: list[str], properties: list[str]) -> list[dict]:
    return _get_contacts_by_ids(ids, properties, secrets=st.secrets)
