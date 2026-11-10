# I09_I14_IMPLEMENTATION_REPORT

**Projekt:** Starfield Data Analysis · **Organisation:** Entropy Development
**Ausgangs-HEAD:** `ed5587acd99b6a45982b0c0a55ad11afb5e50d9a` · **Version:** 1.5.3 (unverändert)
**Datum:** 08.11.2026 · **Status:** implementiert, getestet, **nicht committet**

---

## A. Ausgangszustand

| Feld | Wert |
|---|---|
| Branch | `main` |
| HEAD | `ed5587acd99b6a45982b0c0a55ad11afb5e50d9a` |
| `git diff` | leer |
| `git diff --cached` | leer |
| Dirty State | nur 8 untracked Artefakte (4 Audit-Berichte, 2 Messwerkzeuge, 1 Gap-Analyse, `audit/`) |
| Verworfen / zurückgesetzt | nichts |
| Testlage vorher | 155 passed, 19 skipped |

**Relevante bestehende Implementierung, wie vorgefunden:**

| Stelle | Befund |
|---|---|
| `ssb_i/save_integrity.py` → `check_i09_header_size` | gab **statisch** `UNKNOWN` zurück; Formel nicht vorhanden |
| `ssb_i/savegame_provider.py` → `DatHeader` | `header_size` vorhanden, aber **kein Feld für das Padding-Ende** |
| `ssb_i/savegame_provider.py` → `parse_dat_header` | las das Padding (`off += 8`), verwarf die Position |
| `ssb_i/save_integrity.py` → `check_i14_sequence` | implementiert, prüfte Level und FileTime, **nicht** die Spielzeit |
| `sfda_cli.py` → `cmd_save_verify` | rief `run_all(src, data_dir=…)` **ohne** `sequence` → I-14 konnte nie greifen |
| `ssb_ui/pages/savegame_page.py` → `_run_integrity` | rief `run_all(path)` ohne Sequenz |

Bestätigt: Die Ursachenanalyse der vorherigen Runde war korrekt — I-09 war eine fehlende Formel, I-14 eine fehlende Verdrahtung.

---

## B. I-09 — headerSize

### B.1 Die Formel

```
header_size == padding_end − 16
```

- `padding_end` = Offset **direkt hinter** dem 8-Byte-Padding-Feld, vom Parser aus der tatsächlichen Feldposition geliefert.
- `16` = Formatkonstante: 12 Byte `SFS_SAVEGAME`-Magic + 4 Byte Größenfeld selbst.

Der gezählte Bereich beginnt also bei Offset `0x10` und endet mit dem Padding. **Nicht** mitgezählt werden 27 Byte:

```
0x8D  saveVersion2         1 B
0x8E  currentGameVersion   2 + 10
0x9A  createdGameVersion   2 + 10
0xA6  pluginInfoSize       2
0xA8  = plugin_info_offset (168)
```

Daraus: `plugin_info_offset − header_size = 16 + 27 = 43` — die früher als „nicht auflösbar" notierte Differenz.

### B.2 Konkrete Feldpositionen (Save47, aus dem Payload gelesen)

| Offset | Feld | Bytes |
|---|---|---|
| `0x00` | Magic `SFS_SAVEGAME` | 12 |
| `0x0C` | `headerSize` | 4 |
| `0x10` | **Beginn des gezählten Bereichs** | — |
| `0x10` | engineVersion | 4 |
| `0x14` | saveVersion | 1 |
| `0x15` | saveNumber | 4 |
| `0x19` | playerName (`u16` + 4) | 6 |
| `0x1F` | playerLevel | 4 |
| `0x23` | playerLocation (`u16` + 22) | 24 |
| `0x3B` | playtime (`u16` + 39) | 41 |
| `0x64` | raceName (`u16` + 9) | 11 |
| `0x6F` | gender | 2 |
| `0x71` | experience | 4 |
| `0x75` | experienceRequired | 4 |
| `0x79` | filetime | 8 |
| `0x81` | unknown0 | 4 |
| `0x85` | padding | 8 |
| **`0x8D`** | **`padding_end`** | — |
| `0x8D` … `0xA8` | nicht gezählt (27 B) | |

`0x8D − 0x10 = 125` = `header_size` ✓

### B.3 Änderungen

