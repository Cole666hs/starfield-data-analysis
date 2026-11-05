# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Starfield Data Analysis (Entropy Development).

Builds two programs into one folder:

    StarfieldDataAnalysis    graphical interface (no console window)
    sfda                     command line (console)

Everything is derived from SPECPATH, so the build works from any directory and
on any machine. The AISC 3D preview is not part of this product and is excluded
explicitly; the module does not exist in this repository either.

Usage:
    pyinstaller Starfield-Data-Analysis.spec --noconfirm
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

HERE = Path(SPECPATH).resolve()

#: Release version and names come from the single identity module.
import sys
sys.path.insert(0, str(HERE))
from ssb_i.product import SLUG, VERSION  # noqa: E402

FOLDER = os.environ.get("SFDA_BUILD_NAME", SLUG)
GUI_NAME = SLUG
CLI_NAME = "sfda"

datas = []
binaries = []
hiddenimports = []

# qdarkstyle ships real style resources (QSS + images). The examples and the
# light theme are not used by this program and are dropped from the package.
for package in ("qdarkstyle",):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h


def _is_needed_data(destination: str) -> bool:
    """Drop resources this program never loads (package stays lean)."""
    path = destination.replace("\\", "/").lower()
    if "/example" in path:
        return False
    if "qdarkstyle/light/" in path:
        return False
    # Qt's own translations: this program's texts are English and Qt falls back
    # to built-in English strings, so ~7 MB of .qm files are dead weight.
    if "/translations/" in path or path.endswith("/translations"):
        return False
    return True


datas = [(src, dst) for (src, dst) in datas if _is_needed_data(dst)]

EXCLUDES = [
    # Not part of this product (AISC / runtime module)
    "ssb_ui.pages.aisc_preview_page",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineQuick",
    "ssb_i.runtime_probe", "ssb_i.probe_sequences", "ssb_i.memory_watch",
    "ssb_i.native_provider", "ssb_i.execution_provider", "ssb_i.experiment_engine",
    "ssb_i.experiment_diff", "ssb_i.runtime_correlation", "ssb_i.core",
    "ssb_i.evidence_store", "ssb_i.value_provenance", "ssb_i.lab",
    # Foreign GUI / numeric stacks that are never used
    "tkinter", "matplotlib", "numpy", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2",
    # Qt modules this program never imports (UI uses Widgets/Gui/Core only)
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDataVisualization", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtUiTools", "PySide6.QtPrintSupport", "PySide6.QtNetwork",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtHelp", "PySide6.QtDesigner",
    "PySide6.QtXml", "PySide6.QtDBus",
]

# --- graphical interface ---------------------------------------------------
gui = Analysis(
    [str(HERE / "ssb_ui" / "app.py")],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["ssb_i.product"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False, optimize=0,
)
gui_pyz = PYZ(gui.pure)
gui_exe = EXE(
    gui_pyz, gui.scripts, [],
    exclude_binaries=True,
    name=GUI_NAME,
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

# --- command line ----------------------------------------------------------
cli = Analysis(
    [str(HERE / "sfda_cli.py")],
    pathex=[str(HERE)],
    binaries=[], datas=[],
    hiddenimports=["ssb_i.product"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=EXCLUDES + ["PySide6", "qdarkstyle"],
    noarchive=False, optimize=0,
)
cli_pyz = PYZ(cli.pure)
cli_exe = EXE(
    cli_pyz, cli.scripts, [],
    exclude_binaries=True,
    name=CLI_NAME,
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

coll = COLLECT(
    gui_exe, gui.binaries, gui.datas,
    cli_exe, cli.binaries, cli.datas,
    strip=False, upx=False, upx_exclude=[],
    name=FOLDER,
)
