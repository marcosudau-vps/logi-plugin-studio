"""One session, native identities, passive views. No persistent domain model."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QEvent, Qt

from studio.keypad_contract import ActionOffer
from studio.native_session import NativeProjectSession, NativeSessionError, NativeRevisionConflict
from studio.context_help import HelpRegistry, HelpContext
from studio.context_help.coordinator import HelpCoordinator
from .help_bindings import register_topics, selection_context
from .ict_session import StudioProjectSession
from core.errors import Diagnostic
from uuid import uuid4


class StudioCoordinator(QObject):
    changed = Signal()
    selectionChanged = Signal()
    editRequested = Signal(str)
    createRequested = Signal()

    def __init__(self, explorer, catalog, parent=None):
        super().__init__(parent)
        self.explorer, self.catalog = explorer, catalog
        self.session: NativeProjectSession | None = None
        self.extension_store = None
        self.selection: tuple[str, str] | None = None
        self.action_parameter: str | None = None
        self._syncing = False
        self.selection_guard = None
        self.draft_dirty = lambda: False
        self.project_token = uuid4().hex
        self.problems = None
        self.registry = HelpRegistry()
        register_topics(self.registry)
        self.help = HelpCoordinator(self.registry, self)
        self.selectionChanged.connect(self._selection_help)  # V-08
        explorer.nodeSelected.connect(self.select_node)  # V-03
        explorer.nodeActivated.connect(self.activate_node)  # V-04
        explorer.tree.itemSelectionChanged.connect(self._explorer_selection)  # V-42
        catalog.actionSelected.connect(self.select_offer)  # V-05
        catalog.actionEditRequested.connect(self.request_edit)  # V-06
        catalog.catalog_tree.itemSelectionChanged.connect(self._catalog_selection)  # V-22
        explorer.search_edit.textChanged.connect(self._filtered)  # V-23
        catalog.search_edit.textChanged.connect(self._filtered)  # V-34
        catalog.type_combo.currentIndexChanged.connect(self._filtered)  # V-35
        catalog.createActionRequested.connect(self.request_create)
        catalog.new_action_button.installEventFilter(self)
        catalog.new_action_button.setEnabled(False)

    def eventFilter(self, watched, event):
        # Ohne Session darf auch ein interner Catalogrefresh Create nicht aktivieren.
        if (watched is self.catalog.new_action_button and event.type() == QEvent.Type.EnabledChange
                and watched.isEnabled() and self.session is None):
            watched.setEnabled(False)
        return super().eventFilter(watched, event)

    def open_project(self, path, *, discard=False):
        if self.draft_dirty() and not discard:
            raise NativeSessionError('Offenen Formularentwurf zuerst übernehmen oder verwerfen.')
        if self.session and self.session.dirty and not discard:
            raise NativeSessionError('Ungespeicherte Änderungen zuerst speichern oder explizit verwerfen.')
        if self.extension_store and self.extension_store.dirty and not discard:
            raise NativeSessionError('Ungespeicherte Extension zuerst speichern oder explizit verwerfen.')
        self.activate_project(self.prepare_project(path))

    @staticmethod
    def prepare_project(path):
        from studio.virtual_folders.binding import extension_path, project_identity
        from studio.virtual_folders.codec import ExtensionStore
        from studio.virtual_folders.model import Document
        candidate = StudioProjectSession.load(path)
        snapshot = candidate.snapshot()
        identity, plugin = project_identity(path), snapshot['plugin']['id']
        target = extension_path(path)
        store = (ExtensionStore.load(target, project_id=identity, plugin_id=plugin) if target.exists()
                 else ExtensionStore(Document.create(identity, plugin)))
        store.document.validate_native(snapshot, require_available=False)
        return candidate, store

    def activate_project(self, prepared):
        """Install an already validated native/extension pair; no file writes."""
        candidate, store = prepared
        self._syncing = True
        self.session = candidate
        self.extension_store = store
        self.project_token = uuid4().hex
        self.selection, self.action_parameter = None, None
        self.explorer.clear()
        self.catalog.set_project(None)
        self.catalog.set_filter("")
        self.catalog.set_type_filter(None)
        self.catalog.set_images({})
        self.catalog.set_usage_counts({})
        self.reset_context()  # V-30
        self._syncing = False
        self.refresh()

    def rename_action(self, action_id, display_name, *, base_revision):
        if self.session is None:
            raise NativeSessionError('Kein natives Projekt geöffnet.')
        if base_revision != self.session.revision:
            raise NativeRevisionConflict('Veraltete oder fremde base_revision; nichts geändert.')
        if not self._exists('action', action_id):
            raise NativeSessionError('Native Action-ID nicht mehr vorhanden; nichts geändert.')
        proposed = self.session.snapshot()
        record = next((a for a in proposed['actions'] if a['id'] == action_id), None)
        if record is None:
            raise NativeSessionError('Native Action-ID im JSON-Snapshot verloren; nichts geändert.')
        record['display_name'] = display_name
        revision = self.session.replace(proposed, base_revision=base_revision)  # V-15
        self._after_change()
        return revision

    def apply_action_edit(self, action_id, proposed_action, *, base_revision):
        from copy import deepcopy
        from studio.action_inspector.draft import ActionDraft, DraftError
        if self.session is None:
            raise NativeSessionError('Kein natives Projekt geöffnet.')
        if base_revision != self.session.revision:
            raise NativeRevisionConflict('Veraltete Formularrevision; Entwurf bleibt erhalten. Bewusst verwerfen und neu laden.')
        proposed = self.session.snapshot()
        index = next((i for i, a in enumerate(proposed['actions']) if a['id'] == action_id), None)
        if index is None:
            raise NativeSessionError('Native Action-ID nicht mehr vorhanden.')
        original = proposed['actions'][index]
        if not isinstance(proposed_action, dict) or any(proposed_action.get(k) != original[k] for k in ('id', 'sdk_type')):
            raise NativeSessionError('Action-ID und SDK-Typ sind unveränderlich.')
        try:
            draft = ActionDraft(proposed, action_id, original, base_revision)
            for key in original.keys() | proposed_action.keys():
                if key in ('id', 'sdk_type'): continue
                if key not in proposed_action: draft.remove_field(key)
                else: draft.set_field(key, proposed_action[key])
            draft.proposed_action()
        except (ValueError, TypeError) as exc:
            raise NativeSessionError(str(exc)) from exc
        # Read-only conflict check before even an in-memory commit. Save repeats it.
        if self.session.path is not None:
            self.session._check_disk()
        proposed['actions'][index] = deepcopy(proposed_action)
        revision = self.session.replace(proposed, base_revision=base_revision)
        self._after_change()
        return revision

    def request_create(self):
        if self.session is not None:
            self.createRequested.emit()

    def _lifecycle_guard(self, base_revision, project_token):
        if self.session is None:
            raise NativeSessionError('Kein natives Projekt geöffnet.')
        if project_token != self.project_token or base_revision != self.session.revision:
            raise NativeRevisionConflict('Veraltetes oder fremdes Projekt / Formularrevision; nichts geändert.')
        if self.session.path is not None:
            self.session._check_disk()

    def apply_action_create(self, proposed_action, *, base_revision, project_token):
        from studio.action_inspector.lifecycle import propose_create
        self._lifecycle_guard(base_revision, project_token)
        try:
            proposed = propose_create(self.session.snapshot(), proposed_action)
        except (ValueError, TypeError, KeyError) as exc:
            raise NativeSessionError(str(exc)) from exc
        revision = self.session.replace(proposed, base_revision=base_revision)
        # Direkte Hostauswahl des bestätigten Intents; kein Dirty-Selection-Dialog
        # während des synchronen Commitrefreshs. Die Shell bestätigt danach den Draft.
        self.selection, self.action_parameter = ('action', proposed_action['id']), None
        self._after_change()
        return revision

    def action_delete_check(self, action_id):
        from dataclasses import replace
        from studio.action_inspector.lifecycle import check_delete
        if self.session is None:
            raise NativeSessionError('Kein natives Projekt geöffnet.')
        try:
            check = check_delete(self.session.snapshot(), action_id)
            if self.extension_store:
                refs = tuple((p.folder_id, p.id) for p in self.extension_store.document.placements
                             if p.kind == 'action' and p.target.plugin_id == self.extension_store.document.plugin_id
                             and p.target.resource_id == action_id)
                if refs:
                    reason = (check.reason + '\n' if check.reason else '') + (
                        f'{len(refs)} virtuelle Folder-Referenz(en) verhindern das Löschen: ' +
                        ', '.join(f'{f} / {p}' for f, p in refs))
                    check = replace(check, references=check.references + refs, reason=reason)
            return check
        except (ValueError, TypeError, KeyError) as exc:
            raise NativeSessionError(str(exc)) from exc

    def delete_action(self, action_id, *, base_revision, project_token):
        from studio.action_inspector.lifecycle import propose_delete
        self._lifecycle_guard(base_revision, project_token)
        check = self.action_delete_check(action_id)
        if not check.allowed:
            raise NativeSessionError(check.reason)
        try:
            proposed = propose_delete(self.session.snapshot(), action_id)
        except (ValueError, TypeError, KeyError) as exc:
            raise NativeSessionError(str(exc)) from exc
        revision = self.session.replace(proposed, base_revision=base_revision)
        self.selection, self.action_parameter = None, None
        self._after_change()
        return revision

    def _after_change(self):
        if self.problems:
            self.problems.clear()
        self.refresh()

    def undo(self):
        if self.session:
            self._guard_history(self.session._undo)
            self.session.undo()  # V-16
            self._after_change()

    def redo(self):
        if self.session:
            self._guard_history(self.session._redo)
            self.session.redo()
            self._after_change()

    def _guard_history(self, history):
        """Read-only preflight of the existing owner stack; never another history.

        NativeProjectSession exposes no public peek yet. This boundary uses its
        existing stack only for validation; session.undo/redo remain sole writers.
        Already unavailable references remain repairable.
        """
        if not history or not self.extension_store:
            return
        current = {a['id'] for a in self.session.snapshot()['actions']}
        remaining = {a['id'] for a in history[-1]['actions']}
        removed = current - remaining
        refs = [p.id for p in self.extension_store.document.placements if p.kind == 'action'
                and p.target.plugin_id == self.extension_store.document.plugin_id
                and p.target.resource_id in removed]
        if refs:
            raise NativeSessionError('History würde referenzierte Actions entfernen. Zuerst virtuelle Platzierungen bewusst entfernen: ' + ', '.join(refs))

    def save(self):
        if self.session is None:
            raise NativeSessionError('Kein natives Projekt geöffnet.')
        self.session.save()
        if self.problems:
            self.problems.remove_source('save')
        self.changed.emit()

    def attach_support(self, problems, help_widget):
        self.problems = problems
        self.help.helpChanged.connect(help_widget.set_help)  # V-09
        help_widget.pinRequested.connect(self.help.set_pinned)  # V-10
        help_widget.relatedTopicRequested.connect(self.related_help)  # V-11
        problems.diagnosticSelected.connect(self.diagnostic_selected)  # V-13
        problems.diagnosticActivated.connect(self.diagnostic_activated)  # V-14
        help_widget.set_help(self.help.current())

    def reset_context(self):
        if self.problems:
            self.problems.clear()  # V-39
            self.problems.reset_filters()
        self.help.set_pinned(False)  # V-30
        self.help.set_context(None)

    def publish_diagnostics(self, source, diagnostics, *, project_token, base_revision):
        if project_token != self.project_token or base_revision != (self.session.revision if self.session else None):
            return False
        if self.problems:
            self.problems.set_source_diagnostics(source, diagnostics, revision=base_revision)  # V-12
        return True

    def report_error(self, source, error):
        # The native parser returns text, not structured entity paths.
        self.publish_diagnostics(source, [Diagnostic('NATIVE_' + source.upper(), '/', str(error))],
                                 project_token=self.project_token,
                                 base_revision=self.session.revision if self.session else None)

    def _selection_help(self):
        self.help.set_context(selection_context(self))

    def related_help(self, topic):
        try:
            registered = self.registry.get(topic) is not None
        except (ValueError, TypeError):
            registered = False
        if registered:
            self.help.request_help(HelpContext(topic))

    def diagnostic_selected(self, diagnostic):
        if diagnostic is None:
            self.help.set_context(HelpContext('problems'))
        elif self.problems and any(d is diagnostic for d in self.problems.diagnostics()):
            import re
            facts = (('Code', diagnostic.code),) if re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', diagnostic.code) else ()
            self.help.set_context(HelpContext('problems.diagnostic', facts))

    def diagnostic_activated(self, diagnostic):
        if self.problems and any(d is diagnostic for d in self.problems.diagnostics()):
            self.help.request_help(HelpContext('problems.diagnostic',
                (('Navigation', 'Keine geprüfte native Entity-Zuordnung für diesen Diagnosepfad.'),)))

    def refresh(self):
        project = self.session.native_project() if self.session else None
        self._syncing = True
        try:
            self.explorer.set_project(project, revision=self.session.revision if self.session else None)  # V-01
            self.catalog.set_project(project)  # V-02
            self.catalog.new_action_button.setEnabled(self.session is not None)
            if self.selection and not self._exists(*self.selection):
                self.selection, self.action_parameter = None, None
            elif self.selection and self.selection[0] == "folder_entry":
                self.action_parameter = self._entry_parameter(self.selection[1])
            elif self.action_parameter is not None:
                selected = self.selected_action()
                if selected is None or self.action_parameter not in {p.name for p in selected.parameters}:
                    self.action_parameter = None
            self._mirror()
        finally:
            self._syncing = False
        self.changed.emit()  # V-24
        self.selectionChanged.emit()  # V-25
        self.publish_diagnostics('native.validation', [], project_token=self.project_token,
                                 base_revision=self.session.revision if self.session else None)

    def _exists(self, kind, native_id):
        if self.session is None:
            return False
        p = self.session.native_project()
        ids = {"plugin": [p.plugin_id], "action": [a.id for a in p.actions],
               "handler": [h["id"] for h in p.handlers], "folder": [f.id for f in p.folders],
               "folder_entry": [e.id for f in p.folders for e in f.entries]}
        return native_id in ids.get(kind, ())

    def selected_action(self):
        if not self.session or not self.selection:
            return None
        kind, identity = self.selection
        p = self.session.native_project()
        if kind == "folder_entry":
            identity = next(e.action for f in p.folders for e in f.entries if e.id == identity)
        elif kind != "action":
            return None
        return next((a for a in p.actions if a.id == identity), None)

    def select_node(self, kind, native_id):
        if self._syncing or not self._exists(kind, native_id):
            return
        parameter = (self._entry_parameter(native_id) if kind == "folder_entry" else
                     self.action_parameter if self.selection == (kind, native_id) else None)
        self._select((kind, native_id), parameter)

    def _entry_parameter(self, native_id):
        return next(e.action_parameter for f in self.session.native_project().folders
                    for e in f.entries if e.id == native_id)

    def _select(self, key, parameter=None):
        if (key, parameter) == (self.selection, self.action_parameter):
            return
        if self.selection_guard and not self.selection_guard(key):
            self._syncing = True
            try:
                self._mirror()
            finally:
                self._syncing = False
            return
        self.selection, self.action_parameter = key, parameter
        self._syncing = True
        try:
            self._mirror()
        finally:
            self._syncing = False
        self.selectionChanged.emit()

    def _mirror(self):
        if self.selection:
            # An explicit cross-view selection must be visible, even after a filter.
            self.explorer.set_filter("")
            self.explorer.set_selection(*self.selection)  # V-40
        else:
            self.explorer.set_selection("", "")
        action = self.selected_action()
        if action:
            self.catalog.set_filter("")
            self.catalog.set_type_filter(None)
        self.catalog.set_selected_action(action.id if action else None, self.action_parameter)  # V-41

    def select_offer(self, offer):
        if self._syncing or not isinstance(offer, ActionOffer):
            return
        current = self.catalog.offer_for(offer.action_id, offer.action_parameter)
        if current is not None and self._exists("action", offer.action_id):
            self._select(("action", offer.action_id), offer.action_parameter)

    def _catalog_selection(self):
        if self._syncing:
            return
        key = self.catalog.selected_key()
        if key and self._exists("action", key[0]):
            self._select(("action", key[0]), key[1])
        elif key is None:
            self._select(None)

    def _explorer_selection(self):
        if self._syncing or not self.explorer.tree.user_input:
            return
        item = self.explorer.tree.currentItem()
        if item is None or item.data(0, Qt.ItemDataRole.UserRole) is None:
            self._select(None)

    def _filtered(self, *_):
        if self._syncing:
            return
        # Filters can silently hide a widget selection. Clear the host as well.
        item = self.explorer.tree.currentItem()
        catalog_item = self.catalog.catalog_tree.currentItem()
        if self.selection and (item is None or item.isHidden() or
                               (self.selected_action() and catalog_item is None)):
            self._select(None)

    def activate_node(self, kind, native_id):
        if self._exists(kind, native_id):
            self.select_node(kind, native_id)
            self.selectionChanged.emit()

    def request_edit(self, action_id):
        if self._exists("action", action_id):
            self.select_node("action", action_id)
            if self.selection == ("action", action_id):
                self.editRequested.emit(action_id)
