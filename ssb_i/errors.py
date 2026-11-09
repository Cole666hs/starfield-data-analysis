"""ssb_i/errors.py — sichere Fehlerdarstellung fuer oeffentliche Ausgaben.

GRUNDSATZ
    Oeffentliche Fehlermeldungen werden aus **kontrollierten Bestandteilen**
    gebaut: Fehlerklasse, ``errno`` und eine feste Liste eigener, gefahrloser
    Meldungstexte. Ein roher Exception-Text wird NICHT ungeprueft uebernommen.

    ``exc.strerror`` gilt hier ausdruecklich NICHT als vertrauenswuerdig: eine
    selbst gebaute ``OSError``-Instanz kann dort jeden beliebigen Text tragen,
    auch einen Dateipfad (im unabhaengigen Review nachgewiesen:
    ``OSError("/home/cole/.../x.sfs")`` und ``OSError(2, "<pfad>")``). Deshalb
    wird die Betriebssystemmeldung ausschliesslich aus der festen Tabelle
    :data:`ERRNO_MESSAGES` geholt; unbekannte oder fehlende ``errno``-Werte
    ergeben eine generische Meldung ohne Text und ohne Pfad.

    Damit haengt der Schutz nicht an einem Pfadmuster. Ein Musterfilter kann
    nur bekannte Formen abfangen; die Entscheidung „dieser Text darf hinaus"
    faellt hier stattdessen konservativ: unbekannter Text wird verworfen, nicht
    gefiltert.

SICHERE EIGENE MELDUNGEN (R1.2)
    Eine eigene Meldung wird nicht mehr ueber ein Praefix erkannt, sondern gegen
    eine **exakte Vorlage** aus :data:`SAFE_MESSAGE_TEMPLATES` geprueft. Jede
    Vorlage nennt ihre Platzhalter; fuer jeden Platzhalter ist eine
    **Typklasse** festgelegt:

    ============  ==========================================================
    Platzhalter   erlaubter Inhalt
    ============  ==========================================================
    ``{bytes}``   **keine** Ausgabe der Eingabebytes. Der Platzhalter liefert
                  eine statische, eigene Beschreibung aus
                  :data:`BYTES_DESCRIPTIONS` — erkannt ueber ein
                  Magic-**Praefix** — oder :data:`BYTES_UNKNOWN`.
    ``{int}``     vorzeichenlose ganze Zahl
    ``{hex}``     Hexadezimalzahl ohne ``0x``
    ``{class}``   schlichter Bezeichner (Klassenname eines Fehlers)
    ``{reason}``  Begruendung, die **selbst** einer Vorlage entspricht
    ``{zlib}``    statische Beschreibung des extrahierten zlib-Fehlercodes
                  aus :data:`ZLIB_CODES`
    ============  ==========================================================

    Es gibt bewusst **keinen** Platzhalter fuer eine freie Zeichenkette. Eine
    eigene Meldung kann dadurch keinen fremden, pfadtragenden Text
    einschleusen — unabhaengig davon, wie dieser aussieht. Passt ein Wert
    nicht zu seiner Typklasse, wird die **gesamte** Meldung verworfen; die
    Ausgabe bleibt dann bei der Fehlerklasse.

    Diese Regel gilt fuer jede eigene Meldung, auch fuer neu hinzugefuegte:
    eine Vorlage, deren Platzhalter eine Zeichenkette annimmt, gibt es nicht.

    STRUKTURELLE TRENNUNG (R1.2 — Befund N1)
        Zwei Platzhalter geben **Eingabedaten** wieder: ``{bytes}`` (Datei-
        inhalt) und ``{zlib}`` (CPython-Fehlermeldung). Beide tragen jetzt
        **keinen Eingabetext** in die oeffentliche Meldung:

        * ``{bytes}`` liefert nur noch eine statische Beschreibung aus
          :data:`BYTES_DESCRIPTIONS`. Die Bytefolge selbst — und damit jeder
          Dateiname, Pfad oder Byte-Rest, an welcher Position er auch steht —
          gelangt **nie** in eine oeffentliche Ausgabe.
        * ``{zlib}`` extrahiert den Fehlercode an der Position, an der
          CPython ihn schreibt (``Error -N``), und liefert die statische
          Beschreibung aus :data:`ZLIB_CODES`. Der CPython-Text wird
          verworfen, auch wenn er einen Pfad enthaelt.

        Die *interne* Diagnose (:func:`diagnostic_error`) traegt die
        Originalbytes und den Originaltext weiterhin unveraendert. Sie ist
        genau dafuer da und hat keine oeffentliche Aufrufstelle.

        Damit ist die Grenze nicht mehr musterbasiert, sondern **strukturell**:
        es gibt keinen Pfad, keinen Dateinamen und keinen fremden Text in
        oeffentlichen Meldungen, unabhaengig von Position, Steuerzeichen und
        Laenge der Eingabe.

ZWEI KANAELE
    * :func:`public_error` — fuer CLI, JSON, UI-Dialoge, Statuszeilen.
      Enthaelt nie einen Dateipfad aus einer Exception.
    * :func:`diagnostic_error` — nur fuer interne Auswertung und Tests.
      Enthaelt den vollen Text und darf NICHT in oeffentliche Ausgaben.

KEINE ABHAENGIGKEITEN
    Das Modul importiert nichts aus ``ssb_i`` oder ``ssb_ui``; es kann von
    Core, CLI und UI gemeinsam benutzt werden, ohne einen Zyklus zu bilden.
"""
from __future__ import annotations

import ast
import re

#: Platzhalter fuer bereinigte Pfadangaben (Verteidigung in der Tiefe).
PUBLIC_PATH_PLACEHOLDER = "<pfad>"
#: Obergrenze fuer uebernommene Meldungstexte in oeffentlichen Ausgaben.
PUBLIC_TEXT_MAX = 200
#: Bekannte Magic-/Kennungsbytefolgen mit fester, eigener Beschreibung.
#:
#: Der Platzhalter ``{bytes}`` gibt **keine Eingabebytes** mehr wieder. Er
#: liefert ausschliesslich eine **statische, selbst formulierte** Beschreibung
#: aus dieser Tabelle — oder eine neutrale Kurzmeldung, wenn die Bytefolge
#: nicht bekannt ist.
#:
#: Damit kann die oeffentliche Meldung keine Eingabedaten mehr tragen: es
#: gibt keinen Pfad, keinen Dateinamen und keinen beliebigen Byte-Rest, weil
#: die Bytefolge selbst **nie** in die Ausgabe gelangt.
#:
#: Schluessel ist ein **Praefix** der Bytefolge: so wird auch ein Magic mit
#: angehaengten Steuerzeichen erkannt (``b'MZ\\x00\\x00'`` -> DOS-Header).
#: Der Eintrag mit dem **laengsten** passenden Praefix gewinnt.
BYTES_DESCRIPTIONS = {
    b"BCPS": "BCPS container signature",
    b"ZIP ": "ZIP compression marker",
    b"LZMA": "LZMA compression marker",
    b"MZ": "DOS executable header",
    b"PK\x03\x04": "ZIP archive header",
    b"\x7fELF": "ELF executable header",
    b"\x89PNG": "PNG image header",
    b"SFS_SAVEGAME": "SFS_SAVEGAME inner header signature",
    b"NOT_A_SAVEGA": "unknown container signature",
}

