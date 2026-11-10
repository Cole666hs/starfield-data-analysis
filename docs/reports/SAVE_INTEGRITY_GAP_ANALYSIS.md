# SAVE_INTEGRITY_GAP_ANALYSIS

**Projekt:** Starfield Data Analysis · **Organisation:** Entropy Development
**HEAD:** `ed5587acd99b6a45982b0c0a55ad11afb5e50d9a` · **Version:** 1.5.3
**Datum:** 08.11.2026 · **Modus:** READ-ONLY / EVIDENCE-FIRST
**Gegenstand:** Ursachenanalyse der vier nicht bewerteten Prüfungen I-09, I-12, I-13, I-14

**Keine Codeänderung. Keine Teständerung. Keine Spezifikationsänderung. Kein Commit. Kein Push.**

---

## A. Executive Summary

Die vier offenen Indikatoren haben **vier verschiedene Ursachen** — sie sind nicht austauschbar und nicht mit derselben Maßnahme zu schließen. Das ist das wichtigste Ergebnis dieser Untersuchung.

| Indikator | Ursache der offenen Bewertung | Kategorie | Status nach Untersuchung |
|---|---|---|---|
| **I-09** `headerSize` | Formatwissen fehlte — **jetzt vorhanden** | Erkenntnislücke, geschlossen | **PROVEN** (Formel in 6/6) |
| **I-12** Plugin-Abhängigkeiten | **Implementiert und lauffähig**; benötigt nur ein Data-Verzeichnis | Umgebungsdaten | **PROVEN lauffähig** (WARNING erwartet) |
| **I-13** FormID-Auflösung | Record-Grenzen des Bodys nicht erschlossen | **echte Formatforschung** | **UNKNOWN** (blockiert) |
| **I-14** Sequenzkonsistenz | **Implementiert und lauffähig**; der Aufrufer übergibt keine Sequenz | reine Verdrahtung | **PROVEN** (PASS mit echten Daten) |

**Drei der vier sind ohne neue Formatforschung schließbar.** Nur I-13 braucht tatsächlich Reverse Engineering, und zwar an einer Stelle, die in diesem Projekt bereits dreimal negativ geprüft wurde (Body-Record-Ebene).

Der zentrale neue Befund: **`headerSize` ist nicht mehr UNKNOWN.** Es gilt mit 6/6 Belegen

```
headerSize == Ende_des_Padding_Feldes − 16
```

Damit löst sich auch die bisher als „nicht auflösbar" notierte Differenz `plugin_info_offset − headerSize = 168 − 125 = 43` vollständig auf: **43 = 16 (Magic + Größenfeld) + 27 (der nicht mitgezählte Bereich)**. Die 27 Byte sind `saveVersion2`, `currentGameVersion`, `createdGameVersion` und `pluginInfoSize`.

**Bewertungsabdeckung:** unverändert 10/14 im Produkt. Die Untersuchung ändert keinen Code — sie zeigt, dass 13/14 erreichbar wären (I-13 ausgenommen).

---

## B. Einzelanalyse

### B.1 — I-09 `headerSize`-Semantik

**Prüfziel.** Feststellen, ob das 32-Bit-Feld `headerSize` an Offset 0x0C des dekomprimierten Payloads konsistent zur tatsächlichen Header-Geometrie ist.

**Datenquelle.** Payload-Bytes 0x0C–0x0F (`uint32`), dazu alle Feldpositionen des Headers, die der vorhandene Parser bereits liefert (`DatHeader`).

**Parserstatus.** Das Feld wird seit 1.0.0 gelesen (`DatHeader.header_size`), aber von keiner Stelle benutzt oder validiert.

**Vorhandene Evidenz.** Messung über alle sechs realen Saves, Feldpositionen **direkt aus dem Payload abgeleitet** (nicht aus einer Annahme):

