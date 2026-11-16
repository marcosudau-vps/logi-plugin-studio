from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import Qt, QThread, QObject, Slot
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QMessageBox
    from studio.app import StudioWindow
    from studio.fields import ConfigForm, ObjectEditor, parsed
    from studio.images import export_image, render_tile
    from studio.workers import BuildWorker, DiagnosticWorker
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.product import read_asset
from core.io import load_raw
from library.document import DocumentError, ProjectDocument
from library.templates import callback_project
from unittest.mock import patch


@unittest.skipUnless(HAS_QT, "PySide6 Widgets required")
class StudioUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.path.write_text(json.dumps(callback_project()), encoding="utf-8")
        self.window = StudioWindow(self.path)
        self.addCleanup(self.cleanup_window)
        self.window.show()
        self.app.processEvents()

    def cleanup_window(self):
        self.window.document._saved = self.window.document.text
        if self.window.editor:
            self.window.editor.pending = False
        self.window._raw_pending = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_real_widgets_start_and_all_objects_have_property_editors(self):
        self.assertEqual(self.window.pages.count(), 6)
        self.assertEqual(self.window.validation_table.rowCount(), 0)
        for section in ("components", "states", "bindings", "views", "presentations"):
            entity = self.window.document.raw[section][0]
            editor = ObjectEditor(self.window.document, section, entity)
            self.assertEqual(editor.value(), entity)
            editor.deleteLater()
        self.assertTrue(self.window.preview_page_label.text().startswith("Seite 1/1"))

    def test_component_form_edit_rename_save_and_reload(self):
        self.window.selection = ("components", "action.first")
        self.window.refresh()
        editor = self.window.editor
        editor.id_field.setText("action.renamed")
        editor.config_form._fields["display_name"][0].setText("Meine umbenannte Aktion")
        self.window.apply_editor()
        raw = self.window.document.raw
        self.assertEqual(raw["bindings"][0]["source"]["owner_id"], "action.renamed")
        self.assertEqual(raw["views"][0]["placements"][0]["component"], "action.renamed")
        self.assertTrue(self.window.document.dirty)
        self.assertTrue(self.window.save_project())
        loaded = ProjectDocument()
        loaded.load(self.path)
        self.assertEqual(raw, loaded.raw)

    def test_placement_editor_supports_more_than_physical_page(self):
        self.window.selection = ("views", "view.main")
        self.window.refresh()
        for _ in range(10):
            self.window.editor._new_placement()
            self.window.editor.table.cellWidget(self.window.editor.table.rowCount() - 1, 1).setCurrentText("action.first")
        self.window.apply_editor()
        self.assertEqual(len(self.window.document.raw["views"][0]["placements"]), 12)
        self.window.preview_view.setCurrentText("view.main")
        self.window.render_preview()
        self.assertIn("Seite 1/2", self.window.preview_page_label.text())
        self.window._change_page(1)
        self.assertIn("Seite 2/2", self.window.preview_page_label.text())

    def test_variant_and_binding_forms_make_real_model_changes(self):
        self.window.selection = ("presentations", "visual.mode")
        self.window.refresh()
        self.window.editor.table.cellWidget(0, 1).setText("Neue LCD-Beschriftung")
        self.window.apply_editor()
        self.assertEqual(self.window.document.raw["presentations"][0]["variants"]["idle"]["text"], "Neue LCD-Beschriftung")
        self.window.selection = ("bindings", "binding.first")
        self.window.refresh()
        source = self.window.editor.widgets["source"]
        source.setCurrentIndex(1)
        self.window.apply_editor()
        self.assertEqual(self.window.document.raw["bindings"][0]["source"]["owner_id"], "action.second")

    def test_live_validation_reports_invalid_payload_schema_without_repair(self):
        self.window.selection = ("states", "state.mode")
        self.window.refresh()
        self.window.editor.widgets["scope"].setCurrentText("session")
        self.window.validate_live()
        self.assertGreater(self.window.validation_table.rowCount(), 0)
        self.window.apply_editor()
        self.assertEqual(self.window.document.raw["states"][0]["scope"], "session")

    def test_png_export_size_alpha_and_preview_match_fallback(self):
        source = Path(self.tmp.name) / "input.png"
        image = QImage(40, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(250, 40, 20, 127))
        self.assertTrue(image.save(str(source), "PNG"))
        destination = Path(self.tmp.name) / "assets" / "example.png"
        export_image(source, destination, 116)
        raster = QImage(str(destination))
        self.assertEqual((raster.width(), raster.height()), (116, 116))
        self.assertEqual(raster.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(raster.pixelColor(50, 50).alpha(), 0)
        read_asset(Path(self.tmp.name), {"id": "example", "path": "assets/example.png"})
        raw = self.window.document.raw
        tile = render_tile(raw, Path(self.tmp.name), raw["views"][0]["placements"][0])
        self.assertEqual(tile.pixelColor(0, 0).name(), "#243449")
        with self.assertRaises(DocumentError):
            export_image(source, destination)

    def test_json_property_fields_reject_duplicates_and_nan(self):
        for text in ('{"a":1,"a":2}', 'NaN', '{"value":Infinity}'):
            with self.assertRaises(DocumentError):
                parsed(text)
        self.window.selection = ("states", "state.mode")
        self.window.refresh()
        self.window.editor.widgets["value_schema"].setPlainText("{invalid-json")
        self.window.editor.tabs.setCurrentIndex(1)
        self.assertEqual(self.window.editor.tabs.currentIndex(), 0)
        self.assertFalse(self.window.editor.error_label.isHidden())
        schema = {"type": "object", "properties": {"count": {"type": "integer"}, "fraction": {"type": "number"},
                                                   "optional": {"type": "string"}}}
        values = {"count": 10**40, "fraction": 0.123456789123}
        form = ConfigForm(schema, values)
        self.assertEqual(form.value(), values)
        form.deleteLater()

    def test_malformed_model_stays_editable_without_silent_repair(self):
        for broken in ({"project": None, "components": None, "views": None},
                       {**callback_project(), "states": ["invalid"], "presentations": None}):
            self.window.document.replace_raw(broken)
            expected = self.window.document.raw
            self.window.refresh()
            self.assertEqual(self.window.document.raw, expected)
            self.assertGreater(self.window.validation_table.rowCount(), 0)
            self.assertIn("Keine Vorschau", self.window.preview_page_label.text())
            self.assertEqual(json.loads(self.window.project_json.toPlainText()), expected)

    def test_cancel_and_discard_do_not_apply_invalid_unsaved_json(self):
        before = self.window.document.raw
        self.window.project_json.setPlainText("{not-json")
        with patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window._confirm_unsaved())
        self.assertEqual(self.window.document.raw, before)
        self.assertTrue(self.window._raw_pending)
        with patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window._confirm_unsaved())
        self.assertEqual(self.window.document.raw, before)
        self.window._raw_pending = False

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real installed SDK required")
    def test_worker_builds_product_and_signals_return_to_gui_thread(self):
        output = Path(self.tmp.name) / "build"
        source = Path(self.tmp.name) / "source.png"
        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor(25, 70, 150, 130))
        self.assertTrue(image.save(str(source), "PNG"))
        export_image(source, Path(self.tmp.name) / "assets" / "worker.png", 80)
        raw = self.window.document.raw
        raw["assets"] = [{"id": "asset.worker", "path": "assets/worker.png"}]
        raw["presentations"][0]["variants"]["idle"]["image"] = "asset.worker"
        self.window.document.replace_raw(raw)
        self.window.document.save()
        worker = BuildWorker(self.path, self.window.document.raw, output, "StudioUiTest", str(DEFAULT_SDK_DLL))
        results = []
        failures = []
        ticks = []
        gui_threads = []
        class Receiver(QObject):
            @Slot(dict)
            def receive(receiver, result):
                results.append(result)
                gui_threads.append(QThread.currentThread() == self.app.thread())
        receiver = Receiver()
        worker.succeeded.connect(receiver.receive)
        worker.failed.connect(failures.append)
        worker.start()
        until = time.monotonic() + 90
        while worker.isRunning() and time.monotonic() < until:
            self.app.processEvents()
            ticks.append(1)
            time.sleep(0.01)
        worker.wait(1000)
        self.app.processEvents()
        self.assertFalse(worker.isRunning())
        self.assertFalse(failures, failures)
        self.assertEqual(len(results), 1)
        self.assertEqual(gui_threads, [True])
        self.assertTrue(results[0]["build"]["ok"])
        self.assertGreater(len(ticks), 5)
        self.assertTrue(Path(results[0]["connection"]).is_file())
        self.assertTrue((Path(results[0]["package"]) / "metadata" / "LoupedeckPackage.yaml").is_file())
        worker.deleteLater()

    def test_diagnostic_missing_connection_has_explicit_worker_failure(self):
        worker = DiagnosticWorker(str(Path(self.tmp.name) / "missing.json"))
        errors = []
        worker.failed.connect(errors.append)
        worker.start()
        worker.wait(5000)
        self.app.processEvents()
        self.assertTrue(errors and "CONNECTION_UNREADABLE" in errors[0])
        worker.deleteLater()


if __name__ == "__main__":
    unittest.main()