#: Neutrale Beschreibung fuer eine unbekannte Bytefolge.
#:
#: Bewusst ohne Inhalt: die Bytefolge selbst wird nicht genannt, aber auch
#: nicht geraten. Die Meldung sagt damit "es waren Bytes, aber keine
#: bekannte Kennung" — ohne etwas ueber den Nutzerinhalt preiszugeben.
BYTES_UNKNOWN = "unknown signature"

#: Maximale Laenge einer als Bytefolge uebernommenen Nutzangabe.
SAFE_BYTES_MAX = 16

#: Eigene Meldungen, die gefahrlos oebernommen werden duerfen.
#:
#: Die Eintraege sind **exakte Vorlagen** mit benannten Platzhaltern. Der
#: Platzhaltername bestimmt die erlaubte Typklasse (siehe Modul-Dokstring).
#: Es gibt keine Vorlage mit einem Platzhalter fuer freie Zeichenketten.
SAFE_MESSAGE_TEMPLATES = (
    "Not an SFS file: {bytes} (expected b'BCPS')",
    "Not an SFS file: {bytes}",
    "Only ZIP compression supported, got {bytes}",
    "Not a DAT file: starts with {bytes}",
    "zlib-decompression failed at chunk {int} (pos=0x{hex}, size={int}): {zlib}",
    "decompressed length {int} does not match declared uncompressed_size {int} "
    "(delta {int} bytes)",
    "chunk table incomplete: {int} of {int} bytes at offset 0x{hex}",
    "compressed stream truncated: {int} of {int} bytes present",
    "SFS_SAVEGAME header not decodable ({int} of {int} chunks, {int} bytes): "
    "{class}: {reason}",
    "SFS_SAVEGAME header not decodable ({int} bytes): {class}: {reason}",
    "blob too small for DOS header",
    "bad PE signature",
    "zero optional header size",
    "not PE32+ (magic=0x{hex})",
)

#: Praefix-Anfang der eigenen Meldungen. Nur noch dokumentarisch: die
#: Entscheidung faellt ueber die Vorlagen, nicht ueber dieses Praefix.
SAFE_MESSAGE_PREFIXES = tuple(
    sorted({tpl.split("{", 1)[0] for tpl in SAFE_MESSAGE_TEMPLATES}))

#: Zulaessiges Muster fuer einen ``zlib.error``-**Code**: ``Error -N``.
#:
#: CPython liefert keinen strukturierten Fehlercode (gemessen: ``zlib.error``
#: hat weder ``errno`` noch ``code`` — der Code steht ausschliesslich im
#: Text). Der Code wird deshalb an der **Position** extrahiert, an der ihn
#: CPython schreibt, und danach gegen diese Tabelle geprueft. Alle fuenf
#: realen CPython-Fehlertexte folgen dieser Form:
#:
#:   ``Error -3 while decompressing data: incorrect header check``
#:   ``Error -5 while decompressing data: incomplete or truncated stream``
#:
#: Diese Regex ist die **einzige** Stelle, die das CPython-Format kennt.
#: Alles Weitere arbeitet mit der extrahierten Zahl.
_ZLIB_CODE_RE = re.compile(r"^Error\s+(-?\d+)\b")

#: Bekannte ``zlib``-Fehlercodes mit fester, eigener Beschreibung.
#:
#: Der CPython-Text wird **nicht** uebernommen — er ist fremder Text, der
#: je nach Version und Sprachbindung unterschiedlich formuliert ist. Der Code
#: ist stabil und traegt die Bedeutung. Die Tabelle haelt ausschliesslich
#: selbst formulierte, statische Beschreibungen; kein fremder Text.
ZLIB_CODES = {
    -1: "zlib: no progress possible",
    -2: "zlib: internal error (invalid stream state)",
    -3: "zlib: data error (corrupt or unsupported compressed data)",
    -4: "zlib: memory allocation failed",
    -5: "zlib: buffer error (incomplete or truncated stream)",
    -6: "zlib: version mismatch",
}

#: Fallback fuer einen zlib-Fehler ohne erkannten Code: nur die Fehlerklasse.
ZLIB_UNKNOWN = "zlib: decompression failed"

#: Kontrollierte, pfadfreie Texte fuer bekannte ``errno``-Werte.
#:
#: Bewusst eine feste Tabelle und **nicht** ``os.strerror()``: der
#: Betriebssystemtext ist nicht pruefbar (unter Windows lokalisiert) und bei
#: selbst gebauten ``OSError``-Instanzen ohnehin frei waehlbar. Die Texte
#: entsprechen den gaengigen englischen Systemmeldungen, damit die bisherige
#: Ausgabe fuer echte Dateisystemfehler unveraendert bleibt.
ERRNO_MESSAGES = {
    1: "Operation not permitted",
    2: "No such file or directory",
    3: "No such process",
    4: "Interrupted system call",
    5: "Input/output error",
    6: "No such device or address",
    7: "Argument list too long",
    9: "Bad file descriptor",
    11: "Resource temporarily unavailable",
    12: "Cannot allocate memory",
    13: "Permission denied",
    14: "Bad address",
    16: "Device or resource busy",
    17: "File exists",
    18: "Invalid cross-device link",
    19: "No such device",
    20: "Not a directory",
    21: "Is a directory",
    22: "Invalid argument",
    23: "Too many open files in system",
    24: "Too many open files",
    26: "Text file busy",
    27: "File too large",
    28: "No space left on device",
    30: "Read-only file system",
    31: "Too many links",
    32: "Broken pipe",
    36: "File name too long",
    40: "Too many levels of symbolic links",
    75: "Value too large for defined data type",
    95: "Operation not supported",
    110: "Connection timed out",
    122: "Disk quota exceeded",
}

