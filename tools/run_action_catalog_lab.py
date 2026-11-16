"""Action Catalog Lab: the real ActionCatalogWidget in a small simulated host.

Start: python tools\\run_action_catalog_lab.py [--project DATEI] [--output ORDNER] [--smoke] [--evidence ORDNER] [--os-drag-check ORDNER]

Needs no Logitech service, login or installation. Project files are only read.
The extra lab actions exist in memory and pass through the real native parser.
The keypad under parallel correction is deliberately not used as the drop target:
a neutral target checks the same MIME payload through the existing decoder.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
    from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QFont, QImage, QPainter, QPalette, QPen
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                                   QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print("PySide6 fehlt. Die dokumentierte lokale Python-Umgebung verwenden.", file=sys.stderr)
        raise SystemExit(2) from exc
    raise

from adapters.logitech.native import NativeProject, parse_native_project, project_view
from studio.action_catalog import ActionCatalogWidget
from studio.keypad_contract import ActionOffer
from studio.keypad_preview.mime import ACTION_REF_MIME, decode_action_ref

EXAMPLE_PROJECT = ROOT / "examples" / "project_logitech_native_v1.json"
DEFAULT_OUTPUT = ROOT / "work" / "widget-lab" / "action-catalog-v1" / "lab-output"
WIDTHS = (280, 320, 380)

# Parameter names are deliberately unrelated to their display texts: nothing can be derived.
LAB_ACTIONS = (
    {"id": "lab.scene", "sdk_type": "PluginDynamicCommand", "display_name": "Szene aktivieren",
     "description": "Lab-Aktion im Speicher mit mehreren SDK-Parametern.", "group_name": "Lab-Szenen", "handler": "handler.main",
     "parameters": [
         {"name": "p-7f3a", "display_name": "Morgenlicht", "group_name": "Wohnzimmer"},
         {"name": "p-19c0", "display_name": "Abendlicht", "group_name": "Wohnzimmer"},
         {"name": "scene:night/2", "display_name": "Nachtmodus", "group_name": "Schlafzimmer", "super_group_name": "Haus"},
     ]},
    {"id": "lab.volume", "sdk_type": "PluginDynamicAdjustment", "display_name": "Mischpult-Kanal",
     "description": "Lab-Einstellung mit Parametern.", "group_name": "Lab-Audio", "handler": "handler.main",
     "parameters": [
         {"name": "ch-a", "display_name": "Kanal Musik", "group_name": "Mixer"},
         {"name": "ch-b", "display_name": "Kanal Sprache", "group_name": "Mixer"},
     ],
     "adjustment": {"has_reset": True, "minimum": 0, "maximum": 100, "default": 50}},
    {"id": "lab.mute", "sdk_type": "PluginMultistateDynamicCommand",
     "display_name": "Stummschaltung mit einem sehr langen Anzeigenamen für die schmale Sidebar",
     "description": "Prüft das Kürzen langer Titel.", "group_name": "Lab-Audio", "handler": "handler.main",
     "state_change": "toggle",
     "states": [{"index": 0, "name": "off", "display_name": "Aus", "description": ""},
                {"index": 1, "name": "on", "display_name": "An", "description": ""}]},
)
_STRESS_TYPES = ("PluginDynamicCommand", "PluginMultistateDynamicCommand", "PluginDynamicAdjustment", "ActionEditorCommand")
_STRESS_GROUPS = ("Audio", "Beleuchtung", "Kamera", "Stream", "Werkzeuge", "Zeitleiste")


def read_project_file(path: Path) -> NativeProject:
    """Read only. Raises a readable error; the file is never changed."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return project_view(raw)


def example_raw() -> dict:
    return json.loads(EXAMPLE_PROJECT.read_text(encoding="utf-8"))


def example_project() -> NativeProject:
    return parse_native_project(example_raw())


def example_with_lab_actions() -> NativeProject:
    raw = example_raw()
    raw["actions"].extend(copy.deepcopy(LAB_ACTIONS))
    return parse_native_project(raw)


