"""
ssb_i/savegame_provider.py — SFS savegame analysis provider for SSB-I.

Adopts the SSB-I Provider pattern: read-only, declarative, capability-based.
Supports the savegame operations we built in Phase 2.6/2.7.

Provenance: all operations are READ-ONLY over local .sfs files.
"""
from __future__ import annotations

import os, struct, zlib, json
from dataclasses import dataclass, field, asdict
from typing import Any, BinaryIO, Iterable, Mapping


# =============================================================================
# SFS container decoder (BCPS / Zlib)
# =============================================================================
SFS_MAGIC = b'BCPS'
DAT_MAGIC = b'SFS_SAVEGAME'
DAT_HEADER_SIZE = 124  # typical for save_version >= 120


@dataclass
class SfsChunkInfo:
    """Compressed-chunk metadata, mirrors Nexus-Mods/StarfieldSaveTool."""
    index: int
    compressed_size: int
    padded_size: int
    uncompressed_size: int  # post-zlib
    offset: int


@dataclass
class SfsContainer:
    """Decoded BCPS container header."""
    version0: int
    chunk_size_pre: int
    padding_size: int
    uncompressed_size: int
    compressed_offset: int
    chunk_count: int
    chunks: list[SfsChunkInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version0": self.version0,
            "chunk_size_pre": self.chunk_size_pre,
            "padding_size": self.padding_size,
            "uncompressed_size": self.uncompressed_size,
            "compressed_offset": self.compressed_offset,
            "chunk_count": self.chunk_count,
            "chunks": [asdict(c) for c in self.chunks],
        }


@dataclass
class DatHeader:
    """Decoded SFS_SAVEGAME header."""
    header_size: int
    engine_version: int
    save_version: int
    save_number: int
    player_name: str
    player_level: int
    player_location: str
    playtime: str
    race_name: str
    gender: int
    experience: float
    experience_required: float
    filetime: int
    save_version_2: int
    current_game_version: str
    created_game_version: str
    plugin_info_offset: int
    plugin_info_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginEntry:
    name: str
    is_native: bool
    creation_name: str | None = None
    creation_id: str | None = None


@dataclass
class PluginInfo:
    normal: list[PluginEntry] = field(default_factory=list)
    light: list[PluginEntry] = field(default_factory=list)
    medium: list[PluginEntry] = field(default_factory=list)
    #: VALIDATED = Anzahl und Rahmen stimmen mit den deklarierten Zaehlern
    #: ueberein. UNVERIFIED = die Liste ist NICHT als Plugin-Liste zu lesen.
    decode_state: str = "UNVERIFIED"
    note: str = ""
    declared_normal: int = 0

    @property
    def total(self) -> int:
        return len(self.normal) + len(self.light) + len(self.medium)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normal": [asdict(p) for p in self.normal],
            "light": [asdict(p) for p in self.light],
            "medium": [asdict(p) for p in self.medium],
            "counts": {
                "normal": len(self.normal),
                "light": len(self.light),
                "medium": len(self.medium),
            },
            "decode_state": self.decode_state,
            "declared_normal": self.declared_normal,
            "note": self.note,
        }


