"""Host runtime for Studio-built plugins (no SDK semantics are added here).

Since AP-POLISH-001 every Studio-built plugin (native, compatible and shared)
starts its OWN embedded Python host bundle from the SDK process
(``HostChild`` in the generated C#). The interpreter is the **plugin-local
Studio host runtime**: a copy of the stdlib-only ``LogiPluginStudioHost.exe``
runtime inside the plugin package (``bin/hostruntime-<id>/``), described by
``bin/studio.host-runtime.json`` with RELATIVE paths and SHA-256 per file.

* No absolute path to the Studio, no running Studio, no shared mutable Python.
* ``<id>`` is derived from the runtime content: an updated Studio produces a
  new directory, so a running plugin's runtime files are never overwritten.
* Packages built before 1.0 carry ``studio-host-runtime-1`` (absolute runner
  path). They stay readable; the next update with this Studio replaces the
  record (migration on update). :func:`installed_runtime_status` reports them.

The Studio itself locates its runtime dynamically next to its own executable
(``<studio>/hostruntime``), so Setup and Portable editions can be moved.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

from runtime.wire import json_bytes

from .errors import GenerationError

SRC = Path(__file__).resolve().parents[2]
RUNNER_NAME = "LogiPluginStudioHost.exe"
HOST_RUNTIME_FILE = "studio.host-runtime.json"
RUNTIME_DIR_NAME = "hostruntime"
DISTRIBUTION_FILE = "studio-host-runtime.json"
DISTRIBUTION_FORMAT = "studio-host-runtime-dist-1"
RECORD_FORMAT = "studio-host-runtime-2"
LEGACY_RECORD_FORMAT = "studio-host-runtime-1"
PEER_KEY_FORMATS = ("plain-1", "dpapi-user-1")
RUNTIME_DIRECTORY = re.compile(r"hostruntime-[0-9a-f]{16}")
_SAFE_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+\-]{0,199}")
MAX_RUNTIME_FILES = 512
MAX_RUNTIME_BYTES = 48 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(relative: str) -> bool:
    if not isinstance(relative, str) or not relative or len(relative) > 260 or "\\" in relative or ":" in relative:
        return False
    parts = relative.split("/")
    return all(_SAFE_PART.fullmatch(part) and part not in (".", "..") for part in parts)


def runtime_id(files: dict) -> str:
    lines = "".join(f"{name}\0{files[name]}\n" for name in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()[:16]


# -- Studio side: the runtime distribution beside the Studio executable ---------
def studio_runtime_dir() -> Path | None:
    """Directory of the Studio's host runtime, determined at run time.

    ``LOGI_STUDIO_HOST_RUNTIME`` (absolute directory) overrides; a frozen
    Studio uses ``<directory of the real executable>/hostruntime``. A source
    checkout has no runtime unless the variable points to one.
    """
    configured = os.environ.get("LOGI_STUDIO_HOST_RUNTIME")
    candidates = [Path(configured)] if configured else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / RUNTIME_DIR_NAME)
    for candidate in candidates:
        if candidate.is_absolute() and (candidate / DISTRIBUTION_FILE).is_file():
            return candidate.resolve()
    return None


def load_distribution(directory: Path, *, verify: bool = True) -> dict:
    """Validate a runtime distribution: exact file set, hashes, safe names."""
    try:
        row = json.loads((directory / DISTRIBUTION_FILE).read_bytes()[:1_048_576].decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise GenerationError(f"Host runtime manifest is unreadable: {type(exc).__name__}") from exc
    if not isinstance(row, dict) or row.get("format") != DISTRIBUTION_FORMAT:
        raise GenerationError("Host runtime manifest has an unknown format")
    files, executable = row.get("files"), row.get("executable")
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_RUNTIME_FILES or executable not in files:
        raise GenerationError("Host runtime manifest file list is invalid")
    if not all(safe_relative(name) and isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest)
               for name, digest in files.items()):
        raise GenerationError("Host runtime manifest contains unsafe entries")
    if verify:
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual - {DISTRIBUTION_FILE} != set(files):
            raise GenerationError("Host runtime directory differs from its manifest (missing or unlisted files)")
        total = 0
        for name, digest in files.items():
            file = directory / name
            if file.is_symlink():
                raise GenerationError("Host runtime must not contain links")
            total += file.stat().st_size
            if total > MAX_RUNTIME_BYTES:
                raise GenerationError("Host runtime exceeds the size limit")
            if _sha256_file(file) != digest:
                raise GenerationError(f"Host runtime file was modified: {name}")
    return row


def write_distribution(directory: Path, *, version: str, python: str) -> dict:
    """Build helper: hash every runtime file and write the manifest."""
    files = {p.relative_to(directory).as_posix(): _sha256_file(p)
             for p in sorted(directory.rglob("*")) if p.is_file() and p.name != DISTRIBUTION_FILE}
    row = {"format": DISTRIBUTION_FORMAT, "version": version, "python": python,
           "executable": RUNNER_NAME, "files": files, "runtime_id": runtime_id(files)}
    (directory / DISTRIBUTION_FILE).write_bytes(json_bytes(row))
    load_distribution(directory)
    return row


def studio_host_runner() -> str | None:
    """The Studio's own runner (for Studio-managed test hosts and diagnosis)."""
    directory = studio_runtime_dir()
    if directory is not None:
        try:
            row = load_distribution(directory, verify=False)
            runner = directory / row["executable"]
            if runner.is_file():
                return str(runner)
        except GenerationError:
            pass
    return None


