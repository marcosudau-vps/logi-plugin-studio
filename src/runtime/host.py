"""Headless public Host API; owns the accepted StateStore and dispatch plan."""
from __future__ import annotations

import copy
import hashlib
import hmac
import logging
import queue
import re
import socket
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from core.compat import check_value
from core.io import load_raw
from core.registry import load_manifests
from runtime.dispatcher import InMemoryRuntime
from runtime.plan import compile_plan
from runtime.state_store import ScopeAddress, StateStore, WriterIdentity
from runtime.wire import (MAX_CLOCK_SKEW, MAX_REQUEST, MAX_RESPONSE, PROTOCOL,
                          ConnectionSettings, HostError, json_bytes, parse_json,
                          project_digest, signature)

LOG = logging.getLogger("pluginstudio.host")
MANIFESTS = Path(__file__).resolve().parents[2] / "component_types"
Handler = Callable[[Any, "CommandContext"], Any]
# Upper bounds for discarding a rejected request's body. Below the 2 s socket
# timeout, so a rejected connection holds its slot no longer than an idle one.
DRAIN_SECONDS = 1.0
DRAIN_BYTES = 16 * MAX_REQUEST
# AP-POLISH-001: a self-hosted plugin host runs as long as the plugin is loaded.
# Finished commands older than this are no longer needed for deduplication: the
# C# bridge never resends a command (COMMAND_UNKNOWN_OUTCOME_NO_RETRY), signed
# frames expire after MAX_CLOCK_SKEW and idle sessions after 60 s. Without this
# the host refused every key press after 4096 commands until it was restarted.
COMMAND_RETENTION_SECONDS = 120.0
FINAL_COMMAND_STATES = frozenset({"COMPLETED", "FAILED", "REJECTED_TIMEOUT", "UNKNOWN_OUTCOME", "CANCELLED"})


@dataclass(frozen=True)
class CommandContext:
    command_id: str
    component_id: str
    placement_id: str | None
    target_component: str
    target_port: str
    _host: "PluginHost"
    action_parameter: str | None = None
    operation: str = "command"
    adjustment_diff: int | None = None
    editor_values: dict[str, Any] | None = None

    def set_state(self, state_id: str, value: Any, scope: ScopeAddress | None = None) -> dict:
        with self._host._lock:
            self._host._check_command_active(self.command_id)
            authority = self._host._authorities.get(state_id, {})
            if authority.get("role") == "component":
                if authority.get("component") != self.target_component:
                    raise HostError("STATE_AUTH_VIOLATION", "Handler does not own this state")
                writer = WriterIdentity.component(self.target_component)
            else:
                writer = self._host._host_writer
            return self._host._write_state(state_id, value, scope or ScopeAddress.runtime(), writer)

    def emit(self, port: str, payload: Any) -> dict:
        with self._host._lock:
            self._host._check_command_active(self.command_id)
        depth = getattr(self._host._local, "event_depth", 0)
        if depth >= 8:
            raise HostError("EVENT_REENTRANCY_LIMIT", "Nested explicit emission limit reached")
        json_bytes(payload, limit=MAX_REQUEST)
        self._host._local.event_depth = depth + 1
        try:
            report = self._host._dispatcher.dispatch_event(
                self.target_component, port, payload, correlation_id=self.command_id)
        finally:
            self._host._local.event_depth = depth
        with self._host._lock:
            self._host._check_command_active(self.command_id)
            self._host._append("event", {"component_id": self.target_component,
                                         "port": port, "report": report})
        if report["status"] == "REJECTED":
            raise HostError("EVENT_REJECTED", str(report["diagnostics"]))
        return report


