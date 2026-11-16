"""Native Logitech icon templates (.ict).

The template dict is edited in place: only documented ICT keys are written,
every other key (``$type``, ``originalText``, ``isFullScreen``, unknown future
fields) stays byte-for-byte where it was. Geometry uses the native 100x100 grid.
Font-size and rotation semantics follow the Options+ Icon Editor (see
``work/widget-lab/icon-designer-v1/README.md``).
"""
from __future__ import annotations

import base64
import binascii
import copy
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

GRID = 100
EDITOR_CANVAS_PX = 192
EXPORT_SIZES = (50, 80, 116)
ROTATIONS = {"None": 0, "Rotate90": 90, "Rotate180": 180, "Rotate270": 270}
FONT_SIZES = tuple(range(1, 10))
DEFAULT_FONT = "Brown Logitech Pan Light"
IMAGE = "Image"
TEXT = "Text"
TYPE_NAMES = {IMAGE: "Loupedeck.Service.ActionIconImageItem, LoupedeckShared",
              TEXT: "Loupedeck.Service.ActionIconTextItem, LoupedeckShared"}
MAX_IMAGE_BYTES = 150 * 1024
WHITE = 0xFFFFFFFF
BLACK = 0xFF000000
KNOWN_TOP = {"backgroundColor", "items"}
KNOWN_ITEM = {IMAGE: {"$type", "image", "imageFileName", "imageColor", "imageRotation",
                      "isVisible", "itemType", "area"},
              TEXT: {"$type", "text", "originalText", "textColor", "fontSize", "fontName",
                     "isVisible", "itemType", "area"}}
KNOWN_AREA = {"x", "y", "width", "height", "isFullScreen"}


class IctError(ValueError):
    pass


def font_units(size: int) -> int:
    """ICT ``fontSize`` (1..9) as em height on the 100 grid, as in the Options+ editor."""
    return round(math.floor(17 * GRID / 116) * size / 5)


def editor_px(size: int) -> int:
    """Pixel value Options+ shows for an ICT ``fontSize`` (5 -> 27px)."""
    return round(font_units(size) * EDITOR_CANVAS_PX / GRID)


def argb_hex(value: int) -> str:
    value = int(value) & 0xFFFFFFFF
    return "#%08X" % value


def rgb_hex(value: int) -> str:
    return "#%06X" % (int(value) & 0xFFFFFF)


def parse_argb(text: str) -> int:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{8})", text.strip())
    if not match:
        raise IctError("Farbe muss #RRGGBB oder #AARRGGBB sein")
    digits = match.group(1)
    return int(("FF" + digits) if len(digits) == 6 else digits, 16)


def alpha(value: int) -> int:
    return (int(value) >> 24) & 0xFF


# --- image sources -----------------------------------------------------------

NAMED = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
         "blue": "#0000ff", "yellow": "#ffff00", "gray": "#808080", "grey": "#808080",
         "orange": "#ffa500", "purple": "#800080"}
COLOR_ATTRS = ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color")
IGNORED = {"none", "transparent", "inherit", "initial", "unset", ""}


def sniff_format(data: bytes) -> str:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if head.startswith(b"<svg") or (head.startswith((b"<?xml", b"<!--", b"<!DOCTYPE")) and b"<svg" in data[:4096]):
        return "svg"
    return "unknown"


