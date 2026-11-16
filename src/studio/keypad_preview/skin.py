"""Device look only: native geometry, images, painting. No SDK or placement logic.

Two skins exist. The LogiKeypad skin paints the user's original PNGs and is what
a host should show whenever they are readable. The neutral skin is the fallback
and diagnostic mode; it deliberately resembles no real product. Nothing here
generates, downloads or edits device artwork.

Layer roles of the LogiKeypad skin, bottom to top (checked against Pagination.png):

  keys_black.png            static LCD floor below every key
  keys_off.png + N_*.png    grey face of a key without content, with its tints
  case_transparent.png      unchanged housing with logo and hardware arrows
  black LCD                 occupied key, 3 px larger than the cut-out as in the reference
  tile_image / label        host-resolved content of an occupied slot
  gloss (derived from N_*)  additive sheen on occupied LCDs
  state tint                hover, press and drag colour of an occupied key
  rings, three-dot button   state markers that may overlap the housing

A single-key layer alone reproduces the reference exactly but has jagged gaps at
key 1 and key 9. keys_off.png fills them; its own stray pixels stay covered by the
single layer. keys_white.png has no documented state and is left unused.
"""
from __future__ import annotations

import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

FONT_FAMILY = "Segoe UI"     # Windows UI font; Qt substitutes a real font elsewhere.

ASSET_NATIVE_SIZE = (657, 724)
ASSET_CASE_FILE = "case_transparent.png"
ASSET_LCD_FILE = "keys_black.png"
ASSET_OFF_FILE = "keys_off.png"
ASSET_DIRECTORY_ENV = "LOGI_KEYPAD_SKIN_DIR"
# Alpha bounds measured from the original key layers (technical draft, section 1.1).
ASSET_KEY_RECTS: Mapping[int, tuple[int, int, int, int]] = {
    0: (121, 99, 126, 126), 1: (270, 98, 126, 127), 2: (419, 98, 126, 127),
    3: (121, 250, 126, 124), 4: (270, 249, 126, 125), 5: (419, 249, 126, 125),
    6: (121, 397, 126, 125), 7: (270, 398, 126, 124), 8: (419, 398, 126, 124),
}
ASSET_KEY_FILES: Mapping[int, str] = {
    0: "1_ObenLinks.png", 1: "2_ObenMitte.png", 2: "3_ObenRechts.png",
    3: "4_MitteLinks.png", 4: "5_MitteMitte.png", 5: "6_MitteRechts.png",
    6: "7_UntenLinks.png", 7: "8_UntenMitte.png", 8: "9_UntenRechts.png",
}
# Hardware arrows of case_transparent.png, measured from the hover tint in
# NextPageButton.png and PreviousPageButton.png. The step is the page direction.
ASSET_ARROW_RECTS: Mapping[int, tuple[int, int, int, int]] = {-1: (121, 543, 127, 87), 1: (270, 543, 127, 87)}
_ARROW_RADIUS = 14.0
_ARROW_INNER_RADIUS = 17.0
_ARROW_OUTER_RADIUS = 40.0
# The outer top corners of the 3×3 block are visibly rounder in the case cut-outs.
_KEY_RADIUS = 13.0
_OUTER_KEY_RADIUS = 35.0
_LCD_OUTSET = 3.0          # An occupied key's black area covers the cut-out's edge.
_DEVICE_CENTER_X = 331.0   # Centre of the opaque housing, not of the canvas.
# Reference value of an occupied LCD for a grey-layer value, from Pagination.png.
_GLOSS_KNOTS = ((0, 0), (89, 0), (92, 4), (100, 14), (108, 24), (116, 41), (124, 50), (132, 65), (170, 163), (255, 255))
ALPHA_HIT_THRESHOLD = 16

_KEY_SIZE = 126.0
_KEY_PITCH = 149.0
_MARGIN_X = 121.0
_MARGIN_TOP = 92.0
_MARGIN_BOTTOM = 112.0


