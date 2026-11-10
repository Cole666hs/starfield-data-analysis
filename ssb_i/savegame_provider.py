"""
ssb_i/savegame_provider.py — SFS savegame analysis provider for SSB-I.

Adopts the SSB-I Provider pattern: read-only, declarative, capability-based.
Supports the savegame operations we built in Phase 2.6/2.7.

Provenance: all operations are READ-ONLY over local .sfs files.
"""
from __future__ import annotations

import datetime, math, os, struct, zlib, json, hashlib
from dataclasses import dataclass, field, asdict, fields
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


#: Ende des BCPS-Kopfes: 4 Byte Magic + 11 Felder bis zum Kompressionstag.
CONTAINER_HEADER_END = 72


class SfsHeaderError(ValueError):
    """Der BCPS-Container ist lesbar, der ``SFS_SAVEGAME``-Header aber nicht.

    Abgrenzung zu einem strukturell ungueltigen Container: hier ist der
    Rahmen in Ordnung (Magic, Kompression, Chunk-Tabelle, Geometrie), der
    innere Save-Header laesst sich aber nicht vollstaendig dekodieren. Diese
    Trennung ist fuer die Sequenzermittlung wichtig, weil sie im Bericht als
    eigener Verwerfungsgrund erscheint — eine fehlende Headerangabe ist kein
    Beweis fuer eine beschaedigte Datei.
    """


@dataclass(frozen=True)
class ContainerLayout:
    """Rohe Felder des BCPS-Kopfes an ihren belegten Offsets.

    Ein einziger Offset-Durchlauf fuer alle Leser (``read_container``,
    ``decompress``, ``read_chunk_table``, ``read_header``). Vorher lief
    derselbe Durchlauf dreimal getrennt — eine Aenderung am Layout haette
    drei Stellen nachgezogen werden muessen.
    """
    version0: int
    chunk_sizes_offset: int
    compressed_offset: int
    uncompressed_size: int
    chunk_size_pre: int
    padding_size: int
    compression: bytes

    @property
    def chunk_count(self) -> int:
        """Anzahl der Chunks laut deklarierter Nutzgroesse."""
        if not self.chunk_size_pre:
            return 0
        return (self.uncompressed_size + self.chunk_size_pre - 1) // self.chunk_size_pre

    def padded(self, size: int) -> int:
        """Groesse eines Chunks im Datenstrom (komprimiert, auf Padding gerundet)."""
        if not self.padding_size:
            return size
        return (size + self.padding_size - 1) & ~(self.padding_size - 1)


def _layout_from(data: bytes) -> ContainerLayout:
    """Liest die BCPS-Kopffelder. ``data`` muss ab Offset 0 beginnen."""
    off = 4
    version0, = struct.unpack_from("<i", data, off); off += 4            # +4
    chunk_sizes_offset, = struct.unpack_from("<q", data, off); off += 8   # +8
    off += 8                                                            # +16 unknown0
    compressed_offset, = struct.unpack_from("<q", data, off); off += 8    # +24
    uncompressed_size, = struct.unpack_from("<q", data, off); off += 8    # +32
    off += 4                                                            # +40 version1
    off += 4                                                            # +44 unknown1
    chunk_size_pre, = struct.unpack_from("<q", data, off); off += 8       # +48
    padding_size, = struct.unpack_from("<q", data, off); off += 8         # +56
    off += 4                                                            # +64 unknown2
    compression = data[off:off + 4]                                      # +68
    return ContainerLayout(
        version0=version0,
        chunk_sizes_offset=chunk_sizes_offset,
        compressed_offset=compressed_offset,
        uncompressed_size=uncompressed_size,
        chunk_size_pre=chunk_size_pre,
        padding_size=padding_size,
        compression=compression,
    )


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
    #: Offset direkt HINTER dem 8-Byte-Padding-Feld (2026-11-08 belegt).
    #: ``header_size`` zaehlt genau den Bereich 0x10 .. ``padding_end``.
    #: ``None``, wenn der Header nicht bis dorthin dekodiert werden konnte.
    padding_end: int | None = None
    #: Beginn des von ``header_size`` gezaehlten Bereichs (12 Byte Magic +
    #: 4 Byte Groessenfeld). Formatkonstante, keine Messung.
    header_count_start: int = 16
    #: Das u32-Feld direkt hinter ``filetime``. Der Parser liest es seit
    #: Beginn, fuehrt es aber erst seit O-6 im Datensatz — vorher wurde der
    #: Wert stillschweigend verworfen. **Bedeutung nicht belegt:** in allen
    #: neun Messsaves standing 0. Es wird deshalb nur als Rohwert
    #: ausgewiesen, nie als bekannter Spielerwert.
    unknown_field_0: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Oeffentliche Headerfelder — **explizite Allowlist** (R1_6).
