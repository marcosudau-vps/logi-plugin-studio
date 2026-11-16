"""AP-WIDGET-002 v0.2: device layer stack, hardware arrows, page bar and visual states.

Most tests use generated flat layers, so they run without the user's artwork. Tests
marked by RealAssetTests use the original PNGs and reference screenshots; they skip
visibly on a machine without them. No test edits or copies those files.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, QRect, Qt
    from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QHelpEvent, QImage, QMouseEvent, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolTip

    from studio.keypad_contract import ActionOffer, KeypadFrame, NavigationCapability, SlotData
    from studio.keypad_preview import ACTION_REF_MIME, KeypadPreviewWidget, encode_action_ref, load_logikeypad_skin, neutral_skin
    from studio.keypad_preview.lab_host import VISUAL_FUNCTION, VISUAL_REFERENCE, LabHost, render_reference_tile, REFERENCE_ACTIONS
    from studio.keypad_preview.skin import (ASSET_ARROW_RECTS, ASSET_CASE_FILE, ASSET_DIRECTORY_ENV, ASSET_KEY_FILES, ASSET_KEY_RECTS,
                                            ASSET_LCD_FILE, ASSET_NATIVE_SIZE, find_logikeypad_directory)
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

LEFT = None if not HAS_QT else Qt.MouseButton.LeftButton
NO_BUTTON = None if not HAS_QT else Qt.MouseButton.NoButton
NO_MOD = None if not HAS_QT else Qt.KeyboardModifier.NoModifier
REFERENCES = ROOT.parent / "graphics_pictures" / "KeypadPreviewWidget"
REFERENCE_OFFSET = (106, 33)
GREY = "#606060"
CASE = "#404040"
BACKDROP = (0x1a, 0x1a, 0x1a)


def write_device_layers(directory: Path, *, black: bool = True, size=None) -> None:
    """Generic flat test layers. They imitate no real device artwork."""
    size = size or ASSET_NATIVE_SIZE
    case = QImage(*size, QImage.Format.Format_ARGB32)
    case.fill(QColor(CASE))
    painter = QPainter(case)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    for rect in ASSET_KEY_RECTS.values():
        painter.fillRect(*rect, Qt.GlobalColor.transparent)
    painter.end()
    assert case.save(str(directory / ASSET_CASE_FILE))
    for index, name in ASSET_KEY_FILES.items():
        layer = QImage(*size, QImage.Format.Format_ARGB32)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.fillRect(*ASSET_KEY_RECTS[index], QColor(GREY))
        painter.end()
        assert layer.save(str(directory / name))
    if black:
        lcd = QImage(*size, QImage.Format.Format_ARGB32)
        lcd.fill(Qt.GlobalColor.transparent)
        painter = QPainter(lcd)
        for rect in ASSET_KEY_RECTS.values():
            painter.fillRect(*rect, QColor("#000000"))
        painter.end()
        assert lcd.save(str(directory / ASSET_LCD_FILE))


def black_tile(color="#ffffff") -> "QImage":
    image = QImage(132, 132, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    painter.fillRect(50, 20, 30, 30, QColor(color))
    painter.end()
    return image


def make_frame(*, page_index=0, page_count=1, revision="rev", tile=True, label="Aktion", occupied=(0, 1, 2, 5, 7, 8)) -> "KeypadFrame":
    capability = NavigationCapability("TestDevice", "None", tuple(range(9)))
    slots = tuple(SlotData(i, "placement", f"placement.{i}", f"action.{i}", None, label, black_tile() if tile else None)
                  if i in occupied else SlotData(i, "empty") for i in range(9))
    return KeypadFrame("ctx", "view", revision, capability, slots, page_index, page_count)


def pixel(image: "QImage", x: float, y: float) -> tuple[int, int, int]:
    color = image.pixelColor(round(x), round(y))
    return color.red(), color.green(), color.blue()


def diff_box(first: "QImage", second: "QImage") -> "QRect | None":
    a, b = first.convertToFormat(QImage.Format.Format_ARGB32), second.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, line = a.width(), a.height(), a.bytesPerLine()
    raw_a, raw_b = bytes(a.constBits()), bytes(b.constBits())
    if raw_a == raw_b:
        return None
    columns, rows = [], []
    for y in range(height):
        row_a, row_b = raw_a[y * line:y * line + width * 4], raw_b[y * line:y * line + width * 4]
        if row_a != row_b:
            rows.append(y)
            columns.extend(x for x in range(width) if row_a[x * 4:x * 4 + 4] != row_b[x * 4:x * 4 + 4])
    return QRect(min(columns), min(rows), max(columns) - min(columns) + 1, max(rows) - min(rows) + 1)


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class DeviceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.folder = tempfile.TemporaryDirectory(prefix="keypad-layers-")
        write_device_layers(Path(cls.folder.name))
        cls.skin, problem = load_logikeypad_skin(cls.folder.name)
        assert cls.skin is not None, problem

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.widget = KeypadPreviewWidget()
        self.widget.set_skin(self.skin)
        self.widget.set_motion_enabled(False)
        self.widget.resize(self.widget.size_for_scale(1.0))
        self.selected, self.pages, self.created, self.edits, self.symbols = [], [], [], [], []
        self.widget.slotSelected.connect(self.selected.append)
        self.widget.pageRequested.connect(self.pages.append)
        self.widget.pageCreateRequested.connect(lambda: self.created.append(True))
        self.widget.editRequested.connect(self.edits.append)
        self.widget.symbolEditRequested.connect(self.symbols.append)
        self.widget.show()
        QTest.qWaitForWindowExposed(self.widget)
        self.addCleanup(self.widget.deleteLater)
        self.addCleanup(self.widget.close)

    def grab(self) -> "QImage":
        QApplication.processEvents()
        return self.widget.grab().toImage()

    def editing(self):
        self.widget.set_mode("edit")
        self.widget.set_edit_allowed(True)

    def move(self, position) -> None:
        position = QPointF(position)
        QApplication.sendEvent(self.widget, QMouseEvent(QEvent.Type.MouseMove, position, self.widget.mapToGlobal(position),
                                                        NO_BUTTON, NO_BUTTON, NO_MOD))

    def click(self, position) -> None:
        QTest.mouseClick(self.widget, LEFT, NO_MOD, QPointF(position).toPoint())

    def lcd_point(self, index: int, fx: float = 0.5, fy: float = 0.9) -> "QPointF":
        rect = self.widget.slot_rect(index)
        return QPointF(rect.left() + rect.width() * fx, rect.top() + rect.height() * fy)


class AssetDiscoveryTests(unittest.TestCase):
    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory(prefix="keypad-find-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()

    def populate(self, folder: Path) -> Path:
        folder.mkdir(parents=True)
        (folder / ASSET_CASE_FILE).write_bytes(b"x")
        return folder

    def test_order_is_environment_project_then_sibling(self):
        sibling = self.populate(self.root.parent / "graphics_pictures" / "KeypadPreviewWidget" / "graphics_logi_keypad")
        self.assertEqual(find_logikeypad_directory(self.root, {}), sibling)
        project = self.populate(self.root / "assets" / "ui" / "keypad" / "logikeypad")
        self.assertEqual(find_logikeypad_directory(self.root, {}), project)
        other = self.populate(Path(self.temp.name) / "elsewhere")
        self.assertEqual(find_logikeypad_directory(self.root, {ASSET_DIRECTORY_ENV: str(other)}), other)

    def test_without_any_folder_the_project_path_comes_back_for_a_precise_message(self):
        found = find_logikeypad_directory(self.root, {})
        self.assertEqual(found, self.root / "assets" / "ui" / "keypad" / "logikeypad")
        skin, problem = load_logikeypad_skin(found)
        self.assertIsNone(skin)
        self.assertIn("fehlt", problem)

    def test_complete_incomplete_and_defective_states(self):
        folder = Path(self.temp.name) / "layers"
        folder.mkdir()
        write_device_layers(folder)
        skin, problem = load_logikeypad_skin(folder)
        self.assertEqual(problem, "")
        self.assertEqual((skin.notice, skin.source_directory, skin.native_size), ("", str(folder), (657, 724)))
        self.assertEqual(len(skin.key_images), 9)
        self.assertEqual(len(skin.gloss_images), 9)
        self.assertEqual(set(skin.arrow_rects), {-1, 1})
        (folder / ASSET_LCD_FILE).write_bytes(b"defect")
        skin, problem = load_logikeypad_skin(folder)
        self.assertIsNone(skin)
        self.assertIn(ASSET_LCD_FILE, problem)
        (folder / ASSET_LCD_FILE).unlink()
        skin, problem = load_logikeypad_skin(folder)
        self.assertEqual(problem, "")
        self.assertIn(ASSET_LCD_FILE, skin.notice, "a missing LCD layer must be reported, not hidden")
        (folder / ASSET_KEY_FILES[0]).unlink()
        skin, problem = load_logikeypad_skin(folder)
        self.assertIsNone(skin)
        self.assertIn(ASSET_KEY_FILES[0], problem)

    def test_the_widget_itself_never_searches_for_files(self):
        with patch("studio.keypad_preview.skin.find_logikeypad_directory") as find, patch(
                "studio.keypad_preview.skin.load_logikeypad_skin") as load:
            widget = KeypadPreviewWidget()
            widget.set_frame(make_frame())
            widget.grab()
        find.assert_not_called()
        load.assert_not_called()
        self.assertEqual(widget.effective_skin(), neutral_skin())
        widget.deleteLater()


class LayerStackTests(DeviceCase):
    def test_occupied_black_and_empty_grey_on_the_same_frame(self):
        self.widget.set_frame(make_frame())
        image = self.grab()
        for index in (0, 1, 2, 5, 7, 8):
            self.assertLess(max(pixel(image, *self.lcd_point(index).toTuple())), 12, f"slot {index} must be a black LCD")
        for index in (3, 4, 6):
            self.assertEqual(pixel(image, *self.lcd_point(index).toTuple()), (0x60, 0x60, 0x60), f"slot {index} must be a grey key")

    def test_white_layer_is_never_loaded_and_no_key_layer_covers_occupied_slots(self):
        self.widget.set_frame(make_frame(occupied=tuple(range(9))))
        image = self.grab()
        for index in range(9):
            self.assertNotEqual(pixel(image, *self.lcd_point(index).toTuple()), (0x60, 0x60, 0x60))

    def test_states_do_not_replace_the_occupied_or_empty_base(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.move(self.widget.slot_rect(3).center())
        self.click(self.widget.slot_rect(0).center())
        self.move(self.widget.slot_rect(3).center())
        image = self.grab()
        hovered = pixel(image, *self.lcd_point(3).toTuple())
        self.assertGreater(hovered[1], hovered[0], "hover adds the turquoise tint")
        self.assertGreater(hovered[0], 40, "the grey key still shines through")
        self.assertLess(max(pixel(image, *self.lcd_point(0).toTuple())), 12, "selection adds a ring, no fill")

    def test_case_is_painted_unchanged_at_full_size(self):
        self.widget.set_frame(make_frame())
        image = self.grab()
        for x, y in ((60, 60), (600, 100), (330, 680), (450, 600)):
            self.assertEqual(pixel(image, x, y), (0x40, 0x40, 0x40))
        self.assertEqual(pixel(image, 5, ASSET_NATIVE_SIZE[1] + 20), BACKDROP, "the dark surrounding belongs to the device view")

    def test_tile_is_inside_the_lcd_and_on_top_of_the_case_edge(self):
        self.widget.set_frame(make_frame())
        image = self.grab()
        x, y, width, _ = ASSET_KEY_RECTS[1]
        self.assertEqual(pixel(image, x - 2, y + 60), (0, 0, 0), "occupied LCD covers the cut-out's edge")
        x, y, width, _ = ASSET_KEY_RECTS[4]
        self.assertEqual(pixel(image, x - 2, y + 60), (0x40, 0x40, 0x40), "an empty key does not")

    def test_finished_tile_gets_no_second_label(self):
        self.widget.set_frame(make_frame(label="Erster Text"))
        first = self.grab()
        self.widget.set_frame(make_frame(label="Ganz anderer Text"))
        self.assertIsNone(diff_box(first, self.grab()))

    def test_text_only_slot_is_small_and_stays_inside_its_key(self):
        self.widget.set_frame(make_frame(tile=False, label="", occupied=()))
        empty = self.grab()
        capability = NavigationCapability("TestDevice", "None", tuple(range(9)))
        slots = tuple(SlotData(i, "placement", "p", "a", label="Helligkeit -10 %") if i == 7 else SlotData(i, "empty") for i in range(9))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, slots))
        box = diff_box(empty, self.grab())
        key = QRect(*ASSET_KEY_RECTS[7]).adjusted(-3, -3, 3, 3)
        self.assertTrue(key.contains(box), f"{box} leaves {key}")
        lit = self.grab()
        rows = [y for y in range(key.top() + 20, key.bottom() - 20) if any(pixel(lit, x, y)[0] > 150 for x in range(key.left() + 6, key.right() - 6, 2))]
        self.assertLess(len(rows), 26, "one small line of text, not large letters across the key")

    def test_unreported_and_unavailable_slots_are_dimmed_not_black(self):
        capability = NavigationCapability("TestDevice", "None", (0, 1))
        self.widget.set_frame(KeypadFrame("ctx", "view", "rev", capability, (SlotData(0, "empty"), SlotData(1, "unavailable"))))
        image = self.grab()
        free = pixel(image, *self.lcd_point(0).toTuple())
        unavailable = pixel(image, *self.lcd_point(1, fy=0.1).toTuple())
        unreported = pixel(image, *self.lcd_point(8).toTuple())
        self.assertLess(unavailable[0], free[0])
        self.assertLess(unreported[0], free[0])
        self.assertGreater(unreported[0], 0)


class GeometryTests(DeviceCase):
    SIZES = ((260, 300), (394, 497), (500, 500), (657, 829), (900, 700), (1400, 1600))

    def test_scaling_is_proportional_and_targets_match_the_keys(self):
        self.widget.set_frame(make_frame())
        for width, height in self.SIZES:
            self.widget.resize(width, height)
            QApplication.processEvents()
            scale, x, y = self.widget._canvas()
            for index, (kx, ky, kw, kh) in ASSET_KEY_RECTS.items():
                rect = self.widget.slot_rect(index)
                self.assertAlmostEqual(rect.width() / kw, scale, places=6)
                self.assertAlmostEqual(rect.height() / kh, scale, places=6)
                self.assertEqual(self.widget.slot_at(rect.center()), index)
            first, second = self.widget.slot_rect(0), self.widget.slot_rect(1)
            self.assertIsNone(self.widget.slot_at(QPointF((first.right() + second.left()) / 2, first.center().y())))
            self.assertGreaterEqual(x, -1)
            self.assertLessEqual(y + ASSET_NATIVE_SIZE[1] * scale, height + 1)

    def test_size_for_scale_gives_exactly_that_scale(self):
        self.widget.set_frame(make_frame())
        for scale in (0.5, 0.6, 0.75, 1.0, 1.25):
            self.widget.resize(self.widget.size_for_scale(scale))
            self.assertAlmostEqual(self.widget._canvas()[0], scale, places=2)

    def test_page_bar_sits_below_the_device_centred_on_the_housing(self):
        self.widget.set_frame(make_frame(page_count=7))
        QApplication.processEvents()
        bar = self.widget.page_bar
        top_left = bar.mapTo(self.widget, QPoint(0, 0))
        self.assertGreaterEqual(top_left.y(), ASSET_NATIVE_SIZE[1])
        self.assertAlmostEqual(top_left.x() + bar.width() / 2, 331, delta=2)
        self.assertLessEqual(top_left.y() + bar.height(), self.widget.height())


class HardwareArrowTests(DeviceCase):
    def test_arrows_only_request_pages_and_hold_no_state(self):
        frame = make_frame(page_index=1, page_count=3)
        self.widget.set_frame(frame)
        self.click(self.widget.arrow_rect(1).center())
        self.click(self.widget.arrow_rect(-1).center())
        self.assertEqual(self.pages, [2, 0])
        self.assertIs(self.widget.frame(), frame)
        self.assertEqual((self.selected, self.edits), ([], []))

    def test_arrows_respect_page_bounds_and_single_page(self):
        self.widget.set_frame(make_frame(page_index=0, page_count=2))
        self.click(self.widget.arrow_rect(-1).center())
        self.assertEqual(self.pages, [])
        self.move(self.widget.arrow_rect(-1).center())
        self.assertIsNone(self.widget.hovered_arrow())
        self.widget.set_frame(make_frame(page_count=1))
        self.click(self.widget.arrow_rect(1).center())
        self.assertEqual(self.pages, [])

    def test_release_elsewhere_cancels_and_new_frame_clears_press(self):
        self.widget.set_frame(make_frame(page_count=3))
        arrow = self.widget.arrow_rect(1).center().toPoint()
        QTest.mousePress(self.widget, LEFT, NO_MOD, arrow)
        self.assertEqual(self.widget.pressed_arrow(), 1)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, QPoint(3, 3))
        self.assertEqual(self.pages, [])
        QTest.mousePress(self.widget, LEFT, NO_MOD, arrow)
        self.widget.set_frame(make_frame(page_index=1, page_count=3))
        self.assertIsNone(self.widget.pressed_arrow())
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, arrow)
        self.assertEqual(self.pages, [])

    def test_hover_tints_only_the_arrow_and_shows_the_tooltip(self):
        self.widget.set_frame(make_frame(page_count=3))
        self.move(QPoint(3, 3))
        before = self.grab()
        center = self.widget.arrow_rect(1).center()
        self.move(center)
        self.assertEqual(self.widget.hovered_arrow(), 1)
        tip = self.widget._arrow_tip
        self.assertTrue(tip.isVisible())
        self.assertEqual(tip.text(), "Nächste Seite")
        self.assertFalse(tip.geometry().intersects(self.widget.arrow_rect(1).toAlignedRect()))
        hovered = self.grab()
        tinted = pixel(hovered, center.x() + 30, center.y() + 20)
        self.assertGreater(tinted[1], tinted[0] + 20, "turquoise tint")
        tip.hide()
        box = diff_box(before, self.grab())
        arrow = self.widget.arrow_rect(1).adjusted(-2, -2, 2, 2).toAlignedRect()
        self.assertTrue(arrow.contains(box), f"{box} leaves the arrow {arrow}")
        self.move(QPoint(3, 3))
        self.assertIsNone(self.widget.hovered_arrow())
        self.assertFalse(tip.isVisible())

    def test_previous_tooltip_never_covers_its_arrow_in_a_tight_widget(self):
        self.widget.set_frame(make_frame(page_index=1, page_count=3))
        for scale in (0.6, 1.0):
            self.widget.resize(self.widget.size_for_scale(scale))
            self.move(self.widget.arrow_rect(-1).center())
            tip = self.widget._arrow_tip
            self.assertEqual(tip.text(), "Vorherige Seite")
            self.assertFalse(tip.geometry().intersects(self.widget.arrow_rect(-1).toAlignedRect()))
            self.assertTrue(self.widget.rect().contains(tip.geometry()))
            self.move(QPoint(3, 3))

    def test_arrow_paths_do_not_touch_keys_and_page_controls_are_replaced(self):
        self.widget.set_frame(make_frame(page_count=3))
        self.assertTrue(self.widget.physical_arrows_available())
        self.assertFalse(self.widget.next_page_button.isVisibleTo(self.widget), "hardware arrows replace the page buttons")
        self.assertIsNone(self.widget.slot_at(self.widget.arrow_rect(1).center()))
        for rect in ASSET_ARROW_RECTS.values():
            self.assertFalse(any(QRect(*rect).intersects(QRect(*key)) for key in ASSET_KEY_RECTS.values()))

    def test_neutral_skin_has_no_arrows_and_keeps_its_page_buttons(self):
        self.widget.set_skin(None)
        self.widget.set_frame(make_frame(page_count=3))
        self.assertFalse(self.widget.physical_arrows_available())
        self.assertTrue(self.widget.next_page_button.isVisibleTo(self.widget))
        self.assertIsNone(self.widget._usable_arrow_at(QPointF(300, 560)))


class PageBarTests(DeviceCase):
    def texts(self):
        return [cell.text for cell in self.widget.page_bar.cells()]

    def click_cell(self, cell):
        QTest.mouseClick(self.widget.page_bar, LEFT, NO_MOD, cell.rect.center().toPoint())

    def test_page_counts_come_from_the_frame(self):
        expected = {3: ["Seiten", "1", "2", "3"], 7: ["Seiten", "1", "2", "3", "4", "5", "6", "7"]}
        for count, cells in expected.items():
            self.widget.set_frame(make_frame(page_count=count))
            self.assertEqual(self.texts(), cells)
            self.assertTrue(self.widget.page_bar.isVisibleTo(self.widget))

    def test_single_page_in_preview_shows_no_bar(self):
        self.widget.set_frame(make_frame(page_count=1))
        self.assertFalse(self.widget.page_bar.isVisibleTo(self.widget))
        self.editing()
        self.assertEqual(self.texts(), ["Seiten", "1", "+"])
        self.assertTrue(self.widget.page_bar.isVisibleTo(self.widget))

    def test_many_pages_shorten_but_keep_first_last_and_active(self):
        for count, active in ((10, 0), (10, 5), (30, 15), (30, 29), (200, 100)):
            self.widget.set_frame(make_frame(page_index=active, page_count=count))
            cells = self.widget.page_bar.cells()
            pages = [cell.page for cell in cells if cell.kind == "page"]
            for needed in (0, active, count - 1):
                self.assertIn(needed, pages)
            self.assertEqual(pages, sorted(pages))
            self.assertLessEqual(self.widget.page_bar.width(), self.widget.width())

    def test_gaps_mark_every_jump_and_do_nothing_when_clicked(self):
        self.widget.resize(self.widget.size_for_scale(0.75))
        self.widget.set_frame(make_frame(page_index=15, page_count=30))
        cells = self.widget.page_bar.cells()
        gaps = [cell for cell in cells if cell.kind == "gap"]
        self.assertTrue(gaps, "30 pages cannot fit here")
        pages = [cell for cell in cells if cell.kind in ("page", "gap")]
        for before, after in zip(pages, pages[1:]):
            if before.kind == after.kind == "page":
                self.assertEqual(after.page, before.page + 1)
        self.click_cell(gaps[0])
        self.assertEqual(self.pages, [])

    def test_very_narrow_width_falls_back_to_readable_compact_form(self):
        self.widget.resize(100, 240)
        self.widget.set_frame(make_frame(page_index=1, page_count=12))
        self.assertFalse(self.widget.page_bar.isVisibleTo(self.widget))
        self.assertTrue(self.widget.page_label.isVisibleTo(self.widget))
        self.assertEqual(self.widget.page_label.text(), "Seite 2 / 12")
        self.assertTrue(self.widget.next_page_button.isVisibleTo(self.widget))

    def test_digits_stay_readable_at_small_scale(self):
        self.widget.resize(self.widget.size_for_scale(0.3))
        self.widget.set_frame(make_frame(page_count=3))
        cell = self.widget.page_bar.cell_for_page(1)
        self.assertGreaterEqual(self.widget.page_bar._text_font(cell).pixelSize(), 10)

    def test_direct_choice_only_requests_and_holds_no_state(self):
        frame = make_frame(page_index=1, page_count=7)
        self.widget.set_frame(frame)
        bar = self.widget.page_bar
        self.click_cell(bar.cell_for_page(4))
        self.assertEqual(self.pages, [4])
        self.assertIs(self.widget.frame(), frame)
        self.assertEqual(bar._page_index, 1, "the active cell follows only the host's frame")
        self.click_cell(bar.cell_for_page(1))
        self.assertEqual(self.pages, [4], "the active page is no new request")
        self.widget.set_frame(make_frame(page_index=4, page_count=7))
        self.assertEqual(bar._page_index, 4)

    def test_active_cell_is_turquoise_and_the_others_black(self):
        self.widget.set_frame(make_frame(page_index=1, page_count=3))
        image = self.widget.page_bar.grab().toImage()
        active = self.widget.page_bar.cell_for_page(1).rect
        other = self.widget.page_bar.cell_for_page(0).rect
        self.assertEqual(pixel(image, active.left() + 4, active.top() + 4), (0x99, 0xf7, 0xec))
        self.assertEqual(pixel(image, other.left() + 4, other.top() + 4), (0, 0, 0))

    def test_plus_exists_only_with_edit_permission_and_only_asks(self):
        frame = make_frame(page_count=3)
        self.widget.set_frame(frame)
        self.assertIsNone(self.widget.page_bar.create_cell())
        self.widget.set_mode("edit")
        self.assertIsNone(self.widget.page_bar.create_cell(), "the mode alone is not permission")
        self.widget.set_edit_allowed(True)
        self.click_cell(self.widget.page_bar.create_cell())
        self.assertEqual(self.created, [True])
        self.assertIs(self.widget.frame(), frame, "no spontaneous page commit")
        self.assertEqual((self.pages, self.edits), ([], []))
        self.widget.set_edit_allowed(False)
        self.assertIsNone(self.widget.page_bar.create_cell())
        self.widget._on_create_page()
        self.assertEqual(self.created, [True], "the handler refuses too")

    def test_tooltip_names_the_page_and_the_request(self):
        self.editing()
        self.widget.set_frame(make_frame(page_index=0, page_count=3))
        bar = self.widget.page_bar
        for cell, expected in ((bar.cell_for_page(2), "Seite 3 von 3"), (bar.create_cell(), "Neue Seite beantragen")):
            point = cell.rect.center().toPoint()
            QApplication.sendEvent(bar, QHelpEvent(QEvent.Type.ToolTip, point, bar.mapToGlobal(point)))
            self.assertEqual(QToolTip.text(), expected)

    def test_page_bar_keeps_mouse_away_from_the_keys(self):
        self.widget.set_frame(make_frame(page_count=3))
        self.click_cell(self.widget.page_bar.cell_for_page(2))
        self.assertEqual(self.selected, [])


class MenuButtonTests(DeviceCase):
    def test_button_shows_only_on_hovered_key_in_active_edit(self):
        self.widget.set_frame(make_frame())
        self.move(self.widget.slot_rect(1).center())
        self.assertFalse(self.widget.menu_button_visible(1), "preview has no three-dot path")
        self.widget.set_mode("edit")
        self.assertFalse(self.widget.menu_button_visible(1), "edit without permission neither")
        self.widget.set_edit_allowed(True)
        self.assertTrue(self.widget.menu_button_visible(1))
        self.assertFalse(self.widget.menu_button_visible(2), "only the hovered key")
        self.move(self.widget.slot_rect(2).center())
        self.assertFalse(self.widget.menu_button_visible(1))

    def test_hidden_button_has_no_hit_area_in_the_gap(self):
        self.editing()
        self.widget.set_frame(make_frame())
        key = self.widget.slot_rect(1)
        with patch.object(self.widget, "_exec_menu") as run:
            self.click(QPointF(key.right() + 5, key.top() - 5))
        run.assert_not_called()

    def test_button_overhangs_the_key_as_in_the_reference_and_stays_reachable(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.move(self.widget.slot_rect(1).center())
        button, key = self.widget.menu_button_rect(1), self.widget.slot_rect(1)
        self.assertGreater(button.right(), key.right())
        self.assertLess(button.top(), key.top())
        outside = QPointF(key.right() + 5, key.top() - 5)
        self.assertTrue(button.contains(outside))
        self.move(outside)
        self.assertTrue(self.widget.menu_button_visible(1), "reaching for the button keeps it")

    def test_pointer_on_the_button_removes_the_key_tint(self):
        self.editing()
        self.widget.set_frame(make_frame(occupied=()))
        self.move(self.widget.slot_rect(1).center())
        tinted = pixel(self.grab(), *self.lcd_point(1).toTuple())
        self.move(self.widget.menu_button_rect(1).center())
        plain = pixel(self.grab(), *self.lcd_point(1).toTuple())
        self.assertNotEqual(tinted, plain)
        self.assertEqual(plain, (0x60, 0x60, 0x60))

    def test_menu_names_follow_the_reference_and_keep_all_functions(self):
        self.editing()
        self.widget.set_frame(make_frame())
        menu = self.widget._build_menu(0)
        names = {action.objectName(): action.text() for action in menu.actions() if action.objectName()}
        self.assertEqual(names["keypadCut"], "Aktion schneiden")
        self.assertEqual(names["keypadPaste"], "Aktion einfügen")
        self.assertEqual(names["keypadRemove"], "Aktion löschen")
        self.assertEqual(names["keypadSymbol"], "Symbol bearbeiten")
        self.assertEqual(set(names), {"keypadCut", "keypadCopy", "keypadPaste", "keypadRemove", "keypadSymbol", "keypadUndo", "keypadRedo"})
        self.assertFalse(any(action.icon().isNull() for action in menu.actions() if action.objectName()))
        menu.deleteLater()

    def test_click_on_the_visible_button_opens_the_menu(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.move(self.widget.slot_rect(1).center())
        with patch.object(self.widget, "_exec_menu") as run:
            self.click(self.widget.menu_button_rect(1).center())
        run.assert_called_once()
        self.assertEqual(self.selected, [])


class PressTests(DeviceCase):
    def press_changes(self, index: int, frame: "KeypadFrame") -> None:
        self.widget.set_frame(frame)
        self.widget.set_motion_enabled(True)
        center = self.widget.slot_rect(index).center().toPoint()
        self.move(center)
        before = self.grab()
        QTest.mousePress(self.widget, LEFT, NO_MOD, center)
        QTest.qWait(160)
        self.assertAlmostEqual(self.widget.key_motion(index)[0], 0.97, places=6)
        box = diff_box(before, self.grab())
        self.assertIsNotNone(box)
        allowed = self.widget.slot_rect(index).adjusted(-4, -4, 4, 5).toAlignedRect()
        self.assertTrue(allowed.contains(box), f"{box} leaves key {allowed}")
        QTest.keyClick(self.widget, Qt.Key.Key_Escape)
        QTest.mouseRelease(self.widget, LEFT, NO_MOD, center)
        QTest.qWait(260)
        self.assertEqual(self.widget._progress, {})
        self.assertIsNone(diff_box(before, self.grab()), "nothing stays shifted after the release")

    def test_press_moves_exactly_one_occupied_key(self):
        self.press_changes(1, make_frame())

    def test_press_moves_exactly_one_empty_key(self):
        self.press_changes(4, make_frame())


class DragVisualTests(DeviceCase):
    def hold(self, index: int) -> "QMimeData":
        self.mime = QMimeData()
        self.mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(ActionOffer("action.x", "Angebot"))))
        position = self.widget.slot_rect(index).center()
        QApplication.sendEvent(self.widget, QDragEnterEvent(position, Qt.DropAction.CopyAction, self.mime, LEFT, NO_MOD))
        QApplication.sendEvent(self.widget, QDragMoveEvent(position, Qt.DropAction.CopyAction, self.mime, LEFT, NO_MOD))
        return self.mime

    def finish(self, index: int) -> None:
        position = self.widget.slot_rect(index).center()
        QApplication.sendEvent(self.widget, QDropEvent(position, Qt.DropAction.CopyAction, self.mime, LEFT, NO_MOD))

    def test_free_keys_are_marked_and_the_target_is_strongest(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.hold(4)
        image = self.grab()
        target, candidate = pixel(image, *self.lcd_point(4).toTuple()), pixel(image, *self.lcd_point(3).toTuple())
        self.assertGreater(target[1], candidate[1], "target is stronger than the other candidates")
        self.assertGreater(candidate[1], candidate[0] + 20, "free keys get the turquoise overlay")
        self.assertGreater(candidate[0], 0x20, "an overlay, not a replacing tile colour")
        self.assertLess(max(pixel(image, *self.lcd_point(1).toTuple())), 12, "occupied keys are no target; no silent swap")
        self.finish(4)
        self.assertEqual(self.edits[-1].operation, "place")
        self.assertFalse(self.widget._drag_active)

    def test_occupied_target_shows_refusal_and_sends_nothing(self):
        self.editing()
        self.widget.set_frame(make_frame())
        self.hold(1)
        self.assertEqual((self.widget._drop_index, self.widget._drop_ok), (1, False))
        ring = pixel(self.grab(), self.widget.slot_rect(1).left() - 3, self.widget.slot_rect(1).center().y())
        self.assertGreater(ring[0], ring[1] + 40, "red refusal ring")
        self.finish(1)
        self.assertEqual(self.edits, [])

    def test_page_controls_turn_pages_during_a_drag(self):
        self.editing()
        self.widget.set_frame(make_frame(page_count=4))
        self.mime = QMimeData()
        self.mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(ActionOffer("action.x", "Angebot"))))
        for position, expected in ((self.widget.arrow_rect(1).center(), 1),
                                   (QPointF(self.widget.page_bar.mapTo(self.widget, self.widget.page_bar.cell_for_page(3).rect.center().toPoint())), 3)):
            QApplication.sendEvent(self.widget, QDragEnterEvent(position, Qt.DropAction.CopyAction, self.mime, LEFT, NO_MOD))
            QApplication.sendEvent(self.widget, QDragMoveEvent(position, Qt.DropAction.CopyAction, self.mime, LEFT, NO_MOD))
            self.assertEqual(self.widget._spring_page, expected)
        self.widget._clear_drop()


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class ReferenceTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reference_tiles_are_black_with_a_caption_below_the_symbol(self):
        for action in REFERENCE_ACTIONS:
            image = render_reference_tile(action, None)
            if not action.color:
                self.assertIsNone(image, "text actions stay text; the widget draws them")
                continue
            if action.reference_icon != "star":
                self.assertEqual(pixel(image, 4, image.height() // 2), (0, 0, 0))
            caption = [y for y in range(int(image.height() * 0.72), image.height()) if any(
                pixel(image, x, y)[0] > 200 for x in range(10, image.width() - 10, 3))]
            self.assertTrue(caption, f"{action.action_id} has a caption")

    def test_host_switches_tiles_without_touching_placements(self):
        host = LabHost("reference", visual_mode=VISUAL_FUNCTION)
        placements, revision = dict(host.placements), host.revision
        functional = next(s for s in host.frame().slots if s.physical_index == 0).tile_image
        host.set_visual_mode(VISUAL_REFERENCE)
        reference = next(s for s in host.frame().slots if s.physical_index == 0).tile_image
        self.assertEqual((host.placements, host.revision), (placements, revision))
        self.assertNotEqual(functional, reference)

    def test_reference_scenario_matches_the_screenshot_mix(self):
        host = LabHost("reference", visual_mode=VISUAL_REFERENCE)
        frame = host.frame()
        self.assertEqual((frame.page_index, frame.page_count), (1, 7))
        self.assertEqual({s.physical_index for s in frame.slots if s.role == "empty"}, {3, 4, 6})
        self.assertIsNone(next(s for s in frame.slots if s.physical_index == 7).tile_image)

    def test_host_answers_page_request_by_simulation(self):
        host = LabHost("reference")
        revision = host.revision
        host.add_page()
        frame = host.frame()
        self.assertEqual((frame.page_count, frame.page_index), (8, 7))
        self.assertNotEqual(frame.revision, revision)


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class LabDefaultViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        spec = importlib.util.spec_from_file_location("run_keypad_preview_lab_v2", ROOT / "tools" / "run_keypad_preview_lab.py")
        cls.lab = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.lab
        spec.loader.exec_module(cls.lab)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keypad-lab-")
        self.addCleanup(self.temp.cleanup)
        write_device_layers(Path(self.temp.name))
        self.window = self.lab.KeypadLabWindow(Path(self.temp.name) / "out")
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def test_default_view_shows_device_art_compactly_and_reports_the_source(self):
        with patch.object(self.lab, "SKIN_DIRECTORY", Path(self.temp.name)):
            self.window.use_default_view()
        keypad = self.window.keypad
        self.assertTrue(keypad.effective_skin().is_device_art)
        self.assertIn(Path(self.temp.name).name, self.window.skin_notice.text())
        self.assertEqual(self.window.skin_notice.toolTip(), self.temp.name)
        self.assertAlmostEqual(keypad.width() / ASSET_NATIVE_SIZE[0], 0.6, delta=0.01)
        self.assertEqual(keypad.frame().page_count, 7)
        self.assertEqual(self.window.visual_combo.currentData(), VISUAL_REFERENCE)

    def test_missing_files_are_reported_and_not_shown_as_success(self):
        with patch.object(self.lab, "SKIN_DIRECTORY", Path(self.temp.name) / "fehlt"):
            self.window.use_default_view()
        self.assertFalse(self.window.keypad.effective_skin().is_device_art)
        self.assertIn("Fallback", self.window.skin_notice.text())
        self.assertIn("fehlt", self.window.skin_notice.text())

    def test_function_tiles_stay_available(self):
        self.window.visual_combo.setCurrentIndex(self.window.visual_combo.findData(VISUAL_FUNCTION))
        self.assertEqual(self.window.host.visual_mode, VISUAL_FUNCTION)

    def test_test_instruments_fold_away(self):
        self.window.show()
        self.assertFalse(self.window.catalog_panel.isVisible())
        self.assertFalse(self.window.log_view.isVisible())
        self.assertTrue(self.window.control_panel.isVisible())
        self.window.control_toggle.setChecked(False)
        self.window.catalog_toggle.setChecked(True)
        self.window.log_toggle.setChecked(True)
        self.assertFalse(self.window.control_panel.isVisible())
        self.assertTrue(self.window.catalog_panel.isVisible())
        self.assertTrue(self.window.log_view.isVisible())

    def test_plus_goes_through_the_simulated_host(self):
        self.window.edit_radio.setChecked(True)
        self.window.allow_check.setChecked(True)
        self.window.keypad.pageCreateRequested.emit()
        self.assertTrue(any(event["signal"] == "pageCreateRequested" for event in self.window.events))
        self.assertEqual(self.window.keypad.frame().page_count, self.window.host.page_count)

    def test_catalog_drag_uses_the_reference_label(self):
        offer = self.window.catalog.offers[0]
        self.assertIsNotNone(offer.tile_image)
        self.assertEqual(self.window.catalog.offer_mime(offer).formats(), [ACTION_REF_MIME])


REAL_DIRECTORY = None if not HAS_QT else find_logikeypad_directory(ROOT)
HAVE_REAL = HAS_QT and (REAL_DIRECTORY / ASSET_CASE_FILE).is_file() and (REFERENCES / "Pagination.png").is_file()


@unittest.skipUnless(HAVE_REAL, "Originalgrafiken und Referenzen sind auf diesem Rechner nicht vorhanden")
class RealAssetTests(unittest.TestCase):
    """Original files against the reference screenshot, at 1:1 device pixels."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.skin, problem = load_logikeypad_skin(REAL_DIRECTORY)
        assert cls.skin is not None, problem
        cls.reference = QImage(str(REFERENCES / "Pagination.png")).convertToFormat(QImage.Format.Format_ARGB32)

    def setUp(self):
        self.host = LabHost("reference", visual_mode=VISUAL_REFERENCE)
        self.widget = KeypadPreviewWidget()
        self.widget.set_skin(self.skin)
        self.widget.set_motion_enabled(False)
        self.widget.resize(self.widget.size_for_scale(1.0))
        self.widget.set_frame(self.host.frame())
        self.addCleanup(self.widget.deleteLater)
        self.image = self.widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)

    def mean_difference(self, rect: "QRect") -> float:
        ours = self.image.copy(rect)
        theirs = self.reference.copy(rect.translated(*REFERENCE_OFFSET))
        a, b = bytes(ours.constBits()), bytes(theirs.constBits())
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    def test_loading_leaves_the_files_untouched(self):
        path = REAL_DIRECTORY / ASSET_CASE_FILE
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        load_logikeypad_skin(REAL_DIRECTORY)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_all_nine_key_rects_match_the_cut_outs(self):
        case = self.skin.case_image
        for index, (x, y, width, height) in ASSET_KEY_RECTS.items():
            self.assertEqual(case.pixelColor(x + width // 2, y + height // 2).alpha(), 0, f"cut-out of key {index}")

    def test_housing_logo_and_arrows_match_the_reference(self):
        self.assertLess(self.mean_difference(QRect(0, 530, 657, 194)), 1.5)

    def test_keys_off_closes_the_gaps_of_the_first_key_layer(self):
        area, face = self.skin.key_faces[0]
        layer = self.skin.key_images[0]
        x0, y0 = int(area.x()), int(area.y())
        cut_out = [(x, y) for x in range(x0, x0 + face.width()) for y in range(y0, y0 + face.height())
                   if self.skin.case_image.pixelColor(x, y).alpha() == 0]
        open_in_layer = sum(1 for x, y in cut_out if layer.pixelColor(x, y).alpha() == 0)
        open_in_face = sum(1 for x, y in cut_out if face.pixelColor(x - x0, y - y0).alpha() == 0)
        self.assertLess(open_in_face, open_in_layer)

    def test_empty_keys_match_the_reference(self):
        self.assertLess(self.mean_difference(QRect(*ASSET_KEY_RECTS[6])), 1.0)
        self.assertLess(self.mean_difference(QRect(*ASSET_KEY_RECTS[3])), 3.0)

    def test_black_lcd_sheen_matches_the_reference(self):
        x, y, width, height = ASSET_KEY_RECTS[7]
        self.assertLess(self.mean_difference(QRect(x, y + 6, width, 34)), 8.0, "upper part of a text key, above its text")

    def test_hit_area_matches_the_visible_key_at_each_corner(self):
        for index, (x, y, width, height) in ASSET_KEY_RECTS.items():
            self.assertEqual(self.skin.hit_key(QPointF(x + width / 2, y + height / 2), range(9)), index)
            self.assertIsNone(self.skin.hit_key(QPointF(x - 6, y - 6), range(9)))
        self.assertIsNone(self.skin.hit_key(QPointF(122, 100), range(9)), "the outer key corner is rounder")


if __name__ == "__main__":
    unittest.main()