def stress_project(count: int) -> NativeProject:
    """``count`` native actions through the real parser; every fifth one has two parameters."""
    actions = []
    for index in range(count):
        sdk_type = _STRESS_TYPES[index % len(_STRESS_TYPES)]
        action = {"id": f"stress.action.{index:04d}", "sdk_type": sdk_type, "display_name": f"Testaktion {index:04d}",
                  "description": f"Lasttest {index}", "group_name": _STRESS_GROUPS[index % len(_STRESS_GROUPS)],
                  "handler": "handler.main"}
        if sdk_type == "PluginMultistateDynamicCommand":
            action["states"] = [{"index": 0, "name": "a", "display_name": "A", "description": ""},
                                {"index": 1, "name": "b", "display_name": "B", "description": ""}]
        if index % 5 == 0:
            action["parameters"] = [{"name": f"param-{index}-{n}", "display_name": f"Variante {n}", "group_name": "Varianten"}
                                    for n in (1, 2)]
        actions.append(action)
    return parse_native_project({"schema_version": "logitech-native-1",
                                 "plugin": {"id": "stress.plugin", "display_name": f"Lasttest mit {count} Aktionen"},
                                 "handlers": [{"id": "handler.main", "callback_id": "handler.main"}],
                                 "actions": actions, "folders": []})


def offer_keys(project: NativeProject) -> list[tuple[str, str | None]]:
    keys: list[tuple[str, str | None]] = []
    for action in project.actions:
        if action.parameters:
            keys.extend((action.id, parameter.name) for parameter in action.parameters)
        else:
            keys.append((action.id, None))
    return keys


def host_images(project: NativeProject) -> dict[tuple[str, str | None], QImage]:
    """Stand-in for host previews: every second entry, so the fallback stays visible next to it."""
    images: dict[tuple[str, str | None], QImage] = {}
    for index, key in enumerate(offer_keys(project)):
        if index % 2:
            continue
        digest = hashlib.sha256(repr(key).encode("utf-8")).digest()
        color = QColor.fromHsv(digest[0] * 359 // 255, 150, 185)
        image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(color)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 215))
        painter.drawEllipse(QPointF(48, 48), 22, 22)
        painter.end()
        images[key] = image
    return images


def host_usage(project: NativeProject) -> dict[tuple[str, str | None], int]:
    """Simulated host report, shown only while the lab option is active."""
    keys = offer_keys(project)
    return {key: index + 1 for index, key in enumerate(keys[:3])}


def describe_offer(offer: ActionOffer) -> dict:
    return {"action_id": offer.action_id, "display_name": offer.display_name, "action_parameter": offer.action_parameter,
            "tile_image": None if offer.tile_image is None else f"{offer.tile_image.width()}x{offer.tile_image.height()}"}