@dataclass(frozen=True)
class SkinPalette:
    housing_top: str = "#343a42"
    housing_bottom: str = "#1d2126"
    housing_edge: str = "#4c545e"
    well: str = "#0e1013"
    cap_top: str = "#262b31"
    cap_bottom: str = "#191c21"
    cap_edge: str = "#3f4650"
    display: str = "#0b0d10"
    inert: str = "#16191d"
    text: str = "#ffffff"
    muted: str = "#8b949f"
    selected: str = "#99f7ec"      # Active page cell in Pagination.png.
    tint: str = "#2ae0cb"          # Hover colour fitted to NextPageButton.png.
    focus: str = "#ffffff"
    drop_border: str = "#e4fffb"
    drop_refused: str = "#e5484d"
    navigation: str = "#6fb7c9"
    pressed_tint: str = "#ffffff"
    engraving: str = "#6a727c"


TINT_HOVER = 0.20
TINT_DROP_CANDIDATE = 0.35
TINT_DROP_TARGET = 0.82
TINT_DRAG_SOURCE = 0.28


@dataclass(frozen=True, eq=False)
class KeypadSkin:
    """One device look. All rectangles are in the skin's native coordinate system."""

    name: str
    native_size: tuple[int, int]
    key_rects: Mapping[int, tuple[float, float, float, float]]
    corner_radius: float = 15.0
    display_inset: float = 7.0
    palette: SkinPalette = field(default_factory=SkinPalette)
    case_image: QImage | None = None
    key_images: Mapping[int, QImage] = field(default_factory=dict)
    key_faces: Mapping[int, tuple[QRectF, QImage]] = field(default_factory=dict)
    lcd_image: QImage | None = None
    gloss_images: Mapping[int, QImage] = field(default_factory=dict)
    arrow_rects: Mapping[int, tuple[float, float, float, float]] = field(default_factory=dict)
    backdrop: str | None = None
    center_x: float | None = None
    source_directory: str = ""
    notice: str = ""

    @property
    def is_device_art(self) -> bool:
        return self.case_image is not None

    def covers(self, indices: Iterable[int]) -> bool:
        return all(index in self.key_rects for index in indices)

    def key_rect(self, index: int) -> QRectF:
        return QRectF(*self.key_rects[index])

    def display_rect(self, index: int) -> QRectF:
        inset = self.display_inset
        return self.key_rect(index).adjusted(inset, inset, -inset, -inset)

    def key_path(self, index: int, outset: float = 0.0) -> QPainterPath:
        rect = self.key_rect(index).adjusted(-outset, -outset, outset, outset)
        if self.is_device_art:
            big = {0: 0, 2: 1}.get(index)
            radii = [max(2.0, (_OUTER_KEY_RADIUS if corner == big else _KEY_RADIUS) + outset) for corner in range(4)]
            return _rounded_path(rect, *radii)
        path = QPainterPath()
        radius = max(2.0, self.corner_radius + outset)
        path.addRoundedRect(rect, radius, radius)
        return path

    def lcd_path(self, index: int) -> QPainterPath:
        """Visible LCD area, used for content clipping and state tints."""
        if self.is_device_art:
            return self.key_path(index, _LCD_OUTSET)
        radius = max(2.0, self.corner_radius - self.display_inset)
        path = QPainterPath()
        path.addRoundedRect(self.display_rect(index), radius, radius)
        return path

    def arrow_rect(self, step: int) -> QRectF:
        return QRectF(*self.arrow_rects[step])

    def arrow_path(self, step: int) -> QPainterPath:
        top, inner, outer = _ARROW_RADIUS, _ARROW_INNER_RADIUS, _ARROW_OUTER_RADIUS
        radii = (top, top, outer, inner) if step > 0 else (top, top, inner, outer)
        return _rounded_path(self.arrow_rect(step), *radii)

    def hit_arrow(self, point: QPointF) -> int | None:
        for step in self.arrow_rects:
            if self.arrow_path(step).contains(point):
                return step
        return None

    def hit_key(self, point: QPointF, indices: Iterable[int]) -> int | None:
        """Native point to key; gaps and rounded corners are not part of any key."""
        x, y = int(point.x()), int(point.y())
        for index in indices:
            if index not in self.key_rects or not self.key_rect(index).contains(point):
                continue
            if self.lcd_image is not None:
                # The visible key is where the case is open above the LCD floor.
                if (self.case_image.valid(x, y) and self.case_image.pixelColor(x, y).alpha() < ALPHA_HIT_THRESHOLD
                        and self.lcd_image.pixelColor(x, y).alpha() >= ALPHA_HIT_THRESHOLD):
                    return index
                continue
            mask = self.key_images.get(index)
            if mask is not None:
                if mask.valid(x, y) and mask.pixelColor(x, y).alpha() >= ALPHA_HIT_THRESHOLD:
                    return index
            elif self.key_path(index).contains(point):
                return index
        return None

    def paint_body(self, painter: QPainter) -> None:
        """Static part below the keys; it never moves with a pressed key."""
        if not self.is_device_art:
            _paint_neutral_body(painter, self)
        elif self.lcd_image is not None:
            painter.drawImage(QRectF(0, 0, *self.native_size), self.lcd_image)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#000000"))
            for index in self.key_rects:
                painter.drawPath(self.key_path(index))

    def paint_key_cap(self, painter: QPainter, index: int, *, inert: bool = False, lit: bool = False) -> None:
        """Moving key face. An occupied device key shows the black LCD floor instead."""
        if self.is_device_art:
            if lit:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#000000"))
                painter.drawPath(self.lcd_path(index))
                return
            face = self.key_faces.get(index)
            image = self.key_images.get(index)
            if face is not None:
                painter.drawImage(*face)
            elif image is not None:
                painter.drawImage(QRectF(0, 0, *self.native_size), image)
            if inert:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 120))
                painter.drawPath(self.key_path(index))
            return
        rect = self.key_rect(index)
        tone = self.palette
        if inert:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tone.inert))
            painter.drawRoundedRect(rect, self.corner_radius, self.corner_radius)
            return
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(tone.cap_top))
        gradient.setColorAt(1.0, QColor(tone.cap_bottom))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(tone.cap_edge), 1.2))
        painter.drawRoundedRect(rect, self.corner_radius, self.corner_radius)
        display = self.display_rect(index)
        radius = max(2.0, self.corner_radius - self.display_inset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tone.display))
        painter.drawRoundedRect(display, radius, radius)

    def paint_gloss(self, painter: QPainter, index: int) -> None:
        image = self.gloss_images.get(index)
        if image is None:
            return
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.drawImage(self.key_rect(index), image)
        painter.restore()


