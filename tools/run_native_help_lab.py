"""AP-HELP-001 Windows/Qt evidence lab; only a temporary native project copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QPushButton, QTreeWidgetItemIterator
from core.errors import Diagnostic
from studio.native_shell import NativeStudioShell


def walkthrough(app, w, destination=None):
    if destination and (sys.platform != 'win32' or app.platformName() != 'windows'):
        raise RuntimeError('Evidence requires genuine visible Windows Qt, not offscreen.')
    report = {'platform': app.platformName(), 'os': sys.platform,
              'qt': __import__('PySide6').__version__, 'checks': [], 'screenshots': []}
    if destination: destination.mkdir(parents=True, exist_ok=True)
    c = w.coordinator
    original = c.session.path.read_bytes()
    revision = c.session.revision

    def check(name, condition):
        report['checks'].append({'name': name, 'pass': bool(condition)})
        if not condition: raise AssertionError(name)

    def capture(name):
        if destination is None: return
        w.raise_()
        w.activateWindow()
        QTest.qWait(180)
        pixmap = w.screen().grabWindow(int(w.winId()))
        check(name + ' capture', not pixmap.isNull() and pixmap.save(str(destination / (name + '.png'))))
        report['screenshots'].append({'file': name + '.png', 'pixels': [pixmap.width(), pixmap.height()],
                                      'logical': [w.width(), w.height()], 'dpr': w.devicePixelRatioF()})

    def topic(): return c.help.current().resolved_topic_id

    available = w.screen().availableGeometry()
    w.resize(min(1240, available.width() - 40), min(780, available.height() - 60))
    w.move(available.x() + 15, available.y() + 15)
    w.splitter.setSizes([290, 330, 620])
    w.show()
    w.activateWindow()
    QTest.qWait(100)
    events = QSignalSpy(c.help.helpChanged)
    with patch.object(c.session, 'replace', wraps=c.session.replace) as replace, patch.object(c.session, 'save', wraps=c.session.save) as save:
        combo = w.catalog.type_combo
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Home)
        QTest.keyClick(combo, Qt.Key.Key_Down)
        app.processEvents()
        check('type filter FocusIn and keyboard choice', topic() == 'catalog.type_filter' and combo.currentIndex() == 1)
        QTest.keyClick(combo, Qt.Key.Key_F1)
        app.processEvents()
        check('filter F1 displays matching facts', topic() == 'catalog.type_filter' and ('SDK-Typ', combo.currentText()) in c.help.current().facts)
        capture('01-catalog-filter-help')
        w.catalog.set_type_filter(None)
        tree = w.explorer.tree
        it = QTreeWidgetItemIterator(tree)
        while it.value() and it.value().data(0, Qt.ItemDataRole.UserRole) != ('folder_entry', 'placement.command'):
            it += 1
        item = it.value()
        check('native FolderEntry exists', item is not None)
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        tree.scrollToItem(item)
        app.processEvents()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center())
        app.processEvents()
        check('real explorer mouse selection uses Placement-ID', c.selection == ('folder_entry', 'placement.command') and topic() == 'explorer.folder_entry')
        check('FolderEntry facts separate Action-ID', ('Action-ID', 'action.command') in c.help.current().facts)
        capture('02-explorer-folder-entry-help')
        c.publish_diagnostics('help.lab', [Diagnostic('HELP_LAB', '/', 'Laborhinweis: Diagnose ohne geprüfte Entity-Navigation.'),
                                          Diagnostic('HELP_WARN', '/', 'Zusätzliche Warnung für den Severity-Filter.', 'WARNING')],
                              project_token=c.project_token, base_revision=c.session.revision)
        w.tabs.setCurrentWidget(w.problems)
        app.processEvents()
        table = w.problems.problems_table
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         pos=table.visualRect(table.model().index(0, 0)).center())
        app.processEvents()
        check('problem selection gives diagnostic help', topic() == 'problems.diagnostic')
        check('problem detail text visible', 'Laborhinweis' in w.problems.detail_text() and w.problems.detail_view.isVisible())
        capture('03-problems-detail')
        w.problems.detail_view.setFocus()
        QTest.keyClick(w.problems.detail_view, Qt.Key.Key_F1)
        app.processEvents()
        check('F1 details keeps diagnostic context after tab change', topic() == 'problems.diagnostic')
        capture('04-problems-context-help')
        pin = w.help_widget.findChild(QPushButton, 'helpPin')
        QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
        check('pin click', c.help.current().pinned)
        w.catalog.search_edit.setFocus()
        QTest.keyClicks(w.catalog.search_edit, 'second')
        check('ordinary focus/search respect pin', topic() == 'problems.diagnostic')
        QTest.keyClick(w.catalog.search_edit, Qt.Key.Key_F1)
        app.processEvents()
        check('explicit F1 overrides pin', topic() == 'catalog.search' and c.help.current().pinned)
        capture('05-pinned-explicit-search-help')
        c.help.set_pinned(False)
        w.catalog.set_filter('')
        c.select_node('action', 'action.editor')
        observed = []
        def inspect_modal():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QInputDialog):
                QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_F1)
                observed.append(topic())
                capture('06-modal-help')
                dialog.reject()
        QTimer.singleShot(100, inspect_modal)
        w.rename_selected()
        check('real rename modal F1 and cancel', observed == ['native_shell.rename'])
        c.help.set_pinned(True)
        c.open_project(c.session.path)
        check('project switch clears pin and facts', not c.help.current().pinned and not c.help.current().facts)
        check('project switch clears diagnostics', not w.problems.diagnostics())
        check('Create aktiv; ICT bleibt gesperrt', w.catalog.new_action_button.isEnabled() and not w.ict_action.isEnabled())
        check('help made zero replace/save calls', replace.call_count == 0 and save.call_count == 0)
    check('new session revision and byte-identical temporary JSON', c.session.revision != revision and c.session.path.read_bytes() == original and not c.session.dirty)
    check('bounded help emissions', events.count() < 90)
    report['help_emissions'] = events.count()
    report['original_example_sha256'] = hashlib.sha256((ROOT / 'examples/project_logitech_native_v1.json').read_bytes()).hexdigest()
    report['result'] = 'PASS'
    if destination: (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='native-help-lab-') as directory:
        path = Path(directory) / 'native.json'
        path.write_bytes((ROOT / 'examples/project_logitech_native_v1.json').read_bytes())
        w = NativeStudioShell(path)
        if args.smoke or args.evidence:
            walkthrough(app, w, args.evidence)
            w.hide()
            return 0
        w.show()
        return app.exec()


if __name__ == '__main__': raise SystemExit(main())
