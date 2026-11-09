"""R1 — oeffentliche Fehlertexte ohne private Dateipfade.

Geprueft wird der zentrale Formatter (ssb_i/errors.py) **und** jede betroffene
Ausgabestelle: UI-Statuszeile, ``last_error``, Integrity-Tab, QMessageBox,
``--self-test``-stdout, CLI. Die Gegenbeispiele aus dem unabhaengigen Review
(8 von 19 Pfadformen liefen durch den alten Filter) sind hier als
Regressionstests festgehalten.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import build_dat_payload, build_synthetic_sfs  # noqa: E402

from ssb_i.errors import (diagnostic_error, public_error,  # noqa: E402
                          public_error_detail)

#: Private Bestandteile, die in oeffentlichen Ausgaben nie auftauchen duerfen.
MARKER = "PRIVAT-R1-MARKER"
PRIVATE = "/home/cole/%s/Spielstand.sfs" % MARKER


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _private_dir(tmp_path: Path) -> Path:
    """Verzeichnis mit privatem Namensbestandteil und .sfs-Endung."""
    folder = tmp_path / MARKER
    folder.mkdir()
    victim = folder / "Save.sfs"
    victim.mkdir()                       # lsbar, aber open() scheitert
    return victim


# ---------------------------------------------------------------------------
# Zentraler Formatter
# ---------------------------------------------------------------------------
def test_public_error_keeps_class_and_drops_path_for_oserror():
    cases = (
        IsADirectoryError(21, "Is a directory", PRIVATE),
        FileNotFoundError(2, "No such file or directory", PRIVATE),
        PermissionError(13, "Permission denied", PRIVATE),
        NotADirectoryError(20, "Not a directory", PRIVATE),
        OSError(5, "Input/output error", PRIVATE),
        OSError(9999, None, PRIVATE),                 # ohne strerror
        OSError("/home/cole/%s/ohne_strerror" % MARKER),
        IsADirectoryError(21, None, PRIVATE),
    )
    for exc in cases:
        text = public_error(exc)
        assert type(exc).__name__ in text, text
        assert MARKER not in text, text
        assert "/home/cole" not in text, text


def test_public_error_drops_unknown_messages_entirely():
    """Die acht im Review durchgelassenen Pfadformen duerfen nicht mehr erscheinen."""
    forms = (
        "./%s/a.sfs" % MARKER,                       # relativ mit ./
        "%s/cole/a.sfs" % MARKER,                    # relativ ohne Slash
        "\\\\server\\share\\%s\\a.sfs" % MARKER,     # UNC
        "cole\\%s\\a.sfs" % MARKER,                  # Backslash ohne Laufwerk
        "/home/cole\\%s/a.sfs" % MARKER,             # gemischt
        "/home/cole/My Saves/%s a.sfs" % MARKER,     # Leerzeichen unquotiert
        "%s_geheim.sfs" % MARKER,                    # ohne Trenner
        "/home\\x2fcole\\x2f%s" % MARKER,            # escaped
        "/home/cole/%s/a.sfs" % MARKER,              # absolut (Referenz)
        "C:\\Users\\cole\\%s\\a.sfs" % MARKER,       # Windows-Laufwerk
    )
    for raw in forms:
        exc = ValueError(raw)
        text = public_error(exc)
        # unbekannter Text wird verworfen, nicht gefiltert
        assert text == "ValueError", (raw, text)
        assert MARKER not in text
        # die volle Information bleibt intern verfuegbar
        assert MARKER in diagnostic_error(exc)


def test_public_error_keeps_own_messages():
    """Eigene, kontrollierte Meldungen bleiben lesbar (Diagnose geht nicht verloren)."""
    assert "Not an SFS file" in public_error(
        ValueError("Not an SFS file: b'kein' (expected b'BCPS')"))
    assert "zlib-decompression failed at chunk 3" in public_error(
        ValueError("zlib-decompression failed at chunk 3 (pos=0x1B0, size=91234): Error -3"))

    header_error = type("SfsHeaderError", (ValueError,), {})
    header = header_error("SFS_SAVEGAME header not decodable (1 of 1 chunks, 78 bytes): "
                          "ValueError: Not a DAT file: starts with b'NOT_A_SAVEGA'")
    assert "SFS_SAVEGAME header not decodable" in public_error(header)
    assert public_error_detail(header).startswith("SFS_SAVEGAME header not decodable")


def test_public_error_survives_exception_with_broken_str():
    class Broken(Exception):
        def __str__(self):
            raise RuntimeError("__str__ kaputt")

    text = public_error(Broken())
    assert text == "Broken"          # kein Absturz, keine Faelschung


def test_public_error_caps_length():
    long_message = "zlib-decompression failed at chunk 1 " + "x" * 5000
    assert len(public_error(ValueError(long_message))) <= 260


# ---------------------------------------------------------------------------
# Ausgabestellen — UI
# ---------------------------------------------------------------------------
def test_ui_status_and_last_error_have_no_path(tmp_path, qapp):
    from ssb_ui.pages.savegame_page import SavegamePage

    victim = _private_dir(tmp_path)
    page = SavegamePage()
    assert page.load_file(str(victim), show_dialog=False) is False

    assert page.last_error and "IsADirectoryError" in page.last_error
    assert str(victim) not in page.last_error
    assert MARKER not in page.last_error
    assert MARKER not in page.status_label.text()


def test_ui_integrity_tab_has_no_path(tmp_path, qapp):
    from ssb_ui.pages.savegame_page import SavegamePage

    victim = _private_dir(tmp_path)
    page = SavegamePage()
    page._run_integrity(str(victim))
    shown = page.integrity_view.toPlainText()
    assert "IsADirectoryError" in shown
    assert str(victim) not in shown
    assert MARKER not in shown


def test_hex_view_dialog_has_no_path(tmp_path, qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from ssb_ui.pages.hex_view_page import HexViewPage

    victim = _private_dir(tmp_path)
    captured = {}

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(victim), "")))
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda parent, title, text, *a, **k:
                                     captured.update(title=title, text=text)))
    page = HexViewPage()
    page.on_open_file()

    assert captured, "QMessageBox wurde nicht aufgerufen"
    assert "IsADirectoryError" in captured["text"]
    assert str(victim) not in captured["text"]
    assert MARKER not in captured["text"]


# ---------------------------------------------------------------------------
# Ausgabestellen — CLI / self-test / JSON
# ---------------------------------------------------------------------------
def test_self_test_stdout_has_no_path(tmp_path, qapp):
    repo = Path(__file__).resolve().parents[1]
    victim = _private_dir(tmp_path)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run([sys.executable, "-m", "ssb_ui.app", "--self-test", str(victim)],
                         capture_output=True, text=True, cwd=str(repo), env=env, timeout=300)
    combined = run.stdout + run.stderr
    assert run.returncode == 1
    assert "SELF_TEST FAIL" in combined
    assert "IsADirectoryError" in combined
    assert str(victim) not in combined, combined[:400]
    assert MARKER not in combined


def test_cli_and_json_have_no_path_for_discarded_files(tmp_path):
    """Verworfene Fremddateien duerfen ihren Pfad nicht in die Ausgabe tragen."""
    work = tmp_path / "work"
    work.mkdir()
    target = work / "Save0.sfs"
    target.write_bytes(build_synthetic_sfs(build_dat_payload()))

    seqdir = tmp_path / MARKER                     # privater Ordnername
    seqdir.mkdir()
    (seqdir / "Save1.sfs").mkdir()                 # unreadable
    (seqdir / "Save2.sfs").write_bytes(b"kein BCPS")

    repo = Path(__file__).resolve().parents[1]
    for extra in ((), ("--json",)):
        run = subprocess.run([sys.executable, str(repo / "sfda_cli.py"), *extra,
                              "save", "verify", "--sequence-dir", str(seqdir),
                              str(target)],
                             capture_output=True, text=True, cwd=str(repo), timeout=300)
        out = run.stdout + run.stderr
        assert MARKER not in out, out[:400]
        assert str(seqdir) not in out, out[:400]
        assert "IsADirectoryError" in out          # Diagnose bleibt erhalten
        if extra:
            payload = json.loads(run.stdout)       # gueltiges JSON
            i14 = next(c for c in payload["checks"] if c["check_id"] == "I-14")
            selection = json.dumps(i14["evidence"]["selection"])
            assert MARKER not in selection, selection[:400]


# ---------------------------------------------------------------------------
# Strukturwaechter — AST statt Textmuster
# ---------------------------------------------------------------------------
#: Funktionen, die aus einer Exception einen *oeffentlichen* Text bauen.
EXCEPTION_SINKS = {
    "public_error", "public_error_detail", "diagnostic_error",
    "_error_text", "_error_reason", "_public_error", "_cli_error_text",
}
#: Aufrufe, die eine Exception nur pruefen statt auszugeben.
SAFE_CALLS = {"isinstance", "type", "hasattr", "issubclass", "_exit_code_of"}
#: Attribute, die keine Ausgabe erzeugen.
SAFE_EXCEPTION_ATTRS = {"__class__", "__name__", "__module__", "__traceback__"}
#: Kommentar, der eine geprueft-unbedenkliche Verwendung kennzeichnet. Die
#: Begruendung steht dahinter und ist Pflicht.
REVIEW_MARKER = "exception-text-reviewed"
#: Erwartete Anzahl markierter Stellen. Eine neue Stelle erhoeht diese Zahl —
#: das ist Absicht: sie muss im Review begruendet werden.
REVIEWED_SITES = 4


def unfiltered_exception_uses(source: str) -> list[tuple[int, str]]:
    """Verwendungen einer ``except ... as NAME``-Exception ohne Formatter.

    Erkennt **strukturell** (AST), nicht per Textmuster: ``f"{e!s}"``,
    ``f"{e!r}"``, ``"{}.format(e)"``, ``"%s" % e``, Alias-Variablen,
    ``e.args``, ``e.__str__()``, Stringverkettung, JSON-Serialisierung und
    mehrzeilige Ausdruecke. Jede Verwendung des gebundenen Namens ausserhalb
    eines erlaubten Formatter-Aufrufs faellt auf.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Einzelne Handler-Bloecke sind kein Modul — in eine Funktion einbetten.
        tree = ast.parse("try:\n    pass\n" + textwrap.indent(source, ""))
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    findings: list[tuple[int, str]] = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        for use in ast.walk(handler):
            if not (isinstance(use, ast.Name) and use.id == handler.name
                    and isinstance(use.ctx, ast.Load)):
                continue
            parent = parents.get(id(use))
            if isinstance(parent, ast.Call):
                func = parent.func
                called = (func.id if isinstance(func, ast.Name)
                          else getattr(func, "attr", ""))
                if called in EXCEPTION_SINKS or called in SAFE_CALLS:
                    continue
            if isinstance(parent, ast.Raise):
                continue                     # raise exc / raise ... from exc
            if isinstance(parent, ast.Attribute) and parent.attr in SAFE_EXCEPTION_ATTRS:
                continue
            findings.append((use.lineno, handler.name))
    return findings


