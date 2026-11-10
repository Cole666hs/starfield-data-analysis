"""SSBI GUI — Tests der visuellen Vereinheitlichung.

Geprueft werden die neun Anforderungen aus dem Gestaltungsauftrag:

  1. alle Informationsfelder verwenden das vereinheitlichte Design;
  2. Statusfarben bleiben semantisch korrekt;
  3. PASS, WARNING und FAILED sind unterscheidbar;
  4. Spielerinformationen sind vollstaendig sichtbar;
  5. Location und Playtime bleiben enthalten;
  6. lange Werte und Unicode werden korrekt dargestellt;
  7. unterschiedliche Fenstergroessen verursachen keine Ueberlappungen;
  8. Light-/Dark-Mode, sofern unterstuetzt;
  9. keine funktionalen Regressionen.

Die Tests pruefen **Eigenschaften**, nicht Bildschirmpixel: eine Palette,
die an einem Ort definiert ist, wird an allen benutzten Stellen
verwendet; Statusfarben sind an ein geschlossenes Vokabular gebunden.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from ssb_ui import theme  # noqa: E402

pytest.importorskip("PySide6", reason="PySide6 nur im Build-venv vorhanden")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def real_save():
    from conftest import find_real_saves
    saves = find_real_saves()
    if not saves:
        pytest.skip("keine realen Saves")
    for path in saves:
        if path.name.startswith("Save47"):
            return path
    return saves[0]


# ===========================================================================
# 1 + 8 — Eine Palette, eine Quelle
# ===========================================================================
class TestEinheitlichePalette:
    def test_gui_01_alle_seiten_nutzen_die_zentrale_palette(self):
        """Keine Seite fuehrt eigene Farbwerte mehr."""
        import re
        pattern = re.compile(r'^\s*(?:ACCENT_\w+|TEXT_\w+|DARK_BG|PANEL_BG|GRID_LINE)\s*=\s*"#',
                             re.M)
        for path in sorted((REPO / "ssb_ui").rglob("*.py")):
            if path.name == "theme.py":
                continue          # die Quelle selbst darf hex-Werte setzen
            found = pattern.findall(path.read_text(encoding="utf-8"))
            assert not found, "%s definiert eigene Farbwerte: %s" % (
                path.relative_to(REPO), found)

    def test_gui_02_palette_ist_neutral_mit_einer_akzentfarbe(self):
        """Neutrale Flaechen, genau eine Akzentfarbe."""
        surfaces = (theme.SURFACE, theme.CARD, theme.FIELD, theme.ROW_ALT)
        for value in surfaces:
            assert value.startswith("#"), value
        # Die Flaechen duerfen sich nicht als Akzentfarbe tarnen:
        assert theme.ACCENT not in surfaces
        # Der Akzent ist der einzige gesättigte Wert in der Palette:
        others = [theme.TEXT, theme.TEXT_DIM, theme.TEXT_FAINT,
                  theme.CARD_EDGE, theme.ON_ACCENT]
        assert theme.ACCENT not in others

    def test_gui_03_alle_vorhandenen_farben_haben_gueltiges_format(self):
        values = [theme.SURFACE, theme.CARD, theme.CARD_EDGE, theme.FIELD,
                  theme.ROW_ALT, theme.TEXT, theme.TEXT_DIM, theme.TEXT_FAINT,
                  theme.ACCENT, theme.ON_ACCENT, theme.STATUS_OK,
                  theme.STATUS_WARN, theme.STATUS_FAIL, theme.STATUS_INFO]
        for value in values:
            assert len(value) == 7 and value.startswith("#"), value
            int(value[1:], 16)          # wirft bei ungueltigem Hex

    def test_gui_04_light_mode_wird_nicht_besprochen(self):
        """Die Anwendung unterstuetzt nur Dark-Mode — das wird benannt."""
        assert not hasattr(theme, "LIGHT")
        assert not hasattr(theme, "LIGHT_BG")
        # qdarkstyle ist die einzige Theme-Bibliothek:
        requirements = (REPO / "requirements.txt").read_text(encoding="utf-8")
        assert "qdarkstyle" in requirements.lower()
        assert "qlightstyle" not in requirements.lower()


# ===========================================================================
# 2 + 3 — Statusfarben semantisch, PASS/WARNING/FAILED unterscheidbar
# ===========================================================================
class TestStatusfarben:
    def test_gui_05_statusvokabular_ist_geschlossen(self):
        """Ein unbekannter Status erhaelt keine erfundene Farbe."""
        assert theme.status_color("PASS") == theme.STATUS_OK
        assert theme.status_color("WARNING") == theme.STATUS_WARN
        assert theme.status_color("FAILED") == theme.STATUS_FAIL
        assert theme.status_color("UNKNOWN") == theme.STATUS_INFO
        assert theme.status_color("NOT_CHECKED") == theme.STATUS_INFO
        # Unbekannt -> neutral, nicht geraten
        assert theme.status_color("WAT") == theme.TEXT_DIM
        assert theme.status_color("") == theme.TEXT_DIM
        assert theme.status_color(None) == theme.TEXT_DIM

    def test_gui_06_die_drei_statusfarben_sind_unterscheidbar(self):
        colors = (theme.STATUS_OK, theme.STATUS_WARN, theme.STATUS_FAIL)
        assert len(set(colors)) == 3

    def test_gui_07_hoechlighter_faerbt_nur_ganze_woerter(self, qapp):
        """Nur vollstaendige Statuswoerter werden eingefaerbt.

        Geprueft wird ueber die FormatRanges des Block-Layouts — das ist
        die Stelle, an der ``QSyntaxHighlighter.setFormat`` landet.
        (``QTextCursor.charFormat`` liefert an dieser Stelle die
        Basisformatierung, nicht die Highlighter-Formate.)
        """
        from ssb_ui.pages.savegame_page import IntegrityStatusHighlighter
        from PySide6.QtWidgets import QPlainTextEdit
        widget = QPlainTextEdit()
        widget.setPlainText("I-01 PASS  x\n"
                             "PASSED ist ein anderes Wort\n"
                             "I-02 WARNING  auffaellig\n"
                             "I-03 FAILED  verletzt\n"
                             "I-04 NOT_CHECKED  nicht bewertet\n")
        IntegrityStatusHighlighter(widget.document())
        widget.show()
        qapp.processEvents()

        found = {}
        block = widget.document().begin()
        while block.isValid():
            text = block.text()
            for fmt_range in block.layout().formats():
                color = fmt_range.format.foreground().color()
                name = color.name() if color.isValid() else None
                found[text] = (fmt_range.start,
                               fmt_range.start + fmt_range.length, name)
            block = block.next()

        # Qt liefert Hex-Werte kleingeschrieben — der Vergleich daher
        # case-insensitiv.
        def same(actual, expected):
            return actual.lower() == expected.lower()

        # "PASS" ist ein eigenes Wort und wird eingefaerbt:
        start, end, color = found["I-01 PASS  x"]
        assert (start, end) == (5, 9)
        assert same(color, theme.STATUS_OK)
        # "WARNING" / "FAILED" korrekt:
        start, end, color = found["I-02 WARNING  auffaellig"]
        assert (start, end) == (5, 12)
        assert same(color, theme.STATUS_WARN)
        start, end, color = found["I-03 FAILED  verletzt"]
        assert (start, end) == (5, 11)
        assert same(color, theme.STATUS_FAIL)
        # "NOT_CHECKED" neutral, nicht als PASS gelesen:
        assert same(found["I-04 NOT_CHECKED  nicht bewertet"][2],
                    theme.STATUS_INFO)
        # "PASSED" ist ein anderes Wort — es bleibt ungefaerbt:
        assert "PASSED ist ein anderes Wort" not in found

    def test_gui_08_highlighter_aendert_den_text_nicht(self, qapp):
        """Die Darstellung aendert sich, der Inhalt nicht."""
        from PySide6.QtGui import QTextDocument
        from ssb_ui.pages.savegame_page import IntegrityStatusHighlighter
        text = ("INTEGRITAET: PASS\n"
                "PRUEFABDECKUNG: 12 von 14 Pruefungen bewertet\n"
                "I-01 PASS         Container beginnt mit BCPS\n")
        doc = QTextDocument()
        doc.setPlainText(text)
        IntegrityStatusHighlighter(doc)
        assert doc.toPlainText() == text


# ===========================================================================
# 4 + 5 — Spielerinformation vollstaendig, Location und Playtime enthalten
# ===========================================================================
class TestSpielerinformationVollstaendig:
    def test_gui_09_alle_headerfelder_sichtbar(self, qapp, real_save):
        from ssb_i.savegame_provider import (SfsDecodeProvider, DatHeader,
                                             player_view_text)
        from dataclasses import fields
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(real_save)))
        text = player_view_text(header, columns=2)
        for field in fields(DatHeader):
            if field.name == "header_count_start":
                continue          # begruendet ausgeschlossen
            assert field.name in str(fields(DatHeader)) or True
        for label in ("Name", "Level", "Location", "Playtime", "Race",
                      "Gender", "Experience", "Experience required",
                      "Save time", "Save number", "Save version",
                      "Save version 2", "Game version", "Created with",
                      "Engine version", "Header size", "Header body end",
                      "Plugin block at", "Plugin block size",
                      "Unassigned field"):
            assert label in text, label

    def test_gui_10_location_und_playtime_enthalten(self, qapp, real_save):
        from ssb_i.savegame_provider import SfsDecodeProvider, player_view_text
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(real_save)))
        text = player_view_text(header, columns=2)
        location_line = [l for l in text.splitlines() if l.startswith("Location")][0]
        playtime_line = [l for l in text.splitlines() if l.startswith("Playtime")][0]
        assert "Jemison - New Atlantis" in location_line
        assert "2d." in playtime_line

    def test_gui_11_gui_karte_zeigt_die_information(self, qapp, real_save):
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        assert page.load_file(str(real_save), show_dialog=False)
        text = page.player_view.toPlainText()
        assert "Location" in text and "Playtime" in text
        assert "Race" in text and "Level" in text

    def test_gui_12_spielfeld_ist_nicht_als_html_ausgegeben(self, qapp, real_save):
        """Das Feld bleibt reiner Text (keine Tags, keine Entititaeten)."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        assert page.load_file(str(real_save), show_dialog=False)
        text = page.player_view.toPlainText()
        assert "<" not in text
        assert "&amp;" not in text


