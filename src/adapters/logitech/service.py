"""Read-only Logi Plugin Service detection and the one documented per-plugin reload.

Nothing here restarts the service, kills processes, edits profiles or touches
another plugin. The only state-changing call is :func:`request_plugin_reload`,
which asks the installed ``LogiPluginServiceTool`` to process the SDK-documented
deep link ``loupedeck://plugin/<name>/reload`` for exactly one plugin name.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .errors import GenerationError

SERVICE_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Logi" / "LogiPluginService"
OPTIONS_PLUS = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LogiOptionsPlus" / "logioptionsplus.exe"
PLUGIN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3})\s*\|\s*\d+\s*\|\s*(\w+)\s*\|\s*(.*)$")


def _run(command: list, *, timeout: int) -> tuple[int, str, str]:
    """Subprocess call that also works from a windowed (console-less) EXE."""
    out = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, shell=False,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    decode = lambda data: (data or b"").decode("utf-8", "replace") if data else ""
    return out.returncode, decode(out.stdout), decode(out.stderr)


def service_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise GenerationError("LOCALAPPDATA is not configured")
    return Path(base) / "Logi" / "LogiPluginService"


def _version(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        _, stdout, _ = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             f"(Get-Item -LiteralPath '{path}').VersionInfo.FileVersion"], timeout=30)
        return stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _running(image: str) -> list[int]:
    try:
        _, stdout, _ = _run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for row in stdout.splitlines():
        cells = [c.strip('"') for c in row.split('","')]
        if len(cells) > 1 and cells[0].lower() == image.lower() and cells[1].isdigit():
            pids.append(int(cells[1]))
    return pids


@dataclass
class Prerequisites:
    """What the local machine offers. Missing parts are reported, never installed."""
    plugin_service_installed: bool
    plugin_service_version: str | None
    plugin_api_dll: str | None
    plugin_service_running: bool
    service_tool: str | None
    options_plus_installed: bool
    dotnet: str | None
    dotnet_sdks: list[str] = field(default_factory=list)
    python_for_shared: str | None = None
    issues: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def can_build(self) -> bool:
        return self.plugin_api_dll is not None and bool(self.dotnet_sdks)

    @property
    def can_install(self) -> bool:
        return self.plugin_service_installed


def detect_prerequisites(*, sdk_dll: str | Path | None = None) -> Prerequisites:
    api = Path(sdk_dll) if sdk_dll else SERVICE_DIR / "PluginApi.dll"
    tool = SERVICE_DIR / "LogiPluginServiceTool.exe"
    service = SERVICE_DIR / "LogiPluginService.exe"
    dotnet, sdks = None, []
    try:
        code, stdout, _ = _run(["dotnet", "--list-sdks"], timeout=60)
        if code == 0:
            sdks = [line.split()[0] for line in stdout.splitlines() if line.strip()]
            dotnet = sdks[-1] if sdks else None
    except (OSError, subprocess.SubprocessError):
        pass
    from .host_runtime import resolve_shared_python
    result = Prerequisites(
        plugin_service_installed=service.is_file(), plugin_service_version=_version(service),
        plugin_api_dll=str(api) if api.is_file() else None,
        plugin_service_running=bool(_running("LogiPluginService.exe")),
        service_tool=str(tool) if tool.is_file() else None,
        options_plus_installed=OPTIONS_PLUS.is_file(), dotnet=dotnet, dotnet_sdks=sdks,
        python_for_shared=resolve_shared_python())
    if not service.is_file():
        result.issues.append(dict(code="LOGI_PLUGIN_SERVICE_MISSING", severity="error",
            message="Logi Plugin Service ist nicht installiert. Logi Options+ von logitech.com installieren."))
    if result.plugin_api_dll is None:
        result.issues.append(dict(code="PLUGIN_API_MISSING", severity="error",
            message="PluginApi.dll der lokalen Logitech-Installation fehlt; C#-Build nicht möglich."))
    if not sdks or not any(v.split(".")[0].isdigit() and int(v.split(".")[0]) >= 8 for v in sdks):
        result.issues.append(dict(code="DOTNET_SDK_MISSING", severity="error",
            message=".NET SDK 8 oder neuer fehlt (kostenlos: https://dotnet.microsoft.com/download)."))
    if service.is_file() and not result.plugin_service_running:
        result.issues.append(dict(code="LOGI_PLUGIN_SERVICE_STOPPED", severity="warning",
            message="Logi Plugin Service läuft nicht; Logi Options+ starten."))
    from .host_runtime import load_distribution, studio_runtime_dir
    runtime_dir = studio_runtime_dir()
    if runtime_dir is not None:
        try:
            load_distribution(runtime_dir)
        except GenerationError as exc:
            result.issues.append(dict(code="STUDIO_HOST_RUNTIME_DAMAGED", severity="error",
                message=f"Host-Laufzeit des Studios ist beschädigt ({exc}); Studio neu installieren bzw. neu entpacken."))
    elif getattr(sys, "frozen", False):
        result.issues.append(dict(code="STUDIO_HOST_RUNTIME_MISSING", severity="error",
            message="Ordner 'hostruntime' neben LogiPluginStudio.exe fehlt; Studio neu installieren bzw. neu entpacken."))
    if result.python_for_shared is None:
        result.issues.append(dict(code="SHARED_HOST_RUNTIME_MISSING", severity="warning",
            message="Keine Host-Laufzeit für Plugins gefunden (Studio-Ordner 'hostruntime' oder Python 3.12–3.14). "
                    "Gebaute Plugins erhalten dann keine eingebettete Laufzeit."))
    if result.service_tool is None and service.is_file():
        result.issues.append(dict(code="SERVICE_TOOL_MISSING", severity="warning",
            message="LogiPluginServiceTool.exe fehlt; gezielter Plugin-Reload nicht verfügbar."))
    return result


def package_plugin_name(package: str | Path) -> str:
    """The SDK plugin name from the package's own LoupedeckPackage.yaml."""
    text = (Path(package) / "metadata" / "LoupedeckPackage.yaml").read_text(encoding="utf-8")
    match = re.search(r'^name:\s*"?([^"\r\n]+)"?\s*$', text, re.MULTILINE)
    if not match or not PLUGIN_NAME.fullmatch(match.group(1).strip()):
        raise GenerationError("Package metadata has no valid SDK plugin name")
    return match.group(1).strip()