def _scanned_files() -> list[Path]:
    repo = Path(__file__).resolve().parents[1]
    return [repo / "sfda_cli.py",
            *sorted((repo / "ssb_ui").rglob("*.py")),
            *sorted((repo / "ssb_i").rglob("*.py"))]


def test_no_unfiltered_exception_text_in_output_files():
    """Keine ungefilterte Exception-Verwendung in CLI, UI und Kern.

    Bekannte Grenze: geprueft werden Verwendungen des in ``except`` gebundenen
    Namens. Ein Pfad, der als Argument in eine Fremdfunktion fliesst und dort
    zu Text gebaut wird, wird nur erfasst, wenn diese Funktion nicht in
    ``EXCEPTION_SINKS``/``SAFE_CALLS`` steht. Das ist kein vollstaendiger
    Taint-Nachweis — es ist ein struktureller Regressionswaechter.
    """
    offenders = []
    for path in _scanned_files():
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for lineno, _name in unfiltered_exception_uses(source):
            line = lines[lineno - 1]
            if REVIEW_MARKER in line:
                continue
            offenders.append("%s:%d: %s" % (path.name, lineno, line.strip()))
    assert not offenders, "ungefilterte Exception-Verwendung: %s" % offenders


def test_structure_guard_catches_documented_bypasses():
    """Die im Review dokumentierten Umgehungsformen muessen erkannt werden."""
    cases = {
        "fstring_s": 'except Exception as e:\n    print(f"x {e!s}")\n',
        "fstring_r": 'except Exception as e:\n    print(f"x {e!r}")\n',
        "dot_format": 'except Exception as e:\n    print("x {}".format(e))\n',
        "percent": 'except Exception as e:\n    print("x %s" % e)\n',
        "alias": 'except Exception as e:\n    msg = e\n    print(f"x {msg}")\n',
        "args": 'except Exception as e:\n    print("x", e.args[0])\n',
        "dunder_str": 'except Exception as e:\n    print("x", e.__str__())\n',
        "concat": 'except Exception as e:\n    print("x " + str(e))\n',
        "json": 'except Exception as e:\n    json.dumps({"r": f"{e}"})\n',
        "multiline": 'except Exception as e:\n    print(\n        f"x {e}"\n    )\n',
        "raise_chain_only_ok": None,
    }
    missed = [name for name, src in cases.items()
              if src is not None and not unfiltered_exception_uses(src)]
    assert not missed, "Waechter uebersieht: %s" % missed


