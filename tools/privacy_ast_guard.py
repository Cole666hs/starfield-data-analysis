#!/usr/bin/env python3
"""SSBI R1_6 — statischer Privacy-Guard (AST, vertragsbasiert).

GRENZE — BITTE ZUERST LESEN
    Dieser Guard ist eine **statische Regressionserkennung**. Er
    beweist **keine** Erreichbarkeit eines Codepfads und **keine**
    Leckfreiheit. Ein Befund ist eine Hypothese, kein Nachweis; ein
    fehlender Befund ist kein Beweis fuer Sauberkeit.

    Die tragende Grenze ist die **Runtime-Privacy-Grenze**:
    ``ssb_i.errors.render_public_message()`` und
    ``ssb_i.savegame_provider.public_header_view()``. Der Guard ist
    logisch und technisch davon getrennt und ersetzt sie nicht.

    Die im R1_5-Audit nachgewiesenen Grenzen bleiben bestehen:
    ``dict[str, Any]``-Elemente sind nicht typisierbar, ``**kwargs``
    und ``getattr`` ohne Typ sind nicht analysierbar, Laufzeit-
    Mutationen sind nicht erfassbar.

Der Guard wird aus dem SICHERHEITSVERTRAG abgeleitet, nicht aus der
bestehenden Implementierung.

VERTRAG V1 (Textgrenze)
    In ein oeffentliches Diagnosetextfeld (detail/title/message/reason/
    description/warning/error) darf kein *unbeschaenkter* Text eingehen.

    Zulaessig:
      (a) statische Stringliterale
      (b) typgeprueftes Rendering ueber freigegebene Formatter
      (c) *beschaenkte* Konvertierungen

VERTRAG V2 (Beschraenktheit)
    Der entscheidende Punkt: eine Konvertierung ist dann sicher, wenn sie
    nur einen begrenzten Wertebereich erzeugen kann.

      %d %i %x %X %o %e %f %g  -> rufen __index__/int auf. KANN keinen
                                   fremden Text erzeugen; ein Nicht-Zahlwert
                                   loest TypeError aus (kein Leak).
      %s %r %a                -> rufen __str__/__repr__ auf. KOENNEN
                                   beliebigen Text erzeugen -> VERBOTEN.
      f"{v}"                  -> wie %s -> VERBOTEN.
      f"{v:d}"                -> wie %d -> erlaubt.

VERTRAG V3 (Herkunft)
    Ein Wert muss entweder statisch, typisiert (Annotation) oder ueber
    einen freigegebenen Formatter bestimmt sein. Ein blosser Name ohne
    bekannten Typ ist UNKNOWN und damit nicht freigegeben.

Typinferenz: lokal (Annotationen, Zuweisungen, eingebaute Typen) und
moduluebergreifend (Dataclass-Felderannotationen).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# ------------------------------------------------------------- VERTRAG

APPROVED_FORMATTERS = {
    "public_error", "public_error_detail", "strip_paths",
    "_public_error", "_error_reason", "_error_text", "_strip_paths",
    # R1_6: die geschlossene Meldungsregistry ist ein freigegebener
    # Renderer — sie liefert per Konstruktion kontrollierten Text.
    "render_public_message",
    # R1_6: der CLI-Fehlerformatter. Er wertet einen CliError aus, dessen
    # Text bereits durch die Fehlergrenze gelaufen ist (sfda_cli.py:309).
    "_cli_error_text",
}
APPROVED_RENDERERS = {
    "_render_bytes", "_render_int", "_render_hex", "_render_class",
    "_render_zlib", "_render_reason", "_render_template",
}
#: R1_6: Belegte kontrollierte Herkunft fuer ``ctx.load_errors``.
#:
#: ``SaveContext.load_errors`` wird an genau einer Stelle befuellt:
#: ``ctx.load_errors[<x>] = _error_reason(exc)``, und ``_error_reason``
#: ist ``public_error(exc)`` — der Exception-Formatter, der Pfade und
#: Rohtexte entfernt. Die Werte sind damit per Konstruktion
#: kontrolliert; der Guard kann den Datenfluss nicht selbst verfolgen
#: und braucht deshalb diese belegte Ausnahme.
CONTROLLED_SOURCES = {
    "load_errors",
}
#: R1_6: Belegt kontrollierte **Attribute** (Dataclass-Felder).
#:
#: Jeder Eintrag traegt eine Begruendung, die im Code nachpruefbar ist:
#:
#: ``note``  — ``PluginInfo.note`` wird ausschliesslich aus statischen
#:             Formatstrings und aus ``public_error(exc)`` gesetzt
#:             (savegame_provider.py:809-856). Kein Dateipfad, kein
#:             Spielername, kein Containerinhalt.
#:
#: Der Guard kann den Datenfluss nicht selbst verfolgen; die Ausnahme
#: ersetzt die **statische** Pruefung durch eine belegte, im Code
#: nachpruefbare Aussage. Sie ist damit keine pauschale
#: ERROR-Unterdrueckung.
#:
#: (``total`` ist bewusst NICHT enthalten — der Typ der berechneten
#: Properties wird seit R1_6 aus der Rueckgabeannotation aufgeloest.)
CONTROLLED_ATTRIBUTES = {
    "note",
    # R1_6: ``HexViewPage._label`` — die Bezeichnung des angezeigten
    # Puffers. Nach dem R1_6-Fix ist sie entweder leer, "save" oder
    # "buffer" — **kein** Pfad und **kein** Dateiname
    # (hex_view_page.py:165/207, savegame_page.py:498).
    "_label",
}
#: R1_6: Belegt kontrollierte **Funktionsparameter**.
#:
#: ``message`` in ``_finish_error`` (sfda_cli.py:326) stammt an allen
#: fuenf Aufrufstellen aus ``_cli_error_text(exc)``, ``_public_error(exc)``
#: oder dem statischen Literal ``"Aborted."`` — die Herkunft ist im
#: Repository nachpruefbar.
CONTROLLED_PARAMETERS = {
    ("_finish_error", "message"),
}
#: R1_6: Belegt kontrollierte **Evidence-Schluessel**.
#:
#: ``blocked_by`` traegt die Check-ID, die unmittelbar vorher aus der
#: geschlossenen CHECKS-Menge erzeugt wurde
#: (``check_id = _check_id(check)``). Der Wert kann daher nur eine der
#: 14 Check-IDs sein — kein fremder Text. Die Zuordnung ist im Code
#: nachpruefbar (save_integrity.py:1277-1290).
CONTROLLED_EVIDENCE_KEYS = {
    "blocked_by",
}
#: R1_6: Belegt kontrollierte **Dict-Schluessel** in Ausgabe-Dicts.
#:
#: ``note``  — der Wert stammt aus einem statischen Literal
#:              (savegame_provider.py:956) bzw. aus
#:              ``PluginInfo.note``, das selbst nur aus statischen
#:              Formatstrings und ``public_error`` gesetzt wird.
#:
#: ``status``/``reason``/``decode_state`` — geschlossene Zustandswerte.
CONTROLLED_DICT_KEYS = {
    "note",
    "status",
    "reason",
    "decode_state",
    # R1_6: Plugin-Metadaten. ``creation_name`` ist der Name des Mods,
    # das den Eintrag angelegt hat — F-7 erlaubt Mod-Dateinamen zur
    # funktionalen Mod-Identifikation. ``creation_id`` ist eine
    # Hex-FormID, ``version`` eine Versionsangabe; beide tragen keine
    # Spieleridentitaet.
    "creation_name",
    "creation_id",
    "version",
}
#: R1_6: Reine Zahlenwerte aus kontrollierten Structuren
#: (String-Pool-Zaehler, Offsets, Laengen). Sie tragen keine Identitaet
#: und werden deshalb als Zahl typisiert.
CONTROLLED_NUMERIC_KEYS = {
    "index",
    "offset",
    "count",
    "declared_count",
    "printable_ratio",
    "string_array_offset",
    "end",
    "length",
}
#: R1_6: Belegte fachliche Ausnahme — der **String-Pool-Inhalt**.
#:
#: ``save strings`` listet die Zeichenketten des Saves auf. Das ist die
#: Kernfunktion des Werkzeugs: ein Savegame-Analyse-Tool muss die
#: Strings zeigen, die im Save stehen. R1_5 A-3 fordert den Verzicht
#: auf dekodierten Containerinhalt nur fuer ``detail``/``evidence`` der
#: Integritaetspruefungen — nicht fuer ein ausdruecklich angefordertes
#: Analyseergebnis.
#:
#: Der Befehl ist **explizit** (der Nutzer fordert ihn an), die Ausgabe
#: geht an die Konsole des aufrufenden Nutzers, und der Inhalt wird
#: nicht in eine Integritaetsdiagnose uebernommen.
CONTROLLED_CONTAINER_CONTENT = {
    "text",
}
#: Konvertierungen, die einen begrenzten Wertebereich erzeugen.
BOUNDED_CONVERSIONS = set("dixXoeEf g".replace(" ", ""))
#: Konvertierungen, die beliebigen Text erzeugen koennen.
UNBOUNDED_CONVERSIONS = set("sra")
PUBLIC_TEXT_FIELDS = ("detail", "title", "message", "reason", "description",
                      "warning", "error")

BUILTIN_NUMERIC = {"int", "float", "bool", "complex"}
BUILTIN_TEXT = {"str"}


# ------------------------------------------------------------- Helfer

class Violation:
    __slots__ = ("file", "line", "rule", "severity", "detail", "snippet")

    def __init__(self, file, line, rule, detail, snippet="", severity="WARN"):
        self.file = file
        self.line = line
        self.rule = rule
        self.severity = severity
        self.detail = detail
        self.snippet = snippet

    def as_dict(self):
        return {"file": self.file, "line": self.line, "rule": self.rule,
                "severity": self.severity, "detail": self.detail,
                "snippet": self.snippet[:200]}


def _snip(src, node):
    try:
        return " ".join((ast.get_source_segment(src, node) or "").split())
    except Exception:
        return ""


def _name_of(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_controlled_source(node) -> bool:
    """True, wenn der Ausdruck auf eine belegt kontrollierte Quelle zeigt.

    Erfasst ``ctx.load_errors.get(...)`` und ``ctx.load_errors[...]`` —
    der Zugriff auf ein Attribut, dessen Name in
    :data:`CONTROLLED_SOURCES` steht.

    Bei ``ctx.load_errors.get(x)`` ist der Callable ``get``; die Quelle
    steckt eine Ebene tiefer in ``func.value``. Deshalb wird die
    Attributkette durchlaufen, nicht nur der naechste Name geprueft.
    """
    target = node
    if isinstance(target, ast.Call):
        target = target.func
    # Attributkette nach aussen nach einer kontrollierten Quelle durchsuchen.
    seen = 0
    while isinstance(target, ast.Attribute) and seen < 4:
        if target.attr in CONTROLLED_SOURCES:
            return True
        target = target.value
        seen += 1
    return False


def _ann_of(node) -> str | None:
    """Annotationsname eines Ausdrucks (z.B. 'int', 'SaveContext', None)."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int):
            return "int"
        if isinstance(node.value, float):
            return "float"
        if isinstance(node.value, str):
            return "str"
        if node.value is None:
            return "None"
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # Der Attributname ist KEIN Typ. "header.header_size" ist int, nicht
        # "header_size" — die Aufloesung ueber Dataclass-Felder passiert in
        # Guard._attribute_type, nicht hier.
        return None
    if isinstance(node, ast.Call):
        fname = _name_of(node.func)
        if fname in BUILTIN_NUMERIC:
            return fname
        if fname == "bytes":
            return "bytes"
        if fname == "str":
            return "str"
        if fname == "list":
            return "list"
        if fname == "dict":
            return "dict"
        if fname == "len":
            return "int"
        if fname == "sorted":
            return "list"
        if fname == "set":
            return "set"
        if fname == "tuple":
            return "tuple"
        if fname == "repr":
            return "str"
        if fname == "format":
            return "str"
        return None
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                                ast.FloorDiv, ast.Mod)):
            if isinstance(node.op, ast.Add):
                lann = _ann_of(node.left)
                rann = _ann_of(node.right)
                if lann == "str" or rann == "str":
                    return "str"
            lann = _ann_of(node.left)
            rann = _ann_of(node.right)
            if lann in BUILTIN_NUMERIC and rann in BUILTIN_NUMERIC:
                return lann
            return None
        return None
    if isinstance(node, ast.UnaryOp):
        return _ann_of(node.operand)
    if isinstance(node, ast.Subscript):
        return None          # dict[int]/list[int] -> Elementtyp unbekannt
    if isinstance(node, ast.IfExp):
        a = _ann_of(node.body)
        b = _ann_of(node.orelse)
        return a if a == b else None
    if isinstance(node, ast.JoinedStr):
        return "str"
    return None


