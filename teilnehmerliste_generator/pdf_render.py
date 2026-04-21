import io
import math
from pathlib import Path
from typing import Tuple

import pandas as pd
from PIL import Image
from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# =========================
# Layout / Styling (aus deinem Skript)
# =========================
PAGE_W, PAGE_H = A4

BLUE = (39 / 255, 101 / 255, 174 / 255)
WHITE = (1, 1, 1)
BLACK = (0, 0, 0)

FONT_MAP_FILES = {
    "MyriadReg": "MyriadPro-Regular.ttf",
    "MyriadBold": "MyriadPro-Bold.ttf",
    "PlexReg": "IBMPlexSans.ttf",
    "PlexBold": "IBMPlexSans-Bold.ttf",
}

SEITE_X = 487.0355
SEITE_Y_TOP = 20.42044
SEITE_SIZE = 18.00678

STATUS_X = 15.75275
STATUS_Y_TOP = 78.09307
STATUS_SIZE = 10.99914

# Page 1
P1_COMPANY_X = 16.02060
P1_JOB_X = 310.82413
P1_FIRST_Y_COMPANY_TOP = 153.33754
P1_FIRST_Y_JOB_TOP = 152.63647
LINE_STEP = 19.50735
ROW_FONT_SIZE = 16.00353

# Page 2+
P2_COMPANY_X = 21.02682
P2_JOB_X = 310.11661
P2_FIRST_Y_COMPANY_TOP = 74.02731
P2_FIRST_Y_JOB_TOP = 76.18046
LINE_STEP_P2 = 19.50735

CAP_PAGE1 = 33
CAP_NEXT = 37

COLUMN_GAP_PADDING = 40
RIGHT_MARGIN = 20
TEMPLATE_IMAGE_MAX_WIDTH = 1200
TEMPLATE_IMAGE_JPEG_QUALITY = 80
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
MIN_ROW_FONT_SIZE = 11.0


def y_from_top(y_top: float) -> float:
    return PAGE_H - y_top


def try_register_fonts(font_dir: Path) -> Tuple[str, str, str, str]:
    """
    Nutzt deine Fonts, falls vorhanden – sonst Helvetica Fallback.
    """
    def reg(name: str, filename: str, fallback: str) -> str:
        fpath = font_dir / filename
        if fpath.exists():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(fpath)))
            return name
        return fallback

    myriad_reg = reg("MyriadPro-Regular", FONT_MAP_FILES["MyriadReg"], "Helvetica")
    myriad_bold = reg("MyriadPro-Bold", FONT_MAP_FILES["MyriadBold"], "Helvetica-Bold")
    plex_reg = reg("IBMPlexSans", FONT_MAP_FILES["PlexReg"], "Helvetica")
    plex_bold = reg("IBMPlexSans-Bold", FONT_MAP_FILES["PlexBold"], "Helvetica-Bold")
    return myriad_reg, myriad_bold, plex_reg, plex_bold


def string_width(txt: str, font_name: str, font_size: float) -> float:
    return pdfmetrics.stringWidth(txt, font_name, font_size)


def fit_text(txt: str, font_name: str, base_size: float, max_width: float, min_size: float = MIN_ROW_FONT_SIZE):
    """
    Fit by shrinking, then truncating with '…'
    """
    if not txt:
        return "", base_size

    size = base_size
    w = string_width(txt, font_name, size)
    if w <= max_width:
        return txt, size

    while size > min_size and w > max_width:
        size -= 0.5
        w = string_width(txt, font_name, size)

    if w <= max_width:
        return txt, size

    size = min_size
    ell = "…"
    t = txt
    while t and string_width(t + ell, font_name, size) > max_width:
        t = t[:-1]
    return (t + ell) if t else ell, size


def _calc_total_pages(n_rows: int) -> int:
    if n_rows <= CAP_PAGE1:
        return 1
    return 1 + math.ceil((n_rows - CAP_PAGE1) / CAP_NEXT)


def _chunk_rows(rows: list) -> list:
    pages = [rows[:CAP_PAGE1]]
    rest = rows[CAP_PAGE1:]
    for i in range(0, len(rest), CAP_NEXT):
        pages.append(rest[i:i + CAP_NEXT])
    return pages


def _company_max_width_for_page(page_idx: int) -> float:
    if page_idx == 0:
        return (P1_JOB_X - P1_COMPANY_X) - COLUMN_GAP_PADDING
    return (P2_JOB_X - P2_COMPANY_X) - COLUMN_GAP_PADDING


