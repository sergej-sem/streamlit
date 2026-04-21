# badgegen/render_pdf.py

import os
import re
import unicodedata
from io import BytesIO
from typing import Dict, Any, List, Tuple

from badgegen.category import ALLOWED_CATEGORIES
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

# A6 hochkant
A6_W, A6_H = 105 * mm, 148 * mm

# A6 = 105 x 148 mm.  Header/Logo belegt ca. y > 118 mm.
# Reihenfolge von oben nach unten: Vorname → Nachname → Jobtitel → (Abstand) → Firma
# (x0, x1, y_bottom, y_top) in mm – ReportLab: y=0 ist unten
TEXT_BOXES_MM = {
    "firstname": (10.0, 95.0, 100.0, 112.0),  # oben dominant
    "lastname":  (10.0, 95.0,  89.0,  99.0),  # direkt darunter
    "jobtitle":  (10.0, 95.0,  79.0,  88.0),  # direkt unter Nachname (1 mm Abstand)
    "company":   (10.0, 95.0,  52.0,  67.0),  # deutlich tiefer, klar getrennt vom Jobtitel
}

# QR-Code: 30 mm Quadrat, horizontal zentriert, unterer Bereich
QR_BOX_MM = (37.5, 67.5, 10.0, 40.0)

# ---------------------------------------------------------------------------
# QR-Code-Farben je Kategorie
# Nur dunkle Farben, damit der QR-Code sicher scannbar bleibt.
# Standardfarbe ist schwarz (colored=False oder unbekannte Kategorie).
# ---------------------------------------------------------------------------
_QR_COLOR_BY_CATEGORY = {
    "TN":      colors.HexColor("#1a7a1a"),  # dunkelgrün
    "VIP/REF": colors.HexColor("#B8860B"),  # dunkles Gold
    "Sponsor": colors.black,
    "BEO":     colors.HexColor("#660099"),  # dunkelviolett
    "Team":    colors.HexColor("#cc0000"),  # dunkelrot
}
_QR_COLOR_DEFAULT = colors.black


def _qr_color_for_category(kategorie: str, colored: bool) -> object:
    """Gibt die QR-Vordergrundfarbe für eine Kategorie zurück.
    Bei colored=False oder unbekannter Kategorie immer schwarz."""
    if not colored:
        return _QR_COLOR_DEFAULT
    return _QR_COLOR_BY_CATEGORY.get((kategorie or "").strip(), _QR_COLOR_DEFAULT)


# ---------------------------------------------------------------------------
# Font-Registrierung mit Fallback-Kette
#
# Priorität:
#   1. assets/fonts/ im Projekt-Repo (gebündelte Badge-Fonts für stabile Unicode-Darstellung)
#   2. Windows-Systemfonts (Arial Bold / Arial Regular)
#   3. ReportLab-eigene gebündelte Fonts (Vera Bold / Vera Regular)
#   4. Built-in-Fallback: Helvetica-Bold / Helvetica (immer verfügbar)
#
# Hinweis: Stufe 2 funktioniert nur auf Windows. Stufen 3 und 4 sind
# plattformunabhängig und stellen sicher, dass der Renderer nie abstürzt.
# ---------------------------------------------------------------------------

def _find_first_existing(*paths: str) -> str | None:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def _badge_font_paths() -> tuple[str | None, str | None]:
    # Repo-Root: render_pdf.py liegt in badgegen/, Root ist eine Ebene höher
    _repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    _repo_fonts = os.path.join(_repo_root, "assets", "fonts")

    # Windows-Systemfonts
    _win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

    # ReportLab-eigene gebündelte Fonts
    import reportlab as _rl
    _rl_fonts = os.path.join(os.path.dirname(_rl.__file__), "fonts")

    heavy_path = _find_first_existing(
        # 1. Repo: erwarte dort z. B. "Badge-Heavy.ttf" o.ä.
        os.path.join(_repo_fonts, "Badge-Heavy.ttf"),
        # 2. Windows: Arial Bold
        os.path.join(_win_fonts, "arialbd.ttf"),
        # 3. ReportLab gebündelt: Vera Bold
        os.path.join(_rl_fonts, "VeraBd.ttf"),
    )
    regular_path = _find_first_existing(
        os.path.join(_repo_fonts, "Badge-Regular.ttf"),
        os.path.join(_win_fonts, "arial.ttf"),
        os.path.join(_rl_fonts, "Vera.ttf"),
    )
    return heavy_path, regular_path


