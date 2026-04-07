# tests/test_badgegen_render_pdf.py
"""
Robuste Tests für badgegen/render_pdf.py.

Strategie:
- Keine Annahmen über exakte Fontgrößen-Werte (font metrics variieren je nach
  registriertem Font / Fallback).
- Geprüft werden: Stabiles Verhalten, keine Abstürze, korrekte Wertebereiche,
  Nicht-Überlauf (Texte passen in die Box), valide PDF-Bytes.
"""

import io
import os
import sys
import unittest
from unittest.mock import patch

# Projekt-Root ins sys.path eintragen (tests/ liegt eine Ebene unter Root)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

import badgegen.render_pdf as render_pdf_module
from reportlab.pdfgen import canvas as rl_canvas

from reportlab.lib import colors as rl_colors
from reportlab.lib.utils import ImageReader

from badgegen.render_pdf import (
    MIN_FONT_SIZE,
    MIN_FONT_SIZE_JOB,
    FONT_NAME_FIRST,
    FONT_NAME_LAST,
    FONT_NAME_COMPANY,
    FONT_NAME_JOB,
    FONT_SIZE_FIRST_MAX,
    FONT_SIZE_LAST_MAX,
    FONT_SIZE_COMPANY_MAX,
    FONT_SIZE_JOB_MAX,
    TEXT_BOXES_MM,
    _QR_COLOR_BY_CATEGORY,
    _QR_COLOR_DEFAULT,
    _centered_block_edges,
    _fit_text_in_box,
    _jobtitle_box_between,
    _jobtitle_box_with_gap,
    _mm_box_to_points,
    _qr_color_for_category,
    _wrap_words,
    JOBTITLE_GAP_MIN,
    JOBTITLE_GAP_TARGET,
    badge_font_cache_token,
    _normalize_badge_text,
    render_badges_pdf_bytes,
)
from reportlab.lib.units import mm


# ---------------------------------------------------------------------------
# Hilfsfunktion: minimaler Canvas für Tests (kein echtes PDF nötig)
# ---------------------------------------------------------------------------

def _make_canvas() -> rl_canvas.Canvas:
    buf = io.BytesIO()
    return rl_canvas.Canvas(buf)


class BadgeFontRegistrationTests(unittest.TestCase):

    def test_repo_badge_fonts_are_registered(self):
        self.assertEqual("BadgeHeavy", render_pdf_module._FONT_HEAVY)
        self.assertEqual("BadgeRegular", render_pdf_module._FONT_REGULAR)

    def test_repo_badge_font_files_exist(self):
        repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        self.assertTrue(os.path.isfile(os.path.join(repo_root, "assets", "fonts", "Badge-Heavy.ttf")))
        self.assertTrue(os.path.isfile(os.path.join(repo_root, "assets", "fonts", "Badge-Regular.ttf")))

    def test_badge_font_cache_token_uses_repo_fonts(self):
        heavy_path, heavy_mtime, regular_path, regular_mtime = badge_font_cache_token()
        self.assertTrue(heavy_path.endswith(os.path.join("assets", "fonts", "Badge-Heavy.ttf")))
        self.assertTrue(regular_path.endswith(os.path.join("assets", "fonts", "Badge-Regular.ttf")))
        self.assertGreater(heavy_mtime, 0)
        self.assertGreater(regular_mtime, 0)


class BadgeTextNormalizationTests(unittest.TestCase):

    def test_normalize_badge_text_compose_umlauts(self):
        self.assertEqual("GÖRGÜLÜ", _normalize_badge_text("GO\u0308RGU\u0308LU\u0308"))
        self.assertEqual("Müller", _normalize_badge_text("Mu\u0308ller"))
        self.assertEqual("für", _normalize_badge_text("fu\u0308r"))

    def test_render_normalizes_combining_umlauts_before_drawing(self):
        import tempfile
        from PIL import Image as _PilImage

        with tempfile.TemporaryDirectory() as tmpdir:
            tpl_path = os.path.join(tmpdir, "dummy.png")
            img = _PilImage.new("RGB", (10, 10), color=(255, 255, 255))
            img.save(tpl_path, format="PNG")
            tpl_map = {cat: tpl_path for cat in TEMPLATE_CATEGORIES}

            row = {
                "id": "1",
                "firstname": "Kemal",
                "lastname": "GO\u0308RGU\u0308LU\u0308",
                "jobtitle": "Chief Technology Officer",
                "company": "ARTE",
                "kategorie": "TN",
            }

            original_draw = render_pdf_module._draw_centered_lines_in_box
            draw_calls: list[list[str]] = []

            def tracking_draw(*args, **kwargs):
                draw_calls.append(list(args[1]))
                return original_draw(*args, **kwargs)

            with patch("badgegen.render_pdf._draw_centered_lines_in_box", side_effect=tracking_draw):
                result = render_badges_pdf_bytes(
                    rows=[row],
                    template_by_category=tpl_map,
                    uppercase_names=False,
                    uppercase_company=False,
                    colored_qr=True,
                )

            self.assertTrue(result.startswith(b"%PDF"))
            self.assertIn(["GÖRGÜLÜ"], draw_calls)


