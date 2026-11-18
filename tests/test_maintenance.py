"""Wartung: Qt-freie Logik und Fenster mit einer Attrappe der Installationsfunktionen (V-107)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox

from studio.maintenance.dialog import MaintenanceDialog
from studio.maintenance.model import DeactivationStore, collect_rows, deactivate, reactivate


class FakeBackend:
    """Bildet einen Pluginordner mit einem eigenen und einem fremden Plugin nach."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.installed = {"demo.plugin": {"link": "DemoPlugin", "target": str(self.directory / "DemoPlugin"),
                                          "studio_owned": True, "plugin_id": "demo.plugin", "kind": "directory",
                                          "package": str(self.directory / "DemoPlugin")}}
        self.foreign = {"link": "FremdesPlugin", "target": str(self.directory / "FremdesPlugin"),
                        "studio_owned": False, "plugin_id": None, "kind": "directory"}
        self.calls = []

    def inventory(self):
        return [self.foreign, *self.installed.values()]

    def runtime(self, package):
        return {"status": "PLUGIN_LOCAL"}

    def plugin_name(self, package):
        return "DemoPlugin"

    def reload(self, name):
        self.calls.append(("reload", name))
        return {"returncode": 0}

    def log_lines(self, name, since):
        return [{"time": since + 10, "level": "INFO", "message": f"Plugin '{name}' version '1' loaded from 'x'"}]

    def uninstall(self, plugin_id, plugin_name, method, receipt_dir):
        self.calls.append(("uninstall", plugin_id, plugin_name, method))
        receipt = Path(receipt_dir) / "r.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text("{}", encoding="utf-8")
        self.removed = self.installed.pop(plugin_id)
        return {"receipt": str(receipt), "residual_files": 0}

    def restore(self, method, receipt, plugin_id):
        self.calls.append(("restore", method, Path(receipt).name, plugin_id))
        self.installed[plugin_id] = self.removed

    def prerequisites(self):
        return SimpleNamespace(plugin_service_version="6.4", plugin_service_installed=True,
                               plugin_service_running=True, options_plus_installed=True, plugin_api_dll="dll",
                               dotnet_sdks=["10.0"], service_tool="tool", issues=[])


class MaintenanceModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend(self.temp.name)
        self.store = DeactivationStore(Path(self.temp.name) / "settings")

    def tearDown(self):
        self.temp.cleanup()

    def test_rows_list_own_plugins_first_and_foreign_read_only(self):
        rows = collect_rows(self.backend, self.store)
        self.assertEqual([r.plugin_id for r in rows], ["demo.plugin", None])
        own, foreign = rows
        self.assertEqual((own.state_text, own.kind_text, own.runtime, own.plugin_name),
                         ("aktiv", "Verzeichnis", "eigene Laufzeit, geprüft", "DemoPlugin"))
        self.assertEqual(foreign.state_text, "fremd – wird nicht verändert")
        with self.assertRaises(ValueError):
            deactivate(self.backend, self.store, foreign)

    def test_deactivate_and_reactivate_use_the_existing_functions_with_receipt(self):
        own = collect_rows(self.backend, self.store)[0]
        result = deactivate(self.backend, self.store, own)
        self.assertEqual(self.backend.calls[0], ("uninstall", "demo.plugin", "DemoPlugin", "directory"))
        self.assertTrue(Path(result["receipt"]).is_file())
        self.assertTrue(Path(result["receipt"]).is_relative_to(self.store.receipt_root))
        rows = collect_rows(self.backend, self.store)
        inactive = next(r for r in rows if r.plugin_id == "demo.plugin")
        self.assertEqual(inactive.state_text, "deaktiviert")
        with self.assertRaises(ValueError):
            deactivate(self.backend, self.store, inactive)
        reactivate(self.backend, self.store, inactive)
        self.assertEqual(self.backend.calls[1:], [("restore", "directory", "r.json", "demo.plugin"),
                                                  ("reload", "DemoPlugin")])
        self.assertEqual(self.store.entries(), {})
        self.assertTrue(collect_rows(self.backend, self.store)[0].active)
        with self.assertRaises(ValueError):
            reactivate(self.backend, self.store, collect_rows(self.backend, self.store)[0])

    def test_store_survives_damage_and_ignores_reinstalled_plugins(self):
        self.store.directory.mkdir(parents=True)
        self.store.path.write_text("{kaputt", encoding="utf-8")
        self.assertEqual(self.store.entries(), {})
        self.assertIsNotNone(self.store.last_error)
        self.assertTrue(self.store.add("demo.plugin", "DemoPlugin", "directory", "r.json", "x"))
        self.assertEqual(len(collect_rows(self.backend, self.store)), 2)  # installiert gewinnt


class MaintenanceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend(self.temp.name)
        self.store = DeactivationStore(Path(self.temp.name) / "settings")
        self.dialog = MaintenanceDialog(backend=self.backend, store=self.store)

    def tearDown(self):
        self.dialog.wait()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_buttons_follow_the_selection(self):
        b = self.dialog.buttons
        self.assertFalse(b["reload"].isEnabled() or b["deactivate"].isEnabled() or b["reactivate"].isEnabled())
        self.dialog.table.selectRow(1)  # fremd
        self.assertFalse(b["reload"].isEnabled() or b["deactivate"].isEnabled())
        self.assertTrue(self.dialog.select_plugin("demo.plugin"))
        self.assertTrue(b["reload"].isEnabled() and b["deactivate"].isEnabled())
        self.assertFalse(b["reactivate"].isEnabled())
        from PySide6.QtWidgets import QLabel
        self.assertIn("bewusst nicht angeboten", self.dialog.findChild(QLabel, "maintenanceServiceNote").text())

    def test_deactivate_reactivate_reload_log_and_prerequisites(self):
        changes = []
        self.dialog.pluginChanged.connect(lambda key, active: changes.append((key, active)))
        self.dialog.select_plugin("demo.plugin")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.dialog.deactivate())
        self.assertEqual(self.backend.calls, [])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.dialog.deactivate())
        self.dialog.wait()
        self.assertEqual(changes, [("demo.plugin", False)])
        self.assertIn("deaktiviert", self.dialog.log.toPlainText())
        self.assertIn("Logi-Options+-Profil", self.dialog.log.toPlainText())
        self.dialog.select_plugin("demo.plugin")
        self.assertTrue(self.dialog.buttons["reactivate"].isEnabled())
        self.assertTrue(self.dialog.reactivate())
        self.dialog.wait()
        self.assertEqual(changes[-1], ("demo.plugin", True))
        self.dialog.select_plugin("demo.plugin")
        self.assertTrue(self.dialog.reload())
        self.dialog.wait()
        self.assertEqual(self.backend.calls[-1], ("reload", "DemoPlugin"))
        self.assertTrue(self.dialog.show_log())
        self.assertIn("loaded from", self.dialog.log.toPlainText())
        self.assertTrue(self.dialog.prerequisites())
        self.dialog.wait()
        self.assertIn("Alle Voraussetzungen erfüllt.", self.dialog.log.toPlainText())


if __name__ == "__main__":
    unittest.main()
