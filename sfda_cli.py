#!/usr/bin/env python3
"""sfda_cli.py — Starfield Data Analysis command line (offline, read-only).

Runs the inspection functions without the GUI and without a running game:

    sfda save info    <save.sfs>     container + savegame header + plugin counts
    sfda save header  <save.sfs>     full SFS_SAVEGAME header
    sfda save plugins <save.sfs>     plugin list (normal/light/medium)
    sfda save diff    <a> <b>        byte-level differential of two saves
    sfda pe info      <exe>          PE header, sections, integrity
    sfda pe sections  <exe>          section table only

Grundsätze:
  * Eingabedateien werden ausschließlich gelesen.
  * Unbekannte Strukturen werden NICHT geraten: lieber ``UNVERIFIED`` mit
    Begründung als eine erfundene Liste.
  * Exit-Codes: 0 = Erfolg, 1 = Analyse-/Eingabefehler, 2 = Aufruffehler.
  * ``--json`` liefert maschinenlesbare Ausgabe auf stdout; Meldungen gehen
    immer nach stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Eigener Pfad zuerst, damit der Aufruf aus jedem Arbeitsverzeichnis und aus
# einem entpackten Release-Ordner funktioniert (kein PYTHONPATH nötig).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssb_i.product import (  # noqa: E402
    CLI_PROG, DEVELOPER, PRODUCT_NAME, PRODUCT_SUBTITLE, VERSION,
)

EXIT_OK = 0
EXIT_ERROR = 1


class CliError(RuntimeError):
    """Kontrollierter Abbruch mit benutzerlesbarer Meldung."""


# ----------------------------------------------------------------------------
# Ausgabe
# ----------------------------------------------------------------------------
def emit_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def emit_lines(pairs: list[tuple[str, object]]) -> None:
    width = max(len(k) for k, _ in pairs) if pairs else 0
    for key, value in pairs:
        print(f"{key:<{width}}  {value}")


# ----------------------------------------------------------------------------
# Savegame-Zugriff
# ----------------------------------------------------------------------------
def _require_file(path: str, what: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise CliError(f"{what} not found: {p}")
    if not p.is_file():
        raise CliError(f"{what} is not a file: {p}")
    return p


def _load_save(path: str):
    """Dekodiert ein Savegame. Rückgabe: (provider, container, header, plugins, size)."""
    from ssb_i.savegame_provider import SfsDecodeProvider

    provider = SfsDecodeProvider()
    src = _require_file(path, "Savegame")
    try:
        container = provider.read_container(str(src))
        decompressed = provider.decompress(str(src))
        header = provider.parse_dat_header(decompressed)
        plugins = provider.parse_plugin_info(decompressed, header)
    except CliError:
        raise
    except (ValueError, OSError) as exc:
        raise CliError(f"{src.name}: {type(exc).__name__}: {exc}") from exc
    return provider, container, header, plugins, len(decompressed)


def cmd_save_info(args) -> int:
    _provider, container, header, plugins, size = _load_save(args.save)
    payload = {
        "file": str(Path(args.save).resolve()),
        "container": container.to_dict(),
        "savegame": {
            "player_name": header.player_name,
            "player_level": header.player_level,
            "player_location": header.player_location,
            "save_version": header.save_version,
            "game_version": header.current_game_version,
            "created_game_version": header.created_game_version,
            "playtime": header.playtime,
            "race": header.race_name,
        },
        "decompressed_bytes": size,
        # Schema aus 1.0.0 bleibt gueltig (Zahlen je Kette). Die neuen Felder
        # (total, categories, metadata, block) kommen additiv dazu; die
        # vollstaendige Eintragsliste steht unter "entries".
        "plugins": {
            "decode_state": plugins.decode_state,
            "normal": len(plugins.normal),
            "light": len(plugins.light),
            "medium": len(plugins.medium),
            "note": plugins.note,
            "total": plugins.total,
            "declared": {
                "normal": plugins.declared_normal,
                "light": plugins.declared_light,
                "medium": plugins.declared_medium,
            },
            "categories": {"game": plugins.game_count, "mod": plugins.mod_count},
            "metadata": {
                "present": plugins.metadata_count,
                "unreadable": plugins.unreadable_count,
            },
            "block": {
                "start": plugins.block_start,
                "end": plugins.block_end,
                "declared_end": plugins.block_end_declared,
                "delta": plugins.block_delta,
            },
            "entries": {
                "normal": [asdict(p) for p in plugins.normal],
                "light": [asdict(p) for p in plugins.light],
                "medium": [asdict(p) for p in plugins.medium],
            },
        },
    }
    if args.json:
        emit_json(payload)
        return EXIT_OK
    c = payload["container"]
    s = payload["savegame"]
    emit_lines([
        ("File", Path(args.save).name),
        ("Player", f"{s['player_name']} (level {s['player_level']})"),
        ("Location", s["player_location"]),
        ("Save version", s["save_version"]),
        ("Game version", s["game_version"]),
        ("Playtime", s["playtime"]),
        ("BCPS chunks", c["chunk_count"]),
        ("Decompressed", f"{size:,} bytes"),
        # Trennzeichen bewusst ASCII: die Windows-Konsole (cp850/cp1252) kennt
        # den Mittelpunkt '·' nicht und zeigt ihn als '?' — auf Windows gemessen
        # im Release-Build (Befund 05.11.2026).
        ("Plugins", f"{plugins.decode_state} | "
                     f"{len(plugins.normal)} normal | "
                     f"{len(plugins.light)} light | "
                     f"{len(plugins.medium)} medium | "
                     f"{plugins.total} total"),
        ("Plugin types", f"{plugins.game_count} game | {plugins.mod_count} mod | "
                         f"{plugins.metadata_count} with creation metadata"),
    ])
    if plugins.note:
        print(f"Note: {plugins.note}")
    return EXIT_OK


def cmd_save_header(args) -> int:
    _provider, _container, header, _plugins, _size = _load_save(args.save)
    data = header.to_dict()
    if args.json:
        emit_json(data)
        return EXIT_OK
    emit_lines([(k, v) for k, v in data.items()])
    return EXIT_OK


def cmd_save_plugins(args) -> int:
    _provider, _container, _header, plugins, _size = _load_save(args.save)
    data = plugins.to_dict()
    if args.json:
        emit_json(data)
        return EXIT_OK
    print(f"Plugin decode state: {data['decode_state']}")
    if data.get("note"):
        print(f"Note: {data['note']}")
    for group in ("normal", "light", "medium"):
        print(f"\n{group} ({len(data[group])}):")
        for entry in data[group]:
            kind = entry.get("category", "mod")
            marker = "native" if entry.get("is_native") else kind
            print(f"  - {entry['name']}  [{marker}]")
            if entry.get("metadata_state") == "present":
                print(f"      creation : {entry.get('creation_name') or '-'}")
                print(f"      id       : {entry.get('creation_id') or '-'}")
                print(f"      version  : {entry.get('version') or '-'}")
                if entry.get("achievement_friendly"):
                    print("      achievement friendly: yes")
            elif entry.get("metadata_state") == "unreadable":
                print(f"      metadata unreadable: {entry.get('detail')}")
    print(f"\nTotal: {data['counts']['total']} plugins "
          f"({data['categories']['game']} game, {data['categories']['mod']} mod)")
    return EXIT_OK


def cmd_save_diff(args) -> int:
    from ssb_i.savegame_differential import analyze_paths, markdown_report

    left = _require_file(args.left, "Savegame A")
    right = _require_file(args.right, "Savegame B")
    try:
        report = analyze_paths(str(left), str(right), max_gap=args.max_gap)
    except (ValueError, OSError) as exc:
        raise CliError(f"differential failed: {type(exc).__name__}: {exc}") from exc

    if args.markdown:
        out = Path(args.markdown)
        try:
            out.write_text(markdown_report(report), encoding="utf-8")
        except OSError as exc:
            raise CliError(f"markdown report not writable: {exc}") from exc
        print(f"Markdown report: {out}", file=sys.stderr)

    if args.json:
        emit_json(report)
        return EXIT_OK
    analysis = report.get("analysis") or {}
    sizes = analysis.get("sizes") or {}
    emit_lines([
        ("A", f"{left.name} ({sizes.get('a', '?')} Bytes)"),
        ("B", f"{right.name} ({sizes.get('b', '?')} Bytes)"),
        ("Differing bytes", analysis.get("differing_byte_count", "?")),
        ("Ratio", f"{analysis.get('differing_ratio', 0.0):.4%}"),
        ("Cluster", len(analysis.get("clusters") or [])),
        ("Result", report.get("result", "UNKNOWN")),
    ])
    if report.get("reason"):
        print(f"Reason: {report['reason']}")
    return EXIT_OK


# ----------------------------------------------------------------------------
# PE-Zugriff
# ----------------------------------------------------------------------------
def _load_pe(path: str):
    from ssb_i.ssb_pe_lib import PE, PEIntegrityError

    src = _require_file(path, "binary")
    try:
        return PE(src)
    except PEIntegrityError as exc:
        raise CliError(f"{src.name}: not a valid PE32+ image: {exc}") from exc
    except OSError as exc:
        raise CliError(f"{src.name}: not readable: {exc}") from exc


def cmd_save_verify(args) -> int:
    from ssb_i.save_integrity import FAILED, format_text, run_all

    src = _require_file(args.save, "Savegame")
    try:
        report = run_all(src, data_dir=args.data_dir)
    except (ValueError, OSError) as exc:
        raise CliError(f"{src.name}: {type(exc).__name__}: {exc}") from exc
    if args.json:
        emit_json(report.to_dict())
    else:
        print(format_text(report))
    return EXIT_ERROR if report.total == FAILED else EXIT_OK


def cmd_save_strings(args) -> int:
    from ssb_i.savegame_provider import SfsDecodeProvider

    provider, _container, header, plugins, _size = _load_save(args.save)
    payload = provider.decompress(str(args.save))
    pool = provider.read_string_pool(payload, header, plugins)
    if args.json:
        payload_out = dict(pool)
        if not args.all:
            payload_out["strings"] = pool["strings"][:args.limit]
            payload_out["truncated"] = len(pool["strings"]) > args.limit
        emit_json(payload_out)
        return EXIT_OK
    print(f"Status        {pool['status']}")
    print(f"Reason        {pool['reason']}")
    print(f"Array offset  0x{pool['string_array_offset'] or 0:X}")
    print(f"Strings       {pool['count']} (declared {pool['declared_count']})")
    print(f"Printable     {pool['printable_ratio']:.1%}")
    print(f"Note          {pool['note']}")
    print()
    for entry in pool["strings"][:args.limit]:
        print("  [%4d] 0x%08X  %s" % (entry["index"], entry["offset"], entry["text"]))
    if len(pool["strings"]) > args.limit:
        print("  ... %d weitere (--limit oder --all)" % (len(pool["strings"]) - args.limit))
    return EXIT_OK


def cmd_pe_info(args) -> int:
    from ssb_i.ssb_pe_lib import DEFAULT_TRUST_ROOT_SHA256

    pe = _load_pe(args.binary)
    payload = {
        "file": str(pe.path.resolve()),
        "sha256": pe.sha256,
        "image_base": hex(pe.image_base),
        "sections": [{"name": name, "rva": hex(va), "virtual_size": vsz, "raw_size": rsz}
                     for name, (va, vsz, rsz, _raw) in pe.sec.items()],
        "trust_root": {
            "expected": DEFAULT_TRUST_ROOT_SHA256,
            "match": pe.sha256 == DEFAULT_TRUST_ROOT_SHA256,
        },
    }
    if args.pdata:
        count = pe.build_pdata()
        payload["pdata_functions"] = count
    if args.json:
        emit_json(payload)
        return EXIT_OK
    pairs = [
        ("File", pe.path.name),
        ("SHA-256", pe.sha256),
        ("Image base", payload["image_base"]),
        ("Sections", len(payload["sections"])),
        ("Trust root", "match" if payload["trust_root"]["match"] else "no match (foreign or patched binary)"),
    ]
    if args.pdata:
        pairs.append((".pdata functions", payload["pdata_functions"]))
    emit_lines(pairs)
    if not payload["trust_root"]["match"]:
        print("Note: this file is not the documented original binary. "
              "The analysis works, but statements apply to this file only.")
    return EXIT_OK


def cmd_pe_sections(args) -> int:
    pe = _load_pe(args.binary)
    rows = [{"name": name, "rva": va, "virtual_size": vsz, "raw_size": rsz, "raw_offset": raw}
            for name, (va, vsz, rsz, raw) in pe.sec.items()]
    if args.json:
        emit_json({"file": str(pe.path.resolve()), "sections": rows})
        return EXIT_OK
    print(f"{'Name':<10}{'RVA':>12}{'VSize':>12}{'RawSize':>12}{'RawOff':>12}")
    for r in rows:
        print(f"{r['name']:<10}{hex(r['rva']):>12}{r['virtual_size']:>12}"
              f"{r['raw_size']:>12}{hex(r['raw_offset']):>12}")
    return EXIT_OK


# ----------------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=CLI_PROG,
        description=(f"{PRODUCT_NAME} - {PRODUCT_SUBTITLE}. "
                 f"{DEVELOPER}. All operations are read-only."),
    )
    parser.add_argument("--version", action="version",
                        version=f"{CLI_PROG} {VERSION} - {PRODUCT_NAME} ({DEVELOPER})")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON output on stdout")
    sub = parser.add_subparsers(dest="group", required=True)

    save = sub.add_parser("save", help="inspect savegame files (.sfs)")
    save_sub = save.add_subparsers(dest="command", required=True)

    p_info = save_sub.add_parser("info", help="container, header and plugin counts")
    p_info.add_argument("save")
    p_info.set_defaults(func=cmd_save_info)

    p_header = save_sub.add_parser("header", help="full savegame header")
    p_header.add_argument("save")
    p_header.set_defaults(func=cmd_save_header)

    p_plugins = save_sub.add_parser("plugins", help="plugin list")
    p_plugins.add_argument("save")
    p_plugins.set_defaults(func=cmd_save_plugins)

    p_diff = save_sub.add_parser("diff", help="compare two saves byte by byte")
    p_diff.add_argument("left")
    p_diff.add_argument("right")
    p_diff.add_argument("--max-gap", type=int, default=0,
                        help="gap in bytes within which diff offsets are merged into one "
                             "cluster (default 0 = exact)")
    p_diff.add_argument("--markdown", metavar="PATH",
                        help="also write a readable markdown report")
    p_diff.set_defaults(func=cmd_save_diff)

    p_verify = save_sub.add_parser("verify", help="integrity checks with status model")
    p_verify.add_argument("save")
    p_verify.add_argument("--data-dir", metavar="DIR",
                          help="Data directory for the plugin dependency check (I-12)")
    p_verify.set_defaults(func=cmd_save_verify)

    p_strings = save_sub.add_parser("strings", help="read the body string pool (read-only)")
    p_strings.add_argument("save")
    p_strings.add_argument("--limit", type=int, default=40,
                           help="how many strings to print (default 40)")
    p_strings.add_argument("--all", action="store_true",
                           help="with --json: include every string")
    p_strings.set_defaults(func=cmd_save_strings)

    pe = sub.add_parser("pe", help="inspect PE32+ binaries (e.g. Starfield.exe)")
    pe_sub = pe.add_subparsers(dest="command", required=True)

    p_pe_info = pe_sub.add_parser("info", help="header, sections, integrity")
    p_pe_info.add_argument("binary")
    p_pe_info.add_argument("--pdata", action="store_true",
                           help="also count the .pdata function table")
    p_pe_info.set_defaults(func=cmd_pe_info)

    p_pe_sec = pe_sub.add_parser("sections", help="section table")
    p_pe_sec.add_argument("binary")
    p_pe_sec.set_defaults(func=cmd_pe_sections)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Aborted.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