#: Meldung fuer fehlende, unbekannte oder unbrauchbare ``errno``-Werte.
GENERIC_OS_ERROR = "unclassified OS error"

#: Module, deren Exception-Klassenname allein nicht aussagekraeftig ist
#: (``struct.error`` heisst nur "error"). Reine Diagnoseverbesserung — der
#: Modulname ist ein Importbezeichner, kein Dateipfad.
_QUALIFIED_MODULES = ("struct", "zlib")

#: Endungen, die in einer oeffentlichen Meldung auf einen Dateinamen deuten.
#: Eine eigene Meldung, die so etwas traegt, wird auf die Klasse verkuerzt.
#: Bewusst grob: die sichere Richtung ist der Diagnoseverlust, nicht der Pfad.
_PATHLIKE_EXTENSIONS = (
    ".sfs", ".esm", ".esp", ".ba2", ".exe", ".dll", ".pdb", ".dat", ".cdb",
    ".txt", ".log", ".json", ".ini", ".zip", ".tmp", ".bak", ".bin", ".so",
    ".py", ".md",
)

_QUOTED_PATH_RE = re.compile(r"""(['"])([^'"]*[/\\][^'"]*)\1""")
_POSIX_PATH_RE = re.compile(r"(?<![\w.])/(?:[\w.\-+@]+/?){1,}")
_WINDOWS_PATH_RE = re.compile(r"(?<![\w.])[A-Za-z]:\\[^\s'\"]*")

#: Zeichen, die in einer uebernommenen Bytefolge **nicht** vorkommen duerfen:
#: sie wuerden einen Pfad oder eine Pfadkomponente andeuten.
_PATH_BYTES = b"/\\:"


def strip_paths(text: str) -> str:
    """Entfernt pfadartige Teile und normalisiert Leerraum.

    Nur eine zweite Sicherung hinter der Vorlagen-Entscheidung, keine
    eigenstaendige Garantie.
    """
    out = _QUOTED_PATH_RE.sub(
        lambda match: match.group(1) + PUBLIC_PATH_PLACEHOLDER + match.group(1), text)
    out = _WINDOWS_PATH_RE.sub(PUBLIC_PATH_PLACEHOLDER, out)
    out = _POSIX_PATH_RE.sub(PUBLIC_PATH_PLACEHOLDER, out)
    return " ".join(out.split())


def _message_of(exc: BaseException) -> str:
    """``str(exc)``, aber robust: ein kaputtes ``__str__`` darf nichts werfen."""
    try:
        return str(exc)
    except Exception:                                          # noqa: BLE001
        return ""


def _is_plain_identifier(name: object) -> bool:
    """True, wenn ``name`` ein schlichter Python-Bezeichner ist.

    Ein Bezeichner kann keinen Pfad enthalten: weder ``/`` noch ``\\`` noch
    ``:`` noch Leerzeichen sind erlaubt, und das erste Zeichen muss ein
    Buchstabe oder Unterstrich sein.
    """
    if not isinstance(name, str) or not name:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def _class_name(exc: BaseException) -> str:
    """Klassenname der Exception — bei ``struct``/``zlib`` mit Modulpräfix.

    ``struct.error.__name__`` ist nur ``"error"``; das allein ist als öffentliche
    Meldung wertlos. Der Modulname ist ein Importbezeichner und kann keinen
    Dateipfad enthalten.

    Der Name wird zusaetzlich darauf geprueft, dass er wie ein Python-Bezeichner
    aussieht. Ein manipulierter ``__name__`` (etwa ein Pfad) wird verworfen und
    durch ``Error`` ersetzt — sonst kaeme ein fremder Text ueber den
    Klassennamen in die oeffentliche Ausgabe.
    """
    cls = type(exc)
    name = cls.__name__
    if not _is_plain_identifier(name):
        return "Error"
    module = getattr(cls, "__module__", "")
    if name == "error" and module in _QUALIFIED_MODULES:
        return "%s.%s" % (module, name)
    return name


def _os_error_detail(exc: OSError) -> str:
    """Betriebssystemmeldung aus der festen ``errno``-Tabelle.

    Weder ``str(exc)``/``repr(exc)`` (dort steht der Pfad), noch ``exc.strerror``
    (bei selbst gebauten Instanzen frei waehlbar), noch ``exc.filename``/
    ``exc.args`` werden verwendet. Fehlt der ``errno`` oder ist er unbekannt,
    bleibt eine generische Meldung.
    """
    try:
        code = exc.errno
    except Exception:                                         # noqa: BLE001
        return GENERIC_OS_ERROR
    if isinstance(code, bool) or not isinstance(code, int):
        return GENERIC_OS_ERROR
    detail = ERRNO_MESSAGES.get(code, GENERIC_OS_ERROR)
    if type(exc) is OSError:
        # Bei reinem OSError ist der errno die einzige Unterscheidung.
        return "errno %d: %s" % (code, detail)
    return detail


def _looks_pathlike(text: str) -> bool:
    """Grober Nachweis, dass ein Text einen Pfad oder Dateinamen traegt.

    Angewandt auf einen **fertigen** Meldungstext. Bytes-Schreibweisen
    (``b'...'``) werden dabei ausgeklammert: sie tragen einen Backslash nur
    als Escape-Zeichen (``b'MZ\\x00\\x00'``) und sind kein Pfad. Die in
    solchen Schreibweisen enthaltenen Bytes sind einzeln typgeprueft.
    """
    without_bytes = re.sub(r"b'[^']*'|b\"[^\"]*\"", "", text)
    if "\\" in without_bytes:
        return True
    lowered = without_bytes.lower()
    return any(token in lowered for token in _PATHLIKE_EXTENSIONS)


def _contains_path_chars(text: str) -> bool:
    """True, wenn der Text einen Pfad **mit Trennzeichen** enthaelt.

    Geprueft wird auf ein Pfadtrennzeichen (``/`` oder ``\\``) und auf eine
    Laufwerkskennung (``C:\\...``). Die Laufwerkskennung muss aus **einem**
    Buchstaben, einem Doppelpunkt und einem Trennzeichen bestehen — sonst
    waere das blosse Wortende eines eigenen Satzes (``"Not an SFS file: ..."``)
    ein Pfadzeichen, ebenso wenig wie die Bytes-Schreibweise ``b'BCPS'``.
    """
    without_bytes = re.sub(r"b'[^']*'|b\"[^\"]*\"", "", text)
    if "/" in without_bytes or "\\" in without_bytes:
        return True
    # Laufwerkskennung: ein einzelner Buchstabe + ':' + Trennzeichen.
    return re.search(r"[A-Za-z]:[\\/]", without_bytes) is not None