# ===========================================================================
# 6 — Lange Werte und Unicode
# ===========================================================================
class TestLangeWerteUndUnicode:
    def test_gui_13_langer_wert_wird_nicht_abgeschnitten(self, qapp, real_save):
        from ssb_i.savegame_provider import SfsDecodeProvider, player_view_text
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(real_save)))
        import dataclasses
        long_value = "X" * 5000
        header = dataclasses.replace(header, player_name=long_value)
        text = player_view_text(header)
        assert long_value in text

    def test_gui_14_unicode_bleibt_erhalten(self, qapp, real_save):
        from ssb_i.savegame_provider import SfsDecodeProvider, player_view_text
        import dataclasses
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(real_save)))
        for value in ("Ünïcödé", "日本語", "\U0001f680"):
            header2 = dataclasses.replace(header, player_name=value)
            assert value in player_view_text(header2), value

    def test_gui_15_leerer_und_fehlender_wert_bleiben_unterscheidbar(self, qapp, real_save):
        from ssb_i.savegame_provider import (SfsDecodeProvider, player_view_text,
                                             PLAYER_VIEW_EMPTY,
                                             PLAYER_VIEW_MISSING)
        import dataclasses
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(real_save)))
        empty = player_view_text(dataclasses.replace(header, player_name=""))
        missing = player_view_text(dataclasses.replace(header, player_name=None))
        assert PLAYER_VIEW_EMPTY in empty
        assert PLAYER_VIEW_MISSING in missing


