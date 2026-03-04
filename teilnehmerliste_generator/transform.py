import re
import pandas as pd

# C-Level & VP -> "C-Level", alles andere -> "Fachbereich" (DE) / "Department" (EN)
CLEVEL_RE = re.compile(
    r"\b(CEO|CIO|CISO|CTO|COO|CSO|CDO|CFO|CHRO|CPO|CRO|Chief|Vorstand|Geschäftsführer|Geschaeftsfuehrer|Managing Director)\b"
    r"|\b(VP|V\.P\.|Vice President)\b",
    re.IGNORECASE,
)

# Heuristik für "niedrigste Position entfernen" (nur aus jobtitle-Text)
SENIORITY_RULES = [
    (re.compile(r"\b(CEO|Chief Executive|Vorstandsvorsitz|Chairman)\b", re.IGNORECASE), 100),
    (re.compile(r"\b(Owner|Founder|Inhaber)\b", re.IGNORECASE), 95),
    (re.compile(r"\b(CIO|CISO|CTO|COO|CSO|CDO|CFO|CHRO|CPO|CRO)\b", re.IGNORECASE), 92),
    (re.compile(r"\b(Managing Director|Geschäftsführer|Geschaeftsfuehrer)\b", re.IGNORECASE), 90),
    (re.compile(r"\b(SVP|Senior Vice President)\b", re.IGNORECASE), 85),
    (re.compile(r"\b(VP|Vice President)\b", re.IGNORECASE), 80),
    (re.compile(r"\b(Director|Direktor)\b", re.IGNORECASE), 70),
    (re.compile(r"\b(Head|Leiter)\b", re.IGNORECASE), 60),
    (re.compile(r"\b(Manager)\b", re.IGNORECASE), 50),
    (re.compile(r"\b(Senior)\b", re.IGNORECASE), 45),
    (re.compile(r"\b(Lead)\b", re.IGNORECASE), 40),
    (re.compile(r"\b(Specialist|Engineer|Analyst|Consultant)\b", re.IGNORECASE), 30),
    (re.compile(r"\b(Assistant|Intern|Trainee)\b", re.IGNORECASE), 10),
]


def _clean(x) -> str:
    """Normalize cell values to clean strings (handles NaN/None)."""
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    s = str(x).replace("\u00a0", " ").strip()
    return "" if s.lower() == "nan" else s


def _bucket(jobtitle: str, lang: str) -> str:
    """
    Map original job title text into one of two categories:
      - "C-Level"
      - "Fachbereich" (DE) / "Department" (EN)
    """
    jt = _clean(jobtitle)
    if jt and CLEVEL_RE.search(jt):
        return "C-Level"
    return "Department" if lang == "en" else "Fachbereich"


def _bucket_prio(bucket: str) -> int:
    """Priority used for sorting (higher kept first)."""
    return 2 if bucket == "C-Level" else 1


def _seniority(jobtitle: str) -> int:
    """Heuristic seniority score from job title text."""
    jt = _clean(jobtitle)
    if not jt:
        return 0
    for rx, score in SENIORITY_RULES:
        if rx.search(jt):
            return score
    return 20


def build_teilnehmerliste(df_raw: pd.DataFrame, lang: str = "de") -> pd.DataFrame:
    """
    Input: df_raw mit Spalten 'company' und 'jobtitle' (HubSpot internal names)

    Output: 2 Spalten:
      - Unternehmensname
      - Jobbezeichnung  (DE: C-Level/Fachbereich, EN: C-Level/Department)

    Regeln:
      - A-Z nach Unternehmensname (case-insensitive)
      - C-Level & VP -> C-Level
      - alles andere -> Fachbereich (DE) / Department (EN)
      - max 2 Einträge pro Firma (drops lowest using category priority + seniority heuristic)
    """
    if lang not in ("de", "en"):
        raise ValueError("lang must be 'de' or 'en'")

    df = df_raw.copy()

    # Required columns check (clear error instead of KeyError)
    missing = [c for c in ["company", "jobtitle"] if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    df["company"] = df["company"].apply(_clean)
    df["jobtitle"] = df["jobtitle"].apply(_clean)

    # Company must exist
    df = df[df["company"] != ""].copy()

    # Bucket + ranking
    df["Jobbezeichnung"] = df["jobtitle"].apply(lambda x: _bucket(x, lang))
    df["_prio"] = df["Jobbezeichnung"].apply(_bucket_prio)
    df["_sen"] = df["jobtitle"].apply(_seniority)
    df["_idx"] = range(len(df))  # stable tie-break

    # Sort so best candidates come first within company
    df = df.sort_values(
        ["company", "_prio", "_sen", "_idx"],
        ascending=[True, False, False, True],
        kind="mergesort",
    )

    # Keep max 2 per company
    df = df.groupby("company", as_index=False, sort=False).head(2)

    out = df.rename(columns={"company": "Unternehmensname"})[["Unternehmensname", "Jobbezeichnung"]]
    out = out.sort_values("Unternehmensname", key=lambda s: s.str.casefold(), kind="mergesort").reset_index(drop=True)
    return out