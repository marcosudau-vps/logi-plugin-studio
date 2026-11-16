"""Catalog of the open project's native SDK actions: search, select, drag to a keypad.

The widget only displays a snapshot of ``NativeAction`` values and emits intents.
It reads no files, writes no project data and has no action model of its own. An
``ActionOffer`` is built on demand from the current snapshot, so a removed or
changed action can never be offered from a stale copy.
"""
from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QImage, QKeySequence, QPainter, QPainterPath, QPalette, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QStackedWidget, QStyledItemDelegate, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from adapters.logitech.native import ACTION_TYPES, NativeAction, NativeProject
from studio.keypad_contract import ActionOffer
from studio.keypad_preview.mime import ACTION_REF_MIME, encode_action_ref

ALL_TYPES_LABEL = "Alle"
GROUP_ORDERS = ("project", "name")
_ROW_ROLE = Qt.ItemDataRole.UserRole + 1
_ICON_ACTION = 30
_ICON_PARAMETER = 22
_INDENT = 14

OfferKey = tuple[str, "str | None"]


@dataclass(frozen=True)
class _Row:
    """Display data of one tree row. It identifies native data; it does not replace it."""

    kind: str  # "group" | "action" | "parameter"
    title: str
    detail: str = ""
    action_id: str | None = None
    parameter: str | None = None
    sdk_type: str = ""
    has_offer: bool = False

    @property
    def key(self) -> OfferKey | None:
        return None if self.action_id is None else (self.action_id, self.parameter)


@dataclass(frozen=True)
class _Tones:
    text: QColor
    muted: QColor
    muted_selected: QColor
    hover: QColor
    selected: QColor
    accent: QColor
    focus: QColor
    icon_back: QColor
    icon_mark: QColor
    pill_back: QColor
    drag_back: QColor


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                           a.greenF() + (b.greenF() - a.greenF()) * amount,
                           a.blueF() + (b.blueF() - a.blueF()) * amount)


def tones_for(palette: QPalette) -> _Tones:
    """All colors derive from the host palette, so the catalog follows the Studio theme."""
    base = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    accent = palette.color(QPalette.ColorRole.Highlight)
    selected = _mix(base, accent, 0.30)
    return _Tones(text=text, muted=_mix(base, text, 0.72), muted_selected=_mix(selected, text, 0.78),
                  hover=_mix(base, text, 0.08), selected=selected, accent=accent, focus=_mix(accent, text, 0.35),
                  icon_back=_mix(base, text, 0.13), icon_mark=_mix(base, text, 0.65), pill_back=_mix(base, text, 0.18),
                  drag_back=_mix(base, text, 0.06))