def request_plugin_reload(name: str, *, tool: str | Path | None = None, timeout: int = 45) -> dict:
    """Ask the installed service tool to reload exactly one plugin (SDK deep link)."""
    if not PLUGIN_NAME.fullmatch(name or ""):
        raise GenerationError("Invalid SDK plugin name for reload")
    executable = Path(tool) if tool else SERVICE_DIR / "LogiPluginServiceTool.exe"
    if not executable.is_file():
        raise GenerationError("LogiPluginServiceTool.exe is not installed; reload not possible")
    url = f"loupedeck://plugin/{name}/reload"
    started = time.time()
    try:
        code, stdout, stderr = _run([str(executable), url], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GenerationError("Plugin reload request timed out") from exc
    except OSError as exc:
        raise GenerationError(f"Plugin reload request failed: {exc}") from exc
    return {"url": url, "returncode": code, "requested_at": started,
            "stdout": stdout[-2000:], "stderr": stderr[-2000:]}


def _stamp(text: str) -> float | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H-%M-%S-%f").timestamp()
    except ValueError:
        return None


def plugin_log_lines(name: str, *, since: float = 0.0, log_dir: Path | None = None) -> list[dict]:
    """All service log lines that mention plugin ``name`` (any plugin log file)."""
    root = log_dir if log_dir is not None else service_data_dir() / "Logs" / "plugin_logs"
    if not root.is_dir():
        return []
    needle = f"'{name}'"
    rows = []
    for file in sorted(root.glob("*.log")):
        own = file.stem == name
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            match = _LINE.match(line)
            if not match:
                continue
            stamp = _stamp(match.group(1))
            if stamp is None or stamp < since:
                continue
            if own or needle in match.group(3):
                rows.append(dict(time=stamp, level=match.group(2), message=match.group(3)[:600],
                                 file=file.name))
    rows.sort(key=lambda row: row["time"])
    return rows


def diagnose_plugin_load(name: str, package: str | Path, *, since: float = 0.0,
                         log_dir: Path | None = None) -> dict:
    """Classify the service's load result for one own plugin since ``since``."""
    package = str(Path(package))
    rows = plugin_log_lines(name, since=since, log_dir=log_dir)
    loaded = [r for r in rows if re.search(rf"Plugin '{re.escape(name)}' version '[^']*' loaded from", r["message"])]
    already = [r for r in rows if "is already loaded" in r["message"]]
    errors = [r for r in rows if r["level"] in ("ERROR", "FATAL") and "is already loaded" not in r["message"]]
    started = [r for r in rows if f"Started loading plugin '{name}'" in r["message"]]
    path_ok = None
    for row in loaded:
        match = re.search(r"loaded from '([^']*)'", row["message"])
        if match:
            path_ok = Path(match.group(1).rstrip("\\/")).resolve() == Path(package).resolve()
    if errors:
        status = "LOAD_FAILED"
    elif loaded and path_ok is not False:
        status = "LOADED"
    elif loaded and path_ok is False:
        status = "LOADED_FROM_OTHER_PATH"
    elif already:
        status = "ALREADY_LOADED_RELOAD_REQUIRED"
    elif started:
        status = "LOADING"
    else:
        status = "NO_LOAD_EVENT"
    return {"plugin_name": name, "status": status, "since": since, "events": rows[-40:],
            "errors": errors[-10:], "package": package}


def shared_host_processes(connection: str | Path) -> list[dict]:
    """Child hosts of the plugin service that use this exact connection file."""
    target = str(Path(connection).resolve()).lower()
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*logi-shared-*' } | "
              "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        _, stdout, _ = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=40)
        rows = json.loads(stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    rows = rows if isinstance(rows, list) else [rows]
    return [dict(pid=r["ProcessId"], parent=r["ParentProcessId"]) for r in rows
            if isinstance(r, dict) and target in str(r.get("CommandLine", "")).lower()]