def test_structure_guard_accepts_formatter_and_checks():
    """Formatter-Aufrufe, isinstance/type und ``raise ... from exc`` sind ok."""
    ok = (
        'except Exception as e:\n'
        '    text = public_error(e)\n'
        '    assert isinstance(e, OSError)\n'
        '    raise CliError(text) from e\n'
    )
    assert not unfiltered_exception_uses(ok)


def test_reviewed_exception_text_sites_are_known():
    """Geprueft-unbedenkliche Stellen sind begruendet markiert und abgezaehlt."""
    marked = []
    for path in _scanned_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if REVIEW_MARKER not in line:
                continue
            reason = line.split(REVIEW_MARKER, 1)[1]
            assert reason.strip().startswith(":"), \
                "Begruendung fehlt: %s:%d" % (path.name, number)
            assert len(reason.strip()) > 5, \
                "Begruendung zu kurz: %s:%d" % (path.name, number)
            marked.append("%s:%d" % (path.name, number))
    assert len(marked) == REVIEWED_SITES, (
        "Anzahl markierter Exception-Text-Stellen hat sich geaendert (%d statt %d): %s "
        "— neue Stelle im Review begruenden und REVIEWED_SITES anpassen"
        % (len(marked), REVIEWED_SITES, marked))


def test_safe_prefix_list_matches_real_messages():
    """Jede Whitelist-Zeichenkette existiert wirklich im Produktivcode."""
    from ssb_i.errors import SAFE_MESSAGE_PREFIXES

    sources = "\n".join(p.read_text() for p in
                        (Path(__file__).resolve().parents[1] / "ssb_i").glob("*.py"))
    missing = [prefix for prefix in SAFE_MESSAGE_PREFIXES if prefix not in sources]
    assert not missing, "unbenutzte Whitelist-Eintraege: %s" % missing


