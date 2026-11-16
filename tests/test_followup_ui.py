from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from studio.app import StudioWindow
from library.templates import callback_project
from runtime.wire import project_digest
from studio.workers import ExportWorker


class FollowupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.path.write_text(json.dumps(callback_project()), encoding="utf-8")
        self.window = StudioWindow(self.path)
        self.errors = []
        self.window.show_error = self.errors.append
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.window._build = self.window._deployment = None
        self.window.document._saved = self.window.document.text
        self.window._raw_pending = False
        if self.window.editor:
            self.window.editor.pending = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_close_during_worker_is_blocked_without_thread_kill(self):
        self.window._build = object()
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertIn("Hintergrundauftrag", self.errors[0])

    def test_old_build_cannot_plan_for_changed_project(self):
        self.window.last_build = {"package": str(Path(self.tmp.name) / "missing"),
                                  "manifest": {"product": {"project_hash": project_digest(self.window.document.raw)}}}
        self.window.editor.widgets["display_name"].setText("Noch nicht gebaut")
        with patch("studio.app.DeploymentWorker") as worker:
            self.window.start_deployment_plan()
            worker.assert_not_called()
        self.assertTrue(self.errors)

    def wait_deployment(self):
        until = time.monotonic() + 5
        while self.window._deployment is not None and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.window._deployment)

    def deployment_fixture(self):
        import test_product_deployment as fixtures
        case = fixtures.DeploymentTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_real_plan_save_button_worker_is_read_only_and_refuses_overwrite(self):
        case = self.deployment_fixture()
        destination = Path(self.tmp.name) / "plan.json"
        self.window.last_build = {"package": str(case.package),
                                  "manifest": {"product": {"project_hash": project_digest(self.window.document.raw)}}}
        self.window.plan_save_button.setEnabled(True)
        with patch("adapters.logitech.deployment.plugin_directory", return_value=case.plugins), \
                patch("studio.app.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
            self.window.plan_save_button.click()
            self.wait_deployment()
            self.assertEqual(json.loads(destination.read_text())["authorization"], "DRY_RUN_ONLY")
            self.assertFalse(case.plugins.exists())
            original = destination.read_bytes()
            self.window.plan_save_button.click()
            self.wait_deployment()
            self.assertEqual(destination.read_bytes(), original)
            self.assertIn("FileExistsError", self.window.build_log.toPlainText())

    def test_real_rollback_ui_requires_preview_exact_id_and_confirmation_in_fake_directory(self):
        from adapters.logitech.deployment import install_link, plan_install
        case = self.deployment_fixture()
        with patch("adapters.logitech.deployment.plugin_directory", return_value=case.plugins):
            receipt = install_link(plan_install(case.package), confirm_plugin_id=case.settings.plugin_id,
                                   receipt_dir=Path(self.tmp.name) / "receipts")
            self.window.receipt.setText(str(receipt))
            self.assertFalse(self.window.rollback_button.isEnabled())
            self.window.rollback_plan_button.click()
            self.wait_deployment()
            self.assertTrue(self.window.rollback_button.isEnabled())
            initial = case.target.read_bytes()
            self.assertNotIn("previous_content_hex", self.window.build_log.toPlainText())
            with patch("studio.app.QInputDialog.getText", return_value=("wrong.plugin", True)):
                self.window.rollback_button.click()
                self.assertEqual(case.target.read_bytes(), initial)
            with patch("studio.app.QInputDialog.getText", return_value=(case.settings.plugin_id, True)), \
                    patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                self.window.rollback_button.click()
                self.assertEqual(case.target.read_bytes(), initial)
            with patch("studio.app.QInputDialog.getText", return_value=(case.settings.plugin_id, True)), \
                    patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                self.window.rollback_button.click()
                self.wait_deployment()
                self.assertFalse(case.target.exists())
                self.assertFalse(self.window.rollback_button.isEnabled())

    def test_safe_export_worker_never_exposes_secret_or_traceback(self):
        root = Path(self.tmp.name) / "sources"
        (root / "src").mkdir(parents=True)
        (root / "src" / "file.py").write_text("print('safe')")
        worker = ExportWorker(root, "FINAL-PRODUCT-02", root / "work" / "autopilot" / "FINAL-PRODUCT-02" / "delivery")
        successes, failures = [], []
        worker.succeeded.connect(successes.append)
        worker.failed.connect(failures.append)
        worker.run()
        self.assertTrue(successes[0]["crc_and_hashes_verified"])
        (root / "src" / "credentials.json").write_text("{}")
        worker.run()
        self.assertEqual(len(successes), 1)
        self.assertIn("SAFE_EXPORT_REFUSED", failures[0])
        self.assertNotIn("Traceback", failures[0])

    def test_preview_swap_hides_displaced_widgets_before_deferred_delete(self):
        old = [self.window.preview_grid.itemAt(index).widget() for index in range(self.window.preview_grid.count())]
        self.window.render_preview()
        self.assertTrue(all(widget.isHidden() for widget in old))
