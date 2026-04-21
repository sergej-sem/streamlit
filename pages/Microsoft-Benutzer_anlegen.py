from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

import pandas as pd
import streamlit as st
from microsoft_bulk_user.executor import execute_plan_row
from microsoft_bulk_user.graph_ops import (
    GraphConfig,
    assign_licenses,
    create_graph_app,
    create_user_graph,
    get_access_token,
    get_subscribed_sku_map,
    name_exists,
    upn_exists,
    user_payload,
)
from microsoft_bulk_user.planner import build_plan
from microsoft_bulk_user.parser import read_table
from shared.config import (
    ConfigError,
    is_live_user_creation_enabled,
    load_graph_bulk_user_settings,
)
from streamlit_ui import render_page_title, render_section_title


# ============================================================
# Grundeinstellungen (fuer Benutzer versteckt)
# ============================================================
DEFAULT_DOMAIN = "mysecurityeventde.onmicrosoft.com"
DEFAULT_PASSWORD = ""

CONFIRM_WORD_LIVE = "ANLEGEN"

# ----------------------------
# Lizenz-Auswahl (UI)
# ----------------------------
LICENSE_CATALOG = {
    "FLOW_FREE": "Microsoft Power Automate Free",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "POWER_BI_STANDARD": "Microsoft Fabric (Free)",
    "POWERAPPS_DEV": "Microsoft Power Apps for Developer",
}

DEFAULT_LICENSE_SELECTION = ["O365_BUSINESS_PREMIUM"]
PLAN_DISPLAY_RENAME_MAP = {
    "row": "Zeile",
    "displayName": "Name",
    "firstName": "Vorname",
    "lastName": "Nachname",
    "plannedUPN": "Geplanter Login (UPN)",
    "status": "Status",
    "details": "Hinweis",
}


# ============================================================
# Microsoft Graph (App-only)
# ============================================================
@st.cache_resource
def get_cached_graph_app(cfg: GraphConfig):
    return create_graph_app(cfg)


@st.cache_data(ttl=300)
def get_subscribed_sku_map_cached(token: str) -> Dict[str, str]:
    return get_subscribed_sku_map(token)


@st.cache_data(ttl=300)
def upn_exists_cached(upn: str, token: str) -> bool:
    return upn_exists(upn, token)


@st.cache_data(ttl=300)
def name_exists_cached(first: str, last: str, token: str) -> bool:
    return name_exists(first, last, token)


def _rename_plan_columns(plan_df: pd.DataFrame) -> pd.DataFrame:
    return plan_df.rename(columns=PLAN_DISPLAY_RENAME_MAP)


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="Microsoft-Benutzer anlegen", layout="wide")
render_page_title("Microsoft-Benutzer anlegen (CSV/XLSX → Entra ID)")

st.caption(
    "Ablauf: Datei hochladen → Plan prüfen → (optional) Testlauf → Benutzer anlegen."
)

graph_cfg = None
enable_live_user_creation = False
try:
    graph_settings = load_graph_bulk_user_settings(st.secrets)
except ConfigError:
    graph_settings = None
else:
    graph_cfg = GraphConfig(
        graph_settings.tenant_id,
        graph_settings.client_id,
        graph_settings.client_secret,
    )
    enable_live_user_creation = is_live_user_creation_enabled(st.secrets)

if not graph_cfg:
    st.error(
        "Diese App ist noch nicht konfiguriert (Entra/Graph-Zugangsdaten fehlen). "
        "Bitte wende dich an den Administrator."
    )
    st.stop()

controls_col, main_col = st.columns([1, 2], gap="large")

