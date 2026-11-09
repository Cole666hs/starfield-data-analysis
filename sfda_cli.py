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
from ssb_i.savegame_provider import public_header_view  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


class CliError(RuntimeError):
    """Kontrollierter Abbruch mit benutzerlesbarer Meldung."""


# ----------------------------------------------------------------------------
# Ausgabe
# ----------------------------------------------------------------------------
def emit_json(payload: object) -> None:
    """Schreibt genau ein JSON-Dokument auf stdout.

    Fehlt stdout (PyInstaller ohne Konsolenfenster), weicht die Ausgabe auf
    stderr aus: sonst ginge die Fehlerinformation verloren, obwohl ein Kanal
    vorhanden ist. Der Vertrag „stdout enthaelt genau ein JSON-Dokument" bleibt
    gewahrt, weil stdout in diesem Fall gar nicht existiert.

    Gibt es auch stderr nicht, wird nichts ausgegeben — der Exit-Code traegt
    dann allein die Information, es wird **nicht** so getan, als waere die
    Ausgabe erfolgt.
    """
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if _write_line("stdout", text):
        return
    _write_line("stderr", text)


def _write_line(stream_name: str, text: str) -> bool:
    """Schreibt eine Zeile auf den benannten Stream, falls er existiert.

    ``sys.stdout`` und ``sys.stderr`` koennen ``None`` sein — das ist der Fall
    bei einem PyInstaller-Bundle ohne Konsolenfenster (``console=False``) und
    bei GUI-Anwendungen unter Windows. Ein ``print(..., file=None)`` waere
    stiller Verlust der Meldung.

    Der Rueckfall geht auf ``sys.__stdout__``/``sys.__stderr__``: das sind die
    originalen Streams, die auch dann noch existieren, wenn die Anwendung
    ``sys.stdout`` bewusst auf ``None`` gesetzt hat.

    Rueckgabe: True, wenn die Zeile auf einem Stream gelandet ist.
    """
    stream = getattr(sys, stream_name, None)
    if stream is None:
        stream = getattr(sys, "__%s__" % stream_name, None)
    if stream is None:
        return False
    try:
        print(text, file=stream, flush=True)
    except Exception:                                          # noqa: BLE001
        return False
    return True


def emit_error_line(text: str) -> bool:
    """Fehlerzeile auf stderr — mit Rueckfall, wenn stderr fehlt.

    Wird der Fehlerkanal komplett vermisst (kein stdout und kein stderr),
    geht die Zeile an ``sys.__stderr__``; ist auch das nicht vorhanden, gibt
    es keinen Kanal — dann wird **nichts** behauptet und nichts ausgegeben.
    """
    if _write_line("stderr", text):
        return True
    return _write_line("stdout", text)


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
        # R1_6 / F-6: kein Dateiname in der oeffentlichen Fehlerzeile.
        # Die Ursache bleibt kontrolliert verstaendlich.
        raise CliError(f"Savegame nicht lesbar: {_public_error(exc)}") from exc
    return provider, container, header, plugins, len(decompressed)


