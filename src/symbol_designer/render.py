"""One renderer for canvas, PNG and SVG so the preview equals the export.

Rendering rules (documented in work/widget-lab/icon-designer-v1/README.md):
images keep their aspect ratio centred in their area, are rotated clockwise by
``imageRotation`` and monochrome SVGs are tinted with ``imageColor``; text is
centred in its area, word-wrapped and drawn with the Options+ font-size scale.
"""
from __future__ import annotations

import base64
import hashlib
import math
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from .ict import (BLACK, EXPORT_SIZES, GRID, IMAGE, MAX_IMAGE_BYTES, TEXT, IconTemplate, IctError,
                  ImageInfo, alpha, font_units, image_info, recolor_svg, rgb_hex)

FALLBACK_FONT = "Segoe UI"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RASTER_EDGE = 512
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


@dataclass
class Decoded:
    info: ImageInfo
    natural: QSizeF
    svg: QSvgRenderer | None = None
    raster: QImage | None = None


_decoded: OrderedDict[str, Decoded | None] = OrderedDict()


def decode(data: bytes) -> Decoded | None:
    key = hashlib.sha1(data).hexdigest()
    if key in _decoded:
        _decoded.move_to_end(key)
        return _decoded[key]
    info = image_info(data)
    result = None
    if info.format == "svg":
        renderer = QSvgRenderer(QByteArray(data))
        if renderer.isValid():
            renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            box = renderer.viewBoxF()
            natural = box.size() if box.width() > 0 and box.height() > 0 else QSizeF(renderer.defaultSize())
            if natural.width() <= 0 or natural.height() <= 0:
                natural = QSizeF(GRID, GRID)
            result = Decoded(info, natural, svg=renderer)
    elif info.format != "unknown":
        image = QImage.fromData(data)
        if not image.isNull():
            result = Decoded(info, QSizeF(image.size()), raster=image)
    _decoded[key] = result
    while len(_decoded) > 96:
        _decoded.popitem(last=False)
    return result


def font_available(name: str) -> bool:
    return name in set(QFontDatabase.families())


def resolve_font(name: str) -> tuple[QFont, bool]:
    """Requested family, or a light Segoe UI fallback when it is not installed."""
    if font_available(name):
        return QFont(name), False
    font = QFont(FALLBACK_FONT)
    if "light" in name.lower():
        font.setWeight(QFont.Weight.Light)
    return font, True


@dataclass
class TextLayout:
    font: QFont
    pixel_size: float
    lines: list[tuple[str, float, float]] = field(default_factory=list)
    substituted: bool = False


def wrap_text(text: str, metrics: QFontMetricsF, width: float) -> list[str]:
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else current + " " + word
            if current and metrics.horizontalAdvance(candidate) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def layout_text(template: IconTemplate, size: float) -> TextLayout:
    """Lines as (text, centre x, baseline y) in pixels for an icon of ``size`` px."""
    font, substituted = resolve_font(template.font_name)
    pixel = max(1, round(font_units(template.font_size) * size / GRID))
    font.setPixelSize(pixel)
    metrics = QFontMetricsF(font)
    x, y, w, h = (v * size / GRID for v in template.area(TEXT))
    lines = wrap_text(template.text, metrics, w) if template.text else []
    height = metrics.height() * len(lines)
    top = y + (h - height) / 2
    result = TextLayout(font, pixel, substituted=substituted)
    for index, line in enumerate(lines):
        result.lines.append((line, x + w / 2, top + index * metrics.height() + metrics.ascent()))
    return result


def image_geometry(area: tuple[float, float, float, float], natural: QSizeF, rotation: int):
    """Centre point and unrotated drawing size of an image fitted into ``area``."""
    x, y, w, h = area
    nw, nh = max(natural.width(), 1e-6), max(natural.height(), 1e-6)
    turned = rotation in (90, 270)
    scale = min(w / (nh if turned else nw), h / (nw if turned else nh))
    return QPointF(x + w / 2, y + h / 2), nw * scale, nh * scale


def _tinted_svg(renderer: QSvgRenderer, width: float, height: float, color: int) -> QImage:
    layer = QImage(max(1, math.ceil(width)), max(1, math.ceil(height)), QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)
    painter = QPainter(layer)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(layer.rect(), QColor.fromRgba(color))
    painter.end()
    return layer


