"""First generic Logitech SDK capability: ``core.command_action`` -> C# plugin.

Scope of this slice (see README.md and ``capabilities.py``):

* reusable core validation gate, no second project model or schema;
* deterministic generation of a minimal .NET 10 source tree for
  ``PluginDynamicCommand`` actions plus a universal ``Plugin`` shell;
* a local ``IActionDispatch`` test hook that is explicitly BUILD_ONLY /
  CALLBACK_PENDING (no transport, no authentication, no Python execution);
* an isolated ``dotnet build`` against the installed ``PluginApi.dll`` with no
  installation target, no ``.link`` registration and no service restart.

Nothing here touches the Logi Plugin Service, Options+ or any vendor folder.
"""
from __future__ import annotations

from .build import BuildResult, assert_no_install_target, build_project
from .capabilities import (
    CAPABILITIES,
    COMMAND_ACTION_TYPE,
    NOT_YET_SUPPORTED,
    SUPPORTED_COMPONENT_TYPES,
    capability_report,
)
from .codegen import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    DEFAULT_SDK_DLL,
    ActionSpec,
    GenerationPlan,
    check_output_dir,
    generate,
    plan_generation,
    write_tree,
)
from .errors import (
    BuildError,
    GenerationError,
    LogitechAdapterError,
    NamingError,
    OutputPathError,
    SelectionError,
    ValidationGateError,
)
from .gate import ActionCandidate, ProjectSelection, load_project_selection
from .naming import csharp_literal, identifier, namespace_for, sdk_action_name

__version__ = ADAPTER_VERSION

__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "ActionCandidate",
    "ActionSpec",
    "BuildError",
    "BuildResult",
    "CAPABILITIES",
    "COMMAND_ACTION_TYPE",
    "DEFAULT_SDK_DLL",
    "GenerationError",
    "GenerationPlan",
    "LogitechAdapterError",
    "NOT_YET_SUPPORTED",
    "NamingError",
    "OutputPathError",
    "ProjectSelection",
    "SUPPORTED_COMPONENT_TYPES",
    "SelectionError",
    "ValidationGateError",
    "assert_no_install_target",
    "build_project",
    "capability_report",
    "check_output_dir",
    "csharp_literal",
    "generate",
    "identifier",
    "load_project_selection",
    "namespace_for",
    "plan_generation",
    "sdk_action_name",
    "write_tree",
]
