# SAVE_INTELLIGENCE_SPEC

**Projekt:** Starfield Data Analysis (SSB-I) · **Version dieser Spezifikation:** 1.0
**Stand:** 08.11.2026 · **Grundlage:** `SAVE_INTELLIGENCE_AUDIT.md`, Messungen via `audit/save-intelligence/audit.py`
**Ziel:** direkt umsetzbare Spezifikation. Keine Schreib-, Reparatur- oder Rekompressionsfunktion.

Belegte Datenbasis: Save-Version **153**, Engine **27**, Spielversion **1.16.244.0**, 10 echte Saves.
Für andere `save_version`/`engine_version` gilt Abschnitt 12.2 (Degradation).

---

## 1. Zweck und Abgrenzung

### 1.1 Inhalt dieses Pakets

| ID | Funktion | Paket |
|---|---|---|
| F1 | Identifikation: Metadaten, Dateiname, Charakter, Spielzeit | P2 |
| F2 | Integrität: 12 Einzelprüfungen mit fünfwertigem Status | P1 |
| F3 | Virtuelle Benennung | P2 |
| F4 | Gruppierung nach Charakter, Sortierung nach Zeit/Level/Name | P2 |
| F5 | Index mit Duplikaterkennung und Prüfhistorie | P3 |
| F6 | Vergleich in drei Ebenen inkl. Plugin-Mengendifferenz | P4 |
| F7 | Backup-Kopie mit Hash-Nachweis, Quarantäne-Markierung, Export | P5 |

### 1.2 Nicht-Ziele (verbindlich)

- Kein Schreiben, Umbenennen, Verschieben oder Löschen im Starfield-Save-Verzeichnis.
- Keine Rekompression, keine Reparatur, kein „Fix" eines Spielstands.
- Keine Aussage über die Ladbarkeit im Spiel. `PASS` bedeutet ausschließlich: *diese eine Prüfung hat ihr Kriterium erfüllt*.
- Keine Objekt-Ebene (Schiffe, Außenposten, Referenzen, FormID-Auflösung). Der Body ist nicht erschlossen — siehe Audit 3.4.
- Keine neue Datenbank, kein neues Framework, keine neue Abhängigkeit außerhalb der Standardbibliothek (+ vorhandenem PySide6).
- Keine Änderung an Release 1.0.0: `VERSION` in `ssb_i/product.py` bleibt unverändert.

---

## 2. Datenmodelle

Alle Modelle als `@dataclass(frozen=True)` im Stil des Bestands (`ssb_i/savegame_differential.py:31`).

### 2.1 `ssb_i/save_integrity.py`

```python
PASS = "PASS"; WARNING = "WARNING"; FAILED = "FAILED"
UNKNOWN = "UNKNOWN"; NOT_CHECKED = "NOT_CHECKED"

SEVERITY = {PASS: 0, WARNING: 1, UNKNOWN: 2, NOT_CHECKED: 3, FAILED: 4}

@dataclass(frozen=True)
class CheckResult:
    check_id:   str        # "I-04"
    title:      str        # "Padding-Summe gegen Dateirest"
    status:     str        # PASS|WARNING|FAILED|UNKNOWN|NOT_CHECKED
    detail:     str        # ein Satz, menschenlesbar, ohne Wertung
    evidence:   dict       # Messwerte; nur Zahlen/Str, keine Objekte
    confidence: str        # "deterministic" | "heuristic" | "unverified"

@dataclass(frozen=True)
class IntegrityReport:
    path:        str
    file_size:   int
    sha256:      str
    total:       str       # schlechtester Einzelstatus (SEVERITY-Maximum)
    checks:      list[CheckResult]
    disclaimer:  str       # Wortlaut aus Abschnitt 9.4, immer gesetzt
```

Regeln:
- `total` = Maximum nach `SEVERITY`, **kein** Durchschnitt.
- Ein `FAILED` in `I-01`, `I-02`, `I-03`, `I-05` setzt alle abhängigen Checks auf `NOT_CHECKED` mit `detail = "Voraussetzung fehlt: <check_id> ist FAILED"`.
- `disclaimer` ist konstant und nicht abschaltbar.

### 2.2 `ssb_i/save_identity.py`

```python
@dataclass(frozen=True)
class FilenameParts:
    save_name:   str          # "Save47"
    character_key: str | None # "A7460D2F"
    character_hex_name: str | None  # "Cole" (aus Hex-Tail)
    slot_counter: str | None  # "021034"
    timestamp:   str | None   # "20261007143524"
    level:       int | None   # 24
    save_type:   str | None   # "manual" | "autosave" | "exitsave" | None
    recognized:  bool         # alle Pflichtfelder erkannt

@dataclass(frozen=True)
class Playtime:
    raw: str; days: int | None; hours: int | None; minutes: int | None
    @property
    def total_minutes(self) -> int | None: ...

@dataclass(frozen=True)
class SaveIdentity:
    path: str
    sha256: str
    mtime: float
    # Herkunft je Feld: "header" | "filename" | "computed" | None
    player_name: str | None
    player_level: int | None
    location: str | None
    playtime: Playtime
    filetime_utc: str | None      # ISO-8601
    save_version: int | None
    engine_version: int | None
    game_version_current: str | None
    game_version_created: str | None
    save_number: int | None
    character_key: str | None
    save_type: str | None
    plugin_counts: dict           # {"normal": 25, "light": 50, "medium": 0}
    plugin_state: str             # VALIDATED | UNVERIFIED
    virtual_name: str
    name_parts_used: tuple[str, ...]   # welche Bausteine tatsächlich verwendet wurden
    warnings: tuple[str, ...]
```

### 2.3 `ssb_i/save_index.py`

