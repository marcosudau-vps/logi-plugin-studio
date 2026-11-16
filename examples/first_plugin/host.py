"""Trusted standalone example. No code/module name is loaded from project JSON."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from core.io import load_raw
from runtime.host import PluginHost
from runtime.state_store import ScopeAddress
from runtime.wire import ConnectionSettings, HostError


def create_example_host(project: Path, connection: Path) -> PluginHost:
    raw = load_raw(project)
    definitions = {s["id"]: s for s in raw["states"]}
    contract = definitions.get("state.mode")
    if contract is None or contract["scope"] != "component" or contract["value_schema"] != {"type": "string", "enum": ["active", "idle"]}:
        raise HostError("EXAMPLE_CONTRACT", "This trusted example requires component-scoped state.mode with idle/active enum")
    host = PluginHost(raw, ConnectionSettings.load(connection))

    def on_toggle(payload, context):
        scope = ScopeAddress.component(context.component_id)
        old = host.read_state("state.mode", scope)
        value = "idle" if old["has_value"] and old["value"] == "active" else "active"
        context.set_state("state.mode", value, scope)
        print(f"CALLBACK component={context.component_id} placement={context.placement_id} value={value}", flush=True)
        return {"ok": True, "selected": value}

    trusted_callbacks = {"toggle": on_toggle}
    for component in raw["components"]:
        if component["type"] == "core.host_handler":
            callback_id = component["config"]["callback_id"]
            if callback_id not in trusted_callbacks:
                raise HostError("EXAMPLE_CALLBACK", "Register this callback explicitly in your trusted Python application")
            host.register_handler(component["id"], "invoke", trusted_callbacks[callback_id])
    return host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).with_name("project.json"))
    parser.add_argument("--connection", type=Path, required=True)
    parser.add_argument("--run-for", type=float, help="Optional bounded local smoke test")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        with create_example_host(args.project, args.connection) as host:
            print(f"HOST_READY plugin={host.settings.plugin_id} port={host.settings.port} runtime={host.runtime_instance_id}", flush=True)
            end = time.monotonic() + args.run_for if args.run_for else None
            while end is None or time.monotonic() < end:
                time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    except (HostError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
