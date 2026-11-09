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
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import (PUBLIC_PATH_PLACEHOLDER, public_error, public_error_detail,
                     render_public_message, strip_paths)
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
    """Ergebnis einer Einzelpruefung.

    VERTRAUENSBEREICHE (R1_6)
        ``detail`` und ``evidence`` sind der **oeffentliche** Bereich. Sie
        gelangen ueber :meth:`to_dict` in JSON, in die CLI-Ausgabe und in
        die GUI. Sie duerfen ausschliesslich kontrollierte Werte tragen:
        statischen Text aus der Meldungsregistry, boolesche Werte,
        begrenzte Zahlen und geschlossene Enum-Werte.

        ``internal`` traegt die **interne** Diagnose (Rohbytes, Dateinamen,
        Pfade, Exception-Details). Sie wird **nie** serialisiert und
        erscheint in keiner oeffentlichen Ausgabe. ``repr=False`` und
        ``compare=False`` sorgen dafuer, dass sie weder versehentlich
        in Ausgaben noch in Vergleiche gerät.
    """
    check_id: str
    title: str
    status: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    confidence: str = "deterministic"      # deterministic | heuristic | unverified
    #: Interne Rohdiagnose — NICHT serialisieren, NICHT oeffentlich.
    internal: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Oeffentliche Darstellung — ohne ``internal``.

        ``internal`` wird hier bewusst **nicht** uebernommen. Damit kann
        es auch nicht versehentlich durchgereicht werden.
        """
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
        """Oeffentliche Darstellung — **ohne** Pfad und ohne Dateinamen (F-2).

        ``path`` bleibt intern am Objekt erhalten (Verarbeitung und
        Diagnose), erscheint aber nicht in der oeffentlichen
        Serialisierung. Es wird auch **nicht** durch den Dateinamen
        ersetzt — beides waere eine Dateiidentifikation.
        """
        return {
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
    #: Auswahlprotokoll der Sequenz (welche Datei aufgenommen, verworfen oder
    #: gar nicht beruecksichtigt wurde). Leer, wenn die Sequenz als einfaches
    #: Tupel uebergeben wurde — dann gibt es nichts zu berichten.
    sequence_info: dict[str, Any] = field(default_factory=dict)

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
    protocol = getattr(sequence, "to_evidence", None)
    if callable(protocol):
        try:
            ctx.sequence_info = dict(protocol())
        except Exception:                                      # noqa: BLE001
            ctx.sequence_info = {}

    try:
        ctx.container = provider.read_container(src)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["container"] = _error_reason(exc)
    try:
        ctx.geometry = provider.read_chunk_table(src)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["geometry"] = _error_reason(exc)
    try:
        # verify=False: I-06 prueft die Laenge selbst und meldet den Befund,
        # statt dass der Ladepfad mit einer Ausnahme abbricht.
        ctx.payload = provider.decompress(src, verify=False)
    except Exception as exc:                                   # noqa: BLE001
        ctx.load_errors["payload"] = _error_reason(exc)
    if ctx.payload is not None:
        try:
            ctx.header = provider.parse_dat_header(ctx.payload)
        except Exception as exc:                               # noqa: BLE001
            ctx.load_errors["header"] = _error_reason(exc)
        if ctx.header is not None:
            try:
                ctx.plugin_info = provider.parse_plugin_info(ctx.payload, ctx.header)
            except Exception as exc:                           # noqa: BLE001
                ctx.load_errors["plugins"] = _error_reason(exc)
    return ctx


# ---------------------------------------------------------------------------
# Einzelpruefungen
# ---------------------------------------------------------------------------
def check_i01_magic(ctx: SaveContext) -> CheckResult:
    """I-01 — BCPS-Magic."""
    ok = ctx.disk[:4] == b"BCPS"
    if ok:
        detail = "Container beginnt mit BCPS"
        evidence: dict[str, Any] = {"magic": ctx.disk[:4].hex(),
                                    "expected": b"BCPS".hex()}
    else:
        # R1_6: die rohen Bytes duerfen NICHT in den oeffentlichen Text.
        # Die Registry liefert eine statische Beschreibung des Kennzeichens.
        detail = render_public_message("I-01.MAGIC_MISMATCH",
                                        magic=ctx.disk[:4])
        evidence = {"magic": ctx.disk[:4].hex(),
                    "expected": b"BCPS".hex()}
    return CheckResult(
        "I-01", "BCPS-Magic", PASS if ok else FAILED,
        detail, evidence,
        internal={"actual_magic_bytes": ctx.disk[:4]},
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
        return CheckResult("I-02", "Kompressionstyp", PASS, "Kompression ZIP",
                           evidence)
    # R1_6: der Kompressionstag ist ein Containerinhalt. Oeffentlich nur
    # als statische Beschreibung; die Bytes bleiben intern.
    detail = render_public_message("I-02.COMPRESSION_UNSUPPORTED",
                                    magic=compression)
    return CheckResult("I-02", "Kompressionstyp", FAILED, detail, evidence,
                       internal={"actual_compression_bytes": compression})


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
            # R1_6: der Fehlertext kommt aus public_error() — die
            # Registry rendert ihn als kontrollierten Platzhalter.
            detail = render_public_message("I-05.DECOMPRESSION_FAILED",
                                            index=index, offset=offset,
                                            reason=_error_reason(exc))
            return CheckResult("I-05", "Chunk-Dekompression", FAILED,
                               detail,
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
    """Prueft alle Laengenfelder des Headers. Rueckgabe: Fehlertext oder ''.

    R1_6: die Magic-Pruefung liefert **keinen** Text mit den Rohbytes
    mehr. Stattdessen wird ein Kennzeichen-Marker zurueckgegeben, den
    der Aufrufer ueber die Meldungsregistry rendert. Alle uebrigen
    Meldungen enthalten nur Hex-/Zahlenwerte und sind unbedenklich.
    """
    if payload[:12] != b"SFS_SAVEGAME":
        return "\x00DAT_MAGIC_MISMATCH"
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
    # R1_6: evidence traegt KEINE dekodierten Rohbytes mehr. Die Magic
    # wird nur noch als Vergleichs-Flag ausgegeben.
    evidence = {"magic_matches": magic_ok,
                "header_size": ctx.header.header_size if ctx.header else None}
    if not magic_ok:
        detail = render_public_message("I-08.DAT_MAGIC_MISMATCH",
                                        magic=ctx.payload[:12])
        return CheckResult("I-08", "DAT-Magic und Header-Grenzen", FAILED,
                           detail, evidence,
                           internal={"actual_dat_magic_bytes": ctx.payload[:12]})
    if error:
        # R1_6: der Fehlertext ist ein eigener statischer Text ueber eine
        # Header-Feldgrenze — er wird ueber die Registry gerendert, damit
        # die Herkunft belegt ist.
        detail = render_public_message("I-08.HEADER_FIELD_ERROR", error=error)
        return CheckResult("I-08", "DAT-Magic und Header-Grenzen", FAILED,
                           detail, evidence)
    return CheckResult("I-08", "DAT-Magic und Header-Grenzen", PASS,
                       "DAT-Magic korrekt, alle Header-Laengenfelder innerhalb des Puffers",
                       evidence)


def check_i09_header_size(ctx: SaveContext) -> CheckResult:
    """I-09 — headerSize gegen die tatsaechliche Header-Geometrie.

    Belegte Beziehung (2026-11-08, sechs reale Saves, 6/6 exakt)::

        header_size == padding_end - header_count_start

    ``header_count_start`` ist die Formatkonstante 16 (12 Byte Magic + 4 Byte
    Groessenfeld selbst). ``padding_end`` wird vom Parser aus der tatsaechlichen
    Feldposition geliefert — es wird **kein** Offset und **keine** Stringlaenge
    fest angenommen. Damit ist die Pruefung unabhaengig von Name, Ort, Rasse und
    Spielzeit des konkreten Spielstands.

    Abgrenzung: Der gezählte Bereich endet am Padding. Die 27 Byte danach
    (``saveVersion2``, ``currentGameVersion``, ``createdGameVersion``,
    ``pluginInfoSize``) zaehlt das Feld nicht mit. Deshalb ist
    ``plugin_info_offset - header_size`` nicht konstant 16, sondern 43.
    """
    if ctx.header is None:
        return CheckResult("I-09", "headerSize gegen Header-Geometrie", NOT_CHECKED,
                           "Header nicht dekodierbar", {})
    header = ctx.header
    declared = header.header_size
    padding_end = getattr(header, "padding_end", None)
    count_start = getattr(header, "header_count_start", 16)
    evidence = {
        "header_size": declared,
        "padding_end": padding_end,
        "header_count_start": count_start,
        "plugin_info_offset": header.plugin_info_offset,
    }
    if padding_end is None:
        return CheckResult(
            "I-09", "headerSize gegen Header-Geometrie", NOT_CHECKED,
            "Padding-Ende nicht bestimmt — Header unvollstaendig dekodierbar",
            evidence)
    expected = padding_end - count_start
    evidence["expected"] = expected
    evidence["delta"] = declared - expected
    if expected <= 0:
        return CheckResult(
            "I-09", "headerSize gegen Header-Geometrie", FAILED,
            "Padding-Ende liegt vor dem gezaehlten Bereich (0x%X vs. 0x%X) — "
            "Feldgrenzen inkonsistent" % (padding_end, count_start), evidence)
    if declared != expected:
        return CheckResult(
            "I-09", "headerSize gegen Header-Geometrie", FAILED,
            "headerSize=%d, erwartet %d (padding_end 0x%X - %d) — Delta %+d Byte"
            % (declared, expected, padding_end, count_start, declared - expected),
            evidence)
    return CheckResult(
        "I-09", "headerSize gegen Header-Geometrie", PASS,
        "headerSize=%d entspricht padding_end 0x%X minus %d Byte"
        % (declared, padding_end, count_start),
        evidence)


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
        # R1_6: info.note stammt aus statischen Formatstrings bzw. aus
        # public_error() (savegame_provider.py:809-856) — die Meldung
        # wird ueber die Registry gerendert.
        detail = render_public_message("I-11.CHAINS_UNREADABLE",
                                        note=info.note or "unknown")
        return CheckResult("I-11", "Plugin-Ketten und Metadaten", WARNING,
                           detail,
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
        # R1_6: der Pfad selbst ist eine Verzeichnisinformation und wird
        # nicht oeffentlich ausgegeben.
        detail = render_public_message("I-12.DATA_DIR_MISSING")
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", NOT_CHECKED,
                           detail, {},
                           internal={"data_dir": ctx.data_dir})
    installed = {name.lower() for name in os.listdir(ctx.data_dir)
                 if name.lower().endswith((".esm", ".esl", ".esp"))}
    listed = [p.name for p in info.normal + info.light + info.medium]
    missing = [n for n in listed if n.lower() not in installed]
    # R1_6: evidence enthaelt KEINEN Pfad und KEINE Plugin-Dateinamen.
    # Nur Anzahlen sind oeffentlich (F-3).
    evidence = {"listed": len(listed),
                "installed": len(installed),
                "missing_count": len(missing)}
    if missing:
        return CheckResult("I-12", "Plugin-Abhaengigkeiten", WARNING,
                           "%d von %d gelisteten Plugins fehlen im Data-Verzeichnis"
                           % (len(missing), len(listed)), evidence,
                           internal={"data_dir": ctx.data_dir,
                                     "missing": missing[:32]})
    return CheckResult("I-12", "Plugin-Abhaengigkeiten", PASS,
                       "alle %d gelisteten Plugins im Data-Verzeichnis vorhanden"
                       % len(listed), evidence,
                       internal={"data_dir": ctx.data_dir})


def check_i13_formids(ctx: SaveContext) -> CheckResult:
    """I-13 — FormID-Aufloesung. Dauerhaft NOT_CHECKED."""
    return CheckResult(
        "I-13", "FormID-Aufloesung", NOT_CHECKED,
        "nicht ausgefuehrt: das Record-Format des Bodys ist nicht erschlossen und "
        "die Zuordnung Plugin-Slot -> Master-Index ist nicht belegt",
        {"reason": "body record format unknown"}, confidence="unverified")


#: Maximalzahl von Saves, die fuer die Sequenzpruefung eingelesen werden.
SEQUENCE_MAX_FILES = 64
#: Obergrenze fuer die namentliche Auflistung nicht beruecksichtigter Dateien.
#: Die Anzahl wird immer vollstaendig ausgewiesen, nur die Namensliste ist
#: gekappt — sonst waechst der Bericht bei tausenden Saves unbegrenzt.
SEQUENCE_REPORT_MAX_NAMES = 256

#: Verwerfungsgruende. Getrennt gehalten, damit "nicht lesbar" nicht mit
#: "strukturell ungueltig" oder "Header fehlt" verschmilzt.
KIND_SELECTED = "selected"
KIND_UNREADABLE = "unreadable"
KIND_INVALID = "structurally_invalid"
KIND_NO_HEADER = "no_header_data"
KIND_DUPLICATE = "duplicate"
KIND_NOT_CONSIDERED = "not_considered"

KIND_TEXT = {
    KIND_UNREADABLE: "nicht lesbar",
    KIND_INVALID: "strukturell ungueltig",
    KIND_NO_HEADER: "keine verwertbaren Headerdaten",
    KIND_DUPLICATE: "Duplikat (identischer Payload)",
    KIND_NOT_CONSIDERED: "nicht beruecksichtigt (Auswahllimit)",
}

_PLAYTIME_RE = re.compile(r"^(\d+)d\.(\d+)h\.(\d+)m\.")

#: Oeffentliche Fehlertexte kommen aus :mod:`ssb_i.errors`. Dort werden sie aus
#: kontrollierten Bestandteilen gebaut (Klasse, errno, strerror, Whitelist
#: eigener Meldungen) statt aus rohem Exception-Text gefiltert.
PATH_PLACEHOLDER = PUBLIC_PATH_PLACEHOLDER
_strip_paths = strip_paths


def _error_text(exc: BaseException) -> str:
    """Sicherer Detailteil eines Fehlers (ohne Klasse, ohne Pfad)."""
    return public_error_detail(exc)


def _error_reason(exc: BaseException) -> str:
    """Einheitliche Form ``Klasse: Meldung`` ohne lokale Pfade."""
    return public_error(exc)


def sequence_limitation(*, not_considered: int, discarded: int,
                        max_files: int) -> str:
    """Satz zur Aussagekraft, wenn nicht alle Dateien ausgewertet wurden.

    Leerer String, wenn der Datenbestand vollstaendig beruecksichtigt wurde.
    Bewusst als fachliche Einschraenkung formuliert — nicht als
    Performance-Hinweis und nicht als blosse Randnotiz.
    """
    if not not_considered and not discarded:
        return ""
    parts: list[str] = []
    if not_considered:
        parts.append("%d Datei(en) wegen des Limits von %d Dateien nicht "
                     "beruecksichtigt (Auswahl ueber Datei-mtime, nicht ueber "
                     "die Spielzeit)" % (not_considered, max_files))
    if discarded:
        parts.append("%d Datei(en) ohne verwertbaren Header verworfen" % discarded)
    return ("I-14 bewertet nur die tatsaechlich ausgewertete Sequenz: "
            + "; ".join(parts)
            + ". Ein PASS belegt deshalb NICHT die Konsistenz aller vorhandenen "
              "Saves — ein Level- oder Spielzeitabfall in einer nicht "
              "beruecksichtigten Datei bleibt unbemerkt.")


@dataclass(frozen=True)
class SequenceEntry:
    """Eine Datei der Sequenzauswahl — aufgenommen oder verworfen.

    ``name`` ist der **Dateiname** des Kandidaten. Er wird intern fuer
    Zuordnung und Diagnose gebraucht, ist aber **nicht** Teil der
    oeffentlichen Darstellung (F-3): ``to_dict()`` gibt ihn nicht mehr
    zurueck.

    ``detail`` traegt die internen Headerwerte (Spielername, Spielzeit).
    Auch sie sind intern.
    """
    name: str
    kind: str = KIND_SELECTED
    reason: str = ""
    header: DatHeader | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Interne Darstellung — mit Dateinamen.

        Diese Methode wird **nicht** fuer oeffentliche Ausgaben
        verwendet. Oeffentlich ist nur :meth:`public_dict` zulaessig.
        """
        out: dict[str, Any] = {"file": self.name, "kind": self.kind,
                               "kind_text": KIND_TEXT.get(self.kind, self.kind)}
        if self.reason:
            out["reason"] = self.reason
        if self.detail:
            out["detail"] = dict(self.detail)
        return out

    def public_dict(self) -> dict[str, Any]:
        """Oeffentliche Darstellung — **ohne** Dateinamen und Detail (F-3).

        Nur die geschlossene Ursachenklasse und ihr kontrollierter Text
        sind oeffentlich. Der Dateiname und die internen Headerwerte
        bleiben intern.
        """
        out: dict[str, Any] = {"kind": self.kind,
                               "kind_text": KIND_TEXT.get(self.kind, self.kind)}
        if self.reason:
            out["reason"] = self.reason
        return out


