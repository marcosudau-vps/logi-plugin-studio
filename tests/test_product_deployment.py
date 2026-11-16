from __future__ import annotations

import json
import hashlib
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapters.logitech.deployment import install_link, plan_install, rollback_link
from adapters.logitech.errors import GenerationError
from runtime.wire import ConnectionSettings, json_bytes


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio-deployment-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.plugins = self.directory / "fake-user-plugins"
        self.package = self.directory / "package"
        (self.package / "bin").mkdir(parents=True)
        self.settings = ConnectionSettings("test.own.plugin", "0" * 64, 18900, secrets.token_hex(32))
        (self.package / "bin" / "studio.connection.json").write_bytes(json_bytes(self.settings.as_dict()))
        (self.package / "bin" / "TestPlugin.dll").write_bytes(b"isolated test fixture, not an SDK build")
        (self.package / "bin" / "TestPlugin.deps.json").write_text("{}", encoding="utf-8")
        (self.package / "metadata").mkdir()
        (self.package / "metadata" / "LoupedeckPackage.yaml").write_text("test metadata")
        self.marker = {
            "plugin_id": self.settings.plugin_id, "installation_id": self.settings.installation_id,
            "project_hash": self.settings.project_hash,
            "files": {str(p.relative_to(self.package)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in self.package.rglob("*") if p.is_file()}}
        (self.package / "studio.package.json").write_text(json.dumps(self.marker))
        self.target = self.plugins / (self.settings.plugin_id + ".link")

    def test_dry_run_has_no_side_effects(self):
        result = plan_install(self.package, target_root=self.plugins)
        self.assertEqual(result["authorization"], "DRY_RUN_ONLY")
        self.assertFalse(self.plugins.exists())
        self.assertFalse(result["service_restart"])

    def test_foreign_collision_is_blocked(self):
        self.plugins.mkdir()
        self.target.write_text(str(self.directory / "foreign-package"))
        with self.assertRaisesRegex(GenerationError, "collision blocked"):
            plan_install(self.package, target_root=self.plugins)
        self.assertEqual(self.target.read_text(), str(self.directory / "foreign-package"))

    def test_explicit_own_create_and_rollback_in_isolated_fake_directory(self):
        with patch("adapters.logitech.deployment.plugin_directory", return_value=self.plugins):
            plan = plan_install(self.package)
            with self.assertRaises(GenerationError):
                install_link(plan, confirm_plugin_id="wrong.plugin", receipt_dir=self.directory / "receipts")
            receipt = install_link(plan, confirm_plugin_id=self.settings.plugin_id, receipt_dir=self.directory / "receipts")
            self.assertEqual(self.target.read_text().strip(), str(self.package))
            rollback_link(receipt, confirm_plugin_id=self.settings.plugin_id)
            self.assertFalse(self.target.exists())

    def test_concurrent_edit_prevents_rollback_or_stale_install(self):
        with patch("adapters.logitech.deployment.plugin_directory", return_value=self.plugins):
            plan = plan_install(self.package)
            receipt = install_link(plan, confirm_plugin_id=self.settings.plugin_id, receipt_dir=self.directory / "receipts")
            self.target.write_text("external change")
            with self.assertRaises(GenerationError):
                rollback_link(receipt, confirm_plugin_id=self.settings.plugin_id)
            self.assertEqual(self.target.read_text(), "external change")
            with self.assertRaises(GenerationError):
                install_link(plan, confirm_plugin_id=self.settings.plugin_id, receipt_dir=self.directory / "receipts2")

    def test_update_own_link_and_exact_byte_rollback(self):
        self.plugins.mkdir()
        previous = b"\xef\xbb\xbf" + str(self.package).encode("utf-8") + b"\r\n"
        self.target.write_bytes(previous)
        with patch("adapters.logitech.deployment.plugin_directory", return_value=self.plugins):
            plan = plan_install(self.package)
            self.assertEqual(plan["operation"], "update_own")
            receipt = install_link(plan, confirm_plugin_id=self.settings.plugin_id, receipt_dir=self.directory / "receipts")
            rollback_link(receipt, confirm_plugin_id=self.settings.plugin_id)
            self.assertEqual(self.target.read_bytes(), previous)

    def test_missing_modified_unstaged_and_traversal_package_files_are_blocked(self):
        for change in ({**self.marker, "files": {}},
                       {**self.marker, "project_hash": "1" * 64},
                       {**self.marker, "files": {**self.marker["files"], "..\\foreign.txt": "0" * 64}}):
            (self.package / "studio.package.json").write_text(json.dumps(change))
            with self.assertRaises(GenerationError):
                plan_install(self.package, target_root=self.plugins)
        (self.package / "studio.package.json").write_text(json.dumps(self.marker))
        (self.package / "bin" / "TestPlugin.dll").write_bytes(b"modified")
        with self.assertRaises(GenerationError):
            plan_install(self.package, target_root=self.plugins)
        self.assertFalse(self.plugins.exists())


    def test_missing_or_modified_deps_is_refused_for_install(self):
        deps = self.package / "bin" / "TestPlugin.deps.json"
        deps.unlink()
        with self.assertRaises(GenerationError):
            plan_install(self.package, target_root=self.plugins)
        deps.write_text("altered", encoding="utf-8")
        with self.assertRaisesRegex(GenerationError, "modified"):
            plan_install(self.package, target_root=self.plugins)
        self.assertFalse(self.plugins.exists())

    def test_legacy_three_file_package_cannot_be_newly_installed(self):
        deps = self.package / "bin" / "TestPlugin.deps.json"
        deps.unlink()
        marker = json.loads((self.package / "studio.package.json").read_text())
        marker["files"].pop(str(Path("bin") / "TestPlugin.deps.json"))
        (self.package / "studio.package.json").write_text(json.dumps(marker))
        with self.assertRaisesRegex(GenerationError, "deps.json"):
            plan_install(self.package, target_root=self.plugins)
        # Existing own links and historical installation receipts must remain
        # distinguishable from foreign links and eligible for exact-byte rollback.
        self.plugins.mkdir()
        self.target.write_text(str(self.package))
        from adapters.logitech.deployment import _validate_package
        owner, _ = _validate_package(self.package, allow_legacy=True)
        self.assertEqual(owner["plugin_id"], self.settings.plugin_id)
        with self.assertRaises(GenerationError):
            plan_install(self.package, target_root=self.plugins)

    def test_modified_receipt_backup_is_not_restored(self):
        self.plugins.mkdir()
        self.target.write_text(str(self.package))
        with patch("adapters.logitech.deployment.plugin_directory", return_value=self.plugins):
            receipt = install_link(plan_install(self.package), confirm_plugin_id=self.settings.plugin_id,
                                   receipt_dir=self.directory / "receipts")
            before = self.target.read_bytes()
            raw = json.loads(receipt.read_text())
            raw["previous_content_hex"] = b"foreign replacement".hex()
            receipt.write_text(json.dumps(raw))
            with self.assertRaisesRegex(GenerationError, "backup content"):
                rollback_link(receipt, confirm_plugin_id=self.settings.plugin_id)
            self.assertEqual(self.target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
