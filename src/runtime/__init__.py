"""AP-CORE-002 dispatch spike, AP-CORE-003 StateStore and AP-CORE-004 sync.

Dispatch-Seite (dispatcher/plan): SPIKE_ONLY, experimentell, nicht normativ.
StateStore-Seite (state_store): In-Memory-MVP gemaess RT-ADR-001..006; keine
Persistenz, keine Threads.
Sync-Seite (sync/fake_transport): rein manuell gesteuerter Fake-Transport,
SPIKE_ONLY, kein Wire-Protokoll und keine echte Authentisierung.
Standard library plus core.* only.
"""
from __future__ import annotations

from .dispatcher import MAX_DEPTH, InMemoryRuntime
from .errors import (
    STATE_AUTH_VIOLATION,
    STATE_DEFINITION_UNKNOWN,
    STATE_EPOCH_REUSE,
    STATE_NO_VALUE,
    STATE_OK,
    STATE_SCOPE_MISMATCH,
    STATE_SCOPE_UNKNOWN,
    STATE_SCOPE_UNSUPPORTED,
    STATE_VALUE_INVALID,
    DispatchIssue,
    RegistrationError,
)
from .fake_transport import (
    FakeTransport,
    FakeTransportTrust,
    SYNC_SCHEMA_VERSION,
)
from .plan import Connection, ConnectionPlan, compile_plan
from .state_store import ScopeAddress, StateStore, WriterIdentity, compare_positions
from .sync import SyncLink, SyncMirror, SyncSource

__all__ = [
    "Connection",
    "ConnectionPlan",
    "DispatchIssue",
    "FakeTransport",
    "FakeTransportTrust",
    "InMemoryRuntime",
    "MAX_DEPTH",
    "RegistrationError",
    "SYNC_SCHEMA_VERSION",
    "ScopeAddress",
    "StateStore",
    "SyncLink",
    "SyncMirror",
    "SyncSource",
    "WriterIdentity",
    "compare_positions",
    "compile_plan",
    "STATE_AUTH_VIOLATION",
    "STATE_DEFINITION_UNKNOWN",
    "STATE_EPOCH_REUSE",
    "STATE_NO_VALUE",
    "STATE_OK",
    "STATE_SCOPE_MISMATCH",
    "STATE_SCOPE_UNKNOWN",
    "STATE_SCOPE_UNSUPPORTED",
    "STATE_VALUE_INVALID",
]

__version__ = "0.3.1-sync-spike"
