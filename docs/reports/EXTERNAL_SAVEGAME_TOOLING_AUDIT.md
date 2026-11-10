# EXTERNAL_SAVEGAME_TOOLING_AUDIT

**Projekt:** Starfield Data Analysis (SSB-I) · Entwickler: Entropy Development
**Erstellt:** 08.11.2026 · **Modus:** read-only Recherche + Verifikation gegen eigene Saves
**Ergänzt:** `SAVE_INTELLIGENCE_AUDIT.md`, `SAVE_INTELLIGENCE_SPEC.md` (dortige Nachträge verweisen hierher)
**Keine Implementierung, keine Schreiboperation auf Saves, kein Release-Eingriff.**

---

## 0. Zusammenfassung

Drei Dinge sind wichtiger als die Mod-Liste selbst:

1. **Die im Auftrag genannte Nexus-ID 10457 ist nicht der Save Cleaner.** Sie gehört zu „Starfield Engine Fixes – SFSE" von LarannKiar. Ein Starfield-Save-Cleaner existiert auf Nexus **nicht** — belegt über zwölf Suchläufe, dokumentiert in Abschnitt 2.
2. **Die Formatdokumentation des offiziellen Nexus-Tools hat drei Lücken in unserem Audit geschlossen** — alle drei gegen unsere sechs echten Saves verifiziert: unser Parser **verliert 5 Medium-Plugins pro Save**, die **Plugin-Metadaten sind jetzt dekodierbar** (V9 schließbar), und der **Body ist nicht undurchsichtig** — er beginnt mit einer Pointer-Tabelle auf eine String-Tabelle mit 1709–1735 lesbaren Einträgen.
3. **Das offizielle Tool ist auf Save-Version 140 eingefroren** (Stand 02.09.2024), unsere Saves sind 153. Wir sind dem Referenzwerkzeug damit voraus, nicht hinterher — aber es bedeutet auch: die externe Doku beschreibt einen älteren Formatstand und ist gegen unseren Bestand zu prüfen, nicht zu übernehmen.

Nexus-Endorsements wurden ausschließlich zur Priorisierung der Recherche benutzt. Kein Projekt gilt hier wegen seiner Downloadzahl als technisch belegt.

---

## 1. Methode, Zugriffswege, Grenzen

**Zugriffswege, die tatsächlich funktioniert haben:**

| Weg | Status | Nutzung |
|---|---|---|
| Nexus **GraphQL v2** (`api.nexusmods.com/v2/graphql`) | funktioniert, Key gültig (Cole666hs, Supporter) | Suche über Titel, Beschreibung, Autor; Sortierung, Pagination |
| Nexus **REST v1** (`/v1/games/starfield/mods/{id}.json`) | funktioniert | Detailfelder, Beschreibung (BBCode), Changelogs |
| `jarvis-scrape` (Playwright, DISPLAY=:99) | funktioniert | Abgleich Website ↔ API |
| GitHub raw / `gh api` | funktioniert | Quellcode, Templates, READMEs, CHANGELOGs |
| `web_extract` | **nicht verfügbar** | Backend ist search-only (Brave Free) |
| Nexus-Downloads | **nicht verfügbar** | Account ist Supporter, kein Premium → HTTP 403 |

**Grenzen dieser Untersuchung — wichtig für die Bewertung der Statusangaben:**

- **Keine Datei-Downloads.** Aussagen über implementierte Funktionen stützen sich auf Quellcode, Format-Templates, CHANGELOGs und Beschreibungen — nicht auf ausgeführte Binaries. Wo das die Aussagekraft begrenzt, steht es ausdrücklich dabei.
- **Keine Nexus-Posts/Bugs gelesen.** Die API bietet dafür keinen stabilen Endpunkt; Bugberichte sind damit nicht ausgewertet. Das ist eine echte Lücke, kein Versehen (siehe Abschnitt 9, offene Punkte).
- **Statusdefinition wie im Audit:** `PROVEN` = durch Code/Template **und** eigene Messung belegt · `DOCUMENTED` = durch Projekt-Dokumentation belegt, nicht selbst nachgemessen · `UNKNOWN` = nicht ermittelbar · `NOT_FOUND` = nach definierter Suche nicht existent.

---

## 2. Vorab-Korrektur: der gesuchte Save Cleaner

### 2.1 Nexus-ID 10457 ist ein anderes Projekt

| Feld | Erwartung im Auftrag | Tatsächlich |
|---|---|---|
| 10457 | Starfield Save Cleaner | **Starfield Engine Fixes – SFSE** |
| Autor | — | LarannKiar |
| Version | — | 21.7, aktualisiert 05.11.2026 |
| Endorsements / Downloads | — | 4.520 / 674.792 |
| Funktion | Saves bereinigen | Sammlung von Engine-Bugfixes (Gesichtsausdruck, NPC-Makeup, Papyrus `IsInDialogueWithPlayer`, `UnequipAll`, `SetScale` …) |

Der Mod **verändert keine Save-Dateien** und enthält keine Save-Bereinigungsfunktion. Er arbeitet zur Laufzeit über SFSE-Hooks auf Engine-Funktionen.

### 2.2 Ein Starfield-Save-Cleaner existiert auf Nexus nicht

