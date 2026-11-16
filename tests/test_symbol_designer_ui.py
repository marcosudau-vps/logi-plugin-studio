from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if Path("C:/Windows/Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURE = ROOT / "tests" / "fixtures" / "symbol_designer" / "native_style.ict"

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QToolButton
    from symbol_designer.dialogs import ExportOptions, StyleTarget
    from symbol_designer.ict import (IMAGE, LAYOUTS, TEXT, IconTemplate, IctError, content_fingerprint,
                                     image_info)
    from symbol_designer.lab import LabWindow, sample_targets
    from symbol_designer.library import BUNDLED_ROOT
    from symbol_designer.render import render_template
    from symbol_designer.widget import SymbolDesignerWidget
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

MONO = BUNDLED_ROOT / "Medien" / "Wiedergabe.svg" if HAS_QT else None
PNG = BUNDLED_ROOT / "Beispiele" / "Raster_Abzeichen.png" if HAS_QT else None


@unittest.skipUnless(HAS_QT, "PySide6 Widgets required")
class SymbolDesignerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="symbol-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        library = self.dir / "library" / "TestPack"
        (library / "metadata").mkdir(parents=True)
        (library / "metadata" / "LoupedeckPackage.yaml").write_text(
            "type: IconLibrary\nname: TestPack\ndisplayName: Test-Paket\nlicense: CC0\n", encoding="utf-8")
        shutil.copy(MONO, library / "Play.svg")
        shutil.copy(PNG, library / "Badge.png")
        self.widget = SymbolDesignerWidget(library_root=self.dir / "library")
        self.widget.ask_user = False
        self.widget.resize(1300, 820)
        self.widget.show()
        self.pump()
        self.addCleanup(self.widget.close)

    def pump(self, rounds: int = 5):
        for _ in range(rounds):
            self.app.processEvents()

    def point(self, kind: str, fx: float = .5, fy: float = .5) -> QPoint:
        rect = self.widget.canvas.item_rect(kind)
        return QPoint(round(rect.x() + rect.width() * fx), round(rect.y() + rect.height() * fy))

    def drag(self, start: QPoint, end: QPoint, modifier=Qt.KeyboardModifier.NoModifier):
        canvas = self.widget.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifier, start)
        for step in range(1, 6):
            QTest.mouseMove(canvas, start + (end - start) * step / 5)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifier, end)
        self.pump()

    def units(self, pixels: float) -> int:
        return round(pixels / self.widget.canvas.scale())

    def test_new_template_save_reopen_and_export_all_outputs(self):
        widget = self.widget
        widget.new_template("Meine Aktion")
        self.assertEqual(widget.template.text, "Meine Aktion")
        self.assertFalse(widget.is_dirty())
        widget.import_image(MONO)
        path = widget.save_ict(self.dir / "out" / "neu.ict")
        reopened = IconTemplate.load(path)
        self.assertEqual(reopened.data, widget.template.data)
        report = widget.export_bundle(ExportOptions(self.dir / "out", "neu", True, (50, 80, 116), True, True,
                                                    None, "Demo.Plugin.Action"))
        self.assertEqual(report.errors, [])
        names = sorted(p.relative_to(self.dir / "out").as_posix() for p in report.files)
        self.assertEqual(names, ["actionsymbols/Demo.Plugin.Action.svg", "neu.ict", "neu.svg", "neu_116px.png",
                                 "neu_50px.png", "neu_80px.png"])
        for size in (50, 80, 116):
            self.assertEqual(QImage(str(self.dir / "out" / ("neu_%dpx.png" % size))).size().width(), size)
        widget.load_ict(path)
        self.assertEqual(widget.template.text, "Meine Aktion")
        self.assertTrue(image_info(widget.template.image_bytes()).tintable)

    def test_import_png_svg_via_windows_dialog_and_drop(self):
        widget = self.widget
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(PNG), "")) as dialog:
            QTest.mouseClick(widget.upload_button, Qt.MouseButton.LeftButton)
        dialog.assert_called_once()
        self.assertEqual(widget.template.image_info().format, "png")
        self.assertFalse(widget.image_color_button.isEnabled())
        external = self.dir / "Explorer.svg"
        shutil.copy(MONO, external)
        widget.canvas.filesDropped.emit([external])
        self.assertEqual(widget.template.image_info().format, "svg")
        self.assertTrue(widget.image_color_button.isEnabled())
        self.assertIn("Explorer.svg", widget.image_source.text())
        widget.canvas.filesDropped.emit([MONO])
        self.assertIn("Studio-Startsymbole", widget.image_source.text(), "Ablage aus der Bibliothek behält Herkunft")
        custom = [s for s in widget.library.sections if s.package.id == "eigene-bilder"]
        self.assertEqual(len(custom[0].package.entries), 2)

    def test_mouse_move_and_resize_elements_independently(self):
        widget = self.widget
        widget.import_image(MONO)
        widget.apply_layout("image_top")
        self.pump()
        text_before = widget.template.area(TEXT)
        start = self.point(IMAGE)
        self.drag(start, start + QPoint(-40, 30))
        x, y, w, h = widget.template.area(IMAGE)
        self.assertEqual((w, h), (65, 65))
        self.assertAlmostEqual(x, 17 + self.units(-40), delta=1)
        self.assertAlmostEqual(y, 0 + self.units(30), delta=1)
        self.assertEqual(widget.template.area(TEXT), text_before)
        corner = widget.canvas.handle_rects(IMAGE)["br"].center().toPoint()
        self.drag(corner, corner + QPoint(-60, -10))
        nx, ny, nw, nh = widget.template.area(IMAGE)
        self.assertEqual((nx, ny), (x, y))
        self.assertEqual(nw, nh, "Symbol skaliert standardmäßig proportional")
        self.assertLess(nw, 65)
        widget.select(TEXT)
        right = widget.canvas.handle_rects(TEXT)["t"].center().toPoint()
        self.drag(right, right + QPoint(0, -40))
        tx, ty, tw, th = widget.template.area(TEXT)
        self.assertGreater(th, 30)
        self.assertEqual(widget.template.area(IMAGE), (nx, ny, nw, nh))
        self.assertEqual(widget.geometry_spins[TEXT]["height"].value(), th)
        widget.geometry_spins[IMAGE]["x"].setValue(5)
        self.assertEqual(widget.template.area(IMAGE)[0], 5)

    def test_overlap_selection_cycles_with_alt_click_and_tab(self):
        widget = self.widget
        widget.import_image(MONO)
        widget.apply_layout("text_over")
        self.pump()
        canvas = widget.canvas
        middle = self.point(TEXT)
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        self.assertIsNone(canvas.selected)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, middle)
        self.assertEqual(canvas.selected, TEXT, "oberstes Element (Text) zuerst")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, middle)
        self.assertEqual(canvas.selected, IMAGE)
        self.drag(middle, middle + QPoint(0, 20))
        self.assertEqual(canvas.selected, IMAGE, "ausgewähltes, überdecktes Element bleibt beim Ziehen aktiv")
        QTest.keyClick(canvas, Qt.Key.Key_Tab)
        self.assertEqual(canvas.selected, TEXT)
        QTest.mouseClick(widget.cycle_button, Qt.MouseButton.LeftButton)
        self.assertEqual(canvas.selected, IMAGE)
        self.assertEqual(widget.template.area(IMAGE), (0, 0, 100, 100), "volle Fläche bleibt im Iconbereich")
        widget.set_area(IMAGE, 20, 20, 60, 60)
        QTest.keyClick(canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(canvas, Qt.Key.Key_Up)
        self.assertEqual(widget.template.area(IMAGE), (25, 19, 60, 60))

    def test_four_layout_buttons_visibility_colours_and_font(self):
        widget = self.widget
        widget.import_image(MONO)
        widget.set_text("Inhalt")
        protected = content_fingerprint(widget.template)
        for layout in LAYOUTS[:4]:
            QTest.mouseClick(widget.layout_buttons[layout.key], Qt.MouseButton.LeftButton)
            self.assertEqual(widget.template.area(IMAGE), layout.image)
            self.assertEqual(widget.template.area(TEXT), layout.text)
            self.assertTrue(widget.layout_buttons[layout.key].isChecked())
            self.assertEqual(content_fingerprint(widget.template), protected)
        QTest.mouseClick(widget.eye_buttons[TEXT], Qt.MouseButton.LeftButton)
        self.assertFalse(widget.template.visible(TEXT))
        self.assertTrue(widget.template.visible(IMAGE))
        self.assertEqual(widget.template.text, "Inhalt")
        QTest.mouseClick(widget.eye_buttons[IMAGE], Qt.MouseButton.LeftButton)
        self.assertFalse(widget.template.visible(IMAGE))
        self.assertIsNotNone(widget.template.image_bytes())
        background = render_template(widget.template, 50)
        self.assertEqual(QColor(background.pixel(25, 25)).rgb() & 0xFFFFFF, 0)
        widget.background_button.set_value(0xFF1E3A8A)
        widget.background_button.colorChanged.emit(0xFF1E3A8A)
        widget.text_color_button.colorChanged.emit(0xFFFF8800)
        widget.image_color_button.colorChanged.emit(0xFF00FF00)
        widget.size_combo.setCurrentIndex(widget.size_combo.findData(7))
        widget.font_combo.setEditText("Arial")
        self.assertEqual((widget.template.background, widget.template.text_color, widget.template.image_color,
                          widget.template.font_size, widget.template.font_name),
                         (0xFF1E3A8A, 0xFFFF8800, 0xFF00FF00, 7, "Arial"))
        QTest.mouseClick(widget.rotate_button, Qt.MouseButton.LeftButton)
        self.assertEqual(widget.template.rotation, 90)

    def test_undo_redo_reset_apply_and_cancel(self):
        widget = self.widget
        applied = []
        widget.applied.connect(applied.append)
        baseline = widget.template.snapshot()
        widget.set_background(0xFF112233)
        widget.apply_layout("text_top")
        widget.set_text("A")
        widget.set_text("AB")
        self.assertEqual(widget.undo_stack.count(), 3, "Texteingaben werden zusammengefasst")
        QTest.mouseClick(widget.undo_button, Qt.MouseButton.LeftButton)
        self.assertEqual(widget.template.text, "Neue Aktion")
        widget.undo_stack.undo()
        widget.undo_stack.undo()
        self.assertEqual(widget.template.snapshot(), baseline)
        self.assertFalse(widget.is_dirty())
        widget.undo_stack.redo()
        widget.undo_stack.redo()
        QTest.mouseClick(widget.redo_button, Qt.MouseButton.LeftButton)
        self.assertEqual(widget.template.text, "AB")
        self.assertEqual(widget.text_edit.toPlainText(), "AB")
        widget.reset_to_baseline()
        self.assertEqual(widget.template.snapshot(), baseline)
        widget.undo_stack.undo()
        self.assertEqual(widget.template.text, "AB")
        widget.apply()
        self.assertEqual(applied[-1]["items"][1]["text"], "AB")
        self.assertFalse(widget.is_dirty())
        widget.set_text("verworfen")
        widget.cancel()
        self.assertEqual(widget.template.text, "AB")
        self.assertEqual(widget.undo_stack.count(), 0)

    def test_style_transfer_to_many_targets_is_one_undo_step(self):
        widget = self.widget
        targets = sample_targets()
        fingerprints = [content_fingerprint(t.template) for t in targets]
        texts = [t.template.text for t in targets]
        widget.import_image(MONO)
        widget.set_background(0xFF000000)
        widget.apply_layout("image_top")
        widget.set_font_size(6)
        widget.set_text_color(0xFFFFD000)
        before_index = widget.undo_stack.index()
        results = widget.apply_style_to(targets, ["background", "layout", "font", "text_color", "symbol_format"])
        self.assertEqual(widget.undo_stack.index(), before_index + 1)
        for target, fingerprint, text in zip(targets, fingerprints, texts):
            self.assertEqual(content_fingerprint(target.template), fingerprint)
            self.assertEqual(target.template.text, text)
            self.assertEqual(target.template.background, 0xFF000000)
            self.assertEqual(target.template.font_size, 6)
            self.assertEqual(target.template.area(IMAGE), (17, 0, 65, 65))
            self.assertTrue(target.modified)
        skipped = [s for _, r in results for s in r.skipped]
        self.assertEqual(len(skipped), 2, "mehrfarbiges SVG und PNG werden nicht eingefärbt")
        widget.undo_stack.undo()
        self.assertEqual([t.template.background for t in targets], [0xFF1E3A8A, 0xFF7B1FA2, 0xFF263238, 0xFF004D40])
        self.assertFalse(any(t.modified for t in targets))
        widget.undo_stack.redo()
        self.assertTrue(all(t.template.background == 0xFF000000 for t in targets))

    def test_canvas_scaling_keeps_mouse_mapping(self):
        widget = self.widget
        widget.import_image(MONO)
        for width, height in ((900, 600), (1700, 1100)):
            widget.apply_layout("image_center")
            widget.resize(width, height)
            self.pump(8)
            scale = widget.canvas.scale()
            start = self.point(IMAGE)
            self.drag(start, start + QPoint(round(10 * scale), round(5 * scale)))
            self.assertEqual(widget.template.area(IMAGE)[:2], (30, 25), "Bei %dx%d" % (width, height))
            rendered = widget.canvas.grab()
            self.assertFalse(rendered.isNull())

    def test_invalid_inputs_do_not_crash(self):
        widget = self.widget
        (self.dir / "kaputt.png").write_bytes(b"\x89PNG\r\n\x1a\n000")
        (self.dir / "falsch.ict").write_text("{kein json")
        self.assertIsNone(widget.import_image(self.dir / "kaputt.png"))
        self.assertIn("beschädigt", widget.last_error)
        self.assertIsNone(widget.import_image(self.dir / "nicht_da.svg"))
        with self.assertRaises(IctError):
            widget.load_ict(self.dir / "falsch.ict")
        with self.assertRaises(IctError):
            widget.export_action_symbol(self.dir / "a.svg", PNG)
        widget.set_image_color(0xFF00FF00)
        self.assertIn("einfarbige", widget.last_error)
        widget.load_template({"backgroundColor": 1, "items": [{"itemType": "Text"}, {"itemType": "Video"}]})
        self.assertTrue(any("Video" in n for n in widget.notices))
        widget.set_text("geht")
        self.assertEqual(widget.template.items[1], {"itemType": "Video"})
        self.assertIsNone(widget.template.item(IMAGE))
        self.assertFalse(widget.rotate_button.isEnabled())

    def test_library_search_click_and_animated_gif_choice(self):
        widget = self.widget
        library = widget.library
        self.pump(20)
        self.assertEqual({s.package.display_name for s in library.sections} >= {"Test-Paket", "Studio-Startsymbole"},
                         True)
        library.search.setText("badge")
        library.apply_filter()
        visible = [s for s in library.sections if s.isVisible()]
        self.assertEqual([s.package.id for s in visible], ["TestPack"])
        grid = visible[0].grid
        item = next(grid.item(i) for i in range(grid.count()) if not grid.item(i).isHidden())
        grid.itemClicked.emit(item)
        self.assertEqual(widget.template.image_info().format, "png")
        self.assertIn("Test-Paket", widget.image_source.text())
        self.assertTrue(any("Lizenz" in n for n in widget.notices))
        sys.path.insert(0, str(ROOT / "tests"))
        from test_symbol_designer_core import animated_gif
        gif = self.dir / "anim.gif"
        gif.write_bytes(animated_gif())
        widget.import_image(gif)
        self.assertEqual(widget.template.image_info().format, "png", "ohne Rückfrage bewusst Standbild")
        widget.import_image(gif, gif_mode="original")
        self.assertEqual(widget.template.image_info().format, "gif")
        report = widget.export_bundle(ExportOptions(self.dir / "gif", "anim", True, (80,), True))
        self.assertTrue(any("erste Bild" in n for n in report.notes))

    def test_library_drag_data_is_owned_by_qt(self):
        # Regression: a Python-owned QMimeData was freed by Qt after the drag and again by Python,
        # which crashed the Lab later at an unrelated action (export, colour dialog).
        import shiboken6
        from symbol_designer.library_panel import ROLE
        grid = self.widget.library.sections[0].grid
        data = grid.mimeData([grid.item(0)])
        self.assertFalse(shiboken6.ownedByPython(data))
        self.assertEqual([Path(u.toLocalFile()) for u in data.urls()], [grid.item(0).data(ROLE).path])


@unittest.skipUnless(HAS_QT, "PySide6 Widgets required")
class SymbolDesignerLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lab_exports_reads_files_back_and_verifies_ict(self):
        with tempfile.TemporaryDirectory(prefix="symbol-lab-") as tmp:
            lab = LabWindow(Path(tmp), FIXTURE)
            lab.designer.ask_user = False
            lab.show()
            for _ in range(10):
                self.app.processEvents()
            self.assertEqual(lab.designer.template.text, "Fertig\r\nmelden")
            report = lab.export(ict=True, png=True, svg=True)
            self.assertEqual(report.errors, [])
            self.assertIn("PNG 116 ↔ Editor: mittlere Abweichung 0.000 %", lab.compare_text.text())
            self.assertIn("identisch", lab.ict_result.text())
            exported = (Path(tmp) / "symbol.ict").read_bytes()
            self.assertEqual(exported, FIXTURE.read_bytes(), "unveränderte Vorlage wird byte-identisch exportiert")
            lab.add_samples()
            lab.designer.apply_style_to(lab.designer.style_targets, ["background", "layout"])
            lab.refresh_targets()
            self.assertIn("4 von 4 Zielen", lab.content_check.text())
            lab.save_targets()
            self.assertEqual(len(list((Path(tmp) / "targets").glob("*.ict"))), 4)
            self.assertIn('"futureTemplateField"', lab.json_view.toPlainText())
            lab.close()


if __name__ == "__main__":
    unittest.main()
