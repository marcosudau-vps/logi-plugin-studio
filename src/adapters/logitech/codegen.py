"""Deterministic C# generator for the first Logitech SDK capability.

Input is a *validated* project selection (see :mod:`.gate`) plus a plugin id, an
assembly id, an output directory and the SDK reference.  Output is a minimal
.NET 10 source tree that is compiled against the really installed
``PluginApi.dll`` - nothing else.

Design rules enforced here:

* no timestamps, no random values, no absolute path in generated sources, so
  the same input always yields byte-identical C# sources;
* every user string reaches C# only through :func:`naming.csharp_literal`
  (or YAML quoting), every identifier through :func:`naming.identifier`;
* no installation target: the generated ``.csproj`` never writes to
  ``LOCALAPPDATA``, never creates a ``.link`` file and never restarts a service;
* writes happen only below the resolved output directory, and only after a
  path-safety check that rejects SDK, service and project source directories.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .capabilities import (
    COMMAND_ACTION_TYPE,
    SUPPORTED_COMPONENT_TYPES,
    capability_report,
)
from .errors import GenerationError, NamingError, OutputPathError
from .gate import PROJECT_ROOT, ProjectSelection, load_project_selection
from .naming import (
    csharp_literal,
    identifier,
    namespace_for,
    plugin_class_name,
    sdk_action_name,
    validate_assembly_name,
    yaml_double_quoted,
)

ADAPTER_NAME = "logitech"
ADAPTER_VERSION = "0.1.0"
SCHEMA_VERSION = 1

DEFAULT_SDK_DLL = Path(r"C:\Program Files\Logi\LogiPluginService\PluginApi.dll")
SDK_DLL_NAME = "PluginApi.dll"

MARKER_FILE = ".generated.json"
MANIFEST_FILE = "generated.manifest.json"
CSPROJ_TEMPLATE_NAME = "{assembly}.csproj"

#: Project sub-trees the adapter must never write into (source of truth files).
_READONLY_PROJECT_DIRS = ("src", "tests", "component_types", "schemas", "docs", "references")

#: Vendor runtime folders that must never be touched by a build-only adapter.
_FORBIDDEN_ENV_DIRS = (
    ("LOCALAPPDATA", "Logi"),
    ("APPDATA", "Logi"),
    ("PROGRAMDATA", "Logi"),
    ("PROGRAMFILES", "Logi"),
    ("PROGRAMFILES(X86)", "Logi"),
)
_FORBIDDEN_SEGMENTS = ("logipluginservice",)


@dataclass(frozen=True)
class ActionSpec:
    """One generated C# action."""

    component_id: str
    display_name: str
    type_name: str
    sdk_name: str
    source_path: str

    def as_dict(self) -> dict[str, str]:
        return {
            "component_id": self.component_id,
            "display_name": self.display_name,
            "csharp_type": self.type_name,
            "sdk_name": self.sdk_name,
            "source_file": self.source_path,
        }


@dataclass(frozen=True)
class GenerationPlan:
    """Fully rendered, deterministic generation result (no file system writes yet)."""

    project_id: str
    project_display_name: str
    plugin_id: str
    assembly_name: str
    namespace: str
    plugin_class: str
    plugin_display_name: str
    plugin_version: str
    sdk_dll: Path
    sdk_dll_sha256: str
    actions: tuple[ActionSpec, ...]
    files: dict[str, str | bytes] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    selection: ProjectSelection | None = None

    @property
    def csproj_relative_path(self) -> str:
        return CSPROJ_TEMPLATE_NAME.format(assembly=self.assembly_name)

    @property
    def expected_dll_relative_path(self) -> str:
        return f"bin/Debug/{self.assembly_name}.dll"

    def render(self) -> dict[str, str | bytes]:
        """Return generated text and package-native binary resources."""
        return dict(self.files)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_sdk_dll(sdk_dll: str | Path) -> Path:
    path = Path(sdk_dll)
    if not path.is_absolute():
        raise GenerationError(f"PluginApi.dll path must be absolute, got {sdk_dll!r}")
    if path.name != SDK_DLL_NAME:
        raise GenerationError(f"Expected a reference to {SDK_DLL_NAME}, got {path.name!r}")
    if not path.is_file():
        raise GenerationError(f"{SDK_DLL_NAME} not found at {path}")
    return path


