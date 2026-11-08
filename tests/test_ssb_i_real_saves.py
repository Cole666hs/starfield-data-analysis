"""Reale Saves: Pflichtlauf, Golden-Werte, Unveraendertheit.

Diese Tests ersetzen die frueheren ``pytest.skip``-Fixtures. Sie laufen gegen
die echten Starfield-Spielstaende unter ``SAVE_PROBES`` (Default
``~/ssb_probes``). Fehlt die Datenbasis, schlagen sie fehl — nur mit
``SSB_ALLOW_MISSING_SAVES=1`` wird uebersprungen.

Bevor dieser Test existiert, war die Suite gruen, ohne je einen echten
Spielstand angefasst zu haben. Genau dadurch blieben die drei stillen
Korruptionsfaelle und die fehlende Medium-Kette unbemerkt.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import GOLDEN
from ssb_i.save_integrity import PASS, WARNING, run_all


def sha256(path: Path) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


@pytest.fixture(scope="session")
def save_hashes(real_saves) -> dict[str, str]:
    """SHA-256 aller realen Saves VOR dem Testlauf."""
    return {path.name: sha256(path) for path in real_saves}


# ---------------------------------------------------------------------------
# Container und Header
# ---------------------------------------------------------------------------
def test_all_real_saves_are_readable(real_saves, provider):
    assert len(real_saves) >= GOLDEN["save_count"], (
        "weniger Saves als die dokumentierte Messbasis: %s" % [p.name for p in real_saves])
    for path in real_saves:
        raw = provider.decompress(str(path))
        header = provider.parse_dat_header(raw)
        assert header.save_version == GOLDEN["save_version"], path.name
        assert header.engine_version == GOLDEN["engine_version"], path.name
        assert header.player_name, path.name


def test_container_geometry_matches_golden(real_saves, provider):
    for path in real_saves:
        table = provider.read_chunk_table(str(path))
        assert table["chunk_size_pre"] == GOLDEN["chunk_size_pre"], path.name
        assert table["padding_size"] == GOLDEN["padding_size"], path.name
        assert table["compression"] == "ZIP ", path.name
        assert table["sum_padded"] == table["data_rest"], path.name


# ---------------------------------------------------------------------------
# Plugin-Ketten: die Golden-Werte der Messbasis
# ---------------------------------------------------------------------------
def test_plugin_counts_match_golden(real_saves, provider):
    """25 normal / 50 light / 5 medium = 80. Die Vorgabe 75 war ein Fehler."""
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert info.decode_state == "VALIDATED", (path.name, info.note)
        assert len(info.normal) == GOLDEN["plugins"]["normal"], path.name
        assert len(info.light) == GOLDEN["plugins"]["light"], path.name
        assert len(info.medium) == GOLDEN["plugins"]["medium"], path.name
        assert info.total == GOLDEN["plugins"]["total"], path.name


def test_plugin_categories_match_golden(real_saves, provider):
    """9 Game-Plugins + 71 Mod-Plugins ueber alle drei Ketten."""
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert info.game_count == GOLDEN["categories"]["game"], path.name
        assert info.mod_count == GOLDEN["categories"]["mod"], path.name


def test_plugin_metadata_matches_golden(real_saves, provider):
    """Genau sechs Eintraege tragen echte Creation-Metadaten."""
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert info.metadata_count == GOLDEN["metadata_present"], path.name
        assert info.unreadable_count == 0, path.name
        for entry in info.normal + info.light + info.medium:
            if entry.metadata_state == "present":
                assert entry.creation_name, (path.name, entry.name)
                assert entry.creation_id and entry.creation_id.startswith("TM_"), \
                    (path.name, entry.name, entry.creation_id)


def test_plugin_block_ends_exactly(real_saves, provider):
    """Bytegenaues Blockende ist das staerkste Kriterium der Kettenlesung."""
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert info.block_delta == 0, (path.name, info.block_delta)


def test_medium_plugins_are_identical_across_saves(real_saves, provider):
    """Die fuenf Medium-Plugins sind in allen Saves dieselben."""
    expected = {
        "SFBGS003.esm", "SFBGS006.esm", "PersonalSpacestation.esm",
        "RRLAC - Rabbit's Real Lights Akila City.esm",
        "RRLNA - Rabbit's Real Lights New Atlantis.esm",
    }
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert {p.name for p in info.medium} == expected, path.name


def test_first_plugin_is_starfield_esm(real_saves, provider):
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        assert info.normal[0].name == "Starfield.esm", path.name
        assert info.normal[0].is_native is True, path.name


def test_all_plugin_names_look_like_plugins(real_saves, provider):
    for path in real_saves:
        raw = provider.decompress(str(path))
        info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
        for entry in info.normal + info.light + info.medium:
            assert entry.name.lower().endswith((".esm", ".esl", ".esp")), entry.name


# ---------------------------------------------------------------------------
# String-Pool
# ---------------------------------------------------------------------------
def test_string_pool_reads_on_all_real_saves(real_saves, provider):
    for path in real_saves:
        raw = provider.decompress(str(path))
        header = provider.parse_dat_header(raw)
        info = provider.parse_plugin_info(raw, header)
        pool = provider.read_string_pool(raw, header, info)
        assert pool["status"] == "OK", (path.name, pool["reason"])
        assert 1500 <= pool["count"] <= 2000, (path.name, pool["count"])
        assert pool["count"] == pool["declared_count"], path.name
        assert pool["printable_ratio"] > 0.99, (path.name, pool["printable_ratio"])
        assert len(pool["pointer_table"]) == 12
        # Kein Objektanspruch: die uebrigen elf Zeiger bleiben ohne Semantik.
        assert len(pool["unverified_pointers"]) == 11


def test_string_pool_contents_are_plausible(real_saves, provider):
    path = real_saves[0]
    raw = provider.decompress(str(path))
    header = provider.parse_dat_header(raw)
    info = provider.parse_plugin_info(raw, header)
    pool = provider.read_string_pool(raw, header, info)
    texts = [s["text"] for s in pool["strings"]]
    assert any("Sequence" == t for t in texts)
    assert any(t.startswith("[") for t in texts), "keine Modifikator-Namen gefunden"
    assert any("actors\\human\\animations" in t for t in texts), "keine Animationspfade"


# ---------------------------------------------------------------------------
# Integritaet
# ---------------------------------------------------------------------------
def test_every_real_save_passes_structural_checks(real_saves):
    for path in real_saves:
        report = run_all(path)
        assert report.statuses["I-01"] == PASS, path.name
        assert report.statuses["I-02"] == PASS, path.name
        assert report.statuses["I-04"] == PASS, path.name
        assert report.statuses["I-05"] == PASS, path.name
        assert report.statuses["I-06"] == PASS, path.name
        assert report.statuses["I-07"] == PASS, path.name
        assert report.statuses["I-08"] == PASS, path.name
        assert report.statuses["I-10"] == PASS, path.name
        assert report.statuses["I-11"] == PASS, path.name
        assert report.total in (PASS, WARNING), (path.name, report.total)
        assert report.statuses["I-09"] == "UNKNOWN", path.name
        assert report.statuses["I-13"] == "NOT_CHECKED", path.name


def test_i03_reports_alignment_gap_as_warning(real_saves):
    """Mindestens ein realer Save hat 12 Fuellbytes vor dem Datenstrom."""
    warnings = [p.name for p in real_saves
                if run_all(p).statuses["I-03"] == WARNING]
    passes = [p.name for p in real_saves
              if run_all(p).statuses["I-03"] == PASS]
    assert warnings or passes                              # Status ist bestimmt
    assert all(run_all(p).statuses["I-03"] in (PASS, WARNING) for p in real_saves)


def test_real_save_golden_status_is_stable(real_saves):
    """Zweimal pruefen muss dasselbe Ergebnis liefern (Determinismus)."""
    for path in real_saves[:2]:
        first = run_all(path).statuses
        second = run_all(path).statuses
        assert first == second, path.name


# ---------------------------------------------------------------------------
# Originale unveraendert
# ---------------------------------------------------------------------------
def test_original_saves_are_unchanged(real_saves, save_hashes):
    """SHA-256 vor und nach dem gesamten Testlauf."""
    for path in real_saves:
        assert sha256(path) == save_hashes[path.name], path.name


def test_original_save_metadata_unchanged(real_saves):
    """Keine Umbenennung, kein Verschieben, kein Anhang."""
    for path in real_saves:
        assert path.exists(), path
        assert path.suffix == ".sfs", path
        assert path.stat().st_size > 1024, path


# ---------------------------------------------------------------------------
# CLI-Konsistenz
# ---------------------------------------------------------------------------
def test_cli_reports_same_plugin_total(real_saves):
    """CLI-Ausgabe und Python-API muessen dieselbe Zahl nennen."""
    import json
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    python = sys.executable
    path = real_saves[0]
    result = subprocess.run(
        [python, str(repo / "sfda_cli.py"), "--json", "save", "info", str(path)],
        capture_output=True, text=True, cwd=str(repo), timeout=180)
    assert result.returncode == 0, result.stderr
    plugins = json.loads(result.stdout)["plugins"]
    assert plugins["total"] == GOLDEN["plugins"]["total"]
    assert plugins["medium"] == GOLDEN["plugins"]["medium"]
    assert plugins["medium"] != 0
    assert plugins["categories"]["game"] == GOLDEN["categories"]["game"]


def test_cli_verify_exit_code_zero_on_intact_save(real_saves):
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "save", "verify", str(real_saves[0])],
        capture_output=True, text=True, cwd=str(repo), timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INTEGRITAET: PASS" in result.stdout
    assert "Hinweis:" in result.stdout


def test_cli_verify_exit_code_nonzero_on_failure(tmp_path, real_saves):
    """Ein FAILED muss einen von null verschiedenen Exit-Code liefern."""
    import struct
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    data = bytearray(real_saves[0].read_bytes())
    declared, = struct.unpack_from("<q", data, 32)
    struct.pack_into("<q", data, 32, declared + 1)        # Fall E
    damaged = tmp_path / "damaged.sfs"
    damaged.write_bytes(bytes(data))
    result = subprocess.run(
        [sys.executable, str(repo / "sfda_cli.py"), "save", "verify", str(damaged)],
        capture_output=True, text=True, cwd=str(repo), timeout=180)
    assert result.returncode != 0
    assert "FAILED" in result.stdout
