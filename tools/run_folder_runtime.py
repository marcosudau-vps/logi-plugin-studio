"""Compile an explicit virtual-folder snapshot into SDK-native folder runtime sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.folder_runtime import project_virtual_folders
from adapters.logitech.product import generate_product, build_product
from adapters.logitech.errors import LogitechAdapterError
from core.io import load_raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("extension", type=Path)
    parser.add_argument("--entrypoint", action="append", required=True, metavar="NATIVE_FOLDER=VIRTUAL_NODE")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    try:
        entrypoints = {}
        for pair in args.entrypoint:
            key, value = pair.split("=", 1)
            if key in entrypoints:
                raise ValueError("duplicate entrypoint")
            entrypoints[key] = value
        with args.extension.open("rb") as stream:
            data = stream.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("extension exceeds 4 MiB")
        # The projector reuses the strict extension codec including duplicate keys.
        from studio.virtual_folders.codec import decode
        from dataclasses import asdict
        raw = load_raw(args.project)
        header = json.loads(data)
        document = decode(data, project_id=header.get("project_id"), plugin_id=raw["plugin"]["id"])
        layout = project_virtual_folders(raw, asdict(document), entrypoints=entrypoints, revision=0)
        plan = generate_product(args.project, output_dir=args.out, assembly_name=args.assembly, folder_runtime=layout)
        result = dict(level="GENERATED", folder_runtime="sdk-folders-1", folders=len(layout["folders"]), hardware_test=False)
        if args.build:
            built = build_product(plan, args.out)
            result.update(level="BUILD_PROVEN", build=built.as_dict())
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, LogitechAdapterError) as exc:
        print(f"Folder generation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
