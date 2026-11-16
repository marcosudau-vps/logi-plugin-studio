"""Namespaced folder rendering over read-only, scoped peer replicas."""
from __future__ import annotations

import copy
import hashlib
import re

from .peer_runtime import Scope
from .peer_wire import MAX_SCOPES, PeerError, resource_id, shape


def project_shared_folders(native, document, *, entrypoints, revision):
    """Authoring boundary. Packaged runtimes consume only the projected data."""
    from .runtime_projection import project_virtual_folders

    layout = project_virtual_folders(native, document, entrypoints=entrypoints, revision=revision)
    refs = []
    for placement in document["placements"]:
        target = placement["target"]
        if target["plugin_id"] != layout["plugin_id"]:
            scope = Scope("action" if placement["kind"] == "action" else "folder",
                          target["resource_id"], placement.get("action_parameter"))
            refs.append(dict(placement=placement["id"], plugin=target["plugin_id"], scope=scope.wire()))
    references(refs, layout)
    return layout, refs


def references(rows, layout):
    if not isinstance(rows, list) or len(rows) > MAX_SCOPES * 4:
        raise PeerError("REFERENCE_CAPACITY")
    entries = {e["id"] for f in layout["folders"] for n in f["nodes"]
               for p in n["pages"] for e in p["entries"] if e["kind"] == "unavailable"
               and e["reason"] == "EXTERNAL_REFERENCE_OFFLINE"}
    refs = {}
    for row in rows:
        shape(row, "placement", "plugin", "scope")
        p, plugin = row["placement"], row["plugin"]
        if (not resource_id(p) or p not in entries or p in refs or not resource_id(plugin)
                or plugin == layout["plugin_id"]):
            raise PeerError("INVALID_REFERENCE")
        refs[p] = plugin, Scope.parse(row["scope"])
    if len(set(refs.values())) > MAX_SCOPES:
        raise PeerError("REFERENCE_CAPACITY")
    return refs


def _namespaced(prefix, *parts):
    return prefix + "." + hashlib.sha256("\0".join(parts).encode()).hexdigest()


def offered_nodes(layout):
    nodes = {}
    for folder in layout["folders"]:
        for node in folder["nodes"]:
            old = nodes.setdefault(node["id"], node)
            if old != node:
                raise PeerError("AMBIGUOUS_FOLDER_EXPORT")
    return nodes


def node_view(node, plugin, external):
    # An exported node includes ordered placements and reference targets only.
    pages = []
    for page in node["pages"]:
        entries = []
        for e in page["entries"]:
            ref = external.get(e["id"])
            if e["kind"] == "action":
                ref = plugin, Scope("action", e["action_id"], e.get("action_parameter"))
            elif e["kind"] in ("folder", "link"):
                ref = plugin, Scope("folder", e["target_id"])
            entries.append(dict(id=e["id"], label=e["label"], target=(
                dict(plugin=ref[0], scope=ref[1].wire()) if ref else None)))
        pages.append(dict(id=page["id"], entries=entries))
    return dict(available=True, label=node["label"], pages=pages)


