"""Static connection-plan compilation for the AP-CORE-002 In-Memory spike.

Uses the AP-CORE-001 core validator as the single source of truth for project
validity (P0-ADR-007): this module performs **no** independent project
validation and introduces **no** new endpoint notation. It only projects the
already-checked ``command``/``event`` bindings into a deterministic,
synchronous dispatch table.

Rules (all SPIKE_ONLY where marked):

- Only projects with zero core ``ERROR`` diagnostics compile. ``WARNING``
  diagnostics are preserved on the plan.
- ``state``-kind bindings are recorded as ``ignored_state_bindings`` and are
  never dispatched here (no StateStore in this run, per ADR-005 gate).
- Bindings flagged ``SCHEMA_NOT_PROVEN`` (WARNING) by the core validator are
  quarantined: default ``allow_unproven=False`` refuses compilation with
  ``RUNTIME_UNPROVEN_BLOCKED`` (ERROR); explicit ``allow_unproven=True``
  compiles the remaining proven bindings and marks the plan ``provisional``.
  Quarantined bindings never dispatch silently (``RUNTIME_UNPROVEN_BLOCKED``).
- Dispatch order is lexical by ``binding_id`` (SPIKE_ONLY, not normative —
  see trade-off note in ``06_runtime_vertragsentwurf.md``).
- The input ``raw`` document is never mutated; schemas are deep-copied.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .errors import RUNTIME_ENDPOINT_UNKNOWN, RUNTIME_UNPROVEN_BLOCKED, RUNTIME_UNPROVEN_PROVISIONAL


@dataclass(frozen=True)
class Connection:
    binding_id: str
    kind: str  # "command" | "event"
    source_component: str
    source_port: str
    target_component: str
    target_port: str
    source_schema: dict[str, Any] = field(default_factory=dict)
    target_schema: dict[str, Any] = field(default_factory=dict)
    target_result_schema: Any = None


@dataclass(frozen=True)
class ConnectionPlan:
    project_id: str
    connections: tuple = ()
    quarantined_binding_ids: tuple = ()
    quarantined_routes: tuple = ()
    ignored_state_binding_ids: tuple = ()
    provisional: bool = False
    components: dict = field(default_factory=dict)
    warnings: tuple = field(default_factory=tuple)

    @property
    def targets(self) -> set[tuple[str, str]]:
        return {(c.target_component, c.target_port) for c in self.connections}


def _binding_index(raw: Any) -> list[tuple[int, dict]]:
    bindings = raw.get("bindings", []) if isinstance(raw, dict) else []
    if not isinstance(bindings, list):
        return []
    return [(i, b) for i, b in enumerate(bindings) if isinstance(b, dict)]


def compile_plan(raw: Any, registry: Any, *, allow_unproven: bool = False):
    """Compile a validated P1 project into a dispatch plan.

    Returns ``(plan_or_None, issues)`` where ``issues`` are
    :class:`core.errors.Diagnostic` (plus runtime gate diagnostics) sorted by
    ``(path, code, message, severity)``. Never raises on malformed input;
    malformed roots yield a ``PROJECT_SHAPE``-style diagnostic instead.
    """
    from core.errors import Diagnostic
    from core.validate import is_valid, validate_project

    def diag(code: str, path: str, message: str, severity: str = "ERROR") -> Diagnostic:
        return Diagnostic(code, path, message, severity)

    if not isinstance(raw, dict):
        return None, [diag("PROJECT_SHAPE", "/", "Root must be an object")]

    issues: list = list(getattr(registry, "issues", []) or [])
    try:
        core_issues = validate_project(raw, registry)
    except Exception as exc:  # fail closed, never propagate a traceback
        return None, sorted(
            [*issues, diag("RUNTIME_COMPILE_ERROR", "/", f"Validator raised: {exc}")],
            key=lambda d: d.sort_key(),
        )
    issues.extend(core_issues)
    # R002-03: block on ERROR in *all* merged diagnostics (project validation
    # *and* manifest-registry issues), not just the core-project subset.
    if not is_valid(issues):
        return None, sorted(issues, key=lambda d: d.sort_key())

    # Map SCHEMA_NOT_PROVEN warnings to binding ids (reuses validator output).
    unproven_idx: set[int] = set()
    for item in core_issues:
        if item.code == "SCHEMA_NOT_PROVEN" and item.path.startswith("/bindings/"):
            rest = item.path[len("/bindings/"):]
            head = rest.split("/", 1)[0]
            if head.isdigit():
                unproven_idx.add(int(head))

    indexed = _binding_index(raw)
    idx_to_id: dict[int, str] = {}
    for idx, bind in indexed:
        bid = bind.get("id")
        idx_to_id[idx] = bid if isinstance(bid, str) else f"<index:{idx}>"
    quarantined_ids = sorted({idx_to_id[i] for i in unproven_idx if i in idx_to_id})

    if quarantined_ids and not allow_unproven:
        gate = diag(
            RUNTIME_UNPROVEN_BLOCKED,
            "/bindings",
            "Project carries SCHEMA_NOT_PROVEN payload pairs "
            f"({', '.join(quarantined_ids)}); refusing unprotected dispatch. "
            "Re-run compilation with explicit allow_unproven=True for a "
            "marked provisional simulation (quarantined bindings stay blocked).",
        )
        return None, sorted([*issues, gate], key=lambda d: d.sort_key())

    # Component port metadata projection (needed for dispatch-time checks).
    components: dict[str, Any] = {}
    comp_rows = raw.get("components", [])
    if isinstance(comp_rows, list):
        for comp in comp_rows:
            if not isinstance(comp, dict):
                continue
            cid = comp.get("id")
            if not isinstance(cid, str):
                continue
            manifest = registry.resolve(comp.get("type"), comp.get("version"))
            ports: dict[str, Any] = {}
            if manifest is not None:
                for p in manifest.ports:
                    ports[p.id] = {
                        "direction": p.direction,
                        "kind": p.kind,
                        "payload_schema": copy.deepcopy(p.payload_schema),
                        "result_schema": copy.deepcopy(p.result_schema),
                    }
            components[cid] = {
                "type": comp.get("type"),
                "version": comp.get("version"),
                "ports": ports,
            }

    connections: list[Connection] = []
    ignored_state: list[str] = []
    quarantined_routes: list[tuple] = []
    for idx, bind in indexed:
        bid = idx_to_id[idx]
        if idx in unproven_idx:
            kind = bind.get("kind")
            src = bind.get("source")
            if kind in ("command", "event") and isinstance(src, dict) \
                    and src.get("owner_kind") == "component":
                quarantined_routes.append(
                    (bid, kind, src.get("owner_id"), src.get("port")))
            continue  # quarantined: never part of the dispatch table
        kind = bind.get("kind")
        if kind not in ("command", "event"):
            if kind == "state":
                ignored_state.append(bid)
            continue  # unknown kinds already rejected by the validator
        src, dst = bind.get("source"), bind.get("target")
        if not (isinstance(src, dict) and isinstance(dst, dict)):
            continue  # defensive: validator would have flagged this as ERROR
        if src.get("owner_kind") != "component" or dst.get("owner_kind") != "component":
            continue  # only component-to-component dispatch in this spike
        s_comp, s_port = src.get("owner_id"), src.get("port")
        t_comp, t_port = dst.get("owner_id"), dst.get("port")
        s_meta = components.get(s_comp, {}).get("ports", {}).get(s_port)
        t_meta = components.get(t_comp, {}).get("ports", {}).get(t_port)
        if s_meta is None or t_meta is None:
            gate = diag(
                RUNTIME_ENDPOINT_UNKNOWN,
                f"/bindings/{idx}",
                f"Binding {bid!r} endpoint no longer resolvable; refusing compilation.",
            )
            return None, sorted([*issues, gate], key=lambda d: d.sort_key())
        connections.append(
            Connection(
                binding_id=bid,
                kind=kind,
                source_component=s_comp,
                source_port=s_port,
                target_component=t_comp,
                target_port=t_port,
                source_schema=copy.deepcopy(s_meta["payload_schema"]),
                target_schema=copy.deepcopy(t_meta["payload_schema"]),
                target_result_schema=copy.deepcopy(t_meta["result_schema"]),
            )
        )

    # SPIKE_ONLY ordering: lexical by binding id (deterministic, not normative).
    connections.sort(key=lambda c: c.binding_id)
    ignored_state.sort()

    warnings = tuple(i for i in issues if getattr(i, "severity", "ERROR") != "ERROR")
    provisional = bool(quarantined_ids) and bool(allow_unproven)
    notes = list(issues)
    if provisional:
        notes.append(
            diag(
                RUNTIME_UNPROVEN_PROVISIONAL,
                "/bindings",
                "Provisional simulation: quarantined bindings "
                f"({', '.join(sorted(quarantined_ids))}) stay blocked with "
                "RUNTIME_UNPROVEN_BLOCKED diagnostics; no unprotected pass-through.",
                "WARNING",
            )
        )
    meta = raw.get("project", {})
    project_id = meta.get("id") if isinstance(meta, dict) else ""
    plan = ConnectionPlan(
        project_id=project_id if isinstance(project_id, str) else "",
        connections=tuple(connections),
        quarantined_binding_ids=tuple(sorted(quarantined_ids)),
        quarantined_routes=tuple(sorted(quarantined_routes)),
        ignored_state_binding_ids=tuple(ignored_state),
        provisional=provisional,
        components=components,
        warnings=warnings,
    )
    return plan, sorted(notes, key=lambda d: d.sort_key())
