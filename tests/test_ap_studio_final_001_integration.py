"""Real Qt integration of the accepted Studio widgets and native writers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QByteArray, QMimeData, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from studio.keypad_contract import ActionOffer, EditRequest, SlotAddress
from studio.keypad_preview.mime import ACTION_REF_MIME, encode_action_ref
from studio.native_session import NativeProjectSession, NativeSessionError
from studio.native_shell import NativeStudioShell
from studio.native_shell.ict_session import SessionIctCoordinator
from studio.native_ict_binding import NativeIctBindingError
from studio.native_symbol_dialog import NativeSymbolDesignerDialog
from studio.virtual_folders.binding import extension_path
from studio.virtual_folders.model import PagingCapability, Reference
from symbol_designer.ict import IconTemplate


class StudioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ap-studio-final-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "project.json"
        self.raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        self.raw["folders"][0]["entries"][0]["action_parameter"] = "second"
        self.write_project()
        self.window = NativeStudioShell(self.path)
        self.addCleanup(self.dispose)
        self.window.show()
        self.app.processEvents()
        self.host = self.window.coordinator
        self.binding = self.window.keypad
        self.preview = self.binding.widget

    def write_project(self):
        self.path.write_text(json.dumps(self.raw, ensure_ascii=False), encoding="utf-8")

    def dispose(self):
        if self.window.build_controller.running:
            self.window.build_controller.worker.wait(120_000)
            self.app.processEvents()
        if self.window.composer:
            self.window.composer.dispose()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def open_preview(self, *, virtual=False, edit=False):
        self.window.tabs.setCurrentWidget(self.binding.panel)
        if virtual:
            self.binding.source.setCurrentIndex(self.binding.source.findData("virtual"))
        self.binding.edit.setChecked(edit)
        self.app.processEvents()

    def address(self, index):
        frame = self.preview.frame()
        return SlotAddress(frame.view_id, frame.page_index, index, frame.slots[index].placement_id)

    def click(self, index):
        QTest.mouseClick(self.preview, Qt.MouseButton.LeftButton,
                         pos=self.preview.slot_rect(index).center().toPoint())
        self.app.processEvents()

    def commit_folder(self, update):
        return self.window.composer._commit(update)

    def add_virtual(self, action="action.command", parameter="second"):
        composer = self.window.composer
        self.commit_folder(composer.document.add_action(
            composer.navigation.folder_id, Reference(composer.document.plugin_id, action),
            composer.navigation.page_id, action_parameter=parameter))

    def test_active_native_keypad_without_sidecar_and_selection(self):
        self.open_preview()
        print("Qt platform:", self.app.platformName(), flush=True)
        expected = os.environ.get("AP_STUDIO_EXPECT_QT")
        if expected:
            self.assertEqual(self.app.platformName(), expected)
        frame = self.preview.frame()
        self.assertTrue(self.preview.isVisible())
        self.assertEqual(frame.capability.device_type, "Loupedeck70")
        self.assertEqual(frame.capability.area, "None")
        self.assertEqual(frame.capability.navigation_slots, ())
        self.assertEqual(len(frame.slots), 9)
        self.assertEqual(frame.slots[0].label, "Zweite Variante")
        self.assertEqual(frame.slots[1].label, "Aus")
        self.assertEqual([s.role for s in frame.slots[2:4]], ["unavailable", "unavailable"])
        self.assertIn("Encoder", frame.slots[2].tooltip)
        self.assertIn("ActionEditorCommand", frame.slots[3].tooltip)
        original = self.path.read_bytes()
        self.click(0)
        self.assertEqual(self.host.selection, ("folder_entry", "placement.command"))
        self.assertEqual(self.host.action_parameter, "second")
        self.assertEqual(self.window.inspector.draft.action_id, "action.command")
        self.assertTrue(self.window.ict_action.isEnabled())
        self.assertFalse(self.host.session.dirty)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(extension_path(self.path).exists())

    def test_saved_sidecar_manual_pages_link_and_back(self):
        self.open_preview(virtual=True, edit=True)
        composer = self.window.composer
        root = composer.document.root_id
        self.commit_folder(composer.document.set_mode(root, "manual"))
        with patch.object(composer, "_name", return_value="Zweite Seite"):
            self.preview.pageCreateRequested.emit()
        self.assertEqual(self.preview.frame().page_count, 2)
        self.assertEqual(self.preview.frame().page_index, 1)
        self.add_virtual()
        result, child = composer.document.create_folder("Ziel")
        self.commit_folder(result.add_link(root, Reference(composer.document.plugin_id, child),
                                           composer.navigation.page_id))
        self.assertTrue(self.window.save_folders())
        self.assertTrue(self.window.reload_project())
        self.assertTrue(self.binding.virtual)
        self.assertFalse(self.preview.editing_active())
        self.preview.pageRequested.emit(1)
        self.assertEqual(self.preview.frame().slots[0].action_parameter, "second")
        self.assertEqual(self.preview.frame().slots[1].label, "Link · Ziel")
        self.click(1)
        self.assertEqual(self.window.composer.navigation.folder_id, child)
        self.assertEqual(self.preview.frame().view_id, "virtual:" + child)
        self.binding.back.click()
        self.assertEqual(self.window.composer.navigation.folder_id, root)
        self.assertEqual(self.preview.frame().page_index, 1)

    def test_inspector_native_history_save_reload_and_project_switch(self):
        self.open_preview()
        self.click(0)
        session = self.host.session
        draft = self.window.inspector.draft
        params = session.snapshot()["actions"][0]["parameters"]
        params[1]["display_name"] = "Neu aus Inspector"
        draft.set_field("parameters", params)
        self.window.inspector.applyRequested.emit(draft.action_id, draft.base_revision, draft.proposed_action())
        self.assertEqual(self.preview.frame().slots[0].label, "Neu aus Inspector")
        self.binding.edit.setChecked(True)
        self.preview.undoRequested.emit()
        self.assertEqual(self.preview.frame().slots[0].label, "Zweite Variante")
        self.preview.redoRequested.emit()
        self.assertEqual(self.preview.frame().slots[0].label, "Neu aus Inspector")
        self.assertTrue(self.window.save_project())
        self.assertTrue(self.window.reload_project())
        self.assertEqual(self.preview.frame().slots[0].label, "Neu aus Inspector")
        token = self.preview.frame().context_id
        other = self.root / "other.json"
        self.raw["folders"][0]["entries"] = []
        other.write_text(json.dumps(self.raw), encoding="utf-8")
        self.assertTrue(self.window.open_project(other))
        self.assertNotEqual(self.preview.frame().context_id, token)
        self.assertTrue(all(slot.role == "empty" for slot in self.preview.frame().slots))
        self.assertIsNone(self.preview.selection())

    def test_drop_copy_move_remove_and_separate_history(self):
        self.open_preview(virtual=True, edit=True)
        original = self.path.read_bytes()
        session = self.host.session
        composer = self.window.composer
        document = composer.document
        self.commit_folder(document.set_mode(document.root_id, "manual"))
        self.commit_folder(composer.document.add_page(document.root_id, "Weitere"))
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(ActionOffer("action.command", "Test", "second"))))
        drop = QDropEvent(self.preview.slot_rect(0).center(), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        with patch.object(composer.store, "commit", wraps=composer.store.commit) as commit, \
                patch.object(session, "replace", wraps=session.replace) as replace:
            self.preview.dropEvent(drop)
            self.assertTrue(drop.isAccepted())
            commit.assert_called_once()
            replace.assert_not_called()
        source = self.address(0)
        revision = self.preview.frame().revision
        self.preview.pageRequested.emit(1)
        self.assertEqual(self.preview.frame().revision, revision)
        self.assertTrue(self.binding.apply_edit(EditRequest("copy", revision, "copy",
                        source=source, target=self.address(0))))
        self.assertNotEqual(self.address(0).placement_id, source.placement_id)
        self.assertFalse(self.binding.apply_edit(EditRequest("stale", revision, "move",
                         source=source, target=self.address(1))))
        revision = self.preview.frame().revision
        self.assertTrue(self.binding.apply_edit(EditRequest("move", revision, "move",
                        source=source, target=self.address(1))))
        self.assertEqual(self.address(1).placement_id, source.placement_id)
        self.assertTrue(self.binding.apply_edit(EditRequest("remove", self.preview.frame().revision,
                        "remove", source=self.address(1))))
        self.preview.undoRequested.emit()
        self.assertEqual(self.address(1).placement_id, source.placement_id)
        self.preview.redoRequested.emit()
        self.assertIsNone(self.address(1).placement_id)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(session.dirty)
        self.assertTrue(composer.store.dirty)

    def test_unsupported_page_creation_automatic_placement_and_bad_drop(self):
        self.open_preview(virtual=True, edit=True)
        composer = self.window.composer
        root = composer.document.root_id
        self.preview.pageCreateRequested.emit()
        self.assertEqual(self.preview.frame().page_count, 1)
        request = EditRequest("gap", self.preview.frame().revision, "place", target=self.address(8),
                              action_id="action.command", action_parameter="second")
        self.assertFalse(self.binding.apply_edit(request))
        self.assertIn("nächsten freien", self.binding.message.text())
        request = EditRequest("invalid", self.preview.frame().revision, "place", target=self.address(0),
                              action_id="action.command", action_parameter="missing")
        self.assertFalse(self.binding.apply_edit(request))
        self.commit_folder(composer.document.set_mode(root, "auto", PagingCapability(2, "Autorenmodell")))
        self.assertFalse(self.preview._is_free_target(0))
        self.assertFalse(composer.document.placements)

    def run_dialog(self, trigger, exercise):
        errors = []

        def interact():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertIsInstance(dialog, NativeSymbolDesignerDialog)
                exercise(dialog)
            except BaseException as exc:
                errors.append(exc)
            finally:
                if isinstance(dialog, NativeSymbolDesignerDialog):
                    # Never hang the test if an assertion leaves a dirty dialog.
                    with patch.object(dialog, "_confirm_unsaved", return_value=True):
                        dialog.reject()
                elif dialog is not None:
                    dialog.close()

        QTimer.singleShot(0, interact)
        trigger()
        self.app.processEvents()
        if errors:
            raise errors[0]

    def test_preview_symbol_commit_uses_session_and_refreshes(self):
        self.open_preview(edit=True)
        session = self.host.session
        self.host.rename_action("action.editor", "Andere ungespeicherte Änderung", base_revision=session.revision)
        self.assertTrue(session.dirty)
        self.assertIsNone(self.preview.frame().slots[0].tile_image)

        def exercise(dialog):
            self.assertEqual(dialog.binding.action_id, "action.command")
            self.assertEqual(dialog.binding.action_parameter, "second")
            self.assertTrue(dialog.edit_toggle.isChecked())
            dialog.designer.set_background(0xFF0055AA)
            self.assertFalse(self.window.build_controller.start())
            self.assertFalse(self.window.open_project(self.path))
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            with patch.object(session, "save", wraps=session.save) as save:
                self.assertTrue(dialog.save_current())
                save.assert_called_once()
            self.assertFalse(dialog.designer.is_dirty())
            self.assertEqual(dialog.binding.action_parameter, "second")
            self.assertIsNotNone(self.preview.frame().slots[0].tile_image)

        self.run_dialog(lambda: self.preview.symbolEditRequested.emit(self.address(0)), exercise)
        persisted = NativeProjectSession.load(self.path).snapshot()
        self.assertEqual(persisted["actions"][3]["display_name"], "Andere ungespeicherte Änderung")
        self.assertEqual(persisted["actions"][0]["icon_template"], "icontemplates/action.command.ict")
        self.assertFalse(session.dirty)
        self.assertEqual(IconTemplate.load(self.root / persisted["actions"][0]["icon_template"]).background,
                         0xFF0055AA)

    def test_symbol_dialog_cancel_discard_and_save_on_close(self):
        self.host.select_offer(self.window.catalog.offer_for("action.command", "second"))
        def exercise(dialog):
            self.assertFalse(dialog.edit_toggle.isChecked())
            dialog.edit_toggle.setChecked(True)
            dialog.designer.set_text("Entwurf")
            answer = QMessageBox.StandardButton
            with patch("studio.native_symbol_dialog.QMessageBox.question", return_value=answer.Cancel):
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
                self.assertTrue(dialog.isVisible())
                self.assertTrue(dialog.designer.is_dirty())
                dialog.action_combo.setCurrentIndex(1)
                self.assertEqual(dialog.action_combo.currentData(), "action.command")
            with patch("studio.native_symbol_dialog.QMessageBox.question", return_value=answer.Discard):
                dialog.action_combo.setCurrentIndex(1)
                self.assertEqual(dialog.binding.action_id, "action.multistate")
                self.assertFalse(dialog.designer.is_dirty())
            dialog.designer.set_text("Speichern beim Schließen")
            with patch("studio.native_symbol_dialog.QMessageBox.question", return_value=answer.Save):
                self.assertTrue(dialog.close())

        self.run_dialog(self.window.ict_action.trigger, exercise)
        self.assertFalse((self.root / "icontemplates/action.command.ict").exists())
        self.assertEqual(IconTemplate.load(self.root / "icontemplates/action.multistate.ict").text,
                         "Speichern beim Schließen")

    def test_fork_rollback_retains_exact_session_revision_and_redo(self):
        session = self.host.session
        self.host.rename_action("action.editor", "Undoable", base_revision=session.revision)
        self.host.rename_action("action.editor", "Redoable", base_revision=session.revision)
        self.host.undo()
        before, revision, disk = session.snapshot(), session.revision, self.path.read_bytes()
        binding = SessionIctCoordinator(session, lambda: True)
        target = binding.open_action("action.command")
        with patch.object(session, "save", side_effect=NativeSessionError("gesperrt")):
            with self.assertRaisesRegex(NativeSessionError, "gesperrt"):
                binding.save(target, target.template)
        self.assertEqual(session.snapshot(), before)
        self.assertEqual(session.revision, revision)
        self.assertTrue(session.dirty)
        self.assertTrue(session.can_redo)
        self.assertEqual(self.path.read_bytes(), disk)
        self.assertFalse(target.target.exists())
        session.redo()
        self.assertEqual(session.snapshot()["actions"][3]["display_name"], "Redoable")

    def test_private_asset_conflict_readonly_invalid_and_no_json_write(self):
        target = self.root / "private.ict"
        IconTemplate().save(target)
        self.raw["actions"][0]["icon_template"] = "private.ict"
        self.write_project()
        self.assertTrue(self.window.reload_project())
        session = self.host.session
        binding = SessionIctCoordinator(session, lambda: True)
        opened = binding.open_action("action.command")
        original = self.path.read_bytes()
        with patch.object(session, "save") as save:
            edited = opened.template.copy()
            edited.text = "Private ICT"
            binding.save(opened, edited)
            save.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(IconTemplate.load(target).text, "Private ICT")
        opened = binding.open_action("action.command")
        target.chmod(stat.S_IREAD)
        try:
            with self.assertRaisesRegex(NativeIctBindingError, "schreibgeschützt"):
                binding.save(opened, edited)
        finally:
            target.chmod(stat.S_IREAD | stat.S_IWRITE)
        target.write_bytes(b"external invalid")
        with self.assertRaisesRegex(NativeIctBindingError, "extern verändert"):
            binding.save(opened, edited)
        with self.assertRaises(NativeIctBindingError):
            binding.open_action("action.command")
        self.assertEqual(target.read_bytes(), b"external invalid")

    def test_project_conflict_and_racing_new_asset_do_not_overwrite(self):
        session = self.host.session
        binding = SessionIctCoordinator(session, lambda: True)
        opened = binding.open_action("action.command")
        external = self.path.read_bytes() + b"\n"
        self.path.write_bytes(external)
        with self.assertRaisesRegex(NativeSessionError, "extern verändert"):
            binding.save(opened, opened.template)
        self.assertEqual(self.path.read_bytes(), external)
        self.assertFalse(opened.target.exists())
        self.assertTrue(self.window.reload_project())
        session = self.host.session
        binding = SessionIctCoordinator(session, lambda: True)
        opened = binding.open_action("action.command")
        real_link = os.link

        def competing_link(source, target):
            target.write_bytes(b"anderer Writer")
            real_link(source, target)

        with patch("studio.native_shell.ict_session.os.link", side_effect=competing_link):
            with self.assertRaises(FileExistsError):
                binding.save(opened, opened.template)
        self.assertEqual(opened.target.read_bytes(), b"anderer Writer")
        self.assertEqual(self.path.read_bytes(), external)

    @unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Echte Logitech SDK DLL fehlt")
    def test_real_build_uses_session_ict_and_sidecar(self):
        self.open_preview(virtual=True)
        self.add_virtual()
        self.assertTrue(self.window.save_folders())
        session = self.host.session
        binding = SessionIctCoordinator(session, lambda: True)
        opened = binding.open_action("action.command")
        target = binding.save(opened, opened.template)
        project_before, sidecar_before = self.path.read_bytes(), extension_path(self.path).read_bytes()
        controller = self.window.build_controller
        with patch("studio.native_shell.build_controller.ROOT", self.root):
            self.assertTrue(controller.start())
        deadline = time.monotonic() + 100
        while controller.running and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(25)
        self.assertFalse(controller.running)
        self.assertIsNone(controller.last_error, controller.log.toPlainText())
        output = Path(controller.last_result["output"])
        copied, = (output / "icontemplates").glob("*.ict")
        self.assertEqual(copied.read_bytes(), target.read_bytes())
        self.assertTrue((Path(controller.last_result["package"]) / "studio.package.json").is_file())
        self.assertEqual(self.path.read_bytes(), project_before)
        self.assertEqual(extension_path(self.path).read_bytes(), sidecar_before)

    def test_unsaved_private_link_forks_and_preserves_existing_asset(self):
        path = self.root / "other.ict"
        initial = IconTemplate()
        initial.text = "Andere Vorlage"
        initial.save(path)
        self.raw["actions"][1]["icon_template"] = "other.ict"
        self.write_project()
        self.assertTrue(self.window.reload_project())
        session = self.host.session
        raw = session.snapshot()
        raw["actions"][0]["icon_template"] = "other.ict"
        del raw["actions"][1]["icon_template"]
        session.replace(raw, base_revision=session.revision)
        coordinator = SessionIctCoordinator(session, lambda: True)
        opened = coordinator.open_action("action.command")
        self.assertTrue(opened.forked)
        edited = opened.template.copy()
        edited.text = "Separat"
        target = coordinator.save(opened, edited)
        self.assertEqual(IconTemplate.load(path).text, "Andere Vorlage")
        self.assertEqual(IconTemplate.load(target).text, "Separat")
        self.assertEqual(NativeProjectSession.load(self.path).snapshot(), session.snapshot())

    def test_authored_svg_and_inherited_ict_are_rendered_without_mutation(self):
        (self.root / "action.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<rect width="20" height="20" fill="red"/></svg>', encoding="utf-8")
        self.raw["actions"][0]["icon"] = "action.svg"
        self.write_project()
        self.assertTrue(self.window.reload_project())
        image = self.preview.frame().slots[0].tile_image
        self.assertIsNotNone(image)
        self.assertEqual(image.pixelColor(58, 58).name(), "#ff0000")
        template = IconTemplate()
        template.background = 0xFF123456
        template.save(self.root / "inherited.ict")
        del self.raw["actions"][0]["icon"]
        self.raw["plugin"]["default_icon_template"] = "inherited.ict"
        self.write_project()
        self.assertTrue(self.window.reload_project())
        image = self.preview.frame().slots[0].tile_image
        self.assertEqual(image.pixelColor(0, 0).name(), "#123456")
        self.assertFalse(self.host.session.dirty)
