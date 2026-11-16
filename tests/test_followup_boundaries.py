from __future__ import annotations

import copy
import secrets
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runtime.host import PluginHost
from runtime.wire import ConnectionSettings, HostError, LocalClient, MAX_REQUEST, MAX_RESPONSE, json_bytes, parse_json, project_digest
from test_product_host import sample, settings


class FollowupBoundaryTests(unittest.TestCase):
    def test_connection_wrong_types_ids_ports_are_explicit_errors(self):
        good = dict(plugin_id="plugin.test", project_hash="a" * 64, port=12345, secret=secrets.token_hex(32),
                    installation_id="b" * 32)
        for field, values in (("plugin_id", (None, 7, "../x", "UPPER")),
                              ("project_hash", (None, 7, [], "x")),
                              ("port", (True, 1, -1, 65536, "12345")),
                              ("secret", (None, 7, [], "x")),
                              ("installation_id", (None, 7, [], "x"))):
            for value in values:
                with self.subTest(field=field, type=type(value).__name__), self.assertRaises(HostError):
                    ConnectionSettings(**{**good, field: value})

    def test_malformed_signed_handshake_never_activates_client(self):
        client = LocalClient(settings(sample()))
        for response in ({}, {"session_id": None, "runtime_instance_id": []},
                         {"session_id": "a" * 32, "runtime_instance_id": "bad"},
                         {"session_id": "b" * 32, "runtime_instance_id": "c" * 32, "seq": True}):
            message = {"protocol": "studio-local-1", "plugin_id": client.settings.plugin_id, **response}
            with self.subTest(response_keys=list(response)), patch.object(client, "request", return_value=message):
                with self.assertRaises(HostError):
                    client.handshake()
                self.assertEqual((client.session_id, client.runtime_instance_id), ("", ""))

    def test_frame_limits_duplicate_keys_root_and_depth(self):
        for data in (b'{"x":1,"x":2}', b'[]', b'{"x":NaN}', b'{"x":' + b'[' * 34 + b'0' + b']' * 34 + b'}',
                     b'{"x":"' + b'a' * MAX_REQUEST + b'"}'):
            with self.assertRaises(HostError):
                parse_json(data)
        with self.assertRaisesRegex(HostError, "FRAME_SIZE"):
            json_bytes({"x": "a" * MAX_RESPONSE})
        self.assertEqual(len(json_bytes({"x": "a" * 5}, limit=13)), 13)

    def test_snapshot_budget_rejects_write_before_revision_mutation(self):
        raw = sample()
        raw["states"][0]["value_schema"] = {"type": "string"}
        raw["states"][0].pop("fallback", None)
        raw["bindings"] = [binding for binding in raw["bindings"] if binding["kind"] != "state"]
        host = PluginHost(raw, settings(raw))
        self.addCleanup(host.close)
        host.set_state("state.primary", "before")
        initial = host.read_state("state.primary")
        with self.assertRaises(HostError):
            host.set_state("state.primary", "a" * (512 * 1024))
        self.assertEqual(host.read_state("state.primary"), initial)

    def test_cross_plugin_identity_same_key_port_is_refused(self):
        raw = sample()
        host = PluginHost(raw, settings(raw))
        self.addCleanup(host.close)
        host.start()
        wrong = ConnectionSettings("plugin.someoneelse", project_digest(raw), host.settings.port,
                                   host.settings.secret, host.settings.installation_id)
        with self.assertRaisesRegex(HostError, "HOST_UNTRUSTED"):
            LocalClient(wrong).handshake()
