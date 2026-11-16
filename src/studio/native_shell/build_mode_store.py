"""User-local memory of the chosen plugin type (build mode) per project.

Not part of the project: the native Logitech project format is never migrated
and ``NativeProjectSession`` stays the only project authority. The store is a
small JSON file in the user's Studio data directory, keyed by the canonical
project path identity (``project_identity``) AND the project's plugin ID:

* a moved or copied project has a new path identity → no stored mode → the
  historical default ``compatible``;
* a different project saved at the same path (other plugin ID) never inherits
  a foreign mode;
* unknown/obsolete mode values, damaged files or unwritable locations fall back
  to the default and are never fatal.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_MODE = "compatible"
KNOWN_MODES = ("compatible", "native", "shared")
FORMAT = "studio-build-modes-1"
MAX_ENTRIES = 256
FILE_NAME = "build_modes.json"


def settings_dir() -> Path | None:
    """Same convention as ``build_root``: explicit data dir, user data when
    frozen (Setup and Portable alike), the source tree's work area otherwise."""
    if os.environ.get("LOGI_STUDIO_DATA"):
        return Path(os.environ["LOGI_STUDIO_DATA"]) / "settings"
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "LogiPluginStudio" / "settings" if base else None
    return Path(__file__).resolve().parents[3] / "work" / "generated" / "settings"


class BuildModeStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else settings_dir()
        self.last_error: str | None = None

    @property
    def path(self) -> Path | None:
        return None if self.directory is None else self.directory / FILE_NAME

    def _read(self) -> dict:
        path = self.path
        if path is None or not path.is_file():
            return {}
        try:
            row = json.loads(path.read_bytes()[:1_048_576].decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            self.last_error = f"Buildmodus-Einstellungen unlesbar ({type(exc).__name__}); Standard wird verwendet."
            return {}
        if not isinstance(row, dict) or row.get("format") != FORMAT or not isinstance(row.get("projects"), dict):
            self.last_error = "Buildmodus-Einstellungen haben ein unbekanntes Format; Standard wird verwendet."
            return {}
        return row["projects"]

    def mode_for(self, identity: str, plugin_id: str) -> str:
        entry = self._read().get(identity)
        if not isinstance(entry, dict) or entry.get("plugin_id") != plugin_id:
            return DEFAULT_MODE
        mode = entry.get("mode")
        return mode if mode in KNOWN_MODES else DEFAULT_MODE

    def remember(self, identity: str, plugin_id: str, mode: str) -> bool:
        """Persist atomically; returns False (never raises) if not writable."""
        if mode not in KNOWN_MODES or not identity or not plugin_id or self.path is None:
            return False
        projects = self._read()
        projects[identity] = {"plugin_id": plugin_id, "mode": mode, "updated": round(time.time(), 3)}
        if len(projects) > MAX_ENTRIES:
            newest = sorted(projects.items(), key=lambda item: item[1].get("updated", 0)
                            if isinstance(item[1], dict) else 0, reverse=True)
            projects = dict(newest[:MAX_ENTRIES])
        data = json.dumps({"format": FORMAT, "projects": projects}, ensure_ascii=True, indent=1,
                          sort_keys=True).encode("utf-8")
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(dir=self.directory, prefix=".build-modes-", suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(handle, "wb") as output:
                output.write(data)
            os.replace(temporary, self.path)
            temporary = None
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = f"Buildmodus konnte nicht gespeichert werden ({type(exc).__name__})."
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
