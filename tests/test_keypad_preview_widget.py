"""AP-WIDGET-002: KeypadPreviewWidget, its drag references, skin and in-memory lab host.

Input is driven by real Qt events (QTest, QApplication.sendEvent) wherever Qt
allows it. Only the two blocking OS loops, QDrag.exec and QMenu.exec, are
replaced in most tests; dedicated tests run both of them for real.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import (QColor, QContextMenuEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFocusEvent, QHelpEvent,
                               QImage, QKeyEvent, QMouseEvent, QPainter)
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QToolTip

    from studio.keypad_contract import (ActionOffer, EditRequest, KeypadFrame, KeypadViewState, NavigationCapability,
                                        SlotAddress, SlotData)
    from studio.keypad_preview import ACTION_REF_MIME, KeypadPreviewWidget, encode_action_ref, load_logikeypad_skin, neutral_skin
    from studio.keypad_preview.lab_host import FOREIGN_OFFER, VIEW_ID, LabHost
    from studio.keypad_preview.mime import (MAX_PAYLOAD_BYTES, SLOT_REF_MIME, SlotRef, decode_action_ref, decode_slot_ref,
                                            encode_slot_ref)
    from studio.keypad_preview.skin import ASSET_CASE_FILE, ASSET_KEY_FILES, ASSET_KEY_RECTS, ASSET_NATIVE_SIZE, neutral_skin_for
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

LEFT = None if not HAS_QT else Qt.MouseButton.LeftButton
NO_MOD = None if not HAS_QT else Qt.KeyboardModifier.NoModifier
CTRL = None if not HAS_QT else Qt.KeyboardModifier.ControlModifier


def solid_image(color: str = "#ff0000", size: int = 64) -> "QImage":
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def make_frame(*, revision="rev-1", page_index=0, page_count=1, view_id="folder.main", nav=(), locked=(), unavailable=(),
               content=tuple(range(9)), occupied=(0, 1, 4)) -> "KeypadFrame":
    capability = NavigationCapability("TestDevice", "ButtonArea" if nav else "None", tuple(content), tuple(nav))
    slots = [SlotData(index, "sdk_navigation") for index in nav]
    for index in content:
        if index in unavailable:
            slots.append(SlotData(index, "unavailable"))
        elif index in occupied:
            slots.append(SlotData(index, "placement", f"placement.{page_index}.{index}", f"action.{index}", f"param-{index}",
                                  f"Taste {index}", editable=index not in locked, logical_position=100 + index))
        else:
            slots.append(SlotData(index, "empty", editable=index not in locked))
    return KeypadFrame("ctx", view_id, revision, capability, tuple(slots), page_index, page_count)


def rgba_bytes(image: "QImage") -> tuple[bytes, int, int]:
    converted = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = converted.width(), converted.height()
    line = converted.bytesPerLine()
    raw = bytes(converted.constBits())
    return b"".join(raw[y * line:y * line + width * 4] for y in range(height)), width, height


def diff_box(first: "QImage", second: "QImage") -> "QRectF | None":
    """Bounding box of all differing pixels in logical widget coordinates."""
    a, width, height = rgba_bytes(first)
    b, _, _ = rgba_bytes(second)
    if a == b:
        return None
    columns, rows = [], []
    for y in range(height):
        start = y * width * 4
        row_a, row_b = a[start:start + width * 4], b[start:start + width * 4]
        if row_a != row_b:
            rows.append(y)
            columns.extend(x for x in range(width) if row_a[x * 4:x * 4 + 4] != row_b[x * 4:x * 4 + 4])
    return QRectF(min(columns), min(rows), max(columns) - min(columns) + 1, max(rows) - min(rows) + 1)


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class WidgetCase(unittest.TestCase):
    SIZE = (500, 560)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = KeypadPreviewWidget()
        self.widget.resize(*self.SIZE)
        self.widget.set_motion_enabled(False)
        self.selected, self.pages, self.symbols, self.edits = [], [], [], []
        self.undos, self.redos = [], []
        self.widget.slotSelected.connect(self.selected.append)
        self.widget.pageRequested.connect(self.pages.append)
        self.widget.symbolEditRequested.connect(self.symbols.append)
        self.widget.editRequested.connect(self.edits.append)
        self.widget.undoRequested.connect(lambda: self.undos.append(True))
        self.widget.redoRequested.connect(lambda: self.redos.append(True))
        self.widget.show()
        QTest.qWaitForWindowExposed(self.widget)
        self.addCleanup(self.widget.deleteLater)
        self.addCleanup(self.widget.close)

    def editing(self):
        self.widget.set_mode("edit")
        self.widget.set_edit_allowed(True)

    def center(self, index: int) -> "QPoint":
        return self.widget.slot_rect(index).center().toPoint()

    def click(self, index: int, button=None):
        QTest.mouseClick(self.widget, button or LEFT, NO_MOD, self.center(index))

    def key(self, key, modifier=None, focus: int | None = None):
        if focus is not None:
            self.widget._set_focus_index(focus, visible=True)
        self.widget.setFocus()
        QTest.keyClick(self.widget, key, modifier if modifier is not None else NO_MOD)

    def no_intents(self):
        self.assertEqual((self.edits, self.symbols, self.undos, self.redos), ([], [], [], []))

    def menu_spy(self, trigger: str | None = None) -> dict:
        captured: dict = {"opened": 0, "actions": {}}

        def fake_exec(menu, _position):
            captured["opened"] += 1
            captured["actions"] = {a.objectName(): a for a in menu.actions() if a.objectName()}
            captured["enabled"] = {name for name, a in captured["actions"].items() if a.isEnabled()}
            if trigger:
                captured["actions"][trigger].trigger()

        patcher = patch.object(self.widget, "_exec_menu", fake_exec)
        patcher.start()
        self.addCleanup(patcher.stop)
        return captured

    def context_menu(self, index: int, reason=None):
        event = QContextMenuEvent(reason or QContextMenuEvent.Reason.Mouse, self.center(index),
                                  self.widget.mapToGlobal(self.center(index)))
        QApplication.sendEvent(self.widget, event)
        return event

    def drag_sequence(self, mime: "QMimeData", index_or_point, modifiers=None, actions=None) -> tuple[bool, bool]:
        """Enter, move and drop in Qt's delivery order. Returns (move accepted, drop accepted)."""
        position = (self.widget.slot_rect(index_or_point).center() if isinstance(index_or_point, int)
                    else QPointF(index_or_point))
        modifiers = modifiers if modifiers is not None else NO_MOD
        actions = actions if actions is not None else Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
        enter = QDragEnterEvent(position, actions, mime, LEFT, modifiers)
        QApplication.sendEvent(self.widget, enter)
        move = QDragMoveEvent(position, actions, mime, LEFT, modifiers)
        QApplication.sendEvent(self.widget, move)
        drop = QDropEvent(position, actions, mime, LEFT, modifiers)
        QApplication.sendEvent(self.widget, drop)
        return move.isAccepted(), drop.isAccepted()

    @staticmethod
    def action_mime(action_id="action.ext", parameter=None) -> "QMimeData":
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(ActionOffer(action_id, "Angebot", parameter))))
        return mime

    def internal_drag(self, index: int, drop_on, *, before_drop=None, modifiers=None):
        """Real mouse gesture up to the drag start, then real drag events to the target."""
        results = []

        def fake_exec(mime, _pixmap, _hotspot):
            if before_drop:
                before_drop()
            results.append(self.drag_sequence(mime, drop_on, modifiers))

        with patch.object(self.widget, "_exec_drag", fake_exec):
            start = self.center(index)
            QTest.mousePress(self.widget, LEFT, NO_MOD, start)
            QTest.mouseMove(self.widget, start + QPoint(QApplication.startDragDistance() + 4, 0))
        return results[0] if results else None


class ContractTests(unittest.TestCase):
    """Additive contract changes keep every earlier caller working."""

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_new_fields_default_for_existing_positional_callers(self):
        capability = NavigationCapability("Dev", "None", (0,))
        slot = SlotData(0, "placement", "placement.a", "action.a", "p", "L", None, True)
        frame = KeypadFrame("ctx", "view", "rev", capability, (slot,))
        self.assertEqual((frame.page_index, frame.page_count, slot.logical_position, slot.tooltip), (0, 1, None, ""))
        self.assertEqual(KeypadViewState(frame).mode, "preview")

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_page_values_are_validated(self):
        capability = NavigationCapability("Dev", "None", (0,))
        for page_index, page_count in ((0, 0), (1, 1), (-1, 2), (True, 2), (0, 1.0)):
            with self.subTest(page_index=page_index, page_count=page_count), self.assertRaises(ValueError):
                KeypadFrame("ctx", "view", "rev", capability, (), page_index, page_count)
        self.assertEqual(KeypadFrame("ctx", "view", "rev", capability, (), 1, 2).page_index, 1)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_logical_position_belongs_to_placements(self):
        with self.assertRaises(ValueError):
            SlotData(0, "empty", logical_position=1)
        with self.assertRaises(ValueError):
            SlotData(0, "placement", "p", "a", logical_position=-1)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_edit_request_shape_has_no_replace_or_swap(self):
        source = SlotAddress("v", 0, 0, "placement.a")
        free = SlotAddress("v", 0, 1)
        EditRequest("r", "rev", "move", source, free)
        EditRequest("r", "rev", "copy", source, free, "action.a")
        EditRequest("r", "rev", "place", None, free, "action.a")
        EditRequest("r", "rev", "remove", source)
        bad = (("swap", source, free, None), ("replace", source, free, None), ("move", None, free, None),
               ("move", source, None, None), ("move", source, source, None), ("place", None, free, None),
               ("place", source, free, "action.a"), ("remove", source, free, None), ("remove", free, None, None))
        for operation, src, target, action in bad:
            with self.subTest(operation=operation, source=src, target=target), self.assertRaises(ValueError):
                EditRequest("r", "rev", operation, src, target, action)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_transport_objects_are_frozen(self):
        address = SlotAddress("v", 0, 0)
        with self.assertRaises(AttributeError):
            address.page_index = 3
        with self.assertRaises(ValueError):
            ActionOffer("", "leer")


