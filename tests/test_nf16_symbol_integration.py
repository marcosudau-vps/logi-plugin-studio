"""NF-16 integration tests: real native actions -> finished SymbolDesigner -> ICT package."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.native import parse_native_project
from adapters.logitech.product import build_product, generate_product
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from studio.native_ict_binding import NativeIctBindingError, NativeIctCoordinator
from symbol_designer.ict import IconTemplate
from studio.keypad_contract import KeypadFrame, KeypadViewState, NavigationCapability, SlotData

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from studio.app import StudioWindow
    from studio.native_symbol_dialog import NativeSymbolDesignerDialog
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False


class NativeSymbolBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="native-ict-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project.json"
        raw = json.loads((ROOT / "examples" / "project_logitech_native_v1.json").read_text(encoding="utf-8"))
        self.project.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def project_raw(self):
        return json.loads(self.project.read_text(encoding="utf-8"))

    def set_project(self, raw):
        self.project.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_new_ict_is_connected_to_native_action_and_generator(self):
        controller = NativeIctCoordinator(self.project)
        binding = controller.open_action("action.command")
        self.assertTrue(binding.forked)
        self.assertFalse(binding.target.exists())
        self.assertEqual(binding.template.text, "Parametrisierter Befehl")
        model = binding.template.copy()
        model.text = "Meine SDK-Aktion"
        target = controller.save(binding, model)
        self.assertEqual(IconTemplate.load(target).text, "Meine SDK-Aktion")
        self.assertEqual(self.project_raw()["actions"][0]["icon_template"],
                         "icontemplates/action.command.ict")
        parse_native_project(self.project_raw())
        self.assertEqual(NativeIctCoordinator(self.project).open_action("action.command").source, target)
        plan = generate_product(self.project, output_dir=self.root / "generated", assembly_name="NativeIctTest")
        self.assertTrue(any(key.startswith("icontemplates/") and key.endswith(".ict")
                            for key in plan.files))
        self.assertEqual(next(value for k, value in plan.files.items()
                              if k.startswith("icontemplates/") and k.endswith(".ict")),
                         target.read_bytes())
        if DEFAULT_SDK_DLL.is_file():
            result = build_product(plan, self.root / "generated", log_path=self.root / "sdk-build.log")
            self.assertEqual(result.returncode, 0,
                             (self.root / "sdk-build.log").read_text(encoding="utf-8"))

    def test_existing_private_template_saves_without_reformatting_project(self):
        raw = self.project_raw()
        path = self.root / "icons" / "private.ict"
        IconTemplate().save(path)
        raw["actions"][0]["icon_template"] = "icons/private.ict"
        self.set_project(raw)
        project_before = self.project.read_bytes()
        controller = NativeIctCoordinator(self.project)
        binding = controller.open_action("action.command")
        self.assertFalse(binding.forked)
        model = binding.template.copy()
        model.text = "Befehl neu"
        controller.save(binding, model)
        self.assertEqual(self.project.read_bytes(), project_before)
        self.assertEqual(IconTemplate.load(path).text, "Befehl neu")

    def test_plugin_default_and_shared_action_template_are_not_overwritten(self):
        raw = self.project_raw()
        source = self.root / "icontemplates" / "action.command.ict"
        original = IconTemplate()
        original.text = "Gemeinsam"
        original.save(source)
        source_before = source.read_bytes()
        raw["plugin"]["default_icon_template"] = "icontemplates/action.command.ict"
        raw["actions"][0]["icon_template"] = "icontemplates/action.command.ict"
        raw["actions"][1]["icon_template"] = "icontemplates/action.command.ict"
        self.set_project(raw)
        ctl = NativeIctCoordinator(self.project)
        binding = ctl.open_action("action.command")
        self.assertTrue(binding.forked)
        self.assertNotEqual(binding.target, source)
        ctl.save(binding, binding.template)
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(self.project_raw()["actions"][1]["icon_template"],
                         "icontemplates/action.command.ict")

    def test_conflicting_project_and_external_ict_edits_are_rejected(self):
        ctl = NativeIctCoordinator(self.project)
        binding = ctl.open_action("action.command")
        raw = self.project_raw()
        raw["plugin"]["display_name"] = "Extern geändert"
        self.set_project(raw)
        with self.assertRaisesRegex(NativeIctBindingError, "extern verändert"):
            ctl.save(binding, binding.template)
        self.assertFalse(binding.target.exists())
        # External native ICT change must not be overwritten either.
        raw = self.project_raw()
        current = self.root / "private.ict"
        IconTemplate().save(current)
        raw["actions"][0]["icon_template"] = "private.ict"
        self.set_project(raw)
        ctl = NativeIctCoordinator(self.project)
        binding = ctl.open_action("action.command")
        current.write_text('{"backgroundColor":123,"items":[]}', encoding="utf-8")
        with self.assertRaisesRegex(NativeIctBindingError, "ICT-Quelle wurde extern"):
            ctl.save(binding, binding.template)

    def test_keypad_dto_requires_explicit_edit_mode_and_real_placement(self):
        controller = NativeIctCoordinator(self.project)
        capability = NavigationCapability("SDK-Device", "ButtonArea", (1, 3), (0,))
        frame = KeypadFrame("plugin", "folder.main", "rev1", capability, (
            SlotData(0, "sdk_navigation"),
            SlotData(1, "placement", "placement.command", "action.command", "first"),
            SlotData(3, "placement", "placement.multistate", "action.multistate", None),
        ))
        preview = KeypadViewState(frame)
        with self.assertRaisesRegex(NativeIctBindingError, "Vorschaumodus"):
            controller.from_slot(preview, 1)
        editor = preview.with_mode("edit")
        chosen = controller.from_slot(editor, 1)
        self.assertEqual(chosen.action_id, "action.command")
        self.assertEqual(chosen.action_parameter, "first")
        self.assertNotEqual(chosen.action_parameter, frame.slots[1].placement_id)
        with self.assertRaisesRegex(NativeIctBindingError, "keine bearbeitbare"):
            controller.from_slot(editor, 0)


@unittest.skipUnless(HAS_QT, "Requires PySide6")
class NativeSymbolDialogTests(NativeSymbolBindingTests):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.dialog = NativeSymbolDesignerDialog(self.project, load_library=False)
        self.dialog.designer.ask_user = False
        self.addCleanup(self.dialog.close)

    def test_editor_is_readonly_until_explicit_edit(self):
        self.assertFalse(self.dialog.edit_toggle.isChecked())
        self.assertTrue(self.dialog.designer.apply_button.isHidden())
        self.assertTrue(self.dialog.designer.multi_button.isHidden())
        self.assertFalse(self.dialog.designer.isEnabled())
        self.assertFalse(self.dialog.save_current())
        self.assertFalse((self.root / "icontemplates").exists())
        self.dialog.edit_toggle.setChecked(True)
        self.assertTrue(self.dialog.designer.isEnabled())
        self.dialog.designer.set_background(0xFF003366)
        self.assertTrue(self.dialog.designer.is_dirty())
        self.assertTrue(self.dialog.save_current())
        self.assertFalse(self.dialog.designer.is_dirty())
        self.assertEqual(IconTemplate.load(
            self.root / "icontemplates" / "action.command.ict").background, 0xFF003366)

    def test_slot_contract_opens_correct_template_and_parameter(self):
        capability = NavigationCapability("MX-Keypad", "ButtonArea", (7,), ())
        frame = KeypadFrame("plugin", "folder.main", "rev", capability,
            (SlotData(7, "placement", "placement.command", "action.command", "second"),))
        with self.assertRaisesRegex(NativeIctBindingError, "Vorschaumodus"):
            self.dialog.select_slot(KeypadViewState(frame), 7)
        self.dialog.select_slot(KeypadViewState(frame).with_mode("edit"), 7)
        self.assertTrue(self.dialog.edit_toggle.isChecked())
        self.assertEqual(self.dialog.binding.action_parameter, "second")
        self.assertIn("SDK-actionParameter", self.dialog.status.text())

    def test_studio_exposes_same_editor_without_changing_legacy_document(self):
        from library.templates import callback_project
        from library.document import ProjectDocument
        legacy = self.root / "legacy.json"
        legacy.write_text(json.dumps(callback_project()), encoding="utf-8")
        window = StudioWindow(legacy)
        self.addCleanup(window.close)
        original = window.document.raw
        popup = window.create_native_symbol_dialog(self.project)
        self.addCleanup(popup.close)
        self.assertIsInstance(popup, NativeSymbolDesignerDialog)
        self.assertEqual(window.document.raw, original)
        self.assertTrue(any(action.text() == "Native ICT / Symbol-Designer"
                            for action in window.findChildren(__import__("PySide6").QtGui.QAction)))


if __name__ == "__main__":
    unittest.main()