def _clean_company_name(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def collect_shrunk_company_names(df: pd.DataFrame, font_dir: Path) -> list[str]:
    """
    Return unique company names whose font size is reduced in the final PDF layout.
    The order follows the final PDF order.
    """
    myriad_reg, _myriad_bold, _plex_reg, _plex_bold = try_register_fonts(font_dir)

    rows = df[["Unternehmensname", "Jobbezeichnung"]].values.tolist()
    pages = _chunk_rows(rows)
    shrunk_names: list[str] = []
    seen: set[str] = set()

    for page_idx, page_rows in enumerate(pages):
        maxw_company = _company_max_width_for_page(page_idx)
        for company, _job in page_rows:
            company_name = _clean_company_name(company)
            if not company_name:
                continue

            _company_txt, company_size = fit_text(
                company_name,
                myriad_reg,
                ROW_FONT_SIZE,
                maxw_company,
            )
            if company_size >= ROW_FONT_SIZE:
                continue
            if company_name in seen:
                continue

            seen.add(company_name)
            shrunk_names.append(company_name)

    return shrunk_names


def build_template_image_reader(
    img_path: Path,
    max_width: int = TEMPLATE_IMAGE_MAX_WIDTH,
    jpeg_quality: int = TEMPLATE_IMAGE_JPEG_QUALITY,
) -> ImageReader:
    """
    Keep large page backgrounds compressed inside the PDF.
    The attendee text is drawn separately and stays sharp as vector text.
    """
    with Image.open(img_path) as im:
        im.load()
        rgb = im.convert("RGB")

        if max_width and rgb.width > max_width:
            target_height = round(rgb.height * (max_width / rgb.width))
            rgb = rgb.resize((max_width, target_height), LANCZOS)

        out = io.BytesIO()
        rgb.save(
            out,
            format="JPEG",
            quality=jpeg_quality,
            optimize=True,
            progressive=True,
        )
        out.seek(0)
        return ImageReader(out)


def generate_pdf_bytes(
    df: pd.DataFrame,
    template_p1: Path,
    template_p2: Path,
    font_dir: Path,
    lang: str = "de",
) -> bytes:
    """
    Erwartet df mit Spalten:
      - Unternehmensname
      - Jobbezeichnung  (C-Level/Fachbereich bzw. C-Level/Department)
    Rendert PDF (PNG Templates als Hintergrund) und gibt Bytes zurück.
    """

    if lang not in ("de", "en"):
        raise ValueError("lang must be 'de' or 'en'")

    page_word = "Seite" if lang == "de" else "page"
    people_word = "Anwender" if lang == "de" else "delegates"

    # sanity checks
    for p in [template_p1, template_p2]:
        if not p.exists():
            raise FileNotFoundError(f"Template not found: {p}")
        with Image.open(p) as im:
            im.verify()

    myriad_reg, _myriad_bold, plex_reg, plex_bold = try_register_fonts(font_dir)
    template_p1_reader = build_template_image_reader(template_p1)
    template_p2_reader = build_template_image_reader(template_p2)

    rows = df[["Unternehmensname", "Jobbezeichnung"]].values.tolist()
    n = len(rows)
    total_pages = _calc_total_pages(n)
    pages = _chunk_rows(rows)

    maxw_job = (PAGE_W - RIGHT_MARGIN) - P2_JOB_X

    prev_use_a85 = getattr(rl_config, "useA85", 1)
    rl_config.useA85 = 0

    try:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)

        def draw_bg(img_reader: ImageReader):
            c.drawImage(
                img_reader,
                0, 0,
                width=PAGE_W,
                height=PAGE_H,
                preserveAspectRatio=False,
                mask="auto",
            )

        for page_idx in range(total_pages):
            is_first = page_idx == 0
            draw_bg(template_p1_reader if is_first else template_p2_reader)

            # Seite/page x/y
            c.setFont(plex_bold, SEITE_SIZE)
            c.setFillColorRGB(*BLUE)
            c.drawString(SEITE_X, y_from_top(SEITE_Y_TOP), f"{page_word} {page_idx + 1}/{total_pages}")

            # Status nur Seite 1
            if is_first:
                c.setFont(plex_reg, STATUS_SIZE)
                c.setFillColorRGB(*WHITE)
                c.drawString(STATUS_X, y_from_top(STATUS_Y_TOP), f"Status: {n} {people_word}")

            c.setFillColorRGB(*BLACK)

            page_rows = pages[page_idx] if page_idx < len(pages) else []

            if is_first:
                base_x_company = P1_COMPANY_X
                base_x_job = P1_JOB_X
                first_y_company = P1_FIRST_Y_COMPANY_TOP
                first_y_job = P1_FIRST_Y_JOB_TOP
                step = LINE_STEP
            else:
                base_x_company = P2_COMPANY_X
                base_x_job = P2_JOB_X
                first_y_company = P2_FIRST_Y_COMPANY_TOP
                first_y_job = P2_FIRST_Y_JOB_TOP
                step = LINE_STEP_P2
            maxw_company = _company_max_width_for_page(page_idx)

            for i, (company, job) in enumerate(page_rows):
                y_company = y_from_top(first_y_company + i * step)
                y_job = y_from_top(first_y_job + i * step)

                company_txt, company_size = fit_text(str(company), myriad_reg, ROW_FONT_SIZE, maxw_company)
                job_txt, job_size = fit_text(str(job), myriad_reg, ROW_FONT_SIZE, maxw_job)

                c.setFont(myriad_reg, company_size)
                c.drawString(base_x_company, y_company, company_txt)

                c.setFont(myriad_reg, job_size)
                c.drawString(base_x_job, y_job, job_txt)

            c.showPage()

        c.save()
        return buf.getvalue()
    finally:
        rl_config.useA85 = prev_use_a85
