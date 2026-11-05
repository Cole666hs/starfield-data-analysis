"""hex_view_page.py — read-only Hex-Ansicht für SSB-I.

Ersetzt den früheren Platzhalter („Hex Viewer · coming in next phase") durch
eine echte Funktion: Anzeige beliebiger Bytes als Offset | Hex | ASCII, mit
Seitenweise-Blättern, Sprung zu Offset und Suche nach Text- oder Hex-Mustern.

Warum nur ein Fenster statt der ganzen Datei: ein entpacktes Savegame hat
~23 MB, das sind ~1,5 Mio. Zeilen. Ein vollständiger Dump würde die Oberfläche
blockieren. Deshalb wird ein Fenster von ``PAGE_BYTES`` angezeigt und
seitenweise verschoben.

Read-only: es wird ausschließlich gelesen und gerendert. Es gibt keinen Pfad,
der in eine Eingabedatei schreibt.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

ACCENT_CYAN = "#00E5FF"
ACCENT_PINK = "#FF1F8F"
ACCENT_AMBER = "#FFB300"
TEXT_MAIN = "#E8F0FF"
TEXT_DIM = "#7E8AA0"
DARK_BG = "#0A0E14"

#: Bytes pro Anzeigeseite (16 Zeilen à 16 Byte = 256 Byte wären zu klein;
#: 8192 Byte = 512 Zeilen ist flüssig zu rendern)
PAGE_BYTES = 8192
BYTES_PER_ROW = 16


def parse_pattern(text: str) -> bytes:
    """Wandelt eine Suchanfrage in Bytes.

    ``"4E 50 43"`` oder ``"4e:50:63"`` → Hex-Bytes.
    Alles andere → UTF-8-Text (z. B. ``"SOC_"``).
    """
    compact = text.replace(" ", "").replace(":", "").replace("-", "")
    if len(compact) >= 2 and len(compact) % 2 == 0:
        try:
            return bytes.fromhex(compact)
        except ValueError:
            pass
    return text.encode("utf-8")


def format_rows(data: bytes, base_offset: int = 0,
                bytes_per_row: int = BYTES_PER_ROW) -> str:
    """Rendert einen Puffer als Offset-|-Hex-|-ASCII-Zeilen."""
    lines: list[str] = []
    for i in range(0, len(data), bytes_per_row):
        chunk = data[i:i + bytes_per_row]
        offset = base_offset + i
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        hex_part = f"{hex_part:<{bytes_per_row * 3 - 1}}"
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part}  |{ascii_part}|")
    return "\n".join(lines)


class HexViewPage(QWidget):
    """Hex-Ansicht über einen Puffer aus dem Savegame-Analyzer oder eine Datei."""

    def __init__(self, buffer_getter: Optional[Callable[[], tuple[Optional[str], bytes]]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._buffer_getter = buffer_getter
        self._data: bytes = b""
        self._label: str = ""
        self._offset: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- Werkzeugleiste -------------------------------------------------
        bar = QHBoxLayout()
        self.btn_reload = QPushButton("⟳  Load from analyzer")
        self.btn_reload.clicked.connect(self.load_from_source)
        bar.addWidget(self.btn_reload)

        self.btn_open = QPushButton("▣  Open file...")
        self.btn_open.clicked.connect(self.on_open_file)
        bar.addWidget(self.btn_open)

        bar.addSpacing(16)
        bar.addWidget(QLabel("Offset:"))
        self.offset_edit = QLineEdit()
        self.offset_edit.setFixedWidth(110)
        self.offset_edit.setPlaceholderText("0x0")
        self.offset_edit.returnPressed.connect(self.on_goto)
        bar.addWidget(self.offset_edit)

        self.btn_goto = QPushButton("Go")
        self.btn_goto.clicked.connect(self.on_goto)
        bar.addWidget(self.btn_goto)

        bar.addSpacing(16)
        self.search_edit = QLineEdit()
        self.search_edit.setFixedWidth(180)
        self.search_edit.setPlaceholderText("Search: text or 4E 50 43")
        self.search_edit.returnPressed.connect(self.on_search)
        bar.addWidget(self.search_edit)

        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.on_search)
        bar.addWidget(self.btn_search)
        bar.addStretch(1)
        root.addLayout(bar)

        # --- Blättern -------------------------------------------------------
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Back")
        self.btn_prev.clicked.connect(lambda: self.goto_offset(self._offset - PAGE_BYTES))
        nav.addWidget(self.btn_prev)
        self.btn_next = QPushButton("Forward ▶")
        self.btn_next.clicked.connect(lambda: self.goto_offset(self._offset + PAGE_BYTES))
        nav.addWidget(self.btn_next)
        self.info_label = QLabel("No buffer loaded.")
        self.info_label.setStyleSheet(f"color:{TEXT_DIM};")
        nav.addWidget(self.info_label, stretch=1)
        root.addLayout(nav)

        # --- Anzeige --------------------------------------------------------
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.view.setFont(font)
        self.view.setStyleSheet(
            f"QPlainTextEdit {{ background-color:{DARK_BG}; color:{TEXT_MAIN};"
            f" border:1px solid #1F2937; padding:8px; }}"
        )
        root.addWidget(self.view, stretch=1)

        self._style_buttons()
        self._render()

    # ------------------------------------------------------------------ Optik
    def _style_buttons(self) -> None:
        for btn, color in ((self.btn_reload, ACCENT_CYAN), (self.btn_open, ACCENT_CYAN),
                           (self.btn_goto, ACCENT_AMBER), (self.btn_search, ACCENT_PINK),
                           (self.btn_prev, TEXT_DIM), (self.btn_next, TEXT_DIM)):
            btn.setStyleSheet(
                f"QPushButton {{ background:#131822; color:{color};"
                f" border:1px solid {color}; padding:6px 12px; }}"
                f"QPushButton:hover {{ background:#1a212e; }}"
            )

    # ---------------------------------------------------------------- Puffer
    def set_buffer(self, data: bytes, label: str = "") -> None:
        """Setzt den anzuzeigenden Puffer (read-only Kopie der Referenz)."""
        self._data = bytes(data or b"")
        self._label = label
        self._offset = 0
        self._render()

    def load_from_source(self, *, interactive: bool = True) -> bool:
        """Holt den Puffer aus der Quelle (Savegame-Analyzer).

        ``interactive=False`` unterdrückt jeden Dialog. Das ist Pflicht für
        automatische Aufrufe (Seitenwechsel, kopflose Tests): ein modaler
        Dialog ohne Benutzer blockiert den Prozess und terminiert nie
        (gleiche Fehlerklasse wie im Savegame-Analyzer, Audit-Befund 05.11.).
        """
        if self._buffer_getter is None:
            if interactive:
                QMessageBox.information(
                    self, "No source",
                    "This view has no buffer source. Load a savegame in the "
                    "Savegame Analyzer, or open a file directly.")
            return False
        label, data = self._buffer_getter()
        if not data:
            if interactive:
                QMessageBox.information(
                    self, "No buffer",
                    "No savegame is loaded in the Savegame Analyzer yet "
                    "(or it could not be decoded).")
            return False
        self.set_buffer(data, label or "")
        return True

    def on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open file in hex view", "",
                                              "All files (*)")
        if not path:
            return
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            QMessageBox.critical(self, "File not readable", str(exc))
            return
        self.set_buffer(data, path)

    # -------------------------------------------------------------- Navigation
    def on_goto(self) -> None:
        raw = self.offset_edit.text().strip()
        if not raw:
            return
        try:
            value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 0)
        except ValueError:
            QMessageBox.warning(self, "Invalid offset",
                                f"\"{raw}\" is not a number. Examples: 0x1F40, 8000")
            return
        self.goto_offset(value)

    def goto_offset(self, offset: int) -> None:
        if not self._data:
            return
        limit = max(len(self._data) - PAGE_BYTES, 0)
        self._offset = max(0, min(int(offset), limit))
        self._render()

    def on_search(self) -> None:
        pattern = parse_pattern(self.search_edit.text())
        if not pattern:
            return
        found = self.find_next(pattern)
        if found is None:
            QMessageBox.information(
                self, "Not found",
                f"Pattern {pattern.hex(' ').upper()} does not occur in the buffer.")

    def find_next(self, pattern: bytes, start: Optional[int] = None) -> Optional[int]:
        """Sucht ab ``start`` (Default: aktuelle Position) und springt dorthin.

        Heißt absichtlich NICHT ``find``: ``QWidget.find`` ist eine statische
        Qt-Methode; eine Überschreibung mit anderer Signatur ist ein Fehler.
        """
        if not self._data or not pattern:
            return None
        base = self._offset if start is None else max(0, int(start))
        index = self._data.find(pattern, base)
        if index < 0:
            index = self._data.find(pattern)  # Suche ab Anfang erneut
        if index < 0:
            return None
        self.goto_offset(index)
        return index

    # --------------------------------------------------------------- Rendering
    def _render(self) -> None:
        total = len(self._data)
        if total == 0:
            self.view.setPlainText("")
            self.info_label.setText("No buffer loaded.")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return
        window = self._data[self._offset:self._offset + PAGE_BYTES]
        self.view.setPlainText(format_rows(window, self._offset))
        cursor = self.view.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.view.setTextCursor(cursor)
        end = self._offset + len(window)
        source = self._label or "(buffer)"
        self.info_label.setText(
            f"{source} · {total:,} bytes · window 0x{self._offset:X}–0x{end:X}")
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(end < total)

    # ------------------------------------------------------------------ Status
    def status_text(self) -> str:
        """Kurzstatus für Tests und die Statuszeile."""
        if not self._data:
            return "empty"
        return f"{len(self._data)} Bytes ab 0x{self._offset:X}"
