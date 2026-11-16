"""Shared host adapter. It reuses the native host's single command and state path."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from collections import OrderedDict
import logging
import os
import threading
import time

from adapters.logitech.native import parse_native_project
from runtime.wire import HostError, json_bytes, parse_json

from .host import FolderRuntimeHost
from .peer_projection import node_view, offered_nodes, references, render
from .peer_runtime import MAX_PENDING, PeerRuntime, Scope
from .peer_wire import MAX_SCOPES, PeerError, identity, shape

LOG = logging.getLogger(__name__)
SUPPORTED = {"PluginDynamicCommand", "PluginMultistateDynamicCommand", "PluginDynamicAdjustment"}
SDK_CONTROL = "@shared-folder"
SDK_TIMEOUT = 4
# Remote action images (presentation only): PNG, content addressed, bounded.
IMAGE_LIMIT = 24576
IMAGE_DIMENSION = 512
IMAGE_CACHE_ENTRIES = 64


def decode_image(image_hash, data):
    """Validated PNG bytes for a view's ``image`` field, or None if absent."""
    if data is None:
        return None
    if (not isinstance(data, str) or len(data) > (IMAGE_LIMIT + 2) // 3 * 4 or not isinstance(image_hash, str)
            or len(image_hash) != 64):
        raise PeerError("SDK_IMAGE")
    try:
        png = base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as exc:
        raise PeerError("SDK_IMAGE") from exc
    if (len(png) > IMAGE_LIMIT or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR"
            or hashlib.sha256(png).hexdigest() != image_hash):
        raise PeerError("SDK_IMAGE")
    width, height = struct.unpack(">II", png[16:24])
    if not (0 < width <= IMAGE_DIMENSION and 0 < height <= IMAGE_DIMENSION):
        raise PeerError("SDK_IMAGE")
    return png


