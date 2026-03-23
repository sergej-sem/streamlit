import re
from datetime import datetime


KNOWN_SEGMENT_CODES = {"BER", "DOR", "MUC"}


def normalize_segment_year(raw_year: str) -> str:
    if len(raw_year) == 4:
        return raw_year
    return f"20{raw_year}"


def extract_segment_code_and_year(segment_name: str) -> tuple[str, str]:
    tokens = [tok for tok in re.split(r"[^A-Za-z0-9]+", segment_name.upper()) if tok]

    for token in tokens:
        match = re.fullmatch(r"(?P<code>[A-Z]{3})(?P<year>\d{2}|\d{4})", token)
        if match:
            return match.group("code"), normalize_segment_year(match.group("year"))

        match = re.fullmatch(r"(?P<year>\d{2}|\d{4})(?P<code>[A-Z]{3})", token)
        if match:
            return match.group("code"), normalize_segment_year(match.group("year"))

    for left, right in zip(tokens, tokens[1:]):
        if re.fullmatch(r"[A-Z]{3}", left) and re.fullmatch(r"\d{2}|\d{4}", right):
            return left, normalize_segment_year(right)
        if re.fullmatch(r"\d{2}|\d{4}", left) and re.fullmatch(r"[A-Z]{3}", right):
            return right, normalize_segment_year(left)

    code = next((tok for tok in tokens if tok in KNOWN_SEGMENT_CODES), "")
    year_token = next((tok for tok in tokens if re.fullmatch(r"\d{2}|\d{4}", tok)), "")
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
