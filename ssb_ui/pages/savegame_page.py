"""Savegame Analyzer page — wires the SSB-I savegame provider into a Qt widget.

Layout:
+---------------------------------------------------------------+
| [Open .sfs...] [Run Diff vs another save] [Save Report] |
+---------------------------+-------------------+---------------+
| Player Info Card (O-6)    |                   | Plugins       |
| alle Headerfelder, zwei-  |                   | Starfield.esm |
| spaltig: PLAYER | SAVE    |                   | BlueprintShips|
+---------------------------+-------------------+ Constellation |
| BCPS Container            |                   |               |
| chunk_count=40 padding=16 |                   |               |
+---------------------------+-------------------+---------------+
| Header text (pretty-printed from SFS_SAVEGAME parse)            |
|                                                              |
+---------------------------------------------------------------+
"""
from __future__ import annotations

import json
from pathlib import Path

from ssb_i.errors import public_error
from ssb_i.savegame_provider import player_view_text, public_header_view
from ssb_ui.theme import (

    ACCENT,
    CARD,
    CARD_EDGE,
    FIELD,
    MONO_FAMILY_CSS,
    ON_ACCENT,
    ROW_ALT,
    STATUS_FAIL,
    STATUS_INFO,
    STATUS_OK,
    STATUS_WARN,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    body_font,
    display_width_meter,
    mono_font,
    status_color,
)

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QFont, QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QFileDialog, QFrame, QPlainTextEdit, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox,
)

#: Alte Namen bleiben als Aliase erhalten — sie werden in mehreren Dateien
#: benutzt. Die Werte sind jetzt die neutralen aus ``ssb_ui.theme``.
DARK_BG = SURFACE
PANEL_BG = CARD
GRID_LINE = CARD_EDGE
TEXT_MAIN = TEXT
ACCENT_CYAN = ACCENT
ACCENT_PINK = STATUS_FAIL
ACCENT_AMBER = STATUS_WARN
ACCENT_GREEN = STATUS_OK


# =============================================================================
# Status-Highlighter fuer die Integritaetsuebersicht
# =============================================================================
class IntegrityStatusHighlighter(QSyntaxHighlighter):
    """Faerbt die Statuswoerter der Integritaetsuebersicht semantisch ein.

    Vorher war die Uebersicht reiner Text: PASS, WARNING und FAILED waren
    an einem Blick nicht unterscheidbar. Hier traegt die Farbe eine
    **Bedeutung** — sie ist an den geschlossenen Statusvokabular gebunden
    (``ssb_ui.theme.STATUS_COLORS``). Ein unbekanntes Wort bekommt keine
    erfundene Farbe, sondern bleibt neutral.

    Das Highlighter aendert den Text **nicht**: ``toPlainText()`` liefert
    unveraendert dieselben Zeilen wie vorher. Nur die Darstellung aendert
    sich.
    """

    #: Reihenfolge = Prioritaet. FAILED wird vor PASS geprueft, damit
    #: "NOT_CHECKED" nicht als "CHECKED" gelesen wird und "FAILED" nicht
    #: an "PASS" scheitert.
    STATUS_WORDS = ("FAILED", "WARNING", "NOT_CHECKED", "UNKNOWN", "PASS")

    def __init__(self, document):
        super().__init__(document)
        self._formats = {}
        for status in self.STATUS_WORDS:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(status_color(status)))
            self._formats[status] = fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt-Namenskonvention)
        for status in self.STATUS_WORDS:
            start = 0
            while True:
                index = text.find(status, start)
                if index < 0:
                    break
                before = text[index - 1] if index else " "
                after_index = index + len(status)
                after = text[after_index] if after_index < len(text) else " "
                # Nur ganze Woerter — "PASS" in "PASSED" faellt nicht darunter.
                if not before.isalnum() and not after.isalnum():
                    self.setFormat(index, len(status), self._formats[status])
                start = index + 1


