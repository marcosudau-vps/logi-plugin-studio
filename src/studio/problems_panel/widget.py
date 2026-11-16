"""Problems panel: shows, filters and copies diagnostics delivered by the host.

The widget is a pure presentation. It creates no validation rules, reads no project,
changes no files and starts nothing. ``Diagnostic`` values are kept by reference for
as long as the view lives and are never rewritten; ``path`` is not interpreted.
Navigation is a wish: ``diagnosticActivated`` carries the original instance and the host
decides whether and where to go. Source names and revisions are opaque host data.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter, QPainterPath, QPalette, QPen,
                           QPixmap, QPolygonF, QShortcut, QTextCharFormat, QTextCursor, QTextOption)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QStackedLayout,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget)

from core.errors import Diagnostic
from studio.problems_panel.model import (ALL, COL_CODE, COL_MESSAGE, COL_PATH, COL_SEVERITY, COL_SOURCE, ERROR, OTHER, WARNING,
                                         ProblemRow, ProblemsTableModel, entry_text, fold, plain_tooltip, rows_as_json,
                                         rows_as_table)

DEFAULT_SOURCE = "project"
SEVERITY_ALL = ALL
SEVERITY_ERROR = ERROR
SEVERITY_WARNING = WARNING
SEVERITY_OTHER = OTHER

_SEVERITY_ALIASES = {"all": ALL, "alle": ALL, "error": ERROR, "fehler": ERROR, "warning": WARNING, "warnungen": WARNING,
                     "other": OTHER, "weitere": OTHER}
_STACK_BELOW = 680  # Search below the severity buttons.
_COMPACT_BELOW = 440  # Severity buttons show symbol and number; the full text stays in tooltip and accessible name.
_SIDE_DETAIL_FROM = 960  # Detail view beside instead of below the table.
_ICON_SIZE = 14
_MESSAGE_MINIMUM = 180


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                           a.greenF() + (b.greenF() - a.greenF()) * amount,
                           a.blueF() + (b.blueF() - a.blueF()) * amount)


def severity_color(category: str, palette: QPalette) -> QColor:
    """Marks use fixed hues for meaning, in a light or dark version chosen for the host's background."""
    dark = palette.color(QPalette.ColorRole.Base).lightnessF() < 0.5
    if category == ERROR:
        return QColor("#ff7b72" if dark else "#c62828")
    if category == WARNING:
        return QColor("#e3b341" if dark else "#9a6700")
    return _mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.70)


