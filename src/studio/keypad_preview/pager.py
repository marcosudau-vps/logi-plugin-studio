"""Compact numbered page bar below the device. It only shows and requests pages.

The active page and the page count always come from the host's frame, so the bar
holds no page state of its own. Sizes are measured from Pagination.png at scale 1.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from studio.keypad_preview.skin import FONT_FAMILY

_LABEL_WIDTH = 71.0
_CELL_WIDTH = 42.0
_GAP_WIDTH = 26.0
_HEIGHT = 44.0
_MIN_SCALE = 0.62       # Below this the digits would stop being comfortably readable.
_BORDER = "#666666"
_CHROME = "#333333"
_CHROME_HOVER = "#4a4a4a"
_CELL = "#000000"
_CELL_HOVER = "#262626"
_ACTIVE = "#99f7ec"


@dataclass(frozen=True)
class PageCell:
    kind: str           # "label" | "page" | "gap" | "create"
    page: int | None
    rect: QRectF
    text: str


class PageBar(QWidget):
    pageClicked = Signal(int)
    createClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("keypadPageBar")
        self.setAccessibleName("Seiten")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._page_index = 0
        self._page_count = 1
        self._show_create = False
        self._scale = 1.0
        self._max_width = 1 << 16
        self._cells: list[PageCell] = []
        self._fits = True
        self._hover: PageCell | None = None
        self._pressed: PageCell | None = None

    def set_state(self, page_index: int, page_count: int, show_create: bool, scale: float, max_width: int) -> None:
        self._page_index, self._page_count = page_index, page_count
        self._show_create = show_create
        self._scale = max(_MIN_SCALE, scale)
        self._max_width = max_width
        self._hover = self._pressed = None
        self._rebuild()

    def fits(self) -> bool:
        """False if not even a shortened bar fits; the host of this bar then shows a compact form."""
        return self._fits

    def cells(self) -> tuple[PageCell, ...]:
        return tuple(self._cells)

    def cell_for_page(self, page: int) -> PageCell | None:
        return next((cell for cell in self._cells if cell.kind == "page" and cell.page == page), None)

    def create_cell(self) -> PageCell | None:
        return next((cell for cell in self._cells if cell.kind == "create"), None)

    def page_at(self, point: QPointF) -> int | None:
        cell = self._cell_at(point)
        return cell.page if cell is not None else None

    def _visible_pages(self) -> list[int | None] | None:
        """Pages to show, None marking a gap. Keeps first, last and the pages around the active one."""
        scale = self._scale
        chrome = (_LABEL_WIDTH + (_CELL_WIDTH if self._show_create else 0)) * scale + 2
        room = self._max_width - chrome
        cell, gap = _CELL_WIDTH * scale, _GAP_WIDTH * scale
        count, active = self._page_count, self._page_index
        if count * cell <= room:
            return list(range(count))
        for reach in range(count, -1, -1):
            shown = sorted({0, count - 1, *range(max(0, active - reach), min(count, active + reach + 1))})
            layout: list[int | None] = []
            for page in shown:
                if layout and page - layout[-1] > 1:
                    layout.append(None)
                layout.append(page)
            width = sum(gap if entry is None else cell for entry in layout)
            if width <= room:
                return layout
        return None

    def _rebuild(self) -> None:
        pages = self._visible_pages()
        self._fits = pages is not None
        self._cells = []
        if pages is None:
            self.setFixedSize(0, 0)
            return
        scale = self._scale
        height = round(_HEIGHT * scale)
        x = 1.0
        inner = height - 2

        def add(kind: str, page: int | None, width: float, text: str) -> None:
            nonlocal x
            self._cells.append(PageCell(kind, page, QRectF(x, 1, width, inner), text))
            x += width

        add("label", None, _LABEL_WIDTH * scale, "Seiten")
        for entry in pages:
            if entry is None:
                add("gap", None, _GAP_WIDTH * scale, "…")
            else:
                add("page", entry, _CELL_WIDTH * scale, str(entry + 1))
        if self._show_create:
            add("create", None, _CELL_WIDTH * scale, "+")
        self.setFixedSize(QSize(round(x + 1), height))
        self.update()

    def _cell_at(self, point: QPointF) -> PageCell | None:
        return next((cell for cell in self._cells if cell.rect.contains(point)), None)

    def sizeHint(self) -> QSize:
        return self.size()

    def _text_font(self, cell: PageCell) -> QFont:
        font = QFont(FONT_FAMILY)
        font.setPixelSize(max(10, round((17 if cell.kind == "label" else 18) * self._scale)))
        font.setWeight(QFont.Weight.DemiBold)
        font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
        return font

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 5 * self._scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_CELL))
        painter.drawRoundedRect(frame, radius, radius)
        painter.save()
        clip = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setClipRect(clip)
        for cell in self._cells:
            active = cell.kind == "page" and cell.page == self._page_index
            chrome = cell.kind in ("label", "create")
            hovered = cell == self._hover and cell.kind in ("page", "create") and not active
            fill = _ACTIVE if active else (_CHROME_HOVER if hovered else _CHROME) if chrome else _CELL_HOVER if hovered else _CELL
            painter.fillRect(cell.rect, QColor(fill))
            painter.setPen(QColor("#000000" if active else "#ffffff"))
            if cell.kind == "create":
                # Drawn, because a text plus sits visibly below the middle of the cell.
                center, arm = cell.rect.center(), 7.5 * self._scale
                painter.setPen(QPen(QColor("#ffffff"), max(1.5, 2 * self._scale)))
                painter.drawLine(center - QPointF(arm, 0), center + QPointF(arm, 0))
                painter.drawLine(center - QPointF(0, arm), center + QPointF(0, arm))
                continue
            painter.setFont(self._text_font(cell))
            painter.drawText(cell.rect, int(Qt.AlignmentFlag.AlignCenter), cell.text)
        painter.setPen(QPen(QColor(_BORDER), 1))
        for cell in self._cells[:-1]:
            line = round(cell.rect.right()) - 0.5
            painter.drawLine(QPointF(line, 1), QPointF(line, self.height() - 1))
        painter.restore()
        painter.setPen(QPen(QColor(_BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, radius, radius)

    def mouseMoveEvent(self, event) -> None:
        cell = self._cell_at(event.position())
        if cell != self._hover:
            self._hover = cell
            self.update()
            self.setCursor(Qt.CursorShape.PointingHandCursor if cell is not None and cell.kind in ("page", "create")
                           else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._pressed = self._cell_at(event.position()) if event.button() == Qt.MouseButton.LeftButton else None

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        if pressed is None or event.button() != Qt.MouseButton.LeftButton or self._cell_at(event.position()) != pressed:
            return
        if pressed.kind == "create":
            self.createClicked.emit()
        elif pressed.kind == "page":
            self.pageClicked.emit(pressed.page)

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            cell = self._cell_at(QPointF(event.pos()))
            text = ""
            if cell is not None and cell.kind == "page":
                text = f"Seite {cell.page + 1} von {self._page_count}"
            elif cell is not None and cell.kind == "create":
                text = "Neue Seite beantragen"
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)
