"""Safe review-source export. A full project ZIP is never a distribution artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.export import ExportError, export_sources, verify_archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="FINAL-PRODUCT-02")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        if args.verify:
            manifest = verify_archive(args.verify)
            print(json.dumps({"verified": True, "share_scope": manifest["share_scope"], "files": manifest["count"]}))
        else:
            result = export_sources(ROOT, ROOT / "work" / "autopilot" / args.run / "delivery", run=args.run)
            print(json.dumps(result))
        return 0
    except (ExportError, OSError):
        # File values/contents and malformed secrets never enter terminal output.
        print('{"error":"SAFE_EXPORT_REFUSED","message":"Export validation failed; inspect source locally, not by sharing a full-project ZIP."}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
