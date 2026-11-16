from __future__ import annotations

import copy
import json
import logging
import secrets
import select
import socket
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.io import load_raw
from runtime.host import PluginHost
from runtime.state_store import ScopeAddress
from runtime.wire import ConnectionSettings, HostError, LocalClient, parse_json, project_digest


def sample() -> dict:
    return load_raw(ROOT / "examples" / "project_v0_1_draft.json")


def settings(raw: dict) -> ConnectionSettings:
    return ConnectionSettings(raw["project"]["id"], project_digest(raw), 0, secrets.token_hex(32))


def result_for(client: LocalClient, cid: str, after: int = 0, timeout: float = 3) -> dict:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        reply = client.poll(after)
        for entry in reply["entries"]:
            if entry["kind"] == "command_result" and entry["data"]["command_id"] == cid:
                return entry["data"]
        after = reply["seq"]
        time.sleep(0.01)
    raise AssertionError("No command result arrived")


class HostTests(unittest.TestCase):
    def make_host(self, handler=None, raw=None, **options):
        raw = raw or sample()
        host = PluginHost(raw, settings(raw), **options)
        host.register_handler("handler.primary", "invoke", handler or (lambda payload, ctx: {"ok": True}))
        self.addCleanup(host.close)
        host.start()
        client = LocalClient(host.settings)
        client.handshake()
        return host, client

    def test_real_http_command_explicit_result_state_and_reconnect(self):
        def callback(payload, ctx):
            ctx.set_state("state.primary", "variant_1")
            return {"ok": True}
        host, client = self.make_host(callback)
        baseline = client.snapshot()
        entry = baseline["snapshot"]["states"]["state.primary@runtime"]
        self.assertFalse(entry["has_value"])
        self.assertEqual(entry["quality"], "unknown")
        cid = client.command("action.primary", placement_id="placement.main")["command_id"]
        result = result_for(client, cid)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(host.read_state("state.primary")["value"], "variant_1")
        old_session = client.session_id
        runtime = client.runtime_instance_id
        client.handshake()
        self.assertNotEqual(client.session_id, old_session)
        self.assertEqual(client.runtime_instance_id, runtime)
        self.assertEqual(client.snapshot()["snapshot"]["states"]["state.primary@runtime"]["revision"], 1)

    def test_result_does_not_set_state(self):
        host, client = self.make_host()
        result_for(client, client.command("action.primary")["command_id"])
        self.assertFalse(host.read_state("state.primary")["has_value"])

    def test_duplicate_command_does_not_execute_twice(self):
        calls = []
        host, client = self.make_host(lambda payload, ctx: calls.append(ctx.command_id))
        cid = uuid.uuid4().hex
        client.command("action.primary", command_id=cid)
        result_for(client, cid)
        self.assertTrue(client.command("action.primary", command_id=cid)["duplicate"])
        self.assertEqual(calls, [cid])
        with self.assertRaisesRegex(HostError, "COMMAND_ID_REUSE"):
            client.command("action.primary", command_id=cid, placement_id="placement.main")

    def test_invalid_payload_endpoint_placement_and_session(self):
        host, client = self.make_host()
        for kwargs in ({"payload": {"bad": True}}, {"placement_id": "missing"}):
            with self.assertRaises(HostError):
                client.command("action.primary", **kwargs)
        with self.assertRaisesRegex(HostError, "COMMAND_ENDPOINT"):
            client.command("does.not.exist")
        client.session_id = "bogus"
        with self.assertRaisesRegex(HostError, "SESSION_UNKNOWN"):
            client.snapshot()

    def test_two_plugins_and_wrong_key_are_isolated(self):
        host1, client1 = self.make_host()
        raw = sample()
        raw["project"]["id"] = "different.plugin"
        host2, client2 = self.make_host(raw=raw)
        host1.set_state("state.primary", "variant_1")
        self.assertFalse(host2.read_state("state.primary")["has_value"])
        wrong = copy.copy(host1.settings)
        object.__setattr__(wrong, "secret", secrets.token_hex(32))
        with self.assertRaisesRegex(HostError, "HOST_UNTRUSTED"):
            LocalClient(wrong).handshake()
        self.assertNotEqual(client1.runtime_instance_id, client2.runtime_instance_id)

    def test_journal_gap_requests_snapshot(self):
        host, client = self.make_host(journal_capacity=2)
        for value in ("variant_0", "variant_1", "variant_0"):
            host.set_state("state.primary", value)
        self.assertTrue(client.poll(0)["resync"])
        self.assertEqual(client.snapshot()["seq"], 3)

    def test_timeout_has_unknown_outcome_and_rejects_late_state_write(self):
        release = threading.Event()
        late = []
        def callback(payload, ctx):
            release.wait(2)
            try:
                ctx.set_state("state.primary", "variant_1")
            except HostError as exc:
                late.append(exc.code)
        host, client = self.make_host(callback, command_timeout=0.1)
        self.addCleanup(release.set)
        cid = client.command("action.primary")["command_id"]
        self.assertEqual(result_for(client, cid)["status"], "UNKNOWN_OUTCOME")
        release.set()
        until = time.monotonic() + 2
        while not late and time.monotonic() < until:
            time.sleep(0.01)
        self.assertEqual(late, ["COMMAND_EXPIRED"])
        self.assertFalse(host.read_state("state.primary")["has_value"])

    def test_handler_failure_and_no_handler(self):
        def broken(payload, ctx):
            raise ValueError("intentional")
        host, client = self.make_host(broken)
        self.assertEqual(result_for(client, client.command("action.primary")["command_id"])["status"], "FAILED")
        raw = sample()
        other = PluginHost(raw, settings(raw))
        self.addCleanup(other.close)
        other.start()
        missing = LocalClient(other.settings)
        missing.handshake()
        with self.assertRaisesRegex(HostError, "COMMAND_NO_HANDLER"):
            missing.command("action.primary")

    def test_scope_writer_and_payload_rejections_preserve_snapshot(self):
        host, _ = self.make_host()
        before = host.snapshot()
        for scope, value in ((ScopeAddress.component("action.primary"), "variant_1"),
                             (ScopeAddress.runtime(), "unlisted")):
            with self.assertRaises(HostError):
                host.set_state("state.primary", value, scope)
        self.assertEqual(before, host.snapshot())

    def test_nonce_replay_and_clock_expiry(self):
        from runtime.wire import PROTOCOL, json_bytes, signature
        host, _ = self.make_host()
        fields = {k: v for k, v in host.settings.as_dict().items() if k not in ("port", "secret")}
        fields["sent_at"] = int(time.time())
        body = json_bytes(fields)
        nonce = uuid.uuid4().hex
        tag = signature(host.settings.secret, "/v1/handshake\n" + nonce + "\n", body)
        host._handle("/v1/handshake", nonce, tag, body)
        with self.assertRaisesRegex(HostError, "FRAME_REPLAY"):
            host._handle("/v1/handshake", nonce, tag, body)
        fields["sent_at"] = 1
        body = json_bytes(fields)
        tag = signature(host.settings.secret, "/v1/handshake\n" + nonce + "\n", body)
        with self.assertRaisesRegex(HostError, "FRAME_EXPIRED"):
            host._handle("/v1/handshake", nonce, tag, body)

    def test_bad_json_and_finite_depth_limits(self):
        for data in (b'[]', b'{"a":1,"a":2}', b'{"x":NaN}', b'\xff', b'{'):
            with self.assertRaises(HostError):
                parse_json(data)
        with self.assertRaisesRegex(HostError, "FRAME_DEPTH"):
            parse_json(b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}')

    def test_port_collision_is_explicit(self):
        host, _ = self.make_host()
        other = PluginHost(sample(), host.settings)
        self.addCleanup(other.close)
        with self.assertRaisesRegex(HostError, "HOST_PORT_BUSY"):
            other.start()

    def test_dedup_capacity_refuses_without_forgetting_old_commands(self):
        host, client = self.make_host(command_capacity=1)
        cid = client.command("action.primary")["command_id"]
        result_for(client, cid)
        with self.assertRaisesRegex(HostError, "COMMAND_CAPACITY"):
            client.command("action.primary")
        self.assertTrue(client.command("action.primary", command_id=cid)["duplicate"])

    def test_dedup_capacity_forgets_only_long_finished_commands(self):
        # AP-POLISH-001: self-hosted plugins run indefinitely; finished commands past
        # the retention are dropped instead of refusing every further key press.
        import runtime.host as host_module
        host, client = self.make_host(command_capacity=2)
        first = client.command("action.primary")["command_id"]
        result_for(client, first)
        second = client.command("action.primary")["command_id"]
        result_for(client, second)
        with self.assertRaisesRegex(HostError, "COMMAND_CAPACITY"):
            client.command("action.primary")  # both finished, but within the retention
        with host._lock:
            host._commands[first]["finished"] -= host_module.COMMAND_RETENTION_SECONDS + 1
        third = client.command("action.primary")["command_id"]
        self.assertEqual(result_for(client, third)["status"], "COMPLETED")
        self.assertNotIn(first, host._commands)
        self.assertTrue(client.command("action.primary", command_id=second)["duplicate"])

    def test_component_authority_is_not_claimable_by_public_host_writer(self):
        raw = sample()
        raw["states"][0]["authority"] = {"role": "component", "component": "handler.primary"}
        def callback(payload, ctx):
            ctx.set_state("state.primary", "variant_1")
        host, client = self.make_host(callback, raw=raw)
        with self.assertRaisesRegex(HostError, "STATE_AUTH_VIOLATION"):
            host.set_state("state.primary", "variant_0")
        result_for(client, client.command("action.primary")["command_id"])
        self.assertEqual(host.read_state("state.primary")["value"], "variant_1")

    def test_placement_scope_isolated_for_reused_action(self):
        raw = sample()
        raw["states"][0]["scope"] = "placement"
        duplicate = copy.deepcopy(raw["views"][0]["placements"][0])
        duplicate["id"] = "placement.other"
        duplicate["position"] = 1
        raw["views"][0]["placements"].append(duplicate)
        def callback(payload, ctx):
            ctx.set_state("state.primary", "variant_1", ScopeAddress.placement(ctx.placement_id))
        host, client = self.make_host(callback, raw=raw)
        result_for(client, client.command("action.primary", placement_id="placement.main")["command_id"])
        self.assertTrue(host.read_state("state.primary", ScopeAddress.placement("placement.main"))["has_value"])
        self.assertFalse(host.read_state("state.primary", ScopeAddress.placement("placement.other"))["has_value"])

    def test_blocking_observer_does_not_block_watchdog_and_queue_timeout(self):
        raw = sample()
        release = threading.Event()
        observed = threading.Event()
        host = PluginHost(raw, settings(raw), command_timeout=0.1)
        host.register_handler("handler.primary", "invoke", lambda payload, ctx: release.wait(2))
        def observer(entry):
            observed.set()
            release.wait(2)
        host.observe(observer)
        self.addCleanup(host.close)
        self.addCleanup(release.set)
        host.start()
        host.set_state("state.primary", "variant_0")
        self.assertTrue(observed.wait(1))
        client = LocalClient(host.settings)
        client.handshake()
        first = client.command("action.primary")["command_id"]
        time.sleep(0.03)
        second = client.command("action.primary")["command_id"]
        self.assertEqual(result_for(client, first)["status"], "UNKNOWN_OUTCOME")
        self.assertEqual(result_for(client, second)["status"], "REJECTED_TIMEOUT")

    def test_session_capacity_and_bad_http_framing_are_explicit(self):
        import http.client
        host, _ = self.make_host()
        for _ in range(15):
            LocalClient(host.settings).handshake()
        with self.assertRaisesRegex(HostError, "HOST_BUSY"):
            LocalClient(host.settings).handshake()
        cases = (
            ({"Content-Length": "2", "Content-Type": "text/plain"}, "FRAME_CONTENT_TYPE"),
            ({"Content-Length": "65537", "Content-Type": "application/json"}, "FRAME_SIZE"),
            ({"Transfer-Encoding": "chunked", "Content-Type": "application/json"}, "FRAME_LENGTH"),
            ({"Content-Length": "2", "Content-Type": "application/json"}, "HOST_UNTRUSTED"),
        )
        for headers, expected in cases:
            conn = http.client.HTTPConnection("127.0.0.1", host.settings.port, timeout=3)
            self.addCleanup(conn.close)
            conn.request("POST", "/v1/handshake", b"{}", {**headers, "X-Studio-Nonce": uuid.uuid4().hex})
            reply = conn.getresponse()
            self.assertEqual(reply.status, 400)
            self.assertEqual(json.loads(reply.read())["code"], expected)
            conn.close()

    def _rejected_socket(self, host, headers: dict) -> socket.socket:
        """Send only the header block of a frame the host rejects without reading its body."""
        client = socket.create_connection(("127.0.0.1", host.settings.port), timeout=3)
        self.addCleanup(client.close)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        lines = ["POST /v1/handshake HTTP/1.1", "Host: 127.0.0.1", f"X-Studio-Nonce: {uuid.uuid4().hex}"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        client.sendall("\r\n".join(lines).encode() + b"\r\n\r\n")
        return client

    def test_rejection_reply_survives_a_body_arriving_after_the_decision(self):
        # http.client sends header and body separately. The host may reject in between;
        # the late body must not reset the connection and destroy the explicit reply.
        host, _ = self.make_host()
        cases = (
            ({"Content-Length": "2", "Content-Type": "text/plain"}, "FRAME_CONTENT_TYPE"),
            ({"Content-Length": "65537", "Content-Type": "application/json"}, "FRAME_SIZE"),
            ({"Transfer-Encoding": "chunked", "Content-Type": "application/json"}, "FRAME_LENGTH"),
        )
        for headers, expected in cases:
            with self.subTest(expected=expected):
                client = self._rejected_socket(host, headers)
                self.assertTrue(select.select([client], [], [], 3)[0], "No rejection reply arrived")
                time.sleep(0.05)
                client.sendall(b"{}")
                time.sleep(0.05)
                data = b""
                while chunk := client.recv(4096):
                    data += chunk
                head, _, body = data.partition(b"\r\n\r\n")
                self.assertIn(b" 400 ", head.split(b"\r\n")[0])
                self.assertEqual(json.loads(body)["code"], expected)

    def test_discarding_after_rejection_is_bounded_in_time_and_bytes(self):
        from unittest import mock
        host, _ = self.make_host()
        slots = host._server._slots
        rejected = {"Content-Length": "2", "Content-Type": "text/plain"}
        full = slots._value

        def released(limit: float) -> bool:
            until = time.monotonic() + limit
            while time.monotonic() < until:
                if slots._value == full:
                    return True
                time.sleep(0.01)
            return False

        with mock.patch("runtime.host.DRAIN_SECONDS", 0.1):
            silent = self._rejected_socket(host, rejected)
            self.assertTrue(select.select([silent], [], [], 3)[0])
            self.assertTrue(released(1.5), "A silent client must not keep a connection slot")

        with mock.patch("runtime.host.DRAIN_BYTES", 8192), mock.patch("runtime.host.DRAIN_SECONDS", 30):
            flood = self._rejected_socket(host, {"Content-Length": "9999999", "Content-Type": "application/json"})
            self.assertTrue(select.select([flood], [], [], 3)[0])
            flood.settimeout(0.2)
            with self.assertRaises(OSError):
                for _ in range(2000):
                    flood.sendall(b"x" * 8192)
            self.assertTrue(released(1.5), "A flooding client must not keep a connection slot")

    def test_explicit_event_routes_are_separate_from_result_and_state(self):
        import tempfile
        from runtime.host import MANIFESTS
        temporary = tempfile.TemporaryDirectory(prefix="studio-event-")
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        for path in MANIFESTS.glob("*.json"):
            (directory / path.name).write_bytes(path.read_bytes())
        payload = {"type": "object", "properties": {}, "additionalProperties": False}
        manifest = {
            "type_id": "test.host_relay", "version": "1.0.0", "test_only": True,
            "config_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "ports": [{"id": "invoke", "direction": "in", "kind": "command", "payload_schema": payload},
                      {"id": "done", "direction": "out", "kind": "event", "payload_schema": payload},
                      {"id": "seen", "direction": "in", "kind": "event", "payload_schema": payload}]}
        (directory / "relay.json").write_text(json.dumps(manifest))
        raw = sample()
        handler = next(c for c in raw["components"] if c["id"] == "handler.primary")
        handler.update({"type": "test.host_relay", "config": {}})
        raw["components"].append({"id": "handler.event", "type": "test.host_relay", "version": "1.0.0", "config": {}})
        raw["dependencies"].append({"type": "test.host_relay", "version": "1.0.0"})
        raw["bindings"].append({"id": "binding.done", "kind": "event",
                                "source": {"owner_kind": "component", "owner_id": "handler.primary", "port": "done"},
                                "target": {"owner_kind": "component", "owner_id": "handler.event", "port": "seen"}})
        calls = []
        host = PluginHost(raw, settings(raw), manifest_dir=directory)
        host.register_handler("handler.primary", "invoke", lambda payload, ctx: ctx.emit("done", {}))
        host.register_handler("handler.event", "seen", lambda payload, ctx: calls.append((ctx.target_component, ctx.target_port)))
        self.addCleanup(host.close)
        host.start()
        client = LocalClient(host.settings)
        client.handshake()
        result = result_for(client, client.command("action.primary")["command_id"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(calls, [("handler.event", "seen")])
        self.assertFalse(host.read_state("state.primary")["has_value"])
        self.assertTrue(any(entry["kind"] == "event" for entry in client.poll(0)["entries"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    unittest.main()
