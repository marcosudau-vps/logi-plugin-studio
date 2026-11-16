"""AP-HELP-001: real Qt events against the composed native shell, no SDK writes."""
from __future__ import annotations

import ast
import hashlib
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

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QFocusEvent, QHelpEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QInputDialog,
                               QLineEdit, QMessageBox, QPushButton, QTextEdit,
                               QToolBar, QToolButton, QTreeWidgetItemIterator)
from core.errors import Diagnostic
from studio.context_help import HelpContext, HelpRegistry, load_help_entries
from studio.native_shell import NativeStudioShell
from studio.native_shell.help_bindings import (CONTRIBUTIONS, CONTROL_BINDINGS,
                                               RESOURCES, register_topics)


class NativeHelpCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'native.json'
        self.path.write_bytes((ROOT / 'examples/project_logitech_native_v1.json').read_bytes())
        self.original = self.path.read_bytes()
        self.w = NativeStudioShell(self.path)
        self.c = self.w.coordinator
        self.w.show()
        self.w.activateWindow()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.w.hide()
        self.w.deleteLater()
        self.app.processEvents()

    def state(self, topic=None):
        state = self.c.help.current()
        if topic:
            self.assertEqual(state.resolved_topic_id, topic)
        return state

    def focus(self, widget, topic):
        self.w.activateWindow()
        self.app.processEvents()
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        self.assertTrue(widget.hasFocus(), widget.objectName())
        return self.state(topic)

    def tooltip(self, widget, topic):
        event = QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), widget.mapToGlobal(QPoint(2, 2)))
        QApplication.sendEvent(widget, event)
        return self.state(topic)

    def click_item(self, tree, item):
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        tree.scrollToItem(item)
        self.app.processEvents()
        rect = tree.visualItemRect(item)
        self.assertFalse(rect.isEmpty())
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.app.processEvents()

    def node(self, kind, identity):
        it = QTreeWidgetItemIterator(self.w.explorer.tree)
        while it.value():
            item = it.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == (kind, identity):
                self.click_item(self.w.explorer.tree, item)
                return
            it += 1
        self.fail((kind, identity))

    def offer(self, identity='action.command', parameter='second'):
        self.click_item(self.w.catalog.catalog_tree, self.w.catalog.item_for(identity, parameter))

    def publish(self):
        items = [Diagnostic('HELP_ERROR', '/private/token/location', 'secret=DO_NOT_ECHO <script>', 'error'),
                 Diagnostic('HELP_WARNING', '/', 'Eine zweite Meldung', 'warning')]
        self.c.publish_diagnostics('lab', items, project_token=self.c.project_token,
                                   base_revision=self.c.session.revision)
        self.w.tabs.setCurrentWidget(self.w.problems)
        self.app.processEvents()
        return items

    def diagnostic(self):
        items = self.publish()
        table = self.w.problems.problems_table
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         pos=table.visualRect(table.model().index(0, 0)).center())
        self.app.processEvents()
        return items

    def toolbar(self, key, topic):
        button = self.w.findChild(QToolButton, 'nativeHelpToolbar.' + key)
        self.assertIsNotNone(button)
        if button.isEnabled():
            self.focus(button, topic)
            self.c.help.set_pinned(True)
            QTest.keyClick(button, Qt.Key.Key_F1)
            self.app.processEvents()
            self.state(topic)
        else:
            self.tooltip(button, topic)
            self.assertIn(('Verfügbar', 'False'), self.state().facts)

    def test_v43_source_registration(self):
        registry = HelpRegistry()
        register_topics(registry)
        defaults = load_help_entries(RESOURCES / 'default_topics.de.json')
        self.assertEqual(len(defaults), 16)
        self.assertEqual(len(registry.topics()), 66)
        for entry in defaults:
            self.assertEqual(registry.get(entry.topic_id), entry)
        all_ids = []
        for source, filename in CONTRIBUTIONS.items():
            entries = load_help_entries(RESOURCES / filename)
            all_ids.extend(e.topic_id for e in entries)
            own = HelpRegistry()
            register_topics(own)
            own.unregister_source(source)
            for entry in entries:
                self.assertIsNone(own.get(entry.topic_id))
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for topic in registry.topics():
            entry = registry.get(topic)
            for related in entry.related_topics:
                self.assertIsNotNone(registry.get(related), (topic, related))
        for source, expected in [('catalog', 'catalog.parameter'), ('problems', 'problems.diagnostic'),
                                 ('native_shell', 'studio.help'), ('prepared', 'symbol.ict')]:
            own = HelpRegistry()
            register_topics(own)
            own.unregister_source(source)
            self.assertIsNone(own.get(expected))

    def test_v44_focus_routing(self):
        self.c.select_node('handler', 'handler.main')
        self.focus(self.w.catalog.type_combo, 'catalog.type_filter')
        self.focus(self.w.explorer.search_edit, 'explorer.search')
        self.focus(self.w.catalog.search_edit, 'catalog.search')
        self.assertEqual(len(self.w.findChildren(QTextEdit, 'helpTitle')), 1)

    def test_v45_filter_facts(self):
        self.focus(self.w.catalog.search_edit, 'catalog.search')
        QTest.keyClicks(self.w.catalog.search_edit, 'missing')
        self.assertIn(('Suchlänge', '7'), self.state('catalog.search').facts)
        self.assertIn(('Sichtbare Angebote', '0'), self.state().facts)
        self.assertNotIn('missing', str(self.state().facts))

    def test_v46_explicit_focus_help(self):
        self.offer()
        self.c.help.set_pinned(True)
        self.w.catalog.type_combo.setFocus()
        self.app.processEvents()
        self.state('catalog.parameter')
        QTest.keyClick(self.w.catalog.type_combo, Qt.Key.Key_F1)
        self.app.processEvents()
        self.state('catalog.type_filter')
        self.assertTrue(self.state().pinned)
        self.assertEqual(self.state().facts[-1], ('Sichtbare Angebote', '6'))

    def test_v47_help_controls_keep_article(self):
        self.offer()
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        self.app.processEvents()
        before = self.state()
        for name in ('helpPin', 'helpDetailsToggle', 'helpRelated.action.definition'):
            widget = self.w.help_widget.findChild(QPushButton, name) or self.w.help_widget.findChild(QToolButton, name)
            widget.setFocus()
            self.app.processEvents()
            self.assertEqual(self.state(), before)

    def test_v48_owned_modal_help(self):
        self.c.select_node('action', 'action.editor')
        observed = []
        def inspect_dialog():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QInputDialog):
                self.c.help.set_pinned(True)
                QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_F1)
                observed.append(self.state().resolved_topic_id)
                dialog.reject()
        QTimer.singleShot(30, inspect_dialog)
        self.w.rename_selected()
        self.assertEqual(observed, ['native_shell.rename'])
        self.assertFalse(self.c.session.dirty)

    def test_real_open_dialog_f1_cancel_preserves_selection(self):
        self.offer()
        before = (self.c.selection, self.c.action_parameter, self.c.session)
        observed = []
        def inspect_dialog():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QFileDialog):
                self.c.help.set_pinned(True)
                QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_F1)
                observed.append(self.state().resolved_topic_id)
                dialog.reject()
        QTimer.singleShot(40, inspect_dialog)
        self.w.choose_project()
        self.assertEqual(observed, ['native_shell.open'])
        self.assertEqual((self.c.selection, self.c.action_parameter, self.c.session), before)
        self.assertFalse(self.c.session.dirty)

    def test_v52_selection_topic_projection(self):
        for kind, identity, topic in [('handler', 'handler.main', 'explorer.handler'),
                                      ('folder', 'folder.main', 'explorer.folder'),
                                      ('folder_entry', 'placement.command', 'explorer.folder_entry')]:
            self.c.select_node(kind, identity)
            self.state(topic)
            self.assertIn(identity, str(self.state().facts))

    def test_explorer_entities(self):
        ids = [('plugin', 'plugin.native_sample', 'explorer.plugin'),
               ('action', 'action.command', 'action.definition'),
               ('handler', 'handler.main', 'explorer.handler'),
               ('folder', 'folder.main', 'explorer.folder'),
               ('folder_entry', 'placement.command', 'explorer.folder_entry')]
        ids[0] = ('plugin', self.c.session.native_project().plugin_id, 'explorer.plugin')
        for kind, identity, topic in ids:
            with self.subTest(kind=kind):
                self.node(kind, identity)
                self.assertIn(identity, str(self.state(topic).facts))
                self.focus(self.w.explorer.search_edit, 'explorer.search')
                self.focus(self.w.explorer.tree, topic)
        self.assertIn(('Action-ID', 'action.command'), self.state().facts)

    def test_explorer_groups_and_loss(self):
        self.node('action', 'action.command')
        group = self.w.explorer.tree.topLevelItem(0).child(0)
        self.click_item(self.w.explorer.tree, group)
        self.assertIsNone(self.c.selection)
        self.assertEqual(self.state('explorer').facts, ())

    def test_explorer_search(self):
        self.node('action', 'action.command')
        self.focus(self.w.explorer.search_edit, 'explorer.search')
        QTest.keyClicks(self.w.explorer.search_edit, 'not-present')
        self.assertIsNone(self.c.selection)
        self.assertIn(('Suchlänge', '11'), self.state('explorer.search').facts)

    def test_explorer_reset(self):
        self.w.explorer.set_filter('__not_a_match__')
        self.focus(self.w.explorer.reset_button, 'explorer.search')
        QTest.mouseClick(self.w.explorer.reset_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.explorer.search_edit.text(), '')
        self.assertIn(('Suchlänge', '0'), self.state().facts)

    def test_catalog_definition_and_loss(self):
        self.offer('action.command', None)
        self.state('action.definition')
        self.assertNotIn('actionParameter', str(self.state().facts))
        self.w.catalog.catalog_tree.clearSelection()
        self.assertIsNone(self.c.selection)
        self.state('catalog')

    def test_catalog_parameter(self):
        self.offer()
        self.assertIn(('actionParameter', 'second'), self.state('catalog.parameter').facts)
        self.focus(self.w.catalog.search_edit, 'catalog.search')
        self.focus(self.w.catalog.catalog_tree, 'catalog.parameter')

    def test_catalog_search(self):
        self.offer()
        self.focus(self.w.catalog.search_edit, 'catalog.search')
        QTest.keyClicks(self.w.catalog.search_edit, 'second')
        self.assertIn(('Suchlänge', '6'), self.state('catalog.search').facts)
        self.assertGreater(len(self.w.catalog.visible_keys()), 0)

    def test_catalog_type(self):
        self.focus(self.w.catalog.type_combo, 'catalog.type_filter')
        QTest.keyClick(self.w.catalog.type_combo, Qt.Key.Key_End)
        self.assertIn(('SDK-Typ', self.w.catalog.type_combo.currentText()), self.state('catalog.type_filter').facts)

    def test_catalog_sort(self):
        self.offer()
        self.focus(self.w.catalog.sort_button, 'catalog.sort')
        QTest.mouseClick(self.w.catalog.sort_button, Qt.MouseButton.LeftButton)
        self.assertIn(('Reihenfolge', 'Name'), self.state('catalog.sort').facts)
        self.assertEqual(self.c.action_parameter, 'second')

    def test_catalog_edit(self):
        self.offer('action.editor', None)
        self.focus(self.w.catalog.edit_button, 'catalog.edit')
        with patch('studio.native_shell.window.QInputDialog.getText', return_value=('', False)) as dialog:
            QTest.mouseClick(self.w.catalog.edit_button, Qt.MouseButton.LeftButton)
        dialog.assert_not_called()
        self.assertIs(self.w.tabs.currentWidget(), self.w.inspector)
        self.assertEqual(self.w.inspector.draft.action_id, 'action.editor')
        self.assertFalse(self.c.session.dirty)

    def test_catalog_reset(self):
        self.w.catalog.set_filter('none')
        self.focus(self.w.catalog.reset_filter_button, 'catalog.search')
        QTest.mouseClick(self.w.catalog.reset_filter_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.catalog.search_edit.text(), '')
        self.assertEqual(len(self.w.catalog.visible_keys()), 6)

    def test_problems_search(self):
        self.publish()
        self.focus(self.w.problems.search_field, 'problems.filters')
        QTest.keyClicks(self.w.problems.search_field, 'HELP_ERROR')
        self.assertIn(('Sichtbare Meldungen', '1'), self.state('problems.filters').facts)

    def test_problems_severity(self):
        self.publish()
        for category, button in self.w.problems.severity_buttons.items():
            with self.subTest(category=category):
                self.focus(button, 'problems.filters')
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                self.assertIn(('Schweregrad', category), self.state('problems.filters').facts)

    def test_problems_diagnostic(self):
        self.diagnostic()
        self.state('problems.diagnostic')
        self.focus(self.w.problems.search_field, 'problems.filters')
        self.focus(self.w.problems.problems_table, 'problems.diagnostic')
        self.assertIn(('Code', 'HELP_ERROR'), self.state().facts)
        self.assertNotIn('/private', str(self.state().facts))
        self.assertNotIn('DO_NOT_ECHO', str(self.state().facts))
        QTest.keyClick(self.w.problems.problems_table, Qt.Key.Key_Return)
        self.assertIn('Keine geprüfte', str(self.state().facts))

    def test_problems_details(self):
        self.diagnostic()
        self.focus(self.w.problems.detail_view, 'problems.diagnostic')
        self.assertIn(('Code', 'HELP_ERROR'), self.state().facts)
        QTest.keyClick(self.w.problems.detail_view, Qt.Key.Key_F1)
        self.state('problems.diagnostic')

    def test_problems_empty(self):
        self.w.tabs.setCurrentWidget(self.w.problems)
        self.state('problems.empty')
        self.assertIn(('Leerzustand', 'none'), self.state().facts)
        self.publish()
        self.w.problems.set_filter('absent')
        context = self.w.help_bindings.context_for(self.w.problems.empty_title)
        self.assertEqual(context.topic_id, 'problems.empty')
        self.assertIn(('Leerzustand', 'no_match'), context.facts)

    def test_problems_reset(self):
        self.publish()
        self.w.problems.set_filter('absent')
        self.focus(self.w.problems.empty_reset, 'problems.filters')
        QTest.mouseClick(self.w.problems.empty_reset, Qt.MouseButton.LeftButton)
        self.assertEqual(len(self.w.problems.visible_entries()), 2)

    def test_problems_header(self):
        self.publish()
        header = self.w.problems.problems_table.horizontalHeader()
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(25, 8))
        self.state('problems.sort')

    def test_problems_menu(self):
        self.diagnostic()
        menu = self.w.problems.build_context_menu(0)
        menu.popup(self.w.problems.mapToGlobal(QPoint(25, 25)))
        self.app.processEvents()
        try:
            QTest.keyClick(menu, Qt.Key.Key_F1)
            self.state('problems.diagnostic')
        finally:
            menu.close()
            menu.deleteLater()

    def test_toolbar_open(self): self.toolbar('open', 'native_shell.open')
    def test_toolbar_save(self): self.toolbar('save', 'native_shell.save')
    def test_toolbar_undo(self): self.toolbar('undo', 'native_shell.undo')
    def test_toolbar_redo(self): self.toolbar('redo', 'native_shell.redo')
    def test_toolbar_rename(self):
        self.offer('action.editor', None)
        self.toolbar('rename', 'native_shell.rename')
    def test_toolbar_reload(self): self.toolbar('reload', 'native_shell.reload')

    def test_f1_pin_and_focus(self):
        self.focus(self.w.catalog.search_edit, 'catalog.search')
        self.c.help.set_pinned(True)
        self.w.explorer.search_edit.setFocus()
        self.app.processEvents()
        self.state('catalog.search')
        QTest.keyClick(self.w.explorer.search_edit, Qt.Key.Key_F1)
        self.app.processEvents()
        self.state('explorer.search')
        self.assertTrue(self.state().pinned)
        self.assertIs(self.w.tabs.currentWidget(), self.w.help_widget)
        self.c.help.set_pinned(False)
        self.toolbar('help', 'studio.help')

    def test_shell_details(self):
        self.node('handler', 'handler.main')
        self.focus(self.w.details, 'native_shell.details')
        self.assertIn('handler.main', str(self.state().facts))
        self.assertTrue(self.w.details.isReadOnly())

    def test_shell_tabs(self):
        bar = self.w.tabs.tabBar()
        self.focus(bar, 'native_shell.tabs')
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
        self.state('keypad.overview')
        self.assertIs(self.w.tabs.currentWidget(), self.w.keypad.panel)
        self.assertIsNotNone(self.w.keypad.widget.frame())

    def test_owned_dialogs(self):
        for cls, topic in ((QInputDialog, 'native_shell.rename'), (QFileDialog, 'native_shell.open'),
                           (QMessageBox, 'native_shell.unsaved'), (QDialog, 'studio.help')):
            with self.subTest(dialog=cls.__name__):
                dialog = cls(self.w)
                if isinstance(dialog, QFileDialog):
                    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
                if isinstance(dialog, QInputDialog): dialog.setTextValue('DO_NOT_ECHO_TOKEN')
                dialog.setModal(True)
                dialog.show()
                self.app.processEvents()
                try:
                    self.c.help.set_pinned(True)
                    QTest.keyClick(dialog.focusWidget() or dialog, Qt.Key.Key_F1)
                    self.app.processEvents()
                    self.state(topic)
                    self.assertNotIn('DO_NOT_ECHO_TOKEN', str(self.state().facts))
                finally:
                    dialog.reject()
                    dialog.deleteLater()
                    self.app.processEvents()
                    self.c.help.set_pinned(False)

    def test_help_pin(self):
        self.offer()
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        pin = self.w.help_widget.findChild(QPushButton, 'helpPin')
        self.focus(pin, 'catalog.parameter')
        QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
        self.assertTrue(self.state().pinned)
        QTest.keyClick(pin, Qt.Key.Key_F1)
        self.state('help.pin')
        self.assertTrue(self.state().pinned)
        QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
        self.assertFalse(self.state().pinned)

    def test_help_details(self):
        self.offer()
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        toggle = self.w.help_widget.findChild(QToolButton, 'helpDetailsToggle')
        details = self.w.help_widget.findChild(QTextEdit, 'helpDetails')
        self.focus(toggle, 'catalog.parameter')
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(details.isVisible())
        QTest.keyClick(toggle, Qt.Key.Key_F1)
        self.state('help.details')

    def test_help_related(self):
        self.offer()
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        button = self.w.help_widget.findChild(QPushButton, 'helpRelated.action.definition')
        self.focus(button, 'catalog.parameter')
        self.c.help.set_pinned(True)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.state('action.definition')
        button = self.w.help_widget.findChild(QPushButton, 'helpRelated.catalog.parameter')
        button.setFocus()
        self.app.processEvents()
        QTest.keyClick(button, Qt.Key.Key_F1)
        self.state('help.related')
        before = self.state()
        for topic in ('not.registered', '../../invalid', None):
            self.c.related_help(topic)
            self.assertEqual(self.state(), before)

    def test_help_scroll(self):
        self.offer()
        self.w.tabs.setCurrentWidget(self.w.help_widget)
        scroll = self.w.help_widget.findChild(__import__('PySide6.QtWidgets', fromlist=['QScrollArea']).QScrollArea, 'helpScroll')
        scroll.setFocus()
        self.app.processEvents()
        self.state('catalog.parameter')
        QTest.keyClick(scroll, Qt.Key.Key_F1)
        self.state('studio.help')

    def test_unknown_and_fallback(self):
        self.offer()
        unknown = QLineEdit(self.w)
        unknown.setObjectName('unboundControl')
        unknown.show()
        self.focus(unknown, 'studio.help')
        self.c.help.request_help(HelpContext('catalog.search.unknown', (('UI', 'current'),)))
        self.assertTrue(self.state('catalog.search').is_fallback)
        self.c.help.request_help(HelpContext('totally_unknown', (('secret', 'hidden'),)))
        self.assertIsNone(self.state().entry)
        self.assertEqual(self.state().facts, ())
        self.assertEqual(self.w.help_widget.findChild(QTextEdit, 'helpFacts').toPlainText(), '')

    def test_project_switch(self):
        old = self.diagnostic()[0]
        self.c.help.set_pinned(True)
        self.c.open_project(self.path)
        self.assertFalse(self.state().pinned)
        self.assertEqual(self.state().facts, ())
        self.assertEqual(self.w.problems.diagnostics(), [])
        self.c.diagnostic_selected(old)
        self.assertNotEqual(self.state().resolved_topic_id, 'problems.diagnostic')
        self.assertIsNone(self.c.selection)
        self.assertEqual(self.w.catalog.search_edit.text(), '')

    def test_disabled_capabilities(self):
        self.tooltip(self.w.catalog.new_action_button, 'inspector.create')
        self.assertIn('Formularentwurf', self.w.catalog.new_action_button.toolTip())
        self.c.select_node('action', 'action.command')
        self.assertTrue(self.w.ict_action.isEnabled())
        self.toolbar('ict', 'symbol.ict')
        from studio.keypad_preview.widget import KeypadPreviewWidget
        self.assertEqual(len(self.w.findChildren(KeypadPreviewWidget)), 1)
        for operation in (lambda: self.w.catalog.set_filter('a'),
                          lambda: self.w.catalog.set_group_order('name'), self.c.refresh):
            operation()
            self.assertTrue(self.w.catalog.new_action_button.isEnabled())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.c.session.dirty)

    def test_layout_does_not_write(self):
        self.w.splitter.setSizes([250, 400, 600])
        self.w.problems.body_splitter.setSizes([300, 150])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.c.session.dirty)

    def test_v49_no_session_operations_or_signal_loop(self):
        session = self.c.session
        spy = QSignalSpy(self.c.help.helpChanged)
        with patch.object(session, 'replace', wraps=session.replace) as replace, patch.object(session, 'save', wraps=session.save) as save:
            for _ in range(10):
                self.focus(self.w.catalog.search_edit, 'catalog.search')
                self.focus(self.w.catalog.type_combo, 'catalog.type_filter')
                self.c.help.set_pinned(True)
                self.w.request_help()
                self.c.help.set_pinned(False)
            replace.assert_not_called()
            save.assert_not_called()
        self.assertLess(spy.count(), 70)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_v50_foreign_windows_untouched(self):
        self.offer()
        before = self.state()
        foreign = QLineEdit()
        foreign.show()
        foreign.activateWindow()
        self.app.processEvents()
        foreign.setFocus()
        QTest.keyClick(foreign, Qt.Key.Key_F1)
        self.app.processEvents()
        self.assertEqual(self.state(), before)
        foreign.close()
        foreign.deleteLater()

    def test_duplicate_names_and_unknown_native_identity(self):
        raw = json.loads(self.original)
        for action in raw['actions']: action['display_name'] = 'Identisch'
        self.path.write_text(json.dumps(raw), encoding='utf-8')
        self.c.open_project(self.path)
        self.node('action', 'action.editor')
        self.assertIn('action.editor', str(self.state().facts))
        self.node('action', 'action.multistate')
        self.assertIn('action.multistate', str(self.state().facts))
        self.c.select_node('action', 'Identisch')
        self.assertEqual(self.c.selection, ('action', 'action.multistate'))

    def test_v51_machine_coverage_register(self):
        path = ROOT / 'tests/fixtures/contracts/help-coverage.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'READY_FOR_REVIEW')
        rows = data['surfaces']
        self.assertEqual(len({r['id'] for r in rows}), len(rows))
        before = json.loads((path.parent / 'audit-rows.json').read_text(encoding='utf-8'))
        self.assertEqual({r[0] for r in before}, {r['id'] for r in rows})
        functions = {n.name for n in ast.walk(ast.parse(Path(__file__).read_text(encoding='utf-8'))) if isinstance(n, ast.FunctionDef)}
        for row in rows:
            self.assertIn(row['status'], ('OK', 'NICHT_AKTIV', 'BEWUSST_OHNE'))
            self.assertIn(row['test'].split('::')[1], functions)
            self.assertTrue(row['owner'])
            if row['status'] == 'OK':
                self.assertIsNotNone(self.c.registry.get(row['topic_id']))
        self.assertEqual(data['unresolved_gaps'], [])


if __name__ == '__main__': unittest.main()
