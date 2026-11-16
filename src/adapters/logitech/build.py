"""Isolated ``dotnet build`` runner for generated Logitech plugin sources.

The runner deliberately refuses projects that could install anything: an
``InstallDevelopmentPlugin`` target, a ``.link`` registration, a copy into
``$(LocalAppData)\\Logi`` or any ``WriteLinesToFile`` task aborts the build
before ``dotnet`` is started.  Only a plain assembly build in the project-local
``bin``/``obj`` folders is allowed, so a build can never register a plugin with
the Logi Plugin Service.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .codegen import check_output_dir
from .errors import BuildError

#: Substrings that mark a project as an installation project (never build those).
INSTALL_MARKERS = (
    "InstallDevelopmentPlugin",
    ".link",
    "WriteLinesToFile",
    "LocalAppData",
    "$(PluginDir)",
)

#: Any MSBuild ``<Target ...>`` element is refused: this adapter only builds.
_TARGET_ELEMENT = re.compile(r"<target(?:\s|>)", re.IGNORECASE)


@dataclass(frozen=True)
class BuildResult:
    project_dir: Path
    csproj: Path
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    dll_path: Path | None
    dll_sha256: str | None
    dll_size: int | None
    dotnet_version: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.dll_path is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "project_dir": str(self.project_dir),
            "csproj": str(self.csproj),
            "command": list(self.command),
            "returncode": self.returncode,
            "duration_seconds": round(self.duration_seconds, 3),
            "dotnet_version": self.dotnet_version,
            "assembly": str(self.dll_path) if self.dll_path else None,
            "assembly_size": self.dll_size,
            "assembly_sha256": self.dll_sha256,
            "ok": self.ok,
        }


def assert_no_install_target(csproj_text: str, csproj_path: str = "<memory>") -> None:
    """Refuse to build a project that contains installation machinery."""
    lowered = csproj_text.lower()
    for marker in INSTALL_MARKERS:
        if marker.lower() in lowered:
            raise BuildError(
                f"Refusing to build {csproj_path}: found installation marker {marker!r}"
            )
    if _TARGET_ELEMENT.search(csproj_text):
        raise BuildError(
            f"Refusing to build {csproj_path}: MSBuild target elements are not allowed in a build-only project"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dotnet_version(dotnet: str) -> str:
    try:
        proc = subprocess.run(
            [dotnet, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            shell=False,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"dotnet --version failed: {exc}") from exc
    return (proc.stdout or "").strip()


def build_project(
    project_dir: str | Path,
    *,
    configuration: str = "Debug",
    dotnet: str = "dotnet",
    timeout: int = 900,
    log_path: str | Path | None = None,
    raise_on_error: bool = True,
) -> BuildResult:
    """Build exactly one generated ``.csproj`` inside ``project_dir``."""
    directory = check_output_dir(project_dir)
    if not directory.is_dir():
        raise BuildError(f"Build directory does not exist: {directory}")
    candidates = sorted(directory.glob("*.csproj"))
    if len(candidates) != 1:
        raise BuildError(
            f"Expected exactly one .csproj in {directory}, found {[c.name for c in candidates]}"
        )
    csproj = candidates[0]
    text = csproj.read_text(encoding="utf-8")
    assert_no_install_target(text, str(csproj))

    assembly_name = csproj.stem
    dll_path = directory / "bin" / configuration / f"{assembly_name}.dll"

    env = dict(os.environ)
    env.update(
        {
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "DOTNET_CLI_UI_LANGUAGE": "en",
        }
    )
    command = (dotnet, "build", csproj.name, "-c", configuration, "--nologo", "-v:minimal")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(directory),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"dotnet build timed out after {timeout}s: {csproj.name}") from exc
    except OSError as exc:
        raise BuildError(f"dotnet build could not be started: {exc}") from exc
    duration = time.monotonic() - started

    exists = dll_path.is_file()
    result = BuildResult(
        project_dir=directory,
        csproj=csproj,
        command=tuple(command),
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration_seconds=duration,
        dll_path=dll_path if exists else None,
        dll_sha256=_sha256(dll_path) if exists else None,
        dll_size=dll_path.stat().st_size if exists else None,
        dotnet_version=_dotnet_version(dotnet),
    )

    if log_path is not None:
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            "\n".join(
                [
                    f"command: {' '.join(result.command)}",
                    f"cwd: {directory}",
                    f"dotnet: {result.dotnet_version}",
                    f"exit_code: {result.returncode}",
                    f"duration_seconds: {duration:.3f}",
                    f"assembly: {result.dll_path}",
                    f"assembly_sha256: {result.dll_sha256}",
                    f"assembly_size: {result.dll_size}",
                    "",
                    "--- stdout ---",
                    result.stdout,
                    "--- stderr ---",
                    result.stderr,
                ]
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    if raise_on_error and not result.ok:
        raise BuildError(
            f"dotnet build failed with exit code {result.returncode} ({csproj.name})", result=result
        )
    return result
