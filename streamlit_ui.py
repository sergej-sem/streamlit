from __future__ import annotations

import html
from typing import Callable, Sequence

import streamlit as st

from shared.email_input import build_email_select_options, normalize_email_widget_value


_PAGE_TITLE_CSS = """
<style>
  div.block-container { padding-top: 2.2rem; }
  .page-title {
    font-size: 1.35rem;
    font-weight: 700;
    margin: 1.1rem 0 0.6rem 0;
  }
</style>
"""


def apply_page_title_style() -> None:
    st.markdown(_PAGE_TITLE_CSS, unsafe_allow_html=True)


def page_title_html(title: str) -> str:
    return f"<div class='page-title'>{html.escape(title)}</div>"


def render_page_title(title: str) -> None:
    apply_page_title_style()
    st.markdown(page_title_html(title), unsafe_allow_html=True)


def render_email_selectbox(
    label: str,
    *,
    key: str,
    suggestions: Sequence[str],
    placeholder: str = "",
    help: str | None = None,
    on_change: Callable[[], None] | None = None,
) -> str:
    raw_state = st.session_state.get(key)
    normalized_state = normalize_email_widget_value(raw_state)
    if raw_state is not None and raw_state != normalized_state:
        st.session_state[key] = normalized_state

    value = st.selectbox(
        label,
        options=build_email_select_options(suggestions, normalized_state),
        index=None,
        key=key,
        placeholder=placeholder,
        accept_new_options=True,
        help=help,
        on_change=on_change,
    )
    return normalize_email_widget_value(value)