# =============================================================================
# Card / panel widget — generic container with title + body
# =============================================================================
class CyberPanel(QFrame):
    """Card-style container with a neutral surface and a quiet title label.

    Frueher hatte jede Karte einen cyanfarbenen Rand oben und eine
    cyanfarbene Ueberschrift. Das war Dekoration ohne Bedeutung: alle drei
    Karten (Player, BCPS, Plugins) sahen gleich wichtig aus, die
    visuelle Hierarchie war damit flau. Jetzt traegt nur die Karte als
    solche eine neutrale Flaeche; die Akzentfarbe ist aktiven Zustaenden
    vorbehalten.
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD};
                border: 1px solid {CARD_EDGE};
                border-radius: 3px;
            }}
            QLabel#cardTitle {{
                color: {TEXT_DIM};
                font-family: {MONO_FAMILY_CSS};
                font-size: 9pt;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 2px 0;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        title_label = QLabel(title.upper())
        title_label.setObjectName("cardTitle")
        title_label.setFont(mono_font(9, bold=True))
        layout.addWidget(title_label)
        self.body_layout = layout

    def add_widget(self, w):
        self.body_layout.addWidget(w)


# =============================================================================
# Savegame page
# =============================================================================
class SavegamePage(QWidget):
    def __init__(self):
        super().__init__()
        self.current_path = None
        self.decompressed = None
        self.header = None
        self.plugins = None
        self.string_pool = None
        self.integrity_report = None
        # Letzter Dekodier-Fehler als Text. Der Selbsttest (--self-test) laeuft
        # kopflos und darf keinen modalen Dialog oeffnen — dort wird die
        # Meldung ueber dieses Feld ausgegeben statt in einer QMessageBox.
        self.last_error = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        open_btn = QPushButton("▣  Open .sfs File...")
        # Die Hauptaktion ist die einzige akzentfarbige Flaeche der Seite.
        open_btn.setStyleSheet(self._primary_btn_style())
        open_btn.clicked.connect(self.on_open)
        toolbar.addWidget(open_btn)

        diff_btn = QPushButton("⇄  Diff vs another save...")
        diff_btn.setStyleSheet(self._btn_style(ACCENT))
        diff_btn.clicked.connect(self.on_diff)
        toolbar.addWidget(diff_btn)

        report_btn = QPushButton("⤓  Save Report (JSON)...")
        report_btn.setStyleSheet(self._btn_style(ACCENT))
        report_btn.clicked.connect(self.on_save_report)
        toolbar.addWidget(report_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # Status row
        self.status_label = QLabel("No file loaded · pick a .sfs file to begin")
        self.status_label.setStyleSheet(f"color: {TEXT_DIM}; font-family: {MONO_FAMILY_CSS};")
        root.addWidget(self.status_label)

        # Top grid: 3 cards
        grid = QGridLayout()
        grid.setSpacing(12)

        # Card 1: Player — vollstaendige Spielerinformation (O-6).
        # Seit O-6 zeigt die Karte den gesamten dekodierten Header, nicht mehr
        # vier Zeilen. Deshalb ein eigener, schreibgeschuetzter Textbereich
        # (Monospace, kein Umbruch) statt eines umbrechenden Labels: die
        # Punkt-Ausrichtung bleibt so erhalten, und der Nutzer kann die
        # Angaben markieren und kopieren.
        self.player_card = CyberPanel("Player")
        self.player_view = QPlainTextEdit()
        self.player_view.setReadOnly(True)
        self.player_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.player_view.setFrameShape(QFrame.NoFrame)
        self.player_view.setPlainText("—")
        # Monospace ist hier **fachlich** noetig: die zweispaltige Ansicht
        # richtet ihre Werte ueber Punktfuellung aus. Ein reiner
        # Stylesheet-Fontname genuegt nicht — fehlt die Familie, faellt Qt auf
        # eine proportionale Schrift zurueck und die Spalten verschieben sich
        # (gemessen: 'Cascadia Code' ist nicht auf jeder Plattform installiert).
        # Der Style-Hint laesst Qt eine Monospace-Schrift der Plattform waehlen.
        player_font = QFont("Cascadia Code")
        player_font.setStyleHint(QFont.Monospace)
        player_font.setPointSize(10)
        self.player_view.setFont(player_font)
        # O-7: Der Breitenmesser misst die **Anzeigebreite** ueber
        # QFontMetrics. Ohne ihn richtet die zweispaltige Karte nach
        # Zeichenzahl aus — Breitzeichen (CJK, Emoji) belegen dort zwei
        # Spalten und ruecken die rechte Spalte nach links.
        self._player_width = display_width_meter(player_font)
        self.player_view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {PANEL_BG}; color: {TEXT_MAIN};"
            f" border: none; selection-background-color: {ACCENT};"
            f" selection-color: {ON_ACCENT}; }}")
        self.player_view.setMinimumHeight(232)
        self.player_card.add_widget(self.player_view)
        grid.addWidget(self.player_card, 0, 0, 1, 3)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Card 2: Container metadata
        self.container_card = CyberPanel("BCPS Container")
        self.container_label = QLabel("—")
        self.container_label.setStyleSheet(f"color: {TEXT_MAIN}; font-family: {MONO_FAMILY_CSS}; font-size: 10pt;")
        self.container_label.setWordWrap(True)
        self.container_card.add_widget(self.container_label)
        # Die Karte teilt sich die Zeile mit der Plugin-Liste und wird dabei
        # gestreckt. Ohne den Stretch zentriert Qt den Inhalt senkrecht und
        # die Ueberschrift rutscht nach unten.
        self.container_card.body_layout.addStretch(1)
        grid.addWidget(self.container_card, 1, 0, 1, 1)

        # Card 3: Plugins
        self.plugins_card = CyberPanel("Plugins")
        self.plugins_tree = QTreeWidget()
        self.plugins_tree.setHeaderLabels(["Name", "Type"])
        self.plugins_tree.setRootIsDecorated(False)
        self.plugins_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {FIELD};
                color: {TEXT};
                border: none;
                font-family: {MONO_FAMILY_CSS};
                font-size: 9pt;
            }}
            QTreeWidget::item {{ padding: 2px; }}
            QTreeWidget::item:alternate {{ background-color: {ROW_ALT}; }}
            QTreeWidget::item:selected {{
                background-color: {ACCENT};
                color: {ON_ACCENT};
            }}
        """)
        self.plugins_tree.setAlternatingRowColors(True)
        # Spaltenbreiten: ohne sie schneidet Qt die Namen auf "Starfield.e..." ab
        self.plugins_tree.setColumnWidth(0, 260)
        self.plugins_tree.setColumnWidth(1, 70)
        self.plugins_tree.setMinimumHeight(160)
        self.plugins_count_label = QLabel("—")
        self.plugins_count_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: {MONO_FAMILY_CSS}; font-size: 8pt;")
        self.plugins_count_label.setWordWrap(True)
        self.plugins_card.add_widget(self.plugins_count_label)
        self.plugins_card.add_widget(self.plugins_tree)
        grid.addWidget(self.plugins_card, 1, 1, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        root.addLayout(grid)

        # Bottom: tabs for raw header / diff view
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {GRID_LINE};
                background-color: {DARK_BG};
            }}
            QTabBar::tab {{
                background-color: {PANEL_BG};
                color: {TEXT_DIM};
                padding: 8px 18px;
                border: 1px solid {GRID_LINE};
                border-bottom: none;
                font-family: {MONO_FAMILY_CSS};
            }}
            QTabBar::tab:selected {{
                color: {TEXT};
                border-bottom: 2px solid {ACCENT};
            }}
            QTabBar::tab:hover {{
                color: {TEXT};
            }}
        """)

        # Header dump tab
        self.header_dump = QPlainTextEdit()
        self.header_dump.setReadOnly(True)
        self.header_dump.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {DARK_BG};
                color: {TEXT_MAIN};
                border: none;
                font-family: {MONO_FAMILY_CSS};
                font-size: 10pt;
                padding: 10px;
            }}
        """)
        self.tabs.addTab(self.header_dump, "Header Dump")

        # Diff tab (initially hidden until we run a diff)
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {DARK_BG};
                color: {TEXT_MAIN};
                border: none;
                font-family: {MONO_FAMILY_CSS};
                font-size: 10pt;
                padding: 10px;
            }}
        """)
        self.tabs.addTab(self.diff_view, "Diff vs Other")

        # Integritaets-Tab: Einzelpruefungen mit Status und Begruendung.
        self.integrity_view = QPlainTextEdit()
        self.integrity_view.setReadOnly(True)
        self.integrity_view.setStyleSheet(self._mono_style())
        # Die Statuswoerter werden semantisch eingefaerbt. Der Highlighter
        # aendert den Text nicht — er aendert nur die Darstellung.
        self.integrity_highlighter = IntegrityStatusHighlighter(
            self.integrity_view.document())
        self.tabs.addTab(self.integrity_view, "Integrity")

        # String-Pool-Tab: Zusammenfassung sofort, volle Liste nur auf Klick.
        self.strings_panel = QWidget()
        strings_layout = QVBoxLayout(self.strings_panel)
        strings_layout.setContentsMargins(10, 10, 10, 10)
        strings_layout.setSpacing(6)
        self.strings_summary = QLabel("No file loaded")
        self.strings_summary.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: {MONO_FAMILY_CSS}; font-size: 9pt;")
        self.strings_summary.setWordWrap(True)
        strings_layout.addWidget(self.strings_summary)
        self.strings_load_btn = QPushButton("Load strings (read-only)")
        self.strings_load_btn.setStyleSheet(self._btn_style(ACCENT))
        self.strings_load_btn.clicked.connect(self.on_load_strings)
        self.strings_load_btn.setEnabled(False)
        strings_layout.addWidget(self.strings_load_btn, alignment=Qt.AlignLeft)
        self.strings_view = QPlainTextEdit()
        self.strings_view.setReadOnly(True)
        self.strings_view.setStyleSheet(self._mono_style())
        strings_layout.addWidget(self.strings_view, stretch=1)
        self.tabs.addTab(self.strings_panel, "String Pool")

        root.addWidget(self.tabs, stretch=1)

    # -----------------------------------------------------------------
    # Styles
    # -----------------------------------------------------------------
    def _mono_style(self) -> str:
        return f"""
            QPlainTextEdit {{
                background-color: {FIELD};
                color: {TEXT};
                border: none;
                font-family: {MONO_FAMILY_CSS};
                font-size: 10pt;
                padding: 10px;
            }}
        """

    def _btn_style(self, accent: str) -> str:
        """Neutraler Button.

        ``accent`` wird **nicht** mehr als Text- und Rahmenfarbe
        verwendet. Drei Buttons in drei Farben (cyan/pink/amber) waren
        Dekoration ohne Bedeutung — sie signalisierten nichts, weil es
        keine Prioritaet oder Gefahrenstufe gibt. Der Parameter bleibt in
        der Signatur, damit Aufrufer unveraendert bleiben; die
        Akzentfarbe wird nur noch fuer den Fokus verwendet.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {TEXT};
                border: 1px solid {CARD_EDGE};
                padding: 7px 14px;
                font-family: {MONO_FAMILY_CSS};
            }}
            QPushButton:hover {{
                border-color: {ACCENT};
                color: {ACCENT};
            }}
            QPushButton:focus {{
                border-color: {ACCENT};
            }}
            QPushButton:pressed {{
                background-color: {CARD_EDGE};
            }}
            QPushButton:disabled {{
                color: {TEXT_FAINT};
                border-color: {CARD_EDGE};
            }}
        """

    def _primary_btn_style(self) -> str:
        """Die eine ausgewaehlte Aktion der Seite."""
        return f"""
            QPushButton {{
                background-color: {ACCENT};
                color: {ON_ACCENT};
                border: 1px solid {ACCENT};
                padding: 7px 14px;
                font-family: {MONO_FAMILY_CSS};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ACCENT};
                color: {ON_ACCENT};
                border-color: {ACCENT};
            }}
            QPushButton:pressed {{
                background-color: {CARD_EDGE};
                color: {TEXT};
            }}
        """

    # -----------------------------------------------------------------
    # Slots
    # -----------------------------------------------------------------
    def on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Starfield save", "",
            "Starfield Saves (*.sfs);;All Files (*)",
        )
        if not path:
            return
        self.load_file(path)

    def load_file(self, path: str, *, show_dialog: bool = True) -> bool:
        """Load and parse a .sfs file. Public so tests can call it.

        Rueckgabe: True bei Erfolg, False bei einem Dekodier-Fehler (Text steht
        in ``self.last_error``). Mit ``show_dialog=False`` wird KEIN modaler
        Dialog geoeffnet — im kopflosen Betrieb (``--self-test``) blockiert ein
        Dialog ohne Benutzer den Prozess und der Lauf endet nie
        (Befund SSB-I-Audit 05.11.2026: 100-Byte-Datei liess den Bundle-Lauf
        haengen statt mit Exit 1 zu enden).
        """
        from ssb_i.savegame_provider import SfsDecodeProvider
        provider = SfsDecodeProvider()
        self.last_error = None
        try:
            container = provider.read_container(path)
            decomp = provider.decompress(path)
            header = provider.parse_dat_header(decomp)
            info = provider.parse_plugin_info(decomp, header)
        except Exception as e:
            self.last_error = public_error(e)
            # Alten Zustand verwerfen: sonst zeigt die Oberfläche (und die
            # Hex-Ansicht) weiter die Bytes des vorherigen Saves.
            self.current_path = None
            self.decompressed = None
            self.header = None
            self.plugins = None
            self.status_label.setText(
                f"<span style='color:{STATUS_FAIL}'>● Decode failed</span> "
                f"<span style='color:{TEXT_DIM}'>{public_error(e)}</span>"
            )
            if show_dialog:
                QMessageBox.critical(self, "Decode failed", public_error(e))
            return False

        self.current_path = path
        self.decompressed = decomp
        self.header = header
        self.plugins = info

        # Populate cards
        self.player_view.setPlainText(self._format_player(header))
        self.container_label.setText(self._format_container(container))

        self.plugins_tree.clear()
        if getattr(info, "decode_state", "UNVERIFIED") == "VALIDATED":
            for p in info.normal:
                self._add_plugin_row(p.name, "Normal", p.is_native, p)
            for p in info.light:
                self._add_plugin_row(p.name, "Light", p.is_native, p)
            for p in info.medium:
                self._add_plugin_row(p.name, "Medium", p.is_native, p)
            self.plugins_count_label.setText(
                "%d normal · %d light · %d medium · %d total\n"
                "%d game · %d mod · %d with creation metadata"
                % (len(info.normal), len(info.light), len(info.medium), info.total,
                   info.game_count, info.mod_count, info.metadata_count))
        else:
            # Fail-closed: lieber nichts anzeigen als eine erfundene Liste.
            item = QTreeWidgetItem(["plugin list not decoded", "—"])
            # Semantisch: die Liste konnte nicht gelesen werden.
            item.setForeground(0, QColor(STATUS_WARN))
            self.plugins_tree.addTopLevelItem(item)
            self.plugins_count_label.setText(
                "UNVERIFIED · %s" % (getattr(info, "note", "") or "unbekannt"))

        # Header dump
        self.header_dump.setPlainText(self._format_header_full(header))

        # Integritaetspruefung (rein lesend, gleiche Datei)
        self._run_integrity(path)

        # String-Pool: nur Zusammenfassung, Liste erst auf Klick
        try:
            self.string_pool = provider.read_string_pool(decomp, header, info)
        except Exception as exc:                               # noqa: BLE001
            self.string_pool = None
            self.strings_summary.setText("String pool not readable: %s"
                                         % public_error(exc))
        else:
            pool = self.string_pool
            self.strings_summary.setText(
                "Status %s - %d strings (declared %d), %.1f%% printable\n"
                "Array at 0x%X, read up to 0x%X. %s"
                % (pool["status"], pool["count"], pool["declared_count"],
                   pool["printable_ratio"] * 100,
                   pool["string_array_offset"] or 0, pool["end"], pool["note"]))
            self.strings_view.setPlainText(
                'Read-only preview. Click "Load strings" to list the entries.')
        self.strings_load_btn.setEnabled(
            self.string_pool is not None and self.string_pool["status"] == "OK")

        # Status
        size_mb = len(self.decompressed or b"") / 1024 / 1024
        # R1_6 / O-9: die Statuszeile nennt keinen Dateinamen und keinen
        # Pfad mehr.
        self.status_label.setText(
            f"<span style='color:{STATUS_OK}'>● Loaded</span> "
            f"<span style='color:{TEXT_DIM}'>({size_mb:.2f} MB decompressed · {container.chunk_count} chunks)</span>"
        )
        return True

    def _run_integrity(self, path: str) -> None:
        """Fuehrt die Integritaetspruefung aus und zeigt sie im Integrity-Tab.

        UNKNOWN und NOT_CHECKED werden ausdruecklich als *nicht bewertet*
        getrennt von Fehlern gefuehrt — ein fehlender Befund ist kein PASS.
        """
        from ssb_i.save_integrity import (FAILED, WARNING, collect_sequence,
                                          format_sequence_summary, run_all)

        # Dieselbe Sequenz wie in der CLI: Saves aus dem Verzeichnis der
        # geladenen Datei. collect_sequence() waehlt nur aus und liefert in
        # Dateinamen-Reihenfolge; die chronologische Ordnung nach
        # Header-FileTime entsteht in check_i14_sequence(). Ohne diesen
        # Schritt zeigte die Oberflaeche fuer I-14 NOT_CHECKED, waehrend die
        # CLI PASS meldet.
        try:
            sequence = collect_sequence(path)
        except Exception:                                      # noqa: BLE001
            sequence = ()

        try:
            report = run_all(path, sequence=sequence)
        except Exception as exc:                               # noqa: BLE001
            self.integrity_report = None
            self.integrity_view.setPlainText(
                "Integrity check not runnable: %s" % public_error(exc))
            return
        self.integrity_report = report
        coverage = report.coverage
        header = [
            "INTEGRITAET: %s" % report.total,
            "PRUEFABDECKUNG: %d von %d Pruefungen bewertet "
            "(%d PASS, %d WARNING, %d FAILED, %d UNKNOWN, %d NOT_CHECKED)"
            % (coverage["assessed"], coverage["total"], coverage["PASS"],
               coverage["WARNING"], coverage["FAILED"], coverage["UNKNOWN"],
               coverage["NOT_CHECKED"]),
        ]
        if report.total == FAILED:
            header.append("ACHTUNG: mindestens eine Strukturregel ist verletzt.")
        elif report.total == WARNING:
            header.append("Hinweis: auffaellige Befunde, aber kein sicherer Schaden.")
        header.append("")
        header.append("--- Einzelpruefungen ---")
        lines = list(header)
        for check in report.checks:
            lines.append("%-4s %-12s %s" % (check.check_id, check.status, check.detail))
        if report.gaps:
            lines.append("")
            lines.append("--- NICHT BEWERTET (kein Fehler, aber auch keine Freigabe) ---")
            for gap in report.gaps:
                lines.append("%-4s %-12s %s" % (gap.check_id, gap.status, gap.detail))
        lines.append("")
        lines.append("Sequenz: %d Save(s) einbezogen (chronologisch nach Header-FileTime)."
                     % len(sequence))
        lines.extend(format_sequence_summary(report))
        lines.append("Hinweis: %s" % report.disclaimer)
        self.integrity_view.setPlainText("\n".join(lines))

    def on_load_strings(self) -> None:
        """Listet eine begrenzte Auswahl der String-Pool-Eintraege (read-only)."""
        if not self.string_pool:
            return
        pool = self.string_pool
        limit = 500
        lines = [
            "String pool: %d entries (declared %d), status %s"
            % (pool["count"], pool["declared_count"], pool["status"]),
            "Read-only. No object identity is derived from these texts.",
            "",
            "%5s  %10s  %s" % ("INDEX", "OFFSET", "TEXT"),
        ]
        for entry in pool["strings"][:limit]:
            lines.append("%5d  0x%08X  %s"
                         % (entry["index"], entry["offset"], entry["text"]))
        if len(pool["strings"]) > limit:
            lines.append("... %d more entries (list capped at %d)"
                         % (len(pool["strings"]) - limit, limit))
        self.strings_view.setPlainText("\n".join(lines))

    def current_buffer(self) -> tuple[str | None, bytes]:
        """Der zuletzt dekodierte Puffer für andere Ansichten (z. B. Hex).

        Rückgabe: (Bezeichnung oder None, Bytes). Beim Fehlschlag eines
        Dekodiervorgangs wird der alte Puffer verworfen, damit keine
        veralteten Bytes als aktuell angezeigt werden.

        R1_6 / F-2: die Bezeichnung ist **kein Pfad**. Der absolute
        Savegame-Pfad (``self.current_path``) wird nicht weitergegeben —
        er wuerde in der Hex-Viewer-Infozeile erscheinen. Es genuegt
        die Angabe, dass es sich um einen Save-Puffer handelt.
        """
        if self.last_error:
            return None, b""
        return ("save", self.decompressed or b"")

    def on_diff(self):
        if not self.current_path:
            QMessageBox.warning(self, "No file", "Open a save file first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a save to diff against", "",
            "Starfield Saves (*.sfs);;All Files (*)",
        )
        if not path:
            return
        from ssb_i.savegame_provider import SfsDecodeProvider
        provider = SfsDecodeProvider()
        try:
            result = provider.diff_saves(self.current_path, path, max_diff=500)
        except Exception as e:
            QMessageBox.critical(self, "Diff failed", public_error(e))
            return

        # Format
        # R1_6 / F-2: keine Savegame-Dateinamen in der Diff-Ansicht.
        lines = [
            "=== DIFF A  vs  B ===",
            f"Size A: {result['a_size']:,}   Size B: {result['b_size']:,}",
            f"Differing bytes (first 500): {result['diffs_count']}",
            "",
            f"{'OFFSET':>10}  {'A':>4}  {'B':>4}   ASCII",
        ]
        for d in result["diffs"][:300]:
            a_char = chr(d["a"]) if 32 <= d["a"] < 127 else "."
            b_char = chr(d["b"]) if 32 <= d["b"] < 127 else "."
            lines.append(f"  0x{d['offset']:08X}  0x{d['a']:02X}  0x{d['b']:02X}   {a_char} / {b_char}")
        self.diff_view.setPlainText("\n".join(lines))
        self.tabs.setCurrentWidget(self.diff_view)

    def on_save_report(self):
        if not self.current_path or not self.header or not self.plugins:
            QMessageBox.warning(self, "No file", "Open a save file first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save report", f"{Path(self.current_path).stem}.report.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        report = {
            # R1_6 / F-2: kein Pfad im Export. Der Dateiname des Exports
            # wird auch nicht in den Inhalt geschrieben.
            "decompressed_size": len(self.decompressed),
            # R1_6: nur die kontrollierte oeffentliche Headeransicht —
            # asdict(self.header) waere die vollstaendige interne
            # Repräsentation inkl. Spielername.
            "header": public_header_view(self.header),
            "plugins": self.plugins.to_dict(),
        }
        Path(path).write_text(json.dumps(report, indent=2))
        # R1_6 / F-2: der Dialog nennt keinen Pfad — weder absolut noch
        # als Dateiname. Die Meldung bleibt verstaendlich.
        QMessageBox.information(self, "Saved",
                                "Report written to the selected file.")

    # -----------------------------------------------------------------
    # Formatters
    # -----------------------------------------------------------------
    def _format_player(self, h) -> str:
        """Vollstaendige Spielerinformation (O-6).

        Das ist der **ausdruecklich angeforderte** Analysepfad: der Nutzer
        oeffnet ein Savegame, um dessen Inhalt zu sehen. Deshalb zeigt diese
        Ansicht jedes dekodierte Headerfeld — Name, Location, Playtime, Race,
        Level und alle weiteren. Die Auswahl und Reihenfolge steht in
        ``PLAYER_VIEW_FIELDS``; diese Methode formatiert nur noch.

        Die Privacy-Grenze bleibt davon unberuehrt: Diagnose-, Fehler- und
        Statusausgaben (Statuszeile, Header-Dump, Export, CLI) nutzen
        weiterhin ``public_header_view()``.
        """
        # O-7: Der Breitenmesser kommt aus der GUI-Schicht — der
        # Provider bleibt Qt-frei (siehe ssb_i/savegame_provider.py).
        return player_view_text(h, columns=2,
                                display_width=getattr(self, "_player_width", None))

    def _format_container(self, c) -> str:
        return (
            f"Version:        {c.version0}\n"
            f"Chunk count:    {c.chunk_count}\n"
            f"Uncompressed:   {c.uncompressed_size:,} bytes\n"
            f"Compressed at:  0x{c.compressed_offset:08X}\n"
            f"Padding size:   {c.padding_size}\n"
            f"Chunk size pre: {c.chunk_size_pre:,} bytes"
        )

    def _format_header_full(self, h) -> str:
        # R1_6: der Header-Dump ist eine Diagnoseansicht — er nutzt die
        # kontrollierte oeffentliche Headeransicht, nicht asdict(h).
        # Das Spielfeld (_format_player) bleibt davon unberuehrt (O-6).
        d = public_header_view(h)
        lines = []
        for k, v in d.items():
            lines.append(f"{k:.<26} {v}")
        return "\n".join(lines)

    def _add_plugin_row(self, name: str, ptype: str, is_native: bool,
                       entry=None):
        marker = "★ " if is_native else "  "
        item = QTreeWidgetItem([f"{marker}{name}", ptype])
        # Native Plugins tragen das ★-Zeichen — das ist die Kennzeichnung.
        # Eine eigene Zeilenfarbe waere Dekoration ohne Bedeutung: sie
        # wuerde eine Kategorie (Vanilla/Mod) farblich kodieren, obwohl
        # beides gleich gueltige Plugins sind. Der Text bleibt einheitlich.
        self.plugins_tree.addTopLevelItem(item)
        # Metadaten nur, wenn tatsaechlich vorhanden (nie Platzhalter zeigen).
        state = getattr(entry, "metadata_state", "absent") if entry else "absent"
        if state == "present":
            details = [f"creation: {entry.creation_name or '-'}"]
            if entry.creation_id:
                details.append(f"id: {entry.creation_id}")
            if entry.version:
                details.append(f"version: {entry.version}")
            if entry.achievement_friendly:
                details.append("achievement friendly")
            child = QTreeWidgetItem(["    " + " | ".join(details), ""])
            # Hier traegt die Farbe eine Bedeutung: Metadaten vorhanden.
            child.setForeground(0, QColor(STATUS_OK))
            item.addChild(child)
        elif state == "unreadable":
            child = QTreeWidgetItem(["    metadata unreadable", ""])
            # Ebenso semantisch: die Metadaten konnten nicht gelesen werden.
            child.setForeground(0, QColor(STATUS_FAIL))
            item.addChild(child)
