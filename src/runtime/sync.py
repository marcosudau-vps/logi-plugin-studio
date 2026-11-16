"""Deterministic snapshot/delta sync spike over a fake transport (AP-CORE-004).

SPIKE_ONLY. This is an experimental, in-memory proof of the RT-ADR-003
principles, not a wire protocol, not a distributed-consensus mechanism and
not network authentication:

- ``SyncSource`` wraps exactly one :class:`runtime.state_store.StateStore`.
  It emits a handshake marker, one complete snapshot and only *explicitly
  confirmed* state updates as deltas. A command result is never reinterpreted
  as a state update.
- ``SyncMirror`` is a read-only, non-authoritative replica. It accepts a
  snapshot as its baseline and then only deltas whose runtime origin, session
  generation, authority epoch, expected stream position and revision all match.
  Gaps/duplicates/reordered/late messages never overwrite a value silently.
- ``SyncLink`` is a small convenience wiring of source, mirror and the manual
  :class:`runtime.fake_transport.FakeTransport`.

Boundaries proven here: initial snapshot, explicit deltas, drop/gap, duplicate,
reorder, late message, disconnect/reconnect with a new session, authority-epoch
switch with revision reset, origin isolation, malformed frames and defensive
copies. Everything beyond that (ACK, retry, timeout, backoff, real transport,
persistence, queue limits, authentication) remains ``OPEN``. See
``work/runs/RUN-AP-CORE-004-01/06_sync_vertragsvorschlag.md``.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from .fake_transport import (
    FRAME_TYPES,
    SPIKE_ONLY,
    SYNC_SCHEMA_VERSION,
    FakeTransport,
    FakeTransportTrust,
)
from .state_store import QUALITIES, SCOPE_KINDS, ScopeAddress

SYNC_OK = "OK"
SYNC_HANDSHAKE_ACCEPTED = "SYNC_HANDSHAKE_ACCEPTED"
SYNC_SNAPSHOT_APPLIED = "SYNC_SNAPSHOT_APPLIED"
SYNC_DELTA_APPLIED = "SYNC_DELTA_APPLIED"
SYNC_STALE_IGNORED = "SYNC_STALE_IGNORED"
SYNC_DUPLICATE = "SYNC_DUPLICATE"
SYNC_STREAM_GAP = "SYNC_STREAM_GAP"
SYNC_REVISION_GAP = "SYNC_REVISION_GAP"
SYNC_EPOCH_MISMATCH = "SYNC_EPOCH_MISMATCH"
SYNC_SESSION_MISMATCH = "SYNC_SESSION_MISMATCH"
SYNC_GENERATION_MISMATCH = "SYNC_GENERATION_MISMATCH"
SYNC_ORIGIN_MISMATCH = "SYNC_ORIGIN_MISMATCH"
SYNC_UNTRUSTED = "SYNC_UNTRUSTED"
SYNC_FRAME_INVALID = "SYNC_FRAME_INVALID"
SYNC_NOT_READY = "SYNC_NOT_READY"
SYNC_NOT_CONNECTED = "SYNC_NOT_CONNECTED"
SYNC_UNKNOWN_STATE = "SYNC_UNKNOWN_STATE"
SYNC_UPDATE_NOT_CONFIRMED = "SYNC_UPDATE_NOT_CONFIRMED"
SYNC_UPDATE_MISMATCH = "SYNC_UPDATE_MISMATCH"

LIFECYCLE_STATES = ("disconnected", "connecting", "synchronizing", "ready", "degraded")

_HEADER_STRING_FIELDS = (
    "message_id", "runtime_instance_id", "session_id", "epoch",
)
_HEADER_INT_FIELDS = ("stream_seq", "stream_generation", "epoch_seq")


def _issue(code: str, path: str, message: str) -> dict:
    return {"code": code, "path": path, "message": message}


def _copy_ok(value: Any) -> tuple[bool, Any]:
    try:
        return True, copy.deepcopy(value)
    except Exception:
        return False, None


def _report(status: str, issues: list | None = None, **extra: Any) -> dict:
    out = {"status": status, "issues": list(issues or [])}
    out.update(extra)
    return out


def _header_issues(frame: dict) -> list[dict]:
    issues: list[dict] = []
    if frame.get("schema_version") != SYNC_SCHEMA_VERSION:
        issues.append(_issue(
            SYNC_FRAME_INVALID, "/schema_version",
            f"Unsupported spike schema {frame.get('schema_version')!r}; "
            f"expected {SYNC_SCHEMA_VERSION!r}."))
    if frame.get("spike_only") is not SPIKE_ONLY:
        issues.append(_issue(
            SYNC_FRAME_INVALID, "/spike_only",
            "Frame must carry the explicit spike_only marker."))
    if frame.get("type") not in FRAME_TYPES:
        issues.append(_issue(
            SYNC_FRAME_INVALID, "/type",
            f"Unknown frame type {frame.get('type')!r}."))
    for name in _HEADER_STRING_FIELDS:
        value = frame.get(name)
        if not isinstance(value, str) or not value:
            issues.append(_issue(
                SYNC_FRAME_INVALID, f"/{name}",
                f"Frame field {name!r} must be a non-empty string."))
    for name in _HEADER_INT_FIELDS:
        value = frame.get(name)
        minimum = 1 if name != "epoch_seq" else 0
        if type(value) is not int or value < minimum:
            issues.append(_issue(
                SYNC_FRAME_INVALID, f"/{name}",
                f"Frame field {name!r} must be an integer >= {minimum}."))
    return issues


def _scope_from_dict(value: Any) -> tuple[ScopeAddress | None, str | None]:
    if not isinstance(value, dict):
        return None, "scope must be an object"
    allowed = {"kind", "component_id", "placement_id"}
    if set(value) - allowed:
        return None, f"scope carries unsupported fields {sorted(set(value) - allowed)}"
    address = ScopeAddress(
        kind=value.get("kind"),
        component_id=value.get("component_id"),
        placement_id=value.get("placement_id"),
    )
    problem = address.canonical_problem()
    if problem:
        return None, problem
    return address, None


@dataclass
class _MirrorEntry:
    state_id: str
    scope: dict
    key: str
    value: Any = None
    has_value: bool = False
    quality: str = "unknown"
    revision: int = 0
    epoch: str = ""
    epoch_seq: int = 0

    def as_dict(self) -> dict:
        ok, value = _copy_ok(self.value) if self.has_value else (True, None)
        return {
            "state_id": self.state_id,
            "scope": copy.deepcopy(self.scope),
            "scope_key": self.key,
            "value": value if ok else None,
            "has_value": self.has_value and ok,
            "quality": self.quality,
            "revision": self.revision,
            "epoch": self.epoch,
            "epoch_seq": self.epoch_seq,
        }


class SyncSource:
    """Authoritative side: snapshot and explicit state deltas from one store."""

    def __init__(self, store: Any, transport: FakeTransport, *,
                 trust: FakeTransportTrust | None = None) -> None:
        if getattr(store, "runtime_instance_id", None) is None:
            raise TypeError("SyncSource requires a StateStore")
        if not isinstance(transport, FakeTransport):
            raise TypeError("SyncSource requires a FakeTransport")
        self._store = store
        self._transport = transport
        self._trust = trust or transport.trust
        if transport.trust is not self._trust:
            raise ValueError("source trust must be the transport trust object")
        self._session_id: str | None = None
        self._generation = 0
        self._message_seq = 0

    @property
    def store(self) -> Any:
        return self._store

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def stream_generation(self) -> int:
        return self._generation

    def start_session(self, session_id: str | None = None) -> dict:
        """Emit the fake handshake; a reconnect always opens a new session."""
        if session_id is None:
            session_id = f"session.{uuid.uuid4().hex}"
        if not isinstance(session_id, str) or not session_id:
            return _report(SYNC_NOT_CONNECTED, [_issue(
                SYNC_NOT_CONNECTED, "/session_id",
                "session_id must be a non-empty string.")])
        self._generation += 1
        self._session_id = session_id
        payload = {
            "source": "fake.inmemory",
            "source_kind": "SPIKE_ONLY",
            "capabilities": ["snapshot", "state.delta"],
            "session_generation": self._generation,
        }
        frame = self._frame("handshake", payload)
        sent = self._transport.send(frame)
        return _report(
            sent["status"], session_id=session_id,
            stream_generation=self._generation, frame=sent.get("frame"),
            pending=sent.get("pending"),
        )

    def send_snapshot(self) -> dict:
        """Take one atomic in-memory store snapshot and enqueue it."""
        if self._session_id is None:
            return _report(SYNC_NOT_CONNECTED, [_issue(
                SYNC_NOT_CONNECTED, "/session",
                "A snapshot requires a started session.")])
        snapshot = self._store.snapshot()
        if snapshot.get("status") != SYNC_OK:
            return _report(SYNC_FRAME_INVALID, list(snapshot.get("issues", [])))
        states: dict[str, Any] = {}
        for key, item in snapshot.get("states", {}).items():
            ok, value = _copy_ok(item.get("value")) if item.get("has_value") else (True, None)
            states[key] = {
                "state_id": item.get("state_id"),
                "scope": copy.deepcopy(item.get("scope")),
                "value": value if ok else None,
                "has_value": bool(item.get("has_value")) and ok,
                "quality": item.get("quality"),
                "revision": item.get("revision"),
                "epoch": item.get("epoch"),
                "epoch_seq": item.get("epoch_seq"),
            }
        payload = {
            "snapshot_epoch": snapshot.get("epoch"),
            "snapshot_epoch_seq": snapshot.get("epoch_seq"),
            "state_count": len(states),
            "states": states,
        }
        frame = self._frame(
            "snapshot", payload,
            epoch=snapshot.get("epoch"), epoch_seq=snapshot.get("epoch_seq"),
            runtime_instance_id=snapshot.get("runtime_instance_id"),
        )
        sent = self._transport.send(frame)
        return _report(sent["status"], state_count=len(states),
                       frame=sent.get("frame"), pending=sent.get("pending"))

    def publish_update(self, state_id: str, scope: ScopeAddress, *,
                       write_result: Any) -> dict:
        """Emit a delta only for an explicitly confirmed store write.

        ``write_result`` must be the ``OK`` return value of
        :meth:`StateStore.write` for exactly the current store position. A
        handler result, event or any other value is never interpreted here.
        """
        if not isinstance(write_result, dict) or write_result.get("status") != SYNC_OK:
            return _report(SYNC_UPDATE_NOT_CONFIRMED, [_issue(
                SYNC_UPDATE_NOT_CONFIRMED, "/write_result",
                "Only an explicit StateStore write result with status OK may "
                "produce a delta; command results are never reinterpreted.")])
        if not isinstance(scope, ScopeAddress):
            return _report(SYNC_UPDATE_MISMATCH, [_issue(
                SYNC_UPDATE_MISMATCH, "/scope",
                "A confirmed delta requires a canonical ScopeAddress.")])
        problem = scope.canonical_problem()
        if problem:
            return _report(SYNC_UPDATE_MISMATCH, [_issue(
                SYNC_UPDATE_MISMATCH, "/scope", problem)])
        expected_slot = scope.key_string(state_id)
        current = self._store.read(state_id, scope)
        if current.get("status") != SYNC_OK or not current.get("has_value"):
            return _report(SYNC_UPDATE_NOT_CONFIRMED, list(current.get("issues", [])) or [
                _issue(SYNC_UPDATE_NOT_CONFIRMED, "/write_result",
                       "The store does not hold a confirmed live value.")])
        # A write confirmation belongs to exactly one canonical state slot.
        # Matching revision/epoch numbers alone must never authorize a delta
        # for a different slot, even if both slots happen to be at the same
        # revision.
        confirmed_slot = write_result.get("scope_key")
        if not isinstance(confirmed_slot, str) or not confirmed_slot:
            return _report(SYNC_UPDATE_MISMATCH, [_issue(
                SYNC_UPDATE_MISMATCH, "/write_result/scope_key",
                "The confirmation carries no canonical scope_key; no delta is "
                "emitted.")])
        if confirmed_slot != expected_slot:
            return _report(SYNC_UPDATE_MISMATCH, [_issue(
                SYNC_UPDATE_MISMATCH, "/write_result/scope_key",
                f"Confirmation slot {confirmed_slot!r} does not match the "
                f"expected slot {expected_slot!r}; no delta is emitted.")])
        if current.get("quality") != "fresh":
            return _report(SYNC_UPDATE_NOT_CONFIRMED, [_issue(
                SYNC_UPDATE_NOT_CONFIRMED, "/write_result",
                "The confirmed store value is not fresh; no delta is emitted.")])
        for name in ("revision", "epoch", "epoch_seq"):
            if write_result.get(name) != current.get(name):
                return _report(SYNC_UPDATE_MISMATCH, [_issue(
                    SYNC_UPDATE_MISMATCH, "/write_result",
                    f"Confirmed position {name!r} does not match the current "
                    "store position; no delta is emitted.")])
        if self._session_id is None:
            return _report(SYNC_NOT_CONNECTED, [_issue(
                SYNC_NOT_CONNECTED, "/session",
                "A delta requires a started session.")])
        ok, value = _copy_ok(current.get("value"))
        if not ok:
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/payload/value",
                "Confirmed value is not processable; no delta is emitted.")])
        payload = {
            "state_id": state_id,
            "scope": copy.deepcopy(current.get("scope")),
            "value": value,
            "has_value": True,
            "quality": current.get("quality"),
            "revision": current.get("revision"),
            "epoch": current.get("epoch"),
            "epoch_seq": current.get("epoch_seq"),
        }
        frame = self._frame("delta", payload)
        sent = self._transport.send(frame)
        return _report(sent["status"], frame=sent.get("frame"),
                       pending=sent.get("pending"))

    def _frame(self, frame_type: str, payload: dict, *,
               epoch: str | None = None,
               epoch_seq: int | None = None,
               runtime_instance_id: str | None = None) -> dict:
        self._message_seq += 1
        return {
            "schema_version": SYNC_SCHEMA_VERSION,
            "spike_only": SPIKE_ONLY,
            "type": frame_type,
            "message_id": f"msg.{self._message_seq:06d}",
            "stream_seq": self._transport.next_stream_seq(),
            "runtime_instance_id": runtime_instance_id
            if runtime_instance_id is not None else self._store.runtime_instance_id,
            "session_id": self._session_id,
            "stream_generation": self._generation,
            "epoch": epoch if epoch is not None else self._store.epoch,
            "epoch_seq": epoch_seq if epoch_seq is not None else self._store.epoch_seq,
            "payload": payload,
        }


class SyncMirror:
    """Read-only replica; never authoritative, never writes back."""

    def __init__(self, trust: FakeTransportTrust) -> None:
        if not isinstance(trust, FakeTransportTrust):
            raise TypeError("SyncMirror requires an injected FakeTransportTrust")
        self._trust = trust
        self._state = "disconnected"
        self._entries: dict[str, _MirrorEntry] = {}
        self._origin: str | None = None
        self._session_id: str | None = None
        self._generation: int | None = None
        self._epoch: str | None = None
        self._epoch_seq: int | None = None
        self._expected_seq: int | None = None
        self._last_snapshot_seq: int | None = None
        self._resync_required = False

    # -- inspection -------------------------------------------------------
    @property
    def lifecycle(self) -> str:
        return self._state

    @property
    def origin(self) -> str | None:
        return self._origin

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def stream_generation(self) -> int | None:
        return self._generation

    @property
    def epoch(self) -> str | None:
        return self._epoch

    @property
    def epoch_seq(self) -> int | None:
        return self._epoch_seq

    @property
    def needs_resync(self) -> bool:
        return self._resync_required

    # -- lifecycle --------------------------------------------------------
    def connect(self) -> dict:
        """Enter connecting/synchronizing; a snapshot is still required."""
        if self._state == "disconnected" or self._state == "degraded":
            self._state = "connecting"
        return _report(SYNC_OK, lifecycle=self._state,
                       needs_resync=self._resync_required)

    def disconnect(self) -> dict:
        """Keep known values but mark them stale; unknown stays unknown."""
        self._state = "disconnected"
        self._resync_required = True
        self._session_id = None
        self._expected_seq = None
        for entry in self._entries.values():
            if entry.has_value and entry.quality == "fresh":
                entry.quality = "stale"
        return _report(SYNC_OK, lifecycle=self._state,
                       state_count=len(self._entries), needs_resync=True)

    def invalidate_origin(self) -> dict:
        """Explicitly drop a foreign/obsolete mirror origin and its values."""
        self._entries = {}
        self._origin = None
        self._session_id = None
        self._generation = None
        self._epoch = None
        self._epoch_seq = None
        self._expected_seq = None
        self._last_snapshot_seq = None
        self._resync_required = True
        self._state = "degraded"
        return _report(SYNC_OK, lifecycle=self._state, needs_resync=True)

    # -- receive ----------------------------------------------------------
    def receive(self, frame: Any) -> dict:
        """Apply one frame or return a structured rejection; never raises."""
        try:
            frame = copy.deepcopy(frame)
        except Exception:
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/",
                "Frame is not processable (not copyable/JSON-like).")])
        if not isinstance(frame, dict):
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/", "Frame must be an object.")])
        if self._state == "disconnected":
            return _report(SYNC_NOT_CONNECTED, [_issue(
                SYNC_NOT_CONNECTED, "/",
                "Mirror is disconnected; no frame is applied.")])
        if not self._trust.verify_frame(frame):
            return _report(SYNC_UNTRUSTED, [_issue(
                SYNC_UNTRUSTED, "/transport_auth",
                "Frame was not signed by the injected fake trust object. "
                "Session strings, host-id fields and writer handles never "
                "authorize a frame in this spike.")])

        issues = _header_issues(frame)
        if issues:
            return _report(SYNC_FRAME_INVALID, issues)

        runtime_id = frame["runtime_instance_id"]
        if self._origin is not None and runtime_id != self._origin:
            old = self._origin
            self.invalidate_origin()
            return _report(SYNC_ORIGIN_MISMATCH, [_issue(
                SYNC_ORIGIN_MISMATCH, "/runtime_instance_id",
                f"Frame origin {runtime_id!r} differs from the established "
                f"mirror origin {old!r}; the old mirror provenance was "
                "invalidated and a fresh snapshot is required. Values from "
                "different runtime instances are never mixed.")],
                invalidated=True, lifecycle=self._state)

        frame_type = frame["type"]
        if frame_type == "handshake":
            return self._receive_handshake(frame)
        if frame_type == "snapshot":
            return self._receive_snapshot(frame)
        return self._receive_delta(frame)

    def _receive_handshake(self, frame: dict) -> dict:
        if not isinstance(frame.get("payload"), dict):
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/payload",
                "Handshake payload must be an object.")])
        generation = frame["stream_generation"]
        session_id = frame["session_id"]
        if self._generation is not None:
            if generation < self._generation:
                return _report(SYNC_GENERATION_MISMATCH, [_issue(
                    SYNC_GENERATION_MISMATCH, "/stream_generation",
                    f"Session generation {generation} is older than the "
                    f"mirror generation {self._generation}; rejected without "
                    "mutation.")])
            if generation == self._generation:
                if session_id == self._session_id:
                    return _report(SYNC_STALE_IGNORED, [_issue(
                        SYNC_STALE_IGNORED, "/session_id",
                        "Duplicate handshake for the current session ignored.")],
                        lifecycle=self._state)
                return _report(SYNC_SESSION_MISMATCH, [_issue(
                    SYNC_SESSION_MISMATCH, "/session_id",
                    "A new session requires a higher stream generation; "
                    "session strings alone never transfer authority.")])
        if self._origin is None:
            self._origin = frame["runtime_instance_id"]
        for entry in self._entries.values():
            if entry.has_value and entry.quality == "fresh":
                entry.quality = "stale"
        self._session_id = session_id
        self._generation = generation
        self._epoch = frame["epoch"]
        self._epoch_seq = frame["epoch_seq"]
        self._expected_seq = frame["stream_seq"] + 1
        self._resync_required = False
        self._state = "synchronizing"
        return _report(SYNC_HANDSHAKE_ACCEPTED, lifecycle=self._state,
                       session_id=session_id, stream_generation=generation,
                       origin=self._origin, expected_stream_seq=self._expected_seq)

    def _receive_snapshot(self, frame: dict) -> dict:
        if self._origin is None or self._session_id is None:
            return _report(SYNC_NOT_READY, [_issue(
                SYNC_NOT_READY, "/session",
                "No handshake session; a snapshot cannot establish a baseline.")])
        mismatch = self._session_generation_issue(frame)
        if mismatch:
            return mismatch
        if self._state == "connecting":
            return _report(SYNC_NOT_READY, [_issue(
                SYNC_NOT_READY, "/type",
                "Snapshot received before the handshake was accepted.")])
        seq = frame["stream_seq"]
        if self._last_snapshot_seq is not None and seq <= self._last_snapshot_seq:
            return _report(SYNC_STALE_IGNORED, [_issue(
                SYNC_STALE_IGNORED, "/stream_seq",
                "Snapshot position is not newer than the last applied "
                "snapshot; replayed snapshots are not applied.")],
                lifecycle=self._state)

        entries, issues = self._parse_snapshot(frame)
        if issues:
            return _report(SYNC_FRAME_INVALID, issues)
        self._entries = entries
        self._epoch = frame["epoch"]
        self._epoch_seq = frame["epoch_seq"]
        self._expected_seq = seq + 1
        self._last_snapshot_seq = seq
        self._resync_required = False
        self._state = "ready"
        return _report(SYNC_SNAPSHOT_APPLIED, lifecycle=self._state,
                       state_count=len(entries), epoch=self._epoch,
                       epoch_seq=self._epoch_seq,
                       expected_stream_seq=self._expected_seq)

    def _receive_delta(self, frame: dict) -> dict:
        if self._origin is None or self._session_id is None:
            return _report(SYNC_NOT_READY, [_issue(
                SYNC_NOT_READY, "/session",
                "No snapshot baseline; a delta is never applied.")])
        mismatch = self._session_generation_issue(frame)
        if mismatch:
            return mismatch
        if self._state != "ready" or self._resync_required:
            return _report(SYNC_NOT_READY, [_issue(
                SYNC_NOT_READY, "/lifecycle",
                f"Mirror lifecycle is {self._state!r} with "
                f"resync_required={self._resync_required}; deltas are not "
                "applied until a valid snapshot re-baselines the mirror.")],
                lifecycle=self._state, needs_resync=self._resync_required)
        if frame["epoch"] != self._epoch or frame["epoch_seq"] != self._epoch_seq:
            self._resync_required = True
            self._state = "degraded"
            return _report(SYNC_EPOCH_MISMATCH, [_issue(
                SYNC_EPOCH_MISMATCH, "/epoch",
                f"Delta epoch ({frame['epoch']!r}, seq {frame['epoch_seq']}) "
                f"does not match mirror epoch ({self._epoch!r}, seq "
                f"{self._epoch_seq}); revisions across epochs are never "
                "compared numerically. Resync required.")],
                lifecycle=self._state, needs_resync=True)

        entry, issues = self._parse_delta(frame)
        if issues:
            return _report(SYNC_FRAME_INVALID, issues)

        seq = frame["stream_seq"]
        if self._expected_seq is not None and seq < self._expected_seq:
            code = SYNC_DUPLICATE if seq == self._expected_seq - 1 else SYNC_STALE_IGNORED
            return _report(code, [_issue(
                code, "/stream_seq",
                f"Frame position {seq} is behind the expected position "
                f"{self._expected_seq}; not applied.")],
                lifecycle=self._state)
        if self._expected_seq is not None and seq > self._expected_seq:
            self._resync_required = True
            self._state = "degraded"
            return _report(SYNC_STREAM_GAP, [_issue(
                SYNC_STREAM_GAP, "/stream_seq",
                f"Frame position {seq} skips the expected position "
                f"{self._expected_seq}; a message was lost. Resync required; "
                "no value was changed.")],
                lifecycle=self._state, needs_resync=True)

        known = self._entries.get(entry.key)
        if known is None:
            self._resync_required = True
            self._state = "degraded"
            return _report(SYNC_UNKNOWN_STATE, [_issue(
                SYNC_UNKNOWN_STATE, "/payload/state_id",
                f"State {entry.key!r} was not part of the snapshot baseline; "
                "resync required; no value was changed.")],
                lifecycle=self._state, needs_resync=True)
        if entry.revision <= known.revision:
            # Consume the position but never apply the stale value.
            self._expected_seq = seq + 1
            code = SYNC_DUPLICATE if entry.revision == known.revision else SYNC_STALE_IGNORED
            return _report(code, [_issue(
                code, "/payload/revision",
                f"Delta revision {entry.revision} is not newer than the known "
                f"revision {known.revision}; old value remains authoritative.")],
                lifecycle=self._state)
        if entry.revision > known.revision + 1:
            self._resync_required = True
            self._state = "degraded"
            return _report(SYNC_REVISION_GAP, [_issue(
                SYNC_REVISION_GAP, "/payload/revision",
                f"Delta revision {entry.revision} skips the expected revision "
                f"{known.revision + 1}; resync required; no value was changed.")],
                lifecycle=self._state, needs_resync=True)

        self._entries[entry.key] = entry
        self._expected_seq = seq + 1
        return _report(SYNC_DELTA_APPLIED, lifecycle=self._state,
                       state_id=entry.state_id, scope=copy.deepcopy(entry.scope),
                       revision=entry.revision, epoch=entry.epoch,
                       epoch_seq=entry.epoch_seq,
                       expected_stream_seq=self._expected_seq)

    # -- helpers ----------------------------------------------------------
    def _session_generation_issue(self, frame: dict) -> dict | None:
        if frame["session_id"] != self._session_id:
            return _report(SYNC_SESSION_MISMATCH, [_issue(
                SYNC_SESSION_MISMATCH, "/session_id",
                f"Frame session {frame['session_id']!r} does not match the "
                f"active mirror session {self._session_id!r}; rejected "
                "without mutation.")])
        if frame["stream_generation"] != self._generation:
            return _report(SYNC_GENERATION_MISMATCH, [_issue(
                SYNC_GENERATION_MISMATCH, "/stream_generation",
                f"Frame generation {frame['stream_generation']} does not match "
                f"the active mirror generation {self._generation}; rejected "
                "without mutation.")])
        return None

    def _parse_snapshot(self, frame: dict) -> tuple[dict, list]:
        from core.ids import is_valid_id

        issues: list[dict] = []
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return {}, [_issue(SYNC_FRAME_INVALID, "/payload",
                               "Snapshot payload must be an object.")]
        if payload.get("snapshot_epoch") != frame["epoch"] \
                or payload.get("snapshot_epoch_seq") != frame["epoch_seq"]:
            issues.append(_issue(
                SYNC_FRAME_INVALID, "/payload/snapshot_epoch",
                "Snapshot epoch metadata does not match the frame header."))
        states = payload.get("states")
        if not isinstance(states, dict):
            return {}, [*issues, _issue(
                SYNC_FRAME_INVALID, "/payload/states",
                "Snapshot states must be an object keyed by scope key.")]
        if payload.get("state_count") != len(states):
            issues.append(_issue(
                SYNC_FRAME_INVALID, "/payload/state_count",
                "Snapshot state_count does not match the number of states."))
        entries: dict[str, _MirrorEntry] = {}
        for key, item in states.items():
            path = f"/payload/states/{key}"
            if not isinstance(key, str) or not isinstance(item, dict):
                issues.append(_issue(SYNC_FRAME_INVALID, path,
                                     "Snapshot entry must be an object."))
                continue
            state_id = item.get("state_id")
            if not is_valid_id(state_id):
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/state_id",
                                     f"Invalid state id {state_id!r}."))
                continue
            address, problem = _scope_from_dict(item.get("scope"))
            if address is None:
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/scope",
                                     problem or "Invalid scope."))
                continue
            expected_key = address.key_string(state_id)
            if key != expected_key:
                issues.append(_issue(
                    SYNC_FRAME_INVALID, path,
                    f"Scope key {key!r} does not match {expected_key!r}."))
                continue
            has_value = item.get("has_value")
            if not isinstance(has_value, bool):
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/has_value",
                                     "has_value must be a boolean."))
                continue
            quality = item.get("quality")
            if quality not in QUALITIES:
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/quality",
                                     f"Unknown quality {quality!r}."))
                continue
            # Quality is part of the authoritative snapshot and must never be
            # promoted or silently reinterpreted. Only the consistent
            # combinations are accepted: no value -> unknown, value -> fresh
            # or stale. Contradictory combinations fail closed.
            if not has_value and quality != "unknown":
                issues.append(_issue(
                    SYNC_FRAME_INVALID, f"{path}/quality",
                    "has_value=false requires quality 'unknown'; a snapshot "
                    "must not claim freshness without an authoritative value."))
                continue
            if has_value and quality == "unknown":
                issues.append(_issue(
                    SYNC_FRAME_INVALID, f"{path}/quality",
                    "has_value=true requires quality 'fresh' or 'stale'; "
                    "'unknown' with a value is contradictory."))
                continue
            revision = item.get("revision")
            if type(revision) is not int or revision < 0:
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/revision",
                                     "revision must be an integer >= 0."))
                continue
            if item.get("epoch") != frame["epoch"] \
                    or item.get("epoch_seq") != frame["epoch_seq"]:
                issues.append(_issue(
                    SYNC_FRAME_INVALID, f"{path}/epoch",
                    "Entry epoch does not match the snapshot epoch."))
                continue
            ok, value = _copy_ok(item.get("value")) if has_value else (True, None)
            if not ok or (not has_value and item.get("value") is not None):
                issues.append(_issue(SYNC_FRAME_INVALID, f"{path}/value",
                                     "Entry value is not processable."))
                continue
            entries[key] = _MirrorEntry(
                state_id=state_id,
                scope=address.as_dict(),
                key=key,
                value=value,
                has_value=has_value,
                quality=quality,
                revision=revision,
                epoch=frame["epoch"],
                epoch_seq=frame["epoch_seq"],
            )
        return entries, issues

    def _parse_delta(self, frame: dict) -> tuple[_MirrorEntry | None, list]:
        from core.ids import is_valid_id

        issues: list[dict] = []
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return None, [_issue(SYNC_FRAME_INVALID, "/payload",
                                 "Delta payload must be an object.")]
        state_id = payload.get("state_id")
        if not is_valid_id(state_id):
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/state_id",
                                 f"Invalid state id {state_id!r}."))
        address, problem = _scope_from_dict(payload.get("scope"))
        if address is None:
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/scope",
                                 problem or "Invalid scope."))
        if payload.get("has_value") is not True:
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/has_value",
                                 "A delta must carry a confirmed live value."))
        if payload.get("quality") != "fresh":
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/quality",
                                 "A confirmed delta must be fresh."))
        revision = payload.get("revision")
        if type(revision) is not int or revision < 1:
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/revision",
                                 "Delta revision must be an integer >= 1."))
        if payload.get("epoch") != frame["epoch"] \
                or payload.get("epoch_seq") != frame["epoch_seq"]:
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/epoch",
                                 "Delta epoch does not match the frame header."))
        ok, value = _copy_ok(payload.get("value"))
        if not ok:
            issues.append(_issue(SYNC_FRAME_INVALID, "/payload/value",
                                 "Delta value is not processable."))
        if issues:
            return None, issues
        key = address.key_string(state_id)
        return _MirrorEntry(
            state_id=state_id, scope=address.as_dict(), key=key,
            value=value, has_value=True, quality="fresh",
            revision=revision, epoch=frame["epoch"],
            epoch_seq=frame["epoch_seq"],
        ), []

    # -- read -------------------------------------------------------------
    def read(self, state_id: str, scope: ScopeAddress) -> dict:
        """Defensive read of one mirror entry; never raises."""
        if not isinstance(scope, ScopeAddress):
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/scope",
                "Mirror reads require a ScopeAddress.")])
        problem = scope.canonical_problem()
        if problem:
            return _report(SYNC_FRAME_INVALID, [_issue(
                SYNC_FRAME_INVALID, "/scope", problem)])
        key = scope.key_string(state_id)
        entry = self._entries.get(key)
        if entry is None:
            return _report(SYNC_UNKNOWN_STATE, [_issue(
                SYNC_UNKNOWN_STATE, f"/states/{state_id}",
                f"State {key!r} is not part of the current mirror baseline.")],
                state_id=state_id, has_value=False, quality="unknown")
        return _report(SYNC_OK, entry=entry.as_dict(), **entry.as_dict())

    def snapshot(self) -> dict:
        """Full, isolated mirror view in deterministic key order."""
        states = {key: self._entries[key].as_dict()
                  for key in sorted(self._entries)}
        return {
            "status": SYNC_OK,
            "lifecycle": self._state,
            "origin": self._origin,
            "session_id": self._session_id,
            "stream_generation": self._generation,
            "epoch": self._epoch,
            "epoch_seq": self._epoch_seq,
            "needs_resync": self._resync_required,
            "state_count": len(states),
            "states": states,
        }


class SyncLink:
    """One source + one mirror over one manually controlled fake transport."""

    def __init__(self, store: Any, *, trust: FakeTransportTrust | None = None,
                 writer_id: str = "fake.writer.primary") -> None:
        self.trust = trust or FakeTransportTrust.create(writer_id=writer_id)
        self.transport = FakeTransport(self.trust)
        self.source = SyncSource(store, self.transport, trust=self.trust)
        self.mirror = SyncMirror(self.trust)

    def connect(self, session_id: str | None = None) -> dict:
        self.mirror.connect()
        handshake = self.source.start_session(session_id)
        snapshot = self.source.send_snapshot() if handshake["status"] == "TRANSPORT_ENQUEUED" else None
        return {"handshake": handshake, "snapshot": snapshot,
                "pending": self.transport.pending}

    def disconnect(self) -> dict:
        transport = self.transport.disconnect()
        mirror = self.mirror.disconnect()
        return {"transport": transport, "mirror": mirror}

    def reconnect(self, session_id: str | None = None) -> dict:
        self.transport.reconnect()
        return self.connect(session_id)

    def resync(self) -> dict:
        return self.source.send_snapshot()

    def deliver_next(self) -> dict:
        transport = self.transport.deliver_next()
        if not transport.get("delivered"):
            return {"status": transport.get("status"), "transport": transport,
                    "mirror": None}
        mirror = self.mirror.receive(transport["frame"])
        return {"status": mirror["status"], "transport": transport,
                "mirror": mirror}

    def deliver_all(self, limit: int = 1000) -> list[dict]:
        reports: list[dict] = []
        for _ in range(limit):
            if self.transport.pending == 0 or not self.transport.connected:
                break
            reports.append(self.deliver_next())
        return reports