def _paint_mark(painter: QPainter, category: str, rect: QRectF, color: QColor) -> None:
    """Shape carries the meaning as well, so the severity does not depend on color alone."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = rect.width() / 14
    cut = QColor(255, 255, 255) if color.lightnessF() < 0.5 else QColor(24, 24, 24)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    center_x = rect.center().x()
    if category == WARNING:
        painter.drawPolygon(QPolygonF([QPointF(center_x, rect.top() + 0.5 * unit),
                                       QPointF(rect.right() - 0.2 * unit, rect.bottom() - 0.8 * unit),
                                       QPointF(rect.left() + 0.2 * unit, rect.bottom() - 0.8 * unit)]))
        painter.setBrush(cut)
        painter.drawRoundedRect(QRectF(center_x - 0.8 * unit, rect.top() + 4.6 * unit, 1.6 * unit, 4.6 * unit), 0.6 * unit, 0.6 * unit)
        painter.drawEllipse(QPointF(center_x, rect.top() + 11 * unit), 0.95 * unit, 0.95 * unit)
        return
    painter.drawEllipse(rect.adjusted(0.5 * unit, 0.5 * unit, -0.5 * unit, -0.5 * unit))
    painter.setBrush(cut)
    if category == ERROR:
        painter.drawRoundedRect(QRectF(center_x - 0.95 * unit, rect.top() + 2.9 * unit, 1.9 * unit, 5.2 * unit), 0.7 * unit, 0.7 * unit)
        painter.drawEllipse(QPointF(center_x, rect.top() + 10.3 * unit), 1.05 * unit, 1.05 * unit)
    else:
        painter.drawEllipse(QPointF(center_x, rect.top() + 3.9 * unit), 1.05 * unit, 1.05 * unit)
        painter.drawRoundedRect(QRectF(center_x - 0.95 * unit, rect.top() + 5.9 * unit, 1.9 * unit, 5.2 * unit), 0.7 * unit, 0.7 * unit)


def _mark_icon(category: str, palette: QPalette) -> QIcon:
    """On a selected row the mark takes the highlight text color: a red mark on blue would be hard to see."""
    icon = QIcon()
    variants = ((QIcon.Mode.Normal, severity_color(category, palette)),
                (QIcon.Mode.Selected, palette.color(QPalette.ColorRole.HighlightedText)))
    for mode, color in variants:
        for scale in (1.0, 1.25, 1.5, 2.0, 3.0):
            side = round(_ICON_SIZE * scale)
            pixmap = QPixmap(side, side)
            pixmap.fill(Qt.GlobalColor.transparent)
            pixmap.setDevicePixelRatio(scale)
            painter = QPainter(pixmap)
            _paint_mark(painter, category, QRectF(0, 0, _ICON_SIZE, _ICON_SIZE), color)
            painter.end()
            icon.addPixmap(pixmap, mode)
    return icon


class _SeverityButton(QAbstractButton):
    """Counter and severity filter in one: ``0 Fehler`` stays the unfiltered snapshot count."""

    def __init__(self, category: str, singular: str, plural: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.category = category
        self._singular = singular
        self._plural = plural
        self._count = 0
        self._compact = False
        self._hovered = False
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._sync_text()

    def set_count(self, count: int) -> None:
        self._count = count
        self._sync_text()

    def set_compact(self, compact: bool) -> None:
        if compact != self._compact:
            self._compact = compact
            self.updateGeometry()
            self.update()

    def full_text(self) -> str:
        count = _number(self._count)
        if self.category == ALL:
            return f"{self._plural} {count}"
        return f"{count} {self._singular if self._count == 1 else self._plural}"

    def _shown_text(self) -> str:
        if self.category == ALL:
            return self.full_text()
        return _number(self._count) if self._compact else self.full_text()

    def _sync_text(self) -> None:
        self.setText(self.full_text())
        self.setAccessibleName(self.full_text())
        self.setToolTip(f"Filter: {self.full_text()}")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        icon = 0 if self.category == ALL else _ICON_SIZE + 6
        return QSize(metrics.horizontalAdvance(self._shown_text()) + icon + 18, max(26, metrics.height() + 10))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def event(self, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self._hovered = event.type() == QEvent.Type.HoverEnter
            self.update()
        return super().event(event)

    def paintEvent(self, event) -> None:
        palette = self.palette()
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        accent = palette.color(QPalette.ColorRole.Highlight)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            painter.setPen(QPen(_mix(window, accent, 0.65), 1))
            painter.setBrush(_mix(window, accent, 0.24))
        elif self._hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_mix(window, text, 0.09))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area, 5, 5)
        if self.hasFocus():
            painter.setPen(QPen(_mix(accent, text, 0.35), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 4, 4)
        left = 9
        if self.category != ALL:
            color = severity_color(self.category, palette) if self._count else _mix(window, text, 0.45)
            top = (self.height() - _ICON_SIZE) / 2
            _paint_mark(painter, self.category, QRectF(left, top, _ICON_SIZE, _ICON_SIZE), color)
            left += _ICON_SIZE + 6
        painter.setPen(text)
        painter.drawText(QRect(left, 0, self.width() - left - 6, self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._shown_text())


class _ElidedLabel(QLabel):
    """Plain text that never widens the panel; the complete text stays in the tooltip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(plain_tooltip(text) if text else "")
        self.setAccessibleName(text)
        self._elide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())))


