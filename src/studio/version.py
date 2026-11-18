"""Central product version and edition detection (AP-POLISH-001 / AP-01).

Single source for the Studio version: the release build (``tools/packaging``),
the Inno Setup script (``/DAppVersion=...``), the window title and the
diagnosis all read it from here. The edition is not compiled in: the same
frozen build is shipped as Setup and Portable, and the Setup installer only
adds the marker file ``studio-edition.json`` with ``{"edition": "setup"}``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PRODUCT_NAME = "Logitech Plugin Studio"
VERSION = "1.0.0-rc2"
#: Numeric form for Windows version resources / Inno Setup VersionInfoVersion.
VERSION_NUMERIC = "1.0.0.2"
EDITION_MARKER = "studio-edition.json"


def install_dir() -> Path | None:
    """Directory of the running Studio executable (frozen builds only)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def edition() -> str:
    """``setup`` | ``portable`` | ``source`` – determined at run time."""
    directory = install_dir()
    if directory is None:
        return "source"
    try:
        row = json.loads((directory / EDITION_MARKER).read_text(encoding="utf-8"))
        if isinstance(row, dict) and row.get("edition") == "setup":
            return "setup"
    except (OSError, ValueError):
        pass
    return "portable"


def describe() -> str:
    return f"{PRODUCT_NAME} {VERSION} ({edition()})"
