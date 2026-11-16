"""Minimal Logitech-native project contract and legacy compatibility adapter.

The native document mirrors SDK action classes directly.  It is deliberately
not a replacement for the generic core model: old ``0.1-draft`` documents are
read unchanged and adapted to ``PluginDynamicCommand`` at the adapter edge.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from core.ids import is_valid_id

NATIVE_SCHEMA_VERSION = "logitech-native-1"
ACTION_TYPES = frozenset(
    {
        "PluginDynamicCommand",
        "PluginMultistateDynamicCommand",
        "PluginDynamicAdjustment",
        "ActionEditorCommand",
    }
)
NAVIGATION_AREAS = frozenset({"None", "ButtonArea", "EncoderArea"})
DEVICE_TYPES = frozenset({
    "Loupedeck10", "Loupedeck15", "LoupedeckOriginalFamily", "Loupedeck20", "Loupedeck30",
    "Loupedeck40", "Loupedeck50", "Loupedeck60", "LoupedeckCtFamily", "Loupedeck70",
    "Loupedeck71", "Loupedeck72", "LoupedeckExtendedFamily", "All",
})


class NativeProjectError(ValueError):
    """The native Logitech project is structurally or semantically invalid."""


@dataclass(frozen=True)
class NativeParameter:
    name: str
    display_name: str
    group_name: str
    super_group_name: str | None = None


@dataclass(frozen=True)
class NativeState:
    index: int
    name: str
    display_name: str
    description: str
    image: str | None = None


@dataclass(frozen=True)
class EditorControl:
    type: str
    name: str
    label: str
    description: str | None = None
    default: str | bool | float | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    format_string: str | None = None
    dialog_title: str | None = None
    initial_directory: str | None = None
    filters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class NativeAction:
    id: str
    sdk_type: str
    display_name: str
    description: str
    group_name: str
    handler: str
    parameters: tuple[NativeParameter, ...] = ()
    states: tuple[NativeState, ...] = ()
    state_change: str = "none"
    has_reset: bool = False
    adjustment_min: float | None = None
    adjustment_max: float | None = None
    adjustment_default: float | None = None
    adjustment_format: str = "{0}"
    editor_controls: tuple[EditorControl, ...] = ()
    icon: str | None = None
    icon_template: str | None = None
    symbol: str | None = None
    parameter_symbols: dict[str, str] = field(default_factory=dict)
    legacy: bool = False


@dataclass(frozen=True)
class NativeFolderEntry:
    id: str
    action: str
    position: int
    action_parameter: str | None = None


@dataclass(frozen=True)
class NativeFolder:
    id: str
    display_name: str
    navigation: str
    entries: tuple[NativeFolderEntry, ...]
    device_navigation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeProject:
    plugin_id: str
    display_name: str
    actions: tuple[NativeAction, ...]
    handlers: tuple[dict[str, str], ...]
    folders: tuple[NativeFolder, ...]
    default_icon_template: str | None = None
    licenses: tuple[str, ...] = ()
    legacy_raw: dict[str, Any] | None = None


def is_native_project(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("schema_version") == NATIVE_SCHEMA_VERSION


def _object(value: Any, path: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise NativeProjectError(f"{path} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise NativeProjectError(f"{path} has unknown fields: {sorted(unknown)}")
    if missing:
        raise NativeProjectError(f"{path} is missing fields: {sorted(missing)}")
    return value


def _text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise NativeProjectError(f"{path} must be a non-empty string")
    return value


def _identifier(value: Any, path: str) -> str:
    value = _text(value, path)
    if not is_valid_id(value):
        raise NativeProjectError(f"{path} is not a stable project identifier")
    return value


def _relative_path(value: Any, path: str, suffixes: tuple[str, ...]) -> str:
    value = _text(value, path)
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized or any(part in ("", "..") for part in normalized.split("/")):
        raise NativeProjectError(f"{path} must be a portable project-relative path")
    if not normalized.lower().endswith(suffixes):
        raise NativeProjectError(f"{path} must use one of {suffixes}")
    return normalized


def _parameters(raw: Any, path: str) -> tuple[NativeParameter, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise NativeProjectError(f"{path} must be an array")
    result: list[NativeParameter] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        here = f"{path}/{index}"
        item = _object(item, here, {"name", "display_name", "group_name", "super_group_name"},
                       {"name", "display_name", "group_name"})
        name = _text(item["name"], here + "/name")
        if name in names:
            raise NativeProjectError(f"{path} contains duplicate parameter {name!r}")
        names.add(name)
        super_group = item.get("super_group_name")
        if super_group is not None:
            super_group = _text(super_group, here + "/super_group_name")
        result.append(NativeParameter(name, _text(item["display_name"], here + "/display_name"),
                                      _text(item["group_name"], here + "/group_name"), super_group))
    return tuple(result)


def _states(raw: Any, path: str) -> tuple[NativeState, ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise NativeProjectError(f"{path} must contain at least two fixed states")
    result: list[NativeState] = []
    names: set[str] = set()
    for position, item in enumerate(raw):
        here = f"{path}/{position}"
        item = _object(item, here, {"index", "name", "display_name", "description", "image", "led_color"},
                       {"index", "name", "display_name", "description"})
        if item["index"] != position:
            raise NativeProjectError(f"{here}/index must be fixed, contiguous and equal to {position}")
        if item.get("led_color") is not None:
            raise NativeProjectError(
                f"{here}/led_color is unsupported by the installed PluginApi.dll: "
                "PluginMultistateDynamicCommandState exposes no LED property or setter"
            )
        name = _text(item["name"], here + "/name")
        if name in names:
            raise NativeProjectError(f"{path} contains duplicate state name {name!r}")
        names.add(name)
        image = item.get("image")
        if image is not None:
            image = _relative_path(image, here + "/image", (".png", ".svg"))
        result.append(NativeState(position, name, _text(item["display_name"], here + "/display_name"),
                                  _text(item["description"], here + "/description", allow_empty=True), image))
    return tuple(result)


def _editor_controls(raw: Any, path: str) -> tuple[EditorControl, ...]:
    """Parse only controls whose constructor and callbacks were verified in the installed SDK."""
    import math

    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise NativeProjectError(f"{path} must be a non-empty array")
    supported = {
        "textbox", "checkbox", "textarea", "file_selector",
        "directory_selector", "slider", "numeric_up_down",
    }
    numeric = {"slider", "numeric_up_down"}
    result: list[EditorControl] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        here = f"{path}/{index}"
        item = _object(item, here, {
            "type", "name", "label", "description", "default",
            "minimum", "maximum", "step", "format_string",
            "dialog_title", "initial_directory", "filters",
        }, {"type", "name", "label"})
        control_type = item["type"]
        if control_type not in supported:
            raise NativeProjectError(f"{here}/type is not a supported installed SDK control")
        name = _text(item["name"], here + "/name")
        if name in names:
            raise NativeProjectError(f"{path} contains duplicate control {name!r}")
        names.add(name)
        description = item.get("description")
        if description is not None:
            description = _text(description, here + "/description", allow_empty=True)
        default = item.get("default")
        minimum = maximum = step = None
        fmt = dialog_title = initial_dir = None
        filters: list[tuple[str, str]] = []
        numeric_keys = {"minimum", "maximum", "step", "format_string"}
        dialog_keys = {"dialog_title", "initial_directory", "filters"}
        if control_type in numeric:
            if not {"minimum", "maximum", "step", "default"} <= item.keys():
                raise NativeProjectError(f"{here} numeric controls require minimum, maximum, step and default")
            for key in ("minimum", "maximum", "step", "default"):
                val = item[key]
                if type(val) not in (int, float) or not math.isfinite(val):
                    raise NativeProjectError(f"{here}/{key} must be a finite number")
            minimum, maximum, step, default = (
                float(item["minimum"]), float(item["maximum"]),
                float(item["step"]), float(item["default"]))
            if not (minimum < maximum and step > 0 and minimum <= default <= maximum):
                raise NativeProjectError(f"{here} numeric bounds/default/step are inconsistent")
            if "format_string" in item:
                fmt = _text(item["format_string"], here + "/format_string")
        else:
            if any(key in item for key in numeric_keys):
                raise NativeProjectError(f"{here} numeric options are not applicable to {control_type}")
            if control_type == "checkbox":
                if default is not None and type(default) is not bool:
                    raise NativeProjectError(f"{here}/default must be boolean")
            elif default is not None:
                raise NativeProjectError(f"{here}/default is not supported by the installed SDK control")
        if control_type in {"file_selector", "directory_selector"}:
            if item.get("dialog_title") is not None:
                dialog_title = _text(item["dialog_title"], here + "/dialog_title")
            if item.get("initial_directory") is not None:
                initial_dir = _text(item["initial_directory"], here + "/initial_directory")
            if control_type == "file_selector":
                entries = item.get("filters", [])
                if not isinstance(entries, list):
                    raise NativeProjectError(f"{here}/filters must be an array")
                for j, entry in enumerate(entries):
                    entry = _object(entry, f"{here}/filters/{j}",
                                    {"pattern", "label"}, {"pattern", "label"})
                    filters.append((_text(entry["pattern"], f"{here}/filters/{j}/pattern"),
                                    _text(entry["label"], f"{here}/filters/{j}/label")))
            elif "filters" in item:
                raise NativeProjectError(f"{here}/filters requires file_selector")
        elif any(key in item for key in dialog_keys):
            raise NativeProjectError(f"{here} dialog options are not applicable to {control_type}")
        result.append(EditorControl(
            control_type, name, _text(item["label"], here + "/label"), description,
            default, minimum, maximum, step, fmt, dialog_title, initial_dir, tuple(filters),
        ))
    return tuple(result)


def parse_native_project(raw: Any) -> NativeProject:
    root = _object(raw, "/", {"schema_version", "plugin", "handlers", "actions", "folders", "licenses"},
                   {"schema_version", "plugin", "handlers", "actions", "folders"})
    if root["schema_version"] != NATIVE_SCHEMA_VERSION:
        raise NativeProjectError(f"/schema_version must be {NATIVE_SCHEMA_VERSION!r}")
    plugin = _object(root["plugin"], "/plugin", {"id", "display_name", "default_icon_template"},
                     {"id", "display_name"})
    default_template = plugin.get("default_icon_template")
    if default_template is not None:
        default_template = _relative_path(default_template, "/plugin/default_icon_template", (".ict",))

    handlers_raw = root["handlers"]
    if not isinstance(handlers_raw, list) or not handlers_raw:
        raise NativeProjectError("/handlers must be a non-empty array")
    handlers: list[dict[str, str]] = []
    handler_ids: set[str] = set()
    for index, item in enumerate(handlers_raw):
        here = f"/handlers/{index}"
        item = _object(item, here, {"id", "callback_id"}, {"id", "callback_id"})
        handler_id = _identifier(item["id"], here + "/id")
        if handler_id in handler_ids:
            raise NativeProjectError(f"duplicate handler {handler_id!r}")
        handler_ids.add(handler_id)
        handlers.append({"id": handler_id, "callback_id": _text(item["callback_id"], here + "/callback_id")})

    actions_raw = root["actions"]
    if not isinstance(actions_raw, list) or not actions_raw:
        raise NativeProjectError("/actions must be a non-empty array")
    actions: list[NativeAction] = []
    action_ids: set[str] = set()
    for index, item in enumerate(actions_raw):
        here = f"/actions/{index}"
        item = _object(
            item, here,
            {"id", "sdk_type", "display_name", "description", "group_name", "handler", "parameters",
             "states", "state_change", "adjustment", "editor_controls", "icon", "icon_template", "symbol",
             "parameter_symbols"},
            {"id", "sdk_type", "display_name", "handler"},
        )
        action_id = _identifier(item["id"], here + "/id")
        if action_id in action_ids:
            raise NativeProjectError(f"{here}/id: duplicate action {action_id!r}")
        if action_id in handler_ids:
            raise NativeProjectError(f"{here}/id: action ID {action_id!r} collides with /handlers; actions and handlers share the runtime component namespace")
        action_ids.add(action_id)
        sdk_type = item["sdk_type"]
        if sdk_type not in ACTION_TYPES:
            raise NativeProjectError(f"{here}/sdk_type is not a supported installed SDK action class")
        handler = _identifier(item["handler"], here + "/handler")
        if handler not in handler_ids:
            raise NativeProjectError(f"{here}/handler references unknown handler {handler!r}")
        parameters = _parameters(item.get("parameters"), here + "/parameters")
        states: tuple[NativeState, ...] = ()
        state_change = item.get("state_change", "none")
        if sdk_type == "PluginMultistateDynamicCommand":
            states = _states(item.get("states"), here + "/states")
            if state_change not in ("none", "increment", "decrement", "toggle"):
                raise NativeProjectError(f"{here}/state_change is invalid")
            if state_change == "toggle" and len(states) != 2:
                raise NativeProjectError(f"{here}/state_change 'toggle' requires exactly two states")
        elif "states" in item or "state_change" in item:
            raise NativeProjectError(f"{here} may define states only for PluginMultistateDynamicCommand")

        adjustment = item.get("adjustment")
        has_reset = False
        adj_min = adj_max = adj_default = None
        adj_format = "{0}"
        if sdk_type == "PluginDynamicAdjustment":
            adjustment = _object(adjustment or {}, here + "/adjustment",
                                 {"has_reset", "minimum", "maximum", "default", "format"})
            has_reset = adjustment.get("has_reset", False)
            if type(has_reset) is not bool:
                raise NativeProjectError(f"{here}/adjustment/has_reset must be boolean")
            adj_min, adj_max, adj_default = (adjustment.get(k) for k in ("minimum", "maximum", "default"))
            if any(v is not None and type(v) not in (int, float) for v in (adj_min, adj_max, adj_default)):
                raise NativeProjectError(f"{here}/adjustment numeric values must be numbers")
            if adj_min is not None and adj_max is not None and adj_min > adj_max:
                raise NativeProjectError(f"{here}/adjustment minimum exceeds maximum")
            if adj_default is not None and ((adj_min is not None and adj_default < adj_min) or
                                            (adj_max is not None and adj_default > adj_max)):
                raise NativeProjectError(f"{here}/adjustment default is outside bounds")
            adj_format = _text(adjustment.get("format", "{0}"), here + "/adjustment/format")
        elif adjustment is not None:
            raise NativeProjectError(f"{here}/adjustment is valid only for PluginDynamicAdjustment")

        controls = _editor_controls(item.get("editor_controls"), here + "/editor_controls") \
            if sdk_type == "ActionEditorCommand" else ()
        if sdk_type != "ActionEditorCommand" and "editor_controls" in item:
            raise NativeProjectError(f"{here}/editor_controls is valid only for ActionEditorCommand")
        icon = item.get("icon")
        if icon is not None:
            icon = _relative_path(icon, here + "/icon", (".png", ".svg"))
        template = item.get("icon_template")
        if template is not None:
            template = _relative_path(template, here + "/icon_template", (".ict",))
        symbol = item.get("symbol")
        if symbol is not None:
            symbol = _relative_path(symbol, here + "/symbol", (".svg",))
        parameter_symbols = item.get("parameter_symbols", {})
        if not isinstance(parameter_symbols, dict) or any(not isinstance(k, str) for k in parameter_symbols):
            raise NativeProjectError(f"{here}/parameter_symbols must be an object")
        parameter_names = {parameter.name for parameter in parameters}
        parsed_symbols: dict[str, str] = {}
        for name, source in parameter_symbols.items():
            if name not in parameter_names:
                raise NativeProjectError(f"{here}/parameter_symbols references unknown parameter {name!r}")
            parsed_symbols[name] = _relative_path(source, f"{here}/parameter_symbols/{name}", (".svg",))
        actions.append(NativeAction(
            action_id, sdk_type, _text(item["display_name"], here + "/display_name"),
            _text(item.get("description", "Python host action"), here + "/description", allow_empty=True),
            _text(item.get("group_name", plugin["display_name"]), here + "/group_name"), handler,
            parameters, states, state_change, has_reset, adj_min, adj_max, adj_default, adj_format,
            controls, icon, template, symbol, parsed_symbols,
        ))

    folders_raw = root["folders"]
    if not isinstance(folders_raw, list):
        raise NativeProjectError("/folders must be an array")
    folders: list[NativeFolder] = []
    folder_ids: set[str] = set()
    placement_ids: set[str] = set()
    for index, item in enumerate(folders_raw):
        here = f"/folders/{index}"
        item = _object(item, here, {"id", "display_name", "navigation", "device_navigation", "entries"},
                       {"id", "display_name", "navigation", "entries"})
        folder_id = _identifier(item["id"], here + "/id")
        if folder_id in folder_ids:
            raise NativeProjectError(f"duplicate folder {folder_id!r}")
        folder_ids.add(folder_id)
        navigation = item["navigation"]
        if navigation not in NAVIGATION_AREAS:
            raise NativeProjectError(f"{here}/navigation must be one of {sorted(NAVIGATION_AREAS)}")
        device_navigation = item.get("device_navigation", {})
        if not isinstance(device_navigation, dict):
            raise NativeProjectError(f"{here}/device_navigation must be an object")
        for device, area in device_navigation.items():
            if device not in DEVICE_TYPES or area not in NAVIGATION_AREAS:
                raise NativeProjectError(f"{here}/device_navigation contains an unknown reflected DeviceType or navigation area")
        entries_raw = item["entries"]
        if not isinstance(entries_raw, list):
            raise NativeProjectError(f"{here}/entries must be an array")
        entries: list[NativeFolderEntry] = []
        used_positions: dict[int, str] = {}
        for entry_index, entry in enumerate(entries_raw):
            entry_path = f"{here}/entries/{entry_index}"
            entry = _object(entry, entry_path, {"id", "action", "position", "action_parameter"}, {"id", "action", "position"})
            placement_id = _identifier(entry["id"], entry_path + "/id")
            if placement_id in placement_ids:
                raise NativeProjectError(f"duplicate placement {placement_id!r}")
            placement_ids.add(placement_id)
            action_id = _identifier(entry["action"], entry_path + "/action")
            if action_id not in action_ids:
                raise NativeProjectError(f"{entry_path}/action references unknown action {action_id!r}")
            if type(entry["position"]) is not int or entry["position"] < 0:
                raise NativeProjectError(f"{entry_path}/position must be a non-negative integer")
            if entry["position"] in used_positions:
                raise NativeProjectError(f"{entry_path}/position: position {entry['position']} already occupied by {used_positions[entry['position']]}")
            used_positions[entry["position"]] = entry_path
            parameter = entry.get("action_parameter")
            if parameter is not None:
                action = next(a for a in actions if a.id == action_id)
                if not isinstance(parameter, str) or parameter not in {p.name for p in action.parameters}:
                    raise NativeProjectError(f"{entry_path}/action_parameter: unknown declared action parameter")
            entries.append(NativeFolderEntry(placement_id, action_id, entry["position"], parameter))
        folders.append(NativeFolder(folder_id, _text(item["display_name"], here + "/display_name"),
                                    navigation, tuple(entries), dict(sorted(device_navigation.items()))))

    licenses_raw = root.get("licenses", [])
    if not isinstance(licenses_raw, list):
        raise NativeProjectError("/licenses must be an array")
    licenses = tuple(_relative_path(value, f"/licenses/{index}", (".txt", ".md", ".license"))
                     for index, value in enumerate(licenses_raw))
    return NativeProject(_identifier(plugin["id"], "/plugin/id"),
                         _text(plugin["display_name"], "/plugin/display_name"), tuple(actions),
                         tuple(handlers), tuple(folders), default_template, licenses)


def legacy_project(raw: Any) -> NativeProject:
    """Expose an unchanged 0.1 draft through the native action view."""
    if not isinstance(raw, dict) or raw.get("schema_version") != "0.1-draft":
        raise NativeProjectError("Expected logitech-native-1 or compatible 0.1-draft project")
    header = raw.get("project")
    if not isinstance(header, dict):
        raise NativeProjectError("Legacy project header is invalid")
    actions: list[NativeAction] = []
    handlers = [copy.deepcopy(c) for c in raw.get("components", [])
                if isinstance(c, dict) and c.get("type") == "core.host_handler"]
    handler_ids = {h.get("id") for h in handlers}
    routes = {}
    for binding in raw.get("bindings", []):
        if not isinstance(binding, dict) or binding.get("kind") != "command":
            continue
        source, target = binding.get("source"), binding.get("target")
        if isinstance(source, dict) and isinstance(target, dict) and source.get("port") == "activated":
            routes[source.get("owner_id")] = target.get("owner_id")
    fallback_handler = next(iter(handler_ids), "handler.compat")
    if not handlers:
        handlers = [{"id": fallback_handler, "config": {"callback_id": fallback_handler}}]
    for component in raw.get("components", []):
        if not isinstance(component, dict) or component.get("type") != "core.command_action":
            continue
        config = component.get("config") if isinstance(component.get("config"), dict) else {}
        actions.append(NativeAction(
            str(component.get("id")), "PluginDynamicCommand", str(config.get("display_name", component.get("id"))),
            "Python command", str(header.get("display_name", "Plugin")),
            str(routes.get(component.get("id"), fallback_handler)), legacy=True,
        ))
    folders = tuple(
        NativeFolder(str(view.get("id")), str(view.get("id")), "ButtonArea", tuple(
            NativeFolderEntry(str(entry.get("id")), str(entry.get("component")), int(entry.get("position", 0)))
            for entry in view.get("placements", []) if isinstance(entry, dict)
        ), {})
        for view in raw.get("views", []) if isinstance(view, dict)
    )
    normalized_handlers = tuple({"id": str(h["id"]), "callback_id": str(h.get("config", {}).get("callback_id", h["id"]))}
                                for h in handlers if isinstance(h, dict) and "id" in h)
    return NativeProject(str(header.get("id")), str(header.get("display_name")), tuple(actions),
                         normalized_handlers, folders, legacy_raw=copy.deepcopy(raw))


def project_view(raw: Any) -> NativeProject:
    return parse_native_project(raw) if is_native_project(raw) else legacy_project(raw)


def runtime_projection(raw: Any) -> dict[str, Any]:
    """Create the technical host graph; native SDK semantics remain in ``raw``."""
    project = project_view(raw)
    if project.legacy_raw is not None:
        return copy.deepcopy(project.legacy_raw)
    components = [
        {"id": action.id, "type": "core.command_action", "version": "1.0.0",
         "config": {"display_name": action.display_name}}
        for action in project.actions
    ]
    components.extend(
        {"id": handler["id"], "type": "core.host_handler", "version": "1.0.0",
         "config": {"callback_id": handler["callback_id"]}}
        for handler in project.handlers
    )
    bindings = [
        {"id": f"binding.native.{index}",
         "source": {"owner_kind": "component", "owner_id": action.id, "port": "activated"},
         "target": {"owner_kind": "component", "owner_id": action.handler, "port": "invoke"},
         "kind": "command"}
        for index, action in enumerate(project.actions)
    ]
    views = [
        {"id": folder.id, "type": "folder", "placements": [
            {"id": entry.id, "component": entry.action, "position": entry.position}
            for entry in folder.entries
        ]}
        for folder in project.folders
    ]
    return {
        "schema_version": "0.1-draft",
        "project": {"id": project.plugin_id, "display_name": project.display_name},
        "dependencies": [
            {"type": "core.command_action", "version": "1.0.0"},
            {"type": "core.host_handler", "version": "1.0.0"},
        ],
        "components": components,
        "states": [],
        "bindings": bindings,
        "presentations": [],
        "assets": [],
        "views": views,
    }


__all__ = [
    "ACTION_TYPES", "NATIVE_SCHEMA_VERSION", "NAVIGATION_AREAS", "NativeAction", "NativeFolder",
    "NativeParameter", "NativeProject", "NativeProjectError", "NativeState", "is_native_project",
    "legacy_project", "parse_native_project", "project_view", "runtime_projection",
]
