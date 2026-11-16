from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from adapters.logitech.product import build_product, generate_product, provision_connection
from adapters.logitech.deployment import plan_install, plan_rollback, prepare_package, rollback_link
from adapters.logitech.errors import GenerationError
from delivery.export import export_sources
from runtime.wire import json_bytes
from runtime.wire import ConnectionSettings, LocalClient


class BuildWorker(QThread):
    progress = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, project_path: Path, raw: dict, output: Path, assembly: str, sdk: str,
                 *, folder_runtime: dict | None = None, folder_mode: str | None = None,
                 shared_references: list | None = None, shared_handler: str | None = None):
        super().__init__()
        self.project_path, self.raw, self.output, self.assembly, self.sdk = project_path, raw, output, assembly, sdk
        self.folder_runtime = folder_runtime
        # None keeps the historical call (generator default "compatible").
        self.folder_mode = folder_mode
        self.shared_references, self.shared_handler = shared_references, shared_handler
        self._cancel = False

    def cancel(self):
        """Cooperative cancel between stages; a running dotnet build completes first."""
        self._cancel = True

    def _checkpoint(self):
        if self._cancel:
            raise GenerationError("BUILD_CANCELLED: Build vom Benutzer abgebrochen; keine Installation.")

    def run(self):
        try:
            self.progress.emit("Core-/Capability-Gate und reproduzierbare Generierung ...")
            options = {}
            if self.folder_mode is not None:
                # Studio builds start their own host with a plugin-local runtime.
                options.update(folder_mode=self.folder_mode, embed_host=True, shared_handler=self.shared_handler)
            if self.folder_mode == "shared":
                options.update(shared_references=self.shared_references)
            plan = generate_product(self.project_path, raw_project=self.raw, output_dir=self.output,
                                    assembly_name=self.assembly, sdk_dll=self.sdk,
                                    folder_runtime=self.folder_runtime, **options)
            self._checkpoint()
            self.progress.emit("dotnet build gegen die angegebene echte PluginApi.dll ...")
            result = build_product(plan, self.output, log_path=self.output / "build.log")
            self.progress.emit(result.stdout + result.stderr)
            self._checkpoint()
            connection = provision_connection(plan, self.output)
            package = prepare_package(plan, self.output, connection)
            host_bundle = None
            mode = plan.manifest["folder_runtime"]["mode"]
            if mode != "shared" and "native-host.pyz" in plan.files:
                # Same bytes as the bundle embedded in the plugin DLL; lets the
                # Studio test the build output before it is installed.
                host_bundle = self.output / "native-host.pyz"
            self.succeeded.emit({"build": result.as_dict(), "connection": str(connection),
                                 "package": str(package), "plugin_id": plan.plugin_id,
                                 "manifest": plan.manifest, "output": str(self.output),
                                 "folder_mode": mode, "host_bundle": str(host_bundle) if host_bundle else None,
                                 "assembly": plan.assembly_name,
                                 "host_runtime": (plan.manifest.get("host_runtime") or {}).get("self_hosted", False)})
        except Exception:
            self.failed.emit(traceback.format_exc())


class DiagnosticWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, connection: str):
        super().__init__()
        self.connection = connection

    def run(self):
        try:
            client = LocalClient(ConnectionSettings.load(self.connection))
            handshake = client.handshake()
            snapshot = client.snapshot()
            self.succeeded.emit({"level": "AUTHENTICATED_LOCAL_HOST", "hardware_test": False,
                                 "handshake": handshake, "snapshot": snapshot})
        except Exception:
            self.failed.emit(traceback.format_exc())


class DeploymentWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, package: str, *, save_path: str | None = None, action: str = "install-plan",
                 confirm_plugin_id: str | None = None, expected_plan: dict | None = None):
        super().__init__()
        self.package = package
        self.save_path, self.action = save_path, action
        self.confirm_plugin_id, self.expected_plan = confirm_plugin_id, expected_plan

    def run(self):
        try:
            if self.action == "install-plan":
                result = plan_install(self.package)
            elif self.action in ("rollback-plan", "rollback"):
                result = plan_rollback(self.package)
                if self.action == "rollback":
                    if result != self.expected_plan:
                        raise GenerationError("Rollback plan changed; repeat read-only verification")
                    rollback_link(self.package, confirm_plugin_id=self.confirm_plugin_id)
                    result = {**result, "authorization": "EXPLICIT_USER_COMMAND", "completed": True}
            else:
                raise GenerationError("Unknown deployment worker operation")
            if self.save_path:
                with Path(self.save_path).open("xb") as handle:
                    handle.write(json_bytes(result))
                result = {**result, "saved_plan": self.save_path}
            self.succeeded.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class ExportWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, root: Path, run: str, output: Path):
        super().__init__()
        self.root, self.review_run, self.output = root, run, output

    def run(self):
        from delivery.export import ExportError
        try:
            self.succeeded.emit(export_sources(self.root, self.output, run=self.review_run))
        except (ExportError, OSError, ValueError):
            # Never include source content or the value of a connection key.
            self.failed.emit("SAFE_EXPORT_REFUSED: Quellarchiv nicht freigegeben; Quellen lokal pruefen. "
                             "Kein Vollprojekt-ZIP teilen.")