class DragReferenceTests(unittest.TestCase):
    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_action_reference_round_trip_excludes_image(self):
        payload = encode_action_ref(ActionOffer("action.a", "Name", "param", solid_image()))
        self.assertEqual(decode_action_ref(payload), ("action.a", "param"))
        self.assertEqual(set(json.loads(payload)), {"version", "action_id", "action_parameter"})

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_invalid_action_references_are_refused(self):
        for payload in (b"", b"\xff\xfe", b"not json", b"[]", b'"x"', b'{"action_id":"a"}',
                        b'{"version":2,"action_id":"a"}', b'{"version":true,"action_id":"a"}',
                        b'{"version":1}', b'{"version":1,"action_id":""}', b'{"version":1,"action_id":7}',
                        b'{"version":1,"component_id":"legacy"}', b'{"version":1,"action_id":"a","action_parameter":3}',
                        b"[" * 100000, b'{"version":1,"action_id":"' + b"a" * MAX_PAYLOAD_BYTES + b'"}',
                        b"\x80\x04\x95pickle"):
            with self.subTest(payload=payload[:40]):
                self.assertIsNone(decode_action_ref(payload))

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_slot_reference_round_trip_and_garbage(self):
        ref = SlotRef("inst", "ctx", "rev", SlotAddress("view", 2, 5, "placement.a"))
        self.assertEqual(decode_slot_ref(encode_slot_ref(ref)), ref)
        for payload in (b"{}", b'{"version":1,"instance":"i"}',
                        b'{"version":1,"instance":"i","context_id":"c","revision":"r","view_id":"v",'
                        b'"page_index":-1,"physical_index":0,"placement_id":"p"}'):
            self.assertIsNone(decode_slot_ref(payload))


class ModeTests(WidgetCase):
    def attempt_every_edit_path(self):
        widget = self.widget
        menu = self.menu_spy()
        widget._set_focus_index(0, visible=True)
        for key, modifier in ((Qt.Key.Key_X, CTRL), (Qt.Key.Key_C, CTRL), (Qt.Key.Key_V, CTRL), (Qt.Key.Key_Delete, NO_MOD),
                              (Qt.Key.Key_F2, NO_MOD), (Qt.Key.Key_Z, CTRL), (Qt.Key.Key_Y, CTRL),
                              (Qt.Key.Key_Z, CTRL | Qt.KeyboardModifier.ShiftModifier)):
            self.key(key, modifier)
        self.context_menu(0)
        self.context_menu(0, QContextMenuEvent.Reason.Keyboard)
        QTest.mouseClick(widget, Qt.MouseButton.MiddleButton, NO_MOD, self.center(0))
        QTest.mouseClick(widget, Qt.MouseButton.RightButton, NO_MOD, self.center(0))
        # Offer a drop past Qt's acceptDrops filter too: the handlers must refuse by themselves.
        mime = self.action_mime()
        position = widget.slot_rect(2).center()
        enter = QDragEnterEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
        widget.dragEnterEvent(enter)
        self.assertFalse(enter.isAccepted())
        move = QDragMoveEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
        widget.dragMoveEvent(move)
        self.assertFalse(move.isAccepted())
        drop = QDropEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD)
        widget.dropEvent(drop)
        self.assertFalse(drop.isAccepted())
        self.assertEqual(menu["opened"], 0)
        self.assertIsNone(widget.clipboard_state())
        self.assertFalse(any(widget.has_menu_button(i) for i in range(9)))
        self.assertFalse(widget.acceptDrops())
        # A press that moves far is no drag here.
        with patch.object(widget, "_exec_drag") as drag:
            QTest.mousePress(widget, LEFT, NO_MOD, self.center(0))
            QTest.mouseMove(widget, self.center(1))
            QTest.mouseRelease(widget, LEFT, NO_MOD, self.center(1))
        drag.assert_not_called()
        self.no_intents()

    def test_01_preview_is_default_and_blocks_every_edit_path(self):
        self.assertEqual(self.widget.mode(), "preview")
        self.assertFalse(self.widget.edit_allowed())
        self.widget.set_frame(make_frame())
        self.attempt_every_edit_path()

    def test_01_preview_blocks_edit_even_with_permission(self):
        self.widget.set_edit_allowed(True)
        self.widget.set_frame(make_frame())
        self.assertFalse(self.widget.editing_active())
        self.attempt_every_edit_path()

    def test_02_edit_mode_without_permission_blocks_every_edit_path(self):
        self.widget.set_mode("edit")
        self.widget.set_frame(make_frame())
        self.assertFalse(self.widget.editing_active())
        self.attempt_every_edit_path()

    def test_02_withdrawing_permission_ends_pending_edit_state(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.assertEqual(self.widget.clipboard_state()[0], "copy")
        self.assertTrue(self.widget.acceptDrops())
        self.widget.set_edit_allowed(False)
        self.assertIsNone(self.widget.clipboard_state())
        self.assertFalse(self.widget.acceptDrops())
        self.key(Qt.Key.Key_V, CTRL, focus=2)
        self.no_intents()

    def test_mode_is_validated_and_only_changes_through_the_api(self):
        with self.assertRaises(ValueError):
            self.widget.set_mode("testing")
        self.assertEqual(self.widget.mode(), "preview")

    def test_shortcut_override_is_claimed_only_while_editing(self):
        self.widget.set_frame(make_frame())

        def override(key, modifier) -> bool:
            event = QKeyEvent(QEvent.Type.ShortcutOverride, key, modifier)
            event.ignore()
            QApplication.sendEvent(self.widget, event)
            return event.isAccepted()

        self.assertFalse(override(Qt.Key.Key_Z, CTRL))
        self.editing()
        self.assertTrue(override(Qt.Key.Key_Z, CTRL))
        self.assertTrue(override(Qt.Key.Key_F2, NO_MOD))
        self.assertFalse(override(Qt.Key.Key_A, CTRL))

    def test_view_state_tells_the_truth_about_effective_mode(self):
        self.assertIsNone(self.widget.view_state())
        self.widget.set_frame(make_frame())
        self.widget.set_mode("edit")
        self.assertFalse(self.widget.view_state().editing_enabled)
        self.widget.set_edit_allowed(True)
        self.assertTrue(self.widget.view_state().editing_enabled)


class SlotMappingTests(WidgetCase):
    def test_03_physical_index_and_roles_map_uniquely(self):
        frame = make_frame(content=tuple(range(8)), nav=(8,), unavailable=(5,))
        self.widget.set_frame(frame)
        for index in (0, 1, 2, 3, 4, 6, 7, 8):
            self.click(index)
            self.assertEqual(self.selected[-1].physical_index, index)
            self.assertEqual(self.selected[-1].view_id, "folder.main")
        self.assertEqual(self.selected[0].placement_id, "placement.0.0")
        self.assertIsNone(self.selected[2].placement_id)
        self.assertIsNone(self.selected[-1].placement_id, "SDK navigation carries no placement")
        count = len(self.selected)
        self.click(5)
        self.assertEqual(len(self.selected), count, "unavailable slots are not clickable")
        self.no_intents()

    def test_03_navigation_is_never_assumed(self):
        self.widget.set_frame(make_frame())  # Nine content slots, no navigation reported.
        self.editing()
        self.assertTrue(all(self.widget.has_menu_button(i) for i in range(9)))
        self.assertEqual(self.widget.frame().capability.navigation_slots, ())

    def test_03_unreported_slots_are_inert(self):
        self.editing()
        self.widget.set_frame(make_frame(content=(0, 1, 2, 3), occupied=(0,)))
        rect = neutral_skin().key_rect(8)
        scale_point = self.widget._to_widget(rect).center()
        self.assertIsNone(self.widget.slot_at(scale_point))
        QTest.mouseClick(self.widget, LEFT, NO_MOD, scale_point.toPoint())
        self.assertEqual(self.selected, [])
        self.assertEqual(self.drag_sequence(self.action_mime(), scale_point), (False, False))
        self.assertEqual(self.edits, [])

    def test_03_reported_slot_without_slotdata_is_not_assumed_usable(self):
        capability = NavigationCapability("Dev", "None", (0, 1))
        self.editing()
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (SlotData(0, "empty"),)))
        self.assertTrue(self.widget.has_menu_button(0))
        self.assertFalse(self.widget.has_menu_button(1))
        self.assertIsNone(self.widget.slot_at(self.widget.slot_rect(1).center()))
        self.assertEqual(self.drag_sequence(self.action_mime(), 1), (False, False))
        self.assertEqual(self.edits, [])

    def test_03_capability_beyond_nine_slots_gets_its_own_layout(self):
        capability = NavigationCapability("Custom", "None", (2, 7, 12))
        frame = KeypadFrame("ctx", "view", "rev", capability, (SlotData(12, "empty"), SlotData(2, "empty"), SlotData(7, "empty")))
        self.widget.set_frame(frame)
        self.assertTrue(self.widget.effective_skin().covers((2, 7, 12)))
        for index in (2, 7, 12):
            self.click(index)
            self.assertEqual(self.selected[-1].physical_index, index)
        self.assertEqual(neutral_skin_for(range(9)), neutral_skin())

    def test_03_navigation_slot_cannot_be_edited_or_targeted(self):
        self.editing()
        self.widget.set_frame(make_frame(content=tuple(range(8)), nav=(8,)))
        self.assertFalse(self.widget.has_menu_button(8))
        menu = self.menu_spy()
        self.context_menu(8)
        self.assertEqual(menu["enabled"], {"keypadUndo", "keypadRedo"})
        self.assertEqual(self.drag_sequence(self.action_mime(), 8), (False, False))
        self.key(Qt.Key.Key_Delete, focus=8)
        self.key(Qt.Key.Key_F2, focus=8)
        self.no_intents()

    def test_03_navigation_index_stays_protected_whatever_its_slot_role_claims(self):
        self.editing()
        capability = NavigationCapability("Dev", "ButtonArea", (0, 1), (7, 8))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (
            SlotData(0, "placement", "placement.a", "action.a"), SlotData(1, "empty"),
            SlotData(7, "empty"), SlotData(8, "placement", "placement.b", "action.b"))))
        self.assertTrue(self.widget.has_menu_button(0))
        self.assertFalse(self.widget.has_menu_button(7))
        self.assertFalse(self.widget.has_menu_button(8))
        self.assertEqual(self.drag_sequence(self.action_mime(), 7), (False, False))
        self.key(Qt.Key.Key_Delete, focus=8)
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.key(Qt.Key.Key_V, CTRL, focus=7)
        self.assertEqual(self.edits, [])

    def test_04_identities_pass_through_unchanged_and_independent(self):
        self.editing()
        capability = NavigationCapability("Dev", "None", (3, 6))
        slot = SlotData(3, "placement", "placement.unique", "action.other", "param with spaces ÄÖ", "Label", logical_position=42)
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (slot, SlotData(6, "empty"))))
        self.key(Qt.Key.Key_C, CTRL, focus=3)
        self.key(Qt.Key.Key_V, CTRL, focus=6)
        request = self.edits[-1]
        self.assertEqual(request.source, SlotAddress("view", 0, 3, "placement.unique"))
        self.assertEqual(request.target, SlotAddress("view", 0, 6, None))
        self.assertEqual((request.action_id, request.action_parameter), ("action.other", "param with spaces ÄÖ"))
        self.assertEqual(request.base_revision, "rev")
        self.assertNotEqual(request.source.physical_index, 42, "logical_position is never output as an address")

    def test_04_tile_images_are_defensive_copies(self):
        source = solid_image("#00ff00")
        capability = NavigationCapability("Dev", "None", (0,))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (SlotData(0, "placement", "p", "a", tile_image=source),)))
        before = self.widget.grab().toImage()
        painter = QPainter(source)
        painter.fillRect(0, 0, 64, 64, QColor("#0000ff"))
        painter.end()
        self.widget.update()
        self.assertIsNone(diff_box(before, self.widget.grab().toImage()))

    def test_null_image_falls_back_to_label(self):
        capability = NavigationCapability("Dev", "None", (0,))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (SlotData(0, "placement", "p", "a", label="Text", tile_image=QImage()),)))
        self.widget.grab()