```python
@dataclass(frozen=True)
class IndexEntry:
    path: str; sha256: str; size: int; mtime: float
    identity: SaveIdentity
    integrity_total: str
    integrity_checks: dict        # {"I-04": "PASS", ...} — Status je Check
    quarantined: bool
    first_seen: str; last_checked: str
    @property
    def group_key(self) -> str:   # character_key or "#" + player_name
        ...

@dataclass
class SaveIndex:
    version: int                  # 1
    generated: str                # ISO-8601
    root: str                     # gescanntes Verzeichnis
    entries: list[IndexEntry]
```

### 2.4 `ssb_i/save_compare.py`

```python
SAME_CHARACTER = "SAME_CHARACTER"; DIFFERENT_CHARACTER = "DIFFERENT_CHARACTER"

@dataclass(frozen=True)
class PluginDelta:
    added: list[str]; removed: list[str]; reordered: list[str]
    equal: bool
    comparable: bool              # False wenn ein decode_state != VALIDATED

@dataclass(frozen=True)
class RegionDiff:
    name: str                     # "header_plugin" | "body"
    start: int; end: int
    differing_bytes: int
    ratio: float
    interpretable: bool           # header_plugin: nur feldweise; body: False

@dataclass(frozen=True)
class ComparisonReport:
    left: str; right: str
    identity_verdict: str         # SAME_CHARACTER | DIFFERENT_CHARACTER | UNKNOWN
    identity_fields: dict         # Feld -> {"a":…, "b":…, "equal":bool,"source":…}
    plugins: PluginDelta
    metadata_clusters: list      # Änderungen im Header/Plugin-Bereich (verdächtig)
    body_regions: list[RegionDiff]
    anomalies: tuple[str, ...]
    disclaimer: str
```

---

## 3. Check-Katalog

Gemeinsame Signatur:

```python
def check_XX(ctx: SaveContext) -> CheckResult

@dataclass
class SaveContext:
    path: Path
    disk: bytes                   # Rohdatei
    container: SfsContainer       # aus read_container()
    payload: bytes | None         # None, wenn Dekompression scheiterte
    header: DatHeader | None
    plugin_info: PluginInfo | None
    chunk_sizes: list[int] | None
    geometry: dict                # aus read_chunk_table()
    data_dir: Path | None         # für I-12, optional
```

| ID | Prüft | Kriterium | Status bei Verletzung | Implementiert heute | Erkennt | Erkennt NICHT |
|---|---|---|---|---|---|---|
| **I-01** | Container-Magic | `disk[0:4] == b"BCPS"` | FAILED | ja (`:162`) | falsche Datei, fremdes Format | inhaltlich falschen Save |
| **I-02** | Kompression | `disk[68:72] == b"ZIP "` | FAILED | ja (`:178`) | künftige Verfahren | defekten Strom (→I-05) |
| **I-03** | Chunk-Tabellen-Geometrie | `chunk_sizes_offset + 4·n ≤ compressed_offset` **und** `compressed_offset % padding == 0`; Lücke > 0 → WARNING | FAILED / WARNING | **nein** | verschobene Tabelle, manipulierte Chunk-Anzahl | falsche Werte in plausibler Tabelle |
| **I-04** | Padding-Summe | `Σ ceil(chunk_i/pad)·pad == disk_size − compressed_offset` | FAILED | **nein** | Truncation, angehängte Bytes, vertauschte Größen | größenkonsistente Inhaltsfehler |
| **I-05** | Dekompression | jeder Chunk dekomprimierbar (zlib/Adler32) | FAILED | ja (`:220`) | Bitfehler, Truncation, falsches Padding | konsistente Neukompression |
| **I-06** | Nutzlänge | `len(payload) == container.uncompressed_size` | FAILED | **nein** | manipuliertes Größenfeld, halbe Dekompression | beidseitige Manipulation |
| **I-07** | Chunk-Anzahl | `n == ceil(unc/chunk_pre)` und `n > 0` | WARNING | teilweise (`:180`) | Widerspruch Größe/Raster | andere Raster künftiger Versionen |
| **I-08** | Header-Feldgrenzen | alle Längenfelder innerhalb Puffer, Stringlängen ≤ Rest, `player_level` 1…1000, `save_version` 1…500 | FAILED | **nein** | gekürzter Header, unplausible Längen | plausible Falschwerte |
| **I-09** | `header_size`-Semantik | — (Semantik unbekannt) | **immer UNKNOWN** | nein | nichts | alles |
| **I-10** | Plugin-Block-Grenzen | `plugin_info_offset + plugin_info_size ≤ len(payload)` | FAILED | teilweise (`:413`) | zerstörter Offset | falsche Größe bei gültigem Offset |
| **I-11** | Plugin-Selbstvalidierung | `decode_state == VALIDATED` | WARNING (bei UNVERIFIED) | ja (`:450`) | Desynchronisation, Müll als Liste | fehlende Plugins, fehlende Metadaten |
| **I-12** | Installation | alle gelisteten Plugins in `Data/` vorhanden | WARNING | **nein** | fehlende Master, entfernte Mods | inhaltliche Konflikte, Ladbarkeit |
| **I-14** | Folgen-Konsistenz | FileTime/Level/Spielzeit monoton über Sortierung; Spielversion nicht rückwärts | WARNING | **nein** | zurückgerollte Saves, Installationswechsel | Spielzustand-Inkonsistenz |

`I-13` (FormID-Auflösung) ist **nicht Teil dieses Pakets** und wird nicht als Check registriert — ein `NOT_IMPLEMENTED`-Platzhalter im Report wäre eine Aussage über Fähigkeiten, die nicht existieren. Stattdessen erscheint sie im `disclaimer`-Block als ausdrücklich nicht geprüft.