def cmd_save_info(args) -> int:
    _provider, container, header, plugins, size = _load_save(args.save)
    # R1_6: die oeffentliche Sicht kommt aus public_header_view() — ohne
    # Spielername, Ort, Rasse und Spielzeit (O-5, W-1). Der absolute Pfad
    # des Saves wird nicht ausgegeben (F-2).
    public_header = public_header_view(header)
    payload = {
        "container": container.to_dict(),
        "savegame": {
            "player_level": header.player_level,
            "save_version": header.save_version,
            "game_version": header.current_game_version,
            "created_game_version": header.created_game_version,
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
    # R1_6: kein Spielername, kein Ort, keine Spielzeit, kein Dateiname
    # (W-1, O-5, F-2). Die uebrigen fachlichen Metadaten bleiben.
    emit_lines([
        ("Level", f"{s['player_level']}"),
        ("Save version", s["save_version"]),
        ("Game version", s["game_version"]),
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
    # R1_6: ausschliesslich die kontrollierte oeffentliche Headeransicht.
    # asdict(header) (die vollstaendige interne Repräsentation) wird hier
    # NICHT mehr verwendet.
    data = public_header_view(header)
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
        raise CliError(f"differential failed: {_public_error(exc)}") from exc

    if args.markdown:
        out = Path(args.markdown)
        try:
            out.write_text(markdown_report(report), encoding="utf-8")
        except OSError as exc:
            raise CliError(f"markdown report not writable: {_public_error(exc)}") from exc
        print(f"Markdown report: {out}", file=sys.stderr)

    if args.json:
        emit_json(report)
        return EXIT_OK
    analysis = report.get("analysis") or {}
    sizes = analysis.get("sizes") or {}
    # R1_6 / F-2: keine Savegame-Dateinamen in der oeffentlichen Ausgabe.
    # Die Byte-Zahlen identifizieren die Vergleiche ausreichend.
    emit_lines([
        ("A size", f"{sizes.get('a', '?')} Bytes"),
        ("B size", f"{sizes.get('b', '?')} Bytes"),
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
def _public_error(exc: BaseException) -> str:
    """Oeffentlicher Fehlertext — zentral, ohne lokale Dateipfade."""
    from ssb_i.errors import public_error
    return public_error(exc)


def _cli_error_text(exc: CliError) -> str:
    """Text eines ``CliError`` fuer die oeffentliche Ausgabe.

    ``CliError``-Meldungen werden an der Raise-Stelle aus oeffentlichen Teilen
    zusammengesetzt (``public_error`` plus der vom Nutzer aufgerufene
    Dateiname). Sie hier erneut durch ``public_error`` zu schicken wuerde jede
    Meldung auf ``CliError`` verkuerzen.
    """
    return str(exc)


def _exit_code_of(exc: SystemExit) -> int:
    """Exit-Code eines ``SystemExit`` — reine Pruefung, keine Ausgabe."""
    code = exc.code
    return code if isinstance(code, int) else EXIT_ERROR


def _finish_error(message: str, use_json: bool, code: int = EXIT_ERROR) -> int:
    """Gibt eine Fehlermeldung aus und liefert den Exit-Code.

    R1_6 / F-6: ``message`` stammt ausschliesslich aus kontrollierten
    Quellen — ``_cli_error_text(exc)``, ``_public_error(exc)`` oder
    einem statischen Literal. Dateinamen und Pfade stehen nicht darin.
    """
    """Gibt einen Abbruch aus und liefert den Exit-Code.

    Bei ``--json`` geht genau ein JSON-Dokument auf stdout (Feld ``error`` wie
    in den Befund-Evidenzen des Berichts), sonst die bekannte ``ERROR:``-Zeile
    auf stderr. Ein Traceback entsteht in keinem Fall.

    Fehlt der Stream (PyInstaller ohne Konsolenfenster, ``sys.stdout``/
    ``sys.stderr`` sind ``None``), wird ueber :func:`emit_error_line` der
    Rueckfallweg benutzt. Gibt es **keinen** Kanal, wird nichts ausgegeben —
    aber der Exit-Code bleibt der des Fehlers, ein stiller Fehler wird also
    nicht als Erfolg gemeldet.
    """
    if use_json:
        emit_json({"error": message, "exit_code": code})
    else:
        emit_error_line(f"ERROR: {message}")
    return code


def _load_pe(path: str):
    from ssb_i.ssb_pe_lib import PE, PEIntegrityError

    src = _require_file(path, "binary")
    try:
        return PE(src)
    except PEIntegrityError as exc:
        # R1_6 / F-6: kein Dateiname in der oeffentlichen Fehlerzeile.
        raise CliError(f"not a valid PE32+ image: {_public_error(exc)}") from exc
    except OSError as exc:
        raise CliError(f"binary not readable: {_public_error(exc)}") from exc


def cmd_save_verify(args) -> int:
    from ssb_i.save_integrity import (FAILED, collect_sequence, format_text,
                                      format_sequence_summary, run_all)

    src = _require_file(args.save, "Savegame")

    # I-14 braucht Vergleichsdaten. collect_sequence() waehlt die Saves im
    # Verzeichnis aus und gibt sie in Dateinamen-Reihenfolge zurueck; die
    # chronologische Reihenfolge stellt erst check_i14_sequence() her, anhand
    # des FileTime-Werts aus dem Header. mtime entscheidet nur darueber, welche
    # Dateien bei mehr als 64 Saves ueberhaupt gelesen werden.
    sequence: tuple = ()
    if not args.no_sequence:
        try:
            sequence = collect_sequence(src, directory=args.sequence_dir)
        except (OSError, ValueError) as exc:
            print(f"Sequenz nicht sammelbar: {_public_error(exc)}",
                  file=sys.stderr)
            sequence = ()

    try:
        report = run_all(src, data_dir=args.data_dir, sequence=sequence)
    except (ValueError, OSError) as exc:
        # R1_6 / F-6: kein Dateiname in der oeffentlichen Fehlerzeile.
        raise CliError(f"integrity check failed: {_public_error(exc)}") from exc
    if args.json:
        emit_json(report.to_dict())
    else:
        print(format_text(report))
        if args.no_sequence:
            print("\nSequenz: abgeschaltet (--no-sequence), I-14 nicht geprueft.")
        else:
            print("\nSequenz: %d Save(s) einbezogen (chronologisch nach Header-FileTime)."
                  % len(sequence))
            for line in format_sequence_summary(report):
                print(line)
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
        # R1_6 / F-2: kein absoluter Pfad in oeffentlichen Ausgaben.
        # Der SHA-256 identifiziert die Datei hinreichend.
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
        # R1_6 / F-2: kein absoluter Pfad in oeffentlichen Ausgaben.
        emit_json({"sha256": pe.sha256, "sections": rows})
        return EXIT_OK
    print(f"{'Name':<10}{'RVA':>12}{'VSize':>12}{'RawSize':>12}{'RawOff':>12}")
    for r in rows:
        print(f"{r['name']:<10}{hex(r['rva']):>12}{r['virtual_size']:>12}"
              f"{r['raw_size']:>12}{hex(r['raw_offset']):>12}")
    return EXIT_OK


# ----------------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------------
class _QuietParser(argparse.ArgumentParser):
    """``ArgumentParser``, der seinen Nutzungsfehler nicht selbst ausgibt.

    ``argparse`` schreibt bei einem Aufruffehler den Usage-Text und die
    Fehlermeldung **direkt auf stderr** und beendet sich mit ``SystemExit(2)``.
    Im JSON-Modus ist genau ein JSON-Dokument auf stdout gewuenscht — zusaetz-
    licher Text auf stderr wuerde den Vertrag brechen.

    Dieser Parser unterdrueckt daher die Fehlerausgabe. Die Entscheidung
    uebernimmt :func:`main`: sie erzeugt im JSON-Modus ein JSON-Dokument und
    im Textmodus den gewoehnlichen argparse-Text.

    Der Exit-Code bleibt unveraendert ``2``.
    """

    def error(self, message: str) -> None:          # type: ignore[override]
        raise _UsageError(message, self)


class _UsageError(Exception):
    """Nutzungsfehler von argparse — ohne eigene Ausgabe."""

    def __init__(self, message: str, parser: argparse.ArgumentParser) -> None:
        super().__init__(message)
        self.message = message
        self.parser = parser


def _build_parser_class(json_mode: bool):
    """Parserklasse waehlen — im JSON-Modus ohne eigene Fehlerausgabe."""
    if json_mode:
        return _QuietParser
    return argparse.ArgumentParser


def build_parser(json_mode: bool = False) -> argparse.ArgumentParser:
    """Baut den Argumentparser.

    ``json_mode`` schaltet die eigene Fehlerbehandlung ein: dann gibt der
    Parser keine eigene Fehlermeldung aus, sondern ``main`` erzeugt genau ein
    JSON-Dokument. Der Aufruf mit ``json_mode=True`` ist **ausschliesslich** fuer
    den JSON-Modus bestimmt; im Textmodus bleibt das argparse-Verhalten
    unveraendert.
    """
    parser_class = _build_parser_class(json_mode)
    parser = parser_class(
        prog=CLI_PROG,
        description=(f"{PRODUCT_NAME} - {PRODUCT_SUBTITLE}. "
                 f"{DEVELOPER}. All operations are read-only."),
    )
    parser.add_argument("--version", action="version",
                        version=f"{CLI_PROG} {VERSION} - {PRODUCT_NAME} ({DEVELOPER})")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable JSON output on stdout")
    sub = parser.add_subparsers(dest="group", required=True,
                                 parser_class=parser_class)

    save = sub.add_parser("save", help="inspect savegame files (.sfs)")
    save_sub = save.add_subparsers(dest="command", required=True,
                                    parser_class=parser_class)

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
    p_verify.add_argument("--sequence-dir", metavar="DIR",
                          help="Directory to collect saves from for the sequence check "
                               "(I-14). Default: the save's own directory.")
    p_verify.add_argument("--no-sequence", action="store_true",
                          help="Skip the sequence check (I-14 reports NOT_CHECKED).")
    p_verify.set_defaults(func=cmd_save_verify)

    p_strings = save_sub.add_parser("strings", help="read the body string pool (read-only)")
    p_strings.add_argument("save")
    p_strings.add_argument("--limit", type=int, default=40,
                           help="how many strings to print (default 40)")
    p_strings.add_argument("--all", action="store_true",
                           help="with --json: include every string")
    p_strings.set_defaults(func=cmd_save_strings)

    pe = sub.add_parser("pe", help="inspect PE32+ binaries (e.g. Starfield.exe)")
    pe_sub = pe.add_subparsers(dest="command", required=True,
                                parser_class=parser_class)

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
    """CLI-Einstieg mit zentraler Fehlergrenze.

    Jede unerwartete ``Exception`` (``struct.error``, ``ValueError``, ``OSError``
    und alles andere) endet hier kontrolliert: oeffentlicher Text ueber
    :func:`_public_error`, Exit-Code ``EXIT_ERROR``, bei ``--json`` genau ein
    JSON-Dokument auf stdout. ``KeyboardInterrupt`` und ``SystemExit`` werden
    nicht verschluckt.
    """
    raw_argv = list(sys.argv[1:]) if argv is None else list(argv)
    # Vor dem Parsen bekannt: ein Nutzungsfehler soll bei --json ebenfalls JSON
    # liefern, obwohl ``args`` dann noch nicht existiert.
    wants_json = "--json" in raw_argv
    if wants_json:
        # Eigener Parser: er schreibt bei einem Nutzungsfehler **nichts** auf
        # stderr. Der Fehler kommt als JSON-Dokument auf stdout, sonst wuerde
        # der JSON-Vertrag durch zusaetzlichen Text gebrochen.
        parser = build_parser(json_mode=True)
        try:
            args = parser.parse_args(raw_argv)
        except _UsageError as exc:
            # Nutzungsfehler: genau ein JSON-Dokument, kein stderr-Text.
            emit_json({"error": "invalid command line", "exit_code": EXIT_USAGE})
            return EXIT_USAGE
        except SystemExit as exc:              # argparse: --help/--version
            # Exit 0 (--help/--version): keine Fehlerausgabe, der Exit-Wunsch
            # von argparse bleibt unveraendert.
            return _exit_code_of(exc)
        use_json = bool(getattr(args, "json", False))
        try:
            return args.func(args)
        except CliError as exc:
            return _finish_error(_cli_error_text(exc), use_json)
        except KeyboardInterrupt:
            return _finish_error("Aborted.", use_json)
        except Exception as exc:                           # noqa: BLE001
            return _finish_error(_public_error(exc), use_json)

    parser = build_parser()
    try:
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:                  # argparse: --help/--version/Fehler
        code = _exit_code_of(exc)
        if code and wants_json:
            emit_json({"error": "invalid command line", "exit_code": code})
        raise                                  # Exit-Wunsch von argparse bleibt
    use_json = bool(getattr(args, "json", False))
    try:
        return args.func(args)
    except CliError as exc:
        # CliError-Texte werden bereits beim Bau aus oeffentlichen Teilen
        # zusammengesetzt (public_error + Dateiname) und hier unveraendert
        # ausgegeben.
        return _finish_error(_cli_error_text(exc), use_json)
    except KeyboardInterrupt:
        return _finish_error("Aborted.", use_json)
    except Exception as exc:                               # noqa: BLE001
        # Zentrale Fehlergrenze: kein Traceback, kein interner Text, aber die
        # Fehlerklasse bleibt sichtbar.
        return _finish_error(_public_error(exc), use_json)


if __name__ == "__main__":
    raise SystemExit(main())
