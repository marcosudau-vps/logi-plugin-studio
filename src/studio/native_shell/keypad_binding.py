"""Project the current native session and composer into the existing Keypad view."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from adapters.logitech.errors import GenerationError
from adapters.logitech.product import read_native_resource
from studio.keypad_contract import EditRequest, KeypadFrame, NavigationCapability, SlotAddress, SlotData
from studio.keypad_preview.skin import ASSET_KEY_RECTS, find_logikeypad_directory, load_logikeypad_skin
from studio.keypad_preview.widget import KeypadPreviewWidget
from studio.virtual_folders.model import FolderError, Reference
from symbol_designer.ict import IconTemplate
from symbol_designer.render import decode, paint_template


DEVICE = "Loupedeck70"
# Observed LCD geometry from the accepted device skin. Never a claim about
# the controls or slot order reserved/assigned by the Options+ SDK host.
CELLS = tuple(ASSET_KEY_RECTS)
VIRTUAL = "virtual"


def _tile(root, project, action):
    """Render authored assets only; runtime/user/global overrides stay in the SDK."""
    state = action.states[0] if action.states else None
    image = state.image if state else None
    template = action.icon_template or project.default_icon_template
    if image or (action.icon and not template):
        data = read_native_resource(root, image or action.icon, "icon")
        decoded = decode(data)
        if decoded is None:
            raise ValueError("Bild kann in der Autorenvorschau nicht dargestellt werden.")
        if decoded.raster is not None:
            return decoded.raster
        tile = QImage(116, 116, QImage.Format.Format_ARGB32_Premultiplied)
        tile.fill(Qt.GlobalColor.transparent)
        with QPainter(tile) as painter:
            decoded.svg.render(painter, QRectF(tile.rect()))
        return tile
    if template:
        data = read_native_resource(root, template, "template")
        visual = IconTemplate.from_bytes(data)
        tile = QImage(116, 116, QImage.Format.Format_ARGB32_Premultiplied)
        tile.fill(Qt.GlobalColor.transparent)
        with QPainter(tile) as painter:
            paint_template(painter, visual, 116)
        return tile
    return None


def _action_slot(index, entry_id, position, parameter, action, project, root, *, reason=None):
    variant = next((p for p in action.parameters if p.name == parameter), None)
    state = action.states[0] if action.states else None
    label = state.display_name if state else variant.display_name if variant else action.display_name
    tooltip = f"{action.display_name}\nAction-ID: {action.id}\nSDK-actionParameter: {parameter!r}"
    if state:
        tooltip += "\nSDK-State 0 (Autorenansicht)"
    if reason:
        return SlotData(index, "unavailable", label=label, tooltip=tooltip + "\n" + reason)
    try:
        tile = _tile(root, project, action)
    except (GenerationError, OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        tile = None
        tooltip += "\nAsset nicht darstellbar: " + str(exc)
    return SlotData(index, "placement", entry_id, action.id, parameter, label, tile,
                    logical_position=position, tooltip=tooltip)


def _unavailable_reason(action):
    if action.sdk_type == "PluginDynamicAdjustment":
        return "SDK-Encoder-Action; das MX Creative Keypad hat hier keinen Encoder."
    if action.sdk_type == "ActionEditorCommand":
        return "ActionEditorCommand ist im SDK-Folder nicht unterstützt. Im Katalog verfügbar."
    return None


class NativeKeypadBinding(QObject):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.host = shell.coordinator
        self.panel = QWidget(shell)
        self.panel.setObjectName("nativeKeypadPanel")
        self.widget = KeypadPreviewWidget(self.panel)
        self.widget.setObjectName("nativeKeypadPreview")
        skin, self._skin_warning = load_logikeypad_skin(
            find_logikeypad_directory(Path(__file__).resolve().parents[3]))
        self.widget.set_skin(skin)
        layout = QVBoxLayout(self.panel)
        controls = QHBoxLayout()
        self.source = QComboBox(self.panel)
        self.source.setAccessibleName("Quelle der Tastenvorschau")
        self.back = QPushButton("Zurück im Ordner", self.panel)
        self.edit = QCheckBox("Bearbeiten", self.panel)
        self.edit.setToolTip("ICT bearbeiten; virtuelle Actions nur an freien Folgeplätzen ablegen.")
        for control in (self.source, self.back, self.edit):
            controls.addWidget(control, int(control is self.source))
        layout.addLayout(controls)
        self.notice = QLabel("Ein natives Projekt öffnen, um den Tastenentwurf anzuzeigen.")
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.notice)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.hide()
        layout.addWidget(self.message)
        layout.addWidget(self.widget, 1)
        self.source.setEnabled(False)
        self.edit.setEnabled(False)
        self.back.setEnabled(False)
        self._token = None
        self._folder_options = ()
        self._revision_key = None
        self._paint_key = None
        self._page = 0
        self._virtual_page = None
        self._selecting = False
        self._pages = ()
        self.source.currentIndexChanged.connect(self._source_changed)
        self.back.clicked.connect(self._back)
        self.edit.toggled.connect(lambda enabled: self.widget.set_mode("edit" if enabled else "preview"))
        self.widget.slotSelected.connect(self.select_slot)
        self.widget.pageRequested.connect(self.request_page)
        self.widget.pageCreateRequested.connect(self.create_page)
        self.widget.symbolEditRequested.connect(self.edit_symbol)
        self.widget.editRequested.connect(self.apply_edit)
        self.widget.undoRequested.connect(lambda: self.history(False))
        self.widget.redoRequested.connect(lambda: self.history(True))
        self.host.selectionChanged.connect(self.selection_changed)

    @property
    def virtual(self):
        return self.source.currentData() == VIRTUAL

    def _source_changed(self, *_):
        self._page = 0
        self._virtual_page = None
        self._say("")
        self.refresh()
        self.shell._refresh_status()

    def _say(self, text):
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def refresh(self, *, force=False):
        session, composer = self.host.session, self.shell.composer
        if session is None or composer is None:
            return
        project = session.native_project()
        changed_project = self._token != self.host.project_token
        if changed_project or self._folder_options != tuple((f.id, f.display_name) for f in project.folders):
            self._folder_options = tuple((f.id, f.display_name) for f in project.folders)
            choice = self.source.currentData()
            if changed_project:
                self._token = self.host.project_token
                self._page, self._virtual_page = 0, None
                self.edit.setChecked(False)
                self._say("")
                choice = (VIRTUAL if composer.store.path is not None or not project.folders
                          else "native:" + project.folders[0].id)
            with QSignalBlocker(self.source):
                self.source.clear()
                for folder in project.folders:
                    self.source.addItem(f"SDK-Folder: {folder.display_name} [{folder.id}]", "native:" + folder.id)
                self.source.addItem("Virtuelle Ordner (Autorenmodell)", VIRTUAL)
                index = self.source.findData(choice)
                self.source.setCurrentIndex(max(0, index))
            self.source.setEnabled(True)
        source = self.source.currentData()
        if self.virtual:
            document, nav = composer.document, composer.navigation
            folder = document.folder(nav.folder_id)
            view_id = "virtual:" + folder.id
            virtual_page = (folder.id, nav.page_id)
            if virtual_page != self._virtual_page:
                self._virtual_page = virtual_page
                self._page = None
            area = "None"  # Composer has no device routing; no SDK area is claimed.
            store_key = (composer.store.revision, composer.store.path)
        else:
            folder = next(f for f in project.folders if "native:" + f.id == source)
            view_id = source
            area = folder.device_navigation.get(DEVICE, folder.navigation)
            store_key = None
        revision_key = (self._token, view_id, session.revision, store_key)
        if force or revision_key != self._revision_key:
            self._revision_key = revision_key
            self._frame_revision = uuid4().hex
            if self.virtual:
                self._pages = tuple((page.id, offset, entries[offset:offset + len(CELLS)], len(entries))
                    for page in folder.pages
                    for entries in (document.entries(folder.id, page.id),)
                    for offset in range(0, max(1, len(entries)), len(CELLS)))
            else:
                entries = tuple(sorted(folder.entries, key=lambda entry: entry.position))
                self._pages = tuple((None, offset, entries[offset:offset + len(CELLS)], len(entries))
                                    for offset in range(0, max(1, len(entries)), len(CELLS)))
        if self.virtual and (self._page is None or self._page >= len(self._pages)
                             or self._pages[self._page][0] != nav.page_id):
            self._page = next(i for i, page in enumerate(self._pages) if page[0] == nav.page_id)
        self._page = min(self._page, len(self._pages) - 1)
        page_id, offset, entries, total = self._pages[self._page]
        can_place = self.virtual and folder.mode != "auto" and total <= len(CELLS)
        paint_key = (self._frame_revision, self._page)
        if self._paint_key != paint_key:
            self._paint_key = paint_key
            actions = {a.id: a for a in project.actions}
            slots = []
            for row, index in enumerate(CELLS):
                if row >= len(entries):
                    available = can_place and row == len(entries)
                    slots.append(SlotData(index, "empty", editable=available,
                        tooltip="Nächster freier Platz in der Autorenreihenfolge" if available else
                                "Keine Einzelbelegung: Die Autorenreihenfolge wird lückenlos gespeichert."))
                    continue
                entry = entries[row]
                if self.virtual:
                    if entry.target.plugin_id != document.plugin_id:
                        slots.append(SlotData(index, "unavailable", label=entry.target.key,
                                              tooltip="Externe Referenz; im Studio offline."))
                        continue
                    if entry.kind != "action":
                        target = document.folder(entry.target.resource_id)
                        label = ("Link · " if entry.kind == "link" else "Ordner · ") + target.name
                        # This is an authored folder navigation command, not a
                        # reserved SDK hardware position (navigation_slots).
                        slots.append(SlotData(index, "sdk_navigation", label=label, tooltip=label))
                        continue
                    action = actions.get(entry.target.resource_id)
                else:
                    action = actions[entry.action]
                if action is None:
                    slots.append(SlotData(index, "unavailable", label=entry.target.resource_id,
                                          tooltip="Lokale Action fehlt; Referenz im FolderComposer reparieren."))
                    continue
                reason = _unavailable_reason(action)
                if entry.action_parameter is not None and entry.action_parameter not in {p.name for p in action.parameters}:
                    reason = "SDK-actionParameter fehlt in der aktuellen Actiondefinition."
                slots.append(_action_slot(index, entry.id, entry.position, entry.action_parameter, action,
                                          project, session.path.parent, reason=reason))
            capability = NavigationCapability(DEVICE, area, CELLS)
            self.widget.set_frame(KeypadFrame(self._token, view_id, self._frame_revision, capability,
                                               tuple(slots), self._page, len(self._pages)))
        self.widget.set_edit_allowed(True)
        self.widget.set_placement_edit_allowed(can_place)
        self.widget.set_page_creation_allowed(self.virtual and folder.mode == "manual")
        self.edit.setEnabled(True)
        self.back.setEnabled(self.virtual and bool(composer.navigation.stack))
        owner = composer.store if self.virtual else session
        self.widget.set_history_available(owner.can_undo, owner.can_redo)
        context = (f"Virtuell: {folder.name} / {next(p.name for p in folder.pages if p.id == page_id)}"
                   + (" · nur im Studio (kein gespeichertes Sidecar)" if composer.store.path is None else "")
                   if self.virtual else f"SDK-Folder: {folder.display_name} · SDK-Navigationsbereich: {area}")
        hint = ("Virtuelle Aktionen am nächsten freien Platz ablegen; Reihenfolge bleibt lückenlos."
                if can_place else "Platzierungen hier nur anzeigen; ICT kann bearbeitet werden.")
        overflow = f" · Ausschnitt {offset + 1}–{offset + len(entries)} von {total}" if total > len(CELLS) else ""
        notice = (f"MX Creative Keypad ({DEVICE}) · Autorenvorschau, keine Options+-Tastenbelegung.\n"
                  f"{context}{overflow}\n{hint}")
        if self._skin_warning:
            notice += " Neutrale Darstellung (Gerätegrafik fehlt oder ist ungültig)."
        if self.virtual and not project.folders:
            notice += " Ein SDK-Build mit Platzierungen benötigt einen nativen DynamicFolder."
        if self.notice.text() != notice:
            self.notice.setText(notice)
        self.mirror_selection()

    def selection_changed(self):
        key = self.host.selection
        if not self._selecting and key and key[0] in ("folder", "folder_entry"):
            project = self.host.session.native_project()
            folder = next((f for f in project.folders if
                           (f.id == key[1] if key[0] == "folder" else any(e.id == key[1] for e in f.entries))), None)
            if folder:
                self.source.setCurrentIndex(self.source.findData("native:" + folder.id))
                if key[0] == "folder_entry":
                    page = next((i for i, p in enumerate(self._pages) if any(e.id == key[1] for e in p[2])), 0)
                    if page != self._page:
                        self.request_page(page)
        self.mirror_selection()

    def mirror_selection(self):
        frame = self.widget.frame()
        if frame is None:
            return
        action = self.host.selected_action()
        slots = []
        if action:
            slots = [slot for slot in frame.slots if slot.action_id == action.id
                     and slot.action_parameter == self.host.action_parameter]
            if not self.virtual and self.host.selection[0] == "folder_entry":
                slots = [slot for slot in slots if slot.placement_id == self.host.selection[1]]
        previous = self.widget.selection()
        slot = next((s for s in slots if previous and s.placement_id == previous.placement_id),
                    slots[0] if slots else None)
        self.widget.set_selection(SlotAddress(frame.view_id, frame.page_index, slot.physical_index,
                                             slot.placement_id) if slot else None)

    def _visible_slot(self, address):
        frame = self.widget.frame()
        if (not isinstance(address, SlotAddress) or not frame or frame.context_id != self.host.project_token
                or address.view_id != frame.view_id or address.page_index != frame.page_index):
            return None
        return next((s for s in frame.slots if (s.physical_index, s.placement_id)
                     == (address.physical_index, address.placement_id)), None)

    def select_slot(self, address):
        slot = self._visible_slot(address)
        if slot is None:
            return
        if slot.role == "sdk_navigation" and self.virtual:
            composer = self.shell.composer
            entry = self._pages[self._page][2][CELLS.index(address.physical_index)]
            composer._run(lambda: composer.navigation.open(entry.id))
            composer.refresh()
            self.refresh()
            return
        self._selecting = True
        try:
            if slot.role == "placement":
                key = ("action", slot.action_id) if self.virtual else ("folder_entry", slot.placement_id)
                self.host._select(key, slot.action_parameter)
            elif slot.role == "empty":
                self.host._select(None)
        finally:
            self._selecting = False
        self.mirror_selection()

    def request_page(self, index):
        if type(index) is not int or not 0 <= index < len(self._pages):
            return
        if self.virtual:
            composer = self.shell.composer
            composer.navigation.page(self._pages[index][0])
            composer.refresh()
            self._virtual_page = (composer.navigation.folder_id, composer.navigation.page_id)
        self._page = index
        self._say("")
        self.refresh()

    def _back(self):
        if self.virtual:
            self.shell.composer.back()
            self.refresh()

    def create_page(self):
        if self.virtual and self.widget.editing_active():
            composer = self.shell.composer
            if composer.document.folder(composer.navigation.folder_id).mode == "manual":
                composer._run(composer.add_page)
                self.refresh()

    def edit_symbol(self, address):
        slot = self._visible_slot(address)
        if slot and slot.role == "placement" and slot.editable and self.widget.editing_active():
            self.shell.open_symbol_designer(slot.action_id, slot.action_parameter,
                                            slot=(self.widget.view_state(), address.physical_index))

    def history(self, redo):
        if not self.widget.editing_active():
            return
        (self.shell.redo_project if redo else self.shell.undo_project)()

    def apply_edit(self, request):
        try:
            self._apply_edit(request)
        except (FolderError, OSError) as exc:
            self._say(str(exc))
            self.host.report_error("keypad", exc)
            return False
        self._say("")
        return True

    def _apply_edit(self, request):
        frame = self.widget.frame()
        if (not isinstance(request, EditRequest) or not self.virtual or not self.widget.editing_active()
                or not frame or frame.context_id != self.host.project_token or frame.revision != request.base_revision):
            raise FolderError("Bearbeitungsanfrage veraltet oder Ansicht schreibgeschützt.")
        composer = self.shell.composer
        document = composer.document
        folder = document.folder(composer.navigation.folder_id)
        if (folder.mode == "auto" or self._revision_key !=
                (self.host.project_token, "virtual:" + folder.id, self.host.session.revision,
                 (composer.store.revision, composer.store.path))
                or self._pages[self._page][0] != composer.navigation.page_id):
            raise FolderError("Automatische Seiten im FolderComposer bearbeiten oder aktuelle Seite neu wählen.")
        source = None
        if request.source is not None:
            address = request.source
            if address.view_id != frame.view_id or address.page_index >= len(self._pages) or address.physical_index not in CELLS:
                raise FolderError("Quellplatz gehört nicht zu dieser Ordneransicht.")
            _, _, entries, count = self._pages[address.page_index]
            row = CELLS.index(address.physical_index)
            if row >= len(entries) or count > len(CELLS):
                raise FolderError("Quellplatz ist nicht eindeutig bearbeitbar.")
            source = entries[row]
            if (source.id != address.placement_id or source.kind != "action"
                    or source.target.plugin_id != document.plugin_id):
                raise FolderError("Nur lokale Action-Platzierungen bearbeiten.")
        action_id = source.target.resource_id if source else request.action_id
        parameter = source.action_parameter if source else request.action_parameter
        action = next((a for a in self.host.session.native_project().actions if a.id == action_id), None)
        if action is None or _unavailable_reason(action):
            raise FolderError("Diese Action kann nicht auf einer LCD-Taste platziert werden.")
        if parameter is not None and parameter not in {p.name for p in action.parameters}:
            raise FolderError("SDK-actionParameter ist nicht deklariert.")
        if request.operation == "remove":
            if request.source.page_index != frame.page_index:
                raise FolderError("Nur sichtbare Platzierungen entfernen.")
            result = document.remove_placement(source.id)
        else:
            target = self._visible_slot(request.target)
            if target is None or target.role != "empty" or not target.editable:
                raise FolderError("Nur am nächsten freien Platz ablegen; kein Ersetzen oder Tauschen.")
            page_id, _, entries, _ = self._pages[self._page]
            if request.operation == "move":
                position = sum(entry.id != source.id for entry in entries)
                result = document.move_placement(source.id, folder.id, page_id, position)
            else:
                result = document.add_action(folder.id, Reference(document.plugin_id, action_id),
                                             page_id, action_parameter=parameter)
        composer._commit(result)