| Datei | Änderung |
|---|---|
| `ssb_i/savegame_provider.py` | `DatHeader` erhält `padding_end: int \| None = None` und `header_count_start: int = 16` (additiv, mit Default — bestehende Konstruktionen bleiben gültig). `parse_dat_header` merkt sich die Position hinter dem Padding und gibt sie mit. |
| `ssb_i/save_integrity.py` | `check_i09_header_size` vollständig ersetzt: berechnet den Erwartungswert aus `padding_end − header_count_start`, vergleicht, meldet PASS/FAILED/NOT_CHECKED mit vollständiger Evidenz. |

**Keine fest codierten Offsets, keine festen Stringlängen.** Der Parser liefert die Position; die Prüfung rechnet nur. Ein Test belegt, dass `padding_end` bei variierenden Feldlängen nicht 141 ist und die Formel trotzdem trifft.

**Fehlerbehandlung:** `padding_end is None` (Header unvollständig) → `NOT_CHECKED`, nicht PASS. `expected <= 0` (Feldgrenzen invertiert) → `FAILED`. Abgeschnittener Header scheitert bereits in `parse_dat_header` → `NOT_CHECKED`.

### B.4 Synthetische Variationstests (neu, `tests/test_ssb_i_i09_i14.py`)

Der Test-Builder in `tests/conftest.py` ist jetzt parametrisierbar (`player_name`, `player_location`, `playtime`, `race_name`) und berechnet den erwarteten `headerSize` selbst über `expected_header_size()` = 51 + vier Stringlängen.

| Testgruppe | Fälle |
|---|---|
| Name variiert | `""`, `"A"`, `"Ab"`, 40 Zeichen |
| Ort variiert | `""`, `"X"`, realer Ort, 44 Zeichen |
| Rasse variiert | `""`, `"R"`, `"HumanRace"`, 46 Zeichen |
| Spielzeit variiert | `"0d.0h.0m."`, realer Wert, `"123d.23h.59m."` |
| **Kombinationen** | alle leer · minimal · alle lang · gemischt (Name kurz + Ort lang + Rasse kurz) |
| Wachstum | `+11 Zeichen Name → +11 Byte headerSize` (1:1 nachgewiesen) |

Ergebnis: **alle PASS**, in jedem Fall gilt `header_size == padding_end − 16`.

### B.5 Negativtests

| Fall | Erwartung | Ergebnis |
|---|---|---|
| `headerSize` ±1, ±8 | FAILED | **FAILED**, `delta` = ±1/±8 in der Evidenz |
| Header mitten abgeschnitten (`0x80`) | kein PASS | **NOT_CHECKED** |
| Schnitt genau im Padding | kein PASS | **NOT_CHECKED** |
| Unmögliche Stringlänge (4000) | kein PASS | **I-08 FAILED, I-09 NOT_CHECKED** |
| Leerer Payload | kein PASS | **NOT_CHECKED** |

### B.6 Golden Saves

Alle sechs realen Spielstände: **I-09 PASS**, `delta = 0`.

| Save | `header_size` | `padding_end` | erwartet |
|---|---|---|---|
| Autosave1 | 123 | 139 | 123 |
| Autosave2, Autosave3, Exitsave0, Save46, Save47 | 125 | 141 | 125 |

### B.7 Klassifikation

**I-09 = PROVEN**

- **PROVEN auf sechs echten Saves** (6/6 exakt, `delta = 0`).
- **PROVEN auf synthetischen Variationstests**: vier Feldlängen einzeln und in Kombination variiert, Wachstum 1:1 nachgewiesen.
- **Falsifikation belegt**: Abweichungen ergeben FAILED, nicht PASS; unvollständige Header ergeben NOT_CHECKED.

**Verbleibende Einschränkungen — ausdrücklich:**

1. Untersucht wurden die vier **variablen** Headerfelder (Name, Ort, Spielzeit, Rasse) sowie die festen Felder in ihrer Reihenfolge. Nicht untersucht: Save-Versionen ≠ 153, andere `engine_version`, Saves mit abweichender Feldreihenfolge.
2. Die Konstante `16` stammt aus dem Format selbst (Magic-Länge + Feldbreite), ist aber nicht gegen eine andere Save-Generation verifiziert.
3. Die synthetischen Tests verwenden denselben Builder wie die Produktion — sie belegen die Formel gegen das **implementierte** Format, nicht gegen eine unabhängige Referenz. Die unabhängige Stützung kommt von den sechs realen Saves.
4. **Keine Aussage über andere Savegame-Versionen.** Die Formel gilt für Save-Version 153 / Engine 27.