def _forbidden_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name, leaf in _FORBIDDEN_ENV_DIRS:
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / leaf)
    return roots


def check_output_dir(output_dir: str | Path) -> Path:
    """Resolve and validate a target directory for generated sources.

    Raises :class:`OutputPathError` for anything that is not a dedicated,
    non-source directory.  The check is intentionally strict: a generator that
    can be pointed at ``%LOCALAPPDATA%\\Logi`` by a malformed project file is a
    deployment tool, and this adapter is not one.
    """
    raw = Path(output_dir)
    if not raw.is_absolute():
        raw = (Path.cwd() / raw).resolve()
    else:
        raw = raw.resolve()

    if raw.parent == raw:
        raise OutputPathError(f"Refusing to use a drive root as output directory: {raw}")
    if raw == Path.home().resolve():
        raise OutputPathError("Refusing to use the home directory as output directory")
    project_root = PROJECT_ROOT.resolve()
    if raw == project_root or raw in project_root.parents:
        raise OutputPathError(f"Refusing to write into the project root or above: {raw}")

    for part in raw.parts:
        if part.casefold() in _FORBIDDEN_SEGMENTS:
            raise OutputPathError(f"Refusing to write into a Logi Plugin Service folder: {raw}")
    for forbidden in _forbidden_roots():
        try:
            forbidden = forbidden.resolve()
        except OSError:  # pragma: no cover - unresolvable vendor path
            continue
        if raw == forbidden or forbidden in raw.parents:
            raise OutputPathError(f"Refusing to write into a Logi installation folder: {raw}")

    for name in _READONLY_PROJECT_DIRS:
        guarded = (project_root / name).resolve()
        if raw == guarded or guarded in raw.parents:
            raise OutputPathError(f"Refusing to write into the project source tree: {raw}")

    if raw.exists() and not raw.is_dir():
        raise OutputPathError(f"Output path exists and is not a directory: {raw}")
    return raw


def _clean_relative_path(relative: str) -> PurePosixPath:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(part in ("..", "") for part in posix.parts):
        raise OutputPathError(f"Unsafe relative output path: {relative!r}")
    if "\\" in relative or ":" in relative:
        raise OutputPathError(f"Unsafe relative output path: {relative!r}")
    return posix