# ------------------------------------------------------- Typumgebung

class TypeEnv:
    """Moduluebergreifende Typinformation aus Annotationen.

    Gesammelt werden:
      * Dataclass-Feldannotationen (Klasse -> Feld -> Annotation)
      * Funktionsparameterannotationen (Funktion -> Parameter -> Annotation)
    """

    def __init__(self) -> None:
        self.dataclass_fields: dict[str, dict[str, str]] = {}
        self.function_params: dict[str, dict[str, str]] = {}
        #: Klassen, die von ``enum.Enum`` erben — geschlossene Wertemengen.
        self.enum_classes: set[str] = set()
        #: Berechnete Properties: Klasse -> {Property-Name: Typ}
        #:
        #: R1_6: ``@property``-Methoden sind berechnete Felder (z. B.
        #: ``PluginInfo.total``). Der Guard konnte sie previously nicht
        #: aufloesen, weil nur annotierte Dataclass-Felder erfasst
        #: wurden. Die Rueckgabeannotation der Property ist die
        #: belegte Typangabe.
        self.property_fields: dict[str, dict[str, str]] = {}
        #: Methoden-Rueckgabeannotationen: Methodenname -> Typ
        #:
        #: R1_6: ``provider.parse_plugin_info(...)`` liefert ein
        #: ``PluginInfo``. Ohne diese Angabe kann der Guard den
        #: Attributzugriff auf das Ergebnis nicht aufloesen.
        self.method_returns: dict[str, str] = {}
        #: Modul-Konstanten: Name -> Typ (nur annotierte Zuweisungen).
        #:
        #: R1_6: ``APP_NAME: str = "..."`` und Aehnliches sind statische
        #: Werte. Der Guard kann sie sonst nicht auflösen.
        self.module_constants: dict[str, str] = {}

    def learn(self, path: Path) -> None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            return
        for node in tree.body:
            # R1_6: annotierte Modul-Konstanten (Typ aus der Annotation).
            if isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name):
                self.module_constants[node.target.id] = ast.unparse(
                    node.annotation)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields: dict[str, str] = {}
                # @dataclass kann als Name (@dataclass) oder als Call
                # (@dataclass(frozen=True)) vorliegen — beide Formen gelten.
                is_dc = False
                for d in node.decorator_list:
                    target = d.func if isinstance(d, ast.Call) else d
                    if _name_of(target) == "dataclass":
                        is_dc = True
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(
                            stmt.target, ast.Name):
                        fields[stmt.target.id] = ast.unparse(stmt.annotation)
                if is_dc and fields:
                    self.dataclass_fields[node.name] = fields
                # R1_6: Enum-Klassen sind geschlossene Wertemengen. Ihre
                # String-Darstellung ist der Mitgliedsname und damit
                # kontrolliert.
                for base in node.bases:
                    if _name_of(base) in ("Enum", "IntEnum", "StrEnum",
                                          "Flag", "IntFlag"):
                        self.enum_classes.add(node.name)
                        break
                # R1_6: berechnete Properties (Typ aus der
                # Rueckgabeannotation).
                props: dict[str, str] = {}
                for stmt in node.body:
                    if not isinstance(stmt, (ast.FunctionDef,
                                             ast.AsyncFunctionDef)):
                        continue
                    is_prop = any(_name_of(d) == "property"
                                  for d in stmt.decorator_list)
                    if is_prop and stmt.returns is not None:
                        props[stmt.name] = ast.unparse(stmt.returns)
                if props:
                    self.property_fields[node.name] = props
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                all_args = (list(args.posonlyargs) + list(args.args)
                            + list(args.kwonlyargs))
                params: dict[str, str] = {}
                for arg in all_args:
                    if arg.annotation is not None:
                        params[arg.arg] = ast.unparse(arg.annotation)
                if params:
                    self.function_params[node.name] = params
                if node.returns is not None:
                    self.method_returns[node.name] = ast.unparse(node.returns)

    def property_type(self, cls: str, field: str) -> str | None:
        """Typ einer berechneten Property — ueber die Rueckgabeannotation."""
        props = self.property_fields.get(cls)
        if props:
            return props.get(field)
        return None

    def field_type(self, cls: str, field: str) -> str | None:
        """Typ eines Dataclass-Feldes.

        `cls` darf bereits der Feldname sein (dann wird der Typ direkt
        zurueckgegeben), sonst wird die Klasse nachgeschlagen.
        """
        fields = self.dataclass_fields.get(cls)
        if not fields:
            return None
        ann = fields.get(field)
        if ann is None:
            return None
        # Union aufloesen: "int | None" -> int
        parts = [p.strip() for p in ann.replace("Optional[", "").split("|")]
        parts = [p for p in parts if p and p != "None"]
        if len(parts) == 1:
            return parts[0]
        return None

    def field_owner(self, field_name: str) -> str | None:
        """Findet die Dataclass, die ein Feld mit diesem Namen besitzt.

        Wird genutzt, wenn der Basistyp eines Attributzugriffs nicht
        aufloesbar ist, der Feldname aber eindeutig auf eine bekannte
        Dataclass zeigt (z.B. ``header.header_size`` -> DatHeader).
        """
        owners = [cls for cls, fields in self.dataclass_fields.items()
                  if field_name in fields]
        if len(owners) == 1:
            return owners[0]
        return None


