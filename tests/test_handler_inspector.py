"""HandlerInspector: Qt-freier Lebenszyklus und Integration in die geführte Shell (V-100 bis V-102)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from adapters.logitech.native import parse_native_project
from studio.handler_inspector import (HandlerError, check_handler_delete, handler_usage, propose_handler_create,
                                      propose_handler_delete, propose_handler_rename, suggest_handler_id)
from studio.native_shell import NativeStudioShell
from studio.native_shell.build_controller import NativeBuildController
from studio.native_shell.new_project import create_native_project, new_project_raw
from studio.workflow import DONE, ERROR, WARNING
from studio.workflow.facts import handler_snippet, registered_handlers


class HandlerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.raw = new_project_raw("demo.plugin", "Demo")

    def test_create_appends_one_valid_handler_and_keeps_input_untouched(self):
        before = repr(self.raw)
        proposed = propose_handler_create(self.raw, "handler.licht")
        self.assertEqual(repr(self.raw), before)
        self.assertEqual(proposed["handlers"][-1], {"id": "handler.licht", "callback_id": "handler.licht"})
        self.assertEqual(proposed["actions"], self.raw["actions"])
        parse_native_project(proposed)
        self.assertEqual(suggest_handler_id(proposed, "licht"), "handler.licht-2")

    def test_create_rejects_invalid_duplicate_and_action_ids(self):
        for bad in ("", "Handler Main", "handler.main", "action.command"):
            with self.assertRaises(HandlerError):
                propose_handler_create(self.raw, bad)

    def test_rename_moves_all_action_references_in_one_proposal(self):
        proposed = propose_handler_rename(self.raw, "handler.main", "handler.core")
        self.assertEqual(proposed["handlers"], [{"id": "handler.core", "callback_id": "handler.core"}])
        self.assertTrue(all(a["handler"] == "handler.core" for a in proposed["actions"]))
        self.assertEqual(handler_usage(proposed, "handler.core"), ("action.command", "action.toggle"))
        for bad in ("handler.main", "action.toggle", "Nicht gültig"):
            with self.assertRaises(HandlerError):
                propose_handler_rename(self.raw, "handler.main", bad)
        with self.assertRaises(HandlerError):
            propose_handler_rename(self.raw, "handler.fehlt", "handler.x")

    def test_delete_protects_used_and_last_handler(self):
        self.assertIn("2 Aktion(en)", check_handler_delete(self.raw, "handler.main").reason)
        with self.assertRaises(HandlerError):
            propose_handler_delete(self.raw, "handler.main")
        two = propose_handler_create(self.raw, "handler.frei")
        self.assertTrue(check_handler_delete(two, "handler.frei").allowed)
        self.assertEqual(propose_handler_delete(two, "handler.frei")["handlers"], self.raw["handlers"])
        single = propose_handler_create(self.raw, "handler.neu")
        for action in single["actions"]:
            action["handler"] = "handler.neu"
        single = propose_handler_delete(single, "handler.main")
        self.assertIn("letzte Handler", check_handler_delete(
            {**single, "actions": [dict(a, handler="x") for a in single["actions"]]}, "handler.neu").reason)


class HandlerShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.patches = [patch.dict(os.environ, {"LOGI_STUDIO_DATA": str(self.dir / "data"),
                                                "LOCALAPPDATA": str(self.dir / "local"),
                                                "LOGI_SHARED_HOME": str(self.dir / "shared")}),
                        patch.object(NativeBuildController, "quick_prerequisites", lambda self: [])]
        for item in self.patches:
            item.start()
        self.project = create_native_project(self.dir / "demo.json", "demo.plugin", "Demo")
        self.shell = NativeStudioShell(self.project, workflow=True)
        self.wf = self.shell.workflow

    def tearDown(self):
        self.wf.timer.stop()
        self.shell._context_timer.stop()
        self.shell.pairing_controller.timer.stop()
        self.shell.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def criterion(self, key):
        return next(c for s in self.wf.states for c in s.criteria if c.key == key)

    def test_handler_step_shows_the_panel_with_usage(self):
        self.assertEqual(self.wf.active, "handlers")
        self.assertIs(self.shell.tabs.currentWidget(), self.wf.handlers)
        table = self.wf.handlers.table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "handler.main")
        self.assertIn("2 Aktion(en)", table.item(0, 1).text())
        self.assertIn("Noch keine Handlerdatei", self.wf.handlers.file_status.text())
        self.assertFalse(self.wf.handlers.delete_button.isEnabled())

    def test_v101_template_creates_a_valid_file_once_and_completes_the_step(self):
        self.assertTrue(self.wf.create_handler_file())
        target = self.dir / "demo_handlers.py"
        self.assertEqual(registered_handlers(target), {"handler.main"})
        self.assertEqual(self.shell.build_controller.handler.text(), "demo_handlers.py")
        self.assertEqual(self.wf.state("handlers").status, DONE)
        self.assertIn("✔ demo_handlers.py", self.wf.handlers.file_status.text())
        self.assertIn("registriert", self.wf.handlers.table.item(0, 2).text())
        target.write_text(target.read_text(encoding="utf-8") + "\n# eigener Code\n", encoding="utf-8")
        own = target.read_bytes()
        self.shell.build_controller.handler.setText("")
        self.assertTrue(self.wf.create_handler_file())  # vorhandene Datei wird zugeordnet, nie überschrieben
        self.assertEqual(target.read_bytes(), own)
        self.assertFalse(self.shell.coordinator.session.dirty)  # Projektdatei bleibt unberührt

    def test_v100_create_rename_delete_commit_once_through_the_session(self):
        session = self.shell.coordinator.session
        with patch.object(QInputDialog, "getText", return_value=("handler.licht", True)):
            self.wf.handlers.ask_create()
        self.assertEqual([h["id"] for h in session.snapshot()["handlers"]], ["handler.main", "handler.licht"])
        self.assertTrue(session.dirty and session.can_undo)
        self.assertEqual(self.shell.coordinator.selection, ("handler", "handler.licht"))
        self.assertEqual(self.wf.handlers.selected(), "handler.licht")
        self.assertTrue(self.wf.handlers.delete_button.isEnabled())
        with patch.object(QInputDialog, "getText", return_value=("handler.lampe", True)):
            self.wf.handlers.ask_rename()
        self.assertIn("handler.lampe", [h["id"] for h in session.snapshot()["handlers"]])
        self.wf.handlers.select("handler.main")
        with patch.object(QInputDialog, "getText", return_value=("handler.kern", True)):
            self.wf.handlers.ask_rename()
        self.assertTrue(all(a["handler"] == "handler.kern" for a in session.snapshot()["actions"]))
        self.wf.handlers.select("handler.lampe")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.wf.handlers.ask_delete()
        self.assertEqual([h["id"] for h in session.snapshot()["handlers"]], ["handler.kern"])
        self.shell.coordinator.undo()
        self.assertEqual(len(session.snapshot()["handlers"]), 2)

    def test_invalid_handler_changes_nothing_and_explains(self):
        session = self.shell.coordinator.session
        revision = session.revision
        with patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(self.wf.create_handler("Nicht Gültig"))
            self.assertFalse(self.wf.delete_handler("handler.main"))
            self.assertFalse(self.wf.rename_handler("handler.main", "action.command"))
        self.assertEqual(warning.call_count, 3)
        self.assertEqual(session.revision, revision)
        self.assertFalse(session.dirty)

    def test_file_must_match_the_handlers_actually_used(self):
        self.wf.create_handler_file()
        self.assertTrue(self.wf.create_handler("handler.extra"))
        self.assertEqual(self.wf.state("handlers").status, DONE)  # unbenutzt: keine Registrierung nötig
        raw = self.shell.coordinator.session.snapshot()
        action = dict(raw["actions"][0], handler="handler.extra")
        self.shell.coordinator.apply_action_edit(action["id"], action,
                                                 base_revision=self.shell.coordinator.session.revision)
        self.assertEqual(self.criterion("handlers.registered").status, WARNING)
        self.assertIn('host.register_handler("handler.extra"', self.wf.handlers.snippet.toPlainText())
        target = self.dir / "demo_handlers.py"
        text = target.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + handler_snippet(["handler.extra"]) + "\n"
        target.write_text(text, encoding="utf-8")
        self.wf.refresh()
        self.assertEqual(self.criterion("handlers.registered").status, DONE)
        target.write_text(text + "\n" + handler_snippet(["handler.weg"]) + "\n", encoding="utf-8")
        self.wf.refresh()
        self.assertEqual(self.criterion("handlers.registered").status, ERROR)
        self.assertIn("handler.weg", self.wf.handlers.file_status.text())
        self.assertIn("zuerst Schritt 2", self.wf._build_guard())

    def test_v102_selection_is_mirrored_with_the_project_overview(self):
        self.wf.create_handler("handler.zwei")
        self.wf.handlers.table.selectRow(0)
        self.assertEqual(self.shell.coordinator.selection, ("handler", "handler.main"))
        self.shell.coordinator.select_node("handler", "handler.zwei")
        self.assertEqual(self.wf.handlers.selected(), "handler.zwei")


if __name__ == "__main__":
    unittest.main()
