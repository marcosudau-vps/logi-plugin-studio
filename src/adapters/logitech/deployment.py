"""Explicit, own-plugin-only development links. No service or profile control."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path

from .codegen import GenerationPlan, check_output_dir
from .errors import GenerationError
from .host_runtime import HOST_RUNTIME_FILE, MAX_RUNTIME_FILES, parse_record, plugin_runtime, record_files
from runtime.wire import ConnectionSettings, HostError, json_bytes, parse_json


def plugin_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise GenerationError("LOCALAPPDATA is not configured")
    return Path(base) / "Logi" / "LogiPluginService" / "Plugins"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# SDK package resource folders (official package structure: these folders live
# beside ``metadata`` and ``bin`` in the package root). Only flat, safely named
# files with the SDK-defined suffixes are accepted, so a package can never
# carry nested or foreign content into the Logitech plugin directory.
RESOURCE_RULES = {
    "actionicons": (".png", ".svg"),
    "actionsymbols": (".svg",),
    "icontemplates": (".ict",),
    "licenses": None,  # any suffix, but flat and safely named
}
METADATA_RESOURCES = {"DefaultIconTemplate.ict", "Icon256x256.png"}
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
EXECUTABLE_SUFFIXES = {".dll", ".exe", ".pyz", ".py", ".pyc", ".ps1", ".cmd", ".bat", ".com", ".scr", ".msi", ".so"}
MAX_RESOURCE_FILES = 2048
#: Superseded own files that are still locked by a running plugin host are moved
#: here (same volume, rename of in-use images is permitted) and purged later.
RETIRED_DIR = "bin/.studio-retired"
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,199}")


def resource_role(relative: str) -> str | None:
    """Return the SDK resource folder for an optional package file, else None."""
    parts = relative.split("/")
    if len(parts) != 2 or not _SAFE_NAME.fullmatch(parts[1]) or ".." in parts[1]:
        return None
    folder, name = parts
    if folder == "metadata":
        return "metadata" if name in METADATA_RESOURCES else None
    if folder not in RESOURCE_RULES:
        return None
    suffixes = RESOURCE_RULES[folder]
    if suffixes is not None and Path(name).suffix.lower() not in suffixes:
        return None
    return folder


def _validate_package(package: Path, *, allow_legacy: bool = False) -> tuple[dict, ConnectionSettings]:
    """Validate every owned byte. Legacy three-file packages are readable ONLY
    for old-link ownership and rollback, never accepted as new install targets.

    A package consists of the four core files (DLL, deps.json, connection and
    SDK metadata) plus optional, flat SDK resources (``actionicons``,
    ``actionsymbols``, ``icontemplates``, ``metadata/DefaultIconTemplate.ict``,
    ``metadata/Icon256x256.png`` and ``licenses``).
    """
    try:
        marker = parse_json((package / "studio.package.json").read_bytes(), limit=1_048_576)
        settings = ConnectionSettings.load(package / "bin" / "studio.connection.json")
        if set(marker) != {"plugin_id", "installation_id", "project_hash", "files"}:
            raise GenerationError("Package marker fields are invalid")
        if any(marker[key] != getattr(settings, key) for key in ("plugin_id", "installation_id", "project_hash")):
            raise GenerationError("Package ownership or connection is inconsistent")
        files = marker["files"]
        if not isinstance(files, dict) or not 3 <= len(files) <= 5 + MAX_RESOURCE_FILES + MAX_RUNTIME_FILES:
            raise GenerationError("Package must contain DLL, deps.json, connection and SDK metadata")
        normalized = set()
        total = 0
        for relative, expected in files.items():
            if not isinstance(relative, str) or ":" in relative or Path(relative).is_absolute():
                raise GenerationError("Package file path is unsafe or missing")
            file = (package / relative).resolve()
            if not file.is_relative_to(package.resolve()) or not file.is_file() or file.is_symlink():
                raise GenerationError("Package file path is unsafe or missing")
            name = file.relative_to(package.resolve()).as_posix()
            if name in normalized:
                raise GenerationError("Package lists one file twice")
            normalized.add(name)
            content = file.read_bytes()
            total += len(content)
            if total > MAX_PACKAGE_BYTES:
                raise GenerationError("Package exceeds the size limit")
            if not isinstance(expected, str) or _hash(content) != expected:
                raise GenerationError("Package content was modified after staging")
        record_name = "bin/" + HOST_RUNTIME_FILE
        runtime_files: dict = {}
        if record_name in normalized:
            # Plugin-local host runtime: exactly the files the record lists, with
            # the record's hashes (which the marker hashes above already prove).
            runtime_files = record_files(parse_record((package / record_name).read_bytes()))
            if any(files.get(name) != digest for name, digest in runtime_files.items()):
                raise GenerationError("Package host runtime does not match its record")
        top_level = {name for name in normalized if name.count("/") == 1}
        dlls = {name for name in top_level if name.startswith("bin/") and name.endswith(".dll")}
        dep_files = {name for name in top_level if name.startswith("bin/") and name.endswith(".deps.json")}
        required = {"bin/studio.connection.json", "metadata/LoupedeckPackage.yaml"}
        if not required <= normalized or len(dlls) != 1:
            raise GenerationError("Package file set is invalid")
        dll = next(iter(dlls))
        expected_deps = dll[:-4] + ".deps.json"
        core = required | {dll} | dep_files | ({record_name} & normalized) | set(runtime_files)
        resources = normalized - core
        if any(resource_role(name) is None for name in resources):
            raise GenerationError("Package contains a file outside the SDK resource structure")
        legacy = not dep_files
        if legacy and (not allow_legacy or resources or len(files) != 3):
            raise GenerationError("Incomplete legacy package without deps.json is not permitted for installation")
        if not legacy and dep_files != {expected_deps}:
            raise GenerationError("Package must include matching .deps.json")
        actual = {file.relative_to(package).as_posix() for file in package.rglob("*") if file.is_file()}
        extra = actual - normalized - {"studio.package.json"}
        if normalized - actual:
            raise GenerationError("Package file path is unsafe or missing")
        # Ownership checks (rollback, uninstall, update detection) tolerate data a
        # running plugin wrote into its own bin/ working directory, never code.
        runtime_data = allow_legacy and all(
            name.startswith(RETIRED_DIR + "/") or
            (name.startswith("bin/") and Path(name).suffix.lower() not in EXECUTABLE_SUFFIXES) for name in extra)
        if extra and not runtime_data:
            raise GenerationError("Package contains unstaged files; use a clean owned output directory")
        return marker, settings
    except (OSError, ValueError, HostError) as exc:
        raise GenerationError(f"Invalid development package: {exc}") from exc


def package_resources(plan: GenerationPlan) -> list[str]:
    """Generated SDK resource files that belong in the installable package."""
    return sorted(name for name in plan.files if resource_role(name) is not None)


def prepare_package(plan: GenerationPlan, output_dir: str | Path, connection_path: Path) -> Path:
    """Stage DLL, deps, connection, SDK metadata and all SDK resources.

    The package is assembled in a private staging directory and validated
    before it replaces a previous own package; a failed update leaves the
    previous package byte-for-byte untouched. Own files that are no longer
    generated disappear with the replaced package, foreign files are refused.
    """
    root = check_output_dir(output_dir)
    settings = ConnectionSettings.load(connection_path)
    if settings.plugin_id != plan.plugin_id or settings.project_hash != plan.manifest["product"]["project_hash"]:
        raise GenerationError("Package connection does not match generated plugin")
    package = root / "development-package"
    marker_name = "studio.package.json"
    if package.exists() and any(package.iterdir()):
        if not (package / marker_name).is_file():
            raise GenerationError("Package directory is not owned by Studio")
        previous, _ = _validate_package(package, allow_legacy=True)
        if previous.get("plugin_id") != plan.plugin_id or previous.get("installation_id") != settings.installation_id:
            raise GenerationError("Package ownership does not match")
    sources = {
        f"bin/{plan.assembly_name}.dll": root / "bin" / "Debug" / f"{plan.assembly_name}.dll",
        f"bin/{plan.assembly_name}.deps.json": root / "bin" / "Debug" / f"{plan.assembly_name}.deps.json",
        "bin/studio.connection.json": connection_path,
        "metadata/LoupedeckPackage.yaml": root / "metadata" / "LoupedeckPackage.yaml",
    }
    for relative in package_resources(plan):
        source = root / relative
        expected = plan.files[relative]
        data = expected if isinstance(expected, bytes) else expected.encode("utf-8")
        if not source.is_file() or source.read_bytes() != data:
            raise GenerationError(f"Generated SDK resource is missing or modified: {relative}")
        sources[relative] = source
    folded: dict[str, str] = {}
    for relative in sources:
        if folded.setdefault(relative.casefold(), relative) != relative:
            raise GenerationError(f"Asset name collision on a case-insensitive file system: {relative}")
    staging = Path(tempfile.mkdtemp(prefix=".package-staging-", dir=root))
    try:
        hashes = {}
        for relative, source in sources.items():
            destination = staging / relative
            if not destination.resolve().is_relative_to(staging.resolve()):
                raise GenerationError("Package path escapes the generated directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            hashes[relative] = _hash(destination.read_bytes())
        if (plan.manifest.get("host_runtime") or {}).get("self_hosted"):
            # Plugin-local host runtime (relative record + verified copy): the
            # installed plugin never depends on the Studio location.
            record, runtime_sources = plugin_runtime()
            (staging / "bin" / HOST_RUNTIME_FILE).write_bytes(record)
            hashes["bin/" + HOST_RUNTIME_FILE] = _hash(record)
            expected = record_files(parse_record(record))
            for relative, source in runtime_sources.items():
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                digest = _hash(destination.read_bytes())
                if digest != expected[relative]:
                    raise GenerationError(f"Host runtime file changed while packaging: {relative}")
                hashes[relative] = digest
        manifest = {"plugin_id": plan.plugin_id, "installation_id": settings.installation_id,
                    "project_hash": settings.project_hash, "files": hashes}
        (staging / marker_name).write_bytes(json_bytes(manifest))
        _validate_package(staging)
        retired = None
        if package.exists():
            retired = root / f".package-retired-{os.getpid()}-{secrets.token_hex(4)}"
            os.replace(package, retired)
        try:
            os.replace(staging, package)
        except OSError:
            if retired is not None:
                os.replace(retired, package)
            raise
        staging = None
        if retired is not None:
            shutil.rmtree(retired, ignore_errors=True)
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    _validate_package(package)
    return package



def plan_install(package_path: str | Path, *, target_root: Path | None = None) -> dict:
    package = Path(package_path).resolve()
    _, settings = _validate_package(package)
    root = (target_root if target_root is not None else plugin_directory()).resolve()
    link = root / (settings.plugin_id + ".link")
    if not link.resolve().is_relative_to(root) or link.is_symlink():
        raise GenerationError("Development link path is unsafe")
    previous = link.read_bytes() if link.exists() else None
    if previous is not None:
        try:
            old_package = Path(previous.decode("utf-8-sig").strip()).resolve()
            old_owner, _ = _validate_package(old_package, allow_legacy=True)
        except (OSError, ValueError, GenerationError) as exc:
            raise GenerationError("Existing link is not a provably Studio-owned plugin; collision blocked") from exc
        if old_owner.get("plugin_id") != settings.plugin_id:
            raise GenerationError("Existing development link belongs to another plugin")
    return {"format": "studio-development-plan-1", "plugin_id": settings.plugin_id,
            "installation_id": settings.installation_id, "package": str(package), "target": str(link),
            "target_root": str(root), "operation": "update_own" if previous is not None else "create",
            "previous_sha256": _hash(previous) if previous is not None else None,
            "new_sha256": _hash((str(package) + "\n").encode("utf-8")),
            "service_restart": False, "hardware_status": "HARDWARE_PENDING",
            "authorization": "DRY_RUN_ONLY"}


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".studio-link-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_link(plan: dict, *, confirm_plugin_id: str, receipt_dir: str | Path) -> Path:
    if plan.get("format") != "studio-development-plan-1" or confirm_plugin_id != plan.get("plugin_id"):
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    # CLI installations may target only the real, user-local SDK plugin directory.
    live = plan_install(plan["package"])
    if live != plan:
        raise GenerationError("Deployment plan is stale or was altered; create a new dry run")
    receipt_root = check_output_dir(receipt_dir)
    receipt_root.mkdir(parents=True, exist_ok=True)
    target = Path(live["target"])
    previous = target.read_bytes() if target.exists() else None
    new = (live["package"] + "\n").encode("utf-8")
    receipt = {**live, "authorization": "EXPLICIT_USER_COMMAND",
               "receipt_format": "studio-installation-receipt-1",
               "previous_content_hex": previous.hex() if previous is not None else None}
    file = receipt_root / (live["plugin_id"] + ".receipt.json")
    if file.exists():
        raise GenerationError("Receipt already exists; preserve it and choose a new receipt directory")
    with file.open("xb") as handle:
        handle.write(json_bytes(receipt))
    if (_hash(target.read_bytes()) if target.exists() else None) != live["previous_sha256"]:
        raise GenerationError("Development link changed before installation; nothing overwritten")
    _atomic_write(target, new)
    return file


def _rollback_details(receipt_path: str | Path) -> tuple[dict, Path, bytes | None]:
    receipt = parse_json(Path(receipt_path).read_bytes())
    from core.ids import is_valid_id
    confirm_plugin_id = receipt.get("plugin_id")
    if not is_valid_id(confirm_plugin_id):
        raise GenerationError("Invalid receipt plugin identity")
    if receipt.get("receipt_format") != "studio-installation-receipt-1" or receipt.get("authorization") != "EXPLICIT_USER_COMMAND":
        raise GenerationError("Invalid installation receipt")
    target = plugin_directory().resolve() / (confirm_plugin_id + ".link")
    if str(target) != receipt.get("target") or target.is_symlink() or not target.exists():
        raise GenerationError("Receipt target is not the current own plugin link")
    if _hash(target.read_bytes()) != receipt.get("new_sha256"):
        raise GenerationError("Link was changed since installation; rollback refused")
    previous = receipt.get("previous_content_hex")
    if previous is not None and not isinstance(previous, str):
        raise GenerationError("Receipt backup must be hexadecimal text or null")
    try:
        previous_bytes = bytes.fromhex(previous) if isinstance(previous, str) else None
    except ValueError as exc:
        raise GenerationError("Receipt backup is not hexadecimal text") from exc
    if (_hash(previous_bytes) if previous_bytes is not None else None) != receipt.get("previous_sha256"):
        raise GenerationError("Receipt backup content does not match its original hash")
    owner, _ = _validate_package(Path(receipt["package"]), allow_legacy=True)
    if owner["plugin_id"] != confirm_plugin_id or owner["installation_id"] != receipt.get("installation_id"):
        raise GenerationError("Current package is not the receipt's own installation")
    return receipt, target, previous_bytes


def plan_rollback(receipt_path: str | Path) -> dict:
    receipt, target, previous = _rollback_details(receipt_path)
    return {"format": "studio-rollback-plan-1", "plugin_id": receipt["plugin_id"],
            "receipt": str(Path(receipt_path).resolve()), "target": str(target),
            "operation": "remove_own_link" if previous is None else "restore_exact_original_bytes",
            "current_sha256": receipt["new_sha256"], "restore_sha256": receipt["previous_sha256"],
            "authorization": "DRY_RUN_ONLY", "hardware_status": "HARDWARE_PENDING", "service_restart": False}


def rollback_link(receipt_path: str | Path, *, confirm_plugin_id: str) -> None:
    receipt, target, previous_bytes = _rollback_details(receipt_path)
    if receipt["plugin_id"] != confirm_plugin_id:
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    if _hash(target.read_bytes()) != receipt["new_sha256"]:
        raise GenerationError("Link changed before rollback; nothing overwritten")
    if previous_bytes is None:
        target.unlink()
    else:
        _atomic_write(target, previous_bytes)


def _link_owner(content: bytes) -> tuple[Path, dict] | None:
    """The Studio package a link points to, if it is provably Studio-owned."""
    try:
        package = Path(content.decode("utf-8-sig").strip()).resolve()
        owner, _ = _validate_package(package, allow_legacy=True)
        return package, owner
    except (OSError, ValueError, GenerationError):
        return None


def inventory(*, target_root: Path | None = None) -> list[dict]:
    """Read-only list of development links; foreign links are only reported."""
    root = (target_root if target_root is not None else plugin_directory()).resolve()
    rows = []
    if not root.is_dir():
        return rows
    for link in sorted(root.glob("*.link")):
        if link.is_symlink() or not link.is_file():
            continue
        content = link.read_bytes()[:4096]
        owned = _link_owner(content)
        rows.append({"link": link.name, "target": content.decode("utf-8-sig", "replace").strip(),
                     "studio_owned": owned is not None and owned[1]["plugin_id"] + ".link" == link.name,
                     "plugin_id": owned[1]["plugin_id"] if owned else None, "kind": "link",
                     "package": str(owned[0]) if owned else None})
    for directory in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        marker = directory / "studio.package.json"
        if not marker.is_file():
            rows.append({"link": directory.name, "target": str(directory), "studio_owned": False,
                         "plugin_id": None, "kind": "directory"})
            continue
        try:
            owner, _ = _validate_package(directory, allow_legacy=True)
        except GenerationError:
            owner = None
        rows.append({"link": directory.name, "target": str(directory), "studio_owned": owner is not None,
                     "plugin_id": owner["plugin_id"] if owner else None, "kind": "directory",
                     "package": str(directory) if owner else None})
    return rows


def installed_runtimes(*, target_root: Path | None = None) -> list[dict]:
    """Read-only: host runtime status of every installed Studio-owned plugin."""
    from .host_runtime import installed_runtime_status
    result = []
    for row in inventory(target_root=target_root):
        if row["studio_owned"] and row.get("package"):
            result.append({**row, "runtime": installed_runtime_status(row["package"])})
    return result


def installed_key_support(plugin_id: str, *, target_root: Path | None = None) -> str:
    """``not-installed`` | ``protected-ok`` | ``plaintext-only`` (a build before 1.0)."""
    from .host_runtime import supports_protected_keys
    rows = [r for r in inventory(target_root=target_root) if r["studio_owned"] and r["plugin_id"] == plugin_id]
    if not rows:
        return "not-installed"
    return "protected-ok" if all(supports_protected_keys(r["package"]) for r in rows) else "plaintext-only"


def plan_uninstall(plugin_id: str, *, target_root: Path | None = None) -> dict:
    """Dry run: remove exactly one own development link; package files stay."""
    from core.ids import is_valid_id
    if not is_valid_id(plugin_id):
        raise GenerationError("Invalid plugin identity")
    root = (target_root if target_root is not None else plugin_directory()).resolve()
    link = root / (plugin_id + ".link")
    if not link.resolve().is_relative_to(root) or link.is_symlink() or not link.is_file():
        raise GenerationError("No own development link is installed for this plugin")
    content = link.read_bytes()
    owned = _link_owner(content)
    if owned is None or owned[1]["plugin_id"] != plugin_id:
        raise GenerationError("Installed link is not a provably Studio-owned plugin; uninstall refused")
    return {"format": "studio-uninstall-plan-1", "plugin_id": plugin_id, "target": str(link),
            "target_root": str(root), "package": str(owned[0]), "current_sha256": _hash(content),
            "operation": "remove_own_link", "service_restart": False, "authorization": "DRY_RUN_ONLY"}


def uninstall_link(plan: dict, *, confirm_plugin_id: str, receipt_dir: str | Path,
                   target_root: Path | None = None) -> Path:
    if plan.get("format") != "studio-uninstall-plan-1" or confirm_plugin_id != plan.get("plugin_id"):
        raise GenerationError("Explicit confirmation of the exact plugin ID is required")
    live = plan_uninstall(confirm_plugin_id, target_root=target_root)
    if live != plan:
        raise GenerationError("Uninstall plan is stale or was altered; create a new dry run")
    target = Path(live["target"])
    content = target.read_bytes()
    receipt_root = check_output_dir(receipt_dir)
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt = {**live, "authorization": "EXPLICIT_USER_COMMAND", "receipt_format": "studio-uninstall-receipt-1",
               "previous_content_hex": content.hex()}
    file = receipt_root / (live["plugin_id"] + ".uninstall.receipt.json")
    with file.open("xb") as handle:
        handle.write(json_bytes(receipt))
    if _hash(target.read_bytes()) != live["current_sha256"]:
        raise GenerationError("Link changed before uninstall; nothing removed")
    target.unlink()
    return file


def restore_uninstalled(receipt_path: str | Path, *, confirm_plugin_id: str,
                        target_root: Path | None = None) -> None:
    """Undo an own uninstall: recreate the exact previous link bytes if still absent."""
    receipt = parse_json(Path(receipt_path).read_bytes())
    if (receipt.get("receipt_format") != "studio-uninstall-receipt-1"
            or receipt.get("plugin_id") != confirm_plugin_id):
        raise GenerationError("Invalid uninstall receipt or plugin confirmation")
    root = (target_root if target_root is not None else plugin_directory()).resolve()
    target = root / (confirm_plugin_id + ".link")
    if str(target) != receipt.get("target") or target.exists():
        raise GenerationError("Link exists again or target differs; restore refused")
    content = bytes.fromhex(receipt["previous_content_hex"])
    if _hash(content) != receipt.get("current_sha256"):
        raise GenerationError("Uninstall receipt backup does not match its hash")
    owned = _link_owner(content)
    if owned is None or owned[1]["plugin_id"] != confirm_plugin_id:
        raise GenerationError("Previous package is no longer a valid own package")
    _atomic_write(target, content)