# ---------------------------------------------------------------------------
# Platzhalterpruefung
# ---------------------------------------------------------------------------
def _render_bytes(text: object) -> str | None:
    """Bytefolge -> **feste, eigene Beschreibung** (nie die Bytes selbst).

    Der Platzhalter gibt die Eingabebytes **nicht** wieder. Er liefert
    ausschlich eine statische Beschreibung aus :data:`BYTES_DESCRIPTIONS`
    oder :data:`BYTES_UNKNOWN`.

    Damit ist die Trennung zwischen interner und oeffentlicher Diagnose
    **strukturell**, nicht musterbasiert:

    * Die Bytefolge gelangt nie in die oeffentliche Meldung — also auch
      kein Dateiname, kein Pfad und kein beliebiger Byte-Rest, unabhaengig
      davon, an welcher Position sie steht und welche Steuerzeichen sie
      enthaelt.
    * Die *interne* Diagnose (:func:`diagnostic_error`) traegt die Bytes
      weiterhin unveraendert — sie ist genau dafuer da und hat keine
      oeffentliche Aufrufstelle.

    Geprueft wird nur noch, ob der Wert ueberhaupt eine echte Bytes-
    Schreibweise ist und nicht zu lang ist; die Entscheidung ueber die
    Ausgabe trifft danach die Tabelle, nicht eine Heuristik.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not (stripped.startswith("b'") or stripped.startswith('b"')):
        return None
    try:
        value = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(value, bytes):
        return None
    if len(value) > SAFE_BYTES_MAX:
        return None
    if any(byte in _PATH_BYTES for byte in value):
        # Pfadzeichen: die Bytefolge traegt einen Pfad — nie nennen.
        return BYTES_UNKNOWN
    if _looks_like_filename(value):
        # Dateiname in Nutzerinhalt: nie nennen.
        return BYTES_UNKNOWN
    # Magic als Praefix: der laengste passende Eintrag gewinnt. So wird auch
    # ein Magic mit angehaengten Steuerzeichen erkannt (b'MZ\x00\x00').
    best = None
    best_len = -1
    for magic, description in BYTES_DESCRIPTIONS.items():
        if value.startswith(magic) and len(magic) > best_len:
            best = description
            best_len = len(magic)
    return best if best is not None else BYTES_UNKNOWN


def _printable_runs(value: bytes) -> list[str]:
    """Alle maximalen druckbaren ASCII-Laeufe der Bytefolge.

    Ein Lauf endet an jedem Byte, das nicht druckbar ist (``< 0x20`` oder
    ``> 0x7E``). Steuerzeichen trennen also Laeufe voneinander — das ist
    entscheidend, weil ein Name **hinter** Steuerzeichen beginnen kann.
    """
    runs: list[str] = []
    current = bytearray()
    for byte in value:
        if 0x20 <= byte <= 0x7E:
            current.append(byte)
            continue
        if current:
            runs.append(bytes(current).decode("ascii"))
            current = bytearray()
    if current:
        runs.append(bytes(current).decode("ascii"))
    return runs


def _looks_like_filename(value: bytes) -> bool:
    """True, wenn die Bytefolge an **irgendeiner** Stelle einen Namen traegt.

    Geprueft wird die vollstaendige Bytefolge, nicht nur ihr druckbarer
    Anfang: die ersten 12 Byte einer Datei koennen mit einem Namen
    beginnen (``b'Save.sfs\\x00\\x00\\x00\\x00'``) — aber der Name kann auch
    **hinter** Steuerzeichen stehen (``b'\\x00Save.sfs'``). Eine Pruefung nur
    des An fangs liess genau diese Form durch.

    Ein Lauf, der einen **Punkt** enthaelt, ist ein Name mit Endung
    (``Save.sfs``, ``Spielstand.dat``) — ein Formatkennzeichen wie
    ``b'kein'`` oder ``b'NOT_A_SAVEGA'`` enthaelt keinen Punkt. Zusaetzlich
    gilt die bekannte Endungsliste fuer Laeufe ohne Punkt.

    Der Punkt ist das entscheidende Kriterium, nicht die Endungsliste: eine
    Endungsliste allein faengt ``Save.sfsx`` nicht, ein Punkt schon.
    """
    for run in _printable_runs(value):
        if "." in run:
            return True
        lowered = run.lower()
        if any(lowered.endswith(token) for token in _PATHLIKE_EXTENSIONS):
            return True
    return False


def _render_int(text: object) -> str | None:
    """Ganzzahlige Zahl (optional mit Vorzeichen) — oder ``None``.

    Negative Werte sind zulaessig: die Differenz zwischen deklarierter und
    tatsaechlicher Laenge kann negativ sein (``delta -100 bytes``).
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("+"):
        stripped = stripped[1:]
    if not stripped:
        return None
    if stripped.startswith("-"):
        digits = stripped[1:]
    else:
        digits = stripped
    if not digits.isdigit():
        return None
    return stripped


