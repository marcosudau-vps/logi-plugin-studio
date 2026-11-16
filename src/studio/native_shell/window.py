"""Native shell composed from the accepted, real PySide6 widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QInputDialog, QPlainTextEdit, QSplitter, QTabWidget, QToolBar)

from studio.action_inspector.widget import ActionInspectorWidget
from core.errors import Diagnostic
from studio.action_catalog.widget import ActionCatalogWidget
from studio.native_project_explorer.widget import NativeProjectExplorerWidget
from studio.native_session import NativeSessionError, NativeDiskConflict
from .coordinator import StudioCoordinator
from .build_controller import NativeBuildController
from .keypad_binding import NativeKeypadBinding
from .ict_session import SessionIctCoordinator
from studio.native_symbol_dialog import NativeSymbolDesignerDialog
from studio.problems_panel.widget import ProblemsPanelWidget
from studio.context_help import ContextHelpWidget
from .help_bindings import NativeHelpBindings


class NativeStudioShell(QMainWindow):
    def __init__(self, project_path=None, *, workflow=False):
        super().__init__()
        self.setObjectName("nativeStudioShell")
        self.resize(1300, 850)
        self.explorer = NativeProjectExplorerWidget()
        self.catalog = ActionCatalogWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("nativeSelectionDetails")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.details, "Auswahl / native Details")
        self.splitter = QSplitter()
        for widget in (self.explorer, self.catalog, self.tabs):
            self.splitter.addWidget(widget)
        self.splitter.setSizes([300, 330, 670])
        self.setCentralWidget(self.splitter)
        self.inspector = ActionInspectorWidget()
        self.tabs.addTab(self.inspector, "Aktionsinspektor")
        self.composer = None
        self.folder_notice = QLabel('Ein natives Projekt öffnen, um virtuelle Ordner zu organisieren.')
        self.tabs.addTab(self.folder_notice, 'Virtuelle Ordner')
        self.coordinator = StudioCoordinator(self.explorer, self.catalog, self)
        self.keypad = NativeKeypadBinding(self)
        self.tabs.insertTab(1, self.keypad.panel, "Keypad")
        self.ict_dialog = None
        self.coordinator.changed.connect(self._sync_composer)
        self.coordinator.changed.connect(lambda: self.keypad.refresh(force=True))
        self.coordinator.selection_guard = self._guard_selection
        self.coordinator.draft_dirty = lambda: self.inspector.dirty
        self.inspector.applyRequested.connect(self._apply_inspector)
        self.inspector.createRequested.connect(self._apply_create)
        self.inspector.deleteRequested.connect(self.delete_selected)
        self.inspector.refreshRequested.connect(self.refresh_draft)
        self.coordinator.createRequested.connect(self.create_action)
        self.inspector.discardRequested.connect(self._sync_inspector)
        self.inspector.diagnosticsChanged.connect(self._inspector_diagnostics)
        self.problems = ProblemsPanelWidget()
        self.help_widget = ContextHelpWidget()
        self.tabs.addTab(self.problems, "Probleme")
        self.tabs.addTab(self.help_widget, "Hilfe")
        self.coordinator.attach_support(self.problems, self.help_widget)
        self.coordinator.changed.connect(self._observe_inspector_context)
        self.coordinator.changed.connect(self._refresh_status)  # V-24
        self.coordinator.selectionChanged.connect(self._show_selection)  # V-25
        toolbar = QToolBar("Natives Projekt")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = QAction("Nativ öffnen", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_project)  # V-26
        toolbar.addAction(self.open_action)
        self.new_action = QAction("Neues Projekt …", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.create_project)
        toolbar.insertAction(self.open_action, self.new_action)
        self.save_action = self._action(toolbar, 'Natives Projekt speichern', self.save_project, QKeySequence.StandardKey.Save)
        self.folder_save_action = self._action(toolbar, 'Extension speichern', self.save_folders)
        self.undo_action = self._action(toolbar, 'Rückgängig', self.undo_project, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action(toolbar, 'Wiederholen', self.redo_project, QKeySequence.StandardKey.Redo)
        self.rename_action = self._action(toolbar, 'Anzeigename', self.rename_selected)
        self.reload_action = self._action(toolbar, 'Neu laden', self.reload_project)
        self.coordinator.editRequested.connect(self.open_inspector)  # V-31 / V-54
        self.ict_action = self._action(toolbar, "SymbolDesigner …", lambda: self.open_symbol_designer())
        self.help_action = QAction("Hilfe", self)
        self.help_action.setShortcut(QKeySequence('F1'))
        self.help_action.triggered.connect(self.request_help)  # V-29
        self.addAction(self.help_action)
        toolbar.addAction(self.help_action)
        self.help_bindings = NativeHelpBindings(self, toolbar)
        self.build_controller = NativeBuildController(self, toolbar)
        from .delivery_panels import DeploymentController, PairingController
        self.deployment_controller = DeploymentController(self)
        self.pairing_controller = PairingController(self)
        self.tabs.currentChanged.connect(self._sync_keypad_tab)
        self.tabs.currentChanged.connect(self._refresh_status)
        self._context_timer = QTimer(self)
        self._context_timer.setInterval(350)
        self._context_timer.timeout.connect(self._observe_inspector_context)
        self._context_timer.timeout.connect(self._sync_composer)
        self._context_timer.start()
        # AP-GUIDE-001: optionale Komfortschicht. Ohne ``workflow=True`` bleibt die Shell unverändert.
        self.workflow = None
        if workflow:
            from .workflow_controller import WorkflowController
            self.workflow = WorkflowController(self, toolbar)
        if project_path is not None:
            self.coordinator.open_project(project_path)
        self._refresh_status()

    def _action(self, toolbar, text, callback, shortcut=None):
        action = toolbar.addAction(text)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)  # V-15 / V-16 / V-32
        return action

    def confirm_unsaved(self):
        if not self.confirm_draft(defer_discard=True):
            return False
        session = self.coordinator.session
        if session is not None and session.dirty:
            answer = QMessageBox.question(self, 'Ungespeicherte native Änderungen', 'Natives Projekt vor dem Fortfahren speichern?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Save:
                if not self._save_session():
                    return False
            elif answer != QMessageBox.StandardButton.Discard:
                return False
        # Discards are deferred until the whole switch succeeds. A later Cancel
        # keeps the inspector draft and both histories, including earlier Discard.
        return not self.composer or self.composer.confirm_discard()

    def _sync_composer(self):
        from studio.virtual_folders.widget import FolderComposer
        from studio.virtual_folders.binding import extension_path
        c = self.coordinator
        if c.session is None:
            return
        if self.composer and self.composer.store is c.extension_store:
            snapshot = c.session.snapshot()
            self.composer.source_revision = c.session.revision
            if snapshot != self.composer._native_snapshot:
                self.composer.set_native_snapshot(snapshot)
            self._folder_diagnostics()
            return
        replacement = FolderComposer(c.extension_store.document, c.session.snapshot(), store=c.extension_store,
                                     import_as_document=True)
        replacement.before_commit = lambda: self._guard_folder_commit(replacement)
        replacement.save_target = extension_path(c.session.path)
        replacement.source_revision = c.session.revision
        replacement.setProperty('inspectorTopic', 'folders.studio')
        replacement.refresh()
        old = self.composer or self.folder_notice
        index = self.tabs.indexOf(old)
        current = self.tabs.currentWidget() is old
        self.composer = replacement
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, replacement, 'Virtuelle Ordner')
        if current:
            self.tabs.setCurrentWidget(replacement)
        self.tabs.blockSignals(False)
        if hasattr(old, 'dispose'):
            old.dispose()
        old.deleteLater()
        replacement.changed.connect(self._folders_changed)
        replacement.actionEditRequested.connect(c.request_edit)
        replacement.errorOccurred.connect(lambda message: c.report_error('folders', message))
        self._folder_diagnostics()

    def _guard_folder_commit(self, composer):
        from studio.virtual_folders.model import FolderError
        try:
            if composer is not self.composer or composer.store is not self.coordinator.extension_store:
                raise FolderError('Fremde Extension; nichts übernommen.')
            if composer.source_revision != self.coordinator.session.revision:
                raise FolderError('Native Revision geändert; bitte aktuellen Stand laden.')
            self.coordinator.session._check_disk()
            if self.composer.store.path:
                self.composer.store._check_disk()
        except (NativeSessionError, OSError) as exc:
            raise FolderError(str(exc)) from exc

    def _folders_changed(self):
        self.keypad.refresh()
        self._folder_diagnostics()
        self._update_delete_state()
        self._refresh_status()

    def _folder_diagnostics(self):
        c = self.coordinator
        missing = c.extension_store.document.missing_actions(c.session.snapshot())
        if not missing:
            if self.problems:
                self.problems.remove_source('folders.references')
            return
        c.publish_diagnostics('folders.references', [Diagnostic('FOLDER_ACTION_UNAVAILABLE',
            '/placements/' + p.id, 'Native Action nicht verfügbar: ' + p.target.key +
            '. Platzierung bleibt erhalten; im Ordnertab bewusst entfernen oder native Quelle wiederherstellen.')
            for p in missing], project_token=c.project_token, base_revision=c.session.revision)

    def save_folders(self):
        return bool(self.composer and self.composer._run(self.composer.save_file))

    def save_all(self):
        """Projekt und Extension nacheinander speichern (zwei Writer, keine gemeinsame Atomarität)."""
        session = self.coordinator.session
        if session is None or not self.confirm_draft():
            return False
        if session.dirty and not self._save_session():
            return False
        if self.composer and self.composer.store.dirty and not self.save_folders():
            return False
        self._refresh_status()
        return True

    def _failure(self, source, error):
        self.coordinator.report_error(source, error)
        self.tabs.setCurrentWidget(self.problems)
        self.statusBar().showMessage(str(error))

    def save_project(self):
        if not self.confirm_draft():
            return False
        return self._save_session()

    def _save_session(self):
        try:
            self.coordinator.save()
            return True
        except NativeSessionError as exc:
            self._failure('save', exc)
            return False

    def rename_selected(self, action_id=None):
        c = self.coordinator
        action = c.selected_action()
        if action is None or (isinstance(action_id, str) and action.id != action_id):
            return
        revision = c.session.revision
        name, accepted = QInputDialog.getText(self, 'Nativer Anzeigename',
            f'Nur NativeAction.display_name ändern\n{action.id}', text=action.display_name)
        if accepted:
            try:
                c.rename_action(action.id, name, base_revision=revision)
            except NativeSessionError as exc:
                self._failure('edit', exc)

    def reload_project(self):
        session = self.coordinator.session
        return bool(session and session.path and self.open_project(session.path))

    def closeEvent(self, event):
        if self.ict_dialog is not None:
            event.ignore()
            self.ict_dialog.activateWindow()
            return
        if self.build_controller.running:
            event.ignore()  # Worker owns a frozen build; do not destroy its QThread.
            self.statusBar().showMessage('SDK-Build läuft; Fenster erst nach Buildabschluss schließen.')
            return
        if self.deployment_controller.running:
            event.ignore()
            self.statusBar().showMessage('Installation läuft; Fenster erst danach schließen.')
            return
        if self.confirm_unsaved():  # V-33
            self.deployment_controller.shutdown()
            self.pairing_controller.timer.stop()
            event.accept()
        else:
            event.ignore()

    def create_project(self, path=None, plugin_id=None, display_name=None):
        """Create a new native project from the built-in template and open it."""
        from .new_project import create_native_project
        if plugin_id is None:
            plugin_id, ok = QInputDialog.getText(self, "Neues Projekt", "Plugin-ID (z. B. meinname.meinplugin):")
            if not ok or not plugin_id.strip():
                return False
        if display_name is None:
            display_name, ok = QInputDialog.getText(self, "Neues Projekt", "Anzeigename:")
            if not ok:
                return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Neues Projekt speichern", plugin_id.strip() + ".json",
                                                  "Projekt (*.json)", options=QFileDialog.Option.DontUseNativeDialog)
            if not path:
                return False
        try:
            created = create_native_project(path, plugin_id, display_name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Neues Projekt", str(exc))
            return False
        return self.open_project(created)

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "SDK-natives Projekt öffnen", "", "Projekt (*.json)",
                                            options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.open_project(path)

    def open_project(self, path):
        if self.ict_dialog is not None:
            self.ict_dialog.activateWindow()
            return False
        if self.build_controller.running:
            self.statusBar().showMessage('SDK-Build läuft; Projektwechsel erst danach möglich.')
            return False
        try:
            # Validate both files before any draft/discard dialog. Re-read after
            # dialogs: a Save or an external writer may have changed the target.
            self.coordinator.prepare_project(path)
            if not self.confirm_unsaved():
                return False
            prepared = self.coordinator.prepare_project(path)
            self.coordinator.activate_project(prepared)
            self.inspector.accept_applied()
            self._sync_inspector()
            return True
        except (NativeSessionError, ValueError, OSError) as exc:
            self._failure('open', exc)
            return False

    def open_inspector(self, action_id=None):
        self._sync_inspector()
        self.tabs.setCurrentWidget(self.inspector)

    def _sync_keypad_tab(self, _index):
        if self.tabs.currentWidget() is self.keypad.panel:
            self.keypad.refresh()

    def open_symbol_designer(self, action_id=None, action_parameter=None, *, slot=None):
        c = self.coordinator
        if self.ict_dialog is not None or self.build_controller.running or c.session is None:
            return False
        action = c.selected_action()
        if action_id is None:
            if action is None:
                return False
            action_id, action_parameter = action.id, c.action_parameter
        if not self.confirm_draft():
            return False
        # Applying an Inspector draft may have made the emitted slot stale.
        if slot and self.keypad.widget.frame() is not slot[0].frame:
            self.statusBar().showMessage("Tastenvorschau wurde aktualisiert; Symbol erneut auswählen.")
            return False
        session, token = c.session, c.project_token
        dialog = None
        try:
            session._check_disk()
            binding = SessionIctCoordinator(session, lambda: c.session is session and c.project_token == token)
            dialog = NativeSymbolDesignerDialog(session.path, self, coordinator=binding,
                                                action_id=action_id, action_parameter=action_parameter)
            dialog.setProperty('inspectorTopic', 'symbol.ict')
            if slot:
                dialog.select_slot(*slot)
        except (ValueError, OSError, TypeError, OverflowError, RecursionError) as exc:
            if dialog is not None:
                dialog.deleteLater()
            self._failure('ict', exc)
            return False
        self.ict_dialog = dialog
        dialog.saved.connect(c._after_change)
        self._refresh_status()
        try:
            dialog.exec()
        finally:
            self.ict_dialog = None
            dialog.deleteLater()
            self._refresh_status()
        return True

    def _sync_inspector(self):
        self._observe_inspector_context()
        if self.inspector.dirty or self.inspector.stale:
            return
        c = self.coordinator
        action = c.selected_action()
        raw = c.session.snapshot() if c.session else None
        record = next((a for a in raw['actions'] if a['id'] == action.id), None) if action else None
        draft = self.inspector.draft
        if draft and action and draft.action_id == action.id and draft.base_revision == c.session.revision and draft.project_token == c.project_token:
            return  # Save/Fokus/gleiche Auswahl erhalten Accordionzustand und Eingaben.
        self.inspector.set_action(raw, action.id if action else None, record,
                                  c.session.revision if c.session else None, c.project_token)
        self._update_delete_state()

    def _observe_inspector_context(self):
        c = self.coordinator
        conflict = False
        if self.inspector.draft and c.session and c.session.path:
            try:
                c.session._check_disk()
            except NativeDiskConflict:
                conflict = True
        self.inspector.observe_context(c.session.revision if c.session else None, c.project_token, conflict)
        self._update_delete_state()

    def _update_delete_state(self):
        c = self.coordinator
        # FolderEntry zeigt die referenzierte Action, bietet aber keinen Delete-Intent.
        check = None
        if c.selection and c.selection[0] == 'action' and not self.inspector.creating and not self.inspector.stale:
            try:
                check = c.action_delete_check(c.selection[1])
            except NativeSessionError:
                pass
        self.inspector.set_delete_state(check)

    def create_action(self):
        if not self.confirm_draft(): return False
        c = self.coordinator
        if not c.session: return False
        self.inspector.start_create(c.session.snapshot(), c.session.revision, c.project_token)
        self.tabs.setCurrentWidget(self.inspector)
        return True

    def _apply_create(self, project_token, revision, proposed):
        try:
            self.coordinator.apply_action_create(proposed, base_revision=revision, project_token=project_token)
        except NativeSessionError as exc:
            self.inspector.show_host_error(exc); self.coordinator.report_error('inspector', exc)
            self._observe_inspector_context()
            return False
        self.inspector.accept_applied(); self._sync_inspector()
        return True

    def refresh_draft(self):
        c = self.coordinator
        draft = self.inspector.draft
        identity = draft.action_id if draft and not self.inspector.creating else None
        token = draft.project_token if draft else None
        self.inspector.accept_applied()
        if token == c.project_token and identity:
            # Exakte alte ID neu laden, niemals einen gleichen Anzeigenamen verwenden.
            if c._exists('action', identity):
                c.select_node('action', identity)
            else:
                c._select(None)
        self._sync_inspector()
        if identity and not c._exists('action', identity):
            self.inspector.empty_message = 'Die Action-ID existiert nicht mehr. Entwurf verworfen; aktuelle Action auswählen.'
            self.inspector._validate()

    def delete_selected(self):
        c = self.coordinator
        if not c.selection or c.selection[0] != 'action': return False
        identity = c.selection[1]
        intent_token = c.project_token
        if self.inspector.stale and not self.inspector.dirty:
            self.inspector.show_host_error('Veralteter Formularstand; vor dem Löschen bewusst aktualisieren.')
            return False
        if not self.confirm_draft(): return False
        if intent_token != c.project_token:
            self.inspector.show_host_error('Projekt während des Löschintents gewechselt; nichts gelöscht.')
            return False
        try:
            check = c.action_delete_check(identity)
            if not check.allowed:
                self.inspector.set_delete_state(check)
                return False
            revision, token = c.session.revision, c.project_token
            c._lifecycle_guard(revision, token)
            dialog = QMessageBox(self)
            dialog.setProperty('inspectorTopic', 'inspector.delete')
            dialog.setWindowTitle('Native Aktion löschen')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(f'Aktion „{check.display_name}“ wirklich löschen?\nAction-ID: {identity}\nHandler und Folder bleiben erhalten.')
            delete = dialog.addButton('Aktion löschen', QMessageBox.ButtonRole.DestructiveRole)
            cancel = dialog.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(cancel); dialog.exec()
            if dialog.clickedButton() is not delete: return False
            c.delete_action(identity, base_revision=revision, project_token=token)
        except NativeSessionError as exc:
            self.inspector.show_host_error(exc); c.report_error('inspector', exc)
            self._observe_inspector_context()
            return False
        self.inspector.accept_applied(); self._sync_inspector()
        return True

    def _inspector_diagnostics(self, errors):
        c = self.coordinator
        if not hasattr(self, 'problems') or not self.inspector.draft:
            return
        c.publish_diagnostics('inspector', [Diagnostic('INSPECTOR_INVALID', e.path, e.message) for e in errors],
            project_token=self.inspector.draft.project_token, base_revision=self.inspector.draft.base_revision)

    def _apply_inspector(self, action_id, revision, proposed):
        try:
            self.coordinator.apply_action_edit(action_id, proposed, base_revision=revision)
        except NativeSessionError as exc:
            self.inspector.show_host_error(exc)
            self.coordinator.report_error('inspector', exc)
            self._observe_inspector_context()
            return False
        self.inspector.accept_applied()
        self._sync_inspector()
        return True

    def confirm_draft(self, *, defer_discard=False):
        if not self.inspector.dirty:
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Ungespeicherter Formularentwurf')
        dialog.setText('Formular vor dem Fortfahren übernehmen? Speichern der Projektdatei erfolgt separat.')
        apply = dialog.addButton('Übernehmen', QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton('Verwerfen', QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is apply:
            if not self.inspector.apply_button.isEnabled():
                self.tabs.setCurrentWidget(self.inspector)
                return False
            d = self.inspector.draft
            return (self._apply_create(d.project_token, d.base_revision, d.proposed_action()) if self.inspector.creating else
                    self._apply_inspector(d.action_id, d.base_revision, d.proposed_action()))
        if dialog.clickedButton() is discard:
            if not defer_discard:
                self.inspector.accept_applied()
                self._sync_inspector()
            return True
        return False

    def _guard_selection(self, key):
        if not self.inspector.dirty:
            return True
        # Selecting another placement of the same definition keeps the same draft.
        identity = key[1] if key and key[0] == 'action' else None
        if key and key[0] == 'folder_entry':
            identity = next((e.action for f in self.coordinator.session.native_project().folders
                             for e in f.entries if e.id == key[1]), None)
        if not self.inspector.creating and identity == self.inspector.draft.action_id:
            return True
        return self.confirm_draft()

    def undo_project(self):
        if self._extension_history():
            self.composer._run(lambda: self.composer.history(False))
            return
        if self.confirm_draft():
            try:
                self.coordinator.undo()
            except NativeSessionError as exc:
                self._failure('history', exc)
                return False
            self.inspector.accept_applied()
            self._sync_inspector()

    def redo_project(self):
        if self._extension_history():
            self.composer._run(lambda: self.composer.history(True))
            return
        if self.confirm_draft():
            try:
                self.coordinator.redo()
            except NativeSessionError as exc:
                self._failure('history', exc)
                return False
            self.inspector.accept_applied()
            self._sync_inspector()

    def request_help(self):
        self.help_bindings.request_help()

    def _extension_history(self):
        current = self.tabs.currentWidget()
        return bool(self.composer and (current is self.composer or
                    (current is self.keypad.panel and self.keypad.virtual)))

    def _refresh_status(self):
        session = self.coordinator.session
        folders_dirty = bool(self.composer and self.composer.store.dirty)
        folder_context = self._extension_history()
        from studio.version import PRODUCT_NAME, VERSION
        self.setWindowTitle(("* " if (session and session.dirty) or folders_dirty else "") +
                            (session.native_project().display_name + " — " if session else "") +
                            f"{PRODUCT_NAME} {VERSION}")
        self.statusBar().showMessage(("Nativ: " + ("Ungespeichert" if session.dirty else "Gespeichert") +
            " | Extension: " + ("Ungespeichert" if folders_dirty else "Gespeichert") + " | " + str(session.path))
            if session else "Kein natives Projekt geöffnet")
        self.save_action.setEnabled(session is not None)
        self.folder_save_action.setEnabled(self.composer is not None)
        owner = self.composer.store if folder_context else session
        self.undo_action.setText('Extension rückgängig' if folder_context else 'Native Änderung rückgängig')
        self.redo_action.setText('Extension wiederholen' if folder_context else 'Native Änderung wiederholen')
        self.undo_action.setEnabled(bool(owner and owner.can_undo))
        self.redo_action.setEnabled(bool(owner and owner.can_redo))
        self.reload_action.setEnabled(bool(session and session.path))
        self.rename_action.setEnabled(self.coordinator.selected_action() is not None)
        self.ict_action.setEnabled(self.coordinator.selected_action() is not None
                                   and self.ict_dialog is None and not self.build_controller.running)
        self.build_controller.update_enabled()

    def _show_selection(self):
        self._sync_inspector()
        import json
        c = self.coordinator
        self.rename_action.setEnabled(c.selected_action() is not None)
        self.ict_action.setEnabled(c.selected_action() is not None and self.ict_dialog is None
                                   and not self.build_controller.running)
        if c.selection is None:
            self.details.setPlainText("Eine native Entität auswählen.")
            return
        kind, identity = c.selection
        raw = c.session.snapshot()
        records = {"plugin": [raw["plugin"]], "action": raw.get("actions", []),
                   "handler": raw.get("handlers", []), "folder": raw.get("folders", []),
                   "folder_entry": [e for f in raw.get("folders", []) for e in f["entries"]]}
        record = next(r for r in records[kind] if r["id"] == identity)
        self.details.setPlainText(f"{kind}: {identity}\nactionParameter: {c.action_parameter!r}\n\n" +
                                  json.dumps(record, ensure_ascii=False, indent=2))
