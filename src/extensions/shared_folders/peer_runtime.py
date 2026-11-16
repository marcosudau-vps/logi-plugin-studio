"""Per-plugin peer lifecycle, scoped push streams and owner request deduplication."""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
import time
from dataclasses import dataclass, field

from runtime.wire import HostError

from .peer_wire import (Discovery, FRAME_TIMEOUT, MAX_PEERS, MAX_SCOPES, PeerError,
                        accept, dial, encode, greeting, identity, resource_id, shape)

LOG = logging.getLogger(__name__)
CAPABILITIES = ["scoped-push", "owner-invoke", "loss-witness"]
MAX_REQUESTS = 4096
MAX_PENDING = 32
ERRORS = (PeerError, HostError, OSError, TimeoutError, EOFError, ValueError, TypeError)
OPERATIONS = {"command", "adjustment"}


@dataclass(frozen=True)
class Scope:
    kind: str
    resource: str
    parameter: str | None = None

    def __post_init__(self):
        if (self.kind not in ("action", "folder") or not resource_id(self.resource)
                or self.parameter is not None and (self.kind != "action" or not isinstance(self.parameter, str)
                                                  or len(self.parameter) > 4096)):
            raise PeerError("INVALID_SCOPE")

    def wire(self):
        return dict(kind=self.kind, resource=self.resource, parameter=self.parameter)

    @classmethod
    def parse(cls, row):
        shape(row, "kind", "resource", "parameter")
        return cls(**row)


@dataclass(frozen=True)
class Trust:
    key: bytes = field(repr=False)
    # A missing grant hides the scope. An empty operation set grants read only.
    grants: dict[Scope, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self):
        if (type(self.key) is not bytes or len(self.key) != 32 or len(self.grants) > MAX_SCOPES
                or any(not isinstance(scope, Scope) or not set(ops) <= OPERATIONS
                       or scope.kind == "folder" and ops for scope, ops in self.grants.items())):
            raise PeerError("INVALID_TRUST")


@dataclass
class Link:
    plugin: str
    instance: str
    channel: object
    catalog: dict = field(default_factory=dict)
    inbound: dict = field(default_factory=dict)  # scope -> (subscription token, revision, view)
    outbound: dict = field(default_factory=dict)  # scope -> subscription token
    views: dict = field(default_factory=dict)  # scope -> (revision, view)
    pings: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    closed: bool = False

    async def send(self, kind, payload):
        if self.closed:
            raise PeerError("PEER_DISCONNECTED")
        await self.channel.send(kind, payload)


