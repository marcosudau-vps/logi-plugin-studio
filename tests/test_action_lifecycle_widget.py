"""Echte Qt-Eingaben und separate Create-/Edit-Formularzustände."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QInputMethodEvent
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit
from studio.native_shell import NativeStudioShell
from studio.native_session import NativeProjectSession, NativeSessionError, NativeRevisionConflict, NativeDiskConflict


class ShellCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'native.json'
        self.original = (ROOT / 'examples/project_logitech_native_v1.json').read_bytes()
        self.path.write_bytes(self.original)
        self.w = NativeStudioShell(self.path)
        self.c = self.w.coordinator
        self.w.show(); self.w.activateWindow(); self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.w.hide(); self.w.deleteLater(); self.app.processEvents()

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def fill(self, section, field, text):
        self.w.tabs.setCurrentWidget(self.w.inspector)
        section = self.w.inspector.sections[section]
        section.set_expanded(True)
        target = section.fields[field].input
        self.w.inspector.scroll.ensureWidgetVisible(target)
        target.setFocus(); self.app.processEvents()
        target.selectAll()
        QTest.keyClick(target, Qt.Key.Key_Backspace)
        if text.isascii():
            QTest.keyClicks(target, text)
        else:
            event = QInputMethodEvent(); event.setCommitString(text)
            QApplication.sendEvent(target, event)
        return target

    def create(self, typ='PluginDynamicCommand', identity='action.created'):
        self.click(self.w.catalog.new_action_button)
        field = self.w.inspector.sections['identity'].fields['sdk_type'].input
        # Native QComboBox-Keyevents statt eines alternativen Erstellungswegs.
        index = field.findText(typ)
        QTest.keyClick(field, Qt.Key.Key_Home)
        for _ in range(index):
            field = self.w.inspector.sections['identity'].fields['sdk_type'].input
            QTest.keyClick(field, Qt.Key.Key_Down)
        self.fill('identity', 'id', identity)
        self.fill('common', 'display_name', 'Erstellte Aktion')
        self.assertTrue(self.w.inspector.creating)

    def decision(self, label, inspect=None):
        seen = []
        def respond():
            dialog = QApplication.activeModalWidget()
            if not isinstance(dialog, QMessageBox):
                seen.append('FEHLENDER DIALOG'); return
            if inspect: inspect(dialog)
            button = next((b for b in dialog.buttons() if b.text() == label), None)
            if button:
                seen.append(label); QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            else:
                seen.append('FEHLENDER BUTTON'); dialog.reject()
        QTimer.singleShot(20, respond)
        return seen

    def commit_create(self, typ='PluginDynamicCommand', identity='action.created'):
        self.create(typ, identity)
        self.click(self.w.inspector.apply_button)
        self.assertFalse(self.w.inspector.creating)
        self.assertEqual(self.c.selection, ('action', identity))
        return self.c.session.snapshot()


class LifecycleWidgetTests(ShellCase):
    def test_create_button_project_activation_after_filter_sort_history(self):
        self.assertTrue(self.w.catalog.new_action_button.isEnabled())
        for operation in (lambda:self.w.catalog.set_filter('missing'),
                          lambda:self.w.catalog.set_type_filter('ActionEditorCommand'),
                          lambda:self.w.catalog.set_group_order('name'), self.c.refresh):
            operation(); self.assertTrue(self.w.catalog.new_action_button.isEnabled())
        empty = NativeStudioShell()
        try:
            self.assertFalse(empty.catalog.new_action_button.isEnabled())
            empty.catalog.set_filter('a')
            self.assertFalse(empty.catalog.new_action_button.isEnabled())
        finally:
            empty.deleteLater(); self.app.processEvents()

    def test_create_id_visible_editable_then_immutable_no_double_apply(self):
        revision = self.c.session.revision
        self.create()
        self.assertFalse(self.w.inspector.sections['identity'].fields['id'].input.isReadOnly())
        self.assertEqual(len(self.c.session.snapshot()['actions']), 4)
        self.assertIsNone(self.w.catalog.item_for('action.created'))
        self.assertEqual(self.c.session.revision, revision)
        self.click(self.w.inspector.apply_button)
        self.assertTrue(self.w.inspector.sections['identity'].fields['id'].input.isReadOnly())
        after = self.c.session.revision
        with patch.object(self.c.session, 'replace', wraps=self.c.session.replace) as replace:
            self.click(self.w.inspector.apply_button); replace.assert_not_called()
        self.assertEqual(self.c.session.revision, after)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_create_field_errors_keep_inputs_and_open_section(self):
        self.create()
        for identity in ('action.command', 'Invalid ID'):
            self.fill('identity', 'id', identity)
            self.assertFalse(self.w.inspector.apply_button.isEnabled())
            self.assertEqual(self.w.inspector.draft.action_id, identity)
            self.assertTrue(self.w.inspector.sections['identity'].toggle.isChecked())
        self.fill('identity','id','action.valid')
        self.fill('common','display_name','')
        self.assertFalse(self.w.inspector.apply_button.isEnabled())
        self.assertIn('/display_name', self.w.inspector.errors.text())
        self.assertFalse(self.c.session.can_undo)

    def test_create_type_common_fields_preserved_special_changes_confirmed(self):
        self.create('PluginMultistateDynamicCommand')
        states = self.w.inspector.sections['states']
        states.forms[0].fields['name'].input.setText('changed')
        selector = self.w.inspector.sections['identity'].fields['sdk_type'].input
        with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Cancel):
            selector.setCurrentText('ActionEditorCommand')
        self.assertEqual(self.w.inspector.draft.snapshot()['states'][0]['name'],'changed')
        with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
            selector.setCurrentText('ActionEditorCommand')
        raw = self.w.inspector.draft.proposed_action()
        self.assertEqual(raw['id'],'action.created')
        self.assertEqual(raw['display_name'],'Erstellte Aktion')
        self.assertNotIn('states', raw)
        self.assertEqual(len(raw['editor_controls']),1)

    def test_create_cancel_and_discard_do_not_commit(self):
        self.c.select_node('action','action.command')
        revision = self.c.session.revision
        self.create()
        self.decision('Abbrechen'); self.click(self.w.catalog.new_action_button)
        self.assertTrue(self.w.inspector.creating)
        self.assertEqual(self.w.inspector.draft.action_id,'action.created')
        self.assertEqual(self.c.selection,('action','action.command'))
        self.click(self.w.inspector.discard_button)
        self.assertFalse(self.w.inspector.creating)
        self.assertEqual(self.c.session.revision,revision)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_referenced_delete_disabled_explains_ids_no_confirmation(self):
        for action in self.c.session.snapshot()['actions']:
            self.c.select_node('action', action['id'])
            self.assertFalse(self.w.inspector.delete_button.isEnabled())
            self.assertIn('folder.main',self.w.inspector.delete_info.text())
            self.assertIn('placement.',self.w.inspector.delete_info.text())
            with patch.object(QMessageBox,'exec') as confirmation:
                self.assertFalse(self.w.delete_selected()); confirmation.assert_not_called()
        self.assertFalse(self.c.session.can_undo)

    def test_folder_entry_is_not_delete_target(self):
        self.c.select_node('folder_entry','placement.command')
        self.assertFalse(self.w.inspector.delete_button.isEnabled())
        self.assertFalse(self.w.delete_selected())
        self.assertFalse(self.c.session.dirty)

    def test_delete_confirmation_identity_default_cancel_no_reused_answer(self):
        self.commit_create()
        before = self.c.session.snapshot(); revision=self.c.session.revision
        observations=[]
        def inspect(dialog):
            observations.append((dialog.defaultButton().text(), dialog.text()))
        seen=self.decision('Abbrechen',inspect)
        self.click(self.w.inspector.delete_button)
        self.assertEqual(seen,['Abbrechen'])
        self.assertEqual(observations[0][0],'Abbrechen')
        self.assertIn('action.created',observations[0][1]);self.assertIn('Erstellte Aktion',observations[0][1])
        self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.c.session.revision,revision)
        self.decision('Aktion löschen');self.click(self.w.inspector.delete_button)
        self.assertIsNone(self.w.catalog.offer_for('action.created'))
        self.assertIsNone(self.w.inspector.draft)

    def test_last_unplaced_action_delete_disabled(self):
        raw=self.c.session.snapshot();raw['actions']=raw['actions'][:1];raw['folders']=[]
        self.w.inspector.accept_applied()
        self.path.write_text(json.dumps(raw),encoding='utf-8')
        self.c.open_project(self.path,discard=True);self.c.select_node('action','action.command')
        self.assertFalse(self.w.inspector.delete_button.isEnabled())
        self.assertIn('letzte Aktion',self.w.inspector.delete_info.text())  # AP-GUIDE-001: Begriffsliste
        self.assertFalse(self.w.delete_selected());self.assertFalse(self.c.session.can_undo)


if __name__ == '__main__':
    unittest.main()