class NeutralDropTarget(QFrame):
    """Check for real drops. It only reads the existing reference format, and places nothing."""

    received = Signal(object)  # dict with formats, raw payload and decoded reference
    refused = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("neutralDropTarget")
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self._hovering = False
        layout = QVBoxLayout(self)
        self.status = QLabel("Neutrale Drop-Prüfung: Eintrag aus dem Katalog hierher ziehen.\nKein Keypad, keine Platzierung.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

    def paintEvent(self, event) -> None:
        # Painted, not a style sheet: a sheet would freeze the label's palette on a theme change.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().color(QPalette.ColorRole.WindowText), 2,
                   Qt.PenStyle.SolidLine if self._hovering else Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    def _decode(self, mime: QMimeData) -> tuple[str, str | None] | None:
        return decode_action_ref(bytes(mime.data(ACTION_REF_MIME))) if mime.hasFormat(ACTION_REF_MIME) else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._decode(event.mimeData()) is None:
            self.refused.emit("Drag abgelehnt: keine gültige action-ref-Nutzlast")
            event.ignore()
            return
        self._hovering = True
        self.update()
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hovering = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self.update()
        mime = event.mimeData()
        reference = self._decode(mime)
        if reference is None:
            self.refused.emit("Drop abgelehnt: keine gültige action-ref-Nutzlast")
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        payload = bytes(mime.data(ACTION_REF_MIME))
        self.status.setText(f"decode_action_ref → action_id={reference[0]!r}, action_parameter={reference[1]!r}\n"
                            f"{ACTION_REF_MIME}\n{payload.decode('utf-8')}")
        self.received.emit({"formats": list(mime.formats()), "payload": payload.decode("utf-8"),
                            "action_id": reference[0], "action_parameter": reference[1],
                            "offered_actions": event.possibleActions().value})


class ActionCatalogLabWindow(QMainWindow):
    def __init__(self, output: Path = DEFAULT_OUTPUT, project_path: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("actionCatalogLabWindow")
        self.setWindowTitle("Action Catalog Lab – simulierter Host, keine Hardware")
        self.resize(1160, 820)
        self.output = Path(output)
        self.events: list[dict] = []
        self.project: NativeProject | None = None
        self.catalog = ActionCatalogWidget()
        self.drop_target = NeutralDropTarget()
        self._build_ui()
        self.catalog.actionSelected.connect(self._on_action_selected)
        self.catalog.actionEditRequested.connect(lambda action_id: self.log(
            "actionEditRequested", f"action_id={action_id!r} (nur Intent, nichts geöffnet)", {"action_id": action_id}))
        self.catalog.createActionRequested.connect(lambda: self.log(
            "createActionRequested", "nur Intent, keine Aktionsdatei erstellt", {}))
        self.drop_target.received.connect(lambda data: self.log(
            "drop", f"action_id={data['action_id']!r}, action_parameter={data['action_parameter']!r}", data))
        self.drop_target.refused.connect(lambda text: self.log("drop-abgelehnt", text, {}))
        if project_path is not None:
            self.open_project_file(project_path)
        else:
            self.load_source(0)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.sidebar = QFrame()
        self.sidebar.setObjectName("labSidebar")
        self.sidebar.setFrameShape(QFrame.Shape.StyledPanel)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.catalog)
        self.sidebar.setFixedWidth(WIDTHS[1])

        self.banner = QLabel()
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.setWordWrap(True)
        self.banner.setObjectName("labBanner")

        controls = QGridLayout()
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(6)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["Beispielprojekt + Lab-Parameteraktionen (set_project)", "Nur Beispielprojekt (set_project)",
                                    "Kein Projekt (set_project(None))", "Leere Liste (set_actions(()))",
                                    "50 Aktionen (set_actions)", "300 Aktionen (set_actions)", "Defekte Projektdatei (Demo)"])
        self.source_combo.activated.connect(self.load_source)
        self.open_button = QPushButton("Projektdatei lesen …")
        self.open_button.clicked.connect(self._choose_project)
        controls.addWidget(QLabel("Datenquelle"), 0, 0)
        controls.addWidget(self.source_combo, 0, 1, 1, 2)
        controls.addWidget(self.open_button, 0, 3)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Text für set_filter()")
        self.filter_button = QPushButton("set_filter")
        self.filter_button.clicked.connect(lambda: self._program_filter(self.filter_edit.text()))
        controls.addWidget(QLabel("Filter"), 1, 0)
        controls.addWidget(self.filter_edit, 1, 1, 1, 2)
        controls.addWidget(self.filter_button, 1, 3)

        self.select_combo = QComboBox()
        self.select_button = QPushButton("set_selected_action")
        self.select_button.clicked.connect(self._program_select)
        self.clear_button = QPushButton("Aufheben")
        self.clear_button.clicked.connect(lambda: self._program_select(clear=True))
        controls.addWidget(QLabel("Auswahl"), 2, 0)
        controls.addWidget(self.select_combo, 2, 1)
        controls.addWidget(self.clear_button, 2, 2)
        controls.addWidget(self.select_button, 2, 3)

        self.images_check = QCheckBox("Host liefert QImage-Vorschauen")
        self.images_check.toggled.connect(lambda _: self._apply_host_data())
        self.usage_check = QCheckBox("Host meldet Nutzung")
        self.usage_check.toggled.connect(lambda _: self._apply_host_data())
        self.width_combo = QComboBox()
        self.width_combo.addItems([f"{width} px" for width in WIDTHS])
        self.width_combo.setCurrentIndex(1)
        self.width_combo.currentIndexChanged.connect(lambda index: self.sidebar.setFixedWidth(WIDTHS[index]))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dunkel", "Hell"])
        self.theme_combo.currentIndexChanged.connect(lambda index: apply_lab_theme(QApplication.instance(), dark=index == 0))
        host_row = QHBoxLayout()
        for widget in (self.images_check, self.usage_check, QLabel("Breite"), self.width_combo, QLabel("Thema"), self.theme_combo):
            host_row.addWidget(widget)
        host_row.addStretch(1)
        controls.addWidget(QLabel("Host"), 3, 0)
        controls.addLayout(host_row, 3, 1, 1, 3)

        self.shot_widget_button = QPushButton("Screenshot Widget")
        self.shot_widget_button.clicked.connect(lambda: self.save_screenshot(self.catalog, "catalog"))
        self.shot_lab_button = QPushButton("Screenshot Lab")
        self.shot_lab_button.clicked.connect(lambda: self.save_screenshot(self, "lab"))
        self.clear_log_button = QPushButton("Protokoll leeren")
        shot_row = QHBoxLayout()
        for widget in (self.shot_widget_button, self.shot_lab_button, self.clear_log_button):
            shot_row.addWidget(widget)
        shot_row.addStretch(1)
        controls.addWidget(QLabel("Ausgabe"), 4, 0)
        controls.addLayout(shot_row, 4, 1, 1, 3)
        controls.setColumnStretch(1, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("labEventLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        log_font = QFont("Consolas")
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(log_font)
        self.clear_log_button.clicked.connect(self._clear_log)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("Host-Ereignisprotokoll: actionSelected / actionEditRequested / createActionRequested / drop"))
        log_layout.addWidget(self.log_view, 1)
        host_split = QSplitter(Qt.Orientation.Vertical)
        host_split.addWidget(self.drop_target)
        host_split.addWidget(log_panel)
        host_split.setStretchFactor(1, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.banner)
        right_layout.addLayout(controls)
        right_layout.addWidget(host_split, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        layout.addWidget(self.sidebar, 0)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------ log

    def log(self, kind: str, text: str, data: dict) -> None:
        self.events.append({"kind": kind, **data})
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {kind:<22} {text}")

    def _clear_log(self) -> None:
        self.events.clear()
        self.log_view.clear()

    def _on_action_selected(self, offer: ActionOffer) -> None:
        self.log("actionSelected", f"action_id={offer.action_id!r}, action_parameter={offer.action_parameter!r}, "
                                   f"display_name={offer.display_name!r}", describe_offer(offer))

    def _set_banner(self, text: str, *, error: bool = False) -> None:
        self.banner.setText(text)
        self.banner.setStyleSheet("background:#8a2f2f;color:white;padding:6px;border-radius:4px;" if error else "")

    # ------------------------------------------------------------------ host input

    def load_source(self, index: int) -> None:
        self.source_combo.setCurrentIndex(index)
        if index == 0:
            self._show_project(example_with_lab_actions(), "Beispielprojekt plus Lab-Aktionen im Speicher; die Datei bleibt unverändert")
        elif index == 1:
            self._show_project(example_project(), f"Unverändert aus {EXAMPLE_PROJECT.name}")
        elif index == 2:
            self._show_project(None, "set_project(None)")
        elif index == 3:
            self.project = None
            self.catalog.set_actions(())
            self._after_data_change("set_actions(()): leere Liste")
        elif index in (4, 5):
            project = stress_project(50 if index == 4 else 300)
            self.project = project
            started = time.perf_counter()
            self.catalog.set_actions(project.actions)
            elapsed = (time.perf_counter() - started) * 1000
            self._after_data_change(f"set_actions: {len(project.actions)} Aktionen in {elapsed:.0f} ms")
        else:
            self._show_load_error("Demo", self._broken_project_error())

    @staticmethod
    def _broken_project_error() -> str:
        raw = example_raw()
        raw["actions"][0]["sdk_type"] = "PluginDynamicFolder"
        try:
            parse_native_project(raw)
        except ValueError as exc:
            return str(exc)
        return "Unerwartet gültig"

    def _show_project(self, project: NativeProject | None, text: str) -> None:
        self.project = project
        self.catalog.set_project(project)
        self._after_data_change(text)

    def _after_data_change(self, text: str) -> None:
        self._apply_host_data()
        self._refresh_select_combo()
        self._set_banner(text)
        self.log("host", text, {})

    def _show_load_error(self, source: str, message: str) -> None:
        """The previous project stays on display; a failed import changes nothing."""
        text = f"Import fehlgeschlagen ({source}): {message}"
        self._set_banner(text, error=True)
        self.log("importfehler", text, {"message": message})

    def open_project_file(self, path: Path) -> None:
        try:
            project = read_project_file(path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self._show_load_error(str(path), str(exc))
            return
        self._show_project(project, f"Nur gelesen: {path}")

    def _choose_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Projektdatei lesen", str(EXAMPLE_PROJECT.parent), "Projekt (*.json)")
        if path:
            self.open_project_file(Path(path))

    def _apply_host_data(self) -> None:
        project = self.project
        self.catalog.set_images(host_images(project) if project is not None and self.images_check.isChecked() else {})
        self.catalog.set_usage_counts(host_usage(project) if project is not None and self.usage_check.isChecked() else {})

    def _refresh_select_combo(self) -> None:
        self.select_combo.clear()
        if self.project is not None:
            for key in offer_keys(self.project)[:200]:
                self.select_combo.addItem(f"{key[0]} / {key[1]!r}", key)

    def _program_filter(self, text: str) -> None:
        self.catalog.set_filter(text)
        self.log("host", f"set_filter({text!r}), kein Signal erwartet", {})

    def _program_select(self, *, clear: bool = False) -> None:
        key = None if clear else self.select_combo.currentData()
        if key is None:
            self.catalog.set_selected_action(None)
            self.log("host", "set_selected_action(None), kein Signal erwartet", {})
        else:
            self.catalog.set_selected_action(*key)
            self.log("host", f"set_selected_action({key[0]!r}, {key[1]!r}), kein Signal erwartet", {})

    def save_screenshot(self, widget: QWidget, name: str) -> Path:
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.png"
        widget.grab().save(str(path), "PNG")
        self.log("screenshot", str(path), {"path": str(path)})
        return path


def apply_lab_theme(app: QApplication, *, dark: bool = True) -> None:
    """The lab decides the theme; the widget just follows the palette it gets."""
    app.setStyle("Fusion")
    # Explicit colors: on Windows the style's standard palette follows the system's dark mode.
    window, text, base, alternate, button, accent, placeholder, disabled = (
        ("#1f2227", "#e8ebef", "#2b3037", "#24282e", "#2f343b", "#4a82cf", "#98a0aa", "#737a84") if dark else
        ("#f2f3f5", "#1c1f24", "#ffffff", "#eceef1", "#e6e8eb", "#2f6fc4", "#6a7078", "#979ca3"))
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, window), (QPalette.ColorRole.WindowText, text),
                        (QPalette.ColorRole.Base, base), (QPalette.ColorRole.AlternateBase, alternate),
                        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, button),
                        (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.ToolTipBase, button),
                        (QPalette.ColorRole.ToolTipText, text), (QPalette.ColorRole.Highlight, accent),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, placeholder)):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText, QPalette.ColorRole.Text):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled))
    app.setPalette(palette)


