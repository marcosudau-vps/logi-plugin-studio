"""Scriptable Studio operations for automated release checks (also frozen).

    LogiPluginStudio.exe --build <project.json> --mode native|compatible|shared [--handler rel.py] --out r.json
    LogiPluginStudio.exe --install <package-dir> --confirm <plugin-id> --out r.json
    LogiPluginStudio.exe --uninstall <plugin-id> --confirm <plugin-id> --name <SdkName> --out r.json

``--build`` drives the REAL main window and build controller (same path as the
"SDK-Plugin bauen" button). ``--install``/``--uninstall`` call the same
workflow as the Installation tab (directory method, own plugin only, explicit
plugin-ID confirmation, receipt, documented per-plugin reload, rollback on a
failed load). Nothing here bypasses a check of the interactive path.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _data_dir() -> Path:
    if os.environ.get("LOGI_STUDIO_DATA"):
        return Path(os.environ["LOGI_STUDIO_DATA"])
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LogiPluginStudio"


def _write(out: Path, row: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")


def build(project: Path, mode: str, handler: str | None, out: Path) -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from studio.native_shell import NativeStudioShell
    from studio.version import describe
    window = NativeStudioShell(str(project))
    row = {"operation": "build", "studio": describe(), "executable": sys.executable, "project": str(project),
           "mode": mode, "ok": False}
    try:
        controller = window.build_controller
        controller.set_folder_mode(mode)
        if handler:
            controller.handler.setText(handler)
        if not controller.start():
            row["error"] = controller.last_error
            return 1
        deadline = time.monotonic() + 600
        while controller.running and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.03)
        app.processEvents()
        result = controller.last_result
        if controller.last_error or not result:
            row["error"] = controller.last_error or "no build result"
            return 1
        from adapters.logitech.host_runtime import installed_runtime_status
        row.update(ok=True, output=result["output"], package=result["package"], plugin_id=result["plugin_id"],
                   folder_mode=result["folder_mode"], assembly=result.get("assembly"),
                   host_runtime=installed_runtime_status(result["package"]))
        return 0
    finally:
        window.close()
        app.processEvents()
        _write(out, row)


def install(package: Path, confirm: str, out: Path) -> int:
    from adapters.logitech import workflow
    from studio.version import describe
    row = {"operation": "install", "studio": describe(), "package": str(package), "ok": False}
    try:
        receipts = _data_dir() / "receipts" / time.strftime("%Y%m%d-%H%M%S")
        state = workflow.install_and_verify(package, confirm_plugin_id=confirm, receipt_dir=receipts,
                                            require_connection=True, method="directory")
        row.update(state.as_dict())
        row["ok"] = state.status["installed"] in ("INSTALLED", "UPDATED") and state.status["loaded"] == "LOADED" \
            and state.status["connection"] == "ACTIVE"
        return 0 if row["ok"] else 1
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return 1
    finally:
        _write(out, row)


def uninstall(plugin_id: str, confirm: str, name: str, out: Path) -> int:
    from adapters.logitech import workflow
    from studio.version import describe
    row = {"operation": "uninstall", "studio": describe(), "plugin_id": plugin_id, "ok": False}
    try:
        receipts = _data_dir() / "receipts" / time.strftime("%Y%m%d-%H%M%S")
        result = workflow.uninstall(plugin_id, confirm_plugin_id=confirm, receipt_dir=receipts,
                                    method="directory", plugin_name=name)
        row.update(result)
        row["ok"] = True
        return 0
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return 1
    finally:
        _write(out, row)
