"""Real Qt clicks and modal input, offscreen by default, Windows when requested."""
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
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLineEdit, QMessageBox
from studio.virtual_folders import FolderError, Reference
from studio.virtual_folders.codec import ExtensionStore
from studio.virtual_folders.demo import ComposerWindow
from studio.virtual_folders.providers import DisplayData


class ComposerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'native.json'
        self.original = (ROOT / 'examples/project_logitech_native_v1.json').read_bytes()
        self.source.write_bytes(self.original)
        self.window = ComposerWindow(self.source)
        self.w = self.window.composer
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)
        self.b = next(f.id for f in self.w.document.folders if f.name == 'B')
        self.leaf = next(f.id for f in self.w.document.folders if f.name == 'A_01_01_02')
        self.w.select_folder(self.b)

    def dispose(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(self.window.session.dirty)
        self.window.composer.dispose()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def click(self, button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def select_entry(self, identity):
        for i in range(self.w.entries.count()):
            if self.w.entries.item(i).data(Qt.ItemDataRole.UserRole) == identity:
                self.w.entries.setCurrentRow(i)
                return
        self.fail('Placement nicht sichtbar: ' + identity)

    def choose_folder(self, identity):
        if identity is None:
            return patch.object(QInputDialog, 'getItem', return_value=('Autoren-Root (kein Parent)', True))
        f = self.w.document.folder(identity)
        return patch.object(QInputDialog, 'getItem', return_value=(f'{f.name} · {f.id}', True))

    def test_real_modal_new_folder_rename_copy_move_and_link_share_identity(self):
        observations = []
        def enter_name(value):
            def answer():
                dialog = QApplication.activeModalWidget()
                if not isinstance(dialog, QInputDialog):
                    observations.append('Missing input dialog')
                    return
                observations.append(dialog.windowTitle())
                target = dialog.findChild(QLineEdit)
                target.setFocus()
                target.selectAll()
                QTest.keyClicks(target, value)
                QTest.keyClick(target, Qt.Key.Key_Return)
            QTimer.singleShot(30, answer)
        enter_name('Child')
        self.click(self.w.new_button)
        child = self.w.navigation.folder_id
        self.assertEqual(self.w.document.folder(child).name, 'Child')
        self.assertEqual(self.w.document.folder(child).parent_id, self.b)
        enter_name('Renamed')
        self.click(self.w.rename_button)
        self.assertEqual(self.w.document.folder(child).name, 'Renamed')
        with self.choose_folder(None):
            self.click(self.w.copy_button)
        clone = self.w.navigation.folder_id
        self.assertNotEqual(child, clone)
        self.assertIsNone(self.w.document.folder(clone).parent_id)
        with self.choose_folder(self.b):
            self.click(self.w.move_button)
        self.assertEqual(self.w.navigation.folder_id, clone)
        self.assertEqual(self.w.document.folder(clone).parent_id, self.b)
        self.w.select_folder(self.b)
        with self.choose_folder(child):
            self.click(self.w.link_button)
        self.assertEqual(sum(p.target.resource_id == child for p in self.w.document.entries(self.b)), 2)
        self.assertEqual(len(observations), 2)

    def test_link_open_back_page_switch_real_buttons(self):
        link = next(p for p in self.w.document.entries(self.b) if p.kind == 'link')
        self.select_entry(link.id)
        self.click(self.w.open_button)
        self.assertEqual(self.w.navigation.folder_id, self.leaf)
        self.assertEqual(self.w.navigation.stack[0].placement_id, link.id)
        self.click(self.w.back_button)
        self.assertEqual(self.w.navigation.folder_id, self.b)
        self.click(self.w.next_button)
        self.assertEqual(self.w.navigation.stack, [])
        self.assertTrue(any('nicht verfügbar' in self.w.entries.item(i).text() for i in range(self.w.entries.count())))
        self.click(self.w.previous_button)
        self.assertEqual(self.w.navigation.page_id, self.w.document.folder(self.b).pages[0].id)

    def test_remove_link_keeps_target_and_second_link(self):
        links = [p for p in self.w.document.entries(self.b) if p.kind == 'link']
        self.select_entry(links[0].id)
        self.click(self.w.remove_button)
        self.assertEqual(self.w.document.folder(self.leaf).id, self.leaf)
        self.assertEqual(self.w.document.placement(links[1].id).target.resource_id, self.leaf)
        self.assertNotIn(links[0].id, {p.id for p in self.w.document.placements})

    def test_add_native_action_reorder_remove_and_parameter_identity(self):
        self.assertGreater(self.w.action_combo.count(), 4)
        idx = next(i for i in range(self.w.action_combo.count()) if self.w.action_combo.itemData(i)[1] == 'first')
        self.w.action_combo.setCurrentIndex(idx)
        before = self.window.session.snapshot()
        self.click(self.w.add_action_button)
        p = self.w.document.entries(self.b, self.w.navigation.page_id)[-1]
        self.assertEqual(p.target.resource_id, 'action.command')
        self.assertEqual(p.action_parameter, 'first')
        self.select_entry(p.id)
        self.click(self.w.up_button)
        self.assertEqual(self.w.document.placement(p.id).position, p.position - 1)
        self.click(self.w.down_button)
        self.assertEqual(self.w.document.placement(p.id).position, p.position)
        self.click(self.w.remove_button)
        self.assertEqual(self.window.session.snapshot(), before)

    def test_page_modes_auto_explicit_and_cancel_manual_add_rename_reorder_remove(self):
        with patch.object(QInputDialog, 'getInt', return_value=(2, False)):
            self.w.mode_combo.setCurrentIndex(self.w.mode_combo.findData('auto'))
        self.assertEqual(self.w.document.folder(self.b).mode, 'manual')
        with patch.object(QInputDialog, 'getInt', return_value=(2, True)):
            self.w.mode_combo.setCurrentIndex(self.w.mode_combo.findData('auto'))
        self.assertEqual(len(self.w.document.folder(self.b).pages), 3)
        self.assertEqual(self.w.document.folder(self.b).capability.slots, 2)
        self.w.mode_combo.setCurrentIndex(self.w.mode_combo.findData('single'))
        self.assertEqual(len(self.w.document.folder(self.b).pages), 1)
        self.w.mode_combo.setCurrentIndex(self.w.mode_combo.findData('manual'))
        with patch.object(QInputDialog, 'getText', return_value=('Neue Seite', True)):
            self.click(self.w.add_page_button)
        page = self.w.navigation.page_id
        with patch.object(QInputDialog, 'getText', return_value=('Umbenannt', True)):
            self.click(self.w.rename_page_button)
        self.click(self.w.page_left_button)
        self.assertEqual(self.w.document.folder(self.b).pages[0].id, page)
        self.click(self.w.page_right_button)
        self.click(self.w.delete_page_button)
        self.assertNotIn(page, {p.id for p in self.w.document.folder(self.b).pages})
        self.assertEqual(self.w.navigation.stack, [])

    def test_entry_move_page_and_delete_nonempty_explained(self):
        p = next(p for p in self.w.document.entries(self.b) if p.kind == 'action')
        self.select_entry(p.id)
        f = self.w.document.folder(self.b)
        dest_page = f.pages[1]
        replies = [(f'{f.name} · {f.id}', True), (f'{dest_page.name} · {dest_page.id}', True)]
        with patch.object(QInputDialog, 'getItem', side_effect=replies):
            self.click(self.w.move_entry_button)
        self.assertEqual(self.w.document.placement(p.id).page_id, dest_page.id)
        self.click(self.w.next_button)
        self.click(self.w.delete_page_button)
        self.assertIn('leere', self.w.status.text())
        self.assertIn(dest_page.id, {p.id for p in self.w.document.folder(self.b).pages})

    def test_defensive_delete_root_children_links_and_valid_empty_folder(self):
        self.w.select_folder(self.w.document.root_id)
        self.click(self.w.delete_button)
        self.assertIn('Plugin-Root', self.w.status.text())
        self.w.select_folder(self.leaf)
        self.click(self.w.delete_button)
        self.assertIn('verlinkt', self.w.status.text())
        with patch.object(QInputDialog, 'getText', return_value=('Empty', True)):
            self.click(self.w.new_button)
        identity = self.w.navigation.folder_id
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.click(self.w.delete_button)
        self.assertEqual(self.w.document.folder(identity).name, 'Empty')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.click(self.w.delete_button)
        self.assertNotIn(identity, {f.id for f in self.w.document.folders})

    def test_external_reference_offline_push_visible_across_pages_no_native_mutation(self):
        with patch.object(QInputDialog, 'getText', return_value=('peer::action.remote', True)):
            self.click(self.w.external_action_button)
        p = self.w.document.entries(self.b, self.w.navigation.page_id)[-1]
        self.assertIn('nicht verfügbar', self.w.entry_text(p))
        self.w.providers.push((DisplayData(p.target, 'action', 'Remote online', True),))
        self.app.processEvents()
        self.assertIn('Remote online', self.w.entry_text(p))
        self.assertNotIn('nicht verfügbar', self.w.entry_text(p))
        self.click(self.w.next_button)  # subscription remains although placement is hidden
        self.w.providers.offline('peer')
        self.app.processEvents()
        self.click(self.w.previous_button)
        self.assertIn('nicht verfügbar', self.w.entry_text(p))
        self.assertTrue(any(p.target in refs for refs, _ in self.w.providers._listeners))
        self.select_entry(p.id)
        self.click(self.w.open_button)
        self.assertIn('nicht verfügbar', self.w.status.text())

    def test_external_folder_link_and_bad_reference_error(self):
        for text in ('bad', 'peer::folder.remote'):
            with patch.object(QInputDialog, 'getText', return_value=(text, True)):
                self.click(self.w.external_link_button)
            if text == 'bad':
                self.assertIn('Fehler', self.w.status.text())
        p = self.w.document.entries(self.b, self.w.navigation.page_id)[-1]
        self.select_entry(p.id)
        self.click(self.w.open_button)
        self.assertIn('Externer Ordner nicht verfügbar', self.w.status.text())
        self.assertEqual(self.w.navigation.stack, [])

    def test_export_import_save_history_and_conflict_real_buttons(self):
        path = Path(self.tmp.name) / 'composer.vfolders.json'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
            self.click(self.w.export_button)
        saved = self.w.document
        self.click(self.w.add_action_button)
        changed = self.w.document
        self.click(self.w.undo_button)
        self.assertEqual(self.w.document, saved)
        self.click(self.w.redo_button)
        self.assertEqual(self.w.document, changed)
        self.click(self.w.save_button)
        self.assertFalse(self.w.store.dirty)
        fresh = ExtensionStore.load(path, project_id=saved.project_id, plugin_id=saved.plugin_id)
        self.assertEqual(fresh.document, changed)
        self.click(self.w.add_action_button)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')), patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            self.click(self.w.import_button)
        self.assertEqual(self.w.document, changed)
        path.write_bytes(b'EXTERNAL')
        self.click(self.w.add_action_button)
        self.click(self.w.save_button)
        self.assertIn('Disk-Conflict', self.w.status.text())
        self.assertEqual(path.read_bytes(), b'EXTERNAL')
        self.assertTrue(self.w.store.dirty)

    def test_invalid_import_and_export_existing_keep_draft(self):
        path = Path(self.tmp.name) / 'broken.vfolders.json'
        path.write_bytes(b'invalid')
        self.click(self.w.add_action_button)
        before = self.w.document
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
            self.click(self.w.import_button)
        self.assertIs(self.w.document, before)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
            self.click(self.w.export_button)
        self.assertEqual(path.read_bytes(), b'invalid')
        self.assertTrue(self.w.store.dirty)

    def test_v71_session_snapshot_only_no_native_writes(self):
        before = self.window.session.snapshot()
        for _ in range(3):
            self.click(self.w.add_action_button)
        self.assertEqual(self.window.session.snapshot(), before)
        self.assertFalse(self.window.session.can_undo)
        updated = self.window.session.snapshot()
        updated['actions'][0]['display_name'] = 'Snapshot Update'
        self.w.set_native_snapshot(updated)
        self.assertIn('Snapshot Update', self.w.action_combo.itemText(0))
        self.assertEqual(self.window.session.snapshot(), before)

    def test_v72_project_change_cancel_preserves_draft_and_failed_load_no_loss(self):
        self.click(self.w.add_action_button)
        before, store = self.w.document, self.w.store
        other = Path(self.tmp.name) / 'other.json'
        raw = json.loads(self.original)
        raw['plugin']['id'] = 'other.plugin'
        other.write_text(json.dumps(raw), encoding='utf-8')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.open_project(other))
        self.assertIs(self.window.composer, self.w)
        self.assertIs(self.w.document, before)
        self.assertIs(self.w.store, store)
        with self.assertRaises(ValueError):
            self.window.open_project(Path(self.tmp.name) / 'missing.json')
        self.assertIs(self.w.document, before)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.open_project(other))
        self.assertEqual(self.window.composer.document.plugin_id, 'other.plugin')
        self.assertNotEqual(self.window.composer.document.project_id, before.project_id)
        self.assertFalse(self.window.composer.store.can_undo)

    def test_v73_close_cancel_discard_save_and_export_cancel_protect_draft(self):
        self.click(self.w.add_action_button)
        for choice, expected in ((QMessageBox.StandardButton.Cancel, False), (QMessageBox.StandardButton.Discard, True)):
            event = QCloseEvent()
            with patch.object(QMessageBox, 'question', return_value=choice):
                self.window.closeEvent(event)
            self.assertEqual(event.isAccepted(), expected)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
        path = Path(self.tmp.name) / 'saved.vfolders.json'
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
        self.assertTrue(path.is_file())

    def test_modal_concurrent_change_is_rejected_without_losing_other_commit(self):
        before = self.w.document
        def rename_during_input(*args, **kwargs):
            self.w.store.commit(self.w.document.rename_folder(self.b, 'Parallel geändert'))
            return 'Stale Eingabe', True
        with patch.object(QInputDialog, 'getText', side_effect=rename_during_input):
            self.click(self.w.rename_button)
        self.assertEqual(self.w.document.folder(self.b).name, 'Parallel geändert')
        self.assertIn('während der Eingabe geändert', self.w.status.text())
        self.assertEqual(len(self.w.store._undo), 1)
        self.assertNotEqual(self.w.document, before)

    def test_tree_select_link_and_cycle_count_bounded(self):
        expected = len(self.w.document.folders) + sum(p.kind == 'link' for p in self.w.document.placements)
        def count(item):
            return 1 + sum(count(item.child(i)) for i in range(item.childCount()))
        self.assertEqual(sum(count(self.w.tree.topLevelItem(i)) for i in range(self.w.tree.topLevelItemCount())), expected)
        # Actual tree click on a B link selects the placement before explicit open.
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        iterator = QTreeWidgetItemIterator(self.w.tree)
        while iterator.value():
            item = iterator.value()
            kind, identity = item.data(0, Qt.ItemDataRole.UserRole)
            if kind == 'link' and self.w.document.placement(identity).folder_id == self.b:
                self.w.tree.scrollToItem(item)
                QTest.mouseClick(self.w.tree.viewport(), Qt.MouseButton.LeftButton, pos=self.w.tree.visualItemRect(item).center())
                self.app.processEvents()
                break
            iterator += 1
        self.assertEqual(self.w.navigation.folder_id, self.b)
        self.click(self.w.open_button)
        self.assertEqual(self.w.navigation.folder_id, self.leaf)

    def test_new_root_empty_state_set_plugin_entry_home_and_cycle_error(self):
        previous = self.w.document.root_id
        with patch.object(QInputDialog, 'getText', return_value=('Neuer Root', True)):
            self.click(self.w.root_button)
        root = self.w.navigation.folder_id
        self.assertIsNone(self.w.document.folder(root).parent_id)
        self.assertTrue(self.w.empty_label.isVisible())
        self.click(self.w.set_root_button)
        self.assertEqual(self.w.document.root_id, root)
        self.w.select_folder(previous)
        self.click(self.w.home_button)
        self.assertEqual(self.w.navigation.folder_id, root)
        self.w.select_folder(self.leaf)
        with self.choose_folder(self.leaf):
            self.click(self.w.move_button)
        self.assertIn('Zyklus', self.w.status.text())

    def test_import_foreign_project_or_missing_local_action_preserves_draft(self):
        path = Path(self.tmp.name) / 'invalid-target.vfolders.json'
        self.click(self.w.add_action_button)
        before = self.w.document
        bad, _ = before.add_action(self.b, Reference(before.plugin_id, 'action.missing'))
        ExtensionStore(bad).export(path)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
            self.click(self.w.import_button)
        self.assertIn('SDK-Actionziele fehlen', self.w.status.text())
        self.assertIs(self.w.document, before)
        data = json.loads(path.read_bytes())
        data['project_id'] = 'project.other'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
            self.click(self.w.import_button)
        self.assertIn('Projektidentität', self.w.status.text())
        self.assertIs(self.w.document, before)


if __name__ == '__main__':
    unittest.main()
