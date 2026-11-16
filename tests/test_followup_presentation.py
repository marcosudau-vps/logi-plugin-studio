from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapters.logitech.errors import GenerationError
from adapters.logitech.product import validate_product
from library.document import ProjectDocument
from library.presentation import image_bounds, presentation_options
from library.templates import callback_project
from studio.fields import ObjectEditor
from studio.images import render_tile
from PySide6.QtWidgets import QApplication


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_backward_default_geometry_and_exact_device_sizes(self):
        self.assertEqual(presentation_options({}), ("stretch", None))
        for size in (50, 80, 116):
            self.assertEqual(image_bounds(90, 40, size, "stretch"), (0, 0, size, size))
            h = int(40 * (size / 90))
            self.assertEqual(image_bounds(90, 40, size, "contain"), (0, (size - h) // 2, size, h))
            self.assertEqual(image_bounds(1, 1024, size, "contain"), ((size - 1) // 2, 0, 1, size))

    def test_optional_fields_survive_form_and_model_with_no_default_insertion(self):
        document = ProjectDocument(callback_project())
        entity = copy.deepcopy(document.raw["presentations"][0])
        entity["variants"]["active"].update({"image_fit": "contain", "font_size": 20})
        editor = ObjectEditor(document, "presentations", entity)
        self.assertEqual(editor.value(), entity)
        editor.table.cellWidget(0, 5).setCurrentText("contain")
        editor.table.cellWidget(0, 6).setText("24")
        raw = editor.value()
        self.assertEqual(raw["variants"]["idle"]["font_size"], 24)
        document.replace_entity("presentations", entity["id"], raw)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            document.save(path)
            reloaded = ProjectDocument()
            reloaded.load(path)
            self.assertEqual(reloaded.raw, document.raw)
            validate_product(reloaded.raw, path.parent)
        editor.deleteLater()

    def test_bad_font_fit_and_unknown_fields_refused_without_coercion(self):
        for change in ({"font_size": True}, {"font_size": 0}, {"font_size": 49}, {"font_size": "20"},
                       {"font_size": 20.1}, {"font_size": None}, {"image_fit": "cover"},
                       {"image_fit": []}, {"other": True}):
            raw = callback_project()
            raw["presentations"][0]["variants"]["idle"].update(change)
            with self.subTest(change=change), self.assertRaises(GenerationError):
                validate_product(raw, ROOT)
            # Even a malformed draft stays visibly editable rather than crashing preview.
            image = render_tile(raw, None, raw["views"][0]["placements"][0], "idle")
            self.assertEqual((image.width(), image.height()), (116, 116))
