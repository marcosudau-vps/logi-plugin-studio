"""Render the real KeypadPreviewWidget against the device reference screenshots.

Start: python tools\\keypad_preview_visual_check.py --out DIR [--references DIR]

Uses the normal Qt platform, so that text comes out as it does on Windows. Windows
stay hidden and the pointer is not moved: input is sent as Qt events to the widget.
Writes isolated widget images, side-by-side comparisons and pixel measurements.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# The references are 1:1 device pixels; a scaled monitor would otherwise blur every comparison.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (QColor, QDragEnterEvent, QDragMoveEvent, QFont, QImage, QMouseEvent, QPainter, QPixmap)
from PySide6.QtWidgets import QApplication

from studio.keypad_contract import ActionOffer
from studio.keypad_preview import KeypadPreviewWidget, load_logikeypad_skin
from studio.keypad_preview.lab_host import VISUAL_REFERENCE, LabHost
from studio.keypad_preview.skin import ASSET_ARROW_RECTS, ASSET_KEY_RECTS, ASSET_NATIVE_SIZE, drag_label_pixmap, find_logikeypad_directory
from studio.keypad_preview.mime import ACTION_REF_MIME, encode_action_ref

BACKGROUND = "#1a1a1a"
# Canvas position inside each reference screenshot, found by aligning the case layer.
REFERENCE_OFFSETS = {"Pagination.png": (106, 33), "NextPageButton.png": (22, 36), "PreviousPageButton.png": (301, 60),
                     "DreiPunkteMenu.png": (19, 11)}
LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton
NOMOD = Qt.KeyboardModifier.NoModifier


def default_references() -> Path:
    return ROOT.parent / "graphics_pictures" / "KeypadPreviewWidget"


def make_widget(scale: float, *, scenario: str = "reference", editing: bool = False) -> tuple[KeypadPreviewWidget, LabHost]:
    skin, problem = load_logikeypad_skin(find_logikeypad_directory(ROOT))
    if skin is None:
        raise SystemExit("Originalgrafiken nicht nutzbar: " + problem)
    host = LabHost(scenario, visual_mode=VISUAL_REFERENCE)
    widget = KeypadPreviewWidget()
    widget.set_skin(skin)
    widget.set_motion_enabled(False)
    if editing:
        widget.set_mode("edit")
        widget.set_edit_allowed(True)
    widget.set_frame(host.frame())
    widget.resize(widget.size_for_scale(scale))
    host.frameChanged.connect(widget.set_frame)
    return widget, host


def send_mouse(widget, kind, position: QPointF, button=NONE, buttons=NONE) -> None:
    QApplication.sendEvent(widget, QMouseEvent(kind, position, widget.mapToGlobal(position), button, buttons, NOMOD))


def move(widget, position: QPointF) -> None:
    send_mouse(widget, QEvent.Type.MouseMove, position)


def grab(widget) -> QImage:
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)


def with_menu(widget, index: int) -> QImage:
    """QMenu is its own window, so the image is put together like the screen would show it."""
    image = grab(widget)
    menu = widget._build_menu(index)
    menu.adjustSize()
    picture = menu.grab()
    painter = QPainter(image)
    painter.drawPixmap(widget._menu_anchor(index), picture)
    painter.end()
    menu.deleteLater()
    return image


def isolated_images(out: Path) -> None:
    """Empty, occupied and pressed keys, menu and drag markers at 60 % and 100 %."""
    for percent in (60, 100):
        scale = percent / 100
        widget, host = make_widget(scale)
        grab(widget).save(str(out / f"widget_{percent}_belegt_und_leer.png"))
        host.show_page(4)
        grab(widget).save(str(out / f"widget_{percent}_alle_leer.png"))
        host.show_page(1)
        widget.resize(widget.size_for_scale(scale))
        center = widget.slot_rect(1).center()
        move(widget, center)
        send_mouse(widget, QEvent.Type.MouseButtonPress, center, LEFT, LEFT)
        grab(widget).save(str(out / f"widget_{percent}_taste_gedrueckt.png"))
        send_mouse(widget, QEvent.Type.MouseButtonRelease, center, LEFT, NONE)
        grab(widget).save(str(out / f"widget_{percent}_ausgewaehlt.png"))
        widget.deleteLater()

        widget, host = make_widget(scale, editing=True)
        move(widget, widget.slot_rect(1).center())
        grab(widget).save(str(out / f"widget_{percent}_edit_hover.png"))
        move(widget, widget.menu_button_rect(1).center())
        grab(widget).save(str(out / f"widget_{percent}_edit_drei_punkte.png"))
        with_menu(widget, 1).save(str(out / f"widget_{percent}_edit_kontextmenue.png"))
        drag_markers(widget, host, 4).save(str(out / f"widget_{percent}_drag_ziel.png"))
        widget.deleteLater()


def drag_markers(widget, host: LabHost, index: int) -> QImage:
    from PySide6.QtCore import QByteArray, QMimeData

    mime = QMimeData()
    mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(ActionOffer("lab.ref.access_ring", "Access Ring"))))
    position = widget.slot_rect(index).center()
    actions = Qt.DropAction.CopyAction
    widget.dragEnterEvent(QDragEnterEvent(position, actions, mime, LEFT, NOMOD))
    widget.dragMoveEvent(QDragMoveEvent(position, actions, mime, LEFT, NOMOD))
    image = grab(widget)
    pixmap, hotspot = drag_label_pixmap("Access Ring")
    painter = QPainter(image)
    painter.drawPixmap(position - hotspot, pixmap)
    painter.end()
    widget._drag_active = False
    widget._clear_drop()
    return image


def rgb_bytes(image: QImage) -> tuple[bytes, int, int]:
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height, line = converted.width(), converted.height(), converted.bytesPerLine()
    raw = bytes(converted.constBits())
    return b"".join(raw[y * line:y * line + width * 3] for y in range(height)), width, height


def mean_difference(a: QImage, b: QImage, rect: QRect) -> float:
    first, width, _ = rgb_bytes(a.copy(rect))
    second, _, _ = rgb_bytes(b.copy(rect))
    total = sum(abs(x - y) for x, y in zip(first, second))
    return round(total / (len(first) or 1), 2)


def side_by_side(reference: QImage, output: QImage, title: str, target: Path) -> None:
    """Reference, output and amplified difference, unscaled. Differences can't hide this way."""
    width, height = reference.width(), reference.height()
    head = 34
    sheet = QPixmap(width * 3 + 40, height + head + 10)
    sheet.fill(QColor("#101010"))
    painter = QPainter(sheet)
    font = QFont("Segoe UI")
    font.setPixelSize(16)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QPoint(10, 23), f"Referenz: {title}")
    painter.drawText(QPoint(width + 30, 23), "Ausgabe des Widgets")
    painter.drawText(QPoint(2 * width + 50, 23), "Betrag der Differenz, 3-fach")
    painter.drawImage(QPoint(0, head), reference)
    painter.drawImage(QPoint(width + 20, head), output)
    difference = reference.copy()
    inner = QPainter(difference)
    inner.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
    inner.drawImage(QPoint(0, 0), output)
    inner.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    inner.drawImage(QPoint(0, 0), difference.copy())
    inner.drawImage(QPoint(0, 0), difference.copy())
    inner.end()
    painter.drawImage(QPoint(2 * width + 40, head), difference)
    painter.end()
    sheet.save(str(target))