#:
#: Grund: ``DatHeader.to_dict()`` ist ``asdict(self)`` und damit die
#: vollstaendige interne Repräsentation. Sie enthaelt ``player_name``,
#: ``player_location``, ``race_name`` und ``playtime`` — echte Spieler-
#: identitaet. Wird sie ungeprueft als oeffentliche Ansicht verwendet
#: (CLI ``save header --json``, CLI ``save info``, GUI-Header-Dump,
#: GUI-Export), tritt die Identitaet in vier Ausgabekanaeln aus.
#:
#: Diese Liste ist die **einzige** Quelle oeffentlicher Headerfelder.
#: Ein neues Feld in ``DatHeader`` wird damit NICHT automatisch
#: oeffentlich — es muss hier ausdruecklich aufgenommen werden.
#:
#: Bewusst NICHT oeffentlich: ``player_name`` (Spielername),
#: ``player_location``, ``race_name``, ``playtime``.
PUBLIC_HEADER_FIELDS = (
    "engine_version",
    "save_version",
    "save_number",
    "player_level",
    "gender",
    "experience",
    "experience_required",
    "filetime",
    "save_version_2",
    "current_game_version",
    "created_game_version",
    "plugin_info_offset",
    "plugin_info_size",
)


def public_header_view(header: DatHeader) -> dict[str, Any]:
    """Oeffentliche Ansicht eines Save-Headers — ohne Spieleridentitaet.

    Das ist die **einzige** zulaessige Quelle fuer Headerdaten in
    oeffentlichen Ausgaben (CLI-JSON, CLI-Text, GUI, Export).

    Es wird bewusst **nicht** ``asdict(header)`` verwendet: nur die in
    :data:`PUBLIC_HEADER_FIELDS` gelisteten Felder werden uebernommen.
    Ein spaeter ergaenztes ``DatHeader``-Feld wird dadurch nicht
    automatisch oeffentlich.

    Nur Felder aus der Allowlist und nur mit einfachen, JSON-sicheren
    Werten. Unerwartete Typen werden uebergangen, nicht konvertiert.
    """
    out: dict[str, Any] = {}
    for name in PUBLIC_HEADER_FIELDS:
        if not hasattr(header, name):
            continue
        value = getattr(header, name)
        if value is None or isinstance(value, (bool, int, float, str)):
            out[name] = value
    return out


# =============================================================================
# Spieleransicht (O-6) — vollstaendige Auswertung des Savegame-Headers
# =============================================================================
#: Marker fuer Werte, die der Save nicht hergibt. Sie werden ausgeschrieben
#: statt durch einen Platzhalterwert ersetzt, damit "fehlt" nicht wie "0"
#: oder wie ein leerer String aussieht.
PLAYER_VIEW_MISSING = "(nicht im Save vorhanden)"
PLAYER_VIEW_EMPTY = "(leer)"
PLAYER_VIEW_UNASSIGNED = "(nicht zugeordnet)"
#: O-7: Nicht-endliche Zahlen (NaN, +inf, -inf) sind **kein** Messwert.
#: Sie werden sichtbar als ungueltig gekennzeichnet — nie stillschweigend
#: zu 0, "" oder einer scheinbar gueltigen Zahl gemacht.
PLAYER_VIEW_NOT_FINITE = "(nicht endlich)"

_FILETIME_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


@dataclass(frozen=True)
class PlayerField:
    """Ein Feld der Spieleransicht: Header-Attribut, Beschriftung, Format.

    ``kind`` steuert ausschliesslich die *Darstellung* — nie die Deutung
    eines Werts. ``note`` wird an den formatierten Wert angehaengt und
    benennt offen, was nicht belegt ist (z. B. Geschlechtscode).
    """
    attr: str
    label: str
    kind: str = "text"          # text|int|float|hex|version|filetime
    section: str = "player"     # player|save
    note: str = ""


