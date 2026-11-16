"""AP-CORE-001 P1 Core Model — static, SDK-independent project model.

No Logitech, Qt, transport, or runtime execution logic lives here.
See README.md for scope and draft status.
"""
from __future__ import annotations

from .errors import Diagnostic
from .io import dump_project, load_project, loads_project
from .model import (
    Asset,
    Binding,
    ComponentInstance,
    ComponentType,
    Dependency,
    EndpointRef,
    Placement,
    PortDefinition,
    Presentation,
    Project,
    StateDefinition,
    View,
)
from .registry import TypeRegistry, load_manifests
from .validate import validate_project

__all__ = [
    "Asset",
    "Binding",
    "ComponentInstance",
    "ComponentType",
    "Dependency",
    "Diagnostic",
    "EndpointRef",
    "Placement",
    "PortDefinition",
    "Presentation",
    "Project",
    "StateDefinition",
    "TypeRegistry",
    "View",
    "dump_project",
    "load_manifests",
    "load_project",
    "loads_project",
    "validate_project",
]

__version__ = "0.1.0-p1"