# =============================================================================
# SfsDecodeProvider — READ-ONLY provider
# =============================================================================
class SfsDecodeProvider:
    """Provider for Starfield .sfs savegame decoding and analysis."""

    name = "sfs-decode"

    def capabilities(self) -> Mapping[str, bool]:
        """Declarative capability map. Always read-only."""
        return {
            "process_identity": True,         # can identify save by metadata
            "module_enumeration": True,      # can enumerate plugins
            "memory_read": True,              # can read savegame data
            "memory_write_observation": False,  # strictly read-only
            "execution_events": False,       # no runtime hooks
            "thread_events": False,
            "register_state": False,
            "callstack": False,
            "object_inspection": True,       # can inspect FormIDs/strings
        }

    def capability_probe(self) -> dict[str, Any]:
        """Run read-only probes (currently just file-magic validation)."""
        return {
            "provider": self.name,
            "read_only": True,
            "capabilities": dict(self.capabilities()),
            "provenance": {"source": "static + dynamic analysis", "verified": True},
        }

    # -----------------------------------------------------------------
    # Container decoding
    # -----------------------------------------------------------------
    def read_container(self, sfs_path: str) -> SfsContainer:
        """Parse BCPS header, return chunk table. Does NOT decompress."""
        if not os.path.exists(sfs_path):
            raise FileNotFoundError(sfs_path)
        with open(sfs_path, "rb") as f:
            data = f.read(96)
        if data[:4] != SFS_MAGIC:
            raise ValueError(f"Not an SFS file: {data[:4]!r} (expected b'BCPS')")
        # Header layout per Nexus-Mods/StarfieldSaveTool/SfsFile.cs ReadHeader()
        # EXACT offsets (no guessing):
        off = 4
        version0,           = struct.unpack_from("<i", data, off); off += 4   # +4
        chunk_sizes_offset, = struct.unpack_from("<q", data, off); off += 8   # +8
        unknown0,           = struct.unpack_from("<q", data, off); off += 8   # +16
        compressed_offset,  = struct.unpack_from("<q", data, off); off += 8   # +24
        uncompressed_size,  = struct.unpack_from("<q", data, off); off += 8   # +32
        version1,           = struct.unpack_from("<f", data, off); off += 4   # +40
        unknown1,           = struct.unpack_from("<i", data, off); off += 4   # +44
        chunk_size_pre,     = struct.unpack_from("<q", data, off); off += 8   # +48
        padding_size,       = struct.unpack_from("<q", data, off); off += 8   # +56
        unknown2,           = struct.unpack_from("<i", data, off); off += 4   # +64
        compression         = data[off:off + 4]                                # +68
        if compression != b'ZIP ':
            raise ValueError(f"Only ZIP compression supported, got {compression!r}")
        chunk_count = (uncompressed_size + chunk_size_pre - 1) // chunk_size_pre
        return SfsContainer(
            version0=version0,
            chunk_size_pre=chunk_size_pre,
            padding_size=padding_size,
            uncompressed_size=uncompressed_size,
            compressed_offset=compressed_offset,
            chunk_count=chunk_count,
        )

    def decompress(self, sfs_path: str) -> bytes:
        """Decompress an entire .sfs to a single byte buffer. Returns raw decompressed bytes."""
        with open(sfs_path, "rb") as f:
            data = f.read()
        if data[:4] != SFS_MAGIC:
            raise ValueError(f"Not an SFS file: {data[:4]!r}")
        # Re-parse full header using same layout as read_container()
        off = 4
        off += 4            # version0 (int32)
        chunk_sizes_offset, = struct.unpack_from("<q", data, off); off += 8
        off += 8            # unknown0
        compressed_offset,  = struct.unpack_from("<q", data, off); off += 8
        uncompressed_size,  = struct.unpack_from("<q", data, off); off += 8
        off += 4            # version1 (float)
        off += 4            # unknown1 (int32)
        chunk_size_pre,    = struct.unpack_from("<q", data, off); off += 8
        padding_size,      = struct.unpack_from("<q", data, off); off += 8
        # Skip unknown2 (int32) and compression type (char[4])
        off += 4 + 4
        # Chunk sizes array starts at chunk_sizes_offset, ends at compressed_offset
        chunk_count = (uncompressed_size + chunk_size_pre - 1) // chunk_size_pre
        chunk_sizes = list(
            struct.unpack_from(f"<{chunk_count}i", data, chunk_sizes_offset)
        )

        out = bytearray()
        pos = compressed_offset
        for chunk_idx, cs in enumerate(chunk_sizes):
            chunk = data[pos:pos + cs]
            try:
                out += zlib.decompress(chunk)
            except zlib.error as e:
                raise ValueError(
                    f"zlib-decompression failed at chunk {chunk_idx} "
                    f"(pos=0x{pos:X}, size={cs}): {e}"
                )
            padded = (cs + padding_size - 1) & ~(padding_size - 1) if padding_size else cs
            pos += padded
        return bytes(out)

    # -----------------------------------------------------------------
    # SFS_SAVEGAME header + plugin info
    # -----------------------------------------------------------------
    def parse_dat_header(self, decompressed: bytes) -> DatHeader:
        """Parse the SFS_SAVEGAME inner header."""
        if decompressed[:12] != DAT_MAGIC:
            raise ValueError(f"Not a DAT file: starts with {decompressed[:12]!r}")
        off = 12
        header_size, = struct.unpack_from("<I", decompressed, off); off += 4
        engine_version, = struct.unpack_from("<I", decompressed, off); off += 4
        save_version = decompressed[off]; off += 1
        save_number, = struct.unpack_from("<I", decompressed, off); off += 4
        pname_size, = struct.unpack_from("<H", decompressed, off); off += 2
        player_name = decompressed[off:off + pname_size].decode("ascii", errors="replace")
        off += pname_size
        player_level, = struct.unpack_from("<I", decompressed, off); off += 4
        ploc_size, = struct.unpack_from("<H", decompressed, off); off += 2
        player_location = decompressed[off:off + ploc_size].decode("ascii", errors="replace")
        off += ploc_size
        ptime_size, = struct.unpack_from("<H", decompressed, off); off += 2
        playtime = decompressed[off:off + ptime_size].decode("ascii", errors="replace")
        off += ptime_size
        race_size, = struct.unpack_from("<H", decompressed, off); off += 2
        race_name = decompressed[off:off + race_size].decode("ascii", errors="replace")
        off += race_size
        gender, = struct.unpack_from("<H", decompressed, off); off += 2
        experience, = struct.unpack_from("<f", decompressed, off); off += 4
        experience_req, = struct.unpack_from("<f", decompressed, off); off += 4
        filetime, = struct.unpack_from("<Q", decompressed, off); off += 8
        unknown0, = struct.unpack_from("<I", decompressed, off); off += 4
        off += 8  # padding
        save_version_2 = decompressed[off]; off += 1
        cur_ver_size, = struct.unpack_from("<H", decompressed, off); off += 2
        cur_ver = decompressed[off:off + cur_ver_size].decode("ascii", errors="replace")
        off += cur_ver_size
        cre_ver_size, = struct.unpack_from("<H", decompressed, off); off += 2
        cre_ver = decompressed[off:off + cre_ver_size].decode("ascii", errors="replace")
        off += cre_ver_size
        plugin_info_size, = struct.unpack_from("<H", decompressed, off); off += 2
        return DatHeader(
            header_size=header_size,
            engine_version=engine_version,
            save_version=save_version,
            save_number=save_number,
            player_name=player_name,
            player_level=player_level,
            player_location=player_location,
            playtime=playtime,
            race_name=race_name,
            gender=gender,
            experience=experience,
            experience_required=experience_req,
            filetime=filetime,
            save_version_2=save_version_2,
            current_game_version=cur_ver,
            created_game_version=cre_ver,
            plugin_info_offset=off,
            plugin_info_size=plugin_info_size,
        )

    NATIVE_PLUGINS = {
        "Starfield.esm", "Constellation.esm", "OldMars.esm",
        "BlueprintShips-Starfield.esm", "SFBGS007.esm", "SFBGS008.esm",
        "SFBGS006.esm", "SFBGS003.esm",
    }

    # -- plugin name plausibility (a name, not a memory dump) -----------
    PLUGIN_EXTS = (b'.esm', b'.esl', b'.esp')
    PLUGIN_NAME_MAX = 96
    PLUGIN_META_MAX = 256

    @classmethod
    def is_plugin_name(cls, raw: bytes) -> bool:
        """Ein Pluginname ist druckbar, kurz und endet auf .esm/.esl/.esp."""
        if not (3 <= len(raw) <= cls.PLUGIN_NAME_MAX):
            return False
        if any(b < 0x20 or b > 0x7E for b in raw):
            return False
        return raw.lower().endswith(cls.PLUGIN_EXTS)

    @classmethod
    def _read_name_at(cls, data: bytes, pos: int) -> tuple[str, int] | None:
        """Liest ``u16 len + name``; ``None``, wenn dort kein Name steht."""
        if pos + 2 > len(data):
            return None
        size, = struct.unpack_from("<H", data, pos)
        start = pos + 2
        if size < 3 or start + size > len(data):
            return None
        raw = data[start:start + size]
        if not cls.is_plugin_name(raw):
            return None
        return raw.decode("ascii"), start + size

    @classmethod
    def _walk_names(cls, data: bytes, pos: int, count: int):
        """Liest ``count`` Namen ab ``pos`` — synchronisiert ueber Metadaten.

        Jeder Record ist ``u16 len + Name`` gefolgt von einem optionalen
        Metadaten-Block unbekannter Laenge (belegt: 0 bis ~100 Byte, Inhalt
        NICHT dekodiert). Zwischen zwei Namen wird daher der naechste
        plausible ``u16 len + Name`` gesucht.

        Rueckgabe ``(namen, endposition)`` oder ``(None, pos)``. Die Kette
        gilt nur als gelesen, wenn ALLE ``count`` Namen gefunden wurden.
        """
        names: list[str] = []
        cursor = pos
        for index in range(count):
            got = cls._read_name_at(data, cursor)
            if got is None:
                return None, pos
            name, name_end = got
            names.append(name)
            if index == count - 1:
                return names, name_end
            resync = None
            limit = min(name_end + cls.PLUGIN_META_MAX, len(data) - 2)
            for probe in range(name_end, limit):
                if cls._read_name_at(data, probe) is not None:
                    resync = probe
                    break
            if resync is None:
                return None, pos
            cursor = resync
        return names, cursor

    @classmethod
    def _probe_counted_chain(cls, data: bytes, pos: int, window: int,
                             count_width: int):
        """Sucht ``count + count Namen`` in ``[pos, pos+window)``.

        Der erste Offset, an dem die vollstaendige Kette parst, gewinnt.
        ``count == 0`` ist nur gueltig, wenn ``count_width == 4`` (Medium-Block
        kann leer sein); sonst waere jeder Nullbyte ein Treffer.
        """
        for probe in range(pos, min(pos + window, len(data))):
            if count_width == 2:
                if probe + 2 > len(data):
                    break
                count, = struct.unpack_from("<H", data, probe)
            else:
                if probe + 4 > len(data):
                    break
                count, = struct.unpack_from("<I", data, probe)
            if count == 0:
                if count_width == 4:
                    return [], probe + 4
                continue
            if count > 4096:
                continue
            names, end = cls._walk_names(data, probe + count_width, count)
            if names is not None:
                return names, end
        return None, pos

    def parse_plugin_info(self, decompressed: bytes, header: DatHeader) -> PluginInfo:
        """Liest die Plugin-Liste — selbst-validierend, ohne Semantikraten.

        BELEGT (04.11.2026, Save-Version 153, drei Saves aus einer Partie):

          * ``plugin_info_offset + 2`` traegt die Anzahl der Normal-Plugins
            als ``u8`` (gemessen: 24 in Save41/Save42/Save43).
          * Jeder Record ist ``u16 len`` + Name + optionaler Metadaten-Block
            (0 bis ~100 Byte, Inhalt NICHT dekodiert).
          * Danach folgt ein ``u16`` Anzahlfeld und die Light-Plugins in
            derselben Record-Form.

        WARUM DIE ALT-VERSION FALSCH WAR
          Der alte Parser las nach jedem Namen sofort wieder ``u16 len``.
          Wegen des Metadaten-Blocks desynchronisierte er ab dem zweiten
          Plugin: 24 "normal" + 3.329 "light" Eintraege, davon genau EIN
          plausibler Name. Ungetestet, weil alle Tests mit echten Saves
          uebersprungen wurden (Dateien fehlten).

        ERGEBNIS
          ``decode_state == 'VALIDATED'`` nur wenn die Anzahl der gelesenen
          Namen exakt den deklarierten Zaehlern entspricht. Sonst
          ``UNVERIFIED`` — dann sind die Listen leer und es wird nichts
          angezeigt, was wie eine Plugin-Liste aussieht.
        """
        info = PluginInfo()
        pos = header.plugin_info_offset
        if pos + 3 > len(decompressed):
            info.decode_state = "UNVERIFIED"
            info.note = "plugin_info_offset lies outside the file"
            return info

        declared_normal = decompressed[pos + 2]
        info.declared_normal = declared_normal

        names, end = self._walk_names(decompressed, pos + 3, declared_normal)
        if names is None:
            info.decode_state = "UNVERIFIED"
            info.note = ("normal plugins not fully readable "
                         "(declared %d, aborted at offset 0x%X)"
                         % (declared_normal, pos + 3))
            return info
        info.normal = [PluginEntry(name=n, is_native=n in self.NATIVE_PLUGINS)
                       for n in names]

        # Light-Kette: Anzahlfeld liegt hinter dem Metadaten-Block des letzten
        # Normal-Plugins. Nur eine vollstaendig parsende Kette wird akzeptiert.
        light, light_end = self._probe_counted_chain(
            decompressed, end, self.PLUGIN_META_MAX, count_width=2)
        if light is None:
            info.decode_state = "UNVERIFIED"
            info.note = ("normal plugins read (%d), but no valid "
                         "Light-Kette ab 0x%X" % (len(names), end))
            info.normal = []
            return info
        info.light = [PluginEntry(name=n, is_native=n in self.NATIVE_PLUGINS)
                      for n in light]

        # Medium-Block (save_version >= 122): u32 Anzahl, darf 0 sein.
        medium, _ = self._probe_counted_chain(
            decompressed, light_end, 32, count_width=4)
        info.medium = [PluginEntry(name=n, is_native=n in self.NATIVE_PLUGINS)
                       for n in (medium or [])]

        info.decode_state = "VALIDATED"
        info.note = ("%d normal (declared %d), %d light, %d medium; "
                     "per-record metadata block NOT decoded"
                     % (len(info.normal), declared_normal, len(info.light),
                        len(info.medium)))
        return info

    # -----------------------------------------------------------------
    # Difference analysis
    # -----------------------------------------------------------------
    def diff_saves(self, a_path: str, b_path: str, *, max_diff: int = 200) -> dict[str, Any]:
        """Diff two .sfs files by their decompressed bytes."""
        a = self.decompress(a_path)
        b = self.decompress(b_path)
        min_len = min(len(a), len(b))
        diffs = []
        for i in range(min_len):
            if a[i] != b[i]:
                diffs.append({"offset": i, "a": a[i], "b": b[i]})
                if len(diffs) > max_diff:
                    break
        return {
            "a_size": len(a),
            "b_size": len(b),
            "diffs_count": len(diffs),
            "diffs": diffs,
            "shared_percent": (min_len - len([d for d in diffs if d["offset"] < min_len])) / min_len * 100,
        }


# Public API
def get_provider() -> SfsDecodeProvider:
    return SfsDecodeProvider()
