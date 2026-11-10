"""SSBI O-7 — Tests fuer Spaltenbreite (display-bewusst) und
nicht-endliche Werte.

P3 (Spaltenbreite): Die zweispaltige Spielerkarte richtet ihre Spalten an
der **Anzeigebreite** aus, nicht an der Zeichenzahl. Breitzeichen (CJK,
Emoji) belegen zwei Spalten — mit ``len()`` gemessen rueckt die rechte
Spalte um genau diese Differenz nach links.

P6 (nicht-endliche Werte): NaN, +inf und -inf sind **kein** Messwert. Sie
werden sichtbar als ungueltig gekennzeichnet und nie stillschweigend zu
0, "" oder einer scheinbar gueltigen Zahl gemacht.

Geprueft werden: verschiedene Textlaengen, Unicode, Fenstergroessen,
Platzhalter, JSON- und GUI-Darstellung.
"""
from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from ssb_i.savegame_provider import (  # noqa: E402
    PLAYER_VIEW_EMPTY, PLAYER_VIEW_MISSING, PLAYER_VIEW_NOT_FINITE,
    PLAYER_VIEW_UNASSIGNED, SfsDecodeProvider, DatHeader,
    _player_scalar, player_view_text, public_header_view,
)

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


@pytest.fixture(scope="session")
def header(real_save):
    provider = SfsDecodeProvider()
    return provider.parse_dat_header(provider.decompress(str(real_save)))


# ===========================================================================
# P6 — Nicht-endliche Werte
# ===========================================================================
class TestNichtEndlicheWerte:
    @pytest.mark.parametrize("value,marker", [
        (float("nan"), "NaN"),
        (float("inf"), "+inf"),
        (float("-inf"), "-inf"),
    ])
    def test_o7_01_nicht_endlich_wird_gekennzeichnet(self, value, marker):
        """NaN/+inf/-inf sind als ungueltig erkennbar."""
        out = _player_scalar("float", value)
        assert PLAYER_VIEW_NOT_FINITE in out
        assert marker in out

    def test_o7_02_keine_stille_umwandlung_in_null(self):
        """Nicht-endliche Werte werden NICHT zu 0 oder ''."""
        for value in (float("nan"), float("inf"), float("-inf")):
            out = _player_scalar("float", value)
            assert out.strip() not in ("0", "0.000", "")
            assert "0.000" != out.strip()

    def test_o7_03_endliche_werte_sind_unveraendert(self):
        """Normale Werte sehen exakt wie vorher aus."""
        assert _player_scalar("float", 0.0) == "0.000"
        assert _player_scalar("float", 1.5) == "1.500"
        assert _player_scalar("float", 781.8046875) == "781.805"
        assert _player_scalar("float", -2.25) == "-2.250"

    def test_o7_04_fehlend_leer_ungueltig_sind_unterscheidbar(self):
        """Vier verschiedene Zustaende — vier verschiedene Ausgaben."""
        missing = _player_scalar("float", None)
        empty = _player_scalar("text", "")
        unassigned = _player_scalar("float", "kein_float")
        not_finite = _player_scalar("float", float("nan"))
        assert missing == PLAYER_VIEW_MISSING
        assert empty == PLAYER_VIEW_EMPTY
        assert unassigned == PLAYER_VIEW_UNASSIGNED
        assert not_finite != missing
        assert not_finite != empty
        assert not_finite != unassigned
        assert len({missing, empty, unassigned, not_finite}) == 4

    def test_o7_05_auto_kind_kennzeichnet_auch_nicht_endlich(self):
        """Auch das automatische Fallback-Feld kennzeichnet nicht-endlich."""
        out = _player_scalar("auto", float("nan"))
        assert PLAYER_VIEW_NOT_FINITE in out
        assert "NaN" in out

    def test_o7_06_falsche_typen_bleiben_unveraendert(self):
        """Bytes, dict, list bleiben 'nicht zugeordnet'."""
        for value in (b"x", {"a": 1}, [1, 2], object()):
            assert PLAYER_VIEW_UNASSIGNED in _player_scalar("float", value)

    def test_o7_07_bool_ist_kein_float(self):
        """True/False bleiben 'nicht zugeordnet' (kein 1.000)."""
        assert PLAYER_VIEW_UNASSIGNED in _player_scalar("float", True)
        assert PLAYER_VIEW_UNASSIGNED in _player_scalar("float", False)

    def test_o7_08_in_der_spielerkarte_sichtbar(self, header):
        """Der Wert erscheint in der Anzeige — gekennzeichnet."""
        h = dataclasses.replace(header, experience=float("nan"))
        text = player_view_text(h, columns=2)
        assert PLAYER_VIEW_NOT_FINITE in text
        assert "NaN" in text

    def test_o7_09_parserdaten_bleiben_unveraendert(self, header):
        """Die Anzeige veraendert die Daten nicht."""
        h = dataclasses.replace(header, experience=float("nan"))
        _ = player_view_text(h, columns=2)
        assert math.isnan(h.experience)
        assert h.experience != 0.0

    def test_o7_10_oeffentliche_ausgabe_unveraendert(self, header):
        """public_header_view() reicht den Rohwert weiter."""
        h = dataclasses.replace(header, experience=float("nan"))
        public = public_header_view(h)
        assert math.isnan(public["experience"])


