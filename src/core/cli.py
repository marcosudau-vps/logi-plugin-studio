"""CLI: ``validate`` and ``inspect`` (no side effects on services/plugins)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


def _load_registry(manifest_dir: str):
    from .registry import load_manifests

    return load_manifests(manifest_dir)


def cmd_validate(project_path: str, manifest_dir: str) -> int:
    from .io import load_raw
    from .validate import validate_project

    try:
        raw = load_raw(project_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "issues": [{"code": "PROJECT_UNREADABLE", "path": "/", "message": str(exc), "severity": "ERROR"}]}, ensure_ascii=False, indent=2))
        return EXIT_USAGE
    registry, reg_issues = _load_registry(manifest_dir)
    issues = [i.as_dict() for i in (*reg_issues, *validate_project(raw, registry))]
    issues.sort(key=lambda d: (d["path"], d["code"], d["message"], d.get("severity", "ERROR")))
    valid = all(d.get("severity", "ERROR") != "ERROR" for d in issues)
    print(json.dumps({"valid": valid, "issues": issues}, ensure_ascii=False, indent=2))
    return EXIT_VALID if valid else EXIT_INVALID


def cmd_inspect(project_path: str, manifest_dir: str) -> int:
    from .io import load_raw, project_from_dict
    from .validate import validate_project

    try:
        raw = load_raw(project_path)
        project = project_from_dict(raw)
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "issues": [{"code": "PROJECT_UNREADABLE", "path": "/", "message": str(exc), "severity": "ERROR"}]}, ensure_ascii=False, indent=2))
        return EXIT_USAGE
    registry, reg_issues = _load_registry(manifest_dir)
    issues = [i.as_dict() for i in (*reg_issues, *validate_project(raw, registry))]
    issues.sort(key=lambda d: (d["path"], d["code"], d["message"], d.get("severity", "ERROR")))
    valid = all(d.get("severity", "ERROR") != "ERROR" for d in issues)
    counts = {
        "components": len(project.components),
        "states": len(project.states),
        "bindings": len(project.bindings),
        "views": len(project.views),
        "presentations": len(project.presentations),
        "assets": len(project.assets),
    }
    print(
        json.dumps(
            {
                "project": {"id": project.project_id, "display_name": project.display_name},
                "counts": counts,
                "valid": valid,
                "issues": issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_VALID if valid else EXIT_INVALID


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="P1 Core Model CLI (validate/inspect; read-only)")
    ap.add_argument("command", choices=["validate", "inspect"])
    ap.add_argument("project")
    ap.add_argument("--manifest-dir", default=str(Path(__file__).resolve().parents[2] / "component_types"))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args.project, args.manifest_dir)
    return cmd_inspect(args.project, args.manifest_dir)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
