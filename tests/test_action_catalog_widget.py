"""AP-WIDGET-003: ActionCatalogWidget, its drag payload and the Action Catalog Lab.

Input runs through real Qt events. ``QDrag.exec`` is replaced in most drag tests.
On the offscreen platform the real call returns at once with IgnoreAction, so a
real drop cannot happen here: ProcessTests only prove a real QDrag is memory-safe.
The real Windows drop is ``run_action_catalog_lab.py --os-drag-check``.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"

try:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QCursor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from adapters.logitech.native import (ACTION_TYPES, NativeAction, NativeParameter, NativeProject, legacy_project,
                                          parse_native_project)
    from studio.action_catalog import ALL_TYPES_LABEL, ActionCatalogWidget
    from studio.action_catalog.widget import tones_for
    from studio.keypad_contract import ActionOffer, KeypadFrame, NavigationCapability, SlotData
    from studio.keypad_preview import KeypadPreviewWidget
    from studio.keypad_preview.mime import ACTION_REF_MIME, decode_action_ref, encode_action_ref
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

LEFT = None if not HAS_QT else Qt.MouseButton.LeftButton
NO_MOD = None if not HAS_QT else Qt.KeyboardModifier.NoModifier
_APP_STATE: dict = {}


def setUpModule():
    if HAS_QT:
        app = QApplication.instance() or QApplication([])
        _APP_STATE.update(cursor=QCursor.pos(), style=app.style().objectName(), palette=QApplication.palette())


def tearDownModule():
    """QTest.mouseMove moves the global pointer. Later modules must find the app as it was."""
    if HAS_QT:
        QCursor.setPos(_APP_STATE["cursor"])
        QApplication.setStyle(_APP_STATE["style"])
        QApplication.setPalette(_APP_STATE["palette"])
        for widget in QApplication.topLevelWidgets():
            widget.close()
        QApplication.sendPostedEvents(None, 0)
        QApplication.processEvents()


def lab_module():
    name = "run_action_catalog_lab"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "run_action_catalog_lab.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def native_action(action_id="a.plain", *, sdk_type="PluginDynamicCommand", name=None, description="Beschreibung", group="Gruppe",
                  parameters=()) -> "NativeAction":
    return NativeAction(action_id, sdk_type, name or action_id, description, group, "handler.main", tuple(parameters))


def parameter(name, display="Anzeige", group="PGruppe", super_group=None) -> "NativeParameter":
    return NativeParameter(name, display, group, super_group)


def example_project() -> "NativeProject":
    return parse_native_project(json.loads(EXAMPLE.read_text(encoding="utf-8")))


def solid(color="#ff0000", size=32) -> "QImage":
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def luminance(color: "QColor") -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.redF()) + 0.7152 * channel(color.greenF()) + 0.0722 * channel(color.blueF())


def contrast(a: "QColor", b: "QColor") -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class CatalogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = ActionCatalogWidget()
        self.widget.resize(320, 700)
        self.addCleanup(self._dispose)
        self.selected, self.edits, self.creates = [], [], []
        self.widget.actionSelected.connect(self.selected.append)
        self.widget.actionEditRequested.connect(self.edits.append)
        self.widget.createActionRequested.connect(lambda: self.creates.append(True))
        self.tree = self.widget.catalog_tree

    def _dispose(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def show(self):
        self.widget.show()
        QTest.qWaitForWindowExposed(self.widget)
        self.app.processEvents()

    def rect_of(self, item):
        self.tree.scrollToItem(item)
        self.app.processEvents()
        return self.tree.visualItemRect(item)

    def click_item(self, item):
        QTest.mouseClick(self.tree.viewport(), LEFT, NO_MOD, self.rect_of(item).center())
        self.app.processEvents()

    def click(self, action_id, action_parameter=None):
        self.click_item(self.widget.item_for(action_id, action_parameter))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class SourceContractTests(CatalogCase):
    def test_parser_output_is_shown_without_an_own_action_structure(self):
        project = example_project()
        self.assertIsInstance(project, NativeProject)
        self.assertTrue(all(isinstance(action, NativeAction) for action in project.actions))
        self.widget.set_project(project)
        self.assertEqual(self.widget.project_label.full_text(), "SDK-natives Beispiel")
        self.assertEqual(self.widget.visible_keys(), (
            ("action.command", None), ("action.command", "first"), ("action.command", "second"),
            ("action.multistate", None), ("action.adjustment", None), ("action.editor", None)))

    def test_set_project_directly_delegates_to_set_actions(self):
        project = example_project()
        with patch.object(self.widget, "set_actions") as set_actions:
            self.widget.set_project(project)
            set_actions.assert_called_once_with(project.actions)
            set_actions.reset_mock()
            self.widget.set_project(None)
            set_actions.assert_called_once_with(())

    def test_set_actions_accepts_only_native_actions_and_keeps_state_on_refusal(self):
        self.widget.set_actions((native_action("a.one"),))
        for bad in ([{"id": "a.dict"}], [object()]):
            with self.assertRaises(TypeError):
                self.widget.set_actions(bad)
        with self.assertRaises(ValueError):
            self.widget.set_actions((native_action("a.two"), native_action("a.two")))
        self.assertEqual(self.widget.visible_keys(), (("a.one", None),))

    def test_widget_source_keeps_its_boundaries(self):
        source = (ROOT / "src" / "studio" / "action_catalog" / "widget.py").read_text(encoding="utf-8")
        for forbidden in (r"\bopen\(", r"read_text", r"write_text", r"json\.", r"pickle", r"class ActionOffer", r"ACTION_REF_MIME\s*=",
                          r"KeypadPreviewWidget", r"ProjectDocument", r"mutate", r"\.ict", r"QSvg", r"application/"):
            self.assertIsNone(re.search(forbidden, source), forbidden)
        self.assertIn("from studio.keypad_preview.mime import ACTION_REF_MIME, encode_action_ref", source)
        self.assertIn("from studio.keypad_contract import ActionOffer", source)

    def test_legacy_view_of_a_draft_project_can_be_shown_read_only(self):
        raw = json.loads((ROOT / "examples" / "project_v0_1_draft.json").read_text(encoding="utf-8"))
        before = copy.deepcopy(raw)
        project = legacy_project(raw)
        self.widget.set_project(project)
        self.assertEqual(raw, before)
        self.assertEqual(len(self.widget.visible_keys()), len(project.actions))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class SearchAndFilterTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.widget.set_actions((
            native_action("a.alpha", name="Licht schalten", description="Schaltet die Lampe", group="Haus"),
            native_action("a.beta", sdk_type="PluginDynamicAdjustment", name="Lautstärke", description="Regelt Ton", group="Audio"),
            native_action("a.gamma", name="Szene", description="Startet Szenen", group="Haus", parameters=(
                parameter("id-morning", "Morgenlicht", "Tageszeit", "Dach"), parameter("id-night", "Nachtruhe", "Tageszeit"))),
            native_action("a.delta", sdk_type="ActionEditorCommand", name="Skript", description="", group="Audio"),
        ))

    def keys_for(self, text):
        self.widget.set_filter(text)
        return self.widget.visible_keys()

    def test_each_search_field_is_found(self):
        gamma = (("a.gamma", None), ("a.gamma", "id-morning"), ("a.gamma", "id-night"))
        self.assertEqual(self.keys_for("Licht schalten"), (("a.alpha", None),))  # name
        self.assertEqual(self.keys_for("a.beta"), (("a.beta", None),))  # id
        self.assertEqual(self.keys_for("Lampe"), (("a.alpha", None),))  # description
        self.assertEqual(self.keys_for("id-night"), (("a.gamma", None), ("a.gamma", "id-night")))  # parameter name
        self.assertEqual(self.keys_for("Nachtruhe"), (("a.gamma", None), ("a.gamma", "id-night")))  # parameter display
        self.assertEqual(self.keys_for("Tageszeit"), gamma)  # parameter group
        self.assertEqual(self.keys_for("Dach"), (("a.gamma", None), ("a.gamma", "id-morning")))  # parameter super group
        self.assertEqual(set(self.keys_for("Haus")), {("a.alpha", None), *gamma})  # group
        self.assertEqual(self.keys_for("ActionEditorCommand"), (("a.delta", None),))  # SDK type

    def test_search_ignores_case_and_combines_words(self):
        self.assertEqual(self.keys_for("LAUTSTÄRKE"), (("a.beta", None),))
        self.assertEqual(self.keys_for("  szene   NACHT "), (("a.gamma", None), ("a.gamma", "id-night")))
        self.assertEqual(self.keys_for("lampe nacht"), ())

    def test_typing_in_the_field_filters_live(self):
        self.show()
        self.widget.search_edit.setFocus()
        QTest.keyClicks(self.widget.search_edit, "lamp")
        self.assertEqual(self.widget.visible_keys(), (("a.alpha", None),))
        QTest.keyClick(self.widget.search_edit, Qt.Key.Key_Escape)
        self.assertEqual(self.widget.search_edit.text(), "")
        self.assertEqual(len(self.widget.visible_keys()), 6)

    def test_search_and_type_filter_apply_together(self):
        self.widget.set_type_filter("PluginDynamicCommand")
        self.assertEqual(self.keys_for("Regelt"), ())
        self.assertEqual(self.widget.empty_state()[0], "Keine Treffer")
        self.assertIn("PluginDynamicCommand", self.widget.empty_state()[1])
        self.assertEqual(self.keys_for("id-night"), (("a.gamma", None), ("a.gamma", "id-night")))
        self.widget.set_type_filter("PluginDynamicAdjustment")
        self.assertEqual(self.keys_for("id-night"), ())
        self.assertEqual(self.keys_for("Regelt"), (("a.beta", None),))

    def test_type_filter_offers_exactly_all_and_the_four_native_types(self):
        combo = self.widget.type_combo
        labels = [combo.itemText(index) for index in range(combo.count())]
        self.assertEqual(labels[0], ALL_TYPES_LABEL)
        self.assertEqual(ALL_TYPES_LABEL, "Alle")
        self.assertEqual(set(labels[1:]), set(ACTION_TYPES))
        self.assertEqual(len(ACTION_TYPES), 4)
        with self.assertRaises(ValueError):
            self.widget.set_type_filter("PluginDynamicFolder")
        combo.setCurrentIndex(labels.index("ActionEditorCommand"))
        self.assertEqual(self.widget.visible_keys(), (("a.delta", None),))
        combo.setCurrentIndex(0)
        self.assertEqual(len(self.widget.visible_keys()), 6)

    def test_parameter_match_opens_the_action_and_clearing_restores_the_user_state(self):
        gamma = self.widget.item_for("a.gamma")
        self.assertFalse(gamma.isExpanded())
        self.widget.set_filter("id-morning")
        self.assertTrue(gamma.isExpanded())
        self.assertTrue(self.widget.item_for("a.gamma", "id-night").isHidden())
        self.widget.set_filter("")
        self.assertFalse(gamma.isExpanded())
        self.assertFalse(self.widget.item_for("a.gamma", "id-night").isHidden())

    def test_count_label_and_empty_states(self):
        self.assertEqual(self.widget.count_label.text(), "4 von 4 Aktionen")
        self.widget.set_filter("gibt es nicht")
        self.assertEqual(self.widget.count_label.text(), "0 von 4 Aktionen")
        title, detail = self.widget.empty_state()
        self.assertEqual(title, "Keine Treffer")
        self.assertIn("gibt es nicht", detail)
        self.assertFalse(self.widget.reset_filter_button.isHidden())
        self.widget.reset_filter_button.click()
        self.assertIsNone(self.widget.empty_state())
        self.assertEqual(self.widget.search_edit.text(), "")
        self.widget.set_actions(())
        self.assertEqual(self.widget.empty_state()[0], "Keine Aktionen")
        self.assertTrue(self.widget.reset_filter_button.isHidden())
        self.widget.set_project(None)
        self.assertEqual(self.widget.empty_state()[0], "Kein Projekt geöffnet")
        self.assertFalse(self.widget.new_action_button.isEnabled())

    def test_type_filter_alone_has_its_own_empty_message(self):
        self.widget.set_actions((native_action("a.only"),))
        self.widget.set_type_filter("ActionEditorCommand")
        self.assertEqual(self.widget.empty_state()[1], "Keine Aktion hat diesen SDK-Typ.")

    def test_filter_controls_do_not_emit_a_selection(self):
        self.widget.set_filter("lampe")
        self.widget.set_type_filter("PluginDynamicCommand")
        self.widget.set_filter("")
        self.widget.set_type_filter(None)
        self.assertEqual(self.selected, [])


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class GroupTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.widget.set_actions((
            native_action("a.1", name="Zebra", group="Zeta"), native_action("a.2", name="Apfel", group="Alpha"),
            native_action("a.3", name="Birne", group="Zeta"), native_action("a.4", name="Aal", group="Zeta"),
        ))
        self.show()

    def children(self, group):
        item = self.widget.group_item(group)
        return [item.child(index).text(0) for index in range(item.childCount())]

    def test_groups_are_exactly_the_native_group_names_in_project_order(self):
        self.assertEqual(self.widget.group_names(), ("Zeta", "Alpha"))
        self.assertEqual(self.children("Zeta"), ["Zebra", "Birne", "Aal"])

    def test_order_is_stable_across_repeated_input(self):
        actions = (native_action("a.1", group="Zeta"), native_action("a.2", group="Alpha"))
        for _ in range(3):
            self.widget.set_actions(actions)
            self.assertEqual(self.widget.group_names(), ("Zeta", "Alpha"))

    def test_groups_and_actions_can_be_sorted_and_back(self):
        self.widget.sort_button.click()
        self.assertEqual(self.widget.group_names(), ("Alpha", "Zeta"))
        self.assertEqual(self.children("Zeta"), ["Aal", "Birne", "Zebra"])
        self.widget.sort_button.click()
        self.assertEqual(self.widget.group_names(), ("Zeta", "Alpha"))
        self.assertEqual(self.children("Zeta"), ["Zebra", "Birne", "Aal"])
        with self.assertRaises(ValueError):
            self.widget.set_group_order("kategorie")

    def test_click_folds_a_group_without_selection_and_the_state_survives_updates(self):
        group = self.widget.group_item("Alpha")
        self.assertTrue(group.isExpanded())
        self.click_item(group)
        self.assertFalse(group.isExpanded())
        self.assertEqual(self.selected, [])
        self.assertIsNone(self.widget.selected_key())
        self.widget.set_filter("Apfel")
        self.assertTrue(self.widget.group_item("Alpha").isExpanded())
        self.widget.set_filter("")
        self.assertFalse(self.widget.group_item("Alpha").isExpanded())
        self.widget.set_actions((native_action("a.2", group="Alpha"),))
        self.assertFalse(self.widget.group_item("Alpha").isExpanded())
        self.click_item(self.widget.group_item("Alpha"))
        self.assertTrue(self.widget.group_item("Alpha").isExpanded())

    def test_scale_1_50_300_stays_responsive(self):
        lab = lab_module()
        for count, limit_ms in ((1, 500), (50, 500), (300, 1000)):
            actions = lab.stress_project(count).actions
            started = time.perf_counter()
            self.widget.set_actions(actions)
            self.widget.grab()
            build = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            self.widget.set_filter("testaktion 00")
            self.widget.grab()
            search = (time.perf_counter() - started) * 1000
            self.widget.set_filter("")
            self.assertEqual(sum(1 for key in self.widget.visible_keys() if key[1] is None), count)
            self.assertLess(build, limit_ms, f"Aufbau bei {count}")
            self.assertLess(search, limit_ms, f"Suche bei {count}")


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class OfferTests(CatalogCase):
    def test_action_without_parameters_offers_none(self):
        self.widget.set_project(example_project())
        offer = self.widget.offer_for("action.multistate")
        self.assertIs(type(offer), ActionOffer)
        self.assertEqual((offer.action_id, offer.display_name, offer.action_parameter, offer.tile_image),
                         ("action.multistate", "Nativer Schalter", None, None))

    def test_action_with_two_parameters_has_exactly_two_offers_with_original_names(self):
        self.widget.set_project(example_project())
        self.assertIsNone(self.widget.offer_for("action.command"), "no general variant the SDK did not report")
        first, second = self.widget.offer_for("action.command", "first"), self.widget.offer_for("action.command", "second")
        self.assertEqual((first.action_parameter, first.display_name), ("first", "Erste Variante"))
        self.assertEqual((second.action_parameter, second.display_name), ("second", "Zweite Variante"))
        item = self.widget.item_for("action.command")
        self.assertEqual(item.childCount(), 2)
        self.assertIsNone(self.widget.offer_for("action.command", "Erste Variante"), "never derived from the label")

    def test_unusual_parameter_names_stay_untouched(self):
        names = ("p-7F3a", " mit Leerzeichen ", "scene:night/2", "Ä€-ü", "first")
        self.widget.set_actions((native_action("a.p", parameters=[parameter(name, f"Label {i}") for i, name in enumerate(names)]),))
        offers = [self.widget.offer_for("a.p", name) for name in names]
        self.assertEqual(tuple(offer.action_parameter for offer in offers), names)

    def test_offers_are_fresh_and_never_come_from_a_stale_snapshot(self):
        self.widget.set_actions((native_action("a.x", name="Alt"),))
        self.assertEqual(self.widget.offer_for("a.x").display_name, "Alt")
        self.widget.set_actions((native_action("a.x", name="Neu"),))
        self.assertEqual(self.widget.offer_for("a.x").display_name, "Neu")
        self.widget.set_actions(())
        self.assertIsNone(self.widget.offer_for("a.x"))

    def test_image_belongs_only_to_its_exact_identity(self):
        self.widget.set_project(example_project())
        self.widget.set_images({("action.command", "first"): solid(), ("action.multistate", None): solid("#00ff00")})
        self.assertFalse(self.widget.offer_for("action.command", "first").tile_image.isNull())
        self.assertIsNone(self.widget.offer_for("action.command", "second").tile_image)
        self.assertEqual(self.widget.offer_for("action.multistate").tile_image.pixelColor(0, 0), QColor("#00ff00"))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class SelectionSignalTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.widget.set_project(example_project())
        self.widget.item_for("action.command").setExpanded(True)
        self.show()

    def test_programmatic_input_never_echoes(self):
        self.widget.set_selected_action("action.multistate")
        self.widget.set_selected_action("action.command", "second")
        self.widget.set_project(example_project())
        self.widget.set_actions(example_project().actions)
        self.widget.set_filter("nativ")
        self.widget.set_filter("")
        self.widget.set_images({("action.multistate", None): solid()})
        self.widget.set_usage_counts({("action.multistate", None): 1})
        self.widget.set_group_order("name")
        self.widget.set_project(None)
        self.widget.set_project(example_project())
        self.assertEqual(self.selected, [])

    def test_mouse_selection_emits_exactly_once_and_repeat_click_not_again(self):
        self.click("action.multistate")
        self.assertEqual(len(self.selected), 1)
        self.assertEqual((self.selected[0].action_id, self.selected[0].action_parameter), ("action.multistate", None))
        self.click("action.multistate")
        self.assertEqual(len(self.selected), 1)
        self.click("action.command", "second")
        self.assertEqual(len(self.selected), 2)
        self.assertEqual(self.selected[1].action_parameter, "second")

    def test_keyboard_navigation_emits_one_selection_per_offer_and_none_for_other_rows(self):
        self.widget.set_selected_action("action.command", "first")
        self.tree.setFocus()
        self.assertEqual(self.selected, [])
        QTest.keyClick(self.tree, Qt.Key.Key_Down)
        self.assertEqual([offer.action_parameter for offer in self.selected], ["second"])
        QTest.keyClick(self.tree, Qt.Key.Key_Down)  # group title of the next group
        self.assertEqual(len(self.selected), 1)
        self.assertIsNone(self.widget.selected_key())
        QTest.keyClick(self.tree, Qt.Key.Key_Down)
        self.assertEqual(len(self.selected), 2)
        self.assertEqual(self.selected[1].action_id, "action.multistate")
        self.widget.set_selected_action("action.command", "first")
        count = len(self.selected)
        QTest.keyClick(self.tree, Qt.Key.Key_Up)  # the action row with parameters offers nothing placeable
        self.assertEqual(len(self.selected), count)
        self.assertEqual(self.widget.selected_key(), ("action.command", None))
        self.assertIsNone(self.widget.selected_offer())

    def test_action_with_parameters_selects_for_editing_only_and_opens_on_click(self):
        item = self.widget.item_for("action.command")
        self.assertTrue(item.isExpanded())
        self.click("action.command")
        self.assertEqual(self.selected, [])
        self.assertFalse(item.isExpanded())
        self.assertEqual(self.widget.selected_key(), ("action.command", None))
        self.assertTrue(self.widget.edit_button.isEnabled())
        self.click("action.command")
        self.assertTrue(item.isExpanded())
        self.assertEqual(self.selected, [])

    def test_chevron_toggles_without_selecting(self):
        item = self.widget.item_for("action.command")
        rect = self.rect_of(item)
        QTest.mouseClick(self.tree.viewport(), LEFT, NO_MOD, QPoint(rect.left() - self.tree.indentation() // 2, rect.center().y()))
        self.app.processEvents()
        self.assertFalse(item.isExpanded())
        self.assertIsNone(self.widget.selected_key())
        self.assertEqual(self.selected, [])

    def test_set_selected_action_expands_to_the_variant_and_unknown_identities_clear(self):
        self.widget.set_actions(example_project().actions)
        self.widget.item_for("action.command").setExpanded(False)
        self.widget.set_selected_action("action.command", "second")
        self.assertTrue(self.widget.item_for("action.command").isExpanded())
        self.assertEqual(self.widget.selected_offer().action_parameter, "second")
        self.assertTrue(self.widget.item_for("action.command", "second").isSelected())
        for unknown in (("action.command", "Zweite Variante"), ("action.multistate", "x"), ("nope", None), (None, None)):
            self.widget.set_selected_action("action.command", "first")
            self.widget.set_selected_action(*unknown)
            self.assertIsNone(self.widget.selected_key(), unknown)
            self.assertEqual(self.tree.selectedItems(), [])
            self.assertFalse(self.widget.edit_button.isEnabled())
        self.assertEqual(self.selected, [])

    def test_removed_action_clears_selection_without_signal_and_kept_one_is_refreshed(self):
        project = example_project()
        self.click("action.multistate")
        self.selected.clear()
        kept = tuple(replace(a, display_name="Umbenannt") if a.id == "action.multistate" else a for a in project.actions)
        self.widget.set_actions(kept)
        self.assertEqual(self.widget.selected_offer().display_name, "Umbenannt")
        self.widget.set_actions(tuple(a for a in project.actions if a.id != "action.multistate"))
        self.assertIsNone(self.widget.selected_key())
        self.assertIsNone(self.widget.selected_offer())
        self.assertFalse(self.widget.edit_button.isEnabled())
        self.assertEqual(self.selected, [])

    def test_removed_parameter_clears_only_that_variant(self):
        project = example_project()
        command = project.actions[0]
        self.widget.set_selected_action("action.command", "second")
        shorter = (replace(command, parameters=command.parameters[:1]), *project.actions[1:])
        self.widget.set_actions(shorter)
        self.assertIsNone(self.widget.selected_key())
        self.assertIsNone(self.widget.offer_for("action.command", "second"))
        self.assertIsNotNone(self.widget.offer_for("action.command", "first"))

    def test_filter_hides_a_selection_gently_and_brings_it_back(self):
        self.click("action.multistate")
        self.selected.clear()
        self.widget.set_filter("action.editor")
        self.assertFalse(self.widget.edit_button.isEnabled())
        self.assertEqual(self.tree.selectedItems(), [])
        self.widget.edit_button.click()
        self.assertEqual(self.edits, [])
        self.widget.set_filter("")
        self.assertTrue(self.widget.item_for("action.multistate").isSelected())
        self.assertTrue(self.widget.edit_button.isEnabled())
        self.assertEqual(self.selected, [])

    def test_folding_around_a_selection_emits_nothing(self):
        self.click("action.command", "first")
        self.selected.clear()
        self.widget.group_item("Native").setExpanded(False)
        self.app.processEvents()
        self.widget.group_item("Native").setExpanded(True)
        self.assertEqual(self.selected, [])
        self.assertEqual(self.widget.selected_key(), ("action.command", "first"))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class IntentTests(CatalogCase):
    def test_new_action_emits_only_create_and_changes_nothing(self):
        project = example_project()
        self.widget.set_project(project)
        keys = self.widget.visible_keys()
        before = EXAMPLE.read_bytes()
        self.widget.new_action_button.click()
        self.assertEqual((len(self.creates), self.edits, self.selected), (1, [], []))
        self.assertEqual(self.widget.visible_keys(), keys)
        self.assertEqual(EXAMPLE.read_bytes(), before)

    def test_edit_emits_only_the_native_action_id(self):
        self.widget.set_project(example_project())
        self.assertFalse(self.widget.edit_button.isEnabled())
        self.widget.set_selected_action("action.command", "first")
        self.widget.edit_button.click()
        self.widget.set_selected_action("action.command")
        self.widget.edit_button.click()
        self.widget.set_selected_action("action.editor")
        self.widget.edit_button.click()
        self.assertEqual(self.edits, ["action.command", "action.command", "action.editor"])
        self.assertEqual((self.creates, self.selected), ([], []))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class DragTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.widget.set_project(example_project())
        self.widget.item_for("action.command").setExpanded(True)
        self.show()
        self.drags = []

    def gesture(self, item):
        """Real mouse gesture; only the blocking QDrag.exec is replaced to capture its data."""
        start = self.rect_of(item).center()
        with patch.object(self.widget, "_exec_drag", lambda mime, pixmap, hotspot: self.drags.append((mime, pixmap, hotspot))):
            QTest.mousePress(self.tree.viewport(), LEFT, NO_MOD, start)
            for step in (5, 14, 40):
                QTest.mouseMove(self.tree.viewport(), start + QPoint(step, 0))
            QTest.mouseRelease(self.tree.viewport(), LEFT, NO_MOD, start + QPoint(40, 0))
        self.app.processEvents()

    def payload_of(self, index=-1) -> bytes:
        return bytes(self.drags[index][0].data(ACTION_REF_MIME))

    def test_plain_action_drag_payload_is_the_existing_codec(self):
        self.gesture(self.widget.item_for("action.adjustment"))
        self.assertEqual(len(self.drags), 1)
        self.assertEqual(self.payload_of(), encode_action_ref(self.widget.offer_for("action.adjustment")))
        self.assertEqual(decode_action_ref(self.payload_of()), ("action.adjustment", None))

    def test_each_parameter_is_a_separate_drag_with_the_original_name(self):
        self.gesture(self.widget.item_for("action.command", "first"))
        self.gesture(self.widget.item_for("action.command", "second"))
        self.assertEqual(decode_action_ref(self.payload_of(0)), ("action.command", "first"))
        self.assertEqual(decode_action_ref(self.payload_of(1)), ("action.command", "second"))

    def test_payload_holds_only_the_versioned_reference(self):
        self.widget.set_images({("action.command", "first"): solid(size=256)})
        self.gesture(self.widget.item_for("action.command", "first"))
        mime = self.drags[-1][0]
        self.assertEqual(mime.formats(), [ACTION_REF_MIME])
        self.assertEqual(ACTION_REF_MIME, "application/vnd.logi-plugin-studio.action-ref+json")
        data = json.loads(self.payload_of())
        self.assertEqual(data, {"version": 1, "action_id": "action.command", "action_parameter": "first"})
        self.assertLess(len(self.payload_of()), 200, "no image bytes")
        self.assertFalse(mime.hasImage())
        self.assertFalse(mime.hasText())
        self.assertNotIn(b"handler", self.payload_of())

    def test_drag_carries_the_pressed_entry_even_if_another_one_was_selected(self):
        self.widget.set_selected_action("action.editor")
        self.gesture(self.widget.item_for("action.command", "second"))
        self.assertEqual(decode_action_ref(self.payload_of()), ("action.command", "second"))
        self.assertEqual(self.widget.selected_key(), ("action.command", "second"))
        self.assertEqual([offer.action_parameter for offer in self.selected], ["second"])

    def test_drag_keeps_the_pressed_entry_when_the_host_moves_the_selection(self):
        self.widget.actionSelected.connect(lambda _offer: self.widget.set_selected_action("action.editor"))
        self.gesture(self.widget.item_for("action.command", "second"))
        self.assertEqual(decode_action_ref(self.payload_of()), ("action.command", "second"))
        self.assertEqual(self.widget.selected_key(), ("action.editor", None))

    def test_drag_of_the_selected_entry_emits_no_second_selection(self):
        self.click("action.multistate")
        self.gesture(self.widget.item_for("action.multistate"))
        self.assertEqual(len(self.drags), 1)
        self.assertEqual(len(self.selected), 1)

    def test_rows_without_offer_are_no_drag_source(self):
        self.gesture(self.widget.item_for("action.command"))
        self.gesture(self.widget.group_item("Native"))
        self.assertEqual(self.drags, [])
        self.assertFalse(self.widget.item_for("action.command").flags() & Qt.ItemFlag.ItemIsDragEnabled)
        self.assertFalse(self.widget.group_item("Native").flags() & Qt.ItemFlag.ItemIsDragEnabled)

    def test_stale_press_never_offers_a_removed_action(self):
        item = self.widget.item_for("action.adjustment")
        QTest.mousePress(self.tree.viewport(), LEFT, NO_MOD, self.rect_of(item).center())
        self.widget.set_actions(tuple(a for a in example_project().actions if a.id != "action.adjustment"))
        with patch.object(self.widget, "_exec_drag") as exec_drag:
            self.tree.startDrag(Qt.DropAction.CopyAction)
            self.tree.press_key = ("action.adjustment", None)
            self.tree.startDrag(Qt.DropAction.CopyAction)
        exec_drag.assert_not_called()
        QTest.mouseRelease(self.tree.viewport(), LEFT, NO_MOD, QPoint(1, 1))

    def test_real_exec_offers_only_copy_and_uses_the_visual(self):
        with patch("studio.action_catalog.widget.QDrag") as drag_class:
            self.gesture_real_exec(self.widget.item_for("action.multistate"))
        drag = drag_class.return_value
        drag.exec.assert_called_once_with(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        self.assertEqual(drag.setPixmap.call_count, 1)
        mime = drag.setMimeData.call_args.args[0]
        self.assertEqual(decode_action_ref(bytes(mime.data(ACTION_REF_MIME))), ("action.multistate", None))

    def gesture_real_exec(self, item):
        start = self.rect_of(item).center()
        QTest.mousePress(self.tree.viewport(), LEFT, NO_MOD, start)
        for step in (5, 14, 40):
            QTest.mouseMove(self.tree.viewport(), start + QPoint(step, 0))
        QTest.mouseRelease(self.tree.viewport(), LEFT, NO_MOD, start + QPoint(40, 0))

    def test_drag_visual_shows_a_readable_label_and_a_hotspot_inside(self):
        offer = self.widget.offer_for("action.command", "first")
        pixmap, hotspot = self.widget.drag_visual(offer)
        ratio = pixmap.devicePixelRatio()
        width, height = pixmap.width() / ratio, pixmap.height() / ratio
        self.assertGreater(width, 80)
        self.assertGreaterEqual(height, 36)
        self.assertTrue(0 <= hotspot.x() < width and 0 <= hotspot.y() < height)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0, "rounded corners are transparent")
        self.assertGreater(image.pixelColor(pixmap.width() // 2, pixmap.height() // 2).alpha(), 200)
        long_name = self.widget.drag_visual(ActionOffer("action.multistate", "x" * 400))[0]
        self.assertLess(long_name.width() / long_name.devicePixelRatio(), 320)

    def test_catalog_itself_accepts_no_drops(self):
        self.assertFalse(self.tree.acceptDrops())
        self.assertFalse(self.widget.acceptDrops())

    def test_real_payload_is_accepted_by_the_keypad_public_drop_input(self):
        """Integration by public drag events only; validation stays with the keypad's host."""
        self.gesture(self.widget.item_for("action.command", "second"))
        mime = self.drags[-1][0]
        keypad = KeypadPreviewWidget()
        self.addCleanup(keypad.deleteLater)
        keypad.resize(420, 460)
        keypad.set_mode("edit")
        keypad.set_edit_allowed(True)
        capability = NavigationCapability("TestDevice", "None", (0, 1))
        keypad.set_frame(KeypadFrame("ctx", "view", "rev-1", capability, (SlotData(0, "empty"), SlotData(1, "empty"))))
        keypad.show()
        QTest.qWaitForWindowExposed(keypad)
        requests = []
        keypad.editRequested.connect(requests.append)
        point = keypad.slot_rect(1).center()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            enter = QDragEnterEvent(point.toPoint(), Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
            move = QDragMoveEvent(point.toPoint(), Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
        QApplication.sendEvent(keypad, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(keypad, move)
        self.assertTrue(move.isAccepted())
        QApplication.sendEvent(keypad, QDropEvent(point, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD))
        keypad.close()
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual((request.operation, request.action_id, request.action_parameter, request.base_revision),
                         ("place", "action.command", "second", "rev-1"))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class ImageAndUsageTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.widget.set_project(example_project())
        self.show()

    def test_images_are_deep_copied_and_outlive_a_host_buffer(self):
        buffer = bytearray(b"\x00\x00\xff\xff" * (8 * 8))
        image = QImage(buffer, 8, 8, QImage.Format.Format_ARGB32)
        self.widget.set_images({("action.multistate", None): image})
        for index in range(len(buffer)):
            buffer[index] = 0
        del image
        self.assertEqual(self.widget.offer_for("action.multistate").tile_image.pixelColor(1, 1), QColor(255, 0, 0))
        self.widget.grab()

    def test_null_images_fall_back_and_wrong_types_are_refused(self):
        self.widget.set_images({("action.multistate", None): QImage()})
        self.assertIsNone(self.widget.offer_for("action.multistate").tile_image)
        with self.assertRaises(TypeError):
            self.widget.set_images({("action.multistate", None): "icon.png"})

    def test_fallback_is_neutral_and_stable_and_image_changes_only_its_row(self):
        row = self.widget.item_for("action.multistate").data(0, Qt.ItemDataRole.UserRole + 1)
        first = self.widget._icon_pixmap(row, 30, 1.0).toImage()
        other = ActionCatalogWidget()
        self.addCleanup(other.deleteLater)
        other.setPalette(self.widget.palette())
        self.assertEqual(first, other._icon_pixmap(row, 30, 1.0).toImage())
        self.widget.set_images({row.key: solid("#123456", 30)})
        with_image = self.widget._icon_pixmap(row, 30, 1.0).toImage()
        self.assertNotEqual(first, with_image)
        self.assertEqual(with_image.pixelColor(15, 15), QColor("#123456"))

    def test_fallback_covers_each_type_and_an_unknown_one(self):
        images = set()
        for sdk_type in (*ACTION_TYPES, "UnbekannterTyp"):
            self.widget.set_actions((native_action("a.t", sdk_type=sdk_type),))
            row = self.widget.item_for("a.t").data(0, Qt.ItemDataRole.UserRole + 1)
            image = self.widget._icon_pixmap(row, 30, 2.0).toImage()
            images.add(image.constBits().tobytes())
        self.assertEqual(len(images), 5)

    def test_usage_appears_only_when_the_host_reports_it(self):
        key = ("action.multistate", None)
        accessible = Qt.ItemDataRole.AccessibleTextRole
        self.assertNotIn("verwendet", self.widget.item_for(*key).data(0, accessible))
        base_image = self.widget.grab().toImage()
        self.widget.set_usage_counts({key: 3})
        self.assertIn("3-mal verwendet", self.widget.item_for(*key).data(0, accessible))
        self.assertNotEqual(base_image, self.widget.grab().toImage())
        self.widget.set_usage_counts({})
        self.assertNotIn("verwendet", self.widget.item_for(*key).data(0, accessible))
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                self.widget.set_usage_counts({key: invalid})


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class ViewTests(CatalogCase):
    def palette_of(self, window, text, accent):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
        return palette

    def test_controls_fit_a_sidebar_from_280_to_380_px(self):
        self.widget.set_project(lab_module().example_with_lab_actions())
        self.show()
        for width in (280, 320, 380):
            self.widget.resize(width, 600)
            self.app.processEvents()
            self.assertEqual(self.widget.width(), width)
            self.assertLessEqual(self.widget.minimumSizeHint().width(), 280)
            for button in (self.widget.new_action_button, self.widget.edit_button):
                self.assertGreater(button.width(), button.fontMetrics().horizontalAdvance(button.text()))
            self.assertLessEqual(self.tree.horizontalScrollBar().maximum(), 0)

    def test_hover_selection_and_focus_are_visibly_distinct_row_states(self):
        self.widget.set_project(example_project())
        self.show()
        item = self.widget.item_for("action.multistate")
        rect = self.rect_of(item)
        def row_image():
            return self.tree.viewport().grab(rect).toImage()
        idle = row_image()
        QTest.mouseMove(self.tree.viewport(), rect.center())
        self.app.processEvents()
        hover = row_image()
        self.assertNotEqual(idle, hover)
        self.click("action.multistate")
        self.tree.clearFocus()
        QTest.mouseMove(self.tree.viewport(), QPoint(2, 2))
        self.app.processEvents()
        selected = row_image()
        self.assertNotEqual(hover, selected)
        self.widget.activateWindow()
        self.tree.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        if self.tree.hasFocus():
            self.assertNotEqual(selected, row_image())

    def test_leaving_the_list_clears_hover(self):
        self.widget.set_project(example_project())
        self.show()
        QTest.mouseMove(self.tree.viewport(), self.rect_of(self.widget.item_for("action.editor")).center())
        self.assertIsNotNone(self.tree.hover_row)
        from PySide6.QtCore import QEvent
        QApplication.sendEvent(self.tree.viewport(), QEvent(QEvent.Type.Leave))
        self.assertIsNone(self.tree.hover_row)

    def test_text_contrast_in_light_and_dark_palettes(self):
        for window, text, accent in (("#1f2227", "#e8ebef", "#4a82cf"), ("#f2f3f5", "#1c1f24", "#2f6fc4")):
            palette = self.palette_of(window, text, accent)
            tones = tones_for(palette)
            self.assertGreaterEqual(contrast(tones.muted, QColor(window)), 4.5)
            self.assertGreaterEqual(contrast(tones.text, tones.selected), 4.5)
            self.assertGreaterEqual(contrast(tones.muted_selected, tones.selected), 4.5)
            self.assertGreaterEqual(contrast(tones.muted, tones.hover), 4.5)
            self.assertGreaterEqual(contrast(tones.focus, QColor(window)), 3.0)
            self.assertGreaterEqual(contrast(tones.icon_mark, tones.icon_back), 3.0)

    def test_palette_change_reaches_the_painted_rows(self):
        self.widget.set_project(example_project())
        self.show()
        row = self.widget.item_for("action.multistate").data(0, Qt.ItemDataRole.UserRole + 1)
        before = self.widget._icon_pixmap(row, 30, 1.0).toImage()
        self.widget.setPalette(self.palette_of("#f2f3f5", "#1c1f24", "#2f6fc4"))
        self.app.processEvents()
        self.assertEqual(self.widget.tones().text, QColor("#1c1f24"))
        self.assertNotEqual(before, self.widget._icon_pixmap(row, 30, 1.0).toImage())

    def test_foreign_text_is_never_interpreted_as_markup(self):
        hostile = "<img src='x'><b>Name</b>"
        action = native_action("a.h", name=hostile, description=hostile, parameters=[parameter("p<1>", hostile)])
        self.widget.set_project(NativeProject("p", hostile, (action,), (), ()))
        for text in (self.widget.item_for("a.h").toolTip(0), self.widget.item_for("a.h", "p<1>").toolTip(0)):
            self.assertNotIn("<img", text)
            self.assertIn("&lt;img", text)
        self.assertEqual(self.widget.project_label.textFormat(), Qt.TextFormat.PlainText)
        self.widget.set_filter("<nothing>")
        self.assertEqual(self.widget.empty_detail.textFormat(), Qt.TextFormat.PlainText)

    def test_long_project_name_does_not_widen_the_sidebar(self):
        self.widget.set_project(NativeProject("p", "Sehr langer Name " * 40, (native_action(),), (), ()))
        self.assertLessEqual(self.widget.minimumSizeHint().width(), 280)

    def test_keyboard_paths_to_search_and_list(self):
        self.widget.set_project(example_project())
        self.show()
        self.widget.activateWindow()
        self.widget.search_edit.setFocus()
        self.app.processEvents()
        if not self.widget.search_edit.hasFocus():
            self.skipTest("Plattform vergibt keinen Fokus")
        QTest.keyClick(self.widget.search_edit, Qt.Key.Key_Down)
        self.assertTrue(self.tree.hasFocus())
        self.assertEqual(self.selected, [])
        self.assertEqual(self.widget.search_edit.accessibleName(), "Aktionen suchen")
        self.assertEqual(self.tree.accessibleName(), "Aktionsliste")


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class LabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.lab = lab_module()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = self.lab.ActionCatalogLabWindow(Path(self.temp.name))
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def kinds(self):
        return [event["kind"] for event in self.window.events]

    def test_lab_shows_the_real_widget_with_parser_data_and_extra_parameter_actions(self):
        self.assertIs(type(self.window.catalog), ActionCatalogWidget)
        before = EXAMPLE.read_bytes()
        project = self.lab.example_with_lab_actions()
        self.assertEqual(EXAMPLE.read_bytes(), before)
        scene = next(action for action in project.actions if action.id == "lab.scene")
        self.assertEqual([p.name for p in scene.parameters], ["p-7f3a", "p-19c0", "scene:night/2"])
        self.assertEqual(self.window.catalog.offer_for("lab.scene", "scene:night/2").display_name, "Nachtmodus")

    def test_lab_does_not_pin_the_keypad_widget(self):
        source = (ROOT / "tools" / "run_action_catalog_lab.py").read_text(encoding="utf-8")
        self.assertNotIn("import KeypadPreviewWidget", source)
        self.assertNotIn("from studio.keypad_preview import", source)
        self.assertIn("from studio.keypad_preview.mime import ACTION_REF_MIME, decode_action_ref", source)

    def test_log_records_signals_with_the_original_parameter_and_intents_only(self):
        files_before = sorted(ROOT.joinpath("examples").iterdir())
        catalog = self.window.catalog
        catalog.item_for("lab.scene").setExpanded(True)
        catalog.resize(320, 900)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.app.processEvents()
        self.lab.click_row(catalog, "lab.scene", "p-7f3a")
        self.assertEqual(self.window.events[-1]["action_parameter"], "p-7f3a")
        self.assertIn("'p-7f3a'", self.window.log_view.toPlainText())
        catalog.edit_button.click()
        catalog.new_action_button.click()
        self.assertEqual(self.kinds()[-2:], ["actionEditRequested", "createActionRequested"])
        self.assertEqual(self.window.events[-2]["action_id"], "lab.scene")
        self.assertEqual(sorted(ROOT.joinpath("examples").iterdir()), files_before)

    def test_programmatic_lab_controls_do_not_produce_action_selected(self):
        self.window.select_combo.setCurrentIndex(1)
        self.window.select_button.click()
        self.window.filter_edit.setText("Beispiel")
        self.window.filter_button.click()
        self.assertNotIn("actionSelected", self.kinds())
        self.assertIsNotNone(self.window.catalog.selected_key())

    def test_sources_cover_project_lists_and_empty_states(self):
        catalog = self.window.catalog
        self.window.load_source(1)
        self.assertEqual(len(self.window.project.actions), 4)
        self.window.load_source(2)
        self.assertEqual(catalog.empty_state()[0], "Kein Projekt geöffnet")
        self.window.load_source(3)
        self.assertEqual(catalog.empty_state()[0], "Keine Aktionen")
        self.window.load_source(5)
        self.assertEqual(catalog.count_label.text(), "300 von 300 Aktionen")

    def test_import_errors_are_readable_and_leave_the_catalog_and_file_untouched(self):
        keys = self.window.catalog.visible_keys()
        cases = {"kaputt.json": b"{ kein json", "falsch.json": json.dumps({"schema_version": "x"}).encode(),
                 "binaer.json": b"\xff\xfe\x00"}
        for name, content in cases.items():
            path = Path(self.temp.name) / name
            path.write_bytes(content)
            self.window.open_project_file(path)
            self.assertIn("Import fehlgeschlagen", self.window.banner.text())
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(self.window.catalog.visible_keys(), keys)
        self.window.open_project_file(Path(self.temp.name) / "fehlt.json")
        self.assertIn("Import fehlgeschlagen", self.window.banner.text())
        self.assertEqual(self.kinds().count("importfehler"), 4)
        self.window.load_source(6)
        self.assertIn("sdk_type", self.window.banner.text())

    def test_project_file_is_read_only_through_the_parser(self):
        before = hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        self.window.open_project_file(EXAMPLE)
        self.assertEqual(self.window.catalog.project_label.full_text(), "SDK-natives Beispiel")
        self.assertEqual(hashlib.sha256(EXAMPLE.read_bytes()).hexdigest(), before)

    def test_host_options_set_images_and_usage_only_when_active(self):
        catalog = self.window.catalog
        self.assertIsNone(catalog.offer_for("action.multistate").tile_image)
        self.window.images_check.setChecked(True)
        keys = self.lab.offer_keys(self.window.project)
        self.assertIsNotNone(catalog.offer_for(*keys[0]).tile_image)
        self.assertIsNone(catalog.offer_for(*keys[1]).tile_image, "the fallback stays visible")
        accessible = Qt.ItemDataRole.AccessibleTextRole
        self.assertNotIn("verwendet", catalog.item_for(*keys[0]).data(0, accessible))
        self.window.usage_check.setChecked(True)
        self.assertIn("verwendet", catalog.item_for(*keys[0]).data(0, accessible))

    def test_neutral_target_decodes_real_payload_and_refuses_foreign_data(self):
        target = self.window.drop_target
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        offer = self.window.catalog.offer_for("lab.scene", "p-19c0")
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, encode_action_ref(offer))
        point = target.rect().center()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
            foreign = QMimeData()
            foreign.setText("action.command")
            refused = QDragEnterEvent(point, Qt.DropAction.CopyAction, foreign, LEFT, NO_MOD)
        QApplication.sendEvent(target, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(target, QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, LEFT, NO_MOD))
        self.assertEqual((self.window.events[-1]["kind"], self.window.events[-1]["action_parameter"]), ("drop", "p-19c0"))
        self.assertIn("'p-19c0'", target.status.text())
        QApplication.sendEvent(target, refused)
        self.assertFalse(refused.isAccepted())
        self.assertEqual(self.window.events[-1]["kind"], "drop-abgelehnt")

    def test_screenshots_are_written_to_the_chosen_folder(self):
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.window.shot_widget_button.click()
        self.window.shot_lab_button.click()
        shots = sorted(Path(self.temp.name).glob("*.png"))
        self.assertEqual({shot.name.split("_")[0] for shot in shots}, {"catalog", "lab"})
        self.assertTrue(all(not QImage(str(shot)).isNull() for shot in shots))

    def test_width_and_theme_controls_act_on_the_sidebar(self):
        original = QApplication.palette()
        self.addCleanup(lambda: QApplication.setPalette(original))
        self.window.width_combo.setCurrentIndex(0)
        self.assertEqual(self.window.sidebar.width(), 280)
        self.window.width_combo.setCurrentIndex(2)
        self.assertEqual(self.window.sidebar.width(), 380)
        self.window.theme_combo.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(self.window.catalog.tones().text, QColor("#1c1f24"))
        self.assertEqual(self.window.drop_target.status.palette().color(QPalette.ColorRole.WindowText), QColor("#1c1f24"))
        self.assertEqual(self.window.banner.palette().color(QPalette.ColorRole.WindowText), QColor("#1c1f24"))


class ProcessTests(unittest.TestCase):
    """Isolated processes: a native crash or a hanging OS loop must not stop the suite."""

    def run_script(self, script: str, *, timeout: int = 90) -> str:
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(ROOT / "src")], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return result.stdout

    PRELUDE = """
        import gc, json, sys
        sys.path.insert(0, sys.argv[1])
        from pathlib import Path
        from PySide6.QtCore import QPoint, Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
        from adapters.logitech.native import parse_native_project
        from studio.action_catalog import ActionCatalogWidget
        app = QApplication([])
        QTimer.singleShot(60000, lambda: sys.exit(3))
        root = Path(sys.argv[1]).parent
        project = parse_native_project(json.loads((root / "examples" / "project_logitech_native_v1.json").read_text(encoding="utf-8")))
        catalog = ActionCatalogWidget()
        catalog.set_project(project)
        catalog.item_for("action.command").setExpanded(True)
        tree = catalog.catalog_tree
    """

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_real_qdrag_exec_is_memory_safe_when_repeated(self):
        """Regression guard for the QMimeData double free seen in AP-WIDGET-001.

        A real QDrag owns real mime data here, but offscreen ``exec`` ends immediately.
        """
        output = self.run_script(self.PRELUDE + """
        catalog.resize(320, 600); catalog.show(); QTest.qWaitForWindowExposed(catalog)
        drags = []
        original = ActionCatalogWidget._exec_drag
        def counted(self, *args):
            original(self, *args)
            drags.append(True)
        ActionCatalogWidget._exec_drag = counted
        for _ in range(5):
            start = tree.visualItemRect(catalog.item_for("action.multistate")).center()
            QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
            QTest.mouseMove(tree.viewport(), start + QPoint(6, 0))
            QTest.mouseMove(tree.viewport(), start + QPoint(30, 0))
            QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(30, 0))
            gc.collect(); QTest.qWait(20); gc.collect()
            catalog.grab()
        print("drags", len(drags))
        """)
        self.assertIn("drags 5", output, "every gesture must have entered the real _exec_drag")

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_lab_smoke_mode_ends_successfully(self):
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "run_action_catalog_lab.py"), "--smoke"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=90, env=environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-2000:])
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(result.stdout.count("OK "), 4)


if __name__ == "__main__":
    unittest.main()
