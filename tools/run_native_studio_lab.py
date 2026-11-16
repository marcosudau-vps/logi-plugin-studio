"""Native Windows lab. Every editable project is a temporary example copy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from studio.native_shell import NativeStudioShell


def smoke(window):
    c = window.coordinator
    assert len(c.session.native_project().actions) == 4
    c.select_offer(window.catalog.offer_for('action.command', 'second'))
    assert c.action_parameter == 'second'
    before = c.session.snapshot()
    c.rename_action('action.command', 'Lab change', base_revision=c.session.revision)
    assert c.session.dirty
    c.undo()
    assert c.session.snapshot() == before
    c.redo()
    assert window.save_project()
    assert window.reload_project()
    assert not c.session.dirty
    assert c.session.native_project().actions[0].display_name == 'Lab change'
    assert not window.ict_action.isEnabled()
    assert not window.preview_notice.isEnabled()
    print('NativeStudioShell smoke: 10 checks PASS; temporary JSON only', flush=True)


def visual_evidence(app, window, destination):
    if sys.platform != 'win32' or app.platformName() != 'windows':
        raise RuntimeError('Visual evidence requires the real Windows Qt platform, not offscreen.')
    destination.mkdir(parents=True, exist_ok=True)
    shots = []
    def capture(name):
        window.show()
        window.raise_()
        window.activateWindow()
        QTest.qWait(250)
        screen = window.screen()
        image = screen.grabWindow(int(window.winId()))
        if image.isNull() or not image.save(str(destination / (name + '.png'))):
            raise RuntimeError('Native Windows screen capture failed')
        shots.append({'name': name, 'logical_size': [window.width(), window.height()],
                      'pixels': [image.width(), image.height()], 'dpr': window.devicePixelRatioF()})
    app.setPalette(app.style().standardPalette())
    window.resize(1240, 780)
    window.move(20, 20)
    window.splitter.setSizes([290, 320, 630])
    window.coordinator.select_node('action', 'action.command')
    capture('01-light-wide-details')
    window.coordinator.select_offer(window.catalog.offer_for('action.command', 'second'))
    window.request_help()
    capture('02-light-help-parameter')
    window.resize(920, 740)
    window.splitter.setSizes([245, 260, 415])
    capture('03-light-narrow-help')
    dark = QPalette()
    for role, color in ((QPalette.ColorRole.Window, '#20242a'), (QPalette.ColorRole.Base, '#171b20'),
                        (QPalette.ColorRole.AlternateBase, '#292f37'), (QPalette.ColorRole.Button, '#303741'),
                        (QPalette.ColorRole.WindowText, '#eeeeee'), (QPalette.ColorRole.Text, '#eeeeee'),
                        (QPalette.ColorRole.ButtonText, '#eeeeee'), (QPalette.ColorRole.Highlight, '#247e97'),
                        (QPalette.ColorRole.PlaceholderText, '#a5adb8'),
                        (QPalette.ColorRole.HighlightedText, '#ffffff')):
        dark.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        dark.setColor(QPalette.ColorGroup.Disabled, role, QColor('#8a929c'))
    app.setPalette(dark)
    capture('04-dark-narrow-help')
    window.resize(1240, 780)
    window.splitter.setSizes([290, 320, 630])
    window.tabs.setCurrentWidget(window.details)
    capture('05-dark-wide-details')
    window.coordinator.rename_action('action.command', 'Ungespeicherter Laborname',
                                     base_revision=window.coordinator.session.revision)
    capture('06-dark-dirty')
    path = window.coordinator.session.path
    external = path.read_bytes() + b'\n'
    path.write_bytes(external)  # A controlled external writer, on the temporary copy only.
    assert not window.save_project()
    assert path.read_bytes() == external and window.coordinator.session.dirty
    table = window.problems.problems_table
    QTest.qWait(50)
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                     pos=table.visualRect(table.model().index(0, 0)).center())
    capture('07-dark-save-conflict')
    window.resize(920, 740)
    capture('08-dark-narrow-problems')
    app.setPalette(app.style().standardPalette())
    window.resize(1240, 780)
    capture('09-light-save-conflict')
    modal_seen = []
    def cancel_modal():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QMessageBox):
            return
        image = dialog.screen().grabWindow(int(dialog.winId()))
        modal_seen.append(image.save(str(destination / '10-dirty-close-dialog.png')))
        dialog.button(QMessageBox.StandardButton.Cancel).click()
    QTimer.singleShot(250, cancel_modal)
    assert not window.confirm_unsaved()
    assert modal_seen == [True]
    assert window.coordinator.session.dirty
    window.coordinator.help.set_pinned(False)
    window.coordinator.diagnostic_activated(window.problems.diagnostics('save')[0])
    window.tabs.setCurrentWidget(window.help_widget)
    capture('11-error-help')
    window.tabs.setCurrentWidget(window.preview_notice)
    capture('12-preview-unavailable')
    result = {'platform': app.platformName(), 'screenshots': shots, 'modal_cancel_verified': True,
              'external_bytes_preserved': path.read_bytes() == external,
              'temporary_project': str(path), 'scale_factor': os.environ.get('QT_SCALE_FACTOR', 'OS default')}
    (destination / 'visual-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    with tempfile.TemporaryDirectory(prefix='native-studio-lab-') as temporary:
        project = Path(temporary) / 'project.json'
        source = ROOT / 'examples/project_logitech_native_v1.json'
        original = source.read_bytes()
        project.write_bytes(original)
        window = NativeStudioShell(project)
        window.show()
        app.processEvents()
        try:
            if args.smoke:
                smoke(window)
            elif args.evidence:
                visual_evidence(app, window, args.evidence)
            else:
                return app.exec()
            assert source.read_bytes() == original
        finally:
            # Explicit lab teardown; no dirty close, no project autosave.
            window.hide()
            window.deleteLater()
            app.processEvents()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