class SaveSequence(tuple):
    """Tupel der verwendbaren Header plus Auswahl- und Verwerfungsprotokoll.

    Rueckwaertskompatibel: verhaelt sich vollstaendig wie
    ``tuple[DatHeader, ...]`` (Laenge, Iteration, Vergleich mit ``()``).
    Zusaetzlich traegt es das Protokoll, damit im Bericht nachvollziehbar
    bleibt, welche Dateien ausgewaehlt, verworfen oder gar nicht erst
    beruecksichtigt wurden.
    """

    def __new__(cls, headers: Iterable[DatHeader] = (), *,
                entries: Iterable[SequenceEntry] = (),
                not_considered: Iterable[SequenceEntry] = (),
                candidates: int = 0,
                max_files: int = SEQUENCE_MAX_FILES,
                limit_applied: bool = False,
                stats: Mapping[str, Any] | None = None):
        obj = super().__new__(cls, tuple(headers))
        obj.entries = tuple(entries)
        obj.not_considered = tuple(not_considered)
        obj.candidates = candidates
        obj.max_files = max_files
        obj.limit_applied = limit_applied
        obj.stats = dict(stats or {})
        return obj

    @property
    def discarded(self) -> tuple[SequenceEntry, ...]:
        """Verworfene Header — nicht lesbar, strukturell ungueltig, ohne Header."""
        return tuple(e for e in self.entries if e.kind != KIND_SELECTED
                     and e.kind != KIND_DUPLICATE)

    @property
    def duplicates(self) -> tuple[SequenceEntry, ...]:
        """Dateien, die nur wegen identischen Payloads nicht aufgenommen wurden."""
        return tuple(e for e in self.entries if e.kind == KIND_DUPLICATE)

    def to_evidence(self) -> dict[str, Any]:
        """JSON-faehige **oeffentliche** Beschreibung der Auswahl.

        R1_6 / F-3: oeffentlich sind ausschliesslich **Anzahlen** und
        geschlossene Zustandsangaben. Dateinamen, Spielernamen und
        Headerwerte bleiben intern (:meth:`to_internal_evidence`).
        """
        selected = [e for e in self.entries if e.kind == KIND_SELECTED]
        discarded = [e for e in self.discarded]
        return {
            "candidates": self.candidates,
            "considered": self.stats.get("files_considered", len(selected)),
            "max_files": self.max_files,
            "limit_applied": self.limit_applied,
            "limit_basis": "mtime (Auswahl, nicht Reihenfolge)",
            "selection_order": "Dateiname",
            "chronology": "Header-FileTime, hergestellt in check_i14_sequence()",
            "selected_count": len(selected),
            "discarded_count": len(discarded),
            "discarded": [e.public_dict() for e in discarded],
            "duplicates_removed_count": len(self.duplicates),
            "not_considered": {
                "count": len(self.not_considered),
            },
            "limitation": sequence_limitation(not_considered=len(self.not_considered),
                                              discarded=len(discarded),
                                              max_files=self.max_files),
            "body_check": "nicht durchgefuehrt (Header-only: nur Chunk 0 entpackt)",
            "decompression": dict(self.stats),
        }

    def to_internal_evidence(self) -> dict[str, Any]:
        """Interne Beschreibung der Auswahl — mit Dateinamen.

        Nicht oeffentlich. Nur fuer Diagnose und interne Auswertung.
        """
        selected = [e.name for e in self.entries if e.kind == KIND_SELECTED]
        names = [e.name for e in self.not_considered]
        discarded = [e.to_dict() for e in self.discarded]
        return {
            "selected": selected,
            "not_considered": {"count": len(names),
                               "names": names[:SEQUENCE_REPORT_MAX_NAMES],
                               "truncated": len(names) > SEQUENCE_REPORT_MAX_NAMES},
            "discarded": discarded,
            "duplicates_removed": [e.to_dict() for e in self.duplicates],
        }