with controls_col:
    render_section_title("1) Datei auswählen")
    uploaded = st.file_uploader("CSV oder XLSX hochladen", type=["csv", "xlsx"])

    st.divider()
    render_section_title("2) Einstellungen")

    domain = st.text_input("Login-Domain", value=DEFAULT_DOMAIN, help="Wird für den Login-Namen (UPN) verwendet.")
    password = st.text_input(
        "Start-Passwort (für alle neuen Benutzer)",
        value=DEFAULT_PASSWORD,
        type="password",
        help="Dieses Passwort wird beim Anlegen gesetzt. Bitte anschließend sicher verteilen.",
    )

    selected_license_parts = st.multiselect(
        "Lizenzen zuweisen (für alle neuen Benutzer)",
        options=list(LICENSE_CATALOG.keys()),
        default=DEFAULT_LICENSE_SELECTION,
        format_func=lambda k: LICENSE_CATALOG.get(k, k),
        help="Diese Auswahl gilt für alle Benutzer mit Status BEREIT.",
    )

    st.divider()
    render_section_title("3) Test oder Anlegen")

    mode_options = ["Testlauf (es wird nichts angelegt)"]
    if enable_live_user_creation:
        mode_options.append("Benutzer jetzt anlegen (Achtung!)")

    mode = st.radio(
        "Was möchtest du tun?",
        options=mode_options,
        index=0,
    )
    dry_run = mode.startswith("Testlauf")

    if not enable_live_user_creation:
        st.info(
            "Die Live-Benutzeranlage ist in diesem Deployment deaktiviert. "
            "Sie kann nur über `[mse_graph_bulk_user].enable_live_user_creation = true` "
            "explizit freigeschaltet werden."
        )

    confirm_text = ""
    live_confirmation_placeholder = CONFIRM_WORD_LIVE
    if dry_run:
        st.info("Testlauf aktiv: Es werden keine Benutzer angelegt.")

