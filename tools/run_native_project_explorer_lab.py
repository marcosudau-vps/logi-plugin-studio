"""Standalone, file-read-only NativeProjectExplorer lab (no StudioWindow/session).

    python tools/run_native_project_explorer_lab.py
    python tools/run_native_project_explorer_lab.py --smoke
    python tools/run_native_project_explorer_lab.py --capture-evidence PATH

Only the last, explicit option writes evidence. Screenshots use the real Windows
desktop surface, never QWidget.grab/render or the offscreen renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from adapters.logitech.native import NativeFolderEntry, parse_native_project
from studio.native_project_explorer import NativeProjectExplorerWidget

EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"


class Lab(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Native Project Explorer · AP-WIDGET-006 Lab")
        self.resize(1040, 940)
        self.source_bytes = EXAMPLE.read_bytes()
        self.project = parse_native_project(json.loads(self.source_bytes))
        # Local snapshot: removed command, new action/entry, duplicate label and
        # repeated references to one definition. The real file is never changed.
        changed_action = replace(self.project.actions[0], id="action.local", display_name="Lokaler Snapshot · Änderung")
        changed_folder = replace(self.project.folders[0], entries=(
            NativeFolderEntry("placement.local", "action.local", 0),
            NativeFolderEntry("placement.again", "action.local", 1),
            *self.project.folders[0].entries[1:],
        ))
        self.alternate = replace(self.project, actions=(*self.project.actions[1:], changed_action), folders=(changed_folder,))
        self.explorer = NativeProjectExplorerWidget()
        self.explorer.set_project(self.project, revision="lab-original")
        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QLabel("Natives Plugin-Projekt")
        heading_font = heading.font()
        heading_font.setPointSize(15)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        description = QLabel("Ein Klick wählt ein natives Objekt. Enter oder Doppelklick meldet einen Öffnen-Intent an den Host.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.snapshot_label = QLabel("Snapshot: natives Beispiel · lab-original")
        self.snapshot_label.setWordWrap(True)
        layout.addWidget(self.snapshot_label)

        controls = QHBoxLayout()
        self.original_button = QPushButton("Original-Snapshot")
        self.changed_button = QPushButton("Snapshot wechseln")
        self.empty_button = QPushButton("Projekt leeren")
        controls.addWidget(self.original_button)
        controls.addWidget(self.changed_button)
        controls.addWidget(self.empty_button)
        layout.addLayout(controls)
        self.original_button.clicked.connect(self.original)
        self.changed_button.clicked.connect(self.changed)
        self.empty_button.clicked.connect(self.empty)
        view_controls = QHBoxLayout()
        self.filter_button = QPushButton("Filter: multistate")
        self.reset_button = QPushButton("Filter leeren")
        self.width_combo = QComboBox()
        self.width_combo.addItems(("Breit · 460 px", "Schmal · 280 px"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(("Hell", "Dunkel"))
        for widget in (self.filter_button, self.reset_button, self.width_combo, self.theme_combo):
            view_controls.addWidget(widget)
        layout.addLayout(view_controls)
        self.filter_button.clicked.connect(lambda: self.explorer.set_filter("multistate"))
        self.reset_button.clicked.connect(lambda: self.explorer.set_filter(""))
        self.width_combo.currentIndexChanged.connect(self.sidebar_width)
        self.theme_combo.currentIndexChanged.connect(self.theme)
        layout.addWidget(QLabel("Auswahl / Öffnen-Intents"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        layout.addWidget(self.log, 1)
        note = QLabel("Quelle: examples/project_logitech_native_v1.json\nVier Aktionsdefinitionen · ein Handler · ein Dynamic Folder · vier Placements")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.explorer)
        self.splitter.addWidget(panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([460, 580])
        self.setCentralWidget(self.splitter)
        self.events = []
        self.explorer.nodeSelected.connect(lambda kind, native_id: self.record("nodeSelected", kind, native_id))
        self.explorer.nodeActivated.connect(lambda kind, native_id: self.record("nodeActivated", kind, native_id))
        self.theme(0)

    def record(self, signal, kind, native_id):
        self.events.append((signal, kind, native_id))
        self.log.appendPlainText(f"{signal}({kind!r}, {native_id!r})")

    def original(self):
        self.explorer.set_filter("")
        self.explorer.set_project(self.project, revision="lab-original")
        self.snapshot_label.setText("Snapshot: natives Beispiel · lab-original")

    def changed(self):
        self.explorer.set_project(self.alternate, revision="lab-local-change")
        self.snapshot_label.setText("Snapshot: lokale Änderung · action.local zweimal platziert")

    def empty(self):
        self.explorer.set_project(None)
        self.snapshot_label.setText("Snapshot: kein Projekt")

    def sidebar_width(self, index):
        width = 280 if index else 460
        self.splitter.setSizes([width, max(0, self.splitter.width() - self.splitter.handleWidth() - width)])

    def theme(self, index):
        palette = QPalette()
        dark = bool(index)
        colors = {
            "Window": "#24272c" if dark else "#f2f4f7",
            "WindowText": "#edf0f5" if dark else "#202734",
            "Base": "#1c1f24" if dark else "#ffffff",
            "AlternateBase": "#292d33" if dark else "#edf0f4",
            "Text": "#edf0f5" if dark else "#202734",
            "Button": "#30353d" if dark else "#e7ebf1",
            "ButtonText": "#edf0f5" if dark else "#202734",
            "Highlight": "#225d85" if dark else "#cce6fa",
            "HighlightedText": "#ffffff" if dark else "#102f49",
            "ToolTipBase": "#30353d" if dark else "#ffffff",
            "ToolTipText": "#edf0f5" if dark else "#202734",
            "PlaceholderText": "#a8b0bd" if dark else "#586477",
        }
        for role, color in colors.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
        QApplication.setPalette(palette)


def item_for(window, kind, native_id):
    tree = window.explorer.tree
    pending = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while pending:
        item = pending.pop(0)
        if item.data(0, Qt.ItemDataRole.UserRole) == (kind, native_id):
            return item
        pending.extend(item.child(i) for i in range(item.childCount()))
    raise AssertionError(f"Missing {kind}: {native_id}")


def click_item(window, kind, native_id, *, double=False):
    tree = window.explorer.tree
    item = item_for(window, kind, native_id)
    tree.scrollToItem(item)
    QApplication.processEvents()
    position = tree.visualItemRect(item).center()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
    if double:
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QApplication.processEvents()


def smoke(window):
    """Actual mouse/key events through the real widget and lab controls."""
    try:
        click_item(window, "action", "action.command")
        assert window.events == [("nodeSelected", "action", "action.command")], window.events
        QTest.keyClick(window.explorer.tree, Qt.Key.Key_Return)
        assert window.events[-1] == ("nodeActivated", "action", "action.command")
        before = len(window.events)
        click_item(window, "folder_entry", "placement.editor", double=True)
        assert window.events[before:] == [
            ("nodeSelected", "folder_entry", "placement.editor"),
            ("nodeActivated", "folder_entry", "placement.editor"),
        ], window.events[before:]
        print("PASS: native selection, Enter and double-click (exact signal counts)")
        before = len(window.events)
        search = window.explorer.search_edit
        QTest.mouseClick(search, Qt.MouseButton.LeftButton)
        QTest.keyClicks(search, "MULTISTATE")
        assert not item_for(window, "action", "action.multistate").isHidden()
        assert item_for(window, "action", "action.command").isHidden()
        QTest.keyClick(search, Qt.Key.Key_Escape)
        assert search.text() == ""
        assert len(window.events) == before
        print("PASS: user filter input, case-insensitive results, Esc, no navigation echoes")
        window.explorer.set_selection("action", "action.command")
        QTest.mouseClick(window.changed_button, Qt.MouseButton.LeftButton)
        QTest.keyClick(window.explorer.tree, Qt.Key.Key_Return)
        assert len(window.events) == before
        click_item(window, "folder_entry", "placement.again")
        assert window.events[-1] == ("nodeSelected", "folder_entry", "placement.again")
        assert item_for(window, "action", "action.local")
        print("PASS: snapshot replacement, removed selection and repeated placement identity")
        before = len(window.events)
        QTest.mouseClick(window.empty_button, Qt.MouseButton.LeftButton)
        QTest.keyClick(window.explorer.tree, Qt.Key.Key_Return)
        assert window.explorer.tree.topLevelItemCount() == 0
        assert len(window.events) == before
        QTest.mouseClick(window.original_button, Qt.MouseButton.LeftButton)
        assert window.explorer.tree.topLevelItemCount() == 1
        assert EXAMPLE.read_bytes() == window.source_bytes
        print("PASS: empty state, original snapshot restored, source bytes unchanged")
        print(f"SMOKE PASS · platform={QApplication.platformName()} · 4/4")
        return 0
    except Exception:
        traceback.print_exc()
        print("SMOKE FAIL")
        return 1


def capture_evidence(window, destination):
    """Capture the Windows desktop pixels of this visible lab at both widths/themes."""
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        raise RuntimeError("Evidence requires a visible real Windows desktop (QT_QPA_PLATFORM=windows)")
    # Windows may refuse foreground activation of a background process. Keep the
    # explicitly requested evidence window above other apps during capture.
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.move(window.screen().availableGeometry().topLeft() + QPoint(70, 70))
    window.show()
    destination.mkdir(parents=True, exist_ok=True)
    result = {"platform": sys.platform, "windows": str(sys.getwindowsversion()),
              "qt_platform": QApplication.platformName(), "capture": "QScreen.grabWindow(0), visible desktop region",
              "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"),
              "example_sha256": hashlib.sha256(window.source_bytes).hexdigest(), "screenshots": []}

    def capture(name):
        window.raise_()
        window.activateWindow()
        QTest.qWait(450)
        screen = window.screen()
        top = window.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
        pixmap = screen.grabWindow(0, top.x(), top.y(), window.width(), window.height())
        assert not pixmap.isNull() and pixmap.save(str(destination / name))
        result["screenshots"].append({"file": name, "window_dip": [window.width(), window.height()],
                                      "sidebar_dip": window.explorer.width(), "device_pixel_ratio": window.devicePixelRatioF(),
                                      "pixels": [pixmap.width(), pixmap.height()], "logical_dpi": screen.logicalDotsPerInch()})

    for theme in (0, 1):
        window.theme_combo.setCurrentIndex(theme)
        for width in (0, 1):
            window.original()
            window.width_combo.setCurrentIndex(width)
            window.sidebar_width(width)
            window.explorer.set_selection("folder_entry", "placement.multistate")
            window.explorer.tree.setFocus()
            capture(f"{'dark' if theme else 'light'}-{'narrow' if width else 'wide'}-full.png")
        QTest.mouseClick(window.filter_button, Qt.MouseButton.LeftButton)
        capture(f"{'dark' if theme else 'light'}-filter.png")
    window.explorer.set_filter("nicht-vorhanden")
    capture("no-results.png")
    QTest.mouseClick(window.empty_button, Qt.MouseButton.LeftButton)
    capture("empty-project.png")
    window.original()
    QTest.mouseClick(window.changed_button, Qt.MouseButton.LeftButton)
    click_item(window, "folder_entry", "placement.again", double=True)
    capture("snapshot-change-intents.png")
    assert EXAMPLE.read_bytes() == window.source_bytes
    (destination / "capture-metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WINDOWS EVIDENCE PASS: " + str(destination))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--capture-evidence", type=Path)
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Native Project Explorer Lab")
    app.setStyle("Fusion")
    window = Lab()
    window.show()
    saved_cursor = QCursor.pos()

    def run():
        status = 0
        try:
            if args.smoke:
                status = smoke(window)
            if args.capture_evidence and status == 0:
                capture_evidence(window, args.capture_evidence)
        except Exception:
            traceback.print_exc()
            status = 1
        finally:
            QCursor.setPos(saved_cursor)
        app.exit(status)

    if args.smoke or args.capture_evidence:
        QTimer.singleShot(300, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