def _marker(plan: GenerationPlan) -> str:
    payload = {
        "adapter": ADAPTER_NAME,
        "adapter_version": ADAPTER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "plugin_id": plan.plugin_id,
        "assembly_name": plan.assembly_name,
        "files": sorted(plan.files),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# C# rendering
# --------------------------------------------------------------------------- #

_HEADER = (
    "// <auto-generated>\n"
    "// Generated by PluginStudioArchitecture/src/adapters/logitech "
    f"(adapter {ADAPTER_VERSION}).\n"
    "// Source: project '{project}' (component '{component}').\n"
    "// Do not edit by hand: regenerate from the project definition instead.\n"
    "// </auto-generated>\n"
)


def _render_plugin(plan: GenerationPlan) -> str:
    return (
        _HEADER.format(project=plan.project_id, component="-")
        + "namespace "
        + plan.namespace
        + "\n{\n"
        + "    using System;\n"
        + "    using Loupedeck;\n\n"
        + "    /// <summary>Universal plugin shell of a generated project (BUILD_ONLY).</summary>\n"
        + "    public class "
        + plan.plugin_class
        + " : Plugin\n    {\n"
        + "        public override Boolean HasNoApplication => true;\n\n"
        + "        public override Boolean UsesApplicationApiOnly => true;\n\n"
        + "        public override void Load()\n        {\n"
        + "            ActionDispatcher.Log(\"plugin.load\", "
        + csharp_literal(plan.plugin_id)
        + ");\n        }\n\n"
        + "        public override void Unload()\n        {\n"
        + "            ActionDispatcher.Log(\"plugin.unload\", "
        + csharp_literal(plan.plugin_id)
        + ");\n        }\n"
        + "    }\n}\n"
    )


def _render_application(plan: GenerationPlan) -> str:
    """SDK-required ClientApplication type for a universal plugin.

    Must match the Plugin type prefix. The empty process/bundle means this
    is not tied to a foreground application.
    """
    application_name = plan.plugin_class.removesuffix("Plugin") + "Application"
    return (
        _HEADER.format(project=plan.project_id, component="-")
        + f"""namespace {plan.namespace}
{{
    using System;
    using Loupedeck;

    public class {application_name} : ClientApplication
    {{
        protected override String GetProcessName() => "";
        protected override String GetBundleName() => "";
        public override ClientApplicationStatus GetApplicationStatus()
            => ClientApplicationStatus.Unknown;
    }}
}}
"""
    )


def _render_action(plan: GenerationPlan, action: ActionSpec) -> str:
    description = f"Generated Logitech action for component {action.component_id}."
    return (
        _HEADER.format(project=plan.project_id, component=action.component_id)
        + "namespace "
        + plan.namespace
        + "\n{\n"
        + "    using System;\n"
        + "    using Loupedeck;\n\n"
        + "    /// <summary>Static PluginDynamicCommand generated from a core.command_action instance.</summary>\n"
        + "    public class "
        + action.type_name
        + " : PluginDynamicCommand\n    {\n"
        + "        public const String SdkActionName = "
        + csharp_literal(action.sdk_name)
        + ";\n\n"
        + "        public const String ComponentId = "
        + csharp_literal(action.component_id)
        + ";\n\n"
        + "        public "
        + action.type_name
        + "()\n            : base("
        + csharp_literal(action.display_name)
        + ", "
        + csharp_literal(description)
        + ", "
        + csharp_literal(plan.plugin_display_name)
        + ")\n        {\n        }\n\n"
        + "        protected override void RunCommand(String actionParameter)\n        {\n"
        + "            // BUILD_ONLY / CALLBACK_PENDING: no transport, no authentication, no Python execution.\n"
        + "            ActionDispatcher.Dispatch(SdkActionName, ComponentId);\n"
        + "        }\n"
        + "    }\n}\n"
    )


def _render_dispatcher(plan: GenerationPlan) -> str:
    return (
        _HEADER.format(project=plan.project_id, component="-")
        + "namespace "
        + plan.namespace
        + "\n{\n"
        + "    using System;\n\n"
        + "    /// <summary>\n"
        + "    /// Fachneutraler lokaler Callback-Hook. Es gibt bewusst noch keinen Transport,\n"
        + "    /// keine Authentisierung und keine Python-Ausfuehrung: der Hook protokolliert\n"
        + "    /// nur (BUILD_ONLY / CALLBACK_PENDING) und kann spaeter ersetzt werden.\n"
        + "    /// </summary>\n"
        + "    public interface IActionDispatch\n    {\n"
        + "        void Dispatch(String sdkActionName, String componentId);\n    }\n\n"
        + "    /// <summary>Setzt den aktiven Hook; ein spaeterer Host ersetzt die Protokollvariante.</summary>\n"
        + "    public static class ActionDispatcher\n    {\n"
        + "        private static readonly Object Gate = new Object();\n"
        + "        private static IActionDispatch _current = new DebugActionDispatch();\n\n"
        + "        public static IActionDispatch Current\n        {\n"
        + "            get { lock (Gate) { return _current; } }\n"
        + "            set { lock (Gate) { _current = value ?? new DebugActionDispatch(); } }\n"
        + "        }\n\n"
        + "        public static void Dispatch(String sdkActionName, String componentId)\n        {\n"
        + "            Current.Dispatch(sdkActionName, componentId);\n        }\n\n"
        + "        public static void Log(String eventName, String detail)\n        {\n"
        + "            System.Diagnostics.Debug.WriteLine(\"[plugin-studio] \" + eventName + \" \" + detail);\n        }\n"
        + "    }\n\n"
        + "    internal sealed class DebugActionDispatch : IActionDispatch\n"
        + "    {\n"
        + "        public void Dispatch(String sdkActionName, String componentId)\n        {\n"
        + "            ActionDispatcher.Log(\"callback.pending\", sdkActionName + \" <- \" + componentId);\n"
        + "        }\n    }\n}\n"
    )


def _render_csproj(plan: GenerationPlan) -> str:
    api_dir = str(plan.sdk_dll.parent)
    if not api_dir.endswith(os.sep) and not api_dir.endswith("/"):
        api_dir += os.sep
    return (
        '<Project Sdk="Microsoft.NET.Sdk">\n\n'
        "  <!-- Generated build-only project: a plain assembly build and nothing else.\n"
        "       Installation, registration and service control are out of scope. -->\n"
        "  <PropertyGroup>\n"
        "    <TargetFramework>net10.0</TargetFramework>\n"
        "    <ImplicitUsings>enable</ImplicitUsings>\n"
        "    <Nullable>disable</Nullable>\n"
        "    <LangVersion>latest</LangVersion>\n"
        f"    <RootNamespace>{xml_escape(plan.namespace)}</RootNamespace>\n"
        f"    <AssemblyName>{xml_escape(plan.assembly_name)}</AssemblyName>\n"
        "    <Deterministic>true</Deterministic>\n"
        "    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>\n"
        "    <CopyLocalLockFileAssemblies>false</CopyLocalLockFileAssemblies>\n"
        "    <GenerateDocumentationFile>false</GenerateDocumentationFile>\n"
        "    <DebugType>none</DebugType>\n"
        "    <DebugSymbols>false</DebugSymbols>\n"
        "    <ProduceReferenceAssembly>false</ProduceReferenceAssembly>\n"
        f"    <PluginApiDir>{xml_escape(api_dir)}</PluginApiDir>\n"
        "  </PropertyGroup>\n\n"
        "  <ItemGroup>\n"
        '    <Reference Include="PluginApi">\n'
        "      <HintPath>$(PluginApiDir)PluginApi.dll</HintPath>\n"
        "      <Private>false</Private>\n"
        "    </Reference>\n"
        "  </ItemGroup>\n\n"
        "</Project>\n"
    )


def _render_nuget_config() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<configuration>\n"
        "  <!-- Build-only project: no package restore from the network. -->\n"
        "  <packageSources>\n"
        "    <clear />\n"
        "  </packageSources>\n"
        "</configuration>\n"
    )


