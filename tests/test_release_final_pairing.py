"""AP-RELEASE-FINAL-001 B: pairing and permission administration (policy files only)."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extensions.shared_folders.embedded_host import policy
from extensions.shared_folders.pairing import PairingError, PairingStore, project_offers
from extensions.shared_folders.peer_runtime import Scope
from extensions.shared_folders.runtime_projection import initial_layout

RAW = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
COMMAND = Scope("action", "action.command", "first")
ADJUST = Scope("action", "action.adjustment")


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "shared"
        self.store = PairingStore(self.home)
        self.offers = project_offers(RAW, initial_layout(RAW)[0])

    def test_pairing_creates_matching_keys_and_grants_nothing(self):
        self.store.pair("shared.a", "shared.b")
        self.assertTrue(self.store.is_paired("shared.a", "shared.b"))
        trust_a = policy(self.home, "shared.a")
        trust_b = policy(self.home, "shared.b")
        self.assertEqual(trust_a["shared.b"].key, trust_b["shared.a"].key)
        self.assertEqual(len(trust_a["shared.b"].key), 32)
        self.assertEqual(trust_a["shared.b"].grants, {})
        self.assertEqual(self.store.grants("shared.a"), [])
        with self.assertRaisesRegex(PairingError, "existiert bereits"):
            self.store.pair("shared.b", "shared.a")
        with self.assertRaises(PairingError):
            self.store.pair("shared.a", "shared.a")
        self.store.pair("shared.c", "shared.a")
        self.assertNotEqual(policy(self.home, "shared.a")["shared.c"].key, trust_a["shared.b"].key)

    def test_grant_requires_pairing_offer_and_allowed_operations(self):
        with self.assertRaisesRegex(PairingError, "paaren"):
            self.store.grant("shared.a", "shared.b", COMMAND, ["command"], offers=self.offers)
        self.store.pair("shared.a", "shared.b")
        with self.assertRaisesRegex(PairingError, "nicht an"):
            self.store.grant("shared.a", "shared.b", Scope("action", "action.unknown"), ["command"], offers=self.offers)
        with self.assertRaisesRegex(PairingError, "nicht erlaubt"):
            self.store.grant("shared.a", "shared.b", COMMAND, ["adjustment"], offers=self.offers)
        with self.assertRaisesRegex(PairingError, "lesend"):
            self.store.grant("shared.a", "shared.b", Scope("folder", "folder.main"), ["command"], offers=self.offers)
        self.store.grant("shared.a", "shared.b", COMMAND, ["command"], offers=self.offers)
        self.store.grant("shared.a", "shared.b", ADJUST, ["adjustment"], offers=self.offers)
        trust = policy(self.home, "shared.a")["shared.b"]
        self.assertEqual(trust.grants[COMMAND], frozenset({"command"}))
        # Direction: the consumer did not grant anything back.
        self.assertEqual(policy(self.home, "shared.b")["shared.a"].grants, {})

    def test_no_silent_widening_and_explicit_revocation(self):
        self.store.pair("shared.a", "shared.b")
        self.store.grant("shared.a", "shared.b", ADJUST, ["adjustment"], offers=self.offers)
        with self.assertRaisesRegex(PairingError, "ausdrücklich"):
            self.store.grant("shared.a", "shared.b", ADJUST, ["adjustment", "command"], offers=self.offers)
        self.assertEqual(policy(self.home, "shared.a")["shared.b"].grants[ADJUST], frozenset({"adjustment"}))
        self.store.grant("shared.a", "shared.b", ADJUST, ["adjustment", "command"], offers=self.offers, replace=True)
        self.assertEqual(policy(self.home, "shared.a")["shared.b"].grants[ADJUST], frozenset({"adjustment", "command"}))
        self.store.revoke("shared.a", "shared.b", ADJUST)
        self.assertNotIn(ADJUST, policy(self.home, "shared.a")["shared.b"].grants)
        with self.assertRaises(PairingError):
            self.store.revoke("shared.a", "shared.b", ADJUST)
        self.store.unpair("shared.a", "shared.b")
        self.assertEqual(policy(self.home, "shared.a"), {})
        self.assertFalse(self.store.is_paired("shared.a", "shared.b"))

    def test_rekey_keeps_grants_and_changes_key(self):
        self.store.pair("shared.a", "shared.b")
        self.store.grant("shared.a", "shared.b", COMMAND, ["command"], offers=self.offers)
        old = policy(self.home, "shared.a")["shared.b"].key
        self.store.pair("shared.a", "shared.b", rekey=True)
        new = policy(self.home, "shared.a")["shared.b"]
        self.assertNotEqual(new.key, old)
        self.assertIn(COMMAND, new.grants)
        self.assertTrue(self.store.is_paired("shared.a", "shared.b"))

    def test_invalid_or_one_sided_policies_are_reported_and_never_overwritten_blindly(self):
        self.store.pair("shared.a", "shared.b")
        path = self.home / "config" / "shared.a.json"
        path.write_text('{"peers": {"shared.b": {"key": "zz", "grants": []}}}', encoding="utf-8")
        self.assertTrue(self.store.check("shared.a"))
        with self.assertRaises(PairingError):
            self.store.grant("shared.a", "shared.b", COMMAND, ["command"], offers=self.offers)
        self.assertIn('"zz"', path.read_text(encoding="utf-8"))
        path.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(PairingError, "unlesbar"):
            self.store.peers("shared.a")
        self.assertIn("einseitig", " ".join(self.store.check("shared.b")))

    def test_secrets_never_reach_audit_or_status(self):
        self.store.pair("shared.a", "shared.b")
        self.store.grant("shared.a", "shared.b", COMMAND, ["command"], offers=self.offers)
        # AP-POLISH-001: key is DPAPI-protected on disk; take the decrypted key from the runtime parser.
        stored = json.loads((self.home / "config" / "shared.a.json").read_text())["peers"]["shared.b"]
        self.assertNotIn("key", stored)
        key = policy(self.home, "shared.a")["shared.b"].key.hex()
        self.assertNotIn(key, (self.home / "audit.jsonl").read_text(encoding="utf-8"))
        status = self.store.status("shared.a")
        self.assertFalse(status["online"])
        self.assertNotIn(key, json.dumps(status))
        for grant in self.store.grants("shared.a"):
            self.assertNotIn(key, grant.describe())

    def test_status_reports_fresh_runtime_file_only(self):
        import hashlib
        directory = self.home / "status"
        directory.mkdir(parents=True)
        file = directory / (hashlib.sha256(b"shared.a").hexdigest() + ".json")
        row = dict(format="shared-folder-status-1", plugin="shared.a", instance="0" * 32, time=time.time(),
                   sdk_attached=True, peers={"shared.b": dict(local="connected", circle="reachable", connected=True)})
        file.write_text(json.dumps(row))
        status = self.store.status("shared.a")
        self.assertTrue(status["online"])
        self.assertTrue(status["peers"]["shared.b"]["connected"])
        row["time"] = time.time() - 60
        file.write_text(json.dumps(row))
        self.assertFalse(self.store.status("shared.a")["online"])

    def test_project_offers_mirror_owner_runtime_rules(self):
        self.assertEqual(self.offers[Scope("action", "action.command")], ("command",))
        self.assertEqual(self.offers[COMMAND], ("command",))
        self.assertEqual(self.offers[ADJUST], ("adjustment", "command"))
        self.assertNotIn(Scope("action", "action.editor"), self.offers)
        self.assertIn(Scope("folder", initial_layout(RAW)[0]["folders"][0]["nodes"][0]["id"]), self.offers)


if __name__ == "__main__":
    unittest.main()