# ---------------------------------------------------------------------------
# R1-Fix: OSError ohne strerror-Vertrauen
# ---------------------------------------------------------------------------
ABS = "/home/cole/%s/Spielstand.sfs" % MARKER
REL = "%s/Spielstand.sfs" % MARKER
UNC = r"\\server\share\%s\Spielstand.sfs" % MARKER
BSL = r"cole\%s\Spielstand.sfs" % MARKER
MIXED = "/home/cole\\%s/Spielstand.sfs" % MARKER
SPACED = "/home/cole/My Saves/%s a.sfs" % MARKER
BARE = "%s_geheim.sfs" % MARKER
ESCAPED = "/home\\x2fcole\\x2f%s" % MARKER
DRIVE = r"C:\Users\cole\%s\Spielstand.sfs" % MARKER


class _StrErrorPath(OSError):
    """Selbst gebaute Instanz mit Pfad in ``strerror``."""

    @property
    def strerror(self):                                  # type: ignore[override]
        return ABS


class _StrErrorBare(OSError):
    @property
    def strerror(self):                                  # type: ignore[override]
        return BARE


class _BrokenErrno(OSError):
    @property
    def errno(self):                                     # type: ignore[override]
        raise RuntimeError("errno nicht lesbar")


PATH_FORMS = (
    ("absolut POSIX", ABS),
    ("relativ", REL),
    ("UNC", UNC),
    ("Backslash ohne Laufwerk", BSL),
    ("gemischt", MIXED),
    ("Leerzeichen unquotiert", SPACED),
    ("ohne Trenner", BARE),
    ("escaped", ESCAPED),
    ("Windows-Laufwerk", DRIVE),
)


