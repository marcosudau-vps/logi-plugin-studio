"""Qt-freie Wartungslogik über den vorhandenen Installationsfunktionen.

Keine neue Installationslogik: Deaktivieren ist die vorhandene, belegte
Deinstallation mit Sicherungsbeleg (``workflow.uninstall``), Reaktivieren die
vorhandene Wiederherstellung aus diesem Beleg (``restore_uninstalled``) mit
anschließendem Reload nur dieses Plugins. Fremde Plugins werden nur angezeigt.
Ein Neustart des gesamten Logi Plugin Service wird bewusst nicht angeboten.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from studio.workflow.paths import settings_dir

RUNTIME_TEXT = {"PLUGIN_LOCAL": "eigene Laufzeit, geprüft", "PLUGIN_LOCAL_DAMAGED": "Laufzeit beschädigt – neu installieren",
                "SYSTEM_PYTHON": "ohne eigene Laufzeit (Entwicklerbuild)", "INVALID_RECORD": "Laufzeit-Eintrag ungültig",
                "NO_RECORD": "vor 1.0 gebaut – neu bauen und aktualisieren",
                "LEGACY_ABSOLUTE_PATH": "vor 1.0 gebaut – neu bauen und aktualisieren"}
FORMAT = "studio-deactivated-1"


class MaintenanceBackend:
    """Indirektion auf die vorhandenen Funktionen; Tests ersetzen sie durch eine Attrappe."""

    def inventory(self) -> list[dict]:
        from adapters.logitech.deployment import inventory
        return inventory()

    def runtime(self, package) -> dict:
        from adapters.logitech.host_runtime import installed_runtime_status
        return installed_runtime_status(package)

    def plugin_name(self, package) -> str:
        from adapters.logitech.service import package_plugin_name
        return package_plugin_name(package)

    def reload(self, name) -> dict:
        from adapters.logitech.service import request_plugin_reload
        return request_plugin_reload(name)

    def log_lines(self, name, since) -> list[dict]:
        from adapters.logitech.service import plugin_log_lines
        return plugin_log_lines(name, since=since)

    def uninstall(self, plugin_id, plugin_name, method, receipt_dir) -> dict:
        from adapters.logitech import workflow
        return workflow.uninstall(plugin_id, confirm_plugin_id=plugin_id, receipt_dir=receipt_dir,
                                  method=method, plugin_name=plugin_name)

    def restore(self, method, receipt, plugin_id) -> None:
        from adapters.logitech import deployment, directory_install
        if method == "directory":
            directory_install.restore_uninstalled(receipt, confirm_plugin_id=plugin_id)
        else:
            deployment.restore_uninstalled(receipt, confirm_plugin_id=plugin_id)

    def prerequisites(self):
        from adapters.logitech.service import detect_prerequisites
        return detect_prerequisites()


@dataclass(frozen=True)
class MaintenanceRow:
    name: str                 # Ordner- bzw. Linkname im Pluginordner
    plugin_id: str | None
    kind: str                 # "directory" | "link"
    own: bool
    active: bool
    runtime: str
    location: str
    package: str | None = None
    plugin_name: str | None = None

    @property
    def kind_text(self) -> str:
        return "Verzeichnis" if self.kind == "directory" else "Entwicklungs-Link"

    @property
    def state_text(self) -> str:
        if not self.own:
            return "fremd – wird nicht verändert"
        return "aktiv" if self.active else "deaktiviert"


class DeactivationStore:
    """Benutzerlokale Liste deaktivierter eigener Plugins samt Sicherungsbeleg (nie im Projekt)."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else settings_dir()
        self.last_error: str | None = None

    @property
    def path(self) -> Path | None:
        return None if self.directory is None else self.directory / "deactivated.json"

    @property
    def receipt_root(self) -> Path | None:
        return None if self.directory is None else self.directory.parent / "maintenance-receipts"

    def entries(self) -> dict:
        path = self.path
        if path is None or not path.is_file():
            return {}
        try:
            row = json.loads(path.read_bytes()[:1_048_576].decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            self.last_error = f"Liste deaktivierter Plugins unlesbar ({type(exc).__name__})."
            return {}
        if not isinstance(row, dict) or row.get("format") != FORMAT or not isinstance(row.get("plugins"), dict):
            return {}
        return {key: value for key, value in row["plugins"].items() if isinstance(value, dict)
                and all(isinstance(value.get(k), str) for k in ("plugin_name", "method", "receipt"))}

    def _write(self, plugins: dict) -> bool:
        if self.path is None:
            return False
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(dir=self.directory, prefix=".deactivated-", suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(handle, "wb") as output:
                output.write(json.dumps({"format": FORMAT, "plugins": plugins}, ensure_ascii=True, indent=1,
                                        sort_keys=True).encode("utf-8"))
            os.replace(temporary, self.path)
            temporary = None
            return True
        except OSError as exc:
            self.last_error = f"Liste deaktivierter Plugins nicht gespeichert ({type(exc).__name__})."
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def add(self, plugin_id, plugin_name, method, receipt, location) -> bool:
        plugins = self.entries()
        plugins[plugin_id] = {"plugin_name": plugin_name, "method": method, "receipt": str(receipt),
                              "location": str(location), "deactivated": round(time.time(), 3)}
        return self._write(plugins)

    def remove(self, plugin_id) -> bool:
        plugins = self.entries()
        plugins.pop(plugin_id, None)
        return self._write(plugins)


def collect_rows(backend: MaintenanceBackend, store: DeactivationStore) -> list[MaintenanceRow]:
    """Installierte Plugins (eigene zuerst) plus deaktivierte eigene Plugins aus der Liste."""
    rows, seen = [], set()
    for item in backend.inventory():
        own = bool(item.get("studio_owned") and item.get("package"))
        runtime, plugin_name = "–", None
        if own:
            try:
                status = backend.runtime(item["package"])
                runtime = RUNTIME_TEXT.get(status.get("status"), status.get("status", "unbekannt"))
            except Exception as exc:  # Anzeige, keine Entscheidung
                runtime = f"nicht lesbar ({type(exc).__name__})"
            try:
                plugin_name = backend.plugin_name(item["package"])
            except Exception:
                plugin_name = None
            seen.add(item.get("plugin_id"))
        rows.append(MaintenanceRow(item.get("link", ""), item.get("plugin_id"), item.get("kind", "link"), own, True,
                                   runtime, item.get("target", ""), item.get("package"), plugin_name))
    for plugin_id, entry in sorted(store.entries().items()):
        if plugin_id in seen:
            continue  # inzwischen wieder installiert (z. B. über die Installation)
        rows.append(MaintenanceRow(entry["plugin_name"], plugin_id, entry["method"], True, False, "–",
                                   entry.get("location", ""), None, entry["plugin_name"]))
    rows.sort(key=lambda r: (not r.own, r.name.lower()))
    return rows


def deactivate(backend: MaintenanceBackend, store: DeactivationStore, row: MaintenanceRow) -> dict:
    """Vorhandene Deinstallation mit Beleg; danach in die Liste deaktivierter Plugins."""
    if not row.own or not row.active or not row.plugin_id or not row.plugin_name:
        raise ValueError("Nur aktive, eigene Studio-Plugins lassen sich deaktivieren.")
    if store.receipt_root is None:
        raise ValueError("Kein Ablageort für den Sicherungsbeleg verfügbar.")
    receipt_dir = store.receipt_root / time.strftime("%Y%m%d-%H%M%S")
    result = backend.uninstall(row.plugin_id, row.plugin_name, row.kind, receipt_dir)
    if not store.add(row.plugin_id, row.plugin_name, row.kind, result["receipt"], row.location):
        result["warning"] = store.last_error or "Liste deaktivierter Plugins nicht gespeichert."
    return result


def reactivate(backend: MaintenanceBackend, store: DeactivationStore, row: MaintenanceRow) -> dict:
    """Vorhandene Wiederherstellung aus dem Beleg, danach Reload nur dieses Plugins."""
    entry = store.entries().get(row.plugin_id or "")
    if row.active or entry is None:
        raise ValueError("Für dieses Plugin liegt kein Deaktivierungsbeleg vor.")
    backend.restore(entry["method"], entry["receipt"], row.plugin_id)
    store.remove(row.plugin_id)
    result = {"plugin_id": row.plugin_id, "reload": None}
    try:
        result["reload"] = backend.reload(entry["plugin_name"])
    except Exception as exc:  # die Wiederherstellung bleibt gültig
        result["reload"] = {"error": str(exc)}
    return result