def _register_badge_fonts() -> tuple[str, str]:
    """
    Registriert die beste verfügbare Bold/Regular Sans-Serif-Kombination.
    Gibt (heavy_font_name, regular_font_name) zurück.
    """
    heavy_path, regular_path = _badge_font_paths()

    heavy = "Helvetica-Bold"
    regular = "Helvetica"

    if heavy_path:
        if "BadgeHeavy" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("BadgeHeavy", heavy_path))
        heavy = "BadgeHeavy"
    if regular_path:
        if "BadgeRegular" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("BadgeRegular", regular_path))
        regular = "BadgeRegular"

    return heavy, regular


def badge_font_cache_token() -> tuple[str, int, str, int]:
    heavy_path, regular_path = _badge_font_paths()
    return (
        heavy_path or "",
        int(os.path.getmtime(heavy_path)) if heavy_path and os.path.exists(heavy_path) else 0,
        regular_path or "",
        int(os.path.getmtime(regular_path)) if regular_path and os.path.exists(regular_path) else 0,
    )


def _normalize_badge_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    # NFC folds decomposed sequences like "O\u0308" into precomposed glyphs like "Ö".
    # That keeps umlauts stable across local Windows fonts and Linux/Cloud fallbacks.
    return unicodedata.normalize("NFC", text)


def _company_sort_key(value: str | None) -> tuple[int, str]:
    normalized = _normalize_badge_text(value)
    if not normalized:
        return 1, ""
    return 0, normalized.casefold()


def _sorted_badge_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    known_category_order = {category: index for index, category in enumerate(ALLOWED_CATEGORIES)}
    unknown_category_order: dict[str, int] = {}

    for row in rows:
        category = (row.get("kategorie") or "").strip()
        if category in known_category_order or category in unknown_category_order:
            continue
        unknown_category_order[category] = len(unknown_category_order)

    def _sort_key(row: Dict[str, Any]) -> tuple[int, int, tuple[int, str]]:
        category = (row.get("kategorie") or "").strip()
        known_rank = known_category_order.get(category)
        if known_rank is not None:
            return 0, known_rank, _company_sort_key(row.get("company"))
        return 1, unknown_category_order[category], _company_sort_key(row.get("company"))

    return sorted(rows, key=_sort_key)


_FONT_HEAVY, _FONT_REGULAR = _register_badge_fonts()

FONT_NAME_FIRST   = _FONT_HEAVY
FONT_NAME_LAST    = _FONT_HEAVY
FONT_NAME_COMPANY = _FONT_HEAVY
FONT_NAME_JOB     = _FONT_REGULAR


def _refresh_registered_badge_fonts() -> None:
    global _FONT_HEAVY, _FONT_REGULAR
    global FONT_NAME_FIRST, FONT_NAME_LAST, FONT_NAME_COMPANY, FONT_NAME_JOB

    heavy, regular = _register_badge_fonts()
    if heavy == _FONT_HEAVY and regular == _FONT_REGULAR:
        return

    _FONT_HEAVY = heavy
    _FONT_REGULAR = regular
    FONT_NAME_FIRST = heavy
    FONT_NAME_LAST = heavy
    FONT_NAME_COMPANY = heavy
    FONT_NAME_JOB = regular

FONT_SIZE_FIRST_MAX   = 52
FONT_SIZE_LAST_MAX    = 48
FONT_SIZE_COMPANY_MAX = 40
FONT_SIZE_JOB_MAX     = 30

MIN_FONT_SIZE = 10
MIN_FONT_SIZE_JOB = 8

MAX_LINES_FIRST = 2
MAX_LINES_LAST = 2
MAX_LINES_COMPANY = 3
MAX_LINES_JOB = 3