# ---------------------------------------------------------------------------
# Tests: _fit_text_in_box
# ---------------------------------------------------------------------------

class FitTextInBoxTests(unittest.TestCase):

    def setUp(self):
        self.c = _make_canvas()
        # Breite/Höhe der firstname-Box (größte Box) in Points
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["firstname"]
        self.box_w = (x1 - x0) * mm
        self.box_h = (y1_mm - y0_mm) * mm

    # --- Leerer Text: kein Absturz, gibt max_size zurück ----

    def test_empty_text_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertIsInstance(lines, list)
        self.assertGreater(lh, 0)

    def test_whitespace_only_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "   ", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertIsInstance(lines, list)

    # --- Kurzer Text: Größe im gültigen Bereich ---

    def test_short_text_size_in_range(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "MAX", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)
        self.assertLessEqual(size, FONT_SIZE_FIRST_MAX)
        self.assertGreater(lh, 0)

    def test_short_text_fits_large(self):
        """Kurzer Text soll eine deutlich größere Schrift bekommen als langer."""
        _, size_short, _ = _fit_text_in_box(
            self.c, "Max", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        _, size_long, _ = _fit_text_in_box(
            self.c, "Maximilian Alexander", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size_short, size_long,
            "Kurzer Text muss eine größere oder gleiche Schrift erhalten als langer Text")

    # --- Langer Text: Größe ≥ MIN_FONT_SIZE, kein Absturz ---

    def test_long_name_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "Maximilian Alexander", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)
        self.assertLessEqual(size, FONT_SIZE_FIRST_MAX)

    def test_very_long_lastname_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "von Hohenstein-Falkenried", FONT_NAME_LAST, FONT_SIZE_LAST_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)

    def test_long_jobtitle_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "Senior Vice President Business Development",
            FONT_NAME_JOB, FONT_SIZE_JOB_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)
        self.assertLessEqual(size, FONT_SIZE_JOB_MAX)

    def test_very_long_company_no_crash(self):
        lines, size, lh = _fit_text_in_box(
            self.c, "International Cyber Security Solutions Group",
            FONT_NAME_COMPANY, FONT_SIZE_COMPANY_MAX, MIN_FONT_SIZE,
            self.box_w, self.box_h, 2
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)

    def test_hyphenated_lastname_fits_without_ellipsis(self):
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["lastname"]
        box_w = (x1 - x0) * mm
        box_h = (y1_mm - y0_mm) * mm
        lines, size, _ = _fit_text_in_box(
            self.c,
            "Freiherr von Muenchhausen-Wolfsberg-Hohenried-Altenburg",
            FONT_NAME_LAST,
            FONT_SIZE_LAST_MAX,
            MIN_FONT_SIZE,
            box_w,
            box_h,
            2,
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)
        self.assertFalse(any("…" in ln for ln in lines))

    def test_long_company_can_use_three_lines_without_ellipsis(self):
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["company"]
        box_w = (x1 - x0) * mm
        box_h = (y1_mm - y0_mm) * mm
        lines, size, _ = _fit_text_in_box(
            self.c,
            "Internationale Gesellschaft fuer Unternehmensberatung und Strategieentwicklung GmbH & Co. KG",
            FONT_NAME_COMPANY,
            FONT_SIZE_COMPANY_MAX,
            MIN_FONT_SIZE,
            box_w,
            box_h,
            3,
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE)
        self.assertLessEqual(len(lines), 3)
        self.assertFalse(any("…" in ln for ln in lines))

    def test_long_jobtitle_can_use_smaller_font_and_no_ellipsis(self):
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["jobtitle"]
        box_w = (x1 - x0) * mm
        box_h = (y1_mm - y0_mm) * mm
        lines, size, _ = _fit_text_in_box(
            self.c,
            "Senior Vice President International Business Development and Strategic Partnerships and Alliances",
            FONT_NAME_JOB,
            FONT_SIZE_JOB_MAX,
            MIN_FONT_SIZE_JOB,
            box_w,
            box_h,
            3,
        )
        self.assertGreaterEqual(size, MIN_FONT_SIZE_JOB)
        self.assertLessEqual(len(lines), 3)
        self.assertFalse(any("…" in ln for ln in lines))

    def test_long_jobtitle_can_use_three_lines_at_min_font_without_ellipsis(self):
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["jobtitle"]
        box_w = ((x1 - x0) * mm) - 50
        box_h = (y1_mm - y0_mm) * mm
        lines, size, _ = _fit_text_in_box(
            self.c,
            "Senior Vice President International Business Development and Strategic Partnerships and Alliances",
            FONT_NAME_JOB,
            FONT_SIZE_JOB_MAX,
            MIN_FONT_SIZE_JOB,
            box_w,
            box_h,
            3,
        )
        self.assertEqual(size, MIN_FONT_SIZE_JOB)
        self.assertLessEqual(len(lines), 3)
        self.assertFalse(any("…" in ln for ln in lines))

    # --- Max-Lines-Constraint: nie mehr als max_lines Zeilen ---

    def test_max_lines_respected(self):
        for max_lines in (1, 2):
            with self.subTest(max_lines=max_lines):
                lines, _, _ = _fit_text_in_box(
                    self.c, "International Cyber Security Solutions Group",
                    FONT_NAME_COMPANY, FONT_SIZE_COMPANY_MAX, MIN_FONT_SIZE,
                    self.box_w, self.box_h, max_lines
                )
                self.assertLessEqual(len(lines), max_lines)

    # --- Nicht-Überlauf: jede Zeile passt in die Box-Breite ---

    def _assert_no_width_overflow(self, text, font, max_size, max_lines):
        x0, x1, y0_mm, y1_mm = TEXT_BOXES_MM["firstname"]
        box_w = (x1 - x0) * mm
        box_h = (y1_mm - y0_mm) * mm
        lines, size, lh = _fit_text_in_box(
            self.c, text, font, max_size, MIN_FONT_SIZE, box_w, box_h, max_lines
        )
        self.c.setFont(font, size)
        for ln in lines:
            w = self.c.stringWidth(ln, font, size)
            self.assertLessEqual(
                w, box_w + 1,  # 1pt Toleranz für Rundung
                f"Zeile '{ln}' (size={size}) überläuft die Box-Breite ({w:.1f} > {box_w:.1f})"
            )

    def test_no_overflow_short(self):
        self._assert_no_width_overflow("Max", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, 2)

    def test_no_overflow_medium(self):
        self._assert_no_width_overflow("Marcus", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, 2)

    def test_no_overflow_long(self):
        self._assert_no_width_overflow("Maximilian Alexander", FONT_NAME_FIRST, FONT_SIZE_FIRST_MAX, 2)

    def test_no_overflow_extreme(self):
        self._assert_no_width_overflow(
            "von Hohenstein-Falkenried", FONT_NAME_LAST, FONT_SIZE_LAST_MAX, 2
        )


