"""R1-Fix — zentrale CLI-Fehlergrenze.

Prueft fuer jedes betroffene Subkommando getrennt: stdout, stderr, Exit-Code und
(bei ``--json``) das JSON-Dokument. Auslöser sind strukturell unplausible
Save- und PE-Dateien sowie echte Dateisystemfehler.

Hintergrund: Im unabhaengigen Review (09.11.2026) landeten ungefangene
``struct.error``-Exceptions als Python-Traceback auf stderr — inklusive
absoluter Installationspfade — und bei ``--json`` blieb stdout leer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import build_dat_payload, build_synthetic_sfs  # noqa: E402

CLI = ROOT / "sfda_cli.py"
MARKER = "PRIVAT-R1-MARKER"
PYTHON = sys.executable


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    return subprocess.run([PYTHON, str(CLI), *args], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=300)


# ---------------------------------------------------------------------------
# Fehlerhafte Eingaben
# ---------------------------------------------------------------------------
def _good_save() -> bytes:
    return build_synthetic_sfs(build_dat_payload())


def _flip(blob: bytes, offset: int) -> bytes:
    data = bytearray(blob)
    data[offset] ^= 0xFF
    return bytes(data)


@pytest.fixture(scope="module")
def malformed(tmp_path_factory) -> dict[str, Path]:
    """Strukturell unplausible Save-Dateien (Review- und Fuzz-Faelle)."""
    base = tmp_path_factory.mktemp("malformed")
    good = _good_save()
    blobs = {
        "nur_bcps": b"BCPS",                                # 4 Byte, Review
        "dat13": build_synthetic_sfs(b"SFS_SAVEGAME\x01"),   # 13-Byte-DAT-Payload
        "trunc16": good[:16],                               # Truncation 16 Byte
        "flip12": _flip(good, 12),                          # Mutation Offset 12
        "trunc4": good[:4],                                 # Fuzz
        "flip0": _flip(good, 0),
        "flip8": _flip(good, 8),
        "zeros": b"\x00" * 512,
        "leer": b"",
        "fremdinhalt": "kein Savegame, nur Text".encode("utf-8"),
    }
    folder = base / MARKER                                # privater Verzeichnisname
    folder.mkdir()
    return {name: _write(folder / ("%s.sfs" % name), blob)
            for name, blob in blobs.items()}


@pytest.fixture(scope="module")
def malformed_pe(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("malformed_pe")
    folder = base / MARKER
    folder.mkdir()
    blobs = {
        "mz100": b"MZ" + b"\x00" * 98,                      # 100 Byte, Review
        "optional_header_kaputt": (b"MZ" + b"\x00" * 58
                                   + b"\x40\x00\x00\x00" + b"PE\x00\x00"),
        "signatur_falsch": b"MZ" + b"\x00" * 58 + b"\x40\x00\x00\x00" + b"ZZ\x00\x00",
        "lfanew_riesig": b"MZ" + b"\x00" * 58 + b"\xFF\xFF\xFF\x7F" + b"PE\x00\x00",
        "leer": b"",
    }
    return {name: _write(folder / ("%s.exe" % name), blob)
            for name, blob in blobs.items()}


def _write(path: Path, blob: bytes) -> Path:
    path.write_bytes(blob)
    return path


# ---------------------------------------------------------------------------
# Gemeinsame Zusicherungen
# ---------------------------------------------------------------------------
def assert_no_traceback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined, combined[:600]
    assert str(ROOT) not in combined, ("Installationspfad in der Ausgabe", combined[:600])
    assert MARKER not in combined, ("privater Pfadbestandteil in der Ausgabe", combined[:600])


def assert_text_error(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 1, (result.returncode, result.stderr[:300])
    assert_no_traceback(result)
    assert result.stdout == "", ("stdout muss im Textmodus leer bleiben", result.stdout[:300])
    assert result.stderr.startswith("ERROR: "), result.stderr[:300]
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr[:300]


def assert_json_error(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 1, (result.returncode, result.stderr[:300])
    assert_no_traceback(result)
    assert result.stderr == "", ("stderr muss im JSON-Modus leer bleiben", result.stderr[:300])
    payload = json.loads(result.stdout)              # unabhaengiger Parser
    assert isinstance(payload, dict), payload
    assert "error" in payload and isinstance(payload["error"], str) and payload["error"]
    assert payload["exit_code"] == result.returncode
    assert result.stdout.strip().endswith("}"), result.stdout[-120:]
    return payload


# ---------------------------------------------------------------------------
# Save-Subkommandos
# ---------------------------------------------------------------------------
SAVE_COMMANDS = ("info", "header", "plugins", "strings")


@pytest.mark.parametrize("command", SAVE_COMMANDS)
@pytest.mark.parametrize("case", ["nur_bcps", "dat13", "trunc16", "flip12",
                                  "trunc4", "flip0", "flip8", "zeros", "leer",
                                  "fremdinhalt"])
def test_save_subcommand_text_mode_is_controlled(command, case, malformed):
    assert_text_error(run_cli("save", command, str(malformed[case])))


@pytest.mark.parametrize("command", SAVE_COMMANDS)
@pytest.mark.parametrize("case", ["nur_bcps", "dat13", "trunc16", "flip12", "zeros"])
def test_save_subcommand_json_mode_is_valid(command, case, malformed):
    payload = assert_json_error(run_cli("--json", "save", command, str(malformed[case])))
    assert payload["exit_code"] == 1


@pytest.mark.parametrize("case", ["nur_bcps", "dat13", "trunc16", "flip12"])
def test_save_diff_is_controlled(case, malformed):
    path = str(malformed[case])
    assert_text_error(run_cli("save", "diff", path, path))
    payload = assert_json_error(run_cli("--json", "save", "diff", path, path))
    assert payload["exit_code"] == 1


# ---------------------------------------------------------------------------
# PE-Subkommandos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("command", ("info", "sections"))
@pytest.mark.parametrize("case", ["mz100", "optional_header_kaputt",
                                  "signatur_falsch", "lfanew_riesig", "leer"])
def test_pe_subcommand_text_mode_is_controlled(command, case, malformed_pe):
    assert_text_error(run_cli("pe", command, str(malformed_pe[case])))


@pytest.mark.parametrize("command", ("info", "sections"))
@pytest.mark.parametrize("case", ["mz100", "optional_header_kaputt", "lfanew_riesig"])
def test_pe_subcommand_json_mode_is_valid(command, case, malformed_pe):
    assert_json_error(run_cli("--json", "pe", command, str(malformed_pe[case])))


# ---------------------------------------------------------------------------
# CliError-Vertrag bleibt erhalten
# ---------------------------------------------------------------------------
def test_cli_error_message_is_not_shortened(tmp_path):
    missing = tmp_path / "gibtsnicht.sfs"
    result = run_cli("save", "info", str(missing))
    assert_text_error(result)
    assert "not found" in result.stderr, result.stderr
    assert "CliError" not in result.stderr, result.stderr

    payload = assert_json_error(run_cli("--json", "save", "info", str(missing)))
    assert "not found" in payload["error"]
    assert "CliError" not in payload["error"]


def test_whitelist_message_survives_into_public_error(tmp_path):
    bad = tmp_path / "text.sfs"
    bad.write_text("kein Savegame", encoding="utf-8")
    result = run_cli("save", "info", str(bad))
    assert_text_error(result)
    assert "Not an SFS file" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# Fruehe Dispatch-Fehler und --json-Vertrag
# ---------------------------------------------------------------------------
def test_usage_error_with_json_yields_json_document():
    result = run_cli("--json", "save", "gibtsnicht", "x.sfs")
    assert result.returncode == 2, result.returncode
    payload = json.loads(result.stdout)
    assert payload["exit_code"] == 2
    assert payload["error"]
    assert "Traceback" not in result.stderr


def test_usage_error_without_json_stays_argparse():
    result = run_cli("save", "gibtsnicht", "x.sfs")
    assert result.returncode == 2
    assert result.stdout.strip() == ""
    assert "usage" in result.stderr.lower()


def test_help_and_version_are_not_treated_as_errors():
    for args in (("--help",), ("--version",), ("--json", "--help")):
        result = run_cli(*args)
        assert result.returncode == 0, (args, result.returncode)
        assert "exit_code" not in result.stdout, args


def test_missing_subcommand_with_json_yields_json_document():
    result = run_cli("--json")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["error"] and payload["exit_code"] == 2


# ---------------------------------------------------------------------------
# Unveraenderte Erfolgs-/Regressionspfade
# ---------------------------------------------------------------------------
def test_dump_pages_still_works():
    """``--dump-pages`` gehoert zur UI, nicht zum CLI-Parser."""
    result = subprocess.run([PYTHON, "-m", "ssb_ui.app", "--dump-pages"],
                            cwd=str(ROOT), capture_output=True, text=True, timeout=300,
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen",
                                     PYTHONDONTWRITEBYTECODE="1"))
    assert result.returncode == 0, result.stderr[-300:]
    assert "pages:" in result.stdout
    assert_no_traceback(result)


def test_save_verify_and_self_test_are_regression_free(tmp_path):
    good = _write(tmp_path / "Save0.sfs", _good_save())
    result = run_cli("save", "verify", str(good))
    assert result.returncode in (0, 1), result.stderr[:300]
    assert_no_traceback(result)
    # --self-test ist ein UI-Kanal und braucht Qt offscreen
    ui = subprocess.run([PYTHON, "-m", "ssb_ui.app", "--self-test", str(good)],
                        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
                        env=dict(os.environ, QT_QPA_PLATFORM="offscreen",
                                 PYTHONDONTWRITEBYTECODE="1"))
    assert ui.returncode == 0, (ui.returncode, ui.stdout[-300:], ui.stderr[-300:])
    assert "Traceback" not in (ui.stdout + ui.stderr)


# ---------------------------------------------------------------------------
# KeyboardInterrupt / SystemExit werden nicht verschluckt
# ---------------------------------------------------------------------------
def _parser_with(func):
    class _Args:
        json = False

    class _Parser:
        def parse_args(self, _argv):
            args = _Args()
            setattr(args, "func", func)          # dynamisch, wie argparse
            return args

    return _Parser()


def test_keyboard_interrupt_is_reported_not_swallowed(monkeypatch, capsys):
    import sfda_cli

    def boom(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(sfda_cli, "build_parser", lambda: _parser_with(boom))
    assert sfda_cli.main([]) == sfda_cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert "Aborted." in captured.err
    assert "Traceback" not in captured.err


def test_system_exit_propagates(monkeypatch):
    import sfda_cli

    def bye(_args):
        raise SystemExit(7)

    monkeypatch.setattr(sfda_cli, "build_parser", lambda: _parser_with(bye))
    with pytest.raises(SystemExit) as info:
        sfda_cli.main([])
    assert info.value.code == 7


def test_unexpected_exception_is_caught_at_the_boundary(monkeypatch, capsys):
    import struct

    import sfda_cli

    def boom(_args):
        raise struct.error("unpack requires a buffer of 4 bytes")

    monkeypatch.setattr(sfda_cli, "build_parser", lambda: _parser_with(boom))
    assert sfda_cli.main([]) == sfda_cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.strip() == "ERROR: struct.error"
    assert str(ROOT) not in captured.err
