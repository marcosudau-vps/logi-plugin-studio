"""Compatibility entry point (0.9 name). Builds the Portable edition only.

Since AP-POLISH-001 both Windows editions come from ONE command:
``python tools/packaging/build_release.py`` (Setup + Portable from the same
payload). This wrapper forwards to it with ``--skip-setup``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_release import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--skip-setup", *sys.argv[1:]]))
