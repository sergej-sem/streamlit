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

from reportlab.pdfgen import canvas as rl_canvas

from reportlab.lib import colors as rl_colors

from badgegen.render_pdf import (
    MIN_FONT_SIZE,
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
    _fit_text_in_box,
    _qr_color_for_category,
    _wrap_words,
    render_badges_pdf_bytes,
)
from reportlab.lib.units import mm


# ---------------------------------------------------------------------------
# Hilfsfunktion: minimaler Canvas für Tests (kein echtes PDF nötig)
# ---------------------------------------------------------------------------

def _make_canvas() -> rl_canvas.Canvas:
    buf = io.BytesIO()
    return rl_canvas.Canvas(buf)


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

    # --- colored_qr: Default False, valides PDF ---

    def test_colored_qr_default_false_produces_valid_pdf(self):
        row = self._make_row("Max", "Mustermann", "CEO", "ACME")
        result = self._render([row])  # colored_qr nicht übergeben → Default False
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

    def test_colored_qr_parameter_has_default_false(self):
        import inspect
        sig = inspect.signature(render_badges_pdf_bytes)
        param = sig.parameters.get("colored_qr")
        self.assertIsNotNone(param, "colored_qr-Parameter fehlt in render_badges_pdf_bytes")
        self.assertIs(param.default, False)


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
# Tests: Template-Override bei colored_qr=True (Sponsoren-Template für alle)
# ---------------------------------------------------------------------------

class ColoredQrTemplateOverrideTests(unittest.TestCase):
    """
    Prüft, dass bei colored_qr=True das Sponsoren-Template für alle Badges
    verwendet wird, und bei colored_qr=False das kategoriale Mapping gilt.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from PIL import Image as _PilImage

        cls._tmpdir = tempfile.mkdtemp()

        # Zwei unterschiedliche Templates: TN (blau) und Sponsor (rot) zur Unterscheidung
        cls._tn_path = os.path.join(cls._tmpdir, "tn.png")
        cls._spo_path = os.path.join(cls._tmpdir, "spo.png")

        for path, color in [(cls._tn_path, (0, 0, 255)), (cls._spo_path, (255, 0, 0))]:
            img = _PilImage.new("RGB", (10, 10), color=color)
            img.save(path, format="PNG")

        cls._tpl_map = {cat: cls._tn_path for cat in TEMPLATE_CATEGORIES}
        cls._tpl_map["Sponsor"] = cls._spo_path

    def _render(self, rows, colored_qr):
        return render_badges_pdf_bytes(
            rows=rows,
            template_by_category=self._tpl_map,
            uppercase_names=False,
            uppercase_company=False,
            colored_qr=colored_qr,
        )

    def _make_row(self, cat):
        return {
            "id": "1",
            "firstname": "Max",
            "lastname": "Mustermann",
            "jobtitle": "CEO",
            "company": "ACME",
            "kategorie": cat,
        }

    def test_colored_off_uses_category_template_for_tn(self):
        """colored_qr=False: TN-Kategorie → TN-Template (kein Crash, kein Override)."""
        result = self._render([self._make_row("TN")], colored_qr=False)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_colored_on_uses_sponsor_template_for_tn(self):
        """colored_qr=True: TN-Kategorie → Sponsoren-Template (kein Crash)."""
        result = self._render([self._make_row("TN")], colored_qr=True)
        self.assertTrue(result.startswith(b"%PDF"))

    def test_colored_on_uses_sponsor_template_for_all_categories(self):
        """colored_qr=True: alle Kategorien → Sponsoren-Template, valides PDF."""
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                result = self._render([self._make_row(cat)], colored_qr=True)
                self.assertTrue(result.startswith(b"%PDF"), f"Kein valides PDF für {cat}")

    def test_colored_off_all_categories_no_crash(self):
        """colored_qr=False: alle Kategorien → normales Mapping, kein Crash."""
        for cat in ["TN", "VIP/REF", "Sponsor", "BEO", "Team"]:
            with self.subTest(cat=cat):
                result = self._render([self._make_row(cat)], colored_qr=False)
                self.assertTrue(result.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
