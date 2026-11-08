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
    """Ein Plugin-Eintrag aus dem Savegame-Plugin-Block.

    Semantik der Felder (belegt 08.11.2026, Save-Version 153, 6 Saves):

      * ``category``       "game" wenn ``extraInfo == 0`` (Master des Basisspiels),
                           "mod" wenn ``extraInfo == 1`` (Creation/Plugin).
      * ``metadata_state`` "present"   = extraInfo 1 UND mindestens ein echtes
                                         Metadatenfeld (creation_name/creation_id)
                           "absent"    = keine Metadaten hinterlegt (Game-Plugin
                                         oder Mod ohne Creation-Angaben)
                           "unreadable"= Laengenfeld laeuft aus dem Puffer; alle
                                         Metadatenfelder bleiben None
      * ``version``        Inhalt des ``flags``-Feldes, sofern er wie eine
                           Versionsangabe aussieht (``<epoch>.<major>...``).
                           Der Engine-Platzhalter wird zu ``None`` normalisiert.
    """
    name: str
    is_native: bool
    category: str = "mod"              # "game" | "mod"
    creation_name: str | None = None
    creation_id: str | None = None
    version: str | None = None
    achievement_friendly: bool | None = None
    metadata_state: str = "absent"     # "present" | "absent" | "unreadable"
    position: int = 0                  # Index innerhalb der Kette
    detail: str = ""                   # Begruendung fuer metadata_state