@pytest.mark.parametrize("label,path", PATH_FORMS)
@pytest.mark.parametrize("kind", ["strerror", "filename", "only_message"])
def test_public_error_oserror_drops_every_path_form(kind, label, path):
    """Jede Pfadform in jeder OSError-Spielart bleibt draussen."""
    if kind == "strerror":
        exc = OSError(2, path, path)
    elif kind == "filename":
        exc = FileNotFoundError(2, "No such file or directory", path)
    else:
        exc = FileNotFoundError(path)
    text = public_error(exc)
    assert MARKER not in text, (label, kind, text)
    assert "/home/cole" not in text, (label, kind, text)
    assert "server" not in text, (label, kind, text)
    assert type(exc).__name__ in text, (label, kind, text)


def test_public_error_never_reads_strerror():
    """``strerror`` ist bei selbst gebauten Instanzen frei waehlbar."""
    for exc in (_StrErrorPath(2, None, ABS), _StrErrorBare(2, None, BARE)):
        text = public_error(exc)
        assert MARKER not in text, text
        assert type(exc).__name__ in text
    # auch bei bekannter errno: der Text kommt aus der Tabelle, nicht von aussen.
    # (OSError mit errno 2 wird von CPython als FileNotFoundError gebaut.)
    exc = OSError(2, "cannot open " + ABS, ABS)
    assert public_error(exc) == "FileNotFoundError: No such file or directory"
    assert "cannot open" not in public_error(exc)


def test_public_error_survives_unreadable_errno():
    text = public_error(_BrokenErrno(2, "egal", ABS))
    assert text.startswith("_BrokenErrno"), text
    assert MARKER not in text


@pytest.mark.parametrize("errno_value", [None, 0, -1, 9999, 2**31 + 7, 10**30])
def test_public_error_handles_unusual_errno(errno_value):
    exc = OSError(errno_value, "irgendein Text", ABS)
    text = public_error(exc)
    assert MARKER not in text, text
    assert "OSError" in text


def test_public_error_maps_known_errno_to_fixed_text():
    assert public_error(IsADirectoryError(21, "frei gewaehlt", ABS)) == \
        "IsADirectoryError: Is a directory"
    assert public_error(FileNotFoundError(2, "frei gewaehlt", ABS)) == \
        "FileNotFoundError: No such file or directory"
    assert public_error(PermissionError(13, "frei gewaehlt", ABS)) == \
        "PermissionError: Permission denied"
    assert public_error(OSError(5, "frei gewaehlt", ABS)) == \
        "OSError: errno 5: Input/output error"
    assert public_error(OSError(9999, None, ABS)) == \
        "OSError: errno 9999: unclassified OS error"
    # generische OSError ohne errno nennt keinen Text
    assert public_error(OSError(ABS)) == "OSError: unclassified OS error"


