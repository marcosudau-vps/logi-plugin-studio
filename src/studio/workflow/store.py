"""Benutzerlokaler Oberflächenzustand des geführten Ablaufs.

Kein Projektinhalt: das native Projektformat bleibt unverändert und
``NativeProjectSession`` bleibt alleinige Projektautorität. Gemerkt werden nur
Bedienzustände (geführt/Expertenmodus, zuletzt aktiver Schritt, zugeordnete
Handlerdatei, bestätigter Gerätetest), je Projektpfad UND Plugin-ID – nach dem
Muster von ``native_shell/build_mode_store.py``. Fehler sind nie fatal.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from studio.workflow.paths import settings_dir

FORMAT = "studio-workflow-1"
FILE_NAME = "workflow.json"
MAX_ENTRIES = 256
FIELDS = {"step": str, "handler_file": str, "hardware": str}


class WorkflowStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else settings_dir()
        self.last_error: str | None = None

    @property
    def path(self) -> Path | None:
        return None if self.directory is None else self.directory / FILE_NAME

    def _read(self) -> dict:
        empty = {"guided": True, "projects": {}}
        path = self.path
        if path is None or not path.is_file():
            return empty
        try:
            row = json.loads(path.read_bytes()[:1_048_576].decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            self.last_error = f"Ablauf-Einstellungen unlesbar ({type(exc).__name__}); Standard wird verwendet."
            return empty
        if not isinstance(row, dict) or row.get("format") != FORMAT or not isinstance(row.get("projects"), dict):
            self.last_error = "Ablauf-Einstellungen haben ein unbekanntes Format; Standard wird verwendet."
            return empty
        return {"guided": row.get("guided") is not False, "projects": row["projects"]}

    def _write(self, row: dict) -> bool:
        if self.path is None:
            return False
        data = json.dumps({"format": FORMAT, **row}, ensure_ascii=True, indent=1, sort_keys=True).encode("utf-8")
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(dir=self.directory, prefix=".workflow-", suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(handle, "wb") as output:
                output.write(data)
            os.replace(temporary, self.path)
            temporary = None
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = f"Ablauf-Einstellungen konnten nicht gespeichert werden ({type(exc).__name__})."
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def guided(self) -> bool:
        """Geführter Ablauf ist der Standard; der Expertenmodus wird ausdrücklich gewählt."""
        return self._read()["guided"]

    def set_guided(self, guided: bool) -> bool:
        row = self._read()
        row["guided"] = bool(guided)
        return self._write(row)

    def project(self, identity: str, plugin_id: str) -> dict:
        entry = self._read()["projects"].get(identity)
        if not isinstance(entry, dict) or entry.get("plugin_id") != plugin_id:
            return {}
        return {key: entry[key] for key, kind in FIELDS.items() if isinstance(entry.get(key), kind)}

    def remember(self, identity: str, plugin_id: str, **values) -> bool:
        """Einzelne Felder eines Projekts merken; gibt False zurück statt zu werfen."""
        if not identity or not plugin_id or any(k not in FIELDS or not isinstance(v, FIELDS[k])
                                                for k, v in values.items()):
            return False
        row = self._read()
        entry = row["projects"].get(identity)
        if not isinstance(entry, dict) or entry.get("plugin_id") != plugin_id:
            entry = {"plugin_id": plugin_id}
        entry.update(values, updated=round(time.time(), 3))
        row["projects"][identity] = entry
        if len(row["projects"]) > MAX_ENTRIES:
            newest = sorted(row["projects"].items(), key=lambda item: item[1].get("updated", 0)
                            if isinstance(item[1], dict) else 0, reverse=True)
            row["projects"] = dict(newest[:MAX_ENTRIES])
        return self._write(row)
