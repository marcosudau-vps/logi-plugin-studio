"""SDK folder display/navigation projection. NativeAction remains the only action owner.

No Qt dependency, no service/profile writes and no cross-plugin invocation.
The projection can be built from an explicitly supplied virtual-folders-1 snapshot.
"""
from __future__ import annotations

import copy
import json

from core.ids import is_valid_id
from adapters.logitech.native import parse_native_project

VERSION = "sdk-folders-1"
MAX_LAYOUT_BYTES = 48 * 1024  # fits one existing authenticated journal frame


class FolderRuntimeError(ValueError):
    pass


def _require(condition, path, message):
    if not condition:
        raise FolderRuntimeError(f"{path}: {message}")


def _fields(value, required, optional, path):
    _require(isinstance(value, dict), path, "object required")
    _require(set(required) <= value.keys() and not value.keys() - set(required) - set(optional), path, "missing or unknown fields")


def _id(value, path):
    _require(is_valid_id(value), path, "stable ID required")


def validate_layout(raw, native, *, allow_peers=False):
    """Return a defensive full snapshot; reject before changing any runtime state."""
    project = parse_native_project(native)
    _fields(raw, ("version", "plugin_id", "revision", "folders"), (), "/")
    _require(raw["version"] == VERSION and raw["plugin_id"] == project.plugin_id, "/", "version/plugin mismatch")
    _require(type(raw["revision"]) is int and 0 <= raw["revision"] <= 2**53 - 1, "/revision", "non-negative safe integer required")
    _require(isinstance(raw["folders"], list), "/folders", "array required")
    actions = {a.id: a for a in project.actions}
    real_ids = {f.id for f in project.folders}
    found = set()
    binding_ids = {}
    for i, folder in enumerate(raw["folders"]):
        path = f"/folders/{i}"
        _fields(folder, ("id", "start", "nodes"), (), path)
        _id(folder["id"], path + "/id")
        _id(folder["start"], path + "/start")
        _require(folder["id"] in real_ids and folder["id"] not in found, path + "/id", "unknown or repeated native folder")
        found.add(folder["id"])
        _require(isinstance(folder["nodes"], list) and bool(folder["nodes"]), path + "/nodes", "non-empty array required")
        nodes, pages, entries = set(), set(), set()
        targets = []
        for j, node in enumerate(folder["nodes"]):
            np = f"{path}/nodes/{j}"
            _fields(node, ("id", "label", "pages"), (), np)
            _id(node["id"], np + "/id")
            _require(node["id"] not in nodes, np, "duplicate node")
            nodes.add(node["id"])
            _require(isinstance(node["label"], str) and bool(node["label"]), np + "/label", "non-empty text required")
            _require(isinstance(node["pages"], list) and bool(node["pages"]), np + "/pages", "non-empty array required")
            for k, page in enumerate(node["pages"]):
                pp = f"{np}/pages/{k}"
                _fields(page, ("id", "entries"), (), pp)
                _id(page["id"], pp + "/id")
                _require(page["id"] not in pages, pp, "duplicate page")
                pages.add(page["id"])
                _require(isinstance(page["entries"], list), pp + "/entries", "array required")
                for n, entry in enumerate(page["entries"]):
                    ep = f"{pp}/entries/{n}"
                    peer_fields = ("peer", "instance", "sdk_type", "operations", "value", "state", "image_hash") if allow_peers else ()
                    _fields(entry, ("id", "kind", "label"), ("action_id", "action_parameter", "target_id", "reason", *peer_fields), ep)
                    _id(entry["id"], ep + "/id")
                    _require(entry["id"] not in entries, ep, "duplicate placement")
                    entries.add(entry["id"])
                    _require(isinstance(entry["label"], str), ep + "/label", "text required")
                    kind = entry["kind"]
                    if kind == "action":
                        _require(set(entry) <= {"id", "kind", "label", "action_id", "action_parameter"}, ep, "invalid action fields")
                        _id(entry.get("action_id"), ep + "/action_id")
                        _require(entry.get("action_id") in actions, ep + "/action_id", "unknown native action")
                        action = actions[entry["action_id"]]
                        _require(action.sdk_type != "ActionEditorCommand", ep + "/action_id", "FOLDER_ACTION_EDITOR_UNSUPPORTED: configure this action through its SDK catalog entry")
                        parameter = entry.get("action_parameter")
                        _require(parameter is None or isinstance(parameter, str) and len(parameter) <= 4096, ep + "/action_parameter", "null or bounded string required")
                        _require(parameter is None or parameter in {p.name for p in action.parameters}, ep + "/action_parameter", "unknown declared parameter")
                        binding = (action.id, parameter)
                        _require(entry["id"] not in binding_ids or binding_ids[entry["id"]] == binding, ep + "/id", "placement binding differs between SDK folders")
                        binding_ids[entry["id"]] = binding
                        if action.sdk_type == "PluginDynamicAdjustment":
                            area = next(f for f in project.folders if f.id == folder["id"])
                            _require(area.navigation != "EncoderArea" and "EncoderArea" not in area.device_navigation.values(), ep, "FOLDER_ENCODER_NAVIGATION_CONFLICT: adjustments occupy the encoder area")
                    elif kind == "peer_action" and allow_peers:
                        from .peer_wire import identity
                        _fields(entry, ("id", "kind", "label", "action_id", "action_parameter", *peer_fields), (), ep)
                        _id(entry["peer"], ep + "/peer")
                        _id(entry["action_id"], ep + "/action_id")
                        _require(identity(entry["instance"]) and entry["peer"] != project.plugin_id, ep, "remote owner instance")
                    elif kind in ("folder", "link"):
                        _require(set(entry) <= {"id", "kind", "label", "target_id"}, ep, "invalid navigation fields")
                        _id(entry.get("target_id"), ep + "/target_id")
                        targets.append((entry.get("target_id"), ep))
                    elif kind == "unavailable":
                        _require(set(entry) <= {"id", "kind", "label", "reason"} and isinstance(entry.get("reason"), str), ep, "unavailable entries require a reason and cannot invoke actions")
                    else:
                        raise FolderRuntimeError(f"{ep}/kind: unknown entry kind")
        _require(folder["start"] in nodes, path + "/start", "unknown start node")
        for target, ep in targets:
            _require(target in nodes, ep + "/target_id", "unknown target node")
    _require(found == real_ids, "/folders", "complete snapshot of all native folders required")
    try:
        encoded = json.dumps(raw, ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise FolderRuntimeError("/: finite JSON required") from exc
    _require(len(encoded) <= MAX_LAYOUT_BYTES, "/", "layout exceeds 48 KiB transport budget")
    return copy.deepcopy(raw)


def initial_layout(native):
    project = parse_native_project(native)
    actions = {a.id: a for a in project.actions}
    folders, diagnostics = [], []
    for folder in project.folders:
        entries = []
        for e in sorted(folder.entries, key=lambda e: e.position):
            action = actions[e.action]
            item = dict(id=e.id, kind="action", label=action.display_name,
                        action_id=e.action, action_parameter=e.action_parameter)
            if action.sdk_type == "ActionEditorCommand":
                item = dict(id=e.id, kind="unavailable", label=action.display_name,
                            reason="FOLDER_ACTION_EDITOR_UNSUPPORTED")
                diagnostics.append(dict(code=item["reason"], folder_id=folder.id, placement_id=e.id))
            entries.append(item)
        folders.append(dict(id=folder.id, start=folder.id, nodes=[dict(id=folder.id, label=folder.display_name,
                            pages=[dict(id="page." + folder.id, entries=entries)])]))
    return validate_layout(dict(version=VERSION, plugin_id=project.plugin_id, revision=0, folders=folders), native), diagnostics


def project_virtual_folders(native, document, *, entrypoints, revision):
    """Project an explicit codec snapshot without action copies or Qt imports.

    External references survive as disabled labels. Auto/manual pages are already
    resolved by the authoring owner; the SDK still handles physical overflow.
    """
    project = parse_native_project(native)
    _require(isinstance(document, dict) and document.get("version") == "virtual-folders-1"
             and document.get("plugin_id") == project.plugin_id, "/document", "virtual-folder version/plugin mismatch")
    # Optional extension adapter only: reuse its existing strict Qt-free codec.
    # This path is never loaded by plain native generation/host initialization.
    from dataclasses import asdict
    from studio.virtual_folders.codec import decode
    try:
        document = asdict(decode(json.dumps(document, allow_nan=False).encode("utf-8"),
                                 project_id=document.get("project_id"), plugin_id=project.plugin_id))
    except (ValueError, TypeError, RecursionError) as exc:
        raise FolderRuntimeError(f"/document: {exc}") from exc
    _require(set(entrypoints) == {f.id for f in project.folders}, "/entrypoints", "one explicit start per native folder required")
    nodes = []
    for folder in document["folders"]:
        pages = []
        for page in folder["pages"]:
            entries = []
            for p in sorted((p for p in document["placements"] if p["folder_id"] == folder["id"] and p["page_id"] == page["id"]), key=lambda p: p["position"]):
                target = p["target"]
                item = dict(id=p["id"], kind="action" if p["kind"] == "action" else "link" if p["kind"] == "link" else "folder", label=target["resource_id"])
                if target["plugin_id"] != project.plugin_id:
                    item.update(kind="unavailable", reason="EXTERNAL_REFERENCE_OFFLINE")
                elif p["kind"] == "action":
                    action = next((a for a in project.actions if a.id == target["resource_id"]), None)
                    _require(action is not None, "/document/placements", "orphan local action reference")
                    item.update(label=action.display_name)
                    if action.sdk_type == "ActionEditorCommand":
                        item.update(kind="unavailable", reason="FOLDER_ACTION_EDITOR_UNSUPPORTED")
                    else:
                        item.update(action_id=action.id, action_parameter=p.get("action_parameter"))
                else:
                    item["target_id"] = target["resource_id"]
                entries.append(item)
            pages.append(dict(id=page["id"], entries=entries))
        nodes.append(dict(id=folder["id"], label=folder["name"], pages=pages))
    return validate_layout(dict(version=VERSION, plugin_id=project.plugin_id, revision=revision,
        folders=[dict(id=f.id, start=entrypoints[f.id], nodes=copy.deepcopy(nodes)) for f in project.folders]), native)


def folder_source(plan, folder):
    from adapters.logitech.naming import csharp_literal, identifier
    cases = "\n".join(f"DeviceType.{device} => PluginDynamicFolderNavigation.{area},"
                      for device, area in sorted(folder.device_navigation.items()))
    expression = f"PluginDynamicFolderNavigation.{folder.navigation}"
    if cases:
        expression = f"deviceType switch {{ {cases} _ => {expression} }}"
    return f'''namespace {plan.namespace}
{{
    using Loupedeck;
    public class {identifier('Folder', folder.id)} : NativeFolderBase
    {{
        protected override string FolderId => {csharp_literal(folder.id)};
        public {identifier('Folder', folder.id)}() {{ this.DisplayName = {csharp_literal(folder.display_name)}; this.GroupName = {csharp_literal(plan.plugin_display_name)}; }}
        public override PluginDynamicFolderNavigation GetNavigationArea(DeviceType deviceType) => {expression};
    }}
}}
'''
