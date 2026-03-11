# badgegen/render_pdf.py

import os
from io import BytesIO
from typing import Dict, Any, List, Tuple

from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

# A6 hochkant
A6_W, A6_H = 105 * mm, 148 * mm

# A6 = 105 x 148 mm.  Header/Logo belegt ca. y > 118 mm.
# Alle vier Textfelder eng gruppiert unterhalb des Headers.
# Reihenfolge von oben nach unten: Vorname → Nachname → Firma → Jobtitel
# (x0, x1, y_bottom, y_top) in mm – ReportLab: y=0 ist unten
TEXT_BOXES_MM = {
    "firstname": (10.0, 95.0, 100.0, 112.0),
    "lastname":  (10.0, 95.0,  89.0,  99.0),
    "company":   (10.0, 95.0,  79.0,  88.0),
    "jobtitle":  (10.0, 95.0,  71.0,  78.0),
    "record_id": (10.0, 95.0,   2.0,   6.0),
}

# QR-Code: 30 mm Quadrat, horizontal zentriert, unterer Bereich
QR_BOX_MM = (37.5, 67.5, 10.0, 40.0)

# Fonts – Beispielbadge nutzt eine serifenlose Schrift (ähnlich Arial)
FONT_NAME_FIRST = "Helvetica-Bold"
FONT_NAME_LAST = "Helvetica-Bold"
FONT_NAME_COMPANY = "Helvetica-Bold"
FONT_NAME_JOB = "Helvetica"
FONT_NAME_ID = "Helvetica"

FONT_SIZE_FIRST_MAX = 52
FONT_SIZE_LAST_MAX = 48
FONT_SIZE_COMPANY_MAX = 40
FONT_SIZE_JOB_MAX = 30
FONT_SIZE_ID = 9

MIN_FONT_SIZE = 12

def _wrap_words(c: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> List[str]:
    if not text:
        return [""]
    words = text.split()
    lines: List[str] = []
    current = ""
    c.setFont(font, size)
    for w in words:
        test = (current + " " + w).strip()
        if c.stringWidth(test, font, size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines

def _text_height(font: str, size: int) -> float:
    ascent = pdfmetrics.getAscent(font) * size / 1000.0
    descent = pdfmetrics.getDescent(font) * size / 1000.0
    glyph_h = ascent - descent
    return glyph_h * 1.05

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
    text = (text or "").strip()
    if not text:
        return [""], max_size, _text_height(font, max_size)

    for size in range(max_size, min_size - 1, -1):
        lines = _wrap_words(c, text, font, size, max_width)
        if len(lines) > max_lines:
            continue
        c.setFont(font, size)
        if any(c.stringWidth(ln, font, size) > max_width for ln in lines):
            continue
        line_h = _text_height(font, size)
        if len(lines) * line_h <= max_height:
            return lines, size, line_h

    # Notfall: min_size + Ellipsis
    size = min_size
    c.setFont(font, size)
    line_h = _text_height(font, size)

    lines = _wrap_words(c, text, font, size, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines:
        last = lines[-1]
        while last and c.stringWidth(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
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

def _mm_box_to_points(box_mm: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    x0_mm, x1_mm, y0_mm, y1_mm = box_mm
    return x0_mm * mm, x1_mm * mm, y0_mm * mm, y1_mm * mm

def render_badges_pdf_bytes(
    rows: List[Dict[str, Any]],
    template_by_category: Dict[str, str],
    *,
    uppercase_names: bool,
    uppercase_company: bool,
    print_record_id: bool,
) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(A6_W, A6_H))

    box_first = _mm_box_to_points(TEXT_BOXES_MM["firstname"])
    box_last = _mm_box_to_points(TEXT_BOXES_MM["lastname"])
    box_job = _mm_box_to_points(TEXT_BOXES_MM["jobtitle"])
    box_company = _mm_box_to_points(TEXT_BOXES_MM["company"])
    box_id = _mm_box_to_points(TEXT_BOXES_MM["record_id"])

    for r in rows:
        cat = (r.get("kategorie") or "").strip()
        if not cat:
            raise ValueError("Kategorie fehlt.")
        if cat not in template_by_category:
            raise ValueError(f"Kein Template für Kategorie: {cat}")

        tpl = template_by_category[cat]
        if not os.path.exists(tpl):
            raise FileNotFoundError(f"Template-Datei nicht gefunden: {tpl}")

        c.drawImage(ImageReader(tpl), 0, 0, width=A6_W, height=A6_H, mask="auto")

        firstname = (r.get("firstname") or "").strip()
        lastname = (r.get("lastname") or "").strip()
        jobtitle = (r.get("jobtitle") or "").strip()
        company = (r.get("company") or "").strip()
        record_id = str(r.get("id") or "").strip()

        if uppercase_names:
            firstname = firstname.upper()
            lastname = lastname.upper()
        if uppercase_company:
            company = company.upper()

        # Vorname
        x0, x1, y0, y1 = box_first
        lines, size, lh = _fit_text_in_box(c, firstname, FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE, x1-x0, y1-y0, 2)
        _draw_centered_lines_in_box(c, lines, FONT_NAME_FIRST, size, x0, x1, y0, y1, lh)

        # Nachname
        x0, x1, y0, y1 = box_last
        lines, size, lh = _fit_text_in_box(c, lastname, FONT_NAME_LAST, FONT_SIZE_LAST_MAX, MIN_FONT_SIZE, x1-x0, y1-y0, 2)
        _draw_centered_lines_in_box(c, lines, FONT_NAME_LAST, size, x0, x1, y0, y1, lh)

        # Firma (3. von oben)
        x0, x1, y0, y1 = box_company
        lines, size, lh = _fit_text_in_box(c, company, FONT_NAME_COMPANY, FONT_SIZE_COMPANY_MAX, MIN_FONT_SIZE, x1-x0, y1-y0, 2)
        _draw_centered_lines_in_box(c, lines, FONT_NAME_COMPANY, size, x0, x1, y0, y1, lh)

        # Jobtitel (4. von oben)
        x0, x1, y0, y1 = box_job
        lines, size, lh = _fit_text_in_box(c, jobtitle, FONT_NAME_JOB, FONT_SIZE_JOB_MAX, MIN_FONT_SIZE, x1-x0, y1-y0, 2)
        _draw_centered_lines_in_box(c, lines, FONT_NAME_JOB, size, x0, x1, y0, y1, lh)

        # Datensatz-ID (Text)
        if print_record_id and record_id:
            x0, x1, y0, y1 = box_id
            lines, size, lh = _fit_text_in_box(
                c,
                record_id,
                FONT_NAME_ID,
                FONT_SIZE_ID,
                FONT_SIZE_ID,
                x1 - x0,
                y1 - y0,
                1,
            )
            _draw_centered_lines_in_box(
                c, lines, FONT_NAME_ID, size, x0, x1, y0, y1, lh
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

            qr_widget = qr.QrCodeWidget(qr_data)
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
            # leicht vom Rand einrücken
            renderPDF.draw(drawing, c, qx0, qy0)

        c.showPage()

    c.save()
    return buf.getvalue()
