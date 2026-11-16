"""Invoke as python -m core_spike.cli validate|inspect PROJECT [--manifest-dir DIR]."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import load_manifests, load_project, validate_project


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="P0 draft core model SPIKE")
    ap.add_argument("command", choices=["validate", "inspect"])
    ap.add_argument("project")
    ap.add_argument("--manifest-dir", default=str(Path(__file__).resolve().parents[1] / "component_types"))
    args = ap.parse_args(argv)
    model = load_project(args.project)
    issues = validate_project(model, load_manifests(args.manifest_dir))
    if args.command == "validate":
        print(json.dumps({"valid": not issues, "issues": [i.as_dict() for i in issues]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"project": model.get("project", {}), "counts": {key: len(model.get(key, [])) for key in ("components", "states", "bindings", "views", "presentations")}, "valid": not issues, "issues": [i.as_dict() for i in issues]}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