def _rounded_path(rect: QRectF, top_left: float, top_right: float, bottom_right: float, bottom_left: float) -> QPainterPath:
    path = QPainterPath()
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    path.moveTo(left + top_left, top)
    path.lineTo(right - top_right, top)
    path.arcTo(QRectF(right - 2 * top_right, top, 2 * top_right, 2 * top_right), 90, -90)
    path.lineTo(right, bottom - bottom_right)
    path.arcTo(QRectF(right - 2 * bottom_right, bottom - 2 * bottom_right, 2 * bottom_right, 2 * bottom_right), 0, -90)
    path.lineTo(left + bottom_left, bottom)
    path.arcTo(QRectF(left, bottom - 2 * bottom_left, 2 * bottom_left, 2 * bottom_left), -90, -90)
    path.lineTo(left, top + top_left)
    path.arcTo(QRectF(left, top, 2 * top_left, 2 * top_left), 180, -90)
    path.closeSubpath()
    return path


def _paint_neutral_body(painter: QPainter, skin: KeypadSkin) -> None:
    width, height = skin.native_size
    tone = skin.palette
    housing = QRectF(22, 20, width - 44, height - 44)
    # Soft contact shadow; hand-layered so the cache needs no QGraphicsEffect.
    painter.setPen(Qt.PenStyle.NoPen)
    for step in range(10, 0, -1):
        shadow = QColor(0, 0, 0, 7)
        painter.setBrush(shadow)
        painter.drawRoundedRect(housing.adjusted(-step, -step + 6, step, step + 6), 46 + step, 46 + step)
    gradient = QLinearGradient(housing.topLeft(), housing.bottomLeft())
    gradient.setColorAt(0.0, QColor(tone.housing_top))
    gradient.setColorAt(1.0, QColor(tone.housing_bottom))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(tone.housing_edge), 1.5))
    painter.drawRoundedRect(housing, 46, 46)
    sheen = QRadialGradient(QPointF(width * 0.35, housing.top()), width * 0.7)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 18))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(sheen)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(housing, 46, 46)
    # Key wells are part of the housing, so a pressed key reveals depth.
    painter.setBrush(QColor(tone.well))
    for index in skin.key_rects:
        well = skin.key_rect(index).adjusted(-4, -4, 4, 5)
        painter.drawRoundedRect(well, skin.corner_radius + 3, skin.corner_radius + 3)
    painter.setPen(QColor(tone.engraving))
    font = QFont()
    font.setPixelSize(14)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
    painter.setFont(font)
    painter.drawText(QRectF(housing.left(), height - 82, housing.width(), 30),
                     Qt.AlignmentFlag.AlignCenter, "NEUTRALE VORSCHAU")


