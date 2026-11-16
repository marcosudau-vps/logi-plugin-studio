"""Cross-delivery acceptance: native Studio composer -> real SDK generator/build."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from studio.native_shell import NativeStudioShell
from studio.native_shell.build_integration import (
    NativeBuildPreflightError, prepare_native_build)
from studio.virtual_folders.binding import extension_path
from studio.virtual_folders.model import Reference


class NativeBuildIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "source.json"
        self.original = (ROOT / "examples/project_logitech_native_v1.json").read_bytes()
        self.path.write_bytes(self.original)
        self.window = NativeStudioShell(self.path)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        worker = self.window.build_controller.worker
        if worker:
            worker.wait(120_000)
            self.app.processEvents()
        if self.window.composer:
            self.window.composer.dispose()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def place_and_save(self, parameter="second"):
        composer = self.window.composer
        root = composer.document.root_id
        next_doc, identity = composer.document.add_action(
            root, Reference("sample.native", "action.command"),
            action_parameter=parameter)
        composer._run(lambda: composer._commit(next_doc))
        self.assertTrue(self.window.save_folders())
        self.assertFalse(composer.store.dirty)
        return identity

    def test_native_baseline_without_extension_is_not_silently_replaced(self):
        self.assertIsNone(self.window.coordinator.extension_store.path)
        inputs = prepare_native_build(
            self.window.coordinator.session, self.window.coordinator.extension_store)
        self.assertIsNone(inputs.folder_runtime)
        self.assertEqual(inputs.raw_project["plugin"]["id"], "sample.native")
        self.assertFalse(extension_path(self.path).exists())

    def test_saved_sidecar_projects_actual_placement_and_parameter(self):
        placement = self.place_and_save()
        store = self.window.coordinator.extension_store
        session = self.window.coordinator.session
        inputs = prepare_native_build(
            session, store, entrypoints={"folder.main": store.document.root_id})
        self.assertEqual(inputs.folder_runtime["version"], "sdk-folders-1")
        folders = inputs.folder_runtime["folders"]
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["start"], store.document.root_id)
        entries = folders[0]["nodes"][0]["pages"][0]["entries"]
        action = next(entry for entry in entries if entry["id"] == placement)
        self.assertEqual(action["action_id"], "action.command")
        self.assertEqual(action["action_parameter"], "second")
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(extension_path(self.path).exists())

    def test_unsaved_extension_and_native_session_are_refused(self):
        store = self.window.coordinator.extension_store
        session = self.window.coordinator.session
        updated, _ = store.document.add_action(
            store.document.root_id, Reference("sample.native", "action.command"))
        store.commit(updated)
        with self.assertRaisesRegex(NativeBuildPreflightError, "Virtuelle Ordner"):
            prepare_native_build(session, store)
        store.undo()
        session.replace({**session.snapshot(), "plugin": {
            **session.snapshot()["plugin"], "display_name": "Modified"}},
            base_revision=session.revision)
        with self.assertRaisesRegex(NativeBuildPreflightError, "Natives Projekt"):
            prepare_native_build(session, store)

    def test_disk_conflict_new_unloaded_sidecar_and_missing_entrypoints(self):
        session, store = self.window.coordinator.session, self.window.coordinator.extension_store
        extension_path(self.path).write_text("{}")
        with self.assertRaisesRegex(NativeBuildPreflightError, "externe Extension"):
            prepare_native_build(session, store)
        extension_path(self.path).unlink()
        self.place_and_save()
        with self.assertRaisesRegex(NativeBuildPreflightError, "Einstiegsknoten"):
            prepare_native_build(session, store)
        extension_path(self.path).write_text("{}")
        with self.assertRaisesRegex(NativeBuildPreflightError, "Disk-Conflict"):
            prepare_native_build(session, store, entrypoints={"folder.main": store.document.root_id})

    def test_orphan_reference_never_generates_executable_folder_action(self):
        self.place_and_save()
        session, store = self.window.coordinator.session, self.window.coordinator.extension_store
        raw = session.snapshot()
        raw["actions"] = [a for a in raw["actions"] if a["id"] != "action.command"]
        raw["folders"][0]["entries"] = [e for e in raw["folders"][0]["entries"]
                                          if e["action"] != "action.command"]
        session.replace(raw, base_revision=session.revision)
        session.save()
        with self.assertRaisesRegex(NativeBuildPreflightError, "orphan local action"):
            prepare_native_build(session, store, entrypoints={"folder.main": store.document.root_id})

    def test_no_implicit_build_mutation_and_multiple_folder_mapping(self):
        placement = self.place_and_save()
        c = self.window.build_controller
        self.assertIsNotNone(placement)
        raw = self.window.coordinator.session.snapshot()
        new = json.loads(json.dumps(raw["folders"][0]))
        new["id"] = "folder.second"
        for entry in new["entries"]:
            entry["id"] += ".second"
        raw["folders"].append(new)
        self.window.coordinator.session.replace(raw, base_revision=self.window.coordinator.session.revision)
        self.window.coordinator.session.save()
        from studio.virtual_folders.model import Document
        document = self.window.coordinator.extension_store.document
        extra, second_id = document.create_folder("Second root", parent_id=None)
        self.window.coordinator.extension_store.commit(extra)
        self.assertTrue(self.window.save_folders())
        with patch("studio.native_shell.build_controller.QInputDialog.getItem",
                   side_effect=[("Plugin-Root [" + document.root_id + "]", True),
                                ("Second root [" + second_id + "]", True)]):
            routes = c._entrypoints(raw, self.window.coordinator.extension_store)
        self.assertEqual(routes, {"folder.main": document.root_id, "folder.second": second_id})
        inputs = prepare_native_build(
            self.window.coordinator.session, self.window.coordinator.extension_store,
            entrypoints=routes)
        self.assertEqual(len(inputs.folder_runtime["folders"]), 2)
        self.assertNotEqual(inputs.folder_runtime["folders"][0]["start"],
                            inputs.folder_runtime["folders"][1]["start"])

    def test_build_button_rejects_dirty_inputs_without_writing(self):
        self.place_and_save()
        controller = self.window.build_controller
        store = self.window.coordinator.extension_store
        document, _ = store.document.add_action(
            store.document.root_id, Reference("sample.native", "action.multistate"))
        store.commit(document)
        with patch("studio.native_shell.build_controller.BuildWorker") as worker:
            self.assertFalse(controller.start())
            worker.assert_not_called()
        self.assertIn("Virtuelle Ordner", controller.last_error)
        self.assertFalse(controller.running)

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real Logitech SDK DLL not installed")
    def test_real_worker_compiles_persisted_virtual_folder_from_main_window(self):
        placement = self.place_and_save()
        original_project = self.path.read_bytes()
        original_extension = extension_path(self.path).read_bytes()
        controller = self.window.build_controller
        with patch("studio.native_shell.build_controller.ROOT", self.root):
            self.assertTrue(controller.start())
        self.assertTrue(controller.running)
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.window.open_project(self.path))
        deadline = time.monotonic() + 100
        while controller.running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.025)
        self.app.processEvents()
        self.assertFalse(controller.running, "SDK build worker did not finish")
        self.assertIsNone(controller.last_error, controller.last_error)
        result = controller.last_result
        self.assertIsNotNone(result, controller.log.toPlainText())
        out = Path(result["output"])
        self.assertTrue(Path(result["package"]).exists())
        self.assertIn(placement, (out / "src" / "Spec.cs").read_text(encoding="utf-8"))
        self.assertIn("sdk-folders-1", (out / "src" / "Spec.cs").read_text(encoding="utf-8"))
        self.assertEqual(self.path.read_bytes(), original_project)
        self.assertEqual(extension_path(self.path).read_bytes(), original_extension)
        self.assertEqual(controller.summary.text().split(":")[0], "BUILD_PROVEN")


if __name__ == "__main__":
    unittest.main()