class HostedCase(WidgetCase):
    """The widget wired to the in-memory host, the way a coordinator would."""

    def wire(self, scenario="nine"):
        self.host = LabHost(scenario)
        self.decisions = []
        self.host.decisionMade.connect(self.decisions.append)
        self.host.frameChanged.connect(self.widget.set_frame)
        self.widget.editRequested.connect(self.host.submit)
        self.widget.pageRequested.connect(self.host.show_page)
        self.widget.undoRequested.connect(self.host.undo)
        self.widget.redoRequested.connect(self.host.redo)
        self.widget.set_frame(self.host.frame())
        self.editing()

    def request(self, operation, source=None, target=None, action=None, parameter=None, revision=None):
        return EditRequest("req", revision or self.host.revision, operation, source, target, action, parameter)


class EditSemanticsTests(HostedCase):
    def test_05_same_action_in_two_placements_stays_one_action(self):
        self.wire()
        mute = [p for p in self.host.placements.values() if p.action_id == "lab.action.mute"]
        self.assertEqual(len(mute), 2)
        self.assertEqual(len({p.placement_id for p in mute}), 2)
        frame_slots = [s for s in self.widget.frame().slots if s.action_id == "lab.action.mute"]
        self.assertEqual(len(frame_slots), 2)

    def test_05_copy_requests_new_placement_not_new_action(self):
        self.wire()
        actions_before = dict(self.host.actions)
        count = len(self.host.placements)
        self.key(Qt.Key.Key_C, CTRL, focus=2)  # Szene with parameter "Studio".
        self.key(Qt.Key.Key_V, CTRL, focus=4)
        request = self.edits[-1]
        self.assertEqual(request.operation, "copy")
        self.assertEqual((request.action_id, request.action_parameter), ("lab.action.scene", "Studio"))
        origin, created = self.host.placement_at(0, 2), self.host.placement_at(0, 4)
        self.assertNotEqual(created.placement_id, origin.placement_id)
        self.assertEqual((created.action_id, created.action_parameter), (origin.action_id, origin.action_parameter))
        self.assertEqual(len(self.host.placements), count + 1)
        self.assertEqual(self.host.actions, actions_before)

    def test_06_cut_without_paste_changes_nothing(self):
        self.wire()
        frame = self.widget.frame()
        before = dict(self.host.placements)
        self.key(Qt.Key.Key_X, CTRL, focus=0)
        self.assertEqual(self.widget.clipboard_state()[0], "cut")
        self.assertIs(self.widget.frame(), frame)
        self.assertEqual(self.host.placements, before)
        self.assertEqual(self.host.revision, frame.revision)
        self.key(Qt.Key.Key_Escape)
        self.assertIsNone(self.widget.clipboard_state())
        self.assertEqual(self.edits, [])

    def test_06_remove_deletes_only_the_placement_in_the_host(self):
        self.wire()
        placement = self.host.placement_at(0, 0)
        self.key(Qt.Key.Key_Delete, focus=0)
        request = self.edits[-1]
        self.assertEqual(request.operation, "remove")
        self.assertEqual(request.source.placement_id, placement.placement_id)
        self.assertNotIn(placement.placement_id, self.host.placements)
        self.assertIn(placement.action_id, self.host.actions)
        self.assertEqual([p.action_id for p in self.host.placements.values()].count(placement.action_id), 1)
        self.assertEqual(self.widget._slots[0].role, "empty")

    def test_no_hidden_success_old_slots_stay_until_a_new_frame(self):
        self.editing()
        frame = make_frame()
        self.widget.set_frame(frame)  # Nothing is connected: no host answers.
        self.key(Qt.Key.Key_Delete, focus=0)
        self.assertEqual(self.edits[-1].operation, "remove")
        self.assertIs(self.widget.frame(), frame)
        self.assertEqual(self.widget._slots[0].placement_id, "placement.0.0")

    def test_07_cut_paste_across_pages_keeps_addresses_and_revision(self):
        self.wire()
        moved = self.host.placement_at(0, 0)
        revision = self.host.revision
        self.key(Qt.Key.Key_X, CTRL, focus=0)
        QTest.mouseClick(self.widget.next_page_button, LEFT)
        self.assertEqual(self.widget.frame().page_index, 1)
        self.assertEqual(self.widget.clipboard_state()[1].page_index, 0, "clipboard survives an unchanged revision")
        self.key(Qt.Key.Key_V, CTRL, focus=1)
        request = self.edits[-1]
        self.assertEqual(request.operation, "move")
        self.assertEqual(request.base_revision, revision)
        self.assertEqual((request.source.page_index, request.source.physical_index), (0, 0))
        self.assertEqual((request.target.page_index, request.target.physical_index), (1, 1))
        self.assertEqual(self.host.placements[moved.placement_id].page, 1)
        self.assertIsNone(self.widget.clipboard_state(), "the new revision ends the clipboard")

    def test_07_changed_revision_invalidates_clipboard(self):
        self.wire()
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.host.cycle_visuals()
        self.assertIsNone(self.widget.clipboard_state())
        self.key(Qt.Key.Key_V, CTRL, focus=4)
        self.assertEqual(self.edits, [])

    def test_07_other_view_invalidates_clipboard(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.widget.set_frame(make_frame(view_id="folder.other"))
        self.assertIsNone(self.widget.clipboard_state())

    def test_07_drag_within_page_is_a_move(self):
        self.wire()
        placement = self.host.placement_at(0, 0)
        result = self.internal_drag(0, 4)
        self.assertEqual(result, (True, True))
        self.assertEqual(self.edits[-1].operation, "move")
        self.assertEqual(self.host.placements[placement.placement_id].physical_index, 4)
        self.assertEqual(self.selected, [], "a drag is no click")

    def test_07_drag_with_control_is_a_copy(self):
        self.wire()
        count = len(self.host.placements)
        self.internal_drag(0, 4, modifiers=CTRL)
        self.assertEqual(self.edits[-1].operation, "copy")
        self.assertEqual(len(self.host.placements), count + 1)

    def test_07_drag_across_pages_addresses_both_pages(self):
        self.wire()
        placement = self.host.placement_at(0, 0)
        revision = self.host.revision
        self.internal_drag(0, 1, before_drop=lambda: self.host.show_page(1))
        request = self.edits[-1]
        self.assertEqual((request.source.page_index, request.target.page_index), (0, 1))
        self.assertEqual(request.base_revision, revision)
        self.assertEqual(request.source.placement_id, placement.placement_id)
        self.assertEqual((request.action_id, request.action_parameter), (placement.action_id, placement.action_parameter))
        self.assertEqual(self.host.placements[placement.placement_id].page, 1)

    def test_07_drag_hovering_a_page_button_requests_the_page(self):
        self.wire()
        button = self.widget.next_page_button
        position = QPointF(button.mapTo(self.widget, button.rect().center()))
        mime = self.action_mime()
        QApplication.sendEvent(self.widget, QDragEnterEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD))
        QApplication.sendEvent(self.widget, QDragMoveEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD))
        self.assertEqual(self.pages, [], "no page before the hover delay")
        QTest.qWait(750)
        self.assertEqual(self.pages, [1])
        self.assertEqual(self.widget.frame().page_index, 1)
        QApplication.sendEvent(self.widget, QDropEvent(position, Qt.DropAction.CopyAction, mime, LEFT, NO_MOD))
        self.assertEqual(self.edits, [])

    def test_07_no_silent_swap_on_occupied_target(self):
        self.wire()
        before = dict(self.host.placements)
        self.assertEqual(self.internal_drag(0, 1), (False, False))
        self.assertEqual(self.drag_sequence(self.action_mime("lab.action.note"), 1), (False, False))
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.key(Qt.Key.Key_V, CTRL, focus=1)
        self.assertEqual(self.edits, [])
        self.assertEqual(self.host.placements, before)

    def test_external_offer_is_a_place_request_verified_by_the_host(self):
        self.wire()
        self.assertEqual(self.drag_sequence(self.action_mime("lab.action.scene", "Pause"), 4), (True, True))
        request = self.edits[-1]
        self.assertEqual((request.operation, request.action_id, request.action_parameter),
                         ("place", "lab.action.scene", "Pause"))
        self.assertIsNone(request.source)
        self.assertEqual(self.host.placement_at(0, 4).action_id, "lab.action.scene")

    def test_foreign_widget_slot_reference_is_not_treated_as_internal(self):
        self.editing()
        self.widget.set_frame(make_frame())
        source = SlotAddress("folder.main", 0, 0, "placement.0.0")

        def foreign_mime(instance: str) -> QMimeData:
            mime = QMimeData()
            mime.setData(SLOT_REF_MIME, QByteArray(encode_slot_ref(SlotRef(instance, "ctx", "rev-1", source))))
            return mime

        self.assertEqual(self.drag_sequence(foreign_mime("another-widget"), 2), (False, False))
        self.assertEqual(self.drag_sequence(foreign_mime(self.widget._instance), 2), (False, False),
                         "even this widget's token is void when no drag of it is running")
        results = []
        # Same source while this widget really drags it: only the foreign token differs.
        with patch.object(self.widget, "_exec_drag", lambda *_: results.append(
                self.drag_sequence(foreign_mime("another-widget"), 2))):
            start = self.center(0)
            QTest.mousePress(self.widget, LEFT, NO_MOD, start)
            QTest.mouseMove(self.widget, start + QPoint(QApplication.startDragDistance() + 4, 0))
        self.assertEqual(results, [(False, False)])
        self.assertEqual(self.edits, [])

    def test_invalid_mime_is_refused_without_any_intent(self):
        self.editing()
        self.widget.set_frame(make_frame())
        for payload in (b"garbage", b'{"version":9,"action_id":"a"}', b'{"version":1,"component_id":"a"}'):
            mime = QMimeData()
            mime.setData(ACTION_REF_MIME, QByteArray(payload))
            self.assertEqual(self.drag_sequence(mime, 2), (False, False))
        self.assertEqual(self.edits, [])

    def test_stale_drag_is_refused_when_revision_changed_during_drag(self):
        self.wire()
        self.assertEqual(self.internal_drag(0, 4, before_drop=self.host.cycle_visuals), (False, False))
        self.assertEqual(self.edits, [])

    def test_undo_redo_stay_with_the_host(self):
        self.wire()
        self.key(Qt.Key.Key_Delete, focus=0)
        self.assertEqual(self.widget._slots[0].role, "empty")
        self.key(Qt.Key.Key_Z, CTRL)
        self.assertEqual(len(self.undos), 1)
        self.assertEqual(self.widget._slots[0].role, "placement")
        self.key(Qt.Key.Key_Y, CTRL)
        self.key(Qt.Key.Key_Z, CTRL)
        self.key(Qt.Key.Key_Z, CTRL | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(self.redos), 2)
        self.assertEqual(self.widget._slots[0].role, "empty")


