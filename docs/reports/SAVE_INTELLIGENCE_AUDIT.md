# SAVE_INTELLIGENCE_AUDIT

**Projekt:** Starfield Data Analysis (SSB-I) · Entwickler: Entropy Development
**Repository:** `/home/cole/Developer/starfield-data-analysis` · Stand `9006753`
**Erstellt:** 08.11.2026 · **Modus:** read-only Audit, keine Code-Änderung, keine Schreiboperation auf Saves, Release 1.0.0 unangetastet

**Messgrundlage**
10 echte Starfield-Savegames unter `~/ssb_probes/` (6 mit Starfield-Originalnamen, 4 `ssbm_*`-Kopien), Save-Version 153, Engine 27, Spielversion 1.16.244.0.
Alle Zahlen dieses Berichts stammen aus `audit/save-intelligence/audit.py` (read-only, reproduzierbar):

```
python audit/save-intelligence/audit.py inventory | integrity | perf | dupes | regions | scan
```

Umgebung: Python 3.13.14 (`.venv-build`), SQLite-frei, keine Netzwerkzugriffe.

---

## 1. Tatsächlicher Ist-Zustand

### 1.1 Code-Bestand

| Einheit | Zeilen | Aufgabe |
|---|---|---|
| `ssb_i/savegame_provider.py` | 482 | BCPS-Container, zlib-Chunking, `SFS_SAVEGAME`-Header, Plugin-Liste, Byte-Diff |
| `ssb_i/savegame_differential.py` | 283 | Metadaten-Vergleich, Cluster, FormID-Kandidaten, Markdown-Report |
| `ssb_i/ssb_pe_lib.py` | 235 | PE32+-Analyse (nicht Save-bezogen, bleibt unberührt) |
| `ssb_ui/pages/savegame_page.py` | 441 | Savegame-Seite: drei Karten, Header-Dump, Diff-Tab, JSON-Report |
| `ssb_ui/pages/hex_view_page.py` | 279 | Hex-Ansicht, nutzt den dekomprimierten Puffer der Savegame-Seite |
| `ssb_ui/app.py` | 469 | Fenster, Sidebar, Seiten-Stack (`build_pages`, Zeile 260) |
| `sfda_cli.py` | ~350 | `save info/header/plugins/diff`, `pe info/sections` |
| `tests/` (9 Dateien) | ~1.250 | Provider, Container synthetisch, Differential, Plugin-Parsing, CLI, UI |

Produktive Save-Pfade: **765 Zeilen Kernlogik + 441 Zeilen UI + ~1.250 Zeilen Tests**.

### 1.2 Testlage (gemessen)

```
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
→ 77 passed, 28 skipped in 1.35s
```

Die 28 Skips im Einzelnen:

| Anzahl | Grund |
|---|---|
| 10 | `test_ssb_i_savegame_provider.py` — Referenz-Saves fehlen (`/tmp/starter-save/...`, `/tmp/second-save/...`) |
| 3 | `test_ssb_i_plugin_parsing.py` — `/tmp/ssbi_demo/Save4{1,2,3}.sfs` fehlen |
| 2 | `test_ssb_i_cli.py` — kein reales Savegame / keine `Starfield.exe` |
| 13 | `test_ssb_pe_lib.py` — Trust-Root-Binary nicht gesetzt (`__not_set__`) |

Ohne `QT_QPA_PLATFORM` bricht der Lauf in `test_ssb_ui_hex_view.py:56` mit `Fatal Python error: Aborted` ab (QApplication ohne Display) — Umgebungsproblem, kein Codefehler, aber es muss bekannt sein, bevor die Suite in eine CI wandert.

**Befund:** Die Suite ist grün, ohne dass ein einziger echter Spielstand geprüft wurde. Die Verdrahtung für echte Saves existiert (`DANTE_SFS`/`BRIAN_SFS` lesen `SSB_SFS_*` aus der Umgebung), sie wird nur nie gesetzt. Genau das ist der Grund, warum die drei stillen Integritätsfehler aus Abschnitt 3.2 unbemerkt bleiben konnten.

### 1.3 Was die CLI heute real ausgibt

```
$ sfda save info Save47_A7460D2FM436F6C65_021034_20261007143524_24_0_4.sfs
File          Save47_...sfs
Player        Cole (level 24)
Location      Jemison - New Atlantis
Save version  153
Game version  1.16.244.0
Playtime      2d.10h.34m.2 Tage.10 Stunden.34 Minuten
BCPS chunks   90
Decompressed  23,533,511 bytes
Plugins       VALIDATED | 25 normal | 50 light | 0 medium
Note: 25 normal (declared 25), 50 light, 0 medium; per-record metadata block NOT decoded
```

Sauber, ehrlich, funktioniert. Auffällig: die Spielzeit enthält zwei Formate in einem String — das Feld ist so gespeichert, nicht falsch geparst (siehe 3.3).

---

## 2. Bereits vorhandene und wiederverwendbare Funktionen

Alles Folgende ist **vorhanden, getestet und für Save Intelligence direkt nutzbar**. Es wird nichts davon neu geschrieben.

