"""Validation gate and capability selection for the Logitech adapter.

The adapter never re-implements the project model: it loads the raw document
with :mod:`core.io`, resolves manifests with :mod:`core.registry` and decides
validity exclusively with :mod:`core.validate`.  Generation starts only after
this gate reported zero ERROR diagnostics.

Selection is intentionally narrow: today exactly ``core.command_action``
instances become actions.  Everything else is *recorded* (never dropped) so a
reviewer can see what a project contains and what was not generated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.io import load_raw
from core.registry import load_manifests
from core.validate import validate_project

from .capabilities import ACTIVATED_PORT, COMMAND_ACTION_TYPE
from .errors import SelectionError, ValidationGateError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_DIR = PROJECT_ROOT / "component_types"


@dataclass(frozen=True)
class ActionCandidate:
    """One validated ``core.command_action`` instance that becomes a C# action."""

    component_id: str
    display_name: str
    type_id: str
    version: str


@dataclass(frozen=True)
class ProjectSelection:
    """Result of the gate: what will be generated and what explicitly will not."""

    project_id: str
    display_name: str
    actions: tuple[ActionCandidate, ...]
    warnings: tuple[dict[str, Any], ...] = ()
    unsupported_components: tuple[dict[str, str], ...] = ()
    not_generated: dict[str, Any] = field(default_factory=dict)

    @property
    def action_count(self) -> int:
        return len(self.actions)


def _error_issues(issues: list[Any]) -> list[Any]:
    return [issue for issue in issues if getattr(issue, "severity", "ERROR") == "ERROR"]


def load_project_selection(
    project_path: str | Path,
    manifest_dir: str | Path | None = None,
) -> ProjectSelection:
    """Validate ``project_path`` against the core model and select actions.

    Raises :class:`ValidationGateError` for any ERROR diagnostic and
    :class:`SelectionError` when the project is valid but contains no action
    this capability can generate.
    """
    path = Path(project_path)
    try:
        raw = load_raw(path)
    except (OSError, ValueError) as exc:
        raise ValidationGateError(
            [{"code": "PROJECT_UNREADABLE", "path": "/", "message": str(exc), "severity": "ERROR"}]
        ) from exc

    registry, registry_issues = load_manifests(manifest_dir or DEFAULT_MANIFEST_DIR)
    return select_project(raw, registry, registry_issues)


def select_project(raw: dict, registry: Any, registry_issues: list[Any] | None = None) -> ProjectSelection:
    """Select from one immutable caller snapshot using the same approved gate."""
    registry_issues = registry_issues if registry_issues is not None else list(registry.issues)
    issues = [*registry_issues, *validate_project(raw, registry)]
    errors = _error_issues(issues)
    if errors:
        raise ValidationGateError(errors)

    header = raw.get("project") or {}
    project_id = header.get("id")
    display_name = header.get("display_name")

    actions: list[ActionCandidate] = []
    unsupported: list[dict[str, str]] = []
    for component in raw.get("components", []):
        manifest = registry.resolve(component.get("type"), component.get("version"))
        if manifest is None:  # unreachable: validation already failed
            raise SelectionError(f"Unresolved component type for {component.get('id')!r}")
        if manifest.type_id != COMMAND_ACTION_TYPE:
            unsupported.append(
                {
                    "component_id": str(component.get("id")),
                    "type_id": manifest.type_id,
                    "reason": "no generator for this component type in this capability slice",
                }
            )
            continue
        port = next((p for p in manifest.ports if p.id == ACTIVATED_PORT), None)
        if port is None or port.kind != "command" or port.direction != "out":
            raise SelectionError(
                f"Component {component.get('id')!r} lacks an outgoing command port {ACTIVATED_PORT!r}"
            )
        config = component["config"]
        name = config.get("display_name")
        if not isinstance(name, str) or not name:
            raise SelectionError(f"Component {component.get('id')!r} has no usable display_name")
        actions.append(
            ActionCandidate(
                component_id=str(component["id"]),
                display_name=name,
                type_id=manifest.type_id,
                version=manifest.version,
            )
        )

    if not actions:
        raise SelectionError(
            f"Project contains no {COMMAND_ACTION_TYPE} instance; nothing to generate "
            f"(unsupported components: {[entry['component_id'] for entry in unsupported]})"
        )

    views = []
    for view in raw.get("views", []):
        placements = [
            {
                "placement_id": str(placement.get("id")),
                "component_id": str(placement.get("component")),
                "presentation": placement.get("presentation"),
                "position": placement.get("position"),
            }
            for placement in view.get("placements", [])
            if isinstance(placement, dict)
        ]
        views.append({"view_id": str(view.get("id")), "type": view.get("type"), "placements": placements})

    selection = ProjectSelection(
        project_id=str(project_id),
        display_name=str(display_name),
        actions=tuple(actions),
        warnings=tuple(issue.as_dict() for issue in issues if getattr(issue, "severity", "") != "ERROR"),
        unsupported_components=tuple(unsupported),
        not_generated={
            "views": views,
            "presentations": [str(p.get("id")) for p in raw.get("presentations", [])],
            "assets": [str(a.get("id")) for a in raw.get("assets", [])],
            "bindings": [str(b.get("id")) for b in raw.get("bindings", [])],
            "states": [str(s.get("id")) for s in raw.get("states", [])],
        },
    )
    return selection
