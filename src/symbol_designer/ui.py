"""Small shared Qt helpers: tinted tool icons, colour buttons and thumbnails."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QColorDialog, QToolButton

from .ict import argb_hex, image_info

UI_ROOT = Path(__file__).resolve().parent / "assets" / "ui"
_icons: dict[tuple[str, str], QIcon] = {}
_thumbs: dict[tuple[str, int], tuple[QPixmap | None, str]] = {}


def ui_icon(name: str, color: str = "#E6E6E6") -> QIcon:
    key = (name, color)
    if key not in _icons:
        text = (UI_ROOT / (name + ".svg")).read_text(encoding="utf-8").replace("#FFFFFF", color)
        renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        _icons[key] = QIcon(pixmap)
    return _icons[key]


def thumbnail(path: Path, size: int = 40) -> tuple[QPixmap | None, str]:
    """Scaled preview of a library file; returns (pixmap, error text)."""
    key = (str(path), size)
    if key in _thumbs:
        return _thumbs[key]
    result: tuple[QPixmap | None, str]
    try:
        data = path.read_bytes()
        info = image_info(data)
        if info.format == "svg":
            renderer = QSvgRenderer(QByteArray(data))
            if not renderer.isValid():
                raise ValueError("SVG ungültig")
            image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
        else:
            image = QImage.fromData(data)
            if image.isNull():
                raise ValueError("Bild nicht lesbar")
            image = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        result = (QPixmap.fromImage(image), "")
    except (OSError, ValueError) as exc:
        result = (None, str(exc))
    _thumbs[key] = result
    return result


def broken_pixmap(size: int = 40) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#5b2333"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "!")
    painter.end()
    return pixmap


class ColorButton(QToolButton):
    """Swatch button; ``colorChanged`` carries an ARGB uint32."""
    colorChanged = Signal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self._value = 0xFF000000
        self.setMinimumSize(QSize(120, 30))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.clicked.connect(self.choose)
        self.set_value(self._value)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = int(value) & 0xFFFFFFFF
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        for y in range(0, 22, 6):
            for x in range(0, 22, 6):
                painter.fillRect(x, y, 6, 6, QColor("#bbbbbb" if (x + y) // 6 % 2 else "#ffffff"))
        painter.fillRect(0, 0, 22, 22, QColor.fromRgba(self._value))
        painter.setPen(QColor("#888888"))
        painter.drawRect(0, 0, 21, 21)
        painter.end()
        self.setIcon(QIcon(pixmap))
        self.setText(argb_hex(self._value) if self._value >> 24 != 0xFF else "#%06X" % (self._value & 0xFFFFFF))

    def choose(self) -> None:
        color = QColorDialog.getColor(QColor.fromRgba(self._value), self, self.title,
                                      QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid() and color.rgba() != self._value:
            self.set_value(color.rgba())
            self.colorChanged.emit(self._value)
