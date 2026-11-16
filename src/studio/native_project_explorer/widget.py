"""Passive Qt projection of NativeProject; no files, SDK calls or document owner.

All entities retain their native IDs. Group rows and cached display strings are
transient view data only. Project tuple order is used throughout, including entries
(their native position is displayed, never interpreted as a hardware slot/page).
"""
from __future__ import annotations

import html
from contextlib import contextmanager

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from adapters.logitech.native import NativeProject

_KEY = Qt.ItemDataRole.UserRole
_LINES = Qt.ItemDataRole.UserRole + 1
_SEARCH = Qt.ItemDataRole.UserRole + 2


class _Rows(QStyledItemDelegate):
    """Native selection/focus painting with vertically stacked, elided text."""

    def sizeHint(self, option, index):
        lines = index.data(_LINES) or (index.data(),)
        return QSize(100, QFontMetrics(option.font).height() * len(lines) + 12)

    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)
        painter.save()
        painter.setClipRect(option.rect)
        lines = index.data(_LINES) or (index.data(),)
        font = QFont(option.font)
        height = QFontMetrics(font).height()
        area = option.rect.adjusted(5, 6, -6, -6)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        color_role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        painter.setPen(option.palette.color(color_role))
        for number, text in enumerate(lines):
            font.setBold(number == 0 and index.data(_KEY) is None)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            line_rect = QRect(area.left(), area.top() + number * height, max(0, area.width()), height)
            painter.drawText(line_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, line_rect.width()))
        painter.restore()