| Save | `headerSize` | Ende Padding-Feld | `padEnd − 16` | Übereinstimmung |
|---|---|---|---|---|
| Autosave1 | 123 | 0x8B (139) | 123 | **OK** |
| Autosave2 | 125 | 0x8D (141) | 125 | **OK** |
| Autosave3 | 125 | 0x8D (141) | 125 | **OK** |
| Exitsave0 | 125 | 0x8D (141) | 125 | **OK** |
| Save46 | 125 | 0x8D (141) | 125 | **OK** |
| Save47 | 125 | 0x8D (141) | 125 | **OK** |

Zweite, äquivalente Formulierung ebenfalls 6/6: `headerSize == 51 + len(name) + len(location) + len(playtime) + len(race)`.

Aufbau dahinter (Save47): Der von `headerSize` gezählte Bereich ist `0x10 … 0x8D`, also von **nach** dem Größenfeld bis zum Ende des 8-Byte-Padding-Feldes. **Nicht** mitgezählt werden die 27 Byte danach:

```
0x8D  saveVersion2        1 Byte
0x8E  currentGameVersion  2 + 10
0x9A  createdGameVersion  2 + 10
0xA6  pluginInfoSize      2
0xA8  = plugin_info_offset (168)
```

**Probe:** 168 − 141 = **27** ✓ · 141 − 16 = **125** ✓ · 168 − 125 = **43** = 16 + 27 ✓

**Fehlende Evidenz (Falsifikationsgrenze).** Die sechs Saves unterscheiden sich in **genau einer** variablen Länge: `playtime` (37 vs. 39 Byte bei Autosave1). `player_name`, `location` und `race` sind in allen sechs identisch (4 / 22 / 9 Zeichen). Die positionsbasierte Formel ist von Einzellängen unabhängig und damit strukturell robust, aber ein echter Falsifikationstest bräuchte Saves mit abweichender Namens- oder Ortslänge.

**Ursache des offenen Status.** Das Feld war als „Semantik nicht belegt" markiert worden (Audit-Abschnitt 4, V5), weil bei damals zwei betrachteten Saves nur `123` und `125` bekannt waren und der Bezug zum Plugin-Offset fehlte. Die Erklärung war vorhanden, wurde aber nicht gesucht: Die 43-Differenz ist keine Lücke, sondern die Summe zweier bekannter Teile.

**Technische Machbarkeit.** **Ja, ohne externe Annahme.** Alle Eingangswerte (Feldpositionen) liefert der Parser; die Prüfung ist reine Arithmetik. Zwei mögliche Zuschnitte:

- **Variante A (empfohlen):** `headerSize == padEnd − 16` → deterministisch, `confidence = deterministic`. Erkennt manipulierte Größenfelder und Layout-Verschiebungen.
- **Variante B:** zusätzlich `padEnd + 27 == plugin_info_offset` als Konsistenz zwischen Größenfeld und Blockbeginn.

**Notwendige nächste Schritte.** Keine Formatforschung. Die Prüfung kann aus UNKNOWN in PASS/WARNING/FAILED überführt werden. Empfohlene Statuslogik: Abweichung → `FAILED` (deterministische Strukturregel), nicht `WARNING`.

---

### B.2 — I-12 Plugin-Abhängigkeiten

**Prüfziel.** Feststellen, ob jedes im Save gelistete Plugin in der Installation vorhanden ist (fehlende Master, entfernte Mods, fremde Ladereihenfolge).

**Datenquelle.** Plugin-Liste aus dem Save (80 Einträge, vollständig dekodiert) **plus** ein Verzeichnislisting der installierten `.esm/.esl/.esp`.

**Parserstatus.** Vollständig implementiert (`check_i12_dependencies`, `save_integrity.py:517–537`), inklusive Vergleich und Evidenzliste. Erwartet `--data-dir`.

**Vorhandene Evidenz.** Ein lokales Data-Verzeichnis existiert: `~/Games/Starfield/Data` mit **2** Plugin-Dateien (`Starfield.esm`, `BlueprintShips-Starfield.esm`). Die Prüfung wurde dagegen ausgeführt:

