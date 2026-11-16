from __future__ import annotations
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from core.cli import main

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:] + ([] if '--manifest-dir' in sys.argv[1:] else ['--manifest-dir', str(root / 'component_types')])))
