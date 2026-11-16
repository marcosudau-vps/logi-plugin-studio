"""Independent peer process controlled via stdin only by the test driver."""
import asyncio
import json
import sys
import time

from extensions.shared_folders.peer_runtime import PeerRuntime, Scope, Trust
from extensions.shared_folders.peer_wire import PeerError

ACTION = Scope("action", "action.command", "first")
READ = Scope("action", "action.command", "read-only")


async def main():
    plugin, directory, raw = sys.argv[1:]
    config = json.loads(raw)
    trust = {p: Trust(bytes.fromhex(key), {ACTION: frozenset({"command"}), READ: frozenset()})
             for p, key in config.items()}
    offers = {s: dict(label=plugin + ".command", operations=["command"], sdk_type="PluginDynamicCommand")
              for s in (ACTION, READ)}
    count = 0
    blocked = set()
    silent = set()
    traffic = {}

    async def invoke(caller, instance, request, scope, operation, diff):
        nonlocal count
        count += 1
        publish()
        return "COMPLETED", dict(owner=plugin, count=count, caller=caller, instance=instance, parameter=scope.parameter)

    def publish():
        for scope in offers:
            runtime.publish(scope, dict(available=True, label=plugin, state=count, image_hash="0"*64))

    runtime = PeerRuntime(plugin, directory, trust, offers, invoke=invoke, heartbeat=0.25, timeout=1.5, scan=0.1)
    read = runtime.discovery.read
    runtime.discovery.read = lambda peer: None if peer in blocked else read(peer)
    await runtime.start()
    publish()
    try:
        while raw := await asyncio.to_thread(sys.stdin.readline):
            row = json.loads(raw)
            cmd = row["cmd"]
            result = {}
            try:
                if cmd == "stop":
                    break
                if cmd == "info":
                    result = dict(instance=runtime.instance, count=count, traffic=traffic.copy(), links={
                        p: dict(instance=link.instance, catalog=[s.wire() for s in link.catalog],
                                subscriptions=len(link.inbound), outbound=len(link.outbound))
                        for p, link in runtime.links.items()}, health={p: runtime.health(p) for p in trust})
                elif cmd == "watch":
                    runtime.set_wanted({(p, READ if read_only else ACTION) for p, read_only in row["refs"]})
                elif cmd == "publish":
                    count += 1
                    publish()
                elif cmd == "remote":
                    result = runtime.remote(row["peer"], ACTION)
                elif cmd == "invoke":
                    scope = READ if row.get("read_only") else ACTION
                    peer = row["peer"]
                    result = await runtime.invoke(peer, row["instance"], scope, "command", request=row["request"])
                elif cmd == "instrument":
                    peer = row["peer"]
                    link = runtime.links[peer]
                    original = link.channel.send
                    async def send(kind, payload, peer=peer, original=original):
                        traffic[kind] = traffic.get(kind, 0) + 1
                        if not (peer in silent and kind == "pong"):
                            await original(kind, payload)
                    link.channel.send = send
                elif cmd == "mute":
                    peer = row["peer"]
                    blocked.add(peer)
                    silent.add(peer)
                elif cmd == "restore":
                    blocked.discard(row["peer"])
                    silent.discard(row["peer"])
                elif cmd == "inject_gap":
                    link = runtime.links[row["peer"]]
                    token, revision, view = link.inbound[ACTION]
                    await link.send("delta", dict(scope=ACTION.wire(), token=token, revision=revision + 2,
                                                  view=dict(state=-1)))
                elif cmd == "raw_invoke":
                    await runtime.links[row["peer"]].send("invoke", dict(scope=(ACTION if row.get("expired") else READ).wire(), request=row["request"],
                                                                        operation="command", diff=None,
                                                                        expires=time.time_ns() // 1_000_000 + (-1000 if row.get("expired") else 1000)))
                else:
                    raise AssertionError(cmd)
            except (PeerError, KeyError) as exc:
                result = dict(error=str(exc))
            print("JSON:" + json.dumps(result), flush=True)
    finally:
        await runtime.close()


asyncio.run(main())
