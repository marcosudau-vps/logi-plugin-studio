"""Product generation builds on, but does not replace, the approved build-only cut."""
from __future__ import annotations

import base64
import copy
import json
import re
import secrets
import socket
import struct
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from core.io import load_raw
from core.ids import is_valid_id
from core.registry import load_manifests
from runtime.plan import compile_plan
from runtime.state_store import StateStore
from runtime.wire import ConnectionSettings, HostError, json_bytes, project_digest

from .codegen import (DEFAULT_SDK_DLL, MANIFEST_FILE, GenerationPlan,
                      check_output_dir, plan_generation, write_tree)
from .errors import GenerationError
from .gate import DEFAULT_MANIFEST_DIR, select_project
from .naming import csharp_literal, identifier
from .native import (NativeAction, NativeProject, NativeProjectError, project_view,
                     runtime_projection)

TEMPLATES = Path(__file__).parent / "templates"
SHARED_FOLDER_TEMPLATE = Path(__file__).resolve().parents[2] / "extensions" / "shared_folders" / "templates" / "NativeFolders.cs.in"
PRODUCT_VERSION = "0.2.0"


def _project_file(project_dir: Path, relative: str, *, limit: int = 1_048_576) -> tuple[Path, bytes]:
    if not isinstance(relative, str) or ":" in relative or "\\" in relative or Path(relative).is_absolute():
        raise GenerationError("Resource path must be a project-relative portable path")
    path = (project_dir / relative).resolve()
    if not path.is_relative_to(project_dir.resolve()) or ".." in Path(relative).parts:
        raise GenerationError("Resource path escapes the project directory")
    try:
        if path.stat().st_size > limit:
            raise GenerationError(f"Resource exceeds the {limit} byte limit")
        return path, path.read_bytes()
    except OSError as exc:
        raise GenerationError(f"Resource {relative!r} cannot be read: {exc}") from exc


def read_native_resource(project_dir: Path, relative: str, kind: str) -> bytes:
    """Validate an SDK-native package resource without flattening it."""
    path, content = _project_file(project_dir, relative)
    suffix = path.suffix.lower()
    if kind == "icon" and suffix not in (".png", ".svg"):
        raise GenerationError("Action icons must be PNG or SVG")
    if kind == "symbol" and suffix != ".svg":
        raise GenerationError("Action symbols must be SVG")
    if kind == "template" and suffix != ".ict":
        raise GenerationError("Icon templates must use .ict")
    if suffix == ".png":
        return read_asset(project_dir, {"id": relative, "path": relative})
    if suffix == ".svg":
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise GenerationError("SVG declarations and entities are not accepted")
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise GenerationError(f"Invalid SVG resource: {exc}") from exc
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            raise GenerationError("SVG resource root must be <svg>")
    elif suffix == ".ict":
        try:
            template = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GenerationError(f"Invalid UTF-8/JSON icon template: {exc}") from exc
        if not isinstance(template, dict) or "items" in template and not isinstance(template["items"], list):
            raise GenerationError("Icon template must be a JSON object with an optional items array")
    return content