def crop_reference(references: Path, name: str, size: QSize) -> QImage:
    x, y = REFERENCE_OFFSETS[name]
    image = QImage(str(references / name)).convertToFormat(QImage.Format.Format_ARGB32)
    canvas = QImage(size, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(BACKGROUND))
    painter = QPainter(canvas)
    painter.drawImage(QPoint(0, 0), image, QRect(x, y, size.width(), size.height()))
    painter.end()
    return canvas


def comparisons(references: Path, out: Path) -> dict:
    metrics: dict = {}

    def regions(reference: QImage, output: QImage) -> dict:
        native_w, native_h = ASSET_NATIVE_SIZE
        return {"gesamt_ohne_tasten": mean_difference(reference, output, QRect(0, 526, native_w, 198)),
                "seitenleiste": mean_difference(reference, output, QRect(120, 765, 420, 50))}

    widget, host = make_widget(1.0, editing=True)
    size = widget.size()
    move(widget, widget.slot_rect(1).center())
    move(widget, widget.menu_button_rect(1).center())
    output = grab(widget)
    reference = crop_reference(references, "Pagination.png", size)
    side_by_side(reference, output, "Pagination.png", out / "vergleich_1_pagination.png")
    entry = regions(reference, output)
    for name, index in (("leere_taste_3", 3), ("leere_taste_4", 4), ("leere_taste_6", 6)):
        entry[name] = mean_difference(reference, output, QRect(*ASSET_KEY_RECTS[index]))
    for name, index in (("schwarze_taste_oben_7", 7), ("schwarze_taste_oben_8", 8)):
        x, y, w, _ = ASSET_KEY_RECTS[index]
        entry[name] = mean_difference(reference, output, QRect(x, y, w, 40))
    metrics["Pagination.png"] = entry

    host.show_page(2)
    widget.resize(size)
    move(widget, widget.arrow_rect(1).center())
    output = grab(widget)
    reference = crop_reference(references, "NextPageButton.png", size)
    side_by_side(reference, output, "NextPageButton.png", out / "vergleich_2_naechste_seite.png")
    metrics["NextPageButton.png"] = {"pfeil_hover": mean_difference(reference, output, QRect(*ASSET_ARROW_RECTS[1])),
                                     "gehaeuse_unten": mean_difference(reference, output, QRect(0, 640, ASSET_NATIVE_SIZE[0], 84))}
    widget.deleteLater()

    widget, host = make_widget(1.0)
    move(widget, widget.arrow_rect(-1).center())
    output = grab(widget)
    reference = crop_reference(references, "PreviousPageButton.png", size)
    side_by_side(reference, output, "PreviousPageButton.png", out / "vergleich_3_vorherige_seite.png")
    metrics["PreviousPageButton.png"] = {"pfeil_hover": mean_difference(reference, output, QRect(*ASSET_ARROW_RECTS[-1]))}
    widget.deleteLater()

    widget, host = make_widget(1.0, editing=True)
    host.show_page(2)
    move(widget, widget.slot_rect(7).center())
    move(widget, widget.menu_button_rect(7).center())
    output = with_menu(widget, 7)
    reference = crop_reference(references, "DreiPunkteMenu.png", size)
    side_by_side(reference, output, "DreiPunkteMenu.png", out / "vergleich_4_drei_punkte_menue.png")
    widget.deleteLater()

    # The drag reference has another scale and other slots, so here only the look is put side by side.
    reference = QImage(str(references / "DragNDrop_ColoredOverlayAndBorder.png")).convertToFormat(QImage.Format.Format_ARGB32)
    widget, host = make_widget(0.67, editing=True)
    output = drag_markers(widget, host, 4)
    sheet = QPixmap(reference.width() + output.width() + 20, max(reference.height(), output.height()))
    sheet.fill(QColor(BACKGROUND))
    painter = QPainter(sheet)
    painter.drawImage(QPoint(0, 0), reference)
    painter.drawImage(QPoint(reference.width() + 20, 0), output)
    painter.end()
    sheet.save(str(out / "vergleich_5_drag_drop.png"))
    widget.deleteLater()
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=default_references())
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    isolated_images(args.out)
    report: dict = {"platform": app.platformName(), "font_segoe_ui": QFont("Segoe UI").exactMatch(),
                    "device_pixel_ratio": app.devicePixelRatio(),
                    "references": args.references.is_dir()}
    if args.references.is_dir():
        report["mean_abs_channel_difference"] = comparisons(args.references, args.out)
    (args.out / "visual_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
