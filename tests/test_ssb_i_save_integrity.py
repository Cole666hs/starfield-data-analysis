"""Integritaetspruefung: Statusmodell und synthetische Negativfaelle.

Jede PASS-Regel hat hier mindestens einen Negativtest. Die Faelle E/F/G sind die
drei, die vor diesem Auftrag still durchliefen (Befund 08.11.2026).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import (build_dat_payload, build_synthetic_sfs, plugin_record,
                      write_save)
from ssb_i.save_integrity import (FAILED, NOT_CHECKED, PASS, UNKNOWN, WARNING,
                                 run_all)


def _statuses(path: Path) -> dict[str, str]:
    return run_all(path).statuses


# ---------------------------------------------------------------------------
# Basisverhalten
# ---------------------------------------------------------------------------
def test_intact_synthetic_save_assesses_cleanly(synthetic_save: Path):
    """Ein formatkonformer Save liefert PASS auf allen strukturellen Pruefungen."""
    report = run_all(synthetic_save)
    assert report.total in (PASS, WARNING), report.to_dict()["checks"]
    structural = ("I-01", "I-02", "I-04", "I-05", "I-06", "I-07",
                  "I-08", "I-10", "I-11")
    for check_id in structural:
        assert report.statuses[check_id] == PASS, (check_id, report.by_id(check_id))
    # I-03 darf WARNING sein: der Test-Container richtet die Tabelle auf das
    # Padding-Raster aus, wodurch ein Alignment-Rest entsteht (wie bei realen
    # Saves mit 12 Fuellbytes vor dem Datenstrom).
    assert report.statuses["I-03"] in (PASS, WARNING)
    assert report.statuses["I-09"] == UNKNOWN


def test_report_exposes_gaps_separately(synthetic_save: Path):
    """UNKNOWN/NOT_CHECKED dominieren das Urteil nicht, verschwinden aber nicht."""
    report = run_all(synthetic_save)
    assert report.total in (PASS, WARNING)
    assert report.statuses["I-12"] == NOT_CHECKED      # kein --data-dir
    assert report.statuses["I-13"] == NOT_CHECKED      # FormID dauerhaft offen
    assert report.statuses["I-14"] == NOT_CHECKED      # keine Sequenz
    assert {g.check_id for g in report.gaps} == {"I-09", "I-12", "I-13", "I-14"}
    assert report.coverage["assessed"] == 10
    assert report.coverage["total"] == 14


def test_disclaimer_present(synthetic_save: Path):
    assert "NICHT, dass Starfield den Spielstand laden kann" in run_all(synthetic_save).disclaimer


def test_unknown_is_not_converted_to_pass(synthetic_save: Path):
    """I-09 bleibt UNKNOWN — niemals PASS, solange die Semantik fehlt."""
    assert _statuses(synthetic_save)["I-09"] == UNKNOWN


# ---------------------------------------------------------------------------
# Fall E — manipuliertes Groessenfeld (vorher still)
# ---------------------------------------------------------------------------
def test_case_e_declared_size_plus_one_fails(tmp_path):
    payload = build_dat_payload()
    path = tmp_path / "case_e.sfs"
    path.write_bytes(build_synthetic_sfs(payload, declared_size=len(payload) + 1))
    statuses = _statuses(path)
    assert statuses["I-06"] == FAILED
    assert run_all(path).total == FAILED


# ---------------------------------------------------------------------------
# Fall F — verdoppeltes chunk_size_pre (vorher still, 50 % Datenverlust)
# ---------------------------------------------------------------------------
def test_case_f_chunk_pre_doubled_fails(tmp_path):
    """chunk_size_pre nachtraeglich verdoppelt: die Tabelle passt nicht mehr."""
    payload = build_dat_payload()
    data = bytearray(build_synthetic_sfs(payload, chunk_size_pre=128))
    pre, = struct.unpack_from("<q", data, 48)
    struct.pack_into("<q", data, 48, pre * 2)          # doppeltes Raster
    path = tmp_path / "case_f.sfs"
    path.write_bytes(bytes(data))
    statuses = _statuses(path)
    assert statuses["I-04"] == FAILED
    assert statuses["I-06"] == FAILED
    assert run_all(path).total == FAILED


def test_decompress_without_verify_returns_short_payload(tmp_path):
    """Belegt den stillen Fehler selbst: ohne Pruefung kommt zu wenig an."""
    from ssb_i.savegame_provider import SfsDecodeProvider
    payload = build_dat_payload()
    data = bytearray(build_synthetic_sfs(payload, chunk_size_pre=128))
    pre, = struct.unpack_from("<q", data, 48)
    struct.pack_into("<q", data, 48, pre * 2)
    path = tmp_path / "short.sfs"
    path.write_bytes(bytes(data))
    provider = SfsDecodeProvider()
    short = provider.decompress(str(path), verify=False)
    assert len(short) < len(payload)
    with pytest.raises(ValueError, match="does not match declared uncompressed_size"):
        provider.decompress(str(path))


# ---------------------------------------------------------------------------
# Fall G — Bytes hinter dem zlib-Strom (vorher folgenlos akzeptiert)
# ---------------------------------------------------------------------------
def test_case_g_trailing_bytes_warn_not_fail(tmp_path):
    payload = build_dat_payload()
    path = tmp_path / "case_g.sfs"
    path.write_bytes(build_synthetic_sfs(payload, trailing_per_chunk=b"\x00\x00\x00\x00"))
    report = run_all(path)
    assert report.statuses["I-05"] == WARNING
    assert report.statuses["I-05"] != FAILED       # kein Nachweis einer Beschaedigung
    assert report.statuses["I-05"] != PASS         # darf nicht ungeprueft durchgehen
    detail = report.by_id("I-05")
    assert detail is not None
    assert detail.confidence == "unverified"
    assert detail.evidence["trailing_bytes"] > 0


# ---------------------------------------------------------------------------
# Container-Manipulationen
# ---------------------------------------------------------------------------
def test_bad_magic_blocks_all_following_checks(tmp_path):
    payload = build_dat_payload()
    path = tmp_path / "bad_magic.sfs"
    path.write_bytes(build_synthetic_sfs(payload, magic=b"XXXX"))
    statuses = _statuses(path)
    assert statuses["I-01"] == FAILED
    for check_id in ("I-03", "I-04", "I-05", "I-06", "I-11"):
        assert statuses[check_id] == NOT_CHECKED


def test_unknown_compression_fails(tmp_path):
    payload = build_dat_payload()
    path = tmp_path / "lz4.sfs"
    path.write_bytes(build_synthetic_sfs(payload, compression=b"LZ4 "))
    assert _statuses(path)["I-02"] == FAILED


def test_truncated_file_fails_padding_sum(tmp_path, synthetic_save):
    data = synthetic_save.read_bytes()
    path = tmp_path / "trunc.sfs"
    path.write_bytes(data[:-100])
    statuses = _statuses(path)
    assert statuses["I-04"] == FAILED
    assert run_all(path).total == FAILED


def test_chunk_table_behind_data_stream_fails(tmp_path):
    """Fall M — compressed_offset verschoben: Tabelle ragt in den Datenstrom."""
    payload = build_dat_payload()
    data = bytearray(build_synthetic_sfs(payload))
    compressed_offset, = struct.unpack_from("<q", data, 24)
    struct.pack_into("<q", data, 24, compressed_offset - 64)
    path = tmp_path / "moved.sfs"
    path.write_bytes(bytes(data))
    assert _statuses(path)["I-03"] == FAILED


def test_padding_zero_is_detected(tmp_path):
    payload = build_dat_payload()
    data = bytearray(build_synthetic_sfs(payload))
    struct.pack_into("<q", data, 56, 0)
    path = tmp_path / "pad0.sfs"
    path.write_bytes(bytes(data))
    statuses = _statuses(path)
    assert FAILED in (statuses["I-03"], statuses["I-04"], statuses["I-05"])


# ---------------------------------------------------------------------------
# Header-Manipulationen (I-08)
# ---------------------------------------------------------------------------
def test_broken_dat_magic_fails_header_check(tmp_path):
    payload = build_dat_payload()
    damaged = b"NOT_A_SAVE__" + payload[12:]
    path = tmp_path / "datmagic.sfs"
    path.write_bytes(build_synthetic_sfs(damaged))
    assert _statuses(path)["I-08"] == FAILED


def test_impossible_string_length_fails_header_check(tmp_path):
    payload = bytearray(build_dat_payload())
    # Position des playerLocation-Laengenfelds aus dem Puffer ableiten
    name_len, = struct.unpack_from("<H", payload, 0x19)
    location_length_offset = 0x19 + 2 + name_len + 4      # + playerLevel
    struct.pack_into("<H", payload, location_length_offset, 4000)
    path = tmp_path / "badlen.sfs"
    path.write_bytes(build_synthetic_sfs(bytes(payload)))
    assert _statuses(path)["I-08"] == FAILED


# ---------------------------------------------------------------------------
# Plugin-Ketten und Metadaten (I-10 / I-11)
# ---------------------------------------------------------------------------
def test_medium_chain_is_read_and_counted(tmp_path):
    """Regression zum Produktfehler: medium wurde immer 0 gemeldet."""
    medium = [plugin_record("SFBGS003.esm", category="game"),
              plugin_record("PersonalSpacestation.esm", category="mod")]
    payload = build_dat_payload(medium=medium)
    path = tmp_path / "medium.sfs"
    path.write_bytes(build_synthetic_sfs(payload))
    from ssb_i.savegame_provider import SfsDecodeProvider
    provider = SfsDecodeProvider()
    raw = provider.decompress(str(path))
    info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
    assert len(info.medium) == 2
    assert info.total == len(info.normal) + len(info.light) + 2
    assert info.block_delta == 0


def test_declared_medium_count_mismatch_is_unverified(tmp_path):
    """Stimmt der Medium-Zaehler nicht, wird nichts als Liste ausgegeben."""
    payload = build_dat_payload(medium_count=7)
    path = tmp_path / "badmedium.sfs"
    path.write_bytes(build_synthetic_sfs(payload))
    statuses = _statuses(path)
    assert statuses["I-11"] == WARNING


def test_truncated_plugin_metadata_is_marked_unreadable(tmp_path):
    """Metadaten laufen aus dem Payload -> Kette bricht ab, keine Uebernahme."""
    from ssb_i.savegame_provider import SfsDecodeProvider
    record = plugin_record("Broken.esm", category="mod",
                           creation_name="X", creation_id="TM_x", version="1.0")
    payload = bytearray(build_dat_payload(normal=[record], body=b"\x00" * 32))
    # Header lesen, um den Plugin-Block gezielt anzuschneiden
    provider = SfsDecodeProvider()
    header = provider.parse_dat_header(bytes(payload))
    block_end = header.plugin_info_offset + header.plugin_info_size
    damaged = bytes(payload[:block_end - 5])
    path = tmp_path / "truncmeta.sfs"
    path.write_bytes(build_synthetic_sfs(damaged))
    statuses = _statuses(path)
    assert statuses["I-11"] in (WARNING, NOT_CHECKED)
    assert statuses["I-11"] != PASS


def test_plugin_block_outside_payload_fails_i10(tmp_path):
    payload = build_dat_payload(plugin_info_size_override=0x7FFF)
    path = tmp_path / "bigblock.sfs"
    path.write_bytes(build_synthetic_sfs(payload))
    statuses = _statuses(path)
    assert statuses["I-10"] in (FAILED, WARNING)


def test_engine_placeholder_is_not_a_creation_id():
    """Der Engine-Platzhalter darf nie als echte Creation-ID erscheinen."""
    from ssb_i.savegame_provider import SfsDecodeProvider
    provider = SfsDecodeProvider()
    PLACEHOLDER_ID = SfsDecodeProvider.PLACEHOLDER_ID
    record = plugin_record("NoMeta.esm", category="mod",
                           creation_name="", creation_id=PLACEHOLDER_ID,
                           version=PLACEHOLDER_ID)
    payload = build_dat_payload(normal=[plugin_record("Starfield.esm"),
                                       record])
    raw = payload
    info = provider.parse_plugin_info(raw, provider.parse_dat_header(raw))
                                             # Offset liegt im Test-Payload
    entry = next(e for e in info.normal if e.name == "NoMeta.esm")
    assert entry.creation_id is None
    assert entry.metadata_state == "absent"
    assert "placeholder" in entry.detail


def test_real_creation_metadata_is_decoded():
    from ssb_i.savegame_provider import SfsDecodeProvider
    provider = SfsDecodeProvider()
    record = plugin_record("Mod.esm", category="mod",
                           creation_name="Darker Space",
                           creation_id="TM_60a24112-d7ce-416b-ab44-fec0184d978e",
                           version="1730975455.1.01", achievement=1)
    payload = build_dat_payload(normal=[plugin_record("Starfield.esm"), record])
    info = provider.parse_plugin_info(payload, provider.parse_dat_header(payload))
    entry = next(e for e in info.normal if e.name == "Mod.esm")
    assert entry.metadata_state == "present"
    assert entry.creation_name == "Darker Space"
    assert entry.creation_id == "TM_60a24112-d7ce-416b-ab44-fec0184d978e"
    assert entry.version == "1730975455.1.01"
    assert entry.achievement_friendly is True
    assert entry.category == "mod"


def test_game_plugin_has_no_metadata():
    from ssb_i.savegame_provider import SfsDecodeProvider
    provider = SfsDecodeProvider()
    payload = build_dat_payload()
    info = provider.parse_plugin_info(payload, provider.parse_dat_header(payload))
    game = next(e for e in info.normal if e.name == "Starfield.esm")
    assert game.category == "game"
    assert game.metadata_state == "absent"
    assert game.creation_id is None


# ---------------------------------------------------------------------------
# Abhaengigkeitspruefung I-12
# ---------------------------------------------------------------------------
def test_i12_skipped_without_data_dir(synthetic_save: Path):
    assert _statuses(synthetic_save)["I-12"] == NOT_CHECKED


def test_i12_reports_missing_plugins(tmp_path, synthetic_save):
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    (data_dir / "Starfield.esm").write_bytes(b"")
    report = run_all(synthetic_save, data_dir=data_dir)
    assert report.statuses["I-12"] == WARNING
    i12 = report.by_id("I-12")
    assert i12 is not None
    evidence = i12.evidence
    assert evidence["missing_count"] >= 1
    assert "SFSE.esm" in evidence["missing"]
    assert _statuses(synthetic_save)["I-12"] == NOT_CHECKED   # ohne --data-dir


def test_i12_passes_when_all_plugins_present(tmp_path, synthetic_save):
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    for name in ("Starfield.esm", "SFSE.esm", "SFBGS004.esl", "SFBGS003.esm"):
        (data_dir / name).write_bytes(b"")
    assert run_all(synthetic_save, data_dir=data_dir).statuses["I-12"] == PASS


# ---------------------------------------------------------------------------
# Sequenzkonsistenz I-14
# ---------------------------------------------------------------------------
def test_i14_not_checked_without_sequence(synthetic_save: Path):
    assert _statuses(synthetic_save)["I-14"] == NOT_CHECKED


def test_i14_detects_level_regression(synthetic_save: Path):
    import dataclasses

    from ssb_i.save_integrity import build_context
    header = build_context(synthetic_save).header
    assert header is not None
    earlier = dataclasses.replace(header, player_level=40, filetime=1)
    later = dataclasses.replace(header, player_level=10, filetime=2)
    report = run_all(synthetic_save, sequence=(earlier, later))
    assert report.statuses["I-14"] == WARNING
    i14 = report.by_id("I-14")
    assert i14 is not None and "Level" in i14.detail