class ContextMenuTests(HostedCase):
    def test_menu_availability_on_placement_empty_and_locked(self):
        self.editing()
        self.widget.set_frame(make_frame(locked=(1, 3)))
        menu = self.menu_spy()
        self.context_menu(0)
        self.assertEqual(menu["enabled"], {"keypadCut", "keypadCopy", "keypadRemove", "keypadSymbol", "keypadUndo", "keypadRedo"})
        self.context_menu(2)
        self.assertEqual(menu["enabled"], {"keypadUndo", "keypadRedo"})
        self.key(Qt.Key.Key_C, CTRL, focus=0)
        self.context_menu(2)
        self.assertIn("keypadPaste", menu["enabled"])
        for locked in (1, 3):
            self.context_menu(locked)
            self.assertEqual(menu["enabled"], {"keypadUndo", "keypadRedo"})
        self.no_intents()

    def test_history_availability_is_shown_not_owned(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.widget.set_history_available(False, True)
        menu = self.menu_spy()
        self.context_menu(0)
        self.assertNotIn("keypadUndo", menu["enabled"])
        self.assertIn("keypadRedo", menu["enabled"])

    def test_three_dot_button_opens_the_same_menu(self):
        self.editing()
        self.widget.set_frame(make_frame())
        menu = self.menu_spy()
        button = self.widget.menu_button_rect(0).center().toPoint()
        QTest.mouseClick(self.widget, LEFT, NO_MOD, button)
        self.assertEqual(menu["opened"], 1)
        self.assertEqual(self.selected, [], "the menu button does not select")
        self.assertIsNone(self.widget.pressed_slot())

    def test_menu_remove_is_a_request(self):
        self.wire()
        menu = self.menu_spy(trigger="keypadRemove")
        self.context_menu(0)
        self.assertEqual(self.edits[-1].operation, "remove")
        self.assertEqual(menu["opened"], 1)

    def test_menu_undo_redo_and_symbol_only_signal(self):
        self.editing()
        self.widget.set_frame(make_frame())
        for action in ("keypadUndo", "keypadRedo", "keypadSymbol"):
            with patch.object(self.widget, "_exec_menu", lambda menu, _p, name=action: next(
                    a for a in menu.actions() if a.objectName() == name).trigger()):
                self.context_menu(0)
        self.assertEqual((len(self.undos), len(self.redos), len(self.symbols), self.edits), (1, 1, 1, []))

    def test_menu_cut_then_paste_on_empty_slot(self):
        self.wire()
        with patch.object(self.widget, "_exec_menu", lambda menu, _p: next(
                a for a in menu.actions() if a.objectName() == "keypadCut").trigger()):
            self.context_menu(0)
        self.assertEqual(self.widget.clipboard_state()[0], "cut")
        self.assertEqual(self.edits, [])
        with patch.object(self.widget, "_exec_menu", lambda menu, _p: next(
                a for a in menu.actions() if a.objectName() == "keypadPaste").trigger()):
            self.context_menu(4)
        self.assertEqual(self.edits[-1].operation, "move")

    def test_real_menu_exec_runs_and_triggers(self):
        self.wire()

        def choose():
            menu = self.widget.findChild(QMenu, "keypadSlotMenu")
            self.assertTrue(menu.isVisible())
            next(a for a in menu.actions() if a.objectName() == "keypadSymbol").trigger()
            menu.close()

        QTimer.singleShot(50, choose)
        self.context_menu(0)
        self.assertEqual(len(self.symbols), 1)
        self.assertEqual(self.symbols[0].physical_index, 0)

    def test_new_frame_closes_an_open_menu_without_an_intent(self):
        self.wire()
        reached = []

        def deliver():
            self.host.show_page(1)
            reached.append(self.widget.findChild(QMenu, "keypadSlotMenu").isVisible())

        QTimer.singleShot(50, deliver)
        QTimer.singleShot(1500, lambda: [m.close() for m in QApplication.topLevelWidgets() if isinstance(m, QMenu)])
        self.context_menu(0)
        self.assertEqual(reached, [False])
        self.assertEqual(self.edits, [])

    def test_keyboard_menu_uses_the_focused_slot(self):
        self.wire()
        menu = self.menu_spy()
        self.widget._set_focus_index(4, visible=True)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(0, 0), QPoint(0, 0))
        QApplication.sendEvent(self.widget, event)
        self.assertEqual(menu["opened"], 1)
        self.assertNotIn("keypadCut", menu["enabled"], "slot 4 is empty, the point (0, 0) irrelevant")