def _render_hex(text: object) -> str | None:
    """Hexadezimalzahl ohne ``0x`` — oder ``None``."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or not all(ch in "0123456789ABCDEFabcdef" for ch in stripped):
        return None
    return stripped


def _render_class(text: object) -> str | None:
    """Klassenname eines Fehlers — oder ``None``, wenn er unplausibel ist."""
    if not _is_plain_identifier(text):
        return None
    return text.strip()


def _render_zlib(text: object) -> str | None:
    """``zlib.error``-Code -> feste, eigene Beschreibung.

    Der CPython-Text wird **nicht** uebernommen: er ist fremder Text, der
    je nach Version und Sprachbindung unterschiedlich formuliert ist. Statt
    dessen wird der Fehlercode an der Position extrahiert, an der CPython
    ihn schreibt (``Error -N``), und gegen :data:`ZLIB_CODES` geprueft.

    Ergebnis ist immer eine **statische, selbst formulierte** Beschreibung
    aus dieser Tabelle — kein fremder Text, kein Pfad, kein Exception-Text.
    Alles nach dem Code wird **verworfen**, auch wenn dort ein Pfad steht.

    Drei Faelle:

    * bekannter Code (``-3``, ``-5``, ...) -> feste Beschreibung aus
      :data:`ZLIB_CODES`;
    * unbekannter, aber wohlgeformter Code (``Error -99``) -> generische
      Beschreibung :data:`ZLIB_UNKNOWN`. Der Chunk-Kontext der Meldung
      bleibt damit erhalten — der Verlust entstuende allein der fremden
      Formulierung;
    * kein ``Error -N``-Prefix (z. B. ein eingebetteter Pfad oder ein
      beliebiger Exception-Text) -> ``None``. Die Meldung wird dann
      verworfen und die Ausgabe bleibt bei der Fehlerklasse (fail-closed).
    """
    if not isinstance(text, str):
        return None
    match = _ZLIB_CODE_RE.match(text.strip())
    if match is None:
        return None
    try:
        code = int(match.group(1))
    except ValueError:
        return None
    return ZLIB_CODES.get(code, ZLIB_UNKNOWN)


def _render_reason(text: object, depth: int = 0) -> str | None:
    """Begruendungstext eines Parser-Fehlers.

    Nur angenommen, wenn er selbst wieder einer **eigenen, geprueften**
    Meldung entspricht (also dem Muster einer Vorlage entspricht und alle ihre
    Werte besteht). Damit kann kein fremder Text in die oeffentliche Ausgabe
    gelangen.
    """
    if depth > 2:
        return None
    return _render_template(text, depth=depth + 1)


_RENDERERS = {
    "bytes": _render_bytes,
    "int": _render_int,
    "hex": _render_hex,
    "class": _render_class,
    "zlib": _render_zlib,
}


def _build_templates():
    """Kompiliert die Vorlagen zu Regexen mit benannten Gruppen.

    Ein Platzhalter darf in einer Vorlage mehrfach vorkommen (etwa ``{int}`` in
    drei verschiedenen Zahlen). Jedes Vorkommen bekommt deshalb eine **eigene**
    Regex-Gruppe mit fortlaufendem Index — gleiche Art von Wert, aber jeweils
    eigener Inhalt und eigene Pruefung.

    Der Platzhalter ``{bytes}`` bekommt eine eigene, praezise Gruppe: eine
    Bytes-Schreibweise ``b'...'`` bzw. ``b"..."``. Ein Platzhalter, der am
    Zeilenende steht, wird zusaetzlich per Lookahead verankert, damit er nicht
    den Rest der Nachricht auffrisst.
    """
    compiled = []
    for tpl in SAFE_MESSAGE_TEMPLATES:
        occurrences = re.findall(r"\{([a-z]+)\}", tpl)
        pattern = re.escape(tpl)
        groups = []
        counts: dict[str, int] = {}
        for name in occurrences:
            index = counts.get(name, 0)
            counts[name] = index + 1
            group = "%s_%d" % (name, index)
            if name == "bytes":
                # Bytes-Schreibweise, praezise und nicht gierig.
                body = "(?:b'(?:[^'\\\\]|\\\\.)*'|b\"(?:[^\"\\\\]|\\\\.)*\")"
            else:
                body = ".+?"
            pattern = pattern.replace(re.escape("{%s}" % name),
                                      "(?P<%s>%s)" % (group, body), 1)
            groups.append((group, name))
        compiled.append((re.compile("^" + pattern + "$"), groups, tpl))
    return tuple(compiled)


_COMPILED_TEMPLATES = _build_templates()


def _render_template(message: object, depth: int = 0) -> str | None:
    """Prueft eine eigene Meldung gegen die Vorlagen und rendert sie sicher.

    Die Meldung muss **exakt** einer Vorlage entsprechen, und jeder eingesetzte
    Wert muss zu seiner Typklasse passen. Passt etwas nicht, kommt ``None``
    zurueck — die Ausgabe bleibt dann bei der Fehlerklasse.

    Es wird **alle** Vorlagen durchprobiert und der beste Treffer gewaehlt
    (die Vorlage mit den meisten Platzhaltern). Dadurch gewinnt die spezifische
    Vorlage ``"... {bytes} (expected b'BCPS')"`` gegen die allgemeinere
    ``"... {bytes}"``, ohne dass eine Reihenfolge im Quelltext entscheidet.
    """
    if not isinstance(message, str):
        return None
    best = None
    best_score = -1
    for pattern, groups, tpl in _COMPILED_TEMPLATES:
        match = pattern.match(message)
        if match is None:
            continue
        values = []
        failed = False
        for group, name in groups:
            raw = match.group(group)
            if name == "reason":
                rendered = _render_reason(raw, depth=depth)
            else:
                renderer = _RENDERERS.get(name)
                rendered = renderer(raw) if renderer is not None else None
            if rendered is None:
                failed = True
                break
            values.append((name, rendered))
        if failed:
            continue
        # Das Geruest der Vorlage ist fest und damit pfadfrei. Es wird
        # dennoch geprueft (Verteidigung in der Tiefe) — aber nur gegen
        # **Pfadzeichen**, nicht gegen Dateiendungen: der Gast enthaelt
        # legitim ``b'BCPS'`` und ``.sfs`` als Formatkonstanten.
        if _contains_path_chars(tpl):
            continue
        skeleton = strip_paths(tpl)
        if any(("{%s}" % name) not in skeleton for name, _ in values):
            continue
        out = skeleton
        for name, rendered in values:
            out = out.replace("{%s}" % name, rendered, 1)
        score = len(values)
        if score > best_score:
            best = out
            best_score = score
    return best


def _safe_detail(exc: BaseException) -> str:
    """Oeffentlich zulaessiger Detailtext oder leerer String."""
    try:
        if isinstance(exc, OSError):
            return _os_error_detail(exc)[:PUBLIC_TEXT_MAX]
        message = _message_of(exc)
        rendered = _render_template(message)
        if rendered is None:
            return ""                 # unbekannter Text -> nur die Klasse
        if _looks_pathlike(rendered):
            return ""                 # Rest eines Pfades/Dateinamens -> Klasse
        return rendered[:PUBLIC_TEXT_MAX]
    except Exception:                                         # noqa: BLE001
        return ""


def public_error_detail(exc: BaseException) -> str:
    """Nur der sichere Detailteil, ohne Klassennamen (leer, wenn unsicher)."""
    try:
        return _safe_detail(exc)
    except Exception:                                          # noqa: BLE001
        return ""


def public_error(exc: BaseException) -> str:
    """Oeffentlicher Fehlertext: ``Klasse: sichere Meldung`` (ohne Pfade).

    * ``OSError`` -> Klasse + Text aus der festen ``errno``-Tabelle
      (+ ``errno`` bei generischem OSError); ``strerror``, ``str(exc)``,
      ``filename`` und ``args`` werden nicht ausgewertet
    * eigene Meldungen (Vorlage + gepruefte Bestandteile) -> Klasse + Meldung
    * alles andere -> nur die Klasse; der Originaltext bleibt
      :func:`diagnostic_error` vorbehalten
    """
    name = _class_name(exc)
    detail = public_error_detail(exc)
    return "%s: %s" % (name, detail) if detail else name


def diagnostic_error(exc: BaseException) -> str:
    """Voller Fehlertext — NUR fuer interne Auswertung, Logs, Tests.

    Nicht fuer oeffentliche Ausgaben geeignet: kann Dateipfade enthalten.
    """
    return "%s: %s" % (_class_name(exc), _message_of(exc))


# ===========================================================================
# OEFFENTLICHE MELDUNGSREGISTRY (R1_6)
# ===========================================================================
#
# ZWECK
#     Eine geschlossene Menge von Meldungscodes fuer **oeffentliche
#     Diagnosetexte**. Der Exception-Formatter (oben) schuetzt die Darstellung
#     von *Fehlern*. Diese Registry schuetzt die Darstellung von *Befunden* —
#     CheckResult.detail, evidence-Texte, GUI- und CLI-Ausgaben.
#
#     Beide Grenzen sind getrennt, benutzen aber dieselbe Typidee:
#     ein Wert darf nur in eine oeffentliche Ausgabe gelangen, wenn sein
#     Wertebereich **geschlossen** ist.
#
# TYPISCHE PLAZHALTER
#     INT          vorzeichenlose ganze Zahl (bool nicht erlaubt)
#     HEX          Hexadezimalzahl ohne ``0x``
#     BYTES_MAGIC  Bytefolge -> **statische Beschreibung** aus
#                  :data:`BYTES_DESCRIPTIONS` (Praefix-Match) oder
#                  :data:`BYTES_UNKNOWN`. Die Bytes selbst gelangen NIE
#                  in die Ausgabe.
#     COUNT        nichtnegative ganze Zahl (fuer Anzahlen)
#     OFFSET       Hex-Offset (``0x…``)
#     ENUM         Wert aus einer geschlossenen, hier benannten Menge
#     TEXT_FIXED   fester Text aus :data:`PUBLIC_FIXED_TEXTS`
#
# FAIL-CLOSED
#     * unbekannter Code            -> :data:`PUBLIC_GENERIC_DETAIL`
#     * falscher Platzhaltertyp     -> :data:`PUBLIC_GENERIC_DETAIL`
#     * Renderer wirft               -> :data:`PUBLIC_GENERIC_DETAIL`
#     * unerwarteter Werttyp        -> :data:`PUBLIC_GENERIC_DETAIL`
#
#     Es gibt **keinen** automatischen ``str()``/``repr()``-Fallback und
#     keinen Pfad, auf dem ein Rohwert die Ausgabe erreicht.
#
# INTERNE DIAGNOSE
#     :func:`diagnostic_error` bleibt der einzige Ort fuer Rohdaten. Die
#     Registry hat keine oeffentliche Entsprechung.
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class PlaceholderKind(Enum):
    """Typklasse eines Platzhalters — der erlaubte Wertebereich."""
    INT = "int"
    HEX = "hex"
    BYTES_MAGIC = "bytes_magic"
    COUNT = "count"
    OFFSET = "offset"
    ENUM = "enum"
    TEXT_FIXED = "text_fixed"
    #: Bereits durch public_error() bereinigter Fehlertext.
    #:
    #: Der Wert muss aus :func:`public_error` stammen — dort sind Pfade
    #: und Rohtexte entfernt. Der Guard kann die Herkunft nicht selbst
    #: verfolgen; die Belegbarkeit liegt beim Aufrufer.
    ERROR_TEXT = "error_text"
    #: Titel einer Pruefung (aus dem Docstring der Prueffunktion).
    #:
    #: Es ist ein eigener, statischer Text ohne Identitaetsbezug. Der
    #: Renderer begrenzt ihn auf eine feste Laenge und auf zulaessige
    #: Zeichen (Buchstaben, Ziffern, Leerzeichen, Bindestriche).
    CHECK_TITLE = "check_title"
    #: Eigener statischer Diagnosetext ueber Header-Feldgrenzen.
    #:
    #: Erlaubt sind ausschliesslich ein Header-Feldname aus der
    #: geschlossenen Menge und eine Hex-Angabe. Der Renderer prueft das
    #: — ein beliebiger Text wird verworfen.
    HEADER_ERROR = "header_error"


#: Statischer Ersatztext, wenn eine Meldung nicht sicher gerendert werden kann.
PUBLIC_GENERIC_DETAIL = "Diagnose nicht verfügbar"

#: Feste, eigene Texte fuer Aufzaehlungen (geschlossene Menge).
#:
#: R1_6: ``check_id`` traegt die Check-IDs der geschlossenen CHECKS-Menge
#: bei. Sie sind statisch und werden im Repository-Diff nachpruefbar.
PUBLIC_FIXED_TEXTS = {
    "none": "keine",
    "unknown": "unbekannt",
    "yes": "ja",
    "no": "nein",
    "I-01": "I-01",
    "I-02": "I-02",
    "I-03": "I-03",
    "I-04": "I-04",
    "I-05": "I-05",
    "I-06": "I-06",
    "I-07": "I-07",
    "I-08": "I-08",
    "I-09": "I-09",
    "I-10": "I-10",
    "I-11": "I-11",
    "I-12": "I-12",
    "I-13": "I-13",
    "I-14": "I-14",
}


@dataclass(frozen=True)
class PublicMessage:
    """Eine oeffentliche Meldung: Code, Vorlage, Platzhaltertypen."""
    code: str
    template: str
    placeholders: Mapping[str, PlaceholderKind] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.placeholders is None:
            object.__setattr__(self, "placeholders", {})


def _public_int(value: Any) -> int | None:
    """Ganzzahl (bool ausgeschlossen) — oder ``None``.

    R1_6 (Fehlerkorrektur): frueher wurde hier bereits ``str(value)``
    zurueckgegeben. ``_public_hex`` verglich das Ergebnis danach mit
    ``0`` und warf ``TypeError``. Der Renderer gibt jetzt den **int**
    zurueck; die Textform entsteht erst beim Rendern.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _public_count(value: Any) -> str | None:
    """Nichtnegative Ganzzahl — oder ``None``."""
    number = _public_int(value)
    if number is None or number < 0:
        return None
    return str(number)


