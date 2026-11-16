"""Real A/B/C transport, partitions, scope permissions and authenticated framing."""
import asyncio
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

from test_ap_shared_final_001_plugin import FIXTURES, ROOT, wait_until
from extensions.shared_folders.peer_wire import Discovery, FRAME_LIMIT, PeerError, accept, dial, encode, greeting


class PeerProcess:
    def __init__(self, name, directory, keys):
        self.process = subprocess.Popen([sys.executable, "-u", str(FIXTURES / "peer_process.py"), name,
                                         str(directory), json.dumps(keys)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.queue = queue.Queue()
        def collect():
            for line in self.process.stdout:
                self.queue.put(line)
            self.queue.put(None)
        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()

    def rpc(self, cmd, **fields):
        self.process.stdin.write(json.dumps(dict(cmd=cmd, **fields)) + "\n")
        self.process.stdin.flush()
        row = self.queue.get(timeout=6)
        if row is None:
            raise AssertionError(f"Peer process ended at {cmd}")
        return json.loads(row.removeprefix("JSON:"))

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('{"cmd":"stop"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class TransportProcessTests(unittest.TestCase):
    def test_abc_scoped_push_loss_witness_and_rejoin(self):
        a, b, c = "peer.a", "peer.b", "peer.c"
        keys = {(a,b): "12"*32, (a,c): "13"*32, (b,c): "23"*32}
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as processes:
            directory = Path(tmp) / "discovery"
            def start(peer):
                return processes.enter_context(PeerProcess(peer, directory, {
                    p: keys[tuple(sorted((p, peer)))] for p in (a,b,c) if p != peer}))
            pc, pb, pa = start(c), start(b), start(a)
            for peer in (pa,pb,pc):
                wait_until(lambda: len(peer.rpc("info")["links"]) == 2)
            duplicate = Discovery(directory, a, "0"*32)
            with self.assertRaises(OSError):
                duplicate.start(12345)
            self.assertEqual(duplicate.read(a)["instance"], pa.rpc("info")["instance"])
            info = pc.rpc("info")
            self.assertEqual(len(info["links"][a]["catalog"]), 2)
            self.assertEqual(info["links"][a]["outbound"], 0)
            pa.rpc("instrument", peer=c)
            pc.rpc("instrument", peer=a)
            pc.rpc("watch", refs=[[a, False], [a, False], [a, True], [b, False]])
            def remote(owner):
                return pc.rpc("remote", peer=owner)
            wait_until(lambda: remote(a) and remote(b))
            self.assertEqual(remote(a)[2]["state"], 0)
            self.assertEqual(pa.rpc("info")["links"][c]["subscriptions"], 2)
            aid, bid = remote(a)[0], remote(b)[0]
            request = uuid.uuid4().hex
            first = pc.rpc("invoke", peer=a, instance=aid, request=request)
            second = pc.rpc("invoke", peer=a, instance=aid, request=request)
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "COMPLETED")
            self.assertEqual(first["report"]["parameter"], "first")
            self.assertEqual(first["report"]["instance"], info["instance"])
            self.assertEqual(pa.rpc("info")["count"], 1)
            wait_until(lambda: remote(a)[2]["state"] == 1)
            self.assertIn("error", pc.rpc("invoke", peer=a, instance=aid, request=uuid.uuid4().hex, read_only=True))
            pc.rpc("raw_invoke", peer=a, request=uuid.uuid4().hex)
            pc.rpc("raw_invoke", peer=a, request=uuid.uuid4().hex, expired=True)
            wait_until(lambda: pa.rpc("info")["traffic"].get("result", 0) == 4)
            self.assertEqual(pa.rpc("info")["count"], 1)
            before = pc.rpc("info")["traffic"]["subscribe"]
            pa.rpc("inject_gap", peer=c)
            wait_until(lambda: pc.rpc("info")["traffic"]["subscribe"] == before + 1)
            wait_until(lambda: remote(a) and remote(a)[2]["state"] == 1)
            self.assertEqual(remote(a)[2]["image_hash"], "0"*64)
            # Drop only B's response to A; C's B link stays healthy. Prevent
            # immediate reconnection using the fixture's address lookup filter.
            pb.rpc("instrument", peer=a)
            pb.rpc("mute", peer=a)
            pa.rpc("mute", peer=b)
            def health(circle):
                return pa.rpc("info")["health"][b] == dict(local="disconnected", circle=circle)
            try:
                wait_until(lambda: health("reachable"), timeout=4)
            except AssertionError:
                self.fail(repr([p.rpc("info") for p in (pa,pb,pc)]))
            self.assertEqual(remote(b)[0], bid)
            pb.process.kill()
            pb.process.wait(timeout=5)
            wait_until(lambda: health("unreachable_in_known_circle"))
            wait_until(lambda: remote(b) is None)
            self.assertEqual(pc.rpc("invoke", peer=a, instance=aid, request=uuid.uuid4().hex)["status"], "COMPLETED")
            pa.rpc("restore", peer=b)
            pb2 = start(b)
            wait_until(lambda: remote(b) and remote(b)[0] != bid)
            self.assertIn("error", pc.rpc("invoke", peer=b, instance=bid, request=uuid.uuid4().hex))
            self.assertEqual(remote(b)[2]["state"], 0)
            self.assertEqual(pb2.rpc("info")["links"][c]["subscriptions"], 1)
            pb2.close()
            wait_until(lambda: pc.rpc("info")["health"][b]["local"] == "left")


class WireSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_key_replay_and_oversized_frame(self):
        key = bytes(range(32))
        notices = asyncio.Queue()
        handlers = set()
        async def server(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            try:
                _, channel = await accept(reader, writer, lambda _: key)
                while True:
                    await notices.put(await channel.receive(2))
            except (PeerError, EOFError, OSError) as exc:
                await notices.put(type(exc).__name__ + ":" + str(exc))
            finally:
                writer.close()
                handlers.discard(task)
        server_socket = await asyncio.start_server(server, "127.0.0.1", 0)
        port = server_socket.sockets[0].getsockname()[1]

        async def client(k):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                return await dial(reader, writer, k, greeting("peer.a", "1"*32, "peer.b", "2"*32))
            except BaseException:
                writer.close()
                raise

        async with server_socket:
            with self.assertRaisesRegex(PeerError, "PEER_AUTH"):
                await client(bytes(32))
            await asyncio.wait_for(notices.get(), 2)
            channel = await client(key)
            message = encode(dict(seq=1, kind="ping", payload={"token": "0"*32}))
            packet = hmac.digest(channel.key, b"dial>" + message, hashlib.sha256) + message
            old_packet = struct.pack("!I", len(packet)) + packet
            channel.writer.write(old_packet + old_packet)
            await channel.writer.drain()
            self.assertEqual((await asyncio.wait_for(notices.get(), 2))[0], "ping")
            self.assertEqual(await asyncio.wait_for(notices.get(), 2), "PeerError:FRAME_SEQUENCE")
            channel.writer.close()
            fresh = await client(key)
            fresh.writer.write(old_packet)
            await fresh.writer.drain()
            self.assertEqual(await asyncio.wait_for(notices.get(), 2), "PeerError:FRAME_AUTH")
            fresh.writer.close()
            large = await client(key)
            large.writer.write(struct.pack("!I", FRAME_LIMIT + 1))
            await large.writer.drain()
            self.assertEqual(await asyncio.wait_for(notices.get(), 2), "PeerError:FRAME_SIZE")
            large.writer.close()
        await asyncio.gather(*handlers)
