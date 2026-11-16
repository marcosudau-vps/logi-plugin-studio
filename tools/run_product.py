from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.deployment import install_link, plan_install, prepare_package, rollback_link
from adapters.logitech.errors import LogitechAdapterError
from adapters.logitech.product import build_product, generate_product, product_capabilities, provision_connection
from library.document import ProjectDocument
from library.templates import callback_project
from runtime.wire import ConnectionSettings, HostError, LocalClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Plugin Studio product tools: no implicit installation or service control")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    new = commands.add_parser("new")
    new.add_argument("path", type=Path)
    new.add_argument("--id", required=True)
    new.add_argument("--name", default="Mein Python-Plugin")
    generate = commands.add_parser("generate")
    generate.add_argument("--project", type=Path, required=True)
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--assembly", required=True)
    generate.add_argument("--sdk", type=Path, default=DEFAULT_SDK_DLL)
    generate.add_argument("--build", action="store_true")
    generate.add_argument("--port", type=int)
    diagnose = commands.add_parser("diagnose")
    diagnose.add_argument("--connection", type=Path, required=True)
    press = commands.add_parser("press")
    press.add_argument("--connection", type=Path, required=True)
    press.add_argument("--action", required=True)
    press.add_argument("--placement")
    dry = commands.add_parser("plan-install")
    dry.add_argument("--package", type=Path, required=True)
    dry.add_argument("--save", type=Path)
    install = commands.add_parser("install")
    install.add_argument("--plan", type=Path, required=True)
    install.add_argument("--confirm-plugin-id", required=True)
    install.add_argument("--receipts", type=Path, required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--receipt", type=Path, required=True)
    rollback.add_argument("--confirm-plugin-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "capabilities":
            result = product_capabilities()
        elif args.command == "new":
            document = ProjectDocument(callback_project(args.id, args.name))
            document.save(args.path)
            result = {"project": str(args.path.resolve()), "created": True}
        elif args.command == "generate":
            plan = generate_product(args.project, output_dir=args.out, assembly_name=args.assembly, sdk_dll=args.sdk)
            result = {"output": str(args.out.resolve()), "manifest": plan.manifest}
            if args.build:
                built = build_product(plan, args.out, log_path=args.out / "build.log")
                connection = provision_connection(plan, args.out, port=args.port)
                package = prepare_package(plan, args.out, connection)
                result.update({"build": built.as_dict(), "connection": str(connection), "package": str(package)})
        elif args.command in ("diagnose", "press"):
            client = LocalClient(ConnectionSettings.load(args.connection))
            welcome = client.handshake()
            snapshot = client.snapshot()
            result = {"level": "SIMULATED_INPUT_REAL_HTTP" if args.command == "press" else "AUTHENTICATED_HOST",
                      "hardware_test": False, "handshake": welcome, "state": snapshot}
            if args.command == "press":
                accepted = client.command(args.action, placement_id=args.placement)
                result["accepted"] = accepted
                after = snapshot["seq"]
                until = time.monotonic() + 8
                completed = None
                while time.monotonic() < until and completed is None:
                    reply = client.poll(after)
                    if reply["resync"]:
                        raise HostError("COMMAND_OUTCOME_LOST", "Result fell outside the journal; no retry")
                    for event in reply["entries"]:
                        if event["kind"] == "command_result" and event["data"]["command_id"] == accepted["command_id"]:
                            completed = event["data"]
                    after = reply["seq"]
                    if completed is None:
                        time.sleep(0.05)
                if completed is None:
                    raise HostError("COMMAND_UNKNOWN_OUTCOME", "No result before deadline; command is not retried")
                result["result"] = completed
                result["state"] = client.snapshot()
                if completed["status"] != "COMPLETED":
                    print(json.dumps(result, indent=2))
                    return 2
        elif args.command == "plan-install":
            result = plan_install(args.package)
            if args.save:
                args.save.parent.mkdir(parents=True, exist_ok=True)
                args.save.write_text(json.dumps(result, indent=2), encoding="utf-8")
        elif args.command == "install":
            receipt = install_link(json.loads(args.plan.read_text()), confirm_plugin_id=args.confirm_plugin_id,
                                   receipt_dir=args.receipts)
            result = {"receipt": str(receipt), "service_restart": False, "hardware_test": False}
        else:
            rollback_link(args.receipt, confirm_plugin_id=args.confirm_plugin_id)
            result = {"rolled_back": args.confirm_plugin_id, "service_restart": False}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (HostError, LogitechAdapterError, OSError, ValueError) as exc:
        print(json.dumps({"error": getattr(exc, "code", "PRODUCT_ERROR"), "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