class SharedFolderHost(FolderRuntimeHost):
    _allow_peer_layout = True
    def __init__(self, project, settings, *, folder_runtime, shared_references, directory, trust, **kwargs):
        super().__init__(project, settings, folder_runtime=folder_runtime, **kwargs)
        native = parse_native_project(self._folder_source)
        self._authored = self._folder_layout
        self._external = references(shared_references, self._authored)
        self._nodes = offered_nodes(self._authored) if any(
            s.kind == "folder" for t in trust.values() for s in t.grants) else {}
        self._encoder = {f.id for f in native.folders if f.navigation != "EncoderArea"
                         and "EncoderArea" not in f.device_navigation.values()}
        self._offers = {}
        self._actions = {a.id: a for a in native.actions}
        grants = {s for t in trust.values() for s in t.grants}
        if len(grants) > MAX_SCOPES:
            raise PeerError("EXPORT_SCOPE_CAPACITY")
        for scope in grants:
            if scope.kind == "folder":
                node = self._nodes.get(scope.resource)
                if node is None:
                    raise PeerError("UNKNOWN_FOLDER_EXPORT")
                self._offers[scope] = dict(label=node["label"], operations=[], sdk_type="")
                continue
            action = self._actions.get(scope.resource)
            if action is None or action.sdk_type not in SUPPORTED:
                raise PeerError("FOLDER_REMOTE_ACTION_UNSUPPORTED")
            if scope.parameter is not None and scope.parameter not in {p.name for p in action.parameters}:
                raise PeerError("UNKNOWN_ACTION_PARAMETER")
            operations = ["command"]
            if action.sdk_type == "PluginDynamicAdjustment":
                operations = ["adjustment", "command"] if action.has_reset else ["adjustment"]
            self._offers[scope] = dict(label=action.display_name, operations=operations, sdk_type=action.sdk_type)
        json_bytes({"scopes": [s.wire() for s in grants]}, limit=48 * 1024)
        self.peer = PeerRuntime(native.plugin_id, directory, trust, self._offers,
                                invoke=self._owner_invoke, changed=self._update_projection,
                                subscriptions_changed=self._sync_watches)
        self._sdk_pending = {}
        self._sdk_views = {}
        self._outgoing = 0
        self._watch_scopes = set()
        self._sdk_generation = None
        self._sdk_session = None
        self._sdk_contact = 0
        self._sdk_ready = threading.Event()
        self._ending = threading.Event()
        self._peer_loop = None
        self._last_projection = self._folder_layout
        self._images = OrderedDict()  # hash -> PNG bytes received from owners (consumer side)
        self._delivered = set()  # hashes sent to the current SDK generation
        self._peer_thread = threading.Thread(target=self._run_peer, name="shared-folder-peer", daemon=True)

    def start(self):
        super().start()
        self._peer_thread.start()
        return self

    def close(self):
        self._ending.set()
        self._sdk_ready.set()
        if self._peer_thread.is_alive():
            self._peer_thread.join(timeout=5)
        pending = super().close()
        if self._peer_thread.is_alive():
            pending.append(self._peer_thread.name)
        return pending

    def _run_peer(self):
        self._sdk_ready.wait()
        if self._ending.is_set():
            return

        async def run():
            self._peer_loop = asyncio.get_running_loop()
            try:
                await self.peer.start()
                self._update_projection()
                next_status = 0.0
                while not self._ending.is_set():
                    with self._lock:
                        if self._sdk_session is not None and not self._sdk_online():
                            self._sdk_session = None
                            self._sdk_views.clear()
                            self._invalidate_views()
                    if time.monotonic() >= next_status:
                        next_status = time.monotonic() + 1.0
                        self._write_status()
                    await asyncio.sleep(0.1)
            finally:
                await self.peer.close()
                self._remove_status()
                self._peer_loop = None
        try:
            asyncio.run(run())
        except (OSError, PeerError, HostError) as exc:
            LOG.warning("Shared discovery unavailable (%s: %s)", type(exc).__name__, exc)
        except Exception:
            LOG.exception("Shared peer loop failed")
            raise

    def _status_path(self):
        # Sibling of discovery/; same hashed naming. Contains no keys or grants.
        return self.peer.discovery.directory.parent / "status" / (
            hashlib.sha256(self.peer.plugin.encode()).hexdigest() + ".json")

    def _write_status(self):
        try:
            peers = {}
            for plugin in self.peer.trust:
                link = self.peer.links.get(plugin)
                peers[plugin] = dict(self.peer.health(plugin), connected=link is not None and not link.closed,
                                     instance=link.instance if link is not None else None,
                                     offers=len(link.catalog) if link is not None else 0,
                                     views=len(link.views) if link is not None else 0)
            with self._lock:
                sdk = self._sdk_online()
            row = dict(format="shared-folder-status-1", plugin=self.peer.plugin, instance=self.peer.instance,
                       time=time.time(), sdk_attached=sdk, peers=peers,
                       inbound_subscriptions=len(self.peer.subscribed()), wanted=len(self.peer.wanted))
            path = self._status_path()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = path.with_suffix("." + self.peer.instance + ".tmp")
            temporary.write_bytes(json_bytes(row))
            os.replace(temporary, path)
        except (OSError, ValueError, HostError, RuntimeError):
            pass

    def _remove_status(self):
        try:
            self._status_path().unlink(missing_ok=True)
        except OSError:
            pass

    def snapshot(self):
        with self._lock:
            data = super().snapshot()
            data["shared_watch"] = [scope.wire() for scope in self._watch_scopes]
            return data

    def _sync_watches(self):
        scopes = self.peer.subscribed()
        with self._lock:
            watches = {scope for scope in scopes if scope.kind == "action"}
            if watches != self._watch_scopes:
                removed = self._watch_scopes - watches
                self._watch_scopes = watches
                for scope in removed:
                    self._sdk_views.pop(scope, None)
                    self.peer.values.pop(scope, None)
                self._append("event", dict(component_id="host", port="peer.watch",
                                           report=[scope.wire() for scope in watches]))
        for scope in scopes:
            if scope.kind == "folder" and scope not in self.peer.values:
                try:
                    self.peer.publish(scope, node_view(self._nodes[scope.resource], self.peer.plugin, self._external))
                except HostError:
                    self.peer.publish(scope, dict(available=False, label=self._offers[scope]["label"]))

    def _collect_images(self):
        """Cache validated owner images of subscribed scopes (content addressed)."""
        for link in tuple(self.peer.links.values()):
            for _, view in tuple(link.views.values()):
                image_hash = view.get("image_hash")
                if not isinstance(image_hash, str) or image_hash in self._images:
                    continue
                try:
                    png = decode_image(image_hash, view.get("image"))
                except PeerError:
                    LOG.warning("Remote image rejected")
                    continue
                if png is not None:
                    self._images[image_hash] = png
                    while len(self._images) > IMAGE_CACHE_ENTRIES:
                        old, _ = self._images.popitem(last=False)
                        self._delivered.discard(old)

    def _deliver_images(self, layout):
        """Send each image a rendered peer entry needs once per SDK generation."""
        needed = {e.get("image_hash") for f in layout["folders"] for n in f["nodes"] for p in n["pages"]
                  for e in p["entries"] if e["kind"] == "peer_action"}
        for image_hash in sorted(h for h in needed if h in self._images and h not in self._delivered):
            self._append("event", dict(component_id="host", port="peer.image", report=dict(
                hash=image_hash, data=base64.b64encode(self._images[image_hash]).decode("ascii"))))
            self._delivered.add(image_hash)
            self._images.move_to_end(image_hash)

    def _update_projection(self):
        with self._lock:
            current = self._last_projection
            self._collect_images()
            candidate, wanted = render(self._authored, self._external, self.peer, self._encoder)
            self.peer.set_wanted(wanted)
            self._deliver_images(candidate)
            candidate["revision"] = current["revision"]
            if candidate == current:
                return
            candidate["revision"] += 1
            try:
                self.replace_folder_layout(candidate)
            except (HostError, ValueError):
                LOG.warning("Shared projection rejected; using local layout")
                candidate = dict(self._authored, revision=current["revision"] + 1)
                self.replace_folder_layout(candidate)
            self._last_projection = candidate

    def _command(self, message):
        if message.get("component_id") != SDK_CONTROL:
            return super()._command(message)
        fields = message.get("editor_values")
        cid = message.get("command_id")
        if (not identity(cid) or message.get("operation") != "action_editor" or not isinstance(fields, dict)
                or message.get("placement_id") is not None or message.get("action_parameter") is not None
                or message.get("adjustment_diff") is not None or message.get("payload") != {}):
            raise HostError("PEER_CONTROL", "Invalid SDK control envelope")
        try:
            status = self._sdk_control(fields, message.get("session_id"))
        except (PeerError, TypeError) as exc:
            raise HostError("PEER_CONTROL", "Invalid SDK control payload") from exc
        return {"command_id": cid, "status": status, "duplicate": False}

    def _handle(self, path, nonce, tag, body):
        result = super()._handle(path, nonce, tag, body)
        if path == "/v1/poll":
            with self._lock:
                if self._sdk_session is not None and parse_json(body).get("session_id") == self._sdk_session:
                    self._sdk_contact = time.monotonic()
        return result

    def _sdk_online(self):
        return self._sdk_session is not None and time.monotonic() - self._sdk_contact <= SDK_TIMEOUT

    def _sdk_control(self, fields, session):
        kind = fields.get("kind")
        if kind == "ready":
            shape(fields, "kind", "generation")
            if not identity(fields["generation"]):
                raise PeerError("SDK_GENERATION")
            if self._sdk_generation != fields["generation"]:
                self._sdk_generation = fields["generation"]
                self._sdk_views.clear()
                self._delivered.clear()
                self._schedule(self._invalidate_views)
                self._schedule(self._update_projection)
            self._sdk_session = session
            self._sdk_contact = time.monotonic()
            self._sdk_ready.set()
            return "COMPLETED"
        if session != self._sdk_session or not self._sdk_online():
            return "SDK_NOT_READY"
        if kind == "ack":
            shape(fields, "kind", "ticket", "accepted")
            if not identity(fields["ticket"]) or type(fields["accepted"]) is not bool:
                raise PeerError("SDK_ACK")
            self._schedule(self._accept_sdk, fields["ticket"], fields["accepted"])
            return "COMPLETED"
        if kind == "view":
            shape(fields, "kind", "scope", "view")
            scope = Scope.parse(fields["scope"])
            view = fields["view"]
            shape(view, "label", "available", "value", "state", "image_hash", "image")
            decode_image(view["image_hash"], view["image"])
            if (type(view["available"]) is not bool or not isinstance(view["label"], str)
                    or len(view["label"]) > 1024
                    or view["value"] is not None and not isinstance(view["value"], str)
                    or view["state"] is not None and type(view["state"]) is not int
                    or view["image_hash"] is not None and (not isinstance(view["image_hash"], str)
                                                         or len(view["image_hash"]) != 64)):
                raise PeerError("SDK_VIEW")
            with self._lock:
                if scope in self._watch_scopes and self._sdk_views.get(scope) != view:
                    self._sdk_views[scope] = view
                    self._schedule(self._publish_sdk, scope)
            return "COMPLETED"
        if kind == "forward":
            shape(fields, "kind", "placement", "peer", "instance", "scope", "operation", "diff")
            scope = Scope.parse(fields["scope"])
            with self._lock:
                entry = next((e for f in self._folder_layout["folders"] for n in f["nodes"]
                              for p in n["pages"] for e in p["entries"] if e["id"] == fields["placement"]
                              and e["kind"] == "peer_action"), None)
                if (not entry or entry["peer"] != fields["peer"] or entry["instance"] != fields["instance"]
                        or scope != Scope("action", entry["action_id"], entry.get("action_parameter"))
                        or fields["operation"] not in entry["operations"]):
                    return "DENIED"
                if self._outgoing >= MAX_PENDING or self._peer_loop is None:
                    return "BUSY"
                self._outgoing += 1
                if not self._schedule(self._queue_forward, fields, scope):
                    self._outgoing -= 1
                    return "UNAVAILABLE"
            return "QUEUED"
        raise PeerError("SDK_CONTROL")

    def _schedule(self, fn, *args):
        loop = self._peer_loop
        if loop is None or self._ending.is_set():
            return False
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            return False
        return True

    def _invalidate_views(self):
        for scope in self._watch_scopes.copy():
            self.peer.publish(scope, dict(label=self._offers[scope]["label"], available=False,
                                          value=None, state=None, image_hash=None, image=None))

    def _publish_sdk(self, scope):
        with self._lock:
            view = self._sdk_views.get(scope)
        if view is not None:
            self.peer.publish(scope, view)

    def _accept_sdk(self, ticket, accepted):
        future = self._sdk_pending.get(ticket)
        if future and not future.done():
            future.set_result(accepted)

    def _queue_forward(self, fields, scope):
        async def forward():
            try:
                row = await self.peer.invoke(fields["peer"], fields["instance"], scope, fields["operation"], fields["diff"])
            except (PeerError, HostError, OSError):
                row = dict(status="UNAVAILABLE")
            finally:
                with self._lock:
                    self._outgoing -= 1
            with self._lock:
                self._append("event", dict(component_id="host", port="peer.result",
                                           report=dict(placement=fields["placement"], status=row["status"])))
        self.peer._spawn(forward())

    async def _owner_invoke(self, caller, instance, request, scope, operation, diff):
        action = self._actions[scope.resource]
        ticket = hashlib.sha256(f"{caller}/{instance}/{request}".encode()).hexdigest()[:32]
        with self._lock:
            if not self._sdk_online():
                return "SDK_NOT_READY", None
            routes = [r for r in self._plan.connections if r.source_component == action.id
                      and r.source_port == "activated" and r.kind == "command"]
            if not routes or any((r.target_component, r.target_port) not in self._dispatcher._handlers for r in routes):
                return "NO_HANDLER", None
            if len(self._commands) >= self._command_capacity:
                return "BUSY", None
            future = self._sdk_pending[ticket] = asyncio.get_running_loop().create_future()
            self._append("event", dict(component_id="host", port="peer.invoke",
                                       report=dict(ticket=ticket, scope=scope.wire(), operation=operation,
                                                   diff=diff, expires=int((time.time() + SDK_TIMEOUT) * 1000))))
        try:
            accepted = await asyncio.wait_for(future, SDK_TIMEOUT)
        except TimeoutError:
            return "UNKNOWN_OUTCOME", None
        finally:
            self._sdk_pending.pop(ticket, None)
        if not accepted:
            return "SDK_REJECTED", None
        try:
            super()._command(dict(command_id=ticket, component_id=action.id, payload={},
                                  action_parameter=scope.parameter, operation=operation, adjustment_diff=diff))
        except HostError as exc:
            return exc.code, None
        while not self._ending.is_set():
            with self._lock:
                result = next((e["data"] for e in reversed(self._journal) if e["kind"] == "command_result"
                               and e["data"]["command_id"] == ticket), None)
                if result is not None:
                    return result["status"], result["report"]
                if self._commands[ticket]["status"] not in ("QUEUED", "RUNNING"):
                    return "UNKNOWN_OUTCOME", None
            await asyncio.sleep(0.025)
        return "UNKNOWN_OUTCOME", None