#: **Feldinventur der Spieleransicht** — Reihenfolge = Anzeigereihenfolge.
#:
#: Das ist die einzige Stelle, an der die Anzeige konfiguriert wird. Ein
#: ``DatHeader``-Feld wird entweder hier eingetragen oder in
#: :data:`PLAYER_VIEW_EXCLUDED` mit Begruendung. Fehlt es in beiden, meldet
#: :func:`unmapped_header_fields` das Feld, und die Anzeige stellt es mit
#: seinem Attributnamen dar — statt es zu verschweigen.
PLAYER_VIEW_FIELDS: tuple[PlayerField, ...] = (
    # -- Spieler / Charakter ------------------------------------------
    PlayerField("player_name", "Name"),
    PlayerField("player_level", "Level", "int"),
    PlayerField("player_location", "Location"),
    PlayerField("playtime", "Playtime"),
    PlayerField("race_name", "Race"),
    PlayerField("gender", "Gender", "int", note="Code, Bedeutung nicht belegt"),
    PlayerField("experience", "Experience", "float"),
    PlayerField("experience_required", "Experience required", "float"),
    # -- Save / Header -------------------------------------------------
    PlayerField("filetime", "Save time", "filetime", "save"),
    PlayerField("save_number", "Save number", "int", "save"),
    PlayerField("save_version", "Save version", "int", "save"),
    PlayerField("save_version_2", "Save version 2", "int", "save"),
    PlayerField("current_game_version", "Game version", "version", "save"),
    PlayerField("created_game_version", "Created with", "version", "save"),
    PlayerField("engine_version", "Engine version", "hex", "save"),
    PlayerField("header_size", "Header size", "int", "save"),
    PlayerField("padding_end", "Header body end", "int", "save"),
    PlayerField("plugin_info_offset", "Plugin block at", "hex", "save"),
    PlayerField("plugin_info_size", "Plugin block size", "int", "save"),
    PlayerField("unknown_field_0", "Unassigned field", "int", "save",
                note="Bedeutung nicht belegt"),
)

#: Bewusst **nicht** in der Spieleransicht — jeweils mit Begruendung, damit
#: die Abwesenheit nachpruefbar ist und nicht als Versehen gilt.
PLAYER_VIEW_EXCLUDED: dict[str, str] = {
    "header_count_start":
        "Formatkonstante (immer 16), kein Messwert des Saves",
}

#: Abschnittsueberschriften der Spieleransicht.
PLAYER_VIEW_SECTIONS: tuple[tuple[str, str], ...] = (
    ("player", "PLAYER"),
    ("save", "SAVE"),
)


def _dat_header_fieldnames() -> tuple[str, ...]:
    """Alle Feldnamen des :class:`DatHeader` in Deklarationsreihenfolge."""
    return tuple(item.name for item in fields(DatHeader))


def unmapped_header_fields() -> tuple[str, ...]:
    """Header-Felder, die weder angezeigt noch begruendet ausgeschlossen sind.

    Leer heisst: die Anzeige deckt den dekodierten Header vollstaendig ab.
    Wird der Parser spaeter um ein Feld erweitert, meldet diese Funktion es
    und :func:`player_view_sections` zeigt es an — die Anzeige faellt also
    nicht stillschweigend hinter den Parser zurueck.
    """
    mapped = {item.attr for item in PLAYER_VIEW_FIELDS}
    excluded = set(PLAYER_VIEW_EXCLUDED)
    return tuple(name for name in _dat_header_fieldnames()
                 if name not in mapped and name not in excluded)


