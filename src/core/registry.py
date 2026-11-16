"""Versioned ComponentType registry (manifests resolved by type_id + exact version)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compat import schema_shape_paths, schema_unknown_paths
from .errors import Diagnostic
from .ids import is_valid_id
from .model import ComponentType, PortDefinition
SIGNAL_KINDS = frozenset({"command", "event", "state"})
DIRECTIONS = frozenset({"in", "out"})


def _port_from_dict(raw: Any) -> tuple[PortDefinition | None, Diagnostic | None]:
    if not isinstance(raw, dict):
        return None, Diagnostic("PORT_SHAPE", "/ports", "Port must be an object")
    known = {"id", "direction", "kind", "payload_schema", "result_schema"}
    extra = {k: v for k, v in raw.items() if k not in known}
    pid, direction, kind = raw.get("id"), raw.get("direction"), raw.get("kind")
    if not is_valid_id(pid):
        return None, Diagnostic("PORT_ID_INVALID", "/ports", f"Invalid port id {pid!r}")
    if direction not in DIRECTIONS:
        return None, Diagnostic("PORT_DIRECTION_INVALID", "/ports", f"Invalid direction {direction!r}")
    if kind not in SIGNAL_KINDS:
        return None, Diagnostic("PORT_KIND_INVALID", "/ports", f"Invalid signal kind {kind!r}")
    payload = raw.get("payload_schema", {})
    if not isinstance(payload, dict):
        return None, Diagnostic("SCHEMA_INVALID", "/ports", "payload_schema must be an object")
    unknown = schema_unknown_paths(payload)
    if unknown:
        sub, key = unknown[0]
        return None, Diagnostic("SCHEMA_UNSUPPORTED", f"/ports{sub or ''}", f"payload_schema{sub or ''}: unsupported keyword {key!r}")
    shape = schema_shape_paths(payload)
    if shape:
        sub, detail = shape[0]
        return None, Diagnostic("SCHEMA_INVALID", f"/ports{sub or ''}", f"payload_schema{sub or ''}: {detail}")
    result = raw.get("result_schema")
    if result is not None:
        if not isinstance(result, dict):
            return None, Diagnostic("SCHEMA_INVALID", "/ports", "result_schema must be an object")
        unknown = schema_unknown_paths(result)
        if unknown:
            sub, key = unknown[0]
            return None, Diagnostic("SCHEMA_UNSUPPORTED", f"/ports{sub or ''}", f"result_schema{sub or ''}: unsupported keyword {key!r}")
        shape = schema_shape_paths(result)
        if shape:
            sub, detail = shape[0]
            return None, Diagnostic("SCHEMA_INVALID", f"/ports{sub or ''}", f"result_schema{sub or ''}: {detail}")
    return (
        PortDefinition(
            id=pid,
            direction=direction,
            kind=kind,
            payload_schema=payload,
            result_schema=result,
            extra=extra,
        ),
        None,
    )


def type_from_dict(raw: Any) -> tuple[ComponentType | None, list[Diagnostic]]:
    issues: list[Diagnostic] = []
    if not isinstance(raw, dict):
        return None, [Diagnostic("TYPE_SHAPE", "/", "Manifest must be an object")]
    known = {"type_id", "version", "config_schema", "ports", "capabilities", "test_only"}
    extra = {k: v for k, v in raw.items() if k not in known}
    type_id, version = raw.get("type_id"), raw.get("version")
    if not is_valid_id(type_id):
        issues.append(Diagnostic("TYPE_ID_INVALID", "/type_id", f"Invalid type_id {type_id!r}"))
    if not isinstance(version, str) or not version:
        issues.append(Diagnostic("TYPE_VERSION_INVALID", "/version", f"Invalid version {version!r}"))
    config_schema = raw.get("config_schema", {})
    if not isinstance(config_schema, dict):
        issues.append(Diagnostic("SCHEMA_INVALID", "/config_schema", "config_schema must be an object"))
        config_schema = {}
    else:
        unknown = schema_unknown_paths(config_schema)
        if unknown:
            for sub, key in unknown:
                issues.append(Diagnostic("SCHEMA_UNSUPPORTED", f"/config_schema{sub or ''}", f"Unsupported schema keyword {key!r}"))
        else:
            for sub, detail in schema_shape_paths(config_schema):
                issues.append(Diagnostic("SCHEMA_INVALID", f"/config_schema{sub or ''}", detail))
    ports: list[PortDefinition] = []
    raw_ports = raw.get("ports", [])
    if not isinstance(raw_ports, list):
        issues.append(Diagnostic("PORT_SHAPE", "/ports", "ports must be an array"))
    else:
        seen: set[str] = set()
        for entry in raw_ports:
            port, err = _port_from_dict(entry)
            if err is not None:
                issues.append(err)
                continue
            assert port is not None
            if port.id in seen:
                issues.append(Diagnostic("PORT_DUPLICATE", "/ports", f"Duplicate port {port.id!r}"))
            seen.add(port.id)
            ports.append(port)
    capabilities: list[str] = []
    raw_caps = raw.get("capabilities", [])
    if raw_caps is None:
        raw_caps = []
    if not isinstance(raw_caps, list) or any(not isinstance(c, str) for c in raw_caps):
        issues.append(Diagnostic("CAPABILITY_SHAPE", "/capabilities", "capabilities must be an array of strings"))
    else:
        capabilities = list(raw_caps)
    if issues:
        return None, issues
    return (
        ComponentType(
            type_id=type_id,
            version=version,
            config_schema=config_schema,
            ports=tuple(ports),
            capabilities=tuple(capabilities),
            extra=extra,
        ),
        [],
    )


class TypeRegistry:
    """Exact (type_id, version) manifest resolution with structured diagnostics."""

    def __init__(self) -> None:
        self._types: dict[tuple[str, str], ComponentType] = {}
        self.issues: list[Diagnostic] = []

    def add_manifest(self, raw: Any, origin: str = "<memory>") -> None:
        ctype, problems = type_from_dict(raw)
        for p in problems:
            self.issues.append(Diagnostic(p.code, f"{origin}{p.path}", p.message, p.severity))
        if ctype is None:
            return
        key = (ctype.type_id, ctype.version)
        if key in self._types:
            self.issues.append(
                Diagnostic("MANIFEST_DUPLICATE", origin, f"Duplicate manifest {ctype.type_id}@{ctype.version}")
            )
            return
        self._types[key] = ctype

    def resolve(self, type_id: Any, version: Any) -> ComponentType | None:
        if not isinstance(type_id, str) or not isinstance(version, str):
            return None
        return self._types.get((type_id, version))

    def has_type(self, type_id: Any) -> bool:
        return any(t == type_id for t, _ in self._types)

    def available_versions(self, type_id: Any) -> list[str]:
        return sorted(v for t, v in self._types if t == type_id)

    def port(self, ctype: ComponentType, port_id: str) -> PortDefinition | None:
        for p in ctype.ports:
            if p.id == port_id:
                return p
        return None


def load_manifests(directory: str | Path) -> tuple[TypeRegistry, list[Diagnostic]]:
    registry = TypeRegistry()
    base = Path(directory)
    if not base.is_dir():
        return registry, [Diagnostic("MANIFEST_DIR_MISSING", str(base), "Manifest directory not found")]
    for file in sorted(base.glob("*.json")):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            registry.issues.append(Diagnostic("MANIFEST_UNREADABLE", file.name, f"Cannot read manifest: {exc}"))
            continue
        registry.add_manifest(raw, origin=file.name)
    return registry, list(registry.issues)