| Funktion | Ort | Wiederverwendung |
|---|---|---|
| `SfsDecodeProvider.read_container()` | `savegame_provider.py:156` | Container-Header für Integrität I-01/I-02/I-03 |
| `SfsDecodeProvider.decompress()` | `savegame_provider.py:190` | Chunk-Dekompression, liefert Puffer für alle weiteren Schritte |
| `SfsDecodeProvider.parse_dat_header()` | `savegame_provider.py:233` | 17 Identifikationsfelder |
| `SfsDecodeProvider.parse_plugin_info()` | `savegame_provider.py:386` | Plugin-Liste inkl. Selbstvalidierung (`decode_state`) |
| `SfsDecodeProvider.is_plugin_name()` / `_walk_names()` / `_probe_counted_chain()` | `savegame_provider.py:301–384` | Plugin-Erkennung; `_walk_names` ist auch für künftige Metadaten-Dekodierung die Basis |
| `SfsDecodeProvider.NATIVE_PLUGINS` | `savegame_provider.py:290` | Kennzeichnung offizieller Master |
| `compare_metadata()` | `savegame_differential.py:93` | Identitäts- und Installationsvergleich (Feld für Feld — die einzige belastbare Vergleichsform, siehe 3.5) |
| `cluster_offsets()` | `savegame_differential.py:43` | Cluster-Bildung für Differenzen |
| `analyze_bytes()` / `analyze_paths()` | `savegame_differential.py:163/198` | Byte-Diff-Infrastruktur, `negative_evidence`-Block (vorbildlich: benennt, was **nicht** gilt) |
| `markdown_report()` / `write_reports()` | `savegame_differential.py:226/259` | Report-Erzeugung; Muster für Integritäts-Report |
| `SfsDecodeProvider.capabilities()` | `savegame_provider.py:130` | Deklarative Fähigkeitskarte, `read_only` explizit |
| `SavegamePage.load_file()` | `savegame_page.py:261` | Lädt, dekodiert, füllt Karten; Fehlerpfad verwirft alten Zustand korrekt |
| `SavegamePage.current_buffer()` | `savegame_page.py:336` | Pufferquelle für Hex-Ansicht |
| `build_pages()` | `app.py:260` | Einzige Quelle für Sidebar, Stack und Seitennamen — Integrationspunkt für eine neue Seite |
| `EXIT_OK`/`EXIT_ERROR` + `emit_lines`/`emit_json` | `sfda_cli.py:36/37` | CLI-Ausgabekonvention inkl. ASCII-only-Regel für Windows-Konsolen |
| Korruptions-Testmuster | `test_ssb_i_savegame_container_synthetic.py` | Synthetische Container mit Magic, Chunks, Padding — direkt erweiterbar um die 12 Fälle aus 3.2 |
| `plugins_*`-Fixtures | `test_ssb_i_plugin_parsing.py:63–126` | Selbstvalidierung der Plugin-Kette, inkl. Fail-closed-Fällen |

**Kein einziger dieser Bausteine muss ersetzt werden.** Save Intelligence ist eine Schicht darüber, kein Umbau.

---

## 3. Nachweisbare Fähigkeiten und Grenzen

Statusdefinition: **PROVEN** = durch Implementierung *und* Messung an echten Daten belegt · **PARTIALLY PROVEN** = teilweise erschlossen · **UNKNOWN** = Bedeutung ungeklärt · **NOT IMPLEMENTED** = fehlt.

### 3.1 Was nachweislich funktioniert

| Fähigkeit | Status | Messung |
|---|---|---|
| BCPS-Container lesen | **PROVEN** | 10/10 Saves, `chunk_size_pre=262144`, `padding=16`, `compressed_offset` 432/448 |
| Vollständige Dekompression | **PROVEN** | `len(payload) == uncompressed_size` in 10/10, Abweichung 0 Byte |
| Chunk-Tabelle / Padding-Arithmetik | **PROVEN** | `Σ ceil(chunk_i/padding)·padding == Dateigröße − compressed_offset` in 10/10 |
| `SFS_SAVEGAME`-Header | **PROVEN** (Lesen) | 17 Felder in 10/10, Feldreihenfolge durch Hexdump bestätigt |
| Zeitstempel | **PROVEN** | FileTime 134358573240754512 → 2026-10-07 14:35:24 UTC = Dateiname `20261007143524` in 6/6 echten Saves |
| Plugin-Liste | **PROVEN** | 10/10 `VALIDATED`, 25 normal + 50 light, erster Eintrag `Starfield.esm` |
| CLI `save info/header/plugins` | **PROVEN** | real ausgeführt, siehe 1.3 |
| UI-Savegame-Seite | **PROVEN** | lädt, füllt drei Karten, schreibt JSON-Report (UI-Tests offscreen) |

### 3.2 Die Integritätslücke — gemessen, nicht behauptet

12 Korruptionsfälle auf **Kopien** (`audit.py integrity`), Originale per SHA-256 vor/nach geprüft:

| Fall | Manipulation | Verhalten des heutigen Codes |
|---|---|---|
| intact | — | `accepted`, len 23.383.518/23.383.518 |
| A | letzte 1000 B entfernt | **FAILED** — `zlib error at chunk 89` |
| B | Hälfte entfernt | **FAILED** — `zlib error at chunk 49` |
| C | Bitflip im Kompressionsstrom | **FAILED** — `zlib error at chunk 0` |
| D | Bitflip im letzten Chunk | **FAILED** — `zlib error at chunk 89` |
| H | Magic `BCPS` zerstört | **FAILED** — `Not an SFS file` |
| I | nur 512 B | **FAILED** — `zlib error at chunk 0` |
| J | alles ab Byte 100 genullt | **FAILED** — `zlib error at chunk 0` |
| L | `padding_size = 0` | **FAILED** — `zlib error at chunk 1` |
| M | `compressed_offset` verschoben | **FAILED** — `zlib error at chunk 0` |
| **E** | `uncompressed_size` +1 | **SILENT** — liefert 23.383.518 von 23.383.519 erwarteten Bytes, keine Meldung, Plugin-Liste `VALIDATED` |
| **F** | `chunk_size_pre` ×2 | **SILENT** — liefert 11.796.480 von 23.383.518 Bytes (**50,4 %**), keine Meldung, Header und Plugin-Liste werden plausibel geparst |
| **G** | eine Chunk-Größe +4 | `accepted` — folgenlos: 4 Zusatzbytes werden von zlib ignoriert, Nutzdaten vollständig. Kein Schaden, aber auch keine Meldung. |

**Präzise Aussage:** 9 von 13 Fällen enden in einer Exception (nicht in einem Befund), 3 laufen ohne Meldung durch, davon **2 mit echtem Datenverlust oder falscher Sollgröße**. Der Fall F ist der Beweis, dass „der Parser lief durch" keine Aussage über Vollständigkeit ist: eine halbierte Datei sieht im Ergebnis wie ein vollständiger Spielstand aus.

**Wichtig zur Einordnung:** Der Code *meldet* keine Integrität — er hat keine Prüfschicht. Er kennt nur Ausnahmen beim Dekodieren. Es gibt in den Save-Modulen **kein** `crc`, `sha256` oder `integrity` (verifiziert per `grep`); nur die PE-Bibliothek hat SHA-256.

### 3.3 Was teilweise erschlossen ist