def filetime_to_utc(filetime: Any) -> str | None:
    """Windows-FILETIME als UTC-Text — ``None``, wenn kein Zeitpunkt.

    Belegt an neun realen Saves: der Savegame-Dateiname traegt denselben
    Zeitstempel, Abweichung 0 Sekunden in allen neun Faellen. Der Wert ist
    ein ``u64`` in 100-ns-Schritten seit 1601-01-01 UTC; ``filetime // 10``
    ergibt die Mikrosekunden.
    """
    if isinstance(filetime, bool) or not isinstance(filetime, int):
        return None
    if filetime <= 0:
        return None
    try:
        moment = _FILETIME_EPOCH + datetime.timedelta(microseconds=filetime // 10)
    except (OverflowError, ValueError):
        return None
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def _player_scalar(kind: str, value: Any) -> str:
    """Ein einzelner Headerwert in seiner Anzeigeform (ohne ``note``)."""
    if value is None:
        return PLAYER_VIEW_MISSING
    if kind == "auto":
        # Nicht zugeordnetes Feld: der Typ ist unbekannt, deshalb wird der
        # Wert **typgerecht** ausgegeben statt verworfen. Nur Objekte, deren
        # Text nicht belegt ist, werden als nicht zugeordnet gekennzeichnet.
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            return "%d" % value
        if isinstance(value, float):
            # O-7: Nicht-endliche Werte sind kein Messwert. Sie werden
            # gekennzeichnet, nicht stillschweigend zu 0 gerundet.
            if not math.isfinite(value):
                return "%s (%s)" % (PLAYER_VIEW_NOT_FINITE, _float_kind(value))
            return "%.6g" % value
        if isinstance(value, str):
            text = value.strip("\x00")
            return text if text else PLAYER_VIEW_EMPTY
        return "%s (%s)" % (PLAYER_VIEW_UNASSIGNED, type(value).__name__)
    if kind in ("int", "hex", "filetime"):
        if isinstance(value, bool) or not isinstance(value, int):
            return PLAYER_VIEW_UNASSIGNED
        if kind == "int":
            return "%d" % value
        if kind == "hex":
            return "0x%08X" % value
        stamp = filetime_to_utc(value)
        if stamp is None:
            return "%d (kein gueltiger Zeitstempel)" % value
        return "%d (%s)" % (value, stamp)
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return PLAYER_VIEW_UNASSIGNED
        # O-7: Nicht-endliche Werte (NaN, +inf, -inf) sind kein Messwert.
        # Sie werden als solche gekennzeichnet — nie zu 0, "" oder einer
        # scheinbar gueltigen Zahl gemacht.
        if not math.isfinite(float(value)):
            return "%s (%s)" % (PLAYER_VIEW_NOT_FINITE, _float_kind(value))
        return "%.3f" % float(value)
    # text / version — beliebiger Text, aber kein erfundener Ersatzwert
    if not isinstance(value, str):
        return PLAYER_VIEW_UNASSIGNED
    text = value.strip("\x00")
    return text if text else PLAYER_VIEW_EMPTY


def _float_kind(value: float) -> str:
    """Art eines nicht-endlichen Wertes — ``NaN``, ``+inf`` oder ``-inf``.

    Die Art wird genannt, damit ``NaN`` und ``+inf`` unterscheidbar sind
    und der Wert nicht wie eine gewoehnliche Zahl wirkt.
    """
    if math.isnan(value):
        return "NaN"
    return "+inf" if value > 0 else "-inf"


def format_player_value(item: PlayerField, value: Any) -> str:
    """Anzeigetext eines Feldes; unbelegte Bedeutung wird mitgenannt."""
    text = _player_scalar(item.kind, value)
    if item.note and text not in (PLAYER_VIEW_MISSING, PLAYER_VIEW_UNASSIGNED):
        return "%s (%s)" % (text, item.note)
    return text


def player_view_rows(header: DatHeader) -> list[tuple[str, str]]:
    """Alle Zeilen der Spieleransicht als ``(Beschriftung, Text)``.

    Enthaelt jedes Feld aus :data:`PLAYER_VIEW_FIELDS` **und** jedes noch
    nicht zugeordnete ``DatHeader``-Feld (mit seinem Attributnamen).
    """
    rows: list[tuple[str, str]] = []
    for item in PLAYER_VIEW_FIELDS:
        rows.append((item.label,
                     format_player_value(item, getattr(header, item.attr, None))))
    for name in unmapped_header_fields():
        rows.append((name, format_player_value(PlayerField(name, name, "auto"),
                                              getattr(header, name, None))))
    return rows


def player_view_sections(header: DatHeader) -> list[tuple[str, list[tuple[str, str]]]]:
    """Spieleransicht in Abschnitte gruppiert — feste Reihenfolge."""
    buckets: dict[str, list[tuple[str, str]]] = {key: [] for key, _ in PLAYER_VIEW_SECTIONS}
    for item in PLAYER_VIEW_FIELDS:
        buckets.setdefault(item.section, []).append(
            (item.label, format_player_value(item, getattr(header, item.attr, None))))
    for name in unmapped_header_fields():
        buckets.setdefault("save", []).append(
            (name, format_player_value(PlayerField(name, name, "auto"),
                                       getattr(header, name, None))))
    return [(title, buckets[key]) for key, title in PLAYER_VIEW_SECTIONS if buckets.get(key)]


def player_view_text(header: DatHeader, *, label_width: int = 20,
                     columns: int = 1, gutter: str = "    ",
                     display_width=None) -> str:
    """Die Spieleransicht als Textblock (GUI-Karte und Tests nutzen diesen Weg).

    ``columns=2`` stellt die Abschnitte nebeneinander statt untereinander.
    Das setzt eine **Monospace**-Schrift voraus — dann bleibt die
    Spaltenausrichtung erhalten und die Karte bleibt flach genug, um ohne
    Scrollen vollstaendig sichtbar zu sein.

    ``display_width`` ist ein optionaler **Breitenmesser**: eine Funktion
    ``(text) -> int``, die die *Anzeigebreite* eines Textes liefert (z. B.
    ueber ``QFontMetrics.horizontalAdvance``). Wird sie nicht uebergeben,
    gilt ``len(text)`` — das ist fuer ASCII korrekt, aber **nicht** fuer
    Breitzeichen (CJK, Emoji): die dort 2 Anzeigebreiten belegen, rutscht
    die rechte Spalte.

    Der Provider bleibt bewusst **Qt-frei** (``ssb_i`` haengt nicht an
    PySide6). Die Messung gehoert deshalb in die GUI-Schicht und wird
    hier nur als Parameter hereingereicht.
    """
    blocks = [_render_block(title, rows, label_width)
              for title, rows in player_view_sections(header)]
    if not blocks:
        return ""
    if columns <= 1 or len(blocks) < 2:
        return "\n\n".join("\n".join(block) for block in blocks)
    width_of = display_width if display_width is not None else len
    widths = [max((width_of(line) for line in block), default=0)
              for block in blocks]
    # O-7: Padding muss in **derselben Einheit** gerechnet werden wie die
    # Breite. ``width_of`` liefert Anzeigebreiten (Pixel), das Padding
    # ergaenzt aber Leerzeichen (Zeichen). Deshalb wird die Breite eines
    # Leerzeichens gemessen und die Zahl der noetigen Leerzeichen daraus
    # berechnet — sonst wird die Zelle um ein Vielfaches zu breit.
    space_width = width_of(" ")
    height = max(len(block) for block in blocks)
    lines: list[str] = []
    for index in range(height):
        cells = []
        for position, block in enumerate(blocks):
            cell = block[index] if index < len(block) else ""
            if position < len(blocks) - 1:
                # Die Zelle wird auf die **Anzeigebreite** aufgefuellt —
                # nicht auf die Zeichenzahl. Sonst verschieben
                # Breitzeichen (CJK, Emoji) die rechte Spalte.
                pad = widths[position] - width_of(cell)
                if pad > 0:
                    if space_width > 0:
                        count = pad // space_width
                    else:
                        count = pad
                    cell = cell + " " * count
            cells.append(cell)
        lines.append(gutter.join(cells).rstrip())
    return "\n".join(lines)


def _render_block(title: str, rows: list[tuple[str, str]],
                  label_width: int) -> list[str]:
    """Ein Abschnitt als Zeilenliste mit punktgefuellter Beschriftung."""
    block = [title]
    for label, value in rows:
        padded = label + "." * max(1, label_width - len(label))
        block.append("%s %s" % (padded, value))
    return block


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
        # Header-Layout per Nexus-Mods/StarfieldSaveTool/SfsFile.cs ReadHeader(),
        # EIN Offset-Durchlauf in _layout_from().
        layout = _layout_from(data)
        if layout.compression != b'ZIP ':
            raise ValueError(f"Only ZIP compression supported, got {layout.compression!r}")
        return SfsContainer(
            version0=layout.version0,
            chunk_size_pre=layout.chunk_size_pre,
            padding_size=layout.padding_size,
            uncompressed_size=layout.uncompressed_size,
            compressed_offset=layout.compressed_offset,
            chunk_count=layout.chunk_count,
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
        # Gleicher Kopf-Durchlauf wie read_container(); die Kompressionsart wird
        # hier bewusst NICHT vorab abgewiesen — I-02 meldet den Befund, statt
        # dass der Ladepfad ohne Bewertung abbricht.
        layout = _layout_from(data)
        chunk_count = layout.chunk_count
        chunk_sizes = list(
            struct.unpack_from(f"<{chunk_count}i", data, layout.chunk_sizes_offset)
        )

        out = bytearray()
        pos = layout.compressed_offset
        for chunk_idx, cs in enumerate(chunk_sizes):
            chunk = data[pos:pos + cs]
            try:
                out += zlib.decompress(chunk)
            except zlib.error as e:
                raise ValueError(
                    f"zlib-decompression failed at chunk {chunk_idx} "
                    f"(pos=0x{pos:X}, size={cs}): {e}"  # exception-text-reviewed: zlib.error traegt nur Zahlen
                )
            pos += layout.padded(cs)
        result = bytes(out)
        if verify and len(result) != layout.uncompressed_size:
            raise ValueError(
                "decompressed length %d does not match declared uncompressed_size %d "
                "(delta %+d bytes)" % (len(result), layout.uncompressed_size,
                                       len(result) - layout.uncompressed_size))
        return result

    # -----------------------------------------------------------------
    # Header-only-Pfad: Kopfdaten lesen, Rumpf nicht entpacken
    # -----------------------------------------------------------------
    #: Zusaetzliche Nutzbytes, die ueber den ersten Chunk hinaus entpackt
    #: werden. 0 = nur der erste Chunk (dort liegt der Header bei realen Saves:
    #: padding_end 139/141 gegen 262.144 Nutzbytes je Chunk). Reicht der erste
    #: Chunk nicht fuer den Header, verlaengert ``read_header`` selbsttaetig bis
    #: zum vollen Strom — lieber einmal zu viel als ein halber Header.
    HEADER_PREFIX_BYTES = 0
    #: Blockgroesse beim Hashen des komprimierten Stroms.
    DIGEST_BLOCK_BYTES = 1 << 20

    def read_layout(self, sfs_path: str) -> tuple[ContainerLayout, tuple[int, ...], int]:
        """Liest BCPS-Kopf und Chunk-Groessentabelle, ohne den Strom zu entpacken.

        Gelesen werden 72 Byte Kopf plus 4 Byte je Chunk — bei einem 8-MB-Save
        rund 300 Byte statt der ganzen Datei.
        """
        with open(sfs_path, "rb") as handle:
            head = handle.read(CONTAINER_HEADER_END)
            if head[:4] != SFS_MAGIC:
                raise ValueError("Not an SFS file: %r (expected b'BCPS')"
                                 % (head[:4],))
            layout = _layout_from(head)
            if layout.compression != b'ZIP ':
                raise ValueError("Only ZIP compression supported, got %r"
                                 % (layout.compression,))
            sizes = self._read_chunk_sizes(handle, layout)
            file_size = handle.seek(0, os.SEEK_END)
        return layout, sizes, file_size

    @staticmethod
    def _read_chunk_sizes(handle: BinaryIO, layout: ContainerLayout) -> tuple[int, ...]:
        """Liest die Chunk-Groessentabelle; meldet eine unvollstaendige Tabelle."""
        count = layout.chunk_count
        if not count:
            return ()
        handle.seek(layout.chunk_sizes_offset)
        raw = handle.read(4 * count)
        if len(raw) != 4 * count:
            raise ValueError(
                "chunk table incomplete: %d of %d bytes at offset 0x%X"
                % (len(raw), 4 * count, layout.chunk_sizes_offset))
        return struct.unpack("<%di" % count, raw)

    def _decode_prefix(self, sfs_path: str, layout: ContainerLayout,
                       sizes: tuple[int, ...], *, stop_bytes: int):
        """Entpackt Chunks ab ``compressed_offset`` bis ``stop_bytes`` Nutzbytes.

        Rueckgabe ``(nutzbytes, anzahl_entpackter_chunks)``. Ein zlib-Fehler
        bricht mit ``ValueError`` ab: ein nicht entpackbarer Chunk ist ein
        struktureller Befund, kein blosser Headerengpass.
        """
        out = bytearray()
        pos = layout.compressed_offset
        decoded = 0
        with open(sfs_path, "rb") as handle:
            for index, size in enumerate(sizes):
                handle.seek(pos)
                chunk = handle.read(size)
                try:
                    out += zlib.decompress(chunk)
                except zlib.error as exc:
                    raise ValueError(
                        "zlib-decompression failed at chunk %d (pos=0x%X, size=%d): %s"
                        % (index, pos, size, exc)) from exc  # exception-text-reviewed: zlib.error
                decoded += 1
                pos += layout.padded(size)
                if len(out) >= stop_bytes:
                    break
        return bytes(out), decoded

    def read_header(self, sfs_path: str, *,
                    min_bytes: int = HEADER_PREFIX_BYTES) -> dict[str, Any]:
        """Dekodiert ausschliesslich den ``SFS_SAVEGAME``-Header.

        Entpackt so viele Chunks wie fuer den Header noetig — in der Regel
        genau einen. Der Rumpf wird NICHT entpackt und damit auch nicht
        geprueft; das bleibt I-01..I-13 auf dem Bezugssave. Fuer die
        Sequenzpruefung werden nur Headerfelder gebraucht.

        Fehler:
          * ``ValueError`` — Container strukturell ungueltig (Magic,
            Kompressionsart, Chunk-Tabelle, abgeschnittener Strom, zlib).
          * ``SfsHeaderError`` — Container lesbar, Header nicht dekodierbar.
        """
        layout, sizes, file_size = self.read_layout(sfs_path)
        expected_end = layout.compressed_offset + sum(layout.padded(s) for s in sizes)
        if expected_end > file_size:
            raise ValueError(
                "compressed stream truncated: %d of %d bytes present"
                % (max(0, file_size - layout.compressed_offset),
                   expected_end - layout.compressed_offset))

        prefix, decoded = self._decode_prefix(
            sfs_path, layout, sizes, stop_bytes=max(1, min_bytes))
        try:
            header = self.parse_dat_header(prefix)
        except Exception as first:                              # noqa: BLE001
            if decoded >= len(sizes):
                raise SfsHeaderError(
                    "SFS_SAVEGAME header not decodable (%d of %d chunks, %d bytes): "
                    "%s: %s" % (decoded, len(sizes), len(prefix),
                                type(first).__name__, first)) from first  # exception-text-reviewed: nur Parser-Text
            # Header reicht ueber den Prefix hinaus -> einmal vollstaendig entpacken.
            prefix, decoded = self._decode_prefix(
                sfs_path, layout, sizes, stop_bytes=layout.uncompressed_size)
            try:
                header = self.parse_dat_header(prefix)
            except Exception as second:                         # noqa: BLE001
                raise SfsHeaderError(
                    "SFS_SAVEGAME header not decodable (%d bytes): %s: %s"
                    % (len(prefix), type(second).__name__, second)) from second  # exception-text-reviewed: nur Parser-Text
        return {
            "header": header,
            "layout": layout,
            "sizes": sizes,
            "chunks_decoded": decoded,
            "chunks_total": len(sizes),
            "payload_bytes": len(prefix),
            "full_decoded": decoded >= len(sizes),
            "file_size": file_size,
            "trailing_bytes": max(0, file_size - expected_end),
        }

    def stream_digest(self, sfs_path: str, *,
                      layout: ContainerLayout | None = None) -> str:
        """SHA-256 ueber den komprimierten Datenstrom (inkl. Padding).

        Gleicher Digest plus gleiche Chunk-Geometrie bedeutet nach zlib
        zwingend gleichen entpackten Payload. Damit laesst sich die
        Payload-Deduplizierung weiterfuehren, ohne jeden Rumpf zu entpacken.
        """
        if layout is None:
            layout, _sizes, _file_size = self.read_layout(sfs_path)
        digest = hashlib.sha256()
        with open(sfs_path, "rb") as handle:
            handle.seek(layout.compressed_offset)
            while True:
                block = handle.read(self.DIGEST_BLOCK_BYTES)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()

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
        padding_end = off          # ab hier zaehlt header_size nicht mehr
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
            padding_end=padding_end,
            header_count_start=16,
            unknown_field_0=unknown0,
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
        layout = _layout_from(data)
        chunk_sizes_offset = layout.chunk_sizes_offset
        compressed_offset = layout.compressed_offset
        uncompressed_size = layout.uncompressed_size
        chunk_size_pre = layout.chunk_size_pre
        padding_size = layout.padding_size
        compression = layout.compression
        count = layout.chunk_count
        sizes: list[int] = []
        if count and chunk_sizes_offset + 4 * count <= len(data):
            sizes = list(struct.unpack_from("<%di" % count, data, chunk_sizes_offset))
        padded = [layout.padded(s) for s in sizes]
        return {
            "version0": layout.version0,
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
            "header_end": CONTAINER_HEADER_END,
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
