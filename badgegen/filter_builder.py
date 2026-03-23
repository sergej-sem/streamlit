# badgegen/filter_builder.py

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import streamlit as st

from badgegen.hubspot_search import (
    P_FIRSTNAME, P_LASTNAME, P_COMPANY, P_JOBTITLE, P_HISTORIE,
    hs_post,
)

@dataclass(frozen=True)
class FieldDef:
    label: str
    property_name: str
    kind: str  # "enum" | "text"

FIELDS: List[FieldDef] = [
    FieldDef("Historie", P_HISTORIE, "enum"),
    FieldDef("Vorname", P_FIRSTNAME, "text"),
    FieldDef("Nachname", P_LASTNAME, "text"),
    FieldDef("Unternehmensname", P_COMPANY, "text"),
    FieldDef("Jobbezeichnung", P_JOBTITLE, "text"),
]

FIELD_LABELS = [f.label for f in FIELDS]
LABEL_TO_FIELD = {f.label: f for f in FIELDS}
PROP_TO_LABEL = {f.property_name: f.label for f in FIELDS}

OP_LABELS = ["enthält", "ist genau"]
HS_TO_OP = {"CONTAINS_TOKEN": "enthält", "EQ": "ist genau"}

SUGGEST_MIN_CHARS = 2
SUGGEST_LIMIT = 10
SUGGEST_CONTACTS_LIMIT = 80
SUGGEST_MAX_FILTERGROUPS = 15

def _operator_to_hubspot(op_label: str) -> str:
    return "EQ" if op_label == "ist genau" else "CONTAINS_TOKEN"

def _filter_dict(property_name: str, operator: str, value: str) -> Dict[str, str]:
    return {"propertyName": property_name, "operator": operator, "value": value}

def _as_list_values(v: Any) -> List[str]:
    if isinstance(v, list):
        out = [str(x).strip() for x in v if str(x).strip()]
        seen = set()
        return [x for x in out if not (x in seen or seen.add(x))]
    s = str(v or "").strip()
    return [s] if s else []