def _grid_skin(name: str, columns: int, rows: int, indices: Iterable[int]) -> KeypadSkin:
    width = 2 * _MARGIN_X + columns * _KEY_SIZE + (columns - 1) * (_KEY_PITCH - _KEY_SIZE)
    height = _MARGIN_TOP + _MARGIN_BOTTOM + rows * _KEY_SIZE + (rows - 1) * (_KEY_PITCH - _KEY_SIZE)
    rects = {index: (_MARGIN_X + (index % columns) * _KEY_PITCH,
                     _MARGIN_TOP + (index // columns) * _KEY_PITCH, _KEY_SIZE, _KEY_SIZE)
             for index in indices}
    return KeypadSkin(name, (int(width), int(height)), rects)


_NEUTRAL = _grid_skin("Neutral 3×3", 3, 3, range(9))


def neutral_skin() -> KeypadSkin:
    return _NEUTRAL


def neutral_skin_for(indices: Iterable[int]) -> KeypadSkin:
    """Neutral layout for reported slots; no assumption of nine usable keys."""
    used = sorted(set(indices))
    if not used or used[-1] <= 8:
        return _NEUTRAL
    columns = math.ceil(math.sqrt(used[-1] + 1))
    rows = math.ceil((used[-1] + 1) / columns)
    return _grid_skin(f"Neutral {columns}×{rows}", columns, rows, range(columns * rows))


def _gloss_table() -> bytes:
    table = bytearray(256)
    for (x0, y0), (x1, y1) in zip(_GLOSS_KNOTS, _GLOSS_KNOTS[1:]):
        for x in range(x0, x1 + 1):
            table[x] = round(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return bytes(table)


def _derive_gloss(key_layer: QImage, rect: tuple[int, int, int, int]) -> QImage:
    """Sheen of an occupied LCD, computed in memory from the key's relief. The file stays untouched."""
    gray = key_layer.copy(*rect).convertToFormat(QImage.Format.Format_Grayscale8)
    data = bytes(gray.constBits()).translate(_gloss_table())
    return QImage(data, gray.width(), gray.height(), gray.bytesPerLine(), QImage.Format.Format_Grayscale8).copy()


def _compose_face(off_layer: QImage, key_layer: QImage, rect: tuple[int, int, int, int]) -> tuple[QRectF, QImage]:
    """Grey key face in memory: keys_off below, single-key layer above. The files stay untouched."""
    x, y, width, height = rect
    area = (x - 6, y - 6, width + 12, height + 12)
    face = off_layer.copy(*area)
    painter = QPainter(face)
    painter.drawImage(0, 0, key_layer, *area)
    painter.end()
    return QRectF(*area), face


def _read_layer(path: Path) -> tuple[QImage | None, str]:
    image = QImage(str(path))
    if image.isNull():
        return None, f"Skin-Datei ist kein lesbares Bild: {path.name}"
    if (image.width(), image.height()) != ASSET_NATIVE_SIZE:
        return None, f"Skin-Datei hat nicht {ASSET_NATIVE_SIZE[0]}×{ASSET_NATIVE_SIZE[1]} Pixel: {path.name}"
    if not image.hasAlphaChannel():
        return None, f"Skin-Datei hat keinen Alphakanal: {path.name}"
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied), ""


def load_logikeypad_skin(directory: str | Path) -> tuple[KeypadSkin | None, str]:
    """Load the user's original PNGs after format checks. Returns (skin, problem)."""
    root = Path(directory)
    if not root.is_dir():
        return None, f"Skin-Ordner fehlt: {root}"
    images: dict[str, QImage] = {}
    for filename in (ASSET_CASE_FILE, *ASSET_KEY_FILES.values()):
        path = root / filename
        if not path.is_file():
            return None, f"Skin-Datei fehlt: {filename}"
        image, problem = _read_layer(path)
        if image is None:
            return None, problem
        images[filename] = image
    keys = {index: images[filename] for index, filename in ASSET_KEY_FILES.items()}
    lcd = None
    notice = ""
    if (root / ASSET_LCD_FILE).is_file():
        lcd, problem = _read_layer(root / ASSET_LCD_FILE)
        if lcd is None:
            return None, problem
    else:
        notice = f"{ASSET_LCD_FILE} fehlt; schwarze LCD-Flächen werden ersatzweise gezeichnet."
    faces = {}
    if (root / ASSET_OFF_FILE).is_file():
        off, problem = _read_layer(root / ASSET_OFF_FILE)
        if off is None:
            return None, problem
        faces = {index: _compose_face(off, keys[index], ASSET_KEY_RECTS[index]) for index in keys}
    gloss = {index: _derive_gloss(keys[index], ASSET_KEY_RECTS[index]) for index in keys}
    return KeypadSkin("LogiKeypad (lokale Originaldateien)", ASSET_NATIVE_SIZE, dict(ASSET_KEY_RECTS),
                      corner_radius=_KEY_RADIUS, display_inset=-_LCD_OUTSET, case_image=images[ASSET_CASE_FILE],
                      key_images=keys, key_faces=faces, lcd_image=lcd, gloss_images=gloss, arrow_rects=dict(ASSET_ARROW_RECTS),
                      backdrop="#1a1a1a", center_x=_DEVICE_CENTER_X, source_directory=str(root), notice=notice), ""


def find_logikeypad_directory(project_root: str | Path, environ: Mapping[str, str] | None = None) -> Path:
    """First folder holding the original layers, for hosts and the lab; the widget itself never looks.

    Order: LOGI_KEYPAD_SKIN_DIR, assets/ui/keypad/logikeypad in the project, then the
    sibling folder of the local checkout. Without a hit the project path is returned,
    so that loading it reports a precise problem instead of silently using another skin.
    """
    root = Path(project_root)
    environment = os.environ if environ is None else environ
    project_assets = root / "assets" / "ui" / "keypad" / "logikeypad"
    candidates = [project_assets, root.parent / "graphics_pictures" / "KeypadPreviewWidget" / "graphics_logi_keypad"]
    if environment.get(ASSET_DIRECTORY_ENV):
        candidates.insert(0, Path(environment[ASSET_DIRECTORY_ENV]))
    return next((path for path in candidates if (path / ASSET_CASE_FILE).is_file()), project_assets)


def drag_label_pixmap(text: str, ratio: float = 1.0, *, font_px: int = 15) -> tuple[QPixmap, QPointF]:
    """Drag cursor as in the reference: dark pill with a diamond and the action name."""
    font = QFont(FONT_FAMILY)
    font.setPixelSize(font_px)
    font.setWeight(QFont.Weight.DemiBold)
    metrics = QFontMetricsF(font)
    width = min(320.0, metrics.horizontalAdvance(text) + 2.6 * font_px + 16)
    height = 2.4 * font_px
    pixmap = QPixmap(QSize(round(width * ratio), round(height * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    tone = SkinPalette()
    painter.setPen(QPen(QColor(tone.tint), 1.0))
    painter.setBrush(QColor("#0a0a0a"))
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 3, 3)
    middle = height / 2
    side = font_px * 0.36
    diamond = QPainterPath(QPointF(font_px, middle - side))
    diamond.lineTo(font_px + side, middle)
    diamond.lineTo(font_px, middle + side)
    diamond.lineTo(font_px - side, middle)
    diamond.closeSubpath()
    painter.setPen(QPen(QColor("#ffffff"), 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(diamond)
    painter.setFont(font)
    text_left = 2 * font_px
    painter.drawText(QRectF(text_left, 0, width - text_left - 8, height), int(Qt.AlignmentFlag.AlignVCenter),
                     metrics.elidedText(text, Qt.TextElideMode.ElideRight, width - text_left - 8))
    painter.end()
    return pixmap, QPointF(font_px, middle)

