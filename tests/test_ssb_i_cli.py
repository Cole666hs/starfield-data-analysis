"""CLI smoke tests for Starfield Data Analysis (``sfda_cli.py``).

Deckt alle dokumentierten Befehle ab — mit einem im Test erzeugten Savegame
(keine externen Fixtures nötig) und mit den Fehlerpfaden. Zusätzlich die
Fail-Closed-Erwartung: ein strukturell gültiges Save ohne lesbare Plugin-Liste
muss ``UNVERIFIED`` liefern, keine erfundene Liste.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "sfda_cli.py"


def _load_synthetic_module():
    path = Path(__file__).with_name("test_ssb_i_savegame_container_synthetic.py")
    spec = importlib.util.spec_from_file_location("_ssb_synth", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNTH = _load_synthetic_module()


def dat_header(player: bytes = b"Cole", level: int = 24, location: bytes = b"Jemison",
               version: bytes = b"1.16.244.0", plugin_blob: bytes = b"") -> bytes:
    """Baut einen SFS_SAVEGAME-Kopf exakt im erwarteten Layout."""
    b = bytearray(b"SFS_SAVEGAME")
    b += struct.pack("<I", 125)                     # header_size
    b += struct.pack("<I", 27)                      # engine_version
    b += bytes([153])                               # save_version
    b += struct.pack("<I", 44)                      # save_number
    b += struct.pack("<H", len(player)) + player
    b += struct.pack("<I", level)
    b += struct.pack("<H", len(location)) + location
    b += struct.pack("<H", 5) + b"2d.10"            # playtime
    b += struct.pack("<H", 5) + b"Human"            # race
    b += struct.pack("<H", 1)                       # gender
    b += struct.pack("<f", 1.5) + struct.pack("<f", 2.5)
    b += struct.pack("<Q", 123456789)               # filetime
    b += struct.pack("<I", 0)                       # unknown0
    b += b"\x00" * 8                                # padding
    b += bytes([153])                               # save_version_2
    b += struct.pack("<H", len(version)) + version
    b += struct.pack("<H", len(version)) + version
    b += struct.pack("<H", len(plugin_blob)) + plugin_blob
    return bytes(b)


@pytest.fixture()
def synthetic_save(tmp_path) -> Path:
    path = tmp_path / "synthetic.sfs"
    path.write_bytes(SYNTH.build_synthetic_sfs(dat_header()))
    return path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=120)


# --------------------------------------------------------------- Grundgerüst
def test_version_exits_zero():
    result = run_cli("--version")
    assert result.returncode == 0
    from ssb_i.product import VERSION as _V
    assert "Starfield Data Analysis" in result.stdout and _V in result.stdout


def test_unknown_subcommand_is_usage_error():
    result = run_cli("save", "gibtsnicht", "x.sfs")
    assert result.returncode == 2


# ------------------------------------------------------------------ save info
def test_save_info_reports_synthetic_header(synthetic_save):
    result = run_cli("--json", "save", "info", str(synthetic_save))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    # R1_6: der Spielername ist NICHT mehr oeffentlich (W-1/F-1).
    assert "player_name" not in payload["savegame"]
    # Ebenso Ort, Spielzeit und Rasse (O-5).
    assert "player_location" not in payload["savegame"]
    assert "playtime" not in payload["savegame"]
    assert "race" not in payload["savegame"]
    assert "Cole" not in result.stdout
    assert payload["savegame"]["player_level"] == 24
    assert payload["savegame"]["save_version"] == 153
    assert payload["container"]["chunk_count"] >= 1
    assert payload["decompressed_bytes"] > 0
    # R1_6 / F-2: kein absoluter Pfad und kein Dateiname im JSON.
    assert "file" not in payload
    assert "synthetic" not in result.stdout


def test_save_info_plugins_fail_closed(synthetic_save):
    """Ohne lesbare Plugin-Liste: UNVERIFIED + Begruendung, keine Erfindung."""
    result = run_cli("--json", "save", "info", str(synthetic_save))
    assert result.returncode == 0
    plugins = json.loads(result.stdout)["plugins"]
    assert plugins["decode_state"] == "UNVERIFIED"
    assert plugins["note"]
    assert plugins["normal"] == 0


def test_save_info_text_output_is_readable(synthetic_save):
    result = run_cli("save", "info", str(synthetic_save))
    assert result.returncode == 0
    # R1_6: "Player" und der Dateiname sind entfernt.
    assert "Player" not in result.stdout
    assert "Level" in result.stdout
    assert "UNVERIFIED" in result.stdout


# ---------------------------------------------------------------- save header
def test_save_header_json_fields(synthetic_save):
    result = run_cli("--json", "save", "header", str(synthetic_save))
    assert result.returncode == 0
    header = json.loads(result.stdout)
    # R1_6: die oeffentliche Headeransicht ist eine Allowlist. Der
    # Spielername ist nicht mehr enthalten.
    for key in ("player_level", "save_version", "current_game_version",
                "plugin_info_offset", "plugin_info_size"):
        assert key in header
    assert "player_name" not in header
    assert "player_location" not in header
    assert "race_name" not in header
    assert "playtime" not in header
    assert "Cole" not in result.stdout
    assert header["current_game_version"] == "1.16.244.0"


# --------------------------------------------------------------- save plugins
def test_save_plugins_json_shape(synthetic_save):
    result = run_cli("--json", "save", "plugins", str(synthetic_save))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert set(payload) >= {"normal", "light", "medium", "decode_state", "counts"}
    assert payload["decode_state"] == "UNVERIFIED"


# ------------------------------------------------------------------ save diff
def test_diff_same_file_has_no_differences(synthetic_save):
    result = run_cli("--json", "save", "diff", str(synthetic_save), str(synthetic_save))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["analysis"]["differing_byte_count"] == 0
    assert report["result"] == "MATCHED"


def test_diff_two_different_saves_reports_difference(synthetic_save, tmp_path):
    other = tmp_path / "other.sfs"
    other.write_bytes(SYNTH.build_synthetic_sfs(dat_header(player=b"Other", level=7)))
    result = run_cli("--json", "save", "diff", str(synthetic_save), str(other))
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["analysis"]["differing_byte_count"] > 0


def test_diff_can_write_markdown(synthetic_save, tmp_path):
    target = tmp_path / "diff.md"
    result = run_cli("save", "diff", str(synthetic_save), str(synthetic_save),
                     "--markdown", str(target))
    assert result.returncode == 0
    assert target.exists() and target.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------- Fälle
def test_missing_file_reports_error(tmp_path):
    result = run_cli("save", "info", str(tmp_path / "nope.sfs"))
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_non_sfs_reports_error(tmp_path):
    bad = tmp_path / "text.sfs"
    bad.write_text("kein Savegame", encoding="utf-8")
    result = run_cli("save", "info", str(bad))
    assert result.returncode == 1
    assert "Not an SFS file" in result.stderr


def test_pe_info_rejects_non_pe(tmp_path):
    bad = tmp_path / "no.exe"
    bad.write_bytes(b"MZ" + b"\x00" * 16)
    result = run_cli("pe", "info", str(bad))
    assert result.returncode == 1
    assert "PE" in result.stderr


# -------------------------------------------- reale Datei (Pflicht, siehe conftest)
# Reale Artefakte sind nicht Teil des Repos: der Savegame-Pfad kommt aus
# SAVE_PROBES (Default ~/ssb_probes) und ist eine Pflicht-Fixture — kein Skip.
_PE_ENV = os.environ.get("STARFIELD_EXE", "")
REAL_PE = Path(_PE_ENV) if _PE_ENV else Path("__not_set__")


def test_real_save_plugins_validated(real_saves):
    result = run_cli("--json", "save", "plugins", str(real_saves[0]))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decode_state"] == "VALIDATED"
    assert payload["counts"]["total"] == 80
    assert payload["counts"]["medium"] == 5
    assert payload["categories"]["game"] == 9


@pytest.mark.skipif(not REAL_PE.exists(), reason="kein Starfield.exe vorhanden")
def test_real_pe_trust_root_matches():
    result = run_cli("--json", "pe", "info", str(REAL_PE))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["sections"]
    assert payload["trust_root"]["match"] is True
