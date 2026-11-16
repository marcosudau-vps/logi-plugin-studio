"""Real C# Bridge -> signed HTTP -> Python CommandContext native-operation probe."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from adapters.logitech.codegen import DEFAULT_SDK_DLL, check_output_dir
from adapters.logitech.product import build_product, generate_product, provision_connection
from probe_helpers import ProcessProbe, build_probe
from runtime.host import PluginHost
from runtime.wire import ConnectionSettings, json_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = check_output_dir(args.out)
    output.mkdir(parents=True, exist_ok=True)
    project = ROOT / "examples" / "project_logitech_native_v1.json"
    product = output / "plugin"
    plan = generate_product(project, output_dir=product, assembly_name="NativeFirstProcess")
    build = build_product(plan, product, log_path=output / "sdk-build.log")
    connection = provision_connection(plan, product)
    settings = ConnectionSettings.load(connection)
    seen: list[dict] = []

    def handler(payload, context):
        seen.append({
            "component_id": context.component_id,
            "placement_id": context.placement_id,
            "action_parameter": context.action_parameter,
            "operation": context.operation,
            "adjustment_diff": context.adjustment_diff,
            "editor_values": context.editor_values,
        })
        return {"ok": True}

    host = PluginHost(project, settings)
    host.register_handler("handler.main", "invoke", handler)
    host.start()
    try:
        probe_dll = build_probe(plan, product, output / "probe")
        with ProcessProbe(probe_dll, connection, output / "csharp.log") as probe:
            probe.wait(lambda value: value["ready"])
            commands = [
                "dispatch-parameter action.command|sdk-parameter",
                "adjustment action.adjustment|fine|-3",
                "editor action.editor|configured",
            ]
            for index, command in enumerate(commands, start=1):
                if not probe.rpc(command)["accepted"]:
                    raise AssertionError(f"C# Bridge rejected operation {index}")
                until = time.monotonic() + 5
                while len(seen) < index and time.monotonic() < until:
                    time.sleep(0.02)
                if len(seen) < index:
                    raise AssertionError(f"Python handler did not receive operation {index}")
            assert seen[0] == {
                "component_id": "action.command", "placement_id": None,
                "action_parameter": "sdk-parameter", "operation": "command",
                "adjustment_diff": None, "editor_values": None,
            }, seen[0]
            assert seen[1]["action_parameter"] == "fine" and seen[1]["operation"] == "adjustment" \
                and seen[1]["adjustment_diff"] == -3 and seen[1]["placement_id"] is None, seen[1]
            assert seen[2]["operation"] == "action_editor" \
                and seen[2]["editor_values"] == {"Text": "configured"}, seen[2]
        evidence = {
            "ok": True,
            "level": "REAL_CSHARP_SIGNED_HTTP_PYTHON",
            "hardware_test": False,
            "sdk_build": build.as_dict(),
            "checks": [
                "action_parameter_preserved_and_distinct_from_placement_id",
                "adjustment_diff_preserved",
                "action_editor_values_preserved",
                "existing_bridge_auth_replay_timeout_and_no_retry_path_reused",
            ],
            "received": seen,
        }
        (output / "evidence.json").write_bytes(json_bytes(evidence))
        print(json.dumps(evidence, indent=2))
        return 0
    finally:
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())
