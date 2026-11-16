from __future__ import annotations

from library.document import empty_project


def callback_project(project_id: str = "my.plugin", name: str = "Mein Python-Plugin") -> dict:
    raw = empty_project(project_id, name)
    raw["dependencies"] = [{"type": "core.command_action", "version": "1.0.0"},
                           {"type": "core.host_handler", "version": "1.0.0"}]
    raw["components"] = [
        {"id": "action.first", "type": "core.command_action", "version": "1.0.0",
         "config": {"display_name": "Meine erste Aktion"}},
        {"id": "action.second", "type": "core.command_action", "version": "1.0.0",
         "config": {"display_name": "Meine zweite Aktion"}},
        {"id": "handler.toggle", "type": "core.host_handler", "version": "1.0.0",
         "config": {"callback_id": "toggle"}},
    ]
    raw["states"] = [{"id": "state.mode", "value_schema": {"type": "string", "enum": ["active", "idle"]},
                      "authority": {"role": "host"}, "scope": "component",
                      "persistence": "none", "fallback": "idle"}]
    raw["presentations"] = [{
        "id": "visual.mode", "variants": {
            "idle": {"text": "Bereit", "background": "#243449", "foreground": "#ffffff"},
            "active": {"text": "Aktiv", "background": "#25684a", "foreground": "#ffffff"},
        }}]
    raw["bindings"] = [
        {"id": "binding.first", "kind": "command",
         "source": {"owner_kind": "component", "owner_id": "action.first", "port": "activated"},
         "target": {"owner_kind": "component", "owner_id": "handler.toggle", "port": "invoke"}},
        {"id": "binding.second", "kind": "command",
         "source": {"owner_kind": "component", "owner_id": "action.second", "port": "activated"},
         "target": {"owner_kind": "component", "owner_id": "handler.toggle", "port": "invoke"}},
        {"id": "binding.visual", "kind": "state",
         "source": {"owner_kind": "state", "owner_id": "state.mode", "port": "value"},
         "target": {"owner_kind": "presentation", "owner_id": "visual.mode", "port": "selector"}},
    ]
    raw["views"] = [{"id": "view.main", "type": "folder", "placements": [
        {"id": "placement.first", "component": "action.first", "presentation": "visual.mode", "position": 0},
        {"id": "placement.second", "component": "action.second", "presentation": "visual.mode", "position": 1},
    ]}]
    return raw