def test_public_error_real_filesystem_errors(tmp_path):
    """Echte ``open()``-Fehler: Klasse + Tabellentext, kein Pfad."""
    victim_dir = tmp_path / MARKER
    victim_dir.mkdir()
    unreadable = victim_dir / "Save.sfs"
    unreadable.write_bytes(b"BCPS")
    unreadable.chmod(0o000)
    cases = []
    try:
        open(victim_dir, "rb")
    except OSError as exc:
        cases.append(exc)
    try:
        open(tmp_path / MARKER / "fehlt.sfs", "rb")
    except OSError as exc:
        cases.append(exc)
    try:
        open(unreadable, "rb")
    except OSError as exc:
        cases.append(exc)
    assert len(cases) == 3
    for exc in cases:
        text = public_error(exc)
        assert MARKER not in text, text
        assert "/home" not in text and str(tmp_path) not in text, text
        assert type(exc).__name__ in text
        assert any(word in text for word in
                   ("Is a directory", "No such file", "Permission denied")), text



def test_public_error_whitelist_message_with_path_is_dropped():
    """Whitelist-Praefix plus Pfad/Dateiname faellt auf die Klasse zurueck."""
    forms = (
        "Not an SFS file " + ABS,
        "Not an SFS file " + REL,
        "Not an SFS file " + UNC,
        "Not an SFS file " + BSL,
        "Not an SFS file " + BARE,
        "Not an SFS file " + DRIVE,
        "Not an SFS file " + ESCAPED,
        "Not an SFS file " + ABS + " vs " + DRIVE,
        "zlib-decompression failed at chunk 1 " + UNC,
    )
    for raw in forms:
        text = public_error(ValueError(raw))
        assert MARKER not in text, (raw, text)
        assert "server" not in text, (raw, text)
        assert "Spielstand" not in text, (raw, text)
        assert "x2f" not in text, (raw, text)
        # entweder nur die Klasse (Backslash/Dateiendung) oder ein vollstaendig
        # ersetzter Platzhalter — nie ein Pfadrest
        assert text == "ValueError" or "<pfad>" in text, (raw, text)


def test_public_error_keeps_clean_whitelist_messages():
    """Die echten Projektmeldungen bleiben unveraendert lesbar.

    R1.2: der Byte-Platzhalter gibt nur noch eine statische Beschreibung aus
    (Befund N1). Die Bytes selbst stehen nicht mehr in der oeffentlichen
    Meldung — das ist die strukturelle Trennung, keine Diagnosevereinfachung.
    """
    assert public_error(ValueError("Not an SFS file: b'kein' (expected b'BCPS')")) == \
        "ValueError: Not an SFS file: unknown signature (expected b'BCPS')"
    assert "zlib-decompression failed at chunk 3" in public_error(
        ValueError("zlib-decompression failed at chunk 3 (pos=0x1B0, size=91234): Error -3"))
    assert "SFS_SAVEGAME header not decodable" in public_error(
        ValueError("SFS_SAVEGAME header not decodable (1 of 1 chunks, 78 bytes): "
                   "ValueError: Not a DAT file: starts with b'NOT_A_SAVEGA'"))


def test_public_error_names_generic_error_classes():
    """``struct.error`` heisst ohne Modul nur "error" — mit Modul ist es lesbar."""
    import struct
    import zlib
    try:
        struct.unpack_from("<i", b"\x00", 4)
    except struct.error as exc:
        assert public_error(exc) == "struct.error"
    assert public_error(zlib.error("Error -3")) == "zlib.error"
