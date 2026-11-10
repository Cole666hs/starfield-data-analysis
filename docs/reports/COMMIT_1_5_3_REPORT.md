# COMMIT_1_5_3_REPORT

**Projekt:** Starfield Data Analysis · **Organisation:** Entropy Development
**Version:** 1.5.3 · **Datum:** 08.11.2026
**Auftrag:** unabhängige Abschlussprüfung und kontrollierter Produktcommit

---

## 1. Ausgangs-HEAD

| Feld | Wert |
|---|---|
| Branch | `main` |
| HEAD vor dem Commit | `9006753` — „docs: rewrite BUILD/REPRODUCIBILITY in plainer prose; correct the tag/commit mapping" |
| Working Tree | 9 modifizierte, 11 untracked Einträge (4 Audit-Dokumente, `audit/` mit 2 Dateien, 5 Produkt-/Testdateien) |
| Bestehende Änderungen verworfen | **keine** — kein `git reset`, kein `checkout`, kein `clean` ausgeführt |
| Git-Identität | `Entropy Development <dev@entropy-development.invalid>` (bereits konfiguriert, kein `--author`-Eingriff) |

---

## 2. Geprüfte Änderungen

**Vollständige Diff-Prüfung:** `git diff` (1141 Einfügungen, 366 Löschungen über 9 Dateien) plus die 5 neuen Dateien, jede einzeln gelesen.

### 2.1 Risikomuster-Scan

