import re
from datetime import datetime


KNOWN_SEGMENT_CODES = {"BER", "DOR", "MUC"}
CODE_YEAR_RE = re.compile(r"(?P<code>[A-Z]{3})(?P<year>\d{2}|\d{4})")
YEAR_CODE_RE = re.compile(r"(?P<year>\d{2}|\d{4})(?P<code>[A-Z]{3})")
CODE_TOKEN_RE = re.compile(r"[A-Z]{3}")
YEAR_TOKEN_RE = re.compile(r"\d{2}|\d{4}")


def normalize_segment_year(raw_year: str) -> str:
    if len(raw_year) == 4:
        return raw_year
    return f"20{raw_year}"


def _segment_tokens(segment_name: str) -> list[str]:
    return [tok for tok in re.split(r"[^A-Za-z0-9]+", segment_name.upper()) if tok]


def _match_compound_token(token: str) -> tuple[str, str]:
    match = CODE_YEAR_RE.fullmatch(token)
    if match:
        return match.group("code"), normalize_segment_year(match.group("year"))

    match = YEAR_CODE_RE.fullmatch(token)
    if match:
        return match.group("code"), normalize_segment_year(match.group("year"))

    return "", ""


def _is_code_token(token: str) -> bool:
    return CODE_TOKEN_RE.fullmatch(token) is not None


def _is_year_token(token: str) -> bool:
    return YEAR_TOKEN_RE.fullmatch(token) is not None


def extract_segment_code_and_year(segment_name: str) -> tuple[str, str]:
    tokens = _segment_tokens(segment_name)

    for token in tokens:
        code, year = _match_compound_token(token)
        if code and year:
            return code, year

    for left, right in zip(tokens, tokens[1:]):
        if _is_code_token(left) and _is_year_token(right):
            return left, normalize_segment_year(right)
        if _is_year_token(left) and _is_code_token(right):
            return right, normalize_segment_year(left)

    code = next((tok for tok in tokens if tok in KNOWN_SEGMENT_CODES), "")
    year_token = next((tok for tok in tokens if _is_year_token(tok)), "")
    year = normalize_segment_year(year_token) if year_token else ""
    return code, year


def build_pdf_filename(segment_name: str, lang: str, encrypt: bool) -> str:
    code, year = extract_segment_code_and_year(segment_name)
    event_part = f"{code}{year}"
    date_part = datetime.now().strftime("%d%m%Y")

    parts = ["mse", "Teilnehmerliste"]
    if event_part:
        parts.append(event_part)
    if lang:
        parts.append(lang.upper())
    parts.append(date_part)
    if encrypt:
        parts.append("PW")

    return f"{'_'.join(parts)}.pdf"