@dataclass
class PluginInfo:
    normal: list[PluginEntry] = field(default_factory=list)
    light: list[PluginEntry] = field(default_factory=list)
    medium: list[PluginEntry] = field(default_factory=list)
    #: VALIDATED = alle drei Ketten vollstaendig gelesen.
    #: UNVERIFIED = mindestens eine Kette brach ab; alle Listen bleiben leer,
    #: damit nie eine erfundene Plugin-Liste angezeigt wird.
    decode_state: str = "UNVERIFIED"
    note: str = ""
    declared_normal: int = 0
    declared_light: int = 0
    declared_medium: int = 0
    #: Bytepositionen fuer die Integritaetspruefung (I-10/I-11)
    block_start: int = 0
    block_end: int = 0
    block_end_declared: int = 0

    @property
    def total(self) -> int:
        return len(self.normal) + len(self.light) + len(self.medium)

    @property
    def block_delta(self) -> int:
        """Differenz zwischen gelesenem und deklariertem Blockende (0 = exakt)."""
        return self.block_end_declared - self.block_end

    @property
    def game_count(self) -> int:
        return sum(1 for p in self.normal + self.light + self.medium
                   if p.category == "game")

    @property
    def mod_count(self) -> int:
        return self.total - self.game_count

    @property
    def metadata_count(self) -> int:
        return sum(1 for p in self.normal + self.light + self.medium
                   if p.metadata_state == "present")

    @property
    def unreadable_count(self) -> int:
        return sum(1 for p in self.normal + self.light + self.medium
                   if p.metadata_state == "unreadable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "normal": [asdict(p) for p in self.normal],
            "light": [asdict(p) for p in self.light],
            "medium": [asdict(p) for p in self.medium],
            "counts": {
                "normal": len(self.normal),
                "light": len(self.light),
                "medium": len(self.medium),
                "total": self.total,
            },
            "declared": {
                "normal": self.declared_normal,
                "light": self.declared_light,
                "medium": self.declared_medium,
            },
            "categories": {"game": self.game_count, "mod": self.mod_count},
            "metadata": {
                "present": self.metadata_count,
                "unreadable": self.unreadable_count,
            },
            "block": {
                "start": self.block_start,
                "end": self.block_end,
                "declared_end": self.block_end_declared,
                "delta": self.block_delta,
            },
            "decode_state": self.decode_state,
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

    def decompress(self, sfs_path: str, *, verify: bool = True) -> bytes:
        """Decompress an entire .sfs to a single byte buffer.

        ``verify=True`` (Default) vergleicht das Ergebnis mit der deklarierten
        ``uncompressed_size`` und wirft ``ValueError`` bei Abweichung. Ohne diese
        Pruefung liefen zwei nachgewiesene Fehlerfaelle still durch (08.11.2026):
        ein manipuliertes Groessenfeld und ein verdoppeltes ``chunk_size_pre``,
        das nur 50 % der Nutzdaten lieferte — bei plausibel aussehender Ausgabe.
        """

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
        result = bytes(out)
        if verify and len(result) != uncompressed_size:
            raise ValueError(
                "decompressed length %d does not match declared uncompressed_size %d "
                "(delta %+d bytes)" % (len(result), uncompressed_size,
                                       len(result) - uncompressed_size))
        return result

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
    #: Obergrenze fuer eine Plugin-Kette. Real gemessen: 25/50/5.
    PLUGIN_CHAIN_MAX = 4096
    #: Engine-Platzhalter im creationId-Feld, wenn keine Creation-ID hinterlegt ist.
    PLACEHOLDER_ID = "18446744073709551615.undefined"

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
    def _read_string_field(cls, data: bytes, pos: int):
        """Liest ``u16 len + ASCII``; Rueckgabe ``(wert, neue_position)``.

        Bei Ueberlauf ``(None, pos)`` — die Position bleibt dann unveraendert,
        damit der Aufrufer den Abbruch eindeutig erkennt.
        """
        if pos + 2 > len(data):
            return None, pos
        size, = struct.unpack_from("<H", data, pos)
        start = pos + 2
        if start + size > len(data):
            return None, pos
        return data[start:start + size].decode("ascii", errors="replace"), start + size

    @classmethod
    def _read_plugin_records(cls, data: bytes, pos: int, count: int, *, chain: str):
        """Liest ``count`` Plugin-Records streng nach belegtem Format.

        Format (Save-Version >= 140, belegt 08.11.2026 an 6 realen Saves,
        gegen die Referenzimplementierung Nexus-Mods/StarfieldSaveTool geprueft
        und bis zum bytegenauen Blockende verifiziert)::

            u16 len + pluginName
            u8  extraInfo              # 0 = Game-Plugin, 1 = Mod-Plugin
            if extraInfo == 1:
                u16 len + creationName
                u16 len + creationId
                u16 len + flags        # in der Praxis eine ASCII-Version
                u8  achievementFriendly

        Rueckgabe ``(entries, endposition, fehler)``. ``fehler`` ist ``""``,
        wenn alle ``count`` Records vollstaendig gelesen wurden. Ein Record,
        dessen Metadaten aus dem Puffer laufen, wird mit
        ``metadata_state='unreadable'`` aufgenommen und die Kette abgebrochen —
        es werden keine Metadaten aus benachbarten Records uebernommen.
        """
        entries: list[PluginEntry] = []
        cursor = pos
        for index in range(count):
            name, after_name = cls._read_string_field(data, cursor)
            if name is None:
                return entries, cursor, (
                    "%s chain: name field truncated at 0x%X (record %d of %d)"
                    % (chain, cursor, index, count))
            if not cls.is_plugin_name(name.encode("ascii", "replace")):
                return entries, cursor, (
                    "%s chain: %r at 0x%X is not a plugin name (record %d of %d)"
                    % (chain, name[:32], cursor, index, count))
            cursor = after_name
            if cursor >= len(data):
                return entries, cursor, (
                    "%s chain: no extraInfo byte for %r" % (chain, name))
            extra = data[cursor]
            cursor += 1
            entry = PluginEntry(name=name, is_native=name in cls.NATIVE_PLUGINS,
                                position=index)
            if extra == 0:
                entry.category = "game"
                entry.metadata_state = "absent"
                entry.detail = "game plugin (extraInfo=0)"
                entries.append(entry)
                continue

            entry.category = "mod"
            creation_name, cursor = cls._read_string_field(data, cursor)
            if creation_name is None:
                entry.metadata_state = "unreadable"
                entry.detail = "creationName length runs past the buffer"
                entries.append(entry)
                return entries, cursor, (
                    "%s chain: truncated creationName in %r" % (chain, name))
            creation_id, cursor = cls._read_string_field(data, cursor)
            if creation_id is None:
                entry.metadata_state = "unreadable"
                entry.detail = "creationId length runs past the buffer"
                entries.append(entry)
                return entries, cursor, (
                    "%s chain: truncated creationId in %r" % (chain, name))
            flags, cursor = cls._read_string_field(data, cursor)
            if flags is None:
                entry.metadata_state = "unreadable"
                entry.detail = "flags length runs past the buffer"
                entries.append(entry)
                return entries, cursor, (
                    "%s chain: truncated flags in %r" % (chain, name))
            if cursor >= len(data):
                entry.metadata_state = "unreadable"
                entry.detail = "achievementFriendly byte missing"
                entries.append(entry)
                return entries, cursor, (
                    "%s chain: missing achievementFriendly in %r" % (chain, name))
            entry.achievement_friendly = data[cursor] != 0
            cursor += 1

            # Engine-Platzhalter ist "keine Creation-ID", keine echte ID.
            real_name = creation_name or None
            real_id = None if (not creation_id or creation_id == cls.PLACEHOLDER_ID) else creation_id
            entry.creation_name = real_name
            entry.creation_id = real_id
            # ``flags`` traegt in der Praxis eine Version wie "1753987979.2.3".
            entry.version = flags or None
            if real_name or real_id:
                entry.metadata_state = "present"
                entry.detail = "creation metadata present"
            else:
                entry.metadata_state = "absent"
                placeholder = (creation_id == cls.PLACEHOLDER_ID)
                entry.detail = ("mod plugin without creation data"
                                + (" (engine placeholder)" if placeholder else ""))
            entries.append(entry)
        return entries, cursor, ""

    def parse_plugin_info(self, decompressed: bytes, header: DatHeader) -> PluginInfo:
        """Liest den vollstaendigen Plugin-Block: normal, light UND medium.

        Reihenfolge (belegt, nicht angenommen): ``u8 unknown0``, ``u8 count0``,
        ``u8 normalCount``, Normal-Records, ``u16 lightCount``, Light-Records,
        ``u32 mediumCount``, Medium-Records.

        WARUM DIE VORVERSION FALSCHE ZAHLEN LIEF
          Sie beendete die Kette nach den Light-Plugins und meldete
          ``medium = 0``. Real tragen alle untersuchten Saves fuenf
          Medium-Plugins; die Produktausgabe zeigte 75 statt 80 Eintraege
          (Befund 08.11.2026, gegen die Referenzimplementierung verifiziert).

        ERGEBNIS
          ``decode_state == 'VALIDATED'`` nur wenn alle drei Ketten vollstaendig
          gelesen wurden. ``block_delta`` nennt die Differenz zwischen gelesenem
          und deklariertem Blockende (0 = die Struktur geht bytegenau auf).
          Bei einem Abbruch bleiben ALLE Listen leer — lieber nichts anzeigen
          als eine erfundene Plugin-Liste.
        """
        info = PluginInfo()
        pos = header.plugin_info_offset
        info.block_start = pos
        info.block_end_declared = pos + header.plugin_info_size
        info.block_end = pos
        if pos + 3 > len(decompressed):
            info.note = "plugin_info_offset lies outside the file"
            return info

        info.declared_normal = decompressed[pos + 2]
        cursor = pos + 3

        normal, cursor, error = self._read_plugin_records(
            decompressed, cursor, info.declared_normal, chain="normal")
        if error:
            info.note = error
            return info

        if cursor + 2 > len(decompressed):
            info.note = "light plugin count truncated at 0x%X" % cursor
            return info
        info.declared_light, = struct.unpack_from("<H", decompressed, cursor)
        cursor += 2
        if info.declared_light > self.PLUGIN_CHAIN_MAX:
            info.note = ("implausible light plugin count %d at 0x%X"
                         % (info.declared_light, cursor - 2))
            return info

        light, cursor, error = self._read_plugin_records(
            decompressed, cursor, info.declared_light, chain="light")
        if error:
            info.note = error
            return info

        if cursor + 4 > len(decompressed):
            info.note = "medium plugin count truncated at 0x%X" % cursor
            return info
        info.declared_medium, = struct.unpack_from("<I", decompressed, cursor)
        cursor += 4
        if info.declared_medium > self.PLUGIN_CHAIN_MAX:
            info.note = ("implausible medium plugin count %d at 0x%X"
                         % (info.declared_medium, cursor - 4))
            return info

        medium, cursor, error = self._read_plugin_records(
            decompressed, cursor, info.declared_medium, chain="medium")
        if error:
            info.note = error
            return info

        info.normal, info.light, info.medium = normal, light, medium
        info.block_end = cursor
        info.decode_state = "VALIDATED"
        info.note = (
            "%d normal, %d light, %d medium (declared %d/%d/%d); "
            "%d game + %d mod plugins; block delta %d bytes"
            % (len(normal), len(light), len(medium),
               info.declared_normal, info.declared_light, info.declared_medium,
               info.game_count, info.mod_count, info.block_delta))
        return info


    # -----------------------------------------------------------------
    # Container-Geometrie (fuer die Integritaetspruefung)
    # -----------------------------------------------------------------
    def read_chunk_table(self, sfs_path: str) -> dict[str, Any]:
        """Liest die echte Chunk-Groessentabelle aus dem Dateikopf.

        ``SfsContainer.chunks`` bleibt aus Kompatibilitaetsgruenden leer; die
        Tabelle wird hier materialisiert, damit I-03/I-04 dagegen pruefen
        koennen, ohne den Dekompressionspfad zu duplizieren.
        """
        with open(sfs_path, "rb") as f:
            data = f.read()
        if data[:4] != SFS_MAGIC:
            raise ValueError("Not an SFS file: %r" % data[:4])
        off = 4
        off += 4                                            # version0
        chunk_sizes_offset, = struct.unpack_from("<q", data, off); off += 8
        off += 8                                            # unknown0
        compressed_offset, = struct.unpack_from("<q", data, off); off += 8
        uncompressed_size, = struct.unpack_from("<q", data, off); off += 8
        off += 4                                            # version1 (float)
        off += 4                                            # unknown1
        chunk_size_pre, = struct.unpack_from("<q", data, off); off += 8
        padding_size, = struct.unpack_from("<q", data, off); off += 8
        off += 4                                            # unknown2
        compression = data[off:off + 4]
        count = ((uncompressed_size + chunk_size_pre - 1) // chunk_size_pre
                 if chunk_size_pre else 0)
        sizes: list[int] = []
        if count and chunk_sizes_offset + 4 * count <= len(data):
            sizes = list(struct.unpack_from("<%di" % count, data, chunk_sizes_offset))
        padded = [((s + padding_size - 1) & ~(padding_size - 1)) if padding_size else s
                  for s in sizes]
        return {
            "version0": struct.unpack_from("<i", data, 4)[0],
            "chunk_sizes_offset": chunk_sizes_offset,
            "compressed_offset": compressed_offset,
            "uncompressed_size": uncompressed_size,
            "chunk_size_pre": chunk_size_pre,
            "padding_size": padding_size,
            "compression": compression.decode("ascii", "replace"),
            "declared_chunk_count": count,
            "chunk_sizes": sizes,
            "padded_sizes": padded,
            "sum_padded": sum(padded),
            "table_end": chunk_sizes_offset + 4 * count,
            "file_size": len(data),
            "data_rest": len(data) - compressed_offset,
            "header_end": off + 4,
        }

    # -----------------------------------------------------------------
    # String-Pool (read-only, KEINE Objektidentitaet)
    # -----------------------------------------------------------------
    #: Ab hier gilt ein String-Array als plausibel lesbar.
    STRING_POOL_MIN_PRINTABLE = 0.90
    #: Obergrenze, damit ein beschaedigter Zaehler keinen Riesenlauf ausloest.
    STRING_POOL_MAX = 200_000

    def read_string_pool(self, decompressed: bytes, header: DatHeader,
                         plugin_info: PluginInfo) -> dict[str, Any]:
        """Liest die String-Tabelle am Anfang des Save-Bodys — ausschliesslich lesend.

        Belegte Struktur (08.11.2026, 6/6 reale Saves, gegen das 010-Editor-
        Template von Nexus-Mods/StarfieldSaveTool verifiziert)::

            nach plugin_info_end:
              u16  unlock0                     # in allen Saves 1
              u32  pointer[12]                 # pointer[2] zeigt auf den Folgebenutzer
              byte padding[52]
              u32  pointer0                    # Inhalt unbedeutet
              u32  strings_array_offset        # Offset der String-Tabelle
              u32  unknown0                    # in allen Saves 1
              bei strings_array_offset:
                u16 count
                count x ( u16 len + UTF-8 text )

        HARTE GRENZE
          Diese Funktion liefert Text und Position. Sie belegt KEINE
          Objektidentitaet: keine FormID, kein Record, keine Referenz. Die
          uebrigen elf Pointer bleiben UNKNOWN und werden nur als Zahl
          mitgegeben, nicht interpretiert.

        Rueckgabe-Dict mit ``status``: ``OK`` | ``UNKNOWN`` | ``UNREADABLE``.
        """
        result: dict[str, Any] = {
            "status": "UNKNOWN",
            "reason": "",
            "block_start": plugin_info.block_end,
            "pointer_table": [],
            "pointer_table_offsets": [],
            "string_array_offset": None,
            "declared_count": 0,
            "count": 0,
            "strings": [],
            "end": plugin_info.block_end,
            "printable_ratio": 0.0,
            "unverified_pointers": [],
            "note": ("Text-Pool ohne Objektidentitaet: keine FormID-, Record- "
                     "oder Referenzzuordnung."),
        }
        data = decompressed
        base = plugin_info.block_end or (header.plugin_info_offset + header.plugin_info_size)
        result["block_start"] = base
        if base <= 0 or base + 2 + 48 + 52 + 12 > len(data):
            result["reason"] = "body head beyond buffer (base 0x%X)" % base
            return result

        unlock, = struct.unpack_from("<H", data, base)
        pointers = list(struct.unpack_from("<12I", data, base + 2))
        block2 = base + 2 + 48 + 52
        pointer0, strings_offset, unknown0 = struct.unpack_from("<3I", data, block2)
        result["unlock"] = unlock
        result["pointer_table"] = pointers
        result["pointer_table_offsets"] = ["0x%X" % v for v in pointers]
        result["string_array_offset"] = strings_offset
        result["block2_offset"] = block2
        result["unknown0_block2"] = unknown0

        # Belegte Selbstkonsistenz: pointer[2] zeigt auf den Folgebenutzer.
        if unlock != 1 or unknown0 != 1:
            result["reason"] = ("unexpected marker values (unlock=%d, block2=%d); "
                                "structure not recognised" % (unlock, unknown0))
            return result
        if pointers[2] != block2:
            result["reason"] = ("pointer[2]=0x%X does not point at the follow-up block "
                                "0x%X" % (pointers[2], block2))
            return result
        if not (0 < strings_offset < len(data) - 2):
            result["reason"] = "string offset 0x%X outside payload" % strings_offset
            return result

        declared, = struct.unpack_from("<H", data, strings_offset)
        result["declared_count"] = declared
        if declared > self.STRING_POOL_MAX:
            result["reason"] = "implausible string count %d" % declared
            return result

        cursor = strings_offset + 2
        strings: list[dict[str, Any]] = []
        printable = 0
        error = ""
        for index in range(declared):
            if cursor + 2 > len(data):
                error = "length field of string %d runs past the buffer" % index
                break
            length, = struct.unpack_from("<H", data, cursor)
            start = cursor + 2
            if start + length > len(data):
                error = "string %d (len %d) runs past the buffer" % (index, length)
                break
            raw = data[start:start + length]
            try:
                text = raw.decode("utf-8")
                ok = True
            except UnicodeDecodeError:
                text = raw.decode("utf-8", "replace")
                ok = False
            if ok and all(ch.isprintable() or ch in "\t" for ch in text):
                printable += 1
            strings.append({"index": index, "text": text, "offset": start,
                            "length": length, "status": "ok" if ok else "invalid-utf8"})
            cursor = start + length

        result["strings"] = strings
        result["count"] = len(strings)
        result["end"] = cursor
        result["printable_ratio"] = (printable / len(strings)) if strings else 0.0
        # Die uebrigen Pointer werden NICHT interpretiert, nur auf Bereich geprueft.
        result["unverified_pointers"] = [
            {"index": i, "value": v, "inside_payload": 0 < v < len(data)}
            for i, v in enumerate(pointers) if i != 2]
        if error:
            result["status"] = "UNREADABLE"
            result["reason"] = error
            return result
        if not strings or result["printable_ratio"] < self.STRING_POOL_MIN_PRINTABLE:
            result["status"] = "UNKNOWN"
            result["reason"] = ("printable ratio %.3f below threshold %.2f"
                                % (result["printable_ratio"], self.STRING_POOL_MIN_PRINTABLE))
            return result
        result["status"] = "OK"
        result["reason"] = ("%d strings read, %.1f%% printable"
                            % (len(strings), result["printable_ratio"] * 100))
        return result

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