---

## C. I-14 — Sequenzprüfung

### C.1 Bisherige Aufrufkette (Ursache der Lücke)

```
sfda save verify <save>
  → cmd_save_verify(args)
      → run_all(src, data_dir=args.data_dir)      ← kein sequence
          → build_context(..., sequence=())        ← leer
              → check_i14_sequence: "keine Vergleichsdaten" → NOT_CHECKED
```

Die Prüfung war korrekt implementiert und wurde nie erreicht.

### C.2 Korrigierte Aufrufkette

```
sfda save verify <save>
  → cmd_save_verify(args)
      → collect_sequence(src, directory=args.sequence_dir)     ← NEU
      → run_all(src, data_dir=…, sequence=…)
          → check_i14_sequence  →  PASS / WARNING / NOT_CHECKED
```

`ssb_ui/pages/savegame_page.py → _run_integrity` nutzt dieselbe Sammlung, damit Oberfläche und CLI dasselbe Ergebnis zeigen.

### C.3 `collect_sequence` — Auswahl und Sortierung

```python
collect_sequence(path, *, directory=None, max_files=64) -> tuple[DatHeader, ...]
```

| Aspekt | Regel |
|---|---|
| **Quelle** | alle `*.sfs` im Verzeichnis der geprüften Datei (oder `--sequence-dir`) — ausschließlich real vorhandene Dateien |
| **Auswahl bei > 64 Dateien** | die nach Datei-`mtime` neuesten, danach wieder nach Name sortiert (deterministisch) |
| **Reihenfolge der Rückgabe** | **Dateiname** — `collect_sequence` sortiert *nicht* chronologisch |
| **Sortierung der Sequenz** | erst in `check_i14_sequence()`: **ausschließlich** nach `filetime` aus dem Header, Tiebreak `save_number` — nie nach `mtime` |
| **Doppelte Spielstände** | Dedup über die Identität des dekomprimierten Payloads → derselbe Save tritt nicht zweimal ein |
| **Nicht lesbare Dateien** | werden übersprungen (kein Bestandteil einer belastbaren Sequenz) |
| **Schreibzugriff** | keiner — nur `"rb"` |

> **Korrektur 08.11.2026 (I-14/L1, unabhängiges Abnahmeaudit):** Die vorige Fassung
> dieser Tabelle stand unter der Überschrift „collect_sequence — Auswahl und
> Sortierung" und legte damit nahe, der Sammler sortiere chronologisch. Das war
> falsch. `collect_sequence()` liefert die Header in Dateinamen-Reihenfolge;
> `mtime` entscheidet nur, *welche* 64 Dateien gelesen werden. Die chronologische
> Ordnung — inklusive der Behandlung gleicher Zeitstempel — entsteht
> ausschließlich in `check_i14_sequence()`. Ein Regressionstest hält die
> Verantwortung jetzt fest
> (`test_collect_sequence_returns_filename_order_not_chronology`).

### C.4 Prüflogik (`check_i14_sequence`)

Geprüft werden **Level**, **Spielzeit** und implizit die **Zeitfolge**. Regeln gegen falsche PASS:

1. Nur Header mit `filetime > 0` **und** `player_level > 0` sind verwendbar; andere werden verworfen und gezählt.
2. Weniger als zwei brauchbare Header → **NOT_CHECKED**.
3. Bei mehreren Charakteren im Ordner wird auf den Charakter des geprüften Saves gefiltert (Bezugssave). Bleibt nur einer übrig → **NOT_CHECKED**.
4. Paare mit **identischem** `filetime` sind nicht eindeutig geordnet: das innere Paar wird nicht bewertet, **und** die Sequenz ergibt höchstens WARNING („Reihenfolge nicht eindeutig") — nie PASS.
5. Sind **alle** Zeitstempel identisch → **NOT_CHECKED**.
6. Spielzeit wird nur verglichen, wenn **beide** Werte lesbar sind (`playtime_minutes()`). Ist in keinem Paar eine Spielzeit lesbar → WARNING mit Begründung, kein PASS.

`playtime_minutes()` wertet den maschinenlesbaren Kopf `"Xd.Yh.Zm."` aus und ignoriert die lokalisierte Wiederholung. Kein Raten: passt das Muster nicht, ist das Ergebnis `None`.

### C.5 Echte Zeitreihe (sechs Saves)

| FileTime | Level | Spielzeit | Minuten |
|---|---|---|---|
| 134356099865691096 | 24 | 2d.10h.33m | 3513 |
| 134358573015793139 | 24 | 2d.10h.34m | 3514 |
| 134358573240754512 | 24 | 2d.10h.34m | 3514 |
| 134358574084798719 | 24 | 2d.10h.35m | 3515 |
| 134358599053892393 | 24 | 2d.10h.55m | 3535 |
| 134358605546179676 | 24 | 2d.11h.5m | 3545 |

```
I-14 PASS · "6 Saves von 'Cole' monoton in Level, Spielzeit und Zeit"
evidenz: {saves: 6, character: 'Cole', ordered_pairs: 5,
          playtime_pairs_compared: 5, duplicate_timestamps: 0, discarded_headers: 0}
```

### C.6 Negativtests

| Fall | Erwartetes Ergebnis | erreicht |
|---|---|---|
| nur ein Save | NOT_CHECKED („weniger als zwei brauchbare Header") | **NOT_CHECKED** |
| keine Sequenz übergeben | NOT_CHECKED | **NOT_CHECKED** |
| Levelabfall 40 → 10 | WARNING mit „Level faellt von 40 auf 10" | **WARNING** |
| **Spielzeitabfall** bei steigendem Level | WARNING mit „Spielzeit faellt" | **WARNING** |
| doppelter Zeitstempel | WARNING „Reihenfolge nicht eindeutig" | **WARNING** |
| doppelter Zeitstempel **und** echter Abfall | beide Meldungen | **WARNING, beide** |
| alle Zeitstempel identisch | NOT_CHECKED | **NOT_CHECKED** |
| `filetime = 0` / `player_level = 0` | verworfen, dann NOT_CHECKED | **NOT_CHECKED, discarded = 2** |
| fremder Charakter im Ordner | Bezugssave-Filter greift | **WARNING (echter Abfall bleibt sichtbar), character = TestPilot** |
| Spielzeit in keinem Paar lesbar | WARNING, kein PASS | **WARNING** |
| `--no-sequence` | I-14 NOT_CHECKED | **NOT_CHECKED** |

### C.7 Klassifikation

**I-14 = PROVEN** (Prüfung und Verdrahtung)

- Läuft über den regulären CLI-Aufruf: `test_cli_verify_runs_sequence_on_real_saves` prüft genau das.
- PASS auf echten Daten, WARNING auf synthetischem Abfall, NOT_CHECKED bei unzureichender Datenlage.
- UI liefert denselben Status wie die CLI (`test_savegame_page_i14_matches_cli`).

**Einschränkung:** I-14 prüft eine **Chronologie-Annahme** (Level, Spielzeit und Zeit laufen vorwärts). Sie erkennt zurückgerollte Saves, Spielzeit-Rückschritte und gemischte Installationen. Sie erkennt **nicht**, ob ein Spielstand inhaltlich konsistent ist — ein manipulierter Save mit sauberer Zeitfolge besteht I-14.

---

## D. Regression

### D.1 Testzahlen

```
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
→ 216 passed, 19 skipped in 20.73s
```

| | vorher | nachher |
|---|---|---|
| passed | 155 | **216** (+61) |
| skipped | 19 | 19 (unverändert) |
| neue Testdatei | — | `tests/test_ssb_i_i09_i14.py` (58 Tests) |

### D.2 Übersprungene Tests mit Begründung

Alle 19 unverändert und außerhalb dieses Auftrags:

| Anzahl | Datei | Grund |
|---|---|---|
| 17 | `test_ssb_pe_lib.py`, `test_ssb_pe_lib_vtable.py` | Trust-Root-Binary nicht gesetzt / `capstone` nicht installiert |
| 1 | `test_ssb_i_cli.py` | kein `Starfield.exe` vorhanden |
| 1 | `test_ssb_pe_lib.py` | `capstone` nicht installiert |

**Kein Savegame-bezogener Test wird übersprungen.** Die sechs echten Saves laufen über die Pflicht-Fixture `real_saves`, nicht über `/tmp`-Pfade.

### D.3 Angepasste Bestandstests (dokumentiert)

Vier Tests kodierten den **alten** Zustand „I-09 bleibt UNKNOWN" und mussten mitwandern:

| Test | Änderung |
|---|---|
| `test_ssb_i_save_integrity.py::test_unknown_is_not_converted_to_pass` | ersetzt durch `test_i09_passes_only_with_matching_formula`: PASS nur bei exakter Formel, `+3` ergibt FAILED |
| `test_intact_synthetic_save_assesses_cleanly` | `I-09 == PASS` statt `UNKNOWN` |
| `test_report_exposes_gaps_separately` | `gaps = {I-12, I-13, I-14}`, `assessed = 11` |
| `test_ssb_i_real_saves.py::test_every_real_save_passes_structural_checks` | `I-09 == PASS` statt `UNKNOWN` |

Der **Schutzgedanke** bleibt erhalten: I-09 gibt nur PASS bei erfüllter Formel; jede Abweichung ist FAILED.

### D.4 CLI-Ergebnisse

```
$ sfda --version
sfda 1.5.3 - Starfield Data Analysis (Entropy Development)

$ sfda save info <Save47>
Plugins       VALIDATED | 25 normal | 50 light | 5 medium | 80 total
Plugin types  9 game | 71 mod | 6 with creation metadata
```

Unverändert gegenüber 1.5.3.

```
$ sfda save verify <Save47>
I-01 PASS         Container beginnt mit BCPS
…
I-08 PASS         DAT-Magic korrekt, alle Header-Laengenfelder innerhalb des Puffers
I-09 PASS         headerSize=125 entspricht padding_end 0x8D minus 16 Byte
I-10 PASS         Block 0xA8..0x147D liegt vollstaendig im Payload
I-11 PASS         25/50/5 Plugins gelesen (9 game, 71 mod), Blockende bytegenau
I-12 NOT_CHECKED  kein Data-Verzeichnis angegeben (--data-dir)
I-13 NOT_CHECKED  nicht ausgefuehrt: Record-Format des Bodys nicht erschlossen
I-14 PASS         6 Saves von 'Cole' monoton in Level, Spielzeit und Zeit

INTEGRITAET: PASS
PRUEFABDECKUNG: 12 von 14 Pruefungen bewertet (12 PASS, 0 WARNING, 0 FAILED, 0 UNKNOWN, 2 NOT_CHECKED)
Sequenz: 6 Save(s) einbezogen (chronologisch nach Header-FileTime).
```

**Abdeckung: 10/14 → 12/14.** I-13 bleibt `NOT_CHECKED`, I-12 unverändert `NOT_CHECKED` ohne `--data-dir`.

### D.5 JSON-Ergebnis

```
total           : PASS
total_with_gaps : NOT_CHECKED        (I-12/I-13 offen)
coverage        : {PASS: 12, UNKNOWN: 0, NOT_CHECKED: 2, WARNING: 0, FAILED: 0, assessed: 12, total: 14}
I-09 evidence   : {header_size: 125, padding_end: 141, expected: 125, delta: 0, header_count_start: 16}
I-14 evidence   : {saves: 6, character: 'Cole', ordered_pairs: 5, playtime_pairs_compared: 5,
                   duplicate_timestamps: 0, discarded_headers: 0,
                   span: [134356099865691096, 134358605546179676]}
I-13            : NOT_CHECKED (unverändert)
disclaimer      : vorhanden
```

### D.6 Exit-Codes

| Aufruf | Exit |
|---|---|
| `save verify <intakter Save>` | **0** |
| `save verify --no-sequence <intakter Save>` | **0** |
| `save verify <Fall E, manipuliert>` | **≠ 0** (durch `test_cli_verify_exit_code_nonzero_on_failure` abgesichert) |

### D.7 SHA-256 der sechs Originale

Vor und nach der gesamten Implementierung und aller Testläufe unverändert:

```
c9b1bb5b4422fd784ba4158069111cad…  Autosave1
451ca3e3b8b7b70b9882b7d9404b3e3c…  Autosave2
073f355cb3a4481867129be7f8cbce8f…  Autosave3
53df16b41a7eeb4fa4275e00339cfa0c…  Exitsave0
174b9310c9f60757abc7f2e66b809159…  Save46
bbfaba67aa07cbfdffcae59671211f0e…  Save47
```

---

## E. Abgrenzung — bestätigt

| Zusage | Status |
|---|---|
| **I-12 unverändert** | ✅ `check_i12_dependencies` nicht berührt; liefert weiterhin `NOT_CHECKED` ohne `--data-dir` |
| **I-13 unverändert UNKNOWN/NOT_CHECKED** | ✅ `check_i13_formids` unverändert, gibt weiterhin `NOT_CHECKED` |
| **I-01…I-08, I-10, I-11 unverändert** | ✅ alle sechs realen Saves: unverändert PASS, alle Bestandstests grün |
| Keine Änderung an Original-Savegames | ✅ SHA-256 vor/nach identisch |
| Keine neue Dependency | ✅ nur `re` (Standardbibliothek) neu importiert |
| Keine Datenbank, kein Framework | ✅ |
| Keine Rust-Portierung | ✅ |
| Keine Schreib-/Reparaturfunktion | ✅ Read-only-Test inspiziert weiterhin jeden Provider-Aufruf |
| Keine UI-Neugestaltung | ✅ nur `_run_integrity` um die Sequenz ergänzt |
| Version nicht erhöht | ✅ 1.5.3 |
| **Keine Veröffentlichung, kein Push** | ✅ |
| **Kein Commit** | ✅ alle Änderungen uncommitted |
| Untracked Artefakte unangetastet | ✅ alle 8 vorhanden, nichts gelöscht oder verschoben |

**Disclaimer erhalten:** Jeder Report trägt weiterhin „Diese Pruefung belegt strukturelle Integritaet. Sie belegt NICHT, dass Starfield den Spielstand laden kann. Objekt-, FormID- und Skriptebene werden nicht geprueft." Ein PASS wird nirgends als Engine-Ladbarkeit oder Spielbarkeit dargestellt.

---

## F. Diff-Übersicht

```
HEAD: ed5587acd99b6a45982b0c0a55ad11afb5e50d9a  (unverändert, kein Commit)

 sfda_cli.py                        |  28 ++++-
 ssb_i/save_integrity.py            | 218 +++++++++++++++++++++++++++++++++----
 ssb_i/savegame_provider.py         |  10 ++
 ssb_ui/pages/savegame_page.py      |  15 ++-
 tests/conftest.py                  |  39 ++++++-
 tests/test_ssb_i_real_saves.py     |  24 +++-
 tests/test_ssb_i_save_integrity.py |  33 ++++--
 tests/test_ssb_ui_pages.py         |  38 +++++++
 8 files changed, 367 insertions(+), 38 deletions(-)

neu (untracked): tests/test_ssb_i_i09_i14.py   (58 Tests)
```

### Begründung je Datei

| Datei | Änderung | Warum |
|---|---|---|
| `ssb_i/savegame_provider.py` | `DatHeader` + `padding_end`, `header_count_start`; `parse_dat_header` merkt die Padding-Position | Ohne diese Position kann I-09 nicht rechnen, ohne Offsets fest zu verdrahten. Additiv mit Default → keine Bruchstelle |
| `ssb_i/save_integrity.py` | `check_i09` ersetzt; `playtime_minutes()`, `collect_sequence()`, `check_i14_sequence` überarbeitet | I-09 braucht die Formel; I-14 braucht Spielzeitprüfung, Duplikat- und Charakterbehandlung sowie eine Sammlung der Vergleichsdaten |
| `sfda_cli.py` | `cmd_save_verify` sammelt Sequenz und übergibt sie; `--sequence-dir`, `--no-sequence`; Transparenzzeile | Ohne Übergabe läuft I-14 nie — der eigentliche Auftrag |
| `ssb_ui/pages/savegame_page.py` | `_run_integrity` nutzt `collect_sequence`; Sequenzzeile im Text | Sonst zeigt die UI 11/14, die CLI 12/14 — inkonsistent |
| `tests/conftest.py` | Builder parametrisierbar (Name/Ort/Spielzeit/Rasse), `expected_header_size()`, `truncate_at` | Voraussetzung für die geforderten synthetischen Variationstests |
| `tests/test_ssb_i_i09_i14.py` | **neu**, 58 Tests | Falsifikation für I-09 und I-14 |
| `tests/test_ssb_i_real_saves.py` | I-09-Golden-Test, CLI-Sequenz-Test, I-09 PASS statt UNKNOWN | Golden-Absicherung |
| `tests/test_ssb_i_save_integrity.py` | 4 Tests an den neuen I-09-Status angepasst | Erwartungen kodierten den alten Zustand |
| `tests/test_ssb_ui_pages.py` | UI/CLI-Konsistenztest für I-14 | Absicherung der Verdrahtung |

**Keine nicht zuordenbare Änderung.** Jede Zeile im Diff dient I-09, I-14 oder der dafür nötigen Testbasis.

---

## Abschlussurteil

| Kriterium | Ergebnis |
|---|---|
| I-09 arbeitet auf echten **und** synthetischen Daten korrekt | **erfüllt** — 6/6 real, 20+ synthetische Variationen, 5 Negativfälle |
| I-14 läuft über den regulären CLI-Aufruf | **erfüllt** — Test prüft genau den CLI-Pfad, PASS mit 6 Saves |
| Unvollständige Daten erzeugen keinen falschen PASS | **erfüllt** — 6 NOT_CHECKED-Pfade, 4 WARNING-Pfade, alle getestet |
| Sämtliche Regressionstests bestehen | **erfüllt** — 216 passed, 19 PE-Skips |
| Original-Savegames unverändert | **erfüllt** — SHA-256 vor/nach identisch |
| Änderungen ausschließlich dem Auftrag zuzuordnen | **erfüllt** — 8 Dateien + 1 neue Testdatei, jede begründet |
| Abschlussbericht vollständig | **erfüllt** — dieser Bericht |

**Status: FERTIG, NICHT COMMITTET.**

Bewertungsabdeckung **10/14 → 12/14**. I-09 von `UNKNOWN` auf **PROVEN** gehoben, mit ausdrücklich benannter Fassungsgrenze (Save-Version 153, vier variable Headerfelder). I-14 von `NOT_CHECKED` auf **PROVEN** durch echte Verdrahtung, mit erweiterter Prüfung um die Spielzeit.

**Bekannte neue Einschränkung:** `collect_sequence` dekomprimiert alle Saves im Ordner vollständig. Bei sechs Dateien kostet `save verify` dadurch 1,06 s statt 0,08 s; bei 64 Dateien bis zu ~5 s. Das ist der Preis für eine tatsächlich ausgeführte Sequenzprüfung und im Bericht bewusst nicht beschönigt. Ein schnellerer Weg (nur Chunk 0) wäre eine neue Funktion und war nicht Teil dieses Auftrags.

> **Erledigt 08.11.2026 (I-14/L2):** Der schnelle Weg ist inzwischen umgesetzt. Die Sequenzermittlung dekodiert nur noch den ersten Chunk je Datei (`SfsDecodeProvider.read_header`). Gemessen: 6 Saves 0,97 s → 0,19 s, 64 Dateien 8,16 s → 1,33 s, ohne eine einzige zusätzliche vollständige Dekompression des Rumpfs. Der Bezugssave wird nur noch einmal vollständig entpackt (durch `build_context`), nicht mehr zweimal. Nachweise und Grenzen: `/tmp/SSBI_I14_PERFORMANCE_REPORT.md`.

> **Nachtrag 08.11.2026 (R3, unabhängiger Review):** Die 64-Datei-Grenze ist **keine reine
> Performance-Angabe**. Ab 65 Dateien entscheidet die Dateisystem-`mtime`, welche Saves
> überhaupt ausgewertet werden. Ein dadurch ausgeschlossener Save kann einen echten
> Level- oder Spielzeit-Rückgang enthalten; dieser wird dann nicht bewertet, und I-14 kann
> `PASS` melden, obwohl der Rückgang in den vorhandenen Dateien steckt. Ein `PASS` bezieht
> sich daher **nur auf die tatsächlich ausgewertete Sequenz**, nicht auf den gesamten
> Datenbestand. `not_considered.count` und die Namensliste sind entsprechend zu lesen:
> als Einschränkung der Aussagekraft, nicht als Randnotiz. Die Auswahlregel selbst bleibt
> unverändert; die Einschränkung steht zusätzlich als `selection.limitation` im Befund und
> als `EINSCHRAENKUNG`-Zeile in der Nutzerausgabe. Details:
> `/tmp/SSBI_I14_R1_R3_CORRECTION_REPORT.md`.

**Nicht committet. Kein Push. Kein Upload.** Der Diff liegt vollständig im Working Tree zur Prüfung.