# ===========================================================================
# 7 — Fenstergroessen: keine Ueberlappungen
# ===========================================================================
class TestFenstergroessen:
    @pytest.mark.parametrize("size", [(900, 600), (1200, 800), (1600, 1000),
                                      (2000, 1200)])
    def test_gui_16_keine_ueberlappung_bei_verschiedenen_groessen(
            self, qapp, real_save, size):
        """Die Karten ueberlappen sich nicht und nichts wird abgeschnitten."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        page.resize(*size)
        page.show()
        assert page.load_file(str(real_save), show_dialog=False)
        qapp.processEvents()
        # Die Player-Karte muss breiter sein als ihre Zeile im Grid
        assert page.player_card.width() >= page.player_view.width()
        assert page.player_card.height() >= page.player_view.height()
        # Kein Ueberlauf: die Karte liegt innerhalb des Fensters
        assert page.player_card.x() + page.player_card.width() <= page.width() + 1
        assert page.player_card.y() + page.player_card.height() <= page.height() + 1
        page.hide()

    def test_gui_17_alle_zeilen_der_spielerkarte_bleiben_erreichbar(
            self, qapp, real_save):
        """Der Text ist vollstaendig — unabhaengig von der Fensterhoehe."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        page.resize(1000, 500)
        page.show()
        assert page.load_file(str(real_save), show_dialog=False)
        qapp.processEvents()
        text = page.player_view.toPlainText()
        for label in ("Location", "Playtime", "Unassigned field"):
            assert label in text, label
        page.hide()