# ---------------------------------------------------------------------- scripted runs


def click_row(catalog: ActionCatalogWidget, action_id: str, parameter: str | None = None) -> None:
    tree = catalog.catalog_tree
    rect = tree.visualItemRect(catalog.item_for(action_id, parameter))
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())


def run_smoke(window: ActionCatalogLabWindow) -> int:
    """Initialize, filter, select, end. Prints one line per check; needs no service."""
    catalog = window.catalog
    window.show()
    QApplication.processEvents()
    checks = {
        "Parser liefert Aktionen": bool(catalog.visible_keys()),
    }
    catalog.set_filter("p-7f3a")
    checks["Filter findet Parametername"] = ("lab.scene", "p-7f3a") in catalog.visible_keys()
    catalog.set_filter("")
    catalog.set_selected_action("lab.scene", "p-19c0")
    checks["Programmatische Auswahl ohne Signal"] = (catalog.selected_key() == ("lab.scene", "p-19c0")
                                                     and not [e for e in window.events if e["kind"] == "actionSelected"])
    QApplication.processEvents()
    click_row(catalog, "action.adjustment")
    QApplication.processEvents()
    selected = [e for e in window.events if e["kind"] == "actionSelected"]
    checks["Mausauswahl genau ein Signal"] = len(selected) == 1 and selected[0]["action_id"] == "action.adjustment"
    for name, passed in checks.items():
        print(("OK   " if passed else "FAIL ") + name)
    window.close()
    return 0 if all(checks.values()) else 1