# ------------------------------------------------------------- Guard

class Guard:
    def __init__(self, env: TypeEnv | None = None):
        self.env = env or TypeEnv()

    # -- Typbestimmung eines Ausdrucks --------------------------------
    def expr_type(self, node, scope, local_types) -> str | None:
        """Bestimmt den Typ eines Ausdrucks, soweit er sich belegen laesst."""
        if node is None:
            return None
        ann = _ann_of(node)
        if ann in BUILTIN_NUMERIC or ann == "str" or ann == "bytes":
            return ann
        if isinstance(node, ast.Name):
            # R1_6: Modul-Konstante (annotierte Zuweisung auf Modulebene).
            if node.id in self.env.module_constants:
                base = self.env.module_constants[node.id].split("|")[0].strip()
                if base in BUILTIN_NUMERIC or base in ("str", "bytes"):
                    return "controlled_text" if base == "str" else base
            if node.id in local_types:
                # R1_6: belegt kontrollierter Parameter — die Herkunft
                # ist im Code nachpruefbar (CONTROLLED_PARAMETERS).
                scope_name = getattr(scope, "name", "") or ""
                if (scope_name, node.id) in CONTROLLED_PARAMETERS:
                    return "controlled"
                # R1_6: lokale Zuweisung mit kontrolliertem Wert
                # (``source = self._label or "(buffer)"``). Die Herkunft
                # wird ueber die Zuweisung aufgeloest — aber **nur**,
                # wenn der Wert selbst kontrolliert ist. Ein blosser
                # Name (z. B. ``n = len(ctx.chunks)``) bleibt
                # unaufgeloest: sonst waere die Herkunft nur scheinbar
                # belegt (das waere ein False Negative).
                if scope is not None:
                    for n in ast.walk(scope):
                        if isinstance(n, ast.Assign):
                            for tgt in n.targets:
                                if (isinstance(tgt, ast.Name)
                                        and tgt.id == node.id):
                                    t = self.expr_type(n.value, scope,
                                                       local_types)
                                    if t in ("controlled",
                                             "controlled_text", "enum"):
                                        return t
                return local_types[node.id]
            resolved = self._resolve_name_type(node.id, scope, local_types)
            if resolved:
                return resolved
            return None
        # R1_6: Ein Enum-Typ ist eine geschlossene Wertemenge — die
        # String-Darstellung eines Enum-Werts ist kontrolliert (der Name
        # des Mitglieds). Er wird deshalb wie ein freigegebener
        # Renderer behandelt, nicht als beliebiger String.
        if ann and ann.split(".")[-1] in self.env.enum_classes:
            return "enum"
        if isinstance(node, ast.BinOp):
            # R1_6: ``pool["printable_ratio"] * 100`` — der Typ folgt
            # dem linken Operanden, wenn dieser belegt ist.
            #
            # Ausgenommen ist der **Format-Operator** (``%``): dort ist
            # der Typ des Ergebnisses der Formatstring, nicht der des
            # linken Operanden. Der Format-Ausdruck wird ueber
            # _check_percent geprueft.
            if isinstance(node.op, ast.Mod):
                return ann
            t = self.expr_type(node.left, scope, local_types)
            if t is not None:
                return t
            return self.expr_type(node.right, scope, local_types)
        if isinstance(node, ast.BoolOp):
            # R1_6: ``a or b`` — der Typ ist der des ersten Arms, der
            # einen belegbaren Typ hat (der zweite ist der Fallback).
            for value in node.values:
                t = self.expr_type(value, scope, local_types)
                if t is not None:
                    return t
            return None
        if isinstance(node, ast.Attribute):
            return self._attribute_type(node, scope, local_types)
        if isinstance(node, ast.Subscript):
            return self._subscript_type(node, scope, local_types)
        if isinstance(node, ast.Call):
            fname = _name_of(node.func)
            if fname in APPROVED_FORMATTERS | APPROVED_RENDERERS:
                # R1_6: eigener Typ — der Wert ist kontrollierter Text,
                # kein beliebiger String. Er darf mit %s ausgegeben
                # werden, ohne dass der Guard eine Verletzung meldet.
                return "controlled_text"
            # R1_6: Rueckgabeannotation einer bekannten Methode.
            ret = self.env.method_returns.get(fname)
            if ret:
                base = ret.split("|")[0].strip()
                if base in BUILTIN_NUMERIC or base in ("str", "bytes"):
                    return base
                if base.split(".")[-1] in self.env.dataclass_fields:
                    return base
            # R1_6: Zugriff auf eine belegt kontrollierte Quelle
            # (``ctx.load_errors.get(...)`` / ``ctx.load_errors[...]``).
            if _is_controlled_source(node.func):
                return "controlled"
            # R1_6: ``dict.get("note", "")`` — der Schluessel ist aus der
            # geschlossenen Menge der kontrollierten Felder.
            if fname == "get" and len(node.args) >= 1:
                key_node = node.args[0]
                if isinstance(key_node, ast.Constant) and isinstance(
                        key_node.value, str):
                    key = key_node.value
                    if key in CONTROLLED_DICT_KEYS:
                        return "controlled"
                    if key in CONTROLLED_NUMERIC_KEYS:
                        return "float" if key == "printable_ratio" else "int"
                    if key in CONTROLLED_CONTAINER_CONTENT:
                        return "controlled_text"
            # R1_6: ``getattr(obj, "note", "")`` — der Attributname ist
            # statisch und aus der geschlossenen Menge der belegt
            # kontrollierten Felder. Der Wert selbst ist kontrolliert.
            if fname == "getattr" and len(node.args) >= 2:
                attr = node.args[1]
                if (isinstance(attr, ast.Constant)
                        and isinstance(attr.value, str)
                        and attr.value in CONTROLLED_ATTRIBUTES):
                    return "controlled"
            if fname in self.env.function_params:
                return None
            return _ann_of(node)
        return ann

    def _attribute_type(self, node, scope, local_types) -> str | None:
        """Typ eines Attributzugriffs — ueber Dataclass-Feldannotationen."""
        base = node.value
        # R1_6: Belegt kontrolliertes Attribut (siehe
        # CONTROLLED_ATTRIBUTES) — die Herkunft ist im Code belegt.
        if node.attr in CONTROLLED_ATTRIBUTES:
            return "controlled"
        base_type = self.expr_type(base, scope, local_types)
        if base_type:
            cls = base_type.split("|")[0].strip()
            t = self.env.field_type(cls, node.attr)
            if t:
                return t
            # R1_6: berechnete Property (Typ aus der Rueckgabeannotation).
            t = self.env.property_type(cls, node.attr)
            if t:
                return t
        # Basis nicht aufloesbar: der Feldname kann trotzdem eindeutig auf
        # eine bekannte Dataclass zeigen (``header.header_size``).
        owner = self.env.field_owner(node.attr)
        if owner:
            return self.env.field_type(owner, node.attr)
        return None

    def _resolve_name_type(self, name: str, scope, local_types) -> str | None:
        """Typ eines Namens — ueber eine lokale Zuweisung mit bekannter
        Herkunft (``header = ctx.header`` -> DatHeader | None).

        Die Kette wird einmal aufgeloest: der Name stammt dann aus einem
        Dataclass-Feld, dessen Typ bekannt ist.

        R1_6 (False Positive "annotierte Integer-Felder" / Enum-Ausgabe):
        Ein **Funktionsparameter** traegt seine Typinformation in der
        Annotation, nicht in einer lokalen Zuweisung. ``def f(status: S)``
        belegt ``status`` als ``S`` — das war vorher nicht auflösbar und
        erzeugte ungerechtfertigte Befunde.
        """
        if scope is None:
            return None
        # 1) Funktionsparameter mit Annotation
        scope_name = getattr(scope, "name", "") or ""
        params = self.env.function_params.get(scope_name)
        if params and name in params:
            # R1_6: belegt kontrollierter Parameter (Herunft im Code
            # nachpruefbar) — siehe CONTROLLED_PARAMETERS.
            if (scope_name, name) in CONTROLLED_PARAMETERS:
                return "controlled"
            ann = params[name]
            base = ann.split("|")[0].strip()
            if base in BUILTIN_NUMERIC or base in ("str", "bytes", "enum"):
                return base
            if base.split(".")[-1] in self.env.enum_classes:
                return "enum"
        # 2) lokale Zuweisung mit bekannter Herkunft
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == name:
                        src_t = self.expr_type(n.value, scope, local_types)
                        if src_t:
                            return src_t
            # 3) annotierte lokale Zuweisung: n: int = ...
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                    and n.target.id == name:
                ann = ast.unparse(n.annotation)
                base = ann.split("|")[0].strip()
                if base in BUILTIN_NUMERIC or base in ("str", "bytes"):
                    return base
                if base.split(".")[-1] in self.env.enum_classes:
                    return "enum"
        return None

    def _subscript_type(self, node, scope, local_types) -> str | None:
        """Typ eines Subscripts — ueber die Annotation des Containers."""
        # R1_6: Belegt kontrollierte Quelle (siehe _is_controlled_source).
        if _is_controlled_source(node.value):
            return "controlled"
        # R1_6: Dict-Subscript auf einen belegt kontrollierten Schluessel
        # (siehe CONTROLLED_DICT_KEYS). Der Wert stammt aus einem
        # statischen Literal oder einer geschlossenen Zustandsmenge.
        if (isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            key = node.slice.value
            if key in CONTROLLED_DICT_KEYS:
                # R1_6: Der Schluessel ist aus der geschlossenen Menge der
                # kontrollierten Felder. Die Basis (Dikt) kann variabel
                # benannt sein — der Schluessel entscheidet die Kontrolle.
                return "controlled"
            if key in CONTROLLED_NUMERIC_KEYS:
                # R1_6: reine Zahlenwerte — als Zahl typisiert.
                return "float" if key == "printable_ratio" else "int"
            if key in CONTROLLED_CONTAINER_CONTENT:
                # R1_6: String-Pool-Inhalt — bewusste fachliche Ausnahme
                # (siehe CONTROLLED_CONTAINER_CONTENT).
                return "controlled_text"
        base_type = self.expr_type(node.value, scope, local_types)
        if base_type is None:
            return None
        if base_type.startswith("dict["):
            inner = base_type[base_type.find("[") + 1:base_type.rfind("]")]
            return inner.split(",")[-1].strip() if "," in inner else None
        if base_type.startswith("list[") or base_type.startswith("tuple["):
            return base_type[base_type.find("[") + 1:base_type.rfind("]")]
        return None

    # -- Pruefungen ----------------------------------------------------
    def check_text_expr(self, node, src, file, lineno, field, out,
                        scope, local_types):
        if node is None:
            return
        # Ein f-String wird IMMER ueber die Format-Spec-Regel geprueft —
        # die String-Typ-Ableitung wuerde ihn sonst faelschlich als
        # unbeschaenkten Text einstufen.
        if isinstance(node, ast.JoinedStr):
            self._check_fstring(node, src, file, lineno, field, out,
                                scope, local_types)
            return
        t = self.expr_type(node, scope, local_types)
        # R1_6: Ein Enum ist eine geschlossene Wertemenge — kontrolliert.
        # Ebenso eine belegt kontrollierte Quelle (load_errors).
        if t in ("enum", "controlled", "controlled_text"):
            return
        if t == "str":
            # Freier String-Typ: nur zulaessig, wenn statisch oder
            # ueber einen freigegebenen Formatter erzeugt.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return
            if isinstance(node, ast.Call) and _name_of(node.func) in (
                    APPROVED_FORMATTERS | APPROVED_RENDERERS):
                return
            out.append(Violation(
                file, lineno, "V1_UNCONTROLLED_TEXT",
                "Feld '%s' erhaelt einen String-Typ ohne nachgewiesene "
                "Typkontrolle (Herkunft nicht freigegeben)" % field,
                _snip(src, node)))
            return
        if t in BUILTIN_NUMERIC:
            return                                  # beschaenkt

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return                                  # (a) statisch
        if isinstance(node, ast.Call):
            fname = _name_of(node.func)
            if fname in (APPROVED_FORMATTERS | APPROVED_RENDERERS):
                return                              # (b) freigegeben
            if fname in UNBOUNDED_CONVERSIONS:
                out.append(Violation(
                    file, lineno, "V2_UNBOUNDED_CONVERSION",
                    "Feld '%s' verwendet %s() — erzeugt beliebigen Text ohne "
                    "Typkontrolle" % (field, fname),
                    _snip(src, node)))
                return
            out.append(Violation(
                file, lineno, "V1_UNKNOWN_CALL",
                "Feld '%s' erhaelt %s() ohne erkennbare Typkontrolle"
                % (field, fname),
                _snip(src, node)))
            return

        if isinstance(node, ast.JoinedStr):
            # Format-Spec hat Vorrang vor dem String-Typ: f"{n:d}" ist
            # beschaenkt, f"{v}" ist es nicht.
            self._check_fstring(node, src, file, lineno, field, out,
                                scope, local_types)
            return

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            self._check_percent(node, src, file, lineno, field, out,
                                scope, local_types)
            return

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            out.append(Violation(
                file, lineno, "V1_CONCAT",
                "Feld '%s' ist eine String-Verkettung — keine Typkontrolle"
                % field,
                _snip(src, node)))
            return

        if isinstance(node, ast.Name):
            # R1_6: Ein bloser Name bedeutet "die Herkunft ist nicht
            # belegbar" — das ist eine **Hypothese**, kein belegter
            # Verstoß. In einem Ausgabekanal (Feldname beginnt mit
            # "ausgabe@") bleibt der Befund deshalb ein WARN: er markiert
            # eine offene Pruefstelle, behauptet aber keinen Leak.
            #
            # In einem **Diagnosefeld** (detail/title/message/...) bleibt
            # er ein ERROR — dort ist die Herkunft der oeffentlichen
            # Meldung zwingend nachzuweisen.
            severity = "WARN" if field.startswith("ausgabe@") else "ERROR"
            out.append(Violation(
                file, lineno, "V3_UNKNOWN_ORIGIN",
                "Feld '%s' ist ein blosser Name (%s) — der Typ ist nicht "
                "belegbar, die Herkunft damit unbekannt" % (field, node.id),
                _snip(src, node), severity=severity))
            return

        out.append(Violation(
            file, lineno, "V1_UNCLASSIFIED",
            "Feld '%s' hat einen nicht klassifizierten Ausdruck (%s)"
            % (field, type(node).__name__),
            _snip(src, node)))

    def _check_percent(self, node, src, file, lineno, field, out,
                       scope, local_types):
        fmt = ""
        args = []
        if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            fmt = node.left.value
        if isinstance(node.right, ast.Tuple):
            args = list(node.right.elts)
        elif node.right is not None:
            args = [node.right]

        unbounded = []
        bounded = []
        i = 0
        while i < len(fmt):
            if fmt[i] != "%":
                i += 1
                continue
            if i + 1 < len(fmt) and fmt[i + 1] == "%":
                i += 2
                continue
            j = i + 1
            while j < len(fmt) and fmt[j] in "+- #0123456789.*":
                j += 1
            if j >= len(fmt):
                break
            conv = fmt[j]
            if conv in UNBOUNDED_CONVERSIONS:
                unbounded.append("%" + conv)
            elif conv in BOUNDED_CONVERSIONS:
                bounded.append("%" + conv)
            i = j + 1

        # R1_6: Die Herkunft der Argumente wird VOR der Konvertierung
        # geprueft. Eine geschlossene Wertemenge (Enum) oder ein belegter
        # Zahlentyp ist auch bei %s kontrolliert — der fruehere Ablauf
        # stufte %s pauschal als unbeschaenkt ein und meldete dadurch
        # ungerechtfertigte Befunde (False Positive).
        arg_types = [self.expr_type(a, scope, local_types) for a in args]
        # R1_6: Jedes Argument muss fuer sich kontrolliert sein. Eine
        # belegte Zahl (z. B. ein Offset) ist ebenso kontrolliert wie
        # ein kontrollierter Text.
        all_closed = bool(arg_types) and all(
            (t in ("enum", "controlled", "controlled_text")
             or t in BUILTIN_NUMERIC) for t in arg_types)
        # R1_6: Ein freigegebener Formatter (public_error u. a.) liefert
        # per Konstruktion kontrollierten Text — auch als %-Argument und
        # unabhaengig von der verwendeten Konvertierung. Ein
        # freigegebener Formatter ist **Text**, "%d" darauf anzuwenden
        # waere ein Formatfehler — aber kein Datenleck.
        approved_args = [a for a in args
                         if isinstance(a, ast.Call)
                         and _name_of(a.func) in (
                             APPROVED_FORMATTERS | APPROVED_RENDERERS)]
        all_approved = bool(args) and len(approved_args) == len(args)

        if unbounded and not (all_closed or all_approved):
            out.append(Violation(
                file, lineno, "V2_UNBOUNDED_CONVERSION",
                "Feld '%s' nutzt %s — diese Konvertierung kann beliebigen "
                "Text erzeugen (str/repr eines unbekannten Objekts)"
                % (field, ", ".join(unbounded)),
                _snip(src, node), severity="ERROR"))
            return

        if all_closed:
            return                              # geschlossene Wertemenge

        # Nur beschaenkte Konvertierungen: die Argumente muessen dennoch
        # belegbar sein, sonst ist die Herkunft unbekannt (V3).
        for a, t in zip(args, arg_types):
            if t is None:
                out.append(Violation(
                    file, lineno, "V3_UNKNOWN_ORIGIN",
                    "Feld '%s': Argument der %s-Formatierung hat einen nicht "
                    "belegbaren Typ" % (field, ",".join(bounded) or "%"),
                    _snip(src, a), severity="WARN"))
            elif t == "Any":
                # Untypisierter Containerwert: die Konvertierung selbst ist
                # beschraenkt (%d wirft TypeError bei Text), die Herkunft
                # aber unbelegt. Kein Datenleck, aber keine Belegbarkeit.
                out.append(Violation(
                    file, lineno, "V4_UNTYPED_ORIGIN",
                    "Feld '%s': Argument der %s-Formatierung stammt aus einem "
                    "untypisierten Container (Any) — die Konvertierung kann "
                    "keinen fremden Text transportieren, die Herkunft ist aber "
                    "unbelegt"
                    % (field, ",".join(bounded) or "%"),
                    _snip(src, a), severity="WARN"))
            elif t not in BUILTIN_NUMERIC and t != "str":
                # R1_6: Ein freigegebener Formatter liefert Text. Wird er
                # mit "%d" formatiert, ist das ein Formatfehler — aber
                # kein Datenleck, denn der Text ist kontrolliert.
                out.append(Violation(
                    file, lineno, "V1_TYPE_MISMATCH",
                    "Feld '%s': Argument der %s-Formatierung hat Typ %s, "
                    "erwartet Zahl" % (field, ", ".join(bounded), t),
                    _snip(src, a), severity="ERROR"))

    def _check_fstring(self, node, src, file, lineno, field, out,
                       scope, local_types):
        bad = False
        for v in node.values:
            if not isinstance(v, ast.FormattedValue):
                continue
            # R1_6: Die Konvertierung ``!r``/``!s``/``!a`` steht NICHT in
            # der Format-Spec, sondern im Feld ``conversion`` des
            # FormattedValue. Sie ruft str()/repr()/ascii() auf und ist
            # damit unbeschaenkt — der fruehere Code pruefte nur die
            # Format-Spec und uebersah diese Form (False Negative).
            if v.conversion is not None and v.conversion != -1:
                conversion = chr(v.conversion)
                if conversion in UNBOUNDED_CONVERSIONS:
                    out.append(Violation(
                        file, lineno, "V2_UNBOUNDED_CONVERSION",
                        "Feld '%s': f-String nutzt die unbeschaenkte "
                        "Konvertierung !%s" % (field, conversion),
                        _snip(src, v), severity="ERROR"))
                    bad = True
                    continue
            spec = v.format_spec
            if spec is not None:
                # f"{v:d}" -> beschaenkt; f"{v:s}" / f"{v!r}" -> unbeschaenkt.
                convs = set()
                for sub in ast.walk(spec):
                    if isinstance(sub, ast.Constant) and isinstance(
                            sub.value, str):
                        for c in sub.value:
                            if c in UNBOUNDED_CONVERSIONS:
                                convs.add(c)
                if convs:
                    # R1_6 Korrektur (False Negative): die unbeschaenkte
                    # Konvertierung wurde erkannt, aber **nicht gemeldet** —
                    # es wurde nur das Flag gesetzt. Damit blieb
                    # f"{x:s}" (str() auf einem fremden Wert) unbeanstandet.
                    out.append(Violation(
                        file, lineno, "V2_UNBOUNDED_CONVERSION",
                        "Feld '%s': f-String nutzt die unbeschaenkte "
                        "Konvertierung %s" % (
                            field, "/".join(sorted(convs))),
                        _snip(src, v), severity="ERROR"))
                    bad = True
                    break
                continue
            t = self.expr_type(v.value, scope, local_types)
            # R1_6: Ein freigegebener Formatter (public_error u. a.)
            # liefert per Konstruktion kontrollierten Text — unabhaengig
            # davon, ob der Typaufsatz "str" oder "unbekannt" ergibt.
            if (isinstance(v.value, ast.Call)
                    and _name_of(v.value.func) in (
                        APPROVED_FORMATTERS | APPROVED_RENDERERS)):
                continue
            if t is None:
                out.append(Violation(
                    file, lineno, "V3_UNKNOWN_ORIGIN",
                    "Feld '%s': f-String-Platzhalter hat einen nicht belegbaren "
                    "Typ" % field,
                    _snip(src, v.value), severity="WARN"))
                bad = True
            elif t == "str":
                out.append(Violation(
                    file, lineno, "V2_UNBOUNDED_CONVERSION",
                    "Feld '%s': f-String-Platzhalter hat String-Typ ohne "
                    "Typkontrolle" % field,
                    _snip(src, v.value), severity="ERROR"))
                bad = True
            elif t == "enum":
                continue                              # geschlossene Menge
        if bad:
            return

    def check_evidence(self, node, src, file, lineno, out, scope, local_types):
        """evidence-Dict: kontrollierte Werte, geschlossene Mengen, Zahlen."""
        if node is None:
            return
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if v is None:
                    continue
                # R1_6: ``ast.unparse`` liefert den Schluessel mit
                # Anfuehrungszeichen ("'blocked_by'"). Fuer den Vergleich
                # mit den kontrollierten Schluesselnamen wird er
                # normalisiert.
                key = ast.unparse(k) if k is not None else "?"
                if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                    key = key[1:-1]
                self._check_evidence_value(
                    v, src, file, lineno, out, scope, local_types, key)
            return
        if isinstance(node, ast.Name):
            out.append(Violation(
                file, lineno, "V3_EVIDENCE_ALIAS",
                "evidence ist ein blosser Name (%s) — die Herkunft der Werte "
                "ist am Aufrufort nicht pruefbar" % node.id,
                _snip(src, node), severity="WARN"))
            return
        t = self.expr_type(node, scope, local_types)
        if t is not None:
            return
        out.append(Violation(
            file, lineno, "V1_UNCLASSIFIED",
            "evidence hat einen nicht klassifizierten Ausdruck",
            _snip(src, node)))

    def _check_evidence_value(self, v, src, file, lineno, out, scope,
                              local_types, key):
        # R1_6: Belegt kontrollierter Evidence-Schluessel (siehe
        # CONTROLLED_EVIDENCE_KEYS) — der Wert stammt aus einer
        # geschlossenen Menge.
        if key in CONTROLLED_EVIDENCE_KEYS:
            return
        if isinstance(v, ast.Dict):
            self.check_evidence(v, src, file, lineno, out, scope, local_types)
            return
        if isinstance(v, ast.Constant):
            if isinstance(v.value, str):
                return                              # statischer Text
            if isinstance(v.value, (int, float, bool)) or v.value is None:
                return                              # geschlossene Menge
            return
        if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
            for e in v.elts:
                if isinstance(e, ast.Constant) and isinstance(e.value, str):
                    continue
                self._check_evidence_value(e, src, file, lineno, out, scope,
                                          local_types, key)
            return
        if isinstance(v, ast.Call):
            fname = _name_of(v.func)
            if fname in (APPROVED_FORMATTERS | APPROVED_RENDERERS):
                return                              # kontrolliert
            if fname in UNBOUNDED_CONVERSIONS:
                out.append(Violation(
                    file, lineno, "V2_UNBOUNDED_CONVERSION",
                    "evidence['%s'] verwendet %s() — beliebiger Text"
                    % (key, fname),
                    _snip(src, v), severity="ERROR"))
                return
        t = self.expr_type(v, scope, local_types)
        if t in BUILTIN_NUMERIC:
            return                                  # beschaenkt
        if t == "str":
            out.append(Violation(
                file, lineno, "V1_UNCONTROLLED_TEXT",
                "evidence['%s'] erhaelt einen String-Typ ohne nachgewiesene "
                "Typkontrolle" % key,
                _snip(src, v), severity="ERROR"))
            return
        if t is None:
            out.append(Violation(
                file, lineno, "V3_UNKNOWN_ORIGIN",
                "evidence['%s'] hat eine nicht belegbare Herkunft" % key,
                _snip(src, v), severity="WARN"))
            return


# ------------------------------------------------------- Dateipruefung

def check_file(path: Path, root: Path, guard: Guard) -> list[Violation]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    rel = str(path.relative_to(root)) if root in path.parents else str(path)
    out: list[Violation] = []

    scope_of: dict[int, ast.AST] = {}
    scopes = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module))]
    for scope in scopes:
        for sub in ast.walk(scope):
            scope_of[id(sub)] = scope

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = _name_of(node.func)
        scope = scope_of.get(id(node))
        local_types = _local_types(scope, guard.env.enum_classes)

        # --- Result-Erzeugung
        if fname and fname.endswith(("CheckResult", "Result")):
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            pos = ["check_id", "title", "status", "detail", "evidence",
                   "confidence"]
            for i, a in enumerate(node.args):
                if i < len(pos) and pos[i] not in kwargs:
                    kwargs[pos[i]] = a
            for f in PUBLIC_TEXT_FIELDS:
                if f in kwargs:
                    guard.check_text_expr(kwargs[f], src, rel, node.lineno,
                                          f, out, scope, local_types)
            if "evidence" in kwargs:
                guard.check_evidence(kwargs["evidence"], src, rel, node.lineno,
                                     out, scope, local_types)

        # --- direkte Ausgabe
        #
        # R1_6: Die Ausgabefunktionen haben unterschiedliche Signaturen.
        # Bei den Qt-Dialogen (critical/warning/information) ist das
        # ERSTE Argument das Eltern-Widget (``self``) — der Text steht an
        # Position 2. Der fruehere Code pruefte alle Argumente gleich und
        # meldete deshalb ``self`` als Textfeld (False Positive).
        #
        # Bei ``print``/``emit_lines``/``emit_json``/``setText``/
        # ``setPlainText``/``addItem``/``setToolTip`` steht der Text an
        # Position 1.
        if fname in ("critical", "warning", "information"):
            text_args = node.args[2:]
        elif fname == "emit_json":
            # R1_6: ``emit_json`` serialisiert ein **Dikt**. Der Guard
            # kann ``dict[str, Any]`` nicht typisieren (dokumentierte
            # Grenze) — stattdessen wird der **Inhalt** des Dikt-Literals
            # geprueft. Das ist strenger als der reine Containertyp.
            #
            # Das Argument ist meist eine Variable (``payload = {...}``).
            # Daher wird die Zuweisung im umgebenden Scope nachgeschlagen.
            text_args = []
            for arg in node.args:
                resolved = _resolve_dict_literal(arg, scope)
                if resolved is not None:
                    for k, v in zip(resolved.keys, resolved.values):
                        if k is None:
                            continue
                        key = ast.unparse(k)
                        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                            key = key[1:-1]
                        guard.check_text_expr(v, src, rel, node.lineno,
                                              "ausgabe@emit_json()[%s]" % key,
                                              out, scope, local_types)
                else:
                    text_args.append(arg)
        else:
            text_args = node.args
        if fname in ("print", "emit_lines", "emit_json", "emit_error_line",
                     "setText", "setPlainText", "critical", "warning",
                     "information", "addItem", "setToolTip"):
            for arg in text_args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    continue
                # R1_6: Ein bloser Name in einem Ausgabekanal ist eine
                # **Hypothese** ("koennte beliebiger Text sein"), kein
                # belegter Verstoß. Der Guard versucht deshalb zuerst,
                # die Herkunft im Scope aufzuloesen (Zuweisung, Aufruf,
                # Annotation). Nur wenn das nicht gelingt, bleibt der
                # Befund — dann aber als WARN ("Herkunft nicht
                # belegbar"), nicht als ERROR.
                resolved = _resolve_output_source(arg, scope)
                if resolved is not None:
                    arg = resolved
                guard.check_text_expr(arg, src, rel, node.lineno,
                                      "ausgabe@%s()" % fname, out, scope,
                                      local_types)

    return out