Systematische Suche, jede Zeile mit Grundgesamtheit — nicht „nichts gefunden", sondern „so gesucht":

| Suchraum | Begriff | Treffer | Save-relevant davon |
|---|---|---|---|
| Titel | `editor` | 11 | 0 (ID-Listen, Objekt-Spawner, Material-Editoren) |
| Titel | `save` | 183 | 6 Werkzeuge, **0 Editoren** |
| Titel | `sav` | 195 | keine weiteren (überwiegend „SavrenX"-Texturen) |
| Titel | `clean` | 63 | 0 (Kosmetik: Cleanfield, Reflexvisiere, Supervisor-Lin-Gesicht) |
| Titel | `cleaner` | 11 | 0 (Kosmetik + „Pipeline Cleaner" für `Pipeline.cache`) |
| Titel | `corrupt` | 1 | 0 („Dark Corruption – Sith Eyes") |
| Titel | `runtime` | 0 | — |
| Titel | `formid` | 1 | 1 Referenzliste (`SF Location FormIDs and EditorIDs`) |
| Beschreibung | `save cleaner` | 17 | 0 |
| Beschreibung | `orphan` | 3 | 0 |
| Beschreibung | `duplicate forms` | 7 | 0 |
| Beschreibung | `bloat` | 14 | 0 |
| Beschreibung | `script instance` | 20 | 0 (Frameworks, keine Save-Tools) |
| Beschreibung | `save game corrupt` | 10 | 0 |

**Ergebnis: NOT_FOUND.** Es gibt auf Nexus keinen Mod für Starfield, der Spielstände bereinigt, repariert oder von runtime-generierten Daten befreit. Die einzige Save-bezogene Bereinigungsfunktion im gesamten Bestand ist **„Starfield Pipeline Cleaner" (ID 4483, 24 Endorsements)** — und die löscht `Pipeline.cache`, nicht Spielstände.

**Konsequenz für den Auftrag:** Die „Besondere Untersuchung: Starfield Save Cleaner" (Abschnitt 5) kann nicht an einem Starfield-Projekt erfolgen, weil es keines gibt. Ich habe stattdessen das **Referenzprojekt für Save-Cleaning in Bethesda-Spielen** untersucht — FallrimTools/ReSaver — und daraus die übertragbaren Sicherheitsmechanismen abgeleitet.

---

## 3. Die Kandidaten im Überblick

Priorisiert nach technischer Relevanz, nicht nach Endorsements.

| # | Projekt | Nexus-ID / Quelle | Version | Zuletzt | Art | Save-Datei verändert? | Relevanz |
|---|---|---|---|---|---|---|---|
| 1 | **Starfield Save Tool** | 10472 · GitHub `Nexus-Mods/StarfieldSaveTool` | 1.3.0 | 02.09.2024 | C# CLI, NativeAOT | **ja** (Write-PoC in v1.1.0) | **sehr hoch** — Formatdoku |
| 2 | **Vortex Starfield Extension** | GitHub `Nexus-Mods/game-starfield` | 21 Tags, 243 Commits | aktiv | TypeScript (Vortex-Plugin) | **nein** (ruft 1 auf) | hoch — Integrationsmuster |
| 3 | **FallrimTools / ReSaver** | GitHub `mdfairch/FallrimTools` | Java, 16 Stars | 02.11.2026 | Java Desktop | **ja** (Skyrim/Fallout, nicht Starfield) | hoch — Cleaning-Referenz |
| 4 | Simple Save Manager | 14332 | 1.2.1 | 10.04.2026 | SFSE-Plugin | nein (Runtime) | mittel — Save-Erzeugung |
| 5 | Save Game Thumbnails – SFSE | 15069 | 6.0 | 14.06.2026 | SFSE-Plugin | **ja** (schreibt PNGs zu Saves) | mittel — UI-Idee |
| 6 | Starfield Save Previews | 3846 | 1.1 | 06.11.2024 | SFSE-Plugin | nein (Runtime) | niedrig |
| 7 | Baka Quick Full Saves | 1750 | 7.0.0 | 19.06.2026 | SFSE-Plugin | nein (Runtime) | niedrig |
| 8 | Starfield Save Converter | GitHub `LukeFZ/StarfieldSaveConverter` | — | 16.01.2026 | ? | vermutlich ja | mittel — Konvertierung |
| 9 | Starfield-Save-Switcher | GitHub `ProbeTech-sff/…` | — | 28.03.2026 | App | nein (Ordnerverwaltung) | niedrig — Organisation |
| 10 | starfield-saves-backup | GitHub `bitburner/…` | — | 16.01.2026 | PowerShell | nein (Kopien) | niedrig — Backup-Muster |
| 11 | resaver-save-manager | GitHub `VendorEnlarge/…` | — | 07.11.2026 | Manager für FallrimTools | nein | niedrig |

---

## 4. Einzelprofile

### 4.1 Starfield Save Tool (10472) — das einzige echte Format-Referenzwerkzeug

| Feld | Wert |
|---|---|
| Autor | **Nexus Mods** (offiziell) |
| Version / Stand | 1.3.0, 02.09.2024 · Nexus-Seite 23.09.2024 |
| Endorsements / Downloads | 98 / 23.768 (17.670 unique) |
| Kategorie | Utilities |
| Lizenz | nicht angegeben auf der Mod-Seite; Quellcode öffentlich auf GitHub |

**Zweck (aus der Beschreibung, wörtlich):** „A tool to decompress and convert Starfield save games to JSON format. […] I'm not including the main data blocks of the decompressed file as we are primarily interested in the metadata."

Das ist genau der Schnitt, den ich in `SAVE_INTELLIGENCE_AUDIT.md` als Chunk-0-Kurzpfad gemessen habe (1,27 ms statt 76 ms) — **unabhängig dieselbe Entscheidung**.

**Tatsächliche Funktionen, belegt durch CHANGELOG und Quellcode:**

| Version | Belegte Funktion |
|---|---|
| 1.0.0 | Dekompression + JSON-Export der Metadaten |
| 1.0.1 | Batch-Datei-Fix (Leerzeichen in Pfaden) |
| 1.1.0 | `JsonVersion`-Feld; **„experimental write support […] proof-of-concept testing the full circle of read, decompress, modify, compress, write. The game does successfully read the re-written save file."** |
| 1.2.0 | 64-KB-stdout-Puffer, JSON „uglified" zur Puffergrößenreduktion, NativeAOT |
| 1.3.0 | **„Updated to support save version 140"** (Starfield 1.13.61.0) |

**Das ist der wichtigste externe Befund zur Machbarkeit:** Rekompression und Zurückschreiben eines Starfield-Saves **funktioniert nachweislich** — Nexus Mods hat es gebaut und das Spiel hat die neu geschriebene Datei gelesen. Das ändert die Risikobewertung in unserem Audit **nicht** (wir implementieren weiterhin nichts davon), aber es verschiebt die Kategorie von „unbekannt ob möglich" zu „möglich, mit einem einzigen PoC-Beleg".

**Verarbeitete Datenstrukturen** (`DatFile.cs`, 311 Zeilen — Felddefinitionen wörtlich):

- `FileHeader`: `EngineVersion`, `SaveVersion`, `SaveNumber`, `PlayerName`, `PlayerLevel`, `PlayerLocation`, `Playtime`, `RaceName`, `Gender`, `Experience`, `ExperienceRequired`, `Time`, `DateTime` (konvertiert), `Unknown0`, `Padding`
- `FilePluginInfo`: `Padding`, `PluginCount`, `LightPluginCount`, **`MediumPluginCount`**, `Plugins`, `LightPlugins`, **`MediumPlugins`**
- `FilePlugin`: `PluginName`, `CreationName`, `CreationId`, `Flags`, `AchievementFriendly`
- `HeaderSize` (nicht im JSON)

**Wichtig für uns:** `Unknown0` steht **vor** `Padding` — deckungsgleich mit unserem Parser. Das 010-Editor-Template `SFS-decompressed.bt` hat es umgekehrt (`padding[8]` dann `unknown`). Bei allen sechs echten Saves sind diese 12 Bytes komplett Null, der Widerspruch ist also praktisch folgenlos — **aber die produktive Implementierung ist die Wahrheit, nicht das Template.** Das gehört in unsere Doku, damit niemand später das Template als Referenz nimmt.

**Einschränkungen und Risiken:**

| Einschränkung | Beleg | Bedeutung für uns |
|---|---|---|
| Nur bis **Save-Version 140** | CHANGELOG 1.3.0 | Unsere Saves sind 153 → das Tool ist zwei Formatstände alt |
| „majority of unknowns are in the header of the compressed sfs file, and the plugins data within the decompressed file" | Mod-Beschreibung, wörtlich | Der Autor nennt die Unknowns selbst — wir haben sie teilweise geschlossen (s. 5) |
| NativeAOT/.NET-8-Abhängigkeit | Vortex-Wrapper: `SFSaveToolMissingDotNet` | Läuft nicht ohne .NET 8 Desktop Runtime |
| Write nur PoC | CHANGELOG 1.1.0 | Kein Produkt-Feature, keine Sicherheitsmechanismen dokumentiert |
| Seit 14 Monaten kein Update | 02.09.2024 | Kein aktiver Maintainer für Version 153 |

**Übertragbarkeit auf SSB-I: hoch, aber nicht als Abhängigkeit.** Wir übernehmen das **Formatwissen**, nicht das Tool: keine .NET-Runtime, kein Subprozess, keine externe Binary.

---

### 4.2 Vortex Starfield Extension (`Nexus-Mods/game-starfield`)

| Feld | Wert |
|---|---|
| Art | Vortex-Extension (TypeScript), 243 Commits, 21 Tags, 8 Stars |
| Save-Unterstützung | **indirekt** — `src/SFSaveToolWrapper.ts` (144 Zeilen) startet `StarfieldSaveTool.exe` als Subprozess |
| Bundled Binary | `src/assets/StarfieldSaveTool.exe` + `.pdb` liegen im Repo |

**Belegte Mechanik** (`SFSaveToolWrapper.ts`): `child_process.exec` auf `StarfieldSaveTool.exe`, drei Aktionen (`output-json-file`, `output-raw-file`, `output-stdout`), `ConcurrencyLimiter(20)`, `TIMEOUT_MS = 10000`, und ein `ignoreSaveVersion`-Flag in den Optionen. Fehlerklassen: `SFSaveToolMissing`, `SFSaveToolMissingDotNet`, `SFSaveToolTimedOut`.

**Erkenntnis:** Selbst das offizielle Mod-Management-Tool parst Starfield-Saves **nicht selbst** — es lagert an eine externe Binary aus und muss die Save-Version notfalls ignorieren. Für uns heißt das: eigene Implementierung in Python ist kein Sonderweg, sondern der einzige Weg ohne Fremdruntime.

---

### 4.3 FallrimTools / ReSaver (`mdfairch/FallrimTools`)

| Feld | Wert |
|---|---|
| Autor | Mark Fairchild (mdfairch) — **nicht** `Markemp/Skyrim-Tools`, dieses Repo existiert nicht (HTTP 404) |
| Sprache / Lizenz | Java, Apache 2.0 · 16 Stars, letzte Aktivität 02.11.2026 |
| Zielspiele | Skyrim, Fallout 4 (Nexus-ID der Skyrim-Version: 76776) — **kein Starfield** |
| Artefakte | `Resaver.jar`, `Restringer.jar`, `ReSaver.exe` (Launch4j-Wrapper) |

**Relevanz:** Es ist das etablierte Referenzprojekt für Save-Cleaning in Bethesda-Engines. Da es für Starfield keinen Save Cleaner gibt, ist das die beste verfügbare Quelle für die Frage „wie bereinigt man sicher".

**Belegte Bereinigungsfunktion** (`src/main/java/resaver/gui/BatchCleaner.java`, 217 Zeilen): Der Batch-Clean entfernt

- Skripte (`scripts`) und deren Instanzen (`scriptInstances`),
- Strukturen (`structs`) und deren Instanzen,
- Referenzen (`references`),
- Threads (`threads were terminated`).

**Sicherheitsmechanik, die tatsächlich im Code steht:**

1. **Dialog vor dem Lauf** (`JOptionPane.showConfirmDialog`, OK/CANCEL) mit einer scrollbaren Liste dessen, was gelöscht würde.
2. **Dialog pro Treffer** (`Delete %s?` mit YES/NO/**CANCEL**) — der Nutzer kann einzelne Löschungen ablehnen, nicht nur den ganzen Lauf.
3. **Abschlussbericht mit Zahlen** („Cleaned %d scripts and %d corresponding instances … %d threads were terminated").
4. **Kein automatisches Backup.** `Checkpoints.java` (51 Zeilen) ist ein **interner Konsistenzprüfer** beim Lesen/Schreiben (`AddCheckPoint` / `VerifyCheckPoint`) — **kein** Sicherungsmechanismus. Wer ReSaver nutzt, muss vorher selbst kopieren.

**Das ist die wichtigste übertragbare Lehre:** Auch das Referenzwerkzeug für Save-Cleaning hat **kein** automatisches Rollback. Es setzt auf *Bestätigung pro Einzelentscheidung* und *transparente Abschlussbilanz*. Das ist ein anderes Sicherheitsmodell als „Backup und hoffen" — und für uns das passendere, weil wir ohnehin nichts schreiben.

**Risiko:** Die Live-Datenbank von ReSaver ist das Skyrim-Format (`ESS`). Die Bereinigungslogik ist an FormIDs, Skript-Instanzen und Referenzen eines anderen Formats gebunden. Eine direkte Übertragung auf `.sfs` ist **nicht** möglich — nur das Sicherheitsmodell.

---

### 4.4 Simple Save Manager (14332)

| Feld | Wert |
|---|---|
| Autor / Version | Stentorious · 1.2.1, 10.04.2026 |
| E / DL | 105 / 25.743 |
| Art | **SFSE-Plugin** — arbeitet zur Laufzeit, schreibt keine Save-Dateien um |

**Funktionen (Beschreibung):** Autosave-Trigger für Spielereignisse, zeitgesteuerte Autosaves, „Interval Full Save" (permanenter Save alle X Autosaves), Save-Cooldown, Save-Voraussetzungen (nicht im Kampf, nicht bei niedriger Gesundheit).

**Bewertung:** Erzeugt Saves, verwaltet sie aber nicht. Für Save Intelligence keine Funktion nutzbar — aber ein **Nutzerbedürfnis-Beleg**: 25.743 Downloads für „weniger/anders speichern" zeigen, dass Save-Verwaltung ein reales Bedürfnis ist. Die Dateinamen-Konvention (`Autosave1`, `Exitsave0`) ist genau die, die wir in `save_identity` auswerten.

---

### 4.5 Save Game Thumbnails – SFSE (15069) und Save Previews (3846)

| | Thumbnails | Previews |
|---|---|---|
| Autor | LarannKiar | shadeMe |
| Version / Stand | 6.0, 14.06.2026 | 1.1, 06.11.2024 |
| E / DL | 265 / 46.664 | 110 / 1.584 |
| Funktion | erzeugt `.png`-Vorschaubilder für Saves, rendert sie im Haupt- und Pausenmenü | bringt Savegame-Screenshots zurück |
| Save-Datei verändert | **ja** — schreibt Bilddateien neben die Saves | nein |

**Relevanz:** Bestätigt, dass die Engine Save-Vorschaubilder rendern kann und dass dafür SFSE gebraucht wird. Für unsere Save-Übersicht wäre ein Vorschaubild der größte Einzelgewinn an Wiedererkennbarkeit — aber es ist ein **SFSE-Plugin-Strang**, kein Python-Feature. Nicht Teil dieses Auftrags.

---

### 4.6 Weitere Projekte (kurz)

| Projekt | Befund | Übertragbarkeit |
|---|---|---|
| **Starfield Save Converter** (`LukeFZ`) | Repo existiert, kein README (404 auf README.md); Zweck laut Repo-Beschreibung: Konvertierung Xbox↔Steam | Konzeptionell interessant (Save-Identität über Plattformgrenzen), ohne Doku **UNKNOWN** |
| **Starfield-Save-Switcher** (`ProbeTech-sff`) | README: „separate your test saves from your game saves" — reine Ordnerverwaltung | Zeigt das reale Bedürfnis nach Save-Organisation; technisch trivial |
| **starfield-saves-backup** (`bitburner`) | PowerShell-Skript, kopiert `Documents\My Games\Starfield\Saves` in einen Backup-Ordner, zwei Pfadvariablen | Genau unser P5-Muster, aber **ohne Hash-Nachweis**. Unser Konzept (Kopie → `sha256`-Gegenprüfung → Manifest) ist die härtere Variante |
| **resaver-save-manager** (`VendorEnlarge`) | Manager/Wrapper um FallrimTools ReSaver (Fallout 4) | Kein Starfield-Bezug |
| Baka Quick Full Saves (1750) | SFSE, macht Quicksaves zu normalen Saves | Runtime, kein Dateiformat-Wissen |
| SF Location FormIDs and EditorIDs (16986) | `.txt`-Listen aller Locations mit FormIDs | Referenzdaten, keine Save-Verarbeitung |

---

## 5. Besondere Untersuchung: Save-Cleaning — was es gibt und was nicht

Der Auftrag verlangt acht Fragen zum Save Cleaner. Da das Projekt nicht existiert, beantworte ich sie für den **nächstliegenden realen Fall** (FallrimTools `BatchCleaner`) und markiere, was auf Starfield unbekannt bleibt.

| Frage | FallrimTools (Skyrim/F4) | Starfield |
|---|---|---|
| Welche Daten werden entfernt? | Skripte, Skript-Instanzen, Strukturen (`structs`) + deren Instanzen, Referenzen, Threads | **UNKNOWN** — kein Projekt vorhanden |
| Wie werden sie identifiziert? | Über die Live-Datenbank des Saves (FormID-/Instanz-Auflösung im Skyrim-Format) | **UNKNOWN** |
| Welche Prüfungen vor dem Entfernen? | Bestätigungsdialog mit Liste; Einzelbestätigung pro Treffer (YES/NO/CANCEL) | **UNKNOWN** |
| Wie wird Datenverlust verhindert? | Nur durch Bestätigung + Abschlussbilanz. **Kein automatisches Backup**, `Checkpoints` ist ein interner Konsistenzprüfer | **UNKNOWN** |
| Backup/Wiederherstellung? | Im untersuchten Code **nicht vorhanden** | **UNKNOWN** |
| Unterstützte Spielversionen? | Skyrim/FO4-Formate; Skyrim-Nexus-ID 76776 | **UNKNOWN** |
| Dokumentierte Fehler/Nebenwirkungen? | **Nicht ausgewertet** — Nexus-Posts/Bugs über die API nicht erreichbar (Abschnitt 1) | **UNKNOWN** |
| Für unsere Integritätsprüfung nutzbar? | **Ja, das Sicherheitsmodell:** (a) vor jeder Aktion zeigen, was passieren würde, (b) Einzelentscheidung statt Sammelaktion, (c) Abschlussbilanz mit Zahlen, (d) kein Schreiben ohne vorherige Anzeige. Die **Bereinigungslogik** ist nicht übertragbar | — |

**Übernahme in SSB-I: nichts.** Das ist keine Vorsicht, sondern folgt aus dem Audit: Für `.sfs` ist nicht einmal bekannt, welche Strukturen „runtime-generiert" wären. Der Body-Anfang ist jetzt teilweise lesbar (Abschnitt 6.3), aber es gibt keine Zuordnung „Struktur → ist verzichtbar". Eine Löschfunktion ohne diese Zuordnung wäre Raten an 23 MB Spielstand.

---

## 6. Technische Erkenntnisse — verifiziert an unseren eigenen Saves

Das Format-Template `SFS-decompressed.bt` (Nexus-Mods, 010 Editor) beschreibt Strukturen, die unser Parser nicht kennt. Ich habe jede Aussage gegen alle sechs echten Saves geprüft. Prüfskripte: `~/ssb_save_audit/verify_{external_template,medium_block,body_pointers,string_array}.py`.

### 6.1 Befund A — unser Parser verliert 5 Medium-Plugins pro Save (**Fehler im Bestand**)

Das Template und der C#-Code kennen `MediumPlugins`. Unser `parse_plugin_info()` meldet `medium = 0`.

Messung über alle sechs echten Saves:

| Save | normal | light | **medium (real)** | Blockende geparst | deklariert | Delta |
|---|---|---|---|---|---|---|
| Autosave1 | 25 | 50 | **5** | 0x147B | 0x147B | 0 |
| Autosave2 | 25 | 50 | **5** | 0x147D | 0x147D | 0 |
| Autosave3 | 25 | 50 | **5** | 0x147D | 0x147D | 0 |
| Exitsave0 | 25 | 50 | **5** | 0x147D | 0x147D | 0 |
| Save46 | 25 | 50 | **5** | 0x147D | 0x147D | 0 |
| Save47 | 25 | 50 | **5** | 0x147D | 0x147D | 0 |

Die fünf Medium-Plugins sind in allen Saves identisch: `SFBGS003.esm`, `SFBGS006.esm`, `PersonalSpacestation.esm`, `RRLAC - Rabbit's Real Lights Akila City.esm`, `RRLNA - Rabbit's Real Lights New Atlantis.esm`.

**Die Dekodierung ist bytegenau vollständig:** mit Metadaten-Block endet der Plugin-Bereich in 6/6 Saves **exakt** bei `plugin_info_offset + plugin_info_size` (Delta 0). Das ist der stärkste mögliche Beleg — kein Zufallstreffer, sondern die Struktur geht exakt auf.

**Konsequenz:** `sfda save info` meldet heute „75 Plugins", real sind es **80**. Das ist ein sachlicher Fehler in der Produktausgabe, kein Schönheitsfehler.

### 6.2 Befund B — Plugin-Metadaten sind dekodierbar (Audit-Lücke V9 schließbar)

Format (saveVersion ≥ 140): nach dem Namen ein `u8 extraInfo`; bei `extraInfo == 1` folgen `u16 len + creationName`, `u16 len + creationId`, `u16 len + flags`, `u8 achievementFriendly`.

Verteilung in Save47 (80 Records):

| Klasse | Anzahl | Bedeutung |
|---|---|---|
| `extraInfo = 0` | 9 | Game-Plugin (Starfield.esm, SFBGS00D.esm …) |
| `extraInfo = 1` mit echter Creation-ID (`TM_…`) | 6 | Creation mit Name, ID und Versionsangabe |
| `extraInfo = 1`, Name/ID leer, `flags` = Platzhalter | 65 | Mod-Plugin ohne hinterlegte Creation-Metadaten |

Beispiele mit vollständigen Metadaten:

```
starfield_hair+beards.esm    cn='Starfield Hair+Beards'  ci=TM_84981815-7935-49d1-a9a7-9ed57f491105  flags="1753987979.2.3"   ach=0
cwhdigipickshortcut.esm      cn='Digipick Skip Classic'  ci=TM_e49e8638-1615-44f4-b93a-686824399afc  flags="1776565871.1.01"  ach=0
darkerspace.esm              cn='Darker Space'           ci=TM_60a24112-d7ce-416b-ab44-fec0184d978e  flags="1730975455.1.01"  ach=0
sfbgs019.esm                 cn='Deimog-Fahrzeug'        ci=TM_e3295393-57db-47ba-91e4-2ba74133856a  flags="1763606756.1.0.81" ach=1
```

**Wichtig:** Das `flags`-Feld enthält in der Praxis einen **ASCII-String**, der wie eine Versionsangabe aussieht (`<timestamp>.<major>.<minor>[.<patch>]`), keinen Bitfeld-Wert. Bei Plugins ohne Metadaten steht dort der 30-Zeichen-Platzhalter `18446744073709551615.undefined` (= `uint64.max` + `.undefined`). Das ist ein Engine-Platzhalter für „keine Version hinterlegt", keine Fehlinterpretation.

Damit ist **V9 aus `SAVE_INTELLIGENCE_AUDIT.md` (Abschnitt 4) geschlossen**: Die `PluginEntry.creation_name`/`creation_id` sind keine toten Felder mehr, sondern befüllbar — mit der Einschränkung, dass 81 % der Mod-Plugins keine Creation-Metadaten tragen.

### 6.3 Befund C — der Body ist am Anfang strukturiert (Audit-Befund „undurchsichtig" ist zu korrigieren)

Das Template beschreibt nach dem Plugin-Block einen `NEW_BLOCK`: `u16`, zwölf `uint` (Pointer), 52 Byte Padding, dann `NEW_BLOCK2` mit `pointer0`, `stringsArrayOffset`, `unknown0`.

Prüfung gegen alle sechs Saves, mit fünf unabhängigen Kriterien:

| Kriterium | Ergebnis |
|---|---|
| K1: `pointer2` zeigt exakt auf die Position von `NEW_BLOCK2` | **6/6** |
| K2: `stringsArrayOffset` liegt im Payload und trägt einen plausiblen Zähler | **6/6** |
| K3: alle `count` Strings parsen sequentiell ohne Überlauf und enden vor Payload-Ende | **6/6**, Status „ok" |
| K4: Anteil druckbarer Strings > 90 % | **6/6**, gemessen **99,6 %** |
| K5: Zähler variiert spielstandabhängig (kein konstanter Zufallstreffer) | 1735 / 1713 / 1731 / 1717 / 1727 / 1709 |

Zusätzlich: `unknown0` ist in allen sechs Saves exakt `1`, `NEW_BLOCK2.unknown0` ebenfalls `1`, und 11 von 12 Pointer-Werten liegen im gültigen Payload-Bereich.

**Inhalt der String-Tabelle** (Save Autosave1, 1735 Einträge, 0 Duplikate):

```
'Sequence', 'SitSleep', 'Anzug: Navigator', 'Helm: Navigator', 'Stacked', 'Simultaneous',
'Sandbox', 'LocPt', 'LocRef', 'Anzug: Tiefensucher', '[Neon-Tiefensucher-Rucksack] Rucksack'
…
'[Erweitertes Magazin] MagShot', '[Kalibriert] Anzug: UC-Security',
'[Veredelt] Anzug: Bodencrew', 'Zerlegend [Ausgeglichen] [Geschärft] Kampfmesser'
…
'actors\human\animations\furniture\bench\female\animflavor',
'actors\human\animations\furniture\terminal_standing'
```

Das sind **Objekt- und Item-Namen mit Legendary-Modifikatoren sowie Animationspfade** — also der String-Pool der im Save referenzierten Objekte.

**Was damit belegt ist und was nicht:**

- **PROVEN:** Am Body-Anfang steht eine Pointer-Tabelle; eines ihrer Ziele ist ein String-Array mit 1709–1735 lesbaren Einträgen, das vollständig und verlustfrei parsbar ist (6/6 Saves).
- **NICHT belegt:** die Zuordnung String → Record → FormID. Ich weiß, *dass* „[Kalibriert] Anzug: UC-Security" im Save steht; ich weiß nicht, *welcher* Record oder welche FormID dazugehört. Ebenso unbelegt: die Semantik der übrigen zehn Pointer.
- **Damit korrigiert:** Die Aussage „Body enthält null Record-Signaturen, also nicht erschlossen" bleibt für die *Record-Ebene* richtig, war aber als „undurchsichtig" zu absolut. Der Body hat eine lesbare Kopfstruktur.

---

## 7. Übertragbarkeit auf SSB-I

| Fremdprojekt | Was wir übernehmen | Was wir nicht übernehmen |
|---|---|---|
| **Starfield Save Tool** | Formatwissen (Header, Plugin-Metadaten, Medium-Block, Blockreihenfolge); die Bestätigung, dass Header-only-Auswertung die richtige Strategie ist | .NET-8-Runtime, externe Binary, Subprozess-Aufruf, Write-PoC |
| **Vortex Extension** | Integrationsmuster: Save-Ansicht als eigenständige UI-Fläche, Versionstoleranz explizit als Flag (`ignoreSaveVersion`) | Electron/TypeScript-Stack, gebündelte Fremd-Binary |
| **FallrimTools / BatchCleaner** | **Sicherheitsmodell:** vor der Aktion zeigen, was passieren würde; Einzelentscheidung; Abschlussbilanz mit Zahlen | jede Bereinigungs- oder Löschlogik (Format nicht übertragbar, Zielsemantik unbekannt) |
| **starfield-saves-backup** | Bestätigung, dass „Saves sichern" ein reales Bedürfnis ist | das Fehlen eines Hash-Nachweises |
| **Save Game Thumbnails** | Produktidee Vorschaubild (eigener Strang, SFSE) | nichts in diesem Auftrag |
| **Simple Save Manager** | Nutzerbedürfnis-Beleg für Save-Verwaltung | Runtime-Plugin-Ansatz |

**Nichts davon begründet eine neue Abhängigkeit, eine neue Sprache oder eine neue Datenbank.** Alle übernommenen Erkenntnisse sind Formatwissen und Sicherheitsregeln — beides landet in Python.

---

## 8. Konsequenzen für die bestehenden Dokumente

Die externen Befunde ändern drei Aussagen in `SAVE_INTELLIGENCE_AUDIT.md` und eine in `SAVE_INTELLIGENCE_SPEC.md`. Beide Dateien tragen einen Nachtrag am Ende; hier die Zusammenfassung:

| Stelle | Vorher | Nachher | Beleg |
|---|---|---|---|
| Audit 1.3, Spec 3 (Checks) | `medium`-Block: „0 Einträge in allen 10 Saves, nie verifiziert" | **5 Einträge pro Save, bytegenau bis zum deklarierten Blockende verifiziert** | 6.1 |
| Audit 4 V9 | Plugin-Metadaten: „totes Interface, NOT IMPLEMENTED" | **Format bekannt, dekodierbar** (`extraInfo`/`creationName`/`creationId`/`flags`/`achievementFriendly`) | 6.2 |
| Audit 3.4 | Body: „99,98 % undurchsichtig, keine Struktur" | **Kopfstruktur erschlossen** (Pointer-Tabelle + String-Array, 99,6 % lesbar); Record-Ebene und FormID-Zuordnung weiterhin offen | 6.3 |
| Audit 1.3 (Plugin-Zahl) | „25 normal / 50 light / 0 medium" | **25 / 50 / 5 = 80** — Produktausgabe ist heute unvollständig | 6.1 |

**Was sich nicht ändert:** Der Body bleibt für Objekt-, FormID- und Referenzprüfungen unbrauchbar. Die drei stillen Integritätsfehler bleiben. Es gibt weiterhin keinen Grund, Schreib- oder Reparaturfunktionen zu bauen.

---

## 9. Risiken und offene Punkte

**Neue Risiken aus dieser Recherche:**

| # | Risiko | Gegenmaßnahme |
|---|---|---|
| E1 | Externe Doku beschreibt **Save-Version 140**, wir haben 153. Ein naives Übernehmen der Templates kann bei 153 falsch sein. | Jede übernommene Struktur gegen eigene Saves prüfen (hier geschehen, 6/6). Nie ungeprüft übernehmen. |
| E2 | Das `.bt`-Template hat `padding`/`unknown` vertauscht gegenüber dem produktiven C#-Code. | Produktive Implementierung ist die Referenz. Widerspruch dokumentieren, nicht auflösen durch Raten. |
| E3 | Die verlockende Schlussfolgerung „Write funktioniert ja (PoC), also können wir reparieren" | PoC ≠ Sicherheit. Kein Schreibpfad ohne vollständige Record-Semantik. Bleibt gesperrt. |
| E4 | „Medium-Plugins fehlen" könnte als Anlass für eine schnelle Parser-Änderung genommen werden | Zuerst als **Befund** dokumentieren (geschehen), dann als eigener Schritt mit Korruptions- und Golden-Tests. Kein Ad-hoc-Patch. |

**Offene Punkte, die ich in diesem Auftrag nicht schließen konnte:**

1. **Nexus-Posts und Bugberichte sind nicht ausgewertet.** Die API bietet keinen stabilen Endpunkt; Ergebnis: keine Nutzererfahrungsdaten zu Starfield Save Tool, Simple Save Manager oder Save Game Thumbnails. Konkrete Evidenz, die fehlt: Post-/Bug-Threads der Mod-Seiten, erreichbar nur über Browser-Scraping mit Login oder manuelle Sichtung.
2. **`LukeFZ/StarfieldSaveConverter` hat kein lesbares README** (404). Zweck nur über die Repo-Beschreibung belegt, Implementierung UNKNOWN.
3. **Die zehn übrigen Pointer des Body-Kopfs sind unbedeutet.** Für die Integritätsprüfung nicht nötig; für Objekt-Ebene wären sie der nächste Ansatzpunkt.
4. **Ob die String-Tabelle stabil über Spielversionen ist**, ist offen — alle sechs Saves stammen aus derselben Installation (Save-Version 153).

---

## 10. Empfehlung

1. **Nichts aus dieser Recherche wird als Abhängigkeit eingebunden.** Kein .NET, keine Fremdbinary, keine Lizenzfrage.
2. **Die drei Formatbefunde werden zuerst als Befund geführt, dann als Arbeit** — in dieser Reihenfolge, mit Tests: (a) Medium-Plugins vollständig lesen (Korrektur einer falschen Produktausgabe), (b) Plugin-Metadaten optional dekodieren (schließt V9), (c) String-Tabelle als read-only Zusatzfunktion („welche Objektnamen enthält dieser Spielstand?").
3. **Das Sicherheitsmodell von FallrimTools wird übernommen, seine Funktion nicht:** Anzeigen, was passieren würde → Einzelbestätigung → Abschlussbilanz. Das gilt ab P5 (Backup/Export), obwohl dort nur kopiert wird.
4. **P1 (Integritätsprüfung) bleibt die erste Umsetzung.** Die externen Befunde ändern daran nichts — sie machen die Prüfung an einer Stelle sogar besser: Wenn der Plugin-Block bei 80 statt 75 Einträgen exakt aufgeht, ist das ein zusätzliches, starkes Integritätskriterium (I-11 erweitert).

---

## 11. Belege

**Nexus (API):** GraphQL v2 `mods(filter:…)` für alle Suchläufe; REST v1 `/v1/games/starfield/mods/{id}.json` und `/changelogs.json` für 10457, 10472, 14332, 15069, 3846, 1750. Website-Abgleich via `jarvis-scrape` (11 Treffer „Editor" = API-`totalCount`).
**GitHub (`gh api`, raw):** `Nexus-Mods/StarfieldSaveTool` — `CHANGELOG.md`, `README.md`, `DatFile.cs` (311 Z.), `SfsFile.cs` (233 Z.), `SFS.bt` (74 Z.), `SFS-decompressed.bt` (231 Z.), `Research.md` (45 Z.) · `Nexus-Mods/game-starfield` — `src/SFSaveToolWrapper.ts` (144 Z.) · `mdfairch/FallrimTools` — `README.TXT`, `src/main/java/resaver/gui/BatchCleaner.java` (217 Z.), `src/main/java/mf/Checkpoints.java` (51 Z.).
**Eigene Verifikation:** `~/ssb_save_audit/verify_external_template.py`, `verify_medium_block.py`, `verify_body_pointers.py`, `verify_string_array.py` — read-only gegen 6 echte Saves, Originale per SHA-256 unverändert.
**Eigene Messbasis:** Save-Version 153, Engine 27, Starfield 1.16.244.0, `~/ssb_probes/saves_07oct_2026/`.