class FrameChangeTests(HostedCase):
    def test_08_set_frame_and_selection_send_no_requests(self):
        self.wire()
        self.widget.set_frame(self.host.frame())
        self.widget.set_selection(SlotAddress(VIEW_ID, 0, 0, "lab.placement.1"))
        self.host.show_page(1)
        self.host.show_page(0)
        self.no_intents()
        self.assertEqual(self.selected, [], "external selection emits nothing")
        self.assertEqual(self.pages, [])

    def test_08_new_frame_cancels_a_press_candidate(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        self.assertEqual(self.widget.pressed_slot(), 0)
        self.widget.set_frame(make_frame(revision="rev-2"))
        self.assertIsNone(self.widget.pressed_slot())
        self.assertEqual(self.widget.press_progress(0), 0.0)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        self.assertEqual(self.selected, [], "the release after a frame change is no click")

    def test_08_page_change_cancels_press_and_drop_highlight(self):
        self.wire()
        self.widget._drop_index = 4
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        self.host.show_page(1)
        self.assertIsNone(self.widget.pressed_slot())
        self.assertIsNone(self.widget._drop_index)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        self.assertEqual(self.selected, [])

    def test_selection_follows_placement_and_is_invalidated_safely(self):
        self.editing()
        self.widget.set_frame(make_frame(occupied=(0,)))
        self.click(0)
        self.assertEqual(self.widget.selection().physical_index, 0)
        # The same placement arrives at another key.
        capability = NavigationCapability("TestDevice", "None", tuple(range(9)))
        moved = tuple(SlotData(i, "placement", "placement.0.0", "action.0") if i == 5 else SlotData(i, "empty") for i in range(9))
        self.widget.set_frame(KeypadFrame("ctx", "folder.main", "rev-2", capability, moved))
        self.assertEqual(self.widget.selection().physical_index, 5)
        # The placement is gone.
        self.widget.set_frame(make_frame(revision="rev-3", occupied=()))
        self.assertIsNone(self.widget.selection())
        self.assertEqual(len(self.selected), 1)

    def test_selection_keeps_its_page_and_is_dropped_for_another_view(self):
        self.widget.set_frame(make_frame(page_count=2))
        self.click(0)
        address = self.widget.selection()
        self.widget.set_frame(make_frame(page_index=1, page_count=2))
        self.assertEqual(self.widget.selection(), address)
        self.assertIsNone(self.widget._selected_index(), "not drawn on the other page")
        self.widget.set_frame(make_frame(page_count=2))
        self.assertEqual(self.widget._selected_index(), 0)
        self.widget.set_frame(make_frame(view_id="other"))
        self.assertIsNone(self.widget.selection())

    def test_external_selection_of_unknown_slot_is_ignored(self):
        self.widget.set_frame(make_frame(content=(0, 1), occupied=(0,)))
        self.widget.set_selection(SlotAddress("folder.main", 0, 8))
        self.assertIsNone(self.widget.selection())
        self.widget.set_selection(SlotAddress("other", 0, 0))
        self.assertIsNone(self.widget.selection())
        with self.assertRaises(TypeError):
            self.widget.set_selection("0")

    def test_set_frame_rejects_foreign_types(self):
        with self.assertRaises(TypeError):
            self.widget.set_frame({"slots": []})

    def test_host_answering_inside_the_signal_is_safe(self):
        self.wire()
        for _ in range(4):
            self.internal_drag(0, 4)
            self.internal_drag(4, 0)
        self.assertEqual(len(self.edits), 8)
        self.assertIsNotNone(self.host.placement_at(0, 0))


class RejectionTests(HostedCase):
    def assert_rejected(self, request, code):
        placements = dict(self.host.placements)
        frame = self.widget.frame()
        revision = self.host.revision
        decision = self.host.submit(request)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.code, code)
        self.assertEqual(self.host.placements, placements)
        self.assertEqual(self.host.revision, revision)
        self.assertIs(self.widget.frame(), frame, "a rejection sends no frame, the widget stays as it was")

    def test_09_stale_revision_from_the_widget_is_rejected(self):
        self.wire()
        self.host.external_change()
        frame = self.widget.frame()
        self.key(Qt.Key.Key_Delete, focus=0)
        self.assertEqual(self.decisions[-1].code, "revision_conflict")
        self.assertIs(self.widget.frame(), frame)
        self.assertEqual(self.widget._slots[0].role, "placement")

    def test_09_foreign_action_offer_is_rejected(self):
        self.wire()
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(FOREIGN_OFFER)))
        self.assertEqual(self.drag_sequence(mime, 4), (True, True), "the widget only proposes")
        self.assertEqual(self.decisions[-1].code, "unknown_action")
        self.assertEqual(self.widget._slots[4].role, "empty")

    def test_09_parameter_not_offered_by_the_action_is_rejected(self):
        self.wire()
        self.assert_rejected(self.request("place", None, SlotAddress(VIEW_ID, 0, 4), "lab.action.scene", "Erfunden"),
                             "unknown_parameter")

    def test_09_host_rejects_crafted_requests(self):
        self.wire("locked")
        placement = self.host.placement_at(0, 0)
        source = SlotAddress(VIEW_ID, 0, 0, placement.placement_id)
        locked_source = SlotAddress(VIEW_ID, 0, 1, self.host.placement_at(0, 1).placement_id)
        cases = (
            (self.request("move", source, SlotAddress(VIEW_ID, 0, 8), revision="old"), "revision_conflict"),
            (self.request("move", source, SlotAddress(VIEW_ID, 5, 8)), "target_missing"),
            (self.request("move", source, SlotAddress(VIEW_ID, 0, 77)), "target_missing"),
            (self.request("move", source, SlotAddress("other", 0, 8)), "unknown_view"),
            (self.request("move", source, SlotAddress(VIEW_ID, 0, 4)), "target_locked"),
            (self.request("move", source, SlotAddress(VIEW_ID, 0, 6)), "target_unavailable"),
            (self.request("move", source, SlotAddress(VIEW_ID, 0, 2)), "target_occupied"),
            (self.request("move", locked_source, SlotAddress(VIEW_ID, 0, 8)), "source_locked"),
            (self.request("remove", SlotAddress(VIEW_ID, 0, 0, "placement.none")), "source_mismatch"),
            (self.request("remove", SlotAddress(VIEW_ID, 0, 3, placement.placement_id)), "source_mismatch"),
            (self.request("copy", source, SlotAddress(VIEW_ID, 0, 8), "lab.action.note"), "source_mismatch"),
        )
        for request, code in cases:
            with self.subTest(code=code):
                self.assert_rejected(request, code)

    def test_09_host_rejects_navigation_target(self):
        self.wire("navigation")
        source = SlotAddress(VIEW_ID, 0, 0, self.host.placement_at(0, 0).placement_id)
        self.assert_rejected(self.request("move", source, SlotAddress(VIEW_ID, 0, 8)), "target_navigation")

    def test_09_widget_refuses_locked_slots_itself(self):
        self.wire("locked")
        self.assertFalse(self.widget.has_menu_button(1))
        self.assertFalse(self.widget.has_menu_button(4))
        self.assertFalse(self.widget.has_menu_button(6))
        self.assertEqual(self.drag_sequence(self.action_mime("lab.action.note"), 4), (False, False))
        self.key(Qt.Key.Key_Delete, focus=1)
        self.key(Qt.Key.Key_X, CTRL, focus=1)
        with patch.object(self.widget, "_exec_drag") as drag:
            QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(1))
            QTest.mouseMove(self.widget, self.center(1) + QPoint(20, 0))
            QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(1))
        drag.assert_not_called()
        self.assertEqual(self.edits, [])
        self.assertIsNone(self.widget.clipboard_state())


class SymbolEditTests(HostedCase):
    def test_10_symbol_request_only_for_allowed_placement(self):
        self.editing()
        self.widget.set_frame(make_frame(locked=(1,)))
        self.key(Qt.Key.Key_F2, focus=0)
        self.assertEqual(self.symbols, [SlotAddress("folder.main", 0, 0, "placement.0.0")])
        for index in (1, 2):  # Locked placement, empty slot.
            self.key(Qt.Key.Key_F2, focus=index)
        self.assertEqual(len(self.symbols), 1)
        self.assertEqual(self.edits, [])

    def test_10_keypad_module_never_loads_the_designer(self):
        code = ("import sys; sys.path.insert(0, r'%s');"
                "import studio.keypad_preview;"
                "assert not [m for m in sys.modules if m.startswith('symbol_designer') or m == 'studio.app'"
                " or m.startswith(('adapters', 'runtime', 'core'))], 'forbidden import'") % (ROOT / "src")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_10_request_resolves_through_the_existing_nf16_coordinator_without_writing(self):
        from studio.native_ict_binding import NativeIctBindingError, NativeIctCoordinator

        raw = json.loads((ROOT / "examples" / "project_logitech_native_v1.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="keypad-nf16-") as temp:
            project = Path(temp) / "project.json"
            project.write_text(json.dumps(raw), encoding="utf-8")
            before = hashlib.sha256(project.read_bytes()).hexdigest()
            coordinator = NativeIctCoordinator(project)
            action = coordinator.project.actions[0]
            capability = NavigationCapability("TestDevice", "None", (4,))
            frame = KeypadFrame("ctx", "folder", "rev", capability, (SlotData(4, "placement", "placement.a", action.id),))
            self.widget.set_frame(frame)
            with self.assertRaises(NativeIctBindingError):
                coordinator.from_slot(self.widget.view_state(), 4)
            self.editing()
            self.key(Qt.Key.Key_F2, focus=4)
            binding = coordinator.from_slot(self.widget.view_state(), self.symbols[-1].physical_index)
            self.assertEqual(binding.action_id, action.id)
            self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), before)