def paint_template(painter: QPainter, template: IconTemplate, size: float) -> list[str]:
    """Paint into ``painter`` at (0,0)-(size,size); returns rendering notes."""
    notes = []
    painter.save()
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform |
                           QPainter.RenderHint.TextAntialiasing)
    painter.setClipRect(QRectF(0, 0, size, size))
    painter.fillRect(QRectF(0, 0, size, size), QColor.fromRgba(template.background))
    for kind in template.stacking():
        if not template.visible(kind):
            continue
        if kind == IMAGE:
            data = template.image_bytes()
            if not data:
                continue
            decoded = decode(data)
            if decoded is None:
                notes.append("Eingebettetes Bild kann nicht dekodiert werden")
                continue
            area = tuple(v * size / GRID for v in template.area(IMAGE))
            centre, width, height = image_geometry(area, decoded.natural, template.rotation)
            painter.save()
            painter.translate(centre)
            painter.rotate(template.rotation)
            target = QRectF(-width / 2, -height / 2, width, height)
            if decoded.svg is not None and decoded.info.tintable:
                painter.drawImage(target, _tinted_svg(decoded.svg, width, height, template.image_color))
            elif decoded.svg is not None:
                decoded.svg.render(painter, target)
            else:
                painter.drawImage(target, decoded.raster)
            painter.restore()
        elif kind == TEXT:
            layout = layout_text(template, size)
            if layout.substituted:
                notes.append("Schrift '%s' ist nicht installiert – Ersatzschrift %s"
                             % (template.font_name, FALLBACK_FONT))
            painter.setFont(layout.font)
            painter.setPen(QColor.fromRgba(template.text_color))
            metrics = QFontMetricsF(layout.font)
            for line, centre_x, baseline in layout.lines:
                painter.drawText(QPointF(centre_x - metrics.horizontalAdvance(line) / 2, baseline), line)
    painter.restore()
    return notes


