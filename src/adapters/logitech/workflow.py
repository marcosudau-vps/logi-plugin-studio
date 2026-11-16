"""Own-plugin deployment workflow: validate → plan → install/update → reload →
diagnose → verify → (automatic) rollback, plus explicit uninstall.

Default method ``directory``: the package is copied into the Studio-owned
plugin directory ``Plugins/<SdkName>/`` of the Logi Plugin Service (loaded
live by the per-plugin reload). Method ``link``: ONE Studio-owned
``<plugin_id>.link`` development link (read by the service only at its start).
Every state change is preceded by a fresh dry run, a byte backup in a private
receipt and a collision check. The only service interaction is the
SDK-documented per-plugin reload deep link. Foreign plugins, profiles and
service processes are never touched. The status vocabulary is the one shown in
the Studio deployment tab.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from runtime.wire import ConnectionSettings, LocalClient, json_bytes

from . import deployment, directory_install, service
from .errors import GenerationError

STATUS_KEYS = ("build", "package", "installed", "loaded", "connection", "hardware", "rollback")


@dataclass
class WorkflowState:
    plugin_id: str
    package: str
    plugin_name: str | None = None
    mode: str | None = None
    status: dict = field(default_factory=lambda: {
        "build": "UNKNOWN", "package": "UNKNOWN", "installed": "NO", "loaded": "UNKNOWN",
        "connection": "UNKNOWN", "hardware": "HARDWARE_PENDING", "rollback": "NOT_AVAILABLE"})
    steps: list = field(default_factory=list)
    receipt: str | None = None
    install_plan: dict | None = None
    method: str = "directory"
    loaded_from: str | None = None

    def log(self, step: str, result: str, **detail):
        self.steps.append(dict(time=time.time(), step=step, result=result, **detail))

    def as_dict(self) -> dict:
        return {"plugin_id": self.plugin_id, "package": self.package, "plugin_name": self.plugin_name,
                "mode": self.mode, "status": dict(self.status), "steps": list(self.steps),
                "receipt": self.receipt, "install_plan": self.install_plan, "method": self.method,
                "loaded_from": self.loaded_from}


class ServiceAdapter:
    """Indirection so automated tests can replace the real Logi Plugin Service."""

    def reload(self, name: str) -> dict:
        return service.request_plugin_reload(name)

    def diagnose(self, name: str, package: str, since: float) -> dict:
        return service.diagnose_plugin_load(name, package, since=since)

    def shared_hosts(self, connection: str) -> list[dict]:
        return service.shared_host_processes(connection)


def validate(package: str | Path, state: WorkflowState | None = None) -> WorkflowState:
    package = Path(package).resolve()
    marker, settings = deployment._validate_package(package)
    state = state or WorkflowState(settings.plugin_id, str(package))
    state.plugin_name = service.package_plugin_name(package)
    resources = sorted(k for k in marker["files"] if deployment.resource_role(Path(k).as_posix()) is not None)
    state.status["package"] = "VALID"
    state.log("validate", "OK", files=len(marker["files"]), resources=resources)
    return state


METHODS = ("directory", "link")


def plan(package: str | Path, *, target_root: Path | None = None,
         method: str = "directory") -> tuple[WorkflowState, dict]:
    """Dry run. ``directory`` (default) is live-loadable by the documented
    per-plugin reload; ``link`` is the SDK development link (service start)."""
    if method not in METHODS:
        raise GenerationError("Unknown installation method")
    state = validate(package)
    state.method = method
    if method == "directory":
        install_plan = directory_install.plan_install(state.package, target_root=target_root)
        state.loaded_from = install_plan["target"]
    else:
        install_plan = deployment.plan_install(state.package, target_root=target_root)
        state.loaded_from = state.package
    state.install_plan = install_plan
    state.log("plan", "OK", operation=install_plan["operation"], target=install_plan["target"])
    return state, install_plan


def _wait_loaded(state, adapter, since, timeout):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = adapter.diagnose(state.plugin_name, state.loaded_from or state.package, since)
        if last["status"] in ("LOADED", "LOAD_FAILED", "LOADED_FROM_OTHER_PATH"):
            break
        time.sleep(0.5)
    return last


def check_connection(state: WorkflowState, adapter: ServiceAdapter, *, timeout: float = 10.0) -> str:
    connection = Path(state.package) / "bin" / "studio.connection.json"
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            client = LocalClient(ConnectionSettings.load(connection))
            client.handshake()
            state.status["connection"] = "ACTIVE"
            state.log("connection", "ACTIVE")
            return "ACTIVE"
        except Exception as exc:  # host not (yet) reachable
            error = type(exc).__name__
        time.sleep(0.5)
    state.status["connection"] = "HOST_NOT_RUNNING"
    state.log("connection", "HOST_NOT_RUNNING", error=error)
    return "HOST_NOT_RUNNING"


def install_and_verify(package: str | Path, *, confirm_plugin_id: str, receipt_dir: str | Path,
                       expected_plan: dict | None = None, reload: bool = True, load_timeout: float = 25.0,
                       require_connection: bool = False, rollback_on_failure: bool = True,
                       adapter: ServiceAdapter | None = None, method: str = "directory") -> WorkflowState:
    """Install or update ONE own plugin and prove the result; roll back on failure."""
    adapter = adapter or ServiceAdapter()
    state, live = plan(package, method=method)
    if expected_plan is not None and expected_plan != live:
        raise GenerationError("Installation plan changed since it was shown; review the new plan")
    if confirm_plugin_id != state.plugin_id:
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    since = time.time() - 1
    if method == "directory":
        receipt = directory_install.install(live, confirm_plugin_id=confirm_plugin_id, receipt_dir=receipt_dir)
    else:
        receipt = deployment.install_link(live, confirm_plugin_id=confirm_plugin_id, receipt_dir=receipt_dir)
    state.receipt = str(receipt)
    state.status["installed"] = "UPDATED" if live["operation"] == "update_own" else "INSTALLED"
    state.status["rollback"] = "AVAILABLE"
    state.log("install", "OK", receipt=str(receipt), operation=live["operation"])
    from .host_runtime import installed_runtime_status
    runtime = installed_runtime_status(state.loaded_from or state.package)
    state.log("host_runtime", runtime["status"], directory=runtime.get("directory"),
              version=runtime.get("runtime_version"))
    failure = None
    if reload:
        try:
            result = adapter.reload(state.plugin_name)
            state.log("reload", "REQUESTED", returncode=result.get("returncode"), url=result.get("url"))
        except GenerationError as exc:
            state.log("reload", "UNAVAILABLE", error=str(exc))
        diagnosis = _wait_loaded(state, adapter, since, load_timeout)
        state.status["loaded"] = diagnosis["status"] if diagnosis else "UNKNOWN"
        state.log("diagnose", state.status["loaded"], errors=(diagnosis or {}).get("errors", []))
        if state.status["loaded"] in ("LOAD_FAILED", "LOADED_FROM_OTHER_PATH"):
            failure = "PLUGIN_NOT_LOADED"
        elif method == "directory":
            # The reload released the previous host: drop superseded locked files.
            left = directory_install.purge_retired(live["target"], attempts=10, delay=0.5)
            if left:
                state.log("retired_files", "PENDING", files=left)
    if failure is None and require_connection:
        if check_connection(state, adapter) != "ACTIVE":
            failure = "CONNECTION_NOT_ACTIVE"
    if failure is not None and rollback_on_failure:
        rollback(state, adapter=adapter, reason=failure, reload=reload)
    return state


def rollback(state: WorkflowState, *, adapter: ServiceAdapter | None = None, reason: str = "USER",
             reload: bool = True) -> WorkflowState:
    adapter = adapter or ServiceAdapter()
    if state.receipt is None:
        raise GenerationError("No installation receipt; nothing to roll back")
    if state.method == "directory":
        operation = directory_install.rollback(state.receipt, confirm_plugin_id=state.plugin_id)["operation"]
    else:
        operation = deployment.plan_rollback(state.receipt)["operation"]
        deployment.rollback_link(state.receipt, confirm_plugin_id=state.plugin_id)
    state.status["installed"] = "ROLLED_BACK"
    state.status["rollback"] = "EXECUTED"
    state.log("rollback", "OK", reason=reason, operation=operation)
    if reload and state.plugin_name:
        try:
            adapter.reload(state.plugin_name)
            state.log("reload_after_rollback", "REQUESTED")
        except GenerationError as exc:
            state.log("reload_after_rollback", "UNAVAILABLE", error=str(exc))
    return state


def uninstall(plugin_id: str, *, confirm_plugin_id: str, receipt_dir: str | Path,
              reload: bool = True, adapter: ServiceAdapter | None = None,
              target_root: Path | None = None, plugin_name: str | None = None,
              method: str = "link") -> dict:
    """Remove ONE own installation (link or own plugin directory); receipts allow restore."""
    adapter = adapter or ServiceAdapter()
    if method == "directory":
        if not plugin_name:
            raise GenerationError("SDK plugin name required for directory uninstall")
        dry = directory_install.plan_uninstall(plugin_name, plugin_id, target_root=target_root)
        receipt = directory_install.uninstall(dry, confirm_plugin_id=confirm_plugin_id, receipt_dir=receipt_dir,
                                              target_root=target_root)
        name, package_kept = plugin_name, None
    else:
        dry = deployment.plan_uninstall(plugin_id, target_root=target_root)
        name = service.package_plugin_name(dry["package"])
        receipt = deployment.uninstall_link(dry, confirm_plugin_id=confirm_plugin_id, receipt_dir=receipt_dir,
                                            target_root=target_root)
        package_kept = dry["package"]
    # Keypad assignments live in the user's Options+ profile, which Studio never edits.
    profile_note = "OPTIONS_PLUS_ASSIGNMENTS_MAY_REMAIN"
    result = {"plugin_id": plugin_id, "plugin_name": name, "receipt": str(receipt), "removed": dry["target"],
              "package_kept": package_kept, "method": method, "reload": None, "profile_note": profile_note,
              "residual_files": 0}
    if reload:
        try:
            result["reload"] = adapter.reload(name)
        except GenerationError as exc:
            result["reload"] = {"error": str(exc)}
    if method == "directory":
        # Runtime files of a host that was still running were moved aside;
        # after the reload released them they are deleted (own files only).
        target = Path(dry["target"])
        result["residual_files"] = directory_install.purge_retired(target, attempts=12 if reload else 1, delay=0.5)
        directory_install._remove_empty_tree(target)
        result["directory_removed"] = not target.exists()
    return result


def save_state(state: WorkflowState, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(state.as_dict()))
    return path
