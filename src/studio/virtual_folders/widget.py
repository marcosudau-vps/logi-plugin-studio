"""Standalone PySide6 composer for the optional extension, no native writer."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .codec import ExtensionStore
from .model import Document, FolderError, PagingCapability, Reference
from .navigation import Navigation
from .providers import ReferenceHub

ROLE = Qt.ItemDataRole.UserRole


class FolderComposer(QWidget):
    changed = Signal()
    errorOccurred = Signal(str)
    actionEditRequested = Signal(str)
    metadataChanged = Signal()  # external adapters can emit this from other threads

    def __init__(self, document: Document, native_snapshot, parent=None, *, store=None,
                 import_as_document=False, before_commit=None):
        super().__init__(parent)
        self.setObjectName('folderComposer')
        document.validate_native(native_snapshot, require_available=not import_as_document)
        self.store = store if store is not None else ExtensionStore(document)
        self.import_as_document = import_as_document
        self.before_commit = before_commit
        self.save_target = None
        self.source_revision = None
        self.providers = ReferenceHub(native_snapshot)
        if self.providers.plugin_id != document.plugin_id:
            raise FolderError('Native Plugin-ID und Extension stimmen nicht überein.')
        self.navigation = Navigation(document)
        self._release = None
        self._refreshing = False
        self._intent = None
        self._tree_pending = None
        self._tree_timer = QTimer(self)
        self._tree_timer.setSingleShot(True)
        self._tree_timer.timeout.connect(self._apply_tree_selection)
        self.resize(1280, 820)
        layout = QVBoxLayout(self)
        heading = QLabel('Virtueller FolderComposer · optionale Extension')
        heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(heading)
        notice = QLabel('Ordner = echte Hierarchie · Link = gemeinsames Ziel · Kopie = neue IDs. '
                        'Simulation ohne Hardware. SDK-Aktionen bleiben im nativen Projekt.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        files = QHBoxLayout()
        self._button(files, 'import_button', 'Import …', self.import_file)
        self._button(files, 'export_button', 'Ordner als neue Datei exportieren …', self.export_file)
        self._button(files, 'save_button', 'Ordner speichern', self.save_file)
        self._button(files, 'undo_button', 'Rückgängig (Ordner)', lambda: self.history(False))
        self._button(files, 'redo_button', 'Wiederholen (Ordner)', lambda: self.history(True))
        layout.addLayout(files)
        self.file_status = QLabel()
        self.file_status.setTextFormat(Qt.TextFormat.PlainText)
        self.file_status.setWordWrap(True)
        layout.addWidget(self.file_status)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel('Echte Ordnerhierarchie · Links werden nicht rekursiv aufgefaltet'))
        self.tree = QTreeWidget()
        self.tree.setObjectName('folderHierarchy')
        self.tree.setHeaderLabels(['Ordner / Link'])
        self.tree.currentItemChanged.connect(self._tree_selected)
        left_layout.addWidget(self.tree)
        grid = QGridLayout()
        for i, (attribute, text, callback) in enumerate((
            ('new_button', 'Neuer Unterordner', self.new_folder),
            ('root_button', 'Neuer Autoren-Root', lambda: self.new_folder(root=True)),
            ('link_button', 'Link erstellen …', self.new_link),
            ('external_link_button', 'Externer Link …', self.external_link),
            ('copy_button', 'Ordner kopieren …', self.copy_folder),
            ('move_button', 'Ordner verschieben …', self.move_folder),
            ('rename_button', 'Ordner umbenennen …', self.rename_folder),
            ('delete_button', 'Ordner löschen', self.delete_folder),
            ('set_root_button', 'Als Plugin-Root', self.set_root),
        )):
            self._button(grid, attribute, text, callback, i // 2, i % 2)
        left_layout.addLayout(grid)
        splitter.addWidget(left)
        right = QWidget()
        body = QVBoxLayout(right)
        self.folder_label = QLabel()
        self.folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.folder_label.setWordWrap(True)
        body.addWidget(self.folder_label)
        nav = QHBoxLayout()
        self._button(nav, 'back_button', '← Back (tatsächlicher Weg)', self.back)
        self._button(nav, 'home_button', 'Plugin-Root öffnen', lambda: self.select_folder(self.document.root_id))
        body.addLayout(nav)
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        body.addWidget(self.path_label)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName('pageMode')
        for label, mode in (('Single Page (alle Einträge zusammenführen)', 'single'),
                            ('Auto-Paging (explizite Capability)', 'auto'), ('Manual Pages', 'manual')):
            self.mode_combo.addItem(label, mode)
        self.mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode_combo.setMinimumContentsLength(18)
        self.mode_combo.currentIndexChanged.connect(self.change_mode)
        form.addRow('Seitenmodus', self.mode_combo)
        self.capability_label = QLabel()
        self.capability_label.setWordWrap(True)
        form.addRow('Capability', self.capability_label)
        self.page_combo = QComboBox()
        self.page_combo.setObjectName('currentPage')
        self.page_combo.currentIndexChanged.connect(self._page_selected)
        form.addRow('Aktuelle Seite', self.page_combo)
        body.addLayout(form)
        page_buttons = QGridLayout()
        for i, (attribute, text, callback) in enumerate((
            ('previous_button', '← Vorige Seite', lambda: self.page_delta(-1)),
            ('next_button', 'Nächste Seite →', lambda: self.page_delta(1)),
            ('add_page_button', '+ Seite', self.add_page),
            ('delete_page_button', 'Seite löschen', self.delete_page),
            ('page_left_button', 'Seite früher', lambda: self.reorder_page(-1)),
            ('page_right_button', 'Seite später', lambda: self.reorder_page(1)),
            ('rename_page_button', 'Seite benennen …', self.rename_page),
        )):
            self._button(page_buttons, attribute, text, callback, i // 4, i % 4)
        body.addLayout(page_buttons)
        self.empty_label = QLabel('Leere Seite. Einen Ordner, Link oder eine vorhandene SDK-Aktion hinzufügen.')
        self.empty_label.setWordWrap(True)
        body.addWidget(self.empty_label)
        self.entries = QListWidget()
        self.entries.setObjectName('pageEntries')
        self.entries.itemDoubleClicked.connect(lambda _item: self.activate())
        body.addWidget(self.entries, 1)
        # AP-POLISH-001: two rows of three keep the window usable on 1366/1536 px wide screens.
        row = QGridLayout()
        self._button(row, 'open_button', 'Öffnen / simulieren', self.activate, 0, 0)
        self._button(row, 'edit_action_button', 'Im Aktionsinspektor öffnen', self.edit_action, 0, 1)
        self.edit_action_button.setVisible(import_as_document)
        self._button(row, 'remove_button', 'Platzierung entfernen', self.remove_entry, 0, 2)
        self._button(row, 'up_button', '↑ Eintrag', lambda: self.reorder_entry(-1), 1, 0)
        self._button(row, 'down_button', '↓ Eintrag', lambda: self.reorder_entry(1), 1, 1)
        self._button(row, 'move_entry_button', 'Eintrag verschieben …', self.move_entry, 1, 2)
        body.addLayout(row)
        actions = QGroupBox('Vorhandene native SDK-Aktion referenzieren')
        action_layout = QVBoxLayout(actions)
        self.action_combo = QComboBox()
        self.action_combo.setObjectName('nativeActionSource')
        self.action_combo.setMinimumWidth(180)
        self.action_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        action_layout.addWidget(self.action_combo)
        action_row = QHBoxLayout()
        self._button(action_row, 'add_action_button', 'Aktion platzieren', self.add_action)
        self._button(action_row, 'external_action_button', 'Externe Aktionsreferenz …', self.external_action)
        action_layout.addLayout(action_row)
        body.addWidget(actions)
        splitter.addWidget(right)
        splitter.setSizes([390, 850])
        self.status = QLabel('')
        self.status.setObjectName('folderStatus')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.metadataChanged.connect(self.refresh)
        self.set_native_snapshot(native_snapshot)

    @property
    def document(self):
        return self.store.document

    def _button(self, layout, attribute, text, callback, *position):
        button = QPushButton(text)
        button.setObjectName(attribute)
        button.clicked.connect(lambda checked=False: self._run(callback))
        layout.addWidget(button, *position)
        setattr(self, attribute, button)

    def _run(self, callback):
        previous = self._intent
        self._intent = (self.store, self.document, self._native_snapshot, self.source_revision, self.store.revision)
        try:
            self.status.clear()
            return callback()
        except (FolderError, OSError) as exc:
            self.status.setText('Fehler: ' + str(exc))
            self.errorOccurred.emit(str(exc))
            return False
        finally:
            self._intent = previous

    def _commit(self, result, select=None):
        if self._intent and (self.store is not self._intent[0] or self.document is not self._intent[1]
                             or self._native_snapshot is not self._intent[2]
                             or self.source_revision != self._intent[3]
                             or self.store.revision != self._intent[4]):
            raise FolderError('Extension während der Eingabe geändert; nichts übernommen. Bitte erneut versuchen.')
        if self.before_commit:
            self.before_commit()
        if isinstance(result, tuple):
            result, identity = result
        self.store.commit(result)
        self.navigation.update(self.document)
        if select:
            self.navigation.select(select)
        self.refresh()
        self.changed.emit()

    def _watch_references(self):
        if self._release:
            self._release()
        references = frozenset(p.target for p in self.document.placements if p.kind == 'action' or p.target.plugin_id != self.document.plugin_id)
        # The initial snapshot is already read synchronously by refresh. Subsequent
        # pushes only queue a Qt signal. Keep subscriptions independent of visibility.
        first = True
        def updated(_values):
            nonlocal first
            if first:
                first = False
            else:
                self.metadataChanged.emit()
        self._release = self.providers.subscribe(references, updated)

    def dispose(self):
        self._tree_timer.stop()
        if self._release:
            self._release()
            self._release = None

    def refresh(self):
        self._refreshing = True
        try:
            d, n = self.document, self.navigation
            selected = self.entries.currentItem()
            selected_id = selected.data(ROLE) if selected else None
            self.tree.clear()
            items = {}
            # Build every node before attachment; no recursive link traversal.
            for f in d.folders:
                item = QTreeWidgetItem([f'Ordner · {f.name}' + (' [Plugin-Root]' if f.id == d.root_id else '')])
                item.setData(0, ROLE, ('folder', f.id))
                item.setToolTip(0, f'Node-ID: {f.id}\nOwner: {f.owner}\nParent: {f.parent_id or "Autoren-Root"}')
                items[f.id] = item
            for f in d.folders:
                if f.parent_id:
                    items[f.parent_id].addChild(items[f.id])
                else:
                    self.tree.addTopLevelItem(items[f.id])
            for p in d.placements:
                if p.kind == 'link':
                    item = QTreeWidgetItem([self.entry_text(p)])
                    item.setData(0, ROLE, ('link', p.id))
                    item.setToolTip(0, p.target.key + '\nPlacement-ID: ' + p.id)
                    items[p.folder_id].addChild(item)
            self.tree.expandAll()
            self.tree.setCurrentItem(items[n.folder_id])
            f = d.folder(n.folder_id)
            self.folder_label.setText(f'Ordner: {f.name}\nID: {f.id} · Owner: {f.owner}')
            self.path_label.setText('Weg: ' + (' → '.join(d.folder(s.origin_id).name for s in n.stack) + ' → ' if n.stack else '') + f.name + f' | {len(n.stack)} Schritte')
            self.path_label.setToolTip('\n'.join(s.placement_id for s in n.stack))
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(f.mode))
            self.capability_label.setText(f'{f.capability.slots} Slots · {f.capability.source}' if f.capability else 'Keine Slotannahme / keine Hardwarebindung')
            self.page_combo.clear()
            for i, page in enumerate(f.pages):
                self.page_combo.addItem(f'Seite {i+1}: {page.name}', page.id)
            self.page_combo.setCurrentIndex(d.page_index(f.id, n.page_id))
            self.entries.clear()
            for p in d.entries(f.id, n.page_id):
                item = QListWidgetItem(self.entry_text(p))
                item.setData(ROLE, p.id)
                item.setToolTip(f'Placement-ID: {p.id}\nZiel: {p.target.key}\nSeite: {p.page_id}')
                self.entries.addItem(item)
                if p.id == selected_id:
                    self.entries.setCurrentItem(item)
            if not self.entries.count():
                self.entries.setToolTip('Leere Seite. Ordner, Link oder vorhandene SDK-Aktion hinzufügen.')
            self.empty_label.setVisible(not self.entries.count())
            self.action_combo.clear()
            for value in self.providers.actions():
                suffix = '' if value.available else ' · nicht verfügbar'
                self.action_combo.addItem(f'{value.name} · {value.sdk_type} · {value.reference.key}{suffix}', (value.reference, None))
            # Parameters are read directly from the current native snapshot only.
            for ref, name, parameter, sdk_type in getattr(self, '_parameter_choices', ()):
                self.action_combo.addItem(f'{name} / {parameter} · {sdk_type}', (ref, parameter))
            self.back_button.setEnabled(bool(n.stack))
            page_index = d.page_index(f.id, n.page_id)
            self.previous_button.setEnabled(page_index > 0)
            self.next_button.setEnabled(page_index + 1 < len(f.pages))
            self.add_page_button.setEnabled(f.mode == 'manual')
            self.delete_page_button.setEnabled(f.mode == 'manual' and len(f.pages) > 1)
            self.page_left_button.setEnabled(f.mode == 'manual' and page_index > 0)
            self.page_right_button.setEnabled(f.mode == 'manual' and page_index + 1 < len(f.pages))
            self.add_action_button.setEnabled(self.action_combo.count() > 0)
            self.save_button.setEnabled(self.store.path is not None or self.save_target is not None)
            self.undo_button.setEnabled(self.store.can_undo)
            self.redo_button.setEnabled(self.store.can_redo)
            self.file_status.setText(('Ungespeicherte Extensionänderungen' if self.store.dirty else 'Extensionstand unverändert') + ' | ' + str(self.store.path or 'nur im Speicher; Export explizit'))
            self._watch_references()
        finally:
            self._refreshing = False

    def set_native_snapshot(self, snapshot):
        from copy import deepcopy
        self.providers.update_native(snapshot)
        self._native_snapshot = deepcopy(snapshot)
        self._parameter_choices = tuple((Reference(self.document.plugin_id, a['id']), a['display_name'], p['name'], a['sdk_type'])
                                        for a in snapshot['actions'] for p in a.get('parameters', []))
        self.refresh()

    def entry_text(self, p):
        if p.kind != 'action' and p.target.plugin_id == self.document.plugin_id:
            label = self.document.folder(p.target.resource_id).name
            available = True
        else:
            value = self.providers.resolve(p.target, 'action' if p.kind == 'action' else 'folder')
            label, available = value.name, value.available
        kind = {'contains': 'Ordner', 'link': 'Link ↗', 'action': 'Aktion'}[p.kind]
        parameter = f' [Parameter: {p.action_parameter}]' if p.action_parameter is not None else ''
        return f'{p.position+1}. {kind} · {label}{parameter}' + ('' if available else ' · nicht verfügbar')

    def select_folder(self, identity):
        self.navigation.select(identity)
        self.refresh()

    def _tree_selected(self, current, _previous):
        if not current or self._refreshing:
            return
        # Do not delete QTreeWidgetItems while Qt is still handling their click.
        # Only stable identities survive across the queued boundary.
        self._tree_pending = current.data(0, ROLE)
        self._tree_timer.start(0)

    def _apply_tree_selection(self):
        kind, identity = self._tree_pending
        self._run(lambda: self._select_tree_identity(kind, identity))

    def _select_tree_identity(self, kind, identity):
        if kind == 'folder':
            self.select_folder(identity)
        else:
            # Selecting a link selects its placement, never silently follows it.
            p = self.document.placement(identity)
            self.navigation.select(p.folder_id)
            self.navigation.page(p.page_id)
            self.refresh()
            for i in range(self.entries.count()):
                if self.entries.item(i).data(ROLE) == p.id:
                    self.entries.setCurrentRow(i)

    def _name(self, prompt, initial=''):
        name, ok = QInputDialog.getText(self, prompt, 'Anzeigename (Identität bleibt stabil)', text=initial)
        return name if ok else None

    def _choose_folder(self, prompt, *, allow_root=False):
        choices = [('Autoren-Root (kein Parent)', None)] if allow_root else []
        choices.extend((f'{f.name} · {f.id}', f.id) for f in self.document.folders)
        label, ok = QInputDialog.getItem(self, prompt, 'Zielordner', [x[0] for x in choices], 0, False)
        return ok, next((identity for text, identity in choices if text == label), None)

    def new_folder(self, root=False):
        name = self._name('Neuer echter Ordner')
        if name is not None:
            result, identity = self.document.create_folder(name, None if root else self.navigation.folder_id,
                                                          None if root else self.navigation.page_id)
            self._commit(result, identity)

    def new_link(self):
        ok, target = self._choose_folder('Verknüpfung erstellen (Ziel bleibt unverändert)')
        if ok:
            self._commit(self.document.add_link(self.navigation.folder_id, Reference(self.document.plugin_id, target), self.navigation.page_id))

    def _external_reference(self):
        text, ok = QInputDialog.getText(self, 'Externe Referenz', 'Namespaced ID: plugin.id::resource.id (offline bleibt sichtbar)')
        if not ok:
            return None
        ref = Reference.parse(text)
        if ref.plugin_id == self.document.plugin_id:
            raise FolderError('Für lokale Ziele die vorhandene Auswahl verwenden.')
        return ref

    def external_link(self):
        ref = self._external_reference()
        if ref:
            self._commit(self.document.add_link(self.navigation.folder_id, ref, self.navigation.page_id))

    def external_action(self):
        ref = self._external_reference()
        if ref:
            self._commit(self.document.add_action(self.navigation.folder_id, ref, self.navigation.page_id))

    def copy_folder(self):
        ok, target = self._choose_folder('Echten Teilbaum kopieren (Links behalten ihre Ziele)', allow_root=True)
        if ok:
            result, identity = self.document.copy_folder(self.navigation.folder_id, target)
            self._commit(result, identity)

    def move_folder(self):
        ok, target = self._choose_folder('Echten Parent ändern (Node-ID und Links bleiben)', allow_root=True)
        if ok:
            self._commit(self.document.move_folder(self.navigation.folder_id, target))

    def rename_folder(self):
        name = self._name('Ordner umbenennen', self.document.folder(self.navigation.folder_id).name)
        if name is not None:
            self._commit(self.document.rename_folder(self.navigation.folder_id, name))

    def delete_folder(self):
        f = self.document.folder(self.navigation.folder_id)
        # Validate before a modal confirmation; no recursive resource deletion.
        candidate = self.document.delete_folder(f.id)
        if QMessageBox.question(self, 'Echten Ordner löschen', f'{f.name}\n{f.id}\nNur diesen Ordner und seine Platzierungen löschen? SDK-Aktionen und Linkziele bleiben erhalten.',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self._commit(candidate, f.parent_id or candidate.root_id)

    def set_root(self):
        self._commit(self.document.set_root(self.navigation.folder_id))

    def selected_entry(self):
        item = self.entries.currentItem()
        if item is None:
            raise FolderError('Zuerst einen Eintrag auswählen.')
        return self.document.placement(item.data(ROLE))

    def activate(self):
        p = self.selected_entry()
        if p.kind == 'action':
            value = self.providers.resolve(p.target)
            self.status.setText(f'Simulation: {p.target.key} · Parameter {p.action_parameter!r}' +
                                (' · keine Ausführung in dieser Vorschau' if value.available else ' · nicht verfügbar; Referenz bleibt erhalten'))
        else:
            self.navigation.open(p.id)
            self.refresh()

    def edit_action(self):
        p = self.selected_entry()
        if p.kind != 'action' or p.target.plugin_id != self.document.plugin_id:
            raise FolderError('Nur lokale native Actiondefinitionen im Inspektor öffnen.')
        if not self.providers.resolve(p.target).available:
            raise FolderError('Aktion nicht verfügbar; Platzierung bleibt bis zur bewussten Entfernung erhalten.')
        self.actionEditRequested.emit(p.target.resource_id)

    def back(self):
        self.navigation.back()
        self.refresh()

    def add_action(self):
        value = self.action_combo.currentData()
        if value:
            self._commit(self.document.add_action(self.navigation.folder_id, value[0], self.navigation.page_id, value[1]))

    def remove_entry(self):
        self._commit(self.document.remove_placement(self.selected_entry().id))

    def reorder_entry(self, delta):
        p = self.selected_entry()
        self._commit(self.document.reorder_placement(p.id, p.position + delta))

    def move_entry(self):
        p = self.selected_entry()
        ok, target = self._choose_folder('Platzierung verschieben')
        if not ok:
            return
        f = self.document.folder(target)
        labels = [f'{page.name} · {page.id}' for page in f.pages]
        label, ok = QInputDialog.getItem(self, 'Zielseite', 'Seite', labels, 0, False)
        if ok:
            page_id = f.pages[labels.index(label)].id
            count = len([x for x in self.document.entries(f.id, page_id) if x.id != p.id])
            self._commit(self.document.move_placement(p.id, f.id, page_id, count))

    def change_mode(self, _index):
        if self._refreshing:
            return
        def apply():
            mode = self.mode_combo.currentData()
            cap = None
            if mode == 'auto':
                slots, ok = QInputDialog.getInt(self, 'Explizite Simulations-Capability',
                                               'Verfügbare Slots je Seite (keine Hardwarebehauptung)', 1, 1, 1000000)
                if not ok:
                    return
                cap = PagingCapability(slots, 'Explizite Benutzereingabe für Simulation')
            self._commit(self.document.set_mode(self.navigation.folder_id, mode, cap))
        self._run(apply)
        self.refresh()

    def _page_selected(self, _index):
        if not self._refreshing and self.page_combo.currentData():
            self.navigation.page(self.page_combo.currentData())
            self.refresh()

    def page_delta(self, delta):
        self.navigation.next_page(delta)
        self.refresh()

    def add_page(self):
        name = self._name('Neue Manual-Seite')
        if name is not None:
            result, page_id = self.document.add_page(self.navigation.folder_id, name)
            self._commit(result)
            self.navigation.page(page_id)
            self.refresh()

    def rename_page(self):
        name = self._name('Seite benennen')
        if name is not None:
            self._commit(self.document.rename_page(self.navigation.folder_id, self.navigation.page_id, name))

    def delete_page(self):
        self._commit(self.document.remove_page(self.navigation.folder_id, self.navigation.page_id))

    def reorder_page(self, delta):
        n = self.navigation
        self._commit(self.document.reorder_page(n.folder_id, n.page_id, self.document.page_index(n.folder_id, n.page_id)+delta))

    def history(self, redo):
        if self.before_commit:
            self.before_commit()
        self.store.redo() if redo else self.store.undo()
        self.navigation.update(self.document)
        self.refresh()
        self.changed.emit()

    def confirm_discard(self):
        if not self.store.dirty:
            return True
        answer = QMessageBox.question(self, 'Ungespeicherte Extension', 'Extension vor dem Fortfahren speichern?',
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return bool(self._run(self.save_file if self.store.path or self.save_target else self.export_file))
        return answer == QMessageBox.StandardButton.Discard

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Extension importieren', '', 'Virtual Folders (*.vfolders.json)', options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            # Decode before asking to discard: invalid input cannot lose the draft.
            candidate = ExtensionStore.load(path, project_id=self.document.project_id, plugin_id=self.document.plugin_id)
            candidate.document.validate_native(self._native_snapshot, require_available=not self.import_as_document)
            if self.confirm_discard():
                if self.import_as_document:
                    self._commit(candidate.document, candidate.document.root_id)
                else:
                    self.store = candidate
                    self.navigation = Navigation(candidate.document)
                    self.refresh()
                    self.changed.emit()

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(self, 'In NEUE Extension exportieren', 'folders.vfolders.json',
                                             'Virtual Folders (*.vfolders.json)', options=QFileDialog.Option.DontUseNativeDialog | QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return False
        if self.import_as_document:
            # A copy must not redirect the integrated host's sidecar writer.
            ExtensionStore(self.document).export(path)
        else:
            self.store.export(path)
        self.refresh()
        return True

    def save_file(self):
        if self.store.path is None and self.save_target is not None:
            self.store.export(self.save_target)
        else:
            self.store.save()
        self.refresh()
        self.changed.emit()
        return True
