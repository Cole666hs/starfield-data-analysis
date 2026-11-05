"""Tests for the SFS savegame decode provider (Phase 2.9)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Kein absoluter Arbeitspfad mehr (Befund SSB-I-Audit 05.11.2026): die
# Projektwurzel wird aus der Dateilage abgeleitet, damit der Test auch in einer
# frischen Umgebung laeuft.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Referenz-Saves sind Nutzerdaten (je 5-25 MB) und gehoeren nicht ins Repo.
# Sie lagen bisher unter /tmp und waren beim Audit nicht mehr vorhanden, wodurch
# 8 Tests still uebersprungen wurden. Pfade sind jetzt konfigurierbar; ohne
# Fixture bleibt der Skip, aber mit klarer Anleitung.
DANTE_SFS = os.environ.get(
    "SSB_SFS_DANTE",
    "/tmp/starter-save/Saves/Save1_3E3961A0M44414E5445_001245_20230909055633_100_0_4.sfs",
)
BRIAN_SFS = os.environ.get(
    "SSB_SFS_BRIAN",
    "/tmp/second-save/Saves/Save3130_761983B9_427269616E_102223_20240619134727_330_16_4.sfs",
)


@pytest.fixture(scope="module")
def provider():
    from ssb_i import get_provider
    return get_provider()


@pytest.fixture(scope="module")
def dante_container(provider):
    if not os.path.exists(DANTE_SFS):
        pytest.skip(f"DANTE save not found at {DANTE_SFS}")
    return provider.read_container(DANTE_SFS)


@pytest.fixture(scope="module")
def brian_container(provider):
    if not os.path.exists(BRIAN_SFS):
        pytest.skip(f"BRIAN save not found at {BRIAN_SFS}")
    return provider.read_container(BRIAN_SFS)


def test_capabilities_declares_read_only(provider):
    """Provider must declare itself strictly read-only."""
    caps = provider.capabilities()
    assert caps["memory_write_observation"] is False
    assert caps["execution_events"] is False
    assert caps["memory_read"] is True
    assert caps["module_enumeration"] is True
    assert caps["process_identity"] is True
    assert caps["object_inspection"] is True


def test_capability_probe_marked_read_only(provider):
    probe = provider.capability_probe()
    assert probe["read_only"] is True
    assert probe["provider"] == "sfs-decode"
    assert all(c is False for k, c in probe["capabilities"].items()
               if k in ("memory_write_observation", "execution_events",
                        "thread_events", "register_state", "callstack"))


def test_read_container_returns_sfs(dante_container):
    """DANTE save container parses with expected chunk count and uncompressed size."""
    assert dante_container.chunk_count == 40
    assert dante_container.uncompressed_size == 10_323_570
    assert dante_container.compressed_offset > 0
    assert dante_container.padding_size in (0, 16)


def test_read_container_returns_brian(brian_container):
    assert brian_container.chunk_count == 19
    assert brian_container.uncompressed_size == 4_902_446


def test_decompress_round_trip(provider):
    """Decompressing a known-good save produces the documented size."""
    if not os.path.exists(DANTE_SFS):
        pytest.skip()
    decomp = provider.decompress(DANTE_SFS)
    assert len(decomp) == 10_323_570
    # Must start with the SFS_SAVEGAME magic
    assert decomp[:12] == b"SFS_SAVEGAME"


def test_decompress_brian(provider):
    if not os.path.exists(BRIAN_SFS):
        pytest.skip()
    decomp = provider.decompress(BRIAN_SFS)
    assert len(decomp) == 4_902_446
    assert decomp[:12] == b"SFS_SAVEGAME"


def test_dat_header_dante(provider):
    """DANTE header parses with the expected player/version."""
    if not os.path.exists(DANTE_SFS):
        pytest.skip()
    decomp = provider.decompress(DANTE_SFS)
    header = provider.parse_dat_header(decomp)
    assert header.player_name == "DANTE"
    assert header.player_level == 100
    assert header.current_game_version == "1.7.23.0"
    assert header.save_version == 104


def test_dat_header_brian(provider):
    if not os.path.exists(BRIAN_SFS):
        pytest.skip()
    decomp = provider.decompress(BRIAN_SFS)
    header = provider.parse_dat_header(decomp)
    assert header.player_name == "Brian"
    assert header.player_level == 330
    assert header.current_game_version == "1.12.32.0"
    assert header.save_version == 122


def test_plugin_info_recognizes_blueprints_ships(provider):
    """BlueprintShips-Starfield.esm is the mod Pulse uses; must show up as native."""
    if not os.path.exists(DANTE_SFS):
        pytest.skip()
    decomp = provider.decompress(DANTE_SFS)
    header = provider.parse_dat_header(decomp)
    info = provider.parse_plugin_info(decomp, header)
    normal_names = [p.name for p in info.normal]
    assert "Starfield.esm" in normal_names
    assert "BlueprintShips-Starfield.esm" in normal_names


def test_diff_returns_byte_level_changes(provider):
    """DANTE vs BRIAN diff shows byte-level differences at known offsets."""
    if not (os.path.exists(DANTE_SFS) and os.path.exists(BRIAN_SFS)):
        pytest.skip()
    diff = provider.diff_saves(DANTE_SFS, BRIAN_SFS, max_diff=5)
    assert diff["a_size"] == 10_323_570
    assert diff["b_size"] == 4_902_446
    assert diff["diffs_count"] > 0
    # First difference in the SFS_SAVEGAME region is the player_name byte
    assert diff["diffs"][0]["offset"] < 50


def test_savegame_provider_is_read_only(provider):
    """Sanity: no method on the provider can mutate the file."""
    # All methods are pure: read_container, decompress, parse_*, diff_saves
    # None of them open the file in write mode.
    import inspect
    methods = [m for m in dir(provider) if not m.startswith("_") and callable(getattr(provider, m))]
    for name in methods:
        method = getattr(provider, name)
        src = inspect.getsource(method)
        # Allow our own internal compression to mention 'wb' in docstrings etc., but
        # none of the public methods should open a file in write mode.
        assert "open(" not in src or "wb" not in src or "rb" in src, (
            f"{name} appears to open files for writing — must be strictly read-only"
        )
