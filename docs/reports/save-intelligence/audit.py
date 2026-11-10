"""SAVE INTELLIGENCE — reproduzierbare Audit-Messungen für Starfield .sfs Savegames.

READ-ONLY. Es wird keine Datei geschrieben außer Kopien unter --work (nur für
den Korruptions-Test). Original-Saves werden ausschließlich gelesen.

Aufruf (aus dem Repo-Wurzelverzeichnis):
    python audit/save-intelligence/audit.py inventory
    python audit/save-intelligence/audit.py integrity
    python audit/save-intelligence/audit.py perf
    python audit/save-intelligence/audit.py dupes
    python audit/save-intelligence/audit.py regions
    python audit/save-intelligence/audit.py scan
    python audit/save-intelligence/audit.py all

Referenz-Saves: Verzeichnis über SAVE_PROBES (Default ~/ssb_probes).
Der Unterordner saves_07oct_2026 wird verwendet, wenn vorhanden.

Alle Zahlen in SAVE_INTELLIGENCE_AUDIT.md stammen aus diesem Werkzeug
(Konsole: Python 3.13.14, gemessen 08.11.2026).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import statistics
import struct
import sys
import time
import zlib
from pathlib import Path

# O-11: the script moved from ``audit/save-intelligence/`` to
# ``docs/reports/save-intelligence/`` — one level deeper, so the repository
# root is one ``parents`` level further up.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ssb_i.savegame_differential import analyze_paths          # noqa: E402
from ssb_i.savegame_provider import SfsDecodeProvider          # noqa: E402

PROBES = Path(os.environ.get("SAVE_PROBES", Path.home() / "ssb_probes"))
SAVES_07OCT = PROBES / "saves_07oct_2026"


def all_saves() -> list[Path]:
    """Alle .sfs unter PROBES (ohne die .payload/.decomp-Beidateien)."""
    found: list[Path] = []
    for root in (SAVES_07OCT, PROBES):
        if not root.is_dir():
            continue
        for entry in sorted(os.listdir(root)):
            path = root / entry
            if path.suffix == ".sfs" and path.is_file():
                found.append(path)
    return found


def real_saves() -> list[Path]:
    """Nur Saves mit Starfield-Dateinamen (ssbm_*-Kopien fallen heraus)."""
    return [p for p in all_saves() if not p.name.startswith("ssbm_")]


def geometry(path: Path) -> dict:
    """Container-Geometrie direkt aus dem Dateikopf (ohne Dekompression)."""
    with open(path, "rb") as handle:
        data = handle.read()
    chunk_sizes_offset, = struct.unpack_from("<q", data, 8)
    compressed_offset, = struct.unpack_from("<q", data, 24)
    uncompressed_size, = struct.unpack_from("<q", data, 32)
    chunk_size_pre, = struct.unpack_from("<q", data, 48)
    padding_size, = struct.unpack_from("<q", data, 56)
    count = (uncompressed_size + chunk_size_pre - 1) // chunk_size_pre
    sizes = list(struct.unpack_from("<%di" % count, data, chunk_sizes_offset))
    padded = [((s + padding_size - 1) & ~(padding_size - 1)) if padding_size else s
              for s in sizes]
    return {
        "chunk_sizes_offset": chunk_sizes_offset,
        "compressed_offset": compressed_offset,
        "uncompressed_size": uncompressed_size,
        "chunk_size_pre": chunk_size_pre,
        "padding_size": padding_size,
        "chunk_count": count,
        "table_end": chunk_sizes_offset + 4 * count,
        "sum_padded": sum(padded),
        "disk_rest": len(data) - compressed_offset,
        "disk_size": len(data),
        "sizes": sizes,
    }


# ---------------------------------------------------------------------------
# inventory — Ist-Zustand: liest jeden Save und listet alle Felder
# ---------------------------------------------------------------------------
def cmd_inventory(_args) -> int:
    provider = SfsDecodeProvider()
    files = all_saves()
    print("Datei | Player | Lvl | SaveVer | Eng | hdr | ploff | psize | pstate | n/l/m | "
          "unc_size | chunks | size_ok | tbl_ok | pad_ok")
    ok = 0
    for path in files:
        try:
            geom = geometry(path)
            raw = provider.decompress(str(path))
            header = provider.parse_dat_header(raw)
            plugins = provider.parse_plugin_info(raw, header)
            ok += 1
            print("%-40s | %-6s | %3d | %3d | %2d | %3d | %3d | %4d | %-9s | %d/%d/%d | "
                  "%d | %d | %s | %s | %s" % (
                      path.name[:40], header.player_name, header.player_level,
                      header.save_version, header.engine_version, header.header_size,
                      header.plugin_info_offset, header.plugin_info_size,
                      plugins.decode_state, len(plugins.normal), len(plugins.light),
                      len(plugins.medium), geom["uncompressed_size"], geom["chunk_count"],
                      len(raw) == geom["uncompressed_size"],
                      geom["table_end"] == geom["compressed_offset"],
                      geom["sum_padded"] == geom["disk_rest"]))
        except Exception as exc:                     # noqa: BLE001 — Audit soll weiterlaufen
            print("%-40s | ERROR %s: %s" % (path.name[:40], type(exc).__name__, exc))
    print("\nSaves: %d, lesbar: %d, Fehler: %d" % (len(files), ok, len(files) - ok))
    return 0


# ---------------------------------------------------------------------------
# integrity — Korruptionsmatrix auf Kopien
# ---------------------------------------------------------------------------
def cmd_integrity(args) -> int:
    provider = SfsDecodeProvider()
    sources = real_saves()
    if not sources:
        print("Keine Referenz-Saves unter %s" % PROBES)
        return 2
    src = sources[0]
    work = Path(args.work) if args.work else Path("/tmp/sfda-save-audit")
    work.mkdir(parents=True, exist_ok=True)
    base = src.read_bytes()
    base_sha = hashlib.sha256(base).hexdigest()
    print("Quelle: %s (%d Bytes)" % (src.name, len(base)))

    def probe(label: str, data: bytes) -> None:
        path = work / ("%s.sfs" % label.replace(" ", "_"))
        path.write_bytes(data)
        steps = []
        try:
            container = provider.read_container(str(path))
        except Exception as exc:                     # noqa: BLE001
            print("%-26s | FAILED  read_container: %s: %s"
                  % (label, type(exc).__name__, str(exc)[:60]))
            return
        try:
            raw = provider.decompress(str(path))
        except Exception as exc:                     # noqa: BLE001
            print("%-26s | FAILED  decompress: %s: %s"
                  % (label, type(exc).__name__, str(exc)[:70]))
            return
        steps.append("len=%d/%d" % (len(raw), container.uncompressed_size))
        try:
            header = provider.parse_dat_header(raw)
            info = provider.parse_plugin_info(raw, header)
            steps.append("%s n=%d" % (info.decode_state, len(info.normal)))
        except Exception as exc:                     # noqa: BLE001
            steps.append("header/plugin %s" % type(exc).__name__)
        silent = len(raw) != container.uncompressed_size
        print("%-26s | %s  %s"
              % (label, "SILENT  " if silent else "accepted", " | ".join(steps)))

    print("\n%-26s | Ergebnis" % "Fall")
    probe("intact", base)
    probe("A truncate -1000B", base[:-1000])
    probe("B truncate -50%", base[:len(base) // 2])
    flipped = bytearray(base); flipped[5000] ^= 0xFF
    probe("C bitflip comp@5000", bytes(flipped))
    flipped = bytearray(base); flipped[-500] ^= 0xFF
    probe("D bitflip last-chunk", bytes(flipped))
    tampered = bytearray(base)
    unc, = struct.unpack_from("<q", tampered, 32)
    struct.pack_into("<q", tampered, 32, unc + 1)
    probe("E unc_size+1", bytes(tampered))
    tampered = bytearray(base)
    struct.pack_into("<q", tampered, 48, 262144 * 2)
    probe("F chunk_pre x2", bytes(tampered))
    tampered = bytearray(base)
    size0, = struct.unpack_from("<i", tampered, 72)
    struct.pack_into("<i", tampered, 72, size0 + 4)
    probe("G chunk0 size+4", bytes(tampered))
    tampered = bytearray(base); tampered[0:4] = b"XXXX"
    probe("H bad magic", bytes(tampered))
    probe("I header only 512B", base[:512])
    tampered = bytearray(base); tampered[100:] = b"\x00" * (len(tampered) - 100)
    probe("J zeros after byte 100", bytes(tampered))
    tampered = bytearray(base); struct.pack_into("<q", tampered, 56, 0)
    probe("L padding=0", bytes(tampered))
    tampered = bytearray(base); struct.pack_into("<q", tampered, 24, 448)
    probe("M comp_offset=448", bytes(tampered))

    print("\nOriginal unverändert: %s"
          % (hashlib.sha256(src.read_bytes()).hexdigest() == base_sha))
    return 0


# ---------------------------------------------------------------------------
# perf — Phasen-Zeiten und Scan-Kosten
# ---------------------------------------------------------------------------
def cmd_perf(args) -> int:
    provider = SfsDecodeProvider()
    files = all_saves()[:args.limit]
    print("%-28s | %8s | %9s | %7s | %8s | %8s"
          % ("Datei", "read_ms", "decomp_ms", "hdr_ms", "plug_ms", "total_ms"))
    totals = []
    for path in files:
        sum_read = sum_dec = sum_hdr = sum_plug = 0.0
        for _ in range(args.reps):
            t0 = time.perf_counter(); provider.read_container(str(path))
            t1 = time.perf_counter(); raw = provider.decompress(str(path))
            t2 = time.perf_counter(); header = provider.parse_dat_header(raw)
            t3 = time.perf_counter(); provider.parse_plugin_info(raw, header)
            t4 = time.perf_counter()
            sum_read += (t1 - t0) * 1000
            sum_dec += (t2 - t1) * 1000
            sum_hdr += (t3 - t2) * 1000
            sum_plug += (t4 - t3) * 1000
        total = (sum_read + sum_dec + sum_hdr + sum_plug) / args.reps
        totals.append(total)
        print("%-28s | %8.2f | %9.2f | %7.3f | %8.3f | %8.2f" % (
            path.name[:28], sum_read / args.reps, sum_dec / args.reps,
            sum_hdr / args.reps, sum_plug / args.reps, total))
    print("\nMittel %.2f ms | Median %.2f ms | max %.2f ms | n=%d"
          % (statistics.mean(totals), statistics.median(totals), max(totals), len(totals)))
    print("Hochrechnung 100 Saves (volle Dekompression): %.2f s"
          % (statistics.mean(totals) * 100 / 1000))
    return 0


# ---------------------------------------------------------------------------
# dupes — Hash- und Ähnlichkeitsprüfung
# ---------------------------------------------------------------------------
def cmd_dupes(_args) -> int:
    provider = SfsDecodeProvider()
    files = all_saves()
    by_file, by_payload = {}, {}
    for path in files:
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        payload_hash = hashlib.sha256(provider.decompress(str(path))).hexdigest()
        by_file.setdefault(file_hash, []).append(path.name)
        by_payload.setdefault(payload_hash, []).append(path.name)
    print("Datei-Hashes   : %d distinkt von %d" % (len(by_file), len(files)))
    print("Payload-Hashes : %d distinkt von %d" % (len(by_payload), len(files)))
    for label, table in (("DATEI", by_file), ("PAYLOAD", by_payload)):
        for _hash, names in table.items():
            if len(names) > 1:
                print("  %s-DUPLIKAT: %s" % (label, names))

    payloads = {p.name: provider.decompress(str(p)) for p in real_saves()}
    names = sorted(payloads)
    print("\nPaarweise Byte-Differenz (echte Saves):")
    print("%-24s | %-24s | %10s | %7s" % ("A", "B", "diff", "ratio%"))
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            a, b = payloads[left], payloads[right]
            limit = min(len(a), len(b))
            diff = sum(1 for k in range(limit) if a[k] != b[k]) + abs(len(a) - len(b))
            print("%-24s | %-24s | %10d | %6.2f"
                  % (left[:24], right[:24], diff, diff / max(len(a), len(b)) * 100))
    return 0


# ---------------------------------------------------------------------------
# regions — Differential getrennt nach Header/Plugin und Body
# ---------------------------------------------------------------------------
def cmd_regions(_args) -> int:
    provider = SfsDecodeProvider()
    sources = real_saves()
    if len(sources) < 2:
        print("Mindestens zwei Referenz-Saves nötig")
        return 2
    print("Vorhandenes analyze_paths() auf echten Save-Paaren:")
    for index in range(min(3, len(sources) - 1)):
        left, right = sources[-1], sources[index]
        report = analyze_paths(str(left), str(right))
        analysis = report["analysis"]
        left_raw = provider.decompress(str(left))
        right_raw = provider.decompress(str(right))
        left_header = provider.parse_dat_header(left_raw)
        right_header = provider.parse_dat_header(right_raw)
        head_end = max(left_header.plugin_info_offset + left_header.plugin_info_size,
                       right_header.plugin_info_offset + right_header.plugin_info_size)
        limit = min(len(left_raw), len(right_raw))
        head_diff = sum(1 for i in range(min(head_end, limit)) if left_raw[i] != right_raw[i])
        body_diff = sum(1 for i in range(head_end, limit) if left_raw[i] != right_raw[i])
        body_len = limit - head_end
        print("\n  %s  vs  %s" % (left.name[:26], right.name[:26]))
        print("    Header+Plugin: %6d B, %6d verschieden (%6.2f %%)"
              % (head_end, head_diff, head_diff / max(head_end, 1) * 100))
        print("    Body         : %6d B, %6d verschieden (%6.2f %%)"
              % (body_len, body_diff, body_diff / max(body_len, 1) * 100))
        print("    Urteil analyze_paths: %s | ratio %.4f | Cluster %d | %s"
              % (report["result"], analysis["differing_ratio"],
                 len(analysis["clusters"]),
                 analysis["noise_assessment"]["classification"]))
    return 0


# ---------------------------------------------------------------------------
# scan — Kosten eines Verzeichnis-Scans über den ersten Chunk
# ---------------------------------------------------------------------------
def cmd_scan(args) -> int:
    provider = SfsDecodeProvider()
    sources = real_saves()
    if not sources:
        print("Keine Referenz-Saves unter %s" % PROBES)
        return 2
    src = sources[0]
    data = src.read_bytes()
    chunk_sizes_offset, = struct.unpack_from("<q", data, 8)
    compressed_offset, = struct.unpack_from("<q", data, 24)
    first_size, = struct.unpack_from("<i", data, chunk_sizes_offset)

    def first_chunk() -> bytes:
        return zlib.decompress(data[compressed_offset:compressed_offset + first_size])

    t0 = time.perf_counter()
    for _ in range(args.reps):
        first_chunk()
    first_ms = (time.perf_counter() - t0) / args.reps * 1000
    t0 = time.perf_counter()
    for _ in range(args.reps):
        provider.decompress(str(src))
    full_ms = (time.perf_counter() - t0) / args.reps * 1000
    print("Chunk 0 (%d B)  : %7.2f ms" % (first_size, first_ms))
    print("volle Datei     : %7.2f ms  (Faktor %.1f)" % (full_ms, full_ms / first_ms))
    print("100 Saves: Chunk-0 %.2f s | voll %.2f s"
          % (first_ms * 100 / 1000, full_ms * 100 / 1000))

    raw = first_chunk()
    print("\nHeader vollständig aus Chunk 0?")
    print("  beginnt mit SFS_SAVEGAME: %s" % (raw[:12] == b"SFS_SAVEGAME"))
    header = provider.parse_dat_header(raw)
    plugins = provider.parse_plugin_info(raw, header)
    print("  Header: player=%s lvl=%d | Plugins: %s n=%d l=%d"
          % (header.player_name, header.player_level, plugins.decode_state,
             len(plugins.normal), len(plugins.light)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inventory", help="Ist-Zustand: alle Saves, alle Felder").set_defaults(
        func=cmd_inventory)

    integrity = sub.add_parser("integrity", help="Korruptionsmatrix auf Kopien")
    integrity.add_argument("--work", help="Zielordner für Kopien (Default /tmp/sfda-save-audit)")
    integrity.set_defaults(func=cmd_integrity)

    perf = sub.add_parser("perf", help="Phasen-Zeiten")
    perf.add_argument("--reps", type=int, default=3)
    perf.add_argument("--limit", type=int, default=100)
    perf.set_defaults(func=cmd_perf)

    sub.add_parser("dupes", help="Hash- und Ähnlichkeitsprüfung").set_defaults(func=cmd_dupes)
    sub.add_parser("regions", help="Differential nach Regionen").set_defaults(func=cmd_regions)

    scan = sub.add_parser("scan", help="Scan-Kosten über den ersten Chunk")
    scan.add_argument("--reps", type=int, default=10)
    scan.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    if args.command == "all":
        for func in (cmd_inventory, cmd_integrity, cmd_perf, cmd_dupes, cmd_regions, cmd_scan):
            print("\n" + "=" * 70)
            func(argparse.Namespace(work=None, reps=3, limit=10))
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
