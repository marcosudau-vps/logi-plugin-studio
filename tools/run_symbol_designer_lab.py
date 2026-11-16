"""Start the Symbol Designer Lab: python tools\run_symbol_designer_lab.py [vorlage.ict] [--output DIR] [--library DIR]"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from symbol_designer.lab import main
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print("PySide6 fehlt. Die dokumentierte lokale Python-Umgebung verwenden oder python -m pip install PySide6 ausfuehren.", file=sys.stderr)
        raise SystemExit(2) from exc
    raise

args = sys.argv[1:]
if "--output" not in args:
    args += ["--output", str(ROOT / "work" / "widget-lab" / "icon-designer-v1" / "lab-output")]
raise SystemExit(main(args))