def _norm_color(value: str) -> str | None:
    value = value.strip().lower()
    if value in IGNORED or value.startswith("url("):
        return None
    if value == "currentcolor":
        return "currentcolor"
    if value in NAMED:
        return NAMED[value]
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return "#" + "".join(c * 2 for c in value[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    if re.fullmatch(r"#[0-9a-f]{8}", value):
        return value[:7]
    match = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if match:
        parts = [p.strip() for p in match.group(1).replace("/", ",").split(",")]
        try:
            rgb = [round(float(p[:-1]) * 2.55) if p.endswith("%") else int(float(p)) for p in parts[:3]]
            return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in rgb)
        except ValueError:
            return value
    return value


def svg_colors(text: str) -> set[str]:
    found: set[str] = set()
    for attr in COLOR_ATTRS:
        for match in re.finditer(r'(?<![\w-])' + attr + r'\s*=\s*["\']([^"\']*)["\']', text):
            color = _norm_color(match.group(1))
            if color:
                found.add(color)
        for match in re.finditer(r'(?<![\w-])' + attr + r'\s*:\s*([^;"\'}]+)', text):
            color = _norm_color(match.group(1))
            if color:
                found.add(color)
    return found


@dataclass
class ImageInfo:
    format: str
    size_bytes: int
    monochrome: bool = False
    svg_color: int | None = None
    animated: bool = False
    raster_inside_svg: bool = False

    @property
    def tintable(self) -> bool:
        return self.format == "svg" and self.monochrome

    def describe(self) -> str:
        if self.format == "svg":
            if self.raster_inside_svg:
                kind = "SVG mit eingebetteter Rastergrafik – nicht einfärbbar"
            elif self.monochrome:
                kind = "einfarbiges SVG – Symbolfarbe wird von Logitech angewendet"
            else:
                kind = "mehrfarbiges SVG – Originalfarben bleiben erhalten"
        elif self.format == "gif":
            kind = "GIF" + (" (animiert)" if self.animated else "") + " – Rastergrafik, nicht einfärbbar"
        else:
            kind = self.format.upper() + " – Rastergrafik, nicht einfärbbar"
        return "%s, %.1f KB" % (kind, self.size_bytes / 1024)


def gif_frame_count(data: bytes, limit: int = 2) -> int:
    """Number of image descriptors (stops at ``limit``); walks the GIF block structure."""
    if len(data) < 13:
        return 0

    def skip_table(pos: int, flags: int) -> int:
        return pos + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)

    def skip_blocks(pos: int) -> int:
        while pos < len(data) and data[pos]:
            pos += data[pos] + 1
        return pos + 1

    pos, frames = skip_table(13, data[10]), 0
    while pos < len(data) and frames < limit:
        marker = data[pos]
        if marker == 0x21:
            pos = skip_blocks(pos + 2)
        elif marker == 0x2C and pos + 10 <= len(data):
            frames += 1
            pos = skip_blocks(skip_table(pos + 10, data[pos + 9]) + 1)
        else:
            break
    return frames


def image_info(data: bytes) -> ImageInfo:
    fmt = sniff_format(data)
    info = ImageInfo(fmt, len(data))
    if fmt == "svg":
        text = data.decode("utf-8", "replace")
        info.raster_inside_svg = bool(re.search(r"<(\w+:)?image[\s>]", text))
        colors = svg_colors(text)
        info.monochrome = len(colors) <= 1 and not info.raster_inside_svg
        if info.monochrome:
            color = next(iter(colors), "#000000")
            info.svg_color = 0xFF000000 | int(color[1:], 16) if color.startswith("#") else None
    elif fmt == "gif":
        info.animated = gif_frame_count(data) > 1
    return info


def recolor_svg(text: str, argb: int) -> str:
    """Replace every paint of a monochrome SVG by ``argb`` (used for SVG/action-symbol export)."""
    color = rgb_hex(argb)
    opacity = alpha(argb) / 255

    def attr(match):
        return match.group(0) if _norm_color(match.group(2)) is None else match.group(1) + color + match.group(3)

    def style(match):
        return match.group(0) if _norm_color(match.group(2)) is None else match.group(1) + color

    for name in COLOR_ATTRS:
        text = re.sub(r'((?<![\w-])' + name + r'\s*=\s*["\'])([^"\']*)(["\'])', attr, text)
        text = re.sub(r'((?<![\w-])' + name + r'\s*:\s*)([^;"\'}]+)', style, text)
    if not svg_colors(text):
        text = re.sub(r"<svg\b", '<svg fill="%s"' % color, text, count=1)
    if opacity < 1:
        text = re.sub(r"<svg\b", '<svg opacity="%.3f"' % opacity, text, count=1)
    return text


# --- template ------------------------------------------------------------------