def _match_substring(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()

@st.cache_data(ttl=90)
def _cached_suggest_values_context(
    token: str,
    property_name: str,
    query: str,
    filter_groups_json: str,
    limit: int = SUGGEST_LIMIT,
) -> List[str]:
    q = (query or "").strip()
    if len(q) < SUGGEST_MIN_CHARS:
        return []

    try:
        context_groups = json.loads(filter_groups_json) if filter_groups_json else []
        if not isinstance(context_groups, list):
            context_groups = []
    except Exception:
        context_groups = []

    payload: Dict[str, Any] = {
        "limit": SUGGEST_CONTACTS_LIMIT,
        "properties": [property_name],
    }
    if context_groups and len(context_groups) <= SUGGEST_MAX_FILTERGROUPS:
        payload["filterGroups"] = context_groups

    try:
        data = hs_post(token, "/crm/v3/objects/contacts/search", json=payload)
    except Exception:
        return []
    results = data.get("results", []) or []

    seen = set()
    out: List[str] = []
    for r in results:
        pr = (r.get("properties") or {})
        v = (pr.get(property_name) or "").strip()
        if not v:
            continue
        if not _match_substring(v, q):
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= limit:
            break
    return out

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"

def _default_model() -> List[Dict[str, Any]]:
    gid = _new_id("g")
    fid = _new_id("f")
    return [
        {
            "id": gid,
            "filters": [
                {"id": fid, "property": P_HISTORIE, "op": "CONTAINS_TOKEN", "value": []}
            ],
        }
    ]

def ensure_filter_builder_state(state_key: str = "hs_filter_builder") -> None:
    if state_key not in st.session_state:
        st.session_state[state_key] = _default_model()

def _build_context_filter_groups_for_group(group_filters: List[Dict[str, Any]], exclude_filter_id: str) -> List[Dict[str, Any]]:
    """Build context filter groups for autofill without the active filter itself."""
    partials: List[List[Dict[str, str]]] = [[]]

    for f in group_filters:
        if f.get("id") == exclude_filter_id:
            continue
        prop = (f.get("property") or "").strip()
        op = (f.get("op") or "").strip()
        if not prop or not op:
            continue

        values = _as_list_values(f.get("value"))
        if not values:
            continue

        if len(values) == 1:
            fd = _filter_dict(prop, op, values[0])
            partials = [p + [fd] for p in partials]
        else:
            new_partials: List[List[Dict[str, str]]] = []
            for p in partials:
                for one in values:
                    new_partials.append(p + [_filter_dict(prop, op, one)])
            partials = new_partials

        if len(partials) > SUGGEST_MAX_FILTERGROUPS:
            break

    groups = [{"filters": p} for p in partials if p]
    if len(groups) > SUGGEST_MAX_FILTERGROUPS:
        return []
    return groups

def _set_flag_key(widget_key: str) -> str:
    return f"__set_next_run__:{widget_key}"

def _apply_pending_set(widget_key: str) -> None:
    flag = _set_flag_key(widget_key)
    if flag in st.session_state:
        st.session_state[widget_key] = st.session_state.pop(flag)

def _request_set_next_run(widget_key: str, value: str) -> None:
    st.session_state[_set_flag_key(widget_key)] = value

def build_compiled_groups_from_model(model: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize the UI filter model into search_compiled_groups-ready groups."""
    compiled: List[Dict[str, Any]] = []

    for g in model or []:
        base_server_filters: List[Dict[str, str]] = []
        local_contains: List[Dict[str, str]] = []

        # collect historie multi separately
        historie_values: List[str] = []
        historie_op = "CONTAINS_TOKEN"

        for f in (g.get("filters") or []):
            prop = (f.get("property") or "").strip()
            op = (f.get("op") or "").strip()
            values = _as_list_values(f.get("value"))
            if not prop or not op or not values:
                continue

            if prop == P_HISTORIE:
                historie_values = values
                historie_op = op
                continue

            # text field
            if HS_TO_OP.get(op) == "enthält":
                local_contains.append({"propertyName": prop, "value": values[0]})
            else:
                base_server_filters.append(_filter_dict(prop, op, values[0]))

        # expand historie values as OR across groups
        if historie_values and len(historie_values) > 1:
            for hv in historie_values:
                compiled.append(
                    {
                        "id": g.get("id"),
                        "server_filters": base_server_filters + [_filter_dict(P_HISTORIE, historie_op, hv)],
                        "local_contains": local_contains,
                    }
                )
        else:
            if historie_values:
                base_server_filters.append(_filter_dict(P_HISTORIE, historie_op, historie_values[0]))
            compiled.append(
                {
                    "id": g.get("id"),
                    "server_filters": base_server_filters,
                    "local_contains": local_contains,
                }
            )

    return [c for c in compiled if (c.get("server_filters") or c.get("local_contains"))]

def render_filter_builder(
    *,
    token: str,
    historie_options: List[Tuple[str, str]],
    enable_autofill: bool = True,
    state_key: str = "hs_filter_builder",
) -> List[Dict[str, Any]]:
    ensure_filter_builder_state(state_key=state_key)
    model: List[Dict[str, Any]] = st.session_state[state_key]

    label_to_hist_value = {lbl: val for (lbl, val) in (historie_options or [])}
    hist_value_to_label = {val: lbl for (lbl, val) in (historie_options or [])}
    has_hist_dropdown = bool(historie_options)

    st.markdown(
        """
        <style>
        div.sugglist button[kind="secondary"] {
            width: 100%;
            text-align: left;
            padding: 0.25rem 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for gi, g in enumerate(list(model)):
        gid = g["id"]

        header_cols = st.columns([0.75, 0.25])
        with header_cols[0]:
            st.markdown(f"**Gruppe {gi+1}**")
        with header_cols[1]:
            if len(model) > 1 and st.button("🗑️ Gruppe löschen", key=f"del_group_{gid}", use_container_width=True):
                st.session_state[state_key] = [x for x in model if x["id"] != gid]
                st.rerun()

        filters: List[Dict[str, Any]] = g.get("filters") or []
        if not filters:
            fid = _new_id("f")
            filters = [{"id": fid, "property": P_HISTORIE, "op": "CONTAINS_TOKEN", "value": []}]
            g["filters"] = filters

        for fi, f in enumerate(list(filters)):
            if fi > 0:
                st.caption("und")

            fid = f["id"]
            cols = st.columns([0.30, 0.18, 0.42, 0.10])

            current_label = PROP_TO_LABEL.get(f.get("property"), "Historie")
            with cols[0]:
                picked_label = st.selectbox("Feld", FIELD_LABELS, index=FIELD_LABELS.index(current_label) if current_label in FIELD_LABELS else 0,
                                            key=f"field_{fid}", label_visibility="collapsed")
            field_def = LABEL_TO_FIELD[picked_label]
            if f.get("property") != field_def.property_name:
                f["property"] = field_def.property_name
                f["value"] = [] if field_def.kind == "enum" else ""
                f["op"] = _operator_to_hubspot("enthält")

            current_op_label = HS_TO_OP.get(f.get("op"), "enthält")
            with cols[1]:
                op_label = st.selectbox("Operator", OP_LABELS, index=OP_LABELS.index(current_op_label) if current_op_label in OP_LABELS else 0,
                                        key=f"op_{fid}", label_visibility="collapsed")
            f["op"] = _operator_to_hubspot(op_label)

            with cols[2]:
                if field_def.kind == "enum":
                    if has_hist_dropdown:
                        options_list = [lbl for (lbl, _val) in historie_options]
                        current_vals = _as_list_values(f.get("value"))
                        current_labels = [hist_value_to_label.get(v, v) for v in current_vals]
                        picked_labels = st.multiselect("Wert", options=options_list,
                                                       default=[x for x in current_labels if x in options_list],
                                                       key=f"val_enum_{fid}", label_visibility="collapsed",
                                                       placeholder="Historie auswählen…")
                        f["value"] = [label_to_hist_value.get(lbl, lbl) for lbl in picked_labels]
                    else:
                        raw = st.text_input("Wert", value=",".join(_as_list_values(f.get("value"))), key=f"val_enum_text_{fid}",
                                            label_visibility="collapsed", placeholder="z. B. 26DOR_TN, 26DOR_REF")
                        tokens = [t.strip() for t in raw.replace("\n", ",").split(",") if t.strip()]
                        seen = set()
                        f["value"] = [t for t in tokens if not (t in seen or seen.add(t))]
                else:
                    text_key = f"val_text_{fid}"
                    _apply_pending_set(text_key)
                    if text_key not in st.session_state:
                        st.session_state[text_key] = str(f.get("value") or "")
                    st.text_input("Wert", key=text_key, label_visibility="collapsed", placeholder="Wert eingeben…")
                    typed = (st.session_state.get(text_key) or "").strip()
                    f["value"] = typed

                    if enable_autofill and len(typed) >= SUGGEST_MIN_CHARS:
                        context_groups = _build_context_filter_groups_for_group(filters, exclude_filter_id=fid)
                        context_json = json.dumps(context_groups, ensure_ascii=False, sort_keys=True)
                        suggestions = _cached_suggest_values_context(token, field_def.property_name, typed, context_json, limit=SUGGEST_LIMIT)
                    else:
                        suggestions = []

                    if suggestions:
                        st.markdown('<div class="sugglist">', unsafe_allow_html=True)
                        for i, s in enumerate(suggestions):
                            if st.button(s, key=f"suggbtn_{fid}_{i}", type="secondary", use_container_width=True):
                                _request_set_next_run(text_key, s)
                                st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)

            with cols[3]:
                if st.button("🗑️", key=f"del_filter_{fid}", help="Filter löschen"):
                    g["filters"] = [x for x in filters if x["id"] != fid]
                    st.session_state[state_key] = model
                    st.rerun()

        st.caption("und")
        if st.button("＋ Filter hinzufügen", key=f"add_filter_{gid}", use_container_width=True):
            nid = _new_id("f")
            g["filters"].append({"id": nid, "property": P_FIRSTNAME, "op": "CONTAINS_TOKEN", "value": ""})
            st.session_state[state_key] = model
            st.rerun()

        st.divider()
        if gi < len(model) - 1:
            st.caption("oder")

    add_group_cols = st.columns([0.12, 0.88])
    with add_group_cols[0]:
        st.caption("oder")
    with add_group_cols[1]:
        if st.button("＋ Filtergruppe hinzufügen", key="add_group", use_container_width=True):
            gid = _new_id("g")
            fid = _new_id("f")
            model.append({"id": gid, "filters": [{"id": fid, "property": P_HISTORIE, "op": "CONTAINS_TOKEN", "value": []}]})
            st.session_state[state_key] = model
            st.rerun()

    st.session_state[state_key] = model
    return build_compiled_groups_from_model(model)