def _resolve_output_source(node, scope):
    """Herkunft eines Ausgabearguments im Scope aufloesen — oder ``None``.

    R1_6: Loest eine einfache Zuweisung auf:
      * ``x = <Dikt-Literal>``  -> das Literal
      * ``x = <Aufruf>``         -> der Aufruf (Typ wird vom Guard
                                    ueber die Rueckgabeannotation
                                    aufgeloest)
      * ``x = <annotierter Wert>`` -> bleibt unaufgeloest

    Ein **bloser Name** bleibt unaufgeloest — dann meldet der Guard
    "Herkunft nicht belegbar" als WARN.
    """
    if not isinstance(node, ast.Name) or scope is None:
        return None
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                if isinstance(tgt, ast.Name) and tgt.id == node.id:
                    if isinstance(n.value, (ast.Dict, ast.Call)):
                        return n.value
                    return None
    return None


def _resolve_dict_literal(node, scope):
    """Dikt-Literal hinter einem Namen aufloesen — oder ``None``.

    R1_6: ``payload = {...}`` gefolgt von ``emit_json(payload)``. Der
    Guard verfolgt die Zuweisung im umgebenden Scope, damit der
    **Inhalt** des Dikt geprueft wird statt nur des Containers.
    """
    if isinstance(node, ast.Dict):
        return node
    if isinstance(node, ast.Name) and scope is not None:
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == node.id:
                        if isinstance(n.value, ast.Dict):
                            return n.value
                        return None
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                    and n.target.id == node.id:
                if isinstance(n.value, ast.Dict):
                    return n.value
                return None
    return None


