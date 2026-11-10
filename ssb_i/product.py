"""Public product identity — single source for name, version, developer, license.

Internal note: the former working title "SSB-I" may still appear in developer
documentation and in the Python package name (``ssb_i``). It is **not** a public
product name and must not be used in user-facing output.

Every user-visible string (window title, CLI ``--version``, archive names,
documentation) is derived from this module.
"""
from __future__ import annotations

#: Public product name (no internal abbreviations)
PRODUCT_NAME = "Starfield Data Analysis"

#: Public subtitle / claim
PRODUCT_SUBTITLE = "Advanced Starfield Inspection & Analysis Toolkit"

#: Developer / publisher shown in UI, CLI and documentation
DEVELOPER = "Entropy Development"

#: Release version of the product (not the internal library generation).
#:
#: O-9: This is the **single source of truth** for the product version.
#: The PyInstaller spec, the CLI (``--version``), the GUI window title and
#: the documentation all derive from it. ``ssb_i.__version__`` is
#: re-exported from here instead of carrying a second, drifting literal.
VERSION = "1.6.0"

#: Executable / archive base name (no spaces: safe for shells and archives)
SLUG = "StarfieldDataAnalysis"

#: Command line program name
CLI_PROG = "sfda"

COPYRIGHT = "Copyright (c) 2026 Entropy Development"
LICENSE_NAME = "MIT"


def version_string() -> str:
    """One-line version message shared by CLI and GUI."""
    # ASCII only: the Windows console (cp850/cp1252) has no em dash.
    return f"{CLI_PROG} {VERSION} - {PRODUCT_NAME} ({DEVELOPER})"


def full_title() -> str:
    """Window/header title."""
    return f"{PRODUCT_NAME} {VERSION}"
