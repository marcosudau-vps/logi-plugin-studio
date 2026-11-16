from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter

from adapters.logitech.product import read_asset
from adapters.logitech.errors import LogitechAdapterError
from library.document import DocumentError
from library.presentation import image_bounds, resolve_visual


def export_image(source: str | Path, destination: str | Path, size: int = 116) -> None:
    if size not in (50, 80, 116):
        raise DocumentError("Choose a supported 50, 80 or 116 pixel export size")
    file = Path(source)
    if file.stat().st_size > 8_388_608:
        raise DocumentError("Input image exceeds the 8 MiB import limit")
    reader = QImageReader(str(file))
    dimensions = reader.size()
    if not dimensions.isValid() or dimensions.width() > 4096 or dimensions.height() > 4096:
        raise DocumentError("Invalid image or dimensions exceed 4096px")
    if bytes(reader.format()).lower() not in (b"png", b"jpeg", b"jpg", b"bmp", b"webp"):
        raise DocumentError("Only PNG, JPEG, BMP and WebP imports are supported")
    image = reader.read()
    if image.isNull():
        raise DocumentError("Image cannot be decoded: " + reader.errorString())
    target = Path(destination)
    if target.exists():
        raise DocumentError("Asset already exists; choose another stable asset ID")
    target.parent.mkdir(parents=True, exist_ok=True)
    output = QImage(size, size, QImage.Format.Format_ARGB32)
    output.fill(Qt.GlobalColor.transparent)
    scaled = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(output)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    if not output.save(str(target), "PNG"):
        raise DocumentError("Could not write exported PNG")


def render_tile(raw: dict, project_dir: Path | None, placement: dict | None,
                variant_key: str | None = None, size: int = 116) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor("#243449"))
    painter = QPainter(image)
    error = None
    try:
        resolved = resolve_visual(raw, placement, variant_key)
    except ValueError as exc:
        resolved = resolve_visual({"components": [], "presentations": [], "bindings": [], "states": []}, None)
        error = str(exc)
    background_value = resolved.background
    foreground_value = resolved.foreground
    background = QColor(background_value) if isinstance(background_value, str) else QColor()
    foreground = QColor(foreground_value) if isinstance(foreground_value, str) else QColor()
    painter.fillRect(image.rect(), background if background.isValid() else QColor("#5b2333"))
    asset_id = resolved.image_asset_id
    if asset_id and error is None:
        asset = next((a for a in raw.get("assets", []) if isinstance(a, dict) and a.get("id") == asset_id), None)
        try:
            if project_dir is None or asset is None:
                raise DocumentError("Asset nicht verfuegbar")
            content = read_asset(project_dir, asset)
            raster = QImage.fromData(content, "PNG")
            if raster.isNull():
                raise DocumentError("PNG kann nicht dekodiert werden")
            for y in range(0, size, 8):
                for x in range(0, size, 8):
                    painter.fillRect(x, y, 8, 8, QColor("#8d98a5" if (x + y) // 8 % 2 else "#c5ccd4"))
            painter.drawImage(QRect(*image_bounds(raster.width(), raster.height(), size, resolved.image_fit)), raster)
        except (DocumentError, LogitechAdapterError, OSError, ValueError) as exc:
            error = str(exc)
    text = resolved.text
    painter.setPen(foreground if foreground.isValid() else QColor("#ffffff"))
    font = QFont("Segoe UI", max(8, size // 12))
    if resolved.font_size is not None:
        font.setPixelSize(max(1, (resolved.font_size * size + 58) // 116))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.drawText(QRect(4, 6, size - 8, size - 26), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, str(text))
    painter.fillRect(0, size - 18, size, 18, QColor("#5b2333" if error else "#334155"))
    painter.setFont(QFont("Segoe UI", 7))
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRect(1, size - 18, size - 2, 18), Qt.AlignmentFlag.AlignCenter,
                     "BILDFEHLER" if error else "DESIGN-VORSCHAU")
    painter.end()
    return image