```
I-12 Status : WARNING
I-12 Detail : 78 von 80 gelisteten Plugins fehlen im Data-Verzeichnis
  gelistet    : 80
  installiert : 2
  fehlend     : 78
  Beispiele   : SFBGS00D.esm, AtmosphericAudio.esm, BASE.esm, …
Gesamtstatus : WARNING (Abdeckung steigt auf 11/14)
```

Gegenprobe mit einem Verzeichnis, das nur `Starfield.esm` enthält: `WARNING`, 79 fehlend — die Prüfung reagiert korrekt auf den Verzeichnisinhalt.

**Fehlende Evidenz.** Kein fehlendes Formatwissen. Es fehlt das **passende** Data-Verzeichnis: Der Spielstand stammt aus einer Installation mit 71 Mod-Plugins, die lokale Prüfumgebung hat nur die beiden Vanilla-Master. Die Mods liegen auf Katana (`C:\...\Starfield\Data`), nicht auf diesem Host.

**Ursache des offenen Status.** Reine Umgebungsdaten — der Standardaufruf `sfda save verify` übergibt kein `--data-dir`, deshalb meldet die Prüfung korrekt `NOT_CHECKED` („kein Data-Verzeichnis angegeben").

**Technische Machbarkeit.** **Ja, bereits umgesetzt und heute lauffähig.** Ein `sfda save verify --data-dir ~/Games/Starfield/Data` bewertet I-12 sofort. Das Ergebnis `WARNING` ist dabei **korrekt**, nicht fehlerhaft: Der Save erwartet Plugins, die hier nicht installiert sind.

**Notwendige nächste Schritte.** Keine Formatforschung. Zwei sinnvolle Optionen:
1. Ein Standardpfad-Autodetect (Windows: `%USERPROFILE%\Documents\My Games\Starfield\Data`, Steam-Pfade) mit klarer Anzeige, welches Verzeichnis verwendet wurde.
2. Eine **zweite** Prüfung „Save passt nicht zur Installation" als eigenständiges Ergebnis, damit ein WARNING aus I-12 nicht wie ein Defekt des Spielstands aussieht — die Ursache liegt in der Installation, nicht im Save.

**Wichtige Abgrenzung:** I-12 prüft **Dateiexistenz**, nicht inhaltliche Kompatibilität und nicht Ladbarkeit. Ein `PASS` in I-12 hieße nur „jede gelistete Datei ist vorhanden".

---

### B.3 — I-13 FormID-Auflösung

**Prüfziel.** FormIDs im Body gegen die deklarierte Plugin-Reihenfolge auflösen und daraus verwaiste bzw. nicht auflösbare Referenzen, doppelte und widersprüchliche Kennungen ableiten.

**Datenquelle.** Body-Bytes nach dem Plugin-Block (Save47: 23.528.266 Byte, 99,98 % der Nutzdaten) plus Plugin-Reihenfolge (80 Slots, dekodiert).

**Parserstatus.** **Kein Body-Parser.** `check_i13_formids` gibt statisch `NOT_CHECKED` zurück (`save_integrity.py:546–553`). Es existiert keine Funktion im Projekt, die Body-Records liest.

**Vorhandene Evidenz.** Zwei globale Verteilungsmessungen über den Body (Save47):

| Messung | Ergebnis | Nullmodell |
|---|---|---|
| 4-Byte-Werte mit High-Byte < 80 (gültiger Slot) | 64,50 % | 31,25 % (= 80/256) |
| Rasterabhängigkeit (Startoffset +0…+3) | 64,50 / 63,73 / 63,73 / 65,62 % | — |
| 4-Byte-Werte, die als Offset in den Payload zeigen | 20,20 % | ~0,55 % |
| High-Byte == 0 | 34,94 % | 0,39 % |

Das Nullmodell wurde mit 2 MB Zufallsbytes gemessen und traf den theoretischen Erwartungswert (31,24 % vs. 31,25 %) — die Messmethode ist also kalibriert.

**Interpretation — ausdrücklich HEURISTIC.** Der Body ist **nicht** Zufallswärme: deutlich mehr kleine High-Bytes und massenhaft pointerartige Werte als bei Rauschen zu erwarten. Das ist konsistent mit dem bekannten Pointer-Block am Body-Anfang. Es belegt **keine** FormIDs.

**Warum das kein Fortschritt für I-13 ist:** Ein 4-Byte-Wert mit High-Byte 0 könnte ein Basisspiel-FormID, eine Koordinate, ein Zähler, ein Offset oder ein Fragment eines 8-Byte-Pointers sein. Entscheidend ist nicht die Verteilung, sondern die **Feldgrenze** — und die ist unbekannt. Die Rasterabhängigkeit (63,7–65,6 %) zeigt zusätzlich, dass die genaue Zahl von der willkürlichen Annahme eines 4-Byte-Rasters abhängt.

**Fehlende Evidenz — konkret benannt:**
1. **Record-Grenzen im Body.** Es gibt keine 4-Byte-Signaturen (0 Treffer für `REFR`, `ACHR`, `CELL`, `STDT`, `GBFM`, `MSTT`, `STND`, `FORM`), keine erkennbaren Längenpräfixe.
2. **Slot → Master-Index-Zuordnung.** Die Reihenfolge der 80 Plugins ist lesbar; ob Slot *n* dem Master-Index *n* entspricht, ist nicht belegt.
3. **Bedeutung der elf übrigen Body-Pointer** aus dem Kopfbereich.

**Ursache des offenen Status.** **Echte Formatforschung fehlt.** Nicht die Implementierung: Selbst eine perfekte Prüfimplementierung hätte nichts, worauf sie zeigen könnte.

**Technische Machbarkeit.** **Nein, derzeit nicht** — nicht ohne externe Annahmen. Jede heute gebaute FormID-Prüfung wäre eine Heuristik mit unbekannter Fehlerrate. Sie würde bei einem echten Save vermutlich Fehlalarme produzieren und das Vertrauen in die anderen 13 Prüfungen beschädigen.

**Notwendige nächste Schritte.** Kein Teil dieses Auftrags, ausdrücklich separat zu entscheiden:
1. Body-Struktur über die zwei bekannten Pointer-Ziele hinaus erschließen (v. a. `pointer[0]`, `pointer[1]`, `pointer[11]`).
2. Vergleich mit einem zweiten Spielstand, bei dem **eine** bekannt veränderte Aktion dazwischenliegt — Differenz auf Strukturebene statt Byteebene.
3. Erst wenn Feldgrenzen stehen: FormID-Kandidaten mit Record-Kontext prüfen, nicht global.

---

### B.4 — I-14 Sequenzkonsistenz

**Prüfziel.** Über mehrere Saves desselben Charakters prüfen, ob FileTime, Level und Spielzeit monoton verlaufen — also zurückgerollte oder gemischte Spielstände erkennen.

**Datenquelle.** Zwei oder mehr `DatHeader` desselben Charakters; alle Felder sind bereits dekodiert.

**Parserstatus.** Vollständig implementiert (`check_i14_sequence`, `save_integrity.py:555–575`). Signatur: `run_all(path, sequence=…)`.

**Vorhandene Evidenz.** Die sechs Saves sind eine echte Zeitreihe (Charakter „Cole", Level 24 durchgehend):

| FileTime (UTC) | Level | Spielzeit |
|---|---|---|
| 134356099865691096 | 24 | 2d.10h.33m |
| 134358573015793139 | 24 | 2d.10h.34m |
| 134358573240754512 | 24 | 2d.10h.34m |
| 134358574084798719 | 24 | 2d.10h.35m |
| 134358599053892393 | 24 | 2d.10h.55m |
| 134358605546179676 | 24 | 2d.11h.5m |

`run_all(newest, sequence=<alle sechs Header>)`:

```
I-14 status  : PASS
I-14 detail  : 6 Saves monoton in Level und Zeit
I-14 evidence: {'saves': 6, 'span': [134356099865691096, 134358605546179676]}
Gesamt       : PASS   (vorher ohne Sequenz: NOT_CHECKED)
```

**Negativtest** (einmalig Level künstlich um 5 gesenkt): `I-14 = WARNING`, Detail „Level faellt von 24 auf 19". Die Prüfung ist also falsifizierbar und nicht auf Immer-PASS verdrahtet.

**Fehlende Evidenz.** Keine. Die Prüfung ist vollständig belegt — mit echten Daten und mit Gegenprobe.

**Ursache des offenen Status.** **Reine Verdrahtung.** Die Prüfung existiert und funktioniert, aber der Produktaufruf setzt keine Sequenz: `cmd_save_verify` ruft `run_all(src, data_dir=...)` ohne `sequence`-Argument auf. Deshalb greift der frühe Ausstieg `if not ctx.sequence: return NOT_CHECKED`.

**Technische Machbarkeit.** **Ja, sofort** — der Code ist fertig, es fehlt nur der Aufrufer.

**Notwendige nächste Schritte.** Eine der drei Varianten:
1. **`--sequence <pfad>…`** — explizite Saves, konservativ, keine Überraschungen.
2. **Verzeichnis-Scan** (`--sequence-dir`) mit Filter auf gleichen `character_key`, nur lesend.
3. **Automatik** beim `save verify` im gleichen Ordner — maximaler Nutzen, aber implizit; braucht eine klare Anzeige, welche Saves einbezogen wurden.

Empfehlung: Variante 1 + 2, mit Anzeige der einbezogenen Dateien im Report. Automatik erst, wenn die Anzeige steht.

**Präzisierung der Aussagekraft:** I-14 prüft **eine Chronologie-Annahme** (Level und Zeit laufen vorwärts). Sie erkennt zurückgerollte Saves und gemischte Installationen. Sie erkennt **nicht**, ob ein Spielstand inhaltlich konsistent ist — ein manipulierter Save mit sauberer Zeitfolge besteht I-14.

---

## C. Evidenzmatrix

| Indikator | Daten vorhanden | Parser vorhanden | Nachweis vorhanden | Status |
|---|---|---|---|---|
| **I-01…I-08, I-10, I-11** | ja | ja | ja (6/6 reale Saves, Negativtests) | **PROVEN / PASS** |
| **I-09** `headerSize` | ja | ja (Feld gelesen) | **ja — Formel `padEnd − 16` in 6/6** | **PROVEN** (Implementierung ausstehend) |
| **I-12** Abhängigkeiten | ja (Liste) | ja | **ja — lauffähig, WARNING bei 78 fehlenden** | **PROVEN lauffähig**, Produkt liefert NOT_CHECKED ohne `--data-dir` |
| **I-13** FormIDs | Body vorhanden | **nein** | nein — Record-Grenzen unbekannt | **UNKNOWN** (blockiert) |
| **I-14** Sequenz | ja | ja | **ja — PASS + Negativtest WARNING** | **PROVEN** (Verdrahtung ausstehend) |

---

## D. Abgrenzung — was ist nach diesem Stand zulässig

### Zulässige Aussagen

| Aussage | Grundlage |
|---|---|
| Ein Save ist **strukturell** intakt: Container-Geometrie, Längen, Dekompression, Blockgrenzen | I-01…I-08, I-10, I-11 in 6/6 |
| Die Plugin-Liste ist **vollständig und bytegenau** gelesen (80 Einträge, Blockende exakt) | I-11, Block-Delta 0 in 6/6 |
| `headerSize` ist konsistent zur Header-Geometrie (`padEnd − 16`) | 6/6 Beleg, neue Erkenntnis |
| Die Saves eines Charakters bilden eine **monotone Zeitreihe** | I-14 PASS, 6 Saves |
| Dem Save **fehlen** Plugins gegenüber einer konkreten Installation | I-12, 78 von 80 gegenüber lokalem Verzeichnis |
| Der Body ist **nicht zufällig strukturiert** (viele pointerartige Werte) | HEURISTIC, kalibriertes Nullmodell |

### Ausdrücklich **nicht** zulässige Aussagen

| Aussage | Warum nicht |
|---|---|
| „Der Spielstand ist ladbar" | Keine Prüfung öffnet das Spiel. Struktur ≠ Engine-Ladbarkeit |
| „Der Spielstand ist spielbar" | Setzt Ladbarkeit voraus, plus Engine-interne Invarianten |
| „Es gibt keine verwaisten Referenzen" | I-13 nicht durchführbar; Body-Record-Ebene unbekannt |
| „Alle Objekte sind konsistent" | Objektebene nicht erschlossen (Audit 3.4) |
| „Die FormIDs sind gültig" | Slot→Master-Index nicht belegt, keine Record-Grenzen |
| „Der Save ist frei von Schäden" | Nur strukturell geprüft; semantische Schäden unsichtbar |
| „`total = PASS` heißt gesund" | `PASS` heißt: die 10 bewerteten Strukturregeln sind erfüllt |

### Die fünf Ebenen, getrennt gehalten

| Ebene | Abgedeckt durch | Stand |
|---|---|---|
| **Strukturelle Integrität** | I-01…I-08, I-10, I-11 (+ I-09 nach Implementierung) | **weitgehend PROVEN** |
| **Interne Referenzkonsistenz** | I-13 | **nicht prüfbar** |
| **Semantische Konsistenz** | I-14 (nur Zeit-/Level-Achse) | **teilweise PROVEN** |
| **Engine-Ladbarkeit** | nichts | **nicht geprüft, nicht prüfbar ohne Spielstart** |
| **Spielbarkeit** | nichts | **nicht prüfbar** |

---

## E. Priorisierung — was als Nächstes

**Reihenfolge nach Nutzen pro Aufwand und nach Abhängigkeiten:**

### E1 — I-09 implementieren (höchste Priorität)

- **Aufwand:** klein. Formel steht, alle Eingangswerte liefert der Parser, keine neue Abhängigkeit.
- **Nutzen:** schließt eine der beiden dauerhaften UNKNOWN-Lücken; macht 12/14 bewertbar; erkennt manipulierte Größenfelder und Layout-Verschiebungen deterministisch.
- **Abhängigkeit:** keine.
- **Risiko:** niedrig. Der einzige Vorbehalt ist die Falsifikationsgrenze (nur `playtime` variiert). Empfehlung: die Formel zusätzlich in einem synthetischen Test mit abweichenden Stringlängen prüfen, bevor `FAILED` vergeben wird.

### E2 — I-14 verdrahten (zweitgrößter Nutzen, kleinster Aufwand)

- **Aufwand:** sehr klein — der Code ist fertig, es fehlt ein Argument und ein Aufruf.
- **Nutzen:** eine echte inhaltliche Aussage (Zeitreihe) in einem ansonsten rein strukturellen Report.
- **Abhängigkeit:** keine. Wichtig: Anzeige der einbezogenen Saves, sonst ist das Ergebnis nicht nachvollziehbar.
- **Risiko:** niedrig, sofern kein impliziter Verzeichnis-Scan ohne Anzeige gebaut wird.

### E3 — I-12 nutzbar machen (Umgebungsfrage, nicht Code)

- **Aufwand:** klein (Pfad-Autodetect) bis null (manuell mit `--data-dir` heute schon möglich).
- **Nutzen:** praktisch hoch — „diesem Save fehlen 3 Plugins" ist die konkreteste Aussage, die das Produkt treffen kann.
- **Abhängigkeit:** ein Data-Verzeichnis, das zur Installation des Spielstands passt. Auf diesem Host nicht vorhanden.
- **Risiko:** mittel — ein WARNING aus I-12 muss klar als **Installations**abweichung kommuniziert werden, nicht als Save-Defekt. Sonst entsteht ein falscher Alarm.

### E4 — I-13: nicht priorisieren

- **Aufwand:** unbestimmt, weil Formatforschung mit unbekanntem Ausgang.
- **Nutzen:** hoch, aber nicht erreichbar.
- **Abhängigkeit:** Record-Grenzen im Body, Slot→Master-Index. Beides fehlt.
- **Empfehlung:** als eigenständiges Forschungsvorhaben führen, nicht als Prüfungs-Implementierung. Ein „wir bauen die Prüfung, kriegen die Semantik später" wäre die schlechteste Variante — es würde eine Heuristik mit unbekannter Fehlerrate als Befund ausgeben.

**Empfohlene Reihenfolge:** **E2 → E1 → E3** (nach Aufwand) oder **E1 → E2 → E3** (nach Vollständigkeit). Ich empfehle E1 zuerst, weil es eine dauerhafte UNKNOWN-Lücke schließt und den größeren Erkenntniswert hat; E2 kann direkt danach im selben Zug erfolgen.

---

## F. Reproduzierbarkeit

### Verwendete Dateien

| Datei | Rolle |
|---|---|
| `ssb_i/save_integrity.py` | Prüfungen I-01…I-14, `build_context`, `run_all` |
| `ssb_i/savegame_provider.py` | Container, Header, Plugin-Kette, String-Pool |
| `sfda_cli.py` | Aufrufpfad `save verify` (keine Sequenz, kein `--data-dir`-Default) |
| `~/ssb_probes/saves_07oct_2026/*.sfs` | sechs reale Spielstände, read-only |
| `~/Games/Starfield/Data/` | lokales Data-Verzeichnis (2 Plugins) |

### HAShes der sechs Originale (vor **und** nach der Untersuchung identisch)

```
c9b1bb5b4422fd784ba4158069111cad3a62036dad4513738c8564ccc3439e71  Autosave1_…_24_0_4.sfs
451ca3e3b8b7b70b9882b7d9404b3e3c758248b0349a7df2fe831804a0434ca1  Autosave2_…_24_0_4.sfs
073f355cb3a4481867129be7f8cbce8f7c3a2d65c07e78b09bc3aef7b6f421b6  Autosave3_…_24_0_4.sfs
53df16b41a7eeb4fa4275e00339cfa0c9202ead27448a6d782b45e198123294f  Exitsave0_…_24_0_4.sfs
174b9310c9f60757abc7f2e66b8091595dfd12502c2aca08bac0fb673bc80f2b  Save46_…_24_0_4.sfs
bbfaba67aa07cbfdffcae59671211f0e064c632d3c9d518432a920fa69f267d8  Save47_…_24_0_4.sfs
```

### Verwendete Befehle

```bash
# Ausgangs- und Endkontrolle
git rev-parse HEAD && git status --short
sha256sum ~/ssb_probes/saves_07oct_2026/*.sfs

# I-09: Header-Feldpositionen und Formelpruefung
python3 /tmp/gap_i09_formula.py

# I-14: Sequenz mit echten Headern + Negativtest
python3 /tmp/gap_analysis.py

# I-12: gegen echtes Data-Verzeichnis + Gegenprobe
python3 /tmp/gap_i12_i13.py

# I-13: High-Byte-Verteilung, Rasterkontrolle, Nullmodell
python3 /tmp/gap_i12_i13.py
```

Alle Skripte sind read-only: sie öffnen Saves ausschließlich mit `"rb"`, schreiben nichts und legen nur im Fall des Nullmodells einen In-Memory-Puffer an. Die Hilfsskripte liegen in `/tmp` und sind **nicht** Teil des Repositories.

### Testläufe

| Lauf | Ergebnis |
|---|---|
| `QT_QPA_PLATFORM=offscreen pytest tests -q` (Bestand, unverändert) | 155 passed, 19 skipped |
| `run_all(Save47)` ohne Sequenz, ohne Data-Dir | `total = PASS`, Abdeckung **10/14** |
| `run_all(Save47, sequence=<6 Header>)` | `total = PASS`, **I-14 = PASS**, Abdeckung 11/14 möglich |
| `run_all(Save47, data_dir=~/Games/Starfield/Data)` | `total = WARNING`, **I-12 = WARNING**, Abdeckung 11/14 |
| Negativtest I-14 (Level −5) | `I-14 = WARNING`, „Level faellt von 24 auf 19" |
| Nullmodell I-13 (2 MB Zufallsbytes) | 31,24 % vs. theoretisch 31,25 % — Messmethode kalibriert |

### Relevante Fundstellen im Code

| Thema | Fundstelle |
|---|---|
| I-09 statisch UNKNOWN | `ssb_i/save_integrity.py:466–478` |
| I-12 Implementierung | `ssb_i/save_integrity.py:517–537` |
| I-12 früher Ausstieg ohne `data_dir` | `ssb_i/save_integrity.py:524–526` |
| I-13 statisch NOT_CHECKED | `ssb_i/save_integrity.py:546–553` |
| I-14 Implementierung | `ssb_i/save_integrity.py:555–575` |
| I-14 früher Ausstieg ohne Sequenz | `ssb_i/save_integrity.py:557–559` |
| Aufruf ohne `sequence`/`data_dir` | `sfda_cli.py` → `cmd_save_verify` |
| `headerSize` gelesen, unbenutzt | `ssb_i/savegame_provider.py` → `DatHeader.header_size` |

### Git-Abschlusskontrolle

```
HEAD   vorher : ed5587acd99b6a45982b0c0a55ad11afb5e50d9a
HEAD   nachher: ed5587acd99b6a45982b0c0a55ad11afb5e50d9a   (unverändert)
Branch        : main
Working Tree  : unverändert; sieben untracked Artefakte vorhanden:
  COMMIT_1_5_3_REPORT.md
  EXTERNAL_SAVEGAME_TOOLING_AUDIT.md
  SAVE_FORMAT_AND_INTEGRITY_IMPLEMENTATION_REPORT.md
  SAVE_INTELLIGENCE_AUDIT.md
  SAVE_INTELLIGENCE_SPEC.md
  audit/save-intelligence/audit.py
  audit/save-intelligence/verify_external_format.py
  (+ SAVE_INTEGRITY_GAP_ANALYSIS.md, diese Datei)
```

Kein `git add`, kein Commit, kein Push, kein Stash, kein Reset, kein Checkout. Keine Datei im Repository geändert.

---

## Gesamturteil

**Die vier Indikatoren haben vier verschiedene Ursachen.**

- **I-09** war eine Erkenntnislücke und ist geschlossen: `headerSize == padEnd − 16` in 6/6 Saves, und die „nicht auflösbare" 43 zerlegt sich sauber in 16 + 27. **PROVEN**, Implementierung ausstehend.
- **I-12** ist fertig und lauffähig; es fehlt das passende Data-Verzeichnis. Mit dem lokalen Verzeichnis liefert es korrekt `WARNING` (78 von 80 Plugins fehlen). **PROVEN lauffähig.**
- **I-13** ist die einzige echte Blockade: Ohne Record-Grenzen im Body gibt es keinen Ort, an dem eine FormID-Prüfung ansetzen könnte. Alle messbaren Verteilungen sind HEURISTIC und nicht zuordenbar. **UNKNOWN**, Formatforschung nötig.
- **I-14** ist fertig und liefert mit echten Daten `PASS`; der Negativtest greift. Es fehlt ausschließlich der Aufrufer. **PROVEN**, Verdrahtung ausstehend.

**Damit sind 13 von 14 Prüfungen erreichbar** (I-13 ausgenommen), und die Abdeckung könnte von 10/14 auf 12/14 steigen, ohne eine Zeile Formatforschung. Das ist der eigentliche Ertrag dieser Untersuchung: Die verbleibende Lücke ist kleiner, als der Status `NOT_CHECKED` vermuten ließ — und sie ist an genau einer Stelle echt.

**Ein bestandener Strukturtest bleibt kein Beweis der Ladbarkeit.** Auch mit 13/14 bewerteten Prüfungen gilt: kein Spielstart, keine Engine-Invariante, keine Aussage über Spielbarkeit.
