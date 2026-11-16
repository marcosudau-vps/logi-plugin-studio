"""Keypad Preview Lab: the real KeypadPreviewWidget against a simulated in-memory host.

Start: python tools\\run_keypad_preview_lab.py [--output DIR] [--smoke SECONDS] [--evidence DIR]

Needs no Logitech service, plugin, project file or credentials. It contains no
widget logic of its own; it only drives the public widget API and logs signals.
Catalog, diagnostics and log are test instruments and can be folded away.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QSize, Qt, QTimer
    from PySide6.QtGui import QColor, QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont, QIcon, QPalette, QPixmap
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox,
                                   QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit,
                                   QPushButton, QRadioButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print("PySide6 fehlt. Die dokumentierte lokale Python-Umgebung verwenden.", file=sys.stderr)
        raise SystemExit(2) from exc
    raise

from studio.keypad_contract import ActionOffer, EditRequest, SlotAddress
from studio.keypad_preview import ACTION_REF_MIME, KeypadPreviewWidget, encode_action_ref, load_logikeypad_skin, neutral_skin
from studio.keypad_preview.lab_host import LAB_SCENARIOS, VISUAL_FUNCTION, VISUAL_REFERENCE, HostDecision, LabHost
from studio.keypad_preview.skin import drag_label_pixmap, find_logikeypad_directory

SKIN_DIRECTORY = find_logikeypad_directory(ROOT)
DEFAULT_OUTPUT = ROOT / "work" / "widget-lab" / "keypad-preview-v1" / "lab-output"
ZOOM_LEVELS = (("Fenster anpassen", None), ("50 %", 0.5), ("60 %", 0.6), ("75 %", 0.75), ("100 %", 1.0), ("125 %", 1.25))
DEFAULT_ZOOM = 0.6
BACKDROP = "#1a1a1a"


def describe_address(address: SlotAddress | None) -> dict | None:
    if address is None:
        return None
    return {"view_id": address.view_id, "page_index": address.page_index,
            "physical_index": address.physical_index, "placement_id": address.placement_id}


class OfferCatalog(QListWidget):
    """External drag source outside the widget. It sends a reference, never a picture."""

    def __init__(self, offers: list[ActionOffer], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("labOfferCatalog")
        self.offers = offers
        self.setDragEnabled(True)
        self.setIconSize(QSize(40, 40))
        self.setSpacing(2)
        for offer in offers:
            item = QListWidgetItem(offer.display_name)
            if offer.tile_image is not None:
                item.setIcon(QIcon(QPixmap.fromImage(offer.tile_image)))
            self.addItem(item)

    def offer_mime(self, offer: ActionOffer) -> QMimeData:
        mime = QMimeData()
        mime.setData(ACTION_REF_MIME, QByteArray(encode_action_ref(offer)))
        return mime

    def startDrag(self, _actions) -> None:
        row = self.currentRow()
        if row < 0:
            return
        drag = QDrag(self)
        drag.setMimeData(self.offer_mime(self.offers[row]))
        pixmap, hotspot = drag_label_pixmap(self.offers[row].display_name, self.devicePixelRatioF())
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot.toPoint())
        drag.exec(Qt.DropAction.CopyAction)


class KeypadLabWindow(QMainWindow):
    def __init__(self, output: Path = DEFAULT_OUTPUT) -> None:
        super().__init__()
        self.setObjectName("keypadLabWindow")
        self.setWindowTitle("Keypad Preview Lab – simulierter Host, keine Hardware")
        self.resize(1040, 800)
        self.output = Path(output)
        self.events: list[dict] = []
        self.host = LabHost("nine", self)
        self.keypad = KeypadPreviewWidget()
        self._build_ui()
        self._connect()
        self.keypad.set_frame(self.host.frame())
        self._refresh_revision()
        self._refresh_mode_banner()
        self.log("lab", "Lab gestartet", {"skin": self.keypad.effective_skin().name})

    def use_default_view(self) -> None:
        """Starting view: real device art at a compact size, with tiles that show the intended look."""
        self.visual_combo.setCurrentIndex(self.visual_combo.findData(VISUAL_REFERENCE))
        self.scenario_combo.setCurrentIndex(self.scenario_combo.findData("reference"))
        self.skin_combo.setCurrentIndex(self.skin_combo.findData("asset"))
        self.zoom_combo.setCurrentIndex(self.zoom_combo.findData(DEFAULT_ZOOM))

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        top = QWidget()
        columns = QHBoxLayout(top)
        columns.setContentsMargins(10, 8, 10, 6)
        columns.setSpacing(10)
        self.catalog_panel = self._catalog_panel()
        self.control_panel = self._control_panel()
        columns.addWidget(self.catalog_panel, 0)
        columns.addWidget(self._center_panel(), 1)
        columns.addWidget(self.control_panel, 0)
        splitter.addWidget(top)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("labEventLog")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Ereignisprotokoll")
        self.log_view.setStyleSheet("background:#14161a;")
        splitter.addWidget(self.log_view)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 160])
        self.setCentralWidget(splitter)
        self.catalog_panel.hide()
        self.log_view.hide()
        self.catalog_toggle.toggled.connect(self.catalog_panel.setVisible)
        self.control_toggle.toggled.connect(self.control_panel.setVisible)
        self.log_toggle.toggled.connect(self.log_view.setVisible)

    def _catalog_panel(self) -> QWidget:
        box = QGroupBox("Testkatalog (ActionOffer)")
        box.setFixedWidth(260)
        layout = QVBoxLayout(box)
        hint = QLabel("Externe Drag-Quelle außerhalb des Widgets. Im Bearbeitungsmodus auf eine freie Taste ziehen; "
                      "der Host prüft die Referenz.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.catalog = OfferCatalog(self.host.offers())
        layout.addWidget(self.catalog, 1)
        return box

    def _center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.mode_banner = QLabel()
        self.mode_banner.setObjectName("labModeBanner")
        self.mode_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.mode_banner, 1)
        self.catalog_toggle = self._panel_toggle("Testkatalog", False)
        self.control_toggle = self._panel_toggle("Diagnose", True)
        self.log_toggle = self._panel_toggle("Protokoll", False)
        for toggle in (self.catalog_toggle, self.control_toggle, self.log_toggle):
            head.addWidget(toggle)
        layout.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.keypad)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scroll, 1)
        self.host_banner = QLabel()
        self.host_banner.setObjectName("labHostBanner")
        self.host_banner.setWordWrap(True)
        self.host_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.host_banner.hide()
        layout.addWidget(self.host_banner)
        return panel

    @staticmethod
    def _panel_toggle(text: str, checked: bool) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(checked)
        return button

    def _control_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        mode = QGroupBox("Modus (vom Host gesetzt)")
        mode_layout = QVBoxLayout(mode)
        self.preview_radio = QRadioButton("preview (Standard)")
        self.edit_radio = QRadioButton("edit")
        self.preview_radio.setChecked(True)
        group = QButtonGroup(mode)
        group.addButton(self.preview_radio)
        group.addButton(self.edit_radio)
        self.allow_check = QCheckBox("Bearbeitung erlaubt (set_edit_allowed)")
        self.motion_check = QCheckBox("Animationen an (set_motion_enabled)")
        self.motion_check.setChecked(True)
        for widget in (self.preview_radio, self.edit_radio, self.allow_check, self.motion_check):
            mode_layout.addWidget(widget)
        layout.addWidget(mode)

        view = QGroupBox("Ansicht")
        view_layout = QVBoxLayout(view)
        self.scenario_combo = QComboBox()
        for scenario in LAB_SCENARIOS:
            self.scenario_combo.addItem(scenario.title, scenario.key)
        self.visual_combo = QComboBox()
        self.visual_combo.addItem("Funktionstest (bunte Kacheln)", VISUAL_FUNCTION)
        self.visual_combo.addItem("Optik-Referenz (schwarze LCDs)", VISUAL_REFERENCE)
        self.skin_combo = QComboBox()
        self.skin_combo.addItem("Neutral (Fallback und Diagnose)", "neutral")
        self.skin_combo.addItem("LogiKeypad-Originaldateien", "asset")
        self.zoom_combo = QComboBox()
        for title, value in ZOOM_LEVELS:
            self.zoom_combo.addItem(title, value)
        self.skin_notice = QLabel()
        self.skin_notice.setWordWrap(True)
        for title, widget in (("Slots und Seiten:", self.scenario_combo), ("Testkacheln:", self.visual_combo),
                              ("Skin:", self.skin_combo), ("Zoom:", self.zoom_combo)):
            view_layout.addWidget(QLabel(title))
            view_layout.addWidget(widget)
        view_layout.addWidget(self.skin_notice)
        layout.addWidget(view)

        host = QGroupBox("Simulierter Host")
        host_layout = QVBoxLayout(host)
        self.revision_label = QLabel()
        self.revision_label.setObjectName("labRevision")
        host_layout.addWidget(self.revision_label)
        self.visuals_button = QPushButton("Bilder und Labels wechseln")
        self.external_button = QPushButton("Externe Änderung (Frame zurückhalten)")
        self.external_button.setToolTip("Erhöht nur die Host-Revision. Die nächste Anfrage des Widgets ist damit veraltet.")
        self.resend_button = QPushButton("Aktuellen Frame senden")
        self.clear_selection_button = QPushButton("Auswahl von außen löschen")
        for button in (self.visuals_button, self.external_button, self.resend_button, self.clear_selection_button):
            host_layout.addWidget(button)
        layout.addWidget(host)

        export = QGroupBox("Export (nur Lab-Daten)")
        export_layout = QVBoxLayout(export)
        self.screenshot_button = QPushButton("Screenshot als PNG …")
        self.log_button = QPushButton("Ereignislog als JSON …")
        export_layout.addWidget(self.screenshot_button)
        export_layout.addWidget(self.log_button)
        layout.addWidget(export)
        keys = QLabel("Tasten: Pfeile, Enter/Leertaste, Esc, Bild auf/ab. Bearbeiten: Strg+X/C/V, Entf, F2, Strg+Z/Y, "
                      "Menütaste. Strg beim Ziehen kopiert.")
        keys.setWordWrap(True)
        keys.setStyleSheet("color:#a7afb9;")
        layout.addWidget(keys)
        layout.addStretch(1)
        # Scrolls on small screens instead of squeezing the controls.
        panel.setMinimumHeight(panel.sizeHint().height() + 28)  # Wrapped labels report too little height.
        panel.setMaximumWidth(312)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(332)
        return scroll

    def _connect(self) -> None:
        keypad, host = self.keypad, self.host
        keypad.slotSelected.connect(lambda a: self.log("slotSelected", "Auswahl", describe_address(a)))
        keypad.symbolEditRequested.connect(self._on_symbol_edit)
        keypad.editRequested.connect(self._on_edit_request)
        keypad.pageRequested.connect(self._on_page_request)
        keypad.pageCreateRequested.connect(self._on_page_create)
        keypad.undoRequested.connect(self._on_undo)
        keypad.redoRequested.connect(self._on_redo)
        host.frameChanged.connect(self._on_frame)
        host.decisionMade.connect(self._on_decision)
        host.historyChanged.connect(keypad.set_history_available)
        self.preview_radio.toggled.connect(self._apply_mode)
        self.allow_check.toggled.connect(self._apply_mode)
        self.motion_check.toggled.connect(keypad.set_motion_enabled)
        self.scenario_combo.currentIndexChanged.connect(self._on_scenario)
        self.visual_combo.currentIndexChanged.connect(self._on_visual_mode)
        self.skin_combo.currentIndexChanged.connect(self._on_skin)
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom)
        self.visuals_button.clicked.connect(host.cycle_visuals)
        self.external_button.clicked.connect(self._on_external_change)
        self.resend_button.clicked.connect(host.resend_frame)
        self.clear_selection_button.clicked.connect(lambda: keypad.set_selection(None))
        self.screenshot_button.clicked.connect(self._choose_screenshot)
        self.log_button.clicked.connect(self._choose_log)
        host.historyChanged.emit(False, False)

    # ------------------------------------------------------------------ host wiring

    def log(self, signal: str, text: str, data=None) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.events.append({"time": stamp, "signal": signal, "text": text, "data": data})
        detail = "" if data is None else "  " + json.dumps(data, ensure_ascii=False)
        self.log_view.appendPlainText(f"{stamp}  {signal:<20} {text}{detail}")

    def _refresh_revision(self) -> None:
        frame = self.keypad.frame()
        shown = frame.revision if frame is not None else "–"
        note = "" if shown == self.host.revision else "  (veraltet!)"
        self.revision_label.setText(f"Host: {self.host.revision}\nWidget: {shown}{note}")

    def _on_frame(self, frame) -> None:
        self.keypad.set_frame(frame)
        self.log("set_frame", "Neuer Frame vom Host", {"revision": frame.revision, "page_index": frame.page_index,
                                                       "page_count": frame.page_count})
        self._refresh_revision()
        if self.keypad.skin_notice():
            self.skin_notice.setText(self.keypad.skin_notice())

    def _on_edit_request(self, request: EditRequest) -> None:
        self.log("editRequested", request.operation, {
            "request_id": request.request_id[:8], "base_revision": request.base_revision,
            "source": describe_address(request.source), "target": describe_address(request.target),
            "action_id": request.action_id, "action_parameter": request.action_parameter})
        self.host.submit(request)

    def _on_decision(self, decision: HostDecision) -> None:
        self.log("host", "übernommen" if decision.accepted else "ABGELEHNT",
                 {"code": decision.code, "message": decision.message})
        tone = "#1f6f4a" if decision.accepted else "#a4262c"
        prefix = "Host hat übernommen" if decision.accepted else "Host hat abgelehnt"
        self.host_banner.setStyleSheet(f"background:{tone};color:white;padding:6px;border-radius:4px;")
        self.host_banner.setText(f"{prefix} ({decision.operation}): {decision.message}")
        self.host_banner.show()
        self._refresh_revision()

    def _on_symbol_edit(self, address: SlotAddress) -> None:
        self.log("symbolEditRequested", "Nur Anfrage: ein Host würde den SymbolDesigner öffnen",
                 describe_address(address))

    def _on_page_request(self, page: int) -> None:
        self.log("pageRequested", "Seite angefordert", {"page_index": page})
        self.host.show_page(page)

    def _on_page_create(self) -> None:
        self.log("pageCreateRequested", "Neue Seite beantragt; der simulierte Host legt sie an")
        self.host.add_page()

    def _on_visual_mode(self) -> None:
        mode = self.visual_combo.currentData()
        self.log("lab", "Testkacheln gewechselt", {"mode": mode})
        self.host.set_visual_mode(mode)

    def _on_undo(self) -> None:
        self.log("undoRequested", "Host führt Rückgängig aus" if self.host.undo() else "Nichts rückgängig zu machen")

    def _on_redo(self) -> None:
        self.log("redoRequested", "Host führt Wiederholen aus" if self.host.redo() else "Nichts zu wiederholen")

    def _on_external_change(self) -> None:
        self.host.external_change()
        self.log("host", "Externe Änderung simuliert; Frame zurückgehalten", {"revision": self.host.revision})
        self._refresh_revision()

    def _apply_mode(self) -> None:
        mode = "preview" if self.preview_radio.isChecked() else "edit"
        self.keypad.set_mode(mode)
        self.keypad.set_edit_allowed(self.allow_check.isChecked())
        self.log("mode", f"set_mode({mode}), set_edit_allowed({self.allow_check.isChecked()})")
        self._refresh_mode_banner()

    def _refresh_mode_banner(self) -> None:
        if self.keypad.editing_active():
            text, tone = "BEARBEITEN aktiv – nur Anfragen an den Host", "#6b4a00"
        elif self.keypad.mode() == "edit":
            text, tone = "edit gesetzt, Berechtigung fehlt – wirkt wie Vorschau", "#4a3f70"
        else:
            text, tone = "VORSCHAU – keine Bearbeitung möglich", "#24323d"
        self.mode_banner.setText(text)
        self.mode_banner.setStyleSheet(f"background:{tone};color:white;padding:4px;border-radius:3px;")

    def _on_scenario(self) -> None:
        key = self.scenario_combo.currentData()
        self.log("lab", "Szenario gewechselt (simuliert)", {"scenario": key})
        self.keypad.set_selection(None)
        self.host.load_scenario(key)
        self._on_zoom()

    def _on_skin(self) -> None:
        if self.skin_combo.currentData() == "asset":
            skin, problem = load_logikeypad_skin(SKIN_DIRECTORY)
            if skin is None:
                self.keypad.set_skin(neutral_skin())
                self.skin_notice.setStyleSheet("color:#ff8a8a;")
                self.skin_notice.setText("Neutraler Fallback: " + problem)
                self.log("lab", "Skin-Dateien nicht nutzbar; neutraler Fallback", {"problem": problem})
                self._on_zoom()
                return
            self.keypad.set_skin(skin)
            self.skin_notice.setStyleSheet("")
            parts = Path(skin.source_directory).parts
            self.skin_notice.setText("Aktive Quelle: …\\" + "\\".join(parts[-2:]) + ("\n" + skin.notice if skin.notice else ""))
            self.skin_notice.setToolTip(skin.source_directory)
        else:
            self.keypad.set_skin(neutral_skin())
            self.skin_notice.setStyleSheet("")
            self.skin_notice.setText("Neutraler Diagnose-Skin, bewusst gewählt.")
        self.log("lab", "Skin gesetzt", {"skin": self.keypad.effective_skin().name})
        self._on_zoom()
        self._on_zoom()

    def _on_zoom(self) -> None:
        zoom = self.zoom_combo.currentData()
        if zoom is None:
            self.keypad.setMinimumSize(0, 0)
            self.keypad.setMaximumSize(16777215, 16777215)
            self.scroll.setWidgetResizable(True)
            return
        self.scroll.setWidgetResizable(False)
        self.keypad.setFixedSize(self.keypad.size_for_scale(zoom))

    # ------------------------------------------------------------------ export

    def _choose_screenshot(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Screenshot speichern", str(self.output / "keypad-lab.png"), "PNG (*.png)")
        if path:
            self.keypad.grab().save(path, "PNG")
            self.log("lab", "Screenshot gespeichert", {"file": Path(path).name})

    def _choose_log(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Ereignislog speichern", str(self.output / "keypad-lab-log.json"), "JSON (*.json)")
        if path:
            self.write_log(Path(path))

    def write_log(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"lab": "keypad-preview-v1", "simulated_host": True, "events": self.events},
                                   ensure_ascii=False, indent=2), encoding="utf-8")


def apply_lab_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BACKDROP), (QPalette.ColorRole.WindowText, "#e8ebef"),
                        (QPalette.ColorRole.Base, "#2b3037"), (QPalette.ColorRole.AlternateBase, "#20242a"),
                        (QPalette.ColorRole.Text, "#e8ebef"), (QPalette.ColorRole.Button, "#2a2f36"),
                        (QPalette.ColorRole.ButtonText, "#e8ebef"), (QPalette.ColorRole.ToolTipBase, "#2a2f36"),
                        (QPalette.ColorRole.ToolTipText, "#e8ebef"), (QPalette.ColorRole.Highlight, "#3d6fb5"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, "#7f8791")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6b727b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6b727b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b727b"))
    app.setPalette(palette)


# ---------------------------------------------------------------------- reproducible evidence


def _center(keypad: KeypadPreviewWidget, index: int) -> QPoint:
    return keypad.slot_rect(index).center().toPoint()


def _drop_offer(keypad: KeypadPreviewWidget, catalog: OfferCatalog, offer: ActionOffer, index: int) -> None:
    """Real Qt drag events in delivery order; only the OS drag loop itself is not automated."""
    mime = catalog.offer_mime(offer)
    position = _center(keypad, index)
    copy = Qt.DropAction.CopyAction
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(keypad, QDragEnterEvent(QPointF(position), copy, mime, left, none))
    QApplication.sendEvent(keypad, QDragMoveEvent(QPointF(position), copy, mime, left, none))
    QApplication.sendEvent(keypad, QDropEvent(QPointF(position), copy, mime, left, none))


def _hover_offer(keypad: KeypadPreviewWidget, catalog: OfferCatalog, offer: ActionOffer, index: int) -> None:
    """Hold an offer over a key to show the drop feedback."""
    mime = catalog.offer_mime(offer)
    position = QPointF(_center(keypad, index))
    copy = Qt.DropAction.CopyAction
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(keypad, QDragEnterEvent(position, copy, mime, left, none))
    QApplication.sendEvent(keypad, QDragMoveEvent(position, copy, mime, left, none))


def run_evidence(window: KeypadLabWindow, directory: Path) -> dict:
    """Scripted walkthrough that stores screenshots, event log and check results."""
    global SKIN_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    shots = directory / "screenshots"
    shots.mkdir(exist_ok=True)
    keypad, host = window.keypad, window.host
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(passed), "detail": detail})

    def shot(name: str, widget: QWidget | None = None) -> None:
        QApplication.processEvents()
        (widget or keypad).grab().save(str(shots / f"{name}.png"), "PNG")

    def scenario(key: str) -> None:
        window.scenario_combo.setCurrentIndex(window.scenario_combo.findData(key))
        QApplication.processEvents()

    def editing(enabled: bool) -> None:
        (window.edit_radio if enabled else window.preview_radio).setChecked(True)
        window.allow_check.setChecked(enabled)

    def decisions() -> list[dict]:
        return [e for e in window.events if e["signal"] == "host" and "code" in (e["data"] or {})]

    start_view = KeypadLabWindow(window.output)
    start_view.use_default_view()
    start_view.show()
    QTest.qWaitForWindowExposed(start_view)
    shot("00_lab_standardansicht", start_view)
    check("Standardansicht zeigt die Originalgrafik, wenn verfügbar",
          start_view.keypad.effective_skin().is_device_art or not (SKIN_DIRECTORY / "case_transparent.png").is_file(),
          start_view.skin_notice.text())
    start_view.close()
    window.catalog_toggle.setChecked(True)
    window.log_toggle.setChecked(True)
    window.resize(1320, 960)
    window.skin_combo.setCurrentIndex(window.skin_combo.findData("asset"))
    window.show()
    QTest.qWaitForWindowExposed(window)
    keypad.setFocus()

    shot("01_preview_neun_slots")
    shot("02_lab_gesamt_preview", window)
    check("Standardmodus ist preview", keypad.mode() == "preview" and not keypad.editing_active())
    window.motion_check.setChecked(False)  # Stable screenshots: no key is caught mid-animation.

    QTest.mouseMove(keypad, _center(keypad, 2))
    QTest.mouseClick(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 0))
    QTest.mouseMove(keypad, _center(keypad, 2))
    QTest.keyClick(keypad, Qt.Key.Key_Right)
    QTest.keyClick(keypad, Qt.Key.Key_Down)
    shot("03_auswahl_hover_fokus_unabhaengig")
    check("Auswahl bleibt nach Klick", keypad.selection() is not None and keypad.selection().physical_index == 0)

    window.motion_check.setChecked(True)
    QTest.mousePress(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 2))
    QTest.qWait(160)
    shot("04_taste_gedrueckt_nur_aktive")
    check("Gedrückte Taste skaliert auf 97 %", abs(keypad.key_motion(2)[0] - 0.97) < 1e-6,
          f"motion={keypad.key_motion(2)}")
    check("Nachbartaste unverändert", keypad.key_motion(1) == (1.0, 0.0))
    QTest.keyClick(keypad, Qt.Key.Key_Escape)
    QTest.mouseRelease(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 2))
    QTest.qWait(200)
    window.motion_check.setChecked(False)

    editing(True)
    QTest.mouseMove(keypad, _center(keypad, 4))
    shot("05_edit_drei_punkte")
    shot("06_lab_gesamt_edit", window)
    check("Drei-Punkte nur auf zulässigen Slots", keypad.has_menu_button(0) and keypad.has_menu_button(4))

    QTest.mouseClick(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 1))
    QTest.keyClick(keypad, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    shot("07_ausgeschnitten_slot_bleibt_belegt")
    revision_before = host.revision
    check("Ausschneiden entfernt nichts", keypad.clipboard_state()[0] == "cut" and host.placement_at(0, 1) is not None
          and keypad.frame().revision == revision_before)

    QTest.mouseClick(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 4))
    QTest.keyClick(keypad, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    check("Einfügen nach Ausschneiden committet über Host", host.revision != revision_before)

    _drop_offer(keypad, window.catalog, window.catalog.offers[0], 6)
    check("ActionOffer-Drop platziert über Host", host.placement_at(0, 6) is not None)
    shot("08_nach_move_und_place")

    _hover_offer(keypad, window.catalog, window.catalog.offers[1], 8)
    shot("08a_drop_auf_freie_taste_zulaessig")
    check("Freie Taste ist Drop-Ziel", keypad._drop_index == 8 and keypad._drop_ok)
    QApplication.sendEvent(keypad, QDragLeaveEvent())
    _hover_offer(keypad, window.catalog, window.catalog.offers[1], 0)
    shot("08b_drop_auf_belegte_taste_verweigert")
    check("Belegte Taste ist kein Drop-Ziel", keypad._drop_index == 0 and not keypad._drop_ok)
    QApplication.sendEvent(keypad, QDragLeaveEvent())
    check("Abbruch des Ziehens sendet nichts", host.placement_at(0, 8) is None)

    foreign = window.catalog.offers[-1]
    _drop_offer(keypad, window.catalog, foreign, 8)
    shot("09_host_lehnt_fremde_action_ab", window)
    check("Fremde ActionOffer-Referenz wird abgelehnt", decisions()[-1]["data"]["code"] == "unknown_action")

    window.external_button.click()
    shown_frame = keypad.frame()
    QTest.mouseClick(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _center(keypad, 6))
    QTest.keyClick(keypad, Qt.Key.Key_Delete)
    check("Veraltete Revision wird abgelehnt", decisions()[-1]["data"]["code"] == "revision_conflict")
    check("Slot und Frame bleiben nach Ablehnung unverändert", keypad.frame() is shown_frame and host.placement_at(0, 6) is not None)
    shot("10_revisionskonflikt_abgelehnt", window)
    window.resend_button.click()

    if keypad.physical_arrows_available():
        QTest.mouseClick(keypad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, keypad.arrow_rect(1).center().toPoint())
    else:
        QTest.mouseClick(keypad.next_page_button, Qt.MouseButton.LeftButton)
    check("Nächste Seite kommt als Host-Frame", keypad.frame().page_index == 1)
    shot("11_seite_zwei_von_drei")

    editing(False)
    scenario("navigation")
    shot("12_acht_inhalte_plus_sdk_navigation_simuliert")
    editing(True)
    check("SDK-Navigation hat kein Menü", not keypad.has_menu_button(8))
    shot("13_sdk_navigation_edit")

    scenario("locked")
    shot("14_gesperrt_und_nicht_verfuegbar_edit")
    check("Gesperrter Slot hat kein Menü", not keypad.has_menu_button(1) and not keypad.has_menu_button(4))
    editing(False)
    scenario("four")
    shot("15_vier_gemeldete_slots")
    check("Nicht gemeldeter Slot ist nicht klickbar", keypad.slot_at(QPointF(_center(keypad, 8))) is None)
    scenario("sparse")
    shot("16_lueckenhafte_slots_2_7_12")
    check("Layout folgt der Capability", keypad.effective_skin().covers((2, 7, 12)))
    scenario("nine")

    real_directory, SKIN_DIRECTORY = SKIN_DIRECTORY, directory / "kein-skin-ordner"
    window.skin_combo.setCurrentIndex(window.skin_combo.findData("neutral"))
    window.skin_combo.setCurrentIndex(window.skin_combo.findData("asset"))
    QApplication.processEvents()
    check("Fehlende Skin-Dateien führen zu neutralem Fallback mit Meldung",
          not keypad.effective_skin().is_device_art and "Fallback" in window.skin_notice.text(), window.skin_notice.text())
    shot("17_fehlende_skin_dateien_fallback", window)
    SKIN_DIRECTORY = real_directory
    window.skin_combo.setCurrentIndex(window.skin_combo.findData("neutral"))
    window.skin_combo.setCurrentIndex(window.skin_combo.findData("asset"))

    for size, name in ((QSize(220, 240), "18_klein_220"), (QSize(900, 980), "19_gross_900")):
        probe = KeypadPreviewWidget()
        probe.set_skin(keypad.effective_skin())
        probe.set_frame(host.frame())
        probe.resize(size)
        probe.show()
        QTest.qWaitForWindowExposed(probe)
        shot(name, probe)
        check(f"Trefferfläche skaliert ({size.width()} px)", all(
            probe.slot_at(probe.slot_rect(i).center()) == i for i in range(9)))
        probe.close()

    window.write_log(directory / "lab_event_log.json")
    report = {"lab": "keypad-preview-v1", "platform": QApplication.platformName(),
              "simulated_host": True, "checks": checks,
              "passed": sum(1 for c in checks if c["ok"]), "total": len(checks)}
    (directory / "lab_walkthrough_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keypad Preview Lab")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Vorschlagsordner für PNG-/JSON-Exporte")
    parser.add_argument("--smoke", type=float, metavar="SEKUNDEN", help="Beendet das Lab automatisch nach dieser Zeit")
    parser.add_argument("--evidence", type=Path, metavar="ORDNER", help="Führt den Durchlauf aus und schreibt Nachweise")
    args = parser.parse_args(argv)
    if args.evidence and sys.platform == "win32":
        os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_lab_theme(app)
    if args.evidence and sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))  # The offscreen platform otherwise picks an arbitrary file.
    window = KeypadLabWindow(args.output)
    if not args.evidence:
        window.use_default_view()
    if args.evidence:
        report = run_evidence(window, args.evidence)
        window.close()
        for entry in report["checks"]:
            print(("OK   " if entry["ok"] else "FAIL ") + entry["name"])
        print(f"{report['passed']}/{report['total']} Prüfungen, Plattform {report['platform']}")
        return 0 if report["passed"] == report["total"] else 1
    window.show()
    if args.smoke:
        QTimer.singleShot(round(args.smoke * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
