"""Typed static entities for AP-CORE-001 (P0-ADR-002).

Persisted: Project, ComponentInstance, StateDefinition, Binding, View (+Placement),
Presentation, Asset, Dependency. Library-owned: ComponentType, PortDefinition.
Derived (never persisted as project JSON): EndpointRef.
No RuntimeInstance, no current values, no Logitech/Qt concepts.

Unknown fields are preserved in ``extra`` mappings so that load/dump/reload
never silently drops data; the validator still reports them (FIELD_UNKNOWN).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Sentinel distinguishing "fallback absent" from "fallback: null".
class _Missing:
    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _Missing()


@dataclass(frozen=True)
class PortDefinition:
    id: str
    direction: str  # "in" | "out"
    kind: str  # "command" | "event" | "state"
    payload_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentType:
    type_id: str
    version: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    ports: tuple[PortDefinition, ...] = ()
    capabilities: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EndpointRef:
    """Derived structured reference {owner_kind, owner_id, port} (P0-ADR-001)."""

    owner_kind: str  # "component" | "state" | "presentation"
    owner_id: str
    port: str


@dataclass(frozen=True)
class Dependency:
    type: Any = ""
    version: Any = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentInstance:
    id: str
    type: Any = ""
    version: Any = ""
    config: Any = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateDefinition:
    id: str
    value_schema: Any = field(default_factory=dict)
    authority: Any = field(default_factory=dict)
    scope: Any = ""
    persistence: Any = ""
    fallback: Any = MISSING
    has_fallback: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Binding:
    id: Any = MISSING
    source: Any = MISSING  # EndpointRef when well-formed, raw verbatim when present-but-malformed
    target: Any = MISSING  # EndpointRef when well-formed, raw verbatim when present-but-malformed
    kind: Any = MISSING
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Placement:
    id: Any = MISSING
    component: Any = MISSING
    presentation: Any = MISSING  # MISSING = key absent; None = explicit JSON null
    position: Any = MISSING
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class View:
    id: Any = MISSING
    type: Any = MISSING
    placements: tuple[Placement, ...] = ()
    # Verbatim raw `placements` value (MISSING when the key is absent).
    # Serialization uses this verbatim; `placements` is the structured view.
    placements_raw: Any = MISSING
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Presentation:
    id: str
    variants: Any = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Asset:
    id: str
    path: Any = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    schema_version: Any = ""
    project_id: Any = ""
    display_name: Any = ""
    dependencies: tuple[Dependency, ...] = ()
    components: tuple[ComponentInstance, ...] = ()
    states: tuple[StateDefinition, ...] = ()
    bindings: tuple[Binding, ...] = ()
    presentations: tuple[Presentation, ...] = ()
    assets: tuple[Asset, ...] = ()
    views: tuple[View, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)
    # Lossless round-trip bookkeeping (never silently normalise invalid input):
    present_keys: frozenset[str] = frozenset()
    project_raw: Any = MISSING  # MISSING = `project` key absent; otherwise verbatim when not a dict
    project_extra: dict[str, Any] = field(default_factory=dict)
    raw_items: tuple[tuple[str, int, Any], ...] = ()  # non-dict entries: (collection, raw_index, value)
    raw_collections: dict[str, Any] = field(default_factory=dict)  # verbatim non-list collections
