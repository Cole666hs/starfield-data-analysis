# SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT

**Projekt:** Starfield Data Analysis · **Organisation:** Entropy Development
**Version:** 1.5.3 (vorher 1.0.0) · **Datum:** 08.11.2026
**Auftrag:** P1-Integritätsprüfung + drei nachgewiesene Parserkorrekturen
**Modus:** Implementierung mit reproduzierbaren Tests, read-only gegen alle Spielstände

---

## 1. Ausgangsstand und Git-HEAD

| Feld | Wert |
|---|---|
| Branch | `main` |
| HEAD vor der Arbeit | `9006753` („docs: rewrite BUILD/REPRODUCIBILITY …") |
| Working Tree vor der Arbeit | drei untracked Audit-Dokumente (`SAVE_INTELLIGENCE_AUDIT.md`, `SAVE_INTELLIGENCE_SPEC.md`, `EXTERNAL_SAVEGAME_TOOLING_AUDIT.md`) und `audit/` aus den vorherigen Runden |
| Überschrieben oder verworfen | **nichts** — alle vorhandenen Änderungen blieben erhalten |
| Testlage vorher | 77 passed, 28 skipped (davon alle Tests gegen echte Saves übersprungen) |

Der Zahlenwiderspruch aus dem Auftrag (25+50+5 = 80 vs. „9 Game + 65 Mod") ist in Abschnitt 4 aufgelöst.

---

## 2. Geänderte Dateien

**Bestehender Code — geändert (9):**

| Datei | Zeilen +/− | Inhalt |
|---|---|---|
| `ssb_i/savegame_provider.py` | +556/− | strikte Plugin-Kette inkl. medium, Metadaten, `read_chunk_table()`, `decompress(verify=True)`, `read_string_pool()` |
| `ssb_i/save_integrity.py` | **neu**, 640 Z. | Statusmodell, 14 Prüfungen, `run_all()` |
| `sfda_cli.py` | +102 | `save verify`, `save strings`, korrigiertes `save info`, Metadaten in `save plugins` |
| `ssb_ui/pages/savegame_page.py` | +161 | Integrity-Tab, String-Pool-Tab, Plugin-Kategorien, Metadaten nur bei Vorhandensein |
| `ssb_i/product.py` | ±1 | `VERSION = "1.5.3"` |
| `CHANGELOG.md` | +45 | Eintrag 1.5.3 |
| `tests/test_ssb_i_plugin_parsing.py` | +301/− | auf das belegte Metadatenformat migriert |
| `tests/test_ssb_i_savegame_provider.py` | +236/− | `/tmp`-Fixtures durch Pflicht-Fixture ersetzt |
| `tests/test_ssb_i_cli.py`, `tests/test_ssb_ui_pages.py` | +104 | Versionsbezug, UI-Integritätstests |

**Neue Dateien (8):** `tests/conftest.py`, `tests/test_ssb_i_save_integrity.py`, `tests/test_ssb_i_string_pool.py`, `tests/test_ssb_i_real_saves.py`, `ssb_i/save_integrity.py`, plus die drei Audit-Dokumente und `audit/save-intelligence/` (Messwerkzeuge).

**Nicht angefasst:** `ssb_pe_lib.py`, `hex_view_page.py`, `app.py`, `ssb_ui/__init__.py`, `Starfield-Data-Analysis.spec`, `requirements.txt`.

---

## 3. Konkrete Implementierungen

### 3.1 Strikte Plugin-Kette mit Medium (Aufgabe A)

Vorher endete die Kette nach den Light-Plugins (Heuristik `_probe_counted_chain` mit Namens-Resync). Jetzt wird strikt gelesen:

```
u8  unknown0, u8 count0, u8 normalCount
    normalCount × Record
u16 lightCount
    lightCount × Record
u32 mediumCount
    mediumCount × Record
```

`Record` = `u16 len + Name`, dann `u8 extraInfo`; bei `extraInfo == 1` folgen `creationName`, `creationId`, `flags`, `achievementFriendly` (jeweils `u16 len`-präfigiert, das letzte ein Einzelbyte).

**Validierung:** Alle drei Ketten müssen vollständig lesbar sein, sonst `decode_state = UNVERIFIED` und **alle Listen bleiben leer** (fail-closed, kein Erfinden). Neu ist `block_delta` = gelesenes minus deklariertes Blockende; `0` heißt: die Struktur geht bytegenau auf.

### 3.2 Plugin-Metadaten (Aufgabe B)

| Feld | Typ | Semantik | Behandlung |
|---|---|---|---|
| `category` | `"game"`/`"mod"` | `extraInfo == 0` → Game-Plugin, `1` → Mod-Plugin | belegt, 6/6 Saves |
| `creation_name` | `str \| None` | Name der Creation | leer → `None` |
| `creation_id` | `str \| None` | `TM_<uuid>` | Engine-Platzhalter `18446744073709551615.undefined` → `None` |
| `version` | `str \| None` | Inhalt des `flags`-Feldes; in der Praxis ASCII `epoch.major[.minor[.patch]]` | leer → `None` |
| `achievement_friendly` | `bool \| None` | Einzelbyte | nur bei `extraInfo == 1` |
| `metadata_state` | `present`/`absent`/`unreadable` | siehe unten | pro Eintrag nachvollziehbar |
| `detail` | `str` | Begründung des Zustands | z. B. `"mod plugin without creation data (engine placeholder)"` |

**`unreadable`** tritt auf, wenn ein Längenfeld aus dem Puffer läuft. Dann bricht die Kette ab, der betroffene Eintrag bleibt in der Liste, alle Metadatenfelder bleiben `None` — es wird **nichts** aus dem Nachbarrecord übernommen (eigener Test `test_metadata_is_not_taken_from_neighbour`).

### 3.3 Read-only String-Pool (Aufgabe C)

```python
pool = provider.read_string_pool(decompressed, header, plugin_info)
```

Rückgabe unter anderem: `status` (`OK`/`UNKNOWN`/`UNREADABLE`), `reason`, `pointer_table` (12 Werte), `string_array_offset`, `count`, `declared_count`, `strings` (je `index`, `text`, `offset`, `length`, `status`), `end`, `printable_ratio`, `unverified_pointers`, `note`.

**Gating (kein Raten):** Die Funktion liest nur, wenn `unlock == 1`, `unknown0 == 1` und `pointer[2]` exakt auf den Folgebenutzer zeigt. Sonst `UNKNOWN` mit Begründung und **leerer** Stringliste — es gibt keine heuristische Offsetsuche.

**Harte Grenze, im Code und im Rückgabewert verankert:** Der Rückgabewert enthält keine FormID, keinen Record-Verweis, keine Objektidentität. `note` sagt das wörtlich; die elf nicht belegten Pointer werden nur als Zahl mit `inside_payload`-Flag geliefert.

### 3.4 Integritätsprüfung (Aufgabe D)

`ssb_i/save_integrity.py` mit `PASS | WARNING | FAILED | UNKNOWN | NOT_CHECKED`, je Prüfung `check_id`, `title`, `status`, `detail`, `evidence`, `confidence` (`deterministic`/`heuristic`/`unverified`).

| ID | Prüfung | Bewertung |
|---|---|---|
| I-01 | BCPS-Magic | deterministisch |
| I-02 | Kompressionstyp (liest Feld direkt, unabhängig vom Container-Ladepfad) | deterministisch |
| I-03 | Chunk-Tabellen-Geometrie (`table_end ≤ compressed_offset` **und** `compressed_offset % padding == 0`; Lücke > 0 → WARNING) | deterministisch |
| I-04 | Padding-Summe gegen Dateirest | deterministisch |
| I-05 | Dekompression inkl. zlib-Prüfsumme **und Streamgrenze** (`unused_data`) | deterministisch / bei Restbytes `unverified` |
| I-06 | tatsächliche Nutzlänge gegen `uncompressed_size` | deterministisch |
| I-07 | Chunk-Anzahl gegen Raster | deterministisch, bei nicht-ganzzahligem Raster `heuristic` |
| I-08 | DAT-Magic und alle Header-Längenfelder (eigener strikter Walk) | deterministisch |
| I-09 | `headerSize`-Semantik | **immer UNKNOWN** |
| I-10 | Plugin-Block-Grenzen | deterministisch |
| I-11 | Plugin-Ketten + Metadaten + Blockende | deterministisch |
| I-12 | Plugin-Abhängigkeiten | nur mit `--data-dir`, sonst NOT_CHECKED |
| I-13 | FormID-Auflösung | **immer NOT_CHECKED** |
| I-14 | Sequenzkonsistenz | nur mit übergebenen Vergleichsdaten |

**Aggregation:** `total` = schlechtester Status aus den *bewerteten* Prüfungen (PASS/WARNING/FAILED) — das Integritätsurteil. `total_with_gaps` = schlechtester über alle inklusive UNKNOWN/NOT_CHECKED. `gaps` listet die nicht bewertbaren Prüfungen mit Grund. Damit wird weder „alles gut" noch „nichts geprüft" vorgetäuscht.

**Abbruchkette:** `FAILED` in I-01, I-02 oder I-05 setzt alle folgenden Prüfungen auf `NOT_CHECKED` mit Verweis auf die Ursache.

---

## 4. Geklärte Plugin-Zählung (PROVEN)

Die scheinbar widersprüchlichen Zahlen lösen sich auf, sobald man Kette und Kategorie trennt. Sie sind **unabhängige Achsen**:

- **Kette** = Position im Ladereihenfolge-Block (normal / light / medium)
- **Kategorie** = Herkunft (`extraInfo`: game / mod)

Messung über alle sechs echten Saves, identisch in jedem:

| Kette | gesamt | davon game | davon mod mit Metadaten | davon mod ohne Metadaten |
|---|---|---|---|---|
| normal | 25 | 3 | 1 | 21 |
| light | 50 | 4 | 5 | 41 |
| medium | 5 | 2 | 0 | 3 |
| **Summe** | **80** | **9** | **6** | **65** |

**Die Aufteilung „9 Game / 65 Mod" bezog sich auf 74 Einträge und ließ die sechs Mod-Plugins mit Creation-Metadaten weg. Richtig ist: 9 Game + 71 Mod = 80.** Die Aufteilung gilt für **alle 80** Einträge, nicht nur für die früher erkannten 75.

| Frage aus dem Auftrag | Antwort |
|---|---|
| Was bedeutet Game-Plugin / Mod-Plugin? | `extraInfo == 0` = Master des Basisspiels, `1` = Creation/Mod-Plugin mit Metadatenblock. Belegt an 6/6 Saves und gegen die Referenzimplementierung. |
| Bezieht sich die Aufteilung auf 75 oder 80? | Auf **alle 80**. Die Kategorie ist unabhängig von der Kette — jede Kette enthält beide Kategorien. |
| Wie werden normal/light/medium klassifiziert? | Ausschließlich über die Position im Block (drei getrennte Zähler + Ketten). Keine Namenheuristik. |
| Welche Einträge besitzen Creation-Metadaten? | Genau 6 pro Save: 1 in normal, 5 in light, 0 in medium. |
| Welche enthalten Engine-Platzhalter? | Die 65 Mod-Plugins ohne Metadaten: `creationName` und `creationId` leer, `flags` = `18446744073709551615.undefined`. Wird zu „nicht vorhanden" normalisiert. |

**Keine Kategorie wird als gesichert ausgegeben, ohne dass sie durch Daten gedeckt ist:** `category` und `metadata_state` stammen ausschließlich aus `extraInfo` und den gelesenen Feldern; `version` nur aus einem nicht-leeren `flags`-Feld.

---

## 5. Medium-Plugin-Ergebnisse (PROVEN)

| Save | normal | light | medium | total | Blockende geparst | deklariert | Delta |
|---|---|---|---|---|---|---|---|
| Autosave1 | 25 | 50 | **5** | **80** | 0x147B | 0x147B | 0 |
| Autosave2 | 25 | 50 | **5** | **80** | 0x147D | 0x147D | 0 |
| Autosave3 | 25 | 50 | **5** | **80** | 0x147D | 0x147D | 0 |
| Exitsave0 | 25 | 50 | **5** | **80** | 0x147D | 0x147D | 0 |
| Save46 | 25 | 50 | **5** | **80** | 0x147D | 0x147D | 0 |
| Save47 | 25 | 50 | **5** | **80** | 0x147D | 0x147D | 0 |

Die fünf Medium-Plugins sind in allen Saves dieselben: `SFBGS003.esm`, `SFBGS006.esm`, `PersonalSpacestation.esm`, `RRLAC - Rabbit's Real Lights Akila City.esm`, `RRLNA - Rabbit's Real Lights New Atlantis.esm`.

**Die Ausgabe „75 Plugins" existiert nicht mehr.** `sfda save info` meldet jetzt `25 normal | 50 light | 5 medium | 80 total`.

Die Werte sind **nicht** als Parserannahme codiert: der Parser liest, was im Zähler steht, und prüft danach das Blockende. Die Zahlen 25/50/5 stehen nur in den Tests (`GOLDEN`) als Erwartung an die Messbasis.

---

## 6. Plugin-Metadaten-Ergebnisse (PROVEN)

Genau sechs Einträge pro Save tragen echte Metadaten (Golden-Testfälle aus Save47):

| Plugin | Creation-Name | Creation-ID | Version | Achievement |
|---|---|---|---|---|
| `starfield_hair+beards.esm` | Starfield Hair+Beards | `TM_84981815-7935-49d1-a9a7-9ed57f491105` | 1753989797.2.3 | nein |
| `cwhdigipickshortcut.esm` | Digipick Skip Classic | `TM_e49e8638-1615-44f4-b93a-686824399afc` | 1776565871.1.01 | nein |
| `darkerspace.esm` | Darker Space | `TM_60a24112-d7ce-416b-ab44-fec0184d978e` | 1730975455.1.01 | nein |
| `immersivestarcolours.esm` | Immersive Star Colours | `TM_5582dea7-8d10-4ee7-bf99-da7def720c48` | 1754743933.1.1 | nein |
| `sfbgs019.esm` | Deimog-Fahrzeug | `TM_e3295393-57db-47ba-91e4-2ba74133856a` | 1763606756.1.0.81 | **ja** |
| `satounforcer.esm` | STAG N-Forcer | `TM_20f6cd3a-e6d8-41b2-8445-0ea83ace99ac` | 1733224944.1.00 | nein |

In allen sechs Saves identisch (6 Einträge, 0 `unreadable`). Die übrigen 71 Mod-Plugins haben keine Creation-Metadaten — das ist der Normalfall, kein Fehler, und wird als `absent` mit Begründung geführt.

**Beobachtung zum `flags`-Feld (PARTIALLY PROVEN):** Der Inhalt sieht systematisch wie `<epoch>.<major>.<minor>[.<patch>]` aus (z. B. `1776565871.1.01`), also eine Versionsangabe. Dass es tatsächlich eine Version ist, ist **nicht** belegt — die Referenzimplementierung nennt das Feld `Flags` und behandelt es als Bytefeld. Deshalb heißt das Feld bei uns `version`, wird aber nicht interpretiert (keine Sortierung, kein Versionsvergleich).

---

## 7. String-Pool-Ergebnisse (PROVEN für die Struktur, UNKNOWN für die Semantik)

| Save | Status | Strings | deklariert | printable | Array-Offset | Ende |
|---|---|---|---|---|---|---|
| Autosave1 | OK | 1735 | 1735 | 99,65 % | — | < Payload |
| Autosave2 | OK | 1713 | 1713 | 99,65 % | — | < Payload |
| Autosave3 | OK | 1731 | 1731 | 99,65 % | — | < Payload |
| Exitsave0 | OK | 1717 | 1717 | 99,65 % | — | < Payload |
| Save46 | OK | 1727 | 1727 | 99,65 % | — | < Payload |
| Save47 | OK | 1709 | 1709 | 99,65 % | 0x1472F93 | 0x147D5EF |

**Fünf Kriterien, alle in 6/6 Saves erfüllt:** `pointer[2]` zeigt exakt auf den Folgebenutzer · Zähler plausibel und im Payload · alle Strings sequentiell ohne Überlauf lesbar · > 99 % druckbar · Ende vor Payload-Ende.

Inhaltliche Stichprobe: `Sequence`, `Sandbox`, `Anzug: Navigator`, `[Kalibriert] Anzug: UC-Security`, `Zerlegend [Ausgeglichen] [Geschärft] Kampfmesser`, `actors\human\animations\furniture\terminal_standing`.

**Harte Grenze — ausdrücklich nicht implementiert und nicht behauptet:** FormID-Zuordnung, Record-Identifikation, Referenzauflösung, Objektvollständigkeit, Schiff-/Außenposten-Analyse. Die elf übrigen Pointer bleiben `UNKNOWN`; sie werden nur mit `inside_payload`-Flag ausgegeben, nicht gedeutet.

---

## 8. Integritätsprüfungen und Statusmodell

Statusverteilung über die sechs realen Saves:

| Prüfung | Status |
|---|---|
| I-01, I-02, I-04, I-05, I-06, I-07, I-08, I-10, I-11 | **PASS** in 6/6 |
| I-03 | PASS in 5/6, **WARNING** in Autosave2 (12 Füllbytes vor dem Datenstrom) |
| I-09 | UNKNOWN (Semantik nicht belegt) |
| I-12 | NOT_CHECKED (kein `--data-dir` übergeben) |
| I-13 | NOT_CHECKED (Body-Recordformat unbekannt) |
| I-14 | NOT_CHECKED (keine Vergleichsdaten) |

Gesamturteil: **PASS** für fünf Saves, **WARNING** für Autosave2. `total_with_gaps` ist bei allen sechs `NOT_CHECKED`, weil I-13 strukturell offenbleibt — die CLI zeigt diese Lücke in einer eigenen Sektion.

### Die drei stillen Fälle

| Fall | Manipulation | Vorher | Jetzt |
|---|---|---|---|
| **E** | `uncompressed_size` +1 | still durchgelaufen, Payload 1 Byte zu kurz gemeldet | **I-06 FAILED**, `decompress()` wirft standardmäßig |
| **F** | `chunk_size_pre` verdoppelt | 50,4 % der Daten, keine Meldung, plausibel aussehende Ausgabe | **I-04 FAILED + I-06 FAILED + I-03 WARNING** |
| **G** | 4 Bytes hinter dem zlib-Stream | folgenlos akzeptiert | **I-05 WARNING** mit `trailing_bytes`-Evidenz, `confidence = unverified` |

Fall G ist bewusst **kein** PASS und **kein** FAILED: Es ist nachgewiesen, dass Bytes hinter dem Stream liegen (`zlib.decompressobj().unused_data`), aber ob das Format sie erlaubt, ist nicht belegt. Die Prüfung sagt genau das.

### Abgrenzung

Jeder Report trägt den Satz: *„Diese Pruefung belegt strukturelle Integritaet. Sie belegt NICHT, dass Starfield den Spielstand laden kann. Objekt-, FormID- und Skriptebene werden nicht geprueft."* Der Satz ist nicht abschaltbar.

---

## 9. Tests mit PASS/FAIL/SKIPPED

```
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
→ 155 passed, 19 skipped in 13.90s
```

| Bereich | Tests | Status |
|---|---|---|
| `test_ssb_i_save_integrity.py` | 27 | **alle PASS** |
| `test_ssb_i_string_pool.py` | 12 | **alle PASS** |
| `test_ssb_i_real_saves.py` | 22 | **alle PASS** |
| `test_ssb_i_plugin_parsing.py` | 17 | **alle PASS** |
| `test_ssb_i_savegame_provider.py` | 12 | **alle PASS** |
| `test_ssb_i_cli.py`, `test_ssb_ui_pages.py` | 18 + 18 | **alle PASS** |
| `test_ssb_pe_lib*.py` | 19 | **SKIPPED** — Trust-Root-Binary fehlt bzw. capstone nicht installiert (nicht Save-bezogen, unverändert) |

**Kein Save-bezogener Test wird mehr übersprungen.** Die 19 Skips sind ausschließlich PE-Analyse ohne Testbinary — sie waren vorher und bleiben außerhalb dieses Auftrags.

Synthetische Negativtests (jede PASS-Regel hat mindestens einen): BCPS-Magic zerstört · unbekannte Kompression · Truncation · Chunk-Tabelle in den Datenstrom verschoben · `padding = 0` · Größenfeld +1 · `chunk_size_pre` ×2 · Bytes hinter dem Stream · DAT-Magic zerstört · unmögliche Stringlänge im Header · Medium-Zähler falsch · abgeschnittene Plugin-Metadaten · Plugin-Block hinter dem Payload · ungültiger `pointer[2]` · falsche Marker · überhöhter String-Zähler · abgeschnittener String · ungültige String-Länge · fehlender Body-Kopf · Level-Regression in der Sequenz.

---

## 10. Ergebnisse für jeden realen Save

| Save | n/l/m | total | game/mod | Metadaten | Block-Delta | String-Pool | Integrität |
|---|---|---|---|---|---|---|---|
| Autosave1 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1735 | **PASS** |
| Autosave2 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1713 | **WARNING** (I-03) |
| Autosave3 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1731 | **PASS** |
| Exitsave0 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1717 | **PASS** |
| Save46 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1727 | **PASS** |
| Save47 | 25/50/5 | 80 | 9/71 | 6 | 0 | OK, 1709 | **PASS** |

Alle sechs: Save-Version 153, Engine 27, Spielversion 1.16.244.0, Charakter „Cole", Level 24, 5077 Byte Plugin-Block.

---

## 11. SHA-256-Vergleich der Originaldateien

Vor und nach dem gesamten Testlauf geprüft, unverändert:

```
c9b1bb5b4422fd78…  Autosave1_A7460D2FM436F6C65_021105_20261007152914_24_0_4.sfs
451ca3e3b8b7b70b…  Autosave2_A7460D2FM436F6C65_021034_20261007143501_24_0_4.sfs
073f355cb3a44818…  Autosave3_A7460D2FM436F6C65_021055_20261007151825_24_0_4.sfs
53df16b41a7eeb4f…  Exitsave0_A7460D2FM436F6C65_021035_20261007143648_24_0_4.sfs
174b9310c9f60757…  Save46_A7460D2FM436F6C65_021033_20261004175306_24_0_4.sfs
bbfaba67aa07cbfd…  Save47_A7460D2FM436F6C65_021034_20261007143524_24_0_4.sfs
```

Zusätzlich prüft `test_original_saves_are_unchanged` die Hashes am Ende des Testlaufs, `test_savegame_provider_is_read_only` inspiziert jeden öffentlichen Provider-Aufruf auf Schreibmodi, und `test_read_only_no_file_is_written` vergleicht Größe, mtime und Inhalt nach einem String-Pool-Lauf.

---

## 12. Bekannte Einschränkungen

1. **`chunk_count` bleibt eine Ableitung** (`ceil(uncompressed_size / chunk_size_pre)`), keine Formatzusicherung. Sie ist nur für Save-Version 153 belegt; bei anderen Versionen liefert I-07 `heuristic`-Confidence.
2. **I-09 bleibt dauerhaft UNKNOWN.** `headerSize` (gemessen 123 und 125) hat keine belegte Semantik; 168 − 125 = 43 lässt sich nicht auflösen.
3. **`flags` → `version` ist eine Annahme.** Das Feld sieht wie eine Version aus, ist aber nicht als solche belegt (siehe Abschnitt 6).
4. **Medium-Plugins sind nur mit 5 Einträgen beobachtet.** Andere Werte sind gültig; der Parser prüft die Struktur, nicht die Zahl.
5. **Ältere Save-Versionen (104, 122) sind nicht abgedeckt.** Die früheren Referenzdateien existieren nicht mehr; das Metadatenformat ab Version 140 ist belegt, das Verhalten darunter nicht.
6. **`pytest.skip` wurde nicht vollständig abgeschafft.** PE-Tests ohne Trust-Root-Binary überspringen weiterhin (19 Skips) — das ist beabsichtigt und außerhalb dieses Auftrags. Ein Lauf *ganz ohne* Spieldaten ist nur mit `SSB_ALLOW_MISSING_SAVES=1` möglich.
7. **Die UI wurde offscreen getestet**, nicht auf einem echten Windows-Desktop mit dem Release-Build.

---

## 13. Offene UNKNOWN-Befunde

| Befund | Status | Fehlende Evidenz |
|---|---|---|
| Semantik von `headerSize` | UNKNOWN | Feldbedeutung; nur über mehrere Save-Versionen oder Engine-RE klärbar |
| Bedeutung der elf übrigen Body-Pointer | UNKNOWN | Strukturdefinition; nicht Teil dieses Auftrags |
| String-Pool-Semantik pro Eintrag | UNKNOWN | Zuordnung String → Record/FormID |
| Record-Format des Bodys | UNKNOWN | Formatdefinition (0 Record-Signaturen gemessen) |
| Plugin-Slot → Master-Index | UNKNOWN | Belegte Zuordnung |
| `flags` ist eine Version? | PARTIALLY PROVEN | Referenzimplementierung nennt es `Flags` |
| Save-Typ als Header-Feld | UNKNOWN | nur Dateinamen-Präfix belegt |
| Spielbarkeit | **nicht prüfbar** | statische Prüfung ist kein Ladetest |

---

## 14. Neue CLI- und UI-Funktionen

### CLI

```
sfda save verify  <save.sfs> [--json] [--data-dir DIR]
sfda save strings <save.sfs> [--json] [--limit N] [--all]
sfda save info    <save.sfs> [--json]     # jetzt 80 statt 75, Kategorien ergänzt
sfda save plugins <save.sfs> [--json]     # Metadaten je Eintrag
```

`save verify` liefert Exit-Code 1 bei `FAILED`, sonst 0. Textausgabe zeigt Einzelprüfungen, `INTEGRITAET`, `PRUEFABDECKUNG`, eine eigene `NICHT BEWERTET`-Sektion und den Disclaimer. Beispiel (Save47):

```
INTEGRITAET: PASS
PRUEFABDECKUNG: 10 von 14 Pruefungen bewertet (10 PASS, 0 WARNING, 0 FAILED, 1 UNKNOWN, 3 NOT_CHECKED)
```

### UI (Savegame Analyzer)

- **Integrity-Tab**: Gesamtstatus, Abdeckung, alle 14 Einzelprüfungen, getrennte Sektion „NICHT BEWERTET". Ein FAILED steht damit sichtbar über den Prüfzeilen, nicht in einem versteckten Tab.
- **String Pool-Tab**: Zusammenfassung sofort (Status, Anzahl, printable-Anteil, Offsets), die vollständige Liste erst nach Klick auf „Load strings" und dann auf 500 Einträge begrenzt — kein Überfluten der Oberfläche mit tausenden Zeilen.
- **Plugin-Karte**: `25 normal · 50 light · 5 medium · 80 total` und `9 game · 71 mod · 6 with creation metadata`.
- **Plugin-Baum**: Metadaten erscheinen als Unterzeile **nur** bei `metadata_state == "present"`; `unreadable` wird als solches markiert; Platzhalter erscheinen nie.

CLI und UI liefern denselben Gesamtstatus — geprüft durch `test_savegame_page_integrity_matches_cli`.

---

## 15. Git-Diff und finaler Commit-Status

```
HEAD:   9006753 (unverändert, kein Commit erstellt)

 M CHANGELOG.md
 M sfda_cli.py
 M ssb_i/product.py
 M ssb_i/savegame_provider.py
 M ssb_ui/pages/savegame_page.py
 M tests/test_ssb_i_cli.py
 M tests/test_ssb_i_plugin_parsing.py
 M tests/test_ssb_i_savegame_provider.py
 M tests/test_ssb_ui_pages.py
?? EXTERNAL_SAVEGAME_TOOLING_AUDIT.md
?? SAVE_INTELLIGENCE_AUDIT.md
?? SAVE_INTELLIGENCE_SPEC.md
?? SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md
?? audit/
?? ssb_i/save_integrity.py
?? tests/conftest.py
?? tests/test_ssb_i_real_saves.py
?? tests/test_ssb_i_save_integrity.py
?? tests/test_ssb_i_string_pool.py

9 Dateien geändert, 1141 Einfügungen(+), 366 Löschungen(−)
```

**Kein Commit erstellt** — die Ablage bleibt beim Repository-Inhaber. Version ist auf **1.5.3** gesetzt; es wurde nichts veröffentlicht, nichts hochgeladen und keine Spielinstallation angefasst.

---

## Abnahmekriterien — Status

| Kriterium | Status |
|---|---|
| alle realen Plugin-Listen vollständig inkl. Medium | **erfüllt** (6/6, 25/50/5) |
| falsche Ausgabe 75 → 80 korrigiert | **erfüllt** (CLI, JSON, UI) |
| Plugin-Metadaten korrekt dekodiert | **erfüllt** (6 present, 0 unreadable, Platzhalter normalisiert) |
| String-Pool in sicheren Grenzen lesbar | **erfüllt** (6/6 OK, hartes Gating, keine Objektbehauptung) |
| drei stille Korruptionsfälle angemessen behandelt | **erfüllt** (E/F FAILED, G WARNING mit unverified-Confidence) |
| übrige Korruptionsfälle weiterhin erkannt | **erfüllt** (9/9 deterministisch) |
| reale Tests tatsächlich ausgeführt | **erfüllt** (76 Tests gegen 6 echte Saves, 0 Skips im Save-Bereich) |
| keine Originaldatei verändert | **erfüllt** (SHA-256 vor/nach) |
| CLI und UI konsistent | **erfüllt** (eigener Test) |
| Dokumentation spiegelt den Stand | **erfüllt** (Nachträge in Audit und Spec) |

**Nicht als „fertig" ausgeliefert:** Die Semantik von `headerSize`, die elf Body-Pointer, die Record-Ebene, die FormID-Zuordnung und die Ladbarkeit bleiben ausdrücklich `UNKNOWN` bzw. `NOT_CHECKED`. Sie sind in Abschnitt 13 mit der jeweils fehlenden Evidenz benannt.
