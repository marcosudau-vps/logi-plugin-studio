"""AP-RELEASE-FINAL-001 B/D: Studio tabs Installation and Shared-Peers."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from PySide6.QtWidgets import QApplication
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.gate import DEFAULT_MANIFEST_DIR
from adapters.logitech.host_runtime import native_host_bundle, resolve_shared_python
from adapters.logitech.deployment import prepare_package
from adapters.logitech.product import build_product, generate_product, provision_connection
from extensions.shared_folders.embedded_host import policy
from extensions.shared_folders.peer_runtime import Scope
from studio.native_shell import NativeStudioShell


class FakeService:
    reloads = []

    def reload(self, name):
        FakeService.reloads.append(name)
        return {"url": "fake", "returncode": 0}

    def diagnose(self, name, package, since):
        return {"status": "LOADED", "errors": []}

    def shared_hosts(self, connection):
        return []


def wait(app, controller, timeout=60):
    deadline = time.monotonic() + timeout
    while controller.running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


class DeliveryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugins = self.root / "fake-plugins"
        self.plugins.mkdir()
        self.enterContext(patch.dict(os.environ, {"LOGI_SHARED_HOME": str(self.root / "shared")}))
        self.enterContext(patch("adapters.logitech.deployment.plugin_directory", return_value=self.plugins))
        self.path = self.root / "project.json"
        raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        raw["plugin"]["id"] = "release.ui"
        self.raw = raw
        self.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        self.window = NativeStudioShell(self.path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close)

    def close(self):
        self.window.deployment_controller.shutdown()
        self.window.pairing_controller.timer.stop()
        if self.window.composer:
            self.window.composer.dispose()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_pairing_tab_pairs_grants_revokes_without_secrets_in_ui(self):
        pc = self.window.pairing_controller
        self.assertEqual(pc.owner, "release.ui")
        pc.peer_a.setCurrentText("release.ui")
        pc.peer_b.setCurrentText("release.peer")
        self.assertTrue(pc.pair())
        home = self.root / "shared"
        self.assertTrue(pc.store.is_paired("release.ui", "release.peer"))
        self.assertEqual(policy(home, "release.ui")["release.peer"].grants, {})
        self.assertEqual(pc.consumer.currentText(), "release.peer")
        target = Scope("action", "action.command", "first")
        pc.scope.setCurrentIndex(next(i for i in range(pc.scope.count()) if pc.scope.itemData(i) == target))
        pc.op_command.setChecked(False)
        pc.op_adjust.setChecked(True)
        self.assertFalse(pc.grant())  # adjustment is not allowed for a command action
        pc.op_adjust.setChecked(False)
        pc.op_command.setChecked(True)
        self.assertTrue(pc.grant())
        self.assertEqual(policy(home, "release.ui")["release.peer"].grants[target], frozenset({"command"}))
        self.assertEqual(pc.grants.rowCount(), 1)
        # AP-POLISH-001: key is DPAPI-protected on disk; take the decrypted key from the runtime parser.
        stored = json.loads((home / "config" / "release.ui.json").read_text())["peers"]["release.peer"]
        self.assertNotIn("key", stored)
        key = policy(home, "release.ui")["release.peer"].key.hex()
        self.assertTrue(pc.diagnose())
        self.assertNotIn(key, pc.log.toPlainText())
        self.assertNotIn(key, self.path.read_text(encoding="utf-8"))
        pc.grants.selectRow(0)
        self.assertTrue(pc.revoke())
        self.assertEqual(policy(home, "release.ui")["release.peer"].grants, {})
        self.assertTrue(pc.unpair(confirmed=True))
        self.assertEqual(policy(home, "release.ui"), {})

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file() and shutil.which("dotnet"), "Requires SDK and .NET")
    def test_installation_tab_install_host_rollback_uninstall_restore(self):
        out = self.root / "build"
        plan = generate_product(self.path, output_dir=out, assembly_name="ReleaseUiPlugin", folder_mode="native")
        build = build_product(plan, out, log_path=out / "build.log")
        connection = provision_connection(plan, out)
        package = prepare_package(plan, out, connection)
        bundle = out / "native-host.pyz"
        bundle.write_bytes(native_host_bundle(self.raw, None, "native", DEFAULT_MANIFEST_DIR, None))
        dc = self.window.deployment_controller
        dc.accept_build({"build": build.as_dict(), "connection": str(connection), "package": str(package),
                         "plugin_id": "release.ui", "manifest": plan.manifest, "output": str(out),
                         "folder_mode": "native", "host_bundle": str(bundle), "assembly": "ReleaseUiPlugin"})
        self.assertEqual(dc.status_labels["build"].text(), "OK")
        self.assertEqual(dc.status_labels["package"].text(), "VALID")
        self.assertEqual(dc.status_labels["hardware"].text(), "HARDWARE_PENDING")
        with patch("adapters.logitech.workflow.ServiceAdapter", FakeService):
            self.assertTrue(dc.install(confirmed=True))
            wait(self.app, dc)
        self.assertEqual(dc.status_labels["installed"].text(), "INSTALLED", dc.log.toPlainText())
        self.assertEqual(dc.status_labels["loaded"].text(), "LOADED")
        self.assertEqual(dc.status_labels["rollback"].text(), "AVAILABLE")
        installed = self.plugins / "ReleaseUi"
        self.assertTrue((installed / "studio.package.json").is_file())
        self.assertTrue((installed / "bin" / "ReleaseUiPlugin.dll").is_file())
        self.assertIn("ReleaseUi", FakeService.reloads)
        if resolve_shared_python():
            dc.toggle_host()
            self.assertTrue(dc.host.running)
            with patch("adapters.logitech.workflow.ServiceAdapter", FakeService):
                dc.check()
                wait(self.app, dc)
            self.assertEqual(dc.status_labels["connection"].text(), "ACTIVE", dc.log.toPlainText())
            dc.toggle_host()
            self.assertIsNone(dc.host.process)
        with patch("adapters.logitech.workflow.ServiceAdapter", FakeService):
            self.assertTrue(dc.rollback(confirmed=True))
            wait(self.app, dc)
        self.assertEqual(dc.status_labels["installed"].text(), "ROLLED_BACK")
        self.assertFalse((installed / "studio.package.json").exists())
        with patch("adapters.logitech.workflow.ServiceAdapter", FakeService):
            self.assertTrue(dc.install(confirmed=True))
            wait(self.app, dc)
            self.assertTrue(dc.uninstall(confirmed=True))
            wait(self.app, dc)
        self.assertEqual(dc.status_labels["installed"].text(), "REMOVED")
        self.assertFalse((installed / "studio.package.json").exists())
        self.assertTrue(dc.restore())
        self.assertTrue((installed / "studio.package.json").exists())
        rows = dc.show_inventory()
        self.assertTrue(any(r["studio_owned"] for r in rows))


if __name__ == "__main__":
    unittest.main()
