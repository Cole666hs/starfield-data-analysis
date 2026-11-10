"""Tests fuer den SFS-Savegame-Provider.

FIXTURE-GESCHICHTE
  Bis 08.11.2026 luden diese Tests zwei Referenz-Saves aus
  ``/tmp/starter-save`` und ``/tmp/second-save`` (Spielername "DANTE" bzw.
  "Brian", Save-Version 104 und 122). Diese Dateien existieren nicht mehr, also
  wurden acht Tests still uebersprungen — der Provider, auf dem die einzige
  echte UI-Seite aufbaut, hatte damit keine laufende Regression.

  Jetzt laufen sie gegen die real vorhandenen Spielstaende unter ``SAVE_PROBES``
  (Default ``~/ssb_probes``) und sind Pflicht: fehlt die Datenbasis, schlagen sie
  fehl. Die alten Save-Versionen 104/122 sind als eigene Luecke dokumentiert
  (``docs/reports/SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md``) — fuer sie liegt
  kein Artefakt mehr vor.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import GOLDEN


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


def test_read_container_on_real_saves(real_saves, provider):
    """Container-Metadaten aller echten Saves."""
    for path in real_saves:
        container = provider.read_container(str(path))
        assert container.version0 == 1, path.name
        assert container.chunk_size_pre == GOLDEN["chunk_size_pre"], path.name
        assert container.padding_size == GOLDEN["padding_size"], path.name
        assert container.compressed_offset > 0, path.name
        assert container.chunk_count in (90, 91), (path.name, container.chunk_count)


def test_decompress_round_trip_on_real_saves(real_saves, provider):
    """Dekompression liefert exakt die deklarierte Groesse und den DAT-Magic."""
    for path in real_saves:
        container = provider.read_container(str(path))
        payload = provider.decompress(str(path))
        assert len(payload) == container.uncompressed_size, path.name
        assert payload[:12] == b"SFS_SAVEGAME", path.name


def test_decompress_rejects_length_mismatch(real_saves, provider, tmp_path):
    """verify=True ist Default: eine Luege im Groessenfeld faellt sofort auf."""
    import struct
    data = bytearray(real_saves[0].read_bytes())
    declared, = struct.unpack_from("<q", data, 32)
    struct.pack_into("<q", data, 32, declared + 1)
    damaged = tmp_path / "mismatch.sfs"
    damaged.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="does not match declared uncompressed_size"):
        provider.decompress(str(damaged))
    # Ohne Pruefung kommt der kurze Puffer durch — der stille Fehler von vorher.
    assert len(provider.decompress(str(damaged), verify=False)) == declared


def test_dat_header_on_real_saves(real_saves, provider):
    """Header-Felder, die in allen sechs Saves gleich sind."""
    for path in real_saves:
        payload = provider.decompress(str(path))
        header = provider.parse_dat_header(payload)
        assert header.save_version == GOLDEN["save_version"], path.name
        assert header.engine_version == GOLDEN["engine_version"], path.name
        assert header.player_name == "Cole", path.name
        assert header.player_level == 24, path.name
        assert header.race_name == "HumanRace", path.name
        assert header.current_game_version == "1.16.244.0", path.name
        assert header.created_game_version == "1.16.236.0", path.name
        assert header.plugin_info_offset in (166, 168), path.name
        assert header.plugin_info_size == 5077, path.name


def test_playtime_field_contains_both_formats(real_saves, provider):
    """Der Save speichert zwei Spielzeit-Formate in einem String (Befund)."""
    payload = provider.decompress(str(real_saves[0]))
    header = provider.parse_dat_header(payload)
    assert "d." in header.playtime and "h." in header.playtime
    assert "Tage" in header.playtime or "Tag" in header.playtime


def test_plugin_info_on_real_saves(real_saves, provider):
    """Vollstaendige Plugin-Liste inklusive Medium-Kette."""
    for path in real_saves:
        payload = provider.decompress(str(path))
        header = provider.parse_dat_header(payload)
        info = provider.parse_plugin_info(payload, header)
        assert info.decode_state == "VALIDATED", (path.name, info.note)
        assert info.normal[0].name == "Starfield.esm", path.name
        assert info.total == GOLDEN["plugins"]["total"], path.name


def test_diff_returns_byte_level_changes(real_saves, provider):
    """Zwei echte Saves unterscheiden sich bytegenau."""
    if len(real_saves) < 2:
        pytest.skip("nur ein Save vorhanden")
    diff = provider.diff_saves(str(real_saves[0]), str(real_saves[-1]), max_diff=5)
    assert diff["a_size"] > 0 and diff["b_size"] > 0
    assert diff["diffs_count"] > 0


def test_read_chunk_table_matches_declared_sizes(real_saves, provider):
    """read_chunk_table materialisiert, was decompress() intern verbraucht."""
    for path in real_saves:
        table = provider.read_chunk_table(str(path))
        container = provider.read_container(str(path))
        assert table["declared_chunk_count"] == container.chunk_count, path.name
        assert len(table["chunk_sizes"]) == container.chunk_count, path.name
        assert sum(table["chunk_sizes"]) > 0, path.name


def test_savegame_provider_is_read_only(provider):
    """Kein oeffentlicher Provider-Aufruf oeffnet eine Datei zum Schreiben."""
    methods = [m for m in dir(provider)
               if not m.startswith("_") and callable(getattr(provider, m))]
    assert methods, "keine oeffentlichen Methoden gefunden"
    for name in methods:
        source = inspect.getsource(getattr(provider, name))
        for token in ('"wb"', "'wb'", '"w"', "'w'", '"ab"', "'ab'"):
            assert token not in source, (
                "%s oeffnet Dateien schreibend (%s) — der Provider muss strikt "
                "lesend bleiben" % (name, token))
