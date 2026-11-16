"""AP-RELEASE-FINAL-001 A: plugin type selection Native/Compatible/Shared in the native Studio."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from studio.native_shell import NativeStudioShell
from studio.native_shell.build_integration import (FOLDER_MODES, NativeBuildPreflightError,
                                                   prepare_native_build, validate_handler)
from studio.virtual_folders.binding import extension_path
from studio.virtual_folders.model import Reference

HANDLER = '''"""Trusted test handler."""
def register(host):
    host.register_handler("handler.main", "invoke", lambda payload, context: {"ok": True})
'''


class StudioModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "source.json"
        raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        raw["plugin"]["id"] = "release.modes"
        self.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        (self.root / "handler.py").write_text(HANDLER, encoding="utf-8")
        self.window = NativeStudioShell(self.path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        worker = self.window.build_controller.worker
        if worker:
            worker.wait(180_000)
            self.app.processEvents()
        if self.window.composer:
            self.window.composer.dispose()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def place(self, plugin, resource, parameter=None):
        composer = self.window.composer
        document, identity = composer.document.add_action(
            composer.document.root_id, Reference(plugin, resource), action_parameter=parameter)
        composer._run(lambda: composer._commit(document))
        self.assertTrue(self.window.save_folders())
        return identity

    def run_build(self, mode, handler=None):
        controller = self.window.build_controller
        controller.set_folder_mode(mode)
        controller.handler.setText(handler or "")
        with patch("studio.native_shell.build_controller.ROOT", self.root):
            self.assertTrue(controller.start(), controller.last_error)
        deadline = time.monotonic() + 170
        while controller.running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.025)
        self.app.processEvents()
        self.assertFalse(controller.running)
        self.assertIsNone(controller.last_error, controller.log.toPlainText())
        return controller.last_result

    def test_three_visible_types_with_compatible_default_and_explanation(self):
        controller = self.window.build_controller
        self.assertEqual(controller.folder_mode, "compatible")
        self.assertEqual([controller.mode.itemData(i) for i in range(controller.mode.count())],
                         ["compatible", "native", "shared"])
        for mode, (label, _) in FOLDER_MODES.items():
            controller.set_folder_mode(mode)
            self.assertIn(label, controller.mode_description.text())
        self.assertIn("Peer-Runtime", controller.mode_description.text())

    def test_preflight_projects_external_references_only_in_shared_mode(self):
        external = self.place("release.owner", "action.command", "first")
        local = self.place("release.modes", "action.multistate")
        c = self.window.coordinator
        routes = {"folder.main": c.extension_store.document.root_id}
        shared = prepare_native_build(c.session, c.extension_store, entrypoints=routes, folder_mode="shared")
        self.assertEqual(shared.shared_references,
                         [dict(placement=external, plugin="release.owner",
                               scope=dict(kind="action", resource="action.command", parameter="first"))])
        compatible = prepare_native_build(c.session, c.extension_store, entrypoints=routes)
        self.assertIsNone(compatible.shared_references)
        self.assertTrue(any("offline" in w for w in compatible.warnings))
        native = prepare_native_build(c.session, c.extension_store, folder_mode="native")
        self.assertIsNone(native.folder_runtime)
        self.assertTrue(any("NICHT ausgeliefert" in w for w in native.warnings))
        with self.assertRaises(NativeBuildPreflightError):
            prepare_native_build(c.session, c.extension_store, entrypoints=routes, folder_mode="native")
        with self.assertRaises(NativeBuildPreflightError):
            prepare_native_build(c.session, c.extension_store, entrypoints=routes, folder_mode="peer")
        self.assertIsNotNone(local)

    def test_handler_file_is_validated_statically_without_import(self):
        self.assertEqual(validate_handler(self.path, "handler.py"), "handler.py")
        (self.root / "bad.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "boom.py").write_text("raise SystemExit('imported!')\ndef register(host): pass\n", encoding="utf-8")
        self.assertEqual(validate_handler(self.path, "boom.py"), "boom.py")  # never executed
        for bad in ("bad.py", "../handler.py", "C:/x.py", "missing.py", "source.json"):
            with self.assertRaises(NativeBuildPreflightError):
                validate_handler(self.path, bad)

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real Logitech SDK DLL not installed")
    def test_real_shared_and_native_builds_from_main_window_keep_sources_unchanged(self):
        external = self.place("release.owner", "action.command", "first")
        project_before = self.path.read_bytes()
        sidecar_before = extension_path(self.path).read_bytes()
        shared = self.run_build("shared", "handler.py")
        out = Path(shared["output"])
        self.assertEqual(shared["folder_mode"], "shared")
        manifest = json.loads((out / "generated.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["folder_runtime"]["mode"], "shared")
        self.assertIn("shared_folder_peer", manifest)
        with zipfile.ZipFile(out / "shared-folder-host.pyz") as bundle:
            references = json.loads(bundle.read("shared/references.json"))
            self.assertIn("shared_plugin_handler.py", bundle.namelist())
        self.assertEqual(references[0]["placement"], external)
        self.assertIsNone(shared["host_bundle"])
        native = self.run_build("native", "handler.py")
        nout = Path(native["output"])
        self.assertEqual(native["folder_mode"], "native")
        self.assertFalse((nout / "shared-folder-host.pyz").exists())
        self.assertFalse((nout / "src" / "NativeFolders.cs").exists())
        self.assertTrue((nout / "src" / "StaticSdkFolder.cs").exists())
        with zipfile.ZipFile(native["host_bundle"]) as bundle:
            self.assertIn("studio_plugin_handler.py", bundle.namelist())
            self.assertEqual(json.loads(bundle.read("native/mode.json")), "native")
        self.assertIn("Nativ", self.window.build_controller.summary.text())
        self.assertEqual(self.path.read_bytes(), project_before)
        self.assertEqual(extension_path(self.path).read_bytes(), sidecar_before)


if __name__ == "__main__":
    unittest.main()
