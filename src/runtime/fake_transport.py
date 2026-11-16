"""Deterministic in-memory fake transport (AP-CORE-004, SPIKE_ONLY).

This module is **not** a wire protocol and **not** a security mechanism. It is
a manually driven queue used by the sync spike:

- enqueue, deliver, drop, duplicate, swap ("reorder") frames;
- disconnect and reconnect the simulated link;
- authenticate a sender only through an *injected* fake trust object.

No sockets, no threads, no timers, no files. The HMAC is a deterministic test
token, not network authentication; a real transport handshake, ACK, retry,
backoff, timeout and queue policy all remain ``OPEN`` (see the run's
``06_sync_vertragsvorschlag.md``).

Frame header fields are provisional local test scaffolding. ``stream_seq`` is
a strictly monotonic transport-stream counter and is explicitly **not** a
global StateStore revision.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

SYNC_SCHEMA_VERSION = "spike-sync-0.1"
SPIKE_ONLY = True
FRAME_TYPES = ("handshake", "snapshot", "delta")

TRANSPORT_CONNECTED = "TRANSPORT_CONNECTED"
TRANSPORT_DISCONNECTED = "TRANSPORT_DISCONNECTED"
TRANSPORT_EMPTY = "TRANSPORT_EMPTY"
TRANSPORT_ENQUEUED = "TRANSPORT_ENQUEUED"
TRANSPORT_DROPPED = "TRANSPORT_DROPPED"
TRANSPORT_DUPLICATED = "TRANSPORT_DUPLICATED"
TRANSPORT_REORDERED = "TRANSPORT_REORDERED"
TRANSPORT_FRAME_INVALID = "TRANSPORT_FRAME_INVALID"


def _canonical_bytes(frame: Any) -> bytes | None:
    """Deterministic bytes over every field except ``transport_auth``."""
    if not isinstance(frame, dict):
        return None
    body = {key: value for key, value in frame.items() if key != "transport_auth"}
    try:
        return json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FakeTransportTrust:
    """Injected fake trust handle for exactly one simulated writer.

    ``writer_id`` is a local test identity. A receiver only accepts frames
    signed with the *same* token. Session strings, host-id fields or knowledge
    of a ``WriterIdentity`` handle never authorize anything in this spike.
    """

    writer_id: str = "fake.writer.primary"
    _token: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)

    @classmethod
    def create(cls, writer_id: str = "fake.writer.primary",
               token: str | None = None) -> "FakeTransportTrust":
        if not isinstance(writer_id, str) or not writer_id:
            raise ValueError("writer_id must be a non-empty string")
        return cls(writer_id=writer_id,
                   _token=token if isinstance(token, str) and token else uuid.uuid4().hex)

    def sign(self, frame: Any) -> str | None:
        """Return the fake transport tag, or ``None`` for non-JSON frames."""
        body = _canonical_bytes(frame)
        if body is None:
            return None
        return hmac.new(self._token.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def sign_frame(self, frame: dict) -> dict:
        """Copy *frame*, attach writer id and fake tag; never mutates input."""
        signed = copy.deepcopy(frame)
        signed["transport_writer"] = self.writer_id
        signed.pop("transport_auth", None)
        tag = self.sign(signed)
        if tag is None:
            raise ValueError("frame is not JSON-compatible")
        signed["transport_auth"] = tag
        return signed

    def verify_frame(self, frame: Any) -> bool:
        if not isinstance(frame, dict):
            return False
        if frame.get("transport_writer") != self.writer_id:
            return False
        expected = self.sign(frame)
        received = frame.get("transport_auth")
        if expected is None or not isinstance(received, str):
            return False
        return hmac.compare_digest(expected, received)


class FakeTransport:
    """Manual FIFO frame queue between one source and one mirror.

    All state changes happen through explicit calls; nothing runs in the
    background. ``disconnect`` drops in-flight frames (simulated loss) so a
    reconnect must start with a fresh handshake and snapshot.
    """

    def __init__(self, trust: FakeTransportTrust) -> None:
        if not isinstance(trust, FakeTransportTrust):
            raise TypeError("FakeTransport requires an injected FakeTransportTrust")
        self._trust = trust
        self._queue: list[Any] = []
        self._delivered: list[Any] = []
        self._connected = True
        self._stream_seq = 0
        self._dropped = 0

    # -- inspection -------------------------------------------------------
    @property
    def trust(self) -> FakeTransportTrust:
        return self._trust

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def dropped_count(self) -> int:
        return self._dropped

    @property
    def last_stream_seq(self) -> int:
        return self._stream_seq

    def next_stream_seq(self) -> int:
        """Strictly monotonic local transport-stream counter (SPIKE_ONLY)."""
        self._stream_seq += 1
        return self._stream_seq

    def peek_next(self) -> dict:
        if not self._queue:
            return {"status": TRANSPORT_EMPTY, "frame": None}
        try:
            frame = copy.deepcopy(self._queue[0])
        except Exception:
            return {"status": TRANSPORT_FRAME_INVALID, "frame": None,
                    "pending": self.pending}
        return {"status": TRANSPORT_CONNECTED, "frame": frame}

    def delivered_count(self) -> int:
        return len(self._delivered)

    # -- manual control ---------------------------------------------------
    def send(self, frame: dict) -> dict:
        """Sign and enqueue a frame. Refuses while disconnected."""
        if not self._connected:
            return {"status": TRANSPORT_DISCONNECTED, "frame": None,
                    "pending": self.pending}
        try:
            signed = self._trust.sign_frame(frame)
            stored = copy.deepcopy(signed)
        except Exception:
            return {"status": TRANSPORT_FRAME_INVALID, "frame": None,
                    "pending": self.pending}
        self._queue.append(stored)
        return {"status": TRANSPORT_ENQUEUED, "frame": copy.deepcopy(stored),
                "pending": self.pending}

    def inject(self, frame: Any) -> dict:
        """Enqueue an isolated copy without signing (negative/manual tests).

        A frame that cannot be deep-copied is rejected structurally and never
        enters the queue. The queue is unchanged on rejection, and the response
        itself is a copy so callers cannot alias queued state.
        """
        if not self._connected:
            return {"status": TRANSPORT_DISCONNECTED, "frame": None,
                    "pending": self.pending}
        try:
            stored = copy.deepcopy(frame)
            response = copy.deepcopy(stored)
        except Exception:
            return {"status": TRANSPORT_FRAME_INVALID, "frame": None,
                    "pending": self.pending}
        self._queue.append(stored)
        return {"status": TRANSPORT_ENQUEUED, "frame": response,
                "pending": self.pending}

    def deliver_next(self) -> dict:
        """Hand the next frame to the caller once; nothing is retried."""
        if not self._connected:
            return {"status": TRANSPORT_DISCONNECTED, "delivered": False,
                    "frame": None, "remaining": self.pending}
        if not self._queue:
            return {"status": TRANSPORT_EMPTY, "delivered": False,
                    "frame": None, "remaining": 0}
        # Copy before removing: an unprocessable queue entry must leave the
        # queue untouched instead of being lost after a failed response copy.
        try:
            frame = copy.deepcopy(self._queue[0])
            delivered_copy = copy.deepcopy(frame)
            response = copy.deepcopy(frame)
        except Exception:
            return {"status": TRANSPORT_FRAME_INVALID, "delivered": False,
                    "frame": None, "remaining": self.pending}
        self._queue.pop(0)
        self._delivered.append(delivered_copy)
        return {"status": "TRANSPORT_DELIVERED", "delivered": True,
                "frame": response, "remaining": self.pending}

    def drop_next(self) -> dict:
        """Silently discard the next frame (simulated loss, manual only)."""
        if not self._queue:
            return {"status": TRANSPORT_EMPTY, "dropped": 0,
                    "remaining": self.pending}
        self._queue.pop(0)
        self._dropped += 1
        return {"status": TRANSPORT_DROPPED, "dropped": 1,
                "remaining": self.pending}

    def duplicate_next(self) -> dict:
        """Insert a copy of the next frame in front of it."""
        if not self._queue:
            return {"status": TRANSPORT_EMPTY, "duplicated": 0,
                    "remaining": self.pending}
        self._queue.insert(0, copy.deepcopy(self._queue[0]))
        return {"status": TRANSPORT_DUPLICATED, "duplicated": 1,
                "remaining": self.pending}

    def swap_next_two(self) -> dict:
        """Swap the first two queued frames (simulated reordering)."""
        if len(self._queue) < 2:
            return {"status": TRANSPORT_EMPTY, "reordered": False,
                    "remaining": self.pending}
        self._queue[0], self._queue[1] = self._queue[1], self._queue[0]
        return {"status": TRANSPORT_REORDERED, "reordered": True,
                "remaining": self.pending}

    def disconnect(self) -> dict:
        """Simulate transport loss; in-flight frames are discarded."""
        self._connected = False
        lost = len(self._queue)
        self._queue.clear()
        return {"status": TRANSPORT_DISCONNECTED, "lost": lost}

    def reconnect(self) -> dict:
        self._connected = True
        return {"status": TRANSPORT_CONNECTED, "pending": self.pending}
