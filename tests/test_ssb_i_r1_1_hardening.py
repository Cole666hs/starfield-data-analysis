"""R1.1 — Resthaertung: Whitelist-Vorlagen, argparse-JSON-Vertrag, Stream-Fallback.

Die Tests formulieren die **Sicherheitsanforderung** unabhaengig von der
Implementierung. Sie bilden nicht nach, "wie der Formatter es macht", sondern
pruefen Eigenschaften:

  * eine eigene Meldung darf keinen Pfad und keinen Dateinamen veroeffentlichen
  * eine eigene Meldung darf keinen beliebigen dynamischen Text einschleusen
  * ein manipulierter Exception-Klassenname darf nicht durchkommen
  * im JSON-Modus gibt es bei Nutzungsfehlern genau ein JSON-Dokument auf
    stdout und **nichts** auf stderr
  * fehlt ein Stream, wird nichts erfunden und der Exit-Code bleibt der des
    Fehlers
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssb_i.errors import (  # noqa: E402
    ERRNO_MESSAGES,
    GENERIC_OS_ERROR,
    SAFE_MESSAGE_TEMPLATES,
    diagnostic_error,
    public_error,
    public_error_detail,
)

PY = str(REPO / ".venv-build/bin/python")
CLI = str(REPO / "sfda_cli.py")

#: Private Bestandteile, die in oeffentlichen Ausgaben nie auftauchen duerfen.
MARKER = "PRIVAT-R1-1-MARKER"

#: Pfadformen, die niemals in einer oeffentlichen Ausgabe stehen duerfen.
PATH_FORMS = (
    "/home/cole/%s/Spielstand.sfs" % MARKER,
    "relativ/%s/Spielstand.sfs" % MARKER,
    "./%s/Spielstand.sfs" % MARKER,
    "%s/geheim/ordner" % MARKER,
    "%s_geheim" % MARKER,
    "%s_geheim.sfs" % MARKER,
    "\\\\server\\share\\%s\\Spielstand.sfs" % MARKER,
    "C:\\Users\\cole\\%s\\Spielstand.sfs" % MARKER,
    "/home\\x2fcole\\x2f%s" % MARKER,
    "/home/cole/My Saves/%s a.sfs" % MARKER,
)


def _leaks(text: str) -> list[str]:
    """Gibt alle verratenen privaten Bestandteile einer Ausgabe zurueck."""
    found = []
    if MARKER in text:
        found.append("Marker")
    if "/home/cole" in text:
        found.append("absoluter Pfad")
    if re.search(r"[A-Za-z]:\\", text):
        found.append("Windows-Pfad")
    if "\\\\server" in text:
        found.append("UNC-Pfad")
    return found


# ---------------------------------------------------------------------------
# L1 — die Sicherheitsinvariante
# ---------------------------------------------------------------------------
class TestWhitelistSicherheitsinvariante:
    """Die zentrale Invariante: eine eigene Meldung veroeffentlicht keinen
    Pfad, keinen Dateinamen und keinen beliebigen fremden Text."""

    @pytest.mark.parametrize("pfad", PATH_FORMS)
    def test_pfad_in_eigener_meldung_wird_nicht_ausgegeben(self, pfad):
        """Ein Pfad in einer sonst passenden Meldung darf nicht herauskommen."""
        for message in (
            "Not an SFS file: %s" % pfad,
            "Not an SFS file: %s (expected b'BCPS')" % pfad,
            "Not a DAT file: starts with %s" % pfad,
            "Only ZIP compression supported, got %s" % pfad,
        ):
            out = public_error(ValueError(message))
            leaks = _leaks(out)
            assert not leaks, "Meldung %r leakt %s: %r" % (message, leaks, out)

    def test_unbekanntes_praefix_wird_verworfen(self):
        """Eine Meldung mit fremdem Praefix wird nicht uebernommen."""
        out = public_error(ValueError("Sonstiger Fehler: %s" % MARKER))
        assert not _leaks(out)
        assert out == "ValueError"

    def test_dynamischer_fremdtext_wird_nicht_uebernommen(self):
        """Beliebiger Text hinter einem bekannten Praefix bleibt draussen.

        Der Formatter darf keine Zeichenkette als eigenen Bestandteil
        akzeptieren — sonst koennte ein Pfad durch den Riss schlupfen.
        """
        for message in (
            "Not an SFS file: %s" % MARKER,
            "Not an SFS file: %s (expected b'BCPS')" % MARKER,
            "chunk table incomplete: %s of 16 bytes at offset 0x48" % MARKER,
            "compressed stream truncated: %s of 20 bytes present" % MARKER,
            "zlib-decompression failed at chunk %s (pos=0x1B0, size=91234): Error -3" % MARKER,
        ):
            out = public_error(ValueError(message))
            assert not _leaks(out), "Meldung %r leakt: %r" % (message, out)

    def test_keine_vorlage_nimmt_freie_zeichenketten_an(self):
        """Keine Vorlage darf einen Platzhalter fuer freien Text anbieten.

        Das ist die strukturelle Absicherung der Invariante: eine Vorlage mit
        einem Zeichenketten-Platzhalter wuerde die Moeglichkeit offenlassen,
        einen Pfad einzuschleusen.
        """
        for template in SAFE_MESSAGE_TEMPLATES:
            names = re.findall(r"\{([a-z]+)\}", template)
            for name in names:
                assert name not in ("str", "text", "raw", "any"), (
                    "Vorlage %r nimmt freien Text an (%s)" % (template, name))

    def test_alle_vorlagen_sind_fuer_gueltige_werte_verwendbar(self):
        """Jede Vorlage muss mit einem plausiblen Wert tatsaechlich greifen.

        Sonst waere eine Vorlage toter Code — und ein toter Code ist keine
        Absicherung.
        """
        werte = {
            "bytes": "b'BCPS'",
            "int": "12",
            "hex": "1B0",
            "class": "ValueError",
            "reason": "Not a DAT file: starts with b'XY'",
            "zlib": "Error -3",
        }
        for template in SAFE_MESSAGE_TEMPLATES:
            message = template
            for name in re.findall(r"\{([a-z]+)\}", template):
                message = message.replace("{%s}" % name, werte[name], 1)
            detail = public_error_detail(ValueError(message))
            assert detail, "Vorlage %r greift nicht (Message %r)" % (template, message)


class TestWhitelistSichereDiagnose:
    """Nachweislich sichere Werte bleiben aussagekraeftig."""

    def test_magic_byte_wird_genannt(self):
        """R1.2: die Magic wird benannt — aber **nicht** als Eingabebytes.

        Seit R1.2 gibt der Byte-Platzhalter nur noch eine statische, eigene
        Beschreibung aus. Die Bytes selbst erscheinen nicht mehr in der
        oeffentlichen Meldung (Befund N1). Die Information "es war eine
        falsche Magic" bleibt erhalten.
        """
        out = public_error(ValueError("Not an SFS file: b'kein' (expected b'BCPS')"))
        assert "unknown signature" in out
        assert "b'kein'" not in out
        assert out.startswith("ValueError:")

    def test_kompressionskennung_wird_genannt(self):
        """R1.2: die Kompressionskennung wird benannt, ohne die Eingabebytes."""
        out = public_error(ValueError("Only ZIP compression supported, got b'LZMA'"))
        assert "LZMA" in out
        assert "b'LZMA'" not in out

    def test_zahlen_offsets_und_groessen_bleiben_lesbar(self):
        out = public_error(ValueError(
            "chunk table incomplete: 4 of 16 bytes at offset 0x48"))
        assert "4 of 16" in out and "0x48" in out
        out = public_error(ValueError(
            "zlib-decompression failed at chunk 3 (pos=0x1B0, size=91234): Error -3"))
        assert "chunk 3" in out and "0x1B0" in out and "91234" in out

    def test_bytepraefix_mit_steuerzeichen_bleibt_lesbar(self):
        """L2: die falsche Magic soll erkennbar bleiben.

        ``b'MZ\\x00\\x00'`` ist genau die Information, die bei der Analyse
        hilft — sie darf nicht zu ``b'<pfad>'`` verwaschen werden.

        R1.2: benannt wird die Magic als statische Beschreibung, nicht als
        Bytefolge. Das ist die strukturelle Trennung aus Befund N1: die
        Bytes selbst gelangen nie in die oeffentliche Meldung.
        """
        out = public_error(ValueError(
            "Not an SFS file: b'MZ\\x00\\x00' (expected b'BCPS')"))
        assert "DOS executable header" in out, "Bytepraefix ging verloren: %r" % out
        assert "<pfad>" not in out
        assert "MZ" not in out, "Eingabebytes in der oeffentlichen Meldung: %r" % out

    def test_dateiname_im_byte_feld_wird_verworfen(self):
        """Die ersten 12 Byte einer Datei koennen ein Name sein — der darf
        nicht in der oeffentlichen Meldung landen."""
        out = public_error(ValueError(
            "Not a DAT file: starts with b'Save.sfs'"))
        assert not _leaks(out)
        assert "Save.sfs" not in out


class TestKlassenname:
    """Der Exception-Klassenname ist ebenfalls ein öffentlicher Kanal."""

    def test_manipulierter_klassenname_wird_verworfen(self):
        class Evil(Exception):
            pass

        Evil.__name__ = "/home/cole/%s/Klasse.sfs" % MARKER
        out = public_error(Evil("egal"))
        assert not _leaks(out), out

    def test_manipulierter_klassenname_mit_backslash(self):
        class Evil(Exception):
            pass

        Evil.__name__ = "C:\\Users\\cole\\%s" % MARKER
        out = public_error(Evil("egal"))
        assert not _leaks(out), out

    def test_normaler_klassenname_bleibt_erhalten(self):
        class Normal(Exception):
            pass

        out = public_error(Normal("egal"))
        assert out == "Normal"

    def test_struct_und_zlib_behalten_ihren_modulpraefix(self):
        import struct
        import zlib

        assert public_error(struct.error("x")) == "struct.error"
        assert public_error(zlib.error("x")) == "zlib.error"


class TestOSErrorNachweisbarkeit:
    """Die OSError-Familie bleibt unveraendert sicher."""

    @pytest.mark.parametrize("errno", sorted(ERRNO_MESSAGES))
    def test_jeder_ererrno_hat_einen_text(self, errno):
        exc = OSError(errno, "beliebig")
        out = public_error(exc)
        assert ERRNO_MESSAGES[errno] in out

    def test_unbekannter_errno_wird_generisch(self):
        out = public_error(OSError(9999, "beliebig"))
        assert GENERIC_OS_ERROR in out

    def test_pfad_in_keiner_oserror_variante(self):
        pfad = "/home/cole/%s/x.sfs" % MARKER
        for exc in (FileNotFoundError(2, "No such file", pfad),
                    PermissionError(13, "Permission denied", pfad),
                    IsADirectoryError(21, "Is a directory", pfad),
                    OSError(2, pfad, pfad),
                    OSError(9999, None, pfad)):
            out = public_error(exc)
            assert not _leaks(out), out

    def test_datei_nicht_vorhanden_nennt_keinen_pfad(self):
        """Der fruehere Fund ``raise FileNotFoundError(sfs_path)``."""
        out = public_error(FileNotFoundError("/home/cole/%s/x.sfs" % MARKER))
        assert not _leaks(out), out


class TestDiagnostikGetrennt:
    """``diagnostic_error`` darf vollen Text tragen, ist aber nicht oeffentlich."""

    def test_diagnostic_error_zeigt_den_vollen_text(self):
        out = diagnostic_error(ValueError("/home/cole/%s/x.sfs" % MARKER))
        assert MARKER in out

    def test_diagnostic_error_hat_keine_produktivaufrufstelle(self):
        """Die Trennung ist durch die Aufrufverteilung abgesichert."""
        treffer = []
        for path in sorted((REPO / "ssb_i").rglob("*.py")):
            if path.name == "errors.py":
                continue
            for nummer, zeile in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if "diagnostic_error" in zeile:
                    treffer.append("%s:%d" % (path.relative_to(REPO), nummer))
        assert not treffer, "diagnostic_error wird produktiv benutzt: %s" % treffer


# ---------------------------------------------------------------------------
# R5 — argparse im JSON-Modus
# ---------------------------------------------------------------------------
def _run_cli(args, env_extra=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, CLI] + args, capture_output=True, cwd=REPO, env=env)


NUTZUNGSFEHLER = (
    ("fehlendes Subkommando", ["--json"]),
    ("fehlendes Subkommando bei save", ["--json", "save"]),
    ("unbekanntes Subkommando", ["--json", "save", "gibtsnicht", "x.sfs"]),
    ("unbekanntes Top-Level-Kommando", ["--json", "quatsch"]),
    ("ungueltige Argumente", ["--json", "save", "diff", "a.sfs", "b.sfs",
                               "--max-gap", "abc"]),
    ("fehlendes Argument", ["--json", "save", "info"]),
    ("fehlendes Argument bei diff", ["--json", "save", "diff", "a.sfs"]),
    ("json an ungueltiger Position", ["--json", "save", "info", "a.sfs", "--json"]),
)


class TestJsonVertragBeiNutzungsfehlern:
    """Im JSON-Modus: genau ein JSON-Dokument auf stdout, stderr leer."""

    @pytest.mark.parametrize("label,args", NUTZUNGSFEHLER)
    def test_genau_ein_json_dokument_und_leeres_stderr(self, label, args):
        result = _run_cli(args)
        assert result.returncode == 2, "%s: Exit %d" % (label, result.returncode)
        assert result.stderr == b"", "%s: stderr nicht leer: %r" % (
            label, result.stderr[:300])
        payload = json.loads(result.stdout.decode("utf-8"))
        assert isinstance(payload, dict)
        assert payload["error"]
        assert payload["exit_code"] == 2
        # Kein Byte vor oder nach dem Dokument.
        decoder = json.JSONDecoder()
        obj, end = decoder.raw_decode(result.stdout.decode("utf-8"))
        assert result.stdout.decode("utf-8")[end:].strip() == ""

    @pytest.mark.parametrize("label,args", NUTZUNGSFEHLER)
    def test_kein_pfad_im_json_fehlerdokument(self, label, args):
        result = _run_cli(args)
        assert not _leaks(result.stdout.decode("utf-8"))

    def test_help_bleibt_exit_null_ohne_json(self):
        result = _run_cli(["--json", "--help"])
        assert result.returncode == 0
        assert result.stderr == b""
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout.decode("utf-8"))

    def test_version_bleibt_exit_null_ohne_json(self):
        result = _run_cli(["--json", "--version"])
        assert result.returncode == 0
        assert result.stderr == b""
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout.decode("utf-8"))


class TestTextmodusUnveraendert:
    """Im Textmodus bleibt das argparse-Verhalten unveraendert."""

    @pytest.mark.parametrize("args", [
        [], ["save"], ["save", "gibtsnicht"], ["save", "info"],
    ])
    def test_argparse_schreibt_usage_auf_stderr(self, args):
        result = _run_cli(args)
        assert result.returncode == 2
        assert b"usage:" in result.stderr
        assert b"error:" in result.stderr
        assert result.stdout == b""

    def test_erfolgsfall_unveraendert(self, tmp_path):
        """Ein gueltiger Aufruf bleibt unveraendert: Exit 0, Text auf stdout.

        R1_6: die Zeile "File" (Savegame-Dateiname) ist entfallen (F-2/O-9).
        Der Aufruf bleibt erfolgreich und liefert weiterhin Text auf stdout —
        nur ohne die Dateibezeichnung.
        """
        from conftest import build_dat_payload, build_synthetic_sfs

        save = tmp_path / "Save.sfs"
        save.write_bytes(build_synthetic_sfs(build_dat_payload()))
        result = _run_cli(["save", "info", str(save)])
        assert result.returncode == 0
        assert result.stderr == b""
        assert b"Level" in result.stdout
        # R1_6 / F-2: kein Savegame-Dateiname in der oeffentlichen Ausgabe.
        assert b"File" not in result.stdout
        assert b"Save.sfs" not in result.stdout


# ---------------------------------------------------------------------------
# R6 — Fehlerkanal bei fehlenden Streams
# ---------------------------------------------------------------------------
_HARNESS = r'''
import sys, importlib.util, pathlib
sys.stdout = {stdout}
sys.stderr = {stderr}
sys.__stdout__ = {dunder_stdout}
sys.__stderr__ = {dunder_stderr}
spec = importlib.util.spec_from_file_location("sfda_cli", {cli})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    code = mod.main({argv})
except SystemExit as exc:
    code = exc.code
except BaseException as exc:
    code = "CRASH:" + type(exc).__name__
pathlib.Path({result}).write_text(str(code), encoding="utf-8")
'''


def _run_without_streams(tmp_path, argv, stdout, stderr, dunder_stdout, dunder_stderr):
    result_file = tmp_path / "code.txt"
    source = (_HARNESS
              .replace("{stdout}", stdout)
              .replace("{stderr}", stderr)
              .replace("{dunder_stdout}", dunder_stdout)
              .replace("{dunder_stderr}", dunder_stderr)
              .replace("{cli}", repr(CLI))
              .replace("{argv}", repr(argv))
              .replace("{result}", repr(str(result_file))))
    proc = subprocess.run([PY, "-c", source], capture_output=True, cwd=REPO,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    code = result_file.read_text(encoding="utf-8") if result_file.exists() else ""
    return proc, code


class TestFehlerkanalOhneStream:
    """Fehlt der Stream, wird nichts erfunden — der Exit-Code bleibt."""

    def test_ohne_jeden_stream_bleibt_der_exitcode_des_fehlers(self, tmp_path):
        bad = tmp_path / "bad.sfs"
        bad.write_bytes(b"BCPS")
        proc, code = _run_without_streams(
            tmp_path, ["save", "info", str(bad)],
            "None", "None", "None", "None")
        assert code == "1", "Exit-Code %r" % code
        assert b"Traceback" not in proc.stdout + proc.stderr
        assert proc.stdout == b"" and proc.stderr == b""

    def test_ohne_jeden_stream_bleibt_der_nutzungsfehler_exitcode(self, tmp_path):
        proc, code = _run_without_streams(
            tmp_path, ["--json", "save"], "None", "None", "None", "None")
        assert code == "2", "Exit-Code %r" % code
        assert b"Traceback" not in proc.stdout + proc.stderr

    def test_ohne_stderr_geht_die_meldung_an_stdout(self, tmp_path):
        bad = tmp_path / "bad.sfs"
        bad.write_bytes(b"BCPS")
        proc, code = _run_without_streams(
            tmp_path, ["save", "info", str(bad)],
            "sys.__stdout__", "None", "sys.__stdout__", "None")
        assert code == "1"
        assert b"ERROR:" in proc.stdout
        assert proc.stderr == b""

    def test_ohne_stdout_geht_die_meldung_an_stderr(self, tmp_path):
        bad = tmp_path / "bad.sfs"
        bad.write_bytes(b"BCPS")
        proc, code = _run_without_streams(
            tmp_path, ["save", "info", str(bad)],
            "None", "sys.__stderr__", "None", "sys.__stderr__")
        assert code == "1"
        assert b"ERROR:" in proc.stderr
        assert proc.stdout == b""

    def test_json_ohne_stdout_weicht_auf_stderr_aus(self, tmp_path):
        """Das JSON-Dokument darf nicht verloren gehen."""
        bad = tmp_path / "bad.sfs"
        bad.write_bytes(b"BCPS")
        proc, code = _run_without_streams(
            tmp_path, ["--json", "save", "info", str(bad)],
            "None", "sys.__stderr__", "None", "sys.__stderr__")
        assert code == "1"
        payload = json.loads(proc.stderr.decode("utf-8"))
        assert payload["error"]
        assert payload["exit_code"] == 1

    def test_kein_strom_kein_traceback_und_kein_erfolg(self, tmp_path):
        """Ein stiller Fehler darf nicht als Erfolg gelten."""
        bad = tmp_path / "bad.sfs"
        bad.write_bytes(b"BCPS")
        proc, code = _run_without_streams(
            tmp_path, ["save", "info", str(bad)],
            "None", "None", "None", "None")
        assert code not in ("0", "", "CRASH:BaseException")
