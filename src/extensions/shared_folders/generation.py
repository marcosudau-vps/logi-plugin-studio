"""Generation-only helpers for the independent static SDK route and shared bundle."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from adapters.logitech.naming import csharp_literal, identifier
from runtime.wire import json_bytes

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1]


def template(name, namespace):
    return (HERE / "templates" / (name + ".cs.in")).read_text(encoding="utf-8-sig").replace("$NAMESPACE$", namespace)


def static_folder(plan, folder, actions, specs):
    items = []
    for entry in sorted(folder.entries, key=lambda e: e.position):
        action = actions[entry.action]
        if action.sdk_type == "ActionEditorCommand":
            continue
        adjustment = action.sdk_type == "PluginDynamicAdjustment"
        args = [csharp_literal(entry.id), csharp_literal(f"{plan.namespace}.{specs[action.id].type_name}"),
                "null" if entry.action_parameter is None else csharp_literal(entry.action_parameter), str(adjustment).lower(), str(action.has_reset).lower()]
        items.append("new Placement(" + ", ".join(args) + ")")
    navigation = "PluginDynamicFolderNavigation." + folder.navigation
    if folder.device_navigation:
        cases = " ".join(f"DeviceType.{device} => PluginDynamicFolderNavigation.{area},"
                         for device, area in sorted(folder.device_navigation.items()))
        navigation = f"deviceType switch {{ {cases} _ => {navigation} }}"
    name = identifier("Folder", folder.id)
    return f"""namespace {plan.namespace}
{{
    using System.Collections.Generic;
    using Loupedeck;
    public class {name} : StaticSdkFolder
    {{
        private static readonly Placement[] Items = new Placement[] {{ {', '.join(items)} }};
        protected override IReadOnlyList<Placement> Entries => Items;
        public {name}() {{ DisplayName = {csharp_literal(folder.display_name)}; GroupName = {csharp_literal(plan.plugin_display_name)}; }}
        public override PluginDynamicFolderNavigation GetNavigationArea(DeviceType deviceType) => {navigation};
    }}
}}
"""


def python_bundle(project, layout, refs, manifest_dir, handler):
    """Deterministic zipapp embedded as an assembly resource (and thus in packages)."""
    files = {"__main__.py": (HERE / "embedded_host.py").read_bytes(),
             "shared/project.json": json_bytes(project, limit=16 * 1024 * 1024),
             "shared/layout.json": json_bytes(layout),
             "shared/references.json": json_bytes(refs),
             "adapters/__init__.py": b"",
             "adapters/logitech/__init__.py": b"",
             "adapters/logitech/native.py": (SRC / "adapters/logitech/native.py").read_bytes(),
             "extensions/__init__.py": b""}
    for package in ("core", "runtime"):
        for file in (SRC / package).glob("*.py"):
            files[f"{package}/{file.name}"] = file.read_bytes()
    for module in ("__init__", "host", "runtime_projection", "peer_wire", "peer_runtime", "peer_projection", "peer_host",
                   "secret_store"):
        files[f"extensions/shared_folders/{module}.py"] = (HERE / f"{module}.py").read_bytes()
    manifests = sorted(Path(manifest_dir).glob("*.json"))
    files["shared/manifests.json"] = json.dumps([m.name for m in manifests]).encode("utf-8")
    for manifest in manifests:
        files["shared/manifests/" + manifest.name] = manifest.read_bytes()
    if handler is not None:
        files["shared_plugin_handler.py"] = handler
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(path), data, compress_type=zipfile.ZIP_DEFLATED)
    return target.getvalue()