def _header_identity(header: DatHeader) -> tuple:
    """Alle dekodierten Headerwerte als Vergleichsschluessel.

    Ein identischer Payload erzeugt zwangslaeufig identische Werte. Eine
    Abweichung hier beweist also unterschiedliche Payloads; nur bei
    Gleichheit muss genauer nachgesehen werden.
    """
    return tuple(header.to_dict().values())


def _payload_sha(provider: SfsDecodeProvider, path: str) -> str:
    """SHA-256 des vollstaendig entpackten Payloads (nur fuer den Duplikatbeweis)."""
    import hashlib
    return hashlib.sha256(provider.decompress(path, verify=False)).hexdigest()


def playtime_minutes(raw: str) -> int | None:
    """Spielzeit-String in Minuten. ``None``, wenn nicht lesbar.

    Der Save speichert zwei Formate in einem String, z. B.
    ``"2d.10h.34m.2 Tage.10 Stunden.34 Minuten"``. Ausgewertet wird der
    maschinenlesbare Kopf; die lokalisierte Wiederholung wird ignoriert.
    Kein Raten: passt das Muster nicht, ist das Ergebnis ``None``.
    """
    match = _PLAYTIME_RE.match(raw or "")
    if not match:
        return None
    days, hours, minutes = (int(part) for part in match.groups())
    return days * 1440 + hours * 60 + minutes


