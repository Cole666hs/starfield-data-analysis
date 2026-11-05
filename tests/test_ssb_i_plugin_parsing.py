"""Regressionstests fuer den Plugin-Parser in ssb_i/savegame_provider.py.

HINTERGRUND (04.11.2026)
  Der alte Parser las nach jedem Namen sofort wieder ``u16 len``. Weil jeder
  echte Record nach dem Namen einen variablen Metadatenblock traegt,
  desynchronisierte er ab dem zweiten Plugin und lieferte in der Oberflaeche
  3.329 "Light-Plugins" — davon genau ein plausibler Name. Aufgefallen ist das
  erst beim Fahren der Oberflaeche mit einem echten Save, weil alle Tests mit
  echten Saves uebersprungen wurden.

  Diese Tests brauchen KEIN echtes Save: sie bauen den belegten Rahmen
  synthetisch nach und pruefen die Grenzen. Zusaetzlich laeuft ein Test gegen
  echte Saves, wenn sie vorhanden sind.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ssb_i.savegame_provider import DatHeader, SfsDecodeProvider  # noqa: E402


def _header(offset: int) -> DatHeader:
    return DatHeader(
        header_size=124, engine_version=0, save_version=153, save_number=1,
        player_name="Test", player_level=1, player_location="",
        playtime="", race_name="", gender=0, experience=0.0,
        experience_required=1.0, filetime=0, save_version_2=153,
        current_game_version="1.16.244.0", created_game_version="1.16.244.0",
        plugin_info_offset=offset, plugin_info_size=0,
    )


def _record(name: str, meta: bytes = b"") -> bytes:
    raw = name.encode("ascii")
    return struct.pack("<H", len(raw)) + raw + meta


def build_save(*, normal: list[str], normal_meta: bytes = b"\x01\x00\x00\x00\x00",
               light: list[str], light_meta: bytes = b"\x00",
               normal_count: int | None = None) -> tuple[bytes, int]:
    """Baut einen Save-Header-Bereich mit belegtem Plugin-Record-Rahmen."""
    offset = 0x20
    body = bytearray(b"\x00" * offset)
    body += b"\x00\x00"
    body.append(len(normal) if normal_count is None else normal_count)
    for name in normal:
        body += _record(name, normal_meta)
    body += struct.pack("<H", len(light))
    for name in light:
        body += _record(name, light_meta)
    body += struct.pack("<I", 0)  # medium count
    body += b"\x00" * 32
    return bytes(body), offset


class TestPluginParsing:
    def test_reads_normal_and_light_plugins(self):
        data, off = build_save(
            normal=["Starfield.esm", "SFSE.esm", "BlueprintShips-Starfield.esm"],
            light=["SFBGS003.esl", "SFBGS004.esl", "OutpostShipbuilderUnlocked.esl"],
        )
        info = SfsDecodeProvider().parse_plugin_info(data, _header(off))
        assert info.decode_state == "VALIDATED", info.note
        assert [p.name for p in info.normal] == [
            "Starfield.esm", "SFSE.esm", "BlueprintShips-Starfield.esm"]
        assert [p.name for p in info.light] == [
            "SFBGS003.esl", "SFBGS004.esl", "OutpostShipbuilderUnlocked.esl"]
        assert info.total == 6

    def test_native_plugin_is_flagged(self):
        data, off = build_save(normal=["Starfield.esm"], light=["X.esl"])
        info = SfsDecodeProvider().parse_plugin_info(data, _header(off))
        assert info.decode_state == "VALIDATED"
        assert info.normal[0].is_native is True

    def test_variable_metadata_length_per_record(self):
        """Der Metadatenblock ist je Record unterschiedlich lang."""
        data, off = build_save(normal=[], light=["Z.esl"])
        body = bytearray(data[:off])
        body += b"\x00\x00\x03"
        body += _record("A.esm", b"\x01\x15\x00" + b"x" * 21 + b"\x00")
        body += _record("B.esm", b"\x01\x00\x00\x00\x00\x03\x00abc\x00")
        body += _record("C.esm", b"")
        body += struct.pack("<H", 1) + _record("Z.esl", b"\x00")
        body += struct.pack("<I", 0) + b"\x00" * 32
        info = SfsDecodeProvider().parse_plugin_info(bytes(body), _header(off))
        assert info.decode_state == "VALIDATED", info.note
        assert [p.name for p in info.normal] == ["A.esm", "B.esm", "C.esm"]

    def test_empty_light_block_fails_closed(self):
        """count == 0 wird nicht als Kette akzeptiert (sonst waere jedes
        Nullbyte eine gueltige leere Liste). Fail-closed statt Raten."""
        data, off = build_save(normal=["Starfield.esm"], light=[])
        info = SfsDecodeProvider().parse_plugin_info(data, _header(off))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0

    def test_declared_count_mismatch_is_unverified(self):
        """Stimmt die Anzahl nicht, wird NICHTS als Plugin-Liste ausgegeben."""
        data, off = build_save(normal=["A.esm", "B.esm"], light=[], normal_count=5)
        info = SfsDecodeProvider().parse_plugin_info(data, _header(off))
        assert info.decode_state == "UNVERIFIED"
        assert info.normal == []
        assert info.light == []
        assert "5" in info.note

    def test_garbage_never_becomes_a_plugin_list(self):
        """Regression: 0x00-Rechteck darf nicht 3.329 Light-Plugins erzeugen."""
        data, off = build_save(normal=[], light=[])
        body = bytearray(data[:off]) + bytearray(b"\x00\x00\x01") + bytearray(b"\xff" * 4096)
        info = SfsDecodeProvider().parse_plugin_info(bytes(body), _header(off))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0

    def test_offset_outside_file_is_unverified(self):
        info = SfsDecodeProvider().parse_plugin_info(b"short", _header(0x1000))
        assert info.decode_state == "UNVERIFIED"
        assert info.total == 0

    def test_to_dict_exposes_decode_state(self):
        data, off = build_save(normal=["Starfield.esm"], light=["X.esl"])
        payload = SfsDecodeProvider().parse_plugin_info(data, _header(off)).to_dict()
        assert payload["decode_state"] == "VALIDATED"
        assert payload["counts"] == {"normal": 1, "light": 1, "medium": 0}
        assert payload["note"]


REAL_SAVES = [
    Path("/tmp/ssbi_demo/Save41.sfs"),
    Path("/tmp/ssbi_demo/Save42.sfs"),
    Path("/tmp/ssbi_demo/Save43.sfs"),
]


@pytest.mark.parametrize("path", REAL_SAVES, ids=lambda p: p.name)
def test_real_save_plugin_list_is_validated(path: Path):
    """Echter Save: 24 normale + 50 Light-Plugins, unveraenderlich seit 04.11."""
    if not path.is_file():
        pytest.skip("echtes Save nicht vorhanden: %s" % path)
    provider = SfsDecodeProvider()
    decompressed = provider.decompress(str(path))
    header = provider.parse_dat_header(decompressed)
    info = provider.parse_plugin_info(decompressed, header)
    assert info.decode_state == "VALIDATED", info.note
    assert len(info.normal) == 24
    assert info.normal[0].name == "Starfield.esm"
    assert len(info.light) == 50
    names = [p.name for p in info.normal + info.light]
    assert all(any(n.lower().endswith(e) for e in (".esm", ".esl", ".esp"))
               for n in names)
