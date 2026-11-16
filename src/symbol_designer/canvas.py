"""Square design surface: shows the exact rendered icon plus temporary edit aids."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .ict import GRID, IMAGE, TEXT, IconTemplate
from .render import render_template

HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
           "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
           "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
           "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor}
NAMES = {IMAGE: "Symbol", TEXT: "Text"}
ACCENT = QColor("#00D4C0")
MIN_SIZE = 4
SNAP = 1.5


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class DesignCanvas(QWidget):
    selectionChanged = Signal(object)
    geometryEdited = Signal(str, tuple, bool)
    filesDropped = Signal(list)
    textEditRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("designCanvas")
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.template = IconTemplate()
        self.selected: str | None = None
        self.show_aids = True
        self.show_grid = False
        self.preview_mode = False
        self.lock_aspect = {IMAGE: True, TEXT: False}
        self._drag: dict | None = None
        self._guides: list[tuple[str, float]] = []
        self._drop_active = False

    # geometry helpers
    def icon_rect(self) -> QRectF:
        side = max(40.0, min(self.width(), self.height()) - 24.0)
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def scale(self) -> float:
        return self.icon_rect().width() / GRID

    def to_units(self, point: QPointF) -> QPointF:
        rect = self.icon_rect()
        return QPointF((point.x() - rect.x()) / self.scale(), (point.y() - rect.y()) / self.scale())

    def item_rect(self, kind: str) -> QRectF:
        rect, scale = self.icon_rect(), self.scale()
        x, y, w, h = self.template.area(kind)
        return QRectF(rect.x() + x * scale, rect.y() + y * scale, w * scale, h * scale)

    def kinds(self) -> list[str]:
        return [k for k in (IMAGE, TEXT) if self.template.item(k) is not None]

    def handle_rects(self, kind: str) -> dict[str, QRectF]:
        r = self.item_rect(kind)
        points = {"tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
                  "r": QPointF(r.right(), r.center().y()), "br": r.bottomRight(),
                  "b": QPointF(r.center().x(), r.bottom()), "bl": r.bottomLeft(),
                  "l": QPointF(r.left(), r.center().y())}
        return {k: QRectF(p.x() - 5, p.y() - 5, 10, 10) for k, p in points.items()}

    def items_at(self, point: QPointF) -> list[str]:
        """Item kinds under ``point``, topmost first (ICT list order is the stacking order)."""
        order = list(reversed(self.template.stacking()))
        hits = [k for k in order if self.item_rect(k).adjusted(-3, -3, 3, 3).contains(point)]
        return [k for k in hits if self.template.visible(k) or self.show_aids]

    def editable(self) -> bool:
        return not self.preview_mode and self.isEnabled()

    # selection
    def select(self, kind: str | None) -> None:
        if kind is not None and self.template.item(kind) is None:
            kind = None
        if kind != self.selected:
            self.selected = kind
            self.selectionChanged.emit(kind)
        self.update()

    def cycle_selection(self, point: QPointF | None = None) -> str | None:
        candidates = self.items_at(point) if point is not None else list(reversed(self.template.stacking()))
        if not candidates:
            return self.selected
        index = candidates.index(self.selected) + 1 if self.selected in candidates else 0
        self.select(candidates[index % len(candidates)])
        return self.selected

    # painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.icon_rect()
        cell = 8
        painter.save()
        painter.setClipRect(rect)
        for row in range(int(rect.height() // cell) + 1):
            for col in range(int(rect.width() // cell) + 1):
                painter.fillRect(QRectF(rect.x() + col * cell, rect.y() + row * cell, cell, cell),
                                 QColor("#3a3a3a" if (row + col) % 2 else "#2a2a2a"))
        painter.restore()
        ratio = self.devicePixelRatioF()
        pixels = max(1, round(rect.width() * ratio))
        image: QImage = render_template(self.template, pixels)
        image.setDevicePixelRatio(ratio)
        painter.drawImage(rect.topLeft(), image)
        painter.setPen(QPen(QColor("#5c5c5c"), 1))
        painter.drawRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5))
        if self._drop_active:
            painter.fillRect(rect, QColor(0, 212, 192, 60))
            painter.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
        if self.preview_mode:
            return
        if self.show_grid:
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
            for step in range(10, GRID, 10):
                offset = step * self.scale()
                painter.drawLine(QPointF(rect.x() + offset, rect.top()), QPointF(rect.x() + offset, rect.bottom()))
                painter.drawLine(QPointF(rect.left(), rect.y() + offset), QPointF(rect.right(), rect.y() + offset))
            painter.setPen(QPen(QColor(0, 212, 192, 90), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.center().x(), rect.top()), QPointF(rect.center().x(), rect.bottom()))
            painter.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        label_font = QFont(self.font())
        label_font.setPixelSize(11)
        painter.setFont(label_font)
        for kind in self.kinds():
            item = self.item_rect(kind)
            hidden = not self.template.visible(kind)
            if kind == self.selected:
                painter.setPen(QPen(ACCENT, 1.5, Qt.PenStyle.DashLine if hidden else Qt.PenStyle.SolidLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(item)
                painter.setBrush(QColor("#101010"))
                painter.setPen(QPen(ACCENT, 1.5))
                for handle in self.handle_rects(kind).values():
                    painter.drawRect(handle)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            elif self.show_aids:
                painter.setPen(QPen(QColor(255, 255, 255, 70 if hidden else 110), 1, Qt.PenStyle.DotLine))
                painter.drawRect(item)
            if self.show_aids and (hidden or kind == self.selected):
                tag = NAMES[kind] + (" (ausgeblendet)" if hidden else "")
                painter.setPen(QColor(ACCENT if kind == self.selected else QColor(200, 200, 200)))
                painter.drawText(QPointF(item.left() + 2, max(rect.top() - 4, item.top() - 4)), tag)
        painter.setPen(QPen(QColor("#FF4FD8"), 1))
        for axis, value in self._guides:
            offset = value * self.scale()
            if axis == "x":
                painter.drawLine(QPointF(rect.x() + offset, rect.top()), QPointF(rect.x() + offset, rect.bottom()))
            else:
                painter.drawLine(QPointF(rect.left(), rect.y() + offset), QPointF(rect.right(), rect.y() + offset))

    # mouse interaction
    def handle_at(self, point: QPointF) -> str | None:
        if self.selected is None:
            return None
        return next((k for k, r in self.handle_rects(self.selected).items() if r.contains(point)), None)

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() != Qt.MouseButton.LeftButton or not self.editable():
            return
        point = event.position()
        handle = self.handle_at(point)
        if handle is None:
            candidates = self.items_at(point)
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.cycle_selection(point)
            elif self.selected not in candidates:
                self.select(candidates[0] if candidates else None)
            if self.selected not in self.items_at(point):
                return
        self._drag = {"kind": self.selected, "handle": handle, "start": self.to_units(point),
                      "area": self.template.area(self.selected), "moved": False}

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._drag is None:
            if not self.editable():
                self.unsetCursor()
                return
            handle = self.handle_at(point)
            if handle:
                self.setCursor(QCursor(CURSORS[handle]))
            elif self.selected in self.items_at(point):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.unsetCursor()
            return
        current = self.to_units(point)
        delta = current - self._drag["start"]
        keep = self.lock_aspect.get(self._drag["kind"], False) != bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        snap = not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        area = self._moved(delta, snap) if self._drag["handle"] is None else \
            self._resized(self._drag["handle"], delta, keep)
        if area != self.template.area(self._drag["kind"]):
            self._drag["moved"] = True
            self.geometryEdited.emit(self._drag["kind"], area, False)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is not None and self._drag["moved"]:
            kind = self._drag["kind"]
            self.geometryEdited.emit(kind, self.template.area(kind), True)
        self._drag = None
        self._guides = []
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.editable() and TEXT in self.items_at(event.position()):
            self.select(TEXT)
            self.textEditRequested.emit()

    def _moved(self, delta: QPointF, snap: bool) -> tuple:
        x, y, w, h = self._drag["area"]
        nx = _clamp(x + delta.x(), min(0, GRID - w), max(0, GRID - w))
        ny = _clamp(y + delta.y(), min(0, GRID - h), max(0, GRID - h))
        self._guides = []
        if snap:
            if abs(nx + w / 2 - GRID / 2) < SNAP:
                nx = GRID / 2 - w / 2
                self._guides.append(("x", GRID / 2))
            if abs(ny + h / 2 - GRID / 2) < SNAP:
                ny = GRID / 2 - h / 2
                self._guides.append(("y", GRID / 2))
        return round(nx), round(ny), w, h

    def _resized(self, handle: str, delta: QPointF, keep: bool) -> tuple:
        x, y, w, h = self._drag["area"]
        left, top, right, bottom = x, y, x + w, y + h
        if "l" in handle:
            left = _clamp(left + delta.x(), min(0, x), right - MIN_SIZE)
        if "r" in handle:
            right = _clamp(right + delta.x(), left + MIN_SIZE, max(GRID, x + w))
        if handle.startswith("t"):
            top = _clamp(top + delta.y(), min(0, y), bottom - MIN_SIZE)
        if handle.startswith("b"):
            bottom = _clamp(bottom + delta.y(), top + MIN_SIZE, max(GRID, y + h))
        if keep and len(handle) == 2 and w > 0 and h > 0:
            ratio = w / h
            nw, nh = right - left, bottom - top
            if nw / ratio > nh:
                nh = nw / ratio
            else:
                nw = nh * ratio
            limit_w = (right if "l" in handle else GRID - left)
            limit_h = (bottom if handle.startswith("t") else GRID - top)
            factor = min(1.0, max(limit_w, MIN_SIZE) / nw, max(limit_h, MIN_SIZE) / nh)
            nw, nh = max(MIN_SIZE, nw * factor), max(MIN_SIZE, nh * factor)
            if "l" in handle:
                left = right - nw
            else:
                right = left + nw
            if handle.startswith("t"):
                top = bottom - nh
            else:
                bottom = top + nh
        nx, ny = round(left), round(top)
        return nx, ny, max(MIN_SIZE, round(right) - nx), max(MIN_SIZE, round(bottom) - ny)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Tab:
            self.cycle_selection()
            return
        if key == Qt.Key.Key_Escape:
            self.select(None)
            return
        steps = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in steps and self.selected and self.editable():
            factor = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            x, y, w, h = self.template.area(self.selected)
            dx, dy = steps[key]
            area = (round(_clamp(x + dx * factor, min(0, GRID - w), max(0, GRID - w))),
                    round(_clamp(y + dy * factor, min(0, GRID - h), max(0, GRID - h))), w, h)
            self.geometryEdited.emit(self.selected, area, False)
            self.geometryEdited.emit(self.selected, area, True)
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, forward):
        return False if self.hasFocus() else super().focusNextPrevChild(forward)

    # drag and drop from the library or Windows Explorer
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.isEnabled():
            event.acceptProposedAction()
            self._drop_active = True
            self.update()

    def dragLeaveEvent(self, event):
        self._drop_active = False
        self.update()

    def dropEvent(self, event):
        self._drop_active = False
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.update()
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