def _render_package_yaml(plan: GenerationPlan) -> str:
    # The SDK name matches the discovered Plugin class, not the internal dotted ID.
    sdk_name = plan.plugin_class.removesuffix("Plugin")
    return (
        "# Generated package metadata. NOT installed by this adapter.\n"
        "# supportedDevices is a placeholder taken from the lab observation (LAB_OBSERVED),\n"
        "# not a hardware-approved capability.\n"
        "type: plugin4\n"
        f"name: {yaml_double_quoted(sdk_name)}\n"
        f"displayName: {yaml_double_quoted(plan.plugin_display_name)}\n"
        f"description: {yaml_double_quoted('Generated by Plugin Studio Architecture (build only).')}\n"
        f"pluginFileName: {yaml_double_quoted(plan.assembly_name + '.dll')}\n"
        f"version: {yaml_double_quoted(plan.plugin_version)}\n"
        'author: "Plugin Studio Architecture"\n'
        'copyright: "Plugin Studio Architecture"\n'
        'minimumLoupedeckVersion: "6.0"\n'
        "pluginFolderWin: bin\n"
        "supportedDevices:\n"
        "    - LoupedeckExtendedFamily\n"
        "pluginCapabilities: []\n"
    )


def _manifest_payload(plan: GenerationPlan) -> dict[str, Any]:
    selection = plan.selection
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter": ADAPTER_NAME,
        "adapter_version": ADAPTER_VERSION,
        "project": {"id": plan.project_id, "display_name": plan.project_display_name},
        "plugin": {
            "id": plan.plugin_id,
            "assembly_name": plan.assembly_name,
            "namespace": plan.namespace,
            "plugin_class": plan.plugin_class,
            "sdk_name": plan.plugin_class.removesuffix("Plugin"),
            "display_name": plan.plugin_display_name,
            "version": plan.plugin_version,
            "csproj": plan.csproj_relative_path,
        },
        "sdk": {
            "reference": SDK_DLL_NAME,
            "path": str(plan.sdk_dll),
            "sha256": plan.sdk_dll_sha256,
            "build_proven": True,
        },
        "actions": [action.as_dict() for action in plan.actions],
        "not_generated": {
            "reason": "This capability slice only generates static core.command_action instances.",
            "unsupported_components": list(selection.unsupported_components) if selection else [],
            **(selection.not_generated if selection else {}),
        },
        "warnings": list(selection.warnings) if selection else [],
        "capabilities": capability_report(),
    }


