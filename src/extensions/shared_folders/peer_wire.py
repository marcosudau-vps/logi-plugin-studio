"""Bounded, authenticated direct channels for the optional folder federation."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import struct
import time
import uuid
from pathlib import Path

from core.ids import is_valid_id
from runtime.wire import HostError, json_bytes, parse_json

VERSION = "shared-folder-peer-1"
FRAME_LIMIT = 64 * 1024
PAYLOAD_LIMIT = 48 * 1024
MAX_PEERS = 16
MAX_SCOPES = 128
FRAME_TIMEOUT = 2
ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class PeerError(ValueError):
    pass


def identity(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def resource_id(value):
    return isinstance(value, str) and len(value) <= 256 and is_valid_id(value)


def shape(value, *fields):
    if not isinstance(value, dict) or value.keys() != set(fields):
        raise PeerError("INVALID_FIELDS")


def encode(value, limit=PAYLOAD_LIMIT):
    return json_bytes(value, limit=limit)


async def _read(reader, size, *, idle=None):
    header = await asyncio.wait_for(reader.readexactly(4), idle)
    length, = struct.unpack("!I", header)
    if not 0 < length <= size:
        raise PeerError("FRAME_SIZE")
    return await asyncio.wait_for(reader.readexactly(length), FRAME_TIMEOUT)


async def _write(writer, data):
    writer.write(struct.pack("!I", len(data)) + data)
    await asyncio.wait_for(writer.drain(), FRAME_TIMEOUT)


def _mac(key, domain, data):
    return hmac.digest(key, domain + data, hashlib.sha256)


class Channel:
    def __init__(self, reader, writer, key, initiator):
        self.reader, self.writer, self.key = reader, writer, key
        self.outgoing = b"dial>" if initiator else b"accept>"
        self.incoming = b"accept>" if initiator else b"dial>"
        self.sent = self.received = 0
        self.lock = asyncio.Lock()

    async def send(self, kind, payload):
        encode(payload)
        async with self.lock:
            seq = self.sent + 1
            body = encode(dict(seq=seq, kind=kind, payload=payload), FRAME_LIMIT - 32)
            try:
                await _write(self.writer, _mac(self.key, self.outgoing, body) + body)
            except (Exception, asyncio.CancelledError):
                self.writer.close()
                raise
            self.sent = seq

    async def receive(self, idle):
        packet = await _read(self.reader, FRAME_LIMIT, idle=idle)
        tag, body = packet[:32], packet[32:]
        if not hmac.compare_digest(tag, _mac(self.key, self.incoming, body)):
            raise PeerError("FRAME_AUTH")
        message = parse_json(body, limit=FRAME_LIMIT - 32)
        shape(message, "seq", "kind", "payload")
        if type(message["seq"]) is not int or message["seq"] != self.received + 1:
            raise PeerError("FRAME_SEQUENCE")
        encode(message["payload"])
        self.received += 1
        return message["kind"], message["payload"]


def greeting(plugin, instance, target, target_instance):
    return dict(protocol=VERSION, plugin=plugin, instance=instance, target=target,
                target_instance=target_instance, nonce=uuid.uuid4().hex)


async def dial(reader, writer, key, hello):
    body = encode(hello, 2048)
    await _write(writer, body)
    challenge = await _read(reader, 48, idle=FRAME_TIMEOUT)
    transcript = body + challenge[:16]
    if len(challenge) != 48 or not hmac.compare_digest(challenge[16:], _mac(key, b"server", transcript)):
        raise PeerError("PEER_AUTH")
    await _write(writer, _mac(key, b"client", transcript))
    return Channel(reader, writer, _mac(key, b"session", transcript), True)


async def accept(reader, writer, resolve):
    body = await _read(reader, 2048, idle=FRAME_TIMEOUT)
    hello = parse_json(body, limit=2048)
    shape(hello, "protocol", "plugin", "instance", "target", "target_instance", "nonce")
    if (hello["protocol"] != VERSION or not all(resource_id(hello[k]) for k in ("plugin", "target"))
            or not all(identity(hello[k]) for k in ("instance", "target_instance", "nonce"))):
        raise PeerError("PEER_HELLO")
    key = resolve(hello)
    challenge = os.urandom(16)
    transcript = body + challenge
    await _write(writer, challenge + _mac(key, b"server", transcript))
    proof = await _read(reader, 32, idle=FRAME_TIMEOUT)
    if not hmac.compare_digest(proof, _mac(key, b"client", transcript)):
        raise PeerError("PEER_AUTH")
    return hello, Channel(reader, writer, _mac(key, b"session", transcript), False)


def _retry_file(operation):
    # Windows readers can transiently prevent replacement or unlink.
    for attempt in range(8):
        try:
            return operation()
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.025)


class Discovery:
    """One live writer per plugin ID. The OS releases the lease on process death."""

    def __init__(self, directory, plugin, instance):
        self.directory = Path(directory)
        self.plugin, self.instance = plugin, instance
        self.lease = None

    def _path(self, plugin, extension):
        # Hash keeps IDs distinct even on Windows' case-insensitive filesystem.
        return self.directory / (hashlib.sha256(plugin.encode()).hexdigest() + extension)

    def start(self, port):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt" and (self.directory.stat().st_uid != os.getuid()
                                or self.directory.stat().st_mode & 0o077):
            raise PeerError("DISCOVERY_DIRECTORY_PERMISSIONS")
        lease = self._path(self.plugin, ".lock").open("a+b")
        temporary = self._path(self.plugin, "." + self.instance + ".tmp")
        try:
            if os.name == "nt":
                import msvcrt
                lease.seek(0)
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            temporary.write_bytes(encode(dict(plugin=self.plugin, instance=self.instance, port=port), 1024))
            _retry_file(lambda: os.replace(temporary, self._path(self.plugin, ".json")))
        except BaseException:
            temporary.unlink(missing_ok=True)
            lease.close()
            raise
        self.lease = lease

    def read(self, plugin):
        try:
            with self._path(plugin, ".json").open("rb") as handle:
                row = parse_json(handle.read(1025), limit=1024)
            shape(row, "plugin", "instance", "port")
            if row["plugin"] == plugin and identity(row["instance"]) and type(row["port"]) is int and 0 < row["port"] < 65536:
                return row
        except (OSError, ValueError, HostError):
            pass
        return None

    def close(self):
        if self.lease is not None:
            try:
                _retry_file(lambda: self._path(self.plugin, ".json").unlink(missing_ok=True))
            finally:
                self.lease.close()
                self.lease = None