# ---------------------------------------------------------------------------
# Tests: render_badges_pdf_bytes
# ---------------------------------------------------------------------------

TEMPLATE_CATEGORIES = ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]

class RenderBadgesPdfBytesTests(unittest.TestCase):
    """
    Tests für render_badges_pdf_bytes.
    Nutzt ein PIL-erzeugtes Dummy-PNG als Template, um echte Datei-I/O zu vermeiden.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from PIL import Image as _PilImage

        cls._tmpdir = tempfile.mkdtemp()
        cls._tpl_path = os.path.join(cls._tmpdir, "dummy.png")

        # Echtes, valides PNG via Pillow erzeugen (weiß, 10×10 px)
        img = _PilImage.new("RGB", (10, 10), color=(255, 255, 255))
        img.save(cls._tpl_path, format="PNG")

        cls._tpl_map = {cat: cls._tpl_path for cat in TEMPLATE_CATEGORIES}

    def _render(self, rows, **kwargs):
        defaults = dict(uppercase_names=False, uppercase_company=False)
        defaults.update(kwargs)
        return render_badges_pdf_bytes(
            rows=rows,
            template_by_category=self._tpl_map,
            **defaults,
        )

    def _make_row(self, firstname, lastname, jobtitle, company, cat="TN", id_="42"):
        return {
            "id": id_,
            "firstname": firstname,
            "lastname": lastname,
            "jobtitle": jobtitle,
            "company": company,
            "kategorie": cat,
        }

    # --- Valide PDF-Bytes ---

    def test_produces_valid_pdf_bytes(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME")
        result = self._render([row])
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF"), "Ergebnis ist kein valides PDF")
        self.assertGreater(len(result), 100)

    # --- Testfälle kurz / mittel / lang / extrem ---

    def test_case_short(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME")
        result = self._render([row])
        self.assertTrue(result.startswith(b"%PDF"))

    def test_case_medium(self):
        row = self._make_row("Marcus", "Schaper", "CEO", "SBG Serious Business Gaming")
        result = self._render([row])
        self.assertTrue(result.startswith(b"%PDF"))

    def test_case_long(self):
        row = self._make_row(
            "Maximilian Alexander",
            "von Hohenstein-Falkenried",
            "Senior Vice President Business Development",
            "International Cyber Security Solutions Group",
        )
        result = self._render([row])
        self.assertTrue(result.startswith(b"%PDF"))

    def test_case_extreme(self):
        row = self._make_row(
            "Bartholomäus-Konstantin",
            "Freiherr von Münchhausen-Wolfsberg",
            "Chief Executive Officer and Co-Founder",
            "Internationale Gesellschaft für Unternehmensberatung und Strategieentwicklung",
        )
        result = self._render([row])
        self.assertTrue(result.startswith(b"%PDF"))

    # --- Uppercase-Flags ---

    def test_uppercase_names_no_crash(self):
        row = self._make_row("Marcus", "Schaper", "CEO", "SBG")
        result = self._render([row], uppercase_names=True, uppercase_company=True)
        self.assertTrue(result.startswith(b"%PDF"))

    # --- Leere Felder: kein Absturz ---

    def test_empty_fields_no_crash(self):
        row = self._make_row("", "", "", "")
        result = self._render([row])
        self.assertTrue(result.startswith(b"%PDF"))

    # --- Mehrere Badges in einem PDF ---

    def test_multiple_badges(self):
        rows = [
            self._make_row("Max", "Mustermann", "CEO", "ACME", id_="1"),
            self._make_row("Marcus", "Schaper", "CEO", "SBG", id_="2"),
            self._make_row(
                "Maximilian Alexander",
                "von Hohenstein-Falkenried",
                "Senior Vice President Business Development",
                "International Cyber Security Solutions Group",
                id_="3",
            ),
        ]
        result = self._render(rows)
        self.assertTrue(result.startswith(b"%PDF"))

    # --- Fehlerfall: fehlende Kategorie ---

    def test_missing_category_raises(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME")
        row["kategorie"] = ""
        with self.assertRaises(ValueError):
            self._render([row])

    # --- Fehlerfall: unbekannte Kategorie ---

    def test_unknown_category_raises(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME", cat="UNBEKANNT")
        with self.assertRaises(ValueError):
            self._render([row])

    # --- Keine record_id-Klartext im PDF (QR-Inhalt bleibt kodiert) ---

    def test_no_print_record_id_parameter(self):
        """render_badges_pdf_bytes darf kein print_record_id-Argument mehr kennen."""
        import inspect
        sig = inspect.signature(render_badges_pdf_bytes)
        self.assertNotIn(
            "print_record_id", sig.parameters,
            "print_record_id wurde nicht vollständig aus der Signatur entfernt"
        )

    # --- colored_qr: Default True, valides PDF ---

    def test_colored_qr_default_true_produces_valid_pdf(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME")
        result = self._render([row])  # colored_qr nicht übergeben → Default True
        self.assertTrue(result.startswith(b"%PDF"))

    def test_colored_qr_true_all_categories_no_crash(self):
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                row = self._make_row("Max", "Mustermann", "CEO", "ACME", cat=cat)
                result = render_badges_pdf_bytes(
                    rows=[row],
                    template_by_category=self._tpl_map,
                    uppercase_names=False,
                    uppercase_company=False,
                    colored_qr=True,
                )
                self.assertTrue(result.startswith(b"%PDF"), f"Kein valides PDF für Kategorie {cat}")

    def test_colored_qr_parameter_has_default_true(self):
        import inspect
        sig = inspect.signature(render_badges_pdf_bytes)
        param = sig.parameters.get("colored_qr")
        self.assertIsNotNone(param, "colored_qr-Parameter fehlt in render_badges_pdf_bytes")
        self.assertIs(param.default, True)


# ---------------------------------------------------------------------------
# Tests: _qr_color_for_category
# ---------------------------------------------------------------------------

class QrColorForCategoryTests(unittest.TestCase):

    # --- colored=False → immer schwarz ---

    def test_colored_false_returns_default_for_known_categories(self):
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                c = _qr_color_for_category(cat, colored=False)
                self.assertEqual(c, _QR_COLOR_DEFAULT)

    def test_colored_false_returns_default_for_empty(self):
        self.assertEqual(_qr_color_for_category("", colored=False), _QR_COLOR_DEFAULT)

    def test_colored_false_returns_default_for_unknown(self):
        self.assertEqual(_qr_color_for_category("UNBEKANNT", colored=False), _QR_COLOR_DEFAULT)

    # --- colored=True, bekannte Kategorien ---

    def test_tn_gets_green(self):
        c = _qr_color_for_category("TN", colored=True)
        self.assertNotEqual(c, _QR_COLOR_DEFAULT)
        self.assertEqual(c, _QR_COLOR_BY_CATEGORY["TN"])

    def test_vip_ref_gets_gold(self):
        c = _qr_color_for_category("VIP/REF", colored=True)
        self.assertNotEqual(c, _QR_COLOR_DEFAULT)
        self.assertEqual(c, _QR_COLOR_BY_CATEGORY["VIP/REF"])

    def test_sponsor_gets_black(self):
        c = _qr_color_for_category("Sponsor", colored=True)
        self.assertEqual(c, _QR_COLOR_DEFAULT)

    def test_beo_gets_violet(self):
        c = _qr_color_for_category("BEO", colored=True)
        self.assertNotEqual(c, _QR_COLOR_DEFAULT)
        self.assertEqual(c, _QR_COLOR_BY_CATEGORY["BEO"])

    def test_team_gets_red(self):
        c = _qr_color_for_category("Team", colored=True)
        self.assertNotEqual(c, _QR_COLOR_DEFAULT)
        self.assertEqual(c, _QR_COLOR_BY_CATEGORY["Team"])

    def test_beo_and_vip_different_colors(self):
        """BEO = violett, VIP/REF = gold — müssen unterschiedlich sein."""
        self.assertNotEqual(
            _qr_color_for_category("BEO", colored=True),
            _qr_color_for_category("VIP/REF", colored=True),
        )

    # --- colored=True, unbekannte / leere Kategorie → schwarz ---

    def test_empty_category_returns_default(self):
        self.assertEqual(_qr_color_for_category("", colored=True), _QR_COLOR_DEFAULT)

    def test_none_like_empty_returns_default(self):
        self.assertEqual(_qr_color_for_category("  ", colored=True), _QR_COLOR_DEFAULT)

    def test_unknown_category_returns_default(self):
        self.assertEqual(_qr_color_for_category("UNBEKANNT", colored=True), _QR_COLOR_DEFAULT)
        self.assertEqual(_qr_color_for_category("xyz", colored=True), _QR_COLOR_DEFAULT)


# ---------------------------------------------------------------------------
# Tests: Jobtitel-Positionierung
# ---------------------------------------------------------------------------

class JobtitlePlacementHelperTests(unittest.TestCase):

    def test_centered_block_edges_returns_symmetric_span(self):
        top, bottom = _centered_block_edges(100.0, 160.0, 10.0, 2)
        self.assertEqual((140.0, 120.0), (top, bottom))

    def test_jobtitle_box_uses_actual_gap_between_name_and_company(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        centered = _jobtitle_box_between(default_box, upper_bottom=120.0, lower_top=90.0)

        self.assertEqual((10.0, 95.0, 90.0, 120.0), centered)

    def test_jobtitle_box_with_gap_reserves_equal_space_above_and_below(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        reserved = _jobtitle_box_with_gap(default_box, upper_bottom=120.0, lower_top=90.0, gap=10.0)

        self.assertEqual((10.0, 95.0, 100.0, 110.0), reserved)

    def test_jobtitle_box_with_gap_returns_none_when_gap_does_not_fit(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        reserved = _jobtitle_box_with_gap(default_box, upper_bottom=100.0, lower_top=90.0, gap=6.0)

        self.assertIsNone(reserved)

    def test_jobtitle_box_falls_back_without_name_reference(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        self.assertEqual(
            default_box,
            _jobtitle_box_between(default_box, upper_bottom=None, lower_top=90.0),
        )

    def test_jobtitle_box_falls_back_without_company_reference(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        self.assertEqual(
            default_box,
            _jobtitle_box_between(default_box, upper_bottom=120.0, lower_top=None),
        )

    def test_jobtitle_box_falls_back_when_blocks_overlap(self):
        default_box = (10.0, 95.0, 79.0, 88.0)
        self.assertEqual(
            default_box,
            _jobtitle_box_between(default_box, upper_bottom=90.0, lower_top=90.0),
        )


class RenderedJobtitlePlacementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from PIL import Image as _PilImage

        cls._tmpdir = tempfile.mkdtemp()
        cls._tpl_path = os.path.join(cls._tmpdir, "dummy.png")

        img = _PilImage.new("RGB", (10, 10), color=(255, 255, 255))
        img.save(cls._tpl_path, format="PNG")
        cls._tpl_map = {cat: cls._tpl_path for cat in TEMPLATE_CATEGORIES}

    def _capture_draw_calls(self, row: dict) -> list[dict]:
        original_draw = render_pdf_module._draw_centered_lines_in_box
        draw_calls: list[dict] = []

        def tracking_draw(*args, **kwargs):
            draw_calls.append({
                "lines": list(args[1]),
                "box": (args[4], args[5], args[6], args[7]),
                "line_h": args[8],
            })
            return original_draw(*args, **kwargs)

        with patch("badgegen.render_pdf._draw_centered_lines_in_box", side_effect=tracking_draw):
            render_badges_pdf_bytes(
                rows=[row],
                template_by_category=self._tpl_map,
                uppercase_names=False,
                uppercase_company=False,
                colored_qr=False,
            )

        return draw_calls

    def _render_and_measure_gaps(self, row: dict) -> tuple[dict, float, float]:
        draw_calls = self._capture_draw_calls(row)
        name_call = draw_calls[1] if row.get("lastname", "").strip() else draw_calls[0]
        job_call = draw_calls[2]
        company_call = draw_calls[3]

        _, name_bottom = _centered_block_edges(
            name_call["box"][2], name_call["box"][3], name_call["line_h"], len(name_call["lines"])
        )
        company_top, _ = _centered_block_edges(
            company_call["box"][2], company_call["box"][3], company_call["line_h"], len(company_call["lines"])
        )
        job_top, job_bottom = _centered_block_edges(
            job_call["box"][2], job_call["box"][3], job_call["line_h"], len(job_call["lines"])
        )

        gap_above = name_bottom - job_top
        gap_below = job_bottom - company_top
        return job_call, gap_above, gap_below

    def test_jobtitle_uses_target_gap_when_space_allows_it(self):
        row = {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "Security Architect",
            "company": "ACME",
            "kategorie": "TN",
        }

        draw_calls = self._capture_draw_calls(row)
        job_call = draw_calls[2]
        last_call = draw_calls[1]
        company_call = draw_calls[3]

        _, name_bottom = _centered_block_edges(last_call["box"][2], last_call["box"][3], last_call["line_h"], len(last_call["lines"]))
        company_top, _ = _centered_block_edges(company_call["box"][2], company_call["box"][3], company_call["line_h"], len(company_call["lines"]))
        expected_box = _jobtitle_box_with_gap(
            _mm_box_to_points(TEXT_BOXES_MM["jobtitle"]),
            upper_bottom=name_bottom,
            lower_top=company_top,
            gap=JOBTITLE_GAP_TARGET,
        )

        self.assertEqual(expected_box, job_call["box"])

    def test_jobtitle_uses_min_gap_when_target_gap_would_be_too_tight(self):
        row = {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "Security Architect",
            "company": "ACME",
            "kategorie": "TN",
        }

        original_fit_details = render_pdf_module._fit_text_in_box_details
        original_draw = render_pdf_module._draw_centered_lines_in_box
        draw_calls: list[dict] = []
        job_fit_calls = {"count": 0}

        def tracking_draw(*args, **kwargs):
            draw_calls.append({
                "lines": list(args[1]),
                "box": (args[4], args[5], args[6], args[7]),
                "line_h": args[8],
            })
            return original_draw(*args, **kwargs)

        def selective_fit(*args, **kwargs):
            text = args[1]
            font = args[2]
            if text == row["jobtitle"] and font == FONT_NAME_JOB:
                job_fit_calls["count"] += 1
                if job_fit_calls["count"] == 1:
                    return ["Security Architect"], 18, 12.0, False
                if job_fit_calls["count"] == 2:
                    return ["Security Architect"], 18, 12.0, True
            return original_fit_details(*args, **kwargs)

        with patch("badgegen.render_pdf._fit_text_in_box_details", side_effect=selective_fit), \
             patch("badgegen.render_pdf._draw_centered_lines_in_box", side_effect=tracking_draw):
            render_badges_pdf_bytes(
                rows=[row],
                template_by_category=self._tpl_map,
                uppercase_names=False,
                uppercase_company=False,
                colored_qr=False,
            )

        job_call = draw_calls[2]
        last_call = draw_calls[1]
        company_call = draw_calls[3]
        _, name_bottom = _centered_block_edges(last_call["box"][2], last_call["box"][3], last_call["line_h"], len(last_call["lines"]))
        company_top, _ = _centered_block_edges(company_call["box"][2], company_call["box"][3], company_call["line_h"], len(company_call["lines"]))
        expected_box = _jobtitle_box_with_gap(
            _mm_box_to_points(TEXT_BOXES_MM["jobtitle"]),
            upper_bottom=name_bottom,
            lower_top=company_top,
            gap=JOBTITLE_GAP_MIN,
        )

        self.assertEqual(2, job_fit_calls["count"])
        self.assertEqual(expected_box, job_call["box"])

    def test_jobtitle_falls_back_to_full_gap_when_reserved_gap_still_does_not_fit(self):
        row = {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "Security Architect",
            "company": "ACME",
            "kategorie": "TN",
        }

        original_fit_details = render_pdf_module._fit_text_in_box_details
        original_draw = render_pdf_module._draw_centered_lines_in_box
        draw_calls: list[dict] = []
        job_fit_calls = {"count": 0}

        def tracking_draw(*args, **kwargs):
            draw_calls.append({
                "lines": list(args[1]),
                "box": (args[4], args[5], args[6], args[7]),
                "line_h": args[8],
            })
            return original_draw(*args, **kwargs)

        def selective_fit(*args, **kwargs):
            text = args[1]
            font = args[2]
            if text == row["jobtitle"] and font == FONT_NAME_JOB:
                job_fit_calls["count"] += 1
                if job_fit_calls["count"] in {1, 2}:
                    return ["Security Architect"], 18, 12.0, False
                if job_fit_calls["count"] == 3:
                    return ["Security Architect"], 18, 12.0, True
            return original_fit_details(*args, **kwargs)

        with patch("badgegen.render_pdf._fit_text_in_box_details", side_effect=selective_fit), \
             patch("badgegen.render_pdf._draw_centered_lines_in_box", side_effect=tracking_draw):
            render_badges_pdf_bytes(
                rows=[row],
                template_by_category=self._tpl_map,
                uppercase_names=False,
                uppercase_company=False,
                colored_qr=False,
            )

        job_call = draw_calls[2]
        last_call = draw_calls[1]
        company_call = draw_calls[3]
        _, name_bottom = _centered_block_edges(last_call["box"][2], last_call["box"][3], last_call["line_h"], len(last_call["lines"]))
        company_top, _ = _centered_block_edges(company_call["box"][2], company_call["box"][3], company_call["line_h"], len(company_call["lines"]))
        expected_box = _jobtitle_box_between(
            _mm_box_to_points(TEXT_BOXES_MM["jobtitle"]),
            upper_bottom=name_bottom,
            lower_top=company_top,
        )

        self.assertEqual(3, job_fit_calls["count"])
        self.assertEqual(expected_box, job_call["box"])

    def test_jobtitle_gaps_stay_equal_for_requested_smoke_cases(self):
        cases = [
            {
                "id": "1",
                "firstname": "Max",
                "lastname": "Mustermann",
                "jobtitle": "CEO",
                "company": "ACME",
                "kategorie": "TN",
            },
            {
                "id": "2",
                "firstname": "Max",
                "lastname": "Mustermann",
                "jobtitle": "Senior Vice President International Business Development and Strategic Partnerships and Alliances",
                "company": "ACME",
                "kategorie": "TN",
            },
            {
                "id": "3",
                "firstname": "Max",
                "lastname": "Mustermann",
                "jobtitle": "CEO",
                "company": "Internationale Gesellschaft fuer Unternehmensberatung und Strategieentwicklung GmbH & Co. KG",
                "kategorie": "TN",
            },
            {
                "id": "4",
                "firstname": "Max",
                "lastname": "Mustermann",
                "jobtitle": "Senior Vice President International Business Development and Strategic Partnerships and Alliances",
                "company": "Internationale Gesellschaft fuer Unternehmensberatung und Strategieentwicklung GmbH & Co. KG",
                "kategorie": "TN",
            },
            {
                "id": "5",
                "firstname": "Maximilian Alexander",
                "lastname": "von Hohenstein-Falkenried",
                "jobtitle": "Senior Vice President International Business Development and Strategic Partnerships and Alliances",
                "company": "Internationale Gesellschaft fuer Unternehmensberatung und Strategieentwicklung GmbH & Co. KG",
                "kategorie": "TN",
            },
        ]

        for row in cases:
            with self.subTest(row=row["id"]):
                _, gap_above, gap_below = self._render_and_measure_gaps(row)
                self.assertGreater(gap_above, 0)
                self.assertGreater(gap_below, 0)
                self.assertAlmostEqual(gap_above, gap_below, delta=0.5)

    def test_jobtitle_falls_back_to_static_box_without_company(self):
        row = {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "Security Architect",
            "company": "",
            "kategorie": "TN",
        }

        draw_calls = self._capture_draw_calls(row)
        job_call = draw_calls[2]
        static_job_box = _mm_box_to_points(TEXT_BOXES_MM["jobtitle"])

        self.assertEqual(static_job_box, job_call["box"])


# ---------------------------------------------------------------------------
# Tests: Template-Auswahl bleibt kategorial, auch bei colored_qr=True
# ---------------------------------------------------------------------------

class ColoredQrTemplateSelectionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from PIL import Image as _PilImage

        cls._tmpdir = tempfile.mkdtemp()
        cls._tpl_map = {}
        colors = {
            "TN": (0, 0, 255),
            "VIP/REF": (255, 255, 0),
            "Sponsor": (255, 0, 0),
            "BEO": (128, 0, 128),
            "Team": (0, 128, 0),
        }
        for cat, color in colors.items():
            path = os.path.join(cls._tmpdir, f"{cat.replace('/', '_')}.png")
            img = _PilImage.new("RGB", (10, 10), color=color)
            img.save(path, format="PNG")
            cls._tpl_map[cat] = path

    def _render_and_capture_template(self, cat: str, colored_qr: bool) -> tuple[bytes, str]:
        original_image_reader = ImageReader
        used_paths: list[str] = []

        def tracking_image_reader(path):
            used_paths.append(path)
            return original_image_reader(path)

        row = {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "CEO",
            "company": "ACME",
            "kategorie": cat,
        }

        with patch("badgegen.render_pdf.ImageReader", side_effect=tracking_image_reader):
            pdf = render_badges_pdf_bytes(
                rows=[row],
                template_by_category=self._tpl_map,
                uppercase_names=False,
                uppercase_company=False,
                colored_qr=colored_qr,
            )
        return pdf, used_paths[0]

    def test_colored_on_keeps_category_template_for_all_categories(self):
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                result, template_path = self._render_and_capture_template(cat, colored_qr=True)
                self.assertTrue(result.startswith(b"%PDF"))
                self.assertEqual(self._tpl_map[cat], template_path)

    def test_colored_off_keeps_category_template_for_all_categories(self):
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                result, template_path = self._render_and_capture_template(cat, colored_qr=False)
                self.assertTrue(result.startswith(b"%PDF"))
                self.assertEqual(self._tpl_map[cat], template_path)


if __name__ == "__main__":
    unittest.main()
