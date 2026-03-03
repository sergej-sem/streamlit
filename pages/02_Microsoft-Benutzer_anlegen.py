import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Set

import pandas as pd
import requests
import streamlit as st
import msal


# ============================================================
# Grundeinstellungen (für Benutzer versteckt)
# ============================================================
DEFAULT_DOMAIN = "mysecurityeventde.onmicrosoft.com"
DEFAULT_USAGE_LOCATION = "DE"               # intern gesetzt, nicht in der UI sichtbar
DEFAULT_PASSWORD = "Dortmund2026MSE"        # wird in der UI vorausgefüllt
DEFAULT_DISABLE_PWD_EXP = True              # intern, nicht in der UI sichtbar
DEFAULT_FORCE_CHANGE = False                # intern, nicht in der UI sichtbar

CONFIRM_WORD_LIVE = "ANLEGEN"

# ----------------------------
# Lizenz-Auswahl (UI)
# ----------------------------
# Anzeigenamen (deutsch) für die Weboberfläche
LICENSE_CATALOG = {
    "FLOW_FREE": "Microsoft Power Automate Free",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "POWER_BI_STANDARD": "Microsoft Fabric (Free)",
    "POWERAPPS_DEV": "Microsoft Power Apps for Developer",
}

DEFAULT_LICENSE_SELECTION = ["O365_BUSINESS_PREMIUM"]  # Vorauswahl in der UI
               # Sicherheitswort für Live-Run


# ----------------------------
# Spalten-Aliase (CSV/XLSX)
# ----------------------------
FIRST_ALIASES = {
    "firstname", "first", "givenname", "given", "vorname", "prename", "namefirst", "forename"
}
LAST_ALIASES = {
    "lastname", "last", "surname", "familyname", "family", "nachname", "namelast"
}
FULL_ALIASES = {
    "fullname", "name", "displayname", "kontaktname", "contactname", "benutzer", "mitarbeiter", "teilnehmer"
}
UPN_ALIASES = {
    "userprincipalname", "upn", "email", "mail", "username", "login", "signinname"
}

NAME_PARTICLES = {"von", "van", "de", "del", "da", "der", "den", "di", "la", "le", "du", "st", "st."}


def norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[_\-/\.]", "", s)
    return s