class _ElidedLabel(QLabel):
    """Plain-text label that never widens the sidebar; a long name ends in an ellipsis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(html.escape(text))
        self._elide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())))


class _RowHeights(QStyledItemDelegate):
    """Only row heights. _CatalogTree paints rows itself, independent of the Qt style."""

    def __init__(self, owner: "ActionCatalogWidget") -> None:
        super().__init__(owner)
        self._owner = owner

    def sizeHint(self, option, index) -> QSize:
        return QSize(120, self._owner.row_height(index.data(_ROW_ROLE)))


class _CatalogTree(QTreeWidget):
    def __init__(self, owner: "ActionCatalogWidget") -> None:
        super().__init__(owner)
        self._owner = owner
        self.press_key: OfferKey | None = None
        self.hover_row: _Row | None = None
        self.setObjectName("actionCatalogTree")
        self.setAccessibleName("Aktionsliste")
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setIndentation(_INDENT)
        self.setRootIsDecorated(True)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.viewport().setAutoFillBackground(False)
        self.setItemDelegate(_RowHeights(owner))

    def mousePressEvent(self, event) -> None:
        # Remembered first: the drag must carry exactly the entry under the press.
        item = self.itemAt(event.position().toPoint())
        row = item.data(0, _ROW_ROLE) if item is not None else None
        self.press_key = row.key if row is not None and row.has_offer else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        self._set_hover(item.data(0, _ROW_ROLE) if item is not None else None)
        super().mouseMoveEvent(event)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.Leave:
            self._set_hover(None)
        return super().viewportEvent(event)

    def _set_hover(self, row: _Row | None) -> None:
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def startDrag(self, _supported_actions) -> None:
        key, self.press_key = self.press_key, None
        if key is not None:
            self._owner._start_drag(key)

    def drawRow(self, painter: QPainter, option, index) -> None:
        depth = 1
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        indent = depth * self.indentation()
        row_rect = option.rect
        self.drawBranches(painter, QRect(0, row_rect.y(), indent, row_rect.height()), index)
        row = index.data(_ROW_ROLE)
        content = QRect(indent, row_rect.y(), max(0, row_rect.width() - indent), row_rect.height())
        self._owner._paint_row(painter, content, row, selected=self.selectionModel().isSelected(index),
                               hovered=row == self.hover_row, focused=self.hasFocus() and index == self.currentIndex())

    def drawBranches(self, painter: QPainter, rect: QRect, index) -> None:
        if not self.model().hasChildren(index):
            return
        center = QPointF(rect.right() - self.indentation() / 2 + 1, rect.center().y() + 0.5)
        pen = QPen(self._owner.tones().muted, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        if self.isExpanded(index):
            points = (QPointF(-3.5, -1.8), QPointF(0, 1.8), QPointF(3.5, -1.8))
        else:
            points = (QPointF(-1.8, -3.5), QPointF(1.8, 0), QPointF(-1.8, 3.5))
        painter.drawPolyline([center + point for point in points])
        painter.restore()


class ActionCatalogWidget(QWidget):
    """Sidebar with the open project's actions. The host owns every actual change."""

    actionSelected = Signal(object)  # ActionOffer; only for a real user selection
    actionEditRequested = Signal(str)  # native action_id
    createActionRequested = Signal()  # a later host opens the action editor

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("actionCatalogWidget")
        self.setMinimumWidth(240)
        self._actions: tuple[NativeAction, ...] = ()
        self._by_id: dict[str, NativeAction] = {}
        self._items: dict[OfferKey, QTreeWidgetItem] = {}
        self._group_items: dict[str, QTreeWidgetItem] = {}
        self._group_counts: dict[str, int] = {}
        self._action_text: dict[str, str] = {}
        self._parameter_text: dict[OfferKey, str] = {}
        self._images: dict[OfferKey, QImage] = {}
        self._usage: dict[OfferKey, int] = {}
        self._pixmaps: dict[tuple, QPixmap] = {}
        self._selection: OfferKey | None = None
        self._search = ""
        self._type_filter: str | None = None
        self._group_order = "project"
        self._collapsed_groups: set[str] = set()
        self._expanded_actions: set[str] = set()
        self._has_source = False
        self._project_name = ""
        self._quiet = 0
        self._tones: _Tones | None = None
        self._type_values: tuple[str | None, ...] = (None, *sorted(ACTION_TYPES))
        self._build_ui()
        self._refresh_view()

    # ------------------------------------------------------------------ public API

    def set_project(self, project: NativeProject | None) -> None:
        """A view input only: delegates to ``set_actions``; the project stays with the host."""
        self._project_name = "" if project is None else project.display_name
        self.project_label.set_full_text(self._project_name)
        self.set_actions(() if project is None else project.actions)
        if project is None:
            self._has_source = False
            self._refresh_view()

    def set_actions(self, actions: Iterable[NativeAction]) -> None:
        """Show a read-only snapshot. Never echoes ``actionSelected``."""
        snapshot = tuple(actions)
        by_id: dict[str, NativeAction] = {}
        for action in snapshot:
            if not isinstance(action, NativeAction):
                raise TypeError("ActionCatalogWidget shows NativeAction values only")
            if action.id in by_id:
                raise ValueError(f"Duplicate native action id {action.id!r}")
            by_id[action.id] = action
        self._actions, self._by_id = snapshot, by_id
        self._has_source = True
        self._rebuild()

    def set_images(self, images: Mapping[OfferKey, QImage]) -> None:
        """Finished previews from the host. Deep copies, as host buffers may be short-lived."""
        copies: dict[OfferKey, QImage] = {}
        for key, image in images.items():
            if not isinstance(image, QImage):
                raise TypeError("set_images expects QImage values")
            if not image.isNull():
                copies[key] = image.copy()
        self._images = copies
        self._pixmaps.clear()
        self.catalog_tree.viewport().update()

    def set_filter(self, text: str) -> None:
        self.search_edit.setText(text)

    def set_selected_action(self, action_id: str | None, action_parameter: str | None = None) -> None:
        """Mirror a host selection. Unknown identities clear it. Never emits ``actionSelected``."""
        key = None if action_id is None else (action_id, action_parameter)
        self._selection = key if key in self._items else None
        if self._selection is not None:
            action = self._by_id[self._selection[0]]
            self._collapsed_groups.discard(action.group_name)
            if action_parameter is not None:
                self._expanded_actions.add(action.id)
        self._apply_filter()

    # ------------------------------------------------------------------ additional view methods

    def set_type_filter(self, sdk_type: str | None) -> None:
        if sdk_type not in self._type_values:
            raise ValueError(f"Unknown SDK action type {sdk_type!r}")
        self.type_combo.setCurrentIndex(self._type_values.index(sdk_type))

    def set_group_order(self, order: str) -> None:
        """``project`` keeps the project's order, ``name`` sorts groups and actions by name."""
        if order not in GROUP_ORDERS:
            raise ValueError(f"order must be one of {GROUP_ORDERS}")
        if order != self._group_order:
            self._group_order = order
            self.sort_button.setChecked(order == "name")
            self._rebuild()

    def set_usage_counts(self, counts: Mapping[OfferKey, int]) -> None:
        """Only reported counts are shown; placement is never guessed from device or UI."""
        for count in counts.values():
            if type(count) is not int or count < 0:
                raise ValueError("Usage counts must be non-negative integers")
        self._usage = dict(counts)
        self._rebuild()

    def offer_for(self, action_id: str, action_parameter: str | None = None) -> ActionOffer | None:
        """A fresh offer from the current snapshot; None if no such concrete entry exists."""
        action = self._by_id.get(action_id)
        if action is None:
            return None
        if action_parameter is None:
            if action.parameters:
                return None  # The SDK reports concrete parameters; no general variant is invented.
            display_name = action.display_name
        else:
            parameter = next((p for p in action.parameters if p.name == action_parameter), None)
            if parameter is None:
                return None
            display_name = parameter.display_name
        return ActionOffer(action.id, display_name, action_parameter, self._images.get((action_id, action_parameter)))

    def selected_key(self) -> OfferKey | None:
        return self._selection

    def selected_offer(self) -> ActionOffer | None:
        return None if self._selection is None else self.offer_for(*self._selection)

    def item_for(self, action_id: str, action_parameter: str | None = None) -> QTreeWidgetItem | None:
        return self._items.get((action_id, action_parameter))

    def group_item(self, group_name: str) -> QTreeWidgetItem | None:
        return self._group_items.get(group_name)

    def group_names(self) -> tuple[str, ...]:
        """Visible groups, top to bottom."""
        tree = self.catalog_tree
        rows = (tree.topLevelItem(index) for index in range(tree.topLevelItemCount()))
        return tuple(item.data(0, _ROW_ROLE).title for item in rows if not item.isHidden())

    def visible_keys(self) -> tuple[OfferKey, ...]:
        """Identity of every entry the filters leave visible, in display order."""
        keys: list[OfferKey] = []
        tree = self.catalog_tree
        for group_index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(group_index)
            if group.isHidden():
                continue
            for action_index in range(group.childCount()):
                action = group.child(action_index)
                if action.isHidden():
                    continue
                keys.append(action.data(0, _ROW_ROLE).key)
                for parameter_index in range(action.childCount()):
                    parameter = action.child(parameter_index)
                    if not parameter.isHidden():
                        keys.append(parameter.data(0, _ROW_ROLE).key)
        return tuple(keys)

    def empty_state(self) -> tuple[str, str] | None:
        """(title, detail) of the visible empty state; None while the list is shown."""
        if self.stack.currentWidget() is self.catalog_tree:
            return None
        return self.empty_title.text(), self.empty_detail.text()

    def tones(self) -> _Tones:
        if self._tones is None:
            self._tones = tones_for(self.palette())
        return self._tones

    # ------------------------------------------------------------------ construction

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel("Aktionen")
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() + 1.5)
        self.title_label.setFont(title_font)
        self.count_label = QLabel()
        self.count_label.setTextFormat(Qt.TextFormat.PlainText)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.project_label = _ElidedLabel()
        layout.addWidget(self.project_label)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("actionCatalogSearch")
        self.search_edit.setPlaceholderText("Aktionen suchen …")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Aktionen suchen")
        self.search_edit.setToolTip("Sucht in Name, ID, Beschreibung, Parameter, Gruppe und SDK-Typ")
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.installEventFilter(self)
        layout.addWidget(self.search_edit)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("actionCatalogTypeFilter")
        self.type_combo.setAccessibleName("Nach SDK-Typ filtern")
        self.type_combo.setToolTip("Nach nativem SDK-Typ filtern")
        self.type_combo.setMinimumContentsLength(10)
        self.type_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.type_combo.addItems([ALL_TYPES_LABEL, *self._type_values[1:]])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.sort_button = QToolButton()
        self.sort_button.setObjectName("actionCatalogSort")
        self.sort_button.setText("A–Z")
        self.sort_button.setCheckable(True)
        self.sort_button.setAccessibleName("Alphabetisch sortieren")
        self.sort_button.setToolTip("Gruppen und Aktionen alphabetisch sortieren, sonst Projektreihenfolge")
        self.sort_button.toggled.connect(lambda checked: self.set_group_order("name" if checked else "project"))
        filters.addWidget(self.type_combo, 1)
        filters.addWidget(self.sort_button)
        layout.addLayout(filters)

        self.catalog_tree = _CatalogTree(self)
        self.catalog_tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.catalog_tree.itemClicked.connect(self._on_item_clicked)
        self.catalog_tree.itemExpanded.connect(lambda item: self._on_expansion(item, True))
        self.catalog_tree.itemCollapsed.connect(lambda item: self._on_expansion(item, False))

        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(8, 24, 8, 8)
        empty_layout.setSpacing(6)
        self.empty_title = QLabel()
        self.empty_title.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty_font = self.empty_title.font()
        empty_font.setBold(True)
        self.empty_title.setFont(empty_font)
        self.empty_detail = QLabel()
        self.empty_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_detail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.empty_detail.setWordWrap(True)
        self.reset_filter_button = QPushButton("Filter zurücksetzen")
        self.reset_filter_button.clicked.connect(self._reset_filters)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_detail)
        empty_layout.addWidget(self.reset_filter_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.catalog_tree)
        self.stack.addWidget(self.empty_page)
        layout.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.new_action_button = QPushButton("+ Neue Aktion")
        self.new_action_button.setObjectName("actionCatalogNew")
        self.new_action_button.setToolTip("Bittet den Host, den Aktionseditor zu öffnen")
        self.new_action_button.clicked.connect(lambda: self.createActionRequested.emit())
        self.edit_button = QPushButton("Bearbeiten")
        self.edit_button.setObjectName("actionCatalogEdit")
        self.edit_button.setToolTip("Bittet den Host, die gewählte Aktion zu bearbeiten")
        self.edit_button.clicked.connect(self._on_edit_clicked)
        buttons.addWidget(self.new_action_button, 1)
        buttons.addWidget(self.edit_button, 1)
        layout.addLayout(buttons)

        shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._focus_search)
        self.setTabOrder(self.search_edit, self.type_combo)
        self.setTabOrder(self.type_combo, self.sort_button)
        self.setTabOrder(self.sort_button, self.catalog_tree)
        self.setTabOrder(self.catalog_tree, self.new_action_button)
        self.setTabOrder(self.new_action_button, self.edit_button)
        self._apply_label_tones()

    def _apply_label_tones(self) -> None:
        palette = QPalette(self.palette())
        palette.setColor(QPalette.ColorRole.WindowText, self.tones().muted)
        for label in (self.project_label, self.count_label, self.empty_detail):
            label.setPalette(palette)

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and self.stack.currentWidget() is self.catalog_tree:
                self.catalog_tree.setFocus(Qt.FocusReason.TabFocusReason)
                return True
            if event.key() == Qt.Key.Key_Escape and self.search_edit.text():
                self.search_edit.clear()
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._tones = None
            self._pixmaps.clear()
            if hasattr(self, "catalog_tree"):
                if event.type() == QEvent.Type.PaletteChange:
                    self._apply_label_tones()
                self.catalog_tree.doItemsLayout()
                self.catalog_tree.viewport().update()
        super().changeEvent(event)

    # ------------------------------------------------------------------ list content

    @contextmanager
    def _silent(self):
        """Programmatic list changes are not user interaction and stay signal-free."""
        self._quiet += 1
        try:
            yield
        finally:
            self._quiet -= 1

    def _rebuild(self) -> None:
        tree = self.catalog_tree
        with self._silent():
            tree.setUpdatesEnabled(False)
            try:
                tree.press_key = None
                tree.hover_row = None
                tree.clear()
                self._items, self._group_items = {}, {}
                self._action_text, self._parameter_text = {}, {}
                groups: dict[str, list[NativeAction]] = {}
                for action in self._actions:
                    groups.setdefault(action.group_name, []).append(action)
                names = list(groups)
                if self._group_order == "name":
                    names.sort(key=str.casefold)
                for name in names:
                    group_item = QTreeWidgetItem(tree)
                    group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self._describe(group_item, _Row("group", name), f"Gruppe {name}")
                    self._group_items[name] = group_item
                    actions = groups[name]
                    if self._group_order == "name":
                        actions = sorted(actions, key=lambda a: (a.display_name.casefold(), a.id))
                    for action in actions:
                        self._add_action(group_item, action)
                if self._selection not in self._items:
                    self._selection = None  # Removed: clear gently, and no signal.
            finally:
                tree.setUpdatesEnabled(True)
        self._apply_filter()

    def _add_action(self, group_item: QTreeWidgetItem, action: NativeAction) -> None:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        offered = base | Qt.ItemFlag.ItemIsDragEnabled
        item = QTreeWidgetItem(group_item)
        has_parameters = bool(action.parameters)
        item.setFlags(base if has_parameters else offered)
        row = _Row("action", action.display_name, self._action_detail(action), action.id, None, action.sdk_type,
                   not has_parameters)
        self._describe(item, row, f"{action.display_name}, {action.sdk_type}", self._action_tooltip(action))
        self._items[row.key] = item
        self._action_text[action.id] = "\n".join(
            (action.display_name, action.id, action.description, action.group_name, action.sdk_type)).casefold()
        for parameter in action.parameters:
            child = QTreeWidgetItem(item)
            child.setFlags(offered)
            detail = parameter.name if not parameter.group_name else f"{parameter.name} · {parameter.group_name}"
            child_row = _Row("parameter", parameter.display_name, detail, action.id, parameter.name, action.sdk_type, True)
            tooltip = self._action_tooltip(action, f"<b>{html.escape(parameter.display_name)}</b><br>"
                                                   f"actionParameter: {html.escape(parameter.name)}")
            self._describe(child, child_row, f"{parameter.display_name}, Parameter von {action.display_name}", tooltip)
            self._items[child_row.key] = child
            self._parameter_text[child_row.key] = "\n".join(
                (parameter.name, parameter.display_name, parameter.group_name, parameter.super_group_name or "")).casefold()

    def _describe(self, item: QTreeWidgetItem, row: _Row, accessible: str, tooltip: str = "") -> None:
        item.setData(0, _ROW_ROLE, row)
        item.setText(0, row.title)  # Keyboard search and accessibility; painting uses the row.
        count = self._usage.get(row.key, 0) if row.key is not None else 0
        if count:
            accessible += f", {count}-mal verwendet"
            tooltip += f"<br>Laut Host {count}-mal verwendet"
        item.setData(0, Qt.ItemDataRole.AccessibleTextRole, accessible)
        if tooltip:
            item.setToolTip(0, tooltip)

    @staticmethod
    def _action_detail(action: NativeAction) -> str:
        parts = [action.sdk_type]
        if action.parameters:
            parts.append(f"{len(action.parameters)} Parameter")
        if action.states:
            parts.append(f"{len(action.states)} Zustände")
        if action.has_reset:
            parts.append("Reset")
        if action.editor_controls:
            parts.append(f"{len(action.editor_controls)} Felder")
        if action.legacy:
            parts.append("Altformat")
        return " · ".join(parts)

    @staticmethod
    def _action_tooltip(action: NativeAction, variant: str = "") -> str:
        lines = [variant] if variant else []
        lines.append(f"<b>{html.escape(action.display_name)}</b>" if not variant else html.escape(action.display_name))
        if action.description:
            lines.append(html.escape(action.description))
        lines.append(f"ID: {html.escape(action.id)}")
        lines.append(f"SDK-Typ: {html.escape(action.sdk_type)}")
        return "<br>".join(lines)

    # ------------------------------------------------------------------ filtering

    def _on_search_changed(self, text: str) -> None:
        self._search = text
        self._apply_filter()

    def _on_type_changed(self, index: int) -> None:
        self._type_filter = self._type_values[index]
        self._apply_filter()

    def _reset_filters(self) -> None:
        self.search_edit.clear()
        self.type_combo.setCurrentIndex(0)

    def _apply_filter(self) -> None:
        tokens = self._search.casefold().split()
        tree = self.catalog_tree
        counts: dict[str, int] = {}
        with self._silent():
            tree.setUpdatesEnabled(False)
            try:
                for name, group_item in self._group_items.items():
                    visible = 0
                    for action_index in range(group_item.childCount()):
                        action_item = group_item.child(action_index)
                        if self._filter_action(action_item, tokens):
                            visible += 1
                    counts[name] = visible
                    group_item.setHidden(visible == 0)
                    group_item.setExpanded(bool(tokens) or name not in self._collapsed_groups)
                self._group_counts = counts
                self._sync_tree_selection()
            finally:
                tree.setUpdatesEnabled(True)
        self._refresh_view()

    def _filter_action(self, item: QTreeWidgetItem, tokens: list[str]) -> bool:
        row: _Row = item.data(0, _ROW_ROLE)
        action = self._by_id[row.action_id]
        type_matches = self._type_filter is None or action.sdk_type == self._type_filter
        action_text = self._action_text[action.id]
        direct = all(token in action_text for token in tokens)
        variant_match = False
        for index in range(item.childCount()):
            child = item.child(index)
            text = self._parameter_text[child.data(0, _ROW_ROLE).key]
            matches = type_matches and (direct or all(token in action_text or token in text for token in tokens))
            child.setHidden(not matches)
            variant_match = variant_match or matches
        visible = type_matches and (direct or variant_match)
        item.setHidden(not visible)
        if item.childCount():
            # A match only in a parameter must be visible. Without a search the user's choice returns.
            item.setExpanded(bool(tokens) and not direct and variant_match if tokens
                             else action.id in self._expanded_actions)
        return visible

    def _sync_tree_selection(self) -> None:
        tree = self.catalog_tree
        item = self._items.get(self._selection) if self._selection is not None else None
        if item is None or item.isHidden():
            tree.clearSelection()
            tree.setCurrentItem(None)
            return
        if tree.currentItem() is not item or not item.isSelected():
            tree.setCurrentItem(item)
        tree.scrollToItem(item)

    def _selection_visible(self) -> bool:
        item = self._items.get(self._selection) if self._selection is not None else None
        return item is not None and not item.isHidden()

    def _refresh_view(self) -> None:
        total = len(self._actions)
        visible = sum(self._group_counts.values()) if total else 0
        noun = "Aktion" if total == 1 else "Aktionen"
        self.count_label.setText(f"{visible} von {total} {noun}" if total else "")
        self.project_label.setVisible(bool(self._project_name))
        if not self._has_source:
            self._show_empty("Kein Projekt geöffnet", "Öffne ein Plugin-Projekt, um seine Aktionen zu sehen.", False)
        elif not total:
            self._show_empty("Keine Aktionen", "Dieses Projekt enthält noch keine Aktionen.", False)
        elif not visible:
            query = self._search.strip()
            detail = f"Keine Aktion passt zu „{query}“." if query else "Keine Aktion hat diesen SDK-Typ."
            if query and self._type_filter is not None:
                detail = f"Keine Aktion vom Typ {self._type_filter} passt zu „{query}“."
            self._show_empty("Keine Treffer", detail, True)
        else:
            self.stack.setCurrentWidget(self.catalog_tree)
        self.new_action_button.setEnabled(self._has_source)
        self.edit_button.setEnabled(self._selection_visible())
        self.catalog_tree.viewport().update()

    def _show_empty(self, title: str, detail: str, can_reset: bool) -> None:
        self.empty_title.setText(title)
        self.empty_detail.setText(detail)
        self.reset_filter_button.setVisible(can_reset)
        self.stack.setCurrentWidget(self.empty_page)

    # ------------------------------------------------------------------ user interaction

    def _on_tree_selection(self) -> None:
        if self._quiet:
            return
        items = self.catalog_tree.selectedItems()
        key = items[0].data(0, _ROW_ROLE).key if items else None
        if key == self._selection:
            return
        self._selection = key
        self._refresh_view()
        offer = self.offer_for(*key) if key is not None else None
        if offer is not None:
            self.actionSelected.emit(offer)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        # Groups and actions with parameters are no placeable entries: a click opens them.
        if item.childCount():
            item.setExpanded(not item.isExpanded())

    def _on_expansion(self, item: QTreeWidgetItem, expanded: bool) -> None:
        if self._quiet or self._search.split():
            return  # Automatic expansion by a search is not the user's choice.
        row: _Row = item.data(0, _ROW_ROLE)
        if row.kind == "group":
            (self._collapsed_groups.discard if expanded else self._collapsed_groups.add)(row.title)
        else:
            (self._expanded_actions.add if expanded else self._expanded_actions.discard)(row.action_id)

    def _on_edit_clicked(self) -> None:
        if self._selection is not None and self._selection_visible():
            self.actionEditRequested.emit(self._selection[0])

    # ------------------------------------------------------------------ drag source

    def _start_drag(self, key: OfferKey) -> None:
        offer = self.offer_for(*key)
        if offer is None:
            return  # The snapshot changed; an old offer is never reused.
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(offer)))
        pixmap, hotspot = self.drag_visual(offer)
        self._exec_drag(mime, pixmap, hotspot)

    def _exec_drag(self, mime: QMimeData, pixmap: QPixmap, hotspot: QPoint) -> None:
        # QDrag takes ownership of the mime data and deletes itself afterwards.
        drag = QDrag(self.catalog_tree)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def drag_visual(self, offer: ActionOffer) -> tuple[QPixmap, QPoint]:
        """Cursor image of a drag. Drop-target marks belong to the keypad alone."""
        action = self._by_id[offer.action_id]
        subtitle = action.sdk_type if offer.action_parameter is None else action.display_name
        title_font, detail_font = self._row_fonts()
        title_metrics, detail_metrics = QFontMetrics(title_font), QFontMetrics(detail_font)
        icon = _ICON_ACTION
        text_width = min(240, max(title_metrics.horizontalAdvance(offer.display_name),
                                  detail_metrics.horizontalAdvance(subtitle)) + 2)
        width = 8 + icon + 8 + text_width + 12
        height = max(icon + 12, title_metrics.height() + detail_metrics.height() + 12)
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(width * ratio), round(height * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        tones = self.tones()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0.75, 0.75, width - 1.5, height - 1.5)
        painter.setPen(QPen(tones.accent, 1.5))
        painter.setBrush(tones.drag_back)
        painter.drawRoundedRect(body, 7, 7)
        row = _Row("parameter" if offer.action_parameter else "action", offer.display_name, subtitle, offer.action_id,
                   offer.action_parameter, action.sdk_type, True)
        self._paint_icon(painter, QRect(8, (height - icon) // 2, icon, icon), row)
        left = 8 + icon + 8
        top = (height - title_metrics.height() - detail_metrics.height()) // 2
        painter.setFont(title_font)
        painter.setPen(tones.text)
        painter.drawText(QRect(left, top, text_width, title_metrics.height()), Qt.AlignmentFlag.AlignLeft,
                         title_metrics.elidedText(offer.display_name, Qt.TextElideMode.ElideRight, text_width))
        painter.setFont(detail_font)
        painter.setPen(tones.muted)
        painter.drawText(QRect(left, top + title_metrics.height(), text_width, detail_metrics.height()),
                         Qt.AlignmentFlag.AlignLeft,
                         detail_metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, text_width))
        painter.end()
        return pixmap, QPoint(8 + icon // 2, height // 2)

    # ------------------------------------------------------------------ painting

    def _row_fonts(self) -> tuple[QFont, QFont]:
        title = QFont(self.font())
        title.setWeight(QFont.Weight.Medium)
        detail = QFont(self.font())
        size = self.font().pointSizeF()
        if size > 0:
            detail.setPointSizeF(max(7.5, size - 1))
        return title, detail

    def row_height(self, row: _Row | None) -> int:
        title_font, detail_font = self._row_fonts()
        title, detail = QFontMetrics(title_font).height(), QFontMetrics(detail_font).height()
        if row is None or row.kind == "group":
            return max(26, title + 10)
        if row.kind == "parameter":
            return max(_ICON_PARAMETER + 10, title + detail + 8)
        return max(_ICON_ACTION + 12, title + detail + 12)

    def _paint_row(self, painter: QPainter, rect: QRect, row: _Row, *, selected: bool, hovered: bool, focused: bool) -> None:
        tones = self.tones()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(rect).adjusted(0, 1, -6, -1)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tones.selected if selected else tones.hover)
            painter.drawRoundedRect(body, 6, 6)
        if selected:
            painter.setBrush(tones.accent)
            painter.drawRoundedRect(QRectF(body.left() + 1, body.top() + 6, 3, body.height() - 12), 1.5, 1.5)
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(tones.focus, 1.5))
            painter.drawRoundedRect(body.adjusted(0.75, 0.75, -0.75, -0.75), 5.5, 5.5)
        if row.kind == "group":
            self._paint_group(painter, rect, row, tones)
        else:
            self._paint_entry(painter, rect, row, tones, selected, hovered)
        painter.restore()

    def _paint_group(self, painter: QPainter, rect: QRect, row: _Row, tones: _Tones) -> None:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        count = str(self._group_counts.get(row.title, 0))
        count_width = metrics.horizontalAdvance(count)
        area = rect.adjusted(4, 0, -12, 0)
        painter.setFont(font)
        painter.setPen(tones.muted)
        painter.drawText(area, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count)
        painter.setPen(tones.text)
        painter.drawText(area.adjusted(0, 0, -count_width - 8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, area.width() - count_width - 8))

    def _paint_entry(self, painter: QPainter, rect: QRect, row: _Row, tones: _Tones, selected: bool, hovered: bool) -> None:
        icon = _ICON_PARAMETER if row.kind == "parameter" else _ICON_ACTION
        icon_rect = QRect(rect.left() + 6, rect.top() + (rect.height() - icon) // 2, icon, icon)
        self._paint_icon(painter, icon_rect, row)
        title_font, detail_font = self._row_fonts()
        title_metrics, detail_metrics = QFontMetrics(title_font), QFontMetrics(detail_font)
        left = icon_rect.right() + 9
        right = rect.right() - 11
        if row.has_offer and (selected or hovered):
            self._paint_grip(painter, QPointF(right - 2, rect.center().y() + 0.5), tones)
            right -= 12
        count = self._usage.get(row.key, 0)
        text_top = rect.top() + (rect.height() - title_metrics.height() - detail_metrics.height()) // 2
        title_right = right
        if count:
            pill = f"{count}×"
            pill_width = detail_metrics.horizontalAdvance(pill) + 10
            pill_rect = QRectF(right - pill_width, text_top + 1, pill_width, detail_metrics.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tones.pill_back)
            painter.drawRoundedRect(pill_rect, pill_rect.height() / 2, pill_rect.height() / 2)
            painter.setFont(detail_font)
            painter.setPen(tones.text)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, pill)
            title_right = round(pill_rect.left()) - 6
        painter.setFont(title_font)
        painter.setPen(tones.text)
        painter.drawText(QRect(left, text_top, max(0, title_right - left), title_metrics.height()),
                         Qt.AlignmentFlag.AlignLeft,
                         title_metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, max(0, title_right - left)))
        painter.setFont(detail_font)
        painter.setPen(tones.muted_selected if selected else tones.muted)
        width = max(0, right - left)
        if row.kind == "action" and detail_metrics.horizontalAdvance(row.detail) > width:
            # Markers give way first, and the middle of the SDK type last: start and end identify it.
            detail = detail_metrics.elidedText(row.sdk_type, Qt.TextElideMode.ElideMiddle, width)
        else:
            detail = detail_metrics.elidedText(row.detail, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(left, text_top + title_metrics.height(), width, detail_metrics.height()),
                         Qt.AlignmentFlag.AlignLeft, detail)

    @staticmethod
    def _paint_grip(painter: QPainter, center: QPointF, tones: _Tones) -> None:
        """Six dots: this row can be dragged. Parent rows without an offer never show them."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tones.icon_mark)
        for x in (-2.0, 2.0):
            for y in (-4.0, 0.0, 4.0):
                painter.drawEllipse(center + QPointF(x, y), 1.1, 1.1)

    def _paint_icon(self, painter: QPainter, rect: QRect, row: _Row) -> None:
        ratio = self.devicePixelRatioF()
        painter.drawPixmap(rect.topLeft(), self._icon_pixmap(row, rect.width(), ratio))

    def _icon_pixmap(self, row: _Row, size: int, ratio: float) -> QPixmap:
        image = self._images.get(row.key)
        cache_key = (row.key if image is not None else row.sdk_type, image is not None, size, ratio)
        cached = self._pixmaps.get(cache_key)
        if cached is not None:
            return cached
        pixmap = QPixmap(round(size * ratio), round(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, size, size), 5, 5)
        painter.fillPath(clip, self.tones().icon_back)
        if image is not None:
            painter.setClipPath(clip)
            scaled = image.scaled(round(size * ratio), round(size * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            target = QRectF((size - scaled.width() / ratio) / 2, (size - scaled.height() / ratio) / 2,
                            scaled.width() / ratio, scaled.height() / ratio)
            painter.drawImage(target, scaled)
        else:
            self._paint_fallback(painter, row.sdk_type, size)
        painter.end()
        self._pixmaps[cache_key] = pixmap
        return pixmap

    def _paint_fallback(self, painter: QPainter, sdk_type: str, size: int) -> None:
        """Neutral mark per SDK type: no icon data, no file lookup, always the same result."""
        mark = self.tones().icon_mark
        pen = QPen(mark, max(1.3, size / 18))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        center = size / 2
        unit = size / 30
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if sdk_type == "PluginDynamicCommand":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark)
            painter.drawEllipse(QPointF(center, center), 5 * unit, 5 * unit)
        elif sdk_type == "PluginMultistateDynamicCommand":
            painter.drawEllipse(QPointF(center + 5 * unit, center), 3.5 * unit, 3.5 * unit)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark)
            painter.drawEllipse(QPointF(center - 5 * unit, center), 4 * unit, 4 * unit)
        elif sdk_type == "PluginDynamicAdjustment":
            painter.drawArc(QRectF(center - 8 * unit, center - 8 * unit, 16 * unit, 16 * unit), -45 * 16, 270 * 16)
            painter.drawLine(QPointF(center, center), QPointF(center + 4 * unit, center - 4 * unit))
        elif sdk_type == "ActionEditorCommand":
            for offset, knob in ((-5, -3), (0, 4), (5, -1)):
                painter.drawLine(QPointF(center - 8 * unit, center + offset * unit),
                                 QPointF(center + 8 * unit, center + offset * unit))
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(mark)
                painter.drawEllipse(QPointF(center + knob * unit, center + offset * unit), 2.2 * unit, 2.2 * unit)
                painter.restore()
        else:
            painter.drawRoundedRect(QRectF(center - 6 * unit, center - 6 * unit, 12 * unit, 12 * unit), 2, 2)


__all__ = ["ALL_TYPES_LABEL", "ActionCatalogWidget", "GROUP_ORDERS", "tones_for"]
