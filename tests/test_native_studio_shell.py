import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from studio.native_shell import NativeStudioShell
from studio.app import StudioWindow, main


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = NativeStudioShell(ROOT / 'examples/project_logitech_native_v1.json')
        self.w.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.w.hide()
        self.w.deleteLater()
        self.app.processEvents()

    def test_v24_session_status(self):
        self.assertIn('SDK-natives Beispiel', self.w.windowTitle())
        self.assertIn('project_logitech_native_v1.json', self.w.statusBar().currentMessage())
        self.temporary_native()
        self.make_dirty()
        self.assertTrue(self.w.windowTitle().startswith('* '))
        self.assertIn('Ungespeichert', self.w.statusBar().currentMessage())
        self.assertTrue(self.w.undo_action.isEnabled())
        self.w.coordinator.save()
        self.assertFalse(self.w.windowTitle().startswith('* '))
        self.assertIn('Gespeichert', self.w.statusBar().currentMessage())

    def test_v25_selection_details(self):
        self.w.coordinator.select_node('action', 'action.command')
        self.assertIn('PluginDynamicCommand', self.w.details.toPlainText())
        self.assertIn('handler.main', self.w.details.toPlainText())

    def test_v28_focus_context(self):
        self.w.activateWindow()
        self.w.catalog.search_edit.setFocus()
        self.app.processEvents()
        self.assertEqual(self.w.coordinator.help.current().resolved_topic_id, 'catalog.search')

    def test_v29_f1_overrides_pin(self):
        self.w.coordinator.help.set_pinned(True)
        self.w.activateWindow()
        self.w.catalog.search_edit.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.w.catalog.search_edit, Qt.Key.Key_F1)
        self.app.processEvents()
        self.assertEqual(self.w.coordinator.help.current().resolved_topic_id, 'catalog.search')
        self.assertIs(self.w.tabs.currentWidget(), self.w.help_widget)

    def temporary_native(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'project.json'
        path.write_bytes((ROOT / 'examples/project_logitech_native_v1.json').read_bytes())
        self.w.coordinator.open_project(path)
        return path

    def make_dirty(self):
        self.w.coordinator.rename_action('action.command', 'User change', base_revision=self.w.coordinator.session.revision)

    def test_v16_history_save_reload(self):
        from studio.native_session import NativeProjectSession
        path = self.temporary_native()
        initial = self.w.coordinator.session.snapshot()
        self.make_dirty()
        self.assertTrue(self.w.windowTitle().startswith('* '))
        self.w.undo_action.trigger()
        self.assertEqual(self.w.coordinator.session.snapshot(), initial)
        self.assertFalse(self.w.coordinator.session.dirty)
        self.w.redo_action.trigger()
        self.assertTrue(self.w.coordinator.session.dirty)
        self.w.save_action.trigger()
        self.assertFalse(self.w.coordinator.session.dirty)
        self.assertEqual(NativeProjectSession.load(path).snapshot(), self.w.coordinator.session.snapshot())

    def test_v31_catalog_edit_to_dialog(self):
        self.temporary_native()
        with patch('studio.native_shell.window.QInputDialog.getText', return_value=('Dialog change', True)) as dialog:
            self.w.coordinator.request_edit('action.editor')
        dialog.assert_not_called()
        self.assertIs(self.w.tabs.currentWidget(), self.w.inspector)
        self.assertEqual(self.w.inspector.draft.action_id, 'action.editor')
        self.assertFalse(self.w.coordinator.session.dirty)

    def test_v32_reload(self):
        path = self.temporary_native()
        import json
        raw = json.loads(path.read_text())
        raw['plugin']['display_name'] = 'External valid change'
        path.write_text(json.dumps(raw), encoding='utf-8')
        self.w.reload_action.trigger()
        self.assertIn('External valid change', self.w.windowTitle())

    def test_v33_close_dirty_cancel_save_discard_conflict(self):
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QMessageBox
        path = self.temporary_native()
        self.make_dirty()
        for answer, accepted in ((QMessageBox.StandardButton.Cancel, False),
                                 (QMessageBox.StandardButton.Save, True)):
            event = QCloseEvent()
            with patch('studio.native_shell.window.QMessageBox.question', return_value=answer):
                self.w.closeEvent(event)
            self.assertEqual(event.isAccepted(), accepted)
        self.make_dirty()
        # Same name is a no-op; use a second actual change.
        self.w.coordinator.rename_action('action.editor', 'Other', base_revision=self.w.coordinator.session.revision)
        external = path.read_bytes() + b'\n'
        path.write_bytes(external)
        event = QCloseEvent()
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Save):
            self.w.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.w.coordinator.session.dirty)
        self.assertEqual(path.read_bytes(), external)
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            self.w.closeEvent(event)
        self.assertTrue(event.isAccepted())

    def test_dirty_project_switch_choices_and_invalid_target(self):
        from PySide6.QtWidgets import QMessageBox
        path = self.temporary_native()
        self.make_dirty()
        session = self.w.coordinator.session
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.w.open_project(path))
        self.assertIs(self.w.coordinator.session, session)
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            self.assertFalse(self.w.open_project(path.parent / 'missing.json'))
        self.assertIs(self.w.coordinator.session, session)
        self.assertTrue(session.dirty)
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.w.open_project(path))
        self.assertEqual(self.w.coordinator.session.native_project().actions[0].display_name, 'User change')
        self.w.coordinator.rename_action('action.command', 'Discard me', base_revision=self.w.coordinator.session.revision)
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.w.open_project(path))
        self.assertEqual(self.w.coordinator.session.native_project().actions[0].display_name, 'User change')

    def test_disk_conflict_blocks_project_switch(self):
        from PySide6.QtWidgets import QMessageBox
        path = self.temporary_native()
        self.make_dirty()
        session = self.w.coordinator.session
        external = path.read_bytes() + b'\n'
        path.write_bytes(external)
        with patch('studio.native_shell.window.QMessageBox.question', return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.w.open_project(ROOT / 'examples/project_logitech_native_v1.json'))
        self.assertIs(self.w.coordinator.session, session)
        self.assertTrue(session.dirty)
        self.assertEqual(path.read_bytes(), external)
        self.assertIn('extern verändert', self.w.statusBar().currentMessage())
        self.assertEqual(len(self.w.problems.diagnostics('save')), 1)

    def test_v27_capabilities_unavailable_no_writes(self):
        path = self.temporary_native()
        original = path.read_bytes()
        from studio.keypad_preview.widget import KeypadPreviewWidget
        preview = self.w.findChildren(KeypadPreviewWidget)
        self.assertEqual(len(preview), 1)
        self.assertIsNotNone(preview[0].frame())
        self.assertTrue(self.w.catalog.new_action_button.isEnabled())
        self.w.tabs.setCurrentWidget(self.w.keypad.panel)
        self.app.processEvents()
        self.w.coordinator.select_node('action', 'action.command')
        self.assertTrue(self.w.ict_action.isEnabled())
        with patch.object(self.w, 'open_symbol_designer') as open_designer:
            self.w.ict_action.trigger()
            open_designer.assert_called_once()
        self.assertFalse(self.w.coordinator.session.dirty)
        self.assertEqual(path.read_bytes(), original)

    def test_real_unsaved_dialog_cancel(self):
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer
        self.temporary_native()
        self.make_dirty()
        def cancel():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QMessageBox)
            dialog.button(QMessageBox.StandardButton.Cancel).click()
        QTimer.singleShot(20, cancel)
        self.assertFalse(self.w.confirm_unsaved())
        self.assertTrue(self.w.coordinator.session.dirty)

    def test_v36_redo_route(self):
        self.temporary_native()
        self.make_dirty()
        changed = self.w.coordinator.session.snapshot()
        self.w.undo_action.trigger()
        self.w.redo_action.trigger()
        self.assertEqual(self.w.coordinator.session.snapshot(), changed)

    def test_v37_save_route(self):
        path = self.temporary_native()
        self.make_dirty()
        session = self.w.coordinator.session
        with patch.object(session, 'save', wraps=session.save) as save:
            self.w.save_action.trigger()
            save.assert_called_once()
        self.assertFalse(session.dirty)
        import json
        self.assertEqual(json.loads(path.read_text()), session.snapshot())

    def test_v38_rename_toolbar_route(self):
        self.temporary_native()
        self.w.coordinator.select_node('action', 'action.multistate')
        with patch('studio.native_shell.window.QInputDialog.getText', return_value=('Toolbar name', True)):
            self.w.rename_action.trigger()
        self.assertEqual(self.w.coordinator.selected_action().display_name, 'Toolbar name')

    def test_documented_connections_have_unique_integration_tests(self):
        import ast
        import json
        matrix = json.loads((ROOT / 'tests/fixtures/contracts/studio-connections.json').read_text())
        names = set()
        for item in matrix:
            if item['status'] != 'IMPLEMENTIERT': continue
            self.assertNotIn(item['test'], names)
            names.add(item['test'])
            file, function = item['test'].split('::')
            tree = ast.parse((ROOT / file).read_text(encoding='utf-8'))
            self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == function for n in ast.walk(tree)), item['id'])
            self.assertIn(item['id'], (ROOT / 'docs/architecture/studio/04-Verbindungsregister.md').read_text(encoding='utf-8'))
            for code in item['code']:
                self.assertTrue((ROOT / code).is_file())
        self.assertEqual(len(names), 37)

    def test_f1_preserves_concrete_parameter_facts(self):
        c = self.w.coordinator
        c.select_offer(self.w.catalog.offer_for('action.command', 'second'))
        self.w.catalog.catalog_tree.setFocus()
        self.w.request_help()
        self.assertIn(('actionParameter', 'second'), c.help.current().facts)

    def test_dialog_revision_becomes_stale_without_overwrite(self):
        self.temporary_native()
        c = self.w.coordinator
        c.select_node('action', 'action.command')
        def concurrent_change(*args, **kwargs):
            c.rename_action('action.command', 'Newer revision', base_revision=c.session.revision)
            return 'Stale dialog value', True
        with patch('studio.native_shell.window.QInputDialog.getText', side_effect=concurrent_change):
            self.w.rename_action.trigger()
        self.assertEqual(c.selected_action().display_name, 'Newer revision')
        self.assertEqual(len(self.w.problems.diagnostics('edit')), 1)

    def test_v26_open_dialog_route(self):
        with patch('studio.native_shell.window.QFileDialog.getOpenFileName', return_value=(str(ROOT / 'examples/project_logitech_native_v1.json'), '')):
            self.w.open_action.trigger()
        self.assertEqual(len(self.w.coordinator.session.native_project().actions), 4)

    def test_v17_explicit_entry_legacy_default(self):
        with patch.object(QApplication, 'exec', return_value=0), patch('studio.app.StudioWindow') as legacy:
            self.assertEqual(main([]), 0)
            legacy.assert_called_once_with(None)
        with patch.object(QApplication, 'exec', return_value=0), patch('studio.native_shell.NativeStudioShell') as native:
            self.assertEqual(main(['--native']), 0)
            native.assert_called_once_with(None, workflow=True)  # AP-GUIDE-001: Programmeinstieg startet geführt

    def test_legacy_edit_save_reload(self):
        from library.templates import callback_project
        import json
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'legacy.json'
            path.write_text(json.dumps(callback_project()), encoding='utf-8')
            window = StudioWindow(path)
            try:
                window.document.mutate(lambda raw: raw['project'].__setitem__('display_name', 'Legacy still works'))
                window.refresh()
                self.assertTrue(window.save_project())
                window.document.load(path)
                self.assertEqual(window.document.raw['project']['display_name'], 'Legacy still works')
                self.assertEqual(window.document.raw['schema_version'], '0.1-draft')
            finally:
                window.close()
                window.deleteLater()


if __name__ == '__main__': unittest.main()