| Bereich | Status | Konkret |
|---|---|---|
| `playtime` | **PARTIALLY PROVEN** | Ein String mit zwei Formaten: `"2d.10h.34m.2 Tage.10 Stunden.34 Minuten"` (39 Zeichen). Korrekt gelesen, aber nicht normalisiert — für Namen/Vergleiche unbrauchbar. |
| `header_size` | **UNKNOWN** | Gelesen (123 oder 125), nie benutzt. Bezug zum Plugin-Offset nicht auflösbar: 168 − 125 = 43. Keine Semantik behaupten. |
| `version0`, `unknown0`, `unknown1`, `unknown2`, 8-Byte-Padding | **UNKNOWN** | Undokumentiert. Kandidat für Save-Typ: `u32` bei `0x89`, Wert `1` in allen 10 Saves — **das ist kein Beweis**. |
| Plugin-Metadaten je Record | **NOT IMPLEMENTED** | `PluginEntry.creation_name`/`creation_id` werden nie gesetzt, bleiben immer `None`. Totes Interface. Metadaten-Block (0–~100 B) bewusst undekodiert. |
| `medium`-Plugin-Block | **PARTIALLY PROVEN** | Formel vorhanden, in 10/10 Saves 0 Einträge — nie mit echten Daten verifiziert. |
| Plugin-Slot → FormID-Master-Index | **NOT PROVEN** | Reihenfolge lesbar, Zuordnung nicht belegt. |
| Save-Typ (Auto/Exit/manuell) | **PARTIALLY PROVEN** | Nur aus Dateinamen-Präfix. `save_number` ist es **nicht**: Autosave1, Autosave3 und Exitsave0 tragen alle 48. |
| FormID-Bezug | **PARTIALLY PROVEN** | Nur `formid_candidates()` gegen externe Textliste, Ergebnis ausdrücklich `UNKNOWN`. |
| Save-Body | **UNKNOWN** | Siehe 3.4. |

### 3.4 Der Save-Body ist nicht erschlossen

Nach dem Plugin-Block liegen 99,98 % der Nutzdaten (Save47: 23.528.266 von 23.533.511 Bytes). Gemessen:

- ESM-Record-Signaturen im Body: `REFR` 0, `ACHR` 0, `CELL` 0, `STDT` 0, `GBFM` 0, `MSTT` 0, `STND` 0, `FORM` 0 Treffer.
- Erste 4 KB: 29,4 % druckbares ASCII, 34,9 % Nullbytes → strukturierte Binärdaten, kein Text, kein TES4-artiger Subrecord-Stream.
- Keine zweite Header-Kopie am Ende (`SFS_SAVEGAME` genau 1× im Payload), kein Footer.
- Charakter-ID aus dem Dateinamen (`0xA7460D2F`) kommt im Payload 0× vor (LE und BE geprüft).

**Folgerung:** Schiffe, Außenposten, Referenzen, verwaiste FormIDs, doppelte Kennungen — alles Aussagen, die einen Body-Parser voraussetzen. Der fehlt nicht „noch", er ist **ohne Formatdefinition nicht machbar**. Diese Punkte bleiben `NOT_CHECKED`, niemals `PASS`.

### 3.5 Vergleichsverhalten auf echten Daten — der zweite große Befund

`analyze_paths()` auf echten Save-Paaren (`audit.py regions`):

| Paar | Abstand | Urteil | Ratio | Cluster |
|---|---|---|---|---|
| Save47 vs Autosave1 | 54 min | `UNSUITABLE` | 83,54 % | **1.636.619** |
| Save47 vs Save46 | 3 Tage | `UNSUITABLE` | 83,09 % | **1.710.666** |

Zwei Spielstände derselben Partie, 54 Minuten auseinander, unterscheiden sich in **83 %** der Bytes. Das Urteil ist deshalb in *jedem* realen Fall `UNSUITABLE` — die Funktion kann auf echten Daten nur „nicht vergleichbar" sagen. Ursache: `max_gap = 0` macht aus jedem Einzelbyte-Wechsel einen eigenen Cluster (1,6 Millionen), und die Ratio-Heuristik (>25 %) schlägt immer an.

Aufgeschlüsselt nach Region:

| Paar | Header+Plugin-Bereich | Body |
|---|---|---|
| Save47 vs Save46 (3 Tage) | 5.245 B, **9 verschieden (0,17 %)** | 83,04 % verschieden |
| Save47 vs Autosave1 (54 min) | 5.245 B, **4.682 verschieden (89,27 %)** | 83,43 % verschieden |

Der zweite Fall zeigt einen **Artefakt-Effekt**: Autosave1 hat `header_size=123`/`plugin_info_offset=166`, Save47 `125`/`168`. Der Block ist um 2 Bytes verschoben, deshalb schlägt der Byte-Vergleich nach dieser Stelle für alles Weitere fehl — obwohl der Inhalt identisch ist. **Byte-Vergleich auf dem Header ist irreführend; nur der Feld-für-Feld-Vergleich (`compare_metadata`) ist dort aussagekräftig.** Das ist im Code bereits richtig gelöst — nur eben nicht überall benutzt.

Zusätzlich irreführend: die UI nutzt `diff_saves()`, dessen Kennzahl `shared_percent` bei abgeschnittener Diff-Liste (`max_diff=500`) systematisch **zu hoch** ausfällt und Übereinstimmung suggeriert, wo keine ist.

### 3.6 Duplikate und Ähnlichkeit — gemessen

| Größe | Ergebnis |
|---|---|
| Distinkte Datei-Hashes | **10 von 10** — kein echtes Duplikat |
| Distinkte Payload-Hashes | **10 von 10** — auch dekomprimiert kein Duplikat |
| Paarweise Byte-Differenz echter Saves | 78,7 % – 84,1 % |

Konsequenz für die Duplikaterkennung: **Byte-Gleichheit ist als Kriterium brauchbar (exakte Duplikate), Ähnlichkeit über Byte-Ratio ist es nicht** — die Streuung im Body ist so hoch, dass jedes Paar „fast verschieden" aussieht. Gleich große Payloads gibt es trotzdem (`ssbm_Autosave1_post_place` und `ssbm_Save42_post_place`: beide 23.399.695 B), also ist **Dateigröße allein kein Duplikatkriterium**.

### 3.7 Identität aus dem Dateinamen — nachgewiesen

Muster an 6 echten Saves:

```
Save47_A7460D2FM436F6C65_021034_20261007143524_24_0_4.sfs
  │      │        │       │              │  │ │
  │      │        │       │              │  │ └ Optionen
  │      │        │       │              │  └ Save-Typ-Kennung
  │      │        │       │              └ Level → == header.player_level (6/6)
  │      │        │       └ Zeitstempel → == header.filetime (6/6)
  │      │        └ Slot-Zähler (nicht eindeutig: Save47 und Autosave2 teilen 021034)
  │      └ Charakterkennung <8 Hex> "M" <Name als Hex>
  └ Save-Name
```

