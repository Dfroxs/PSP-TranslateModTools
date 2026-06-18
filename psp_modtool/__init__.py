"""
PSP Mod Tool
============
Tool untuk extract, scan, terjemahkan, dan repack file ISO PSP.
Berguna untuk lokalisasi bahasa game (mis. English -> Indonesia).
"""

__version__ = "1.0.0"

from .core import (
    extract_iso,
    scan_folder,
    apply_translations,
    repack_iso,
    run_all,
)

__all__ = [
    "extract_iso",
    "scan_folder",
    "apply_translations",
    "repack_iso",
    "run_all",
    "__version__",
]