def detect_delimiter(sample: str) -> str:
    candidates = [";", ",", "\t", "|"]
    counts = {d: sample.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ";"


def decode_bytes_auto(raw: bytes) -> Tuple[str, str]:
    """Return (text, encoding_name) with simple BOM + fallback strategy."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16", errors="replace"), "utf-16-le(bom)"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace"), "utf-16-be(bom)"

    # try utf-8 first
    txt = raw.decode("utf-8", errors="replace")
    has_replacement = "\ufffd" in txt
    has_c1 = bool(re.search(r"[\x80-\x9f]", txt))
    if has_replacement or has_c1:
        return raw.decode("cp1252", errors="replace"), "cp1252"
    return txt, "utf-8"


def looks_like_headerless(cols) -> bool:
    # If first two "column names" contain letters and are not generic headers,
    # it's likely the first row was interpreted as headers.
    col0 = str(cols[0]) if len(cols) > 0 else ""
    col1 = str(cols[1]) if len(cols) > 1 else ""
    generic = {"firstname", "lastname", "vorname", "nachname", "name", "fullname", "email", "upn"}
    return (
        bool(re.search(r"[A-Za-zÄÖÜäöüß]", col0 + col1))
        and norm_key(col0) not in generic
        and norm_key(col1) not in generic
        and len(cols) >= 2
    )


def has_any_alias_columns(cols) -> bool:
    keys = {norm_key(c) for c in cols}
    return bool(keys & (FIRST_ALIASES | LAST_ALIASES | FULL_ALIASES | UPN_ALIASES))


def find_col(cols, aliases: set) -> Optional[str]:
    for c in cols:
        if norm_key(c) in aliases:
            return c
    return None


def split_fullname(fullname: str) -> Optional[Tuple[str, str]]:
    if not fullname or not str(fullname).strip():
        return None
    x = re.sub(r"\s+", " ", str(fullname).strip())
    parts = [p for p in x.split(" ") if p]
    if len(parts) < 2:
        return None

    last = parts[-1]
    i = len(parts) - 2
    while i >= 0 and parts[i].lower() in NAME_PARTICLES:
        last = parts[i] + " " + last
        i -= 1
    first = " ".join(parts[: i + 1]).strip()
    if not first or not last:
        return None
    return first, last


def normalize_name_part(s: str) -> str:
    """Normalization for UPN parts."""
    if not s:
        return ""
    s = str(s).strip()

    # German specific mapping first
    s = (
        s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        .replace("ß", "ss")
    )

    # Remove other accents (é -> e, ë -> e, etc.)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

    s = s.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def read_table(uploaded_file, worksheet_number: int = 1) -> Tuple[pd.DataFrame, str]:
    name = uploaded_file.name.lower()
    raw = uploaded_file.getvalue()

    if name.endswith(".xlsx"):
        bio = io.BytesIO(raw)
        df = pd.read_excel(bio, sheet_name=max(0, worksheet_number - 1), dtype=str, engine="openpyxl").fillna("")
        # heuristic: if headers look like data, retry header=None
        if not has_any_alias_columns(df.columns) and looks_like_headerless(df.columns):
            bio2 = io.BytesIO(raw)
            df2 = pd.read_excel(
                bio2, sheet_name=max(0, worksheet_number - 1), header=None, dtype=str, engine="openpyxl"
            ).fillna("")
            if df2.shape[1] >= 2:
                df2.columns = ["FirstName", "LastName"] + [f"Col{idx}" for idx in range(3, df2.shape[1] + 1)]
                df = df2
        return df, "xlsx"

    text, enc = decode_bytes_auto(raw)
    lines = [ln for ln in re.split(r"\r?\n", text) if ln.strip() != ""]
    if not lines:
        return pd.DataFrame(), f"csv({enc})"

    delim = detect_delimiter(lines[0])
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=delim, dtype=str, encoding=enc).fillna("")
    except Exception:
        df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str).fillna("")

    if not has_any_alias_columns(df.columns) and looks_like_headerless(df.columns):
        try:
            df2 = pd.read_csv(io.BytesIO(raw), sep=delim, header=None, dtype=str, encoding=enc).fillna("")
        except Exception:
            df2 = pd.read_csv(io.StringIO(text), sep=delim, header=None, dtype=str).fillna("")
        if df2.shape[1] >= 2:
            df2.columns = ["FirstName", "LastName"] + [f"Col{idx}" for idx in range(3, df2.shape[1] + 1)]
            df = df2

    return df, f"csv({enc}, Trennzeichen='{delim}')"


# ============================================================
# Microsoft Graph (App-only)
# ============================================================
@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str


@st.cache_resource
def get_graph_app(cfg: GraphConfig):
    authority = f"https://login.microsoftonline.com/{cfg.tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=cfg.client_id,
        authority=authority,
        client_credential=cfg.client_secret,
    )


def get_access_token(cfg: GraphConfig) -> str:
    app = get_graph_app(cfg)
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_silent(scopes, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" not in result:
        raise RuntimeError(f"Token-Fehler: {result.get('error')} - {result.get('error_description')}")
    return result["access_token"]


@st.cache_data(ttl=300)
def get_subscribed_sku_map(token: str) -> Dict[str, str]:
    """
    Liefert ein Mapping {SkuPartNumber -> skuId} aus Graph /subscribedSkus.
    """
    url = "https://graph.microsoft.com/v1.0/subscribedSkus"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Graph-Abfrage (subscribedSkus) fehlgeschlagen ({r.status_code}): {r.text}")
    data = r.json().get("value", [])
    out: Dict[str, str] = {}
    for item in data:
        part = item.get("skuPartNumber")
        sku_id = item.get("skuId")
        if part and sku_id:
            out[str(part)] = str(sku_id)
    return out


def assign_licenses(user_id: str, sku_ids: List[str], token: str) -> None:
    """
    Weist einem Benutzer Lizenzen zu (addLicenses). Entfernt nichts.
    """
    if not sku_ids:
        return
    url = f"https://graph.microsoft.com/v1.0/users/{user_id}/assignLicense"
    payload = {
        "addLicenses": [{"skuId": sid} for sid in sku_ids],
        "removeLicenses": [],
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Lizenzzuweisung fehlgeschlagen ({r.status_code}): {r.text}")


def _escape_odata_string(s: str) -> str:
    return (s or "").replace("'", "''")


@st.cache_data(ttl=300)
def upn_exists_cached(upn: str, token: str) -> bool:
    url = "https://graph.microsoft.com/v1.0/users"
    params = {"$filter": f"userPrincipalName eq '{_escape_odata_string(upn)}'", "$top": "1"}
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return bool(data.get("value"))
    raise RuntimeError(f"Graph-Abfrage (UPN) fehlgeschlagen ({r.status_code}): {r.text}")


@st.cache_data(ttl=300)
def name_exists_cached(first: str, last: str, token: str) -> bool:
    """
    Prüft, ob bereits ein Benutzer mit identischem Vor- UND Nachnamen existiert.
    Primär über givenName + surname; falls nicht unterstützt, Fallback über displayName.
    """
    url = "https://graph.microsoft.com/v1.0/users"
    f = _escape_odata_string(first.strip())
    l = _escape_odata_string(last.strip())

    # Versuch 1: givenName + surname
    params = {"$filter": f"givenName eq '{f}' and surname eq '{l}'", "$top": "1", "$select": "id"}
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
    if r.status_code == 200:
        return bool(r.json().get("value"))
    if r.status_code not in (400, 501):
        raise RuntimeError(f"Graph-Abfrage (Name) fehlgeschlagen ({r.status_code}): {r.text}")

    # Fallback: displayName exakt "Vorname Nachname"
    display = _escape_odata_string(f"{first.strip()} {last.strip()}".strip())
    params2 = {"$filter": f"displayName eq '{display}'", "$top": "1", "$select": "id"}
    r2 = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params2, timeout=30)
    if r2.status_code == 200:
        return bool(r2.json().get("value"))
    raise RuntimeError(f"Graph-Abfrage (displayName Fallback) fehlgeschlagen ({r2.status_code}): {r2.text}")


def create_user_graph(payload: dict, token: str) -> Dict:
    url = "https://graph.microsoft.com/v1.0/users"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if r.status_code in (200, 201):
        return r.json()
    raise RuntimeError(f"Benutzer anlegen fehlgeschlagen ({r.status_code}): {r.text}")


# ============================================================
# Planung (UPN + Prüfungen)
# ============================================================
def build_plan(df: pd.DataFrame, domain: str, token: str) -> pd.DataFrame:
    """
    Regeln:
      - Pro identischem Vorname+Nachname darf es nur 1 Benutzer geben.
      - Wenn Name in der Datei mehrfach vorkommt -> nur der erste bleibt, rest wird übersprungen.
      - Wenn Name in Entra bereits existiert -> überspringen (und explizit ausweisen).
      - UPN wird deterministisch gebaut: vorname.nachname@domain (ohne Suffix-Varianten).
      - Wenn UPN bereits existiert (aber Name nicht als Duplikat erkannt wurde) -> Fehler, weiterlaufen.
    """
    cols = df.columns.tolist()
    c_first = find_col(cols, FIRST_ALIASES)
    c_last = find_col(cols, LAST_ALIASES)
    c_full = find_col(cols, FULL_ALIASES)
    c_upn = find_col(cols, UPN_ALIASES)

    seen_names: Set[Tuple[str, str]] = set()
    rows: List[Dict] = []

    for idx, row in df.iterrows():
        first_raw = str(row.get(c_first, "")).strip() if c_first else ""
        last_raw = str(row.get(c_last, "")).strip() if c_last else ""
        provided_upn = str(row.get(c_upn, "")).strip() if c_upn else ""

        if (not first_raw or not last_raw) and c_full:
            split = split_fullname(str(row.get(c_full, "")).strip())
            if split:
                if not first_raw:
                    first_raw = split[0]
                if not last_raw:
                    last_raw = split[1]

        # fallback: first two columns
        if (not first_raw or not last_raw) and len(cols) >= 2:
            if not first_raw:
                first_raw = str(row.get(cols[0], "")).strip()
            if not last_raw:
                last_raw = str(row.get(cols[1], "")).strip()

        display = (first_raw + " " + last_raw).strip()

        if not first_raw or not last_raw:
            rows.append({
                "row": idx + 1,
                "displayName": display,
                "firstName": first_raw,
                "lastName": last_raw,
                "plannedUPN": "",
                "status": "FEHLER",
                "details": "Vorname/Nachname fehlt oder konnte nicht erkannt werden",
            })
            continue

        # Duplikat in Datei (identischer Name)
        name_key = (first_raw.casefold(), last_raw.casefold())
        if name_key in seen_names:
            rows.append({
                "row": idx + 1,
                "displayName": display,
                "firstName": first_raw,
                "lastName": last_raw,
                "plannedUPN": "",
                "status": "ÜBERSPRUNGEN",
                "details": "Duplikat in der Datei (gleicher Vor- und Nachname) – wird nicht angelegt",
            })
            continue
        seen_names.add(name_key)

        # UPN bestimmen
        if provided_upn:
            planned_upn = provided_upn if "@" in provided_upn else f"{provided_upn}@{domain}"
        else:
            first_norm = normalize_name_part(first_raw)
            last_norm = normalize_name_part(last_raw)
            if not first_norm or not last_norm:
                rows.append({
                    "row": idx + 1,
                    "displayName": display,
                    "firstName": first_raw,
                    "lastName": last_raw,
                    "plannedUPN": "",
                    "status": "FEHLER",
                    "details": "Name kann nicht zu einem gültigen Login-Namen umgewandelt werden",
                })
                continue
            planned_upn = f"{first_norm}.{last_norm}@{domain}"

        # Duplikat in Entra (identischer Name)
        if name_exists_cached(first_raw, last_raw, token):
            rows.append({
                "row": idx + 1,
                "displayName": display,
                "firstName": first_raw,
                "lastName": last_raw,
                "plannedUPN": planned_upn,
                "status": "ÜBERSPRUNGEN",
                "details": "Benutzer existiert bereits in Entra (gleicher Vor- und Nachname) – wird nicht angelegt",
            })
            continue

        # UPN-Kollision (laut Anforderung kein Suffix -> Fehler)
        if upn_exists_cached(planned_upn, token):
            rows.append({
                "row": idx + 1,
                "displayName": display,
                "firstName": first_raw,
                "lastName": last_raw,
                "plannedUPN": planned_upn,
                "status": "FEHLER",
                "details": "Login-Name (UPN) existiert bereits – kein automatisches Umbenennen erlaubt",
            })
            continue

        rows.append({
            "row": idx + 1,
            "displayName": display,
            "firstName": first_raw,
            "lastName": last_raw,
            "plannedUPN": planned_upn,
            "status": "BEREIT",
            "details": "",
        })

    return pd.DataFrame(rows)


def user_payload(
    display_name: str,
    upn: str,
    mail_nick: str,
    given: str,
    surname: str,
    password: str,
) -> dict:
    payload = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": mail_nick,
        "userPrincipalName": upn,
        "givenName": given,
        "surname": surname,
        "usageLocation": DEFAULT_USAGE_LOCATION,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": bool(DEFAULT_FORCE_CHANGE),
            "password": password,
        },
    }
    if DEFAULT_DISABLE_PWD_EXP:
        payload["passwordPolicies"] = "DisablePasswordExpiration"
    return payload


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="Microsoft-Benutzer anlegen", layout="wide")
st.title("Microsoft-Benutzer anlegen (CSV/XLSX → Entra ID)")

st.caption(
    "Ablauf: Datei hochladen → Plan prüfen → (optional) Testlauf → Benutzer anlegen."
)

# Konfiguration nur über st.secrets
graph_cfg = None
if "mse_graph_bulk_user" in st.secrets:
    g = st.secrets["mse_graph_bulk_user"]
    if all(k in g for k in ("tenant_id", "client_id", "client_secret")):
        graph_cfg = GraphConfig(g["tenant_id"], g["client_id"], g["client_secret"])

if not graph_cfg:
    st.error(
        "Diese App ist noch nicht konfiguriert (Entra/Graph-Zugangsdaten fehlen). "
        "Bitte wende dich an den Administrator."
    )
    st.stop()

# Layout
controls_col, main_col = st.columns([1, 2], gap="large")

with controls_col:
    st.subheader("1) Datei auswählen")
    uploaded = st.file_uploader("CSV oder XLSX hochladen", type=["csv", "xlsx"])

    st.divider()
    st.subheader("2) Einstellungen")

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
    st.subheader("3) Test oder Anlegen")

    mode = st.radio(
        "Was möchtest du tun?",
        options=[
            "Testlauf (es wird nichts angelegt)",
            "Benutzer jetzt anlegen (Achtung!)",
        ],
        index=0,
    )
    dry_run = mode.startswith("Testlauf")

    confirm_text = ""
    if not dry_run:
        st.warning("Achtung: Im nächsten Schritt werden echte Benutzerkonten angelegt.")
        confirm_text = st.text_input(
            f"Sicherheitsabfrage: Bitte {CONFIRM_WORD_LIVE} eintippen",
            value="",
            help="Damit nicht aus Versehen Benutzer angelegt werden.",
        )
    else:
        st.info("Testlauf aktiv: Es werden keine Benutzer angelegt.")

with main_col:
    if uploaded is None:
        st.info("Bitte links eine CSV oder XLSX hochladen. Danach erscheint hier die Vorschau und der Plan.")
        st.stop()

    # Datei lesen
    try:
        df, source = read_table(uploaded, worksheet_number=1)
    except Exception as e:
        st.error(f"Datei konnte nicht gelesen werden: {e}")
        st.stop()

    st.subheader("Vorschau")
    st.write(f"Quelle: **{source}** · Zeilen: **{len(df)}** · Spalten: **{len(df.columns)}**")
    st.dataframe(df.head(25), use_container_width=True, hide_index=True)

    # Token holen
    try:
        token = get_access_token(graph_cfg)
        sku_map = get_subscribed_sku_map(token)
        selected_sku_ids: List[str] = []
        missing_parts: List[str] = []
        for part in selected_license_parts:
            if part in sku_map:
                selected_sku_ids.append(sku_map[part])
            else:
                missing_parts.append(part)

        if missing_parts:
            missing_names = ", ".join(LICENSE_CATALOG.get(p, p) for p in missing_parts)
            st.warning(
                "Achtung: Folgende ausgewählte Lizenzen sind im Tenant nicht verfügbar und werden ignoriert: "
                + missing_names
            )
    except Exception as e:
        st.error(f"Anmeldung an Microsoft (Graph) fehlgeschlagen: {e}")
        st.stop()

    # Plan erstellen
    plan = build_plan(df=df, domain=domain.strip(), token=token)

    st.subheader("Plan (wer wird angelegt?)")

    # Filter
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

    # Anzeige: deutsche Spalten
    plan_display = plan_view.rename(columns={
        "row": "Zeile",
        "displayName": "Name",
        "firstName": "Vorname",
        "lastName": "Nachname",
        "plannedUPN": "Geplanter Login (UPN)",
        "status": "Status",
        "details": "Hinweis",
    })
    st.dataframe(plan_display, use_container_width=True, hide_index=True)

    # Export (deutsche Spalten)
    plan_export = plan.rename(columns={
        "row": "Zeile",
        "displayName": "Name",
        "firstName": "Vorname",
        "lastName": "Nachname",
        "plannedUPN": "Geplanter Login (UPN)",
        "status": "Status",
        "details": "Hinweis",
    })
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

    st.divider()
    st.subheader("Ausführen")

    allow_live = (not dry_run) and (confirm_text.strip().upper() == CONFIRM_WORD_LIVE)

    if not dry_run and not allow_live:
        st.error(f"Zum Anlegen bitte links {CONFIRM_WORD_LIVE} eintippen.")

    can_start = ready_count > 0 and (dry_run or allow_live)
    start_label = "Testlauf starten" if dry_run else "Benutzer anlegen"
    run_btn = st.button(start_label, type="primary", disabled=not can_start)

    if ready_count == 0:
        st.info("Es gibt keine Einträge mit Status BEREIT. Bitte Plan prüfen (ÜBERSPRUNGEN/FEHLER).")

    if run_btn:
        log_rows: List[Dict] = []
        progress = st.progress(0)
        status_box = st.empty()

        rows = plan.to_dict(orient="records")
        total = max(1, len(rows))

        for i, r in enumerate(rows, start=1):
            progress.progress(int(i / total * 100))

            st_status = r.get("status", "")
            upn = r.get("plannedUPN", "")
            display = r.get("displayName", "")
            first = r.get("firstName", "")
            last = r.get("lastName", "")

            if st_status != "BEREIT":
                log_rows.append({
                    "Zeile": r.get("row"),
                    "Name": display,
                    "Login (UPN)": upn,
                    "Ergebnis": st_status,
                    "Hinweis": r.get("details", ""),
                })
                continue

            status_box.write(f"{'TEST' if dry_run else 'ANLEGEN'}: {upn}")

            try:
                if dry_run:
                    log_rows.append({
                        "Zeile": r.get("row"),
                        "Name": display,
                        "Login (UPN)": upn,
                        "Ergebnis": "TESTLAUF",
                        "Hinweis": (
                            "Nicht angelegt (Testlauf)"
                            + (f" · Würde Lizenzen zuweisen: {', '.join(LICENSE_CATALOG.get(p, p) for p in selected_license_parts)}"
                               if selected_license_parts else "")
                        ),
                    })
                    continue

                mail_nick = upn.split("@")[0]
                payload = user_payload(
                    display_name=display,
                    upn=upn,
                    mail_nick=mail_nick,
                    given=first,
                    surname=last,
                    password=password,
                )
                created = create_user_graph(payload, token)
                user_id = created.get("id")
                lizenz_hinweis = ""
                if selected_sku_ids and user_id:
                    try:
                        assign_licenses(user_id, selected_sku_ids, token)
                        lizenz_hinweis = "Lizenzen zugewiesen"
                    except Exception as le:
                        lizenz_hinweis = f"Lizenzzuweisung fehlgeschlagen: {le}"
                log_rows.append({
                    "Zeile": r.get("row"),
                    "Name": display,
                    "Login (UPN)": upn,
                    "Ergebnis": "ANGELEGT",
                    "Hinweis": lizenz_hinweis,
                })
            except Exception as e:
                log_rows.append({
                    "Zeile": r.get("row"),
                    "Name": display,
                    "Login (UPN)": upn,
                    "Ergebnis": "FEHLER",
                    "Hinweis": str(e),
                })

        progress.progress(100)
        status_box.write("Fertig.")

        log_df = pd.DataFrame(log_rows)
        st.subheader("Protokoll")
        st.dataframe(log_df, use_container_width=True, hide_index=True)

        log_csv = log_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Protokoll als CSV herunterladen",
            data=log_csv,
            file_name="benutzer_protokoll.csv",
            mime="text/csv",
        )