JOBTITLE_GAP_TARGET_MM = 5.0
JOBTITLE_GAP_MIN_MM = 3.5
JOBTITLE_GAP_TARGET = JOBTITLE_GAP_TARGET_MM * mm
JOBTITLE_GAP_MIN = JOBTITLE_GAP_MIN_MM * mm


def _wrap_segments(text: str) -> List[Tuple[str, bool]]:
    segments: List[Tuple[str, bool]] = []
    for word in text.split():
        parts = re.split(r"(-)", word)
        first_segment = True
        current = ""

        for part in parts:
            if not part:
                continue
            current += part
            if part == "-":
                segments.append((current, first_segment))
                current = ""
                first_segment = False

        if current:
            segments.append((current, first_segment))

    return segments


def _wrap_words(c: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> List[str]:
    if not text:
        return [""]
    segments = _wrap_segments(text)
    if not segments:
        return [text]
    lines: List[str] = []
    current = ""
    c.setFont(font, size)
    for segment, add_space in segments:
        test = current + ((" " + segment) if (current and add_space) else segment)
        if c.stringWidth(test, font, size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = segment
    if current:
        lines.append(current)
    return lines


def _text_height(font: str, size: int) -> float:
    ascent = pdfmetrics.getAscent(font) * size / 1000.0
    descent = pdfmetrics.getDescent(font) * size / 1000.0
    glyph_h = ascent - descent
    return glyph_h * 1.05


def _fit_text_in_box_details(
    c: canvas.Canvas,
    text: str,
    font: str,
    max_size: int,
    min_size: int,
    max_width: float,
    max_height: float,
    max_lines: int,
) -> Tuple[List[str], int, float, bool]:
    text = (text or "").strip()
    if not text:
        line_h = _text_height(font, max_size)
        return [""], max_size, line_h, True

    for size in range(max_size, min_size - 1, -1):
        lines = _wrap_words(c, text, font, size, max_width)
        if len(lines) > max_lines:
            continue
        c.setFont(font, size)
        if any(c.stringWidth(ln, font, size) > max_width for ln in lines):
            continue
        line_h = _text_height(font, size)
        if len(lines) * line_h <= max_height:
            return lines, size, line_h, True

    # Notfall: min_size + Ellipsis
    size = min_size
    c.setFont(font, size)
    line_h = _text_height(font, size)
    max_lines_by_height = max(1, int(max_height // line_h)) if line_h > 0 else 1
    effective_max_lines = min(max_lines, max_lines_by_height)

    wrapped_lines = _wrap_words(c, text, font, size, max_width)
    truncated = len(wrapped_lines) > effective_max_lines
    lines = wrapped_lines[:effective_max_lines]
    needs_ellipsis = truncated or any(c.stringWidth(ln, font, size) > max_width for ln in lines)
    if lines and needs_ellipsis:
        last = lines[-1]
        while last and c.stringWidth(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
    fits_without_truncation = (not needs_ellipsis) and (len(lines) * line_h <= max_height)
    return lines, size, line_h, fits_without_truncation


def _fit_text_in_box(
    c: canvas.Canvas,
    text: str,
    font: str,
    max_size: int,
    min_size: int,
    max_width: float,
    max_height: float,
    max_lines: int,
) -> Tuple[List[str], int, float]:
    lines, size, line_h, _ = _fit_text_in_box_details(
        c, text, font, max_size, min_size, max_width, max_height, max_lines
    )
    return lines, size, line_h


def _draw_centered_lines_in_box(
    c: canvas.Canvas,
    lines: List[str],
    font: str,
    size: int,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    line_h: float,
):
    x_center = (x0 + x1) / 2.0
    box_center_y = (y0 + y1) / 2.0
    total_h = len(lines) * line_h

    ascent = pdfmetrics.getAscent(font) * size / 1000.0
    y_top = box_center_y + (total_h / 2.0)
    baseline = y_top - ascent

    c.setFont(font, size)
    for i, ln in enumerate(lines):
        c.drawCentredString(x_center, baseline - i * line_h, ln)


def _centered_block_edges(y0: float, y1: float, line_h: float, line_count: int) -> Tuple[float, float]:
    box_center_y = (y0 + y1) / 2.0
    total_h = line_count * line_h
    return box_center_y + (total_h / 2.0), box_center_y - (total_h / 2.0)


def _jobtitle_box_between(
    default_box: Tuple[float, float, float, float],
    *,
    upper_bottom: float | None,
    lower_top: float | None,
) -> Tuple[float, float, float, float]:
    if upper_bottom is None or lower_top is None:
        return default_box

    if upper_bottom <= lower_top:
        return default_box

    return default_box[0], default_box[1], lower_top, upper_bottom


def _jobtitle_box_with_gap(
    default_box: Tuple[float, float, float, float],
    *,
    upper_bottom: float | None,
    lower_top: float | None,
    gap: float,
) -> Tuple[float, float, float, float] | None:
    if upper_bottom is None or lower_top is None:
        return None

    if upper_bottom <= lower_top:
        return None

    y0 = lower_top + gap
    y1 = upper_bottom - gap
    if y1 <= y0:
        return None

    return default_box[0], default_box[1], y0, y1


def _mm_box_to_points(box_mm: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    x0_mm, x1_mm, y0_mm, y1_mm = box_mm
    return x0_mm * mm, x1_mm * mm, y0_mm * mm, y1_mm * mm


def render_badges_pdf_bytes(
    rows: List[Dict[str, Any]],
    template_by_category: Dict[str, str],
    *,
    uppercase_names: bool,
    uppercase_company: bool,
    colored_qr: bool = True,
) -> bytes:
    _refresh_registered_badge_fonts()

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(A6_W, A6_H))

    box_first   = _mm_box_to_points(TEXT_BOXES_MM["firstname"])
    box_last    = _mm_box_to_points(TEXT_BOXES_MM["lastname"])
    box_job     = _mm_box_to_points(TEXT_BOXES_MM["jobtitle"])
    box_company = _mm_box_to_points(TEXT_BOXES_MM["company"])

    for r in _sorted_badge_rows(rows):
        cat = (r.get("kategorie") or "").strip()
        if not cat:
            raise ValueError("Kategorie fehlt.")
        if cat not in template_by_category:
            raise ValueError(f"Kein Template für Kategorie: {cat}")

        tpl = template_by_category[cat]
        if not os.path.exists(tpl):
            raise FileNotFoundError(f"Template-Datei nicht gefunden: {tpl}")

        c.drawImage(ImageReader(tpl), 0, 0, width=A6_W, height=A6_H, mask="auto")

        firstname = _normalize_badge_text(r.get("firstname"))
        lastname  = _normalize_badge_text(r.get("lastname"))
        jobtitle  = _normalize_badge_text(r.get("jobtitle"))
        company   = _normalize_badge_text(r.get("company"))
        record_id = str(r.get("id") or "").strip()

        if uppercase_names:
            firstname = firstname.upper()
            lastname  = lastname.upper()
        if uppercase_company:
            company = company.upper()

        first_lines, first_size, first_lh = _fit_text_in_box(
            c, firstname, FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE, box_first[1] - box_first[0], box_first[3] - box_first[2], MAX_LINES_FIRST
        )
        last_lines, last_size, last_lh = _fit_text_in_box(
            c, lastname, FONT_NAME_LAST, FONT_SIZE_LAST_MAX, MIN_FONT_SIZE, box_last[1] - box_last[0], box_last[3] - box_last[2], MAX_LINES_LAST
        )
        company_lines, company_size, company_lh = _fit_text_in_box(
            c, company, FONT_NAME_COMPANY, FONT_SIZE_COMPANY_MAX, MIN_FONT_SIZE, box_company[1] - box_company[0], box_company[3] - box_company[2], MAX_LINES_COMPANY
        )

        name_bottom = None
        if lastname:
            _, name_bottom = _centered_block_edges(box_last[2], box_last[3], last_lh, len(last_lines))
        elif firstname:
            _, name_bottom = _centered_block_edges(box_first[2], box_first[3], first_lh, len(first_lines))

        company_top = None
        if company:
            company_top, _ = _centered_block_edges(box_company[2], box_company[3], company_lh, len(company_lines))

        if name_bottom is None or company_top is None or name_bottom <= company_top:
            job_box = box_job
            job_lines, job_size, job_lh = _fit_text_in_box(
                c,
                jobtitle,
                FONT_NAME_JOB,
                FONT_SIZE_JOB_MAX,
                MIN_FONT_SIZE_JOB,
                job_box[1] - job_box[0],
                job_box[3] - job_box[2],
                MAX_LINES_JOB,
            )
        else:
            full_job_box = _jobtitle_box_between(box_job, upper_bottom=name_bottom, lower_top=company_top)
            chosen_job = None

            for gap in (JOBTITLE_GAP_TARGET, JOBTITLE_GAP_MIN):
                candidate_box = _jobtitle_box_with_gap(
                    box_job,
                    upper_bottom=name_bottom,
                    lower_top=company_top,
                    gap=gap,
                )
                if candidate_box is None:
                    continue
                candidate_lines, candidate_size, candidate_lh, fits_without_truncation = _fit_text_in_box_details(
                    c,
                    jobtitle,
                    FONT_NAME_JOB,
                    FONT_SIZE_JOB_MAX,
                    MIN_FONT_SIZE_JOB,
                    candidate_box[1] - candidate_box[0],
                    candidate_box[3] - candidate_box[2],
                    MAX_LINES_JOB,
                )
                if fits_without_truncation:
                    chosen_job = (candidate_box, candidate_lines, candidate_size, candidate_lh)
                    break

            if chosen_job is None:
                job_lines, job_size, job_lh, _ = _fit_text_in_box_details(
                    c,
                    jobtitle,
                    FONT_NAME_JOB,
                    FONT_SIZE_JOB_MAX,
                    MIN_FONT_SIZE_JOB,
                    full_job_box[1] - full_job_box[0],
                    full_job_box[3] - full_job_box[2],
                    MAX_LINES_JOB,
                )
                job_box = full_job_box
            else:
                job_box, job_lines, job_size, job_lh = chosen_job

        _draw_centered_lines_in_box(c, first_lines, FONT_NAME_FIRST, first_size, box_first[0], box_first[1], box_first[2], box_first[3], first_lh)
        _draw_centered_lines_in_box(c, last_lines, FONT_NAME_LAST, last_size, box_last[0], box_last[1], box_last[2], box_last[3], last_lh)
        _draw_centered_lines_in_box(c, job_lines, FONT_NAME_JOB, job_size, job_box[0], job_box[1], job_box[2], job_box[3], job_lh)
        _draw_centered_lines_in_box(
            c,
            company_lines,
            FONT_NAME_COMPANY,
            company_size,
            box_company[0],
            box_company[1],
            box_company[2],
            box_company[3],
            company_lh,
        )

        # QR-Code (kodiert die Datensatz-ID, falls vorhanden, sonst Name+Firma)
        qr_data = record_id or " ".join(
            part
            for part in [firstname, lastname, company]
            if part
        )
        if qr_data:
            qx0, qx1, qy0, qy1 = _mm_box_to_points(QR_BOX_MM)
            qr_box_w = qx1 - qx0
            qr_box_h = qy1 - qy0
            qr_size = min(qr_box_w, qr_box_h)

            qr_color = _qr_color_for_category(cat, colored_qr)
            qr_widget = qr.QrCodeWidget(qr_data, barFillColor=qr_color)
            bounds = qr_widget.getBounds()
            w = bounds[2] - bounds[0]
            h = bounds[3] - bounds[1]

            # Skalierung über den Drawing-Transform, nicht über das Widget
            if w > 0 and h > 0:
                scale = qr_size / max(w, h)
                drawing = Drawing(
                    qr_size,
                    qr_size,
                    transform=[scale, 0, 0, scale, 0, 0],
                )
            else:
                drawing = Drawing(qr_size, qr_size)

            drawing.add(qr_widget)
            renderPDF.draw(drawing, c, qx0, qy0)

        c.showPage()

    c.save()
    return buf.getvalue()
