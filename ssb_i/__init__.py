"""Starfield Data Analysis — inspection and analysis package.

Public product: *Starfield Data Analysis* by Entropy Development.
The Python package keeps the historical working name ``ssb_i`` because it is an
internal identifier, not a product name.

Only the modules that belong to this product are shipped here:

    savegame_provider      .sfs (BCPS/SFS_SAVEGAME) decoding
    savegame_differential  byte-level save comparison
    ssb_pe_lib             PE32+ integrity and section analysis
    product                public identity

Everything else that grew in the old working tree (runtime probing, memory
watch, experiment engine, AISC preview) belongs to other products and is not
part of this repository. The names below are resolved lazily (PEP 562), so an
import of a module that is not shipped fails at first use, not at import time.
"""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.0.0"          # version of this shipped package
__product__ = "Starfield Data Analysis"

#: Export name -> module that provides it.
_MODULE_EXPORTS: dict[str, list[str]] = {
    "savegame_provider": [
        "SfsDecodeProvider", "SfsContainer", "SfsChunkInfo", "DatHeader",
        "PluginEntry", "PluginInfo", "get_provider",
    ],
    "savegame_differential": [
        "analyze_bytes", "analyze_paths", "compare_metadata", "markdown_report",
        "load_known_formids", "formid_candidates", "cluster_offsets",
    ],
    "ssb_pe_lib": ["PE", "PEIntegrityError", "DEFAULT_TRUST_ROOT_SHA256"],
    "product": [
        "PRODUCT_NAME", "PRODUCT_SUBTITLE", "DEVELOPER", "VERSION", "SLUG",
        "CLI_PROG", "COPYRIGHT", "LICENSE_NAME", "version_string", "full_title",
    ],
}

_NAME_TO_MODULE: dict[str, str] = {
    name: module for module, names in _MODULE_EXPORTS.items() for name in names
}

__all__ = sorted(_NAME_TO_MODULE) + ["__version__", "__product__"]


def __getattr__(name: str) -> Any:
    """PEP 562: import the providing module only when the name is used."""
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return __all__


def available_exports() -> dict[str, str]:
    """Diagnostic: which public name comes from which module?"""
    return dict(_NAME_TO_MODULE)
