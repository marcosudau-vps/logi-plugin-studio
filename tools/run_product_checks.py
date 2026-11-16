"""Real C# -> HTTP -> Python -> StateStore -> C# process evidence, not hardware."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.codegen import check_output_dir
from adapters.logitech.product import build_product, generate_product, provision_connection
from runtime.host import PluginHost
from runtime.wire import ConnectionSettings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "autopilot" / "FINAL-PRODUCT-02" / "process-check")
    options = parser.parse_args()
    directory = check_output_dir(options.out)
    directory.mkdir(parents=True, exist_ok=True)
    project = ROOT / "examples" / "project_v0_1_draft.json"
    product = directory / "plugin"
    plan = generate_product(project, output_dir=product, assembly_name="StudioProcessCheck")
    build = build_product(plan, product, log_path=directory / "sdk-build.log")
    connection = provision_connection(plan, product)
    settings = ConnectionSettings.load(connection)
    probe = directory / "probe"
    probe.mkdir(exist_ok=True)
    # Generated test harness links the exact generated product transport sources.
    (probe / "Program.cs").write_text(
        (ROOT / "tests" / "process_probe" / "Program.cs.in").read_text().replace("$NAMESPACE$", plan.namespace),
        encoding="utf-8")
    includes = "\n".join(f'<Compile Include="{escape(str(product / "src" / name))}" Link="{name}" />'
                         for name in ("Bridge.cs", "Spec.cs"))
    (probe / "ProcessProbe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        '<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
        '</PropertyGroup><ItemGroup>' + includes + '</ItemGroup></Project>', encoding="utf-8")
    (probe / "nuget.config").write_text("<configuration><packageSources><clear /></packageSources></configuration>")
    environment = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    compiled = subprocess.run(["dotnet", "build", str(probe / "ProcessProbe.csproj"), "--nologo", "-v:q"],
                              capture_output=True, text=True, timeout=120, env=environment)
    (directory / "probe-build.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    if compiled.returncode:
        print(compiled.stdout + compiled.stderr)
        return compiled.returncode
    calls: list[str] = []

    def callback(payload, context):
        calls.append(context.command_id)
        context.set_state("state.primary", "variant_1")
        return {"ok": True}

    def new_host():
        instance = PluginHost(project, settings)
        instance.register_handler("handler.primary", "invoke", callback)
        return instance

    host = new_host().start()
    responses: queue.Queue[str] = queue.Queue()
    log = (directory / "csharp-process.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        ["dotnet", str(probe / "bin" / "Debug" / "net10.0" / "ProcessProbe.dll"), str(connection)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", env=environment)

    def collect():
        for line in process.stdout:
            responses.put(line)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    evidence = {"level": "REAL_CSHARP_PYTHON_PROCESSES", "hardware_test": False,
                "sdk_build": build.as_dict(), "checks": []}

    def rpc(command):
        process.stdin.write(command + "\n")
        process.stdin.flush()
        line = responses.get(timeout=8)
        if not line.startswith("JSON:"):
            raise AssertionError(line)
        return json.loads(line[5:])

    def wait_for(predicate):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            state = rpc("inspect")
            if predicate(state):
                return state
            time.sleep(0.1)
        raise AssertionError("C# mirror did not reach the required observable state")

    try:
        assembly = str(product / "bin" / "Debug" / (plan.assembly_name + ".dll"))
        assert rpc("connection-path " + assembly)["path"] == str(connection)
        assert rpc("connection-path [empty]")["path"] is None
        evidence["checks"].append("sdk_assembly_file_path_resolves_private_config_and_rejects_empty")
        schemas = [
            ({"type": "string", "maxLength": 1}, "\U0001f600", True),
            ({"type": "string", "maxLength": 1}, "ab", False),
            ({"type": "integer", "maximum": 10}, 10, True),
            ({"type": "integer", "maximum": 10}, 10**40, False),
            ({"type": "array", "items": {"type": "integer"}, "minItems": 1}, [2], True),
            ({"type": "array", "items": {"type": "integer"}}, ["bad"], False),
            ({"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}},
              "additionalProperties": False}, {"name": "okay"}, True),
            ({"type": "object", "required": ["name"]}, {}, False),
            ({"type": "object", "properties": {}, "additionalProperties": False}, {"extra": 1}, False),
            ({"enum": [{"a": 1, "b": 2}]}, {"b": 2, "a": 1}, True),
            ({"const": "fixed"}, "different", False),
        ]
        for schema, value, expected in schemas:
            assert rpc("schema " + json.dumps({"schema": schema, "value": value}))["valid"] == expected
        evidence["checks"].append("generated_csharp_schema_validator_11_positive_negative_unicode_nested_range_cases")
        first = wait_for(lambda s: s["ready"])
        slot = "state.primary@runtime"
        assert first["states"][slot]["quality"] == "unknown"
        evidence["checks"].append("signed_handshake_and_unknown_snapshot")
        assert rpc("dispatch action.primary")["accepted"]
        changed = wait_for(lambda s: s["states"].get(slot, {}).get("value") == "variant_1" and s["last_result"] == "COMPLETED")
        assert calls and len(calls) == 1
        assert changed["states"][slot]["revision"] == 1
        evidence["checks"].append("csharp_command_python_handler_explicit_state_delta_completed_result")
        runtime = changed["runtime_instance_id"]
        host.close()
        offline = wait_for(lambda s: not s["ready"])
        assert offline["states"][slot]["value"] == "variant_1"
        assert offline["states"][slot]["quality"] == "stale"
        assert not rpc("dispatch action.primary")["accepted"]
        evidence["checks"].append("disconnect_preserves_value_stale_and_refuses_commands")
        host = new_host()
        host.set_state("state.primary", "variant_0")
        host.start()
        restarted = wait_for(lambda s: s["ready"] and s["runtime_instance_id"] != runtime)
        assert restarted["states"][slot]["value"] == "variant_0"
        assert restarted["states"][slot]["quality"] == "fresh"
        assert len(calls) == 1
        evidence["checks"].append("host_restart_invalidates_runtime_snapshot_no_command_replay")
        assert rpc("dispatch action.primary")["accepted"]
        wait_for(lambda s: s["states"][slot]["value"] == "variant_1")
        assert len(calls) == 2
        evidence["checks"].append("new_runtime_accepts_new_explicit_command")
        actual_handle = host._handle
        corrupt = True

        def corrupted_handle(path, nonce, tag, body):
            reply = actual_handle(path, nonce, tag, body)
            if corrupt and path == "/v1/poll":
                reply["resync"] = True
            if corrupt and path == "/v1/snapshot":
                reply["snapshot"]["states"][slot]["scope"] = {"kind": "component", "component_id": "foreign"}
            return reply

        host._handle = corrupted_handle
        rejected = wait_for(lambda s: not s["ready"] and s["states"].get(slot, {}).get("quality") == "stale")
        assert rejected["states"][slot]["value"] == "variant_1"
        assert not rpc("dispatch action.primary")["accepted"]
        time.sleep(0.5)
        assert not rpc("inspect")["ready"]
        corrupt = False
        wait_for(lambda s: s["ready"] and s["states"][slot]["quality"] == "fresh")
        assert len(calls) == 2
        evidence["checks"].append("signed_malformed_scope_snapshot_rejected_and_full_resync_without_replay")
        evidence["ok"] = True
        print(json.dumps(evidence, indent=2))
        return 0
    finally:
        (directory / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        host.close()
        if process.poll() is None:
            process.stdin.write("stop\n")
            process.stdin.flush()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        reader.join(timeout=2)
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
