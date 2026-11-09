"""R1.2 — Gezielte Korrektur der Befunde N1 und N2.

Die beiden Befunde stammen aus der unabhaengigen Abnahmepruefung von R1_1
(``/tmp/SSBI_I14_R1_1_INDEPENDENT_ACCEPTANCE_REVIEW.md``):

**N1 (HOCH)** — ``_looks_like_filename()`` untersuchte nur den druckbaren
Praefix ab Byte 0. Begann der Dateiinhalt mit einem Steuerzeichen, blieb der
Praefix leer, die Dateinamenpruefung lief ins Leere und der Inhalt gelangte
**mit dem Dateinamen** in die oeffentliche Meldung. Reproduktion:
``Not a DAT file: starts with b'\\x00Save.sfs\\x00\\x00\\x00'``.

**N2 (MITTEL)** — die Typklasse ``{zlib}`` akzeptierte keine reale
CPython-zlib-Meldung (``Error -3 while decompressing data: incorrect header
check``). Im Produktivpfad ging deshalb bei jedem realen zlib-Fehler die
gesamte Diagnose verloren: Chunk-Index, Position und Chunk-Groesse.

Diese Datei formuliert die **Anforderung**, nicht die Implementierung:

  * eine oeffentliche Meldung gibt **keine** Eingabebytes wieder — weder
    als Dateiname, noch als Pfad, noch als Byte-Rest, an welcher Position
    er auch steht;
  * eine oeffentliche Meldung gibt **keinen** CPython-Fehltext wieder;
  * der sichere Kontext einer zlib-Meldung (Chunk-Index, Position, Groesse)
    bleibt **erhalten**, unabhaengig von der Formulierung der zlib-Meldung;
  * unbekannte Faelle fallen sicher zurueck: kein Traceback, kein Datenleck;
  * die **interne** Diagnose traegt die Originaldaten weiterhin — sie ist
    strikt von den oeffentlichen Pfaden getrennt.

Die Tests pruefen die **oeffentliche CLI-Ausgabe**, nicht nur den Formatter:
ein isolierter Unit-Test waere kein Nachweis fuer den Produktivpfad.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssb_i.errors import (  # noqa: E402
    diagnostic_error,
    public_error,
    public_error_detail,
)

# Die beiden neuen Konstanten existieren erst ab R1.2. Sie werden optional
# importiert, damit die Falsifikationsprobe diese Testdatei auch gegen die
# aeltere Implementierung laufen laesst (dort schlaegt dann die JEWEILIGE
# Anforderung fehl, nicht der Import).
try:
    from ssb_i.errors import BYTES_UNKNOWN  # noqa: E402
except ImportError:                       # pragma: no cover - nur R1.1-Stand
    BYTES_UNKNOWN = "unknown signature"

try:
    from ssb_i.errors import ZLIB_CODES  # noqa: E402
except ImportError:                       # pragma: no cover - nur R1.1-Stand
    ZLIB_CODES = {}

from conftest import build_synthetic_sfs  # noqa: E402

PY = str(REPO / ".venv-build/bin/python")
CLI = str(REPO / "sfda_cli.py")

#: Private Bestandteile, die in oeffentlichen Ausgaben nie auftauchen duerfen.
MARKER = "PRIVAT-R1-2-MARKER"

#: Name, der in Nutzerinhalt stehen kann und nie sichtbar werden darf.
DATEINAME = "Save.sfs"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _run_cli(args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    return subprocess.run([PY, CLI] + args, capture_output=True, cwd=REPO, env=env)


def _leaks(text: str) -> list[str]:
    """Alle verratenen privaten Bestandteile einer oeffentlichen Ausgabe."""
    found = []
    if MARKER in text:
        found.append("Marker")
    if DATEINAME in text:
        found.append("Dateiname")
    if "/home/cole" in text:
        found.append("absoluter Pfad")
    if re.search(r"[A-Za-z]:\\", text):
        found.append("Windows-Pfad")
    if "\\\\server" in text:
        found.append("UNC-Pfad")
    if "/geheim" in text:
        found.append("relativer Pfad")
    return found


def _dat_message(raw: bytes) -> str:
    """Die Meldung, die ``parse_dat_header`` bei falscher Magic erzeugt."""
    return "Not a DAT file: starts with %s" % repr(raw)


def _sfs_message(raw: bytes) -> str:
    """Die Meldung, die ``read_container`` bei falscher Magic erzeugt."""
    return "Not an SFS file: %s (expected b'BCPS')" % repr(raw)


# ---------------------------------------------------------------------------
# N1 — Byte-Inhalt darf nie in einer oeffentlichen Meldung stehen
# ---------------------------------------------------------------------------
#: Die zehn Pflichtfaelle aus dem Auftrag. Der Name steht an
#: unterschiedlichen Positionen, teils hinter Steuerzeichen, teils in
#: langen Daten.
N1_BYTE_CASES = (
    ("01 Name am Anfang",           b"Save.sfs"),
    ("02 Name hinter NUL",          b"\x00Save.sfs\x00\x00\x00"),
    ("03 Name hinter zwei Steuerz", b"\x01\x02Save.sfs"),
    ("04 Magic mit Steuerzeichen",  b"MZ\x00\x00"),
    ("05 absoluter Pfad eingebettet",
     b"\x00\x00/home/cole/" + MARKER.encode() + b"/x.sfs"),
    ("06 relativer Pfad eingebettet",
     b"\x01relativ/" + MARKER.encode() + b"/geheim"),
    ("07 UNC-Pfad eingebettet",
     b"\x00\\\\server\\share\\" + MARKER.encode() + b"\\x.sfs"),
    ("08 Name an anderer Position", b"\x00\x00\x00\x00\x00\x00Save.sfs"),
    ("09 lange Daten mit Name",     b"\x00" + b"A" * 40 + b"Save.sfs" + b"B" * 40),
    ("10 Dateiname mit Endung an Position 4",
     b"\x00\x00\x00Save.sfs"),
)


class TestN1ByteInhaltBleibtPrivat:
    """N1: kein Byte-Inhalt darf oeffentlich werden — an keiner Position."""

    @pytest.mark.parametrize("label,raw", N1_BYTE_CASES)
    def test_byte_inhalt_wird_nicht_ausgegeben(self, label, raw):
        """Die oeffentliche Meldung nennt weder Name noch Pfad noch Bytes."""
        for message in (_dat_message(raw), _sfs_message(raw)):
            out = public_error(ValueError(message))
            leaks = _leaks(out)
            assert not leaks, "%s: %r leakt %s: %r" % (label, message, leaks, out)

    @pytest.mark.parametrize("label,raw", N1_BYTE_CASES)
    def test_byte_inhalt_wird_nicht_ausgegeben_json(self, label, raw):
        """Auch die Detail-Ausgabe (JSON-Feld ``error``) bleibt sauber."""
        out = public_error_detail(ValueError(_dat_message(raw)))
        leaks = _leaks(out)
        assert not leaks, "%s: %r leakt %s: %r" % (label, raw, leaks, out)

    def test_byte_inhalt_erscheint_gar_nicht_in_der_meldung(self):
        """Strukturell: die Meldung enthaelt die Bytefolge nicht.

        Das ist staerker als ein Mustervergleich: es wird geprueft, dass
        der **Wert selbst** nicht in der Ausgabe steht — unabhaengig davon,
        an welcher Stelle der Bytefolge er stand.
        """
        raw = b"\x00\x01Save.sfs\x00"
        out = public_error(ValueError(_dat_message(raw)))
        assert "Save" not in out
        assert "\\x00" not in out
        assert "\\x01" not in out

    def test_interne_diagnose_traegt_die_bytes_weiterhin(self):
        """Die Trennung ist beidseitig: intern bleibt alles erhalten."""
        raw = b"\x00Save.sfs\x00\x00\x00"
        exc = ValueError(_dat_message(raw))
        intern = diagnostic_error(exc)
        assert "Save.sfs" in intern, intern
        assert MARKER not in intern

    def test_diagnostic_error_hat_keine_produktivaufrufstelle(self):
        """Die internen Daten duerfen keinen Weg in die oeffentliche Ausgabe."""
        treffer = []
        for path in sorted((REPO / "ssb_i").rglob("*.py")):
            if path.name == "errors.py":
                continue
            for nummer, zeile in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if "diagnostic_error" in zeile:
                    treffer.append("%s:%d" % (path.relative_to(REPO), nummer))
        assert not treffer, "diagnostic_error wird produktiv benutzt: %s" % treffer


class TestN1CliAusgabe:
    """N1 am echten CLI-Pfad — ein Unit-Test waere kein Nachweis."""

    def test_gueltiger_bcps_container_mit_name_leakt_nicht(self, tmp_path):
        """Der Originalfall: ein gueltiger Container, dessen Innenstrom mit
        einem Dateinamen beginnt. Genau dieser Fall hat N1 ausgeloest."""
        inner = b"\x00" + DATEINAME.encode() + b"\x00\x00\x00" + b"FALSCH" * 8
        blob = build_synthetic_sfs(inner)
        target = tmp_path / "valid_container_leak.sfs"
        target.write_bytes(blob)

        result = _run_cli(["save", "info", str(target)])
        combined = result.stdout.decode("utf-8", "replace") + \
            result.stderr.decode("utf-8", "replace")
        leaks = _leaks(combined)
        assert not leaks, "CLI leakt %s: %r" % (leaks, combined)
        assert result.returncode == 1

    def test_gueltiger_bcps_container_mit_name_leakt_nicht_json(self, tmp_path):
        """Dasselbe im JSON-Modus: genau ein Dokument, kein Leck."""
        inner = b"\x00" + DATEINAME.encode() + b"\x00\x00\x00" + b"FALSCH" * 8
        target = tmp_path / "valid_container_leak.sfs"
        target.write_bytes(build_synthetic_sfs(inner))

        result = _run_cli(["--json", "save", "info", str(target)])
        payload = json.loads(result.stdout.decode("utf-8"))
        assert isinstance(payload, dict)
        leaks = _leaks(result.stdout.decode("utf-8"))
        assert not leaks, "CLI leakt %s: %r" % (leaks, result.stdout)

    def test_falsche_magic_am_containeranfang_leakt_nicht(self, tmp_path):
        """Auch der 4-Byte-Containerkopf darf keinen Namen nennen."""
        target = tmp_path / "kaputt.sfs"
        target.write_bytes(b"\x00" + DATEINAME.encode() + b"\x00" * 88)
        result = _run_cli(["save", "info", str(target)])
        combined = result.stdout.decode("utf-8", "replace") + \
            result.stderr.decode("utf-8", "replace")
        assert not _leaks(combined), combined

    def test_pfad_in_den_bytes_eines_containers_leakt_nicht(self, tmp_path):
        """Ein Pfad, der im Dateiinhalt steckt, darf nicht erscheinen."""
        target = tmp_path / "pfad.sfs"
        target.write_bytes(b"/home/cole/" + MARKER.encode() + b"/x.sfs" + b"\x00" * 60)
        result = _run_cli(["--json", "save", "info", str(target)])
        assert not _leaks(result.stdout.decode("utf-8")), result.stdout

    def test_kein_traceback_in_der_cli_ausgabe(self, tmp_path):
        """Die Fehlergrenze bleibt intakt: kein Traceback, kein Absturz."""
        target = tmp_path / "kaputt.sfs"
        target.write_bytes(b"\x00" + DATEINAME.encode() + b"\x00" * 88)
        result = _run_cli(["save", "info", str(target)])
        combined = result.stdout.decode("utf-8", "replace") + \
            result.stderr.decode("utf-8", "replace")
        assert "Traceback" not in combined, combined
        assert result.returncode == 1


class TestN1BeschreibungBleibtAussagekraeftig:
    """N1 darf die Diagnose nicht zu einem informationslosen Text machen."""

    def test_magic_wird_benannt(self):
        """Eine bekannte Magic wird als Magic benannt — ohne die Bytes."""
        out = public_error(ValueError(_sfs_message(b"MZ\x00\x00")))
        assert "DOS executable header" in out
        assert "Save" not in out

    def test_unbekannte_magic_wird_neutral_beschrieben(self):
        """Eine unbekannte Magic wird neutral beschrieben, nicht geraten."""
        out = public_error(ValueError(_sfs_message(b"XXXX")))
        assert BYTES_UNKNOWN in out
        assert "XXXX" not in out

    def test_kompressionskennung_wird_benannt(self):
        out = public_error(ValueError(
            "Only ZIP compression supported, got b'LZMA'"))
        assert "LZMA" in out
        assert out.startswith("ValueError:")

    def test_magic_mit_steuerzeichen_wird_benannt(self):
        """``b'MZ\\x00\\x00'`` bleibt als DOS-Header erkennbar."""
        out = public_error(ValueError(_sfs_message(b"MZ\x00\x00")))
        assert "DOS executable header" in out
        assert "<pfad>" not in out


# ---------------------------------------------------------------------------
# N2 — zlib-Diagnose: Kontext erhalten, fremden Text nie ausgeben
# ---------------------------------------------------------------------------
#: Die realen CPython-zlib-Meldungen. Gemessen ueber CPython 3.13:
#: alle fuenf realen Fehlertexte beginnen mit ``Error -N``.
REAL_ZLIB_MESSAGES = (
    ("Error -3 while decompressing data: incorrect header check", -3),
    ("Error -3 while decompressing data: invalid block type", -3),
    ("Error -3 while decompressing data: invalid stored block lengths", -3),
    ("Error -3 while decompressing data: invalid window size", -3),
    ("Error -3 while decompressing data: unknown compression method", -3),
    ("Error -5 while decompressing data: incomplete or truncated stream", -5),
)


def _zlib_message(chunk: int, pos: int, size: int, text: str) -> str:
    return ("zlib-decompression failed at chunk %d (pos=0x%X, size=%d): %s"
            % (chunk, pos, size, text))


class TestN2ZlibKontextBleibtErhalten:
    """N2: der sichere Kontext geht nicht verloren, weil CPython anders
    formuliert."""

    @pytest.mark.parametrize("text,code", REAL_ZLIB_MESSAGES)
    def test_reale_zlib_meldung_behaelt_den_kontext(self, text, code):
        """Chunk-Index, Position und Groesse bleiben erhalten."""
        out = public_error(ValueError(_zlib_message(3, 0x1B0, 91234, text)))
        assert "chunk 3" in out, out
        assert "0x1B0" in out, out
        assert "91234" in out, out

    @pytest.mark.parametrize("text,code", REAL_ZLIB_MESSAGES)
    def test_reale_zlib_meldung_gibt_nicht_den_cpython_text_aus(self, text, code):
        """Der CPython-Text selbst erscheint nicht in der oeffentlichen Meldung."""
        out = public_error(ValueError(_zlib_message(3, 0x1B0, 91234, text)))
        assert "while decompressing data" not in out, out
        assert "incorrect header check" not in out, out
        assert text not in out, out

    @pytest.mark.parametrize("text,code", REAL_ZLIB_MESSAGES)
    def test_bekannter_code_ergibt_die_feste_beschreibung(self, text, code):
        """Der Code wird ueber die eigene Tabelle beschrieben."""
        out = public_error(ValueError(_zlib_message(3, 0x1B0, 91234, text)))
        assert ZLIB_CODES[code] in out, out

    def test_synthetische_alte_form_wird_ebenfalls_akzeptiert(self):
        """Die bisherige synthetische Form ``Error -3`` bleibt gueltig."""
        out = public_error(ValueError(_zlib_message(3, 0x1B0, 91234, "Error -3")))
        assert "chunk 3" in out and "0x1B0" in out and "91234" in out

    def test_unbekannter_code_behaelt_den_kontext(self):
        """Ein unbekannter, aber wohlgeformter Code verliert den Kontext nicht."""
        out = public_error(ValueError(
            _zlib_message(4, 0x200, 1000, "Error -99")))
        assert "chunk 4" in out, out
        assert "0x200" in out, out
        assert "1000" in out, out

    def test_alle_bekannten_codes_haben_eine_beschreibung(self):
        """Jeder Code in der Tabelle hat eine eigene, statische Beschreibung."""
        for code, description in ZLIB_CODES.items():
            assert description
            assert "zlib:" in description
            assert description == description.strip()
            assert str(code) not in description, (code, description)

    def test_fehlender_code_faellt_sicher_zurueck(self):
        """Ohne ``Error -N``-Prefix: kein Leck, kein Absturz, keine Ausgabe."""
        out = public_error(ValueError(
            _zlib_message(0, 0x1B0, 8, "irgendwas Beliebiges")))
        leaks = _leaks(out)
        assert not leaks, out
        assert "irgendwas" not in out, out

    def test_ungueltiger_code_faellt_sicher_zurueck(self):
        """``Error --3`` ist kein gueltiger Code — kein Leck."""
        out = public_error(ValueError(
            _zlib_message(0, 0x1B0, 8, "Error --3")))
        assert "Error --3" not in out, out

    def test_exception_text_mit_pfad_leakt_nicht(self):
        """Ein Exception-Text mit eingebettetem Pfad wird nie ausgegeben."""
        out = public_error(ValueError(_zlib_message(
            0, 0x1B0, 8, "/home/cole/%s/x.sfs" % MARKER)))
        leaks = _leaks(out)
        assert not leaks, out
        assert MARKER not in out, out

    def test_exception_text_mit_pfad_und_code_leakt_nicht(self):
        """Auch ein wohlgeformter Code darf keinen Pfad dahinter tragen."""
        out = public_error(ValueError(_zlib_message(
            0, 0x1B0, 8, "Error -3 /home/cole/%s/x.sfs" % MARKER)))
        leaks = _leaks(out)
        assert not leaks, out

    def test_interner_text_bleibt_vollstaendig(self):
        """Die interne Diagnose traegt den Originaltext weiterhin."""
        raw = "Error -3 while decompressing data: incorrect header check"
        exc = ValueError(_zlib_message(3, 0x1B0, 91234, raw))
        intern = diagnostic_error(exc)
        assert raw in intern, intern
        assert "chunk 3" in intern, intern

    def test_kein_traceback_bei_kaputtem_zlib_text(self):
        """Ein zerstoerter zlib-Text darf keinen Absturz ausloesen."""
        for raw in ("Error -3", "Error -99", "Error", "Error --3", "", "Error -3 " * 50):
            out = public_error(ValueError(_zlib_message(0, 0, 0, raw)))
            assert isinstance(out, str)


class TestN2ProduktiverPfad:
    """N2 am echten Dekompressionspfad — der Fall aus dem Befund."""

    def test_kaputter_chunk_verliert_den_kontext_nicht(self, tmp_path):
        """Ein echter BCPS-Container mit zerstoertem zlib-Chunk.

        Der Chunk wird so gebaut, dass ``zlib.decompress`` mit einem echten
        CPython-Fehler scheitert (``incorrect header check``). Der Fehler
        darf den Chunk-Kontext nicht mehr verlieren.
        """
        payload = b"SFS_SAVEGAME" + b"\x00" * 64
        blob = bytearray(build_synthetic_sfs(payload))
        # Der erste Chunk beginnt direkt nach Kopf + Groessen-Tabelle.
        # Wir zerstoeren ihn so, dass zlib an der Magic scheitert.
        layout = _container_layout(bytes(blob))
        offset = layout["compressed_offset"]
        size = layout["first_chunk_size"]
        blob[offset:offset + size] = b"\xff" * size
        target = tmp_path / "kaputter_chunk.sfs"
        target.write_bytes(bytes(blob))

        result = _run_cli(["save", "info", str(target)])
        combined = result.stdout.decode("utf-8", "replace") + \
            result.stderr.decode("utf-8", "replace")
        assert "Traceback" not in combined, combined
        assert result.returncode == 1
        # Der Chunk-Kontext muss in der oeffentlichen Ausgabe stehen.
        assert "chunk 0" in combined, combined
        assert "0x%X" % offset in combined, combined
        assert str(size) in combined, combined

    def test_kaputter_chunk_bleibt_auch_im_json_modus_lesbar(self, tmp_path):
        """Dasselbe im JSON-Modus: genau ein Dokument mit dem Kontext."""
        payload = b"SFS_SAVEGAME" + b"\x00" * 64
        blob = bytearray(build_synthetic_sfs(payload))
        layout = _container_layout(bytes(blob))
        offset = layout["compressed_offset"]
        size = layout["first_chunk_size"]
        blob[offset:offset + size] = b"\xff" * size
        target = tmp_path / "kaputter_chunk.sfs"
        target.write_bytes(bytes(blob))

        result = _run_cli(["--json", "save", "info", str(target)])
        payload_out = json.loads(result.stdout.decode("utf-8"))
        assert payload_out["exit_code"] == 1
        assert "chunk 0" in payload_out["error"], payload_out
        assert not _leaks(result.stdout.decode("utf-8")), result.stdout


def _container_layout(blob: bytes) -> dict:
    """Liest die noetigen Kopf-Felder direkt aus dem Container."""
    chunk_sizes_offset = struct.unpack_from("<q", blob, 8)[0]
    compressed_offset = struct.unpack_from("<q", blob, 24)[0]
    first_size = struct.unpack_from("<i", blob, chunk_sizes_offset)[0]
    return {
        "chunk_sizes_offset": chunk_sizes_offset,
        "compressed_offset": compressed_offset,
        "first_chunk_size": first_size,
    }


# ---------------------------------------------------------------------------
# Querschnitt: die R1.1-Invarianten duerfen nicht gebrochen werden
# ---------------------------------------------------------------------------
class TestR1_1InvariantenUnveraendert:
    """Die Korrektur darf die bestehenden Sicherheitszusagen nicht brechen."""

    def test_pfade_in_meldungen_werden_weiterhin_verworfen(self):
        from test_ssb_i_r1_1_hardening import PATH_FORMS
        for pfad in PATH_FORMS:
            for message in ("Not an SFS file: %s" % pfad,
                            "Not a DAT file: starts with %s" % pfad,
                            "Only ZIP compression supported, got %s" % pfad):
                out = public_error(ValueError(message))
                assert not _leaks(out), (message, out)

    def test_fremdtext_wird_weiterhin_verworfen(self):
        out = public_error(ValueError("Sonstiger Fehler: %s" % MARKER))
        assert not _leaks(out)
        assert out == "ValueError"

    def test_oserror_bleibt_unveraendert(self):
        out = public_error(OSError(2, "/home/cole/%s/x.sfs" % MARKER))
        assert not _leaks(out)
        assert out == "FileNotFoundError: No such file or directory"

    def test_kein_platzhalter_nimmt_freie_zeichenketten_an(self):
        from ssb_i.errors import SAFE_MESSAGE_TEMPLATES
        for template in SAFE_MESSAGE_TEMPLATES:
            names = re.findall(r"\{([a-z]+)\}", template)
            for name in names:
                assert name not in ("str", "text", "raw", "any"), (template, name)

    def test_meldungslaenge_bleibt_begrenzt(self):
        long_message = "zlib-decompression failed at chunk 1 " + "x" * 5000
        assert len(public_error(ValueError(long_message))) <= 260

    def test_alle_vorlagen_sind_verwendbar(self):
        """Jede Vorlage greift mit einem plausiblen Wert tatsaechlich."""
        from ssb_i.errors import SAFE_MESSAGE_TEMPLATES
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
