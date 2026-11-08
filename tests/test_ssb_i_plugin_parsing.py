"""Regressionstests fuer den Plugin-Parser in ssb_i/savegame_provider.py.

FORMATGESCHICHTE
  04.11.2026 — Der alte Parser las nach jedem Namen sofort wieder ``u16 len``.
  Weil jeder echte Record einen variablen Metadatenblock traegt,
  desynchronisierte er ab dem zweiten Plugin und lieferte 3.329
  "Light-Plugins" — davon genau ein plausibler Name. Die damalige Korrektur
  suchte den naechsten plausiblen Namen (Resync-Heuristik).

  08.11.2026 — Das Metadatenformat wurde erschlossen (Referenz:
  Nexus-Mods/StarfieldSaveTool, ``DatFile.cs`` + ``SFS-decompressed.bt``,
  gegen 6 reale Saves bis zum bytegenauen Blockende verifiziert):
      u16 len + Name
      u8  extraInfo           # 0 = Game-Plugin, 1 = Mod-Plugin
      if extraInfo == 1:
          u16 len + creationName
          u16 len + creationId
          u16 len + flags     # in der Praxis eine ASCII-Version
          u8  achievementFriendly
  Die Heuristik ist damit ersetzt: es wird strikt gelesen, nicht geraten.
  Zusaetzlich wurde die Medium-Kette ergaenzt — sie fehlte vollstaendig, was
  die Produktausgabe um fuenf Plugins zu klein machte.

  Diese Tests bauen das belegte Format synthetisch nach und brauchen kein
  echtes Save. Die realen Saves prueft ``test_ssb_i_real_saves.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import (build_dat_payload, build_plugin_block, plugin_record)
from ssb_i.savegame_provider import DatHeader, SfsDecodeProvider


def _header(offset: int, size: int = 0) -> DatHeader:
    return DatHeader(
        header_size=124, engine_version=0, save_version=153, save_number=1,
        player_name="Test", player_level=1, player_location="",
        playtime="", race_name="", gender=0, experience=0.0,
        experience_required=1.0, filetime=0, save_version_2=153,
        current_game_version="1.16.244.0", created_game_version="1.16.244.0",
        plugin_info_offset=offset, plugin_info_size=size,
    )


def _parse(payload: bytes):
    provider = SfsDecodeProvider()
    return provider.parse_plugin_info(payload, provider.parse_dat_header(payload))


class TestPluginChains:
    def test_reads_normal_light_and_medium(self):
        payload = build_dat_payload(
            normal=[plugin_record("Starfield.esm"),
                    plugin_record("SFSE.esm", category="mod")],
            light=[plugin_record("SFBGS004.esl"), plugin_record("X.esl")],
            medium=[plugin_record("SFBGS003.esm"),
                    plugin_record("PersonalSpacestation.esm")],
        )
        info = _parse(payload)
        assert info.decode_state == "VALIDATED", info.note
        assert [p.name for p in info.normal] == ["Starfield.esm", "SFSE.esm"]
        assert [p.name for p in info.light] == ["SFBGS004.esl", "X.esl"]
        assert [p.name for p in info.medium] == ["SFBGS003.esm",
                                                 "PersonalSpacestation.esm"]
        assert info.total == 6

    def test_medium_chain_is_not_dropped(self):
        """Regression: die Medium-Kette wurde nach der Light-Kette nie gelesen."""
        payload = build_dat_payload(
            medium=[plugin_record("SFBGS003.esm"),
                    plugin_record("SFBGS006.esm"),
                    plugin_record("PersonalSpacestation.esm")],
        )
        info = _parse(payload)
        assert len(info.medium) == 3
        assert info.total == len(info.normal) + len(info.light) + 3

    def test_block_ends_exactly_at_declared_size(self):
        payload = build_dat_payload()
        info = _parse(payload)
        assert info.block_delta == 0
        assert info.block_end == info.block_end_declared

    def test_native_plugin_is_flagged(self):
        info = _parse(build_dat_payload(normal=[plugin_record("Starfield.esm")],
                                        light=[plugin_record("X.esl")]))
        assert info.normal[0].is_native is True
        assert info.light[0].is_native is False

    def test_empty_light_chain_is_accepted_when_consistent(self):
        """count == 0 ist eine gueltige leere Kette (strikte Lesart).

        Frueher galt hier 'fail closed', weil die Resync-Heuristik jeden
        Nullbyte als Treffer gewertet haette. Mit strikter Dekodierung ist eine
        leere Kette eindeutig und wird akzeptiert.
        """
        payload = build_dat_payload(light=[])
        info = _parse(payload)
        assert info.decode_state == "VALIDATED", info.note
        assert info.light == []
        assert info.declared_light == 0

    def test_declared_count_mismatch_is_unverified(self):
        """Stimmt der Zaehler nicht, wird NICHTS als Plugin-Liste ausgegeben."""
        payload = build_dat_payload(normal_count=5)
        info = _parse(payload)
        assert info.decode_state == "UNVERIFIED"
        assert info.normal == []
        assert info.light == []
        assert info.medium == []
        assert info.total == 0

    def test_implausible_light_count_is_unverified(self):
        payload = build_dat_payload(light_count=9999)
        info = _parse(payload)
        assert info.decode_state == "UNVERIFIED"
        assert "light plugin count" in info.note

    def test_garbage_never_becomes_a_plugin_list(self):
        """Regression: 0x00-Rechteck darf keine erfundene Liste erzeugen."""
        header = bytearray(b"SFS_SAVEGAME" + b"\x00" * 4 + b"\x00" * 12)
        header += b"\x00\x00\x01" + b"\xff" * 4096
        info = SfsDecodeProvider().parse_plugin_info(bytes(header), _header(0))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0

    def test_offset_outside_file_is_unverified(self):
        info = SfsDecodeProvider().parse_plugin_info(b"short", _header(0x1000))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0


class TestPluginMetadata:
    def test_game_plugin_has_no_metadata(self):
        info = _parse(build_dat_payload(normal=[plugin_record("Starfield.esm")]))
        entry = info.normal[0]
        assert entry.category == "game"
        assert entry.metadata_state == "absent"
        assert entry.creation_id is None

    def test_mod_without_creation_data_is_absent(self):
        info = _parse(build_dat_payload(normal=[plugin_record("Plain.esm",
                                                              category="mod")]))
        entry = info.normal[0]
        assert entry.category == "mod"
        assert entry.metadata_state == "absent"
        assert entry.creation_name is None
        assert entry.creation_id is None

    def test_full_creation_metadata_is_decoded(self):
        info = _parse(build_dat_payload(normal=[plugin_record(
            "Mod.esm", category="mod", creation_name="Darker Space",
            creation_id="TM_60a24112-d7ce-416b-ab44-fec0184d978e",
            version="1730975455.1.01", achievement=1)]))
        entry = info.normal[0]
        assert entry.metadata_state == "present"
        assert entry.creation_name == "Darker Space"
        assert entry.creation_id == "TM_60a24112-d7ce-416b-ab44-fec0184d978e"
        assert entry.version == "1730975455.1.01"
        assert entry.achievement_friendly is True

    def test_engine_placeholder_is_normalised_to_none(self):
        """18446744073709551615.undefined ist keine Creation-ID."""
        placeholder = SfsDecodeProvider.PLACEHOLDER_ID
        info = _parse(build_dat_payload(normal=[plugin_record(
            "NoMeta.esm", category="mod", creation_name="",
            creation_id=placeholder, version=placeholder)]))
        entry = info.normal[0]
        assert entry.creation_id is None
        assert entry.metadata_state == "absent"
        assert "placeholder" in entry.detail

    def test_metadata_is_not_taken_from_neighbour(self):
        """Zwei Records: der zweite ohne Metadaten darf nichts erben."""
        info = _parse(build_dat_payload(normal=[
            plugin_record("WithMeta.esm", category="mod",
                          creation_name="Has Name",
                          creation_id="TM_aaa", version="1.0"),
            plugin_record("Bare.esm", category="mod"),
        ]))
        assert info.normal[0].creation_name == "Has Name"
        assert info.normal[1].creation_name is None
        assert info.normal[1].creation_id is None
        assert info.normal[1].metadata_state == "absent"

    def test_truncated_metadata_marks_unreadable(self):
        """Abgeschnittene Metadaten: 'unreadable', keine Uebernahme."""
        provider = SfsDecodeProvider()
        payload = bytearray(build_dat_payload(normal=[plugin_record(
            "Broken.esm", category="mod", creation_name="X",
            creation_id="TM_x", version="1.0")], body=b"\x00" * 32))
        header = provider.parse_dat_header(bytes(payload))
        block_end = header.plugin_info_offset + header.plugin_info_size
        damaged = bytes(payload[:block_end - 5])
        info = provider.parse_plugin_info(damaged,
                                          _header(header.plugin_info_offset,
                                                  len(damaged) - header.plugin_info_offset))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0
        assert "truncated" in info.note or "runs past" in info.note


class TestPluginInfoPayload:
    def test_to_dict_exposes_counts_categories_and_block(self):
        payload = build_dat_payload(
            normal=[plugin_record("Starfield.esm"),
                    plugin_record("Mod.esm", category="mod",
                                  creation_name="N", creation_id="TM_1",
                                  version="1.0")],
            light=[plugin_record("SFBGS004.esl")],
            medium=[plugin_record("SFBGS003.esm")],
        )
        data = _parse(payload).to_dict()
        assert data["decode_state"] == "VALIDATED"
        assert data["counts"] == {"normal": 2, "light": 1, "medium": 1, "total": 4}
        # game: Starfield.esm + SFBGS004.esl + SFBGS003.esm = 3
        # mod : Mod.esm (mit Creation-Metadaten)               = 1
        assert data["categories"] == {"game": 3, "mod": 1}
        assert data["metadata"] == {"present": 1, "unreadable": 0}
        assert data["block"]["delta"] == 0
        assert data["note"]

    def test_legacy_json_fields_still_present(self):
        """``save info --json`` nutzt Zahlen je Kette — nicht die Eintragslisten."""
        payload = build_dat_payload()
        provider = SfsDecodeProvider()
        header = provider.parse_dat_header(payload)
        info = provider.parse_plugin_info(payload, header)
        assert len(info.normal) == 2      # Starfield.esm + SFSE.esm (Default)
        assert len(info.light) == 1
        assert len(info.medium) == 1
        # Die Listen bleiben Listen; die Zahlen liefert die CLI selbst.
        assert isinstance(info.normal, list)
