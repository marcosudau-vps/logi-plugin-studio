"""Start the hardware-free AP-FOLDER-001 demo, optionally capture a Qt smoke."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT / 'examples/project_logitech_native_v1.json')
    parser.add_argument('--extension', type=Path)
    parser.add_argument('--empty', action='store_true', help='Leerer Plugin-Root statt A/B-Beispiel')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from studio.virtual_folders.demo import ComposerWindow
    app = QApplication.instance() or QApplication([])
    original = args.project.read_bytes()
    window = ComposerWindow(args.project, extension_path=args.extension, demo=not args.empty)
    window.show()
    app.processEvents()
    if not args.smoke and not args.evidence:
        return app.exec()
    try:
        w = window.composer
        assert not args.empty, 'Smoke erwartet die A/B-Demo'
        b = next(f for f in w.document.folders if f.name == 'B')
        w.select_folder(b.id)
        w.entries.setCurrentRow(0)
        QTest.mouseClick(w.open_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert w.document.folder(w.navigation.folder_id).name == 'A_01_01_02'
        assert len(w.navigation.stack) == 1
        QTest.mouseClick(w.back_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert w.navigation.folder_id == b.id and not w.navigation.stack
        QTest.mouseClick(w.next_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert not w.navigation.stack
        assert any('nicht verfügbar' in w.entries.item(i).text() for i in range(w.entries.count()))
        assert args.project.read_bytes() == original
        assert not window.session.dirty
        report = dict(result='PASS', platform=app.platformName(), dpr=w.devicePixelRatioF(),
                      checked=['B-Link öffnen', 'Back nach B', 'Seitenwechsel ohne Stack',
                               'Offline-Referenz sichtbar', 'Native Quelle unverändert'],
                      hardware_status='HARDWARE_PENDING')
        if args.evidence:
            args.evidence.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(args.evidence / f'composer-{app.platformName()}.png'))
            (args.evidence / f'smoke-{app.platformName()}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        window.composer.dispose()
        window.hide()
        window.deleteLater()
        app.processEvents()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
