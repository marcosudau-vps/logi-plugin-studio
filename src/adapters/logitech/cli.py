"""Command line entry point of the Logitech adapter (build-only, no install).

Examples
--------
``python tools/run_logitech_adapter.py capabilities``
``python tools/run_logitech_adapter.py generate --project examples/project_core_valid.json
  --plugin-id studio.sample --assembly StudioSample --out work/tmp/sample --build``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .build import build_project
from .capabilities import capability_report
from .codegen import DEFAULT_SDK_DLL, generate
from .errors import BuildError, LogitechAdapterError
from .gate import load_project_selection

EXIT_OK = 0
EXIT_ADAPTER_ERROR = 1
EXIT_USAGE = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_capabilities(_: argparse.Namespace) -> int:
    print(json.dumps(capability_report(), ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_generate(args: argparse.Namespace) -> int:
    plan = generate(
        args.project,
        plugin_id=args.plugin_id,
        assembly_name=args.assembly,
        output_dir=args.out,
        sdk_dll=args.sdk_dll,
        plugin_display_name=args.display_name,
        plugin_version=args.version,
    )
    out_dir = Path(args.out).resolve()
    payload: dict[str, Any] = {
        "status": "GENERATED",
        "project": plan.project_id,
        "plugin": plan.plugin_id,
        "assembly": plan.assembly_name,
        "namespace": plan.namespace,
        "plugin_class": plan.plugin_class,
        "output_dir": str(out_dir),
        "sdk_reference": {"path": str(plan.sdk_dll), "sha256": plan.sdk_dll_sha256},
        "actions": [action.as_dict() for action in plan.actions],
        "files": {relative: _sha256(out_dir / relative) for relative in plan.files},
    }
    exit_code = EXIT_OK
    if args.build:
        try:
            result = build_project(out_dir, log_path=out_dir.parent / f"{out_dir.name}-dotnet-build.log")
        except BuildError as exc:
            payload["status"] = "BUILD_FAILED"
            payload["build"] = exc.result.as_dict() if exc.result else {"error": exc.message}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return EXIT_ADAPTER_ERROR
        payload["status"] = "BUILT"
        payload["build"] = result.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def cmd_inspect(args: argparse.Namespace) -> int:
    selection = load_project_selection(args.project)
    print(
        json.dumps(
            {
                "project": selection.project_id,
                "display_name": selection.display_name,
                "actions": [action.component_id for action in selection.actions],
                "unsupported_components": list(selection.unsupported_components),
                "not_generated": selection.not_generated,
                "warnings": list(selection.warnings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Logitech SDK adapter (generates and builds a C# plugin; never installs)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capabilities", help="Print the capability matrix as JSON")
    cap.set_defaults(func=cmd_capabilities)

    gen = sub.add_parser("generate", help="Generate (and optionally build) plugin sources")
    gen.add_argument("--project", required=True, help="Validated project definition (JSON)")
    gen.add_argument("--plugin-id", required=True, help="Unique plugin identifier")
    gen.add_argument("--assembly", required=True, help="C# assembly name")
    gen.add_argument("--out", required=True, help="Output directory for generated sources")
    gen.add_argument("--sdk-dll", default=str(DEFAULT_SDK_DLL), help="Path to the installed PluginApi.dll")
    gen.add_argument("--display-name", default=None, help="Plugin display name (default: project display name)")
    gen.add_argument("--version", default="0.1.0", help="Plugin version for package metadata")
    gen.add_argument("--build", action="store_true", help="Run dotnet build in the output directory")
    gen.set_defaults(func=cmd_generate)

    inspect = sub.add_parser("inspect", help="Show what the adapter would generate")
    inspect.add_argument("--project", required=True)
    inspect.set_defaults(func=cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except LogitechAdapterError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_ADAPTER_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
