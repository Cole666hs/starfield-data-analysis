"""SSB-M UI: PySide6 GUI for the SSB-Multi-Toolkit.

Main app: SSBWorkbench — bundles Savegame-Parser, SFSE-Plugin-Config,
DLL-Deploy-Helper, and the full SSB-I runtime introspection suite
into a single Windows-deployable .exe (built via PyInstaller).
"""
# O-9: derived from the single product version source, so it cannot drift
from ssb_i.product import VERSION as __version__  # noqa: E402
