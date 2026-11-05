"""Starfield Data Analysis — Qt user interface.

Ships exactly three pages, each with a real, tested purpose:
- Savegame Analyzer (read-only .sfs decoding via ssb_i.savegame_provider)
- Hex Viewer (read-only byte view over the decoded buffer)
- Event Log (start-up and status messages)

Not part of this product: the AISC 3D preview (AISC), plugin configuration,
DLL deployment and runtime capture (both belong to the separate runtime module).

Theme: qdarkstyle + custom QSS accents.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QAction, QPalette, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStackedWidget, QListWidget, QListWidgetItem,
    QStatusBar, QToolBar, QMessageBox, QSplitter, QTextEdit,
    QFrame,
)

# Theme
import qdarkstyle

# -----------------------------------------------------------------------------
# Skript-Modus absichern (Befund SSB-I-Audit 05.11.2026)
# Wird die Anwendung direkt gestartet (``python ssb_ui/app.py``), liegt nur das
# Verzeichnis ``ssb_ui/`` auf sys.path — die Projektwurzel fehlt. Dann scheitern
# die Paketimporte (``ssb_ui.pages.*``); die Savegame-Seite faellt still auf eine
# Fehlermeldung zurueck und ``--self-test`` endet mit "no attribute 'load_file'".
# Nur der PyInstaller-Bundle funktionierte, weil er die Pfade selbst setzt.
# Deshalb die Projektwurzel hier explizit ergaenzen.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Produktname und -version aus EINER Quelle (ssb_i/product.py), damit GUI, CLI
# und Release-Dateien nie auseinanderlaufen. SSB_APP_NAME bleibt als Override
# für den Workbench-Build (SSB-M) erhalten.
from ssb_i.product import DEVELOPER as _DEVELOPER
from ssb_i.product import PRODUCT_NAME as _PRODUCT_NAME
from ssb_i.product import PRODUCT_SUBTITLE as _PRODUCT_SUBTITLE
from ssb_i.product import CLI_PROG
from ssb_i.product import VERSION as PRODUCT_VERSION

# Produktname und -version kommen ausschliesslich aus ssb_i/product.py.
APP_NAME = os.environ.get("SFDA_APP_NAME") or _PRODUCT_NAME
APP_SUBTITLE = _PRODUCT_SUBTITLE


# =============================================================================
# Theme constants — cyberpunk accent colors
# =============================================================================
ACCENT_CYAN   = "#00E5FF"
ACCENT_PINK   = "#FF1F8F"
ACCENT_AMBER  = "#FFB300"
ACCENT_GREEN  = "#39FF14"
ACCENT_PURPLE = "#B026FF"
DARK_BG       = "#0A0E14"
PANEL_BG      = "#131822"
GRID_LINE     = "#1F2937"
TEXT_MAIN     = "#E8F0FF"
TEXT_DIM      = "#7E8AA0"


# =============================================================================
# Sidebar page enum
# =============================================================================
PAGE_SAVEGAME = 0
PAGE_PLUGIN   = 1
PAGE_DEPLOY   = 2
PAGE_RUNTIME  = 3
PAGE_HEXVIEW  = 4
PAGE_LOG      = 5


# =============================================================================
# Sidebar widget — left navigation
# =============================================================================
class Sidebar(QListWidget):
    """Cyberpunk-themed sidebar with icon-style entries.

    Die Eintraege kommen von aussen als Liste ``(Label, page_id)``, damit
    Sidebar-Reihenfolge und StackedWidget-Index aus EINER Quelle stammen.
    Vorher standen die Eintraege hier fest und die Seitenliste war eine zweite,
    unabhaengige Liste — dadurch konnten beide auseinanderlaufen.
    """

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setSpacing(2)
        self.setFrameShape(QFrame.NoFrame)
        for label, page_id in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, page_id)
            self.addItem(item)
        self.setCurrentRow(0)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {PANEL_BG};
                color: {TEXT_MAIN};
                border: none;
                border-right: 1px solid {GRID_LINE};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 11pt;
                padding: 6px 0;
            }}
            QListWidget::item {{
                padding: 12px 18px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:hover {{
                background-color: #1a212e;
                color: {ACCENT_CYAN};
            }}
            QListWidget::item:selected {{
                background-color: #1a212e;
                color: {ACCENT_CYAN};
                border-left: 3px solid {ACCENT_CYAN};
            }}
        """)