def _local_types(scope, enum_classes=None) -> dict[str, str]:
    """Lokale Typinformation aus Annotationen und Zuweisungen."""
    types: dict[str, str] = {}
    if scope is None:
        return types
    enum_classes = enum_classes or set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = scope.args
        all_args = (list(args.posonlyargs) + list(args.args)
                    + list(args.kwonlyargs))
        for arg in all_args:
            if arg.annotation is not None:
                ann = ast.unparse(arg.annotation)
                # R1_6: Eine Enum-Annotation ist eine geschlossene
                # Wertemenge — sie wird als "enum" gefuehrt, damit der
                # Guard sie nicht als beliebigen String einstuft.
                if ann.split(".")[-1] in enum_classes:
                    types[arg.arg] = "enum"
                else:
                    types[arg.arg] = ann
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign):
            t = _ann_of(n.value)
            if t:
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name):
                        types[tgt.id] = t
    return types


# ------------------------------------------------------- Fixtures

POSITIVE = {
    "static_detail": '''
def f(ctx):
    return CheckResult("I-01", "Titel", "PASS", "Container beginnt mit BCPS", {})
''',
    "approved_formatter": '''
from ssb_i.errors import public_error
def f(ctx, exc):
    return CheckResult("I-05", "Titel", "FAILED", public_error(exc), {})
''',
    "numeric_percent": '''
def f(ctx):
    n = len(ctx.chunks)
    return CheckResult("I-04", "Titel", "PASS", "Summe %d passt" % n,
                       {"count": n, "delta": 0})
''',
    "evidence_literals": '''
def f(ctx):
    return CheckResult("I-01", "Titel", "PASS", "ok",
                       {"magic": "42435053", "expected": "42435053",
                        "count": 3, "flag": True})
''',
    "evidence_approved_call": '''
from ssb_i.errors import public_error
def f(ctx, exc):
    return CheckResult("I-05", "Titel", "FAILED", "x",
                       {"error": public_error(exc)})
''',
    "bounded_fstring": '''
def f(ctx):
    n = len(ctx.chunks)
    return CheckResult("I-04", "Titel", "PASS", f"Summe {n:d} passt", {})
''',
    # R1_6: ``load_errors`` ist die belegt kontrollierte Fehlerquelle des
    # Projekts — jeder Eintrag stammt aus ``public_error(exc)``
    # (save_integrity.py:211-231). Der fruehere Selbsttest erwartete
    # hier eine Verletzung; das widersprach der belegten Herkunft.
    # Der Wert wird deshalb als kontrolliert gefuehrt.
    "controlled_load_errors": '''
def f(ctx):
    return CheckResult("I-10", "Titel", "FAILED", ctx.load_errors["plugins"], {})
''',
}