class PaginationTests(HostedCase):
    def test_11_page_buttons_only_request(self):
        self.widget.set_frame(make_frame(page_index=1, page_count=3))
        self.assertTrue(self.widget.prev_page_button.isVisibleTo(self.widget))
        QTest.mouseClick(self.widget.next_page_button, LEFT)
        QTest.mouseClick(self.widget.prev_page_button, LEFT)
        self.assertEqual(self.pages, [2, 0])
        self.assertEqual(self.widget.frame().page_index, 1, "the frame comes from the host")
        self.assertEqual(self.widget.page_label.text(), "Seite 2 / 3")
        self.no_intents()

    def test_11_page_keys_work_in_preview_and_respect_bounds(self):
        self.widget.set_frame(make_frame(page_count=2))
        self.assertFalse(self.widget.prev_page_button.isEnabled())
        self.key(Qt.Key.Key_PageUp)
        self.assertEqual(self.pages, [])
        self.key(Qt.Key.Key_PageDown)
        self.assertEqual(self.pages, [1])

    def test_11_single_page_shows_no_pager(self):
        self.widget.set_frame(make_frame())
        self.assertFalse(self.widget.next_page_button.isVisibleTo(self.widget))
        self.key(Qt.Key.Key_PageDown)
        self.assertEqual(self.pages, [])

    def test_11_host_delivers_requested_page(self):
        self.wire()
        QTest.mouseClick(self.widget.next_page_button, LEFT)
        self.assertEqual(self.widget.frame().page_index, 1)
        self.assertEqual(self.widget.page_label.text(), "Seite 2 / 3")


class HitTestTests(WidgetCase):
    SIZES = ((170, 190), (300, 340), (500, 560), (760, 420), (420, 900), (1300, 1400))

    def test_12_all_nine_keys_hit_at_every_size(self):
        self.widget.set_frame(make_frame())
        for width, height in self.SIZES:
            self.widget.resize(width, height)
            QApplication.processEvents()
            for index in range(9):
                with self.subTest(size=(width, height), index=index):
                    self.widget.set_selection(None)
                    self.click(index)
                    self.assertEqual(self.widget.selection().physical_index, index)

    def test_12_gaps_corners_and_housing_are_not_clickable(self):
        self.widget.set_frame(make_frame())
        for width, height in self.SIZES:
            self.widget.resize(width, height)
            QApplication.processEvents()
            first, second, below = (self.widget.slot_rect(i) for i in (0, 1, 3))
            points = (QPointF((first.right() + second.left()) / 2, first.center().y()),
                      QPointF(first.center().x(), (first.bottom() + below.top()) / 2),
                      first.topLeft() + QPointF(0.5, 0.5),   # Rounded key corner.
                      QPointF(2, 2), QPointF(width - 3, height - 3))
            for point in points:
                with self.subTest(size=(width, height), point=point):
                    self.assertIsNone(self.widget.slot_at(point))
                    QTest.mouseClick(self.widget, LEFT, NO_MOD, point.toPoint())
        self.assertEqual(self.selected, [])

    def test_12_mapping_round_trip_is_exact(self):
        self.widget.set_frame(make_frame())
        self.widget.resize(733, 811)
        for index in range(9):
            native = self.widget._to_native(self.widget.slot_rect(index).center())
            self.assertAlmostEqual(native.x(), neutral_skin().key_rect(index).center().x(), places=6)
            self.assertAlmostEqual(native.y(), neutral_skin().key_rect(index).center().y(), places=6)

    def test_12_pager_reserves_room_and_hit_test_follows(self):
        self.widget.set_frame(make_frame(page_count=2))
        for index in range(9):
            self.click(index)
            self.assertEqual(self.selected[-1].physical_index, index)
        self.assertGreater(self.widget.next_page_button.mapTo(self.widget, QPoint(0, 0)).y(), self.widget.slot_rect(8).bottom())


class PressAnimationTests(WidgetCase):
    def test_13_press_scales_only_the_active_key(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        QTest.mouseMove(self.widget, self.center(4))
        QApplication.processEvents()
        before = self.widget.grab().toImage()
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(4))
        QTest.qWait(160)
        factor, offset = self.widget.key_motion(4)
        self.assertAlmostEqual(factor, 0.97, places=6)
        self.assertAlmostEqual(offset, 1.5, places=6)
        for index in set(range(9)) - {4}:
            self.assertEqual(self.widget.key_motion(index), (1.0, 0.0))
            self.assertEqual(self.widget.press_progress(index), 0.0)
        pressed = self.widget.grab().toImage()
        box = diff_box(before, pressed)
        self.assertIsNotNone(box)
        self.assertTrue(self.widget.slot_rect(4).adjusted(-2, -2, 2, 3).contains(box), f"{box} left the key")
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(4))
        QTest.qWait(220)
        self.assertEqual(self.widget.key_motion(4), (1.0, 0.0))

    def test_13_input_geometry_ignores_the_animation(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        rest = self.widget.slot_rect(4)
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(4))
        QTest.qWait(150)
        self.assertEqual(self.widget.slot_rect(4), rest)
        self.assertEqual(self.widget.slot_at(rest.topLeft() + QPointF(rest.width() * 0.02, rest.height() * 0.5)), 4)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(4))

    def test_13_reduced_motion_has_no_transform_only_a_tint(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(False)
        QTest.mouseMove(self.widget, self.center(2))
        QApplication.processEvents()
        before = self.widget.grab().toImage()
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(2))
        self.assertEqual(self.widget.key_motion(2), (1.0, 0.0))
        self.assertEqual(self.widget.press_progress(2), 1.0, "applies at once without an animation")
        box = diff_box(before, self.widget.grab().toImage())
        display = self.widget._to_widget(neutral_skin().display_rect(2)).adjusted(-1, -1, 1, 1)
        self.assertTrue(display.contains(box), f"{box} leaves the display area {display}")
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(2))
        self.assertEqual(self.widget.press_progress(2), 0.0)

    def test_13_disabling_motion_mid_press_is_safe(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(2))
        self.widget.set_motion_enabled(False)
        self.assertEqual(self.widget.key_motion(2), (1.0, 0.0))
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(2))
        self.assertEqual(self.widget.press_progress(2), 0.0)
        self.assertEqual(len(self.selected), 1)

    def test_very_short_click_still_shows_a_press_and_settles(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        seen = []
        original = self.widget._set_progress
        with patch.object(self.widget, "_set_progress", lambda i, v: (seen.append(v), original(i, v))):
            self.click(4)
            QTest.qWait(320)
        self.assertGreater(max(seen), 0.9, "the press phase ran although the click was instantaneous")
        self.assertEqual(self.widget.press_progress(4), 0.0)
        self.assertEqual(len(self.selected), 1)

    def test_fast_clicks_on_different_keys_do_not_interfere(self):
        self.widget.set_frame(make_frame())
        self.widget.set_motion_enabled(True)
        for index in (0, 1, 2, 3):
            self.click(index)
        self.assertEqual([a.physical_index for a in self.selected], [0, 1, 2, 3])
        QTest.qWait(320)
        self.assertEqual(self.widget._progress, {})
        self.assertEqual(self.widget._anims, {})

    def test_hover_selection_focus_and_press_are_independent(self):
        self.widget.set_frame(make_frame())
        self.click(0)
        QTest.mouseMove(self.widget, self.center(1))
        self.widget.setFocus()
        self.key(Qt.Key.Key_Right)
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(5))
        self.assertEqual(self.widget.selection().physical_index, 0)
        self.assertEqual(self.widget.hovered_slot(), 1)
        self.assertEqual(self.widget.pressed_slot(), 5)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(5))
        self.assertEqual(self.widget.selection().physical_index, 5)
        self.assertIsNone(self.widget.pressed_slot())


