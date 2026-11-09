"""Gemeinsame Testinfrastruktur fuer SSB-I.

Zwei Dinge, die die bisherige Suite nicht hatte:

1. **Reale Saves sind Fixtures, keine Option.** Pfad ueber ``SAVE_PROBES``
   (Default ``~/ssb_probes``). Fehlt das Verzeichnis, schlagen die realen Tests
   FEHL statt still uebersprungen zu werden — nur mit ausdruecklichem
   ``SSB_ALLOW_MISSING_SAVES=1`` wird uebersprungen (z. B. in einer CI ohne
   Spieldaten). Grund: eine gruene Suite ohne einen einzigen echten Spielstand
   hat 2026-11 genau die Fehler verdeckt, die dieser Auftrag behebt.

2. **Synthetische Saves im belegten Format.** ``build_dat_payload()`` erzeugt
   Header + Plugin-Block (normal/light/medium, mit und ohne Metadaten),
   ``build_body_head()`` den Body-Kopf mit Pointer-Tabelle und String-Array.
   Damit lassen sich alle Pruefungen falsifizieren, ohne 23-MB-Fixtures.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Konfiguration realer Saves
# ---------------------------------------------------------------------------
SAVE_PROBES = Path(os.environ.get("SAVE_PROBES", Path.home() / "ssb_probes"))
ALLOW_MISSING = os.environ.get("SSB_ALLOW_MISSING_SAVES") == "1"

#: Golden-Werte der Messbasis (Save-Version 153, Engine 27, Starfield 1.16.244.0).
GOLDEN = {
    "save_version": 153,
    "engine_version": 27,
    "chunk_size_pre": 262144,
    "padding_size": 16,
    "plugins": {"normal": 25, "light": 50, "medium": 5, "total": 80},
    "categories": {"game": 9, "mod": 71},
    "metadata_present": 6,
    "save_count": 6,
}


def find_real_saves() -> list[Path]:
    """Alle echten Starfield-Saves unter SAVE_PROBES (ohne ssbm_*-Kopien)."""
    found: list[Path] = []
    for root in (SAVE_PROBES / "saves_07oct_2026", SAVE_PROBES):
        if root.is_dir():
            found += [root / name for name in sorted(os.listdir(root))
                      if name.endswith(".sfs")
                      and name.startswith(("Save", "Auto", "Exit"))]
    # Duplikate vermeiden, falls beide Verzeichnisse existieren
    unique: dict[str, Path] = {}
    for path in found:
        unique.setdefault(path.name, path)
    return list(unique.values())


@pytest.fixture(scope="session")
def real_saves() -> list[Path]:
    """Pflicht-Fixture fuer reale Saves. Fehlt sie, ist das ein Testfehler."""
    saves = find_real_saves()
    if not saves:
        message = ("keine realen Saves unter %s gefunden — Fixture ueber "
                   "SAVE_PROBES setzen oder SSB_ALLOW_MISSING_SAVES=1 fuer einen "
                   "Lauf ohne Spieldaten" % SAVE_PROBES)
        if ALLOW_MISSING:
            pytest.skip(message)
        pytest.fail(message)
    return saves


@pytest.fixture(scope="session")
def provider():
    from ssb_i import get_provider
    return get_provider()


# ---------------------------------------------------------------------------
# Synthetischer BCPS-Container
# ---------------------------------------------------------------------------
#: Echter BCPS-Kopf endet bei Byte 72 (compression bei 68..71).
CONTAINER_HEADER_SIZE = 72


def build_synthetic_sfs(payload: bytes, *, chunk_size_pre: int = 256,
                        padding: int = 16, compression: bytes = b"ZIP ",
                        magic: bytes = b"BCPS",
                        declared_size: int | None = None,
                        chunk_size_override: list[int] | None = None,
                        trailing_per_chunk: bytes = b"") -> bytes:
    """Minimaler, formatkonformer BCPS-Container.

    ``declared_size`` ueberschreibt die deklarierte Nutzgroesse (Fall E).
    ``chunk_size_override`` ersetzt die Groessen in der Tabelle (Fall G).
    ``trailing_per_chunk`` haengt Bytes hinter jeden zlib-Strom (Fall G, echt).
    """
    chunks = [payload[i:i + chunk_size_pre] for i in range(0, len(payload), chunk_size_pre)] or [b""]
    compressed = [zlib.compress(chunk) + trailing_per_chunk for chunk in chunks]
    sizes = chunk_size_override if chunk_size_override is not None else [len(c) for c in compressed]

    chunk_count = len(compressed)
    chunk_sizes_offset = CONTAINER_HEADER_SIZE
    table = struct.pack("<%di" % chunk_count, *sizes)
    compressed_offset = chunk_sizes_offset + len(table)
    if padding and compressed_offset % padding:
        # Wie im echten Format: auf das Padding-Raster ausrichten. Die entstehende
        # Luecke fuellt I-03 mit Nullen und meldet sie als WARNING — genau das
        # Verhalten, das ein realer Save mit Alignment zeigt.
        compressed_offset = (compressed_offset + padding - 1) & ~(padding - 1)

    header = bytearray(CONTAINER_HEADER_SIZE)
    header[0:4] = magic
    struct.pack_into("<i", header, 4, 1)                       # version0
    struct.pack_into("<q", header, 8, chunk_sizes_offset)
    struct.pack_into("<q", header, 16, 0)                      # unknown0
    struct.pack_into("<q", header, 24, compressed_offset)
    struct.pack_into("<q", header, 32,
                     len(payload) if declared_size is None else declared_size)
    struct.pack_into("<f", header, 40, 2.0)                    # version1
    struct.pack_into("<i", header, 44, 0)                      # unknown1
    struct.pack_into("<q", header, 48, chunk_size_pre)
    struct.pack_into("<q", header, 56, padding)
    struct.pack_into("<i", header, 64, 0)                      # unknown2
    header[68:72] = compression

    body = bytearray(table)
    body += b"\x00" * (compressed_offset - chunk_sizes_offset - len(table))
    for blob, size in zip(compressed, sizes):
        body += blob[:size] if chunk_size_override is None else blob
        if padding:
            body += b"\x00" * ((-len(blob)) % padding)
    return bytes(header) + bytes(body)


# ---------------------------------------------------------------------------
# Synthetischer DAT-Payload (SFS_SAVEGAME + Plugin-Block + Body-Kopf)
# ---------------------------------------------------------------------------
def _qstring(text: str) -> bytes:
    raw = text.encode("ascii")
    return struct.pack("<H", len(raw)) + raw


def plugin_record(name: str, *, category: str = "game",
                  creation_name: str = "", creation_id: str = "",
                  version: str = "", achievement: int = 0) -> bytes:
    """Ein Plugin-Record im belegten Format."""
    out = _qstring(name)
    if category == "game":
        return out + b"\x00"
    out += b"\x01"
    out += _qstring(creation_name)
    out += _qstring(creation_id)
    out += _qstring(version)
    out += bytes([achievement])
    return out


def build_plugin_block(*, normal: list[bytes], light: list[bytes],
                       medium: list[bytes],
                       normal_count: int | None = None,
                       light_count: int | None = None,
                       medium_count: int | None = None) -> bytes:
    """Baut den Plugin-Block: Zaehler, dann die drei Ketten."""
    out = bytearray()
    out += b"\x00\x00"                                   # unknown0, count0
    out.append(len(normal) if normal_count is None else normal_count)
    for record in normal:
        out += record
    out += struct.pack("<H", len(light) if light_count is None else light_count)
    for record in light:
        out += record
    out += struct.pack("<I", len(medium) if medium_count is None else medium_count)
    for record in medium:
        out += record
    return bytes(out)


def build_body_head(strings: list[str], *, base: int = 0, unlock: int = 1,
                    pointer2_override: int | None = None,
                    declared_count: int | None = None,
                    truncate_last_string: bool = False,
                    bad_string_length: bool = False) -> bytes:
    """Body-Kopf: Pointer-Tabelle + NEW_BLOCK2 + String-Array.

    Layout (belegt, siehe savegame_provider.read_string_pool):
        u16 unlock, 12 x u32 pointer, 52 Byte Padding,
        u32 pointer0, u32 strings_offset, u32 unknown0,
        u16 count, count x (u16 len + utf8)
    """
    # Alle Offsets sind ABSOLUT zum Payload-Anfang (belegt an realen Saves).
    block2 = base + 2 + 48 + 52
    strings_offset = block2 + 12
    encoded = bytearray()
    for text in strings:
        raw = text.encode("utf-8")
        length = len(raw) + (1 if bad_string_length else 0)
        encoded += struct.pack("<H", length) + raw
        if truncate_last_string and text is strings[-1]:
            encoded = encoded[:-1]                        # letztes Byte weg
    count = len(strings) if declared_count is None else declared_count
    pointers = [0, 0, block2 if pointer2_override is None else pointer2_override,
                0, 0, 0, 0, 0, 0, 0, 0, 0]
    out = bytearray()
    out += struct.pack("<H", unlock)
    out += struct.pack("<12I", *pointers)
    out += b"\x00" * 52
    out += struct.pack("<III", 0, strings_offset, unlock)
    out += struct.pack("<H", count)
    out += encoded
    return bytes(out)


DEFAULT_STRINGS = ["Sequence", "SitSleep", "Sandbox", "LocPt",
                   "[Kalibriert] Anzug: UC-Security",
                   "actors\\human\\animations\\furniture\\terminal_standing"]


#: Feste Bytes des Headers zwischen name und createdGameVersion.
#: Hergeleitet aus der belegten Feldreihenfolge (siehe _HEADER_FIXED_BYTES).
_HEADER_FIXED_BYTES = 51


def expected_header_size(player_name: str, player_location: str,
                         playtime: str, race_name: str) -> int:
    """Von ``headerSize`` gezaehlter Bereich: 51 feste + vier Stringlaengen.

    Belegt an sechs realen Saves (6/6 exakt) und unabhaengig von den konkreten
    Werten: 51 + len(name) + len(location) + len(playtime) + len(race).
    """
    return (_HEADER_FIXED_BYTES + len(player_name) + len(player_location)
            + len(playtime) + len(race_name))


def build_dat_payload(*, normal: list[bytes] | None = None,
                      light: list[bytes] | None = None,
                      medium: list[bytes] | None = None,
                      strings: list[str] | None = None,
                      body: bytes | None = None,
                      body_options: dict | None = None,
                      header_size_field: int | None = None,
                      plugin_info_size_override: int | None = None,
                      save_version: int = 153,
                      player_name: str = "TestPilot",
                      player_location: str = "Jemison - New Atlantis",
                      playtime: str = "1d.2h.3m.1 Tag.2 Stunden.3 Minuten",
                      race_name: str = "HumanRace",
                      save_number: int = 1,
                      player_level: int = 24,
                      filetime: int = 134358573240754512,
                      truncate_at: int | None = None,
                      **plugin_kwargs) -> bytes:
    """Vollstaendiger Payload: 12-Byte-Magic + Header + Plugin-Block + Body."""
    normal = normal if normal is not None else [
        plugin_record("Starfield.esm", category="game"),
        plugin_record("SFSE.esm", category="mod"),
    ]
    light = light if light is not None else [
        plugin_record("SFBGS004.esl", category="game"),
    ]
    medium = medium if medium is not None else [
        plugin_record("SFBGS003.esm", category="game"),
    ]
    block = build_plugin_block(normal=normal, light=light, medium=medium,
                              **plugin_kwargs)
    head = bytearray(b"SFS_SAVEGAME")
    if header_size_field is None:
        header_size_field = expected_header_size(player_name, player_location,
                                                 playtime, race_name)
    head += struct.pack("<I", header_size_field)
    head += struct.pack("<I", 27)                          # engineVersion
    head += bytes([save_version])                          # saveVersion
    head += struct.pack("<I", save_number)                 # saveNumber
    head += _qstring(player_name)                          # playerName
    head += struct.pack("<I", player_level)                # playerLevel
    head += _qstring(player_location)                      # playerLocation
    head += _qstring(playtime)                             # playtime
    head += _qstring(race_name)                            # raceName
    head += struct.pack("<H", 0)                           # gender
    head += struct.pack("<f", 1.0)                         # experience
    head += struct.pack("<f", 2.0)                         # experienceRequired
    head += struct.pack("<Q", filetime)                     # filetime
    head += struct.pack("<I", 0)                           # unknown0
    head += b"\x00" * 8                                    # padding
    head += bytes([save_version])                          # saveVersion2
    head += _qstring("1.16.244.0")                         # currentGameVersion
    head += _qstring("1.16.236.0")                         # createdGameVersion
    head += struct.pack("<H", plugin_info_size_override
                        if plugin_info_size_override is not None else len(block))
    head += block
    if body is None:
        options = dict(body_options or {})
        body = build_body_head(strings if strings is not None else DEFAULT_STRINGS,
                               base=len(head), **options)
    result = bytes(head) + body
    if truncate_at is not None:
        result = result[:truncate_at]
    return result


def write_save(path: Path, payload: bytes, **container_kwargs) -> Path:
    path.write_bytes(build_synthetic_sfs(payload, **container_kwargs))
    return path


@pytest.fixture()
def synthetic_save(tmp_path) -> Path:
    """Gueltiger synthetischer Save mit allen drei Ketten und String-Pool."""
    return write_save(tmp_path / "synthetic.sfs", build_dat_payload())