def registered_python() -> str | None:
    if os.name != "nt":
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for version in ("3.12", "3.13", "3.14"):
            try:
                with winreg.OpenKey(hive, rf"Software\Python\PythonCore\{version}\InstallPath") as key:
                    path, _ = winreg.QueryValueEx(key, "ExecutablePath")
            except OSError:
                continue
            if isinstance(path, str) and Path(path).is_file():
                return path
    return None


def resolve_shared_python() -> str | None:
    """Interpreter for Studio-managed hosts: env, Studio runtime, registry."""
    configured = os.environ.get("LOGI_SHARED_PYTHON")
    if configured and Path(configured).is_absolute() and Path(configured).is_file():
        return configured
    return studio_host_runner() or registered_python()


# -- Package side: the plugin-local copy --------------------------------------
def plugin_runtime() -> tuple[bytes, dict[str, Path]]:
    """Record bytes and ``{package path: source file}`` for a self-hosting plugin.

    Without a Studio runtime (source checkout) the record states
    ``directory: null``: the plugin then uses ``LOGI_SHARED_PYTHON`` or a
    registered CPython, exactly like before 1.0 (diagnosed as a warning).
    """
    directory = studio_runtime_dir()
    record = {"format": RECORD_FORMAT, "directory": None, "executable": RUNNER_NAME, "runtime_version": None,
              "runtime_id": None, "files": {}, "peer_key_formats": list(PEER_KEY_FORMATS)}
    sources: dict[str, Path] = {}
    if directory is not None:
        row = load_distribution(directory)
        identifier = runtime_id(row["files"])
        folder = f"hostruntime-{identifier}"
        record.update(directory=folder, executable=row["executable"], runtime_version=row.get("version"),
                      runtime_id=identifier, files=dict(sorted(row["files"].items())))
        sources = {f"bin/{folder}/{name}": directory / name for name in row["files"]}
    return json_bytes(record), sources