class InputCancelTests(WidgetCase):
    def test_14_release_outside_or_after_leaving_is_no_click(self):
        self.widget.set_frame(make_frame())
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        QTest.mouseMove(self.widget, self.center(1))
        self.assertIsNone(self.widget.pressed_slot(), "leaving the key cancels")
        QTest.mouseMove(self.widget, self.center(0))
        self.assertIsNone(self.widget.pressed_slot(), "coming back does not revive the click")
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(2))
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, QPoint(1, 1))
        self.assertEqual(self.selected, [])

    def test_14_escape_cancels_mouse_and_key_press(self):
        self.widget.set_frame(make_frame())
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        self.key(Qt.Key.Key_Escape)
        self.assertIsNone(self.widget.pressed_slot())
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        self.widget._set_focus_index(1, visible=True)
        QTest.keyPress(self.widget, Qt.Key.Key_Space)
        self.assertEqual(self.widget.pressed_slot(), 1)
        QTest.keyClick(self.widget, Qt.Key.Key_Escape)
        QTest.keyRelease(self.widget, Qt.Key.Key_Space)
        self.assertEqual(self.selected, [])

    def test_14_unhandled_escape_and_enter_are_passed_on_to_the_host(self):
        self.widget.set_frame(make_frame())
        for key in (Qt.Key.Key_Escape, Qt.Key.Key_Return):
            event = QKeyEvent(QEvent.Type.KeyPress, key, NO_MOD)
            QApplication.sendEvent(self.widget, event)
            self.assertFalse(event.isAccepted())

    def test_14_focus_loss_and_second_button_cancel(self):
        self.widget.set_frame(make_frame())
        self.widget.setFocus()
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        self.assertEqual(self.widget.pressed_slot(), 0)
        self.widget.clearFocus()
        self.assertIsNone(self.widget.pressed_slot())
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        QTest.mousePress(self.widget, LEFT, NO_MOD, self.center(0))
        QTest.mousePress(self.widget, Qt.MouseButton.RightButton, NO_MOD, self.center(0))
        self.assertIsNone(self.widget.pressed_slot())
        QTest.mouseRelease(self.widget, Qt.MouseButton.RightButton, NO_MOD, self.center(0))
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, self.center(0))
        self.assertEqual(self.selected, [])

    def test_14_double_click_emits_one_selection_and_no_intent(self):
        self.editing()
        self.widget.set_frame(make_frame())
        point = QPointF(self.center(0))
        # The order Qt really delivers: press, release, double click, release.
        QTest.mouseClick(self.widget, LEFT, NO_MOD, point.toPoint())
        QApplication.sendEvent(self.widget, QMouseEvent(QEvent.Type.MouseButtonDblClick, point, self.widget.mapToGlobal(point),
                                                        LEFT, LEFT, NO_MOD))
        self.assertEqual(self.widget.pressed_slot(), 0)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, point.toPoint())
        self.assertIsNone(self.widget.pressed_slot())
        self.assertEqual(len(self.selected), 1)
        self.no_intents()

    def test_14_keyboard_navigation_and_activation(self):
        self.widget.set_frame(make_frame())
        self.widget.setFocus()
        QApplication.sendEvent(self.widget, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        self.assertEqual(self.widget.focused_slot(), 0)
        self.key(Qt.Key.Key_Right)
        self.assertEqual(self.widget.focused_slot(), 1)
        self.key(Qt.Key.Key_Down)
        self.assertEqual(self.widget.focused_slot(), 4)
        self.key(Qt.Key.Key_Left)
        self.assertEqual(self.widget.focused_slot(), 3)
        self.key(Qt.Key.Key_Up)
        self.assertEqual(self.widget.focused_slot(), 0)
        self.key(Qt.Key.Key_Up)
        self.assertEqual(self.widget.focused_slot(), 0, "stays at the edge")
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.selected[-1].physical_index, 0)
        self.widget._set_focus_index(2, visible=True)
        self.key(Qt.Key.Key_Space)
        self.assertEqual(self.selected[-1].physical_index, 2)
        self.assertEqual(len(self.selected), 2)
        self.no_intents()

    def test_14_key_auto_repeat_produces_one_activation(self):
        self.widget.set_frame(make_frame())
        self.widget._set_focus_index(0, visible=True)
        self.widget.setFocus()
        for repeated in (False, True, True):
            QApplication.sendEvent(self.widget, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, NO_MOD, "", repeated))
        self.assertEqual(self.selected, [])
        QApplication.sendEvent(self.widget, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, NO_MOD))
        self.assertEqual(len(self.selected), 1)

    def test_14_keyboard_skips_unavailable_slots(self):
        self.widget.set_frame(make_frame(unavailable=(1,)))
        self.widget._set_focus_index(0, visible=True)
        self.key(Qt.Key.Key_Right)
        self.assertEqual(self.widget.focused_slot(), 2)

    def test_14_description_follows_focus_for_assistive_technology(self):
        self.widget.set_frame(make_frame(page_count=2))
        self.widget._set_focus_index(0, visible=True)
        self.assertIn("Taste 1", self.widget.accessibleDescription())
        self.assertIn("Seite 1 von 2", self.widget.accessibleDescription())
        self.editing()
        self.assertIn("Bearbeitung aktiv", self.widget.accessibleDescription())

    def test_tooltip_shows_host_text_only_on_a_slot(self):
        capability = NavigationCapability("Dev", "None", (0, 1))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (
            SlotData(0, "placement", "p", "a", label="Label", tooltip="Hilfetext"), SlotData(1, "placement", "q", "b", label="Nur Label"))))
        for index, expected in ((0, "Hilfetext"), (1, "Nur Label")):
            point = self.center(index)
            QApplication.sendEvent(self.widget, QHelpEvent(QEvent.Type.ToolTip, point, self.widget.mapToGlobal(point)))
            self.assertEqual(QToolTip.text(), expected)
        QApplication.sendEvent(self.widget, QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), self.widget.mapToGlobal(QPoint(1, 1))))
        QTest.qWait(400)  # Qt hides a tooltip after a short delay.
        self.assertFalse(QToolTip.isVisible())

    def test_frame_while_pointer_is_over_the_widget_recomputes_hover(self):
        self.widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        self.widget.set_frame(make_frame())
        self.widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        self.assertEqual(self.selected, [])

    def test_empty_widget_ignores_all_input(self):
        QTest.mouseClick(self.widget, LEFT, NO_MOD, QPoint(200, 200))
        self.key(Qt.Key.Key_Right)
        self.key(Qt.Key.Key_PageDown)
        self.widget.set_mode("edit")
        self.widget.set_edit_allowed(True)
        self.key(Qt.Key.Key_Delete)
        self.widget.grab()
        self.assertEqual(self.selected, [])
        self.no_intents()


class SkinTests(WidgetCase):
    def test_15_neutral_skin_works_without_original_files(self):
        skin, problem = load_logikeypad_skin(ROOT / "assets" / "does-not-exist")
        self.assertIsNone(skin)
        self.assertIn("fehlt", problem)
        self.widget.set_frame(make_frame())
        self.assertEqual(self.widget.effective_skin(), neutral_skin())
        self.assertFalse(self.widget.grab().isNull())

    def test_15_rendering_changes_no_project_files(self):
        watched = [p for folder in ("examples", "schemas", "component_types") for p in (ROOT / folder).rglob("*") if p.is_file()]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
        self.widget.set_frame(make_frame(page_count=2))
        self.editing()
        self.widget.grab()
        self.key(Qt.Key.Key_Delete, focus=0)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched})

    def write_skin(self, directory: Path, size=ASSET_NATIVE_SIZE) -> None:
        """Generic flat test images. They imitate no real device artwork."""
        transparent = QImage(*size, QImage.Format.Format_ARGB32)
        transparent.fill(Qt.GlobalColor.transparent)
        self.assertTrue(transparent.save(str(directory / ASSET_CASE_FILE)))
        for index, filename in ASSET_KEY_FILES.items():
            layer = QImage(*size, QImage.Format.Format_ARGB32)
            layer.fill(Qt.GlobalColor.transparent)
            painter = QPainter(layer)
            x, y, width, height = ASSET_KEY_RECTS[index]
            painter.fillRect(x + 10, y + 10, width - 20, height - 20, QColor("#505050"))
            painter.end()
            self.assertTrue(layer.save(str(directory / filename)))

    def test_optional_asset_skin_uses_alpha_for_hit_testing(self):
        with tempfile.TemporaryDirectory(prefix="keypad-skin-") as temp:
            self.write_skin(Path(temp))
            skin, problem = load_logikeypad_skin(temp)
        self.assertEqual(problem, "")
        self.assertEqual(skin.native_size, (657, 724))
        self.widget.set_skin(skin)
        self.widget.set_frame(make_frame())
        self.assertIs(self.widget.effective_skin(), skin)
        for index in range(9):
            self.click(index)
            self.assertEqual(self.selected[-1].physical_index, index)
        x, y, _, _ = ASSET_KEY_RECTS[0]
        inside_bounds_but_transparent = self.widget._to_widget(QRectF(x + 3, y + 3, 1, 1)).center()
        self.assertIsNone(self.widget.slot_at(inside_bounds_but_transparent))
        self.widget.grab()

    def test_defective_asset_files_are_reported_and_refused(self):
        with tempfile.TemporaryDirectory(prefix="keypad-skin-") as temp:
            root = Path(temp)
            self.write_skin(root)
            (root / ASSET_KEY_FILES[4]).write_bytes(b"not an image")
            skin, problem = load_logikeypad_skin(root)
            self.assertIsNone(skin)
            self.assertIn(ASSET_KEY_FILES[4], problem)
            (root / ASSET_KEY_FILES[4]).unlink()
            self.assertIn("fehlt", load_logikeypad_skin(root)[1])
        with tempfile.TemporaryDirectory(prefix="keypad-skin-") as temp:
            self.write_skin(Path(temp), (100, 100))
            self.assertIn("657", load_logikeypad_skin(temp)[1])
        with tempfile.TemporaryDirectory(prefix="keypad-skin-") as temp:
            root = Path(temp)
            self.write_skin(root)
            opaque = QImage(*ASSET_NATIVE_SIZE, QImage.Format.Format_RGB32)
            opaque.fill(QColor("#101010"))
            opaque.save(str(root / ASSET_CASE_FILE))
            self.assertIn("Alpha", load_logikeypad_skin(root)[1])

    def test_skin_not_covering_the_capability_falls_back_visibly(self):
        with tempfile.TemporaryDirectory(prefix="keypad-skin-") as temp:
            self.write_skin(Path(temp))
            skin, _ = load_logikeypad_skin(temp)
        self.widget.set_skin(skin)
        capability = NavigationCapability("Custom", "None", (12,))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (SlotData(12, "empty"),)))
        self.assertIsNot(self.widget.effective_skin(), skin)
        self.assertIn("Fallback", self.widget.skin_notice())
        self.click(12)
        self.assertEqual(self.selected[-1].physical_index, 12)

    def test_set_skin_rejects_foreign_types_and_none_is_neutral(self):
        with self.assertRaises(TypeError):
            self.widget.set_skin("neutral")
        self.widget.set_skin(None)
        self.assertEqual(self.widget.effective_skin(), neutral_skin())

    def test_neutral_geometry_is_inside_the_canvas_and_does_not_overlap(self):
        skin = neutral_skin()
        canvas = QRectF(0, 0, *skin.native_size)
        rects = [skin.key_rect(i) for i in range(9)]
        for index, rect in enumerate(rects):
            self.assertTrue(canvas.contains(rect))
            self.assertFalse(any(rect.intersects(other) for other in rects[index + 1:]))