### 3.1 Aggregation

```python
def run_all(ctx: SaveContext) -> IntegrityReport
```
Reihenfolge fest: I-01, I-02, I-03, I-04, I-05, I-06, I-07, I-08, I-09, I-10, I-11, I-12, I-14.
Abbruchkette: `FAILED` in I-01/I-02/I-03/I-05 → alle folgenden `NOT_CHECKED`.

### 3.2 Messwerte für die Implementierung (Golden Values, Save-Version 153)

| Größe | Wert (10 echte Saves) |
|---|---|
| `chunk_size_pre` | 262144 |
| `padding_size` | 16 |
| `chunk_count` | 90 oder 91 |
| `compressed_offset` | 432 oder 448 (16-Byte-aligned) |
| `header_size` | 123 oder 125 |
| `plugin_info_offset` | 166 oder 168 |
| `plugin_info_size` | 5077 (Originale) |
| Plugin-Zahlen | 25 normal / 50 light / 0 medium |
| `save_version` / `engine_version` | 153 / 27 |

---

## 4. Identifikation und virtuelle Benennung (P2)

### 4.1 Dateinamen-Schema

```
<NName>_<ID8>M<NAMEHEX>_<SLOT6>_<YYYYMMDDHHMMSS>_<LEVEL>_<A>_<B>.sfs
```

Parser-Regel (Regex, tolerant):
```
^(?P<save_name>[A-Za-z]+\d+)
 _(?P<id8>[0-9A-Fa-f]{8})M(?P<namehex>[0-9A-Fa-f]{4,40})
 _(?P<slot>\d{6})
 _(?P<ts>\d{14})
 _(?P<level>\d{1,3})
 (?:_(?P<a>\d+)_(?P<b>\d+))?\.sfs$
```
`namehex` wird paarweise hex-dekodiert; Ergebnis gilt nur, wenn es druckbares ASCII ist.

`save_type` aus `save_name`: Präfix `Autosave` → `autosave`, `Exitsave` → `exitsave`, `Quicksave` → `quicksave`, `Save` → `manual`, sonst `None`.

### 4.2 `playtime`-Normalisierung

Eingabe (gemessen): `"2d.10h.34m.2 Tage.10 Stunden.34 Minuten"`
Regel: erstes Vorkommen von `(\d+)d\.(\d+)h\.(\d+)m\.` gewinnt; fehlt es, `(\d+)\s*Tage?` / `Stunden?` / `Minuten?` in derselben Reihenfolge.
Ergebnis: `Playtime(raw, days, hours, minutes)`, `total_minutes = days*1440 + hours*60 + minutes`.
Nicht parsebar → alle Felder `None`, **kein** Raten, Warnung `playtime_unparsed`.

### 4.3 Virtueller Name

```
<Player>_L<Level>_<YYYY-MM-DD_HHMM>_<Type><SaveNumber>_<Playtime>_<NN>p
```
Beispiel: `Cole_L24_2026-10-07_1435_Manual47_2d10h_75p`

Bausteine, Quellen und Ausfallverhalten:

| Baustein | Erste Quelle | Zweite Quelle | Ausfall |
|---|---|---|---|
| `<Player>` | `header.player_name` | `filename.character_hex_name` | beide leer → `Unknown` |
| `L<Level>` | `header.player_level` | `filename.level` | beide leer → Baustein weglassen |
| Datum | `header.filetime` → UTC | `filename.timestamp` | beide leer → `mtime` (UTC) + Warnung |
| `<Type>` | `filename.save_type` | — | `Save` |
| `<SaveNumber>` | `header.save_number` | `filename.slot` | weglassen |
| `<Playtime>` | `Playtime` → `XdYh` | — | weglassen |
| `<NN>p` | `plugin_counts` Summe | — | weglassen (bei `UNVERIFIED`) |

Bereinigung: `[^A-Za-z0-9-]` → `-`, Mehrfach-Striche zusammenfassen, Länge ≤ 120 Zeichen.
Kollision im Index: Suffix `_2`, `_3`, …; die Kollision wird als Warnung geführt.
**Der Originaldateiname wird nie geändert.** `virtual_name` existiert nur in Index und Anzeige.

### 4.4 Gruppierung und Sortierung

```python
def group_key(entry) -> str:   # character_key (Dateiname) oder "name:" + player_name
def sort_key(entry, mode) -> tuple
```
Sortiermodi:
- `time` (Default): `(filetime_utc or mtime, save_number)` — neueste zuerst
- `level`: `(-player_level, filetime_utc)`
- `playtime`: `(-playtime.total_minutes, filetime_utc)`
- `name`: `(virtual_name.lower(),)`

Fehlende Werte sortieren immer ans Ende, nie als `0` — sonst erscheint ein unbekannter Level als niedrigster.

---

## 5. Index, Duplikate, Historie (P3)

### 5.1 Dateiformat

`save_index.json`, UTF-8, `indent=2`, `sort_keys=True`:

```json
{
  "version": 1,
  "generated": "2026-11-08T14:52:11Z",
  "root": "/pfad/zum/save-ordner",
  "entries": [
    {
      "path": "/…/Save47_A7460D2FM436F6C65_….sfs",
      "sha256": "bbfaba67…",
      "size": 8188176,
      "mtime": 1791383724.0,
      "identity": { "player_name": "Cole", "player_level": 24, "…": "…" },
      "integrity_total": "PASS",
      "integrity_checks": { "I-01": "PASS", "I-04": "PASS", "I-09": "UNKNOWN" },
      "quarantined": false,
      "first_seen": "2026-11-08T14:52:11Z",
      "last_checked": "2026-11-08T14:52:11Z"
    }
  ]
}
```