| Suchmuster | Treffer | Bewertung |
|---|---|---|
| Schreibzugriffe (`open(...,'w')`, `write_bytes`, `shutil.*`, `os.remove/unlink/rename`) | 2 | **harmlos** — `tests/...:damaged.write_bytes()` schreibt eine Kopie nach `tmp_path`; `for token in ('"wb"', …)` ist der Read-only-Regressionstest, der Schreibmodi *sucht* |
| Lokale Pfade (`/home/…`, `C:\`, Benutzername) | 1 | **harmlos** — Docstring in `test_ssb_i_savegame_provider.py`, der die *entfernten* alten `/tmp`-Fixtures dokumentiert |
| Debug-Reste (`pdb`, `breakpoint`, `FIXME`, `HACK`) | 0 | — |
| `print()` | 1 | legitime CLI-Ausgabe der String-Pool-Tabelle |

Im **gestagten** Diff: 0 Treffer bei lokalen Pfaden und Schreibpfaden außerhalb von Test-Kopien.

### 2.2 Die neun geforderten Prüfpunkte

| # | Prüfpunkt | Befund | Beleg |
|---|---|---|---|
| 1 | Medium-Kette 25/50/5 | **bestätigt** | 6/6 reale Saves; `test_plugin_counts_match_golden`, `test_medium_chain_is_not_dropped` |
| 2 | Plugin-Gesamtzahl 80 | **bestätigt** | CLI-Ausgabe `… 5 medium \| 80 total`; `test_cli_reports_same_plugin_total` |
| 3 | Metadaten und Platzhalterbehandlung | **bestätigt** | 6 `present`, 0 `unreadable`; Platzhalter `18446744073709551615.undefined` → `None`; `test_engine_placeholder_is_normalised_to_none`, `test_metadata_is_not_taken_from_neighbour` |
| 4 | String-Pool mit strengem Pointer-Gating | **bestätigt** | Gating auf `unlock == 1`, `unknown0 == 1`, `pointer[2] == block2`; Verstoß → `UNKNOWN` mit leerer Liste; `test_broken_pointer2_yields_unknown_not_guess`, `test_wrong_marker_yields_unknown` |
| 5 | Integritätsprüfungen I-01 bis I-14 | **bestätigt** | 14 von 14 vorhanden und registriert; JSON-Ausgabe liefert `I-01 … I-14` lückenlos |
| 6 | Trennung `total` / `total_with_gaps` | **bestätigt** | Save47: `total = PASS`, `total_with_gaps = NOT_CHECKED`, `coverage.assessed = 10/14`, `gaps = [I-09, I-12, I-13, I-14]` |
| 7 | CLI- und UI-Konsistenz | **bestätigt** | `test_savegame_page_integrity_matches_cli` vergleicht den Gesamtstatus beider Wege; `test_cli_reports_same_plugin_total` vergleicht Zählwerte |
| 8 | Keine Savegame-Schreib- oder Reparaturfunktion | **bestätigt** | `test_savegame_provider_is_read_only` inspiziert jeden öffentlichen Provider-Aufruf auf `"wb"`/`"w"`/`"ab"`; `test_read_only_no_file_is_written` vergleicht Größe, mtime und Inhalt. Einzige Schreibpfade im Repo sind Report-Dateien (`savegame_differential.write_reports`, unverändert) |
| 9 | Keine unbelegten Aussagen zu Objektidentität oder Ladbarkeit | **bestätigt** | `FormID` erscheint ausschließlich im Disclaimer und in I-13 (`NOT_CHECKED`); `read_string_pool` trägt die Grenze im Rückgabewert (`note`) und in `unverified_pointers` |

---

## 3. Ausgeschlossene Dateien

Bewusst **nicht** im Commit — bleiben unverändert im Working Tree:

| Datei | Grund |
|---|---|
| `SAVE_INTELLIGENCE_AUDIT.md` | unabhängiger Analysebericht |
| `SAVE_INTELLIGENCE_SPEC.md` | unabhängige Spezifikation |
| `EXTERNAL_SAVEGAME_TOOLING_AUDIT.md` | Fremdprojekt-Recherche |
| `SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md` | Implementierungsbericht |
| `COMMIT_1_5_3_REPORT.md` (diese Datei) | Abschlussbericht |
| `audit/save-intelligence/audit.py` | Messwerkzeug, keine Produktimplementierung |
| `audit/save-intelligence/verify_external_format.py` | Verifikationswerkzeug, keine Produktimplementierung |

Begründung: Der Auftrag gestattet ausschließlich Produktimplementierung und die dafür erforderlichen Produkt-Tests. Messwerkzeuge und Berichte sind keins von beidem.

---

## 4. Testergebnis

```
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
→ 155 passed, 19 skipped in 13.79s
```

**Identisch zum Stand vor dem Commit** (155/19) — keine Abweichung, keine Ursachenforschung nötig.

Die 19 Skips, vollständig aufgezählt:

| Anzahl | Datei | Grund |
|---|---|---|
| 17 | `test_ssb_pe_lib.py`, `test_ssb_pe_lib_vtable.py` | Trust-Root-Binary nicht gesetzt bzw. `capstone` nicht installiert |
| 1 | `test_ssb_i_cli.py:201` | kein `Starfield.exe` vorhanden |
| 1 | `test_ssb_pe_lib.py:125` | `capstone` nicht installiert |

**Kein Savegame-Test wird übersprungen.** Alle 76 Tests gegen die sechs realen Spielstände liefen ausgeführt durch.

---

## 5. Reale Savegame-Prüfung

Gegen `Save47_A7460D2FM436F6C65_021034_20261007143524_24_0_4.sfs`:

**`sfda save info`**
```
Plugins       VALIDATED | 25 normal | 50 light | 5 medium | 80 total
Plugin types  9 game | 71 mod | 6 with creation metadata
Note: 25 normal, 50 light, 5 medium (declared 25/50/5); 9 game + 71 mod plugins; block delta 0 bytes
```

**`sfda save verify`** → Exit-Code **0**, Gesamtstatus `PASS`, Abdeckung `10 von 14 bewertet`, `NICHT BEWERTET: I-09, I-12, I-13, I-14`, Disclaimer vorhanden.

**JSON-Ausgabe `save verify --json`**
```
checks: 14 | I-01 ... I-14   (keine Lücke)
total            : PASS
total_with_gaps  : NOT_CHECKED
coverage         : {PASS: 10, UNKNOWN: 1, NOT_CHECKED: 3, FAILED: 0, WARNING: 0, assessed: 10, total: 14}
gaps             : ['I-09', 'I-12', 'I-13', 'I-14']
```

**JSON-Ausgabe `save strings --json --limit 3`**
```
status: OK | count: 1709 | truncated: true
note  : Text-Pool ohne Objektidentitaet: keine FormID-, Record- oder …
entry : {'index': 0, 'length': 8, 'offset': 21442455, 'status': 'ok', 'text': 'Sequence'}
```

**Exit-Code-Prüfung:** `save verify` liefert 0 bei PASS. Der Nicht-Null-Pfad ist durch `test_cli_verify_exit_code_nonzero_on_failure` abgedeckt (Fall E → Exit ≠ 0, „FAILED" in der Ausgabe) und wurde zusätzlich manuell gegen eine manipulierte Kopie verifiziert.

`sfda --version` → `sfda 1.5.3 - Starfield Data Analysis (Entropy Development)`

---

## 6. SHA-256-Ergebnisse

Alle sechs Originale **unverändert**, identisch zu den vor dem Auftrag dokumentierten Werten:

```
c9b1bb5b4422fd784ba4158069111cad3a62036dad4513738c8564ccc3439e71  Autosave1_A7460D2FM436F6C65_021105_20261007152914_24_0_4.sfs
451ca3e3b8b7b70b9882b7d9404b3e3c758248b0349a7df2fe831804a0434ca1  Autosave2_A7460D2FM436F6C65_021034_20261007143501_24_0_4.sfs
073f355cb3a4481867129be7f8cbce8f7c3a2d65c07e78b09bc3aef7b6f421b6  Autosave3_A7460D2FM436F6C65_021055_20261007151825_24_0_4.sfs
53df16b41a7eeb4fa4275e00339cfa0c9202ead27448a6d782b45e198123294f  Exitsave0_A7460D2FM436F6C65_021035_20261007143648_24_0_4.sfs
174b9310c9f60757abc7f2e66b8091595dfd12502c2aca08bac0fb673bc80f2b  Save46_A7460D2FM436F6C65_021033_20261004175306_24_0_4.sfs
bbfaba67aa07cbfdffcae59671211f0e064c632d3c9d518432a920fa69f267d8  Save47_A7460D2FM436F6C65_021034_20261007143524_24_0_4.sfs
```

Die Werte stimmen mit `SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md` Abschnitt 11 überein. Kein Testlauf hat eine Originaldatei angefasst.

---

## 7. Commit-Hash und Message

| Feld | Wert |
|---|---|
| **Commit-Hash** | `ed5587acd99b6a45982b0c0a55ad11afb5e50d9a` (kurz `ed5587a`) |
| **Message** | `feat(savegame): add integrity checks and extended save parsing` |
| Autor | Entropy Development `<dev@entropy-development.invalid>` |
| Branch | `main` |
| Eltern-Commit | `9006753` |

Der Commit enthält Version 1.5.3: `ssb_i/product.py` ist die einzige Versionsquelle, CLI und UI leiten daraus ab.

---

## 8. Enthaltene Dateien

14 Dateien, 2852 Einfügungen, 366 Löschungen:

| Status | Datei |
|---|---|
| M | `CHANGELOG.md` |
| M | `sfda_cli.py` |
| M | `ssb_i/product.py` |
| **A** | `ssb_i/save_integrity.py` |
| M | `ssb_i/savegame_provider.py` |
| M | `ssb_ui/pages/savegame_page.py` |
| **A** | `tests/conftest.py` |
| M | `tests/test_ssb_i_cli.py` |
| M | `tests/test_ssb_i_plugin_parsing.py` |
| **A** | `tests/test_ssb_i_real_saves.py` |
| **A** | `tests/test_ssb_i_save_integrity.py` |
| M | `tests/test_ssb_i_savegame_provider.py` |
| **A** | `tests/test_ssb_i_string_pool.py` |
| M | `tests/test_ssb_ui_pages.py` |

Staging erfolgte ausschließlich über 14 explizite Dateipfade — kein `git add -A`, kein `git add .`, kein Glob.

---

## 9. Verbleibende Änderungen

Nach dem Commit, unverändert im Working Tree:

```
?? EXTERNAL_SAVEGAME_TOOLING_AUDIT.md
?? SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md
?? SAVE_INTELLIGENCE_AUDIT.md
?? SAVE_INTELLIGENCE_SPEC.md
?? COMMIT_1_5_3_REPORT.md            (diese Datei)
?? audit/save-intelligence/audit.py
?? audit/save-intelligence/verify_external_format.py
```

Keine Bereinigung durchgeführt: kein `git clean`, kein `git stash`, kein Löschen. Keine modifizierten, nicht committeten Produktdateien — der Produktstand ist vollständig im Commit.

---

## 10. Versionskonsistenz — geprüft, bewusst nicht geändert

| Quelle | Wert | Bewertung |
|---|---|---|
| `ssb_i/product.py:22` | `VERSION = "1.5.3"` | **einzige Versionsquelle** |
| CLI `sfda --version` | `sfda 1.5.3 …` | abgeleitet, konsistent |
| UI-Fenstertitel | aus `PRODUCT_VERSION` abgeleitet | abgeleitet, konsistent |
| `CHANGELOG.md` | Abschnitt „1.5.3 — 2026-11-08" | konsistent |
| `tests/test_ssb_ui_pages.py` | prüft `VERSION == "1.5.3"` | Testschutz vorhanden |
| `INSTALL.md`, `requirements.txt` | nennen 1.0.0 | **nicht geändert** (siehe unten) |
| `REPRODUCIBILITY.md`, `LICENSE.txt` | 1.0.0-Artefakt-Hashes, „version 1.0.0 and later" | **nicht geändert** — historisch bzw. rechtlich korrekt |

**Entscheidung:** `INSTALL.md` und `requirements.txt` bleiben auf 1.0.0. Sie beschreiben das **veröffentlichte** Paket einschließlich des Download-Dateinamens `Starfield-Data-Analysis-1.0.0-linux-x86_64.zip`. Ein 1.5.3-Archiv existiert nicht; ein Bump würde eine Anleitung erzeugen, die auf eine nicht existierende Datei zeigt — also eine neue Inkonsistenz statt einer behobenen. Diese Dateien werden beim nächsten tatsächlichen Release neu erzeugt. Das ist eine bewusste Entscheidung, keine Auslassung.

Keine echte Inkonsistenz in den tatsächlich verwendeten Versionsquellen.

---

## Abschließendes Urteil

# COMMITTED

Alle Prüfungen erfolgreich:

- Diff vollständig geprüft, keine fremden oder unzugehörigen Änderungen
- alle neun inhaltlichen Prüfpunkte bestätigt
- Tests 155 passed / 19 skipped, ausschließlich PE-Skips, kein Savegame-Skip
- CLI, JSON und UI konsistent, Exit-Codes korrekt
- Version 1.5.3 in der einzigen Quelle hinterlegt, CLI und UI leiten ab
- sechs Original-Saves SHA-256-identisch
- Staging ausschließlich über 14 explizite Pfade, gestagter Diff vor dem Commit geprüft
- Audit-Dokumente und Messwerkzeuge weiterhin unverändert im Working Tree

**Kein Push. Keine Veröffentlichung. Keine weiteren Implementierungen.** Der Commit liegt lokal auf `main`.