class _SearchField(QLineEdit):
    leaveDown = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down:
            self.leaveDown.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CellDelegate(QStyledItemDelegate):
    """Paths lose their middle, other text its end. Focus is shown for the whole row, not one cell."""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle if index.column() == COL_PATH else Qt.TextElideMode.ElideRight
        option.decorationSize = QSize(_ICON_SIZE, _ICON_SIZE)
        option.state &= ~QStyle.StateFlag.State_HasFocus

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        view = self.parent()
        if not view.hasFocus() or view.currentIndex().row() != index.row():
            return
        palette = option.palette
        painter.save()
        painter.setPen(QPen(_mix(palette.color(QPalette.ColorRole.Highlight), palette.color(QPalette.ColorRole.Text), 0.45), 1))
        rect = option.rect.adjusted(0, 0, -1, -1)
        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if index.column() == view.model().columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())
        if index.column() == 0:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        painter.restore()


class _ProblemsTable(QTableView):
    """Own activation path: QAbstractItemView.activated can fire on a single click on some styles."""

    rowActivated = Signal(int)
    copyRequested = Signal()
    contextMenuRequested = Signal(object, QPoint)  # position or None, global point
    viewportResized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("problemsTable")
        self.setItemDelegate(_CellDelegate(self))
        self.setAccessibleName("Problemliste")
        self.setAccessibleDescription("Enter oder Doppelklick fordert beim Host die Navigation zur markierten Meldung an.")
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTabKeyNavigation(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setCornerButtonEnabled(False)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        rows = self.verticalHeader()
        rows.hide()
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(True)
        header.setSectionsMovable(False)
        header.setMinimumSectionSize(44)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewportResized.emit()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            event.accept()
            self.copyRequested.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            if not event.isAutoRepeat() and self.currentIndex().isValid():
                self.rowActivated.emit(self.currentIndex().row())
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        activate = event.button() == Qt.MouseButton.LeftButton and index.isValid()
        row = index.row()
        super().mouseDoubleClickEvent(event)
        if activate:
            self.rowActivated.emit(row)

    def contextMenuEvent(self, event) -> None:
        event.accept()
        if event.reason() == event.Reason.Mouse:
            index = self.indexAt(event.pos())
            self.contextMenuRequested.emit(index.row() if index.isValid() else None, event.globalPos())
            return
        index = self.currentIndex()
        anchor = self.visualRect(index).center() if index.isValid() else self.viewport().rect().center()
        self.contextMenuRequested.emit(index.row() if index.isValid() else None, self.viewport().mapToGlobal(anchor))

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.viewport().update()

    def currentChanged(self, current, previous) -> None:
        super().currentChanged(current, previous)
        self.viewport().update()


def _number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _messages(count: int) -> str:
    return f"{_number(count)} Meldung" if count == 1 else f"{_number(count)} Meldungen"


class ProblemsPanelWidget(QWidget):
    """Flat view of the diagnostics of any number of independent host sources."""

    diagnosticActivated = Signal(object)  # exactly the original Diagnostic; the host decides on any navigation
    diagnosticSelected = Signal(object)  # the original Diagnostic or None; user selection only, a display intent

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("problemsPanel")
        self.setAccessibleName("Probleme")
        self._model = ProblemsTableModel(self)
        self._wanted: ProblemRow | None = None  # Selection, also while a filter hides it.
        self._programmatic = 0
        self._severity = ALL
        self._columns_fitted_by_user = False
        self._fitting_columns = False
        self._theming = False
        self._build_ui()
        self.problems_table.setModel(self._model)
        self.problems_table.setSortingEnabled(True)
        self.problems_table.horizontalHeader().setSortIndicator(COL_SEVERITY, Qt.SortOrder.AscendingOrder)
        self.problems_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.problems_table.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.problems_table.viewportResized.connect(self._fit_columns)
        self._apply_theme()
        self._fit_row_height()
        self._apply_responsive_layout()
        self._sync_chrome()

    # ------------------------------------------------------------------ public API

    def set_diagnostics(self, diagnostics: Sequence[Diagnostic]) -> None:
        """Convenience: replaces only the default channel ``project``."""
        self.set_source_diagnostics(DEFAULT_SOURCE, diagnostics)

    def set_source_diagnostics(self, source: str, diagnostics: Sequence[Diagnostic], *, revision: str | None = None) -> None:
        """Replaces the snapshot of exactly one source. A refused call changes nothing."""
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        if not source.strip():
            raise ValueError("source must not be empty")
        if revision is not None and not isinstance(revision, str):
            raise TypeError("revision must be a string or None")
        snapshot = tuple(diagnostics)
        for item in snapshot:
            if not isinstance(item, Diagnostic):
                raise TypeError(f"Expected core.errors.Diagnostic, got {type(item).__name__}")
        self._change_rows(lambda: self._model.replace_source(source, snapshot, revision))

    def remove_source(self, source: str) -> None:
        if self._model.has_source(source):
            self._change_rows(lambda: self._model.remove_source(source))

    def clear(self) -> None:
        """Removes all sources. Search text and severity filter are view settings and stay."""
        self._change_rows(self._model.clear)

    def set_filter(self, text: str) -> None:
        """Sets the search field. All words must occur in code, path, message or source, ignoring case."""
        if not isinstance(text, str):
            raise TypeError("filter text must be a string")
        self.search_field.setText(text)

    def set_severity_filter(self, severity: str) -> None:
        """``ALL``, ``ERROR``, ``WARNING``, ``OTHER`` or the visible names ``Alle``, ``Fehler``, ``Warnungen``, ``Weitere``."""
        category = _SEVERITY_ALIASES.get(severity.casefold()) if isinstance(severity, str) else None
        if category is None:
            raise ValueError(f"Unknown severity filter {severity!r}")
        self.severity_buttons[category].setChecked(True)

    def reset_filters(self) -> None:
        self.search_field.clear()
        self.severity_buttons[ALL].setChecked(True)

    # ------------------------------------------------------------------ queries

    def sources(self) -> list[str]:
        return self._model.sources()

    def source_revision(self, source: str) -> str | None:
        return self._model.revision_of(source)

    def diagnostics(self, source: str | None = None) -> list[Diagnostic]:
        """Original instances: of one source in delivered order, otherwise of all in base order."""
        rows = self._model.all_rows() if source is None else self._model.source_rows(source)
        return [row.diagnostic for row in rows]

    def visible_entries(self) -> list[tuple[str, Diagnostic]]:
        """``(source, original instance)`` per visible row, in display order."""
        return [(row.source, row.diagnostic) for row in self._model.rows()]

    def counts(self) -> dict[str, int]:
        """Unfiltered counts of the current snapshots: keys ``ERROR``, ``WARNING``, ``OTHER``."""
        return self._model.counts()

    def filter_text(self) -> str:
        return self.search_field.text()

    def severity_filter(self) -> str:
        return self._severity

    def selected_diagnostic(self) -> Diagnostic | None:
        row = self._selected_row()
        return None if row is None else row.diagnostic

    def selected_source(self) -> str | None:
        row = self._selected_row()
        return None if row is None else row.source

    def empty_state(self) -> str:
        """``""`` with visible rows, ``"none"`` without any diagnostics, ``"no_match"`` when only filters hide them."""
        if self._model.total() == 0:
            return "none"
        return "" if self._model.rowCount() else "no_match"

    def detail_text(self) -> str:
        return self.detail_view.toPlainText()

    def build_context_menu(self, position: int | None = None) -> QMenu:
        """The menu of one visible table position, or of the empty table area. Nothing is copied by building it."""
        row = self._model.row_at(position) if position is not None else None
        menu = QMenu(self)
        menu.setObjectName("problemsContextMenu")
        activate = menu.addAction("Navigation anfordern", lambda: self._activate_row(row))
        activate.setShortcut(QKeySequence(Qt.Key.Key_Return))
        activate.setEnabled(row is not None)
        menu.addSeparator()
        entry = menu.addAction("Eintrag kopieren", lambda: self._copy_entry(row))
        entry.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy))
        entry.setEnabled(row is not None)
        code = menu.addAction("Fehlercode kopieren", lambda: self._copy_field(row, "code"))
        code.setEnabled(row is not None and bool(row.code))
        path = menu.addAction("Pfad kopieren", lambda: self._copy_field(row, "path"))
        path.setEnabled(row is not None and bool(row.path))
        menu.addSeparator()
        count = self._model.rowCount()
        visible = menu.addAction(f"Alle gefilterten Einträge kopieren ({_number(count)})", self._copy_visible_table)
        visible.setEnabled(count > 0)
        as_json = menu.addAction("Gefilterte Einträge als JSON kopieren", self._copy_visible_json)
        as_json.setEnabled(count > 0)
        return menu

    # ------------------------------------------------------------------ construction

    def _build_ui(self) -> None:
        self.severity_buttons: dict[str, _SeverityButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.severity_row = QHBoxLayout()
        self.severity_row.setContentsMargins(0, 0, 0, 0)
        self.severity_row.setSpacing(2)
        names = ((ALL, "Alle", "Alle"), (ERROR, "Fehler", "Fehler"), (WARNING, "Warnung", "Warnungen"), (OTHER, "Weitere", "Weitere"))
        for category, singular, plural in names:
            button = _SeverityButton(category, singular, plural, self)
            button.setObjectName(f"problemsSeverity{category.title()}")
            group.addButton(button)
            self.severity_buttons[category] = button
            self.severity_row.addWidget(button)
            button.toggled.connect(lambda checked, value=category: checked and self._on_severity_chosen(value))
        self.severity_row.addStretch(1)
        self.severity_buttons[ALL].setChecked(True)
        self._severity_group = group

        self.search_field = _SearchField(self)
        self.search_field.setObjectName("problemsSearch")
        self.search_field.setPlaceholderText("Suchen in Code, Pfad, Meldung, Quelle")
        self.search_field.setAccessibleName("Probleme durchsuchen")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(120)
        self.search_field.textChanged.connect(self._on_search_changed)
        self.search_field.leaveDown.connect(self._focus_results)
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._focus_search)

        self.filter_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.filter_row.setContentsMargins(0, 0, 0, 0)
        self.filter_row.setSpacing(8)
        self.filter_row.addLayout(self.severity_row)
        self.filter_row.addWidget(self.search_field, 1)

        self.summary_label = _ElidedLabel(self)
        self.summary_label.setObjectName("problemsSummary")

        self.problems_table = _ProblemsTable(self)
        self.problems_table.rowActivated.connect(self._activate_position)
        self.problems_table.copyRequested.connect(lambda: self._copy_entry(self._selected_row()))
        self.problems_table.contextMenuRequested.connect(self._show_context_menu)

        self.empty_title = QLabel(self)
        self.empty_title.setObjectName("problemsEmptyTitle")
        self.empty_title.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont(self.empty_title.font())
        title_font.setBold(True)
        self.empty_title.setFont(title_font)
        self.empty_detail = QLabel(self)
        self.empty_detail.setObjectName("problemsEmptyDetail")
        self.empty_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_detail.setWordWrap(True)
        self.empty_reset = QPushButton("Filter zurücksetzen", self)
        self.empty_reset.setObjectName("problemsEmptyReset")
        self.empty_reset.clicked.connect(self.reset_filters)
        self.empty_page = QFrame(self)
        self.empty_page.setObjectName("problemsEmptyPage")
        self.empty_page.setFrameShape(QFrame.Shape.StyledPanel)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setSpacing(6)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_detail)
        empty_layout.addWidget(self.empty_reset, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)

        self.result_stack = QStackedLayout()
        self.result_stack.setContentsMargins(0, 0, 0, 0)
        self.result_stack.addWidget(self.problems_table)
        self.result_stack.addWidget(self.empty_page)
        self.result_host = QWidget(self)
        self.result_host.setLayout(self.result_stack)
        self.result_host.setMinimumSize(120, 72)

        self.detail_view = QPlainTextEdit(self)
        self.detail_view.setObjectName("problemsDetail")
        self.detail_view.setAccessibleName("Details der markierten Meldung")
        self.detail_view.setReadOnly(True)
        self.detail_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.detail_view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.detail_view.setPlaceholderText("Keine Meldung markiert.")
        self.detail_view.setMinimumSize(120, 56)

        self.body_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.body_splitter.setObjectName("problemsSplitter")
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.addWidget(self.result_host)
        self.body_splitter.addWidget(self.detail_view)
        self.body_splitter.setStretchFactor(0, 3)
        self.body_splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(self.filter_row)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.body_splitter, 1)

        self.setTabOrder(self.severity_buttons[OTHER], self.search_field)
        self.setTabOrder(self.search_field, self.problems_table)
        self.setTabOrder(self.problems_table, self.detail_view)

    def sizeHint(self) -> QSize:
        return QSize(920, 340)

    def minimumSizeHint(self) -> QSize:
        return QSize(300, 200)

    # ------------------------------------------------------------------ updates

    def _change_rows(self, change, *, follow_selection: bool = False) -> None:
        """Every row change: keeps or drops the selection and sends no signal.

        Selection follows the same message of the new snapshot (code, path, text, severity
        and repetition within the source). Without such a message nothing stays selected.
        """
        table = self.problems_table
        wanted = self._wanted
        identity = wanted.identity if wanted is not None else None
        scroll = table.verticalScrollBar().value()
        old_position = self._model.position_of(wanted)
        was_on_screen = old_position is not None and table.viewport().rect().intersects(table.visualRect(self._model.index(old_position, 0)))
        self._programmatic += 1
        try:
            change()
            self._wanted = self._model.live_row(identity)
            position = self._model.position_of(self._wanted)
            self._sync_chrome()  # Page first: the table must be current before its layout is used.
            table.doItemsLayout()
            table.verticalScrollBar().setValue(scroll)
            if position is not None:
                index = self._model.index(position, 0)
                table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                                       | QItemSelectionModel.SelectionFlag.Rows)
                if follow_selection or was_on_screen:
                    table.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        finally:
            self._programmatic -= 1
        self._sync_detail()

    def _on_search_changed(self, text: str) -> None:
        self._apply_filters()

    def _on_severity_chosen(self, category: str) -> None:
        if category != self._severity:
            self._severity = category
            self._apply_filters()

    def _apply_filters(self) -> None:
        tokens = tuple(fold(self.search_field.text()).split())
        self._change_rows(lambda: self._model.set_filters(tokens, self._severity), follow_selection=True)

    def _sync_chrome(self) -> None:
        counts = self._model.counts()
        self.severity_buttons[ERROR].set_count(counts[ERROR])
        self.severity_buttons[WARNING].set_count(counts[WARNING])
        self.severity_buttons[OTHER].set_count(counts[OTHER])
        self.severity_buttons[ALL].set_count(self._model.total())
        self.summary_label.set_full_text(self._summary_text())
        state = self.empty_state()
        if state:
            had_focus = self.problems_table.hasFocus()
            self._show_empty(state)
            self.result_stack.setCurrentWidget(self.empty_page)
            if had_focus:
                self.search_field.setFocus()
        else:
            self.result_stack.setCurrentWidget(self.problems_table)
        self.detail_view.setVisible(not state)
        self._fit_columns()

    def _show_empty(self, state: str) -> None:
        if state == "none":
            self.empty_title.setText("Keine Probleme")
            self.empty_detail.setText("Der Host hat für die angezeigten Quellen keine Meldungen geliefert."
                                      if self._model.sources() else "Der Host hat noch keine Prüfergebnisse geliefert.")
            self.empty_reset.hide()
        else:
            self.empty_title.setText("Kein Treffer für Filter")
            self.empty_detail.setText(f"Der Filter blendet alle {_messages(self._model.total())} aus.")
            self.empty_reset.show()

    def _summary_text(self) -> str:
        visible, total = self._model.rowCount(), self._model.total()
        head = _messages(total) if visible == total else f"{_number(visible)} von {_messages(total)}"
        parts = []
        for source in self._model.sources():
            revision = self._model.revision_of(source)
            count = len(self._model.source_rows(source))
            parts.append(f"{source} {_number(count)}" + (f" (Stand: {revision})" if revision else ""))
        return f"{head}  ·  Quellen: {' · '.join(parts)}" if parts else f"{head}  ·  Keine Quelle geliefert"

    # ------------------------------------------------------------------ selection and detail

    def _selected_row(self) -> ProblemRow | None:
        selection = self.problems_table.selectionModel()
        indexes = selection.selectedRows() if selection is not None else []
        return self._model.row_at(indexes[0].row()) if indexes else None

    def _on_selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        if self._programmatic:
            return
        row = self._selected_row()
        self._wanted = row
        self._sync_detail()
        self.diagnosticSelected.emit(None if row is None else row.diagnostic)

    def _sync_detail(self) -> None:
        row = self._selected_row()
        view = self.detail_view
        view.clear()
        if row is None:
            return
        palette = self.palette()
        muted = QTextCharFormat()
        muted.setForeground(_mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.72))
        plain = QTextCharFormat()
        strong = QTextCharFormat()
        strong.setFontWeight(QFont.Weight.Bold)
        cursor = QTextCursor(view.document())
        cursor.insertText(f"{row.severity} · {row.code}\n", strong)
        cursor.insertText("Quelle: ", muted)
        cursor.insertText(row.label() + "\n", plain)
        cursor.insertText("Pfad: ", muted)
        if row.path:
            cursor.insertText(row.path + "\n\n", plain)
        else:
            cursor.insertText("(leer)\n\n", muted)
        cursor.insertText(row.message, plain)
        view.moveCursor(QTextCursor.MoveOperation.Start)

    def _focus_search(self) -> None:
        self.search_field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_field.selectAll()

    def _focus_results(self) -> None:
        if self._model.rowCount() == 0:
            return
        table = self.problems_table
        table.setFocus(Qt.FocusReason.TabFocusReason)  # Qt may set a current row here, but selects nothing.
        if not table.selectionModel().hasSelection():
            table.selectRow(max(0, table.currentIndex().row()))

    # ------------------------------------------------------------------ user intents

    def _activate_position(self, position: int) -> None:
        self._activate_row(self._model.row_at(position))

    def _activate_row(self, row: ProblemRow | None) -> None:
        """Only a row of the current view: the snapshot may have changed while a menu was open."""
        position = self._model.position_of(row)
        if position is None:
            return
        if self._selected_row() is not row:
            self.problems_table.selectRow(position)
            if self._model.position_of(row) is None:  # A host slot replaced the snapshot on selection.
                return
        self.diagnosticActivated.emit(row.diagnostic)

    def _show_context_menu(self, position: int | None, point: QPoint) -> None:
        menu = self.build_context_menu(position)
        menu.exec(point)
        menu.deleteLater()

    def _copy_entry(self, row: ProblemRow | None) -> None:
        if self._model.position_of(row) is not None:
            self._to_clipboard(entry_text(row))

    def _copy_field(self, row: ProblemRow | None, field: str) -> None:
        if self._model.position_of(row) is not None and getattr(row, field):
            self._to_clipboard(getattr(row, field))

    def _copy_visible_table(self) -> None:
        if self._model.rowCount():
            self._to_clipboard(rows_as_table(self._model.rows()))

    def _copy_visible_json(self) -> None:
        if self._model.rowCount():
            self._to_clipboard(rows_as_json(self._model.rows()))

    @staticmethod
    def _to_clipboard(text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    # ------------------------------------------------------------------ layout and theme

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        width = self.width()
        direction = QBoxLayout.Direction.TopToBottom if width < _STACK_BELOW else QBoxLayout.Direction.LeftToRight
        if self.filter_row.direction() != direction:
            self.filter_row.setDirection(direction)
        compact = width < _COMPACT_BELOW
        for button in self.severity_buttons.values():
            button.set_compact(compact)
        orientation = Qt.Orientation.Horizontal if width >= _SIDE_DETAIL_FROM else Qt.Orientation.Vertical
        if self.body_splitter.orientation() != orientation:
            self.body_splitter.setOrientation(orientation)
            total = width if orientation == Qt.Orientation.Horizontal else max(self.height(), 200)
            self.body_splitter.setSizes([total * 7 // 10, total * 3 // 10])

    def _column_widths(self) -> dict[int, tuple[int, int]]:
        """Preferred and smallest width per fixed column, from the current font and the delivered codes and sources."""
        metrics = self.problems_table.fontMetrics()

        def width(text: str) -> int:
            return metrics.horizontalAdvance(text) + 20

        def fitting(texts: set[str], at_least: str, at_most: str) -> int:
            # Only the longest text is measured: this runs on every update and may see thousands of distinct codes.
            return min(max(width(at_least), width(max(texts, key=len, default=""))), width(at_most))

        severity = width("WARNING") + _ICON_SIZE + 6
        return {COL_SEVERITY: (severity, severity),
                COL_CODE: (fitting(self._model.distinct_codes(), "ID_INVALID", "ADAPTER_CAPABILITY_TOO_LONG_X"), width("ID_INVALID")),
                COL_SOURCE: (fitting(set(self._model.sources()), "project", "a_rather_long_source"), width("project")),
                COL_PATH: (width("/views/10/placements/10/component"), width("/components/1"))}

    def _fit_columns(self) -> None:
        """The message keeps the most room. Other columns shrink towards their minimum; then the table scrolls sideways."""
        table = self.problems_table
        if self._columns_fitted_by_user:
            return
        widths = self._column_widths()
        preferred = sum(value[0] for value in widths.values())
        minimum = sum(value[1] for value in widths.values())
        room = table.viewport().width() - _MESSAGE_MINIMUM
        share = 1.0 if room >= preferred else max(0.0, (room - minimum) / max(1, preferred - minimum))
        self._fitting_columns = True
        try:
            for column, (wide, narrow) in widths.items():
                table.setColumnWidth(column, round(narrow + (wide - narrow) * share))
        finally:
            self._fitting_columns = False

    def _on_section_resized(self, column: int, _old: int, _new: int) -> None:
        if not self._fitting_columns and column != COL_MESSAGE:
            self._columns_fitted_by_user = True  # A width the user chose stays for the life of the view.

    def _fit_row_height(self) -> None:
        self.problems_table.verticalHeader().setDefaultSectionSize(max(24, self.problems_table.fontMetrics().height() + 8))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.StyleChange):
            self._apply_theme()
        elif event.type() in (QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange):
            self._fit_row_height()
            self._fit_columns()

    def _apply_theme(self) -> None:
        if self._theming:
            return
        self._theming = True
        try:
            palette = self.palette()
            self._model.set_icons({category: _mark_icon(category, palette) for category in (ERROR, WARNING, OTHER)})
            muted = _mix(palette.color(QPalette.ColorRole.Window), palette.color(QPalette.ColorRole.WindowText), 0.72)
            for label in (self.summary_label, self.empty_detail):
                tinted = QPalette(palette)
                tinted.setColor(QPalette.ColorRole.WindowText, muted)
                label.setPalette(tinted)
            self._sync_detail()
        finally:
            self._theming = False
