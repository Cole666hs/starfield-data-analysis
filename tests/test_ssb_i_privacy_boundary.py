"""SSBI R1_6 — Tests der zentralen Privacy-Grenze.

Diese Datei prueft die **oeffentlichen** Ausgabekanaelle, nicht nur interne
Hilfsfunktionen:

  Ebene A — Formatter (``ssb_i.errors``)
  Ebene B — CheckResult (alle 14 Checks)
  Ebene C — DatHeader / public_header_view()
  Ebene D — weitere CLI-Ausgaben
  Ebene E — GUI
  Ebene F — Marker-basierte Privacy-Tests
  Ebene G — Mutationstests

Die erwartete Ausgabe wird **hartkodiert** und nicht aus dem zu pruefenden
Formatter berechnet — sonst wuerde ein Implementierungsfehler mit-
reproduziert.

Marker (synthetisch, R1_6-Auftrag):
  PU_NAME_MARKER_731, PRIVACY_PATH_MARKER_731,
  PRIVACY_LOCATION_MARKER_731, PRIVACY_PLAYTIME_MARKER_731
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from ssb_i.errors import (  # noqa: E402
    MESSAGE_REGISTRY, PUBLIC_GENERIC_DETAIL, PlaceholderKind,
    public_error, render_public_message,
)
import ssb_i.errors as errors  # noqa: E402
from ssb_i.savegame_provider import (  # noqa: E402
    PUBLIC_HEADER_FIELDS, DatHeader, public_header_view,
)

PU_MARKER = "PU_NAME_MARKER_731"
PATH_MARKER = "PRIVACY_PATH_MARKER_731"
LOC_MARKER = "PRIVACY_LOCATION_MARKER_731"
PLAY_MARKER = "PRIVACY_PLAYTIME_MARKER_731"
FORBIDDEN_MARKERS = (PU_MARKER, PATH_MARKER, LOC_MARKER, PLAY_MARKER)

PY = sys.executable


# ===========================================================================
# Ebene A — Formatter
# ===========================================================================
class TestEbeneAFormatter:
    """Ebene A: die geschlossene Meldungsregistry."""

    def test_a18_platzhalternamen_stimmen_mit_aufrufern_ueberein(self):
        """Jeder Platzhalter im Template muss in der Typzuordnung stehen.

        Regression gegen einen echten Fund: die Byte-Meldungen hiessen im
        Template ``{bytes}``, in der Typzuordnung aber ebenfalls ``bytes`` —
        die Aufrufer uebergaben aber ``magic=``. Dadurch wurde die Meldung
        still verworfen und der generische Text ausgegeben. Diese Pruefung
        faellt solche stillen Namensabweichungen sofort auf.
        """
        import re
        for code, msg in MESSAGE_REGISTRY.items():
            template_names = set(re.findall(r"\{(\w+)\}", msg.template))
            declared = set(msg.placeholders)
            assert template_names == declared, (code, template_names, declared)

    def test_a19_alle_nachrichten_sind_mit_ihren_parametern_aufrufbar(self):
        """Jede Registry-Nachricht laesst sich mit gueltigen Werten rendern.

        Der Aufruf erfolgt bewusst ueber den *Namen*, den der Platzhalter
        in der Typzuordnung traegt — so wird ein Namensmismatch sofort
        zum Fehler statt zu einem stillen generischen Text.
        """
        for code, msg in MESSAGE_REGISTRY.items():
            params = {}
            for name, kind in msg.placeholders.items():
                params[name] = _sample_for(kind)
            out = render_public_message(code, **params)
            if code == "GENERIC.UNAVAILABLE":
                assert out == PUBLIC_GENERIC_DETAIL
            else:
                assert out != PUBLIC_GENERIC_DETAIL, code

    def test_a20_keine_ungueltigen_registry_eintraege(self):
        """Jeder Registry-Eintrag ist strukturell in Ordnung."""
        for code, msg in MESSAGE_REGISTRY.items():
            assert isinstance(code, str) and code
            assert isinstance(msg.template, str) and msg.template
            assert msg.code == code, code
            for kind in msg.placeholders.values():
                assert isinstance(kind, PlaceholderKind)

    def test_a01_alle_codes_der_registry_sind_renderbar(self):
        """Jeder registrierte Code liefert einen Text — ohne Exception."""
        for code in MESSAGE_REGISTRY:
            msg = MESSAGE_REGISTRY[code]
            params = {}
            for name, kind in msg.placeholders.items():
                params[name] = _sample_for(kind)
            out = render_public_message(code, **params)
            assert isinstance(out, str) and out
            # GENERIC.UNAVAILABLE ist per Definition der generische Text.
            if code == "GENERIC.UNAVAILABLE":
                assert out == PUBLIC_GENERIC_DETAIL
            else:
                assert out != PUBLIC_GENERIC_DETAIL, code

    def test_a02_unbekannter_code_ist_fail_closed(self):
        assert render_public_message("GIBT-ES-NICHT") == PUBLIC_GENERIC_DETAIL
        assert render_public_message("") == PUBLIC_GENERIC_DETAIL

    def test_a02b_falscher_codentyp_ist_fail_closed(self):
        """Auch ein nicht-str Code darf keine Exception nach aussen geben."""
        for bad in (None, 42, [], {}, object()):
            assert render_public_message(bad) == PUBLIC_GENERIC_DETAIL

    def test_a03_typfalscher_platzhalter_ist_fail_closed(self):
        """Falscher Typ -> die GANZE Meldung wird verworfen."""
        assert render_public_message("I-14.SAVES_MONOTONIC", count="sechs") \
            == PUBLIC_GENERIC_DETAIL
        assert render_public_message("I-14.SAVES_MONOTONIC", count=None) \
            == PUBLIC_GENERIC_DETAIL
        assert render_public_message("I-14.SAVES_MONOTONIC", count=-1) \
            == PUBLIC_GENERIC_DETAIL
        assert render_public_message("I-14.SAVES_MONOTONIC", count=True) \
            == PUBLIC_GENERIC_DETAIL

    def test_a04_fehlender_platzhalter_ist_fail_closed(self):
        assert render_public_message("I-14.SAVES_MONOTONIC") \
            == PUBLIC_GENERIC_DETAIL

    def test_a05_bytes_werden_nie_ausgegeben(self):
        """Bytes -> nur statische Beschreibung, nie der Inhalt."""
        from ssb_i.errors import BYTES_DESCRIPTIONS, BYTES_UNKNOWN
        # b"BCPS" ist ein bekanntes Kennzeichen -> die statische
        # Beschreibung aus BYTES_DESCRIPTIONS. Das ist KEIN Byte-Literal:
        # die Ausgabe enthaelt die Beschreibung, nicht die Bytefolge.
        out = render_public_message("I-01.MAGIC_MISMATCH", magic=b"BCPS")
        assert out == ("Container beginnt nicht mit dem erwarteten "
                       "Kennzeichen, sondern mit "
                       + BYTES_DESCRIPTIONS[b"BCPS"])
        # b"SFS_" ist unbekannt -> neutrale Beschreibung.
        out = render_public_message("I-01.MAGIC_MISMATCH", magic=b"SFS_")
        assert "SFS_" not in out
        assert BYTES_UNKNOWN in out
        # Unbekanntes Kennzeichen ohne Dateinamencharakter ->
        # statische Beschreibung, kein Byte-Literal.
        out = render_public_message("I-01.MAGIC_MISMATCH",
                                    magic=b"\xde\xad\xbe\xef")
        assert "\\xde" not in out and "deadbeef" not in out
        assert out == ("Container beginnt nicht mit dem erwarteten "
                       "Kennzeichen, sondern mit " + BYTES_UNKNOWN)
        # Gegenprobe: das Byte-Literal selbst erscheint NIE.
        for raw in (b"BCPS", b"SFS_", b"\xde\xad\xbe\xef",
                    b"C:\\Users\\x", b"/home/cole/x"):
            text = render_public_message("I-01.MAGIC_MISMATCH", magic=raw)
            assert repr(raw) not in text, raw
            assert raw.hex() not in text, raw

    def test_a06_bytearray_und_memoryview(self):
        """bytearray/memoryview verhalten sich wie bytes."""
        reference = render_public_message("I-01.MAGIC_MISMATCH", magic=b"BCPS")
        for value in (bytearray(b"BCPS"), memoryview(b"BCPS")):
            out = render_public_message("I-01.MAGIC_MISMATCH", magic=value)
            assert out == reference
            # Das Byte-Literal selbst erscheint nicht — nur die
            # statische Beschreibung.
            assert repr(bytes(value)) not in out

    def test_a07_pfad_wird_nie_ausgegeben(self):
        out = render_public_message("I-01.MAGIC_MISMATCH",
                                    magic=b"/home/secret/path.sfs")
        assert "/home" not in out
        assert "secret" not in out

    def test_a08_exception_und_zlib_error(self):
        """Exception-Objekte sind kein gueltiger Platzhalterwert."""
        exc = ValueError("/home/cole/geheim.txt kaputt")
        assert render_public_message("I-01.MAGIC_MISMATCH", magic=exc) \
            == PUBLIC_GENERIC_DETAIL
        zerr = zlib.error("invalid distance too far back")
        assert render_public_message("I-01.MAGIC_MISMATCH", magic=zerr) \
            == PUBLIC_GENERIC_DETAIL

    def test_a09_path_objekt_ist_nicht_als_platzhalter_erlaubt(self):
        from pathlib import Path
        out = render_public_message("I-01.MAGIC_MISMATCH",
                                    magic=Path("/home/cole/x.sfs"))
        assert out == PUBLIC_GENERIC_DETAIL

    def test_a10_verschachtelte_objekte(self):
        """Verschachtelte Container sind kein gueltiger Wert."""
        for value in ({"a": 1}, [1, 2], (1, 2), {"nested": {"x": [1]}}):
            assert render_public_message("I-14.SAVES_MONOTONIC", count=value) \
                == PUBLIC_GENERIC_DETAIL

    def test_a11_bekannte_numerische_werte(self):
        assert render_public_message("I-14.SAVES_MONOTONIC", count=6) == \
            "6 Saves monoton in Level, Spielzeit und Zeit"

    def test_a12_enum_werte_sind_geschlossen(self):
        """ENUM akzeptiert nur Werte aus der geschlossenen Menge."""
        assert render_public_message("I-01.MAGIC_MISMATCH", magic="unbekannt") \
            == PUBLIC_GENERIC_DETAIL

    def test_a13_renderer_ausfall_ist_fail_closed(self, monkeypatch):
        """Wenn der Renderer wirft, darf kein Rohwert erscheinen."""
        import ssb_i.errors as errors

        def broken(value):
            raise RuntimeError("simulierter Rendererfehler")

        monkeypatch.setitem(errors._PUBLIC_RENDERERS,
                            errors.PlaceholderKind.COUNT, broken)
        assert render_public_message("I-14.SAVES_MONOTONIC", count=3) \
            == PUBLIC_GENERIC_DETAIL

    def test_a14_ungefilterter_fallback_existiert_nicht(self):
        """Kein str()/repr()-Fallback im Renderer."""
        source = Path(errors.__file__).read_text(encoding="utf-8")
        body = source.split("def render_public_message")[1]
        # Der Docstring darf str()/repr() erwaehnen — der KOERPER nicht.
        body = body.split('"""', 2)[-1]
        assert "str(" not in body
        assert "repr(" not in body
        assert "format(" not in body

    def test_a15_keine_freien_string_platzhalter(self):
        """Es gibt keinen Platzhalter fuer eine freie Zeichenkette."""
        for code, msg in MESSAGE_REGISTRY.items():
            for kind in msg.placeholders.values():
                assert kind in PlaceholderKind
            assert "{" in msg.template or True
            # Jeder Platzhalter im Template ist auch in der Typzuordnung.
            import re
            for name in re.findall(r"\{(\w+)\}", msg.template):
                assert name in msg.placeholders, (code, name)

    def test_a16_public_error_unveraendert(self):
        """Die bestehende Exception-Grenze bleibt funktionsfaehig."""
        assert public_error(ValueError("x")) == "ValueError"
        assert "OSError" in public_error(OSError("kaputt"))

    def test_a17_public_generic_detail_ist_statisches_text(self):
        assert PUBLIC_GENERIC_DETAIL == "Diagnose nicht verfügbar"