def _public_hex(value: Any) -> str | None:
    """Hexadezimalzahl ohne ``0x`` — oder ``None``."""
    number = _public_int(value)
    if number is None or number < 0:
        return None
    return format(number, "X")


def _public_offset(value: Any) -> str | None:
    """Hex-Offset mit ``0x`` — oder ``None``."""
    number = _public_hex(value)
    if number is None:
        return None
    return "0x" + number


def _public_bytes_magic(value: Any) -> str | None:
    """Bytefolge -> **statische Beschreibung** (nie die Bytes selbst).

    Nutzt dieselbe Praefix-Tabelle wie der Exception-Formatter. Die
    Bytefolge selbst, und damit jeder Dateiname, Pfad oder Byte-Rest,
    gelangt **nie** in eine oeffentliche Ausgabe.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    elif isinstance(value, str):
        # Nur die Schreibweise ``b'…'`` ist zulaessig — sie ist eine
        # kontrollierte Darstellung, keine freie Zeichenkette.
        stripped = value.strip()
        if not (stripped.startswith("b'") or stripped.startswith('b"')):
            return None
        try:
            parsed = ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            return None
        if not isinstance(parsed, bytes):
            return None
        raw = parsed
    else:
        return None
    if len(raw) > SAFE_BYTES_MAX:
        return BYTES_UNKNOWN
    if any(byte in _PATH_BYTES for byte in raw):
        return BYTES_UNKNOWN
    if _looks_like_filename(raw):
        return BYTES_UNKNOWN
    best = None
    best_len = -1
    for magic, description in BYTES_DESCRIPTIONS.items():
        if raw.startswith(magic) and len(magic) > best_len:
            best = description
            best_len = len(magic)
    return best if best is not None else BYTES_UNKNOWN


def _public_enum(value: Any) -> str | None:
    """Wert aus einer geschlossenen Menge — oder ``None``."""
    if not isinstance(value, str):
        return None
    return value if value in PUBLIC_FIXED_TEXTS else None


def _public_text_fixed(value: Any) -> str | None:
    """Fester Text aus :data:`PUBLIC_FIXED_TEXTS` — oder ``None``."""
    return _public_enum(value)


def _public_error_text(value: Any) -> str | None:
    """Bereinigter Fehlertext — oder ``None``, wenn er nicht belegt ist.

    Der Wert muss aus :func:`public_error` stammen. Zusaetzlich wird
    geprueft, dass er **keinen** Pfad und **keinen** Dateinamen traegt:
    das ist die zweite, unabhaengige Sicherung. Ein Text, der einem
    Pfad oder einer Dateiendung nachsieht, wird verworfen.
    """
    if not isinstance(value, str) or not value:
        return None
    if len(value) > PUBLIC_TEXT_MAX:
        return None
    # Pfad- oder Dateinamenmuster -> nicht belegt.
    if "/" in value or "\\" in value:
        return None
    lowered = value.lower()
    if any(lowered.endswith(token)
           for token in (".sfs", ".esm", ".esp", ".esl", ".ba2", ".dll",
                         ".exe", ".txt", ".json", ".log", ".dat")):
        return None
    return value


#: Header-Feldnamen, die in einem Headergrenzen-Text genannt werden
#: duerfen. Es sind **Schema-Begriffe**, keine Werte — der Spielername
#: selbst wird nie ausgegeben.
PUBLIC_HEADER_FIELDS = (
    "playerName", "playerLevel", "playerLocation", "playtime", "raceName",
    "gender", "experience", "experienceRequired", "saveNumber",
    "currentGameVersion", "createdGameVersion", "pluginInfoOffset",
    "pluginInfoSize", "headerSize", "engineVersion", "saveVersion",
    "filetime", "unknown",
)


def _public_header_error(value: Any) -> str | None:
    """Eigener statischer Text ueber eine Header-Feldgrenze.

    Zulaessig sind nur:
      * ein Feldname aus :data:`PUBLIC_HEADER_FIELDS`,
      * optional eine Hex-Angabe (``0x...``),
      * ein kurzer statischer Zusatz.

    Alles andere wird verworfen — der Platzhalter ist damit auf
    bekannte Muster begrenzt und kann keinen fremden Text transportieren.
    """
    if not isinstance(value, str) or not value or len(value) > PUBLIC_TEXT_MAX:
        return None
    if "/" in value or "\\" in value:
        return None
    lowered = value.lower()
    if any(lowered.endswith(token)
           for token in (".sfs", ".esm", ".esp", ".esl", ".ba2", ".dll",
                         ".exe", ".txt", ".json", ".log", ".dat")):
        return None
    # Erlaubte Bausteine: Feldname, Hexzahl, statische Woerter.
    rest = value
    for field in PUBLIC_HEADER_FIELDS:
        rest = rest.replace(field, " ")
    rest = rest.replace("0x", " ")
    for token in ("Laengenfeld", "hinter", "dem", "Puffer", "unplausible",
                  "Laenge", "bei", "Inhalt", "Feld", "unbekannt",
                  "Laengen", "Wert", "ausserhalb", "des", "Bereichs"):
        rest = rest.replace(token, " ")
    rest = rest.replace("(", " ").replace(")", " ").replace(":", " ")
    rest = rest.replace(",", " ").replace(".", " ")
    # R1_6: Hex-Ziffern sind zulaessig (0-9, a-f, A-F, x).
    for ch in rest:
        if not (ch.isspace() or ch.isdigit() or ch in "xXabcdefABCDEF"):
            return None
    return value


def _public_check_title(value: Any) -> str | None:
    """Eigener, statischer Titel einer Pruefung — oder ``None``.

    Zulaessig sind Buchstaben, Ziffern, Leerzeichen, Bindestriche,
    Doppelpunkte und Klammern. Alles andere wird verworfen. Insbesondere
    sind Pfadzeichen (``/``, ``\\``) und Dateiendungen ausgeschlossen.
    """
    if not isinstance(value, str) or not value or len(value) > 120:
        return None
    if "/" in value or "\\" in value:
        return None
    lowered = value.lower()
    if any(lowered.endswith(token)
           for token in (".sfs", ".esm", ".esp", ".esl", ".ba2", ".dll",
                         ".exe", ".txt", ".json", ".log", ".dat")):
        return None
    for ch in value:
        if not (ch.isalnum() or ch in " -:()[].,"):
            return None
    return value


_PUBLIC_RENDERERS = {
    PlaceholderKind.INT: _public_int,
    PlaceholderKind.COUNT: _public_count,
    PlaceholderKind.HEX: _public_hex,
    PlaceholderKind.OFFSET: _public_offset,
    PlaceholderKind.BYTES_MAGIC: _public_bytes_magic,
    PlaceholderKind.ENUM: _public_enum,
    PlaceholderKind.TEXT_FIXED: _public_text_fixed,
    PlaceholderKind.ERROR_TEXT: _public_error_text,
    PlaceholderKind.HEADER_ERROR: _public_header_error,
    PlaceholderKind.CHECK_TITLE: _public_check_title,
}


# ---------------------------------------------------------------------------
# Die Registry — geschlossen. Jeder Code ist exakt einmal definiert.
# ---------------------------------------------------------------------------
MESSAGE_REGISTRY: Mapping[str, PublicMessage] = {
    # --- I-01 BCPS-Magic
    "I-01.MAGIC_MISMATCH": PublicMessage(
        "I-01.MAGIC_MISMATCH",
        "Container beginnt nicht mit dem erwarteten Kennzeichen, "
        "sondern mit {magic}",
        {"magic": PlaceholderKind.BYTES_MAGIC},
    ),
    # --- I-02 Kompressionstyp
    "I-02.COMPRESSION_UNSUPPORTED": PublicMessage(
        "I-02.COMPRESSION_UNSUPPORTED",
        "Kompressionstyp {magic} wird nicht unterstützt",
        {"magic": PlaceholderKind.BYTES_MAGIC},
    ),
    # --- I-08 DAT-Magic
    "I-08.DAT_MAGIC_MISMATCH": PublicMessage(
        "I-08.DAT_MAGIC_MISMATCH",
        "DAT-Kennung ist {magic}, erwartet b'SFS_SAVEGAME'",
        {"magic": PlaceholderKind.BYTES_MAGIC},
    ),
    # --- I-12 Data-Verzeichnis
    "I-12.DATA_DIR_MISSING": PublicMessage(
        "I-12.DATA_DIR_MISSING",
        "Data-Verzeichnis nicht vorhanden oder nicht lesbar",
    ),
    # --- I-14 Sequenz
    "I-14.MULTIPLE_CHARACTERS": PublicMessage(
        "I-14.MULTIPLE_CHARACTERS",
        "mehrere Charaktere im Savebestand ({count}), "
        "kein Bezugssave bestimmt",
        {"count": PlaceholderKind.COUNT},
    ),
    "I-14.SINGLE_CHARACTER": PublicMessage(
        "I-14.SINGLE_CHARACTER",
        "nur ein Save eines Charakters im Savebestand ({count})",
        {"count": PlaceholderKind.COUNT},
    ),
    "I-14.SAVES_MONOTONIC": PublicMessage(
        "I-14.SAVES_MONOTONIC",
        "{count} Saves monoton in Level, Spielzeit und Zeit",
        {"count": PlaceholderKind.COUNT},
    ),
    # --- I-05 zlib-Fehler
    "I-05.DECOMPRESSION_FAILED": PublicMessage(
        "I-05.DECOMPRESSION_FAILED",
        "zlib-Fehler in Chunk {index} bei 0x{offset}: {reason}",
        {"index": PlaceholderKind.COUNT,
         "offset": PlaceholderKind.HEX,
         "reason": PlaceholderKind.ERROR_TEXT},
    ),
    # --- Check-Titel (aus dem Docstring der Prueffunktion)
    "GENERIC.CHECK_TITLE": PublicMessage(
        "GENERIC.CHECK_TITLE",
        "{title}",
        {"title": PlaceholderKind.CHECK_TITLE},
    ),
    # --- I-08 Header-Feldgrenze
    "I-08.HEADER_FIELD_ERROR": PublicMessage(
        "I-08.HEADER_FIELD_ERROR",
        "{error}",
        {"error": PlaceholderKind.HEADER_ERROR},
    ),
    # --- I-11 Plugin-Ketten
    "I-11.CHAINS_UNREADABLE": PublicMessage(
        "I-11.CHAINS_UNREADABLE",
        "Ketten nicht vollstaendig lesbar: {note}",
        {"note": PlaceholderKind.ERROR_TEXT},
    ),
    # --- Allgemein
    "GENERIC.PREREQUISITE_MISSING": PublicMessage(
        "GENERIC.PREREQUISITE_MISSING",
        "Voraussetzung fehlt: {blocked} ist FAILED",
        {"blocked": PlaceholderKind.TEXT_FIXED},
    ),

    "GENERIC.UNAVAILABLE": PublicMessage(
        "GENERIC.UNAVAILABLE", PUBLIC_GENERIC_DETAIL),
}


def render_public_message(code: str, **params: Any) -> str:
    """Rendert eine oeffentliche Meldung aus der Registry — fail-closed.

    Verhalten:

    * unbekannter Code            -> :data:`PUBLIC_GENERIC_DETAIL`
    * falscher Codentyp           -> :data:`PUBLIC_GENERIC_DETAIL`
    * unbekannter Platzhalter     -> :data:`PUBLIC_GENERIC_DETAIL`
    * falscher Platzhaltertyp     -> :data:`PUBLIC_GENERIC_DETAIL`
    * Renderer wirft               -> :data:`PUBLIC_GENERIC_DETAIL`
    * fehlender Platzhalter        -> :data:`PUBLIC_GENERIC_DETAIL`

    Es gibt **keinen** ``str()``/``repr()``-Fallback: ein Wert, der nicht
    in seinen Typbereich passt, wird verworfen, nicht in Text verwandelt.
    """
    try:
        if not isinstance(code, str):
            return PUBLIC_GENERIC_DETAIL
        message = MESSAGE_REGISTRY.get(code)
        if message is None:
            return PUBLIC_GENERIC_DETAIL
        template = message.template
        values: dict[str, str] = {}
        for name, kind in message.placeholders.items():
            if name not in params:
                return PUBLIC_GENERIC_DETAIL
            renderer = _PUBLIC_RENDERERS.get(kind)
            if renderer is None:
                return PUBLIC_GENERIC_DETAIL
            rendered = renderer(params[name])
            if rendered is None:
                return PUBLIC_GENERIC_DETAIL
            values[name] = rendered
        # Unerwartete zusaetzliche Parameter sind erlaubt (z. B. interne
        # Werte, die der Aufrufer mitgibt) — sie werden NICHT gerendert.
        for name, rendered in values.items():
            template = template.replace("{%s}" % name, rendered, 1)
        if "{" in template and "}" in template:
            # Ein nicht ersetzter Platzhalter ist ein Registry-Fehler.
            return PUBLIC_GENERIC_DETAIL
        return template[:PUBLIC_TEXT_MAX]
    except Exception:                                         # noqa: BLE001
        # Ein Rendererfehler darf NIE zu ungefilterter Ausgabe fuehren.
        return PUBLIC_GENERIC_DETAIL
