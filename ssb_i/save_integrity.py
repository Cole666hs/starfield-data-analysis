"""ssb_i/save_integrity.py — Integritaetspruefung fuer Starfield-.sfs-Spielstaende.

Rein lesend. Es wird keine Datei geschrieben, nichts repariert, nichts
rekomprimiert. Jede Pruefung liefert einen eigenen Status; der Gesamtstatus ist
das schlechteste Einzelergebnis (kein Durchschnitt).

STATUSMODELL
    PASS        Kriterium erfuellt, durch mindestens einen Negativtest falsifiziert
    WARNING     auffaellig, aber nicht sicher als Beschaedigung klassifizierbar
    FAILED      deterministisch nachgewiesene Verletzung einer Strukturregel
    UNKNOWN     Formatsemantik nicht ausreichend bekannt
    NOT_CHECKED Pruefung nicht ausgefuehrt oder Voraussetzung fehlt

ABGRENZUNG
    Ein bestandener Lauf belegt strukturelle Integritaet. Er belegt NICHT, dass
    Starfield den Spielstand laden kann. Objekt-, FormID- und Skriptebene werden
    nicht geprueft (I-13 bleibt dauerhaft NOT_CHECKED).
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .savegame_provider import DatHeader, PluginInfo, SfsDecodeProvider

PASS = "PASS"
WARNING = "WARNING"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
NOT_CHECKED = "NOT_CHECKED"

#: Rang fuer die Aggregation: hoeher = schlechter.
SEVERITY = {PASS: 0, WARNING: 1, UNKNOWN: 2, NOT_CHECKED: 3, FAILED: 4}

DISCLAIMER = (
    "Diese Pruefung belegt strukturelle Integritaet. Sie belegt NICHT, dass "
    "Starfield den Spielstand laden kann. Objekt-, FormID- und Skriptebene "
    "werden nicht geprueft."
)

#: Belegte Werte fuer Save-Version 153 / Engine 27 (6 reale Saves).
GOLDEN_SAVE_VERSION = 153
GOLDEN_ENGINE_VERSION = 27
GOLDEN_CHUNK_SIZE_PRE = 262144
GOLDEN_PADDING = 16
GOLDEN_PLUGIN_COUNTS = {"normal": 25, "light": 50, "medium": 5}


@dataclass(frozen=True)
class CheckResult:
    """Ergebnis einer Einzelpruefung."""
    check_id: str
    title: str
    status: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    confidence: str = "deterministic"      # deterministic | heuristic | unverified

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class IntegrityReport:
    """Gesamtergebnis fuer eine Datei.

    Zwei getrennte Aussagen, damit weder „alles gut" noch „nichts geprueft"
    vorgetaeuscht wird:

      * ``total``  — schlechtester Status aus den Pruefungen, die tatsaechlich
                     eine Integritaetsaussage treffen (PASS/WARNING/FAILED).
                     Das ist das Integritaetsurteil.
      * ``total_with_gaps`` — schlechtester Status ueber ALLE Pruefungen,
                     inklusive UNKNOWN und NOT_CHECKED. Wer asketisch sein will,
                     nimmt diesen Wert.
      * ``gaps``   — die nicht bewertbaren Pruefungen mit Begruendung. Sie
                     werden nie verschwiegen, dominieren aber das Urteil nicht.
    """
    path: str
    file_size: int
    sha256: str
    total: str
    checks: tuple[CheckResult, ...]
    total_with_gaps: str = PASS
    gaps: tuple[CheckResult, ...] = ()
    disclaimer: str = DISCLAIMER

    def by_id(self, check_id: str) -> CheckResult | None:
        for check in self.checks:
            if check.check_id == check_id:
                return check
        return None

    @property
    def statuses(self) -> dict[str, str]:
        return {c.check_id: c.status for c in self.checks}

    @property
    def coverage(self) -> dict[str, int]:
        counts = {PASS: 0, WARNING: 0, FAILED: 0, UNKNOWN: 0, NOT_CHECKED: 0}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        counts["total"] = len(self.checks)
        counts["assessed"] = counts[PASS] + counts[WARNING] + counts[FAILED]
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_size": self.file_size,
            "sha256": self.sha256,
            "total": self.total,
            "total_with_gaps": self.total_with_gaps,
            "coverage": self.coverage,
            "checks": [c.to_dict() for c in self.checks],
            "gaps": [c.to_dict() for c in self.gaps],
            "disclaimer": self.disclaimer,
        }


@dataclass
class SaveContext:
    """Alle Zwischenergebnisse, die die Pruefungen gemeinsam nutzen."""
    path: str
    disk: bytes
    container: Any = None                  # SfsContainer
    geometry: dict[str, Any] = field(default_factory=dict)
    payload: bytes | None = None
    header: DatHeader | None = None
    plugin_info: PluginInfo | None = None
    load_errors: dict[str, str] = field(default_factory=dict)
    data_dir: str | None = None
    sequence: tuple[DatHeader, ...] = ()

    @property
    def file_size(self) -> int:
        return len(self.disk)

    @property
    def sha256(self) -> str:
        import hashlib
        return hashlib.sha256(self.disk).hexdigest()


def build_context(path: str | Path, *, data_dir: str | Path | None = None,
                  sequence: Sequence[DatHeader] = ()) -> SaveContext:
    """Laedt Datei und Parsergebnisse. Fehler werden gesammelt, nicht geworfen."""
    provider = SfsDecodeProvider()
    src = str(path)
    with open(src, "rb") as handle:
        disk = handle.read()
    ctx = SaveContext(path=src, disk=disk,
                      data_dir=str(data_dir) if data_dir else None,
                      sequence=tuple(sequence))

    try:
        ctx.container = provider.read_container(src)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["container"] = "%s: %s" % (type(exc).__name__, exc)
    try:
        ctx.geometry = provider.read_chunk_table(src)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["geometry"] = "%s: %s" % (type(exc).__name__, exc)
    try:
        # verify=False: I-06 prueft die Laenge selbst und meldet den Befund,
        # statt dass der Ladepfad mit einer Ausnahme abbricht.
        ctx.payload = provider.decompress(src, verify=False)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["payload"] = "%s: %s" % (type(exc).__name__, exc)
    if ctx.payload is not None:
        try:
            ctx.header = provider.parse_dat_header(ctx.payload)
        except Exception as exc:                               # noqa: BLE001
            ctx.load_errors["header"] = "%s: %s" % (type(exc).__name__, exc)
        if ctx.header is not None:
            try:
                ctx.plugin_info = provider.parse_plugin_info(ctx.payload, ctx.header)
            except Exception as exc:                           # noqa: BLE001
                ctx.load_errors["plugins"] = "%s: %s" % (type(exc).__name__, exc)
    return ctx


# ---------------------------------------------------------------------------
# Einzelpruefungen
# ---------------------------------------------------------------------------
def check_i01_magic(ctx: SaveContext) -> CheckResult:
    """I-01 — BCPS-Magic."""
    ok = ctx.disk[:4] == b"BCPS"
    return CheckResult(
        "I-01", "BCPS-Magic", PASS if ok else FAILED,
        "Container beginnt mit BCPS" if ok
        else "erste 4 Bytes sind %r, erwartet b'BCPS'" % ctx.disk[:4],
        {"magic": ctx.disk[:4].hex(), "expected": b"BCPS".hex()},
    )


def check_i02_compression(ctx: SaveContext) -> CheckResult:
    """I-02 — Kompressionstyp.

    Liest das Feld direkt aus der Datei, nicht ueber den Container-Ladepfad:
    bei einem unbekannten Verfahren wirft ``read_container`` bereits, und dann
    waere NOT_CHECKED die falsche Antwort — die Ursache ist ja bekannt.
    """
    compression = ctx.disk[68:72]
    evidence = {"compression": compression.decode("ascii", "replace")}
    if ctx.container is not None:
        evidence["container_error"] = None
    elif ctx.load_errors.get("container"):
        evidence["container_error"] = ctx.load_errors["container"]
    if compression == b"ZIP ":
        return CheckResult("I-02", "Kompressionstyp", PASS, "Kompression ZIP", evidence)
    return CheckResult("I-02", "Kompressionstyp", FAILED,
                       "Kompressionstyp %r wird nicht unterstuetzt"
                       % compression.decode("ascii", "replace"), evidence)


def check_i03_chunk_table(ctx: SaveContext) -> CheckResult:
    """I-03 — Chunk-Tabellen-Geometrie."""
    geom = ctx.geometry
    if not geom:
        return CheckResult("I-03", "Chunk-Tabellen-Geometrie", NOT_CHECKED,
                           "Geometrie nicht lesbar: %s"
                           % ctx.load_errors.get("geometry", "unbekannt"),
                           {"error": ctx.load_errors.get("geometry", "")})
    table_end = geom["table_end"]
    compressed_offset = geom["compressed_offset"]
    padding = geom["padding_size"]
    problems = []
    if table_end > compressed_offset:
        problems.append("Tabelle endet bei 0x%X hinter compressed_offset 0x%X"
                        % (table_end, compressed_offset))
    if padding and compressed_offset % padding:
        problems.append("compressed_offset %d ist kein Vielfaches von padding %d"
                        % (compressed_offset, padding))
    gap = compressed_offset - table_end
    evidence = {"table_end": table_end, "compressed_offset": compressed_offset,
                "gap_bytes": gap, "padding_size": padding}
    if problems:
        return CheckResult("I-03", "Chunk-Tabellen-Geometrie", FAILED,
                           "; ".join(problems), evidence)
    if gap:
        return CheckResult("I-03", "Chunk-Tabellen-Geometrie", WARNING,
                           "Tabelle endet 0x%X, compressed_offset 0x%X — "
                           "%d Byte Ausrichtung vor dem Datenstrom"
                           % (table_end, compressed_offset, gap), evidence)
    return CheckResult("I-03", "Chunk-Tabellen-Geometrie", PASS,
                       "Tabelle schliesst exakt an den Datenstrom an (0x%X)"
                       % table_end, evidence)


def check_i04_padding_sum(ctx: SaveContext) -> CheckResult:
    """I-04 — Padding-Summe gegen Dateirest."""
    geom = ctx.geometry
    if not geom or not geom.get("chunk_sizes"):
        return CheckResult("I-04", "Padding-Summe gegen Dateirest", NOT_CHECKED,
                           "Chunk-Groessen nicht verfuegbar", {})
    total = geom["sum_padded"]
    rest = geom["data_rest"]
    evidence = {"sum_padded": total, "data_rest": rest, "delta": rest - total,
                "chunk_count": len(geom["chunk_sizes"])}
    if total == rest:
        return CheckResult("I-04", "Padding-Summe gegen Dateirest", PASS,
                           "Summe der gepolsterten Chunks %d == Dateirest %d"
                           % (total, rest), evidence)
    return CheckResult("I-04", "Padding-Summe gegen Dateirest", FAILED,
                       "Summe %d != Dateirest %d (Delta %+d Byte) — "
                       "Truncation, angehaengte Bytes oder manipulierte Groessen"
                       % (total, rest, rest - total), evidence)


def check_i05_decompression(ctx: SaveContext) -> CheckResult:
    """I-05 — Chunk-Dekompression inklusive Pruefsumme und Streamgrenze."""
    geom = ctx.geometry
    if not geom or not geom.get("chunk_sizes"):
        return CheckResult("I-05", "Chunk-Dekompression", NOT_CHECKED,
                           "Chunk-Groessen nicht verfuegbar", {})
    if ctx.load_errors.get("payload"):
        return CheckResult("I-05", "Chunk-Dekompression", FAILED,
                           ctx.load_errors["payload"],
                           {"error": ctx.load_errors["payload"]})
    offset = geom["compressed_offset"]
    padding = geom["padding_size"] or 1
    trailing_total = 0
    trailing_chunks = 0
    for index, size in enumerate(geom["chunk_sizes"]):
        chunk = ctx.disk[offset:offset + size]
        if len(chunk) < size:
            return CheckResult("I-05", "Chunk-Dekompression", FAILED,
                               "Chunk %d ist abgeschnitten (%d von %d Byte)"
                               % (index, len(chunk), size),
                               {"chunk_index": index, "offset": offset})
        try:
            inflater = zlib.decompressobj()
            inflater.decompress(chunk)
            inflater.flush()
        except zlib.error as exc:
            return CheckResult("I-05", "Chunk-Dekompression", FAILED,
                               "zlib-Fehler in Chunk %d bei 0x%X: %s"
                               % (index, offset, exc),
                               {"chunk_index": index, "offset": offset, "size": size})
        trailing = len(inflater.unused_data)
        if trailing:
            trailing_total += trailing
            trailing_chunks += 1
        offset += ((size + padding - 1) & ~(padding - 1)) if padding > 1 else size

    if trailing_total:
        return CheckResult(
            "I-05", "Chunk-Dekompression", WARNING,
            "alle Chunks dekomprimierbar, aber %d Byte liegen hinter dem "
            "zlib-Stream (%d Chunk(s)). Ob das Format diesen Rest erlaubt, ist "
            "nicht belegt — daher WARNING statt PASS oder FAILED."
            % (trailing_total, trailing_chunks),
            {"trailing_bytes": trailing_total, "trailing_chunks": trailing_chunks},
            confidence="unverified")
    return CheckResult("I-05", "Chunk-Dekompression", PASS,
                       "alle %d Chunks dekomprimierbar, keine Bytes hinter dem Stream"
                       % len(geom["chunk_sizes"]),
                       {"chunks": len(geom["chunk_sizes"])})


def check_i06_payload_length(ctx: SaveContext) -> CheckResult:
    """I-06 — tatsaechliche Dekompressionslaenge gegen deklarierte Groesse."""
    if ctx.payload is None:
        return CheckResult("I-06", "Nutzlaenge gegen Deklaration", NOT_CHECKED,
                           "kein Payload: %s" % ctx.load_errors.get("payload", ""),
                           {"error": ctx.load_errors.get("payload", "")})
    declared = ctx.container.uncompressed_size if ctx.container else None
    if declared is None:
        return CheckResult("I-06", "Nutzlaenge gegen Deklaration", NOT_CHECKED,
                           "deklarierte Groesse nicht lesbar", {})
    actual = len(ctx.payload)
    evidence = {"actual": actual, "declared": declared, "delta": actual - declared}
    if actual == declared:
        return CheckResult("I-06", "Nutzlaenge gegen Deklaration", PASS,
                           "Nutzlaenge %d == deklarierte Groesse %d"
                           % (actual, declared), evidence)
    return CheckResult("I-06", "Nutzlaenge gegen Deklaration", FAILED,
                       "Nutzlaenge %d != deklariert %d (Delta %+d Byte) — "
                       "Groessenfeld manipuliert oder Dekompression unvollstaendig"
                       % (actual, declared, actual - declared), evidence)


def check_i07_chunk_count(ctx: SaveContext) -> CheckResult:
    """I-07 — Chunk-Anzahl gegen Groessenraster."""
    geom = ctx.geometry
    if not geom:
        return CheckResult("I-07", "Chunk-Anzahl", NOT_CHECKED,
                           "Geometrie nicht verfuegbar", {})
    pre = geom["chunk_size_pre"]
    declared = geom["declared_chunk_count"]
    sizes = geom["chunk_sizes"]
    evidence = {"declared": declared, "table_entries": len(sizes),
                "chunk_size_pre": pre,
                "uncompressed_size": geom["uncompressed_size"]}
    if pre <= 0 or declared <= 0:
        return CheckResult("I-07", "Chunk-Anzahl", FAILED,
                           "unplausibles Raster: chunk_size_pre=%d, count=%d"
                           % (pre, declared), evidence)
    if len(sizes) != declared:
        return CheckResult("I-07", "Chunk-Anzahl", FAILED,
                           "Tabelle hat %d Eintraege, Raster verlangt %d"
                           % (len(sizes), declared), evidence)
    expected = -(-geom["uncompressed_size"] // pre)
    if expected != declared:
        return CheckResult("I-07", "Chunk-Anzahl", WARNING,
                           "Raster ergibt %d Chunks, Tabelle hat %d"
                           % (expected, declared), evidence)
    return CheckResult("I-07", "Chunk-Anzahl", PASS,
                       "%d Chunks entsprechen dem Raster (ceil(%d/%d))"
                       % (declared, geom["uncompressed_size"], pre), evidence,
                       confidence="heuristic" if geom["uncompressed_size"] % pre else
                       "deterministic")


def _strict_header_walk(payload: bytes) -> str:
    """Prueft alle Laengenfelder des Headers. Rueckgabe: Fehlertext oder ''."""
    if payload[:12] != b"SFS_SAVEGAME":
        return "DAT-Magic ist %r, erwartet b'SFS_SAVEGAME'" % payload[:12]
    cursor = 12 + 4                       # magic + headerSize
    cursor += 4                           # engineVersion
    cursor += 1                           # saveVersion
    cursor += 4                           # saveNumber
    if cursor + 2 > len(payload):
        return "playerName: Laengenfeld hinter dem Puffer (0x%X)" % cursor
    name_len, = struct.unpack_from("<H", payload, cursor)
    cursor += 2 + name_len                # playerName
    cursor += 4                           # playerLevel (u32)
    for field_name in ("playerLocation", "playtime", "raceName"):
        if cursor + 2 > len(payload):
            return "%s: Laengenfeld hinter dem Puffer (0x%X)" % (field_name, cursor)
        length, = struct.unpack_from("<H", payload, cursor)
        cursor += 2
        if length > 4096:
            return "%s: unplausible Laenge %d bei 0x%X" % (field_name, length, cursor - 2)
        if cursor + length > len(payload):
            return "%s: Inhalt hinter dem Puffer (0x%X)" % (field_name, cursor)
        cursor += length
    cursor += 2 + 4 + 4 + 8 + 4 + 8       # gender, experience, expReq, time, unk, pad
    cursor += 1                           # saveVersion2
    for field_name in ("currentGameVersion", "createdGameVersion"):
        if cursor + 2 > len(payload):
            return "%s: Laengenfeld hinter dem Puffer" % field_name
        length, = struct.unpack_from("<H", payload, cursor)
        cursor += 2
        if length > 4096:
            return "%s: unplausible Laenge %d" % (field_name, length)
        if cursor + length > len(payload):
            return "%s: Inhalt hinter dem Puffer" % field_name
        cursor += length
    if cursor + 2 > len(payload):
        return "pluginInfoSize: Feld hinter dem Puffer"
    return ""


def check_i08_header(ctx: SaveContext) -> CheckResult:
    """I-08 — DAT-Magic und Header-Feldgrenzen."""
    if ctx.payload is None:
        return CheckResult("I-08", "DAT-Magic und Header-Grenzen", NOT_CHECKED,
                           "kein Payload verfuegbar", {})
    error = _strict_header_walk(ctx.payload)
    magic_ok = ctx.payload[:12] == b"SFS_SAVEGAME"
    evidence = {"magic": ctx.payload[:12].decode("ascii", "replace"),
                "header_size": ctx.header.header_size if ctx.header else None}
    if not magic_ok:
        return CheckResult("I-08", "DAT-Magic und Header-Grenzen", FAILED, error, evidence)
    if error:
        return CheckResult("I-08", "DAT-Magic und Header-Grenzen", FAILED, error, evidence)
    return CheckResult("I-08", "DAT-Magic und Header-Grenzen", PASS,
                       "DAT-Magic korrekt, alle Header-Laengenfelder innerhalb des Puffers",
                       evidence)


def check_i09_header_size(ctx: SaveContext) -> CheckResult:
    """I-09 — Semantik des headerSize-Feldes. Zwingend UNKNOWN."""
    value = ctx.header.header_size if ctx.header else None
    return CheckResult(
        "I-09", "headerSize-Semantik", UNKNOWN,
        "headerSize=%s gelesen, Bedeutung nicht belegt (gemessen 123 und 125 bei "
        "sonst gleichem Aufbau; Bezug zum Plugin-Offset nicht aufloesbar)"
        % value,
        {"header_size": value,
         "plugin_info_offset": ctx.header.plugin_info_offset if ctx.header else None},
        confidence="unverified")


def check_i10_plugin_block(ctx: SaveContext) -> CheckResult:
    """I-10 — Plugin-Block-Grenzen."""
    if ctx.header is None or ctx.plugin_info is None:
        return CheckResult("I-10", "Plugin-Block-Grenzen", NOT_CHECKED,
                           "Header oder Plugin-Block nicht lesbar: %s"
                           % ctx.load_errors.get("plugins", ""), {})
    start = ctx.plugin_info.block_start
    declared_end = ctx.plugin_info.block_end_declared
    payload_len = len(ctx.payload or b"")
    evidence = {"start": start, "declared_end": declared_end,
                "payload_size": payload_len}
    if start < 12:
        return CheckResult("I-10", "Plugin-Block-Grenzen", FAILED,
                           "Block beginnt bei 0x%X, also im DAT-Header" % start, evidence)
    if declared_end > payload_len:
        return CheckResult("I-10", "Plugin-Block-Grenzen", FAILED,
                           "deklariertes Blockende 0x%X liegt hinter dem Payload (0x%X)"
                           % (declared_end, payload_len), evidence)
    return CheckResult("I-10", "Plugin-Block-Grenzen", PASS,
                       "Block 0x%X..0x%X liegt vollstaendig im Payload"
                       % (start, declared_end), evidence)


def check_i11_plugin_chains(ctx: SaveContext) -> CheckResult:
    """I-11 — Plugin-Ketten (normal/light/medium) und Metadaten."""
    info = ctx.plugin_info
    if info is None:
        return CheckResult("I-11", "Plugin-Ketten und Metadaten", NOT_CHECKED,
                           "Plugin-Block nicht lesbar", {})
    evidence = {
        "decode_state": info.decode_state,
        "counts": {"normal": len(info.normal), "light": len(info.light),
                   "medium": len(info.medium), "total": info.total},
        "declared": {"normal": info.declared_normal, "light": info.declared_light,
                     "medium": info.declared_medium},
        "block_delta": info.block_delta,
        "metadata_present": info.metadata_count,
        "metadata_unreadable": info.unreadable_count,
    }
    if info.decode_state != "VALIDATED":
        return CheckResult("I-11", "Plugin-Ketten und Metadaten", WARNING,
                           "Ketten nicht vollstaendig lesbar: %s" % (info.note or "ohne Notiz"),
                           evidence, confidence="deterministic")
    if info.unreadable_count:
        return CheckResult("I-11", "Plugin-Ketten und Metadaten", WARNING,
                           "%d Plugin-Eintraege mit nicht lesbaren Metadaten"
                           % info.unreadable_count, evidence)
    if info.block_delta != 0:
        return CheckResult("I-11", "Plugin-Ketten und Metadaten", WARNING,
                           "gelesenes Blockende weicht um %+d Byte vom deklarierten ab"
                           % info.block_delta, evidence)
    return CheckResult(
        "I-11", "Plugin-Ketten und Metadaten", PASS,
        "%d/%d/%d Plugins gelesen (%d game, %d mod), Blockende bytegenau, "
        "%d Eintraege mit Creation-Metadaten"
        % (len(info.normal), len(info.light), len(info.medium),
           info.game_count, info.mod_count, info.metadata_count),
        evidence)


def check_i12_dependencies(ctx: SaveContext) -> CheckResult:
    """I-12 — Plugin-Abhaengigkeiten gegen das Data-Verzeichnis."""
    info = ctx.plugin_info
    if info is None or info.decode_state != "VALIDATED":
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", NOT_CHECKED,
                           "Plugin-Liste nicht verlaesslich lesbar", {})
    if not ctx.data_dir:
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", NOT_CHECKED,
                           "kein Data-Verzeichnis angegeben (--data-dir)", {})
    if not os.path.isdir(ctx.data_dir):
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", NOT_CHECKED,
                           "Data-Verzeichnis %r nicht vorhanden" % ctx.data_dir, {})
    installed = {name.lower() for name in os.listdir(ctx.data_dir)
                 if name.lower().endswith((".esm", ".esl", ".esp"))}
    listed = [p.name for p in info.normal + info.light + info.medium]
    missing = [n for n in listed if n.lower() not in installed]
    evidence = {"data_dir": ctx.data_dir, "listed": len(listed),
                "installed": len(installed), "missing": missing[:32],
                "missing_count": len(missing)}
    if missing:
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", WARNING,
                           "%d von %d gelisteten Plugins fehlen im Data-Verzeichnis"
                           % (len(missing), len(listed)), evidence)
    return CheckResult("I-12", "Plugin-Abhaengigkeiten", PASS,
                       "alle %d gelisteten Plugins im Data-Verzeichnis vorhanden"
                       % len(listed), evidence)


def check_i13_formids(ctx: SaveContext) -> CheckResult:
    """I-13 — FormID-Aufloesung. Dauerhaft NOT_CHECKED."""
    return CheckResult(
        "I-13", "FormID-Aufloesung", NOT_CHECKED,
        "nicht ausgefuehrt: das Record-Format des Bodys ist nicht erschlossen und "
        "die Zuordnung Plugin-Slot -> Master-Index ist nicht belegt",
        {"reason": "body record format unknown"}, confidence="unverified")


def check_i14_sequence(ctx: SaveContext) -> CheckResult:
    """I-14 — Sequenzkonsistenz ueber mehrere Saves desselben Charakters."""
    if not ctx.sequence:
        return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                           "keine Vergleichsdaten uebergeben", {})
    headers = list(ctx.sequence)
    ordered = sorted(headers, key=lambda h: h.filetime)
    problems = []
    for previous, current in zip(ordered, ordered[1:]):
        if current.player_level < previous.player_level:
            problems.append("Level faellt von %d auf %d"
                            % (previous.player_level, current.player_level))
        if current.filetime < previous.filetime:
            problems.append("FileTime rueckwaerts")
    evidence = {"saves": len(ordered),
                "span": [ordered[0].filetime, ordered[-1].filetime]}
    if problems:
        return CheckResult("I-14", "Sequenzkonsistenz", WARNING,
                           "; ".join(sorted(set(problems))), evidence)
    return CheckResult("I-14", "Sequenzkonsistenz", PASS,
                       "%d Saves monoton in Level und Zeit" % len(ordered), evidence)


CHECKS = (
    check_i01_magic,
    check_i02_compression,
    check_i03_chunk_table,
    check_i04_padding_sum,
    check_i05_decompression,
    check_i06_payload_length,
    check_i07_chunk_count,
    check_i08_header,
    check_i09_header_size,
    check_i10_plugin_block,
    check_i11_plugin_chains,
    check_i12_dependencies,
    check_i13_formids,
    check_i14_sequence,
)

#: Ein FAILED hier setzt alle NACHFOLGENDEN Pruefungen auf NOT_CHECKED.
BLOCKING_CHECKS = {"I-01", "I-02", "I-05"}
#: Pruefungen, die zwingend einen Payload brauchen.
PAYLOAD_DEPENDENT = {"I-06", "I-08", "I-10", "I-11", "I-12"}


def _check_id(func) -> str:
    """``check_i04_padding_sum`` -> ``I-04``."""
    return "I-%02d" % int(func.__name__.split("_")[1][1:])


def run_all(path: str | Path, *, data_dir: str | Path | None = None,
            sequence: Sequence[DatHeader] = ()) -> IntegrityReport:
    """Fuehrt alle Pruefungen aus und aggregiert zum Gesamtstatus."""
    ctx = build_context(path, data_dir=data_dir, sequence=sequence)
    results: list[CheckResult] = []
    blocked_by: str | None = None

    for check in CHECKS:
        check_id = _check_id(check)
        if blocked_by is not None:
            title = (check.__doc__ or "").split("—")[-1].strip()
            results.append(CheckResult(
                check_id, title, NOT_CHECKED,
                "Voraussetzung fehlt: %s ist FAILED" % blocked_by,
                {"blocked_by": blocked_by}))
            continue
        result = check(ctx)
        if ctx.payload is None and result.check_id in PAYLOAD_DEPENDENT \
                and result.status != NOT_CHECKED:
            # Ohne Payload kann keine dieser Pruefungen bestanden werden.
            result = CheckResult(
                result.check_id, result.title, NOT_CHECKED,
                "kein Payload verfuegbar", result.evidence, result.confidence)
        results.append(result)
        if result.check_id in BLOCKING_CHECKS and result.status == FAILED:
            blocked_by = result.check_id

    # Zwei getrennte Aggregate: Integritaetsurteil und strenge Sicht inkl. Luecken.
    total = PASS
    total_with_gaps = PASS
    for result in results:
        if SEVERITY[result.status] > SEVERITY[total_with_gaps]:
            total_with_gaps = result.status
        if result.status in (PASS, WARNING, FAILED):
            if SEVERITY[result.status] > SEVERITY[total]:
                total = result.status
    gaps = tuple(r for r in results if r.status in (UNKNOWN, NOT_CHECKED))
    return IntegrityReport(
        path=str(path),
        file_size=ctx.file_size,
        sha256=ctx.sha256,
        total=total,
        checks=tuple(results),
        total_with_gaps=total_with_gaps,
        gaps=gaps,
    )


def format_text(report: IntegrityReport) -> str:
    """Klartextdarstellung fuer die CLI (ASCII, Windows-Konsole tauglich)."""
    lines = []
    for check in report.checks:
        lines.append("%-4s %-12s %s" % (check.check_id, check.status, check.detail))
    coverage = report.coverage
    lines.append("")
    lines.append("INTEGRITAET: %s" % report.total)
    lines.append("PRUEFABDECKUNG: %d von %d Pruefungen bewertet "
                 "(%d PASS, %d WARNING, %d FAILED, %d UNKNOWN, %d NOT_CHECKED)"
                 % (coverage["assessed"], coverage["total"], coverage[PASS],
                    coverage[WARNING], coverage[FAILED], coverage[UNKNOWN],
                    coverage[NOT_CHECKED]))
    if report.gaps:
        lines.append("NICHT BEWERTET:")
        for gap in report.gaps:
            lines.append("  %-4s %-12s %s" % (gap.check_id, gap.status, gap.detail))
    lines.append("")
    lines.append("Hinweis: %s" % report.disclaimer)
    return "\n".join(lines)