Charakterkennung an zwei unabhängigen Paaren belegt:
`A7460D2F` + `M` + `436F6C65` → `Cole` · `3E3961A0` + `M` + `44414E5445` → `DANTE`

Die 8-stellige Hex-ID ist als **stabiler Schlüssel** brauchbar, ihre Herkunft ist **UNKNOWN** — keine FormID-Semantik darauf bauen (0 Vorkommen im Payload).

### 3.8 Performance — gemessen

`audit.py perf`, 3 Durchläufe je Datei, 8,1 MB Datei → 23,4 MB Payload:

| Phase | Mittel |
|---|---|
| `read_container` | 0,05 ms |
| `decompress` | ~70 ms (dominiert alles) |
| `parse_dat_header` | 0,015 ms |
| `parse_plugin_info` | ~2,7 ms |
| **gesamt** | **76,5 ms Mittel / 73,5 ms Median / 95,7 ms max** |

Und der entscheidende Zusatzbefund (`audit.py scan`):

| Weg | Zeit | 100 Saves |
|---|---|---|
| nur Chunk 0 dekomprimieren | **1,27 ms** | **0,13 s** |
| volle Datei dekomprimieren | 93,5 ms | 9,35 s |

**Header und Plugin-Liste sind vollständig aus Chunk 0 lesbar** (`VALIDATED`, 25 normal, 50 light). Für Identifikation, Integritäts-Vorprüfung und Index braucht man den Body nicht.

---

## 4. Fehlende technische Voraussetzungen

| # | Fehlt | Wirkung | Was konkret an Evidenz fehlt |
|---|---|---|---|
| V1 | Prüfschicht mit Ergebnisobjekt | Kein Status, kein Report, keine Aggregation — Exceptions sind kein Befund | nichts, rein Implementierung |
| V2 | Soll-Ist-Vergleich `len(payload)` vs `uncompressed_size` | Fall E/F bleiben still | nichts |
| V3 | Chunk-Tabellen- und Padding-Arithmetik als Prüfung | Fall A/G/M nur über zlib-Umweg | nichts |
| V4 | Bounds-Checks im DAT-Header-Parser | Gekürzter Puffer → `struct.error` statt Befund | nichts |
| V5 | Semantik von `header_size`, `version0`, `unknown0..2`, 8-B-Padding | I-09 bleibt `UNKNOWN` | Feldbedeutung; nur über Vergleich vieler Save-Versionen oder Engine-RE klärbar |
| V6 | Save-Typ-Feld im Header | Typ nur aus Dateiname | Vergleich mehrerer Save-Arten (Quicksave, Exit, Autosave) aus verschiedenen Quellen |
| V7 | Plugin-Slot → Master-Index | FormID-Auflösung unmöglich | Belegte Zuordnung; ohne Body-Parser nicht abschließend prüfbar |
| V8 | Body-Format | Alles Objektbezogene unmöglich | Formatdefinition; 0 Record-Signaturen gemessen. **Nicht durch Implementierung zu schließen** |
| V9 | Plugin-Metadaten (Creation-ID, Version) | `creation_name`/`creation_id` totes Feld | Metadaten-Blockformat |
| V10 | Verzeichnis-Scan / Index / Hash-Kette | Keine zentrale Verwaltung | nichts |
| V11 | Dateinamen-Parser, `playtime`-Normalisierung | Keine virtuellen Namen | nichts |
| V12 | Aktive Real-Save-Tests | Suite grün ohne echte Daten | nichts — Saves liegen vor, `SAVE_PROBES` muss gesetzt werden |
| V13 | Ein einziger Diff-Pfad | CLI und UI antworten unterschiedlich | nichts |

**V8 ist die einzige Voraussetzung, die nicht durch Implementierung geschlossen werden kann.** Alles andere ist Arbeit, kein Forschungsrisiko.

---

## 5. Konkrete Architekturentscheidung

### 5.1 Entscheidung

**Weiter in Python 3.13, im bestehenden Paket `ssb_i`, ohne neue Abhängigkeit, ohne neue Datenbank, ohne neues Framework.**

Vier neue Module als Schicht über dem vorhandenen Provider, plus zwei chirurgische Erweiterungen im Provider und je ein Integrationspunkt in CLI und UI:

```
                    ┌──────────────────────────────────────────┐
   CLI  sfda  ─────▶│  save_index    (Scan, Index, Historie)   │
   UI   Seite ─────▶│  save_compare  (Identität/Installation/  │
                    │                 Inhalt)                  │
                    │  save_identity (Dateiname, virtueller    │
                    │                 Name, Spielzeit)         │
                    │  save_integrity(CheckResult, run_all)    │
                    └───────────────────┬──────────────────────┘
                                        │ nutzt ausschließlich
                    ┌───────────────────▼──────────────────────┐
                    │  SfsDecodeProvider  (bestehend, 482 Z.)  │
                    │  read_container / decompress /           │
                    │  parse_dat_header / parse_plugin_info    │
                    └──────────────────────────────────────────┘
```

**Begründung in drei Sätzen:** Alle Daten, die für Identifikation, Integrität, Gruppierung, Sortierung und Vergleich nötig sind, liegen bereits nach 1,27 ms im Speicher (Chunk 0) — es fehlt keine Fähigkeit, sondern eine Schicht. Die Integritätsprüfungen sind Arithmetik über ohnehin gelesene Felder und in 10/10 echten Saves bytegenau validierbar; das ist die risikoärmste Erweiterung, die dieses Projekt haben kann. Ein Eingriff in Container-, Header- oder Plugin-Parser ist **nicht** erforderlich, deshalb bleibt der Release 1.0.0 funktional unberührt.

### 5.2 Was ausdrücklich nicht gemacht wird

- **Keine neue Datenbank.** Der Index ist eine JSON-Datei, die aus den Saves jederzeit neu aufbaubar ist. SQLite erst, wenn nachgewiesener Bedarf an Abfragen über mehrere hundert Einträge besteht (heute: 10 Saves, 0,13 s Vollscan).
- **Kein neues Framework.** Kein Pydantic, kein Rich, kein pytest-Plugin. `dataclass` + `json` + `argparse` + `pathlib` reichen; das ist der bestehende Stil des Projekts.
- **Kein Rewrite des Providers.** Zwei kleine Erweiterungen (`read_chunk_table()`, optionaler Längenvergleich in `decompress()`), sonst unverändert.
- **Keine Schreib-, Reparatur- oder Rekompressionsfunktion.** Siehe Abschnitt 8.
- **Kein Rust.** Siehe 6.

