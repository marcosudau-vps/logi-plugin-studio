"""Bounded real C# process probe using exact generated transport sources."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]


def build_probe(plan, product: Path, directory: Path, *, sdk_dll: Path | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Program.cs").write_text(
        (ROOT / "tests" / "process_probe" / "Program.cs.in").read_text().replace("$NAMESPACE$", plan.namespace),
        encoding="utf-8")
    includes = "".join(f'<Compile Include="{escape(str(product / "src" / name))}" Link="{name}" />'
                       for name in ("Bridge.cs", "Spec.cs"))
    if sdk_dll is not None:
        includes += f'<Compile Include="{escape(str(product / "src" / "Visuals.cs"))}" Link="Visuals.cs" />'
        includes += '<Reference Include="PluginApi"><HintPath>' + escape(str(sdk_dll)) + '</HintPath></Reference>'
    constants = '<DefineConstants>VISUALS_PROBE</DefineConstants>' if sdk_dll is not None else ''
    (directory / "Probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        '<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
        '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
        '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>'
        '<ImportDirectoryPackagesProps>false</ImportDirectoryPackagesProps>'
        '<ImportProjectExtensionProps>false</ImportProjectExtensionProps>'
        '<ImportProjectExtensionTargets>false</ImportProjectExtensionTargets>'
        + constants + '</PropertyGroup><ItemGroup>' + includes + '</ItemGroup></Project>', encoding="utf-8")
    (directory / "nuget.config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    result = subprocess.run(["dotnet", "build", str(directory / "Probe.csproj"), "--nologo", "-v:q"],
                            capture_output=True, text=True, encoding="utf-8", timeout=120,
                            env={**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"})
    (directory / "probe-build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("C# probe compilation failed; see probe-build.log")
    return directory / "bin" / "Debug" / "net10.0" / "Probe.dll"


class ProcessProbe:
    def __init__(self, dll: Path, connection: Path, log: Path, *, sdk_dll: Path | None = None):
        self.log_path = Path(log)
        self.log = self.log_path.open("w", encoding="utf-8")
        child_env = os.environ.copy()
        if sdk_dll is not None:
            # The real SDK bitmap renderer loads libSkiaSharp.dll natively.
            # Only the probe child needs the vendor directory in its DLL search path.
            sdk_dir = Path(sdk_dll).resolve().parent
            child_env["PATH"] = str(sdk_dir) + os.pathsep + child_env.get("PATH", "")
        try:
            self.process = subprocess.Popen(
                ["dotnet", str(dll), str(connection)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, encoding="utf-8", env=child_env,
            )
        except OSError:
            self.log.close()
            raise
        self.responses = queue.Queue()

        def collect():
            try:
                for line in self.process.stdout:
                    self.responses.put(line)
            finally:
                # EOF wakes an RPC immediately after a child-process crash.
                self.responses.put(None)

        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()

    def _stopped(self, operation: str) -> RuntimeError:
        code = self.process.poll()
        if code is None:
            try:
                code = self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                code = "unknown"
        return RuntimeError(
            f"C# probe terminated during {operation} (exit code {code}); "
            f"see local log {self.log_path}"
        )

    def rpc(self, command: str):
        operation = command.split(maxsplit=1)[0] if command else "RPC"
        if self.process.poll() is not None:
            raise self._stopped(operation)
        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise self._stopped(operation) from exc
        try:
            response = self.responses.get(timeout=8)
        except queue.Empty as exc:
            if self.process.poll() is not None:
                raise self._stopped(operation) from exc
            raise TimeoutError(
                f"C# probe RPC '{operation}' timed out; see local log {self.log_path}"
            ) from exc
        if response is None:
            raise self._stopped(operation)
        if not response.startswith("JSON:"):
            raise AssertionError("Malformed process probe response")
        return json.loads(response[5:])

    def wait(self, predicate):
        until = time.monotonic() + 12
        while time.monotonic() < until:
            value = self.rpc("inspect")
            if predicate(value):
                return value
            time.sleep(0.05)
        raise AssertionError("C# probe did not reach expected state")

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("stop\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                # A failed probe may already have closed its input pipe.
                pass
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def check_callback_process(plan, project: Path, product: Path, connection: Path,
                           directory: Path, raw: dict, sdk_dll: Path) -> list[str]:
    """Exercise the fixed trusted example host, not Python loaded from project data."""
    dll = build_probe(plan, product, directory / "probe", sdk_dll=sdk_dll)
    host_log = (directory / "standalone-host.log").open("w", encoding="utf-8")
    host = subprocess.Popen([sys.executable, str(ROOT / "examples" / "first_plugin" / "host.py"),
                             "--project", str(project), "--connection", str(connection), "--run-for", "10"],
                            stdout=host_log, stderr=subprocess.STDOUT)
    try:
        with ProcessProbe(dll, connection, directory / "csharp.log", sdk_dll=sdk_dll) as probe:
            probe.wait(lambda value: value["ready"])
            for size in (50, 80, 116):
                result = probe.rpc(f"geometry 90 40 {size} contain")
                h = max(1, int(40 * (size / 90)))
                assert result == {"x": 0, "y": (size - h) // 2, "width": size, "height": h}, result
            actions = [c["id"] for c in raw["components"] if c["type"] == "core.command_action"]
            for action in actions:
                slot = "state.mode@component:" + action
                assert probe.rpc("dispatch " + action)["accepted"]
                result = probe.wait(lambda value: value["states"][slot]["has_value"])
                state = result["states"][slot]
                assert (state["value"], state["quality"], state["revision"]) == ("active", "fresh", 1), state
                placement = next(p for v in raw["views"] for p in v["placements"] if p["component"] == action)
                visual = next(p for p in raw["presentations"] if p["id"] == placement["presentation"])
                expected_text = visual["variants"]["active"]["text"]
                for size in (50, 80, 116):
                    image = probe.rpc(f"visual {action} {placement['id']} {size}")
                    assert image == {"text": expected_text, "width": size, "height": size}, image
        if host.wait(timeout=15) != 0:
            raise AssertionError("Standalone host failed; inspect its local log")
        return ["standalone_python_trusted_handlers_csharp_dispatch_state_mirror",
                "exact_generated_visuals_real_sdk_state_text_render_geometry_50_80_116"]
    finally:
        if host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        host_log.close()
