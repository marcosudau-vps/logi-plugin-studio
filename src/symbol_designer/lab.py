"""Symbol Designer Lab – a test shell around the real SymbolDesignerWidget.

The Lab contains no designer logic of its own: editing, rendering and export
all go through the widget. Result previews read the files back from disk.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import time
import traceback
from pathlib import Path

import PySide6
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .dialogs import ExportOptions, StyleTarget, content_summary
from .ict import (EXPORT_SIZES, IMAGE, TEXT, IconTemplate, IctError, apply_layout, argb_hex, content_fingerprint,
                  parse_argb)
from .library import BUNDLED_ROOT, ENV_VAR
from .render import prepare_file, render_template
from .widget import SymbolDesignerWidget

SAMPLES = (("Wiedergabe", "Medien/Wiedergabe.svg", "image_top", "#FF1E3A8A"),
           ("Stumm schalten", "Medien/Stumm.svg", "text_top", "#FF7B1FA2"),
           ("Mehrfarbig", "Beispiele/Mehrfarbig_Kacheln.svg", "image_center", "#FF263238"),
           ("Raster-PNG", "Beispiele/Raster_Abzeichen.png", "image_full", "#FF004D40"))


def sample_targets() -> list[StyleTarget]:
    targets = []
    for text, relative, layout, color in SAMPLES:
        template = IconTemplate()
        prepared = prepare_file(BUNDLED_ROOT / relative)
        template.set_image(prepared.data, prepared.filename)
        template.text = text
        template.background = parse_argb(color)
        template.font_size = 4
        apply_layout(template, layout)
        targets.append(StyleTarget("Beispiel: " + text, template))
    return targets


def image_difference(first: QImage, second: QImage) -> float:
    """Mean absolute channel difference in percent (0 = identical pixels)."""
    a = first.convertToFormat(QImage.Format.Format_ARGB32)
    b = second.convertToFormat(QImage.Format.Format_ARGB32)
    if a.size() != b.size():
        b = b.scaled(a.size())
    total = 0
    for y in range(a.height()):
        for x in range(a.width()):
            p, q = a.pixel(x, y), b.pixel(x, y)
            total += sum(abs(((p >> s) & 255) - ((q >> s) & 255)) for s in (0, 8, 16, 24))
    return 100 * total / (a.width() * a.height() * 4 * 255)


def svg_image(path: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(path))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    if renderer.isValid():
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
    return image


def shortened(data, limit: int = 120):
    if isinstance(data, dict):
        return {k: (v[:limit] + "… (%d Zeichen Base64)" % len(v)) if k == "image" and isinstance(v, str)
                and len(v) > limit else shortened(v, limit) for k, v in data.items()}
    if isinstance(data, list):
        return [shortened(v, limit) for v in data]
    return data


def dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "#121212"), (QPalette.ColorRole.WindowText, "#e6e6e6"),
                        (QPalette.ColorRole.Base, "#0b0b0b"), (QPalette.ColorRole.AlternateBase, "#1a1a1a"),
                        (QPalette.ColorRole.Text, "#e6e6e6"), (QPalette.ColorRole.Button, "#222222"),
                        (QPalette.ColorRole.ButtonText, "#e6e6e6"), (QPalette.ColorRole.Highlight, "#00897b"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#222222"),
                        (QPalette.ColorRole.ToolTipText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, "#808080")):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


class LabWindow(QMainWindow):
    def __init__(self, output: Path, ict: Path | None = None, library_root: Path | None = None):
        super().__init__()
        self.setWindowTitle("Symbol Designer Lab – Logitech Plugin Studio")
        self.setObjectName("symbolDesignerLab")
        self.resize(1560, 980)
        self.output = Path(output)
        self.last_files: dict[str, Path] = {}
        self.target_fingerprints: dict[int, list] = {}
        self.designer = SymbolDesignerWidget(library_root=library_root)
        self.designer.applied.connect(self._applied)
        self.designer.templateChanged.connect(self._schedule_json)
        self.designer.styleTransferred.connect(lambda _: self.refresh_targets())
        self.designer.noticesChanged.connect(lambda notes: notes and self.log(" | ".join(notes)))
        self.designer.library.rootChanged.connect(lambda _: self.refresh_library_report())
        self._json_timer = QTimer(self)
        self._json_timer.setSingleShot(True)
        self._json_timer.setInterval(250)
        self._json_timer.timeout.connect(self.refresh_json)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.designer)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("labTabs")
        self.tabs.addTab(self._export_tab(), "Export && Ergebnisvorschau")
        self.tabs.addTab(self._ict_tab(), "ICT-Prüfung")
        self.tabs.addTab(self._style_tab(), "Für mehrere übernehmen")
        self.tabs.addTab(self._library_tab(), "Bibliothek")
        self.tabs.addTab(self._json_tab(), "ICT/JSON")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, "Protokoll")
        splitter.addWidget(self.tabs)
        splitter.setSizes([780, 220])
        self.setCentralWidget(splitter)
        self._menu()
        if ict:
            try:
                self.designer.load_ict(ict)
                self.log("ICT geladen: %s" % ict)
            except IctError as exc:
                QMessageBox.warning(self, "ICT kann nicht geöffnet werden", str(exc))
        self.refresh_json()

    # ------------------------------------------------------------- structure
    def _menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")
        file_menu.addAction("Neue Vorlage", self.designer.new_template_interactive)
        file_menu.addAction("ICT öffnen …", self.designer.open_dialog)
        file_menu.addAction("Speichern", self.designer.save_interactive)
        file_menu.addAction("Speichern unter …", self.designer.save_as_dialog)
        file_menu.addSeparator()
        file_menu.addAction("Ausgabeordner wählen …", self.choose_output)
        file_menu.addAction("Ausgabeordner im Explorer öffnen", lambda: self.open_path(self.output))
        file_menu.addSeparator()
        file_menu.addAction("Beenden", self.close)
        help_menu = self.menuBar().addMenu("&Hilfe")
        help_menu.addAction("Über das Lab", lambda: QMessageBox.information(
            self, "Symbol Designer Lab",
            "Testhülle um das wiederverwendbare SymbolDesignerWidget (AP-WIDGET-001).\n"
            "Bearbeitung und Export laufen ausschließlich über das Widget; Ergebnisvorschauen lesen die "
            "tatsächlich geschriebenen Dateien.\nLogitech Plugin Service wird nicht benötigt."))

    def _button(self, text: str, slot, name: str = "") -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        if name:
            button.setObjectName(name)
        return button

    def _export_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        folder = QHBoxLayout()
        self.output_edit = QLineEdit(str(self.output))
        self.output_edit.setObjectName("outputDir")
        self.output_edit.editingFinished.connect(lambda: setattr(self, "output", Path(self.output_edit.text())))
        folder.addWidget(QLabel("Ausgabeordner:"))
        folder.addWidget(self.output_edit, 1)
        folder.addWidget(self._button("Wählen …", self.choose_output))
        folder.addWidget(self._button("Im Explorer öffnen", lambda: self.open_path(self.output)))
        left.addLayout(folder)
        stem_row = QHBoxLayout()
        self.stem_edit = QLineEdit("symbol")
        self.stem_edit.setObjectName("stem")
        stem_row.addWidget(QLabel("Dateiname:"))
        stem_row.addWidget(self.stem_edit, 1)
        self.symbol_name = QLineEdit()
        self.symbol_name.setPlaceholderText("Aktionsname für actionsymbols/ (optional)")
        stem_row.addWidget(self.symbol_name, 1)
        left.addLayout(stem_row)
        buttons = QGridLayout()
        for index, (text, slot, name) in enumerate((
                ("ICT exportieren", lambda: self.export(ict=True), "exportIct"),
                ("PNG 50/80/116 exportieren", lambda: self.export(png=True), "exportPng"),
                ("SVG exportieren", lambda: self.export(svg=True), "exportSvg"),
                ("Action-Symbol exportieren", lambda: self.export(symbol=True), "exportSymbol"),
                ("Alles exportieren", lambda: self.export(ict=True, png=True, svg=True), "exportAll"),
                ("Ergebnisse neu einlesen", self.refresh_results, "reloadResults"))):
            buttons.addWidget(self._button(text, slot, name), index // 3, index % 3)
        left.addLayout(buttons)
        self.files_list = QListWidget()
        self.files_list.setObjectName("exportedFiles")
        self.files_list.itemDoubleClicked.connect(lambda item: self.open_path(Path(item.data(Qt.ItemDataRole.UserRole)),
                                                                              select=True))
        left.addWidget(QLabel("Geschriebene Dateien (Doppelklick: im Explorer zeigen):"))
        left.addWidget(self.files_list, 1)
        layout.addLayout(left, 2)
        compare = QGroupBox("Ergebnisvorschau aus den geschriebenen Dateien – Vergleich mit der Editoransicht")
        grid = QGridLayout(compare)
        self.result_labels: dict[str, QLabel] = {}
        columns = (("editor", "Editor (116 px)"), ("png50", "PNG 50"), ("png80", "PNG 80"), ("png116", "PNG 116"),
                   ("svg", "SVG (116)"))
        for column, (key, title) in enumerate(columns):
            grid.addWidget(QLabel(title), 0, column, Qt.AlignmentFlag.AlignHCenter)
            label = QLabel("–")
            label.setFixedSize(124, 124)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background:#2a2a2a; border-radius:4px;")
            grid.addWidget(label, 1, column, Qt.AlignmentFlag.AlignHCenter)
            self.result_labels[key] = label
        self.compare_text = QLabel()
        self.compare_text.setWordWrap(True)
        self.compare_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(self.compare_text, 2, 0, 1, len(columns))
        layout.addWidget(compare, 3)
        return page

    def _ict_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(self._button("Exportierte ICT erneut importieren und prüfen", self.verify_ict, "verifyIct"))
        row.addWidget(self._button("Geprüfte ICT in den Designer laden", self.load_verified, "loadVerified"))
        row.addStretch(1)
        layout.addLayout(row)
        self.ict_result = QLabel("Noch keine ICT exportiert.")
        self.ict_result.setWordWrap(True)
        layout.addWidget(self.ict_result)
        self.ict_table = QTableWidget(0, 3)
        self.ict_table.setHorizontalHeaderLabels(["Eigenschaft", "Editor", "Wieder eingelesene Datei"])
        self.ict_table.horizontalHeader().setStretchLastSection(True)
        self.ict_table.setColumnWidth(0, 220)
        self.ict_table.setColumnWidth(1, 380)
        layout.addWidget(self.ict_table, 1)
        return page

    def _style_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        for text, slot, name in (("Beispielziele erzeugen", self.add_samples, "addSamples"),
                                 ("ICT-Dateien als Ziele laden …", self.add_target_files, "addTargets"),
                                 ("Für mehrere übernehmen …", self.designer.open_style_dialog, "openStyleDialog"),
                                 ("Rückgängig (letzte Übertragung)", self.designer.undo_stack.undo, "undoStyle"),
                                 ("Ziele als ICT in Ausgabeordner speichern", self.save_targets, "saveTargets"),
                                 ("Ausgewähltes Ziel im Designer öffnen", self.open_target, "openTarget")):
            left.addWidget(self._button(text, slot, name))
        left.addStretch(1)
        layout.addLayout(left)
        self.targets_list = QListWidget()
        self.targets_list.setObjectName("labTargets")
        self.targets_list.setIconSize(QSize(80, 80))
        layout.addWidget(self.targets_list, 1)
        self.content_check = QLabel("Inhaltsschutz: noch keine Ziele.")
        self.content_check.setWordWrap(True)
        self.content_check.setMinimumWidth(320)
        layout.addWidget(self.content_check)
        return page

    def _library_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.library_path = QLabel()
        self.library_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.library_path, 1)
        row.addWidget(self._button("Pfad wählen …", self.designer.library.choose_root))
        row.addWidget(self._button("Neu einlesen", lambda: self.designer.set_library_root(self.designer.library.root())))
        row.addWidget(self._button("Bericht als JSON speichern", self.save_library_report, "saveLibraryReport"))
        layout.addLayout(row)
        self.library_table = QTableWidget(0, 6)
        self.library_table.setHorizontalHeaderLabels(["Paket (displayName)", "name", "Icons", "Formate",
                                                      "Nicht unterstützt", "Hinweise/Fehler"])
        self.library_table.horizontalHeader().setStretchLastSection(True)
        self.library_table.setColumnWidth(0, 240)
        layout.addWidget(self.library_table, 1)
        return page

    def _json_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.shorten = QCheckBox("Base64-Bilddaten kürzen")
        self.shorten.setChecked(True)
        self.shorten.toggled.connect(lambda _: self.refresh_json())
        layout.addWidget(self.shorten)
        self.json_view = QPlainTextEdit()
        self.json_view.setObjectName("jsonView")
        self.json_view.setReadOnly(True)
        self.json_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.json_view, 1)
        return page

    # ------------------------------------------------------------- helpers
    def log(self, text: str) -> None:
        self.log_view.appendPlainText("%s  %s" % (time.strftime("%H:%M:%S"), text))

    def open_path(self, path: Path, select: bool = False) -> None:
        path = Path(path)
        if select and path.is_file() and sys.platform == "win32":
            os.startfile(str(path.parent))
            return
        if not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Test-Ausgabeverzeichnis wählen", str(self.output))
        if chosen:
            self.output = Path(chosen)
            self.output_edit.setText(chosen)

    def _schedule_json(self) -> None:
        self._json_timer.start()

    def refresh_json(self) -> None:
        data = self.designer.template_data()
        self.json_view.setPlainText(json.dumps(shortened(data) if self.shorten.isChecked() else data,
                                               indent=2, ensure_ascii=False))

    def _applied(self, data: dict) -> None:
        self.log("Übernommen (applied-Signal, %d Elemente)" % len(data.get("items", [])))
        if self.designer.path is not None:
            self.log("Gespeichert: %s" % self.designer.save_ict())

    # ------------------------------------------------------------- export and results
    def export(self, ict=False, png=False, svg=False, symbol=False):
        self.output = Path(self.output_edit.text())
        options = ExportOptions(self.output, self.stem_edit.text().strip() or "symbol", ict,
                                EXPORT_SIZES if png else (), svg, symbol, None, self.symbol_name.text().strip())
        report = self.designer.export_bundle(options)
        for path in report.files:
            key = path.suffix.lower().lstrip(".")
            if key == "png":
                key = "png" + path.stem.rsplit("_", 1)[-1].replace("px", "")
            if path.parent.name == "actionsymbols":
                key = "symbol"
            self.last_files[key] = path
            self.log("Geschrieben: %s (%d Bytes)" % (path, path.stat().st_size))
        for note in report.notes:
            self.log("Hinweis: " + note)
        for error in report.errors:
            self.log("FEHLER: " + error)
        if report.errors and self.designer.ask_user:
            QMessageBox.warning(self, "Exportfehler", "\n".join(report.errors))
        self.refresh_results()
        if ict and "ict" in self.last_files:
            self.verify_ict()
        return report

    def refresh_results(self) -> None:
        self.files_list.clear()
        for key, path in sorted(self.last_files.items()):
            exists = path.exists()
            item = QListWidgetItem("%s  –  %s  (%s)" % (key.upper(), path,
                                                        "%d Bytes" % path.stat().st_size if exists else "fehlt"))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files_list.addItem(item)
        editor = render_template(self.designer.template, 116)
        self.result_labels["editor"].setPixmap(QPixmap.fromImage(editor))
        lines = []
        for key in ("png50", "png80", "png116"):
            path = self.last_files.get(key)
            image = QImage(str(path)) if path and path.exists() else QImage()
            if image.isNull():
                self.result_labels[key].setText("–")
                continue
            self.result_labels[key].setPixmap(QPixmap.fromImage(image))
            lines.append("%s: %d×%d px aus Datei gelesen" % (key.upper(), image.width(), image.height()))
            if key == "png116":
                lines.append("PNG 116 ↔ Editor: mittlere Abweichung %.3f %%" % image_difference(editor, image))
        path = self.last_files.get("svg")
        if path and path.exists():
            image = svg_image(path, 116)
            self.result_labels["svg"].setPixmap(QPixmap.fromImage(image))
            lines.append("SVG ↔ Editor (QtSvg-Rendering der Datei): mittlere Abweichung %.3f %% – Abweichungen "
                         "entstehen durch Kantenglättung/Schrift-Rasterung" % image_difference(editor, image))
        self.compare_text.setText("\n".join(lines) or "Noch keine Exportdateien.")

    # ------------------------------------------------------------- ICT verification
    def verify_ict(self) -> None:
        path = self.last_files.get("ict")
        if not path or not path.exists():
            self.ict_result.setText("Bitte zuerst eine ICT exportieren.")
            return
        try:
            loaded = IconTemplate.load(path)
        except (OSError, IctError) as exc:
            self.ict_result.setText("Wieder einlesen fehlgeschlagen: %s" % exc)
            return
        self.verified = path
        current = self.designer.template
        same = loaded.data == current.data
        self.ict_result.setText("%s: %s" % (path, "inhaltlich identisch mit dem Editorzustand" if same else
                                            "ABWEICHUNG zum Editorzustand (Editor nach Export geändert?)"))
        rows = []

        def describe(template: IconTemplate) -> list[str]:
            info = template.image_info()
            item = template.item(IMAGE) or {}
            return [argb_hex(template.background),
                    "%s · %s" % (item.get("imageFileName") or "–", info.describe() if info else "kein Bild"),
                    "%s / %s" % (template.area(IMAGE), "sichtbar" if template.visible(IMAGE) else "ausgeblendet"),
                    "%d° · %s" % (template.rotation, argb_hex(template.image_color)),
                    repr(template.text), "%s, %d" % (template.font_name, template.font_size),
                    argb_hex(template.text_color),
                    "%s / %s" % (template.area(TEXT), "sichtbar" if template.visible(TEXT) else "ausgeblendet")]
        labels = ["Hintergrund", "Bild", "Bildbereich / Sichtbarkeit", "Drehung · Symbolfarbe", "Text",
                  "Schrift, Schriftgrad", "Textfarbe", "Textbereich / Sichtbarkeit"]
        for label, a, b in zip(labels, describe(current), describe(loaded)):
            rows.append((label, a, b))
        self.ict_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2 and values[1] != values[2]:
                    item.setBackground(QColor("#5b2333"))
                self.ict_table.setItem(row, column, item)
        self.log("ICT erneut eingelesen: %s – %s" % (path, "identisch" if same else "abweichend"))

    def load_verified(self) -> None:
        path = getattr(self, "verified", None)
        if path:
            self.designer.load_ict(path)
            self.log("Geprüfte ICT in den Designer geladen: %s" % path)

    # ------------------------------------------------------------- style transfer targets
    def _register_targets(self, targets: list[StyleTarget]) -> None:
        for target in targets:
            self.target_fingerprints[id(target)] = content_fingerprint(target.template)
        self.designer.set_style_targets(self.designer.style_targets + targets)
        self.refresh_targets()

    def add_samples(self) -> None:
        targets = sample_targets()
        self._register_targets(targets)
        self.log("%d Beispielziele erzeugt" % len(targets))

    def add_target_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "ICT-Vorlagen als Ziele laden", str(self.output),
                                                "Logitech Icon Templates (*.ict)")
        targets = []
        for name in files:
            try:
                targets.append(StyleTarget(Path(name).stem, IconTemplate.load(name), Path(name)))
            except (OSError, IctError) as exc:
                self.log("Ziel nicht geladen: %s – %s" % (name, exc))
        self._register_targets(targets)

    def refresh_targets(self) -> None:
        for target in self.designer.style_targets:
            self.target_fingerprints.setdefault(id(target), content_fingerprint(target.template))
        self.targets_list.clear()
        intact = 0
        for target in self.designer.style_targets:
            ok = content_fingerprint(target.template) == self.target_fingerprints[id(target)]
            intact += ok
            item = QListWidgetItem(QIcon(QPixmap.fromImage(render_template(target.template, 80))),
                                   "%s%s\n%s\nInhalt %s" % (target.name, " (geändert)" if target.modified else "",
                                                            content_summary(target.template),
                                                            "unverändert ✔" if ok else "VERÄNDERT ✖"))
            item.setData(Qt.ItemDataRole.UserRole, target)
            self.targets_list.addItem(item)
        count = len(self.designer.style_targets)
        self.content_check.setText(
            "Inhaltsschutz: %d von %d Zielen mit unveränderten Bild-/Textinhalten, Dateinamen, $type und "
            "unbekannten Feldern." % (intact, count) if count else "Inhaltsschutz: noch keine Ziele.")

    def save_targets(self) -> None:
        directory = Path(self.output_edit.text()) / "targets"
        written = []
        for index, target in enumerate(self.designer.style_targets, 1):
            stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in target.name)
            written.append(target.template.save(directory / ("%02d_%s.ict" % (index, stem))))
        self.log("Ziele gespeichert: %s" % ", ".join(str(p) for p in written))
        if written and self.designer.ask_user:
            QMessageBox.information(self, "Ziele gespeichert", "%d ICT-Dateien in %s" % (len(written), directory))

    def open_target(self) -> None:
        item = self.targets_list.currentItem()
        if item is not None:
            target: StyleTarget = item.data(Qt.ItemDataRole.UserRole)
            self.designer.load_template(target.template, target.name, target.path)

    # ------------------------------------------------------------- library report
    def refresh_library_report(self) -> None:
        scan = self.designer.library.scan
        if scan is None:
            return
        self.library_path.setText("Bibliothekspfad: %s   (Umgebungsvariable %s=%s)" % (
            scan.root, ENV_VAR, os.environ.get(ENV_VAR, "– nicht gesetzt, Standard verwendet")))
        self.library_table.setRowCount(len(scan.packages))
        for row, package in enumerate(scan.packages):
            values = [package.display_name, package.meta("name") or package.id, str(len(package.entries)),
                      ", ".join("%s %d" % (k.upper(), v) for k, v in sorted(package.formats().items())),
                      str(len(package.unsupported)), "; ".join(package.errors) or "–"]
            for column, value in enumerate(values):
                self.library_table.setItem(row, column, QTableWidgetItem(value))
        self.log("Bibliothek: %d Pakete, %d Symbole, %d Fehler" % (len(scan.packages), scan.icon_count,
                                                                   len(scan.summary()["errors"])))

    def save_library_report(self) -> Path | None:
        scan = self.designer.library.scan
        if scan is None:
            return None
        path = Path(self.output_edit.text()) / "library_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scan.summary(), indent=2, ensure_ascii=False), encoding="utf-8")
        self.log("Bibliotheksbericht: %s" % path)
        return path


def install_diagnostics(log_path: Path) -> Path:
    """Log Python errors, native crashes and Qt messages; Python errors are shown instead of lost."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    stream.write("\n=== Symbol Designer Lab gestartet %s (PySide6 %s, Python %s) ===\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), PySide6.__version__, sys.version.split()[0]))
    faulthandler.enable(stream, all_threads=True)
    for name in ("stdout", "stderr"):
        current = getattr(sys, name)
        if current is not None and hasattr(current, "reconfigure"):
            current.reconfigure(errors="backslashreplace")

    def message(mode, context, text):
        stream.write("%s Qt %s: %s\n" % (time.strftime("%H:%M:%S"), mode.name, text))

    def hook(kind, value, tb):
        details = "".join(traceback.format_exception(kind, value, tb))
        stream.write("%s Unbehandelter Fehler:\n%s" % (time.strftime("%H:%M:%S"), details))
        if sys.stderr is not None:
            sys.stderr.write(details)
        if QApplication.instance() is not None and not getattr(hook, "busy", False):
            hook.busy = True
            try:
                QMessageBox.critical(None, "Unerwarteter Fehler",
                                     "%s: %s\n\nDie Anwendung läuft weiter. Details stehen in:\n%s"
                                     % (kind.__name__, value, log_path))
            finally:
                hook.busy = False

    qInstallMessageHandler(message)
    sys.excepthook = hook
    return log_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Symbol Designer Lab")
    parser.add_argument("ict", nargs="?", help="optionale ICT-Vorlage zum Öffnen")
    parser.add_argument("--output", default=str(Path.cwd() / "symbol-designer-output"),
                        help="Test-Ausgabeverzeichnis")
    parser.add_argument("--library", help="Ordner mit Logitech-Icon-Paketen (sonst %s bzw. Standard)" % ENV_VAR)
    args = parser.parse_args(argv)
    log_path = install_diagnostics(Path(args.output) / "symbol-designer-lab.log")
    print("Diagnoseprotokoll:", log_path)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    dark_palette(app)
    window = LabWindow(Path(args.output), Path(args.ict) if args.ict else None,
                       Path(args.library) if args.library else None)
    window.show()
    return app.exec()
