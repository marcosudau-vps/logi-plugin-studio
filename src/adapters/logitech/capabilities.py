"""Capability matrix of the first Logitech adapter slice (single source of truth).

The matrix is deliberately conservative: only what the generator emits *and*
what a local ``dotnet build`` actually proved is called ``BUILD_PROVEN``.
Anything learned from the lab (``LAB_OBSERVED``) is labelled as such, and every
not-yet-implemented SDK surface stays ``NOT_YET_SUPPORTED`` instead of being
presented as working.
"""
from __future__ import annotations

COMMAND_ACTION_TYPE = "core.command_action"
COMMAND_ACTION_VERSION = "1.0.0"
ACTIVATED_PORT = "activated"

STATUS_BUILD_PROVEN = "BUILD_PROVEN"
STATUS_LAB_OBSERVED = "LAB_OBSERVED"
STATUS_NOT_SUPPORTED = "NOT_YET_SUPPORTED"
STATUS_HARDWARE_PENDING = "HARDWARE_PENDING"
STATUS_CALLBACK_PENDING = "CALLBACK_PENDING"

#: Component types this generator can turn into code today.
SUPPORTED_COMPONENT_TYPES = (COMMAND_ACTION_TYPE,)

#: What the generated code was actually compiled against, and how it was proven.
CAPABILITIES = {
    "plugin.universal_plugin_class": {
        "status": STATUS_BUILD_PROVEN,
        "note": "Plugin subclass with HasNoApplication/UsesApplicationApiOnly, Load/Unload; compiled against the installed PluginApi.dll.",
    },
    "action.plugin_dynamic_command.static": {
        "status": STATUS_BUILD_PROVEN,
        "note": "One PluginDynamicCommand subclass per core.command_action instance; constructor name/description/group escape-encoded.",
    },
    "action.run_command.dispatch_hook": {
        "status": STATUS_CALLBACK_PENDING,
        "note": "RunCommand forwards to a local IActionDispatch hook. No transport, no authentication, no Python execution.",
    },
    "package.metadata.loupedeck_yaml": {
        "status": STATUS_LAB_OBSERVED,
        "note": "Metadata file is generated for later packaging but never installed by this adapter.",
    },
    "deployment.install_development_plugin": {
        "status": STATUS_NOT_SUPPORTED,
        "note": "No .link registration, no copy into the Options+ plugin folder, no service restart.",
    },
}

#: SDK surfaces that exist but are intentionally out of scope for this AP.
NOT_YET_SUPPORTED = (
    "PluginDynamicFolder / dynamic views (view, placement, membership changes)",
    "PluginDynamicAdjustment (rotary/encoder actions)",
    "Command parameters and parameter groups (AddParameter/ParametersChanged)",
    "GetCommandImage / BitmapImage / BitmapBuilder rendering and assets",
    "Localization (.resx / translations)",
    "Application plugins (ClientApplication binding, process detection)",
    "Hardware verification of any generated action (HARDWARE_PENDING)",
    "Any host transport (HTTP/IPC/socket) and any authentication scheme",
)


def capability_report() -> dict[str, object]:
    """Serialisable snapshot used in the generated manifest and CLI output."""
    return {
        "supported_component_types": list(SUPPORTED_COMPONENT_TYPES),
        "capabilities": {name: dict(value) for name, value in sorted(CAPABILITIES.items())},
        "not_yet_supported": list(NOT_YET_SUPPORTED),
        "runtime_status": "BUILD_ONLY",
        "callback_status": STATUS_CALLBACK_PENDING,
    }