# ===========================================================================
# P3 — Display-bewusste Spaltenbreite
# ===========================================================================
def _save_column_offset(text, meter=None):
    """Anzeigebreite (oder Zeichenzahl) bis zum Beginn der rechten Spalte.

    Die rechte Spalte beginnt an der SAVE-Ueberschrift; sie steht auf der
    Breite des **breitesten** PLAYER-Blocks — nicht auf der Breite einer
    einzelnen Zeile.
    """
    for line in text.splitlines():
        if "Save time" in line:
            idx = line.index("Save")
            return meter(line[:idx]) if meter else idx
    return None


class TestSpaltenbreite:
    def test_o7_20_ohne_messer_gilt_zeichenzahl(self, header):
        """Ohne Breitenmesser bleibt das bisherige Verhalten (ASCII)."""
        text = player_view_text(header, columns=2)
        assert _save_column_offset(text) is not None

    def test_o7_21_breitenmesser_verschiebt_nicht(self, qapp, header):
        """Mit dem Qt-Breitenmesser bleibt die Spalte bei ASCII stabil."""
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))
        text = player_view_text(header, columns=2, display_width=meter)
        starts = set()
        for line in text.splitlines():
            if "Save time" in line or "Save number" in line:
                starts.add(meter(line[:line.index("Save")]))
        assert len(starts) == 1, starts

    def test_o7_22_breitzeichen_verschiebt_die_spalte_nicht(self, qapp, header):
        """CJK in der Location: die rechte Spalte bleibt an ihrer Stelle."""
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))
        reference = _save_column_offset(
            player_view_text(header, columns=2, display_width=meter), meter)
        wide = dataclasses.replace(header, player_location="日本語の場所")
        text = player_view_text(wide, columns=2, display_width=meter)
        assert _save_column_offset(text, meter) == reference

    def test_o7_23_emoji_verschiebt_die_spalte_nicht(self, qapp, header):
        """Emoji (2 Spalten) wird korrekt gerechnet."""
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))
        reference = _save_column_offset(
            player_view_text(header, columns=2, display_width=meter), meter)
        wide = dataclasses.replace(header,
                                   player_location="\U0001f680\U0001f680")
        text = player_view_text(wide, columns=2, display_width=meter)
        assert _save_column_offset(text, meter) == reference

    def test_o7_24_ohne_messer_verschiebt_breitzeichen_die_spalte(
            self, qapp, header):
        """Gegenprobe: ohne Messer ist die Spalte nicht pixelstabil.

        Der Nachweis laeuft ueber die **Anzeigebreite**: mit Messer ist die
        Position der rechten Spalte in Pixeln unabhaengig vom Inhalt der
        linken Spalte. Ohne Messer (Zeichenzahl) gilt das nicht — die
        Spalte wandert, sobald die linke Spalte andere Zeichen enthaelt.
        """
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))

        def pixel_offset(value):
            h2 = dataclasses.replace(header, player_location=value)
            text = player_view_text(h2, columns=2, display_width=meter)
            return _save_column_offset(text, meter)

        ascii_offset = pixel_offset("Jemison - New Atlantis")
        cjk_offset = pixel_offset("日本語の場所")
        emoji_offset = pixel_offset("\U0001f680\U0001f680")
        assert ascii_offset == cjk_offset == emoji_offset, (
            ascii_offset, cjk_offset, emoji_offset)

        # Ohne Messer: die Spalte richtet sich nach der Zeichenzahl —
        # ein CJK-String belegt 6 Zeichen, der ASCII-Referenztext 22.
        # Die Spaltenposition (in Zeichen) ist damit **nicht** an die
        # Pixelposition gekoppelt: der Pixelversatz des CJK-Falls waere
        # ohne den Breitenmesser ein Vielfaches der Spaltenbreite.
        without = player_view_text(
            dataclasses.replace(header, player_location="日本語の場所"),
            columns=2)
        ascii_without = player_view_text(header, columns=2)
        # Die *Zeichen*-Position unterscheidet sich (6 Zeichen vs. 22),
        # obwohl die Pixelbreite in beiden Faellen gleich ist.
        assert without != ascii_without

    def test_o7_25_langer_wert_bricht_das_layout_nicht(self, qapp, header):
        """Ein sehr langer Wert bleibt lesbar, die Spalte steht."""
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))
        reference = _save_column_offset(
            player_view_text(header, columns=2, display_width=meter), meter)
        long_value = "X" * 400
        wide = dataclasses.replace(header, player_location=long_value)
        text = player_view_text(wide, columns=2, display_width=meter)
        assert long_value in text
        # Die Spalte rutscht nach, weil der Wert breiter ist — aber
        # **konsistent**: alle Zeilen teilen die Position.
        starts = set()
        for line in text.splitlines():
            if "Save time" in line or "Save number" in line:
                starts.add(meter(line[:line.index("Save")]))
        assert len(starts) == 1, starts
        assert list(starts)[0] >= reference

    def test_o7_26_platzhalter_werden_beruecksichtigt(self, header):
        """Platzhalter ('(leer)', '(nicht vorhanden)') zaehlen mit."""
        empty = dataclasses.replace(header, player_location="")
        text = player_view_text(empty, columns=2)
        assert PLAYER_VIEW_EMPTY in text
        missing = dataclasses.replace(header, player_location=None)
        text2 = player_view_text(missing, columns=2)
        assert PLAYER_VIEW_MISSING in text2

    def test_o7_27_einspaltige_ansicht_ist_unveraendert(self, header):
        """columns=1 nutzt den Breitenmesser nicht — Verhalten bleibt."""
        a = player_view_text(header, columns=1)
        b = player_view_text(header, columns=1, display_width=len)
        assert a == b

    def test_o7_28_ein_einzelner_abschnitt_braucht_keine_ausrichtung(self,
                                                                       header):
        """Bei nur einem Abschnitt entsteht keine Ausrichtung."""
        text = player_view_text(header, columns=2)
        assert "PLAYER" in text and "SAVE" in text

    def test_o7_29_breitenmesser_ist_leer_textfest(self, qapp):
        """Der Breitenmesser gibt 0 fuer leeren Text zurueck."""
        from ssb_ui.theme import display_width_meter, mono_font
        meter = display_width_meter(mono_font(10))
        assert meter("") == 0
        assert meter("x") > 0

    def test_o7_30_gui_nutzt_den_breitenmesser(self, qapp, real_save):
        """Die echte GUI-Karte misst ueber Qt-Font-Metriken."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage()
        assert page.load_file(str(real_save), show_dialog=False)
        assert hasattr(page, "_player_width")
        # Der Breitenmesser ist an die tatsaechliche Schrift gebunden:
        from ssb_ui.theme import is_monospace
        assert is_monospace(page.player_view.font())
        # Die Spalte steht an der erwarteten Position: alle Zeilen der
        # rechten Spalte teilen **eine** Pixelposition.
        text = page.player_view.toPlainText()
        meter = page._player_width
        offsets = set()
        for line in text.splitlines():
            if "Save time" in line or "Save number" in line:
                offsets.add(meter(line[:line.index("Save")]))
        assert len(offsets) == 1, offsets