def read_asset(project_dir: Path, asset: dict) -> bytes:
    relative = asset["path"]
    if not isinstance(relative, str) or ":" in relative or "\\" in relative or Path(relative).is_absolute():
        raise GenerationError("Asset path must be a project-relative portable path")
    path = (project_dir / relative).resolve()
    if not path.is_relative_to(project_dir.resolve()) or ".." in Path(relative).parts:
        raise GenerationError("Asset path escapes the project directory")
    try:
        if path.stat().st_size > 1_048_576:
            raise GenerationError("Asset exceeds the 1 MiB image limit")
        content = path.read_bytes()
    except OSError as exc:
        raise GenerationError(f"Asset {asset['id']!r} cannot be read: {exc}") from exc
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        raise GenerationError("Product images must be exported as PNG")
    offset = 8
    ended = False
    has_data = False
    compressed = bytearray()
    channels = 0
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset:offset + 4])[0]
        kind = content[offset + 4:offset + 8]
        if (not re.fullmatch(b"[a-zA-Z]{4}", kind) or
                (kind[0] < 97 and kind not in (b"IHDR", b"PLTE", b"IDAT", b"IEND")) or
                (kind == b"IHDR" and offset != 8)):
            raise GenerationError("PNG contains invalid or unsupported critical chunks")
        end = offset + 12 + length
        if end > len(content):
            raise GenerationError("Truncated PNG asset")
        payload = content[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", content[offset + 8 + length:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise GenerationError("PNG checksum mismatch")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise GenerationError("Invalid PNG header")
            width, height = struct.unpack(">II", payload[:8])
            if not 1 <= width <= 1024 or not 1 <= height <= 1024:
                raise GenerationError("PNG dimensions exceed the 1024px decode limit")
            if payload[8] != 8 or payload[9] not in (2, 6) or payload[10:13] != b"\0\0\0":
                raise GenerationError("Export images as non-interlaced 8-bit RGB/RGBA PNG")
            channels = 3 if payload[9] == 2 else 4
        if kind == b"IDAT":
            has_data = True
            compressed.extend(payload)
        if kind == b"IEND":
            ended = True
            if length != 0 or end != len(content):
                raise GenerationError("Invalid PNG end marker")
            break
        offset = end
    if not ended or not has_data:
        raise GenerationError("Incomplete PNG asset")
    expected_size = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(bytes(compressed), expected_size + 1)
    except zlib.error as exc:
        raise GenerationError("PNG raster decompression failed") from exc
    if not decoder.eof or decoder.unused_data or len(pixels) != expected_size:
        raise GenerationError("PNG raster size or compression stream is invalid")
    stride = 1 + width * channels
    if any(pixels[row * stride] > 4 for row in range(height)):
        raise GenerationError("PNG raster contains an invalid scanline filter")
    return content


def default_plugin_icon(plugin_id: str, size: int = 256) -> bytes:
    """Deterministic Studio-generated plugin icon (required metadata/Icon256x256.png).

    A coloured rounded tile derived from the plugin ID; no third-party artwork.
    """
    import hashlib
    digest = hashlib.sha256(plugin_id.encode("utf-8")).digest()
    r, g, b = 40 + digest[0] % 160, 40 + digest[1] % 160, 40 + digest[2] % 160
    radius, inner = size // 8, size // 4
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx = max(radius - x, 0, x - (size - 1 - radius))
            dy = max(radius - y, 0, y - (size - 1 - radius))
            if dx * dx + dy * dy > radius * radius:
                row += b"\0\0\0\0"
            elif inner <= x < size - inner and inner <= y < size - inner and (x // 16 + y // 16) % 2 == 0:
                row += bytes((255, 255, 255, 255))
            else:
                row += bytes((r, g, b, 255))
        rows.append(b"\0" + bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def validate_product(raw: dict, project_dir: Path) -> dict[str, str]:
    from library.presentation import presentation_options
    assets: dict[str, str] = {}
    for component in raw["components"]:
        if component["type"] not in ("core.command_action", "core.host_handler"):
            raise GenerationError(f"No product implementation for component type {component['type']!r}")
    for state in raw["states"]:
        if state["scope"] == "session":
            raise GenerationError("Session-scoped business states are unsupported")
        if state["persistence"] not in ("none", "external", "runtime_local"):
            raise GenerationError("Unsupported persistence policy")
        schema = state["value_schema"]
        if "type" in schema and not isinstance(schema["type"], str):
            raise GenerationError("Product wire state schemas currently require a single JSON type")
    for asset in raw["assets"]:
        assets[asset["id"]] = base64.b64encode(read_asset(project_dir, asset)).decode("ascii")
    selector_targets: set[str] = set()
    for binding in raw["bindings"]:
        if binding["kind"] != "state":
            continue
        if binding["source"]["owner_kind"] != "state" or binding["target"]["owner_kind"] != "presentation":
            raise GenerationError("Product state bindings currently support state -> presentation only")
        target = binding["target"]["owner_id"]
        if target in selector_targets:
            raise GenerationError(f"Ambiguous selector writers for presentation {target!r}")
        selector_targets.add(target)
    for presentation in raw["presentations"]:
        for key, variant in presentation["variants"].items():
            if set(variant) - {"text", "background", "foreground", "image", "image_fit", "font_size"}:
                raise GenerationError(f"Unsupported presentation fields in {presentation['id']}/{key}")
            try:
                presentation_options(variant)
            except ValueError as exc:
                raise GenerationError(str(exc)) from exc
            if "text" in variant and (not isinstance(variant["text"], str) or len(variant["text"]) > 256):
                raise GenerationError("Presentation text must be a string of at most 256 characters")
            for field in ("background", "foreground"):
                if field in variant and (not isinstance(variant[field], str) or
                                         not re.fullmatch(r"#[0-9a-fA-F]{6}", variant[field])):
                    raise GenerationError(f"Presentation {field} must be #RRGGBB")
            if "image" in variant and (not isinstance(variant["image"], str) or variant["image"] not in assets):
                raise GenerationError("Presentation image references an unknown asset")
    action_ids = {c["id"] for c in raw["components"] if c["type"] == "core.command_action"}
    for view in raw["views"]:
        if view["type"] not in ("folder", "grid"):
            raise GenerationError(f"Unsupported view type {view['type']!r}; use folder or grid")
        for placement in view["placements"]:
            if placement["component"] not in action_ids:
                raise GenerationError("Only command actions may be projected onto a keypad placement")
    return assets


def _plugin(plan: GenerationPlan, *, native_folders: bool = False, shared: bool = False,
            self_host: bool = False) -> str:
    # SDK-native plugins opt into the optional folder extension before starting
    # transport; legacy products keep the original, extension-free startup.
    load = ("public override void Load() { FolderRuntimeHub.Initialize(); Bridge.StartFromPluginAssembly(this.AssemblyFilePath); }"
            if native_folders else
            "public override void Load() => Bridge.StartFromPluginAssembly(this.AssemblyFilePath);")
    unload = "Bridge.Stop();"
    if self_host and not shared:
        # The plugin starts its own embedded host with its plugin-local runtime.
        init = "FolderRuntimeHub.Initialize(); " if native_folders else ""
        load = (f"public override void Load() {{ {init}HostChild.Start(this.AssemblyFilePath, \"native-host.pyz\"); "
                "Bridge.StartFromPluginAssembly(this.AssemblyFilePath); }")
        unload = "Bridge.Stop(); HostChild.Stop();"
    if shared:
        load = ("public override void Load() { FolderRuntimeHub.Initialize(); SharedSdk.Start(this); "
                "SharedChild.Start(this.AssemblyFilePath); Bridge.StartFromPluginAssembly(this.AssemblyFilePath); }")
        unload = "SharedSdk.Stop(); Bridge.Stop(); SharedChild.Stop();"
    return f"""namespace {plan.namespace}
{{
    using System;
    using Loupedeck;
    public class {plan.plugin_class} : Plugin
    {{
        public override Boolean HasNoApplication => true;
        public override Boolean UsesApplicationApiOnly => true;
        {load}
        public override void Unload() {{ {unload} }}
    }}
}}
"""


def _action(plan: GenerationPlan, action: Any) -> str:
    return f"""namespace {plan.namespace}
{{
    using System;
    using Loupedeck;
    public class {action.type_name} : PluginDynamicCommand
    {{
        public const String ComponentId = {csharp_literal(action.component_id)};
        public {action.type_name}() : base({csharp_literal(action.display_name)}, "Python command", {csharp_literal(plan.plugin_display_name)}) {{ }}
        protected override Boolean OnLoad() {{ Bridge.Changed += Refresh; return true; }}
        protected override Boolean OnUnload() {{ Bridge.Changed -= Refresh; return true; }}
        private void Refresh() => this.ActionImageChanged();
        protected override void RunCommand(String actionParameter)
            => Bridge.Dispatch(ComponentId, actionParameter: actionParameter);
        protected override String GetCommandDisplayName(String actionParameter, PluginImageSize imageSize)
            => Visuals.Text(ComponentId, Visuals.DefaultPlacement(ComponentId));
        protected override BitmapImage GetCommandImage(String actionParameter, PluginImageSize imageSize)
            => Visuals.Render(ComponentId, Visuals.DefaultPlacement(ComponentId), imageSize);
    }}
}}
"""


def _parameter_lines(action: NativeAction, indent: str = "            ") -> str:
    lines: list[str] = []
    for parameter in action.parameters:
        args = [csharp_literal(parameter.name), csharp_literal(parameter.display_name),
                csharp_literal(parameter.group_name)]
        if parameter.super_group_name is not None:
            args.append(csharp_literal(parameter.super_group_name))
        lines.append(indent + "this.AddParameter(" + ", ".join(args) + ");")
    return "\n".join(lines)


def _native_command(plan: GenerationPlan, spec: Any, action: NativeAction) -> str:
    parameters = _parameter_lines(action)
    return f"""namespace {plan.namespace}
{{
    using System;
    using Loupedeck;
    public class {spec.type_name} : PluginDynamicCommand
    {{
        public const String ComponentId = {csharp_literal(action.id)};
        public {spec.type_name}() : base({csharp_literal(action.display_name)}, {csharp_literal(action.description)}, {csharp_literal(action.group_name)})
        {{
{parameters}
        }}
        protected override Boolean OnLoad() {{ Bridge.Changed += Refresh; return true; }}
        protected override Boolean OnUnload() {{ Bridge.Changed -= Refresh; return true; }}
        private void Refresh() => this.ActionImageChanged();
        protected override void RunCommand(String actionParameter)
            => Bridge.Dispatch(ComponentId, actionParameter: actionParameter);
    }}
}}
"""


def _native_multistate(plan: GenerationPlan, spec: Any, action: NativeAction,
                       state_resources: dict[int, str]) -> str:
    parameters = _parameter_lines(action)
    states = "\n".join(
        "            this.AddState(" + ", ".join(map(csharp_literal, (state.name, state.display_name, state.description))) + ");"
        for state in action.states
    )
    mutation = {
        "none": "",
        "increment": "            this.IncrementCurrentState(actionParameter);\n",
        "decrement": "            this.DecrementCurrentState(actionParameter);\n",
        "toggle": "            this.ToggleCurrentState(actionParameter);\n",
    }[action.state_change]
    names = "\n".join(
        f"                {state.index} => {csharp_literal(state.display_name)},"
        for state in action.states
    )
    image_cases = "\n".join(
        f"                {index} => BitmapImage.FromResource(this.Plugin.Assembly, {csharp_literal(logical)}),"
        for index, logical in sorted(state_resources.items())
    )
    image_override = ""
    if image_cases:
        image_override = f"""
        protected override BitmapImage GetCommandImage(String actionParameter, Int32 stateIndex, PluginImageSize imageSize)
            => stateIndex switch
            {{
{image_cases}
                _ => base.GetCommandImage(actionParameter, stateIndex, imageSize),
            }};
"""
    return f"""namespace {plan.namespace}
{{
    using System;
    using Loupedeck;
    public class {spec.type_name} : PluginMultistateDynamicCommand
    {{
        public const String ComponentId = {csharp_literal(action.id)};
        public {spec.type_name}() : base({csharp_literal(action.display_name)}, {csharp_literal(action.description)}, {csharp_literal(action.group_name)})
        {{
{parameters}
{states}
        }}
        protected override Boolean OnLoad() {{ Bridge.Changed += Refresh; return true; }}
        protected override Boolean OnUnload() {{ Bridge.Changed -= Refresh; return true; }}
        private void Refresh() => this.ActionImageChanged();
        protected override void RunCommand(String actionParameter)
        {{
{mutation}            Bridge.Dispatch(ComponentId, actionParameter: actionParameter);
            this.ActionImageChanged(actionParameter);
        }}
        protected override String GetCommandDisplayName(String actionParameter, Int32 stateIndex, PluginImageSize imageSize)
            => stateIndex switch
            {{
{names}
                _ => base.GetCommandDisplayName(actionParameter, stateIndex, imageSize),
            }};
{image_override}    }}
}}
"""


def _nullable_number(value: float | None) -> str:
    if value is None:
        return "null"
    return format(value, ".17g") + "d"


def _native_adjustment(plan: GenerationPlan, spec: Any, action: NativeAction) -> str:
    parameters = _parameter_lines(action)
    return f"""namespace {plan.namespace}
{{
    using System;
    using System.Collections.Generic;
    using Loupedeck;
    public class {spec.type_name} : PluginDynamicAdjustment
    {{
        public const String ComponentId = {csharp_literal(action.id)};
        private readonly Object _gate = new Object();
        private readonly Dictionary<String, Double> _values = new Dictionary<String, Double>();
        public {spec.type_name}() : base({csharp_literal(action.display_name)}, {csharp_literal(action.description)}, {csharp_literal(action.group_name)}, {str(action.has_reset).lower()})
        {{
            this.AdjustmentMinValue = {_nullable_number(action.adjustment_min)};
            this.AdjustmentMaxValue = {_nullable_number(action.adjustment_max)};
            this.AdjustmentDefaultValue = {_nullable_number(action.adjustment_default)};
            this.AdjustmentFormatString = {csharp_literal(action.adjustment_format)};
{parameters}
        }}
        protected override void ApplyAdjustment(String actionParameter, Int32 diff)
        {{
            String key = actionParameter ?? String.Empty;
            Double value;
            lock (this._gate)
            {{
                Double current = this._values.TryGetValue(key, out var stored) ? stored : (this.AdjustmentDefaultValue ?? 0d);
                value = this.FixAdjustmentValue(actionParameter, current + diff);
                this._values[key] = value;
            }}
            this.AdjustmentValueChanged(actionParameter, value);
            Bridge.Dispatch(ComponentId, actionParameter: actionParameter, operation: "adjustment", adjustmentDiff: diff);
        }}
        protected override Nullable<Double> GetAdjustmentDoubleValue(String actionParameter)
        {{
            lock (this._gate)
                return this._values.TryGetValue(actionParameter ?? String.Empty, out var value)
                    ? value : this.AdjustmentDefaultValue;
        }}
        protected override void RunCommand(String actionParameter)
        {{
            if (!{str(action.has_reset).lower()}) return;
            Double value = this.FixAdjustmentValue(actionParameter, this.AdjustmentDefaultValue ?? 0d);
            lock (this._gate) this._values[actionParameter ?? String.Empty] = value;
            this.AdjustmentValueChanged(actionParameter, value);
            Bridge.Dispatch(ComponentId, actionParameter: actionParameter);
        }}
    }}
}}
"""


def _native_action_editor(plan: GenerationPlan, spec: Any, action: NativeAction) -> str:
    """Create actual native SDK editor controls, never a custom action editor."""
    controls: list[str] = []
    values: list[str] = []
    for control in action.editor_controls:
        description = "null" if control.description is None else csharp_literal(control.description)
        name, label = csharp_literal(control.name), csharp_literal(control.label)
        if control.type == "checkbox":
            suffix = "" if control.default is None else f".SetDefaultValue({str(control.default).lower()})"
            controls.append(
                f"            this.ActionEditor.AddControlEx(new ActionEditorCheckbox({name}, {label}, {description}){suffix});")
            values.append(f"            values[{name}] = actionParameters.GetBoolean({name});")
        elif control.type in ("slider", "numeric_up_down"):
            class_name = "ActionEditorSlider" if control.type == "slider" else "ActionEditorNumericUpDown"
            args = ", ".join(format(x, ".17g") for x in (
                control.minimum, control.maximum, control.default, control.step))
            chain = f".SetValues({args})"
            if control.format_string is not None:
                chain += f".SetFormatString({csharp_literal(control.format_string)})"
            controls.append(
                f"            this.ActionEditor.AddControlEx(new {class_name}({name}, {label}, {description}){chain});")
            # ActionEditorActionParameters exposes GetString/GetInt32, not GetDouble.
            # Preserve SDK's original representation instead of truncating a decimal to int.
            values.append(f"            values[{name}] = actionParameters.GetString({name});")
        else:
            class_names = {
                "textbox": "ActionEditorTextbox",
                "textarea": "ActionEditorTextArea",
                "file_selector": "ActionEditorFileSelector",
                "directory_selector": "ActionEditorDirectorySelector",
            }
            class_name = class_names[control.type]
            chain = ""
            if control.dialog_title is not None:
                chain += f".SetDialogTitle({csharp_literal(control.dialog_title)})"
            if control.initial_directory is not None:
                chain += f".SetInitialDirectory({csharp_literal(control.initial_directory)})"
            for pattern, display in control.filters:
                chain += f".AddFilter({csharp_literal(pattern)}, {csharp_literal(display)})"
            controls.append(
                f"            this.ActionEditor.AddControlEx(new {class_name}({name}, {label}, {description}){chain});")
            values.append(f"            values[{name}] = actionParameters.GetString({name});")
    return f"""namespace {plan.namespace}
{{
    using System;
    using System.Collections.Generic;
    using Loupedeck;
    public class {spec.type_name} : ActionEditorCommand
    {{
        public const String ComponentId = {csharp_literal(action.id)};
        public {spec.type_name}()
        {{
            this.Name = {csharp_literal(spec.type_name)};
            this.DisplayName = {csharp_literal(action.display_name)};
            this.Description = {csharp_literal(action.description)};
            this.GroupName = {csharp_literal(action.group_name)};
{chr(10).join(controls)}
        }}
        protected override Boolean RunCommand(ActionEditorActionParameters actionParameters)
        {{
            var values = new Dictionary<String, Object>();
{chr(10).join(values)}
            return Bridge.Dispatch(ComponentId, operation: "action_editor", editorValues: values);
        }}
    }}
}}
"""


def _folder(plan: GenerationPlan, view: dict, *, navigation: str = "ButtonArea",
            display_name: str | None = None,
            device_navigation: dict[str, str] | None = None) -> str:
    placements = sorted(view["placements"], key=lambda p: p["position"])
    entries = ", ".join(csharp_literal(p["id"]) for p in placements)
    name = identifier("Folder", view["id"])
    device_navigation = device_navigation or {}
    navigation_expression = f"PluginDynamicFolderNavigation.{navigation}"
    if device_navigation:
        cases = "\n".join(
            f"                DeviceType.{device} => PluginDynamicFolderNavigation.{area},"
            for device, area in sorted(device_navigation.items())
        )
        navigation_expression = f"""deviceType switch
            {{
{cases}
                _ => PluginDynamicFolderNavigation.{navigation},
            }}"""
    return f"""namespace {plan.namespace}
{{
    using System;
    using System.Collections.Generic;
    using System.Linq;
    using Loupedeck;
    public class {name} : PluginDynamicFolder
    {{
        private static readonly String[] Placements = new String[] {{ {entries} }};
        public {name}() {{ this.DisplayName = {csharp_literal(display_name or view["id"])}; this.GroupName = {csharp_literal(plan.plugin_display_name)}; }}
        public override Boolean Load() {{ Bridge.Changed += Refresh; return true; }}
        public override Boolean Unload() {{ Bridge.Changed -= Refresh; return true; }}
        public override PluginDynamicFolderNavigation GetNavigationArea(DeviceType deviceType)
            => {navigation_expression};
        public override IEnumerable<String> GetButtonPressActionNames(DeviceType deviceType)
            => Placements.Select(p => this.CreateCommandName(p)).ToArray();
        public override String GetCommandDisplayName(String parameter, PluginImageSize size)
        {{
            if (!Placements.Contains(parameter)) return "UNKNOWN PLACEMENT";
            var placement = Visuals.Placement(parameter);
            return Visuals.Text(placement.GetProperty("component").GetString(), parameter);
        }}
        public override BitmapImage GetCommandImage(String parameter, PluginImageSize size)
        {{
            if (!Placements.Contains(parameter)) return null;
            var placement = Visuals.Placement(parameter);
            return Visuals.Render(placement.GetProperty("component").GetString(), parameter, size);
        }}
        public override void RunCommand(String parameter)
        {{
            if (!Placements.Contains(parameter)) {{ Bridge.Log("PLACEMENT_REJECTED"); return; }}
            Bridge.Dispatch(Visuals.Placement(parameter).GetProperty("component").GetString(), parameter);
        }}
        private void Refresh()
        {{
            foreach (var placement in Placements) this.CommandImageChanged(placement);
        }}
    }}
}}
"""


def generate_product(project_path: str | Path, *, output_dir: str | Path,
                     assembly_name: str, sdk_dll: str | Path = DEFAULT_SDK_DLL,
                     manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
                     raw_project: dict | None = None,
                     folder_runtime: dict | None = None,
                     folder_mode: str = "compatible",
                     shared_references: list[dict] | None = None,
                     shared_handler: str | None = None,
                     embed_host: bool = False) -> GenerationPlan:
    """Generate the SDK project. ``embed_host`` (used by the Studio) makes a
    native/compatible plugin start its own embedded Python host; Shared plugins
    always do. ``shared_handler`` is then the trusted handler of that host."""
    path = Path(project_path).resolve()
    source_raw = load_raw(path) if raw_project is None else copy.deepcopy(raw_project)
    try:
        native = project_view(source_raw)
        raw = runtime_projection(source_raw)
    except NativeProjectError as exc:
        raise GenerationError(str(exc)) from exc
    registry, registry_issues = load_manifests(manifest_dir)
    selection = select_project(raw, registry, registry_issues)
    connection_plan, issues = compile_plan(raw, registry)
    if connection_plan is None:
        raise GenerationError("; ".join(f"{d.code}: {d.message}" for d in issues))
    store, issues = StateStore.create(raw, registry)
    if store is None:
        raise GenerationError("; ".join(f"{d.code}: {d.message}" for d in issues))
    assets = validate_product(raw, path.parent)
    plan = plan_generation(selection, plugin_id=native.plugin_id, assembly_name=assembly_name,
                           sdk_dll=sdk_dll, plugin_version=PRODUCT_VERSION)
    files = dict(plan.files)
    if folder_mode not in ("compatible", "native", "shared"):
        raise GenerationError("Unknown folder_mode")
    if native.legacy_raw is not None and folder_mode != "compatible":
        raise GenerationError("Explicit folder modes require logitech-native-1")
    if folder_mode == "native" and folder_runtime is not None:
        raise GenerationError("Native folder mode uses SDK entries from the project")
    shared = folder_mode == "shared"
    self_host = shared or (embed_host and native.legacy_raw is None)
    if not shared and (shared_references is not None or (shared_handler is not None and not self_host)):
        raise GenerationError("Shared references and handlers require shared folder mode")
    optional_layout = native.legacy_raw is None and folder_mode != "native"
    folder_layout, folder_diagnostics = None, []
    if optional_layout:
        from extensions.shared_folders.runtime_projection import initial_layout, validate_layout
        folder_layout, folder_diagnostics = initial_layout(source_raw)
        if folder_runtime is not None:
            folder_layout = validate_layout(folder_runtime, source_raw)
        files["src/NativeFolders.cs"] = SHARED_FOLDER_TEMPLATE.read_text(encoding="utf-8").replace("$NAMESPACE$", plan.namespace)
    elif folder_runtime is not None:
        raise GenerationError("SDK folder runtime requires logitech-native-1; legacy files are not migrated implicitly")
    if folder_mode == "native":
        from extensions.shared_folders.generation import template
        files["src/StaticSdkFolder.cs"] = template("StaticSdkFolder", plan.namespace)
    if shared:
        from extensions.shared_folders.generation import python_bundle, template
        from extensions.shared_folders.peer_projection import references
        shared_references = [] if shared_references is None else shared_references
        references(shared_references, folder_layout)
        handler = _project_file(path.parent, shared_handler, limit=262144)[1] if shared_handler is not None else None
        files["shared-folder-host.pyz"] = python_bundle(source_raw, folder_layout, shared_references, manifest_dir, handler)
        files["src/NativeFolders.cs"] = "#define SHARED_FOLDER_PEER\n" + files["src/NativeFolders.cs"]
        files["src/SharedSdk.cs"] = template("SharedSdk", plan.namespace)
    files.pop("src/ActionDispatch.cs")
    files["src/Plugin.cs"] = _plugin(plan, native_folders=optional_layout, shared=shared, self_host=self_host)
    if self_host:
        files["src/HostChild.cs"] = (TEMPLATES / "HostChild.cs.in").read_text(encoding="utf-8").replace("$NAMESPACE$", plan.namespace)
    specs = {spec.component_id: spec for spec in plan.actions}
    native_actions = {action.id: action for action in native.actions}
    embedded: list[tuple[str, str]] = [("shared-folder-host.pyz", "shared-folder-host.pyz")] if shared else []
    if self_host and not shared:
        from .host_runtime import native_host_bundle
        handler = _project_file(path.parent, shared_handler, limit=262144)[1] if shared_handler is not None else None
        files["native-host.pyz"] = native_host_bundle(source_raw, folder_layout, folder_mode, manifest_dir, handler)
        embedded.append(("native-host.pyz", "native-host.pyz"))
    state_resources: dict[str, dict[int, str]] = {}
    if native.legacy_raw is None:
        for action in native.actions:
            spec = specs[action.id]
            full_name = f"{plan.namespace}.{spec.type_name}"
            for source, folder, kind in (
                (action.icon, "actionicons", "icon"),
                (action.icon_template, "icontemplates", "template"),
                (action.symbol, "actionsymbols", "symbol"),
            ):
                if source is not None:
                    suffix = Path(source).suffix.lower()
                    files[f"{folder}/{full_name}{suffix}"] = read_native_resource(path.parent, source, kind)
            for parameter, source in sorted(action.parameter_symbols.items()):
                if any(mark in parameter for mark in ("/", "\\", ":")):
                    raise GenerationError("Parameter symbol names cannot contain path separators or a drive marker")
                files[f"actionsymbols/{full_name}___{parameter}.svg"] = read_native_resource(
                    path.parent, source, "symbol")
            for state in action.states:
                if state.image is None:
                    continue
                suffix = Path(state.image).suffix.lower()
                relative = f"native_state_images/{spec.type_name}_{state.index}{suffix}"
                logical = f"native.state.{spec.type_name}.{state.index}{suffix}"
                files[relative] = read_native_resource(path.parent, state.image, "icon")
                embedded.append((relative, logical))
                state_resources.setdefault(action.id, {})[state.index] = logical
        # LogiPluginTool requires a plugin icon in metadata/.
        files["metadata/Icon256x256.png"] = default_plugin_icon(native.plugin_id)
        if native.default_icon_template is not None:
            files["metadata/DefaultIconTemplate.ict"] = read_native_resource(
                path.parent, native.default_icon_template, "template")
        used_license_names: set[str] = set()
        for source in native.licenses:
            name = Path(source).name
            if name.casefold() in used_license_names:
                raise GenerationError(f"Duplicate license file name {name!r}")
            used_license_names.add(name.casefold())
            files[f"licenses/{name}"] = _project_file(path.parent, source)[1]
    for spec in plan.actions:
        action = native_actions[spec.component_id]
        if action.legacy:
            files[spec.source_path] = _action(plan, spec)
        elif action.sdk_type == "PluginDynamicCommand":
            files[spec.source_path] = _native_command(plan, spec, action)
        elif action.sdk_type == "PluginMultistateDynamicCommand":
            files[spec.source_path] = _native_multistate(plan, spec, action, state_resources.get(action.id, {}))
        elif action.sdk_type == "PluginDynamicAdjustment":
            files[spec.source_path] = _native_adjustment(plan, spec, action)
        elif action.sdk_type == "ActionEditorCommand":
            files[spec.source_path] = _native_action_editor(plan, spec, action)
    folder_by_id = {folder.id: folder for folder in native.folders}
    for view in raw["views"]:
        folder = folder_by_id.get(view["id"])
        navigation = folder.navigation if folder is not None else "ButtonArea"
        display_name = folder.display_name if folder is not None else view["id"]
        if folder_mode == "native":
            from extensions.shared_folders.generation import static_folder
            files[f"src/folders/{identifier('Folder', view['id'])}.cs"] = static_folder(plan, folder, native_actions, specs)
        elif optional_layout:
            from extensions.shared_folders.runtime_projection import folder_source
            files[f"src/folders/{identifier('Folder', view['id'])}.cs"] = folder_source(plan, folder)
        else:
            files[f"src/folders/{identifier('Folder', view['id'])}.cs"] = _folder(
                plan, view, navigation=navigation, display_name=display_name,
                device_navigation=folder.device_navigation if folder is not None else None)
    for name in ("Bridge", "Visuals"):
        files[f"src/{name}.cs"] = (TEMPLATES / f"{name}.cs.in").read_text(encoding="utf-8").replace("$NAMESPACE$", plan.namespace)
    if native.legacy_raw is None:
        # Correlation is transient; all mutations still execute on the SDK-owned action.
        placement = "FolderCall.Placement" if optional_layout else "NativePlacement.Id"
        notify = "FolderCall.Notify()" if optional_layout else "NativePlacement.Notify()"
        dispatch = "SharedSdk.Dispatch" if shared else "Bridge.Dispatch"
        for spec in plan.actions:
            files[spec.source_path] = files[spec.source_path].replace(
                "Bridge.Dispatch(ComponentId, actionParameter:",
                f"{dispatch}(ComponentId, placement: {placement}, actionParameter:")
            files[spec.source_path] = files[spec.source_path].replace(
                "this.ActionImageChanged(actionParameter);", f"this.ActionImageChanged(actionParameter);\n            {notify};")
            files[spec.source_path] = files[spec.source_path].replace(
                "this.AdjustmentValueChanged(actionParameter, value);", f"this.AdjustmentValueChanged(actionParameter, value);\n            {notify};")
    initial = store.snapshot()["states"]
    for entry in initial.values():
        entry["epoch"] = ""
    # No runtime IDs, epochs, timestamps or secrets enter generated sources.
    folder_spec = f"""
        public const string FolderLayout = {csharp_literal(json.dumps(folder_layout or dict(version='sdk-folders-1', plugin_id=native.plugin_id, revision=0, folders=[]), separators=(',', ':')))};
        public const string NativeFolders = {csharp_literal(json.dumps([f.id for f in native.folders] if native.legacy_raw is None else []))};
        public const string NativeEncoderFolders = {csharp_literal(json.dumps([f.id for f in native.folders if f.navigation != 'EncoderArea' and 'EncoderArea' not in f.device_navigation.values()] if native.legacy_raw is None else []))};
        public const string NativeActions = {csharp_literal(json.dumps({a.id: dict(type=f'{plan.namespace}.{specs[a.id].type_name}', sdk_type=a.sdk_type, parameters=[p.name for p in a.parameters], has_reset=a.has_reset) for a in native.actions} if native.legacy_raw is None else {}))};
""" if optional_layout else ""
    files["src/Spec.cs"] = f"""namespace {plan.namespace}
{{
    internal static class Spec
    {{
        public const string PluginId = {csharp_literal(plan.plugin_id)};
        public const string ProjectHash = {csharp_literal(project_digest(source_raw))};
{folder_spec}        public const string Project = {csharp_literal(json_bytes(raw).decode())};
        public const string Assets = {csharp_literal(json_bytes(assets).decode())};
        public const string InitialStates = {csharp_literal(json_bytes(initial).decode())};
        public const string StateDefinitions = {csharp_literal(json_bytes({s['id']: s for s in raw['states']}).decode())};
    }}
}}
"""
    # No ancestor build customizations and no wildcard compilation of foreign C#.
    guarded = ("    <ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>\n"
               "    <ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>\n"
               "    <ImportDirectoryPackagesProps>false</ImportDirectoryPackagesProps>\n"
               "    <ImportProjectExtensionProps>false</ImportProjectExtensionProps>\n"
               "    <ImportProjectExtensionTargets>false</ImportProjectExtensionTargets>\n"
               "    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>\n")
    csproj = files[plan.csproj_relative_path].replace("  <PropertyGroup>\n", "  <PropertyGroup>\n" + guarded, 1)
    compile_items = "".join(f'    <Compile Include="{source}" />\n' for source in sorted(files) if source.endswith(".cs"))
    resource_items = "".join(
        f'    <EmbeddedResource Include="{relative}"><LogicalName>{logical}</LogicalName></EmbeddedResource>\n'
        for relative, logical in embedded
    )
    item_groups = "  <ItemGroup>\n" + compile_items + "  </ItemGroup>\n"
    if resource_items:
        item_groups += "  <ItemGroup>\n" + resource_items + "  </ItemGroup>\n"
    files[plan.csproj_relative_path] = csproj.replace("</Project>", item_groups + "</Project>")
    manifest = dict(plan.manifest)
    manifest["adapter_version"] = PRODUCT_VERSION
    manifest["product"] = {"protocol": "studio-local-1", "project_hash": project_digest(source_raw),
                           "requires_trusted_python_host": True, "hardware_status": "HARDWARE_PENDING"}
    manifest["native_project"] = {
        "schema_version": source_raw.get("schema_version"),
        "compatibility_adapter": native.legacy_raw is not None,
        "sdk_action_types": {action.id: action.sdk_type for action in native.actions},
        "multistate_led": "UNAVAILABLE_IN_INSTALLED_SDK_PUBLIC_API",
    }
    manifest["folder_runtime"] = {"version": "sdk-folders-1", "enabled": optional_layout, "mode": folder_mode,
        "diagnostics": folder_diagnostics, "hardware_status": "HARDWARE_PENDING",
        "action_editor": "EXPLICITLY_BLOCKED", "external_invoke": "POLICY_GATED" if shared else "UNSUPPORTED"}
    if shared:
        manifest["shared_folder_peer"] = {"protocol": "shared-folder-peer-1", "embedded_resource": "shared-folder-host.pyz"}
    if self_host:
        manifest["host_runtime"] = {"self_hosted": True, "record": "bin/studio.host-runtime.json",
                                    "embedded_resource": "shared-folder-host.pyz" if shared else "native-host.pyz",
                                    "studio_required_at_runtime": False}
    manifest["not_generated"] = {"runtime_view_membership_overrides": "NOT_YET_SUPPORTED",
                               "multistate_led": "INSTALLED_SDK_CAPABILITY_GAP"}
    manifest["capabilities"] = product_capabilities()
    manifest["warnings"] = [*manifest["warnings"],
                           {"code": "HARDWARE_PENDING", "message": "Build and process tests are not a device test"},
                           {"code": "PERSISTENCE_EXTERNAL", "message": "State values are not persisted automatically"},
                           {"code": "DEFAULT_PLACEMENT", "message": "Standalone actions use the first placement ID for their default visual"}]
    manifest["sdk"]["build_proven"] = False
    files[MANIFEST_FILE] = json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    plan = replace(plan, files=dict(sorted(files.items())), manifest=manifest)
    write_tree(plan, output_dir)
    return plan


def build_product(plan: GenerationPlan, output_dir: str | Path, *, configuration: str = "Debug",
                  log_path: str | Path | None = None):
    from .build import build_project
    root = check_output_dir(output_dir)
    if configuration not in ("Debug", "Release"):
        raise GenerationError("Product builds support Debug or Release only")
    for relative, expected in plan.files.items():
        file = root / relative
        actual = file.read_bytes() if isinstance(expected, bytes) else file.read_text(encoding="utf-8")
        if not file.resolve().is_relative_to(root) or actual != expected:
            raise GenerationError(f"Generated source was externally modified: {relative}")
    return build_project(root, configuration=configuration, log_path=log_path)


def product_capabilities() -> dict:
    return {
        "runtime_status": "PROCESS_TESTABLE", "hardware_status": "HARDWARE_PENDING",
        "command_action": "IMPLEMENTED", "authenticated_http": "IMPLEMENTED",
        "snapshot_delta_reconnect": "IMPLEMENTED", "text_png_state_variants": "IMPLEMENTED",
        "presentation_layout": {"image_fit": ["stretch", "contain"], "font_size": "6..48px_at_116_scaled_to_50_80"},
        "folder_placements": "IMPLEMENTED_SDK_NAVIGATION_HARDWARE_PENDING",
        "runtime_view_overrides": "NOT_YET_SUPPORTED", "adjustments": "BUILD_PROVEN_HARDWARE_PENDING",
        "parameters": "BUILD_PROVEN_HARDWARE_PENDING", "multistate": "BUILD_PROVEN_HARDWARE_PENDING",
        "action_editor": "BUILD_PROVEN_HARDWARE_PENDING",
        "multistate_led": "UNAVAILABLE_IN_INSTALLED_SDK_PUBLIC_API",
        "native_package_resources": ["actionicons", "actionsymbols", "icontemplates", "metadata/DefaultIconTemplate.ict"],
        "automatic_install_reload": "NOT_YET_SUPPORTED",
    }


def provision_connection(plan: GenerationPlan, output_dir: str | Path,
                         *, configuration: str = "Debug", port: int | None = None) -> Path:
    root = check_output_dir(output_dir)
    binary_dir = root / "bin" / configuration
    if not (binary_dir / f"{plan.assembly_name}.dll").is_file():
        raise GenerationError("Build the product DLL before provisioning the local connection")
    if not binary_dir.resolve().is_relative_to(root):
        raise GenerationError("Connection directory escapes the generated tree")
    connection_path = binary_dir / "studio.connection.json"
    if connection_path.exists():
        previous = ConnectionSettings.load(connection_path)
        if previous.plugin_id != plan.plugin_id or previous.project_hash != plan.manifest["product"]["project_hash"]:
            raise GenerationError("Existing local connection belongs to another revision; use a new isolated build directory. "
                                  "Do not replace or remove an active connection.")
        if port is not None and port != previous.port:
            raise GenerationError("Existing connection uses another port")
        return connection_path
    if port is None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
    settings = ConnectionSettings(plan.plugin_id, plan.manifest["product"]["project_hash"],
                                  port, secrets.token_hex(32))
    with connection_path.open("xb") as handle:
        handle.write(json_bytes(settings.as_dict()))
    return connection_path
