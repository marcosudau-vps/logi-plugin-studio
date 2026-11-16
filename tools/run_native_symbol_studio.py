"""Start the real native ICT editor (same widget used by the Studio toolbar)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox
from studio.native_symbol_dialog import NativeSymbolDesignerDialog


def main() -> int:
    parser = argparse.ArgumentParser(description="SDK-nativen SymbolDesigner mit Projektzuordnung öffnen")
    parser.add_argument("project", type=Path, help="Pfad zu einem logitech-native-1-Projekt")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        dialog = NativeSymbolDesignerDialog(args.project)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(None, "Native ICT", str(exc))
        return 2
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