@dataclass
class JsonStyle:
    indent: int = 2
    newline: str = "\n"
    bom: bool = False
    trailing_newline: bool = False
    ensure_ascii: bool = True

    @classmethod
    def detect(cls, raw: bytes) -> "JsonStyle":
        text = raw.decode("utf-8-sig")
        match = re.search(r"\n( +)\"", text)
        return cls(len(match.group(1)) if match else 2, "\r\n" if "\r\n" in text else "\n",
                   raw.startswith(b"\xef\xbb\xbf"), text.endswith("\n"),
                   all(ord(c) < 128 for c in text))


def default_image_item() -> dict:
    return {"$type": TYPE_NAMES[IMAGE], "image": "", "imageFileName": None, "imageColor": WHITE,
            "imageRotation": "None", "isVisible": True, "itemType": IMAGE,
            "area": {"x": 17, "y": 0, "width": 65, "height": 65}}


def default_text_item(text: str = "") -> dict:
    return {"$type": TYPE_NAMES[TEXT], "text": text, "textColor": WHITE, "fontSize": 5,
            "fontName": DEFAULT_FONT, "isVisible": True, "itemType": TEXT,
            "area": {"x": 0, "y": 65, "width": 100, "height": 30}}


def new_template_data(text: str = "Neue Aktion") -> dict:
    return {"backgroundColor": BLACK, "items": [default_image_item(), default_text_item(text)]}