# =============================================================================
# Header banner — cyberpunk brand bar
# =============================================================================
class HeaderBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {DARK_BG},
                    stop: 0.4 {PANEL_BG},
                    stop: 1 {DARK_BG}
                );
                border-bottom: 1px solid {ACCENT_CYAN};
            }}
            QLabel#title {{
                color: {ACCENT_CYAN};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 18pt;
                font-weight: bold;
                letter-spacing: 2px;
            }}
            QLabel#subtitle {{
                color: {TEXT_DIM};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 9pt;
            }}
            QLabel#accent {{
                color: {ACCENT_PINK};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 14pt;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        title = QLabel(APP_NAME.upper())
        title.setObjectName("title")
        layout.addWidget(title)
        accent = QLabel("◆")
        accent.setObjectName("accent")
        layout.addWidget(accent)
        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle, stretch=1)
        version = QLabel(f"v{PRODUCT_VERSION}")
        version.setStyleSheet(f"color: {ACCENT_AMBER}; font-family: 'Cascadia Code'; font-size: 10pt;")
        layout.addWidget(version)


# =============================================================================
# Seiten-Wrapper
# =============================================================================
class SavegamePage(QWidget):
    """Savegame-Analyzer-Seite, lazy geladen (Startkosten).

    Die echte Seite liegt in ``ssb_ui.pages.savegame_page``. Dieser Wrapper
    reicht die nach außen gebrauchten Aufrufe weiter — vorher fehlte das, und
    ein Aufruf wie ``page.current_buffer()`` scheiterte am Wrapper statt an der
    Seite. Zusätzlich wird ein Ladefehler nicht mehr verschluckt, sondern in
    ``self.load_error`` festgehalten und im Fenster sichtbar gemacht.
    """
    def __init__(self):
        super().__init__()
        self.load_error = None
        self._inner = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        try:
            from ssb_ui.pages.savegame_page import SavegamePage as _RealPage
            self._inner = _RealPage()
            layout.addWidget(self._inner)
        except Exception as e:  # pragma: no cover - nur bei kaputtem Build
            self.load_error = f"{type(e).__name__}: {e}"
            info = QLabel(f"Savegame page could not be loaded: {e}")
            info.setStyleSheet(f"color: {TEXT_DIM};")
            layout.addWidget(info)

    # --- Durchreichen an die echte Seite -----------------------------------
    def load_file(self, path, **kwargs):
        if self._inner is None:
            raise RuntimeError(f"savegame page not loaded ({self.load_error})")
        return self._inner.load_file(path, **kwargs)

    def current_buffer(self):
        if self._inner is None:
            return None, b""
        return self._inner.current_buffer()


# --- Seiten, die zum SSB-I-Produkt gehören --------------------------------
# Die früheren Platzhalter (Plugin Config, DLL Deploy, Runtime Capture) sind
# ENTFERNT, nicht nur versteckt: eine sichtbare, funktionslose Seite ist kein
# Releasezustand. Plugin Config/DLL Deploy/Runtime Capture gehören thematisch
# zu SSB-M (Runtime-Modul) und werden dort gebaut, nicht hier.
from ssb_ui.pages.hex_view_page import HexViewPage  # noqa: E402

# Die AISC-3D-Vorschau ist aus diesem Produkt ENTFERNT (05.11.2026): sie gehört
# zu AISC, nicht zu Starfield Data Analysis. Es gibt keine Importstelle, keine
# Seitenregistrierung und keinen Build-Eintrag mehr dafür.


