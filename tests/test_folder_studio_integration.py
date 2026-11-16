"""Actual shell, separate writers, staged lifecycle and Qt user intents."""
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
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from studio.native_shell import NativeStudioShell
from studio.native_session import NativeSessionError
from studio.virtual_folders.binding import extension_path
from studio.virtual_folders.codec import ExtensionStore
from studio.virtual_folders.model import Reference


class FolderStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'native.json'
        self.original = (ROOT / 'examples/project_logitech_native_v1.json').read_bytes()
        self.path.write_bytes(self.original)
        self.other = self.path.with_name('other.json')
        self.other.write_bytes(self.original)
        self.w = NativeStudioShell(self.path)
        self.w.show()
        self.w.activateWindow()
        self.c = self.w.coordinator
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.w.composer.dispose()
        self.w.hide()
        self.w.deleteLater()
        self.app.processEvents()

    def click(self, button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def folder_tab(self):
        self.w.tabs.setCurrentWidget(self.w.composer)
        self.app.processEvents()
        return self.w.composer

    def place(self, action='action.command'):
        f = self.folder_tab()
        index = next(i for i in range(f.action_combo.count())
                     if f.action_combo.itemData(i) == (Reference(f.document.plugin_id, action), None))
        f.action_combo.setCurrentIndex(index)
        self.click(f.add_action_button)
        return f.document.placements[-1]

    def native_dirty(self):
        self.c.rename_action('action.command', 'Changed', base_revision=self.c.session.revision)

    def draft(self):
        self.c.request_edit('action.command')
        field = self.w.inspector.sections['common'].fields['display_name'].input
        field.selectAll()
        QTest.keyClicks(field, 'Keep draft')

    def answer_draft(self, label):
        def answer():
            dialog = QApplication.activeModalWidget()
            next(b for b in dialog.buttons() if b.text() == label).click()
        QTimer.singleShot(20, answer)

    def test_v74_tab_snapshot_create_folder_link_and_multiple_placements(self):
        f = self.folder_tab()
        self.assertGreater(f.action_combo.count(), 4)
        root = f.document.root_id
        self.place()
        with patch.object(QInputDialog, 'getText', return_value=('Child', True)):
            self.click(f.new_button)
        child = f.navigation.folder_id
        self.place()
        with patch.object(f, '_choose_folder', return_value=(True, root)):
            self.click(f.link_button)
        self.assertEqual(len([p for p in f.document.placements if p.kind == 'action']), 2)
        link = f.document.placements[-1]
        f.navigation.open(link.id)
        self.assertEqual(f.navigation.folder_id, root)
        f.navigation.back()
        self.assertEqual(f.navigation.folder_id, child)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.c.session.dirty)
        self.native_dirty()
        self.assertIn('Changed', f.action_combo.itemText(0))

    def test_v75_separate_saves_and_restart(self):
        self.place()
        doc = self.w.composer.document
        self.assertTrue(self.w.save_folders())
        sidecar = extension_path(self.path)
        saved = sidecar.read_bytes()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.native_dirty()
        self.assertTrue(self.w.save_project())
        self.assertEqual(sidecar.read_bytes(), saved)
        self.assertTrue(self.w.open_project(self.path))
        self.assertEqual(self.w.composer.document, doc)
        self.assertFalse(self.w.composer.store.dirty)
        self.assertFalse(self.w.composer.store.can_undo)
        self.assertEqual(self.c.session.snapshot()['actions'][0]['display_name'], 'Changed')

    def test_v76_three_dirty_contexts_cancel_retains_deferred_discards(self):
        self.place()
        self.native_dirty()
        self.draft()
        session, composer, draft = self.c.session, self.w.composer, self.w.inspector.draft
        self.answer_draft('Verwerfen')
        with patch.object(QMessageBox, 'question', side_effect=[QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel]):
            self.assertFalse(self.w.open_project(self.other))
        self.assertIs(self.c.session, session)
        self.assertIs(self.w.composer, composer)
        self.assertIs(self.w.inspector.draft, draft)
        self.assertTrue(session.dirty)
        self.assertTrue(composer.store.dirty)
        self.assertTrue(self.w.inspector.dirty)

    def test_invalid_native_or_extension_precedes_discard(self):
        self.place()
        doc = self.w.composer.document
        extension_path(self.other).write_bytes(b'invalid')
        with patch.object(self.w, 'confirm_unsaved') as confirm:
            self.assertFalse(self.w.open_project(self.other))
            confirm.assert_not_called()
        self.assertIs(self.w.composer.document, doc)
        self.other.write_bytes(b'invalid')
        self.assertFalse(self.w.open_project(self.other))
        self.assertIs(self.w.composer.document, doc)

    def test_cancel_native_then_folder_save_then_switch(self):
        self.place()
        self.native_dirty()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.w.open_project(self.other))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.w.open_project(self.other))
        self.assertTrue(extension_path(self.path).exists())
        self.assertFalse(self.w.composer.document.placements)
        self.assertNotEqual(self.w.composer.document.project_id,
                            ExtensionStore.load(extension_path(self.path), project_id=self.c.prepare_project(self.path)[1].document.project_id,
                                                plugin_id=self.w.composer.document.plugin_id).document.project_id)

    def test_native_save_success_folder_failure_retains_unsaved_folder(self):
        self.place()
        self.native_dirty()
        f, session = self.w.composer, self.c.session
        extension_path(self.path).write_bytes(b'external winner')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.w.open_project(self.other))
        self.assertIs(self.c.session, session)
        self.assertIs(self.w.composer, f)
        self.assertFalse(session.dirty)  # explicitly saved first step
        self.assertTrue(f.store.dirty)
        self.assertEqual(extension_path(self.path).read_bytes(), b'external winner')

    def test_v77_context_history_independent(self):
        self.native_dirty()
        self.place()
        self.w.undo_action.trigger()
        self.assertFalse(self.w.composer.document.placements)
        self.assertTrue(self.c.session.dirty)
        self.w.redo_action.trigger()
        self.w.tabs.setCurrentWidget(self.w.details)
        self.w.undo_action.trigger()
        self.assertFalse(self.c.session.dirty)
        self.assertEqual(len(self.w.composer.document.placements), 1)

    def test_v78_composer_to_inspector_guard(self):
        self.place('action.editor')
        self.draft()
        f = self.folder_tab()
        f.entries.setCurrentRow(0)
        self.answer_draft('Abbrechen')
        self.click(f.edit_action_button)
        self.assertEqual(self.c.selection, ('action', 'action.command'))
        self.assertTrue(self.w.inspector.dirty)
        self.answer_draft('Verwerfen')
        self.click(f.edit_action_button)
        self.assertEqual(self.c.selection, ('action', 'action.editor'))
        self.assertIs(self.w.tabs.currentWidget(), self.w.inspector)

    def test_v79_folder_f1_and_errors_to_problems(self):
        f = self.folder_tab()
        f.new_button.setFocus()
        QTest.keyClick(f.new_button, Qt.Key.Key_F1)
        self.assertEqual(self.c.help.current().resolved_topic_id, 'folders.studio')
        self.folder_tab()
        self.click(f.remove_button)
        self.assertIn('auswählen', f.status.text())
        self.assertEqual(len(self.w.problems.diagnostics('folders')), 1)

    def test_import_export_keep_sidecar_owner(self):
        self.place()
        self.w.save_folders()
        f = self.w.composer
        target = Path(self.tmp.name) / 'copy.vfolders.json'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
            self.click(f.export_button)
        self.assertEqual(f.store.path, extension_path(self.path))
        f._commit(f.document.rename_folder(f.document.root_id, 'Edited'))
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(target), '')), patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            self.click(f.import_button)
        self.assertEqual(f.store.path, extension_path(self.path))
        self.assertNotEqual(f.document.folder(f.document.root_id).name, 'Edited')
        self.assertIs(f.store, self.c.extension_store)

    def test_close_cancel_and_extension_disk_conflict(self):
        self.place()
        self.w.save_folders()
        self.place()
        extension_path(self.path).write_bytes(b'external bytes')
        event = QCloseEvent()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save):
            self.w.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.w.composer.store.dirty)
        self.assertEqual(extension_path(self.path).read_bytes(), b'external bytes')

    def test_modal_stale_snapshot_rejects_commit(self):
        f = self.folder_tab()
        before = f.document
        def answer(*args, **kwargs):
            self.native_dirty()
            return 'Stale folder', True
        with patch.object(QInputDialog, 'getText', side_effect=answer):
            self.click(f.new_button)
        self.assertIs(f.document, before)
        self.assertIn('während', f.status.text())

    def create_native(self, identity='action.new'):
        action = dict(id=identity, sdk_type='PluginDynamicCommand', display_name='New', handler='handler.main')
        self.c.apply_action_create(action, base_revision=self.c.session.revision, project_token=self.c.project_token)
        return identity

    def test_v80_virtual_references_block_delete_and_placement_removal_keeps_definition(self):
        identity = self.create_native()
        p = self.place(identity)
        check = self.c.action_delete_check(identity)
        self.assertFalse(check.allowed)
        self.assertIn(p.id, check.reason)
        before = self.c.session.snapshot()
        with self.assertRaises(NativeSessionError):
            self.c.delete_action(identity, base_revision=self.c.session.revision, project_token=self.c.project_token)
        self.assertEqual(self.c.session.snapshot(), before)
        f = self.w.composer
        f.entries.setCurrentRow(0)
        self.click(f.remove_button)
        self.assertEqual(self.c.session.snapshot(), before)
        self.assertTrue(self.c.action_delete_check(identity).allowed)
        self.c.delete_action(identity, base_revision=self.c.session.revision, project_token=self.c.project_token)
        self.assertNotIn(identity, [a['id'] for a in self.c.session.snapshot()['actions']])

    def test_reference_check_repeated_after_delete_confirmation(self):
        identity = self.create_native()
        # Pre-confirmation check passed; a new reference arrives while dialog is open.
        self.assertTrue(self.c.action_delete_check(identity).allowed)
        self.place(identity)
        with self.assertRaises(NativeSessionError):
            self.c.delete_action(identity, base_revision=self.c.session.revision, project_token=self.c.project_token)

    def test_v81_orphan_reload_diagnosis_save_and_explicit_repair(self):
        identity = self.create_native()
        self.place(identity)
        self.place()
        self.w.save_project()
        self.w.save_folders()
        raw = json.loads(self.path.read_bytes())
        raw['actions'] = [a for a in raw['actions'] if a['id'] != identity]
        self.path.write_text(json.dumps(raw), encoding='utf-8')
        orphan_bytes = extension_path(self.path).read_bytes()
        self.assertTrue(self.w.reload_project())
        f = self.folder_tab()
        self.assertEqual(len(f.document.placements), 2)
        self.assertIn('nicht verfügbar', f.entries.item(0).text())
        self.assertEqual(len(self.w.problems.diagnostics('folders.references')), 1)
        self.assertTrue(self.w.save_folders())
        self.assertEqual(extension_path(self.path).read_bytes(), orphan_bytes)
        native_bytes = self.path.read_bytes()
        f.entries.setCurrentRow(0)
        self.click(f.remove_button)
        self.assertEqual(len(f.document.placements), 1)
        self.assertFalse(self.w.problems.diagnostics('folders.references'))
        self.assertTrue(self.w.save_folders())
        self.assertTrue(self.w.reload_project())
        self.assertEqual(self.path.read_bytes(), native_bytes)
        self.assertEqual(len(self.w.composer.document.placements), 1)

    def test_orphan_import_keeps_reference_and_sidecar_identity(self):
        f = self.folder_tab()
        doc, identity = f.document.add_action(f.document.root_id, Reference(f.document.plugin_id, 'action.missing'))
        incoming = self.path.with_name('incoming.vfolders.json')
        ExtensionStore(doc).export(incoming)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(incoming), '')):
            self.click(f.import_button)
        self.assertEqual(f.document.placements[0].id, identity)
        self.assertIs(f.store, self.c.extension_store)
        self.assertEqual(len(self.w.problems.diagnostics('folders.references')), 1)

    def test_v82_history_preflight_and_independent_folder_undo(self):
        identity = self.create_native()
        self.place(identity)
        native_revision = self.c.session.revision
        self.w.tabs.setCurrentWidget(self.w.details)
        self.assertFalse(self.w.undo_project())
        self.assertEqual(self.c.session.revision, native_revision)
        f = self.folder_tab()
        self.w.undo_action.trigger()  # remove placement through extension history
        self.assertFalse(f.document.placements)
        self.w.tabs.setCurrentWidget(self.w.details)
        self.w.undo_action.trigger()  # creation is now safe to undo
        self.assertNotIn(identity, [a['id'] for a in self.c.session.snapshot()['actions']])
        self.folder_tab()
        self.w.redo_action.trigger()  # an unavailable reference is preserved
        self.assertEqual(len(f.document.placements), 1)
        self.assertEqual(len(self.w.problems.diagnostics('folders.references')), 1)
        self.w.tabs.setCurrentWidget(self.w.details)
        self.w.redo_action.trigger()  # restore definition
        self.assertFalse(self.w.problems.diagnostics('folders.references'))

    def test_redo_delete_cannot_remove_newly_referenced_action(self):
        identity = self.create_native()
        self.c.delete_action(identity, base_revision=self.c.session.revision, project_token=self.c.project_token)
        self.c.undo()
        self.place(identity)
        revision = self.c.session.revision
        with self.assertRaises(NativeSessionError):
            self.c.redo()
        self.assertEqual(self.c.session.revision, revision)
        self.assertTrue(self.c.session.can_redo)

    def test_external_offline_references_preserved_save_reload(self):
        f = self.folder_tab()
        doc, action = f.document.add_action(f.document.root_id, Reference('peer.plugin', 'action.remote'))
        doc, link = doc.add_link(doc.root_id, Reference('peer.plugin', 'folder.remote'))
        f._commit(doc)
        self.w.save_folders()
        self.w.reload_project()
        f = self.folder_tab()
        self.assertEqual({p.id for p in f.document.placements}, {action, link})
        self.assertTrue(all('nicht verfügbar' in f.entries.item(i).text() for i in range(f.entries.count())))
        self.assertFalse(self.w.problems.diagnostics('folders.references'))

    def test_foreign_project_import_cannot_rebind_implicitly(self):
        self.place()
        f = self.w.composer
        from dataclasses import replace
        doc = replace(f.document, project_id='project.foreign')
        incoming = self.path.with_name('foreign.vfolders.json')
        ExtensionStore(doc).export(incoming)
        before = f.document
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(incoming), '')):
            self.click(f.import_button)
        self.assertIs(f.document, before)
        self.assertIn('Projektidentität', f.status.text())

    def test_disk_changes_block_folder_mutation_and_history(self):
        self.place()
        self.w.save_folders()
        self.native_dirty()
        self.path.write_bytes(self.original + b'\n')
        f = self.folder_tab()
        before = f.document
        self.click(f.add_action_button)
        self.assertIs(f.document, before)
        self.click(f.undo_button)
        self.assertIs(f.document, before)
        self.assertIn('extern verändert', f.status.text())

    def test_direct_stale_native_revision_rejects_folder_commit(self):
        f = self.folder_tab()
        before = f.document
        raw = self.c.session.snapshot()
        raw['actions'][0]['display_name'] = 'Direct owner mutation'
        self.c.session.replace(raw, base_revision=self.c.session.revision)
        self.click(f.add_action_button)
        self.assertIs(f.document, before)
        self.assertIn('Revision', f.status.text())

    def test_extension_revision_rejects_modal_undo_aba(self):
        f = self.folder_tab()
        before, revision = f.document, f.store.revision
        def answer(*args, **kwargs):
            f._commit(f.document.rename_folder(f.document.root_id, 'Temporary'))
            f.history(False)
            self.assertIs(f.document, before)
            return 'Old dialog', True
        with patch.object(QInputDialog, 'getText', side_effect=answer):
            self.click(f.new_button)
        self.assertIs(f.document, before)
        self.assertNotEqual(f.store.revision, revision)
        self.assertIn('während', f.status.text())

    def test_folder_dialog_f1_routes_to_folder_help(self):
        f = self.folder_tab()
        observed = []
        def cancel():
            d = QApplication.activeModalWidget()
            self.assertIsInstance(d, QInputDialog)
            observed.append(self.w.help_bindings.context_for(d).topic_id)
            d.reject()
        QTimer.singleShot(20, cancel)
        self.click(f.new_button)
        self.assertEqual(observed, ['folders.studio'])

    def test_project_changed_during_folder_dialog_rejects_old_intent(self):
        f = self.folder_tab()
        before = f.document
        def answer(*args, **kwargs):
            self.c.open_project(self.other, discard=True)
            return 'Old project folder', True
        with patch.object(QInputDialog, 'getText', side_effect=answer):
            self.click(f.new_button)
        self.assertIs(f.document, before)
        self.assertIsNot(self.w.composer, f)
        self.assertEqual(len(self.w.composer.document.folders), 1)
        self.assertFalse(self.w.composer.store.dirty)

    def test_candidate_invalidated_after_discard_keeps_all_old_drafts(self):
        self.place()
        self.native_dirty()
        self.draft()
        session, f, draft = self.c.session, self.w.composer, self.w.inspector.draft
        answers = []
        def answer(*args, **kwargs):
            answers.append(True)
            if len(answers) == 2:
                extension_path(self.other).write_bytes(b'changed while modal')
            return QMessageBox.StandardButton.Discard
        self.answer_draft('Verwerfen')
        with patch.object(QMessageBox, 'question', side_effect=answer):
            self.assertFalse(self.w.open_project(self.other))
        self.assertEqual(len(answers), 2)
        self.assertIs(self.c.session, session)
        self.assertIs(self.w.composer, f)
        self.assertIs(self.w.inspector.draft, draft)
        self.assertTrue(session.dirty and f.store.dirty and self.w.inspector.dirty)
