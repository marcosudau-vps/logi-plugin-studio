"""Compare the owner-provided pre-migration hash manifest with the workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with zipfile.ZipFile(args.snapshot) as archive:
        manifest = json.loads(archive.read("snapshot-manifest.json"))
    unchanged: list[str] = []
    changed: list[dict[str, str]] = []
    missing: list[str] = []
    for entry in manifest["files"]:
        relative = entry["path"]
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
            continue
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        if current == entry["sha256"]:
            unchanged.append(relative)
        else:
            changed.append({"path": relative, "sha256_before": entry["sha256"], "sha256_after": current})
    result = {
        "snapshot": str(args.snapshot.resolve()),
        "manifest_files": len(manifest["files"]),
        "unchanged_count": len(unchanged),
        "changed_count": len(changed),
        "missing": missing,
        "changed": changed,
        "protected_parallel_paths_present_in_snapshot": any(
            item["path"].startswith("src/symbol_designer/") or
            item["path"] in ("tests/test_symbol_designer_core.py", "tests/test_symbol_designer_ui.py")
            for item in manifest["files"]
        ),
        "ok": not missing,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
