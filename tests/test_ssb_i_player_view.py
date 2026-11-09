"""SSBI O-6 — vollstaendige Spielerinformation in der Spieleranalyse.

Prueft zwei Dinge getrennt:

  A) **Anzeige** — die Spieleranalyse zeigt jedes dekodierte Headerfeld.
     Grundlage sind ``PLAYER_VIEW_FIELDS``, ``player_view_rows/sections/text``
     und ``SavegamePage._format_player``.
  B) **Privacy-Abgrenzung** — dieselben Werte duerfen nicht in Diagnose-,
     Fehler- oder Statusausgaben erscheinen.

Grundsaetze dieser Datei:

  * Erwartete Werte werden **hartkodiert**, nicht aus dem Pruefling
    berechnet — sonst wuerde ein Implementierungsfehler mitreproduziert.
  * Reale Saves werden ausschliesslich **gelesen**; ein Hash-Vergleich
    vor/nach weist das nach (Golden Saves bleiben unveraendert).
  * Die Privacy-Negativtests haben eine Gegenprobe: die Marker muessen
    nachweislich im entpackten Save stehen. Ohne sie waeren die
    Negativergebnisse wertlos.

Marker (synthetisch, O-6):  O6_NAME_MARKER, O6_LOCATION_MARKER,
O6_PLAYTIME_MARKER, O6_RACE_MARKER
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from ssb_i import savegame_provider as provider_module  # noqa: E402
from ssb_i.savegame_provider import (  # noqa: E402
    PLAYER_VIEW_EMPTY, PLAYER_VIEW_EXCLUDED, PLAYER_VIEW_FIELDS,
    PLAYER_VIEW_MISSING, PLAYER_VIEW_UNASSIGNED, DatHeader, PlayerField,
    SfsDecodeProvider, filetime_to_utc, format_player_value,
    player_view_rows, player_view_sections, player_view_text,
    public_header_view, unmapped_header_fields,
)

PY = sys.executable

NAME_MARKER = "O6_NAME_MARKER"
LOCATION_MARKER = "O6_LOCATION_MARKER"
PLAYTIME_MARKER = "O6_PLAYTIME_MARKER"
RACE_MARKER = "O6_RACE_MARKER"
FORBIDDEN_MARKERS = (NAME_MARKER, LOCATION_MARKER, PLAYTIME_MARKER, RACE_MARKER)

#: Die Feldinventur als *Erwartung*, nicht als Ableitung aus dem Code.
EXPECTED_LABELS = (
    "Name", "Level", "Location", "Playtime", "Race", "Gender", "Experience",
    "Experience required", "Save time", "Save number", "Save version",
    "Save version 2", "Game version", "Created with", "Engine version",
    "Header size", "Header body end", "Plugin block at", "Plugin block size",
    "Unassigned field",
)

#: Die Anzeige vor O-6 — jedes dieser Felder muss weiterhin erscheinen.
LEGACY_FIELDS = (
    ("Name", "Cole"),
    ("Level", "24"),
    ("Location", "Jemison - New Atlantis"),
    ("Race", "HumanRace"),
    ("Playtime", "2d.10h.34m"),
    ("Gender", "0"),
    ("Experience", "781.805"),
    ("Experience required", "2030.000"),
    ("Game version", "1.16.244.0"),
    ("Save version", "153"),
    ("Engine version", "0x0000001B"),
    ("Save number", "47"),
)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def _parse(path) -> DatHeader:
    """Header eines Saves lesen (read-only)."""
    provider = SfsDecodeProvider()
    return provider.parse_dat_header(provider.decompress(str(path)))


def _real_save_47(real_saves) -> Path:
    """Der Mess-Save mit Save-Nummer 47 (Golden-Werte 1.16.244.0)."""
    for path in real_saves:
        if path.name.startswith("Save47"):
            return path
    pytest.fail("Save47 nicht in der Messbasis gefunden")


def _marked_save(tmp_path, name="o6_marked.sfs") -> Path:
    """Save mit eindeutigen Markern in allen vier Identitaetsfeldern."""
    from conftest import build_dat_payload, write_save
    payload = build_dat_payload(
        player_name=NAME_MARKER,
        player_location=LOCATION_MARKER,
        playtime=PLAYTIME_MARKER,
        race_name=RACE_MARKER,
    )
    return write_save(tmp_path / name, payload)


def _run_cli(args):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run([PY, str(REPO / "sfda_cli.py"), *args],
                          capture_output=True, text=True, env=env,
                          cwd=str(REPO), timeout=240)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def qapp():
    """Eine QApplication fuer alle GUI-Tests (offscreen)."""
    pytest.importorskip("PySide6", reason="PySide6 nur im Build-venv")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ===========================================================================
# A) Feldinventur — Vollstaendigkeit ist pruefbar, nicht behauptet
# ===========================================================================
class TestFeldinventur:
    def test_o6_01_jedes_headerfeld_ist_zugeordnet(self):
        """Kein dekodiertes Headerfeld bleibt unklassifiziert.

        Das ist die eigentliche Sperre gegen stillen Informationsverlust:
        ein neues ``DatHeader``-Feld ohne Eintrag in ``PLAYER_VIEW_FIELDS``
        oder ``PLAYER_VIEW_EXCLUDED`` laesst diesen Test fallen.
        """
        assert unmapped_header_fields() == ()

    def test_o6_02_inventur_ist_konsistent(self):
        """Keine Doppelungen, keine erfundenen Attribute, Begruendung je Ausschluss."""
        attrs = [item.attr for item in PLAYER_VIEW_FIELDS]
        assert len(attrs) == len(set(attrs)), "doppelter Eintrag in PLAYER_VIEW_FIELDS"
        header_fields = {f.name for f in DatHeader.__dataclass_fields__.values()}
        for attr in attrs:
            assert attr in header_fields, "%s existiert nicht in DatHeader" % attr
        for name, reason in PLAYER_VIEW_EXCLUDED.items():
            assert name in header_fields, "%s existiert nicht in DatHeader" % name
            assert reason.strip(), "Ausschluss ohne Begruendung: %s" % name

    def test_o6_03_anzahl_der_zeilen_entspricht_der_inventur(self):
        header = DatHeader(header_size=1, engine_version=1, save_version=1,
                           save_number=1, player_name="X", player_level=1,
                           player_location="Y", playtime="Z", race_name="R",
                           gender=0, experience=1.0, experience_required=2.0,
                           filetime=0, save_version_2=1,
                           current_game_version="v", created_game_version="v",
                           plugin_info_offset=0, plugin_info_size=0)
        assert len(player_view_rows(header)) == len(PLAYER_VIEW_FIELDS)
        assert len(header.__dataclass_fields__) == (
            len(PLAYER_VIEW_FIELDS) + len(PLAYER_VIEW_EXCLUDED))


# ===========================================================================
# A) Anzeige — alle vorhandenen Felder, ausdruecklich Location und Playtime
# ===========================================================================
class TestAnzeigeRealerSave:
    def test_o6_04_alle_felder_erscheinen(self, real_saves):
        text = player_view_text(_parse(_real_save_47(real_saves)))
        for label in EXPECTED_LABELS:
            assert label in text, "Feld fehlt in der Anzeige: %s" % label

    def test_o6_05_location_ist_sichtbar(self, real_saves):
        text = player_view_text(_parse(_real_save_47(real_saves)))
        line = [l for l in text.splitlines() if l.startswith("Location")][0]
        assert line.split(" ", 1)[1].strip() == "Jemison - New Atlantis"

    def test_o6_06_playtime_ist_sichtbar_und_vollstaendig(self, real_saves):
        """Playtime darf nicht gekuerzt werden — inklusive lokalisiertem Teil."""
        text = player_view_text(_parse(_real_save_47(real_saves)))
        line = [l for l in text.splitlines() if l.startswith("Playtime")][0]
        assert "2d.10h.34m" in line
        assert "2 Tage.10 Stunden.34 Minuten" in line

    def test_o6_07_race_und_level_sind_sichtbar(self, real_saves):
        text = player_view_text(_parse(_real_save_47(real_saves)))
        values = dict((line.split(".", 1)[0].strip(),
                       line.rsplit(" ", 1)[-1]) for line in text.splitlines()
                      if "." in line)
        assert "HumanRace" in text
        assert values["Level"] == "24"
        assert "HumanRace" in [l.split()[-1] for l in text.splitlines()
                              if l.startswith("Race")]

    def test_o6_08_weitere_felder_mit_wert(self, real_saves):
        """Alle neun Felder, die die alte Anzeige nicht zeigte."""
        text = player_view_text(_parse(_real_save_47(real_saves)))
        assert "134358573240754512 (2026-10-07 14:35:24 UTC)" in text
        for expected in ("Save version 2", "Created with", "Header size",
                         "Header body end", "Plugin block at",
                         "Plugin block size", "Unassigned field"):
            assert expected in text, expected
        assert "1.16.236.0" in text          # created_game_version
        assert "125" in text                 # header_size
        assert "141" in text                 # padding_end
        assert "0x000000A8" in text          # plugin_info_offset
        assert "5077" in text                # plugin_info_size

    def test_o6_09_erfahrung_ohne_praezisionsverlust(self, real_saves):
        """781.805 wurde frueher als 781.80 angezeigt — echte Kuerzung."""
        text = player_view_text(_parse(_real_save_47(real_saves)))
        assert "781.805" in text
        assert "781.80 " not in text

    def test_o6_10_geschlechtscode_wird_als_code_gekennzeichnet(self, real_saves):
        """Ein Code ohne belegte Bedeutung darf nicht als Wert gelesen werden."""
        text = player_view_text(_parse(_real_save_47(real_saves)))
        assert "0 (Code, Bedeutung nicht belegt)" in text

    def test_o6_11_regression_kein_altes_feld_geht_verloren(self, real_saves):
        """Jedes vor O-6 sichtbare Feld bleibt mit seinem Wert sichtbar."""
        text = player_view_text(_parse(_real_save_47(real_saves)))
        for label, expected in LEGACY_FIELDS:
            line = [l for l in text.splitlines() if l.startswith(label)]
            assert line, "altes Feld fehlt: %s" % label
            assert expected in line[0], (label, line[0])

    def test_o6_12_alle_realen_saves_vollstaendig(self, real_saves):
        """Die Anzeige ist nicht auf einen Save zugeschnitten."""
        for path in real_saves:
            text = player_view_text(_parse(path))
            for label in EXPECTED_LABELS:
                assert label in text, (path.name, label)
            for marker in (PLAYER_VIEW_UNASSIGNED,):
                assert marker not in text, (path.name, marker)

    def test_o6_13_zweispaltig_bleibt_vollstaendig(self, real_saves):
        """Die GUI-Variante (columns=2) zeigt dieselben Felder."""
        header = _parse(_real_save_47(real_saves))
        single = player_view_text(header)
        double = player_view_text(header, columns=2)
        for label in EXPECTED_LABELS:
            assert label in double, label
        assert len(double.splitlines()) < len(single.splitlines())


# ===========================================================================
# A) Fehlende, leere und unbekannte Werte
# ===========================================================================
class TestFehlendeUndUnbekannteWerte:
    def _header(self, **overrides) -> DatHeader:
        base = dict(header_size=125, engine_version=27, save_version=153,
                    save_number=47, player_name="Cole", player_level=24,
                    player_location="Jemison - New Atlantis",
                    playtime="2d.10h.34m.2 Tage.10 Stunden.34 Minuten",
                    race_name="HumanRace", gender=0, experience=781.805,
                    experience_required=2030.0, filetime=134358573240754512,
                    save_version_2=153, current_game_version="1.16.244.0",
                    created_game_version="1.16.236.0", plugin_info_offset=168,
                    plugin_info_size=5077, padding_end=141,
                    header_count_start=16, unknown_field_0=0)
        base.update(overrides)
        return DatHeader(**base)

    def test_o6_14_fehlende_werte_werden_gekennzeichnet(self):
        text = player_view_text(self._header(player_location=None,
                                            playtime=None, race_name=None))
        assert PLAYER_VIEW_MISSING in text
        for line in text.splitlines():
            if line.startswith(("Location", "Playtime", "Race")):
                assert PLAYER_VIEW_MISSING in line, line

    def test_o6_15_fehlender_wert_wird_nicht_erfunden(self):
        """Kein Platzhalter darf wie ein Messwert aussehen."""
        text = player_view_text(self._header(player_location=None))
        line = [l for l in text.splitlines() if l.startswith("Location")][0]
        assert "0" not in line.split(".", 1)[1].replace("(nicht im Save vorhanden)", "")

    def test_o6_16_leere_werte_werden_als_leer_gezeigt(self):
        text = player_view_text(self._header(player_name="", playtime=""))
        assert PLAYER_VIEW_EMPTY in text
        for line in text.splitlines():
            if line.startswith(("Name", "Playtime")):
                assert PLAYER_VIEW_EMPTY in line, line

    def test_o6_17_ungueltige_typen_werden_nicht_als_wert_ausgegeben(self):
        """Ein Text in einem Zahlenfeld ist kein Zahlenwert."""
        text = player_view_text(self._header(player_level="24",
                                            engine_version="0x1B",
                                            experience="781.805"))
        assert PLAYER_VIEW_UNASSIGNED in text
        for line in text.splitlines():
            if line.startswith(("Level", "Engine version", "Experience..")):
                assert PLAYER_VIEW_UNASSIGNED in line, line

    def test_o6_18_unbekanntes_feld_wird_angezeigt_statt_verschwiegen(self, monkeypatch):
        """Ein kuenftiges Parserfeld erscheint automatisch — ohne GUI-Aenderung."""
        header = self._header()
        future = SimpleNamespace(**asdict(header), future_field=42)
        monkeypatch.setattr(provider_module, "_dat_header_fieldnames",
                            lambda: tuple(f.name for f in
                                          DatHeader.__dataclass_fields__.values())
                            + ("future_field",))
        assert unmapped_header_fields() == ("future_field",)
        text = player_view_text(future)
        line = [l for l in text.splitlines() if l.startswith("future_field")]
        assert line, "unbekanntes Feld wird verschwiegen"
        assert line[0].rstrip().endswith("42")

    def test_o6_19_unbelegte_bedeutung_wird_benannt(self):
        value = format_player_value(
            PlayerField("unknown_field_0", "Unassigned field", "int",
                        "save", "Bedeutung nicht belegt"), 0)
        assert value == "0 (Bedeutung nicht belegt)"

    def test_o6_20_ungueltiger_zeitstempel(self):
        assert filetime_to_utc(0) is None
        assert filetime_to_utc(-5) is None
        assert filetime_to_utc("134358573240754512") is None
        assert filetime_to_utc(True) is None
        assert "kein gueltiger Zeitstempel" in format_player_value(
            PlayerField("filetime", "Save time", "filetime", "save"), 0)


# ===========================================================================
# A) Zeitstempel — belegte Ableitung, nicht geraten
# ===========================================================================
class TestFiletime:
    def test_o6_21_bekannter_wert(self):
        assert filetime_to_utc(134358573240754512) == "2026-10-07 14:35:24 UTC"

    def test_o6_22_reale_saves_gegen_dateinamen(self, real_saves):
        """Herleitung unabhaengig geprueft: der Dateiname traegt den Zeitstempel.

        Der Savegame-Dateiname enthaelt ``YYYYMMDDHHMMSS`` in UTC. Stimmt er
        mit dem aus ``filetime`` berechneten Zeitpunkt ueberein, ist die
        FILETIME-Deutung belegt und nicht angenommen.
        """
        pattern = re.compile(r"_(\d{14})_")
        checked = 0
        for path in real_saves:
            match = pattern.search(path.name)
            if not match:
                continue
            stamp = str(match.group(1))
            expected = "%s-%s-%s %s:%s:%s UTC" % (
                stamp[0:4], stamp[4:6], stamp[6:8],
                stamp[8:10], stamp[10:12], stamp[12:14])
            header = _parse(path)
            assert filetime_to_utc(header.filetime) == expected, path.name
            checked += 1
        assert checked >= 6, "zu wenige Saves geprueft: %d" % checked


# ===========================================================================
# A) GUI — die Karte nutzt genau diesen Weg
# ===========================================================================
class TestGui:
    def test_o6_23_format_player_zeigt_alle_felder(self, qapp, real_saves):
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage.__new__(SavegamePage)
        text = SavegamePage._format_player(page, _parse(_real_save_47(real_saves)))
        for label in EXPECTED_LABELS:
            assert label in text, label

    def test_o6_24_format_player_zeigt_marker(self, qapp, tmp_path):
        """Die Spieleranalyse ist der ausdruecklich angeforderte Kanal."""
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage.__new__(SavegamePage)
        text = SavegamePage._format_player(page, _parse(_marked_save(tmp_path)))
        for marker in FORBIDDEN_MARKERS:
            assert marker in text, marker


# ===========================================================================
# B) Privacy-Abgrenzung — dieselben Werte bleiben aus den Diagnosekanaelen
# ===========================================================================
class TestPrivacyAbgrenzung:
    def test_o6_25_gegenprobe_marker_stehen_im_save(self, tmp_path):
        """Ohne diese Gegenprobe waeren alle Negativtests wertlos."""
        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        for marker in FORBIDDEN_MARKERS:
            assert marker.encode() in raw, marker

    def test_o6_26_cli_save_info_text_ohne_identitaet(self, tmp_path):
        save = _marked_save(tmp_path)
        result = _run_cli(["save", "info", str(save)])
        assert result.returncode == 0, result.stderr
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker

    def test_o6_27_cli_save_info_json_ohne_identitaet(self, tmp_path):
        save = _marked_save(tmp_path)
        result = _run_cli(["--json", "save", "info", str(save)])
        assert result.returncode == 0, result.stderr
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker

    def test_o6_28_cli_save_header_ohne_identitaet(self, tmp_path):
        save = _marked_save(tmp_path)
        for args in (["save", "header", str(save)],
                     ["--json", "save", "header", str(save)]):
            result = _run_cli(args)
            assert result.returncode == 0, result.stderr
            for marker in FORBIDDEN_MARKERS:
                assert marker not in result.stdout, (args, marker)

    def test_o6_29_cli_save_verify_ohne_identitaet(self, tmp_path):
        save = _marked_save(tmp_path)
        for args in (["save", "verify", str(save)],
                     ["--json", "save", "verify", str(save)]):
            result = _run_cli(args)
            assert result.returncode == 0, result.stderr
            for marker in FORBIDDEN_MARKERS:
                assert marker not in result.stdout, (args, marker)

    def test_o6_30_gui_header_dump_ohne_identitaet(self, tmp_path):
        """Der Header-Dump ist Diagnose — er zeigt die oeffentliche Sicht."""
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage.__new__(SavegamePage)
        dump = SavegamePage._format_header_full(page, _parse(_marked_save(tmp_path)))
        for marker in FORBIDDEN_MARKERS:
            assert marker not in dump, marker

    def test_o6_31_gui_export_ohne_identitaet(self, tmp_path, monkeypatch):
        """Der Export laeuft ueber den echten Code-Pfad von ``on_save_report``."""
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ssb_ui.pages.savegame_page import SavegamePage

        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        header = provider.parse_dat_header(raw)
        plugins = provider.parse_plugin_info(raw, header)

        page = SavegamePage()
        page.current_path = str(save)
        page.decompressed = raw
        page.header = header
        page.plugins = plugins
        out_file = tmp_path / "export.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(out_file), "")))
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: None))
        SavegamePage.on_save_report(page)
        assert out_file.exists()
        blob = out_file.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, marker
        assert "path" not in json.loads(blob)

    def test_o6_32_oeffentliche_headeransicht_unveraendert(self, tmp_path):
        """Beide Sichten kommen aus demselben Header — nur eine zeigt Identitaet."""
        header = _parse(_marked_save(tmp_path))
        public = public_header_view(header)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in json.dumps(public, default=str), marker
        for name in ("player_name", "player_location", "race_name", "playtime"):
            assert name not in public, name
        # ... die Spieleransicht zeigt sie sehr wohl:
        player_text = player_view_text(header)
        for marker in FORBIDDEN_MARKERS:
            assert marker in player_text, marker


# ===========================================================================
# B) Golden Saves — read-only, nachgewiesen
# ===========================================================================
class TestGoldenSavesUnveraendert:
    def test_o6_33_hashes_vor_und_nach_dem_lesen_identisch(self, real_saves):
        before = {path.name: _sha256(path) for path in real_saves}
        mtimes = {path.name: path.stat().st_mtime_ns for path in real_saves}
        for path in real_saves:
            player_view_text(_parse(path))
        after = {path.name: _sha256(path) for path in real_saves}
        assert before == after
        assert mtimes == {path.name: path.stat().st_mtime_ns for path in real_saves}