class LogPage(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_BG};
                color: {TEXT_MAIN};
                border: none;
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 10pt;
                padding: 12px;
            }}
        """)
        self.append(f'<span style="color:{ACCENT_CYAN}">▶ {APP_NAME} {PRODUCT_VERSION} — UI loaded</span>')
        self.append(f'<span style="color:{TEXT_DIM}">  Cyberpunk theme active · qdarkstyle + custom QSS</span>')
        self.append(f'<span style="color:{TEXT_DIM}">  Read-only by default · capability map respected</span>')
        self.append(f'<span style="color:{ACCENT_AMBER}">  Available tools: Savegame Analyzer, Hex Viewer</span>')
        self.append(f'<span style="color:{TEXT_DIM}">  {_PRODUCT_NAME} · {_DEVELOPER} · command line: {CLI_PROG} --help</span>')


# =============================================================================
# Main window
# =============================================================================
class SSBWorkbench(QMainWindow):
    @staticmethod
    def build_pages():
        """Baut die Seiten des Produkts. Eine Quelle für Sidebar, Stack und Namen.

        Format: (Label, page_id, Widget).
        Die Hex-Ansicht bekommt eine Pufferquelle aus dem Savegame-Analyzer,
        damit der Arbeitsablauf „Datei wählen → analysieren → Bytes ansehen"
        ohne erneutes Laden funktioniert.
        """
        savegame = SavegamePage()
        pages: list[tuple[str, int, QWidget]] = [
            ("▣  Savegame Analyzer", PAGE_SAVEGAME, savegame),
            ("⌗  Hex Viewer",        PAGE_HEXVIEW,
             HexViewPage(buffer_getter=savegame.current_buffer)),
            ("⚡  Event Log",         PAGE_LOG,       LogPage()),
        ]
        return pages

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {PRODUCT_VERSION} · {_DEVELOPER}")
        self.resize(1400, 900)

        # Central layout: HeaderBanner / (Sidebar + StackedWidget) / StatusBar
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(HeaderBanner())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._specs = self.build_pages()
        specs = self._specs
        self.sidebar = Sidebar([(label, page_id) for label, page_id, _w in specs])
        body.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        for _label, _page_id, widget in specs:
            self.pages.addWidget(widget)
        body.addWidget(self.pages, stretch=1)

        root_layout.addLayout(body)

        # Status bar
        self.statusbar = QStatusBar()
        self.statusbar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {PANEL_BG};
                color: {TEXT_MAIN};
                border-top: 1px solid {GRID_LINE};
                font-family: "Cascadia Code", monospace;
            }}
        """)
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage(f"Ready · v{PRODUCT_VERSION} · read-only mode")

        self.sidebar.currentRowChanged.connect(self.on_page_changed)
        self.on_page_changed(0)

    def on_page_changed(self, row):
        self.pages.setCurrentIndex(row)
        names = [label.split("  ", 1)[-1].strip() for label, _id, _w in self._specs]
        if 0 <= row < len(names):
            self.statusbar.showMessage(f"Active: {names[row]} · READ-ONLY mode")
        # Hex-Ansicht beim Öffnen frisch aus dem Analyzer ziehen, damit sie
        # nicht auf einem veralteten Puffer steht.
        widget = self.pages.widget(row)
        if widget is not None and hasattr(widget, "load_from_source"):
            try:
                if not widget._data:  # noch nichts geladen
                    # interactive=False: kein Dialog bei automatischem Aufruf
                    widget.load_from_source(interactive=False)
            except Exception:
                pass


