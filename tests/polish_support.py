"""Test helpers for AP-POLISH-001 (plugin-local host runtime, packages).

``make_dev_runtime`` creates a tiny but REAL host runtime distribution from the
locally installed CPython: ``python.exe`` renamed to ``LogiPluginStudioHost.exe``
plus its DLLs and a ``python312._pth`` that points at the local standard
library. It is only for tests (the release uses the frozen PyInstaller runner);
it lets the generated C# ``HostChild`` verify and start a plugin-local runtime
without the Studio and without ``LOGI_SHARED_PYTHON``.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from adapters.logitech.host_runtime import RUNNER_NAME, write_distribution  # noqa: E402
from runtime.wire import ConnectionSettings, json_bytes  # noqa: E402


def make_dev_runtime(target: Path, *, version: str = "test", extra: bytes | None = None) -> Path:
    base = Path(sys.base_prefix)
    target.mkdir(parents=True, exist_ok=True)
    if extra is not None:  # different content => different runtime ID
        (target / "VARIANT.txt").write_bytes(extra)
    shutil.copyfile(base / "python.exe", target / RUNNER_NAME)
    major_minor = f"{sys.version_info.major}{sys.version_info.minor}"
    for name in (f"python{major_minor}.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if (base / name).is_file():
            shutil.copyfile(base / name, target / name)
    (target / f"python{major_minor}._pth").write_text(f"{base / 'DLLs'}\n{base / 'Lib'}\n", encoding="utf-8")
    write_distribution(target, version=version, python=sys.version.split()[0])
    return target


def run_runtime(runtime_dir: Path, seconds: int = 60):
    """Start the runtime's runner for real: Windows then holds an image lock on it."""
    import subprocess
    return subprocess.Popen([str(runtime_dir / RUNNER_NAME), "-I", "-c", f"import time; time.sleep({seconds})"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def fake_runtime(target: Path, marker: bytes = b"v1") -> Path:
    """A non-executable runtime distribution for file-level tests only."""
    (target / "_internal").mkdir(parents=True, exist_ok=True)
    (target / RUNNER_NAME).write_bytes(b"MZ-fake-runner-" + marker)
    (target / "_internal" / "python312.dll").write_bytes(b"fake-dll-" + marker)
    (target / "_internal" / "stdlib.zip").write_bytes(b"PK-fake-" + marker)
    write_distribution(target, version="fake-" + marker.decode(), python="3.12")
    return target


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hand_package(directory: Path, *, plugin_id: str = "polish.pkg", name: str = "PolishPkg",
                 record: bytes | None = None, runtime: dict[str, bytes] | None = None,
                 dll: bytes = b"dll-v1", settings: ConnectionSettings | None = None) -> Path:
    """A minimal valid Studio package (as ``prepare_package`` stages it), built by hand."""
    files: dict[str, bytes] = {
        f"bin/{name}Plugin.dll": dll,
        f"bin/{name}Plugin.deps.json": b"{}",
        "metadata/LoupedeckPackage.yaml": f'name: "{name}"\nversion: 1.0\n'.encode(),
    }
    settings = settings or ConnectionSettings(plugin_id, "0" * 64, 50123, secrets.token_hex(32))
    files["bin/studio.connection.json"] = json_bytes(settings.as_dict())
    if record is not None:
        files["bin/studio.host-runtime.json"] = record
    for relative, data in (runtime or {}).items():
        files[relative] = data
    for relative, data in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    marker = {"plugin_id": settings.plugin_id, "installation_id": settings.installation_id,
              "project_hash": settings.project_hash, "files": {k: _sha(v) for k, v in files.items()}}
    (directory / "studio.package.json").write_bytes(json_bytes(marker))
    return directory


def runtime_payload(runtime_dir: Path) -> tuple[bytes, dict[str, bytes]]:
    """Record + package files exactly as ``prepare_package`` would stage them."""
    import os
    from unittest.mock import patch
    from adapters.logitech.host_runtime import plugin_runtime
    with patch.dict(os.environ, {"LOGI_STUDIO_HOST_RUNTIME": str(runtime_dir)}):
        record, sources = plugin_runtime()
    return record, {relative: Path(source).read_bytes() for relative, source in sources.items()}


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