Kein SQLite. Begründung: 10 Saves, Vollscan 0,13 s über Chunk 0 — eine Datenbank wäre eine Architektur ohne belegten Bedarf.

### 5.2 Scan

```python
def scan(root: Path, *, cache: SaveIndex | None = None,
         integrity: bool = True) -> SaveIndex
```
- **Kurzpfad** (Standard): nur Chunk 0 dekomprimieren → Header + Plugin-Liste (gemessen 1,27 ms). Reicht für Identifikation, Gruppierung, Sortierung.
- **Vollpfad** (`integrity=True` oder `--full`): vollständige Dekompression (76 ms) für I-04/I-06 und Body-Regionen.
- Inkrementell: Eintrag wird nur neu bewertet, wenn sich `(size, mtime)` geändert hat; ansonsten Status aus dem Cache übernommen, `last_checked` bleibt.

### 5.3 Duplikaterkennung

Drei Stufen, aufsteigend teuer, jede mit eigener Aussage:

| Stufe | Kriterium | Aussage |
|---|---|---|
| D1 | gleicher `sha256` der Datei | **exaktes Duplikat** (byte-identisch) |
| D2 | gleicher `sha256` des Payloads, verschiedene Datei | gleicher Spielinhalt, andere Kompression/Verpackung |
| D3 | gleicher `character_key` **und** `filetime` **und** `player_level` **und** `save_number` | **wahrscheinlich gleicher Spielstand**, verschiedene Datei |

Wichtig (gemessen): Dateigröße **allein** ist kein Kriterium — zwei verschiedene Saves haben exakt 23.399.695 Payload-Bytes. Byte-Ratio ist ebenfalls **kein** Kriterium: echte, verwandte Saves unterscheiden sich in 78,7–84,1 % der Bytes. D3 ist deshalb ein *struktureller* Vergleich, kein Ähnlichkeitsvergleich.

### 5.4 Prüfhistorie

```python
@dataclass(frozen=True)
class HistoryEntry:
    path: str; sha256: str; checked_at: str
    integrity_total: str; checks: dict
```
Persistenz: `save_history.jsonl`, append-only, eine Zeile je Prüfung. Auswertung: pro `character_key` eine chronologische Kette; daraus
- Level-Verlauf, Spielzeit-Verlauf,
- Statuswechsel (`PASS` → `FAILED`),
- Plugin-Zahl-Änderungen,
- Rückwärtsbewegungen (FileTime/Level/Spielzeit) → **Auffälligkeit**.

Rotationsregel: maximal 5.000 Zeilen, dann `save_history.1.jsonl` (eine Sicherung, keine Löschkette).

---

## 6. Vergleich (P4)

```python
def compare(left_path, right_path, *, known_formids=None) -> ComparisonReport
```

### 6.1 Ebene 1 — Identität
Feldweise über `compare_metadata` (`savegame_differential.py:93`). Verglichen: `character_key`, `player_name`, `player_level`, `save_version`, `save_version_2`, `engine_version`, `current_game_version`, `created_game_version`.
Urteil: `SAME_CHARACTER`, wenn `character_key` gleich (oder beide `None` und `player_name` gleich); sonst `DIFFERENT_CHARACTER`; bei fehlenden Schlüsseln `UNKNOWN`.

### 6.2 Ebene 2 — Installation
```python
def plugin_delta(a: PluginInfo, b: PluginInfo) -> PluginDelta
```
- `added` = Namen in B, nicht in A (Reihenfolge B)
- `removed` = Namen in A, nicht in B (Reihenfolge A)
- `reordered` = in beiden vorhanden, Index verschieden —
  **nur berechnet, wenn `added` und `removed` leer sind**; sonst ist eine Reihenfolge-Aussage bedeutungslos und `reordered` bleibt leer.
- `comparable = (a.decode_state == VALIDATED == b.decode_state)`
- Zusätzlich: `creation_id`-Vergleich nur, wenn dekodiert (heute nie → Feld weglassen, nicht `None` ausgeben)

### 6.3 Ebene 3 — Inhalt
Regionen werden **getrennt** ausgewertet:

| Region | Grenzen | Auswertung | `interpretable` |
|---|---|---|---|
| `header_plugin` | `0 … max(plugin_end_a, plugin_end_b)` | **feldweise** über `compare_metadata`; Byte-Diff nur als Indikator. Ein Byte-Unterschied ohne Feld-Unterschied wird als `layout_shift` markiert (belegt: 89,27 % „Unterschied" bei 2-Byte-Verschiebung) | eingeschränkt |
| `body` | `max(plugin_end) … min(len_a, len_b)` | nur Zählung (`differing_bytes`, `ratio`) ohne Deutung | **nein** |

`anomalies` (verdächtig) — ausschließlich aus belegbaren Kriterien:
1. `character_key` gleich, aber `filetime` rückwärts.
2. `player_level` kleiner bei neuerem `filetime`.
3. Plugin in A, in B entfernt.
4. `save_version`/`engine_version` verschieden, aber `character_key` gleich.
5. Header-Feld unterschiedlich **ohne** Änderung der zugehörigen Metadaten (Layout-Verschiebung → als Artefakt kennzeichnen, **nicht** als Anomalie zählen).

Kein Kriterium verwendet Byte-Ratio im Body. Die heutige Regel („ratio > 25 % ⇒ UNSUITABLE") entfällt: sie trifft auf **jedes** echte Save-Paar zu (gemessen 83 %) und trägt damit keine Information.

---

## 7. Organisation (P5)

### 7.1 Backup

```python
def create_backup(entry: IndexEntry, target_root: Path) -> BackupResult
```
Ablauf, unveränderlich in dieser Reihenfolge:
1. Zielpfad `<target_root>/<group_key>/<YYYY-MM-DD>/<original_name>` bestimmen und **anzeigen**.
2. Existiert das Ziel: Suffix `_2`, `_3`, … — nie überschreiben.
3. Kopie erzeugen (`shutil.copy2`), Quelle ausschließlich lesend geöffnet.
4. `sha256(Kopie) == entry.sha256` prüfen. Bei Abweichung: Kopie löschen, `BackupResult(ok=False, reason="hash_mismatch")`.
5. Manifest `backup_manifest.jsonl` ergänzen: Zeit, Quelle, Ziel, Hash, Größe, `virtual_name`.

`BackupResult(ok: bool, target: str | None, sha256: str | None, reason: str)`.

Ein Backup gilt nur als erfolgreich, wenn Schritt 4 bestanden ist. Ein „Kopie existiert"-Status ohne Hash-Vergleich ist unzulässig.

### 7.2 Quarantäne

```python
def mark_quarantine(index: SaveIndex, path: str, on: bool) -> SaveIndex
```
Setzt ausschließlich `quarantined` im Index. **Keine Dateioperation.** Anzeige in UI/CLI: eigener Abschnitt „Auffällig", nicht gemischt mit intakten Saves. Aufhebung nur explizit pro Eintrag.

### 7.3 Export (Reorganisation ohne Eingriff)

```python
def export_selection(entries: list[IndexEntry], target: Path,
                     scheme: str = "virtual") -> ExportResult
```
- `scheme="virtual"`: Zielname = `virtual_name + ".sfs"`
- `scheme="grouped"`: `target/<group_key>/<virtual_name>.sfs`
- Immer **Kopie**, Quelle unverändert; Hash-Gegenprüfung wie 7.1; Kollision → Suffix, nie überschreiben.
- `dry_run=True` ist der Standard in der CLI; ohne `--commit` wird nur gedruckt, was passieren würde.

---

## 8. CLI-Spezifikation

Konventionen des Bestands beibehalten: `emit_lines`, `emit_json`, ASCII-only-Ausgabe (Windows-Konsole, `sfda_cli.py:105`), `EXIT_OK=0`, `EXIT_ERROR=1`.

| Kommando | Argumente | Ausgabe (Text) | Exit |
|---|---|---|---|
| `sfda save verify <save.sfs>` | `--json`, `--full` | Tabelle `ID  STATUS  Detail` + Gesamtstatus + Disclaimer | `FAILED` → 1, sonst 0 |
| `sfda save list <dir>` | `--json`, `--sort time\|level\|playtime\|name`, `--group`, `--full` | Gruppe, virtueller Name, Level, Datum, Plugins, Status | 0 |
| `sfda save scan <dir>` | `--out index.json`, `--full`, `--quiet` | Anzahl Saves, Gruppen, Dauer | 0 |
| `sfda save compare <a> <b>` | `--json`, `--markdown PATH` | Identität, Plugin-Delta, Regionen, Auffälligkeiten | 0 (Bericht), 1 bei `DIFFERENT_CHARACTER` |
| `sfda save dupes <dir>` | `--json` | D1/D2/D3-Gruppen | 0 |
| `sfda save backup <save.sfs> --to <dir>` | `--commit` (sonst dry-run) | Zielpfad, Hash-Nachweis | 0 / 1 bei Hash-Mismatch |
| `sfda save export <dir> --out <dir>` | `--scheme`, `--commit` | Liste Quellen → Ziele | 0 |

Beispiel `save verify`:
```
$ sfda save verify Save47_....sfs
I-01  PASS     Container-Magic BCPS
I-02  PASS     Kompression ZIP
I-03  PASS     Chunk-Tabelle endet bei 432, compressed_offset 432
I-04  PASS     Padding-Summe 8187744 == Dateirest 8187744
I-05  PASS     alle 90 Chunks dekomprimierbar
I-06  PASS     Nutzlaenge 23533511 == Sollwert 23533511
I-07  PASS     90 Chunks == ceil(23533511/262144)
I-08  PASS     Header-Feldgrenzen eingehalten
I-09  UNKNOWN  header_size=125, Semantik nicht belegt
I-10  PASS     Plugin-Block 168+5077 innerhalb 23533511
I-11  PASS     Plugin-Liste VALIDATED (25 normal, 50 light)
I-14  NOT_CHECKED  Einzeldatei ohne Folgenvergleich

TOTAL: UNKNOWN
Hinweis: Diese Pruefung belegt strukturelle Integritaet. Sie belegt NICHT,
dass Starfield den Spielstand laden kann. Objekt-, FormID- und Skriptebene
werden nicht geprueft.
```
Bewusste Konsequenz: `I-09` ist dauerhaft `UNKNOWN`, deshalb ist `TOTAL` eines fehlerfreien Saves `UNKNOWN`, nicht `PASS`. Das ist korrekt und muss so bleiben, bis die `header_size`-Semantik belegt ist — ein `PASS` auf einer unbekannten Semantik wäre ein erfundener Befund. Wer eine positivere Anzeige will, muss zuerst V5 (Audit 4) klären.

---

## 9. UI-Spezifikation

### 9.1 Integrationspunkte (unverändert im Bestand)

- `ssb_ui/app.py:75–80` — `PAGE_*`-Konstanten. Neu: `PAGE_SAVES = 6` (5 ist belegt, 1–3 reserviert).
- `ssb_ui/app.py:260` — `build_pages()` ist die **einzige** Quelle für Sidebar/Stack. Neue Seite dort eintragen.
- `ssb_ui/pages/savegame_page.py:174` — `QTabWidget`; neuer Tab `Integrity` nach `Header Dump`.
- Bestehende Seiten (`Savegame Analyzer`, `Hex Viewer`, `Event Log`) bleiben funktional unverändert; `current_buffer()` bleibt die Pufferquelle der Hex-Ansicht.

### 9.2 Neue Seite „Save Overview"

| Element | Inhalt | Quelle |
|---|---|---|
| Toolbar | `Scan Folder…`, `Refresh`, `Verify all`, Sortier-Dropdown, `Group by character` (Checkbox) | `scan()` |
| Tabelle | virtueller Name · Charakter · Level · Spielzeit · Datum · Plugins · Status · Auffällig | `IndexEntry` |
| Statusspalte | Farbcode: PASS grün, WARNING amber, FAILED pink, UNKNOWN grau, NOT_CHECKED grau | `integrity_total` |
| Filterzeile | „nur auffällige" (Checkbox) | `quarantined`/`FAILED` |
| Detailbereich | Integritäts-Tabelle des gewählten Saves + Disclaimer | `IntegrityReport` |
| Aktionen | `Open in Analyzer`, `Compare with…`, `Backup…` (dry-run-Dialog mit Zielpfad) | bestehende `SavegamePage.load_file()` |

Doppelklick → `SavegamePage.load_file(path, show_dialog=False)` über den bestehenden Seitenwechsel; das ist der einzige Eingriff in die Savegame-Seite und additiv.

### 9.3 Integritäts-Tab in `SavegamePage`

Tabelle `ID | Status | Detail`, Sortierung nach `SEVERITY` absteigend (FAILED zuerst, dann UNKNOWN, NOT_CHECKED, WARNING, PASS). Direkt unter dem Status-Label, damit ein `FAILED` nicht in einem verborgenen Tab verschwindet. Badge im Seitentitel zeigt `TOTAL`.

---

## 10. Provider-Erweiterungen

Zwei additive Methoden, kein Verhalten des Bestehenden ändert sich:

```python
def read_chunk_table(self, sfs_path: str) -> list[int]:
    """Echte Chunk-Größentabelle aus dem Dateikopf.

    Heute wird die Tabelle in decompress() lokal gelesen und verworfen;
    SfsContainer.chunks bleibt immer leer. Diese Methode materialisiert sie.
    """

def decompress(self, sfs_path: str, *, verify: bool = True) -> bytes:
    """verify=True vergleicht das Ergebnis mit uncompressed_size und wirft
    ValueError bei Abweichung (Fall E/F aus dem Audit). Default True, weil
    stiller Datenverlust der gefaehrlichere Zustand ist."""
```

Wichtig: `verify=True` als Default ändert das Verhalten von `decompress()` für heute stille Fehlerfälle von „liefert Daten" zu „wirft" — das ist beabsichtigt und der Kern von P1b. Die bestehenden Tests prüfen nur intakte und klar defekte Container und bleiben grün (verifiziert: 77 passed).

`PluginEntry.creation_name`/`creation_id`: bleiben unverändert `None`, aber die Feld-Dokumentation wird auf `# NOT DECODED (see audit V9)` gesetzt. Kein Entfernen — das wäre eine API-Änderung ohne Not.

---

## 11. Testfälle

### 11.1 Synthetisch (P1)

| # | Fixture | Erwartung |
|---|---|---|
| T01 | intakter Container | alle Checks `PASS` außer I-09 `UNKNOWN`, I-14 `NOT_CHECKED` |
| T02 | letzte 1000 B entfernt | I-04 `FAILED`, I-05 `FAILED`, Rest `NOT_CHECKED` |
| T03 | Hälfte entfernt | I-04 `FAILED`, I-05 `FAILED` |
| T04 | Bitflip im Chunk | I-05 `FAILED` |
| T05 | `uncompressed_size` +1 | **I-06 `FAILED`** (heute still) |
| T06 | `chunk_size_pre` ×2 | **I-06 `FAILED`** (heute still, 50 % Verlust) |
| T07 | Chunk-Größe +4 | I-04 `PASS` mit Notiz „4 Zusatzbytes, Nutzdaten vollständig" |
| T08 | Magic `XXXX` | I-01 `FAILED`, alles weitere `NOT_CHECKED` |
| T09 | nur 512 B | I-01 `PASS`, I-04 `FAILED` |
| T10 | `padding_size = 0` | I-03 `FAILED` oder I-05 `FAILED` (nicht `PASS`) |
| T11 | `compressed_offset` verschoben | I-03 `FAILED` |
| T12 | `plugin_info_offset` hinter Dateiende | I-10 `FAILED`, I-11 `WARNING` |
| T13 | Plugin-Zähler falsch | I-11 `WARNING` (`UNVERIFIED`) |
| T14 | `compressed_offset` mit Alignment-Lücke (12 B, wie Autosave2) | I-03 `WARNING`, nicht `FAILED` |

### 11.2 Real-Save (Pflicht)

| # | Fixture | Erwartung |
|---|---|---|
| T20 | 6 echte Saves aus `SAVE_PROBES` | `TOTAL` je Save stabil; I-04/I-06 `PASS` |
| T21 | `feature`-Golden | 25 normal / 50 light / 0 medium, `uncompressed_size` exakt |
| T22 | Zeitstempel | `filetime` == Dateiname-Timestamp in allen 6 |
| T23 | Fehlen der Saves | **`pytest.fail`**, nicht `skip` |
| T24 | 100 Saves gescannt | Laufzeit < 5 s über Chunk 0 |

### 11.3 Identifikation

| # | Fall | Erwartung |
|---|---|---|
| T30 | `Cole`-Dateiname | `character_hex_name == "Cole"`, `character_key == "A7460D2F"` |
| T31 | `DANTE`-Dateiname | `character_hex_name == "DANTE"` |
| T32 | `ssbm_*`-Dateiname | `recognized == False`, `virtual_name` aus Header, Warnung `filename_unrecognized` |
| T33 | `playtime` kombiniert | `(2, 10, 34)`, `total_minutes == 3514` |
| T34 | `playtime` unparsebar | Felder `None`, Warnung, **kein** `0` |
| T35 | Level fehlt | Baustein weggelassen, nicht `L0` |
| T36 | zwei Saves, gleicher virtueller Name | Suffix `_2` + Warnung |
| T37 | Kollisionsfreiheit | zwei Läufe erzeugen identische Namen (deterministisch) |

### 11.4 Vergleich

| # | Fall | Erwartung |
|---|---|---|
| T40 | Save47 vs Save46 | `SAME_CHARACTER`, `plugins.equal == True`, `anomalies == ()` |
| T41 | Save47 vs Autosave1 (Header verschoben) | Header-Region als `layout_shift`, **keine** Anomalie |
| T42 | Plugin entfernt | `removed == ["…"]`, Anomalie 3 |
| T43 | FileTime rückwärts | Anomalie 1 |
| T44 | verschiedene Charaktere | `DIFFERENT_CHARACTER`, Exit 1 |
| T45 | ein `decode_state == UNVERIFIED` | `PluginDelta.comparable == False`, keine `reordered`-Aussage |
| T46 | Body-Vergleich | `ratio` berichtet, `interpretable == False`, **keine** Anomalie aus Ratio |

### 11.5 Organisation

| # | Fall | Erwartung |
|---|---|---|
| T50 | Backup | `sha256` Ziel == Quelle, Manifest-Eintrag |
| T51 | Backup, Ziel existiert | Suffix `_2`, Original unverändert |
| T52 | Hash-Mismatch simuliert | `ok=False`, Kopie entfernt |
| T53 | Export ohne `--commit` | nichts geschrieben, Ausgabe zeigt Plan |
| T54 | Quarantäne setzen | nur Index geändert, Datei-`mtime` unverändert (Test misst sie) |
| T55 | Original-Save nach vollem Lauf | `sha256` unverändert (Regressionstest für alle P-Pakete) |

---

## 12. Abnahmekriterien und Degradation

### 12.1 Definition of Done je Paket

**P1:** T01–T14 grün; T20–T24 grün; `sfda save verify` Exit-Code korrekt; kein `skip` bei fehlenden Real-Saves; Testlauf < 5 s; `disclaimer` in jedem Report.
**P2:** T30–T37 grün; virtuelle Namen deterministisch; kein Dateizugriff im Schreibmodus (Test prüft `open`-Aufrufe).
**P3:** T50–T55 grün; Vollscan 100 Saves < 5 s; Index aus Saves vollständig rekonstruierbar.
**P4:** T40–T46 grün; `anomalies` ausschließlich aus den fünf belegbaren Kriterien.
**P5:** T50–T55 grün; jede Schreiboperation mit Hash-Nachweis; dry-run Standard.

### 12.2 Degradation bei unbekannter Save-Version

Wenn `save_version != 153` oder `engine_version != 27`:
- I-03, I-04, I-06, I-07 → `UNKNOWN` mit `detail = "nicht belegt fuer save_version=<n>"`
- I-09 bleibt `UNKNOWN`
- Identifikation läuft weiter (Header-Felder sind versionsunabhängig gelesen), aber mit Warnung `unverified_save_version`
- Vergleich: `identity_verdict = UNKNOWN`, Regionen nur gezählt

Damit kann die Anwendung neue Save-Versionen **nicht falsch bewerten**, sondern nur ehrlich als unbekannt melden.

### 12.3 Verbotene Muster (Review-Checkliste)

- Ein `PASS` auf einer Prüfung ohne Falsifikationsfall.
- `TOTAL = PASS`, solange I-09 `UNKNOWN` ist.
- Ein Objekt-, Schiffs- oder Außenposten-Feld im Datenmodell, bevor ein Body-Parser existiert.
- Eine Byte-Ratio im Body als Anomaliekriterium.
- Ein Backup-Status ohne Hash-Vergleich.
- Ein Schreibzugriff auf einen Pfad innerhalb des Starfield-Save-Verzeichnisses.
- `pytest.skip` als Ersatz für fehlende Real-Save-Fixtures.

---

## Nachtrag 08.11.2026 — Ergänzungen aus der externen Tooling-Recherche

Quelle: `EXTERNAL_SAVEGAME_TOOLING_AUDIT.md`. Messungen: 6/6 echte Saves, Prüfskripte `~/ssb_save_audit/verify_*.py`.

### N1 — Plugin-Block: Medium-Plugins sind Pflichtbestandteil

`I-11` wird verschärft. Die Selbstvalidierung gilt erst als bestanden, wenn **drei** Ketten vollständig gelesen sind und der Block danach **exakt** bei `plugin_info_offset + plugin_info_size` endet:

```
normal  (u8-Zähler bei offset+2, Records ab offset+3)
light   (u16-Zähler, danach Records)
medium  (u32-Zähler, danach Records)      ← heute vom Parser verschluckt
Ende == plugin_info_offset + plugin_info_size    (Delta 0, gemessen 6/6)
```

Ist `Delta != 0`, lautet der Status `WARNING` mit dem Delta als Evidenz — nicht `PASS`. Golden Values (Save-Version 153): **25 normal / 50 light / 5 medium**, Blockende 0x147B bzw. 0x147D.

### N2 — Plugin-Metadaten: neues Datenfeld, optional dekodiert

Record-Format (saveVersion ≥ 140):

```
u16 len + pluginName
u8  extraInfo                  # 0 = Game-Plugin, 1 = Creation/Mod-Plugin
if extraInfo == 1:
    u16 len + creationName
    u16 len + creationId
    u16 len + flags            # in der Praxis ASCII-Version, z. B. "1753987979.2.3"
    u8  achievementFriendly
```

`PluginEntry.creation_name` / `.creation_id` werden damit befüllbar (V9 geschlossen). Zwei Einschränkungen sind verbindlich zu dokumentieren:

- 81 % der Mod-Plugins tragen **keine** Creation-Metadaten (Save47: 65 von 80 mit leerem Namen/ID). Ein leeres Feld ist normal, kein Fehler.
- Bei fehlenden Metadaten enthält `flags` den Engine-Platzhalter `18446744073709551615.undefined`. Das darf **nicht** als ungültige Version gemeldet werden — Status `WARNING` mit Hinweis „keine Creation-Version hinterlegt" wäre hier falsch; korrekt ist, den Platzhalter als „nicht vorhanden" zu normalisieren.

Der `medium`-Block wird mit demselben Record-Format gelesen.

### N3 — Body-Kopf als optionale Leseoperation (P2-Erweiterung, read-only)

Erschlossen und in 6/6 Saves verifiziert:

```
nach plugin_info_end:
  u16  unknown0                     # in allen Saves 1
  uint pointer[12]                  # pointer[2] zeigt auf NEW_BLOCK2
  byte padding[52]
  NEW_BLOCK2: uint pointer0, uint stringsArrayOffset, uint unknown0
  an stringsArrayOffset: u16 count, dann count × (u16 len + utf8 text)
```

Gemessen: count 1.709–1.735, 99,6 % druckbar, 0 Duplikate, vollständig parsbar.

Freigabe als **eigene, rein lesende Funktion** `read_string_pool()`:

- Rückgabe: Liste der Strings + `count` + belegte Endposition; **keine** Zuordnung zu Records oder FormIDs.
- Die Funktion liefert keine Objekt-Identität. Sie darf nicht als „Inventar" oder „Schiffsdaten" bezeichnet werden — Inhalte sind ein String-Pool, dessen Semantik pro Eintrag unbelegt ist.
- Kein Schreiben, kein Rekomprimieren, keine Änderung an bestehenden Funktionen.
- Gating: nur bei erkanntem `unknown0 == 1` und `pointer[2]` innerhalb des Payloads; sonst `UNKNOWN` mit Evidenz, kein Rätselraten.

### N4 — Externe Doku ist versionsgebunden

Alle übernommenen Strukturen stammen aus der Formatdokumentation des offiziellen Nexus-Tools, das **Save-Version 140** unterstützt. Unsere Saves sind 153. Regel für jede künftige Übernahme: gegen die eigene Messbasis prüfen und das Ergebnis festschreiben; nie ungeprüft übernehmen. Zusätzlich gilt: das 010-Editor-Template hat `padding`/`unknown` in umgekehrter Reihenfolge gegenüber dem produktiven C#-Code — Referenz ist der produktive Code, nicht das Template.

### N5 — Was unverändert bleibt

Kein Schreibpfad, keine Rekompression, keine Reparatur, keine Objektprüfung. Der Write-Proof-of-Concept des Nexus-Tools (v1.1.0) belegt technische Machbarkeit, **nicht** Sicherheit — er ändert keine Freigabe in diesem Dokument.

---

## Nachtrag 08.11.2026 (2) — Umsetzungsstand

Die Pakete P1 (Integrität), die Medium-Kette, die Plugin-Metadaten und der String-Pool sind in Version 1.5.3 umgesetzt. Abweichungen von dieser Spezifikation, die beim Bauen nötig waren:

1. **`total` und `total_with_gaps` sind getrennt.** Die Spezifikation verlangte einen Gesamtstatus als schlechtestes Einzelergebnis. In der Praxis hätte das jeden intakten Save als `NOT_CHECKED` ausgewiesen, weil I-13 dauerhaft offen ist. Jetzt gilt: `total` = schlechtestes *bewertetes* Ergebnis (Integritätsurteil), `total_with_gaps` = strengste Sicht inklusive Lücken, `gaps` listet die nicht bewertbaren Prüfungen. Damit bleibt die Aussage ehrlich, ohne das Urteil zu verwässern.
2. **I-02 liest das Kompressionsfeld direkt** aus der Datei statt über den Container-Ladepfad. Grund: bei unbekanntem Verfahren wirft `read_container` bereits, und `NOT_CHECKED` wäre die falsche Antwort — die Ursache ist bekannt.
3. **I-03 muss Ungleichheit zulassen.** Die Bedingung ist `table_end ≤ compressed_offset` plus Ausrichtung, nicht Gleichheit. Ein realer Save (Autosave2) hat 12 Füllbytes; Gleichheit hätte einen Fehlalarm erzeugt.
4. **`decompress(verify=True)` ist Default.** Das ändert das Verhalten bei den Fällen E und F von „liefert Daten" zu „wirft" — beabsichtigt und der Kern der Korrektur.
5. **`save info --json` behält das 1.0.0-Schema** (Zahlen je Kette) und erweitert additiv. Die vollständige Eintragsliste steht unter `entries`, damit bestehende Aufrufer nicht brechen.
6. **`read_string_pool()` gibt einen Status zurück** (`OK`/`UNKNOWN`/`UNREADABLE`) statt nur einer Liste, plus `pointer_table`, `unverified_pointers` und `note` — die harte Grenze „keine Objektidentität" steht damit im Rückgabewert selbst.

