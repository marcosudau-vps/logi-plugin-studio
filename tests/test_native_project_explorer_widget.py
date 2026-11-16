"""Native Project Explorer contract + real Qt input; no session/SDK execution."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeWidgetItem

from adapters.logitech.native import (
    ACTION_TYPES, NativeFolderEntry, NativeProject, legacy_project, parse_native_project,
)
from studio.native_project_explorer import NativeProjectExplorerWidget

EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"
APP = None


def rows(tree):
    result = []

    def collect(item):
        result.append(item)
        for i in range(item.childCount()):
            collect(item.child(i))

    for i in range(tree.topLevelItemCount()):
        collect(tree.topLevelItem(i))
    return result


def key(item):
    return item.data(0, Qt.ItemDataRole.UserRole)


class ExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global APP
        APP = QApplication.instance() or QApplication([])
        cls.cursor = QCursor.pos()

    @classmethod
    def tearDownClass(cls):
        QCursor.setPos(cls.cursor)

    def setUp(self):
        self.raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.project = parse_native_project(self.raw)
        self.widget = NativeProjectExplorerWidget()
        self.widget.resize(460, 1050)
        self.widget.show()
        self.selected, self.activated = [], []
        self.widget.nodeSelected.connect(lambda *value: self.selected.append(value))
        self.widget.nodeActivated.connect(lambda *value: self.activated.append(value))
        self.widget.set_project(self.project, revision="opaque-host-revision")
        QApplication.processEvents()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()

    def item(self, kind, native_id):
        return next(row for row in rows(self.widget.tree) if key(row) == (kind, native_id))

    def click(self, item, *, double=False):
        self.widget.tree.scrollToItem(item)
        QApplication.processEvents()
        pos = self.widget.tree.visualItemRect(item).center()
        QTest.mouseClick(self.widget.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        if double:
            QTest.mouseDClick(self.widget.tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        QApplication.processEvents()

    def test_exact_real_example_counts_and_ids(self):
        entities = [key(item) for item in rows(self.widget.tree) if key(item)]
        self.assertEqual(len(entities), 11)
        for kind, count in (("plugin", 1), ("action", 4), ("handler", 1), ("folder", 1), ("folder_entry", 4)):
            self.assertEqual(sum(key[0] == kind for key in entities), count)
        self.assertEqual(len(rows(self.widget.tree)), 14)
        self.assertEqual({self.item("action", a.id).data(0, Qt.ItemDataRole.UserRole + 1)[2]
                          for a in self.project.actions}, ACTION_TYPES)

    def test_project_tuple_order_including_unsorted_positions(self):
        folder = replace(self.project.folders[0], entries=tuple(reversed(self.project.folders[0].entries)))
        project = replace(self.project, actions=tuple(reversed(self.project.actions)), folders=(folder,))
        self.widget.set_project(project)
        groups = self.widget.tree.topLevelItem(0)
        self.assertEqual([key(groups.child(0).child(i))[1] for i in range(4)], [a.id for a in project.actions])
        item = self.item("folder", folder.id)
        self.assertEqual([key(item.child(i))[1] for i in range(4)], [e.id for e in folder.entries])

    def test_all_entity_kinds_emit_exact_native_selection_and_activation(self):
        for kind, native_id in (("plugin", "sample.native"), ("action", "action.command"),
                                ("handler", "handler.main"), ("folder", "folder.main"),
                                ("folder_entry", "placement.multistate")):
            with self.subTest(kind=kind):
                self.selected.clear()
                self.activated.clear()
                self.click(self.item(kind, native_id))
                self.assertEqual(self.selected, [(kind, native_id)])
                self.assertEqual(self.activated, [])
                QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
                self.assertEqual(self.activated, [(kind, native_id)])

    def test_double_click_once_and_no_activation_on_single_click(self):
        self.click(self.item("folder_entry", "placement.command"), double=True)
        self.assertEqual(self.selected, [("folder_entry", "placement.command")])
        self.assertEqual(self.activated, [("folder_entry", "placement.command")])

    def test_enter_numpad_and_autorepeat(self):
        self.widget.set_selection("action", "action.editor")
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Enter)
        self.assertEqual(self.activated, [("action", "action.editor")])
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "", True)
        QApplication.sendEvent(self.widget.tree, event)
        self.assertEqual(len(self.activated), 1)

    def test_groups_navigate_without_entity_signals(self):
        group = self.widget.tree.topLevelItem(0).child(0)
        self.click(group)
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertFalse(group.isExpanded())
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Right)
        self.assertTrue(group.isExpanded())
        self.click(group, double=True)
        self.assertFalse(group.isExpanded())
        self.assertEqual(self.selected, [])
        self.assertEqual(self.activated, [])

    def test_keyboard_arrows_emit_once(self):
        self.widget.set_selection("action", "action.command")
        self.widget.tree.setFocus()
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Down)
        self.assertEqual(self.selected, [("action", "action.multistate")])
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertEqual(self.activated, [("action", "action.multistate")])

    def test_all_public_programmatic_changes_are_silent(self):
        self.widget.set_selection("action", "action.command")
        self.widget.set_filter("command")
        self.widget.set_project(self.project, revision="another opaque value")
        self.widget.set_filter("")
        self.widget.set_selection("handler", "handler.main")
        self.widget.clear()
        QApplication.processEvents()
        self.assertEqual((self.selected, self.activated), ([], []))

    def test_unknown_selection_clears_without_phantom_or_intent(self):
        self.widget.set_selection("action", "action.command")
        for value in (("action", "missing"), ("group", "Aktionen"), ("folder_entry", "action.command")):
            self.assertFalse(self.widget.set_selection(*value))
            self.assertIsNone(self.widget.tree.currentItem())
            self.assertEqual(self.widget.tree.selectedItems(), [])
            QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertEqual((self.selected, self.activated), ([], []))

    def test_filtered_selection_cleared_and_not_resurrected(self):
        self.widget.set_selection("action", "action.command")
        self.widget.set_filter("multistate")
        self.assertIsNone(self.widget.tree.currentItem())
        self.assertFalse(self.widget.set_selection("action", "action.command"))
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.widget.set_filter("")
        self.assertIsNone(self.widget.tree.currentItem())
        self.assertEqual((self.selected, self.activated), ([], []))

    def test_repeat_placements_do_not_duplicate_action_definitions(self):
        folder = self.project.folders[0]
        folder = replace(folder, entries=(*folder.entries, NativeFolderEntry("placement.second", "action.command", 9)))
        self.widget.set_project(replace(self.project, folders=(folder,)))
        self.assertEqual(sum(key(i) == ("action", "action.command") for i in rows(self.widget.tree)), 1)
        self.click(self.item("folder_entry", "placement.second"))
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertEqual(self.selected, [("folder_entry", "placement.second")])
        self.assertEqual(self.activated, [("folder_entry", "placement.second")])

    def test_snapshot_removed_objects_cannot_activate_and_new_objects_select(self):
        self.widget.set_selection("folder_entry", "placement.command")
        action = replace(self.project.actions[0], id="action.new")
        folder = replace(self.project.folders[0], entries=(NativeFolderEntry("placement.new", action.id, 0),))
        replacement = replace(self.project, actions=(action,), folders=(folder,))
        self.widget.set_project(replacement, revision="new")
        self.assertIsNone(self.widget.tree.currentItem())
        self.assertFalse(self.widget.set_selection("action", "action.command"))
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertEqual(self.activated, [])
        self.click(self.item("folder_entry", "placement.new"))
        self.assertEqual(self.selected, [("folder_entry", "placement.new")])

    def test_snapshot_same_ids_refresh_labels_and_keep_selection(self):
        self.widget.set_selection("action", "action.command")
        action = replace(self.project.actions[0], display_name="Neuer Titel")
        self.widget.set_project(replace(self.project, actions=(action, *self.project.actions[1:])))
        self.assertEqual(key(self.widget.tree.currentItem()), ("action", action.id))
        self.assertEqual(self.item("action", action.id).text(0), "Neuer Titel")
        self.assertEqual(self.item("folder_entry", "placement.command").text(0), "Neuer Titel")
        self.assertEqual((self.selected, self.activated), ([], []))

    def test_plugin_change_drops_selection_even_if_action_id_reused(self):
        self.widget.set_selection("action", "action.command")
        self.widget.set_project(replace(self.project, plugin_id="other.plugin"))
        self.assertIsNone(self.widget.tree.currentItem())

    def test_revision_is_opaque_tooltip_only_and_does_not_affect_identity(self):
        revision = "任意 <host> / 0007"
        self.widget.set_project(self.project, revision=revision)
        root = self.widget.tree.topLevelItem(0)
        self.assertEqual(key(root), ("plugin", self.project.plugin_id))
        self.assertIn("任意 &lt;host&gt; / 0007", root.toolTip(0))
        self.widget.set_project(self.project)
        self.assertNotIn("Host-Revision:", self.widget.tree.topLevelItem(0).toolTip(0))

    def test_filter_casefold_ids_parent_visibility_and_groups(self):
        self.widget.set_filter("PLACEMENT.MULTISTATE")
        entry = self.item("folder_entry", "placement.multistate")
        self.assertFalse(entry.isHidden())
        parent = entry.parent()
        while parent:
            self.assertFalse(parent.isHidden())
            self.assertTrue(parent.isExpanded())
            parent = parent.parent()
        self.assertTrue(self.item("action", "action.command").isHidden())
        self.assertTrue(self.item("folder_entry", "placement.command").isHidden())
        self.widget.set_filter("DYNAMIC FOLDERS")
        self.assertFalse(entry.isHidden())
        self.assertTrue(self.item("action", "action.command").isHidden())

    def test_filter_visible_type_callback_navigation_and_action_reference(self):
        for text, target in (("PluginDynamicAdjustment", ("action", "action.adjustment")),
                             ("Callback", ("handler", "handler.main")),
                             ("ButtonArea", ("folder", "folder.main")),
                             ("action.command", ("folder_entry", "placement.command"))):
            with self.subTest(text=text):
                self.widget.set_filter(text)
                self.assertFalse(self.item(*target).isHidden())

    def test_unicode_duplicate_labels_long_text_and_tooltip_escaping(self):
        label = "Grüße STRASSE 東京 <b>& " + "Sehr langer Anzeigename " * 30
        actions = tuple(replace(action, display_name=label) for action in self.project.actions)
        self.widget.set_project(replace(self.project, actions=actions))
        self.widget.resize(280, 1000)
        self.widget.set_filter("straße 東京")
        for action in actions:
            item = self.item("action", action.id)
            self.assertFalse(item.isHidden())
            self.assertTrue(self.widget.set_selection("action", action.id))
            self.assertEqual(key(self.widget.tree.currentItem()), ("action", action.id))
            self.assertIn("&lt;b&gt;&amp;", item.toolTip(0))
        QApplication.processEvents()
        self.assertLessEqual(self.widget.width(), 280)
        self.assertFalse(self.widget.tree.horizontalScrollBar().isVisible())

    def test_same_id_across_entity_kinds_does_not_collide(self):
        project = replace(self.project, plugin_id="action.command")
        self.widget.set_project(project)
        self.assertTrue(self.widget.set_selection("plugin", "action.command"))
        self.assertTrue(self.widget.set_selection("action", "action.command"))
        self.assertEqual(key(self.widget.tree.currentItem()), ("action", "action.command"))

    def test_no_results_none_clear_and_empty_collections(self):
        self.widget.set_filter("no-such-object")
        self.assertEqual(self.widget.stack.currentWidget(), self.widget.empty_page)
        self.assertIn("Keine Treffer", self.widget.empty_label.text())
        self.widget.set_project(None)
        self.assertEqual(self.widget.tree.topLevelItemCount(), 0)
        self.assertIsNone(self.widget.tree.currentItem())
        self.assertIn("Kein Projekt", self.widget.empty_label.text())
        self.widget.clear()
        self.assertEqual(self.widget.search_edit.text(), "")
        folder = replace(self.project.folders[0], entries=())
        empty = NativeProject("empty.plugin", "Leeres natives Objekt", (), (), (folder,))
        self.widget.set_project(empty)
        self.assertEqual(self.item("folder", folder.id).childCount(), 0)
        self.assertEqual(sum(key(i) is not None for i in rows(self.widget.tree)), 2)
        # Parser permits empty folders/entries, but not empty actions/handlers.
        self.raw["folders"][0]["entries"] = []
        self.widget.set_project(parse_native_project(self.raw))
        self.assertEqual(self.item("folder", folder.id).childCount(), 0)
        self.raw["folders"] = []
        self.widget.set_project(parse_native_project(self.raw))
        self.assertFalse(any(key(i) and key(i)[0] == "folder" for i in rows(self.widget.tree)))

    def test_filter_input_escape_and_find_shortcut(self):
        self.widget.tree.setFocus()
        QTest.keyClick(self.widget.tree, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.widget.search_edit.hasFocus())
        QTest.keyClicks(self.widget.search_edit, "MULTISTATE")
        self.assertFalse(self.item("action", "action.multistate").isHidden())
        QTest.keyClick(self.widget.search_edit, Qt.Key.Key_Escape)
        self.assertEqual(self.widget.search_edit.text(), "")
        QTest.keyClick(self.widget.search_edit, Qt.Key.Key_Down)
        self.assertTrue(self.widget.tree.hasFocus())
        self.assertEqual((self.selected, self.activated), ([], []))

    def test_expansion_restored_after_filter_and_snapshot(self):
        folder = self.item("folder", "folder.main")
        folder.setExpanded(False)
        self.widget.set_filter("placement.command")
        self.assertTrue(folder.isExpanded())
        self.widget.set_filter("")
        self.assertFalse(folder.isExpanded())
        self.widget.set_project(self.project)
        self.assertFalse(self.item("folder", "folder.main").isExpanded())
        self.assertTrue(self.widget.set_selection("folder_entry", "placement.command"))
        self.assertTrue(self.item("folder", "folder.main").isExpanded())

    def test_read_only_flags_and_edit_keys(self):
        self.assertEqual(self.widget.tree.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(self.widget.tree.dragDropMode(), QAbstractItemView.DragDropMode.NoDragDrop)
        for item in rows(self.widget.tree):
            for flag in (Qt.ItemFlag.ItemIsEditable, Qt.ItemFlag.ItemIsDragEnabled, Qt.ItemFlag.ItemIsDropEnabled):
                self.assertFalse(item.flags() & flag)
        before = copy.deepcopy(self.project)
        self.widget.set_selection("action", "action.command")
        for code in (Qt.Key.Key_F2, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            QTest.keyClick(self.widget.tree, code)
        self.assertEqual(self.project, before)
        self.assertEqual(self.item("action", "action.command").text(0), self.project.actions[0].display_name)

    def test_no_source_mutations_or_file_access(self):
        before = copy.deepcopy(self.project)
        digest = hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        with patch("builtins.open", side_effect=AssertionError("Widget attempted file access")):
            self.widget.set_project(self.project)
            self.widget.set_filter("handler.main")
            self.widget.set_selection("handler", "handler.main")
            self.widget.clear()
        self.assertEqual(self.project, before)
        self.assertEqual(hashlib.sha256(EXAMPLE.read_bytes()).hexdigest(), digest)

    def test_native_only_explicit_legacy_projection(self):
        legacy = {"schema_version": "0.1-draft", "project": {"id": "old.plugin", "display_name": "Alt"},
                  "components": [{"id": "old.action", "type": "core.command_action", "config": {"display_name": "Altaktion"}}]}
        with self.assertRaises(TypeError):
            self.widget.set_project(legacy)
        self.assertEqual(self.widget.tree.topLevelItem(0).text(0), self.project.display_name)
        self.widget.set_project(legacy_project(legacy))
        self.assertTrue(self.widget.set_selection("action", "old.action"))

    def test_duplicate_native_identity_rejected_without_losing_snapshot(self):
        invalid = replace(self.project, actions=(self.project.actions[0], self.project.actions[0]))
        with self.assertRaises(ValueError):
            self.widget.set_project(invalid)
        self.assertTrue(self.widget.set_selection("action", "action.editor"))

    def test_programmatic_tree_focus_is_not_a_user_selection(self):
        self.widget.tree.setCurrentItem(self.item("action", "action.command"))
        QApplication.processEvents()
        self.assertEqual(self.selected, [])

    def test_collapsed_parent_prevents_activation_of_hidden_descendant(self):
        self.widget.set_selection("folder_entry", "placement.command")
        self.item("folder", "folder.main").setExpanded(False)
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertNotIn(("folder_entry", "placement.command"), self.activated)

    def test_host_selected_parent_stays_expanded_after_refresh(self):
        self.item("folder", "folder.main").setExpanded(False)
        self.widget.set_selection("folder_entry", "placement.command")
        self.widget.set_filter("command")
        self.widget.set_filter("")
        self.assertTrue(self.item("folder", "folder.main").isExpanded())
        self.widget.set_project(self.project)
        self.assertEqual(key(self.widget.tree.currentItem()), ("folder_entry", "placement.command"))

    def test_reentrant_host_refresh_on_user_intents(self):
        self.widget.nodeSelected.connect(lambda *_: self.widget.set_project(self.project, revision="refresh"))
        self.click(self.item("action", "action.command"))
        self.assertEqual(self.selected, [("action", "action.command")])
        self.widget.nodeActivated.connect(lambda *_: self.widget.clear())
        QTest.keyClick(self.widget.tree, Qt.Key.Key_Return)
        self.assertEqual(self.activated, [("action", "action.command")])
        self.assertEqual(self.widget.tree.topLevelItemCount(), 0)


class LabProcessTests(unittest.TestCase):
    def test_offscreen_smoke_real_process(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
        run = subprocess.run([sys.executable, str(ROOT / "tools/run_native_project_explorer_lab.py"), "--smoke"],
                             cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=40)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("SMOKE PASS", run.stdout)
        self.assertEqual(run.stdout.count("PASS:"), 4)


if __name__ == "__main__":
    unittest.main()