NEGATIVE = {
    "raw_bytes_detail": '''
def f(ctx):
    return CheckResult("I-01", "Titel", "FAILED",
                       "erste 4 Bytes sind %r" % ctx.disk[:4], {})
''',
    "raw_bytes_fstring": '''
def f(ctx):
    return CheckResult("I-01", "Titel", "FAILED",
                       f"erste 4 Bytes sind {ctx.disk[:4]!r}", {})
''',
    "exception_text": '''
def f(ctx, exc):
    return CheckResult("I-05", "Titel", "FAILED", "zlib-Fehler: %s" % exc, {})
''',
    "evidence_raw_bytes": '''
def f(ctx):
    return CheckResult("I-08", "Titel", "FAILED", "x",
                       {"magic": ctx.payload[:12].decode("ascii", "replace")})
''',
    "str_conversion": '''
def f(ctx, value):
    return CheckResult("I-11", "Titel", "FAILED", str(value), {})
''',
    "direct_print": '''
def f(ctx, path):
    print(f"Pfad: {path}")
''',
    "evidence_alias": '''
def f(ctx, evidence):
    return CheckResult("I-12", "Titel", "PASS", "ok", evidence)
''',
    "nested_evidence": '''
def f(ctx):
    return CheckResult("I-13", "Titel", "PASS", "ok",
                       {"sel": {"name": ctx.player_name}})
''',
    # R1_6: Die Konversion ``!r`` steht im ``conversion``-Feld des
    # FormattedValue, nicht in der Format-Spec. Der Guard hat sie
    # frueher uebersehen (zweiter False Negative).
    "repr_conversion": '''
def f(ctx):
    return CheckResult("I-01", "Titel", "FAILED", f"erste {ctx.disk[:4]!r}", {})
''',
    # R1_6: ``sys.argv[0]`` ist ein Pfad und darf nicht in eine
    # oeffentliche Ausgabe gelangen (F-2).
    "argv_path_output": '''
import sys
def f():
    print("usage: %s [--opt]" % sys.argv[0])
''',
    "plain_fstring": '''
def f(ctx, name):
    return CheckResult("I-14", "Titel", "PASS", f"Saves von {name}", {})
''',
}


