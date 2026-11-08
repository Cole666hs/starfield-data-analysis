"""Read-only String-Pool: Positiv- und Negativtests.

Die Funktion belegt Text und Position. Sie belegt KEINE Objektidentitaet —
dieser Test haelt diese Grenze ausdruecklich fest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import (DEFAULT_STRINGS, build_body_head, build_dat_payload,
                      build_synthetic_sfs, plugin_record)
from ssb_i.savegame_provider import SfsDecodeProvider


def _read(payload: bytes):
    provider = SfsDecodeProvider()
    header = provider.parse_dat_header(payload)
    info = provider.parse_plugin_info(payload, header)
    return provider.read_string_pool(payload, header, info)


def test_reads_string_pool_from_synthetic_payload():
    pool = _read(build_dat_payload())
    assert pool["status"] == "OK", pool["reason"]
    assert pool["count"] == len(DEFAULT_STRINGS)
    assert pool["declared_count"] == len(DEFAULT_STRINGS)
    assert [s["text"] for s in pool["strings"]] == DEFAULT_STRINGS
    assert pool["printable_ratio"] == 1.0


def test_each_string_carries_position_and_status():
    pool = _read(build_dat_payload())
    for entry in pool["strings"]:
        assert set(entry) >= {"index", "text", "offset", "length", "status"}
        assert entry["status"] == "ok"
        assert entry["offset"] > 0
        assert entry["length"] == len(entry["text"].encode("utf-8"))
    offsets = [e["offset"] for e in pool["strings"]]
    assert offsets == sorted(offsets)          # sequentiell gelesen
    assert pool["end"] > pool["strings"][-1]["offset"]


def test_pointer_table_is_reported_and_unverified_pointers_listed():
    pool = _read(build_dat_payload())
    assert len(pool["pointer_table"]) == 12
    # pointer[2] ist der belegte Zeiger auf den Folgebenutzer
    assert pool["pointer_table"][2] == pool["block2_offset"]
    # die uebrigen elf bleiben ausdruecklich ohne Semantik
    assert len(pool["unverified_pointers"]) == 11
    assert all("inside_payload" in entry for entry in pool["unverified_pointers"])


def test_no_object_identity_is_claimed():
    pool = _read(build_dat_payload())
    note = pool["note"].lower()
    assert "keine formid" in note and "record" in note and "referenzzuordnung" in note


def test_broken_pointer2_yields_unknown_not_guess():
    """Ungueltiger Zeiger wird NICHT durch heuristische Suche ersetzt."""
    payload = build_dat_payload(body_options={"pointer2_override": 0xDEAD})
    pool = _read(payload)
    assert pool["status"] == "UNKNOWN"
    assert "does not point at the follow-up block" in pool["reason"]
    assert pool["strings"] == []


def test_wrong_marker_yields_unknown():
    payload = build_dat_payload(body_options={"unlock": 7})
    pool = _read(payload)
    assert pool["status"] == "UNKNOWN"
    assert "unexpected marker values" in pool["reason"]


def test_oversized_string_count_is_rejected():
    payload = build_dat_payload(body_options={"declared_count": 9999})
    pool = _read(payload)
    assert pool["status"] in ("UNKNOWN", "UNREADABLE")
    assert pool["strings"] == [] or pool["count"] < 9999


def test_truncated_string_is_reported_as_unreadable():
    payload = build_dat_payload(body_options={"truncate_last_string": True})
    pool = _read(payload)
    assert pool["status"] == "UNREADABLE"
    assert "runs past the buffer" in pool["reason"]


def test_bad_string_length_is_reported_as_unreadable():
    payload = build_dat_payload(body_options={"bad_string_length": True})
    pool = _read(payload)
    assert pool["status"] == "UNREADABLE"


def test_body_beyond_buffer_yields_unknown():
    """Wenn der Body-Kopf gar nicht existiert: UNKNOWN, kein Absturz."""
    payload = build_dat_payload(body=b"")
    pool = _read(payload)
    assert pool["status"] == "UNKNOWN"
    assert "beyond buffer" in pool["reason"]


def test_function_is_independent_of_header_parsing_state():
    """read_string_pool arbeitet nur auf Puffer + Header + PluginInfo."""
    provider = SfsDecodeProvider()
    payload = build_dat_payload()
    header = provider.parse_dat_header(payload)
    info = provider.parse_plugin_info(payload, header)
    # Absichtlich eine gefaelschte PluginInfo mit block_end = Header-Ende:
    # die Funktion muss den uebergebenen Blockanfang respektieren.
    assert provider.read_string_pool(payload, header, info)["status"] == "OK"
    info.block_end = 0
    pool = provider.read_string_pool(payload, header, info)
    # block_end == 0 -> Rueckfall auf plugin_info_offset + plugin_info_size
    assert pool["block_start"] == header.plugin_info_offset + header.plugin_info_size
    assert pool["status"] == "OK"


def test_read_only_no_file_is_written(tmp_path):
    """Die Funktion schreibt nichts: Dateigroesse und mtime bleiben gleich."""
    path = tmp_path / "readonly.sfs"
    path.write_bytes(build_synthetic_sfs(build_dat_payload()))
    before = (path.stat().st_size, path.stat().st_mtime_ns,
              path.read_bytes())
    provider = SfsDecodeProvider()
    payload = provider.decompress(str(path))
    header = provider.parse_dat_header(payload)
    info = provider.parse_plugin_info(payload, header)
    provider.read_string_pool(payload, header, info)
    after = (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
    assert before == after
