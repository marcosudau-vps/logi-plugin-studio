"""Table model of the problems panel: one flat, filtered and sorted view of source snapshots.

Holds ``core.errors.Diagnostic`` instances by reference for as long as the view lives.
A ``ProblemRow`` is private display data around one instance (with precomputed search
and sort keys); it is no replacement for the instance and is never persisted.

Filtering and sorting run in plain Python on precomputed keys instead of a
``QSortFilterProxyModel``: that proxy would call back into Python for every comparison,
and this keeps a keystroke in the millisecond range even with many thousand rows.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QIcon

from core.errors import Diagnostic

COLUMN_TITLES = ("Schwere", "Code", "Quelle", "Pfad", "Meldung")
COL_SEVERITY, COL_CODE, COL_SOURCE, COL_PATH, COL_MESSAGE = range(5)

# Severity filter categories. Only the exact Diagnostic values count as ERROR or WARNING,
# the same comparison core.validate.is_valid uses; everything else stays "further" under its own name.
ALL = "ALL"
ERROR = "ERROR"
WARNING = "WARNING"
OTHER = "OTHER"
_RANK = {ERROR: 0, WARNING: 1, OTHER: 2}

_DISPLAY_LIMIT = 400  # The table shows one line. The full original stays in the detail view and on the clipboard.
_TOOLTIP_LIMIT = 2000
_DIGITS = re.compile(r"([0-9]{1,18})")  # Bounded: int() refuses digit runs beyond 4300 characters.
_LINE_BREAKS = re.compile(r"\r\n|[\r\n\t\v\f\u0085  ]")


def text_of(value: Any) -> str:
    """Display text of one Diagnostic field. Diagnostic does not check types at run time."""
    return value if isinstance(value, str) else str(value)


def fold(text: str) -> str:
    """Comparison form only, never shown: composed and case-insensitive, 'ß' also matches 'SS'."""
    return unicodedata.normalize("NFC", text).casefold()


def natural_key(text: str) -> tuple:
    """So that /components/2 sorts before /components/10."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part)
                 for part in _DIGITS.split(fold(text)) if part)


def category_of(severity: str) -> str:
    return severity if severity in (ERROR, WARNING) else OTHER


def plain_tooltip(text: str) -> str:
    """Foreign text is never markup: Qt would otherwise guess rich text from its content."""
    return f"<qt><span style='white-space:pre-wrap'>{html.escape(text)}</span></qt>"


def one_line(text: str) -> str:
    """Display form for one table row. Only the view is shortened, the Diagnostic is not."""
    shown = _LINE_BREAKS.sub(lambda match: "  " if match.group() == "\t" else " ↵ ", text)
    return shown if len(shown) <= _DISPLAY_LIMIT else shown[:_DISPLAY_LIMIT] + "…"


class ProblemRow:
    """One diagnostic of one source snapshot. Identity is the object: same text from two sources stays two rows."""

    __slots__ = ("source", "revision", "diagnostic", "ordinal", "identity", "code", "path", "message", "severity",
                 "category", "needle", "base_key", "column_keys", "shown_message")

    def __init__(self, source: str, revision: str | None, diagnostic: Diagnostic, ordinal: int, occurrence: int) -> None:
        self.source = source
        self.revision = revision
        self.diagnostic = diagnostic
        self.ordinal = ordinal
        self.code = text_of(diagnostic.code)
        self.path = text_of(diagnostic.path)
        self.message = text_of(diagnostic.message)
        self.severity = text_of(diagnostic.severity)
        self.category = category_of(self.severity)
        self.identity = (source, self.code, self.path, self.message, self.severity, occurrence)
        self.needle = "\n".join(fold(part) for part in (self.code, self.path, self.message, source))
        rank = _RANK[self.category]
        severity_key = (rank, fold(self.severity))
        path_key = natural_key(self.path)
        self.column_keys = (severity_key, fold(self.code), fold(source), path_key, fold(self.message))
        self.base_key = (severity_key, fold(source), source, path_key,
                         tuple(text_of(part) for part in diagnostic.sort_key()), ordinal)
        self.shown_message = one_line(self.message)

    def label(self) -> str:
        return f"{self.source} · Stand: {self.revision}" if self.revision else self.source

    def as_dict(self) -> dict[str, Any]:
        """Export form: the Diagnostic's own dictionary plus the host's display channel."""
        return {"source": self.source, "revision": self.revision, **self.diagnostic.as_dict()}


class _Snapshot:
    __slots__ = ("revision", "rows", "by_identity")

    def __init__(self, source: str, revision: str | None, diagnostics: Sequence[Diagnostic]) -> None:
        self.revision = revision
        self.rows: list[ProblemRow] = []
        self.by_identity: dict[tuple, ProblemRow] = {}
        seen: dict[tuple, int] = {}
        for ordinal, diagnostic in enumerate(diagnostics):
            value = (text_of(diagnostic.code), text_of(diagnostic.path), text_of(diagnostic.message), text_of(diagnostic.severity))
            occurrence = seen.get(value, 0)
            seen[value] = occurrence + 1
            row = ProblemRow(source, revision, diagnostic, ordinal, occurrence)
            self.rows.append(row)
            self.by_identity[row.identity] = row


def entry_text(row: ProblemRow) -> str:
    """One entry as a readable block with the complete original message."""
    return (f"{row.severity} {row.code}\nQuelle: {row.label()}\nPfad: {row.path}\nMeldung: {row.message}")