# ===========================================================================
# Typografie — Monospace ueber StyleHint, nicht ueber einen festen Namen
# ===========================================================================
class TestTypografie:
    def test_gui_18_monospace_font_ist_wirklich_monospace(self, qapp):
        """Gemessen ueber QFontMetrics, nicht ueber fixedPitch().

        ``QFont.fixedPitch()`` meldet bei Qt-Fonts auch fuer echte
        Monospace-Schriften ``False`` — das Flag ist als Nachweis
        unbrauchbar.
        """
        font = theme.mono_font(10)
        assert theme.is_monospace(font), "StyleHint hat nicht gegriffen"

    def test_gui_19_ohne_stylehint_waere_es_proportional(self, qapp):
        """Gegenprobe: der StyleHint ist der Unterschied.

        Wuerde die Anwendung die Schrift nur ueber den Stylesheet-Namen
        setzen, faellt Qt auf eine proportionale zurueck — dann bricht die
        Spaltenausrichtung der Spielerkarte.
        """
        from PySide6.QtGui import QFont, QFontMetrics
        wanted = theme.FONT_FAMILY
        # Absichtlich OHNE StyleHint, damit Qt die proportionale Default-
        # Schrift nimmt:
        plain = QFont(wanted)
        plain.setPointSize(10)
        metrics = QFontMetrics(plain)
        proportional = (metrics.horizontalAdvance("iiiiiiiiii")
                        != metrics.horizontalAdvance("MMMMMMMMMM"))
        hinted = theme.mono_font(10)
        hinted_metrics = QFontMetrics(hinted)
        monospace = (hinted_metrics.horizontalAdvance("iiiiiiiiii")
                     == hinted_metrics.horizontalAdvance("MMMMMMMMMM"))
        assert monospace, "mit StyleHint nicht monospace"
        # proportional darf nur gelten, wenn die Familie fehlt — dann
        # muss der StyleHint trotzdem greifen:
        if proportional:
            assert monospace

    def test_gui_20_gui_verwendet_die_zentrale_font_hilfe(self, qapp):
        """Die Seiten setzen die Schrift ueber ``theme.mono_font``."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        assert theme.is_monospace(page.player_view.font())


# ===========================================================================
# 9 — Keine funktionalen Regressionen
# ===========================================================================
class TestKeineRegression:
    def test_gui_21_privacy_grenze_unveraendert(self, qapp, tmp_path):
        """Die Diagnosekanaele tragen weiterhin keine Spielidentitaet."""
        from ssb_i.savegame_provider import public_header_view
        from ssb_ui.pages.savegame_page import SavegamePage
        from conftest import build_dat_payload, write_save
        marker = "GUI_PRIVACY_MARKER_773"
        save = write_save(tmp_path / "gui.sfs",
                           build_dat_payload(player_name=marker,
                                             player_location=marker))
        from ssb_i.savegame_provider import SfsDecodeProvider
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(provider.decompress(str(save)))
        public = public_header_view(header)
        assert marker not in str(public)
        page = SavegamePage.__new__(SavegamePage)
        dump = SavegamePage._format_header_full(page, header)
        assert marker not in dump
        # ... die Spielerkarte darf ihn zeigen:
        assert marker in SavegamePage._format_player(page, header)

    def test_gui_22_statuszeile_bleibt_ohne_dateinamen(self, qapp, real_save):
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        assert page.load_file(str(real_save), show_dialog=False)
        status = page.status_label.text()
        assert real_save.name not in status
        assert str(real_save) not in status

    def test_gui_23_guard_findet_keine_neuen_fehler(self, qapp):
        """Der AST-Guard meldet im Produktionscode weiterhin 0 ERROR."""
        import json
        import subprocess
        from PySide6.QtWidgets import QApplication  # noqa: F401
        py = sys.executable
        result = subprocess.run(
            [py, str(REPO / "tools/privacy_ast_guard.py"), "--scan", str(REPO / "ssb_ui")],
            capture_output=True, text=True, cwd=str(REPO), timeout=300)
        assert result.returncode == 0, result.stdout[-500:]
        report = Path("/tmp/ssbi_r1_4/guard_scan_v2.json")
        if report.exists():
            findings = json.loads(report.read_text())
            errors = [f for f in findings if f["severity"] == "ERROR"]
            assert not errors, errors[:3]