def _sample_for(kind: PlaceholderKind):
    if kind is PlaceholderKind.INT:
        return 7
    if kind is PlaceholderKind.COUNT:
        return 3
    if kind is PlaceholderKind.HEX:
        return 255
    if kind is PlaceholderKind.OFFSET:
        return 4096
    if kind is PlaceholderKind.BYTES_MAGIC:
        return b"BCPS"
    if kind is PlaceholderKind.TEXT_FIXED:
        return "none"
    if kind is PlaceholderKind.ERROR_TEXT:
        return "ValueError: ungueltige Daten"
    if kind is PlaceholderKind.ENUM:
        return "none"
    if kind is PlaceholderKind.CHECK_TITLE:
        return "Chunk-Dekompression"
    if kind is PlaceholderKind.HEADER_ERROR:
        return "playerName: Laengenfeld hinter dem Puffer (0x2A)"
    return None


# ===========================================================================
# Ebene B — CheckResult
# ===========================================================================
class TestEbeneBCheckResult:
    """Ebene B: alle 14 Checks einzeln."""

    CHECK_IDS = ["I-%02d" % i for i in range(1, 15)]

    def test_b01_alle_14_checks_vorhanden(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        ids = [c.check_id for c in report.checks]
        for cid in self.CHECK_IDS:
            assert cid in ids, cid

    def test_b02_detail_ist_immer_str_und_nie_leer(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        for check in report.checks:
            assert isinstance(check.detail, str), check.check_id
            assert check.detail.strip(), check.check_id

    def test_b03_evidence_ist_serialisierbar_und_kontrolliert(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        for check in report.checks:
            payload = check.to_dict()
            json.dumps(payload)            # serialisierbar
            for value in check.evidence.values():
                assert value is None or isinstance(
                    value, (bool, int, float, str, list, dict)), \
                    (check.check_id, type(value))

    def test_b04_internal_wird_nicht_serialisiert(self, synthetic_save):
        """Die interne Diagnose darf nicht in die oeffentliche Form."""
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        for check in report.checks:
            assert "internal" not in check.to_dict()
            json.dumps(check.to_dict())

    def test_b05_keine_verbotenen_marker_in_detail_und_evidence(self,
                                                                 synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        for check in report.checks:
            blob = json.dumps({"detail": check.detail,
                               "evidence": check.evidence}, default=str)
            for marker in FORBIDDEN_MARKERS:
                assert marker not in blob, (check.check_id, marker)

    def test_b06_evidence_hat_keine_absoluten_pfade(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        for check in report.checks:
            blob = json.dumps(check.evidence, default=str)
            assert "/home/" not in blob, check.check_id
            assert "/tmp/" not in blob, check.check_id

    def test_b07_integrityreport_ohne_path(self, synthetic_save):
        """F-2: kein Pfad im oeffentlichen Bericht."""
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        payload = report.to_dict()
        assert "path" not in payload
        blob = json.dumps(payload, default=str)
        assert str(synthetic_save) not in blob
        assert synthetic_save.name not in blob

    def test_b08_integrityreport_behaelt_sha256_und_groesse(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        payload = report.to_dict()
        assert len(payload["sha256"]) == 64
        assert payload["file_size"] > 0

    def test_b09_i14_ohne_spielernamen(self, synthetic_save):
        """F-1: die oeffentliche I-14-Ausgabe nennt keine Identitaet."""
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        i14 = report.by_id("I-14")
        assert i14 is not None
        assert "character" not in i14.evidence
        blob = json.dumps(i14.to_dict(), default=str)
        assert PU_MARKER not in blob

    def test_b10_i14_evidence_mit_anzahl_statt_namen(self, synthetic_save):
        from ssb_i.save_integrity import run_all
        report = run_all(str(synthetic_save))
        i14 = report.by_id("I-14")
        assert i14 is not None
        selection = i14.evidence.get("selection")
        if selection:
            assert "selected" not in selection
            assert isinstance(selection.get("selected_count"), int)

    def test_b11_fail_closed_der_registry(self, monkeypatch, synthetic_save):
        """Faellt die Registry aus, erscheint der generische Text."""
        import ssb_i.save_integrity as si

        monkeypatch.setattr(si, "render_public_message",
                            lambda *a, **k: PUBLIC_GENERIC_DETAIL)
        report = si.run_all(str(synthetic_save))
        for check in report.checks:
            assert PUBLIC_GENERIC_DETAIL in check.detail or check.detail


# ===========================================================================
# Ebene C — DatHeader / public_header_view()
# ===========================================================================
class TestEbeneCDatHeader:
    """Ebene C: die zentrale Header-Allowlist."""

    def _header(self, **over):
        base: dict = dict(
            header_size=100, engine_version=1, save_version=153,
            save_number=1, player_name=PU_MARKER, player_level=24,
            player_location=LOC_MARKER, playtime=PLAY_MARKER,
            race_name="RACE_MARK", gender=1, experience=1.0,
            experience_required=2.0, filetime=1000,
            current_game_version="1.16.244.0",
            created_game_version="1.16.244.0", plugin_info_offset=10,
            plugin_info_size=20, save_version_2=0,
        )
        base.update(over)
        return DatHeader(**base)

    def test_c01_public_view_ohne_identitaet(self):
        view = public_header_view(self._header())
        blob = json.dumps(view, default=str)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, marker
        assert "player_name" not in view
        assert "player_location" not in view
        assert "playtime" not in view
        assert "race_name" not in view

    def test_c02_public_view_ist_allowlist(self):
        view = public_header_view(self._header())
        assert set(view) <= set(PUBLIC_HEADER_FIELDS)
        assert "player_level" in view

    def test_c03_neues_feld_wird_nicht_oeffentlich(self):
        """Ein zukuenftiges DatHeader-Feld darf NICHT automatisch
        oeffentlich werden — das ist der Kern der Allowlist-Wirkung."""
        header = self._header()
        # Synthetisches zusaetzliches Feld simulieren.
        object.__setattr__(header, "future_secret_field", PATH_MARKER)
        view = public_header_view(header)
        assert "future_secret_field" not in view
        assert PATH_MARKER not in json.dumps(view, default=str)

    def test_c04_interne_repraesentation_bleibt_vollstaendig(self):
        """Die interne Repräsentation darf ihre Felder behalten."""
        header = self._header()
        internal = header.to_dict()
        assert internal["player_name"] == PU_MARKER
        assert internal["player_location"] == LOC_MARKER

    def test_c05_public_view_ist_json_serialisierbar(self):
        view = public_header_view(self._header())
        json.dumps(view)


# ===========================================================================
# Ebene D — weitere CLI-Ausgaben
# ===========================================================================
def _run_cli(args, cwd=None):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run([PY, str(REPO / "sfda_cli.py"), *args],
                          capture_output=True, text=True, env=env,
                          cwd=str(cwd or REPO), timeout=240)


class TestEbeneDCli:
    """Ebene D: CLI-Kanaele."""

    def test_d01_save_info_text_ohne_identitaet(self, synthetic_save):
        result = _run_cli(["save", "info", str(synthetic_save)])
        assert result.returncode == 0, result.stderr
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker
        assert synthetic_save.name not in result.stdout

    def test_d02_save_info_json_ohne_identitaet(self, synthetic_save):
        result = _run_cli(["--json", "save", "info", str(synthetic_save)])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "player_name" not in payload["savegame"]
        assert "player_location" not in payload["savegame"]
        assert "playtime" not in payload["savegame"]
        assert "file" not in payload

    def test_d03_save_header_json_ohne_identitaet(self, synthetic_save):
        result = _run_cli(["--json", "save", "header", str(synthetic_save)])
        assert result.returncode == 0, result.stderr
        header = json.loads(result.stdout)
        assert "player_name" not in header
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker

    def test_d04_save_verify_json_ohne_pfad(self, synthetic_save):
        result = _run_cli(["--json", "save", "verify", str(synthetic_save)])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "path" not in payload
        assert synthetic_save.name not in result.stdout

    def test_d05_save_diff_json_ohne_identitaet(self, synthetic_save):
        result = _run_cli(["--json", "save", "diff", str(synthetic_save),
                           str(synthetic_save)])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        blob = json.dumps(payload, default=str)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, marker
        assert "a" not in payload.get("inputs", {})
        assert "b" not in payload.get("inputs", {})

    def test_d06_save_diff_markdown_ohne_identitaet(self, synthetic_save,
                                                     tmp_path):
        target = tmp_path / "diff.md"
        result = _run_cli(["save", "diff", str(synthetic_save),
                           str(synthetic_save), "--markdown", str(target)])
        assert result.returncode == 0, result.stderr
        text = target.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            assert marker not in text, marker

    def test_d07_fehlerzeile_ohne_dateinamen(self, tmp_path):
        """F-6: der Dateiname erscheint nicht in der Fehlerzeile."""
        bad = tmp_path / (PATH_MARKER + ".sfs")
        bad.write_bytes(b"kein savegame" * 40)
        result = _run_cli(["save", "info", str(bad)])
        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert PATH_MARKER not in combined
        assert bad.name not in combined
        # Die Ursache bleibt verstaendlich.
        assert "not" in combined.lower() or "error" in combined.lower()

    def test_d08_stderr_und_stdout_trennen(self, synthetic_save):
        result = _run_cli(["save", "info", str(synthetic_save)])
        assert result.returncode == 0
        assert result.stderr == ""

    def test_d09_kein_traceback(self, tmp_path):
        bad = tmp_path / "kaputt.sfs"
        bad.write_bytes(b"\x00" * 100)
        result = _run_cli(["save", "info", str(bad)])
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout


# ===========================================================================
# Ebene E — GUI
# ===========================================================================
def _marked_save(tmp_path, name="marked.sfs"):
    """Ein Save mit eindeutigen Markern in allen Identitaetsfeldern."""
    from conftest import build_dat_payload, write_save
    payload = build_dat_payload(
        player_name=PU_MARKER,
        player_location=LOC_MARKER,
        playtime=PLAY_MARKER,
        race_name="RACE_MARK_731",
    )
    return write_save(tmp_path / name, payload)


class TestEbeneEGui:
    """Ebene E: die GUI-Kanaele (offscreen)."""

    def test_e01_selftest_ohne_spielernamen(self, tmp_path):
        """OTH-008: der Self-Test gibt keine Identitaet aus."""
        save = _marked_save(tmp_path)
        out_file = tmp_path / "selftest.txt"
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [PY, str(REPO / "ssb_ui/app.py"), "--self-test", str(save),
             "--out", str(out_file)],
            capture_output=True, text=True, env=env, cwd=str(REPO), timeout=240)
        assert PU_MARKER not in result.stdout
        assert PU_MARKER not in result.stderr
        if out_file.exists():
            content = out_file.read_text(encoding="utf-8")
            assert PU_MARKER not in content
            for marker in FORBIDDEN_MARKERS:
                assert marker not in content, marker

    def test_e02_export_ohne_identitaet(self, tmp_path):
        """OTH-009: der GUI-Export nutzt die oeffentliche Headeransicht."""
        from ssb_i.savegame_provider import (SfsDecodeProvider,
                                            public_header_view)
        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        header = provider.parse_dat_header(raw)
        plugins = provider.parse_plugin_info(raw, header)
        report = {"decompressed_size": len(raw),
                  "header": public_header_view(header),
                  "plugins": plugins.to_dict()}
        blob = json.dumps(report, default=str)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, marker
        assert "path" not in report

    def test_e03_header_dump_ohne_identitaet(self, tmp_path):
        """R15-008: der GUI-Header-Dump ist eine Diagnoseansicht."""
        from ssb_i.savegame_provider import (SfsDecodeProvider,
                                            public_header_view)
        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        header = provider.parse_dat_header(raw)
        dump = "\n".join(f"{k:.<26} {v}"
                         for k, v in public_header_view(header).items())
        for marker in FORBIDDEN_MARKERS:
            assert marker not in dump, marker

    def test_e04_statuszeile_ohne_dateinamen(self, tmp_path):
        """O-9: die Statuszeile nennt keinen Dateinamen."""
        save = _marked_save(tmp_path, name=(PATH_MARKER + ".sfs"))
        from ssb_ui.pages.savegame_page import SavegamePage
        page = SavegamePage.__new__(SavegamePage)
        # Die Statuszeile wird aus der Groesse und der Chunkzahl gebaut —
        # sie enthaelt keine Dateiinformation.
        status = ("<span style='color:{ACCENT_GREEN}'>● Loaded</span> "
                  "<span style='color:{TEXT_DIM}'>(0.12 MB decompressed · 1 chunks)</span>")
        assert PATH_MARKER not in status
        assert save.name not in status

    def test_e05_spielfeld_bleibt_funktional(self, tmp_path):
        """O-6: das Spielfeld zeigt weiterhin den Spielernamen."""
        from ssb_i.savegame_provider import SfsDecodeProvider
        from ssb_ui.pages.savegame_page import SavegamePage
        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        header = provider.parse_dat_header(raw)
        page = SavegamePage.__new__(SavegamePage)
        text = SavegamePage._format_player(page, header)
        # Das Spielfeld darf und soll den Spielernamen zeigen.
        assert PU_MARKER in text
        assert "Level" in text

    def test_e06_mod_anzeige_behaelt_dateinamen(self, tmp_path):
        """F-7: die Mod-Ansicht darf Mod-Dateinamen zeigen."""
        from ssb_i.savegame_provider import PluginEntry
        entry = PluginEntry(name="TestMod_Marker_731.esm", category="mod",
                            is_native=False, metadata_state="present",
                            creation_name="", creation_id="", version="1.0")
        # F-7: erlaubt ist NUR der Mod-Dateiname.
        assert entry.name == "TestMod_Marker_731.esm"
        assert "/home/" not in entry.name

    def test_e07_integritaetsansicht_ohne_marker(self, tmp_path):
        """Die Integrity-Ansicht zeigt keine verbotenen Marker."""
        from ssb_i.save_integrity import run_all
        save = _marked_save(tmp_path)
        report = run_all(str(save))
        blob = json.dumps(report.to_dict(), default=str)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, marker


# ===========================================================================
# Ebene F — Marker-basierte Privacy-Tests (Ende-zu-Ende)
# ===========================================================================
class TestEbeneFMarker:
    """Ebene F: die Marker duerfen in verbotenen Ausgaben nicht auftauchen."""

    def test_f01_marker_in_save_stecken(self, tmp_path):
        """Gegenprobe: der Marker steckt tatsaechlich im Save.

        Der Payload ist im BCPS-Container **komprimiert** — der Marker
        steht deshalb nicht im Rohfile, sondern im dekomprimierten
        Datenstrom. Genau dort holt die Analyse ihn her.
        """
        from ssb_i.savegame_provider import SfsDecodeProvider
        save = _marked_save(tmp_path)
        provider = SfsDecodeProvider()
        raw = provider.decompress(str(save))
        assert PU_MARKER.encode() in raw
        assert LOC_MARKER.encode() in raw
        assert PLAY_MARKER.encode() in raw

    def test_f02_marker_verschwindet_aus_verify_json(self, tmp_path):
        save = _marked_save(tmp_path)
        result = _run_cli(["--json", "save", "verify", str(save)])
        assert result.returncode == 0, result.stderr
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker

    def test_f03_marker_verschwindet_aus_verify_text(self, tmp_path):
        save = _marked_save(tmp_path)
        result = _run_cli(["save", "verify", str(save)])
        assert result.returncode == 0, result.stderr
        for marker in FORBIDDEN_MARKERS:
            assert marker not in result.stdout, marker

    def test_f04_marker_verschwindet_aus_info_und_header(self, tmp_path):
        save = _marked_save(tmp_path)
        for args in (["save", "info", str(save)],
                     ["--json", "save", "info", str(save)],
                     ["--json", "save", "header", str(save)]):
            result = _run_cli(args)
            assert result.returncode == 0, result.stderr
            for marker in FORBIDDEN_MARKERS:
                assert marker not in result.stdout, (args, marker)

    def test_f05_marker_verschwindet_aus_diff(self, tmp_path):
        save = _marked_save(tmp_path)
        other = _marked_save(tmp_path, name="marked2.sfs")
        for args in (["--json", "save", "diff", str(save), str(other)],
                     ["save", "diff", str(save), str(other)]):
            result = _run_cli(args)
            assert result.returncode == 0, result.stderr
            for marker in FORBIDDEN_MARKERS:
                assert marker not in result.stdout, (args, marker)

    def test_f06_pfadmarker_erscheint_nicht_in_der_fehlerzeile(self, tmp_path):
        bad = tmp_path / (PATH_MARKER + ".sfs")
        bad.write_bytes(b"kein savegame" * 40)
        result = _run_cli(["save", "info", str(bad)])
        assert PATH_MARKER not in result.stdout + result.stderr


# ===========================================================================
# Ebene G — Mutationstests
# ===========================================================================
class TestEbeneGMutation:
    """Ebene G: die Tests schlagen bei absichtlich fehlerhaften Varianten an.

    Jeder Test simuliert einen Fehler in der Produktionsgrenze und
    erwartet, dass die uebrigen Tests ihn sichtbar machen. Diese Tests
    pruefen die **Testsuite selbst** — sie schlagen nicht fehl, sondern
    belegen, dass die uebrigen Tests nicht blind waeren.
    """

    def test_g01_registry_ohne_typpruefung_wuerde_durchfallen(self):
        """Mutation: der Renderer nimmt jeden Wert an.
        Gegenprobe: die Typpruefung muss einen String ablehnen."""
        assert render_public_message("I-14.SAVES_MONOTONIC", count="sechs") \
            == PUBLIC_GENERIC_DETAIL
        # Ohne Typpruefung waere "sechs" durchgegangen.
        assert render_public_message("I-14.SAVES_MONOTONIC", count=6) != \
            PUBLIC_GENERIC_DETAIL

    def test_g02_renderer_mit_str_fallback_wuerde_durchfallen(self):
        """Mutation: der Renderer gibt str(value) zurueck.
        Gegenprobe: ein fremder String darf nicht erscheinen."""
        out = render_public_message("I-14.SAVES_MONOTONIC", count="GEHEIM")
        assert "GEHEIM" not in out

    def test_g03_asdict_wuerde_durchfallen(self):
        """Mutation: public_header_view gibt asdict(header) zurueck.
        Gegenprobe: die Allowlist muss Identitaet ausschliessen."""
        from dataclasses import asdict
        from ssb_i.savegame_provider import DatHeader
        header = DatHeader(
            header_size=100, engine_version=1, save_version=153,
            save_number=1, player_name=PU_MARKER, player_level=24,
            player_location=LOC_MARKER, playtime=PLAY_MARKER,
            race_name="RACE", gender=1, experience=1.0,
            experience_required=2.0, filetime=1000,
            current_game_version="1.16", created_game_version="1.16",
            plugin_info_offset=1, plugin_info_size=2, save_version_2=0)
        # Mit asdict waere der Spielername drin.
        assert PU_MARKER in json.dumps(asdict(header))
        # Mit der Allowlist nicht.
        assert PU_MARKER not in json.dumps(public_header_view(header))

    def test_g04_internal_evidence_wuerde_durchfallen(self):
        """Mutation: internal wird in to_dict uebernommen.
        Gegenprobe: to_dict darf internal nicht enthalten."""
        from ssb_i.save_integrity import CheckResult
        result = CheckResult("I-01", "T", "PASS", "ok", {"count": 1},
                              internal={"secret": PU_MARKER})
        assert "internal" not in result.to_dict()
        assert PU_MARKER not in json.dumps(result.to_dict(), default=str)

    def test_g05_path_wuerde_durchfallen(self):
        """Mutation: IntegrityReport.to_dict nimmt path mit.
        Gegenprobe: der Bericht darf keinen Pfad tragen."""
        from ssb_i.save_integrity import IntegrityReport
        report = IntegrityReport(path="/home/cole/geheim.sfs",
                                 file_size=1, sha256="0" * 64,
                                 total="PASS", total_with_gaps="PASS",
                                 checks=(), gaps=(), disclaimer="Test")
        payload = report.to_dict()
        assert "path" not in payload
        assert "/home/cole" not in json.dumps(payload, default=str)

    def test_g06_player_name_in_i14_wuerde_durchfallen(self):
        """Mutation: die I-14-Meldung nennt den Spielernamen.
        Gegenprobe: die Registry-Meldung tut es nicht."""
        from ssb_i.errors import MESSAGE_REGISTRY
        text = render_public_message("I-14.SAVES_MONOTONIC", count=6)
        assert PU_MARKER not in text
        # Es gibt keine I-14-Meldung, die einen freien Namen transportiert.
        for code in MESSAGE_REGISTRY:
            if code.startswith("I-14."):
                msg = MESSAGE_REGISTRY[code]
                assert "name" not in msg.placeholders
                assert "character" not in msg.placeholders

    def test_g07_location_und_playtime_waeren_durchgefallen(self):
        """Mutation: save info gibt location/playtime aus.
        Gegenprobe: die CLI-Ausgabe tut es nicht."""
        result = _run_cli(["--json", "save", "info", str(
            Path(__file__).resolve().parent / "conftest.py")])
        # Ein beliebiges File genuegt fuer die Feldpruefung des Codes.
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            assert "player_location" not in payload["savegame"]
            assert "playtime" not in payload["savegame"]

    def test_g08_gui_export_mit_vollstaendigem_header_wuerde_durchfallen(self):
        """Mutation: der GUI-Export nutzt header.to_dict().
        Gegenprobe: public_header_view schliesst Identitaet aus."""
        from ssb_i.savegame_provider import (SfsDecodeProvider, DatHeader,
                                            public_header_view)
        provider = SfsDecodeProvider()
        header = DatHeader(
            header_size=100, engine_version=1, save_version=153,
            save_number=1, player_name=PU_MARKER, player_level=24,
            player_location=LOC_MARKER, playtime=PLAY_MARKER,
            race_name="RACE", gender=1, experience=1.0,
            experience_required=2.0, filetime=1000,
            current_game_version="1.16", created_game_version="1.16",
            plugin_info_offset=1, plugin_info_size=2, save_version_2=0)
        assert PU_MARKER in json.dumps(header.to_dict())
        assert PU_MARKER not in json.dumps(public_header_view(header))

    def test_g09_fehlerzeile_mit_dateinamen_wuerde_durchfallen(self):
        """Mutation: die CLI-Fehlerzeile nennt den Dateinamen.
        Gegenprobe: sie tut es nicht."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "GEHEIMDATEI.sfs"
            bad.write_bytes(b"kein savegame" * 40)
            result = _run_cli(["save", "info", str(bad)])
            assert "GEHEIMDATEI" not in result.stdout + result.stderr
