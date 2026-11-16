"""Local authenticated transport, separate from the AP-CORE-004 fake protocol."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROTOCOL = "studio-local-1"
MAX_REQUEST = 65_536
MAX_RESPONSE = 1_048_576
MAX_DEPTH = 32
MAX_CLOCK_SKEW = 30


class HostError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def json_bytes(value: Any, *, limit: int = MAX_RESPONSE) -> bytes:
    def check(item: Any, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise HostError("FRAME_DEPTH", "JSON nesting exceeds the transport limit")
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float) and math.isfinite(item):
            return
        if isinstance(item, list):
            for child in item:
                check(child, depth + 1)
            return
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise HostError("FRAME_VALUE", "Only finite, JSON-compatible values are permitted")

    check(value, 0)
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HostError("FRAME_JSON", str(exc)) from exc
    if len(encoded) > limit:
        raise HostError("FRAME_SIZE", f"Encoded JSON exceeds {limit} bytes")
    return encoded


def parse_json(data: bytes, *, limit: int = MAX_REQUEST) -> dict:
    if len(data) > limit:
        raise HostError("FRAME_SIZE", f"Body exceeds {limit} bytes")

    def unique(pairs: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise HostError("FRAME_DUPLICATE_KEY", "Duplicate JSON keys are forbidden")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               HostError("FRAME_VALUE", "Non-finite number")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HostError("FRAME_JSON", "Invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise HostError("FRAME_SHAPE", "Message root must be an object")
    json_bytes(value, limit=limit)
    return value


def project_digest(raw: dict) -> str:
    return hashlib.sha256(json_bytes(raw, limit=16 * MAX_RESPONSE)).hexdigest()


def signature(secret: str, prefix: str, body: bytes) -> str:
    return hmac.new(bytes.fromhex(secret), prefix.encode("ascii") + body,
                    hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ConnectionSettings:
    plugin_id: str
    project_hash: str
    port: int
    secret: str = field(repr=False)
    installation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        from core.ids import is_valid_id
        if not is_valid_id(self.plugin_id):
            raise HostError("CONNECTION_PLUGIN", "Plugin ID must be a valid stable ID")
        if not isinstance(self.project_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", self.project_hash):
            raise HostError("CONNECTION_PROJECT", "Expected a SHA-256 project fingerprint")
        if type(self.port) is not int or not (self.port == 0 or 1024 <= self.port <= 65535):
            raise HostError("CONNECTION_PORT", "Expected an unprivileged local TCP port")
        if not isinstance(self.secret, str) or not re.fullmatch(r"[a-f0-9]{64}", self.secret):
            raise HostError("CONNECTION_SECRET", "Expected a random 256-bit key")
        if not isinstance(self.installation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", self.installation_id):
            raise HostError("CONNECTION_INSTALLATION", "Invalid installation identity")

    def as_dict(self) -> dict:
        return {"protocol": PROTOCOL, "plugin_id": self.plugin_id,
                "project_hash": self.project_hash, "port": self.port,
                "secret": self.secret, "installation_id": self.installation_id}

    @classmethod
    def load(cls, path: str | Path) -> "ConnectionSettings":
        try:
            raw = parse_json(Path(path).read_bytes())
        except OSError as exc:
            raise HostError("CONNECTION_UNREADABLE", str(exc)) from exc
        if set(raw) != {"protocol", "plugin_id", "project_hash", "port",
                        "secret", "installation_id"} or raw["protocol"] != PROTOCOL:
            raise HostError("CONNECTION_FORMAT", "Unknown connection configuration")
        try:
            return cls(**{k: v for k, v in raw.items() if k != "protocol"})
        except (TypeError, ValueError) as exc:
            raise HostError("CONNECTION_FORMAT", "Malformed connection configuration") from exc


class LocalClient:
    """Test/diagnostic client using the same real HTTP contract as the C# adapter."""

    def __init__(self, settings: ConnectionSettings, *, timeout: float = 2) -> None:
        self.settings = settings
        self.timeout = timeout
        self.session_id = ""
        self.runtime_instance_id = ""

    def request(self, path: str, fields: dict | None = None) -> dict:
        nonce = uuid.uuid4().hex
        body = json_bytes({
            "protocol": PROTOCOL, "plugin_id": self.settings.plugin_id,
            "project_hash": self.settings.project_hash,
            "installation_id": self.settings.installation_id,
            "sent_at": int(time.time()), **(fields or {}),
        }, limit=MAX_REQUEST)
        headers = {"Content-Type": "application/json", "X-Studio-Nonce": nonce,
                   "X-Studio-Signature": signature(self.settings.secret, path + "\n" + nonce + "\n", body)}
        connection = http.client.HTTPConnection("127.0.0.1", self.settings.port, timeout=self.timeout)
        try:
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE + 1)
            tag = response.getheader("X-Studio-Signature", "")
            expected = signature(self.settings.secret, nonce + "\n", data)
            if not hmac.compare_digest(tag, expected):
                raise HostError("HOST_UNTRUSTED", "Response signature is invalid")
            message = parse_json(data, limit=MAX_RESPONSE)
            if message.get("protocol") != PROTOCOL or message.get("plugin_id") != self.settings.plugin_id:
                raise HostError("HOST_UNTRUSTED", "Response identity is invalid")
            if response.status >= 400:
                raise HostError(message.get("code", "HTTP_ERROR"), message.get("message", "Request refused"))
            return message
        except (OSError, http.client.HTTPException) as exc:
            raise HostError("HOST_OFFLINE", str(exc)) from exc
        finally:
            connection.close()

    def handshake(self) -> dict:
        self.session_id = self.runtime_instance_id = ""
        response = self.request("/v1/handshake")
        if set(response) != {"protocol", "plugin_id", "session_id", "runtime_instance_id"} or any(
                not isinstance(response.get(key), str) or not re.fullmatch(r"[a-f0-9]{32}", response[key])
                for key in ("session_id", "runtime_instance_id")):
            raise HostError("HOST_HANDSHAKE", "Malformed handshake identities or fields")
        self.session_id = response["session_id"]
        self.runtime_instance_id = response["runtime_instance_id"]
        return response

    def scoped_request(self, path: str, fields: dict | None = None) -> dict:
        return self.request(path, {"session_id": self.session_id,
                                  "runtime_instance_id": self.runtime_instance_id, **(fields or {})})

    def snapshot(self) -> dict:
        return self.scoped_request("/v1/snapshot")

    def poll(self, after: int) -> dict:
        return self.scoped_request("/v1/poll", {"after": after})

    def command(self, component_id: str, *, command_id: str | None = None,
                placement_id: str | None = None, payload: Any = None,
                action_parameter: str | None = None, operation: str = "command",
                adjustment_diff: int | None = None,
                editor_values: dict[str, Any] | None = None) -> dict:
        return self.scoped_request("/v1/command", {
            "command_id": command_id or uuid.uuid4().hex, "component_id": component_id,
            "placement_id": placement_id, "payload": {} if payload is None else payload,
            "action_parameter": action_parameter, "operation": operation,
            "adjustment_diff": adjustment_diff, "editor_values": editor_values,
        })