class PeerRuntime:
    """All mutable transport state belongs to one asyncio loop."""

    def __init__(self, plugin, directory, trust, offers, *, invoke, changed=lambda: None,
                 subscriptions_changed=lambda: None, heartbeat=3, timeout=12, scan=0.5):
        if (not resource_id(plugin) or plugin in trust or len(trust) > MAX_PEERS
                or any(not resource_id(peer) or not isinstance(config, Trust) for peer, config in trust.items())
                or len({t.key for t in trust.values()}) != len(trust)
                or not 0 < scan <= heartbeat < timeout):
            raise PeerError("PEER_CONFIG")
        self.plugin, self.instance = plugin, uuid.uuid4().hex
        self.discovery = Discovery(directory, plugin, self.instance)
        self.trust = {p: Trust(t.key, {s: frozenset(ops) for s, ops in t.grants.items()}) for p, t in trust.items()}
        self.offers = copy.deepcopy(offers)
        self.execute, self.changed = invoke, changed
        self.subscriptions_changed = subscriptions_changed
        self.heartbeat, self.timeout, self.scan = heartbeat, timeout, scan
        self.wanted, self.links, self.latest = set(), {}, {}
        self.local_health, self.loss = {}, {}
        self._retired = set()
        self.values, self.executions, self.requests = {}, {}, {}
        self._tasks, self._dialing, self._witnessing = set(), set(), set()
        self._incoming = 0
        self._server = None
        self._stopping = False
        self._dirty = asyncio.Event()
        for peer in trust:
            self._catalog(peer)

    def _catalog(self, peer):
        rows = []
        for scope, operations in self.trust[peer].grants.items():
            if scope not in self.offers or not operations <= set(self.offers[scope]["operations"]):
                raise PeerError("INVALID_SCOPE_GRANT")
            rows.append(dict(scope=scope.wire(), label=self.offers[scope]["label"],
                             operations=sorted(operations), sdk_type=self.offers[scope]["sdk_type"]))
        return dict(capabilities=CAPABILITIES, offers=rows)

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        def done(finished):
            self._tasks.discard(finished)
            if not finished.cancelled() and finished.exception() is not None:
                LOG.warning("Peer task failed (%s)", type(finished.exception()).__name__)
        task.add_done_callback(done)
        return task

    async def start(self):
        if self._server is not None or self._stopping:
            raise PeerError("PEER_LIFECYCLE")
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0, backlog=32)
        try:
            self.discovery.start(self._server.sockets[0].getsockname()[1])
        except BaseException:
            self._server.close()
            await self._server.wait_closed()
            raise
        self._spawn(self._scan())
        self._spawn(self._push())
        return self

    async def close(self):
        if self._stopping:
            return
        self._stopping = True
        try:
            # Stop accepting first, but do not wait yet: since Python 3.12
            # Server.wait_closed() also waits for accepted connections, which
            # are only closed after the leave messages below.
            if self._server is not None:
                self._server.close()
            await asyncio.gather(*(link.send("leave", {}) for link in tuple(self.links.values())), return_exceptions=True)
            tasks = tuple(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for link in tuple(self.links.values()):
                try:
                    link.channel.writer.close()
                except (OSError, RuntimeError, AttributeError):
                    pass
            if self._server is not None:
                try:
                    await asyncio.wait_for(self._server.wait_closed(), 2)
                except (TimeoutError, OSError):
                    LOG.warning("Peer server close timed out")
        finally:
            self.discovery.close()

    async def _accept(self, reader, writer):
        if self._incoming >= MAX_PEERS * 2 or self._stopping:
            writer.close()
            return
        self._incoming += 1
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            def resolve(hello):
                peer = hello["plugin"]
                row = self.discovery.read(peer) if peer in self.trust else None
                if (peer >= self.plugin or hello["target"] != self.plugin
                        or hello["target_instance"] != self.instance or row is None
                        or hello["instance"] != row["instance"]):
                    raise PeerError("PEER_IDENTITY")
                return self.trust[peer].key
            hello, channel = await accept(reader, writer, resolve)
            await self._join(hello["plugin"], hello["instance"], channel)
        except ERRORS:
            pass
        finally:
            self._incoming -= 1
            self._tasks.discard(task)
            writer.close()

    async def _scan(self):
        while True:
            for peer in self.trust:
                row = self.discovery.read(peer)
                link = self.links.get(peer)
                if row and link and row["instance"] != link.instance:
                    # Only a freshly authenticated join can supersede an instance.
                    # Discovery is an address hint, never authoritative on its own.
                    continue
                if row and link is None and self.plugin < peer and peer not in self._dialing:
                    self._dialing.add(peer)
                    self._spawn(self._connect(peer, row))
            await asyncio.sleep(self.scan)

    async def _connect(self, peer, row):
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", row["port"]), FRAME_TIMEOUT)
            channel = await dial(reader, writer, self.trust[peer].key,
                                 greeting(self.plugin, self.instance, peer, row["instance"]))
            await self._join(peer, row["instance"], channel)
        except ERRORS:
            pass
        finally:
            if writer is not None:
                writer.close()
            self._dialing.discard(peer)

    async def _join(self, peer, instance, channel):
        await channel.send("ready", self._catalog(peer))
        kind, payload = await channel.receive(FRAME_TIMEOUT)
        shape(payload, "capabilities", "offers")
        if (kind != "ready" or payload["capabilities"] != CAPABILITIES
                or not isinstance(payload["offers"], list) or len(payload["offers"]) > MAX_SCOPES):
            raise PeerError("PEER_CAPABILITIES")
        link = Link(peer, instance, channel)
        for item in payload["offers"]:
            shape(item, "scope", "label", "operations", "sdk_type")
            scope = Scope.parse(item["scope"])
            if (scope in link.catalog or not isinstance(item["label"], str)
                    or not isinstance(item["sdk_type"], str) or not isinstance(item["operations"], list)
                    or any(not isinstance(op, str) or op not in OPERATIONS for op in item["operations"])
                    or len(set(item["operations"])) != len(item["operations"])
                    or scope.kind == "folder" and item["operations"]):
                raise PeerError("PEER_OFFER")
            link.catalog[scope] = item
        row = self.discovery.read(peer)
        previous = self.links.get(peer)
        if (not row or row["instance"] != instance or previous is not None
                or (peer, instance) in self._retired or self._stopping):
            raise PeerError("PEER_STALE")
        former = self.latest.get(peer)
        if former is not None and former != instance:
            if len(self._retired) >= MAX_REQUESTS:
                raise PeerError("INSTANCE_CAPACITY")
            self._retired.add((peer, former))
        self.links[peer] = link
        self.latest[peer] = instance
        self.local_health[peer] = "connected"
        self.loss.pop(peer, None)
        orderly = False
        try:
            self.changed()
            self._dirty.set()
            keepalive = self._spawn(self._heartbeat(link))
            try:
                while True:
                    kind, payload = await channel.receive(self.timeout)
                    if kind == "leave":
                        shape(payload)
                        orderly = True
                        break
                    await self._message(link, kind, payload)
            finally:
                keepalive.cancel()
        finally:
            link.closed = True
            channel.writer.close()
            if self.links.get(peer) is link:
                del self.links[peer]
                self.local_health[peer] = "left" if orderly else "disconnected"
                self.changed()
                self.subscriptions_changed()
                if not self._stopping and not orderly:
                    self._report_loss(link)
            for future in (*link.pending.values(), *link.pings.values()):
                if not future.done():
                    future.set_result(None)

    async def _heartbeat(self, link):
        while True:
            await asyncio.sleep(self.heartbeat)
            if await self._probe(link) is not True:
                link.channel.writer.close()
                return

    async def _probe(self, link):
        if link.closed or len(link.pings) >= MAX_PEERS + 1:
            return False
        token = uuid.uuid4().hex
        future = link.pings[token] = asyncio.get_running_loop().create_future()
        try:
            await link.send("ping", dict(token=token))
            return await asyncio.wait_for(future, min(self.timeout, self.heartbeat * 2))
        except ERRORS:
            return False
        finally:
            del link.pings[token]

    def _report_loss(self, link):
        witnesses = {p: w.instance for p, w in self.links.items()}
        token = uuid.uuid4().hex
        self.loss[link.plugin] = dict(instance=link.instance, token=token, witnesses=witnesses, votes={})
        for peer in witnesses:
            self._spawn(self._send_or_close(self.links[peer], "lost",
                                          dict(plugin=link.plugin, instance=link.instance, token=token)))

    def health(self, plugin):
        local = self.local_health.get(plugin, "unknown")
        if local in ("connected", "left"):
            return dict(local=local, circle="reachable" if local == "connected" else "left")
        loss = self.loss.get(plugin)
        if not loss:
            return dict(local=local, circle="unknown")
        votes = {peer: vote for peer, vote in loss["votes"].items()
                 if peer in self.links and self.links[peer].instance == loss["witnesses"][peer]
                 and asyncio.get_running_loop().time() - vote[1] < self.timeout}
        if any(v[0] == "reachable" for v in votes.values()):
            circle = "reachable"
        elif loss["witnesses"] and all(votes.get(p, ("unknown",))[0] == "unreachable" for p in loss["witnesses"]):
            circle = "unreachable_in_known_circle"
        else:
            circle = "unknown"
        return dict(local=local, circle=circle)

    async def _send_or_close(self, link, kind, payload):
        try:
            await link.send(kind, payload)
        except ERRORS:
            link.channel.writer.close()

    async def _witness(self, reporter, row):
        target = self.links.get(row["plugin"])
        local = self.health(row["plugin"])["local"]
        vote = "unknown"
        if target and target.instance == row["instance"]:
            vote = "reachable" if await self._probe(target) else "unreachable"
            if vote == "unreachable":
                target.channel.writer.close()
        elif self.latest.get(row["plugin"]) == row["instance"] and local in ("disconnected", "left"):
            vote = "unreachable"
        await self._send_or_close(reporter, "witness", dict(**row, vote=vote))

    async def _message(self, link, kind, row):
        if kind in ("ping", "pong"):
            shape(row, "token")
            if not identity(row["token"]):
                raise PeerError("PEER_TOKEN")
            if kind == "ping":
                await link.send("pong", row)
            else:
                pending = link.pings.get(row["token"])
                if pending and not pending.done():
                    pending.set_result(True)
        elif kind in ("lost", "witness"):
            extra = ("vote",) if kind == "witness" else ()
            shape(row, "plugin", "instance", "token", *extra)
            if not resource_id(row["plugin"]) or not all(identity(row[k]) for k in ("instance", "token")):
                raise PeerError("PEER_LOSS")
            if kind == "lost":
                loss = self.loss.get(row["plugin"])
                if (loss and loss["instance"] == row["instance"]
                        and loss["witnesses"].get(link.plugin) == link.instance):
                    loss["votes"][link.plugin] = "unreachable", asyncio.get_running_loop().time()
                key = link.plugin, row["plugin"]
                if key not in self._witnessing and row["plugin"] in self.trust:
                    self._witnessing.add(key)
                    async def witness():
                        try:
                            await self._witness(link, row)
                        finally:
                            self._witnessing.discard(key)
                    self._spawn(witness())
            else:
                loss = self.loss.get(row["plugin"])
                if row["vote"] not in ("unknown", "reachable", "unreachable"):
                    raise PeerError("PEER_VOTE")
                if (loss and loss["token"] == row["token"] and loss["instance"] == row["instance"]
                        and loss["witnesses"].get(link.plugin) == link.instance):
                    loss["votes"][link.plugin] = row["vote"], asyncio.get_running_loop().time()
        elif kind in ("subscribe", "unsubscribe"):
            shape(row, "scope", "token")
            scope = Scope.parse(row["scope"])
            if scope not in self.trust[link.plugin].grants or not identity(row["token"]):
                raise PeerError("SUBSCRIPTION_DENIED")
            if kind == "subscribe":
                link.inbound[scope] = (row["token"], 0, None)
            elif scope in link.inbound and link.inbound[scope][0] == row["token"]:
                del link.inbound[scope]
            self.subscriptions_changed()
            self._dirty.set()
        elif kind in ("snapshot", "delta"):
            shape(row, "scope", "token", "revision", "view")
            scope = Scope.parse(row["scope"])
            if not identity(row["token"]) or type(row["revision"]) is not int or not isinstance(row["view"], dict):
                raise PeerError("INVALID_VIEW")
            token = link.outbound.get(scope)
            if token != row["token"]:
                return
            previous = link.views.get(scope)
            if kind == "snapshot" and previous is None and row["revision"] == 1:
                link.views[scope] = (1, row["view"])
            elif kind == "delta" and previous and row["revision"] == previous[0] + 1:
                link.views[scope] = (row["revision"], previous[1] | row["view"])
            else:
                link.views.pop(scope, None)
                link.outbound.pop(scope, None)
                self._dirty.set()
            self.changed()
        elif kind == "invoke":
            await self._invoke_received(link, row)
        elif kind == "result":
            shape(row, "request", "status", "report")
            if not identity(row["request"]) or not isinstance(row["status"], str):
                raise PeerError("INVALID_RESULT")
            future = link.pending.get(row["request"])
            if future and not future.done():
                future.set_result(row)
        else:
            raise PeerError("PEER_MESSAGE")

    def set_wanted(self, references):
        refs = set(references)
        if (len(refs) > MAX_SCOPES or any(not resource_id(peer) or not isinstance(scope, Scope) for peer, scope in refs)):
            raise PeerError("REFERENCE_CAPACITY")
        if refs != self.wanted:
            self.wanted = refs
            self._dirty.set()

    def subscribed(self):
        return {scope for link in self.links.values() for scope in link.inbound}

    def publish(self, scope, view):
        if scope not in self.offers or not isinstance(view, dict):
            raise PeerError("INVALID_VIEW")
        encode(dict(scope=scope.wire(), token="0"*32, revision=2**53 - 1, view=view))
        if self.values.get(scope) != view:
            self.values[scope] = copy.deepcopy(view)
            self._dirty.set()

    async def _push(self):
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            # Slow channels are independent; healthy peers do not wait on their I/O.
            await asyncio.gather(*(self._flush(link) for link in tuple(self.links.values())))

    async def _flush(self, link):
        try:
            wanted = {s for p, s in self.wanted if p == link.plugin and s in link.catalog}
            for scope in link.outbound.keys() - wanted:
                token = link.outbound.pop(scope)
                link.views.pop(scope, None)
                await link.send("unsubscribe", dict(scope=scope.wire(), token=token))
                self.changed()
            for scope in wanted - link.outbound.keys():
                token = link.outbound[scope] = uuid.uuid4().hex
                await link.send("subscribe", dict(scope=scope.wire(), token=token))
            for scope, previous in tuple(link.inbound.items()):
                if link.inbound.get(scope) != previous:
                    continue
                token, revision, old = previous
                view = self.values.get(scope)
                if view is None or old == view:
                    continue
                delta = view if old is None else {k: view.get(k) for k in old.keys() | view.keys() if old.get(k) != view.get(k)}
                link.inbound[scope] = (token, revision + 1, view)
                await link.send("snapshot" if old is None else "delta",
                                dict(scope=scope.wire(), token=token, revision=revision + 1, view=delta))
        except ERRORS:
            link.channel.writer.close()

    def remote(self, peer, scope):
        link = self.links.get(peer)
        if link is None or scope not in link.views:
            return None
        return link.instance, copy.deepcopy(link.catalog[scope]), copy.deepcopy(link.views[scope][1])

    async def invoke(self, peer, instance, scope, operation, diff=None, *, request=None):
        request = uuid.uuid4().hex if request is None else request
        link = self.links.get(peer)
        if link is None or link.instance != instance:
            raise PeerError("PEER_DISCONNECTED")
        if (not identity(request) or operation not in link.catalog.get(scope, {}).get("operations", ())
                or len(link.pending) >= MAX_PENDING or request in link.pending):
            raise PeerError("INVOKE_DENIED_OR_BUSY")
        future = link.pending[request] = asyncio.get_running_loop().create_future()
        try:
            expires = time.time_ns() // 1_000_000 + int(min(self.timeout, 12) * 1000)
            await link.send("invoke", dict(scope=scope.wire(), request=request, operation=operation, diff=diff, expires=expires))
            result = await asyncio.wait_for(future, self.timeout)
            return result or dict(request=request, status="UNKNOWN_OUTCOME", report=None)
        except (TimeoutError, OSError):
            return dict(request=request, status="UNKNOWN_OUTCOME", report=None)
        finally:
            del link.pending[request]

    async def _invoke_received(self, link, row):
        shape(row, "scope", "request", "operation", "diff", "expires")
        scope = Scope.parse(row["scope"])
        request, operation, diff = row["request"], row["operation"], row["diff"]
        if not identity(request) or not isinstance(operation, str):
            raise PeerError("INVOKE_FORMAT")
        result = dict(request=request, status="DENIED", report=None)
        now = time.time_ns() // 1_000_000
        if type(row["expires"]) is not int or not now <= row["expires"] <= now + 12_000:
            await link.send("result", dict(result, status="REQUEST_EXPIRED"))
            return
        ops = self.trust[link.plugin].grants.get(scope, ())
        if (operation not in ops or scope not in link.inbound or scope not in self.values
                or self.values[scope].get("available") is not True
                or (operation == "adjustment" and not (type(diff) is int and -(2**31) <= diff < 2**31))
                or (operation == "command" and diff is not None)):
            await link.send("result", result)
            return
        # A reconnect of the same caller keeps the ledger. New caller instances
        # must use new requests; reusing a request is rejected even after rejoin.
        key = link.plugin, request
        fingerprint = link.instance, scope, operation, diff
        previous = self.requests.get(key)
        if previous:
            if previous[0] == fingerprint and previous[1] is not None:
                result = previous[1]
            else:
                result["status"] = "IN_PROGRESS" if previous[0] == fingerprint else "REQUEST_REUSE"
        elif len(self.requests) >= MAX_REQUESTS or len(self.executions) >= MAX_PENDING:
            result["status"] = "BUSY"
        else:
            self.requests[key] = (fingerprint, None)
            self.executions[key] = self._spawn(self._execute(link, key, fingerprint))
            return
        await link.send("result", result)

    async def _execute(self, link, key, fingerprint):
        _, scope, operation, diff = fingerprint
        request = key[1]
        try:
            status, report = await self.execute(link.plugin, link.instance, request, scope, operation, diff)
            row = dict(request=request, status=status, report=report)
            encode(row)
        except Exception:
            row = dict(request=request, status="UNKNOWN_OUTCOME", report=None)
        finally:
            self.executions.pop(key, None)
        self.requests[key] = (fingerprint, row)
        await self._send_or_close(link, "result", row)
