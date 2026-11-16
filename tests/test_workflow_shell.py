"""Geführter Ablauf in der echten nativen Shell (Qt offscreen). Kanten V-90 bis V-99."""
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

from studio.native_shell import NativeStudioShell
from studio.native_shell.build_controller import NativeBuildController
from studio.native_shell.new_project import create_native_project
from studio.workflow import DONE, LOCKED, OPEN, STALE, STEP_KEYS
from studio.workflow.facts import handler_template, registered_handlers
from studio.workflow.store import WorkflowStore


class WorkflowShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LOGI_STUDIO_DATA": str(self.dir / "data"),
                                           "LOCALAPPDATA": str(self.dir / "local"),
                                           "LOGI_SHARED_HOME": str(self.dir / "shared")})
        self.env.start()
        self.prereq = patch.object(NativeBuildController, "quick_prerequisites", lambda self: [])
        self.prereq.start()
        self.project = create_native_project(self.dir / "demo.json", "demo.plugin", "Demo")
        self.shells = []

    def tearDown(self):
        for shell in self.shells:
            if shell.workflow:
                shell.workflow.timer.stop()
            shell._context_timer.stop()
            shell.pairing_controller.timer.stop()
            shell.deleteLater()
        self.app.processEvents()
        self.prereq.stop()
        self.env.stop()
        self.temp.cleanup()

    def shell(self, project=None, **kwargs):
        shell = NativeStudioShell(project, workflow=True, **kwargs)
        self.shells.append(shell)
        return shell

    def visible_tabs(self, shell):
        return [shell.tabs.tabText(i) for i in range(shell.tabs.count()) if shell.tabs.isTabVisible(i)]

    def write_handler(self, shell):
        text = handler_template("Demo", ["handler.main"])
        (self.dir / "demo_handlers.py").write_text(text, encoding="utf-8")
        shell.build_controller.handler.setText("demo_handlers.py")

    def fake_build(self, shell):
        wf, build, deploy = shell.workflow, shell.build_controller, shell.deployment_controller
        self.assertIsNone(wf._build_guard())
        build.last_result = {"package": "x", "output": "y", "folder_mode": "compatible"}
        deploy.result = build.last_result
        deploy.state = SimpleNamespace(status={}, receipt=None, steps=[])
        deploy.status_codes["package"] = "VALID"
        wf._build_finished()

    def test_shell_without_workflow_is_unchanged(self):
        plain = NativeStudioShell(self.project)
        self.shells.append(plain)
        self.assertIsNone(plain.workflow)
        self.assertEqual(plain.tabs.count(), 9)
        self.assertEqual(plain.tabs.tabText(0), "Auswahl / native Details")
        self.assertTrue(all(plain.tabs.isTabVisible(i) for i in range(plain.tabs.count())))
        self.assertEqual(plain.build_controller.guards, [])
        self.assertFalse(hasattr(plain, "save_all_action"))

    def test_v90_start_without_project_shows_only_start_and_help(self):
        shell = self.shell()
        wf = shell.workflow
        self.assertEqual(wf.active, "project")
        self.assertEqual(self.visible_tabs(shell), ["Start", "Hilfe"])
        self.assertTrue(shell.explorer.isHidden() and shell.catalog.isHidden())
        self.assertTrue(wf.rail.buttons["project"].isEnabled())
        self.assertFalse(any(wf.rail.buttons[k].isEnabled() for k in STEP_KEYS[1:]))
        self.assertFalse(wf.rail.next_button.isEnabled())
        self.assertIn("Noch kein Projekt", wf.start_page.project.text())
        self.assertFalse(wf.save_all_action.isVisible())
        self.assertTrue(shell.new_action.isVisible() and shell.open_action.isVisible())

    def test_v91_v92_steps_unlock_in_order_and_gate_views(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.assertEqual(wf.active, "handlers")  # Projekt vorhanden, Handlerdatei fehlt
        self.assertEqual(wf.state("project").status, DONE)
        self.assertEqual(wf.state("handlers").status, OPEN)
        self.assertEqual(wf.state("actions").status, LOCKED)
        self.assertFalse(shell.explorer.isHidden())
        self.assertTrue(shell.catalog.isHidden())
        self.assertNotIn("Plugin-Build", self.visible_tabs(shell))
        self.assertFalse(wf.enter("build"))
        self.assertEqual(wf.active, "handlers")
        self.assertIn("gesperrt", shell.statusBar().currentMessage())
        self.write_handler(shell)
        self.assertEqual(wf.state("handlers").status, DONE)
        self.assertTrue(wf.rail.next_button.isEnabled())
        self.assertTrue(wf.next())
        self.assertEqual(wf.active, "actions")
        self.assertIn("Aktionsinspektor", self.visible_tabs(shell))
        self.assertNotIn("Keypad", self.visible_tabs(shell))
        self.assertFalse(shell.catalog.isHidden())
        self.assertIs(shell.tabs.currentWidget(), shell.inspector)
        self.assertTrue(shell.rename_action.isVisible())
        self.assertFalse(shell.build_controller.action.isVisible())
        self.assertTrue(wf.enter("layout"))
        self.assertEqual(self.visible_tabs(shell), ["Keypad", "Virtuelle Ordner", "Probleme", "Hilfe"])
        self.assertTrue(wf.back())
        self.assertEqual(wf.active, "symbols")

    def test_v93_step_and_handler_file_are_remembered_per_project(self):
        shell = self.shell(self.project)
        self.write_handler(shell)
        self.assertTrue(shell.workflow.enter("actions"))
        again = self.shell(self.project)
        self.assertEqual(again.build_controller.handler.text(), "demo_handlers.py")
        self.assertEqual(again.workflow.active, "actions")
        self.assertEqual(again.coordinator.session.snapshot(), shell.coordinator.session.snapshot())
        self.assertNotIn("handler_file", self.project.read_text(encoding="utf-8"))

    def test_v94_expert_mode_shows_everything_and_is_remembered(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        wf.set_expert(True)
        self.assertEqual(len(self.visible_tabs(shell)), shell.tabs.count())
        self.assertFalse(shell.explorer.isHidden() or shell.catalog.isHidden())
        self.assertTrue(shell.save_action.isVisible() and shell.folder_save_action.isVisible())
        self.assertTrue(wf.enter("build"))  # frei erreichbar, Status bleibt sichtbar gesperrt
        self.assertEqual(wf.state("build").status, LOCKED)
        self.assertFalse(WorkflowStore().guided())
        wf.set_expert(False)
        self.assertTrue(WorkflowStore().guided())
        self.assertEqual(wf.active, "handlers")
        self.assertNotIn("Plugin-Build", self.visible_tabs(shell))

    def test_v95_checklist_entries_navigate(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.write_handler(shell)
        wf.enter("layout")
        self.assertTrue(any("Platzierung" in t and "[erfüllt]" in t for t in wf.rail.checklist_texts()))
        shell.tabs.setCurrentWidget(shell.problems)
        self.assertTrue(wf.activate_criterion("layout.references"))
        self.assertIs(shell.tabs.currentWidget(), shell.keypad.panel)
        self.assertFalse(wf.activate_criterion("install.package"))  # Ziel gehört nicht zu diesem Schritt
        self.assertFalse(wf.activate_criterion("unknown"))

    def test_v96_v97_guide_topics_use_the_existing_help(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        for key in STEP_KEYS:
            self.assertIsNotNone(shell.coordinator.registry.get("guide." + {
                "project": "project", "handlers": "handlers", "actions": "actions", "symbols": "symbols",
                "layout": "layout", "build": "build", "install": "install"}[key]))
        wf.show_guide()
        self.assertIs(shell.tabs.currentWidget(), shell.help_widget)
        self.assertEqual(shell.coordinator.help.current().resolved_topic_id, "guide.handlers")

    def test_v98_build_is_refused_until_everything_is_saved(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.assertIn("zuerst Schritt 2", wf._build_guard())
        self.write_handler(shell)
        self.assertIsNone(wf._build_guard())
        action = shell.coordinator.session.snapshot()["actions"][0]
        shell.coordinator.rename_action(action["id"], "Geändert", base_revision=shell.coordinator.session.revision)
        self.assertIn("Alles gespeichert", wf._build_guard())
        self.assertTrue(wf.save_all_action.isEnabled())
        self.assertTrue(shell.save_all())
        self.assertFalse(shell.coordinator.session.dirty)
        self.assertIsNone(wf._build_guard())
        wf.set_expert(True)
        shell.coordinator.rename_action(action["id"], "Nochmal", base_revision=shell.coordinator.session.revision)
        self.assertIsNone(wf._build_guard())  # Expertenmodus sperrt nicht

    def test_build_becomes_stale_after_a_saved_change(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.write_handler(shell)
        self.fake_build(shell)
        self.assertEqual(wf.state("build").status, DONE)
        self.assertEqual(wf.state("install").status, OPEN)
        action = shell.coordinator.session.snapshot()["actions"][0]
        shell.coordinator.rename_action(action["id"], "Neu", base_revision=shell.coordinator.session.revision)
        self.assertEqual(wf.state("build").status, OPEN)  # ungespeichert
        shell.save_all()
        self.assertEqual(wf.state("build").status, STALE)
        self.assertEqual(wf.state("install").status, LOCKED)
        self.assertIn("neu bauen", wf.rail.hint.text() if wf.active == "build" else
                      next(c.detail for c in wf.state("build").criteria if c.key == "build.done"))

    def test_device_test_must_be_confirmed_by_the_user(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.write_handler(shell)
        self.assertFalse(wf.confirm_hardware(confirmed=True))
        self.fake_build(shell)
        deploy = shell.deployment_controller
        deploy.state.status.update(installed="INSTALLED", loaded="LOADED", connection="ACTIVE")
        wf.refresh()
        self.assertEqual(wf.state("install").status, OPEN)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(wf.confirm_hardware())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(wf.confirm_hardware())
        self.assertEqual(wf.state("install").status, DONE)
        self.assertEqual(deploy.status_codes["hardware"], "HARDWARE_PASS")
        self.assertTrue(wf.enter("install"))
        self.assertIn("Fertig", wf.rail.hint.text())

    def test_v99_open_points_appear_in_the_existing_problem_list(self):
        shell = self.shell(self.project)
        wf = shell.workflow
        self.assertIn("workflow", shell.problems.sources())
        codes = [d.code for d in shell.problems.diagnostics("workflow")]
        self.assertEqual(codes, ["WORKFLOW_HANDLERS_FILE"])
        self.assertEqual(wf.facts().problem_errors, 0)  # eigene Hinweise zählen nicht als Projektfehler
        self.write_handler(shell)
        self.assertNotIn("workflow", shell.problems.sources())

    def test_save_all_writes_both_files_through_their_owners(self):
        shell = self.shell(self.project)
        self.write_handler(shell)
        action = shell.coordinator.session.snapshot()["actions"][0]
        shell.coordinator.rename_action(action["id"], "Geändert", base_revision=shell.coordinator.session.revision)
        self.assertTrue(shell.save_all())
        self.assertFalse(shell.coordinator.session.dirty)
        self.assertFalse(shell.composer.store.dirty)
        self.assertTrue(shell.save_all())  # ohne Änderungen ein erfolgreicher Leerlauf
        self.assertIn("Geändert", self.project.read_text(encoding="utf-8"))

    def test_handler_template_registers_every_handler(self):
        text = handler_template('Mein "Plugin"', ["handler.main", "handler.second", "handler-main"])
        compile(text, "handlers.py", "exec")
        file = self.dir / "t.py"
        file.write_text(text, encoding="utf-8")
        self.assertEqual(registered_handlers(file), {"handler.main", "handler.second", "handler-main"})
        self.assertIsNone(registered_handlers(self.dir / "fehlt.py"))


if __name__ == "__main__":
    unittest.main()
