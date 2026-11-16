"""Create a new, valid logitech-native-1 project from a small built-in template."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from adapters.logitech.native import NativeProjectError, project_view

TEMPLATE = {
    "schema_version": "logitech-native-1",
    "plugin": {"id": "", "display_name": ""},
    "handlers": [{"id": "handler.main", "callback_id": "handler.main"}],
    "actions": [
        {"id": "action.command", "sdk_type": "PluginDynamicCommand", "display_name": "Befehl",
         "description": "Ruft den Python-Handler auf.", "group_name": "Allgemein", "handler": "handler.main",
         "parameters": [{"name": "first", "display_name": "Variante 1", "group_name": "Varianten"}]},
        {"id": "action.toggle", "sdk_type": "PluginMultistateDynamicCommand", "display_name": "Schalter",
         "handler": "handler.main", "state_change": "toggle",
         "states": [{"index": 0, "name": "off", "display_name": "Aus", "description": "Ausgeschaltet"},
                    {"index": 1, "name": "on", "display_name": "An", "description": "Eingeschaltet"}]},
    ],
    "folders": [
        {"id": "folder.main", "display_name": "Startseite", "navigation": "ButtonArea",
         "entries": [{"id": "placement.command", "action": "action.command", "position": 0,
                      "action_parameter": "first"},
                     {"id": "placement.toggle", "action": "action.toggle", "position": 1}]}
    ],
}


def new_project_raw(plugin_id: str, display_name: str) -> dict:
    raw = copy.deepcopy(TEMPLATE)
    raw["plugin"]["id"] = plugin_id.strip()
    raw["plugin"]["display_name"] = display_name.strip() or plugin_id.strip()
    try:
        project_view(raw)
    except NativeProjectError as exc:
        raise ValueError(f"Ungültige Plugin-ID oder Name: {exc}") from exc
    return raw


def create_native_project(path: str | Path, plugin_id: str, display_name: str) -> Path:
    """Write a new project file; never overwrites an existing file."""
    path = Path(path)
    raw = new_project_raw(plugin_id, display_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return path
