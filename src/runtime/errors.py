"""Structured dispatch diagnostics for the AP-CORE-002 In-Memory spike.

SPIKE_ONLY: these codes are provisional test scaffolding, not a normative
runtime API (P0-ADR-003/007 remain the binding contract for diagnostics shape
``{code, path, message}``). No transport, no threads, no Logitech/Qt imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# --- compile-stage codes (returned alongside core validator diagnostics) ---
RUNTIME_UNPROVEN_BLOCKED = "RUNTIME_UNPROVEN_BLOCKED"
RUNTIME_UNPROVEN_PROVISIONAL = "RUNTIME_UNPROVEN_PROVISIONAL"
RUNTIME_ENDPOINT_UNKNOWN = "RUNTIME_ENDPOINT_UNKNOWN"

# --- dispatch-stage codes ---
DISPATCH_OK = "OK"
DISPATCH_NO_ROUTE = "RUNTIME_NO_ROUTE"
DISPATCH_ENDPOINT_UNKNOWN = "RUNTIME_ENDPOINT_UNKNOWN"
DISPATCH_KIND_MISMATCH = "RUNTIME_KIND_MISMATCH"
DISPATCH_PAYLOAD_INVALID = "RUNTIME_PAYLOAD_INVALID"
DISPATCH_NO_HANDLER = "RUNTIME_NO_HANDLER"
DISPATCH_HANDLER_ERROR = "RUNTIME_HANDLER_ERROR"
DISPATCH_RESULT_INVALID = "RUNTIME_RESULT_INVALID"
DISPATCH_UNPROVEN_BLOCKED = "RUNTIME_UNPROVEN_BLOCKED"
DISPATCH_REENTRANCY_LIMIT = "RUNTIME_REENTRANCY_LIMIT"
DISPATCH_EMIT_INVALID = "RUNTIME_EMIT_INVALID"

# --- state-store codes (AP-CORE-003, RT-ADR-002/003) ---------------------
# Structured result codes for the in-memory StateStore. Same diagnostic shape
# ``{code, path, message}`` (P0-ADR-007). No transport, no persistence.
STATE_OK = "OK"
STATE_DEFINITION_UNKNOWN = "STATE_DEFINITION_UNKNOWN"
STATE_SCOPE_UNKNOWN = "STATE_SCOPE_UNKNOWN"
STATE_SCOPE_MISMATCH = "STATE_SCOPE_MISMATCH"
STATE_SCOPE_UNSUPPORTED = "STATE_SCOPE_UNSUPPORTED"
STATE_EPOCH_REUSE = "STATE_EPOCH_REUSE"
STATE_AUTH_VIOLATION = "STATE_AUTH_VIOLATION"
STATE_VALUE_INVALID = "STATE_VALUE_INVALID"
STATE_NO_VALUE = "STATE_NO_VALUE"


@dataclass(frozen=True)
class DispatchIssue:
    """Single structured issue inside a delivery or report."""

    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class RegistrationError(ValueError):
    """Programming error at handler-registration time (carries a code)."""

    code: str = DISPATCH_ENDPOINT_UNKNOWN
    path: str = "/"
    message: str = "Invalid handler registration"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class Delivery:
    """Outcome of one binding traversal (deterministic, JSON-plain)."""

    binding_id: str
    target_component: str
    target_port: str
    status: str
    issues: tuple = field(default_factory=tuple)
    result: object = None
    emitted: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "binding_id": self.binding_id,
            "target": {"component": self.target_component, "port": self.target_port},
            "status": self.status,
            "issues": [i.as_dict() if isinstance(i, DispatchIssue) else dict(i) for i in self.issues],
            "result": self.result,
            "emitted": list(self.emitted),
        }