### 5.3 Integrationspunkte im Bestand

| Punkt | Datei:Zeile | Änderung |
|---|---|---|
| Provider | `savegame_provider.py:156/190` | `read_chunk_table()` neu; `decompress(verify=True)` optional |
| CLI | `sfda_cli.py:282–306` | vier Subparsers unter `save` |
| UI-Savegame-Seite | `savegame_page.py:174` (Tabs) | Integritäts-Tab |
| UI-Seitenliste | `app.py:260` (`build_pages`) | eine neue Seite, `PAGE_*`-Konstante ergänzen |
| Tests | `tests/test_ssb_i_savegame_container_synthetic.py` | 12 Korruptionsfälle |
| Test-Fixtures | `tests/test_ssb_i_savegame_provider.py:24` | `SAVE_PROBES` als Pflicht, `skip` → `fail` |

Die bestehenden Seiten (`Savegame Analyzer`, `Hex Viewer`, `Event Log`) und die drei belegten `PAGE_*`-IDs bleiben unverändert; `PAGE_PLUGIN/DEPLOY/RUNTIME` (75–78) sind reserviert und werden nicht angefasst.

---

## 6. Python/Rust-Bewertung

Bewertet an acht vorgegebenen Kriterien, jeweils mit Messwert oder konkretem Projektbezug. Skala: ++ klar überlegen · + leicht überlegen · = gleichwertig · − nachteilig.

| Kriterium | Python (Bestand) | Rust (Neuentwurf) | Bewertung |
|---|---|---|---|
| **Wiederverwendung** | 765 Z. Parser + 441 Z. UI + 1.250 Z. Tests direkt nutzbar, `ssb_i` ist bereits Paket | Vollständiger Neubau von Container, Header, Plugin-Logik; Tests müssten portiert werden | **++ Python** |
| **Parser-Sicherheit** | Bounds-Checks fehlen teils (V4), `struct.error` statt Befund; zlib wirft bei Defekt. Fail-closed ist bei der Plugin-Liste bereits umgesetzt (`decode_state`) | Typsicherheit, keine Integer-Überläufe, `Result`-Fehlerbehandlung erzwingt Behandlung | **+ Rust** (theoretisch), praktisch durch V4-Spezifikation neutralisierbar |
| **Fehlerbehandlung** | Exceptions ohne Prüfschicht — genau die Lücke aus 3.2. Eine `CheckResult`-Schicht behebt das unabhängig von der Sprache | `Result<T, E>` + `?` macht stille Fehler schwerer | **= nach Einführung von `CheckResult`** |
| **Performance** | **76,5 ms** je Save (voll), **1,27 ms** über Chunk 0 → **0,13 s für 100 Saves** | Reine Dekompression ist bereits C (zlib); Rust-Gewinn läge im Parsen — das kostet heute **2,7 ms** von 76,5 ms | **=** — kein messbarer Bedarf |
| **Wartbarkeit** | Ein Sprach-Ökosystem, ein Build, ein `.spec`-PyInstaller-Paket, Team-Kontext vorhanden | Zweite Sprache, zweiter Build, PyO3/FFI-Schicht oder CLI-Brücke | **++ Python** |
| **Testbarkeit** | 77 Tests laufen in 1,35 s, synthetische Fixtures vorhanden | Tests müssten neu geschrieben werden; Rust-Tests sind nicht langsamer, aber es fehlt jede Basis | **++ Python** |
| **Entwicklungsaufwand** | P1–P3 ca. 20 h inkl. Tests (Abschnitt 7) | Gleicher Funktionsumfang plus Portierung: grob 3–4× Aufwand, ohne Nutzen | **++ Python** |
| **Interoperabilität** | CLI `sfda`, PySide6-UI, `Starfield-Data-Analysis.spec` — alles Python | Erfordert PyO3-Bindings oder Subprozess + JSON-Protokoll; jedes Interface ist eine neue Fehlerquelle | **++ Python** |

### Ergebnis

**Python bleibt. Rust wird nicht eingeführt.**

Die drei Punkte, an denen Rust theoretisch vorn liegt, halten der Messung nicht stand:

1. **Parser-Sicherheit** — das reale Problem sind fehlende Bounds-Checks (V4), nicht die Sprache. Ein Bounds-Check-Layer ist in Python in wenigen Stunden umgesetzt und sofort testbar.
2. **Performance** — der einzige heiße Pfad ist `zlib.decompress`, und das ist bereits C-Code, den Rust nicht schneller macht. Der gesamte nicht-Dekompressions-Anteil liegt bei 2,7 ms von 76,5 ms. Für den Scan-Fall reduziert die Chunk-0-Optimierung 9,35 s auf 0,13 s — ein Rust-Parser hätte an derselben Stelle 9,3 s gebraucht.
3. **Fehlerbehandlung** — `CheckResult` mit fünf Statuswerten löst das Problem in Python vollständig.

**Wo Rust später sinnvoll werden könnte** — als bedingte Aussage, nicht als Empfehlung:
- Wenn der Body geparst wird und sich zeigt, dass ein vollständiger Scan über hunderte Saves pro Durchlauf nötig ist **und** die Dekompression nicht mehr der Engpass ist. Beides ist heute nicht absehbar.
- Wenn Rekompression für Reparaturfunktionen nötig würde und byte-exakte Ausgabe gefordert ist — auch das ist ohne Formatverständnis nicht erreichbar (Abschnitt 8).

**Eine Bedingung ist an diese Entscheidung geknüpft:** Wenn sich bei P6 (Body-Format) herausstellt, dass ein Parsen des 23-MB-Bodys pro Save im Sekundenbereich liegt und interaktiv nötig ist, wird die Frage neu gestellt — dann mit Messwerten, nicht mit Neigung. Bis dahin gibt es keinen belegten technischen Vorteil.

---

## 7. Implementierungsumfang mit nachvollziehbarem Aufwand

Schätzung in Stunden, Basis: bestehendes Repo, keine neuen Abhängigkeiten, ein Entwickler mit Projektkenntnis. **Schätzung, nicht gemessen** — gemessen sind nur Bestand und Verhalten (Abschnitte 1–3).

