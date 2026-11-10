"""SSBI O-7 — Tests der Sensitivitaetsaufloesung im Privacy-Guard.

Der Guard bekommt in O-7 eine **explizite** Sensitivitaetszuordnung:

  * jedes Headerfeld wird genau einer Klasse zugeordnet
    (``IDENTITY`` / ``PUBLIC`` / ``UNKNOWN``);
  * ein Feld ohne Zuordnung gilt als ``UNKNOWN`` und wird **nicht**
    automatisch freigegeben (fail-closed);
  * die vollstaendige Spieler-Analyseansicht darf Identitaet zeigen —
    aber **nur** in diesem konkreten Pfad;
  * Diagnose-, Fehler-, Status-, Export- und Report-Kanaele bleiben
    geschuetzt.

Diese Tests sind bewusst in drei Gruppen geteilt:

  * **positiv** — die erlaubten Faelle bleiben ohne Befund;
  * **negativ**  — die verbotenen Faelle werden als ERROR gemeldet;
  * **adversarial** — Versuche, die Regel zu umgehen (fremder Formatter,
    umbenannter Sink, Zwischenmethode, Alias), werden erkannt.

Der Guard ist eine **statische** Erkennung. Er beweist keine Laufzeit-
sicherheit — das tut die empirische Gegenprobe in
``tests/test_ssb_i_privacy_boundary.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import privacy_ast_guard as G  # noqa: E402

from ssb_i.savegame_differential import IDENTITY_FIELDS  # noqa: E402
from ssb_i.savegame_provider import (  # noqa: E402
    DatHeader, PLAYER_VIEW_EXCLUDED, PLAYER_VIEW_FIELDS,
    PUBLIC_HEADER_FIELDS, unmapped_header_fields,
)


def _scan(tmp_path, source: str):
    """Kontrolliert eine Quelldatei mit dem Guard."""
    env = G.TypeEnv()
    guard = G.Guard(env)
    target = tmp_path / "probe.py"
    target.write_text(source, encoding="utf-8")
    env.learn(target)
    return G.check_file(target, tmp_path, guard)


def _rules(violations):
    return [v.rule for v in violations]


def _v4(violations):
    return [v for v in violations if v.rule == "V4_IDENTITY_IN_PROTECTED_SINK"]


# ===========================================================================
# Die Zuordnung selbst — sie muss mit der Quelle uebereinstimmen
# ===========================================================================
class TestSensitivitaetszuordnung:
    def test_guard_01_identitaetsmenge_stimmt_mit_quelle_ueberein(self):
        """IDENTITY in der Guard-Tabelle == IDENTITY_FIELDS im Produktivcode."""
        guard_identity = {f for f, c in G.FIELD_SENSITIVITY.items()
                          if c == G.SENSITIVITY_IDENTITY}
        assert guard_identity == set(IDENTITY_FIELDS)

    def test_guard_02_public_menge_stimmt_mit_quelle_ueberein(self):
        """PUBLIC in der Guard-Tabelle == PUBLIC_HEADER_FIELDS."""
        guard_public = {f for f, c in G.FIELD_SENSITIVITY.items()
                        if c == G.SENSITIVITY_PUBLIC}
        assert guard_public == set(PUBLIC_HEADER_FIELDS)

    def test_guard_03_unbekanntes_feld_ist_unknown(self):
        """fail-closed: kein Feldname wird automatisch freigegeben."""
        assert G.sensitivity_of("gibtsnicht") == G.SENSITIVITY_UNKNOWN
        assert G.sensitivity_of("") == G.SENSITIVITY_UNKNOWN
        assert G.sensitivity_of("player_name_x") == G.SENSITIVITY_UNKNOWN

    def test_guard_04_keine_automatik_aus_namensheuristik(self):
        """Ein Name, der nach Identitaet aussieht, wird NICHT freigegeben."""
        # "player_name_extra" ist kein deklariertes Feld -> UNKNOWN
        assert G.sensitivity_of("player_name_extra") == G.SENSITIVITY_UNKNOWN
        # "race" ist kein deklariertes Feld -> UNKNOWN
        assert G.sensitivity_of("race") == G.SENSITIVITY_UNKNOWN

    def test_guard_05_analysesicht_felder_stimmen_mit_quelle_ueberein(self):
        """Die Felder der Analysekette == PLAYER_VIEW_FIELDS + Fallback."""
        declared = {item.attr for item in PLAYER_VIEW_FIELDS}
        assert declared <= G.ANALYSIS_VIEW_FIELDS
        # Jedes ungemappte Feld ist ebenfalls Teil der Analysekette:
        for name in unmapped_header_fields():
            assert name in G.ANALYSIS_VIEW_FIELDS

    def test_guard_06_analysesicht_liest_identitaet(self):
        """Die Analysekette enthaelt nachweislich Identitaetsfelder."""
        assert G.analysis_view_reads_identity() is True
        identity = {f for f in G.ANALYSIS_VIEW_FIELDS
                    if G.sensitivity_of(f) == G.SENSITIVITY_IDENTITY}
        assert identity == set(IDENTITY_FIELDS)

    def test_guard_07_ausgeschlossene_felder_sind_keine_identitaet(self):
        """``header_count_start`` ist begruendet ausgeschlossen."""
        for name in PLAYER_VIEW_EXCLUDED:
            assert name not in G.ANALYSIS_VIEW_FIELDS


# ===========================================================================
# Positiv: erlaubte Faelle bleiben ohne Befund
# ===========================================================================
class TestPositiv:
    def test_guard_10_spielerkarte_ist_erlaubt(self, tmp_path):
        """Die ausdruecklich erlaubte Spieler-Analyseansicht."""
        src = '''
from ssb_i.savegame_provider import player_view_text
from PySide6.QtWidgets import QPlainTextEdit


def show(self, header) -> None:
    self.player_view.setPlainText(player_view_text(header, columns=2))
'''
        findings = _scan(tmp_path, src)
        assert not _v4(findings), _v4(findings)

    def test_guard_11_spielerkarte_ueber_zwischenmethode_ist_erlaubt(
            self, tmp_path):
        """Der reale Produktionspfad nutzt ``self._format_player(header)``."""
        src = '''
from ssb_i.savegame_provider import player_view_text
from PySide6.QtWidgets import QPlainTextEdit


class Page:
    def _format_player(self, h) -> str:
        return player_view_text(h, columns=2)

    def show(self, header) -> None:
        self.player_view.setPlainText(self._format_player(header))
'''
        findings = _scan(tmp_path, src)
        assert not _v4(findings), _v4(findings)

    def test_guard_12_oeffentliche_ausgabe_ist_erlaubt(self, tmp_path):
        """public_header_view() enthaelt keine Identitaet."""
        src = '''
from ssb_i.savegame_provider import public_header_view


def dump(header) -> None:
    print(public_header_view(header))
'''
        findings = _scan(tmp_path, src)
        assert not _v4(findings), _v4(findings)

    def test_guard_13_diagnosekanal_mit_nur_technischen_feldern_ist_erlaubt(
            self, tmp_path):
        """Direkte Lesezugriffe auf PUBLIC-Felder sind unkritisch."""
        src = '''
def dump(header) -> None:
    print("Level", header.player_level, "Version", header.save_version)
'''
        findings = _scan(tmp_path, src)
        assert not _v4(findings), _v4(findings)


# ===========================================================================
# Negativ: verbotene Faelle werden als ERROR gemeldet
# ===========================================================================
class TestNegativ:
    def test_guard_20_print_der_analysesicht_ist_ein_verstoss(self, tmp_path):
        src = '''
from ssb_i.savegame_provider import player_view_text


def dump(header) -> None:
    print(player_view_text(header, columns=2))
'''
        findings = _scan(tmp_path, src)
        v4 = _v4(findings)
        assert v4, "Druck der Spieleranalyse muss ein ERROR sein"
        assert v4[0].severity == "ERROR"

    def test_guard_21_settext_der_analysesicht_ist_ein_verstoss(self, tmp_path):
        src = '''
from ssb_i.savegame_provider import player_view_text
from PySide6.QtWidgets import QLabel


def show(label: QLabel, header) -> None:
    label.setText(player_view_text(header, columns=2))
'''
        findings = _scan(tmp_path, src)
        assert _v4(findings)
        assert _v4(findings)[0].severity == "ERROR"

    def test_guard_22_zwischenmethode_in_geschuetztem_kanal(self, tmp_path):
        """Auch ueber eine Zwischenmethode wird der Leak erkannt."""
        src = '''
from ssb_i.savegame_provider import player_view_text


def _fmt(header) -> str:
    return player_view_text(header, columns=2)


def dump(header) -> None:
    print(_fmt(header))
'''
        findings = _scan(tmp_path, src)
        assert _v4(findings), "Zwischenmethode umgeht die Regel nicht"

    def test_guard_23_zuweisung_in_geschuetztem_kanal(self, tmp_path):
        """Auch ueber eine lokale Variable wird der Leak erkannt."""
        src = '''
from ssb_i.savegame_provider import player_view_text


def dump(header) -> None:
    text = player_view_text(header, columns=2)
    print(text)
'''
        findings = _scan(tmp_path, src)
        assert _v4(findings), "Lokale Variable umgeht die Regel nicht"


# ===========================================================================
# Adversarial: Umgehungsversuche
# ===========================================================================
class TestAdversarial:
    def test_guard_30_fremder_formatter_mit_identitaet_ist_nicht_freigegeben(
            self, tmp_path):
        """Keine pauschale Ausnahme fuer "irgendein Formatter"."""
        src = '''
def leak_formatter(header) -> str:
    return "Name: %s" % header.player_name


def dump(header) -> None:
    print(leak_formatter(header))
'''
        findings = _scan(tmp_path, src)
        # Der Formatter ist nicht aufgeloest — der Guard darf nichts
        # behaupten, dass er nicht belegen kann. Er MUSS aber auch nicht
        # freigeben:
        assert not [v for v in findings
                    if v.rule == "V4_IDENTITY_IN_PROTECTED_SINK"
                    and "freigegeben" in v.detail]
        # Der bestehende Herkunftsbefund bleibt unveraendert:
        assert findings, "Der Kanal muss weiterhin beanstandet werden"

    def test_guard_31_umbenannter_sink_wird_erkannt(self, tmp_path):
        """Die Erlaubnis haengt am konkreten Pfad, nicht am Formatter."""
        src = '''
from ssb_i.savegame_provider import player_view_text
from PySide6.QtWidgets import QPlainTextEdit


def show(view: QPlainTextEdit, header) -> None:
    view.setPlainText(player_view_text(header, columns=2))
'''
        findings = _scan(tmp_path, src)
        assert _v4(findings), "Ein fremdes Objekt ist kein erlaubter Sink"

    def test_guard_32_zweiter_sink_in_der_selben_datei(self, tmp_path):
        """Der erlaubte Sink macht die anderen Kanaele nicht erlaubt."""
        src = '''
from ssb_i.savegame_provider import player_view_text
from PySide6.QtWidgets import QPlainTextEdit


def show(self, view: QPlainTextEdit, header) -> None:
    self.player_view.setPlainText(player_view_text(header, columns=2))
    view.setPlainText(player_view_text(header, columns=2))
'''
        findings = _scan(tmp_path, src)
        assert len(_v4(findings)) == 1, _v4(findings)

    def test_guard_33_unbekanntes_feld_wird_nicht_freigegeben(self, tmp_path):
        """Ein Feld ohne Sensitivitaetszuordnung bleibt unaufgeloest."""
        assert G.sensitivity_of("player_name_typo") == G.SENSITIVITY_UNKNOWN

    def test_guard_34_die_guard_tabelle_ist_fail_closed(self):
        """Nicht deklarierte Felder ergeben nie PUBLIC."""
        for field in ("player_name", "player_location", "playtime",
                      "race_name"):
            assert G.sensitivity_of(field) == G.SENSITIVITY_IDENTITY
        # Ein zukuenftiges Feld, das niemand deklariert hat:
        assert G.sensitivity_of("neues_feld_2099") == G.SENSITIVITY_UNKNOWN


# ===========================================================================
# Der Produktionscode muss sauber bleiben
# ===========================================================================
class TestProduktionscode:
    def test_guard_40_kein_error_im_produktionscode(self):
        """Der Guard meldet im Produktionscode weiterhin 0 ERROR.

        Wichtig: der TypeEnv muss **alle** Produktionsdateien kennen,
        sonst sind kontrollierte Modulkonstanten (z. B. ``APP_NAME``)
        nicht aufgeloest und es entstehen Scheinbefunde.
        """
        env = G.TypeEnv()
        # Alle Produktionsdateien zuerst lernen — in derselben Reihenfolge
        # wie der bestehende Guard-Test (die Lernreihenfolge ist relevant:
        # Modulkonstanten werden ueber die Datei aufgeloest).
        for rel in ("ssb_i/savegame_provider.py", "ssb_i/save_integrity.py",
                    "ssb_i/errors.py", "ssb_i/savegame_differential.py",
                    "sfda_cli.py", "ssb_ui/app.py",
                    "ssb_ui/pages/savegame_page.py"):
            path = REPO / rel
            if path.exists():
                env.learn(path)
        guard = G.Guard(env)
        findings = []
        for rel in ("ssb_i/savegame_provider.py", "ssb_i/save_integrity.py",
                    "ssb_i/errors.py", "ssb_i/savegame_differential.py",
                    "sfda_cli.py", "ssb_ui/app.py",
                    "ssb_ui/pages/savegame_page.py"):
            path = REPO / rel
            if path.exists():
                findings.extend(G.check_file(path, REPO, guard))
        errors = [v for v in findings if v.severity == "ERROR"]
        assert not errors, [(v.file, v.line, v.rule, v.detail) for v in errors[:5]]

    def test_guard_41_spielerkarte_bleibt_ohne_v4(self):
        """Im echten Produktionspfad entsteht kein V4-Befund."""
        env = G.TypeEnv()
        guard = G.Guard(env)
        path = REPO / "ssb_ui" / "pages" / "savegame_page.py"
        env.learn(path)
        findings = G.check_file(path, REPO, guard)
        assert not _v4(findings), _v4(findings)

    def test_guard_42_die_analyseansicht_zeigt_locale_und_playtime(self):
        """Die erlaubte Ausnahme umfasst Location und Playtime."""
        assert "player_location" in G.ANALYSIS_VIEW_FIELDS
        assert "playtime" in G.ANALYSIS_VIEW_FIELDS
        assert G.sensitivity_of("player_location") == G.SENSITIVITY_IDENTITY
        assert G.sensitivity_of("playtime") == G.SENSITIVITY_IDENTITY
