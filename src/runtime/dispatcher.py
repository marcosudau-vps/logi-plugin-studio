"""Synchronous deterministic In-Memory dispatch for AP-CORE-002.

SPIKE_ONLY scaffolding, not a normative runtime API:

- ``command`` and ``event`` are strictly separated dispatch entry points
  (P0-ADR-003). No automatic success events, no implicit state writes —
  a handler result is just a result.
- A handler may *explicitly* emit follow-up ``event`` messages from its own
  component's ``out``/``event`` ports by returning
  ``{"result": ..., "emit": [{"port": ..., "payload": ...}, ...]}``.
  This is a test convenience, **not** the future host-callback contract.
- Fan-out order over one source is lexical by ``binding_id`` (SPIKE_ONLY).
- Reentrancy is bounded by ``MAX_DEPTH`` nested emissions (SPIKE_ONLY guard,
  not a normative retry/reentrancy policy).
- Every faulty input yields a structured report; dispatch never raises for
  bad payloads, unknown endpoints, missing handlers or handler exceptions.
  Only programming errors at registration time raise
  :class:`runtime.errors.RegistrationError` (with a ``code``).

Standard library only. No sockets, no threads, no Qt/Logitech imports.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from .errors import (
    DISPATCH_EMIT_INVALID,
    DISPATCH_ENDPOINT_UNKNOWN,
    DISPATCH_HANDLER_ERROR,
    DISPATCH_KIND_MISMATCH,
    DISPATCH_NO_HANDLER,
    DISPATCH_NO_ROUTE,
    DISPATCH_PAYLOAD_INVALID,
    DISPATCH_REENTRANCY_LIMIT,
    DISPATCH_RESULT_INVALID,
    DISPATCH_UNPROVEN_BLOCKED,
    DispatchIssue,
    RegistrationError,
)

MAX_DEPTH = 8
ALLOWED_HANDLER_KEYS = frozenset({"result", "emit"})


def _is_json_like(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str, int, float)):
        return True
    if isinstance(value, list):
        return all(_is_json_like(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_like(v) for k, v in value.items())
    return False


class InMemoryRuntime:
    """Dispatches commands/events over a compiled :class:`ConnectionPlan`."""

    def __init__(self, plan: Any) -> None:
        if plan is None:
            raise RegistrationError(
                code="RUNTIME_NO_PLAN", path="/", message="Runtime requires a compiled plan"
            )
        self._plan = plan
        self._handlers: dict[tuple[str, str], Callable] = {}

    @property
    def plan(self) -> Any:
        return self._plan

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

    # -- registration ----------------------------------------------------
    def register_handler(self, component_id: str, port_id: str, fn: Callable) -> None:
        from core.ids import is_valid_id

        if not is_valid_id(component_id) or not is_valid_id(port_id):
            raise RegistrationError(
                code=DISPATCH_ENDPOINT_UNKNOWN,
                path=f"/handlers/{component_id}/{port_id}",
                message=f"Invalid handler endpoint {component_id!r}:{port_id!r}",
            )
        if not callable(fn):
            raise RegistrationError(
                code=DISPATCH_NO_HANDLER,
                path=f"/handlers/{component_id}/{port_id}",
                message="Handler must be callable",
            )
        self._handlers[(component_id, port_id)] = fn

    def unregister_handler(self, component_id: str, port_id: str) -> bool:
        return self._handlers.pop((component_id, port_id), None) is not None

    # -- public entry points ---------------------------------------------
    def dispatch_command(
        self,
        source_component: str,
        source_port: str,
        payload: Any,
        *,
        correlation_id: Any = None,
    ) -> dict:
        return self._dispatch(
            "command", source_component, source_port, payload,
            correlation_id=correlation_id, depth=0,
        )

    def dispatch_event(
        self,
        source_component: str,
        source_port: str,
        payload: Any,
        *,
        correlation_id: Any = None,
    ) -> dict:
        return self._dispatch(
            "event", source_component, source_port, payload,
            correlation_id=correlation_id, depth=0,
        )

    # -- core --------------------------------------------------------------
    def _source_meta(self, component: str, port: str) -> dict | None:
        # Defensive against unhashable/mistyped keys (R002-01): any lookup
        # failure yields None (structured EMIT/ENDPOINT diagnostics upstream).
        try:
            comp = self._plan.components.get(component)
        except TypeError:
            return None
        if not isinstance(comp, dict):
            return None
        try:
            meta = comp.get("ports", {}).get(port)
        except (AttributeError, TypeError):
            return None
        return meta if isinstance(meta, dict) else None

    def _dispatch(
        self,
        kind: str,
        source_component: str,
        source_port: str,
        payload: Any,
        *,
        correlation_id: Any,
        depth: int,
    ) -> dict:
        from core.compat import check_value
        from core.ids import is_valid_id

        base: dict[str, Any] = {
            "kind": kind,
            "source": {"component": source_component, "port": source_port},
            "correlation_id": correlation_id,
            "status": "DISPATCHED",
            "deliveries": [],
            "diagnostics": [],
        }
        if depth > MAX_DEPTH:
            base["status"] = "REJECTED"
            base["diagnostics"] = [{
                "code": DISPATCH_REENTRANCY_LIMIT,
                "path": "/depth",
                "message": f"Maximum nested emission depth ({MAX_DEPTH}) exceeded; "
                           "refusing further dispatch (SPIKE_ONLY guard).",
            }]
            return base
        if not is_valid_id(source_component) or not is_valid_id(source_port):
            base["status"] = "REJECTED"
            base["diagnostics"] = [{
                "code": DISPATCH_ENDPOINT_UNKNOWN,
                "path": "/source",
                "message": f"Unknown source endpoint {source_component!r}:{source_port!r}",
            }]
            return base
        meta = self._source_meta(source_component, source_port)
        if meta is None:
            base["status"] = "REJECTED"
            base["diagnostics"] = [{
                "code": DISPATCH_ENDPOINT_UNKNOWN,
                "path": "/source",
                "message": f"Unknown source endpoint {source_component!r}:{source_port!r}",
            }]
            return base
        if meta.get("direction") != "out" or meta.get("kind") != kind:
            base["status"] = "REJECTED"
            base["diagnostics"] = [{
                "code": DISPATCH_KIND_MISMATCH,
                "path": "/source",
                "message": f"Source {source_component!r}:{source_port!r} is "
                           f"{meta.get('direction')}/{meta.get('kind')}; "
                           f"{kind} dispatch requires out/{kind}",
            }]
            return base

        incoming: Any = None
        try:
            # R002-02: copy before any schema inspection, but fail closed —
            # non-copyable / non-JSON-compatible inputs (e.g. memoryview)
            # are rejected structurally instead of raising TypeError.
            incoming = copy.deepcopy(payload)
        except Exception:
            base["status"] = "REJECTED"
            base["diagnostics"] = [{
                "code": DISPATCH_PAYLOAD_INVALID,
                "path": "/payload",
                "message": f"Payload of type {type(payload).__name__} is not "
                           "processable; only JSON-compatible values are accepted.",
            }]
            return base
        problems = check_value(incoming, meta.get("payload_schema", {}))
        if problems:
            base["status"] = "REJECTED"
            base["diagnostics"] = [
                {"code": code if code.startswith(("VALUE_", "SCHEMA_")) else DISPATCH_PAYLOAD_INVALID,
                 "path": "/payload", "message": detail}
                for code, detail in problems
            ]
            return base

        routes = [c for c in self._plan.connections
                  if c.kind == kind and c.source_component == source_component
                  and c.source_port == source_port]
        quarantined = [
            bid for bid in self._plan.quarantined_binding_ids
            if self._binding_belongs_to_source(bid, kind, source_component, source_port)
        ]
        if not routes:
            base["status"] = "REJECTED"
            if quarantined:
                base["diagnostics"] = [{
                    "code": DISPATCH_UNPROVEN_BLOCKED,
                    "path": "/bindings",
                    "message": "All routes for this source are quarantined "
                               f"({', '.join(sorted(quarantined))}); no unprotected "
                               "pass-through (provisional plan).",
                }]
            else:
                base["diagnostics"] = [{
                    "code": DISPATCH_NO_ROUTE,
                    "path": "/bindings",
                    "message": f"No {kind} binding routes from "
                               f"{source_component!r}:{source_port!r}",
                }]
            return base

        deliveries: list[dict] = []
        for conn in routes:  # already lexical by binding_id (SPIKE_ONLY)
            deliveries.append(self._deliver(
                conn, copy.deepcopy(incoming),
                correlation_id=correlation_id, depth=depth,
            ))
        base["deliveries"] = deliveries
        if quarantined:
            base["diagnostics"] = [{
                "code": DISPATCH_UNPROVEN_BLOCKED,
                "path": "/bindings",
                "message": "Quarantined bindings skipped without pass-through: "
                           f"{', '.join(sorted(quarantined))}.",
            }]
        return base

    def _binding_belongs_to_source(
        self, binding_id: str, kind: str, component: str, port: str
    ) -> bool:
        # Quarantined bindings are kept out of plan.connections; membership is
        # answered from the plan-level quarantine route table recorded at
        # compile time (binding_id, kind, source_component, source_port).
        return (binding_id, kind, component, port) in set(
            getattr(self._plan, "quarantined_routes", ()))

    def _deliver(self, conn: Any, payload: Any, *, correlation_id: Any, depth: int) -> dict:
        from core.compat import check_value

        target_problems = check_value(payload, conn.target_schema)
        if target_problems:
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": DISPATCH_PAYLOAD_INVALID,
                "issues": [
                    {"code": c if c.startswith(("VALUE_", "SCHEMA_")) else DISPATCH_PAYLOAD_INVALID,
                     "path": f"/bindings/{conn.binding_id}/payload", "message": d}
                    for c, d in target_problems
                ],
                "result": None,
                "emitted": [],
            }
        fn = self._handlers.get((conn.target_component, conn.target_port))
        if fn is None:
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": DISPATCH_NO_HANDLER,
                "issues": [{
                    "code": DISPATCH_NO_HANDLER,
                    "path": f"/bindings/{conn.binding_id}",
                    "message": f"No handler registered for "
                               f"{conn.target_component!r}:{conn.target_port!r}",
                }],
                "result": None,
                "emitted": [],
            }
        ctx = {
            "kind": conn.kind,
            "binding_id": conn.binding_id,
            "source_component": conn.source_component,
            "source_port": conn.source_port,
            "target_component": conn.target_component,
            "target_port": conn.target_port,
            "correlation_id": correlation_id,
            "depth": depth,
        }
        try:
            returned = fn(copy.deepcopy(payload), dict(ctx))
        except Exception as exc:  # structured, never propagated
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": DISPATCH_HANDLER_ERROR,
                "issues": [{
                    "code": DISPATCH_HANDLER_ERROR,
                    "path": f"/bindings/{conn.binding_id}",
                    "message": f"Handler raised {type(exc).__name__}: {exc}",
                }],
                "result": None,
                "emitted": [],
            }
        return self._finish_delivery(conn, returned, ctx, depth=depth)

    def _finish_delivery(self, conn: Any, returned: Any, ctx: dict, *, depth: int) -> dict:
        from core.compat import check_value
        from core.ids import is_valid_id

        if returned is None:
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": "OK",
                "issues": [],
                "result": None,
                "emitted": [],
            }
        result_value: Any = None
        emit_list: list = []
        try:
            # R002-02 (handler side): handler returns are copied fail-closed;
            # a non-copyable result must not escape as an uncaught exception.
            if isinstance(returned, dict) and set(returned) <= ALLOWED_HANDLER_KEYS:
                result_value = copy.deepcopy(returned.get("result"))
                emit_list = returned.get("emit", [])
                if emit_list is None:
                    emit_list = []
            else:
                result_value = copy.deepcopy(returned)
        except Exception:
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": DISPATCH_RESULT_INVALID,
                "issues": [{
                    "code": DISPATCH_RESULT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/result",
                    "message": "Handler result is not processable; only "
                               "JSON-compatible values are accepted.",
                }],
                "result": None,
                "emitted": [],
            }

        if conn.kind == "command" and conn.target_result_schema is not None:
            res_problems = check_value(result_value, conn.target_result_schema)
            if res_problems:
                return {
                    "binding_id": conn.binding_id,
                    "target": {"component": conn.target_component, "port": conn.target_port},
                    "status": DISPATCH_RESULT_INVALID,
                    "issues": [
                        {"code": c if c.startswith(("VALUE_", "SCHEMA_")) else DISPATCH_RESULT_INVALID,
                         "path": f"/bindings/{conn.binding_id}/result", "message": d}
                        for c, d in res_problems
                    ],
                    "result": None,
                    "emitted": [],
                }
        if emit_list is not None and not isinstance(emit_list, list):
            return {
                "binding_id": conn.binding_id,
                "target": {"component": conn.target_component, "port": conn.target_port},
                "status": DISPATCH_EMIT_INVALID,
                "issues": [{
                    "code": DISPATCH_EMIT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/emit",
                    "message": "'emit' must be a list of {port, payload} entries",
                }],
                "result": result_value,
                "emitted": [],
            }

        emitted_reports: list = []
        emit_issues: list = []
        for pos, entry in enumerate(emit_list or []):
            if not isinstance(entry, dict) or "port" not in entry or "payload" not in entry:
                emit_issues.append({
                    "code": DISPATCH_EMIT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/emit/{pos}",
                    "message": "Each emit entry requires {port, payload}",
                })
                continue
            out_port = entry["port"]
            # R002-01: validate the port value before any dict-key use so
            # malformed emit entries (list/dict/None/...) yield a structured
            # RUNTIME_EMIT_INVALID instead of an uncaught TypeError.
            if not isinstance(out_port, str) or not is_valid_id(out_port):
                emit_issues.append({
                    "code": DISPATCH_EMIT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/emit/{pos}",
                    "message": f"Emit port {out_port!r} is not a valid port identifier; "
                               "only the handler's own component out/event ports "
                               "may emit (SPIKE_ONLY).",
                })
                continue
            out_meta = self._source_meta(conn.target_component, out_port)
            if out_meta is None or out_meta.get("direction") != "out" or out_meta.get("kind") != "event":
                emit_issues.append({
                    "code": DISPATCH_EMIT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/emit/{pos}",
                    "message": f"Emit port {out_port!r} is not an out/event port of "
                               f"{conn.target_component!r}; only the handler's own "
                               "component out/event ports may emit (SPIKE_ONLY).",
                })
                continue
            nested_payload: Any = None
            try:
                nested_payload = copy.deepcopy(entry["payload"])
            except Exception:
                emit_issues.append({
                    "code": DISPATCH_EMIT_INVALID,
                    "path": f"/bindings/{conn.binding_id}/emit/{pos}",
                    "message": "Emit payload is not processable; only "
                               "JSON-compatible values are accepted.",
                })
                continue
            nested = self._dispatch(
                "event", conn.target_component, out_port,
                nested_payload,
                correlation_id=ctx.get("correlation_id"), depth=depth + 1,
            )
            emitted_reports.append({
                "port": out_port,
                "report": nested,
            })
        status = "OK" if not emit_issues else DISPATCH_EMIT_INVALID
        issues = emit_issues
        return {
            "binding_id": conn.binding_id,
            "target": {"component": conn.target_component, "port": conn.target_port},
            "status": status,
            "issues": issues,
            "result": result_value,
            "emitted": emitted_reports,
        }