class ProcessTests(unittest.TestCase):
    """Isolated processes: a native crash or a hanging OS loop must not stop the suite."""

    def run_script(self, script: str, *, env: dict | None = None, timeout: int = 90) -> str:
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **(env or {})}
        result = subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(ROOT / "src")], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return result.stdout

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_real_qdrag_exec_is_memory_safe_when_repeated(self):
        """Regression guard for the QMimeData double free seen in AP-WIDGET-001."""
        output = self.run_script("""
            import gc, sys
            sys.path.insert(0, sys.argv[1])
            from PySide6.QtCore import QPoint, Qt, QTimer
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from studio.keypad_contract import KeypadFrame, NavigationCapability, SlotData
            from studio.keypad_preview import KeypadPreviewWidget
            app = QApplication([])
            widget = KeypadPreviewWidget()
            widget.resize(400, 440)
            widget.set_mode("edit"); widget.set_edit_allowed(True)
            widget.set_frame(KeypadFrame("c", "v", "r", NavigationCapability("D", "None", (0, 1)),
                                         (SlotData(0, "placement", "p", "a"), SlotData(1, "empty"))))
            widget.show(); QTest.qWaitForWindowExposed(widget)
            QTimer.singleShot(45000, lambda: sys.exit(3))
            finished = 0
            drags = []
            original = KeypadPreviewWidget._exec_drag
            def counted(self, *args):
                original(self, *args)
                drags.append(True)
            KeypadPreviewWidget._exec_drag = counted
            for _ in range(5):
                start = widget.slot_rect(0).center().toPoint()
                QTimer.singleShot(60, lambda: QTest.keyClick(app.focusWidget() or widget, Qt.Key.Key_Escape))
                QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
                QTest.mouseMove(widget, start + QPoint(30, 0))
                QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
                gc.collect(); QTest.qWait(20); gc.collect()
                widget.grab()
                finished += 1
            print("finished", finished, "drags", len(drags))
        """)
        self.assertIn("finished 5 drags 5", output, "every gesture must really have entered QDrag.exec")

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_real_catalog_drag_in_the_lab_is_memory_safe(self):
        output = self.run_script("""
            import gc, importlib.util, sys
            from pathlib import Path
            root = Path(sys.argv[1]).parent
            spec = importlib.util.spec_from_file_location("lab", root / "tools" / "run_keypad_preview_lab.py")
            lab = importlib.util.module_from_spec(spec)
            sys.modules["lab"] = lab
            spec.loader.exec_module(lab)
            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            app = QApplication([])
            window = lab.KeypadLabWindow()
            window.show(); QTest.qWaitForWindowExposed(window)
            QTimer.singleShot(45000, lambda: sys.exit(3))
            window.catalog.setCurrentRow(0)
            for _ in range(4):
                QTimer.singleShot(60, lambda: QTest.keyClick(app.focusWidget() or window, Qt.Key.Key_Escape))
                window.catalog.startDrag(Qt.DropAction.CopyAction)
                gc.collect(); QTest.qWait(20); gc.collect()
            window.grab()
            print("catalog drags ok")
        """)
        self.assertIn("catalog drags ok", output)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_hidpi_scale_factor_keeps_hit_testing_and_renders_sharper(self):
        output = self.run_script("""
            import sys
            sys.path.insert(0, sys.argv[1])
            from PySide6.QtWidgets import QApplication
            from studio.keypad_contract import KeypadFrame, NavigationCapability, SlotData
            from studio.keypad_preview import KeypadPreviewWidget
            app = QApplication([])
            widget = KeypadPreviewWidget()
            widget.resize(400, 440)
            widget.set_frame(KeypadFrame("c", "v", "r", NavigationCapability("D", "None", tuple(range(9))),
                                         tuple(SlotData(i, "empty") for i in range(9))))
            widget.show()
            app.processEvents()
            image = widget.grab()
            assert widget.devicePixelRatioF() == 2.0, widget.devicePixelRatioF()
            assert image.width() == 800, image.width()
            assert all(widget.slot_at(widget.slot_rect(i).center()) == i for i in range(9))
            print("hidpi ok")
        """, env={"QT_SCALE_FACTOR": "2"})
        self.assertIn("hidpi ok", output)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_lab_starts_standalone_and_quits(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "run_keypad_preview_lab.py"), "--smoke", "0.3"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_lab_evidence_walkthrough_passes(self):
        with tempfile.TemporaryDirectory(prefix="keypad-lab-") as temp:
            result = subprocess.run([sys.executable, str(ROOT / "tools" / "run_keypad_preview_lab.py"), "--evidence", temp],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
            self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
            report = json.loads((Path(temp) / "lab_walkthrough_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["passed"], report["total"])
            self.assertGreater(len(list((Path(temp) / "screenshots").glob("*.png"))), 15)


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class LabWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        spec = importlib.util.spec_from_file_location("run_keypad_preview_lab", ROOT / "tools" / "run_keypad_preview_lab.py")
        cls.lab = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.lab
        spec.loader.exec_module(cls.lab)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keypad-lab-")
        self.addCleanup(self.temp.cleanup)
        self.window = self.lab.KeypadLabWindow(Path(self.temp.name))
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def test_lab_uses_the_real_widget_and_starts_in_preview(self):
        self.assertIsInstance(self.window.keypad, KeypadPreviewWidget)
        self.assertEqual(self.window.keypad.mode(), "preview")
        self.assertIn("VORSCHAU", self.window.mode_banner.text())

    def test_edit_and_permission_are_separate_and_shown(self):
        self.window.edit_radio.setChecked(True)
        self.assertFalse(self.window.keypad.editing_active())
        self.assertIn("Berechtigung fehlt", self.window.mode_banner.text())
        self.window.allow_check.setChecked(True)
        self.assertTrue(self.window.keypad.editing_active())
        self.assertIn("BEARBEITEN", self.window.mode_banner.text())
        self.window.preview_radio.setChecked(True)
        self.assertFalse(self.window.keypad.editing_active())

    def test_catalog_drop_and_foreign_offer_show_the_host_decision(self):
        self.window.edit_radio.setChecked(True)
        self.window.allow_check.setChecked(True)
        keypad, catalog = self.window.keypad, self.window.catalog
        self.lab._drop_offer(keypad, catalog, catalog.offers[0], 4)
        self.assertIn("übernommen", self.window.host_banner.text())
        self.assertEqual(keypad._slots[4].role, "placement")
        self.lab._drop_offer(keypad, catalog, catalog.offers[-1], 6)
        self.assertIn("abgelehnt", self.window.host_banner.text())
        self.assertEqual(keypad._slots[6].role, "empty")

    def test_every_scenario_builds_a_valid_frame_and_only_simulated_data(self):
        for row in range(self.window.scenario_combo.count()):
            self.window.scenario_combo.setCurrentIndex(row)
            self.assertFalse(self.window.keypad.grab().isNull())
            self.assertEqual(self.window.keypad.frame().revision, self.window.host.revision)
            self.assertIn("simuliert", self.window.scenario_combo.currentText())

    def test_missing_skin_files_show_the_neutral_fallback(self):
        with patch.object(self.lab, "SKIN_DIRECTORY", Path(self.temp.name) / "missing"):
            self.window.skin_combo.setCurrentIndex(1)
        self.assertIn("Neutraler Fallback", self.window.skin_notice.text())
        self.assertEqual(self.window.keypad.effective_skin(), neutral_skin())

    def test_zoom_fixed_and_fit(self):
        self.window.zoom_combo.setCurrentIndex(self.window.zoom_combo.findData(0.5))
        fixed = self.window.keypad.size()
        self.assertEqual(fixed.width(), round(self.window.keypad.effective_skin().native_size[0] * 0.5))
        self.window.zoom_combo.setCurrentIndex(0)
        self.assertEqual(self.window.keypad.maximumWidth(), 16777215)

    def test_log_export_contains_only_harmless_lab_data(self):
        self.window.keypad.setFocus()
        QTest.mouseClick(self.window.keypad, LEFT, NO_MOD, self.window.keypad.slot_rect(0).center().toPoint())
        path = Path(self.temp.name) / "log.json"
        self.window.write_log(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["simulated_host"])
        self.assertTrue(any(event["signal"] == "slotSelected" for event in data["events"]))
        self.assertNotIn(str(Path.home()), path.read_text(encoding="utf-8"))

    def test_catalog_mime_has_only_the_reference(self):
        offer = self.window.catalog.offers[0]
        self.assertIsNotNone(offer.tile_image)
        mime = self.window.catalog.offer_mime(offer)
        self.assertEqual(mime.formats(), [ACTION_REF_MIME])
        self.assertFalse(mime.hasImage())
        self.assertLess(len(bytes(mime.data(ACTION_REF_MIME))), 200)


if __name__ == "__main__":
    unittest.main()