def collect_sequence(path: str | Path, *, directory: str | Path | None = None,
                     max_files: int = SEQUENCE_MAX_FILES) -> SaveSequence:
    """Sammelt Header und Auswahlprotokoll der Saves fuer die Sequenzpruefung.

    AUSWAHL — das ist alles, was diese Funktion entscheidet:

      * Kandidaten sind alle ``*.sfs`` im Verzeichnis der geprueften Datei
        (oder in ``directory``), zunaechst in Dateinamen-Reihenfolge.
      * Sind es mehr als ``max_files``, bleiben die nach Datei-Aenderungszeit
        (``mtime``) neuesten ``max_files`` uebrig und werden danach wieder
        nach Dateinamen geordnet.

    ``mtime`` entscheidet damit ausschliesslich, WELCHE Dateien in die Auswahl
    kommen — nie, in welcher Reihenfolge sie ausgewertet werden. Die
    chronologische Ordnung stellt allein :func:`check_i14_sequence` her, und
    zwar anhand des ``filetime``-Werts aus dem Save-Header. Diese Funktion
    sortiert nichts chronologisch und wertet ``mtime`` nicht als Zeitangabe
    des Spielstands aus.

    ZURUECKGEGEBEN wird ein :class:`SaveSequence`: ein Tupel der verwendbaren
    Header, das zusaetzlich das Protokoll traegt — aufgenommen, verworfen
    (mit Grund und Ursachenklasse) und nicht beruecksichtigt.

    DUPLIKATE werden ueber die Identitaet des entpackten Payloads entfernt,
    damit derselbe Spielstand nicht zweimal in die Zeitreihe eintritt. Beweis
    ohne vollstaendige Dekompression: gleicher Header, gleiche Nutzgroesse und
    gleicher SHA-256 des komprimierten Stroms bedeuten nach zlib zwingend
    gleichen Payload. Nur wenn Header und Nutzgroesse gleich sind, der Strom
    aber abweicht (theoretisch: derselbe Spielstand, anders komprimiert),
    wird zur Entscheidung einmal vollstaendig entpackt und verglichen — sonst
    koennte ein Duplikat unbemerkt in die Sequenz geraten.

    KOSTEN: je Datei wird nur der erste Chunk entpackt (Header-only). Der
    Rumpf wird hier nicht geprueft; das leisten I-01..I-13, und die laufen auf
    dem Bezugssave. Der Befund weist diese Grenze als ``body_check`` aus.

    Eine Datei, deren Container strukturell ungueltig ist oder deren Header
    sich nicht dekodieren laesst, wird NICHT stillschweigend uebergangen: sie
    erscheint mit Ursachenklasse und Grund im Protokoll und traegt damit kein
    erfundenes Headerfeld in die Zeitreihe ein.

    AUSWAHLGRENZE — FOLGEN, DIE DER BEFUND NICHT VERSCHWEIGEN DARF:

      1. Die Auswahl passiert VOR der chronologischen Bewertung. Sie ist eine
         Vorbedingung, keine Folge der Zeitreihe.
      2. Welche Dateien beruecksichtigt werden, kann die Dateisystem-``mtime``
         beeinflussen (bei mehr als ``max_files`` Dateien). ``mtime`` ist damit
         ein Auswahlkriterium mit fachlicher Wirkung.
      3. Innerhalb der Auswahl richtet sich die chronologische Bewertung
         ausschliesslich nach dem ``filetime``-Wert aus dem Save-Header.
      4. Ein nicht beruecksichtigter Save kann einen relevanten Level- oder
         Spielzeit-RUECKGANG enthalten. Dieser Rueckgang wird dann nicht
         bewertet — er verschwindet nicht, er wird nur nicht gesehen.
      5. Ein I-14-PASS bezieht sich ausschliesslich auf die tatsaechlich
         ausgewertete Sequenz, nicht auf den vorhandenen Datenbestand.
      6. ``not_considered`` (Anzahl und Namensliste) ist deshalb keine
         Randnotiz, sondern eine Einschraenkung der Aussagekraft der Pruefung.
         Es ist ein fachlicher Hinweis, keine reine Performance-Angabe.
      7. Bei nicht vollstaendig beruecksichtigtem Datenbestand belegt ein PASS
         NICHT die Konsistenz aller vorhandenen Saves.

    Die Auswahlregel selbst ist eine bewusste Implementierungsgrenze und wird
    hier nicht veraendert; sie wird nur offengelegt.
    """
    from .savegame_provider import SfsDecodeProvider, SfsHeaderError

    source = Path(path)
    folder = Path(directory) if directory else source.parent
    if not folder.is_dir():
        return SaveSequence()

    candidates = sorted(folder.glob("*.sfs"), key=lambda p: p.name)
    candidates_total = len(candidates)
    limit_applied = candidates_total > max_files
    not_considered: list[SequenceEntry] = []
    if limit_applied:
        kept = sorted(candidates, key=lambda p: p.stat().st_mtime,
                      reverse=True)[:max_files]
        kept_names = {p.name for p in kept}
        not_considered = [
            SequenceEntry(
                name=p.name, kind=KIND_NOT_CONSIDERED,
                reason="Auswahllimit %d Dateien: aeltere Datei nach mtime"
                       % max_files)
            for p in candidates if p.name not in kept_names]
        candidates = sorted(kept, key=lambda p: p.name)

    provider = SfsDecodeProvider()
    entries: list[SequenceEntry] = []
    headers: list[DatHeader] = []
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    stats: dict[str, Any] = {
        "files_considered": len(candidates),
        "header_only": 0,
        "full_decompressions": 0,
        "stream_digest_checks": 0,
        "payload_sha_checks": 0,
    }

    for candidate in candidates:
        try:
            probe = provider.read_header(str(candidate))
        except SfsHeaderError as exc:
            entries.append(SequenceEntry(name=candidate.name, kind=KIND_NO_HEADER,
                                         reason=_error_text(exc)))
            continue
        except OSError as exc:
            entries.append(SequenceEntry(
                name=candidate.name, kind=KIND_UNREADABLE,
                reason=_error_reason(exc)))
            continue
        except Exception as exc:                               # noqa: BLE001
            entries.append(SequenceEntry(
                name=candidate.name, kind=KIND_INVALID,
                reason=_error_reason(exc)))
            continue

        header = probe["header"]
        layout = probe["layout"]
        sizes = probe["sizes"]
        stats["header_only"] += 1

        key = _header_identity(header)
        digest: str | None = None
        duplicate_of: str | None = None
        body_error: str | None = None
        for other in buckets.get(key, []):
            if other["uncompressed_size"] != layout.uncompressed_size:
                # Gleiche Header, andere Nutzgroesse: unterschiedliche Payloads
                # sind damit bewiesen (gleicher Payload haette gleiche Laenge).
                continue
            if other["digest"] is None:
                other["digest"] = provider.stream_digest(
                    other["path"], layout=other["layout"])
                stats["stream_digest_checks"] += 1
            if digest is None:
                digest = provider.stream_digest(str(candidate), layout=layout)
                stats["stream_digest_checks"] += 1
            if (digest == other["digest"] and other["sizes"] == sizes
                    and other["padding_size"] == layout.padding_size):
                duplicate_of = other["name"]
                break
            # Unterschiedlicher Strom bei gleichem Header und gleicher Groesse:
            # nur eine andere Kompression kann den Payload noch gleich machen.
            stats["payload_sha_checks"] += 1
            try:
                candidate_sha = _payload_sha(provider, str(candidate))
                stats["full_decompressions"] += 1
                if other["payload_sha"] is None:
                    other["payload_sha"] = _payload_sha(provider, other["path"])
                    stats["full_decompressions"] += 1
            except (ValueError, OSError) as exc:
                # Der volle Strom laesst sich nicht entpacken. Das ist ein
                # Befund ueber die Datei — kein Grund, die ganze Sequenz
                # abzubrechen und auch keinen Grund, sie als Duplikat zu werten.
                body_error = _error_reason(exc)
                break
            if candidate_sha == other["payload_sha"]:
                duplicate_of = other["name"]
                break

        if body_error is not None:
            entries.append(SequenceEntry(
                name=candidate.name, kind=KIND_INVALID,
                reason="voller Datenstrom nicht entpackbar: %s" % body_error))
            continue
        if duplicate_of is not None:
            entries.append(SequenceEntry(
                name=candidate.name, kind=KIND_DUPLICATE,
                reason="identischer Payload wie %s" % duplicate_of))
            continue

        buckets.setdefault(key, []).append({
            "name": candidate.name,
            "path": str(candidate),
            "uncompressed_size": layout.uncompressed_size,
            "padding_size": layout.padding_size,
            "sizes": sizes,
            "layout": layout,
            "digest": digest,
            "payload_sha": None,
        })
        entries.append(SequenceEntry(
            name=candidate.name, kind=KIND_SELECTED, header=header,
            detail={"filetime": header.filetime,
                    "player_level": header.player_level,
                    "playtime": header.playtime,
                    "player_name": header.player_name}))
        headers.append(header)

    return SaveSequence(headers, entries=entries, not_considered=not_considered,
                        candidates=candidates_total, max_files=max_files,
                        limit_applied=limit_applied, stats=stats)