def _send_drag_to_target(window: ActionCatalogLabWindow, mime: QMimeData) -> None:
    """Real Qt drag events on the neutral target for the MIME data the widget really built."""
    target = window.drop_target
    position = QPointF(target.rect().center())
    actions = Qt.DropAction.CopyAction
    QApplication.sendEvent(target, QDragEnterEvent(position.toPoint(), actions, mime, Qt.MouseButton.LeftButton,
                                                   Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(target, QDropEvent(position, actions, mime, Qt.MouseButton.LeftButton,
                                              Qt.KeyboardModifier.NoModifier))


def run_evidence(window: ActionCatalogLabWindow, directory: Path) -> dict:
    """Scripted walkthrough: screenshots, event log, timings and check results."""
    directory = Path(directory)
    shots = directory / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    catalog = window.catalog
    tree = catalog.catalog_tree
    results: list[dict] = []

    def settle() -> None:
        for _ in range(3):
            QApplication.processEvents()

    def shot(name: str, widget: QWidget | None = None) -> None:
        settle()
        (widget or catalog).grab().save(str(shots / f"{name}.png"), "PNG")

    def check(name: str, passed: bool, detail: object = None) -> None:
        results.append({"name": name, "ok": bool(passed), "detail": detail})

    window.show()
    QTest.qWaitForWindowExposed(window)
    settle()
    window._clear_log()
    shot("01_catalog_default_320")

    window.width_combo.setCurrentIndex(0)
    shot("02_catalog_narrow_280")
    check("Schmale Sidebar: Steuerung passt in 280 px",
          catalog.minimumSizeHint().width() <= 280 and catalog.width() <= 280, catalog.minimumSizeHint().width())
    catalog.item_for("action.command").setExpanded(True)
    catalog.item_for("lab.scene").setExpanded(True)
    catalog.item_for("lab.volume").setExpanded(True)
    shot("03_catalog_expanded_280")

    def viewport_point(action_id: str, parameter: str | None = None) -> QPoint:
        return tree.visualItemRect(catalog.item_for(action_id, parameter)).center()

    tree.scrollToItem(catalog.item_for("action.command", "second"))
    settle()
    QTest.mouseMove(tree.viewport(), viewport_point("action.command", "first"))
    shot("04_hover_parameter")
    click_row(catalog, "action.command", "second")
    tree.setFocus()
    QTest.mouseMove(tree.viewport(), viewport_point("action.multistate"))
    shot("05_selected_hover_focus")
    selected = [e for e in window.events if e["kind"] == "actionSelected"]
    check("Mausklick auf Parameter: genau ein actionSelected mit Originalname",
          len(selected) == 1 and selected[0]["action_parameter"] == "second", selected)
    window.width_combo.setCurrentIndex(2)
    shot("06_catalog_wide_380")
    window.width_combo.setCurrentIndex(1)

    catalog.set_filter("nachtmodus")
    shot("07_search_parameter_match")
    check("Suche findet Parameter und zeigt nur die passende Variante",
          catalog.visible_keys() == (("lab.scene", None), ("lab.scene", "scene:night/2")), catalog.visible_keys())
    catalog.set_filter("gibt-es-nicht")
    shot("08_no_results")
    check("Keine-Treffer-Zustand sichtbar", catalog.empty_state() is not None and catalog.empty_state()[0] == "Keine Treffer")
    catalog.set_filter("")
    catalog.set_type_filter("PluginDynamicAdjustment")
    shot("09_type_filter_adjustment")
    check("Typfilter zeigt nur Einstellungen",
          {key[0] for key in catalog.visible_keys()} == {"action.adjustment", "lab.volume"}, catalog.visible_keys())
    catalog.set_type_filter(None)

    window.images_check.setChecked(True)
    window.usage_check.setChecked(True)
    shot("10_host_images_usage")

    captured: list[QMimeData] = []
    visuals: list = []
    original = catalog._exec_drag

    def capture(mime: QMimeData, pixmap, hotspot) -> None:
        captured.append(mime)
        visuals.append((pixmap, hotspot))

    catalog._exec_drag = capture
    drag_results = []
    for action_id, parameter in (("action.command", "first"), ("lab.scene", "scene:night/2"), ("action.adjustment", None)):
        if parameter is not None:
            catalog.item_for(action_id).setExpanded(True)
            settle()
        tree.scrollToItem(catalog.item_for(action_id, parameter))
        settle()
        start = viewport_point(action_id, parameter)
        count = len(captured)
        QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in (6, 14, 30):
            QTest.mouseMove(tree.viewport(), start + QPoint(step, 0))
        QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(30, 0))
        settle()
        started = len(captured) == count + 1
        if started:
            _send_drag_to_target(window, captured[-1])
            label = f"{action_id}_{parameter or 'none'}".translate(str.maketrans(".:/", "___"))
            visuals[-1][0].save(str(shots / f"11_drag_pixmap_{label}.png"), "PNG")
            drops = [e for e in window.events if e["kind"] == "drop"]
            passed = bool(drops) and drops[-1]["action_id"] == action_id and drops[-1]["action_parameter"] == parameter
            drag_results.append({"key": [action_id, parameter], "started": True, "ok": passed,
                                 "formats": drops[-1]["formats"] if drops else None,
                                 "payload": drops[-1]["payload"] if drops else None})
        else:
            drag_results.append({"key": [action_id, parameter], "started": False, "ok": False})
    catalog._exec_drag = original
    check("Geste mit Maus bis zum Drag-Start, Nutzlast am neutralen Ziel korrekt dekodiert",
          all(entry["ok"] for entry in drag_results), drag_results)
    shot("12_lab_after_drops", window)

    catalog.edit_button.click()
    catalog.new_action_button.click()
    kinds = [e["kind"] for e in window.events[-2:]]
    check("Bearbeiten und Neue Aktion melden nur Intents",
          kinds == ["actionEditRequested", "createActionRequested"], window.events[-2:])

    window.load_source(6)
    shot("13_lab_import_error", window)
    check("Importfehler lesbar, Katalog bleibt bestehen",
          "Import fehlgeschlagen" in window.banner.text() and bool(catalog.visible_keys()), window.banner.text())

    window.load_source(2)
    shot("14_no_project")
    check("Kein-Projekt-Zustand sichtbar", catalog.empty_state() is not None and catalog.empty_state()[0] == "Kein Projekt geöffnet")

    timings = []
    for count in (1, 50, 300):
        project = stress_project(count)
        started = time.perf_counter()
        catalog.set_actions(project.actions)
        settle()
        build = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        catalog.set_filter("testaktion 00")
        settle()
        search = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        catalog.set_filter("")
        settle()
        clear = (time.perf_counter() - started) * 1000
        timings.append({"actions": count, "build_ms": round(build, 1), "search_ms": round(search, 1), "clear_ms": round(clear, 1)})
        if count == 300:
            shot("15_stress_300")
    check("Keine auffällige Latenz bei 1, 50, 300 Einträgen", all(t["build_ms"] < 500 and t["search_ms"] < 250 for t in timings), timings)

    window.load_source(0)
    window.width_combo.setCurrentIndex(1)
    catalog.item_for("lab.scene").setExpanded(True)
    window.theme_combo.setCurrentIndex(1)
    shot("16_lab_light", window)
    shot("17_catalog_light")
    window.theme_combo.setCurrentIndex(0)
    shot("18_lab_dark", window)

    screen = window.screen()
    report = {
        "platform": QApplication.platformName(), "style": QApplication.style().objectName(),
        "font": QApplication.font().family(), "device_pixel_ratio": window.devicePixelRatioF(),
        "screen": screen.name() if screen else None, "timings_ms": timings, "checks": results,
        "passed": sum(1 for entry in results if entry["ok"]), "total": len(results),
    }
    (directory / "lab_walkthrough_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "lab_event_log.json").write_text(json.dumps(window.events, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _physical_point(window: QWidget, widget: QWidget, point: QPoint) -> tuple[int, int]:
    """Screen pixels for SetCursorPos; Qt reports device-independent coordinates."""
    screen = window.screen()
    origin = screen.geometry().topLeft()
    logical = widget.mapToGlobal(point) - origin
    ratio = screen.devicePixelRatio()
    return origin.x() + round(logical.x() * ratio), origin.y() + round(logical.y() * ratio)


def run_os_drag_check(window: ActionCatalogLabWindow, directory: Path) -> dict:
    """A real Windows drag with OS mouse input from the list to the neutral target.

    Opt-in, because it moves the real mouse pointer for a few seconds. It presses
    only if both points really lie on the lab window, and it restores the pointer.
    """
    import ctypes
    import threading
    from ctypes import wintypes

    catalog = window.catalog
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    left_down, left_up, ga_root = 0x0002, 0x0004, 2
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.raise_()
    window.activateWindow()
    QTest.qWait(300)
    window._clear_log()
    results: list[dict] = []
    aborted: str | None = None
    entered: list[str] = []
    original_position = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_position))
    original_exec = catalog._exec_drag

    def recording_exec(mime, pixmap, hotspot) -> None:
        entered.append("QDrag.exec gestartet")
        original_exec(mime, pixmap, hotspot)
        entered.append("QDrag.exec beendet")

    catalog._exec_drag = recording_exec

    def on_window(point: tuple[int, int]) -> bool:
        hwnd = user32.WindowFromPoint(wintypes.POINT(*point))
        return bool(hwnd) and int(user32.GetAncestor(hwnd, ga_root) or 0) == int(window.winId())

    def drive(start: tuple[int, int], target: tuple[int, int], done: threading.Event) -> None:
        pressed = False
        try:
            user32.SetCursorPos(*start)
            time.sleep(0.12)
            user32.mouse_event(left_down, 0, 0, 0, 0)
            pressed = True
            time.sleep(0.12)
            steps = 16
            for step in range(1, steps + 1):
                user32.SetCursorPos(start[0] + (target[0] - start[0]) * step // steps,
                                    start[1] + (target[1] - start[1]) * step // steps)
                time.sleep(0.03)
            time.sleep(0.15)
        finally:
            if pressed:
                user32.mouse_event(left_up, 0, 0, 0, 0)
            done.set()

    try:
        for action_id, parameter in (("action.command", "second"), ("lab.scene", "scene:night/2"), ("action.adjustment", None)):
            if parameter is not None:
                catalog.item_for(action_id).setExpanded(True)
            item = catalog.item_for(action_id, parameter)
            catalog.catalog_tree.scrollToItem(item)
            QApplication.processEvents()
            rect = catalog.catalog_tree.visualItemRect(item)
            start = _physical_point(window, catalog.catalog_tree.viewport(), rect.center())
            target = _physical_point(window, window.drop_target, window.drop_target.rect().center())
            if not (on_window(start) and on_window(target)):
                aborted = f"Punkt liegt nicht auf dem Lab-Fenster: {start} / {target}"
                break
            before = sum(1 for event in window.events if event["kind"] == "drop")
            done = threading.Event()
            threading.Thread(target=drive, args=(start, target, done), daemon=True).start()
            deadline = time.monotonic() + 10
            while not done.is_set() and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.005)
            QTest.qWait(250)
            drops = [event for event in window.events if event["kind"] == "drop"]
            arrived = len(drops) == before + 1
            results.append({"key": [action_id, parameter], "drop": drops[-1] if arrived else None,
                            "ok": arrived and drops[-1]["action_id"] == action_id and drops[-1]["action_parameter"] == parameter})
    finally:
        user32.SetCursorPos(original_position.x, original_position.y)
        catalog._exec_drag = original_exec
    report = {"platform": QApplication.platformName(), "device_pixel_ratio": window.devicePixelRatioF(), "aborted": aborted,
              "exec": entered, "results": results, "passed": bool(results) and not aborted and all(r["ok"] for r in results)}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "os_drag_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    window.grab().save(str(directory / "os_drag_check_lab.png"), "PNG")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Action Catalog Lab")
    parser.add_argument("--project", type=Path, help="Projektdatei nur lesend öffnen")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Ordner für Screenshots aus dem Lab")
    parser.add_argument("--smoke", action="store_true", help="Initialisiert, filtert, selektiert und beendet")
    parser.add_argument("--evidence", type=Path, metavar="ORDNER", help="Durchlauf mit Screenshots, Ereignislog und Bericht")
    parser.add_argument("--os-drag-check", type=Path, metavar="ORDNER",
                        help="Echter Windows-Drag mit OS-Mauseingaben; bewegt den Mauszeiger einige Sekunden")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_lab_theme(app)
    window = ActionCatalogLabWindow(args.output, args.project)
    if args.smoke:
        return run_smoke(window)
    if args.os_drag_check:
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            print("--os-drag-check braucht die echte Windows-Qt-Plattform.", file=sys.stderr)
            return 2
        report = run_os_drag_check(window, args.os_drag_check)
        window.close()
        print(json.dumps({key: report[key] for key in ("aborted", "exec", "passed")}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    if args.evidence:
        report = run_evidence(window, args.evidence)
        window.close()
        for entry in report["checks"]:
            print(("OK   " if entry["ok"] else "FAIL ") + entry["name"])
        print(f"{report['passed']}/{report['total']} Prüfungen, Plattform {report['platform']}, "
              f"Schrift {report['font']}, DPR {report['device_pixel_ratio']}")
        return 0 if report["passed"] == report["total"] else 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