| Paket | Inhalt | Neue LOC | Tests | Stunden |
|---|---|---|---|---|
| P1 `save_integrity.py` | `CheckResult`, 12 Checks (I-01…I-14 ohne I-13), `run_all()` | 320 | 180 | 5,0 |
| P1b Provider-Erweiterung | `read_chunk_table()`, `decompress(verify)`, Bounds-Checks | 80 | 60 | 2,0 |
| P2 `save_identity.py` | Dateinamen-Parser, `playtime`-Normalisierung, virtueller Name, Gruppierung/Sortierung | 220 | 120 | 3,5 |
| P3 `save_index.py` | Scan, JSON-Index, Hashes, Duplikaterkennung, Historie | 280 | 130 | 4,5 |
| P4 `save_compare.py` | Drei-Ebenen-Vergleich, Plugin-Mengendifferenz, Regionen-Klassifikation | 300 | 150 | 5,0 |
| P5 Organisation | Backup-Kopie+Manifest, Quarantäne-Markierung, Export | 250 | 100 | 4,0 |
| CLI | `save verify/list/scan/compare` | 120 | 80 | 2,0 |
| UI | Integritäts-Panel + Save-Browser-Seite | 300 | 90 | 5,0 |
| **Summe** | | **1.870 LOC** | **910 LOC** | **31,0 h** |

Nachrechnung: 320+80+220+280+300+250+120+300 = **1.870**. Tests: 180+60+120+130+150+100+80+90 = **910**. Stunden: 5,0+2,0+3,5+4,5+5,0+4,0+2,0+5,0 = **31,0**.

**Nicht enthalten und nicht schätzbar:** P6 (Body-Format-Forschung). Aufwand dort ist nicht abschätzbar, weil die Formatdefinition fehlt — jede Zahl wäre erfunden.