def parse_record(data: bytes) -> dict:
    """Validate a package runtime record (format 2, or legacy format 1)."""
    try:
        row = json.loads(data[:262144].decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GenerationError("Host runtime record is not valid JSON") from exc
    if not isinstance(row, dict):
        raise GenerationError("Host runtime record is invalid")
    if row.get("format") == LEGACY_RECORD_FORMAT:
        if set(row) != {"format", "executable"} or not isinstance(row["executable"], str):
            raise GenerationError("Legacy host runtime record is invalid")
        return row
    if row.get("format") != RECORD_FORMAT or set(row) != {"format", "directory", "executable", "runtime_version",
                                                          "runtime_id", "files", "peer_key_formats"}:
        raise GenerationError("Host runtime record has an unknown format")
    files = row["files"]
    if not isinstance(files, dict) or len(files) > MAX_RUNTIME_FILES:
        raise GenerationError("Host runtime record file list is invalid")
    if row["directory"] is None:
        if files:
            raise GenerationError("Host runtime record lists files without a directory")
        return row
    if not isinstance(row["directory"], str) or not RUNTIME_DIRECTORY.fullmatch(row["directory"]) \
            or row["executable"] not in files or row["directory"] != f"hostruntime-{runtime_id(files)}":
        raise GenerationError("Host runtime record directory or executable is invalid")
    if not all(safe_relative(name) and isinstance(d, str) and re.fullmatch("[0-9a-f]{64}", d) for name, d in files.items()):
        raise GenerationError("Host runtime record contains unsafe entries")
    return row


def record_files(record: dict) -> dict[str, str]:
    """Package-relative runtime files declared by a format-2 record."""
    if record.get("format") != RECORD_FORMAT or record.get("directory") is None:
        return {}
    return {f"bin/{record['directory']}/{name}": digest for name, digest in record["files"].items()}


def installed_runtime_status(package_dir: str | Path) -> dict:
    """Read-only classification of an installed/packaged plugin's host runtime."""
    record_path = Path(package_dir) / "bin" / HOST_RUNTIME_FILE
    if not record_path.is_file():
        return {"status": "NO_RECORD", "detail": "Vor 1.0 gebaut: Host über Studio, LOGI_SHARED_PYTHON oder Python"}
    try:
        row = parse_record(record_path.read_bytes())
    except (OSError, GenerationError) as exc:
        return {"status": "INVALID_RECORD", "detail": str(exc)}
    if row["format"] == LEGACY_RECORD_FORMAT:
        exists = Path(row["executable"]).is_file()
        return {"status": "LEGACY_ABSOLUTE_PATH", "executable": row["executable"], "executable_exists": exists,
                "detail": "Absoluter Studio-Hostpfad (vor 1.0). Mit diesem Studio neu bauen und aktualisieren."}
    if row["directory"] is None:
        return {"status": "SYSTEM_PYTHON", "detail": "Ohne eingebettete Laufzeit gebaut (Entwicklerbuild)"}
    problems = []
    root = Path(package_dir) / "bin" / row["directory"]
    for name, digest in row["files"].items():
        file = root / name
        if not file.is_file():
            problems.append(f"fehlt: {name}")
        elif _sha256_file(file) != digest:
            problems.append(f"verändert: {name}")
    if root.is_dir():
        listed = {root / name for name in row["files"]}
        problems += [f"nicht gelistet: {p.relative_to(root).as_posix()}" for p in root.rglob("*")
                     if p.is_file() and p not in listed]
    return {"status": "PLUGIN_LOCAL" if not problems else "PLUGIN_LOCAL_DAMAGED", "directory": row["directory"],
            "runtime_version": row["runtime_version"], "files": len(row["files"]), "problems": problems[:20]}


def supports_protected_keys(package_dir: str | Path) -> bool:
    """True if the plugin's embedded Shared host can read DPAPI-protected keys."""
    record_path = Path(package_dir) / "bin" / HOST_RUNTIME_FILE
    try:
        row = parse_record(record_path.read_bytes())
    except (OSError, GenerationError):
        return False
    return row["format"] == RECORD_FORMAT and "dpapi-user-1" in row["peer_key_formats"]


# -- Bundles and Studio-managed hosts ------------------------------------------
def native_host_bundle(project: dict, layout: dict | None, mode: str, manifest_dir: str | Path,
                       handler: bytes | None) -> bytes:
    """Deterministic zipapp for the normal (non-peer) Python bridge host."""
    if mode not in ("native", "compatible"):
        raise GenerationError("Native host bundles serve native or compatible mode only")
    files = {"__main__.py": (Path(__file__).with_name("native_host_main.py")).read_bytes(),
             "native/project.json": json_bytes(project, limit=16 * 1024 * 1024),
             "native/layout.json": json_bytes(layout),
             "native/mode.json": json_bytes(mode),
             "adapters/__init__.py": b"", "adapters/logitech/__init__.py": b"",
             "adapters/logitech/native.py": (SRC / "adapters/logitech/native.py").read_bytes(),
             "extensions/__init__.py": b"", "extensions/shared_folders/__init__.py": b""}
    for package in ("core", "runtime"):
        for file in (SRC / package).glob("*.py"):
            files[f"{package}/{file.name}"] = file.read_bytes()
    for module in ("host", "runtime_projection"):
        files[f"extensions/shared_folders/{module}.py"] = (SRC / "extensions/shared_folders" / f"{module}.py").read_bytes()
    manifests = sorted(Path(manifest_dir).glob("*.json"))
    files["native/manifests.json"] = json.dumps([m.name for m in manifests]).encode("utf-8")
    for manifest in manifests:
        files["native/manifests/" + manifest.name] = manifest.read_bytes()
    if handler is not None:
        files["studio_plugin_handler.py"] = handler
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(path), data, compress_type=zipfile.ZIP_DEFLATED)
    return target.getvalue()


def host_command(bundle: str | Path, connection: str | Path) -> list[str]:
    interpreter = resolve_shared_python()
    if interpreter is None:
        raise GenerationError("No host runtime: Studio host runner or Python 3.12-3.14 required")
    return [interpreter, "-I", "-B", str(Path(bundle).resolve()), str(Path(connection).resolve())]


def connection_active(connection: str | Path, timeout: float = 1.5) -> bool:
    """True if an authenticated host already serves this connection."""
    from runtime.wire import ConnectionSettings, LocalClient
    try:
        client = LocalClient(ConnectionSettings.load(connection), timeout=timeout)
        client.handshake()
        return True
    except Exception:
        return False


class ManagedHost:
    """One Studio-owned native host process; stdin EOF stops it."""

    def __init__(self, bundle: str | Path, connection: str | Path, log_path: str | Path):
        self.bundle, self.connection, self.log_path = Path(bundle), Path(connection), Path(log_path)
        self.process: subprocess.Popen | None = None
        self._log = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> int:
        with self._lock:
            if self.running:
                return self.process.pid
            if connection_active(self.connection):
                raise GenerationError("HOST_ALREADY_RUNNING: Für diese Verbindung läuft bereits ein Host "
                                      "(z. B. vom installierten Plugin selbst gestartet).")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("ab")
            env = dict(os.environ, LOGI_HOST_STDIN_LIFETIME="1", PYTHONIOENCODING="utf-8")
            for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
                env.pop(name, None)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self.process = subprocess.Popen(host_command(self.bundle, self.connection), stdin=subprocess.PIPE,
                                                stdout=self._log, stderr=subprocess.STDOUT,
                                                cwd=str(self.connection.parent), env=env, creationflags=flags)
            except BaseException:
                self._log.close()
                self._log = None
                raise
            return self.process.pid

    def stop(self, timeout: float = 6.0) -> int | None:
        with self._lock:
            process, self.process = self.process, None
            if process is None:
                return None
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            finally:
                if self._log:
                    self._log.close()
                    self._log = None
            return process.returncode