def rows_as_table(rows: Iterable[ProblemRow]) -> str:
    """Tab-separated with a header line; line breaks in a field stay readable through CSV quoting."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect="excel-tab", lineterminator="\n")
    writer.writerow(COLUMN_TITLES)
    for row in rows:
        writer.writerow((row.severity, row.code, row.source, row.path, row.message))
    return buffer.getvalue()


def rows_as_json(rows: Iterable[ProblemRow]) -> str:
    return json.dumps([row.as_dict() for row in rows], ensure_ascii=False, indent=2, default=str)


class ProblemsTableModel(QAbstractTableModel):
    RowRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._snapshots: dict[str, _Snapshot] = {}
        self._base: list[ProblemRow] = []
        self._rows: list[ProblemRow] = []
        self._positions: dict[int, int] = {}
        self._tokens: tuple[str, ...] = ()
        self._category = ALL
        self._sort_column = COL_SEVERITY
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._counts = {ERROR: 0, WARNING: 0, OTHER: 0}
        self._icons: dict[str, QIcon] = {}
        self._codes: set[str] = set()

    # ------------------------------------------------------------------ Qt model

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole and 0 <= section < len(COLUMN_TITLES):
            return COLUMN_TITLES[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row.shown_message if column == COL_MESSAGE else one_line(self._full_text(row, column))
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icons.get(row.category) if column == COL_SEVERITY else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row, column)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self._full_text(row, column)[:_TOOLTIP_LIMIT]
        if role == self.RowRole:
            return row
        return None

    @staticmethod
    def _full_text(row: ProblemRow, column: int) -> str:
        return (row.severity, row.code, row.source, row.path, row.message)[column]

    def _tooltip(self, row: ProblemRow, column: int) -> str:
        text = row.label() if column == COL_SOURCE else self._full_text(row, column)
        if len(text) > _TOOLTIP_LIMIT:
            text = text[:_TOOLTIP_LIMIT] + "…\n(Vollständiger Text im Detailbereich)"
        return plain_tooltip(text)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Keeps the selection through Qt's persistent indexes. Equal keys keep the deterministic base order."""
        if not 0 <= column < len(COLUMN_TITLES):
            return
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        held = [self._rows[index.row()] for index in persistent]
        self._rows = self._sorted(self._rows)
        self._index_positions()
        self.changePersistentIndexList(persistent, [self.index(self._positions[id(row)], index.column())
                                                    for row, index in zip(held, persistent)])
        self.layoutChanged.emit()

    # ------------------------------------------------------------------ snapshots

    def replace_source(self, source: str, diagnostics: Sequence[Diagnostic], revision: str | None) -> None:
        snapshot = _Snapshot(source, revision, diagnostics)
        self._rebuild(lambda: self._snapshots.__setitem__(source, snapshot))

    def remove_source(self, source: str) -> None:
        self._rebuild(lambda: self._snapshots.pop(source, None))

    def clear(self) -> None:
        self._rebuild(self._snapshots.clear)

    def set_filters(self, tokens: tuple[str, ...], category: str) -> None:
        def change() -> None:
            self._tokens = tokens
            self._category = category
        self._rebuild(change, base_changed=False)

    def _rebuild(self, change, *, base_changed: bool = True) -> None:
        self.beginResetModel()
        change()
        if base_changed:
            self._base = sorted((row for snapshot in self._snapshots.values() for row in snapshot.rows),
                                key=lambda row: row.base_key)
            self._counts = {ERROR: 0, WARNING: 0, OTHER: 0}
            for row in self._base:
                self._counts[row.category] += 1
            self._codes = {row.code for row in self._base}
        self._rows = self._sorted([row for row in self._base if self._accepts(row)])
        self._index_positions()
        self.endResetModel()

    def _accepts(self, row: ProblemRow) -> bool:
        if self._category != ALL and row.category != self._category:
            return False
        return all(token in row.needle for token in self._tokens)

    def _sorted(self, rows: list[ProblemRow]) -> list[ProblemRow]:
        # Python's sort is stable also in reverse, so ties stay in base order in both directions.
        column = self._sort_column
        rows = sorted(rows, key=lambda row: row.base_key)
        rows.sort(key=lambda row: row.column_keys[column], reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
        return rows

    def _index_positions(self) -> None:
        self._positions = {id(row): position for position, row in enumerate(self._rows)}

    # ------------------------------------------------------------------ queries

    def rows(self) -> list[ProblemRow]:
        return list(self._rows)

    def all_rows(self) -> list[ProblemRow]:
        return list(self._base)

    def row_at(self, position: int) -> ProblemRow | None:
        return self._rows[position] if 0 <= position < len(self._rows) else None

    def position_of(self, row: ProblemRow | None) -> int | None:
        """Position of exactly this object; None once its snapshot is gone or a filter hides it."""
        if row is None:
            return None
        position = self._positions.get(id(row))
        return position if position is not None and self._rows[position] is row else None

    def live_row(self, identity: tuple | None) -> ProblemRow | None:
        """The row of the current snapshot that is the same message; never a neighbouring one."""
        if identity is None:
            return None
        snapshot = self._snapshots.get(identity[0])
        return None if snapshot is None else snapshot.by_identity.get(identity)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def total(self) -> int:
        return len(self._base)

    def sources(self) -> list[str]:
        return sorted(self._snapshots)

    def distinct_codes(self) -> set[str]:
        return self._codes

    def has_source(self, source: str) -> bool:
        return source in self._snapshots

    def revision_of(self, source: str) -> str | None:
        snapshot = self._snapshots.get(source)
        return None if snapshot is None else snapshot.revision

    def source_rows(self, source: str) -> list[ProblemRow]:
        snapshot = self._snapshots.get(source)
        return [] if snapshot is None else list(snapshot.rows)

    def set_icons(self, icons: dict[str, QIcon]) -> None:
        self._icons = icons
        if self._rows:
            self.dataChanged.emit(self.index(0, COL_SEVERITY), self.index(len(self._rows) - 1, COL_SEVERITY),
                                  [Qt.ItemDataRole.DecorationRole])
