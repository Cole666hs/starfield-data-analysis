"""Savegame Analyzer page — wires the SSB-I savegame provider into a Qt widget.

Layout:
+---------------------------------------------------------------+
| [Open .sfs...] [Run Diff vs another save] [Save Report] |
+---------------------------------------------------------------+
| Player Info Card   | Container Metadata     | Plugins       |
| DANTE              | chunk_count=40         | Starfield.esm |
| L100               | uncompressed=10.3MB    | BlueprintShips|
| v1.7.23            | padding=16             | Constellation |
+---------------------------------------------------------------+
| Header text (pretty-printed from SFS_SAVEGAME parse)            |
|                                                              |
+---------------------------------------------------------------+
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QFileDialog, QFrame, QPlainTextEdit, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox,
)

# Cyberpunk accent colors (mirror of app.py — kept local for self-containment)
ACCENT_CYAN = "#00E5FF"
ACCENT_PINK = "#FF1F8F"
ACCENT_AMBER = "#FFB300"
ACCENT_GREEN = "#39FF14"
DARK_BG = "#0A0E14"
PANEL_BG = "#131822"
GRID_LINE = "#1F2937"
TEXT_MAIN = "#E8F0FF"
TEXT_DIM = "#7E8AA0"


# =============================================================================
# Card / panel widget — generic container with title + body
# =============================================================================
class CyberPanel(QFrame):
    """Card-style container with cyan border on top + title label."""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {PANEL_BG};
                border: 1px solid {GRID_LINE};
                border-top: 2px solid {ACCENT_CYAN};
                border-radius: 0;
            }}
            QLabel#cardTitle {{
                color: {ACCENT_CYAN};
                font-family: "Cascadia Code", monospace;
                font-size: 10pt;
                font-weight: bold;
                letter-spacing: 2px;
                padding: 4px 0;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(8)
        title_label = QLabel(title.upper())
        title_label.setObjectName("cardTitle")
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
        open_btn.setStyleSheet(self._btn_style(ACCENT_CYAN))
        open_btn.clicked.connect(self.on_open)
        toolbar.addWidget(open_btn)

        diff_btn = QPushButton("⇄  Diff vs another save...")
        diff_btn.setStyleSheet(self._btn_style(ACCENT_PINK))
        diff_btn.clicked.connect(self.on_diff)
        toolbar.addWidget(diff_btn)

        report_btn = QPushButton("⤓  Save Report (JSON)...")
        report_btn.setStyleSheet(self._btn_style(ACCENT_AMBER))
        report_btn.clicked.connect(self.on_save_report)
        toolbar.addWidget(report_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # Status row
        self.status_label = QLabel("No file loaded · pick a .sfs file to begin")
        self.status_label.setStyleSheet(f"color: {TEXT_DIM}; font-family: 'Cascadia Code';")
        root.addWidget(self.status_label)

        # Top grid: 3 cards
        grid = QGridLayout()
        grid.setSpacing(12)

        # Card 1: Player
        self.player_card = CyberPanel("Player")
        self.player_label = QLabel("—")
        self.player_label.setStyleSheet(f"color: {TEXT_MAIN}; font-family: 'Cascadia Code'; font-size: 10pt;")
        self.player_label.setWordWrap(True)
        self.player_card.add_widget(self.player_label)
        grid.addWidget(self.player_card, 0, 0)

        # Card 2: Container metadata
        self.container_card = CyberPanel("BCPS Container")
        self.container_label = QLabel("—")
        self.container_label.setStyleSheet(f"color: {TEXT_MAIN}; font-family: 'Cascadia Code'; font-size: 10pt;")
        self.container_label.setWordWrap(True)
        self.container_card.add_widget(self.container_label)
        grid.addWidget(self.container_card, 0, 1)

        # Card 3: Plugins
        self.plugins_card = CyberPanel("Plugins")
        self.plugins_tree = QTreeWidget()
        self.plugins_tree.setHeaderLabels(["Name", "Type"])
        self.plugins_tree.setRootIsDecorated(False)
        self.plugins_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {DARK_BG};
                color: {TEXT_MAIN};
                border: 1px solid {GRID_LINE};
                font-family: "Cascadia Code", monospace;
                font-size: 9pt;
            }}
            QTreeWidget::item {{ padding: 2px; }}
            QTreeWidget::item:alternate {{ background-color: #0e131c; }}
        """)
        self.plugins_tree.setAlternatingRowColors(True)
        # Spaltenbreiten: ohne sie schneidet Qt die Namen auf "Starfield.e..." ab
        self.plugins_tree.setColumnWidth(0, 260)
        self.plugins_tree.setColumnWidth(1, 70)
        self.plugins_tree.setMinimumHeight(160)
        self.plugins_count_label = QLabel("—")
        self.plugins_count_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: 'Cascadia Code'; font-size: 8pt;")
        self.plugins_count_label.setWordWrap(True)
        self.plugins_card.add_widget(self.plugins_count_label)
        self.plugins_card.add_widget(self.plugins_tree)
        grid.addWidget(self.plugins_card, 0, 2)

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
                font-family: "Cascadia Code", monospace;
            }}
            QTabBar::tab:selected {{
                color: {ACCENT_CYAN};
                border-bottom: 2px solid {ACCENT_CYAN};
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
                font-family: "Cascadia Code", monospace;
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
                font-family: "Cascadia Code", monospace;
                font-size: 10pt;
                padding: 10px;
            }}
        """)
        self.tabs.addTab(self.diff_view, "Diff vs Other")

        # Integritaets-Tab: Einzelpruefungen mit Status und Begruendung.
        self.integrity_view = QPlainTextEdit()
        self.integrity_view.setReadOnly(True)
        self.integrity_view.setStyleSheet(self._mono_style())
        self.tabs.addTab(self.integrity_view, "Integrity")

        # String-Pool-Tab: Zusammenfassung sofort, volle Liste nur auf Klick.
        self.strings_panel = QWidget()
        strings_layout = QVBoxLayout(self.strings_panel)
        strings_layout.setContentsMargins(10, 10, 10, 10)
        strings_layout.setSpacing(6)
        self.strings_summary = QLabel("No file loaded")
        self.strings_summary.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: 'Cascadia Code'; font-size: 9pt;")
        self.strings_summary.setWordWrap(True)
        strings_layout.addWidget(self.strings_summary)
        self.strings_load_btn = QPushButton("Load strings (read-only)")
        self.strings_load_btn.setStyleSheet(self._btn_style(ACCENT_CYAN))
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
                background-color: {DARK_BG};
                color: {TEXT_MAIN};
                border: none;
                font-family: "Cascadia Code", monospace;
                font-size: 10pt;
                padding: 10px;
            }}
        """

    def _btn_style(self, accent: str) -> str:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {accent};
                border: 1px solid {accent};
                padding: 8px 16px;
                font-family: "Cascadia Code", monospace;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background-color: {accent};
                color: {DARK_BG};
            }}
            QPushButton:pressed {{
                background-color: {accent};
                color: {DARK_BG};
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
            self.last_error = "%s: %s" % (type(e).__name__, e)
            # Alten Zustand verwerfen: sonst zeigt die Oberfläche (und die
            # Hex-Ansicht) weiter die Bytes des vorherigen Saves.
            self.current_path = None
            self.decompressed = None
            self.header = None
            self.plugins = None
            self.status_label.setText(
                f"<span style='color:{ACCENT_PINK}'>● Decode failed</span> "
                f"<span style='color:{TEXT_MAIN}'>{Path(path).name}</span> "
                f"<span style='color:{TEXT_DIM}'>{e}</span>"
            )
            if show_dialog:
                QMessageBox.critical(self, "Decode failed", str(e))
            return False

        self.current_path = path
        self.decompressed = decomp
        self.header = header
        self.plugins = info

        # Populate cards
        self.player_label.setText(self._format_player(header))
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
            item.setForeground(0, QColor(ACCENT_AMBER))
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
            self.strings_summary.setText("String pool not readable: %s: %s"
                                         % (type(exc).__name__, exc))
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
        self.status_label.setText(
            f"<span style='color:{ACCENT_GREEN}'>● Loaded</span> "
            f"<span style='color:{TEXT_MAIN}'>{Path(path).name}</span> "
            f"<span style='color:{TEXT_DIM}'>({size_mb:.2f} MB decompressed · {container.chunk_count} chunks)</span>"
        )
        return True

    def _run_integrity(self, path: str) -> None:
        """Fuehrt die Integritaetspruefung aus und zeigt sie im Integrity-Tab.

        UNKNOWN und NOT_CHECKED werden ausdruecklich als *nicht bewertet*
        getrennt von Fehlern gefuehrt — ein fehlender Befund ist kein PASS.
        """
        from ssb_i.save_integrity import FAILED, WARNING, run_all

        try:
            report = run_all(path)
        except Exception as exc:                               # noqa: BLE001
            self.integrity_report = None
            self.integrity_view.setPlainText(
                "Integrity check not runnable: %s: %s" % (type(exc).__name__, exc))
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

        Rückgabe: (Pfad oder None, Bytes). Beim Fehlschlag eines Dekodiervorgangs
        wird der alte Puffer verworfen, damit keine veralteten Bytes als aktuell
        angezeigt werden.
        """
        if self.last_error:
            return None, b""
        return self.current_path, (self.decompressed or b"")

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
            QMessageBox.critical(self, "Diff failed", str(e))
            return

        # Format
        lines = [
            f"=== DIFF {Path(self.current_path).name}  vs  {Path(path).name} ===",
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
            "path": self.current_path,
            "decompressed_size": len(self.decompressed),
            "header": self.header.to_dict(),
            "plugins": self.plugins.to_dict(),
        }
        Path(path).write_text(json.dumps(report, indent=2))
        QMessageBox.information(self, "Saved", f"Report written to:\n{path}")

    # -----------------------------------------------------------------
    # Formatters
    # -----------------------------------------------------------------
    def _format_player(self, h) -> str:
        return (
            f"Name:           {h.player_name}\n"
            f"Level:          {h.player_level}\n"
            f"Location:       {h.player_location}\n"
            f"Race:           {h.race_name}\n"
            f"Gender:         {h.gender}\n"
            f"Experience:     {h.experience:.2f} / {h.experience_required:.2f}\n"
            f"Playtime:       {h.playtime}\n"
            f"Game version:   {h.current_game_version}\n"
            f"Save version:   {h.save_version} / {h.save_version_2}\n"
            f"Engine:         0x{h.engine_version:08X}\n"
            f"Save number:    {h.save_number}"
        )

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
        d = h.to_dict()
        lines = []
        for k, v in d.items():
            lines.append(f"{k:.<26} {v}")
        return "\n".join(lines)

    def _add_plugin_row(self, name: str, ptype: str, is_native: bool,
                       entry=None):
        marker = "★ " if is_native else "  "
        item = QTreeWidgetItem([f"{marker}{name}", ptype])
        if is_native:
            item.setForeground(0, QColor(ACCENT_AMBER))
        else:
            item.setForeground(0, QColor(ACCENT_CYAN))
        self.plugins_tree.addTopLevelItem(item)
        # Metadaten nur, wenn tatsaechlich vorhanden (nie Platzhalter zeigen).
        state = getattr(entry, "metadata_state", "absent") if entry else "absent"
        if state == "present":
            details = ["creation: %s" % (entry.creation_name or "-")]
            if entry.creation_id:
                details.append("id: %s" % entry.creation_id)
            if entry.version:
                details.append("version: %s" % entry.version)
            if entry.achievement_friendly:
                details.append("achievement friendly")
            child = QTreeWidgetItem(["    " + " | ".join(details), ""])
            child.setForeground(0, QColor(ACCENT_GREEN))
            item.addChild(child)
        elif state == "unreadable":
            child = QTreeWidgetItem(["    metadata unreadable", ""])
            child.setForeground(0, QColor(ACCENT_PINK))
            item.addChild(child)