def check_i14_sequence(ctx: SaveContext) -> CheckResult:
    """I-14 — Sequenzkonsistenz ueber mehrere Saves desselben Charakters.

    SORTIERVERANTWORTUNG: Diese Funktion ist die einzige Stelle, die die
    Zeitreihe ordnet. Sie sortiert die von :func:`collect_sequence`
    gelieferten Header nach dem ``filetime``-Wert aus dem Save-Header
    (Tiebreak ``save_number``). ``collect_sequence`` liefert die Kandidaten
    lediglich in Dateinamen-Reihenfolge und benutzt ``mtime`` nur, um bei
    mehr als ``SEQUENCE_MAX_FILES`` Dateien auszuwaehlen, welche ueberhaupt
    gelesen werden — nie als Zeitangabe des Spielstands.

    Geprueft werden Level, Spielzeit und FileTime in chronologischer Folge.
    Regeln, damit kein falscher PASS entsteht:

      * Nur Header mit ``filetime > 0`` und ``player_level > 0`` sind
        verwendbar; unbrauchbare werden verworfen.
      * Nur Header desselben Charakters (``player_name``) bilden eine Sequenz.
      * Paare mit identischem ``filetime`` sind nicht eindeutig geordnet und
        werden nicht bewertet; bleiben weniger als zwei geordnete Paare uebrig,
        lautet das Ergebnis ``NOT_CHECKED``.
      * Eine Spielzeit wird nur verglichen, wenn beide Werte lesbar sind.

    Der Befund traegt unter ``selection`` das Auswahlprotokoll aus
    :func:`collect_sequence`: welche Dateien aufgenommen, welche verworfen
    (mit Grund) und welche wegen des Dateilimits nicht beruecksichtigt wurden.
    Das Auswahlprotokoll beeinflusst die Bewertung nicht — es macht sie nur
    nachvollziehbar.

    REICHWEITE DES URTEILS: Ein ``PASS`` gilt nur fuer die ausgewertete
    Sequenz. Wurden Dateien verworfen oder wegen des Limits nicht
    beruecksichtigt, ist der PASS KEIN Beleg fuer die Konsistenz des gesamten
    vorhandenen Datenbestands — ein Level- oder Spielzeitabfall in einer nicht
    ausgewerteten Datei bleibt unbemerkt. Der Befund weist das unter
    ``selection.limitation`` und in der Klartextausgabe aus.
    """
    selection = {"selection": dict(ctx.sequence_info)} if ctx.sequence_info else {}
    if not ctx.sequence:
        return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                           "keine Vergleichsdaten uebergeben", dict(selection))

    usable = [h for h in ctx.sequence if h.filetime > 0 and h.player_level > 0]
    discarded = len(ctx.sequence) - len(usable)
    if len(usable) < 2:
        return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                           "weniger als zwei brauchbare Header (%d von %d)"
                           % (len(usable), len(ctx.sequence)),
                           {"usable": len(usable), "discarded": discarded,
                            **selection})

    # Nur eine Charakter-Zeitreihe bewerten.
    names = sorted({h.player_name for h in usable})
    if len(names) > 1:
        reference = ctx.header.player_name if ctx.header else None
        if reference is None:
            # R1_6: keine Spielernamen in oeffentlichen Meldungen — nur
            # die Anzahl der gefundenen Charaktere.
            detail = render_public_message("I-14.MULTIPLE_CHARACTERS",
                                            count=len(names))
            return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                               detail,
                               {"character_count": len(names), **selection},
                               internal={"characters": names[:8]})
        usable = [h for h in usable if h.player_name == reference]
        if len(usable) < 2:
            detail = render_public_message("I-14.SINGLE_CHARACTER",
                                            count=len(usable))
            return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                               detail,
                               {"character_count": len(usable), **selection},
                               internal={"character": reference})

    # Hier — und nur hier — entsteht die chronologische Ordnung.
    ordered = sorted(usable, key=lambda h: (h.filetime, h.save_number))
    pairs = [(a, b) for a, b in zip(ordered, ordered[1:]) if a.filetime != b.filetime]
    evidence = {
        "saves": len(ordered),
        "character_count": 1,
        "span": [ordered[0].filetime, ordered[-1].filetime],
        "ordered_pairs": len(pairs),
        "discarded_headers": discarded,
        "duplicate_timestamps": len(ordered) - 1 - len(pairs),
        "order_basis": "Header-FileTime (Tiebreak save_number)",
        **selection,
    }
    if not pairs:
        return CheckResult("I-14", "Sequenzkonsistenz", NOT_CHECKED,
                           "keine eindeutig sortierbare Reihenfolge "
                           "(alle FileTime-Werte identisch)", evidence,
                           internal={"character": ordered[0].player_name})

    problems: list[str] = []
    if evidence["duplicate_timestamps"]:
        # Innerhalb einer Gruppe gleicher FileTime-Werte ist die Reihenfolge
        # unbestimmt; der Uebergang zur naechsten Gruppe nutzt dann ein
        # beliebiges Element. Damit ist die Sequenz nicht vollstaendig
        # belastbar — das darf kein PASS ergeben.
        problems.append("%d Paar(e) mit identischem FileTime — Reihenfolge nicht "
                        "eindeutig" % evidence["duplicate_timestamps"])
    playtime_compared = 0
    for previous, current in pairs:
        if current.player_level < previous.player_level:
            problems.append("Level faellt von %d auf %d"
                            % (previous.player_level, current.player_level))
        before = playtime_minutes(previous.playtime)
        after = playtime_minutes(current.playtime)
        if before is not None and after is not None:
            playtime_compared += 1
            if after < before:
                problems.append("Spielzeit faellt von %d auf %d Minuten"
                                % (before, after))
    evidence["playtime_pairs_compared"] = playtime_compared
    if playtime_compared == 0:
        problems.append("Spielzeit in keinem Paar lesbar")

    if problems:
        return CheckResult("I-14", "Sequenzkonsistenz", WARNING,
                           "; ".join(sorted(set(problems))), evidence,
                           internal={"character": ordered[0].player_name})
    # R1_6: der Spielername darf nicht in der oeffentlichen Meldung stehen.
    detail = render_public_message("I-14.SAVES_MONOTONIC", count=len(ordered))
    return CheckResult(
        "I-14", "Sequenzkonsistenz", PASS,
        detail, evidence,
        internal={"character": ordered[0].player_name})


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
            # R1_6: der Titel stammt aus dem Docstring der Prueffunktion —
            # ein eigener, statischer Text. Er wird ueber die Registry
            # gerendert, damit die Herkunft belegt ist.
            title = render_public_message(
                "GENERIC.CHECK_TITLE",
                title=(check.__doc__ or "").split("\u2014")[-1].strip())
            # R1_6: ``blocked_by`` ist eine Check-ID aus der geschlossenen
            # Menge der CHECKS — kein fremder Text. Die Meldung wird
            # ueber die Registry gerendert, damit die Herkunft belegt ist.
            detail = render_public_message("GENERIC.PREREQUISITE_MISSING",
                                           blocked=blocked_by)
            results.append(CheckResult(
                check_id, title, NOT_CHECKED,
                detail,
                # R1_6: blocked_by ist eine Check-ID aus der geschlossenen
                # CHECKS-Menge — kein fremder Text.
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


def format_sequence_summary(report: IntegrityReport,
                            *, max_lines: int = 5) -> list[str]:
    """Klartextzeilen zur Sequenzauswahl aus dem I-14-Befund.

    Quelle ist ausschliesslich das Auswahlprotokoll im Befund — CLI und UI
    zeigen damit dieselbe Auskunft, unabhaengig davon, woher sie die Sequenz
    bezogen haben. Die Klartextsicht kuerzt lange Listen auf ``max_lines``
    Eintraege; vollstaendig steht alles im JSON (``--json``). Leere Liste,
    wenn keine Sequenz vorlag.

    R1_6 / F-3: oeffentlich sind nur **Anzahlen** und geschlossene
    Zustandsangaben. Dateinamen erscheinen hier nicht mehr.
    """
    check = report.by_id("I-14")
    if check is None:
        return []
    info = check.evidence.get("selection") if check.evidence else None
    if not isinstance(info, Mapping) or not info:
        return []

    lines: list[str] = []
    considered = info.get("considered", 0)
    candidates = info.get("candidates", considered)
    if info.get("limit_applied"):
        lines.append(
            "Sequenzauswahl: %d Datei(en) im Verzeichnis, %d beruecksichtigt "
            "(Limit %s Dateien ueber mtime — die Auswahl, nicht die Reihenfolge)."
            % (candidates, considered, info.get("max_files")))
    else:
        lines.append("Sequenzauswahl: %d Datei(en) im Verzeichnis, alle "
                     "beruecksichtigt." % candidates)

    discarded = list(info.get("discarded", []) or [])
    for entry in discarded[:max_lines]:
        # R1_6: ohne Dateinamen — nur die Ursachenklasse.
        lines.append("  verworfen: %s (%s)"
                     % (entry.get("kind_text", entry.get("kind", "")),
                        entry.get("reason", "ohne Grund")))
    if len(discarded) > max_lines:
        lines.append("  ... und %d weitere verworfene Datei(en) — vollstaendig "
                     "mit --json" % (len(discarded) - max_lines))

    duplicates_count = int(info.get("duplicates_removed_count", 0) or 0)
    if duplicates_count:
        lines.append("  %d Datei(en) nicht doppelt gezaehlt (identischer Payload)"
                     % duplicates_count)

    skipped = info.get("not_considered") or {}
    if skipped.get("count"):
        lines.append("  nicht beruecksichtigt: %d Datei(en) wegen des Limits"
                     % skipped["count"])
    limitation = info.get("limitation")
    if limitation:
        lines.append("  EINSCHRAENKUNG: %s" % limitation)
    lines.append("  Rumpfpruefung: %s" % info.get("body_check", "nicht ausgewiesen"))
    return lines
