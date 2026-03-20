from __future__ import annotations

import html

import streamlit as st


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
