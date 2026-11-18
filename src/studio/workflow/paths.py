"""Benutzerlokaler Einstellungsordner, Qt-frei.

Gleiche Regel wie ``studio.native_shell.build_mode_store.settings_dir`` (dort unverändert). Eine Kopie ist nötig,
weil der Paketimport von ``studio.native_shell`` Qt lädt; ``tests/test_workflow_qt_free.py`` prüft die Gleichheit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def settings_dir() -> Path | None:
    if os.environ.get("LOGI_STUDIO_DATA"):
        return Path(os.environ["LOGI_STUDIO_DATA"]) / "settings"
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "LogiPluginStudio" / "settings" if base else None
    return Path(__file__).resolve().parents[3] / "work" / "generated" / "settings"
