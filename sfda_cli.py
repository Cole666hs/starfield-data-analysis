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
        "plugins": {
            "decode_state": plugins.decode_state,
            "normal": len(plugins.normal),
            "light": len(plugins.light),
            "medium": len(plugins.medium),
            "note": plugins.note,
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
                     f"{len(plugins.medium)} medium"),
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
            native = "native" if entry.get("is_native") else "plugin"
            print(f"  - {entry['name']}  [{native}]")
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

    src = _require_file(path, "Binärdatei")
    try:
        return PE(src)
    except PEIntegrityError as exc:
        raise CliError(f"{src.name}: not a valid PE32+ image: {exc}") from exc
    except OSError as exc:
        raise CliError(f"{src.name}: not readable: {exc}") from exc


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
        description=(f"{PRODUCT_NAME} — {PRODUCT_SUBTITLE}. "
                 f"{DEVELOPER}. All operations are read-only."),
    )
    parser.add_argument("--version", action="version",
                        version=f"{CLI_PROG} {VERSION} — {PRODUCT_NAME} ({DEVELOPER})")
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
