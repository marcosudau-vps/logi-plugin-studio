from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from studio.app import main
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print("PySide6 fehlt. Die dokumentierte lokale Python-Umgebung verwenden oder python -m pip install PySide6 ausfuehren.", file=sys.stderr)
        raise SystemExit(2) from exc
    raise

raise SystemExit(main())
