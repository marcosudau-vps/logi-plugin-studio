"""Realistic Windows Editor -> SDK build -> standalone Python -> C# workflow."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapters.logitech.codegen import check_output_dir
from adapters.logitech.product import generate_product
from core.validate import validate_project
from studio.app import StudioWindow
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from probe_helpers import check_callback_process


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "autopilot" / "FINAL-PRODUCT-02" / "editor-workflow")
    args = parser.parse_args()
    output = check_output_dir(args.out)
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project.json"
    # A fresh project file is mandatory; do not silently replace a user's workflow.
    if project.exists():
        raise ValueError("Use a new workflow output directory; project already exists")
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = StudioWindow()
    window.show()
    errors = []
    window.show_error = lambda message: errors.append(str(message))
    evidence = {"level": "WINDOWS_EDITOR_SDK_STANDALONE_CSHARP", "hardware_test": False, "checks": []}
    try:
        window.new_callback_project()
        window.editor.id_field.setText("studio.mx.workflow02")
        window.editor.widgets["display_name"].setText("Eigenes MX-Keypad-Projekt")
        window.apply_editor()
        with patch("studio.app.QFileDialog.getSaveFileName", return_value=(str(project), "")):
            assert window.save_as()
        def select(section, eid):
            window.selection = (section, eid)
            window.refresh()
            return window.editor
        action_ids = ("action.focus", "action.capture", "action.review")
        select("components", "action.first").id_field.setText(action_ids[0])
        window.editor.config_form._fields["display_name"][0].setText("Fokus umschalten")
        window.apply_editor()
        select("components", "action.second").id_field.setText(action_ids[1])
        window.editor.config_form._fields["display_name"][0].setText("Aufnahme umschalten")
        window.apply_editor()
        select("components", action_ids[0])
        window.duplicate_entity()
        window.editor.id_field.setText(action_ids[2])
        window.editor.config_form._fields["display_name"][0].setText("Review umschalten")
        window.apply_editor()
        for action, name in zip(action_ids, ("handler.focus", "handler.capture", "handler.review")):
            select("components", "handler.toggle")
            window.duplicate_entity()
            window.editor.id_field.setText(name)
            window.apply_editor()
            binding_id = "binding.first" if action == action_ids[0] else "binding.second" if action == action_ids[1] else None
            if binding_id is None:
                window.add_entity("bindings")
                binding_id = window.selection[1]
            editor = select("bindings", binding_id)
            for side, owner, port in (("source", action, "activated"), ("target", name, "invoke")):
                widget = editor.widgets[side]
                index = next(i for i in range(widget.count()) if widget.itemData(i) ==
                             {"owner_kind": "component", "owner_id": owner, "port": port})
                widget.setCurrentIndex(index)
            window.apply_editor()
        select("components", "handler.toggle")
        with patch("studio.app.QMessageBox.question", return_value=__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes):
            window.remove_entity()
        image = QImage(90, 40, QImage.Format.Format_ARGB32)
        image.fill(QColor(45, 135, 95, 150))
        source = output / "input.png"
        assert image.save(str(source), "PNG")
        with patch("studio.app.QFileDialog.getOpenFileName", return_value=(str(source), "")), \
                patch("studio.app.QInputDialog.getText", return_value=("asset.workflow", True)):
            window.import_asset()
        select("assets", "asset.workflow").widgets["path"].setText("input.png")
        window.apply_editor()
        editor = select("presentations", "visual.mode")
        editor.table.cellWidget(0, 1).setText("Bereit fuer meine Aktion")
        editor.table.cellWidget(1, 1).setText("Meine Aktion ist aktiv")
        editor.table.cellWidget(1, 4).setText("asset.workflow")
        editor.table.cellWidget(1, 5).setCurrentText("contain")
        editor.table.cellWidget(1, 6).setText("20")
        window.apply_editor()
        editor = select("views", "view.main")
        editor._new_placement()
        row = editor.table.rowCount() - 1
        editor.table.cellWidget(row, 1).setCurrentText(action_ids[2])
        editor.table.cellWidget(row, 2).setCurrentText("visual.mode")
        window.apply_editor()
        select("views", "view.main")
        window.duplicate_entity()
        window.editor.id_field.setText("view.everything")
        for index in range(8):
            window.editor._new_placement()
            row = window.editor.table.rowCount() - 1
            window.editor.table.cellWidget(row, 1).setCurrentText(action_ids[index % 3])
            window.editor.table.cellWidget(row, 2).setCurrentText("visual.mode")
        window.apply_editor()
        expected = window.document.raw
        window.undo()
        window.redo()
        assert window.document.raw == expected
        assert window.save_project()
        window.close()
        window = StudioWindow(project)
        window.show_error = lambda message: errors.append(str(message))
        window.show()
        editor = select("components", action_ids[2])
        editor.id_field.setText("action.inspect")
        window.apply_editor()
        action_ids = (*action_ids[:2], "action.inspect")
        assert window.save_project()
        assert not validate_project(window.document.raw, window.document.registry)
        window.output.setText(str(output / "build"))
        window.assembly.setText("StudioWorkflow02")
        window.start_build()
        until = time.monotonic() + 120
        while window._build is not None and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert window._build is None and window.last_build is not None and not errors, errors
        build = window.last_build
        with patch("studio.app.QInputDialog.getText", return_value=("FINAL-PRODUCT-02", True)):
            window.start_export()
        until = time.monotonic() + 30
        while window._export is not None and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert window._export is None and '"crc_and_hashes_verified": true' in window.build_log.toPlainText()
        evidence["checks"].append("actual_gui_source_export_qthread_crc_sha_no_private_connections")
        window.pages.setCurrentIndex(1)
        window.preview_view.setCurrentText("view.everything")
        window.preview_variant.setCurrentText("active")
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert window.grab().save(str(output / "editor.png"), "PNG")
        evidence["checks"].append("three_free_actions_handlers_state_png_two_views_reuse_save_reopen_rename_undo_redo_sdk_worker")
        evidence["build"] = build["build"]
        plan = generate_product(project, raw_project=window.document.raw, output_dir=output / "build",
                                assembly_name="StudioWorkflow02")
        evidence["checks"].extend(check_callback_process(plan, project, output / "build", Path(build["connection"]),
                                                         output, window.document.raw, Path(window.sdk.text())))
        evidence["ok"] = True
        print(json.dumps(evidence, indent=2))
        return 0
    finally:
        if window._build is not None:
            window._build.wait(120000)
            app.processEvents()
        if window._export is not None:
            window._export.wait(30000)
            app.processEvents()
        window.document._saved = window.document.text
        window._raw_pending = False
        if window.editor:
            window.editor.pending = False
        window.close()
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
