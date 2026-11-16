"""Optional trusted Python publisher over the existing authenticated Host transport.

Only presentation/navigation snapshots change. Native definitions, handlers and
states remain owned by PluginHost/SDK. No new network endpoint is introduced.
"""
from __future__ import annotations

import copy
from pathlib import Path

from core.io import load_raw
from runtime.host import PluginHost
from runtime.wire import HostError, json_bytes, MAX_REQUEST
from .runtime_projection import initial_layout, validate_layout


class FolderRuntimeHost(PluginHost):
    _allow_peer_layout = False
    def __init__(self, project, settings, *, folder_runtime=None, **kwargs):
        source = load_raw(project) if isinstance(project, (str, Path)) else copy.deepcopy(project)
        layout = initial_layout(source)[0] if folder_runtime is None else validate_layout(folder_runtime, source)
        super().__init__(source, settings, **kwargs)
        self._folder_source = source
        self._folder_layout = layout
        self._base_views = copy.deepcopy(self._raw["views"])
        self._install_placements(layout)

    def _install_placements(self, layout):
        # Derived authorization list only, never persisted into native JSON.
        base = {p["id"]: p for v in self._base_views for p in v["placements"]}
        placements = {}
        for folder in layout["folders"]:
            for node in folder["nodes"]:
                for page in node["pages"]:
                    for entry in page["entries"]:
                        if entry["kind"] == "action":
                            p = dict(id=entry["id"], component=entry["action_id"], position=len(placements))
                            old = base.get(p["id"])
                            if old and old["component"] != p["component"]:
                                raise HostError("FOLDER_PLACEMENT_COLLISION", "placement refers to a different native action")
                            placements[p["id"]] = p
        self._raw["views"] = [dict(id="view.folder-runtime", type="folder", placements=list(placements.values()))]

    def snapshot(self):
        with self._lock:
            result = super().snapshot()
            result["folder_runtime"] = copy.deepcopy(self._folder_layout)
            return result

    def replace_folder_layout(self, proposed):
        candidate = validate_layout(proposed, self._folder_source, allow_peers=self._allow_peer_layout)
        event = dict(component_id="host", port="folder.layout", report=candidate)
        json_bytes(event, limit=MAX_REQUEST)
        with self._lock:
            if candidate["revision"] == self._folder_layout["revision"] and candidate == self._folder_layout:
                return False
            if candidate["revision"] <= self._folder_layout["revision"]:
                raise HostError("FOLDER_REVISION", "layout revision must increase")
            self._install_placements(candidate)
            self._folder_layout = candidate
            self._append("event", event)
            return True

    def _command(self, message):
        # The authenticated caller must still refer to a currently authorized binding.
        placement = message.get("placement_id")
        if placement is not None:
            with self._lock:
                entries = [e for f in self._folder_layout["folders"] for n in f["nodes"]
                           for p in n["pages"] for e in p["entries"] if e["id"] == placement]
                if entries:
                    e = entries[0]
                    if e["kind"] != "action" or e["action_id"] != message.get("component_id") or e.get("action_parameter") != message.get("action_parameter"):
                        raise HostError("FOLDER_BINDING", "placement/action/parameter mismatch")
                return super()._command(message)
        return super()._command(message)
