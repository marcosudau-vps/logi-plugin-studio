"""Live-loadable own installation: ``Plugins\\<SdkName>\\`` owned by Studio.

Observed on LogiPluginService 6.4.2 (AP-RELEASE-FINAL-001, 08.11.2026):
* development ``.link`` files are read only at service start;
* the documented per-plugin reload ``loupedeck://plugin/<SdkName>/reload``
  loads ``Plugins\\<SdkName>\\`` immediately ("Plugin ... loaded from ...");
* the service keeps a handle on that directory (it cannot be renamed), but
  plugin files are not locked.

Hence updates replace OWN files one by one (temporary file + ``os.replace``)
after a full byte backup into a private receipt; the Studio marker is written
last, so an interrupted update is never mistaken for a complete one. Only
directories whose marker proves this plugin identity are ever changed.

Since AP-POLISH-001 a package may contain its plugin-local host runtime
(``bin/hostruntime-<id>/``). While the plugin runs, Windows locks those
executable images: unchanged files are therefore never rewritten, and an own
superseded file that cannot be deleted is renamed into ``bin/.studio-retired``
(permitted for in-use images on the same volume) and purged once released.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import time
from pathlib import Path

from runtime.wire import json_bytes, parse_json

from .codegen import check_output_dir
from . import deployment
from .deployment import _hash, _validate_package
from .errors import GenerationError

INSTALL_FORMAT = "studio-directory-plan-1"
RECEIPT_FORMAT = "studio-directory-receipt-1"
UNINSTALL_FORMAT = "studio-directory-uninstall-receipt-1"
MARKER = "studio.package.json"


def _posix(files: dict) -> dict:
    return {Path(k).as_posix(): v for k, v in files.items()}


def _sdk_name(package: Path) -> str:
    from .service import package_plugin_name
    return package_plugin_name(package)


def owned(directory: Path):
    """(marker, settings) of a Studio-owned installed directory, else None."""
    if not (directory / MARKER).is_file():
        return None
    try:
        return _validate_package(directory, allow_legacy=True)
    except GenerationError:
        return None


def plan_install(package_path: str | Path, *, target_root: Path | None = None) -> dict:
    package = Path(package_path).resolve()
    marker, settings = _validate_package(package)
    name = _sdk_name(package)
    root = (target_root if target_root is not None else deployment.plugin_directory()).resolve()
    target = root / name
    if target == root or not target.resolve().is_relative_to(root) or target.is_symlink():
        raise GenerationError("Install directory path is unsafe")
    if (root / (settings.plugin_id + ".link")).exists():
        raise GenerationError("A development link for this plugin exists; roll it back first "
                              "(both would load the same plugin)")
    previous = None
    if target.exists():
        current = owned(target)
        if current is None or current[0]["plugin_id"] != settings.plugin_id:
            raise GenerationError("Plugin directory exists and is not provably this Studio plugin; collision blocked")
        previous = _posix(current[0]["files"])
    return {"format": INSTALL_FORMAT, "plugin_id": settings.plugin_id, "installation_id": settings.installation_id,
            "plugin_name": name, "package": str(package), "target": str(target), "target_root": str(root),
            "operation": "update_own" if previous is not None else "create", "previous_files": previous,
            "new_files": _posix(marker["files"]), "service_restart": False,
            "hardware_status": "HARDWARE_PENDING", "authorization": "DRY_RUN_ONLY"}


def _same(data: bytes, destination: Path) -> bool:
    try:
        if not destination.is_file() or destination.stat().st_size != len(data):
            return False
        return hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(data).digest()
    except OSError:
        return False


def _retire(target: Path, relative: str) -> None:
    """Remove one own file; if Windows keeps it locked (running host), move it aside."""
    file = target / relative
    try:
        file.unlink(missing_ok=True)
        return
    except OSError:
        if not file.exists():
            return
    retired = target / deployment.RETIRED_DIR / secrets.token_hex(6)
    retired.mkdir(parents=True, exist_ok=True)
    os.replace(file, retired / file.name)


def purge_retired(target: str | Path, *, attempts: int = 1, delay: float = 0.5) -> int:
    """Best effort: delete retired files whose host has exited; returns what is left."""
    root = Path(target) / deployment.RETIRED_DIR
    for attempt in range(max(1, attempts)):
        if not root.exists():
            return 0
        shutil.rmtree(root, ignore_errors=True)
        if not root.exists():
            return 0
        if attempt + 1 < attempts:
            time.sleep(delay)
    return sum(1 for p in root.rglob("*") if p.is_file())


def _replace(data: bytes, destination: Path) -> None:
    if _same(data, destination):
        return  # unchanged (possibly in use by the running plugin host)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".studio-{secrets.token_hex(4)}.tmp")
    temporary.write_bytes(data)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _snapshot(directory: Path, files, backup: Path) -> dict:
    saved = {}
    for relative in list(files) + [MARKER]:
        source = directory / relative
        if source.is_file():
            data = source.read_bytes()
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            saved[relative] = _hash(data)
    return saved


def _remove_empty_tree(target: Path) -> bool:
    """Remove now-empty directories; data written by the plugin stays."""
    if not target.exists():
        return True
    for directory in sorted((p for p in target.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        target.rmdir()
        return True
    except OSError:
        return False


def _restore(receipt: dict) -> None:
    target = Path(receipt["target"])
    new = set(receipt["new_files"]) | {MARKER}
    saved = receipt.get("backup_hashes")
    if saved:
        backup = Path(receipt["backup"])
        for relative, digest in saved.items():
            if _hash((backup / relative).read_bytes()) != digest:
                raise GenerationError("Backup content does not match its recorded hash; restore refused")
        (target / MARKER).unlink(missing_ok=True)
        for relative in new - set(saved):
            _retire(target, relative)
        for relative in sorted(saved, key=lambda r: r == MARKER):
            _replace((backup / relative).read_bytes(), target / relative)
    else:
        for relative in [MARKER, *sorted(new - {MARKER})]:
            _retire(target, relative)
        purge_retired(target)
        _remove_empty_tree(target)


def install(plan: dict, *, confirm_plugin_id: str, receipt_dir: str | Path, target_root: Path | None = None) -> Path:
    if plan.get("format") != INSTALL_FORMAT or confirm_plugin_id != plan.get("plugin_id"):
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    live = plan_install(plan["package"], target_root=target_root)
    if live != plan:
        raise GenerationError("Installation plan is stale or was altered; create a new dry run")
    target, package = Path(live["target"]), Path(live["package"])
    if target.exists():
        purge_retired(target)
    receipt_root = check_output_dir(receipt_dir)
    receipt_root.mkdir(parents=True, exist_ok=True)
    backup = receipt_root / "previous"
    saved = _snapshot(target, live["previous_files"], backup) if live["previous_files"] else None
    receipt = {**live, "authorization": "EXPLICIT_USER_COMMAND", "receipt_format": RECEIPT_FORMAT,
               "backup": str(backup) if saved else None, "backup_hashes": saved}
    file = receipt_root / (live["plugin_id"] + ".directory.receipt.json")
    with file.open("xb") as handle:
        handle.write(json_bytes(receipt))
    stale = sorted(set(live["previous_files"] or {}) - set(live["new_files"]))
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / MARKER).unlink(missing_ok=True)  # not owned while files are inconsistent
        for relative in live["new_files"]:
            _replace((package / relative).read_bytes(), target / relative)
        for relative in stale:
            _retire(target, relative)
        _replace((package / MARKER).read_bytes(), target / MARKER)
        current = owned(target)
        if current is None or current[0]["installation_id"] != live["installation_id"]:
            raise GenerationError("Installed directory does not validate")
    except BaseException:
        _restore(receipt)
        raise
    return file


def rollback(receipt_path: str | Path, *, confirm_plugin_id: str) -> dict:
    receipt = parse_json(Path(receipt_path).read_bytes(), limit=1_048_576)
    if receipt.get("receipt_format") != RECEIPT_FORMAT or receipt.get("plugin_id") != confirm_plugin_id:
        raise GenerationError("Invalid directory receipt or plugin confirmation")
    target = Path(receipt["target"])
    current = owned(target)
    if current is None or current[0]["installation_id"] != receipt["installation_id"] or \
            _posix(current[0]["files"]) != receipt["new_files"]:
        raise GenerationError("Installed directory changed since installation; rollback refused")
    _restore(receipt)
    return {"plugin_id": confirm_plugin_id, "target": str(target),
            "operation": "restore_previous" if receipt.get("backup_hashes") else "remove_own_files",
            "directory_removed": not target.exists()}


def plan_uninstall(plugin_name: str, plugin_id: str, *, target_root: Path | None = None) -> dict:
    from .service import PLUGIN_NAME
    if not PLUGIN_NAME.fullmatch(plugin_name or ""):
        raise GenerationError("Invalid SDK plugin name")
    root = (target_root if target_root is not None else deployment.plugin_directory()).resolve()
    target = root / plugin_name
    current = owned(target) if target.is_dir() else None
    if current is None or current[0]["plugin_id"] != plugin_id:
        raise GenerationError("No provably Studio-owned plugin directory with this identity")
    return {"format": "studio-directory-uninstall-plan-1", "plugin_id": plugin_id, "plugin_name": plugin_name,
            "target": str(target), "files": _posix(current[0]["files"]),
            "installation_id": current[0]["installation_id"], "authorization": "DRY_RUN_ONLY", "service_restart": False}


def uninstall(plan: dict, *, confirm_plugin_id: str, receipt_dir: str | Path, target_root: Path | None = None) -> Path:
    if confirm_plugin_id != plan.get("plugin_id"):
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    live = plan_uninstall(plan["plugin_name"], plan["plugin_id"], target_root=target_root)
    if live != plan:
        raise GenerationError("Uninstall plan is stale; create a new dry run")
    target = Path(live["target"])
    receipt_root = check_output_dir(receipt_dir)
    receipt_root.mkdir(parents=True, exist_ok=True)
    backup = receipt_root / "previous"
    receipt = {**live, "receipt_format": UNINSTALL_FORMAT, "backup": str(backup),
               "backup_hashes": _snapshot(target, live["files"], backup), "authorization": "EXPLICIT_USER_COMMAND"}
    file = receipt_root / (live["plugin_id"] + ".directory.uninstall.json")
    with file.open("xb") as handle:
        handle.write(json_bytes(receipt))
    for relative in [MARKER, *live["files"]]:
        _retire(target, relative)
    purge_retired(target)
    receipt["directory_removed"] = _remove_empty_tree(target)
    file.write_bytes(json_bytes(receipt))
    return file


def restore_uninstalled(receipt_path: str | Path, *, confirm_plugin_id: str) -> None:
    receipt = parse_json(Path(receipt_path).read_bytes(), limit=1_048_576)
    if receipt.get("receipt_format") != UNINSTALL_FORMAT or receipt.get("plugin_id") != confirm_plugin_id:
        raise GenerationError("Invalid uninstall receipt")
    target = Path(receipt["target"])
    if (target / MARKER).exists():
        raise GenerationError("Plugin directory is installed again; restore refused")
    backup = Path(receipt["backup"])
    for relative, digest in receipt["backup_hashes"].items():
        if _hash((backup / relative).read_bytes()) != digest:
            raise GenerationError("Backup content does not match its recorded hash")
    for relative in sorted(receipt["backup_hashes"], key=lambda r: r == MARKER):
        _replace((backup / relative).read_bytes(), target / relative)
