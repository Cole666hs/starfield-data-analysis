"""Verifikation externer Formataussagen gegen echte Starfield-Saves.

Quelle der geprueften Aussagen: Formatdokumentation von
https://github.com/Nexus-Mods/StarfieldSaveTool
  - SFS-decompressed.bt  (010-Editor-Template, 231 Zeilen)
  - DatFile.cs           (311 Zeilen, produktive C#-Implementierung)

READ-ONLY. Keine Datei wird geschrieben, kein Save veraendert.

Aufruf:
    python audit/save-intelligence/verify_external_format.py

Prueft drei Aussagen, die im SSB-I-Parser heute NICHT umgesetzt sind:
  A  Medium-Plugin-Block existiert und endet bytegenau am deklarierten Blockende
  B  Plugin-Records tragen Metadaten (extraInfo/creationName/creationId/flags/ach)
  C  Der Body beginnt mit Pointer-Tabelle + String-Array (5 Kriterien)

Exit-Code 0 = alle pruefbaren Aussagen bestaetigt, 2 = mindestens eine widerlegt.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

# O-11: the script moved from ``audit/save-intelligence/`` to
# ``docs/reports/save-intelligence/`` — one level deeper, so the repository
# root is one ``parents`` level further up.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ssb_i.savegame_provider import SfsDecodeProvider   # noqa: E402

PROBES = Path(os.environ.get("SAVE_PROBES", Path.home() / "ssb_probes"))
PROVIDER = SfsDecodeProvider()


def real_saves() -> list[Path]:
    """Starfield-Saves (ssbm_*-Kopien ausgeschlossen)."""
    found: list[Path] = []
    for root in (PROBES / "saves_07oct_2026", PROBES):
        if root.is_dir():
            found += [root / name for name in sorted(os.listdir(root))
                      if name.endswith(".sfs")
                      and name.startswith(("Save", "Auto", "Exit"))]
    return found


def walk_plugin_records(raw: bytes, start: int, count: int):
    """Liest count Plugin-Records inkl. Metadaten-Block (saveVersion >= 140)."""
    records: list[dict] = []
    pos = start
    for _ in range(count):
        if pos + 2 > len(raw):
            return records, pos, "EOF bei Namenslaenge"
        name_len, = struct.unpack_from("<H", raw, pos)
        pos += 2
        if not (3 <= name_len <= 96) or pos + name_len > len(raw):
            return records, pos, "unplausible Namenslaenge %d" % name_len
        name = raw[pos:pos + name_len].decode("ascii", "replace")
        pos += name_len
        if not name.lower().endswith((".esm", ".esl", ".esp")):
            return records, pos, "kein Pluginname: %r" % name[:20]
        if pos >= len(raw):
            return records, pos, "EOF nach Name"
        extra = raw[pos]
        pos += 1
        record = {"name": name, "extra": extra}
        if extra == 1:
            for field, read_bytes in (("creation_name", True), ("creation_id", True),
                                      ("flags", True), ("achievement_friendly", False)):
                if read_bytes:
                    if pos + 2 > len(raw):
                        return records, pos, "EOF bei %s" % field
                    length, = struct.unpack_from("<H", raw, pos)
                    pos += 2
                    if pos + length > len(raw):
                        return records, pos, "EOF in %s" % field
                    record[field] = raw[pos:pos + length].decode("ascii", "replace")
                    pos += length
                else:
                    record[field] = raw[pos] if pos < len(raw) else None
                    pos += 1
        records.append(record)
    return records, pos, "ok"


def read_string_array(raw: bytes, offset: int, count: int, limit: int = 100000):
    """Liest count QSTRINGs (u16 len + UTF-8)."""
    out: list[str] = []
    pos = offset
    for _ in range(min(count, limit)):
        if pos + 2 > len(raw):
            return out, pos, "EOF bei Laengenfeld"
        length, = struct.unpack_from("<H", raw, pos)
        pos += 2
        if length > 5000:
            return out, pos, "unplausible Laenge %d" % length
        if pos + length > len(raw):
            return out, pos, "EOF im String"
        try:
            out.append(raw[pos:pos + length].decode("utf-8"))
        except UnicodeDecodeError:
            return out, pos, "UTF-8-Fehler"
        pos += length
    return out, pos, "ok"


def main() -> int:
    saves = real_saves()
    if not saves:
        print("Keine Referenz-Saves unter %s" % PROBES)
        return 2

    print("=" * 92)
    print("A + B) Plugin-Block: normal / light / medium + Metadaten")
    print("=" * 92)
    print("%-26s | %4s %5s %6s | %-10s %-10s %6s | %s"
          % ("Save", "norm", "light", "med", "Ende geparst", "deklariert", "Delta", "Metadaten"))
    a_ok = b_ok = 0
    for path in saves:
        raw = PROVIDER.decompress(str(path))
        header = PROVIDER.parse_dat_header(raw)
        base = header.plugin_info_offset
        normal_count = raw[base + 2]
        normal, end1, s1 = walk_plugin_records(raw, base + 3, normal_count)
        light_count, = struct.unpack_from("<H", raw, end1)
        light, end2, s2 = walk_plugin_records(raw, end1 + 2, light_count)
        medium_count, = struct.unpack_from("<I", raw, end2)
        medium, end3, s3 = walk_plugin_records(raw, end2 + 4, medium_count) \
            if 0 < medium_count < 200 else ([], end2 + 4, "skip")
        declared = base + header.plugin_info_size
        delta = declared - end3
        if delta == 0 and s1 == s2 == "ok":
            a_ok += 1
        all_records = normal + light + medium
        with_id = sum(1 for r in all_records if str(r.get("creation_id", "")).startswith("TM_"))
        if with_id:
            b_ok += 1
        print("%-26s | %4d %5d %6d | 0x%-8X 0x%-8X %6d | %d/%d mit TM_-ID"
              % (path.name[:26], len(normal), len(light), len(medium),
                 end3, declared, delta, with_id, len(all_records)))
    print("\n  A bestaetigt: %d/%d Saves (Blockende exakt)" % (a_ok, len(saves)))
    print("  B bestaetigt: %d/%d Saves (mindestens eine echte Creation-ID)" % (b_ok, len(saves)))

    print("\n" + "=" * 92)
    print("C) Body-Kopf: Pointer-Tabelle + String-Array (5 Kriterien)")
    print("=" * 92)
    print("%-26s | %-11s | %-7s | %-22s | %-10s | %-9s"
          % ("Save", "K1 p2=NB2", "K2 count", "K3 Status", "K4 druckbar", "K5 Ende"))
    c_ok = 0
    for path in saves:
        raw = PROVIDER.decompress(str(path))
        header = PROVIDER.parse_dat_header(raw)
        end = header.plugin_info_offset + header.plugin_info_size
        unknown0, = struct.unpack_from("<H", raw, end)
        pointers = list(struct.unpack_from("<12I", raw, end + 2))
        new_block2 = end + 2 + 48 + 52
        _, strings_offset, _ = struct.unpack_from("<3I", raw, new_block2)
        k1 = pointers[2] == new_block2
        count = None
        strings: list[str] = []
        status = "offset ausserhalb"
        endpos = 0
        if 0 < strings_offset < len(raw) - 4:
            count, = struct.unpack_from("<H", raw, strings_offset)
            strings, endpos, status = read_string_array(raw, strings_offset + 2, count)
        printable = (sum(1 for s in strings if s and all(ch.isprintable() for ch in s))
                     / len(strings)) if strings else 0.0
        k5 = bool(strings) and endpos < len(raw)
        if k1 and status == "ok" and printable > 0.9 and k5:
            c_ok += 1
        print("%-26s | %-11s | %-7s | %-22s | %10.3f | %-9s"
              % (path.name[:26], k1, count, status, printable, k5))
    print("\n  C bestaetigt: %d/%d Saves (alle fuenf Kriterien)" % (c_ok, len(saves)))

    print("\n" + "-" * 92)
    ok = a_ok == len(saves) and c_ok == len(saves)
    print("GESAMT: %s" % ("alle Aussagen bestaetigt" if ok else "mindestens eine Aussage widerlegt"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