def _int(value, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return fallback
    return int(round(value))


class IconTemplate:
    """Thin editor around a native ICT dict; reading never mutates the data."""

    def __init__(self, data: dict | None = None, style: JsonStyle | None = None):
        if data is None:
            data = new_template_data()
        if not isinstance(data, dict):
            raise IctError("ICT-Inhalt muss ein JSON-Objekt sein")
        if "items" in data and not isinstance(data["items"], list):
            raise IctError("ICT-Feld 'items' muss eine Liste sein")
        self.data = data
        self.style = style or JsonStyle()

    # persistence
    @classmethod
    def from_bytes(cls, raw: bytes) -> "IconTemplate":
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise IctError("ICT-Datei ist nicht UTF-8-kodiert") from exc
        except json.JSONDecodeError as exc:
            raise IctError("ICT-Datei ist kein gültiges JSON (Zeile %d, Spalte %d): %s"
                           % (exc.lineno, exc.colno, exc.msg)) from exc
        return cls(data, JsonStyle.detect(raw))

    @classmethod
    def load(cls, path: str | Path) -> "IconTemplate":
        file = Path(path)
        if file.stat().st_size > 16 * 1024 * 1024:
            raise IctError("ICT-Datei ist größer als 16 MB")
        return cls.from_bytes(file.read_bytes())

    def to_bytes(self) -> bytes:
        style = self.style
        text = json.dumps(self.data, indent=style.indent, ensure_ascii=style.ensure_ascii)
        if style.newline != "\n":
            text = text.replace("\n", style.newline)
        if style.trailing_newline:
            text += style.newline
        return (b"\xef\xbb\xbf" if style.bom else b"") + text.encode("utf-8")

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_bytes(self.to_bytes())
        temp.replace(target)
        return target

    def copy(self) -> "IconTemplate":
        return IconTemplate(copy.deepcopy(self.data), copy.copy(self.style))

    def snapshot(self) -> str:
        return json.dumps(self.data, sort_keys=False)

    def restore(self, snapshot: str) -> None:
        self.data.clear()
        self.data.update(json.loads(snapshot))

    # structure
    @property
    def items(self) -> list:
        items = self.data.get("items")
        return items if isinstance(items, list) else []

    def item(self, kind: str) -> dict | None:
        return next((i for i in self.items if isinstance(i, dict) and i.get("itemType") == kind), None)

    def ensure_item(self, kind: str) -> dict:
        found = self.item(kind)
        if found is not None:
            return found
        if not isinstance(self.data.get("items"), list):
            self.data["items"] = []
        created = default_image_item() if kind == IMAGE else default_text_item()
        if kind == IMAGE:
            self.data["items"].insert(0, created)
        else:
            self.data["items"].append(created)
        return created

    def stacking(self) -> list[str]:
        """Item kinds from bottom to top as drawn (list order)."""
        return [i["itemType"] for i in self.items if isinstance(i, dict) and i.get("itemType") in (IMAGE, TEXT)]

    def notices(self) -> list[str]:
        notes = []
        unknown_top = sorted(set(self.data) - KNOWN_TOP)
        if unknown_top:
            notes.append("Unbekannte Felder bleiben erhalten: " + ", ".join(unknown_top))
        if not isinstance(self.data.get("backgroundColor"), int):
            notes.append("Hintergrundfarbe fehlt oder ist ungültig – Vorschau verwendet Schwarz")
        counts: dict[str, int] = {}
        for index, item in enumerate(self.items):
            kind = item.get("itemType") if isinstance(item, dict) else None
            if kind not in (IMAGE, TEXT):
                notes.append("Element %d (%r) wird nicht bearbeitet, bleibt aber erhalten" % (index, kind))
                continue
            counts[kind] = counts.get(kind, 0) + 1
            extra = sorted(set(item) - KNOWN_ITEM[kind])
            area = item.get("area")
            if isinstance(area, dict):
                extra += ["area." + k for k in sorted(set(area) - KNOWN_AREA)]
            else:
                notes.append("%s-Element ohne gültigen Bereich – Standardbereich wird angezeigt" % kind)
            if extra:
                notes.append("%s: unbekannte Felder bleiben erhalten: %s" % (kind, ", ".join(extra)))
            if kind == IMAGE and item.get("imageFileName") and not item.get("image"):
                notes.append("Bild ist nur als Dateiname '%s' referenziert und nicht eingebettet – "
                             "Vorschau ohne Bild; zum Einbetten Bild ersetzen" % item["imageFileName"])
            if kind == IMAGE and isinstance(item.get("imageRotation"), str) and item["imageRotation"] not in ROTATIONS:
                notes.append("Unbekannte Rotation %r bleibt erhalten" % item["imageRotation"])
        for kind, count in counts.items():
            if count > 1:
                notes.append("%d %s-Elemente vorhanden – nur das erste wird bearbeitet" % (count, kind))
        return notes

    # background
    @property
    def background(self) -> int:
        return _int(self.data.get("backgroundColor"), BLACK) & 0xFFFFFFFF

    @background.setter
    def background(self, value: int) -> None:
        self.data["backgroundColor"] = int(value) & 0xFFFFFFFF

    # common item properties
    def area(self, kind: str) -> tuple[int, int, int, int]:
        item = self.item(kind) or {}
        area = item.get("area") if isinstance(item.get("area"), dict) else {}
        default = (default_image_item() if kind == IMAGE else default_text_item())["area"]
        return tuple(_int(area.get(k), default[k]) for k in ("x", "y", "width", "height"))

    def set_area(self, kind: str, x: int, y: int, width: int, height: int) -> None:
        item = self.ensure_item(kind)
        if not isinstance(item.get("area"), dict):
            item["area"] = {}
        item["area"].update({"x": int(x), "y": int(y), "width": max(1, int(width)), "height": max(1, int(height))})

    def visible(self, kind: str) -> bool:
        item = self.item(kind)
        return bool(item is not None and item.get("isVisible", True) is not False)

    def set_visible(self, kind: str, value: bool) -> None:
        self.ensure_item(kind)["isVisible"] = bool(value)

    # image
    def image_bytes(self) -> bytes | None:
        item = self.item(IMAGE)
        encoded = item.get("image") if item else None
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None

    def image_info(self) -> ImageInfo | None:
        data = self.image_bytes()
        return image_info(data) if data else None

    def set_image(self, data: bytes, filename: str | None) -> ImageInfo:
        info = image_info(data)
        if info.format == "unknown":
            raise IctError("Unbekanntes Bildformat")
        item = self.ensure_item(IMAGE)
        item["image"] = base64.b64encode(data).decode("ascii")
        item["imageFileName"] = filename or ""
        if info.tintable and info.svg_color is not None:
            item["imageColor"] = info.svg_color
        return info

    def clear_image(self) -> None:
        item = self.item(IMAGE)
        if item is not None:
            item["image"] = ""
            item["imageFileName"] = ""

    @property
    def image_color(self) -> int:
        return _int((self.item(IMAGE) or {}).get("imageColor"), WHITE) & 0xFFFFFFFF

    @image_color.setter
    def image_color(self, value: int) -> None:
        self.ensure_item(IMAGE)["imageColor"] = int(value) & 0xFFFFFFFF

    @property
    def rotation(self) -> int:
        return ROTATIONS.get((self.item(IMAGE) or {}).get("imageRotation"), 0)

    @rotation.setter
    def rotation(self, degrees: int) -> None:
        names = {v: k for k, v in ROTATIONS.items()}
        self.ensure_item(IMAGE)["imageRotation"] = names[int(degrees) % 360]

    # text
    @property
    def text(self) -> str:
        value = (self.item(TEXT) or {}).get("text")
        return value if isinstance(value, str) else ""

    @text.setter
    def text(self, value: str) -> None:
        self.ensure_item(TEXT)["text"] = value

    @property
    def text_color(self) -> int:
        return _int((self.item(TEXT) or {}).get("textColor"), WHITE) & 0xFFFFFFFF

    @text_color.setter
    def text_color(self, value: int) -> None:
        self.ensure_item(TEXT)["textColor"] = int(value) & 0xFFFFFFFF

    @property
    def font_size(self) -> int:
        return max(1, _int((self.item(TEXT) or {}).get("fontSize"), 5))

    @font_size.setter
    def font_size(self, value: int) -> None:
        if int(value) not in FONT_SIZES:
            raise IctError("Schriftgrad muss zwischen 1 und 9 liegen")
        self.ensure_item(TEXT)["fontSize"] = int(value)

    @property
    def font_name(self) -> str:
        value = (self.item(TEXT) or {}).get("fontName")
        return value if isinstance(value, str) and value else DEFAULT_FONT

    @font_name.setter
    def font_name(self, value: str) -> None:
        self.ensure_item(TEXT)["fontName"] = value.strip() or DEFAULT_FONT


# --- layouts -------------------------------------------------------------------

@dataclass(frozen=True)
class Layout:
    key: str
    label: str
    image: tuple[int, int, int, int]
    text: tuple[int, int, int, int]
    basic: bool = True


LAYOUTS = (
    Layout("image_top", "Symbol oben, Text unten", (17, 0, 65, 65), (0, 65, 100, 30)),
    Layout("text_top", "Text oben, Symbol unten", (17, 35, 65, 65), (0, 5, 100, 30)),
    Layout("image_center", "Symbol zentriert", (20, 20, 60, 60), (0, 70, 100, 30)),
    Layout("image_full", "Symbol flächig", (0, 0, 100, 100), (0, 70, 100, 30)),
    Layout("text_over", "Text mittig über Symbol", (0, 0, 100, 100), (0, 35, 100, 30), False),
    Layout("compact", "Kleines Symbol, große Textfläche", (30, 4, 40, 40), (0, 46, 100, 50), False),
)
LAYOUT_BY_KEY = {layout.key: layout for layout in LAYOUTS}


def apply_layout(template: IconTemplate, key: str) -> None:
    """Geometry only: content, colours and visibility stay untouched."""
    layout = LAYOUT_BY_KEY[key]
    for kind, area in ((IMAGE, layout.image), (TEXT, layout.text)):
        if template.item(kind) is not None:
            template.set_area(kind, *area)


def detect_layout(template: IconTemplate) -> str | None:
    for layout in LAYOUTS:
        if all(template.item(k) is None or template.area(k) == a
               for k, a in ((IMAGE, layout.image), (TEXT, layout.text))):
            return layout.key
    return None


# --- style transfer -------------------------------------------------------------

STYLE_ASPECTS = {
    "background": "Hintergrundfarbe",
    "layout": "Layout: Positionen und Größen",
    "visibility": "Sichtbarkeit von Symbol und Text",
    "font": "Schriftart und Schriftgrad",
    "text_color": "Textfarbe",
    "symbol_format": "Symbolfarbe und Drehung (soweit unterstützt)",
}
PROTECTED = ("image", "imageFileName", "text", "originalText", "itemType", "$type")


@dataclass
class StyleResult:
    changes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def transfer_style(source: IconTemplate, target: IconTemplate, aspects) -> StyleResult:
    """Copy design properties to ``target``; image/text content is never touched."""
    aspects = set(aspects)
    unknown = aspects - set(STYLE_ASPECTS)
    if unknown:
        raise IctError("Unbekannte Gestaltungsmerkmale: " + ", ".join(sorted(unknown)))
    result = StyleResult()

    def change(label, before, after, apply):
        if before != after:
            apply()
            result.changes.append("%s: %s → %s" % (label, before, after))

    if "background" in aspects:
        change("Hintergrund", argb_hex(target.background), argb_hex(source.background),
               lambda: setattr(target, "background", source.background))
    for kind, name in ((IMAGE, "Symbol"), (TEXT, "Text")):
        if not aspects & {"layout", "visibility"}:
            break
        if source.item(kind) is None:
            continue
        if target.item(kind) is None:
            result.skipped.append("%s: Ziel enthält kein %s-Element – Layout/Sichtbarkeit übersprungen" % (name, name))
            continue
        if "layout" in aspects:
            change(name + "-Bereich", target.area(kind), source.area(kind),
                   lambda k=kind: target.set_area(k, *source.area(k)))
        if "visibility" in aspects:
            change(name + " sichtbar", target.visible(kind), source.visible(kind),
                   lambda k=kind: target.set_visible(k, source.visible(k)))
    if aspects & {"font", "text_color"} and source.item(TEXT) is not None:
        if target.item(TEXT) is None:
            result.skipped.append("Text: Ziel enthält kein Text-Element – Schrift/Textfarbe übersprungen")
        else:
            if "font" in aspects:
                change("Schriftart", target.font_name, source.font_name,
                       lambda: setattr(target, "font_name", source.font_name))
                change("Schriftgrad", target.font_size, source.font_size,
                       lambda: setattr(target, "font_size", source.font_size))
            if "text_color" in aspects:
                change("Textfarbe", argb_hex(target.text_color), argb_hex(source.text_color),
                       lambda: setattr(target, "text_color", source.text_color))
    if "symbol_format" in aspects and source.item(IMAGE) is not None:
        if target.item(IMAGE) is None:
            result.skipped.append("Symbol: Ziel enthält kein Bild – Symbolformat übersprungen")
        else:
            change("Drehung", "%d°" % target.rotation, "%d°" % source.rotation,
                   lambda: setattr(target, "rotation", source.rotation))
            info = target.image_info()
            if info is not None and info.tintable:
                change("Symbolfarbe", argb_hex(target.image_color), argb_hex(source.image_color),
                       lambda: setattr(target, "image_color", source.image_color))
            else:
                reason = info.describe() if info else "kein eingebettetes Bild"
                result.skipped.append("Symbolfarbe nicht übertragen – Ziel-Bild ist nicht einfärbbar (%s)" % reason)
    return result


def preview_style(source: IconTemplate, target: IconTemplate, aspects) -> tuple[IconTemplate, StyleResult]:
    candidate = target.copy()
    return candidate, transfer_style(source, candidate, aspects)


def content_fingerprint(template: IconTemplate) -> list:
    """Everything a style transfer must never change (used by tests and the dialog)."""
    rows = []
    for item in template.items:
        if isinstance(item, dict):
            rows.append({k: item.get(k) for k in PROTECTED if k in item})
            rows[-1]["unknown"] = {k: v for k, v in item.items()
                                   if k not in KNOWN_ITEM.get(item.get("itemType"), set())}
    rows.append({k: v for k, v in template.data.items() if k not in KNOWN_TOP})
    return rows