def render_template(template: IconTemplate, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_template(painter, template, size)
    painter.end()
    return image


def export_png(template: IconTemplate, path: str | Path, size: int) -> Path:
    if size not in EXPORT_SIZES:
        raise IctError("PNG-Größe muss 50, 80 oder 116 px sein")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not render_template(template, size).save(str(target), "PNG"):
        raise IctError("PNG konnte nicht geschrieben werden: %s" % target)
    return target


def export_pngs(template: IconTemplate, directory: str | Path, stem: str, sizes=EXPORT_SIZES) -> list[Path]:
    return [export_png(template, Path(directory) / ("%s_%dpx.png" % (stem, size)), size) for size in sizes]


# --- SVG ----------------------------------------------------------------------------

@dataclass
class SvgReport:
    path: Path
    vector_image: bool = False
    raster_embedded: bool = False
    notes: list[str] = field(default_factory=list)


def _png_bytes(image: QImage) -> bytes:
    array = QByteArray()
    buffer = QBuffer(array)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(array.data())


def _fmt(value: float) -> str:
    return ("%.3f" % value).rstrip("0").rstrip(".")


def _strip_foreign(element: ET.Element) -> None:
    for child in list(element):
        if child.tag.startswith("{") and not child.tag.startswith("{" + SVG_NS):
            element.remove(child)
        else:
            _strip_foreign(child)
    for key in list(element.attrib):
        if key.startswith("{") and not key.startswith(("{" + XLINK_NS, "{http://www.w3.org/XML/1998/namespace")):
            del element.attrib[key]


def _svg_image(parent: ET.Element, template: IconTemplate, data: bytes, decoded: Decoded, report: SvgReport) -> None:
    area = template.area(IMAGE)
    rotation = template.rotation
    centre, width, height = image_geometry(area, decoded.natural, rotation)
    place = "translate(%s %s) rotate(%d) translate(%s %s)" % (_fmt(centre.x()), _fmt(centre.y()), rotation,
                                                            _fmt(-width / 2), _fmt(-height / 2))
    if decoded.svg is not None:
        text = data.decode("utf-8", "replace")
        if decoded.info.tintable:
            text = recolor_svg(text, template.image_color)
        try:
            source = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            raise IctError("Eingebettetes SVG kann nicht übernommen werden: %s" % exc) from exc
        _strip_foreign(source)
        box = decoded.svg.viewBoxF()
        if box.width() <= 0 or box.height() <= 0:
            box = QRectF(0, 0, decoded.natural.width(), decoded.natural.height())
        scale = width / box.width()
        outer = ET.SubElement(parent, "{%s}g" % SVG_NS, {
            "id": "symbol", "transform": place + " scale(%s) translate(%s %s)" % (
                _fmt(scale), _fmt(-box.x()), _fmt(-box.y()))})
        clip = ET.SubElement(ET.SubElement(outer, "{%s}defs" % SVG_NS), "{%s}clipPath" % SVG_NS,
                             {"id": "symbol-viewbox"})
        ET.SubElement(clip, "{%s}rect" % SVG_NS, {"x": _fmt(box.x()), "y": _fmt(box.y()),
                                                  "width": _fmt(box.width()), "height": _fmt(box.height())})
        inner = ET.SubElement(outer, "{%s}g" % SVG_NS, {"clip-path": "url(#symbol-viewbox)"})
        for key, value in source.attrib.items():
            if key not in ("width", "height", "viewBox", "x", "y", "version", "preserveAspectRatio", "id"):
                inner.set(key, value)
        inner.extend(list(source))
        report.vector_image = True
        return
    raw, mime = data, {"png": "image/png", "jpeg": "image/jpeg"}.get(decoded.info.format)
    if mime is None:
        raw, mime = _png_bytes(decoded.raster), "image/png"
        report.notes.append("%s-Bild wurde für das SVG als PNG eingebettet" % decoded.info.format.upper()
                            + (" (Standbild, GIF-Animation entfällt)" if decoded.info.animated else ""))
    group = ET.SubElement(parent, "{%s}g" % SVG_NS, {"id": "symbol", "transform": place})
    ET.SubElement(group, "{%s}image" % SVG_NS, {
        "width": _fmt(width), "height": _fmt(height), "preserveAspectRatio": "none",
        "{%s}href" % XLINK_NS: "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))})
    report.raster_embedded = True
    report.notes.append("Symbol ist eine eingebettete Rastergrafik – keine Vektorisierung")


def build_svg(template: IconTemplate, size: int = 116, path: str | Path = "") -> tuple[bytes, SvgReport]:
    report = SvgReport(Path(path))
    root = ET.Element("{%s}svg" % SVG_NS, {"width": str(size), "height": str(size),
                                           "viewBox": "0 0 %d %d" % (GRID, GRID), "version": "1.1"})
    ET.SubElement(root, "{%s}desc" % SVG_NS).text = "Exportiert vom Logitech Plugin Studio Symbol-Designer aus einer ICT-Vorlage"
    background = template.background
    ET.SubElement(root, "{%s}rect" % SVG_NS, {"id": "background", "width": str(GRID), "height": str(GRID),
                                              "fill": rgb_hex(background),
                                              "fill-opacity": _fmt(alpha(background) / 255)})
    for kind in template.stacking():
        if not template.visible(kind):
            continue
        if kind == IMAGE:
            data = template.image_bytes()
            decoded = decode(data) if data else None
            if decoded is not None:
                _svg_image(root, template, data, decoded, report)
            elif data:
                report.notes.append("Eingebettetes Bild ist nicht dekodierbar und fehlt im SVG")
        elif kind == TEXT and template.text:
            scale = 10
            layout = layout_text(template, GRID * scale)
            if layout.substituted:
                report.notes.append("Schrift '%s' nicht installiert – SVG verwendet wie die Vorschau die "
                                    "Ersatzschrift %s" % (template.font_name, FALLBACK_FONT))
            color = template.text_color
            # a single family: QtSvg does not resolve CSS font lists
            group = ET.SubElement(root, "{%s}g" % SVG_NS, {
                "id": "text", "font-family": layout.font.family(), "data-ict-font-name": template.font_name,
                "font-size": _fmt(layout.pixel_size / scale), "fill": rgb_hex(color),
                "fill-opacity": _fmt(alpha(color) / 255), "text-anchor": "middle",
                "font-weight": "300" if getattr(layout.font.weight(), "value", 400) <= 300 else "400"})
            for line, centre_x, baseline in layout.lines:
                # one <text> per line: QtSvg ignores x/y on <tspan>
                node = ET.SubElement(group, "{%s}text" % SVG_NS, {"x": _fmt(centre_x / scale),
                                                                  "y": _fmt(baseline / scale)})
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                node.text = line
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8"), report


def export_svg(template: IconTemplate, path: str | Path, size: int = 116) -> SvgReport:
    data, report = build_svg(template, size, path)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return report


def action_symbol_svg(data: bytes) -> bytes:
    """Transparent single-colour (black) SVG for the plugin's ``actionsymbols`` folder."""
    info = image_info(data)
    if info.format != "svg":
        raise IctError("Action-Symbole müssen SVG-Dateien sein; %s kann nicht verlustfrei umgewandelt werden – "
                       "bitte eine eigene einfarbige SVG wählen" % info.format.upper())
    if info.raster_inside_svg:
        raise IctError("Das SVG enthält eingebettete Rastergrafik und ist als Action-Symbol ungeeignet")
    if not info.monochrome:
        raise IctError("Das Symbol ist mehrfarbig. Logitech verlangt einfarbige (schwarze) Action-Symbole – "
                       "bitte eine separate einfarbige SVG wählen")
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise IctError("SVG ist beschädigt")
    return recolor_svg(data.decode("utf-8", "replace"), BLACK).encode("utf-8")


def export_action_symbol(data: bytes, path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".svg":
        raise IctError("Action-Symbole benötigen die Endung .svg")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(action_symbol_svg(data))
    return target


# --- import ------------------------------------------------------------------------

@dataclass
class PreparedImage:
    data: bytes
    filename: str
    info: ImageInfo
    notes: list[str] = field(default_factory=list)


GIF_STILL = "still"
GIF_ORIGINAL = "original"


def _shrink_to_png(image: QImage, notes: list[str], reason: str) -> bytes:
    edge = MAX_RASTER_EDGE
    while True:
        scaled = image
        if max(image.width(), image.height()) > edge:
            scaled = image.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        encoded = _png_bytes(scaled.convertToFormat(QImage.Format.Format_ARGB32))
        if len(encoded) <= MAX_IMAGE_BYTES or edge <= 64:
            break
        edge //= 2
    if len(encoded) > MAX_IMAGE_BYTES:
        raise IctError("Bild lässt sich nicht unter 150 KB bringen")
    notes.append("%s → PNG %d×%d px (%.1f KB, Transparenz erhalten)"
                 % (reason, scaled.width(), scaled.height(), len(encoded) / 1024))
    return encoded


def prepare_image(data: bytes, filename: str, gif_mode: str = GIF_STILL) -> PreparedImage:
    """Validate and, where needed, convert an image for embedding into an ICT."""
    if len(data) > MAX_INPUT_BYTES:
        raise IctError("Datei ist größer als 8 MB und wird nicht importiert")
    if not data:
        raise IctError("Datei ist leer")
    info = image_info(data)
    notes: list[str] = []
    stem = Path(filename).stem or "symbol"
    if info.format == "unknown":
        raise IctError("'%s' ist kein unterstütztes Bild (PNG, SVG, JPEG, BMP, WebP, GIF)" % filename)
    if info.format == "svg":
        if QSvgRenderer(QByteArray(data)).isValid() is False:
            raise IctError("SVG '%s' ist beschädigt oder ungültig" % filename)
        if len(data) > MAX_IMAGE_BYTES:
            raise IctError("SVG ist %.0f KB groß; Logitech erlaubt höchstens 150 KB – bitte vereinfachen"
                           % (len(data) / 1024))
        if info.raster_inside_svg:
            notes.append("SVG enthält eingebettete Rastergrafik – keine echte Vektorgrafik, nicht einfärbbar")
        return PreparedImage(data, Path(filename).name, info, notes)
    image = QImage.fromData(data)
    if image.isNull():
        raise IctError("Bild '%s' ist beschädigt oder kann nicht gelesen werden" % filename)
    if info.format == "gif" and info.animated and gif_mode == GIF_ORIGINAL:
        if len(data) > MAX_IMAGE_BYTES:
            raise IctError("Animiertes GIF ist %.0f KB groß und überschreitet die 150-KB-Grenze des Logitech-"
                           "Icon-Editors; die Animation kann nicht nachweislich kompatibel eingebettet werden – "
                           "bitte bewusst das Standbild verwenden" % (len(data) / 1024))
        notes.append("Animiertes GIF unverändert eingebettet. PNG-/SVG-Exporte zeigen nur das erste Bild; "
                     "ob der Logitech-Dienst eingebettete GIFs animiert, ist nicht verifiziert")
        return PreparedImage(data, Path(filename).name, info, notes)
    if info.format in ("png", "jpeg") and len(data) <= MAX_IMAGE_BYTES and \
            max(image.width(), image.height()) <= MAX_RASTER_EDGE:
        return PreparedImage(data, Path(filename).name, info, notes)
    if info.format == "gif":
        reason = "Animiertes GIF: bewusst erstes Einzelbild" if info.animated else "GIF"
    elif info.format in ("png", "jpeg"):
        reason = "%s %d×%d px (%.0f KB) verkleinert" % (info.format.upper(), image.width(), image.height(),
                                                         len(data) / 1024)
    else:
        reason = "%s umgewandelt" % info.format.upper()
    converted = _shrink_to_png(image, notes, reason)
    return PreparedImage(converted, stem + ".png", image_info(converted), notes)


def prepare_file(path: str | Path, gif_mode: str = GIF_STILL) -> PreparedImage:
    file = Path(path)
    try:
        size = file.stat().st_size
        if size > MAX_INPUT_BYTES:
            raise IctError("Datei ist größer als 8 MB und wird nicht importiert")
        data = file.read_bytes()
    except OSError as exc:
        raise IctError("Datei kann nicht gelesen werden: %s" % exc) from exc
    return prepare_image(data, file.name, gif_mode)