**Empfohlene Zuschnitt-Variante (P1+P1b+P2, „erste auslieferbare Erweiterung"):** 620 LOC Produktion, 360 LOC Tests, **10,5 Stunden**. Das liefert Integritätsstatus und virtuelle Namen — die zwei Funktionen, die aus dem vorhandenen Datenbestand sofort echten Nutzen ziehen.

---

## 8. Risiken und Sicherheitsanforderungen

### 8.1 Risiken

| # | Risiko | Schwere | Gegenmaßnahme |
|---|---|---|---|
| R1 | **Falsches Grün.** Ein „PASS" wird als Ladbarkeits-Garantie gelesen | hoch | Jeder Report trägt den Satz aus 9.4 wörtlich; `PASS` heißt ausschließlich „Kriterium dieser einen Prüfung erfüllt" |
| R2 | **`chunk_count` ist eine Ableitung**, belegt nur für Save-Version 153 / Engine 27 | mittel | Bei `save_version != 153` oder `engine_version != 27` → I-03/I-07 auf `UNKNOWN`, nicht auf `PASS` |
| R3 | **Verschiebungsartefakt** im Header-Byte-Vergleich (belegt: 89,27 % „Unterschied" bei identischem Inhalt) | mittel | Header/Plugin nur feldweise vergleichen; Byte-Diff dort nur als Indikator mit explizitem Hinweis |
| R4 | **Tote Real-Save-Tests** — Suite grün ohne echte Daten | hoch | `SAVE_PROBES` als Pflicht-Fixture, `pytest.fail` statt `skip` |
| R5 | **Zwei Diff-Pfade** liefern unterschiedliche Antworten | mittel | P4 führt sie zusammen; `diff_saves()`/`shared_percent` als irreführend entfernen oder umbiegen |
| R6 | **Body-Blackbox** verleitet zu Produktaussagen über Schiffe/Außenposten | hoch | In UI und Doku als nicht verfügbar kennzeichnen; keine Objekt-Felder im Datenmodell anlegen, bevor ein Parser existiert |
| R7 | **Dateinamen-Identität** wird als FormID missverstanden | niedrig | Feld heißt `character_key`, nicht `form_id`; Dokumentation der Herkunft `filename` |
| R8 | **Stiller Datenverlust** (Fall F) in jeder Pipeline, die heute `decompress()` aufruft | hoch | P1b: Längenvergleich standardmäßig aktiv |

### 8.2 Sicherheitsanforderungen (verbindlich)

1. **Read-only gegen den Spielordner.** Die Anwendung öffnet Saves ausschließlich mit `"rb"`. Kein `rename`, kein `unlink`, kein `open(..., "wb")` auf einem Pfad innerhalb des Starfield-Save-Verzeichnisses — auch nicht „nur zum Testen".
2. **Schreibziele nur außerhalb des Spielordners**, explizit vom Nutzer gewählt, mit Anzeige des Zielpfads vor der Aktion.
3. **Vor jeder Kopie ein Hash, nach jeder Kopie eine Gegenprüfung.** Ein Backup gilt erst als erstellt, wenn `sha256(Kopie) == sha256(Quelle)`.
4. **Keine Reorganisation, keine Reparatur, kein Rekomprimieren** — solange das Body-Format und die Schreiboperationen nicht nachgewiesen verstanden sind. Das ist keine Vorsicht, sondern eine Messaussage: Der Body ist zu 99,98 % undurchsichtig (3.4), und es existiert **kein** Code, der einen Save schreiben könnte.
5. **Quarantäne ist eine Markierung, keine Dateioperation.** Ein `FAILED`-Save wird im Index gekennzeichnet; verschoben wird nur auf ausdrückliche, einzelne Bestätigung.
6. **Kein Netzwerk.** Save-Analyse ist lokal; keine Uploads, keine Telemetrie.
7. **Keine Änderung an Release 1.0.0.** Neue Module und Seiten sind additiv; `VERSION` in `ssb_i/product.py` bleibt, bis ein neuer Release beschlossen ist.

---

## 9. Teststrategie

### 9.1 Ebenen

| Ebene | Was | Basis |
|---|---|---|
| **Synthetisch** | Container-Geometrie, alle 12 Korruptionsfälle, Header-Feldgrenzen, Plugin-Kette | vorhandenes Muster in `test_ssb_i_savegame_container_synthetic.py` |
| **Real-Save** | 6 echte Saves als Pflicht-Fixtures (`SAVE_PROBES`) | vorhandene Verdrahtung, heute ungenutzt |
| **Golden** | feste Erwartungswerte je Save: 25 normal/50 light, `uncompressed_size`, `filetime`, `header_size` | mit Anschlagzeile, damit Datenbasis-Änderung auffällt |
| **Negativ** | jeder `PASS`-Check braucht mindestens einen manipulierten Fall, der `FAILED` erzeugt | Pflicht, kein Check ohne Falsifikationsfall |
| **UI (offscreen)** | `QT_QPA_PLATFORM=offscreen`, Seiten bauen, Save laden, Integritäts-Panel füllen | vorhandene UI-Tests |

### 9.2 Falsifikationsmatrix (aus den Messungen abgeleitet)

| Check | Muss `FAILED` liefern bei | Darf `PASS` bleiben bei |
|---|---|---|
| I-01 Magic | `XXXX` statt `BCPS` | intaktem Save |
| I-03 Tabellen-Geometrie | verschobenem `compressed_offset` | Alignment-Füllung (Autosave2, 12 B) |
| I-04 Padding-Summe | Truncation, angehängten Bytes | intaktem Save |
| I-05 Dekompression | Bitflip, Padding 0 | intaktem Save |
| I-06 Länge | `uncompressed_size` +1 | intaktem Save |
| I-07 Chunk-Anzahl | `chunk_size_pre` ×2 | intaktem Save |
| I-10 Plugin-Grenzen | `plugin_info_offset` hinter Dateiende | `medium = 0` |

Die drei stillen Fälle E/F/G aus 3.2 sind damit abgedeckt: E → I-06 `FAILED`, F → I-06 `FAILED` (50,4 % geliefert), G → I-04 `PASS` mit Notiz „4 Zusatzbytes in Chunk 0, Nutzdaten vollständig".

### 9.3 Abnahmekriterien für P1

1. Alle 13 Fälle aus `audit.py integrity` werden korrekt klassifiziert (`FAILED` bzw. `PASS` mit Begründung).
2. `sfda save verify` endet bei `FAILED` mit Exit-Code ≠ 0.
3. Die 6 echten Saves liefern reproduzierbar denselben Gesamtstatus.
4. Kein Test überspringt sich stillschweigend: fehlt ein Referenz-Save, schlägt der Lauf fehl.
5. Testlauf bleibt unter 5 s und ohne Netzwerk.

### 9.4 Grenze jeder Teststrategie

Ein bestandener statischer Test ist **kein** Nachweis der Ladbarkeit. Keine Prüfung dieses Pakets öffnet das Spiel oder prüft Engine-interne Invarianten. Ein Save kann alle Checks mit `PASS` bestehen und beim Laden scheitern. Dieser Satz gehört in den Report, den die CLI ausgibt, nicht nur in die Doku.

---

## 10. Empfohlene erste umsetzbare Erweiterung

**P1 + P1b: Integritätsprüfung mit Ergebnisobjekt.**

Warum genau dieses Paket zuerst:

1. **Kein neues Formatwissen.** Alle Prüfungen sind Arithmetik über Felder, die heute schon gelesen werden. Kein Risiko, sich in unbelegter Semantik zu verlieren.
2. **Sofort validierbar.** I-04 ist in 10/10 echten Saves bytegenau erfüllt — das Kriterium ist an realen Daten bewiesen, nicht angenommen.
3. **Schließt den gefährlichsten Fehler.** Fall F (halbierte Datei sieht vollständig aus) ist heute möglich und wird von keiner Stelle gemeldet.
4. **Klein und unabhängig.** 400 LOC Produktion + 240 LOC Tests, ~7 Stunden, keine Berührung von UI oder CLI-Struktur. `sfda save verify` ist ein zusätzliches Subkommando.
5. **Voraussetzung für alles Weitere.** Index, Historie, Quarantäne und Vergleich brauchen einen Status, den sie speichern und vergleichen können.

Konkreter Zuschnitt:

```
ssb_i/save_integrity.py      CheckResult, checks I-01..I-12, run_all()
ssb_i/savegame_provider.py   + read_chunk_table()
                             + decompress(verify: bool = True)
sfda_cli.py                  + sfda save verify <save.sfs> [--json]
tests/                       + 12 Korruptionsfälle, + Real-Save-Pflicht
```

Danach P2 (Identität + virtuelle Namen) als zweiter Schritt — es ist das, was Nutzer unmittelbar sehen.

---

## Gesamtbefund

### Was können wir bereits?

Den **Container vollständig und zuverlässig lesen**: BCPS-Header, zlib-Chunking, Padding-Arithmetik bytegenau in 10/10 echten Saves. Den **`SFS_SAVEGAME`-Header in 17 Feldern** dekodieren (Name, Level, Ort, Rasse, Geschlecht, EXP, Spielzeit, FileTime, Spiel-/Engine-Version). Die **Plugin-Liste selbst-validierend** auslesen (25 normal + 50 light, `VALIDATED` in 10/10). Aus dem **Dateinamen Charakterkennung, Zeitstempel und Level** ableiten, belegt gegen den Header. Und das **in 76 ms je Save bzw. 1,27 ms über Chunk 0**.

### Was können wir kurzfristig ergänzen?

Integritätsprüfung mit fünfwertigem Status (P1, ~7 h), virtuelle Namen samt Gruppierung und Sortierung (P2, ~3,5 h), Index mit Duplikaterkennung und Prüfhistorie (P3, ~4,5 h), Plugin-Mengendifferenz und regionenbewusster Vergleich (P4, ~5 h), Backup und Quarantäne-Markierung (P5, ~4 h). Zusammen rund 31 Stunden für den vollen Umfang, davon 10,5 Stunden für den ersten auslieferbaren Zuschnitt. Nichts davon braucht neues Formatwissen.

### Was ist technisch noch nicht möglich?

**Alles Objektbezogene.** Schiffe, Außenposten, Referenzen, verwaiste FormIDs, doppelte Kennungen — der Body ist zu 99,98 % undurchsichtig, enthält null ESM-Record-Signaturen, und die Charakter-ID aus dem Dateinamen kommt darin nicht vor. Diese Punkte bleiben `NOT_CHECKED`. Ebenso ungeklärt: Bedeutung von `header_size` und den `unknown*`-Feldern (UNKNOWN), Save-Typ als Header-Feld (nur Dateiname belegt), Plugin-Metadaten je Eintrag (totes Interface), `medium`-Block (0 Einträge in allen Saves). Und: **Rekompression, Reparatur, Reorganisation** — nicht weil es verboten ist, sondern weil es keinen Code und kein Formatverständnis dafür gibt.

### Was sollte als Erstes implementiert werden?

**`ssb_i/save_integrity.py` + `sfda save verify`.** Es schließt den einzigen Fehler, der heute still zu falschen Ergebnissen führt (Fall F: halbierte Datei wird als vollständig gemeldet), ist an realen Daten bytegenau validierbar, berührt weder Release 1.0.0 noch bestehende Parser und ist die Voraussetzung dafür, dass Index und Historie später einen Status speichern können.

### Welche realistischen Produktmöglichkeiten entstehen daraus?

1. **„Ist mein Spielstand in Ordnung?"** — eine konkrete, ehrliche Antwort mit sieben bis zwölf Einzelprüfungen und expliziter Aussage, was *nicht* geprüft wurde. Das ist der Kern, den kein bestehendes Save-Tool für Starfield liefert.
2. **Zentrale Savegame-Übersicht** über alle Charaktere: virtueller Name, Charakter, Level, Spielzeit, Datum, Plugin-Anzahl, Integritätsstatus, Auffälligkeiten — sortier- und gruppierbar, ohne eine einzige Datei umzubenennen.
3. **Installations-Diagnose**: „dieser Spielstand erwartet 75 Plugins, 3 davon fehlen in deiner Installation" — praktisch wertvoll und vollständig aus vorhandenen Daten ableitbar, sobald P4 steht.
4. **Backup mit Nachweis**: Kopie plus Hash-Gegenprüfung plus Manifest — nachvollziehbar statt „ich habe da eine Kopie gemacht".
5. **Prüfhistorie**: pro Charakter eine chronologische Kette mit Level-/Spielzeit-Verlauf und Installationswechseln. Das ist die Stelle, an der Auffälligkeiten ohne Objekt-Semantik belastbar werden.

Nicht Teil dieser Möglichkeiten und ausdrücklich nicht versprochen: Aussagen über Schiffe, Außenposten oder die tatsächliche Ladbarkeit im Spiel.

---

## Nachtrag 08.11.2026 — Korrekturen aus der externen Tooling-Recherche

Quelle: `EXTERNAL_SAVEGAME_TOOLING_AUDIT.md`. Alle Korrekturen sind an den sechs echten Saves nachgemessen (6/6), Prüfskripte `~/ssb_save_audit/verify_*.py`.

| Stelle | Bisherige Aussage | Korrigiert |
|---|---|---|
| 1.3 / 3.3, `medium`-Block | „in allen 10 Saves 0 Einträge — nie mit echten Daten verifiziert" | **5 Medium-Plugins pro Save.** Der Block endet mit Metadaten bytegenau bei `plugin_info_offset + plugin_info_size` (Delta 0 in 6/6). Die fünf sind in allen Saves identisch: `SFBGS003.esm`, `SFBGS006.esm`, `PersonalSpacestation.esm`, `RRLAC …`, `RRLNA …`. |
| 2.1 (Plugin-Zahl) | „25 normal + 50 light" | **25 normal + 50 light + 5 medium = 80.** `sfda save info` meldet heute 75 — die Produktausgabe ist unvollständig. |
| 4, V9 | Plugin-Metadaten „totes Interface, NOT IMPLEMENTED" | **Format bekannt und dekodierbar:** `u8 extraInfo`; bei 1 folgen `creationName`, `creationId`, `flags`, `achievementFriendly`. In Save47: 6 von 80 Records mit echter `TM_…`-Creation-ID und Name, 65 mit leerem Namen/ID und Engine-Platzhalter in `flags`, 9 Game-Plugins. V9 damit **geschlossen**. |
| 3.4 | Body „99,98 % undurchsichtig, keine Struktur" | **Kopfstruktur erschlossen:** Pointer-Tabelle (`u16` + 12×`uint` + 52 B Padding) und ein String-Array mit **1.709–1.735 Einträgen**, 99,6 % druckbar, 0 Duplikate, in 6/6 Saves vollständig parsbar. Inhalte sind Item-Namen mit Legendary-Modifikatoren und Animationspfade. |

**Was ausdrücklich weiter gilt:** Die Record-Ebene des Bodys bleibt unbelegt — es gibt **keine** Zuordnung String → Record → FormID, und die zehn übrigen Pointer sind unbedeutet. Objekt-, Referenz- und FormID-Prüfungen bleiben `NOT_CHECKED`. Die drei stillen Integritätsfehler (Fall E/F) bleiben unverändert. Es gibt weiterhin keinen Grund, Schreib- oder Reparaturfunktionen zu bauen — auch nicht, weil das offizielle Nexus-Tool in v1.1.0 einen Write-Proof-of-Concept belegt: ein PoC ist keine Sicherheit.

**Zusätzlicher Integritätsansatz:** Dass der Plugin-Block bei 80 Einträgen exakt am deklarierten Ende aufgeht, ist ein starkes zusätzliches Kriterium für I-11 (Plugin-Listen-Selbstvalidierung) und sollte dort als Pflichtprüfung aufgenommen werden.

---

## Nachtrag 08.11.2026 (2) — Umsetzungsstand Version 1.5.3

Der Audit beschreibt den Ist-Zustand von 1.0.0. Seit 1.5.3 umgesetzt und durch Tests belegt (Details: `SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md`):

| Audit-Punkt | Stand |
|---|---|
| P1 Integrität (Abschnitt 3) | **implementiert** — `ssb_i/save_integrity.py`, 14 Prüfungen, `sfda save verify`, UI-Tab |
| Medium-Kette (Nachtrag 1) | **implementiert** — 25/50/5 = 80 in 6/6 Saves, Blockende bytegenau |
| Plugin-Metadaten (V9) | **implementiert** — `present`/`absent`/`unreadable`, Platzhalter normalisiert |
| String-Pool (Nachtrag 1) | **implementiert** — `read_string_pool()`, 6/6 OK, ohne Objektanspruch |
| Die drei stillen Integritätsfälle (3.2) | **behoben** — E/F → FAILED, G → WARNING mit `unverified` |
| Real-Save-Tests (1.2) | **aktiviert** — Pflicht-Fixture, 0 Skips im Save-Bereich |

**Unverändert offen und weiterhin `UNKNOWN`/`NOT_CHECKED`:** Objekt-, Referenz- und FormID-Ebene, Record-Format des Bodys, `headerSize`-Semantik, die elf übrigen Body-Pointer. Die Aussage aus Abschnitt 3.4 bleibt in Kraft: eine bestandene statische Prüfung ist kein Nachweis der Ladbarkeit.