with main_col:
    if uploaded is None:
        st.info("Bitte links eine CSV oder XLSX hochladen. Danach erscheint hier die Vorschau und der Plan.")
        st.stop()

    try:
        df, source = read_table(uploaded, worksheet_number=1)
    except Exception as exc:
        st.error(f"Datei konnte nicht gelesen werden: {exc}")
        st.stop()

    render_section_title("Vorschau")
    st.write(f"Quelle: **{source}** · Zeilen: **{len(df)}** · Spalten: **{len(df.columns)}**")
    st.dataframe(df.head(25), use_container_width=True, hide_index=True)

    try:
        token = get_access_token(graph_cfg, app=get_cached_graph_app(graph_cfg))
        sku_map = get_subscribed_sku_map_cached(token)
        selected_sku_ids: List[str] = []
        selected_license_labels = [LICENSE_CATALOG.get(part, part) for part in selected_license_parts]
        missing_parts: List[str] = []
        for part in selected_license_parts:
            if part in sku_map:
                selected_sku_ids.append(sku_map[part])
            else:
                missing_parts.append(part)

        if missing_parts:
            missing_names = ", ".join(LICENSE_CATALOG.get(part, part) for part in missing_parts)
            st.warning(
                "Achtung: Folgende ausgewählte Lizenzen sind im Tenant nicht verfügbar und werden ignoriert: "
                + missing_names
            )
    except Exception as exc:
        st.error(f"Anmeldung an Microsoft (Graph) fehlgeschlagen: {exc}")
        st.stop()

    plan = build_plan(
        df=df,
        domain=domain.strip(),
        name_exists=lambda first, last: name_exists_cached(first, last, token),
        upn_exists=lambda upn: upn_exists_cached(upn, token),
    )

    render_section_title("Plan (wer wird angelegt?)")

    filter_opt = st.selectbox(
        "Anzeige filtern",
        options=["Alle", "Nur BEREIT", "Nur ÜBERSPRUNGEN", "Nur FEHLER"],
        index=0,
    )
    if filter_opt == "Nur BEREIT":
        plan_view = plan[plan["status"] == "BEREIT"]
    elif filter_opt == "Nur ÜBERSPRUNGEN":
        plan_view = plan[plan["status"] == "ÜBERSPRUNGEN"]
    elif filter_opt == "Nur FEHLER":
        plan_view = plan[plan["status"] == "FEHLER"]
    else:
        plan_view = plan

    plan_display = _rename_plan_columns(plan_view)
    st.dataframe(plan_display, use_container_width=True, hide_index=True)

    plan_export = _rename_plan_columns(plan)
    plan_csv = plan_export.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Plan als CSV herunterladen",
        data=plan_csv,
        file_name="benutzer_plan.csv",
        mime="text/csv",
    )

    ready_count = int((plan["status"] == "BEREIT").sum())
    skip_count = int((plan["status"] == "ÜBERSPRUNGEN").sum())
    err_count = int((plan["status"] == "FEHLER").sum())
    st.write(f"BEREIT: **{ready_count}** · ÜBERSPRUNGEN: **{skip_count}** · FEHLER: **{err_count}**")

    expected_live_confirmation = f"{CONFIRM_WORD_LIVE} {ready_count}"
    live_confirmation_placeholder = expected_live_confirmation

    if not dry_run:
        with controls_col:
            st.warning("Achtung: Im nächsten Schritt werden echte Benutzerkonten angelegt.")
            confirm_text = st.text_input(
                f"Sicherheitsabfrage: Bitte exakt {expected_live_confirmation} eintippen",
                value="",
                help=(
                    "Damit nicht aus Versehen Benutzer angelegt werden. "
                    f"Erwartet wird exakt: {expected_live_confirmation}"
                ),
            )

    st.divider()
    render_section_title("Ausführen")

    allow_live = (
        enable_live_user_creation
        and (not dry_run)
        and bool(password.strip())
        and ready_count > 0
        and (confirm_text.strip().upper() == expected_live_confirmation.upper())
    )

    if not dry_run and not enable_live_user_creation:
        st.error("Die Live-Benutzeranlage ist aktuell deaktiviert.")
    elif not dry_run and not password.strip():
        st.error("Zum Anlegen bitte ein Start-Passwort eingeben.")
    elif not dry_run and not allow_live:
        st.error(f"Zum Anlegen bitte links exakt {live_confirmation_placeholder} eintippen.")

    can_start = ready_count > 0 and (dry_run or allow_live)
    start_label = "Testlauf starten" if dry_run else "Benutzer anlegen"
    run_btn = st.button(start_label, type="primary", disabled=not can_start)

    if ready_count == 0:
        st.info("Es gibt keine Einträge mit Status BEREIT. Bitte Plan prüfen (ÜBERSPRUNGEN/FEHLER).")

    if run_btn:
        if not dry_run and not enable_live_user_creation:
            st.error("Die Live-Benutzeranlage ist in diesem Deployment deaktiviert.")
            st.stop()
        if not dry_run and not password.strip():
            st.error("Zum Anlegen bitte ein Start-Passwort eingeben.")
            st.stop()
        if not dry_run and not allow_live:
            st.error(f"Zum Anlegen bitte links exakt {expected_live_confirmation} eintippen.")
            st.stop()

        log_rows: List[Dict] = []
        progress = st.progress(0)
        status_box = st.empty()
        run_started_utc = datetime.now(timezone.utc)
        run_context = {
            "Run-ID": f"MBU-{run_started_utc.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
            "Modus": "TESTLAUF" if dry_run else "LIVE",
            "Zeitpunkt UTC": run_started_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "Domain": domain.strip(),
            "Lizenzen": ", ".join(selected_license_labels),
            "BEREIT im Plan": ready_count,
        }

        rows = plan.to_dict(orient="records")
        total = max(1, len(rows))

        for i, row in enumerate(rows, start=1):
            progress.progress(int(i / total * 100))

            if row.get("status", "") == "BEREIT":
                status_box.write(f"{'TEST' if dry_run else 'ANLEGEN'}: {row.get('plannedUPN', '')}")

            result = execute_plan_row(
                row,
                dry_run=dry_run,
                enable_live_user_creation=enable_live_user_creation,
                password=password,
                selected_license_labels=selected_license_labels,
                selected_sku_ids=selected_sku_ids,
                build_payload=lambda **kw: user_payload(**kw),
                create_user=lambda payload: create_user_graph(payload, token),
                assign_user_licenses=lambda user_id, sku_ids: assign_licenses(user_id, sku_ids, token),
            )
            log_rows.append({**result["log_row"], **run_context})

        progress.progress(100)
        status_box.write("Fertig.")

        log_df = pd.DataFrame(log_rows)
        result_counts = (
            log_df["Ergebnis"].fillna("").astype(str).value_counts()
            if "Ergebnis" in log_df.columns
            else pd.Series(dtype="int64")
        )

        st.write(
            "Ergebnisübersicht: "
            f"ANGELEGT: **{int(result_counts.get('ANGELEGT', 0))}** · "
            f"TEILERFOLG: **{int(result_counts.get('TEILERFOLG', 0))}** · "
            f"FEHLER: **{int(result_counts.get('FEHLER', 0))}** · "
            f"TESTLAUF: **{int(result_counts.get('TESTLAUF', 0))}** · "
            f"ÜBERSPRUNGEN: **{int(result_counts.get('ÜBERSPRUNGEN', 0))}**"
        )
        render_section_title("Protokoll")
        st.dataframe(log_df, use_container_width=True, hide_index=True)

        log_csv = log_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Protokoll als CSV herunterladen",
            data=log_csv,
            file_name="benutzer_protokoll.csv",
            mime="text/csv",
        )