def _render_manifest(plan: GenerationPlan) -> str:
    return json.dumps(plan.manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def plan_generation(
    selection: ProjectSelection,
    *,
    plugin_id: str,
    assembly_name: str,
    sdk_dll: str | Path = DEFAULT_SDK_DLL,
    plugin_display_name: str | None = None,
    plugin_version: str = "0.1.0",
) -> GenerationPlan:
    """Build a :class:`GenerationPlan` from a validated selection (pure)."""
    validate_assembly_name(assembly_name)
    if not isinstance(plugin_id, str) or not plugin_id:
        raise NamingError("Plugin id must be a non-empty string")
    if not isinstance(plugin_version, str) or not plugin_version:
        raise NamingError("Plugin version must be a non-empty string")

    resolved_sdk = _resolve_sdk_dll(sdk_dll)
    namespace = namespace_for(plugin_id)
    plugin_class = plugin_class_name(assembly_name)
    display = plugin_display_name if plugin_display_name else selection.display_name

    actions: list[ActionSpec] = []
    used: dict[str, str] = {}
    for candidate in selection.actions:
        type_name = identifier("Action", candidate.component_id)
        previous = used.get(type_name)
        if previous is not None and previous != candidate.component_id:
            raise NamingError(
                f"C# type collision between {previous!r} and {candidate.component_id!r} ({type_name})"
            )
        used[type_name] = candidate.component_id
        actions.append(
            ActionSpec(
                component_id=candidate.component_id,
                display_name=candidate.display_name,
                type_name=type_name,
                sdk_name=sdk_action_name(plugin_id, candidate.component_id),
                source_path=f"src/actions/{type_name}.cs",
            )
        )

    plan = GenerationPlan(
        project_id=selection.project_id,
        project_display_name=selection.display_name,
        plugin_id=plugin_id,
        assembly_name=assembly_name,
        namespace=namespace,
        plugin_class=plugin_class,
        plugin_display_name=display,
        plugin_version=plugin_version,
        sdk_dll=resolved_sdk,
        sdk_dll_sha256=_sha256_file(resolved_sdk),
        actions=tuple(actions),
        selection=selection,
    )

    files: dict[str, str] = {
        "nuget.config": _render_nuget_config(),
        plan.csproj_relative_path: _render_csproj(plan),
        "src/Plugin.cs": _render_plugin(plan),
        "src/Application.cs": _render_application(plan),
        "src/ActionDispatch.cs": _render_dispatcher(plan),
        "metadata/LoupedeckPackage.yaml": _render_package_yaml(plan),
    }
    for action in plan.actions:
        files[action.source_path] = _render_action(plan, action)

    plan = replace(plan, files=dict(sorted(files.items())))
    plan = replace(plan, manifest=_manifest_payload(plan))
    files[MANIFEST_FILE] = _render_manifest(plan)
    return replace(plan, files=dict(sorted(files.items())))


def write_tree(plan: GenerationPlan, output_dir: str | Path) -> list[Path]:
    """Write the generated tree below ``output_dir`` and return the written files.

    Re-running into the same directory is allowed only when the directory
    carries a marker for the same plugin id; previously generated files are
    then removed first, so a renamed or deleted action cannot leave stale code.
    """
    target = check_output_dir(output_dir)
    marker_path = target / MARKER_FILE

    if target.exists():
        entries = [entry for entry in target.iterdir()]
        if entries:
            if not marker_path.is_file():
                raise OutputPathError(
                    f"Output directory is not empty and was not generated by this adapter: {target}"
                )
            try:
                previous = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise OutputPathError(f"Unreadable generator marker in {target}: {exc}") from exc
            if previous.get("plugin_id") != plan.plugin_id:
                raise OutputPathError(
                    "Output directory belongs to plugin "
                    f"{previous.get('plugin_id')!r}, not {plan.plugin_id!r}"
                )
            for relative in previous.get("files", []):
                stale = target / _clean_relative_path(relative)
                if stale.is_file() and stale.resolve().is_relative_to(target):
                    stale.unlink()
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for relative, content in plan.files.items():
        destination = target / _clean_relative_path(relative)
        try:
            destination.resolve().relative_to(target)
        except ValueError as exc:
            raise OutputPathError(f"Output path escapes {target}: {relative!r}") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        else:
            with destination.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        written.append(destination)

    with marker_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(_marker(plan))
    written.append(marker_path)

    # Drop now-empty action directories left behind by a shrinking project.
    actions_dir = target / "src" / "actions"
    if actions_dir.is_dir() and not any(actions_dir.iterdir()):
        shutil.rmtree(actions_dir, ignore_errors=True)
    return written


def generate(
    project_path: str | Path,
    *,
    plugin_id: str,
    assembly_name: str,
    output_dir: str | Path,
    sdk_dll: str | Path = DEFAULT_SDK_DLL,
    manifest_dir: str | Path | None = None,
    plugin_display_name: str | None = None,
    plugin_version: str = "0.1.0",
) -> GenerationPlan:
    """Validate, plan and write in one call (the only public write entry point)."""
    selection = load_project_selection(project_path, manifest_dir)
    plan = plan_generation(
        selection,
        plugin_id=plugin_id,
        assembly_name=assembly_name,
        sdk_dll=sdk_dll,
        plugin_display_name=plugin_display_name,
        plugin_version=plugin_version,
    )
    write_tree(plan, output_dir)
    return plan


def scratch_directory(prefix: str = "logitech-adapter-") -> Path:
    """Create an isolated temporary directory (used by tests and the CLI)."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def supported_types() -> tuple[str, ...]:
    """Component types this capability can generate (single source of truth)."""
    return tuple(SUPPORTED_COMPONENT_TYPES)


__all__ = [
    "ActionSpec",
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "COMMAND_ACTION_TYPE",
    "DEFAULT_SDK_DLL",
    "GenerationError",
    "GenerationPlan",
    "MARKER_FILE",
    "MANIFEST_FILE",
    "check_output_dir",
    "generate",
    "plan_generation",
    "scratch_directory",
    "supported_types",
    "write_tree",
]
