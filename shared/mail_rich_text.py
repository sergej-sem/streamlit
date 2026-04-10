from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping

try:
    import bleach
    from bleach.css_sanitizer import CSSSanitizer
except ModuleNotFoundError:
    bleach = None
    CSSSanitizer = None

from serienmailing.mail_builder import html_to_plain_text
from shared.mail_signatures import known_signature_html_values, signature_html_for_sender

_DEFAULT_BODY_TEXT = "\n\nBeste Grüße,"
_DEFAULT_EDITOR_HTML = "<p><br></p><p><br></p><p>Beste Grüße,</p>"
_ALLOWED_TAGS = [
    "div",
    "p",
    "br",
    "strong",
    "em",
    "u",
    "span",
    "a",
    "ol",
    "ul",
    "li",
]
_ALLOWED_ATTRIBUTES = {
    "*": ["style"],
    "a": ["href", "title", "target", "rel"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]
_CSS_SANITIZER = (
    CSSSanitizer(
        allowed_css_properties=[
            "background-color",
            "color",
            "font-family",
            "font-size",
            "font-style",
            "font-weight",
            "text-decoration",
        ]
    )
    if CSSSanitizer is not None
    else None
)
_FONT_STYLE_MAP = {
    "ql-font-serif": "font-family: Georgia, 'Times New Roman', serif",
    "ql-font-monospace": "font-family: Consolas, 'Courier New', monospace",
}
_SIZE_STYLE_MAP = {
    "ql-size-small": "font-size: 0.85em",
    "ql-size-large": "font-size: 1.25em",
    "ql-size-huge": "font-size: 1.75em",
}
_QUILL_TOOLBAR = [
    [{"font": ["", "serif", "monospace"]}, {"size": ["small", False, "large", "huge"]}],
    ["bold", "italic", "underline", "link"],
    [{"color": []}, {"background": []}],
    ["clean"],
]
_QUILL_HISTORY = {
    "delay": 250,
    "maxStack": 100,
    "userOnly": True,
}
_QUILL_UI_BRIDGE_STYLE = """
.ql-snow .ql-picker.ql-font {
  width: 122px !important;
}
.ql-snow .ql-picker.ql-font .ql-picker-label::before,
.ql-snow .ql-picker.ql-font .ql-picker-item::before {
  content: 'Serifenlos' !important;
}
.ql-snow .ql-picker.ql-font .ql-picker-label[data-value=serif]::before,
.ql-snow .ql-picker.ql-font .ql-picker-item[data-value=serif]::before {
  content: 'Serif' !important;
}
.ql-snow .ql-picker.ql-font .ql-picker-label[data-value=monospace]::before,
.ql-snow .ql-picker.ql-font .ql-picker-item[data-value=monospace]::before {
  content: 'Monoschrift' !important;
}
.ql-snow .ql-picker.ql-size .ql-picker-label::before,
.ql-snow .ql-picker.ql-size .ql-picker-item::before {
  content: 'Normal' !important;
}
.ql-snow .ql-picker.ql-size .ql-picker-label[data-value=small]::before,
.ql-snow .ql-picker.ql-size .ql-picker-item[data-value=small]::before {
  content: 'Klein' !important;
}
.ql-snow .ql-picker.ql-size .ql-picker-label[data-value=large]::before,
.ql-snow .ql-picker.ql-size .ql-picker-item[data-value=large]::before {
  content: 'Groß' !important;
}
.ql-snow .ql-picker.ql-size .ql-picker-label[data-value=huge]::before,
.ql-snow .ql-picker.ql-size .ql-picker-item[data-value=huge]::before {
  content: 'Riesig' !important;
}
.ql-snow .ql-tooltip::before {
  content: 'Link öffnen:' !important;
}
.ql-snow .ql-tooltip a.ql-action::after {
  content: 'Bearbeiten' !important;
}
.ql-snow .ql-tooltip a.ql-remove::before {
  content: 'Entfernen' !important;
}
.ql-snow .ql-tooltip.ql-editing a.ql-action::after {
  content: 'Speichern' !important;
}
.ql-snow .ql-tooltip[data-mode=link]::before {
  content: 'Link eingeben:' !important;
}
"""


def _quill_ui_bridge_html() -> str:
    return f"""
<script>
(function() {{
  const styleId = "mse-quill-de-style";
  const observerFlag = "__mseQuillUiObserver";
  const urlPattern = /^(https?:\\/\\/|mailto:|tel:)/i;
  const styleText = {json.dumps(_QUILL_UI_BRIDGE_STYLE, ensure_ascii=False)};

  function isUrlLike(value) {{
    return urlPattern.test(String(value || "").trim());
  }}

  function clearNonUrlPrefill(input) {{
    if (!input) {{
      return;
    }}
    const trimmed = String(input.value || "").trim();
    const lastCheckedValue = input.getAttribute("data-mse-last-checked-value") || "";
    if (lastCheckedValue === trimmed) {{
      return;
    }}
    input.setAttribute("data-mse-last-checked-value", trimmed);
    if (trimmed && !isUrlLike(trimmed)) {{
      input.value = "";
      input.setAttribute("data-mse-last-checked-value", "");
      input.dispatchEvent(new Event("input", {{ bubbles: true }}));
      input.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }}
    input.focus();
    if (typeof input.setSelectionRange === "function") {{
      input.setSelectionRange(0, 0);
    }}
  }}

  function scheduleLinkInputChecks(input) {{
    clearNonUrlPrefill(input);
    window.requestAnimationFrame(function() {{
      clearNonUrlPrefill(input);
    }});
    window.setTimeout(function() {{
      clearNonUrlPrefill(input);
    }}, 0);
    window.setTimeout(function() {{
      clearNonUrlPrefill(input);
    }}, 60);
  }}

  function installLinkHandlerOverride(doc) {{
    doc.querySelectorAll(".ql-container").forEach(function(container) {{
      const quill = container && container.__quill;
      if (!quill || quill.__mseLinkHandlerPatched) {{
        return;
      }}
      const toolbar = typeof quill.getModule === "function" ? quill.getModule("toolbar") : null;
      const tooltip = quill.theme && quill.theme.tooltip;
      if (!toolbar || typeof toolbar.addHandler !== "function" || !tooltip || typeof tooltip.edit !== "function") {{
        return;
      }}

      toolbar.addHandler("link", function(value) {{
        if (!value) {{
          quill.format("link", false);
          return;
        }}

        const range = quill.getSelection();
        if (range == null || range.length === 0) {{
          return;
        }}

        let existingLink = "";
        if (typeof quill.getFormat === "function") {{
          const formats = quill.getFormat(range);
          if (formats && typeof formats.link === "string") {{
            existingLink = formats.link;
          }}
        }}

        tooltip.edit("link", existingLink || "");
      }});

      quill.__mseLinkHandlerPatched = true;
    }});
  }}

  function syncLinkTooltip(doc) {{
    const tooltip = doc.querySelector(".ql-tooltip[data-mode='link']");
    if (!tooltip) {{
      return;
    }}
    const isEditing = tooltip.classList.contains("ql-editing");
    const wasEditing = tooltip.getAttribute("data-mse-link-editing") === "true";
    tooltip.setAttribute("data-mse-link-editing", isEditing ? "true" : "false");
    if (!isEditing) {{
      return;
    }}
    const input = tooltip.querySelector("input[type='text']");
    if (!input) {{
      return;
    }}
    if (!input.getAttribute("data-mse-input-observed")) {{
      input.setAttribute("data-mse-input-observed", "true");
      input.addEventListener("input", function() {{
        clearNonUrlPrefill(input);
      }});
    }}
    clearNonUrlPrefill(input);
    if (!wasEditing) {{
      scheduleLinkInputChecks(input);
    }}
  }}

  function installBridge(doc) {{
    if (!doc || !doc.head || !doc.body) {{
      return;
    }}
    if (!doc.querySelector(".ql-toolbar, .ql-container, .ql-editor")) {{
      return;
    }}
    if (!doc.getElementById(styleId)) {{
      const style = doc.createElement("style");
      style.id = styleId;
      style.textContent = styleText;
      doc.head.appendChild(style);
    }}
    installLinkHandlerOverride(doc);
    syncLinkTooltip(doc);
    const view = doc.defaultView;
    if (!view || view[observerFlag]) {{
      return;
    }}
    const observer = new MutationObserver(function() {{
      syncLinkTooltip(doc);
    }});
    observer.observe(doc.body, {{
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class", "data-mode"],
    }});
    view[observerFlag] = observer;
  }}

  function scanQuillFrames() {{
    const parentDoc = window.parent && window.parent.document;
    if (!parentDoc) {{
      return;
    }}
    parentDoc.querySelectorAll("iframe").forEach(function(frame) {{
      try {{
        installBridge(frame.contentDocument);
      }} catch (error) {{
      }}
    }});
  }}

  scanQuillFrames();
  const intervalId = window.setInterval(scanQuillFrames, 400);
  window.addEventListener("beforeunload", function() {{
    window.clearInterval(intervalId);
  }});
}})();
</script>
"""


def _render_quill_ui_bridge() -> None:
    import streamlit.components.v1 as components

    components.html(_quill_ui_bridge_html(), height=0, width=0)


def default_mail_body_text() -> str:
    return _DEFAULT_BODY_TEXT


def default_mail_body_html() -> str:
    return _DEFAULT_EDITOR_HTML


def quill_toolbar_config() -> list:
    return _QUILL_TOOLBAR


def quill_history_config() -> dict[str, int | bool]:
    return _QUILL_HISTORY


def _rich_text_widget_key(key: str) -> str:
    return f"{key}__widget"


def _rich_text_fallback_widget_key(key: str) -> str:
    return f"{key}__fallback_text"


def render_mail_rich_text_editor(
    *,
    label: str,
    key: str,
    placeholder: str = "",
    value: str = "",
) -> str:
    storage_value = str(value or "")
    try:
        from streamlit_quill import st_quill
    except ModuleNotFoundError:
        import streamlit as st

        st.caption("Rich-Text-Editor nicht verfügbar. Das Feld läuft vorübergehend im Textmodus.")
        fallback_key = _rich_text_fallback_widget_key(key)
        if fallback_key not in st.session_state:
            st.session_state[fallback_key] = _extract_editor_text(storage_value)
        text_result = st.text_area(
            label,
            value=st.session_state[fallback_key],
            placeholder=placeholder,
            key=fallback_key,
        )
        html_result = "<p><br></p>" if not str(text_result or "").strip() else plain_text_to_editor_html(text_result)
        st.session_state[key] = html_result
        return html_result

    import streamlit as st

    widget_key = _rich_text_widget_key(key)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = storage_value

    result = st_quill(
        value=st.session_state[widget_key],
        placeholder=placeholder,
        html=True,
        toolbar=quill_toolbar_config(),
        history=quill_history_config(),
        preserve_whitespace=True,
        key=widget_key,
    )
    _render_quill_ui_bridge()
    html_result = storage_value if result is None else str(result)
    st.session_state[key] = html_result
    return html_result


def _normalize_editor_html(value: str | None) -> str:
    return str(value or "").strip()


def editor_html_is_meaningful(value: str | None) -> bool:
    return bool(_extract_editor_text(value))


def _fallback_html_to_text(value: str | None) -> str:
    normalized = _normalize_editor_html(value)
    if not normalized:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", normalized)
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|li|ul|ol)>", "\n", text)
    text = re.sub(r"(?i)<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_editor_text(value: str | None) -> str:
    normalized = _normalize_editor_html(value)
    if not normalized:
        return ""
    if bleach is None:
        return _fallback_html_to_text(normalized)

    text_only = bleach.clean(normalized, tags=[], attributes={}, strip=True)
    text_only = html.unescape(text_only).replace("\xa0", " ")
    text_only = re.sub(r"\s+", " ", text_only).strip()
    return text_only


def plain_text_to_editor_html(text: str) -> str:
    normalized = str(text or "")
    if not normalized.strip():
        return default_mail_body_html()
    lines = normalized.splitlines()
    paragraphs = []
    for line in lines:
        if line.strip():
            paragraphs.append(f"<p>{html.escape(line)}</p>")
        else:
            paragraphs.append("<p><br></p>")
    return "".join(paragraphs)


def _replace_placeholders(template_html: str, values: Mapping[str, str]) -> str:
    result = template_html
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", html.escape(value or ""))
    return result


def _style_map_for_classes(classes: list[str]) -> list[str]:
    styles: list[str] = []
    for class_name in classes:
        if class_name in _FONT_STYLE_MAP:
            styles.append(_FONT_STYLE_MAP[class_name])
        if class_name in _SIZE_STYLE_MAP:
            styles.append(_SIZE_STYLE_MAP[class_name])
    return styles


def _merge_style_parts(existing_style: str, new_styles: list[str]) -> str:
    parts = [item.strip().rstrip(";") for item in existing_style.split(";") if item.strip()]
    parts.extend(item.strip().rstrip(";") for item in new_styles if item.strip())
    return "; ".join(dict.fromkeys(parts))


def _inline_known_quill_classes(value: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        tag_name = match.group("tag")
        before = match.group("before") or ""
        class_text = match.group("class_text") or ""
        after = match.group("after") or ""
        classes = [item for item in class_text.split() if item]
        styles = _style_map_for_classes(classes)
        cleaned_classes = [
            class_name
            for class_name in classes
            if class_name not in _FONT_STYLE_MAP and class_name not in _SIZE_STYLE_MAP
        ]

        style_match = re.search(r'style="([^"]*)"', before + after)
        existing_style = style_match.group(1) if style_match else ""
        merged_style = _merge_style_parts(existing_style, styles)

        attrs = re.sub(r'\sstyle="[^"]*"', "", before + after)
        attrs = re.sub(r'\sclass="[^"]*"', "", attrs)
        if cleaned_classes:
            attrs = f'{attrs} class="{" ".join(cleaned_classes)}"'
        if merged_style:
            attrs = f'{attrs} style="{merged_style}"'
        return f"<{tag_name}{attrs}>"

    pattern = re.compile(
        r"<(?P<tag>div|p|span)(?P<before>[^>]*)\sclass=\"(?P<class_text>[^\"]+)\"(?P<after>[^>]*)>",
        re.IGNORECASE,
    )
    return pattern.sub(_rewrite, value)


def sanitize_editor_html(value: str | None) -> str:
    normalized = _normalize_editor_html(value)
    if not normalized:
        normalized = "<p><br></p>"
    inlined = _inline_known_quill_classes(normalized)
    if bleach is None:
        fallback_text = _fallback_html_to_text(inlined)
        return "<p><br></p>" if not fallback_text else plain_text_to_editor_html(fallback_text)
    cleaned = bleach.clean(
        inlined,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        css_sanitizer=_CSS_SANITIZER,
    )
    return cleaned or "<p><br></p>"


def _normalize_mail_block_spacing(value: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        tag_name = match.group("tag")
        attrs = match.group("attrs") or ""
        style_match = re.search(r'\sstyle="([^"]*)"', attrs)
        existing_style = style_match.group(1) if style_match else ""
        merged_style = _merge_style_parts(existing_style, ["margin:0", "line-height:inherit"])
        attrs_without_style = re.sub(r'\sstyle="[^"]*"', "", attrs)
        return f'<{tag_name}{attrs_without_style} style="{merged_style}">'

    return re.sub(
        r"<(?P<tag>p|div)(?P<attrs>[^>]*)>",
        _rewrite,
        value,
        flags=re.IGNORECASE,
    )


def render_personalized_rich_text_html(
    template_html: str | None,
    *,
    vorname: str = "",
    firma: str = "",
    email: str = "",
) -> str:
    template = sanitize_editor_html(template_html)
    personalized = _replace_placeholders(
        template,
        {
            "vorname": vorname,
            "firma": firma,
            "email": email,
        },
    )
    cleaned = _normalize_mail_block_spacing(sanitize_editor_html(personalized))
    return (
        '<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.5;">'
        f"{cleaned}"
        "</div>"
    )


def _normalized_html_fragment(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _normalized_text_fragment(value: str | None) -> str:
    return re.sub(r"\s+", " ", html_to_plain_text(str(value or ""))).strip()


def _body_contains_html_fragment(body_html: str | None, fragment_html: str | None) -> bool:
    normalized_fragment = _normalized_html_fragment(fragment_html)
    normalized_body = _normalized_html_fragment(body_html)
    if normalized_fragment and normalized_fragment in normalized_body:
        return True

    text_fragment = _normalized_text_fragment(fragment_html)
    if not text_fragment:
        return False
    return text_fragment in _normalized_text_fragment(body_html)


def _choose_signature_html(
    *,
    body_html: str,
    sender_email: str,
    explicit_signature_html: str,
) -> str:
    explicit_signature = str(explicit_signature_html or "").strip()
    default_signature = signature_html_for_sender(sender_email)
    chosen_signature = explicit_signature or default_signature
    if not chosen_signature:
        return ""
    if _body_contains_html_fragment(body_html, chosen_signature):
        return ""
    if explicit_signature and _body_contains_html_fragment(body_html, explicit_signature):
        return ""
    if any(_body_contains_html_fragment(body_html, known_signature) for known_signature in known_signature_html_values()):
        return ""
    return chosen_signature


def _append_signature_block(body_html: str, signature_html: str) -> str:
    if not signature_html.strip():
        return body_html

    signature_block = f'<div style="margin-top:16px;">{signature_html}</div>'
    if body_html.rstrip().endswith("</div>"):
        return f"{body_html.rstrip()[:-6]}{signature_block}</div>"
    return body_html + signature_block


def render_final_mail_html(
    template_html: str | None,
    *,
    sender_email: str = "",
    explicit_signature_html: str = "",
    vorname: str = "",
    firma: str = "",
    email: str = "",
) -> str:
    personalized_body = render_personalized_rich_text_html(
        template_html,
        vorname=vorname,
        firma=firma,
        email=email,
    )
    signature_html = _choose_signature_html(
        body_html=personalized_body,
        sender_email=sender_email,
        explicit_signature_html=explicit_signature_html,
    )
    return _append_signature_block(personalized_body, signature_html)
