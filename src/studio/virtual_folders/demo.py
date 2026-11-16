"""Hardware-free host: native session is a read source, extension is separate."""
from __future__ import annotations

from .binding import project_identity

from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from studio.native_session import NativeProjectSession, NativeSessionError
from .codec import ExtensionStore
from .model import Document, FolderError
from .sample import demo_document
from .widget import FolderComposer


class ComposerWindow(QMainWindow):
    def __init__(self, project_path, *, extension_path=None, demo=True):
        super().__init__()
        self.setWindowTitle('FolderComposer · Hardwarefreie Autorenansicht')
        self.resize(1380, 900)
        self.session = NativeProjectSession.load(project_path)
        snapshot = self.session.snapshot()
        identity = project_identity(project_path)
        document = demo_document(snapshot, identity) if demo else Document.create(identity, snapshot['plugin']['id'])
        if extension_path:
            store = ExtensionStore.load(extension_path, project_id=identity, plugin_id=snapshot['plugin']['id'])
            document = store.document
        self.composer = FolderComposer(document, snapshot)
        self.composer.set_native_snapshot(snapshot)  # V-71, read-only session snapshot
        if extension_path:
            self.composer.store = store
            self.composer.refresh()
        self.setCentralWidget(self.composer)
        toolbar = self.addToolBar('Native Auswahlquelle (nur lesen)')
        self.open_action = toolbar.addAction('Anderes natives Projekt öffnen …')
        self.open_action.triggered.connect(self.choose_project)  # V-72

    def open_project(self, path):
        # Prepare and validate everything before any discard decision.
        candidate = NativeProjectSession.load(path)
        snapshot = candidate.snapshot()
        document = Document.create(project_identity(path), snapshot['plugin']['id'])
        replacement = FolderComposer(document, snapshot)
        replacement.set_native_snapshot(snapshot)
        if not self.composer.confirm_discard():
            replacement.dispose()
            replacement.deleteLater()
            return False
        old = self.takeCentralWidget()
        old.dispose()
        old.deleteLater()
        self.session, self.composer = candidate, replacement
        self.setCentralWidget(replacement)
        return True

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'SDK-native Quelle (nur lesen)', '', 'Native Projektdatei (*.json)',
                                             options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            try:
                self.open_project(path)
            except (FolderError, NativeSessionError, OSError) as exc:
                QMessageBox.warning(self, 'Projekt nicht geöffnet', str(exc))

    def closeEvent(self, event):
        if self.composer.confirm_discard():  # V-73
            self.composer.dispose()
            event.accept()
        else:
            event.ignore()
