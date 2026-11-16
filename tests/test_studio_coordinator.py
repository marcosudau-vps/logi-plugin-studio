from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from studio.native_shell import NativeStudioShell
from studio.keypad_contract import ActionOffer
from studio.native_session import NativeSessionError, NativeRevisionConflict, NativeDiskConflict, NativeProjectSession
from core.errors import Diagnostic


class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        self.path.write_text(json.dumps(self.raw), encoding="utf-8")
        self.w = NativeStudioShell(self.path)
        self.c = self.w.coordinator
        self.w.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        # Tests may intentionally leave a dirty session. Teardown is explicit discard.
        self.w.hide()
        self.w.deleteLater()
        self.app.processEvents()

    def click_node(self, kind, identity):
        tree = self.w.explorer.tree
        iterator = __import__('PySide6.QtWidgets', fromlist=['QTreeWidgetItemIterator']).QTreeWidgetItemIterator(tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == (kind, identity):
                tree.scrollToItem(item)
                QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center())
                self.app.processEvents()
                return
            iterator += 1
        self.fail("native entity missing")

    def click_offer(self, identity, parameter=None):
        tree = self.w.catalog.catalog_tree
        item = self.w.catalog.item_for(identity, parameter)
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        tree.scrollToItem(item)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center())
        self.app.processEvents()

    def test_v01_session_to_explorer(self):
        tree = self.w.explorer.tree
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        keys = []
        it = QTreeWidgetItemIterator(tree)
        while it.value():
            key = it.value().data(0, Qt.ItemDataRole.UserRole)
            if key: keys.append(key)
            it += 1
        self.assertEqual(len(keys), 11)
        self.assertEqual(sum(k[0] == 'action' for k in keys), 4)
        self.assertEqual(sum(k[0] == 'folder_entry' for k in keys), 4)
        self.assertIn(('handler', 'handler.main'), keys)
        self.assertIn(('folder', 'folder.main'), keys)
        spy = QSignalSpy(self.w.explorer.nodeSelected)
        self.c.refresh()
        self.assertEqual(spy.count(), 0)

    def test_v02_session_to_catalog(self):
        self.assertEqual(len({k[0] for k in self.w.catalog.visible_keys()}), 4)
        self.assertEqual(len({a.sdk_type for a in self.c.session.native_project().actions}), 4)
        spy = QSignalSpy(self.w.catalog.actionSelected)
        self.c.refresh()
        self.assertEqual(spy.count(), 0)

    def test_v03_explorer_selection(self):
        spy = QSignalSpy(self.w.catalog.actionSelected)
        self.click_node('action', 'action.command')
        self.assertEqual(self.w.catalog.selected_key(), ('action.command', None))
        self.assertIsNone(self.w.catalog.selected_offer())
        self.assertEqual(spy.count(), 0)
        self.click_node('handler', 'handler.main')
        self.assertIsNone(self.w.catalog.selected_key())

    def test_v04_explorer_activation(self):
        self.click_node('folder_entry', 'placement.command')
        spy = QSignalSpy(self.c.selectionChanged)
        QTest.keyClick(self.w.explorer.tree, Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(self.c.selection, ('folder_entry', 'placement.command'))
        self.assertFalse(self.c.session.dirty)

    def test_v05_catalog_parameter_selection(self):
        spy = QSignalSpy(self.w.explorer.nodeSelected)
        self.click_offer('action.command', 'second')
        self.assertEqual(self.c.selection, ('action', 'action.command'))
        self.assertEqual(self.c.action_parameter, 'second')
        self.assertEqual(spy.count(), 0)
        self.c.select_offer(ActionOffer('action.command', 'bad', 'missing'))
        self.assertEqual(self.c.action_parameter, 'second')

    def test_v06_catalog_edit_request(self):
        self.click_offer('action.adjustment')
        spy = QSignalSpy(self.c.editRequested)
        with patch('studio.native_shell.window.QInputDialog.getText', return_value=('', False)):
            QTest.mouseClick(self.w.catalog.edit_button, Qt.MouseButton.LeftButton)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0), ['action.adjustment'])

    def test_v22_catalog_definition_selection(self):
        self.click_offer('action.multistate')
        self.click_offer('action.command')
        self.assertEqual(self.c.selection, ('action', 'action.command'))
        self.assertIsNone(self.c.action_parameter)

    def test_v23_filters_invalidate_hidden_selection(self):
        self.click_offer('action.command', 'second')
        self.w.explorer.set_filter('not-found')
        self.assertIsNone(self.c.selection)
        self.w.explorer.set_filter('')
        self.click_offer('action.multistate')
        self.w.catalog.set_filter('not-found')
        self.assertIsNone(self.c.selection)

    def test_duplicate_names_keep_native_ids(self):
        proposed = copy.deepcopy(self.raw)
        for a in proposed['actions']: a['display_name'] = 'Same'
        self.path.write_text(json.dumps(proposed), encoding='utf-8')
        self.c.open_project(self.path)
        self.click_node('action', 'action.editor')
        self.assertEqual(self.w.catalog.selected_key(), ('action.editor', None))

    def test_invalid_open_preserves_session(self):
        session = self.c.session
        bad = Path(self.tmp.name) / 'bad.json'
        for content in ('{', '{"schema_version":"0.1-draft"}'):
            bad.write_text(content, encoding='utf-8')
            with self.assertRaises(NativeSessionError): self.c.open_project(bad)
            self.assertIs(self.c.session, session)

    def test_v08_selection_help_context(self):
        self.click_offer('action.command', 'second')
        state = self.c.help.current()
        self.assertEqual(state.resolved_topic_id, 'catalog.parameter')
        self.assertIn(('actionParameter', 'second'), state.facts)

    def test_v09_help_display(self):
        self.click_node('action', 'action.multistate')
        title = self.w.help_widget.findChild(__import__('PySide6.QtWidgets', fromlist=['QTextEdit']).QTextEdit, 'helpTitle')
        self.assertEqual(title.toPlainText(), self.c.help.current().entry.title)

    def test_v10_pin(self):
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        self.click_node('action', 'action.multistate')
        pin = self.w.help_widget.findChild(__import__('PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton, 'helpPin')
        QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
        self.assertTrue(self.c.help.current().pinned)
        self.click_offer('action.command', 'second')
        self.assertEqual(self.c.help.current().resolved_topic_id, 'action.definition')
        QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
        self.assertFalse(self.c.help.current().pinned)

    def test_v11_related_topic(self):
        self.click_node('action', 'action.multistate')
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        from PySide6.QtWidgets import QPushButton
        button = self.w.help_widget.findChild(QPushButton, 'helpRelated.catalog.parameter')
        self.assertIsNotNone(button)
        button.click()
        self.assertEqual(self.c.help.current().resolved_topic_id, 'catalog.parameter')

    def test_v12_diagnostics_sources_and_correlation(self):
        d = Diagnostic('TEST', '/actions/0', 'Source one')
        token, revision = self.c.project_token, self.c.session.revision
        self.assertTrue(self.c.publish_diagnostics('parser', [d], project_token=token, base_revision=revision))
        self.c.publish_diagnostics('io', [Diagnostic('IO', '/', 'Source two')], project_token=token, base_revision=revision)
        self.assertIs(self.w.problems.diagnostics('parser')[0], d)
        self.assertEqual(len(self.w.problems.diagnostics('io')), 1)
        self.assertFalse(self.c.publish_diagnostics('parser', [], project_token='old', base_revision=revision))
        self.assertFalse(self.c.publish_diagnostics('parser', [], project_token=token, base_revision='old'))
        self.assertEqual(len(self.w.problems.diagnostics('parser')), 1)

    def publish_problem(self):
        d = Diagnostic('NATIVE_VALIDATION', '/actions/0', 'No entity mapping')
        self.c.publish_diagnostics('parser', [d], project_token=self.c.project_token, base_revision=self.c.session.revision)
        self.w.tabs.setCurrentWidget(self.w.problems)
        self.app.processEvents()
        table = self.w.problems.problems_table
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(table.model().index(0, 0)).center())
        return d

    def test_v13_problem_selection_help(self):
        self.publish_problem()
        self.assertEqual(self.c.help.current().resolved_topic_id, 'problems.diagnostic')
        self.assertIsNone(self.c.selection)

    def test_v14_problem_activation_no_guessed_navigation(self):
        self.click_node('handler', 'handler.main')
        self.publish_problem()
        QTest.keyClick(self.w.problems.problems_table, Qt.Key.Key_Return)
        self.assertEqual(self.c.selection, ('handler', 'handler.main'))
        self.assertIn('Keine geprüfte', str(self.c.help.current().facts))

    def test_v30_project_switch_resets_context(self):
        d = self.publish_problem()
        self.w.problems.set_filter('old-filter')
        self.c.help.set_pinned(True)
        old_token = self.c.project_token
        self.c.open_project(self.path)
        self.assertNotEqual(old_token, self.c.project_token)
        self.assertFalse(self.c.help.current().pinned)
        self.assertEqual(self.c.help.current().facts, ())
        self.assertEqual(self.w.problems.diagnostics(), [])
        self.assertEqual(self.w.problems.filter_text(), '')
        self.c.diagnostic_activated(d)
        self.assertNotEqual(self.c.help.current().resolved_topic_id, 'problems.diagnostic')

    def test_v15_display_name_exactly_one_commit(self):
        before = self.c.session.snapshot()
        self.click_offer('action.command', 'second')
        with patch.object(self.c.session, 'replace', wraps=self.c.session.replace) as commit:
            with patch('studio.native_shell.window.QInputDialog.getText', return_value=('Renamed', True)):
                self.w.rename_action.trigger()
            commit.assert_called_once()
        expected = copy.deepcopy(before)
        expected['actions'][0]['display_name'] = 'Renamed'
        self.assertEqual(self.c.session.snapshot(), expected)
        self.assertEqual(self.c.session.native_project().actions[0].display_name, 'Renamed')
        self.assertEqual(self.c.action_parameter, 'second')
        self.assertTrue(self.c.session.dirty)
        self.assertEqual(json.loads(self.path.read_text()), before)

    def test_stale_revision_and_missing_entity_fail_closed(self):
        revision = self.c.session.revision
        self.c.rename_action('action.command', 'New', base_revision=revision)
        before = self.c.session.snapshot()
        with self.assertRaises(NativeRevisionConflict):
            self.c.rename_action('action.command', 'Stale', base_revision=revision)
        with self.assertRaises(NativeSessionError):
            self.c.rename_action('lost.id', 'Missing', base_revision=self.c.session.revision)
        self.assertEqual(self.c.session.snapshot(), before)
        self.c.undo()
        self.assertEqual(self.c.session.snapshot(), self.raw)
        self.assertFalse(self.c.session.can_undo)

    def test_invalid_snapshot_parser_rejects_without_commit(self):
        session = self.c.session
        revision = session.revision
        candidates = []
        for mutation in (lambda r: r['actions'][0].__setitem__('handler', 'missing'),
                         lambda r: r['folders'][0]['entries'][0].__setitem__('action', 'missing'),
                         lambda r: r.__setitem__('schema_version', '0.1-draft'),
                         lambda r: r['actions'][0].__setitem__('id', 'lost.id')):
            candidate = copy.deepcopy(self.raw)
            mutation(candidate)
            candidates.append(candidate)
        for candidate in candidates:
            with patch.object(session, 'snapshot', return_value=candidate):
                with self.assertRaises(NativeSessionError):
                    self.c.rename_action('action.command', 'Invalid', base_revision=revision)
            self.assertEqual(session.revision, revision)
            self.assertFalse(session.dirty)
            self.assertFalse(session.can_undo)
        with self.assertRaises(NativeSessionError):
            self.c.rename_action('action.command', '', base_revision=revision)

    def test_external_bytes_save_conflict(self):
        self.c.rename_action('action.command', 'Changed', base_revision=self.c.session.revision)
        external = self.path.read_bytes() + b'\n'
        self.path.write_bytes(external)
        with self.assertRaises(NativeDiskConflict): self.c.save()
        self.assertEqual(self.path.read_bytes(), external)
        self.assertTrue(self.c.session.dirty)

    def test_direct_dirty_open_requires_explicit_discard(self):
        self.c.rename_action('action.command', 'Changed', base_revision=self.c.session.revision)
        session = self.c.session
        with self.assertRaises(NativeSessionError): self.c.open_project(self.path)
        self.assertIs(self.c.session, session)

    def test_v34_catalog_search_invalidates_host(self):
        self.click_offer('action.multistate')
        self.w.catalog.set_filter('missing')
        self.assertIsNone(self.c.selection)
        self.assertTrue(self.w.catalog.new_action_button.isEnabled())

    def test_v35_catalog_type_invalidates_host(self):
        self.click_offer('action.multistate')
        self.w.catalog.set_type_filter('PluginDynamicAdjustment')
        self.assertIsNone(self.c.selection)
        self.assertTrue(self.w.catalog.new_action_button.isEnabled())

    def test_v39_project_switch_clears_problem_sources_and_filters(self):
        self.publish_problem()
        self.w.problems.set_filter('NATIVE')
        self.w.problems.set_severity_filter('ERROR')
        self.c.open_project(self.path)
        self.assertEqual(self.w.problems.sources(), ['native.validation'])
        self.assertEqual(self.w.problems.visible_entries(), [])
        self.assertEqual(self.w.problems.filter_text(), '')
        self.assertEqual(self.w.problems.severity_filter(), 'ALL')

    def test_v40_host_to_explorer_silent(self):
        spy = QSignalSpy(self.w.explorer.nodeSelected)
        self.c.select_node('folder_entry', 'placement.command')
        item = self.w.explorer.tree.currentItem()
        self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole), ('folder_entry', 'placement.command'))
        self.assertEqual(spy.count(), 0)

    def test_v41_host_to_catalog_silent(self):
        spy = QSignalSpy(self.w.catalog.actionSelected)
        self.c.select_node('folder_entry', 'placement.command')
        self.assertEqual(self.w.catalog.selected_key(), ('action.command', None))
        self.assertIsNone(self.w.catalog.selected_offer())
        self.assertEqual(spy.count(), 0)

    def test_v42_explorer_group_clears_host_selection(self):
        self.click_node('action', 'action.command')
        tree = self.w.explorer.tree
        group = tree.topLevelItem(0).child(0)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(group).center())
        self.assertIsNone(self.c.selection)
        self.assertIsNone(self.w.catalog.selected_key())
        self.assertFalse(self.w.rename_action.isEnabled())


if __name__ == '__main__': unittest.main()