def render(layout, direct, runtime, encoder_folders):
    """Derive both standing subscriptions and a bounded SDK presentation."""
    candidate = copy.deepcopy(layout)
    wanted = set(direct.values())
    for folder in candidate["folders"]:
        originals = {n["id"]: n for n in folder["nodes"]}
        imported = {}
        def entry(placement, label, ref, ancestry):
            offline = dict(id=placement, label=label, kind="unavailable", reason="EXTERNAL_REFERENCE_OFFLINE")
            if ref is None:
                return offline
            plugin, scope = ref
            if plugin == runtime.plugin:
                # A peer-supplied node cannot introduce executable local bindings.
                return offline
            if ref in ancestry:
                return dict(offline, reason="FOLDER_LINK_CYCLE")
            if len(wanted) >= MAX_SCOPES and ref not in wanted:
                return offline
            wanted.add(ref)
            data = runtime.remote(plugin, scope)
            if data is None:
                return offline
            instance, offer, view = data
            if view.get("available") is not True or not isinstance(view.get("label"), str):
                return offline
            label = view["label"][:1024]
            if scope.kind == "action":
                sdk_type = offer["sdk_type"]
                if sdk_type not in ("PluginDynamicCommand", "PluginMultistateDynamicCommand", "PluginDynamicAdjustment"):
                    return dict(offline, reason="FOLDER_REMOTE_ACTION_UNSUPPORTED")
                operations = offer["operations"]
                if not operations:
                    return dict(offline, label=label, reason="FOLDER_REMOTE_INVOKE_DENIED")
                if sdk_type != "PluginDynamicAdjustment" and operations != ["command"]:
                    return dict(offline, reason="FOLDER_REMOTE_ACTION_UNSUPPORTED")
                if sdk_type == "PluginDynamicAdjustment" and folder["id"] not in encoder_folders:
                    return dict(offline, label=label, reason="FOLDER_ENCODER_NAVIGATION_CONFLICT")
                value, state, image_hash = (view.get(k) for k in ("value", "state", "image_hash"))
                if (value is not None and (not isinstance(value, str) or len(value) > 1024)
                        or state is not None and (type(state) is not int or not 0 <= state < 2**31)
                        or image_hash is not None and (not isinstance(image_hash, str) or not re.fullmatch("[0-9a-f]{64}", image_hash))):
                    return dict(offline, reason="FOLDER_REMOTE_VIEW_INVALID")
                return dict(id=placement, kind="peer_action", label=label, peer=plugin, instance=instance,
                            action_id=scope.resource, action_parameter=scope.parameter, sdk_type=sdk_type,
                            operations=operations, value=value, state=state, image_hash=image_hash)
            target = _namespaced("peer.node", plugin, scope.resource)
            if target in originals or len(ancestry) >= 16:
                return offline
            if target not in imported:
                pages = view.get("pages")
                if not isinstance(pages, list) or not 0 < len(pages) <= MAX_SCOPES:
                    return offline
                node = dict(id=target, label=label or scope.resource, pages=[])
                try:
                    parsed = _remote_pages(pages)
                except (PeerError, TypeError):
                    return offline
                imported[target] = node
                for page_id, rows in parsed:
                    page_key = _namespaced("peer.page", target, page_id)
                    node["pages"].append(dict(id=page_key, entries=[
                        entry(_namespaced("peer.placement", page_key, pid), text, child, ancestry | {ref})
                        for pid, text, child in rows]))
            return dict(id=placement, label=label, kind="link", target_id=target)

        for node in originals.values():
            for page in node["pages"]:
                page["entries"] = [entry(e["id"], e["label"], direct[e["id"]], set())
                                   if e["id"] in direct else e for e in page["entries"]]
        folder["nodes"].extend(imported.values())
    return candidate, wanted


def _remote_pages(pages):
    parsed, ids = [], set()
    count = 0
    for page in pages:
        shape(page, "id", "entries")
        pid = page["id"]
        if not resource_id(pid) or pid in ids or not isinstance(page["entries"], list):
            raise PeerError("INVALID_REMOTE_PAGE")
        ids.add(pid)
        count += len(page["entries"])
        if count > MAX_SCOPES:
            raise PeerError("REMOTE_NODE_CAPACITY")
        rows, placements = [], set()
        for row in page["entries"]:
            shape(row, "id", "label", "target")
            key, label, target = row["id"], row["label"], row["target"]
            if not resource_id(key) or key in placements or not isinstance(label, str):
                raise PeerError("INVALID_REMOTE_PLACEMENT")
            placements.add(key)
            child = None
            if target is not None:
                shape(target, "plugin", "scope")
                if not resource_id(target["plugin"]):
                    raise PeerError("INVALID_REMOTE_PLUGIN")
                child = target["plugin"], Scope.parse(target["scope"])
            rows.append((key, label[:1024], child))
        parsed.append((pid, rows))
    return parsed