# =============================================================================
# Entry point
# =============================================================================
def self_test(save: str, out_path: str | None = None) -> int:
    """Kopfloser Selbsttest: Fenster bauen, Save laden, Ergebnis drucken.

    Zweck: ein gepacktes Bundle (PyInstaller) kann nicht interaktiv geprueft
    werden. Mit ``--self-test <save.sfs>`` laedt die Anwendung den Analyzer
    wirklich, druckt die Kerndaten und beendet sich mit Code 0/1. Damit ist
    der Build pruefbar, ohne dass jemand klicken muss.
    """
    from PySide6.QtWidgets import QApplication as _QA
    # In Tests existiert bereits eine QApplication; eine zweite Instanz würde
    # eine Exception werfen. Deshalb die vorhandene verwenden.
    _app = _QA.instance() or _QA([])
    win = SSBWorkbench()
    page = win.pages.widget(0)
    inner = getattr(page, "_inner", page)

    # Windows-Build ist ein GUI-Programm (console=False): dort gibt es KEIN
    # stdout, ``print`` landet im Nichts. Ergebnisse werden deshalb gesammelt
    # und auf Wunsch in eine Datei geschrieben (``--out``).
    lines: list[str] = []

    def emit(msg: str) -> None:
        lines.append(msg)
        if sys.stdout is not None:
            print(msg, flush=True)

    def finish(code: int) -> int:
        if out_path:
            try:
                Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                code = 1
        return code

    try:
        # show_dialog=False: im kopflosen Lauf darf kein modaler Dialog
        # aufgehen — er blockiert den Prozess und der Selbsttest endet nie.
        loaded = inner.load_file(save, show_dialog=False)
    except Exception as exc:  # pragma: no cover - nur im Bundle relevant
        emit("SELF_TEST FAIL load: %s: %s" % (type(exc).__name__, exc))
        return finish(1)
    if not loaded:
        emit("SELF_TEST FAIL load: %s"
             % (getattr(inner, "last_error", None) or "unbekannter Fehler"))
        return finish(1)
    header = inner.header
    info = inner.plugins
    if header is None or info is None:
        emit("SELF_TEST FAIL: no header/plugin result")
        return finish(1)
    ok = (info.decode_state == "VALIDATED" and info.total > 0)
    emit("SELF_TEST player=%r level=%s game=%s save_version=%s"
         % (header.player_name, header.player_level,
            header.current_game_version, header.save_version))
    emit("SELF_TEST header_fields=%d decompressed_bytes=%d"
         % (len(header.to_dict()), len(inner.decompressed or b"")))
    emit("SELF_TEST plugins state=%s normal=%d light=%d medium=%d"
         % (info.decode_state, len(info.normal), len(info.light),
            len(info.medium)))
    emit("SELF_TEST %s" % ("PASS" if ok else "FAIL"))
    return finish(0 if ok else 1)


def dump_pages(out_path: str | None = None) -> int:
    """Listet die ausgelieferten Seiten — für Support und Abnahme im Paket.

    Auch in der gefrorenen Anwendung nutzbar, ohne dass ein Fenster aufgeht:
        StarfieldDataAnalysis --dump-pages [--out pages.txt]
    """
    app = QApplication.instance() or QApplication([])
    win = SSBWorkbench()
    lines = [f"{APP_NAME} {PRODUCT_VERSION} ({_DEVELOPER})",
             f"pages: {win.pages.count()}"]
    for index in range(win.sidebar.count()):
        label = win.sidebar.item(index).text().strip()
        widget = type(win.pages.widget(index)).__name__
        lines.append(f"  {index}: {label}  [{widget}]")
    for line in lines:
        if sys.stdout is not None:
            print(line, flush=True)
    if out_path:
        try:
            Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return 1
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--dump-pages":
        out_path = None
        if "--out" in sys.argv:
            idx = sys.argv.index("--out")
            if idx + 1 < len(sys.argv):
                out_path = sys.argv[idx + 1]
        return dump_pages(out_path)
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        if len(sys.argv) < 3:
            print("usage: %s --self-test <save.sfs> [--out <report.txt>]" % sys.argv[0])
            return 2
        out_path = None
        if "--out" in sys.argv:
            idx = sys.argv.index("--out")
            if idx + 1 < len(sys.argv):
                out_path = sys.argv[idx + 1]
        return self_test(sys.argv[2], out_path)

    app = QApplication(sys.argv)

    # Apply cyberpunk theme (qdarkstyle_pyside6 / palette)
    qss = qdarkstyle.load_stylesheet_pyside6()
    app.setStyleSheet(qss + f"""
        QMainWindow {{
            background-color: {DARK_BG};
        }}
    """)

    win = SSBWorkbench()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