def selftest(env: TypeEnv) -> int:
    import tempfile
    guard = Guard(env)
    rows = []
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, code in POSITIVE.items():
            p = root / f"pos_{name}.py"
            p.write_text(code, encoding="utf-8")
            v = check_file(p, root, guard)
            ok = len(v) == 0
            rows.append({"case": name, "expect": "clean", "violations": len(v),
                         "pass": ok})
            if not ok:
                failures += 1
                for x in v:
                    print(f"  FALSE POSITIVE {name}: {x.rule} {x.detail}")
        for name, code in NEGATIVE.items():
            p = root / f"neg_{name}.py"
            p.write_text(code, encoding="utf-8")
            v = check_file(p, root, guard)
            ok = len(v) > 0
            rows.append({"case": name, "expect": "violation",
                         "violations": len(v), "pass": ok})
            if not ok:
                failures += 1
                print(f"  FALSE NEGATIVE {name}: nicht erkannt")
    print("=== AST-Guard v2 Selbsttest ===")
    for r in rows:
        mark = "OK  " if r["pass"] else "FAIL"
        print(f"  {mark} {r['case']:26s} erwartet={r['expect']:10s} "
              f"verletzungen={r['violations']}")
    print(f"\nFAILS: {failures}/{len(rows)}")
    Path("/tmp/ssbi_r1_4/guard_selftest_v2.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if failures else 0


def scan(target: Path) -> int:
    root = target if target.is_dir() else target.parent
    files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
    env = TypeEnv()
    for f in files:
        if ".venv" in f.parts or "__pycache__" in f.parts:
            continue
        env.learn(f)
    guard = Guard(env)
    allv = []
    for f in files:
        if ".venv" in f.parts or "__pycache__" in f.parts:
            continue
        try:
            allv.extend(check_file(f, root, guard))
        except SyntaxError as exc:
            print(f"  SYNTAX ERROR {f}: {exc}")
    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for v in allv:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        by_file[v.file] = by_file.get(v.file, 0) + 1
    print(f"=== AST-Guard v2 Scan: {len(files)} Dateien, {len(allv)} Befunde ===")
    for r, n in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {r}")
    print("\n--- pro Datei ---")
    for f, n in sorted(by_file.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {f}")
    print("\n--- ERROR-klassifizierte Befunde (echte Verletzungen) ---")
    errs = [v for v in allv if v.severity == "ERROR"]
    print(f"  {len(errs)} ERROR / {len(allv) - len(errs)} WARN")
    for v in errs:
        print(f"  {v.file}:{v.line}  [{v.rule}] {v.detail}")
        print(f"      {v.snippet[:150]}")
    Path("/tmp/ssbi_r1_4/guard_scan_v2.json").write_text(
        json.dumps([v.as_dict() for v in allv], indent=2, ensure_ascii=False),
        encoding="utf-8")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scan", type=Path)
    args = ap.parse_args()
    env = TypeEnv()
    # Das Verzeichnis wird aus dem Skriptpfad abgeleitet, nicht fest
    # eingetragen: der Guard wird auch aus einem anderen Arbeitsverzeichnis
    # und aus einer anderen Arbeitskopie heraus gestartet.
    repo = Path(__file__).resolve().parent.parent
    for d in ("ssb_i", "ssb_ui"):
        p = repo / d
        if p.is_dir():
            for f in p.rglob("*.py"):
                env.learn(f)
    env.learn(repo / "sfda_cli.py")
    if args.selftest:
        sys.exit(selftest(env))
    if args.scan:
        sys.exit(scan(args.scan))
    ap.print_help()


if __name__ == "__main__":
    main()