class PluginHost:
    def __init__(self, project: str | Path | dict, settings: ConnectionSettings,
                 *, manifest_dir: str | Path = MANIFESTS, command_timeout: float = 5,
                 journal_capacity: int = 1024, command_capacity: int = 4096) -> None:
        raw = load_raw(project) if isinstance(project, (str, Path)) else copy.deepcopy(project)
        json_bytes(raw, limit=16 * MAX_RESPONSE)
        if not isinstance(raw, dict):
            raise HostError("PROJECT_INVALID", "Project must be a JSON object")
        source_raw = raw
        header = raw.get("plugin") if raw.get("schema_version") == "logitech-native-1" else raw.get("project")
        if not isinstance(header, dict):
            raise HostError("PROJECT_INVALID", "Project metadata must be an object")
        if settings.project_hash != project_digest(source_raw) or settings.plugin_id != header.get("id"):
            raise HostError("PROJECT_MISMATCH", "Connection and project fingerprints differ")
        if raw.get("schema_version") == "logitech-native-1":
            try:
                from adapters.logitech.native import runtime_projection
                raw = runtime_projection(raw)
            except ValueError as exc:
                raise HostError("PROJECT_INVALID", str(exc)) from exc
        if command_timeout <= 0 or journal_capacity < 1 or command_capacity < 1:
            raise HostError("HOST_CONFIG", "Timeout and buffer capacities must be positive")
        registry, registry_issues = load_manifests(manifest_dir)
        plan, issues = compile_plan(raw, registry)
        if plan is None or any(d.severity == "ERROR" for d in [*registry_issues, *issues]):
            raise HostError("PROJECT_INVALID", "; ".join(f"{d.code} {d.path}: {d.message}" for d in [*registry_issues, *issues]))
        store, issues = StateStore.create(raw, registry)
        if store is None:
            raise HostError("STATE_INVALID", "; ".join(f"{d.code} {d.path}: {d.message}" for d in issues))
        self.settings = settings
        self._raw = raw
        self._plan = plan
        self._dispatcher = InMemoryRuntime(plan)
        self._store = store
        json_bytes(store.snapshot(), limit=MAX_RESPONSE // 2)
        self._host_writer = WriterIdentity.host(uuid.uuid4().hex)
        self._authorities = {s["id"]: s["authority"] for s in raw["states"]}
        self._lock = threading.RLock()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=64)
        self._journal: deque[dict] = deque(maxlen=journal_capacity)
        self._commands: dict[str, dict] = {}
        self._command_capacity = command_capacity
        self._seq = 0
        self._timeout = command_timeout
        self._sessions: OrderedDict[str, float] = OrderedDict()
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._stop = threading.Event()
        self._server: _Server | None = None
        self._threads: list[threading.Thread] = []
        self._started = False
        self._closed = False
        self._observers: list[Callable[[dict], None]] = []
        self._local = threading.local()

    @property
    def runtime_instance_id(self) -> str:
        return self._store.runtime_instance_id

    def register_handler(self, component_id: str, port: str, handler: Handler) -> None:
        if self._started:
            raise HostError("REGISTRATION_CLOSED", "Register trusted handlers before starting the host")
        if not callable(handler) or (component_id, port) not in self._plan.targets:
            raise HostError("HANDLER_ENDPOINT", "Handler must address a connected input port")

        def invoke(payload: Any, internal: dict) -> dict:
            context = getattr(self._local, "context", None)
            if context is None:
                raise HostError("COMMAND_CONTEXT", "No active trusted dispatch context")
            typed = replace(context, target_component=component_id, target_port=port)
            result = handler(payload, typed)
            json_bytes(result, limit=MAX_REQUEST)
            return {"result": result}

        self._dispatcher.register_handler(component_id, port, invoke)

    def observe(self, callback: Callable[[dict], None]) -> None:
        if not callable(callback) or self._started:
            raise HostError("OBSERVER_REGISTRATION", "Register callable observers before start")
        self._observers.append(callback)

    def _append(self, kind: str, data: dict) -> dict:
        json_bytes(data, limit=MAX_REQUEST)
        self._seq += 1
        entry = {"seq": self._seq, "kind": kind, "data": copy.deepcopy(data)}
        self._journal.append(entry)
        LOG.info("%s seq=%s", kind, self._seq)
        return entry

    def _write_state(self, state_id: str, value: Any, scope: ScopeAddress, writer: WriterIdentity) -> dict:
        json_bytes(value, limit=MAX_REQUEST // 4)
        if self._closed:
            raise HostError("HOST_CLOSED", "Host is closed")
        before = self._store.read(state_id, scope)
        if before["status"] != "OK":
            raise HostError(before["status"], str(before["issues"]))
        # Check the entire candidate snapshot before committing, not after mutation.
        candidate = self._store.snapshot()
        candidate["states"][before["scope_key"]]["value"] = value
        json_bytes(candidate, limit=MAX_RESPONSE // 2)
        result = self._store.write(state_id, scope, value, writer=writer)
        if result["status"] != "OK":
            raise HostError(result["status"], str(result["issues"]))
        entry = self._store.read(state_id, scope)
        self._append("state", entry)
        return entry

    def set_state(self, state_id: str, value: Any, scope: ScopeAddress | None = None) -> dict:
        with self._lock:
            # Handler writes must use its expiring CommandContext.
            if getattr(self._local, "context", None) is not None:
                raise HostError("CONTEXT_REQUIRED", "Use context.set_state from a handler")
            return self._write_state(state_id, value, scope or ScopeAddress.runtime(), self._host_writer)

    def read_state(self, state_id: str, scope: ScopeAddress | None = None) -> dict:
        with self._lock:
            entry = self._store.read(state_id, scope or ScopeAddress.runtime())
            if entry["status"] != "OK":
                raise HostError(entry["status"], str(entry["issues"]))
            return entry

    def snapshot(self) -> dict:
        with self._lock:
            return {"seq": self._seq, "snapshot": self._store.snapshot()}

    def diagnostics(self) -> dict:
        with self._lock:
            return {"runtime_instance_id": self.runtime_instance_id,
                    "plugin_id": self.settings.plugin_id, "port": self.settings.port,
                    "running": self._started and not self._closed,
                    "queue_depth": self._queue.qsize(), "sequence": self._seq,
                    "session_count": len(self._sessions), "command_count": len(self._commands),
                    "recent": copy.deepcopy(list(self._journal)[-20:])}

    def _check_command_active(self, command_id: str) -> None:
        command = self._commands.get(command_id)
        if self._closed or command is None or command["status"] not in ("QUEUED", "RUNNING"):
            raise HostError("COMMAND_EXPIRED", "Command no longer has authority to produce effects")
        if time.monotonic() >= command["deadline"]:
            raise HostError("COMMAND_EXPIRED", "Command deadline elapsed")

    def _command(self, message: dict) -> dict:
        cid, component = message.get("command_id"), message.get("component_id")
        if not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{32}", cid):
            raise HostError("COMMAND_ID", "Expected a UUID hex command ID")
        if not isinstance(component, str):
            raise HostError("COMMAND_ENDPOINT", "Component ID must be a string")
        payload = message.get("payload")
        action_parameter = message.get("action_parameter")
        if action_parameter is not None and (not isinstance(action_parameter, str) or len(action_parameter) > 4096):
            raise HostError("COMMAND_ACTION_PARAMETER", "action_parameter must be null or a string of at most 4096 characters")
        operation = message.get("operation", "command")
        if operation not in ("command", "adjustment", "action_editor"):
            raise HostError("COMMAND_OPERATION", "Unknown native SDK operation")
        adjustment_diff = message.get("adjustment_diff")
        editor_values = message.get("editor_values")
        if operation == "adjustment":
            if type(adjustment_diff) is not int:
                raise HostError("COMMAND_ADJUSTMENT", "Adjustment operation requires an integer diff")
        elif adjustment_diff is not None:
            raise HostError("COMMAND_ADJUSTMENT", "adjustment_diff is valid only for adjustment operations")
        if operation == "action_editor":
            if not isinstance(editor_values, dict) or any(not isinstance(k, str) for k in editor_values):
                raise HostError("COMMAND_EDITOR_VALUES", "Action Editor operation requires an object of control values")
        elif editor_values is not None:
            raise HostError("COMMAND_EDITOR_VALUES", "editor_values is valid only for Action Editor operations")
        fingerprint = hashlib.sha256(json_bytes({
            "component": component, "placement": message.get("placement_id"), "payload": payload,
            "action_parameter": action_parameter, "operation": operation,
            "adjustment_diff": adjustment_diff, "editor_values": editor_values})).hexdigest()
        with self._lock:
            previous = self._commands.get(cid)
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    raise HostError("COMMAND_ID_REUSE", "Command ID reused with different contents")
                return {"command_id": cid, "status": previous["status"], "duplicate": True}
            if len(self._commands) >= self._command_capacity:
                self._forget_finished_commands()
            if len(self._commands) >= self._command_capacity:
                raise HostError("COMMAND_CAPACITY", "Deduplication capacity reached; explicit host restart required")
            meta = self._plan.components.get(component)
            port = meta.get("ports", {}).get("activated") if meta else None
            if port is None or port["direction"] != "out" or port["kind"] != "command":
                raise HostError("COMMAND_ENDPOINT", "Unknown outgoing command action")
            problems = check_value(payload, port["payload_schema"])
            if problems:
                raise HostError("COMMAND_PAYLOAD", str(problems))
            routes = [c for c in self._plan.connections
                      if c.source_component == component and c.source_port == "activated" and c.kind == "command"]
            if not routes or any((r.target_component, r.target_port) not in self._dispatcher._handlers for r in routes):
                raise HostError("COMMAND_NO_HANDLER", "No fully registered command route")
            placement = message.get("placement_id")
            if placement is not None and not any(
                p["id"] == placement and p["component"] == component
                for v in self._raw["views"] for p in v["placements"]
            ):
                raise HostError("COMMAND_PLACEMENT", "Placement does not refer to this action")
            command = {"fingerprint": fingerprint, "component_id": component,
                        "placement_id": placement, "payload": copy.deepcopy(payload),
                       "action_parameter": action_parameter, "operation": operation,
                       "adjustment_diff": adjustment_diff, "editor_values": copy.deepcopy(editor_values),
                        "deadline": time.monotonic() + self._timeout, "status": "QUEUED"}
            try:
                self._queue.put_nowait(cid)
            except queue.Full as exc:
                raise HostError("COMMAND_BUSY", "Bounded command queue is full") from exc
            self._commands[cid] = command
            return {"command_id": cid, "status": "QUEUED", "duplicate": False}

    def _forget_finished_commands(self) -> int:
        """Drop deduplication entries that finished more than the retention ago (caller holds the lock)."""
        limit = time.monotonic() - COMMAND_RETENTION_SECONDS
        stale = [cid for cid, command in self._commands.items()
                 if command["status"] in FINAL_COMMAND_STATES and command.get("finished", limit + 1) <= limit]
        for cid in stale:
            del self._commands[cid]
        return len(stale)

    def _finish(self, cid: str, status: str, report: dict | None = None) -> None:
        self._commands[cid]["finished"] = time.monotonic()
        self._commands[cid]["status"] = status
        self._append("command_result", {"command_id": cid, "status": status, "report": report})

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                cid = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if cid is None:
                break
            with self._lock:
                command = self._commands[cid]
                if command["status"] != "QUEUED":
                    continue
                if time.monotonic() >= command["deadline"]:
                    self._finish(cid, "REJECTED_TIMEOUT")
                    continue
                command["status"] = "RUNNING"
                context = CommandContext(
                    cid, command["component_id"], command["placement_id"], "", "", self,
                    command["action_parameter"], command["operation"], command["adjustment_diff"],
                    copy.deepcopy(command["editor_values"]),
                )
            self._local.context = context
            try:
                report = self._dispatcher.dispatch_command(
                    context.component_id, "activated", command["payload"], correlation_id=cid)
                json_bytes(report, limit=MAX_REQUEST)
            except HostError as exc:
                report = {"status": "REJECTED", "diagnostics": [{"code": exc.code, "message": str(exc)}]}
            finally:
                self._local.context = None
            with self._lock:
                if command["status"] == "RUNNING":
                    success = report["status"] != "REJECTED" and all(
                        d["status"] == "OK" for d in report.get("deliveries", []))
                    self._finish(cid, "COMPLETED" if success else "FAILED", report)

    def _watch(self) -> None:
        while not self._stop.wait(0.05):
            with self._lock:
                now = time.monotonic()
                for cid, command in self._commands.items():
                    if command["status"] in ("QUEUED", "RUNNING") and now >= command["deadline"]:
                        self._finish(cid, "UNKNOWN_OUTCOME" if command["status"] == "RUNNING" else "REJECTED_TIMEOUT")

    def _observe(self) -> None:
        seen = 0
        while not self._stop.wait(0.05):
            with self._lock:
                entries = copy.deepcopy([e for e in self._journal if e["seq"] > seen])
                if entries:
                    if entries[0]["seq"] != seen + 1:
                        LOG.warning("Observer journal gap; resnapshot required")
                    seen = entries[-1]["seq"]
            for entry in entries:
                for observer in self._observers:
                    try:
                        observer(copy.deepcopy(entry))
                    except Exception:
                        LOG.exception("Observer failed at seq=%s", entry["seq"])

    def _handle(self, path: str, nonce: str, tag: str, body: bytes) -> dict:
        expected = signature(self.settings.secret, path + "\n" + nonce + "\n", body)
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not hmac.compare_digest(tag, expected):
            raise HostError("HOST_UNTRUSTED", "Request authentication failed")
        message = parse_json(body)
        if message.get("protocol") != PROTOCOL:
            raise HostError("PROTOCOL_MISMATCH", "Unsupported protocol")
        if any(message.get(key) != getattr(self.settings, key)
               for key in ("plugin_id", "project_hash", "installation_id")):
            raise HostError("PLUGIN_MISMATCH", "Plugin, project or installation does not match")
        sent = message.get("sent_at")
        if type(sent) is not int or abs(time.time() - sent) > MAX_CLOCK_SKEW:
            raise HostError("FRAME_EXPIRED", "Signed request timestamp is outside the allowed window")
        base = {"protocol", "plugin_id", "project_hash", "installation_id", "sent_at"}
        allowed = {
            "/v1/handshake": base,
            "/v1/snapshot": base | {"session_id", "runtime_instance_id"},
            "/v1/poll": base | {"session_id", "runtime_instance_id", "after"},
            "/v1/command": base | {"session_id", "runtime_instance_id", "command_id",
                                    "component_id", "placement_id", "payload", "action_parameter",
                                    "operation", "adjustment_diff", "editor_values"},
        }
        fields = set(message)
        legacy_command_fields = base | {"session_id", "runtime_instance_id", "command_id",
                                        "component_id", "placement_id", "payload"}
        if path not in allowed or (fields != allowed[path] and
                                   not (path == "/v1/command" and fields == legacy_command_fields)):
            raise HostError("FRAME_FIELDS", "Unknown endpoint, missing or unexpected fields")
        with self._lock:
            now = time.monotonic()
            while self._nonces and next(iter(self._nonces.values())) < now - 60:
                self._nonces.popitem(last=False)
            if nonce in self._nonces:
                raise HostError("FRAME_REPLAY", "Request nonce was already consumed")
            if len(self._nonces) >= 8192:
                raise HostError("HOST_BUSY", "Replay cache capacity reached")
            self._nonces[nonce] = now
            if path == "/v1/handshake":
                session = uuid.uuid4().hex
                while self._sessions and next(iter(self._sessions.values())) < now - 60:
                    self._sessions.popitem(last=False)
                if len(self._sessions) >= 16:
                    raise HostError("HOST_BUSY", "Session capacity reached")
                self._sessions[session] = now
                return {"session_id": session, "runtime_instance_id": self.runtime_instance_id}
            session = message.get("session_id")
            if not isinstance(session, str) or session not in self._sessions:
                raise HostError("SESSION_UNKNOWN", "A valid handshake is required")
            if now - self._sessions[session] > 60:
                del self._sessions[session]
                raise HostError("SESSION_EXPIRED", "Reconnect with a new handshake")
            if message.get("runtime_instance_id") != self.runtime_instance_id:
                raise HostError("RUNTIME_CHANGED", "Previous runtime identity is invalid")
            self._sessions[session] = now
            self._sessions.move_to_end(session)
            if path == "/v1/snapshot":
                return self.snapshot()
            if path == "/v1/poll":
                after = message["after"]
                if type(after) is not int or after < 0 or after > self._seq:
                    raise HostError("STREAM_POSITION", "Invalid journal position")
                if self._journal and after < self._journal[0]["seq"] - 1:
                    return {"resync": True, "entries": [], "seq": self._seq}
                entries = [e for e in self._journal if e["seq"] > after][:8]
                return {"resync": False, "entries": copy.deepcopy(entries),
                        "seq": entries[-1]["seq"] if entries else after}
            return self._command(message)

    def start(self) -> "PluginHost":
        if self._started or self._closed:
            raise HostError("HOST_LIFECYCLE", "A Host instance can be started exactly once")
        try:
            self._server = _Server(("127.0.0.1", self.settings.port), _Request)
        except OSError as exc:
            raise HostError("HOST_PORT_BUSY", str(exc)) from exc
        self._server.host = self
        self.settings = replace(self.settings, port=self._server.server_port)
        self._started = True
        self._threads = [threading.Thread(target=target, name=name, daemon=True)
                         for target, name in ((self._server.serve_forever, "studio-http"),
                                              (self._work, "studio-handler"),
                                              (self._watch, "studio-watch"),
                                              (self._observe, "studio-observers"))]
        for thread in self._threads:
            thread.start()
        LOG.info("Host started plugin=%s port=%s runtime=%s", self.settings.plugin_id,
                 self.settings.port, self.runtime_instance_id)
        return self

    def close(self) -> list[str]:
        if self._closed:
            return []
        with self._lock:
            self._closed = True
            for cid, command in self._commands.items():
                if command["status"] in ("QUEUED", "RUNNING"):
                    self._finish(cid, "UNKNOWN_OUTCOME" if command["status"] == "RUNNING" else "CANCELLED")
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
        pending = [t.name for t in self._threads if t.is_alive()]
        if pending:
            LOG.error("Shutdown incomplete; trusted callback still running: %s", pending)
        return pending

    def __enter__(self) -> "PluginHost":
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.close()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 16
    host: PluginHost

    def __init__(self, *args: Any) -> None:
        self._slots = threading.BoundedSemaphore(16)
        super().__init__(*args)

    def process_request(self, request: Any, client_address: Any) -> None:
        request.settimeout(2)
        if not self._slots.acquire(blocking=False):
            LOG.warning("HTTP connection limit reached")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _Request(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *_: Any) -> None:
        pass

    def do_POST(self) -> None:
        nonce = self.headers.get("X-Studio-Nonce", "")
        status = 200
        body_unread = True
        try:
            if not re.fullmatch(r"[a-f0-9]{32}", nonce):
                raise HostError("FRAME_NONCE", "Invalid nonce")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
                raise HostError("FRAME_LENGTH", "Exactly one explicit Content-Length is required")
            length = int(lengths[0])
            if not 0 < length <= MAX_REQUEST:
                raise HostError("FRAME_SIZE", "Invalid request size")
            if self.headers.get_content_type() != "application/json":
                raise HostError("FRAME_CONTENT_TYPE", "Expected application/json")
            body_unread = False
            body = self.rfile.read(length)
            if len(body) != length:
                raise HostError("FRAME_LENGTH", "Truncated request body")
            result = self.server.host._handle(
                self.path, nonce, self.headers.get("X-Studio-Signature", ""), body)
        except HostError as exc:
            status = 400
            result = {"code": exc.code, "message": str(exc)}
            LOG.warning("Request rejected path=%s code=%s", self.path, exc.code)
        except (OSError, ValueError, OverflowError) as exc:
            status = 400
            result = {"code": "FRAME_IO", "message": type(exc).__name__}
            LOG.warning("Request IO failed: %s", type(exc).__name__)
        result = {"protocol": PROTOCOL, "plugin_id": self.server.host.settings.plugin_id, **result}
        data = json_bytes(result)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if re.fullmatch(r"[a-f0-9]{32}", nonce):
            self.send_header("X-Studio-Signature", signature(self.server.host.settings.secret, nonce + "\n", data))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            LOG.warning("Client disconnected before response delivery")
        if body_unread:
            self._discard_rejected_body()

    def _discard_rejected_body(self) -> None:
        """Half-close, then drop what the client still sends, within fixed bounds.

        Clients may send header and body separately. If the body reaches an
        already closed socket, TCP answers with a reset, and the client loses
        the explicit rejection it has not read yet (WinError 10053 on Windows).
        Dropped bytes are never parsed or stored.
        """
        deadline = time.monotonic() + DRAIN_SECONDS
        remaining = DRAIN_BYTES
        try:
            self.connection.shutdown(socket.SHUT_WR)
            while remaining > 0:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    return
                self.connection.settimeout(wait)
                chunk = self.connection.recv(min(8192, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
        except OSError:
            pass
