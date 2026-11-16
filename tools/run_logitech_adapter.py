from __future__ import annotations
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from adapters.logitech.cli import main

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