class _Tree(QTreeWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.user_input = False

    @contextmanager
    def _input(self):
        previous = self.user_input
        self.user_input = True
        try:
            yield
        finally:
            self.user_input = previous

    def mousePressEvent(self, event):
        with self._input():
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        with self._input():
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.owner._activate(self.currentItem())
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.owner.search_edit.text():
            self.owner.set_filter("")
            event.accept()
            return
        with self._input():
            super().keyPressEvent(event)


class NativeProjectExplorerWidget(QWidget):
    """A read-only sidebar. Only actual user input emits selection/open intents.

    ``revision`` is an opaque host label. Programmatic selection of a missing or
    filtered entity returns False and clears the current selection. Filtering
    away a selection clears it, so Enter can never open an invisible entity.
    """

    nodeSelected = Signal(str, str)
    nodeActivated = Signal(str, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("nativeProjectExplorer")
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._branches: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._collapsed: set[tuple[str, str]] = set()
        self._plugin_id: str | None = None
        self._quiet = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        title = QLabel("Projektübersicht")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("nativeProjectExplorerSearch")
        self.search_edit.setPlaceholderText("Name, ID oder SDK-Typ suchen …")
        self.search_edit.setAccessibleName("Projektbaum filtern")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip("Filtert Namen, native IDs und angezeigte Details. Esc leert den Filter.")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.search_edit.installEventFilter(self)
        layout.addWidget(self.search_edit)

        self.tree = _Tree(self)
        self.tree.setObjectName("nativeProjectExplorerTree")
        self.tree.setAccessibleName("Natives Plugin-Projekt")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tree.setIndentation(12)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.tree.setDragEnabled(False)
        self.tree.setAcceptDrops(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setItemDelegate(_Rows(self.tree))
        self.tree.itemSelectionChanged.connect(self._selected)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._activate(item))
        self.tree.itemExpanded.connect(lambda item: self._expansion(item, False))
        self.tree.itemCollapsed.connect(lambda item: self._expansion(item, True))

        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(8, 24, 8, 8)
        self.empty_label = QLabel()
        self.empty_label.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        self.reset_button = QPushButton("Filter zurücksetzen")
        self.reset_button.clicked.connect(lambda: self.set_filter(""))
        empty_layout.addWidget(self.reset_button)
        empty_layout.addStretch()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.empty_page)
        layout.addWidget(self.stack, 1)
        self.setFocusProxy(self.tree)
        self._find = QShortcut(QKeySequence.StandardKey.Find, self)
        self._find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._find.activated.connect(self._focus_search)
        self._apply_filter()

    @contextmanager
    def _silent(self):
        self._quiet += 1
        try:
            yield
        finally:
            self._quiet -= 1

    def set_project(self, project: NativeProject | None, *, revision: str | None = None) -> None:
        """Replace the view snapshot; retain visible native identity within a plugin."""
        if project is not None and not isinstance(project, NativeProject):
            raise TypeError("Expected NativeProject or None; legacy projection belongs to the host")
        if revision is not None and not isinstance(revision, str):
            raise TypeError("revision must be an opaque string or None")
        if project is not None:
            # Validate identity before discarding a good view. No SDK semantics are inferred.
            keys = [("plugin", project.plugin_id)]
            keys += [("action", a.id) for a in project.actions]
            keys += [("handler", h["id"]) for h in project.handlers]
            keys += [("folder", f.id) for f in project.folders]
            keys += [("folder_entry", e.id) for f in project.folders for e in f.entries]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate native entity identity")
        old_selection = self._current_key()
        same_plugin = project is not None and self._plugin_id == project.plugin_id
        if not same_plugin:
            old_selection = None
            self._collapsed.clear()
        with self._silent():
            self.tree.clear()
            self._items.clear()
            self._branches.clear()
            self._plugin_id = None if project is None else project.plugin_id
            if project is not None:
                root_lines = (project.display_name, project.plugin_id)
                root = self._add(None, ("plugin", project.plugin_id), root_lines,
                                 ("Plugin", *root_lines, *(() if revision is None else ("Host-Revision: " + revision,))))
                groups = {name: self._add(root, None, (f"{name} · {count}",), (name,))
                          for name, count in (("Aktionen", len(project.actions)),
                                              ("Handler", len(project.handlers)),
                                              ("Dynamic Folders", len(project.folders)))}
                self._branches.update({("group", name): item for name, item in groups.items()})
                for action in project.actions:
                    lines = (action.display_name, action.id, action.sdk_type)
                    self._add(groups["Aktionen"], ("action", action.id), lines,
                              (*lines, "Handler: " + action.handler, action.description))
                for handler in project.handlers:
                    lines = (handler["id"], "Callback: " + handler["callback_id"])
                    self._add(groups["Handler"], ("handler", handler["id"]), lines, lines)
                actions = {action.id: action for action in project.actions}
                for folder in project.folders:
                    lines = (folder.display_name, folder.id, "Navigation: " + folder.navigation)
                    devices = tuple(f"{device}: {area}" for device, area in folder.device_navigation.items())
                    item = self._add(groups["Dynamic Folders"], ("folder", folder.id), lines, (*lines, *devices))
                    for entry in folder.entries:
                        action = actions.get(entry.action)
                        lines = (action.display_name if action else entry.action, entry.id, "→ " + entry.action)
                        self._add(item, ("folder_entry", entry.id), lines,
                                  ("Folder Entry / Placement", *lines, f"Position: {entry.position}"))
            self._collapsed.intersection_update(self._branches)
            self._apply_filter()
            if old_selection is not None:
                self.set_selection(*old_selection)

    def set_selection(self, node_kind: str, native_id: str) -> bool:
        """Silently select an existing filter-visible entity, expanding its parents."""
        item = self._items.get((node_kind, native_id))
        with self._silent():
            self._clear_selection()
            if item is None or item.isHidden():
                return False
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                if not self.search_edit.text().strip():
                    for branch_key, branch in self._branches.items():
                        if branch is parent:
                            self._collapsed.discard(branch_key)
                            break
                parent = parent.parent()
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        return True

    def set_filter(self, text: str) -> None:
        self.search_edit.setText(text)

    def clear(self) -> None:
        """Remove the snapshot, revision, filter and selection without emitting intents."""
        self.set_project(None)
        self.set_filter("")

    def _add(self, parent, key, lines, details):
        item = QTreeWidgetItem(parent if parent is not None else self.tree)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setText(0, lines[0])
        item.setData(0, _KEY, key)
        item.setData(0, _LINES, lines)
        item.setData(0, _SEARCH, "\n".join((*lines, *details)).casefold())
        item.setData(0, Qt.ItemDataRole.AccessibleTextRole, ", ".join(lines))
        item.setToolTip(0, "<qt>" + "<br>".join(html.escape(line) for line in details) + "</qt>")
        if key is not None:
            self._items[key] = item
            self._branches[key] = item
        return item

    def _apply_filter(self, *_):
        query = self.search_edit.text().strip().casefold()

        def visit(item, inherited=False):
            direct = not query or query in item.data(0, _SEARCH)
            descendant = False
            for index in range(item.childCount()):
                descendant = visit(item.child(index), inherited or direct) or descendant
            visible = inherited or direct or descendant
            item.setHidden(not visible)
            return visible

        with self._silent():
            root = self.tree.topLevelItem(0)
            visible = root is not None and visit(root)
            for key, item in self._branches.items():
                item.setExpanded(bool(query) or key not in self._collapsed)
            current = self.tree.currentItem()
            if current is not None and current.isHidden():
                self._clear_selection()
            if visible:
                self.stack.setCurrentWidget(self.tree)
            else:
                self.empty_label.setText("Kein Projekt geöffnet.\nDer Host liefert ein natives Plugin-Projekt."
                                         if root is None else "Keine Treffer.\nFilter ändern oder zurücksetzen.")
                self.reset_button.setVisible(root is not None)
                self.stack.setCurrentWidget(self.empty_page)

    def _clear_selection(self):
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)

    def _current_key(self):
        item = self.tree.currentItem()
        if item is None or item.isHidden() or not item.isSelected():
            return None
        parent = item.parent()
        while parent is not None:
            if parent.isHidden() or not parent.isExpanded():
                return None
            parent = parent.parent()
        key = item.data(0, _KEY)
        return key if self._items.get(key) is item else None

    def _selected(self):
        if not self._quiet and self.tree.user_input:
            key = self._current_key()
            if key is not None:
                self.nodeSelected.emit(*key)

    def _activate(self, item):
        if self._quiet or item is None or item is not self.tree.currentItem():
            return
        key = self._current_key()
        if key is not None:
            self.nodeActivated.emit(*key)
        elif item.childCount():
            item.setExpanded(not item.isExpanded())

    def _expansion(self, item, collapsed):
        if self._quiet or self.search_edit.text().strip():
            return
        key = next((key for key, branch in self._branches.items() if branch is item), None)
        if key is not None:
            (self._collapsed.add if collapsed else self._collapsed.discard)(key)

    def _focus_search(self):
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def eventFilter(self, watched, event):
        if watched is self.search_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.set_filter("")
                return True
            if event.key() == Qt.Key.Key_Down and self.stack.currentWidget() is self.tree:
                self.tree.setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)
