"""Dialogs of the symbol designer: style transfer and export selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout)

from .ict import EXPORT_SIZES, IMAGE, MAX_IMAGE_BYTES, STYLE_ASPECTS, IconTemplate, IctError, preview_style
from .render import render_template

DEFAULT_ASPECTS = ("background", "layout", "font", "text_color", "symbol_format")


@dataclass
class StyleTarget:
    """A template that may receive a design; ``key`` identifies it for a host (e.g. an action id)."""
    name: str
    template: IconTemplate
    path: Path | None = None
    key: object = None
    modified: bool = False


def pixmap_of(template: IconTemplate, size: int) -> QPixmap:
    return QPixmap.fromImage(render_template(template, size))


def content_summary(template: IconTemplate) -> str:
    item = template.item(IMAGE) or {}
    image = item.get("imageFileName") or ("eingebettetes Bild" if item.get("image") else "kein Bild")
    return "Bild: %s · Text: „%s“" % (image, template.text.replace("\r", " ").replace("\n", " ")[:40])


class StyleTransferDialog(QDialog):
    def __init__(self, source: IconTemplate, targets: list[StyleTarget], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestaltung für mehrere übernehmen")
        self.setObjectName("styleTransferDialog")
        self.resize(940, 560)
        self.source = source
        self.targets = list(targets)
        layout = QVBoxLayout(self)
        intro = QLabel("Übertragen wird nur die <b>Gestaltung</b>. Bilder, Bildquellen, Texte, Aktionsidentität, "
                       "Parameter und Callbacks der Ziele bleiben unverändert.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        left = QVBoxLayout()
        left.addWidget(QLabel("1. Ziele auswählen"))
        self.list = QListWidget()
        self.list.setObjectName("styleTargets")
        self.list.setIconSize(QSize(48, 48))
        self.list.currentRowChanged.connect(self.update_preview)
        self.list.itemChanged.connect(lambda _: self.update_summary())
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        for text, slot in (("Alle", lambda: self.check_all(True)), ("Keine", lambda: self.check_all(False)),
                           ("ICT-Dateien hinzufügen …", self.add_files)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        left.addLayout(buttons)
        body.addLayout(left, 3)
        middle = QGroupBox("2. Zu übernehmende Eigenschaften")
        aspects = QVBoxLayout(middle)
        self.aspect_boxes: dict[str, QCheckBox] = {}
        for key, label in STYLE_ASPECTS.items():
            box = QCheckBox(label)
            box.setChecked(key in DEFAULT_ASPECTS)
            box.toggled.connect(lambda _: (self.update_preview(self.list.currentRow()), self.update_summary()))
            aspects.addWidget(box)
            self.aspect_boxes[key] = box
        hint = QLabel("Symbolfarbe wird nur auf einfarbige SVG-Ziele übertragen; mehrfarbige SVGs und "
                      "Rasterbilder behalten ihre Farben (Logitech-Regel).")
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        aspects.addWidget(hint)
        aspects.addStretch(1)
        body.addWidget(middle, 2)
        right = QGroupBox("3. Änderungen prüfen")
        grid = QGridLayout(right)
        self.before = QLabel()
        self.after = QLabel()
        for column, (title, label) in enumerate((("Vorher", self.before), ("Nachher", self.after))):
            grid.addWidget(QLabel(title), 0, column, Qt.AlignmentFlag.AlignHCenter)
            label.setFixedSize(116, 116)
            grid.addWidget(label, 1, column, Qt.AlignmentFlag.AlignHCenter)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("styleDetails")
        grid.addWidget(self.details, 2, 0, 1, 2)
        body.addWidget(right, 3)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.box = QDialogButtonBox()
        self.apply_button = self.box.addButton("Übernehmen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("applyStyle")
        self.box.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        layout.addWidget(self.box)
        for target in self.targets:
            self._add_item(target)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.update_summary()

    def _add_item(self, target: StyleTarget) -> None:
        item = QListWidgetItem(QIcon(pixmap_of(target.template, 48)),
                               "%s\n%s" % (target.name, content_summary(target.template)))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, target)
        self.list.addItem(item)

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "ICT-Vorlagen als Ziele laden", "",
                                                "Logitech Icon Templates (*.ict);;Alle Dateien (*)")
        errors = []
        for name in files:
            try:
                target = StyleTarget(Path(name).stem, IconTemplate.load(name), Path(name))
            except (OSError, IctError) as exc:
                errors.append("%s: %s" % (name, exc))
                continue
            self.targets.append(target)
            self._add_item(target)
        if errors:
            QMessageBox.warning(self, "Nicht geladen", "\n".join(errors))
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.update_summary()

    def check_all(self, value: bool) -> None:
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)

    def aspects(self) -> list[str]:
        return [k for k, box in self.aspect_boxes.items() if box.isChecked()]

    def selected_targets(self) -> list[StyleTarget]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def update_preview(self, row: int) -> None:
        if row < 0 or row >= self.list.count():
            self.before.clear()
            self.after.clear()
            self.details.setPlainText("Keine Ziele vorhanden. Über „ICT-Dateien hinzufügen …“ laden.")
            return
        target: StyleTarget = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        candidate, result = preview_style(self.source, target.template, self.aspects())
        self.before.setPixmap(pixmap_of(target.template, 116))
        self.after.setPixmap(pixmap_of(candidate, 116))
        lines = ["Unverändert: " + content_summary(target.template), ""]
        lines += result.changes or ["Keine Gestaltungsänderung."]
        lines += ["Übersprungen: " + s for s in result.skipped]
        self.details.setPlainText("\n".join(lines))

    def update_summary(self) -> None:
        targets = self.selected_targets()
        changes = sum(len(preview_style(self.source, t.template, self.aspects())[1].changes) for t in targets)
        self.summary.setText("%d Ziel(e) ausgewählt, %d Eigenschaftsänderung(en). Die Übernahme ist als "
                             "ein Schritt rückgängig machbar." % (len(targets), changes))
        self.apply_button.setText("Auf %d Ziel(e) übernehmen" % len(targets))
        self.apply_button.setEnabled(bool(targets) and bool(self.aspects()))


@dataclass
class ExportOptions:
    directory: Path
    stem: str
    ict: bool = True
    png_sizes: tuple[int, ...] = EXPORT_SIZES
    svg: bool = True
    action_symbol: bool = False
    action_source: Path | None = None
    action_name: str = ""


@dataclass
class ExportReport:
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ExportDialog(QDialog):
    def __init__(self, directory: Path, stem: str, symbol_ok: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.setObjectName("exportDialog")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        folder = QHBoxLayout()
        self.directory = QLineEdit(str(directory))
        browse = QPushButton("…")
        browse.clicked.connect(self.browse)
        folder.addWidget(self.directory, 1)
        folder.addWidget(browse)
        form.addRow("Zielordner:", folder)
        self.stem = QLineEdit(stem)
        form.addRow("Dateiname:", self.stem)
        layout.addLayout(form)
        products = QGroupBox("Ausgabeprodukte")
        column = QVBoxLayout(products)
        self.ict = QCheckBox("ICT – editierbare Logitech-Icon-Vorlage (icontemplates/)")
        self.ict.setChecked(True)
        column.addWidget(self.ict)
        pngs = QHBoxLayout()
        pngs.addWidget(QLabel("PNG:"))
        self.png_boxes = {}
        for size in EXPORT_SIZES:
            box = QCheckBox("%d × %d px" % (size, size))
            box.setChecked(True)
            pngs.addWidget(box)
            self.png_boxes[size] = box
        pngs.addStretch(1)
        column.addLayout(pngs)
        self.svg = QCheckBox("SVG – gestaltete Darstellung (Rasterbilder werden eingebettet, nicht vektorisiert)")
        self.svg.setChecked(True)
        column.addWidget(self.svg)
        self.symbol = QCheckBox("Action-Symbol – einfarbiges schwarzes SVG für actionsymbols/")
        column.addWidget(self.symbol)
        symbol_row = QHBoxLayout()
        self.from_image = QRadioButton("aus aktuellem Symbol")
        self.from_file = QRadioButton("separate SVG-Datei …")
        self.from_image.setEnabled(symbol_ok)
        (self.from_image if symbol_ok else self.from_file).setChecked(True)
        self.source_path: Path | None = None
        self.from_file.toggled.connect(lambda on: on and self.choose_symbol())
        symbol_row.addSpacing(20)
        symbol_row.addWidget(self.from_image)
        symbol_row.addWidget(self.from_file)
        column.addLayout(symbol_row)
        name_row = QHBoxLayout()
        name_row.addSpacing(20)
        name_row.addWidget(QLabel("Aktionsname:"))
        self.action_name = QLineEdit()
        self.action_name.setPlaceholderText("z. B. Loupedeck.MeinPlugin.ToggleMuteCommand")
        name_row.addWidget(self.action_name, 1)
        column.addLayout(name_row)
        if not symbol_ok:
            note = QLabel("Das aktuelle Symbol ist kein einfarbiges SVG und kann nicht direkt als Action-Symbol "
                          "dienen – bitte eine separate einfarbige SVG wählen.")
            note.setWordWrap(True)
            note.setObjectName("hintLabel")
            column.addWidget(note)
        layout.addWidget(products)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Exportieren")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.directory.text())
        if chosen:
            self.directory.setText(chosen)

    def choose_symbol(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Einfarbige SVG als Action-Symbol wählen", "",
                                              "SVG (*.svg)")
        if name:
            self.source_path = Path(name)
            self.from_file.setText("separate SVG: " + Path(name).name)
            self.symbol.setChecked(True)

    def options(self) -> ExportOptions:
        return ExportOptions(Path(self.directory.text()), self.stem.text().strip() or "symbol",
                             self.ict.isChecked(), tuple(s for s, b in self.png_boxes.items() if b.isChecked()),
                             self.svg.isChecked(), self.symbol.isChecked(),
                             self.source_path if self.from_file.isChecked() else None,
                             self.action_name.text().strip())


class GifChoiceDialog(QMessageBox):
    def __init__(self, name: str, size_bytes: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Animiertes GIF")
        self.setIcon(QMessageBox.Icon.Question)
        self.setText("„%s“ ist ein animiertes GIF (%.0f KB)." % (name, size_bytes / 1024))
        self.original = None
        if size_bytes <= MAX_IMAGE_BYTES:
            self.setInformativeText(
                "Original einbetten: Die Animation bleibt in der ICT-Vorlage erhalten. Ob der Logitech-Dienst "
                "eingebettete GIFs animiert, ist nicht verifiziert; PNG/SVG-Exporte zeigen das erste Bild.\n\n"
                "Standbild: Das erste Bild wird bewusst als PNG eingebettet.")
            self.original = self.addButton("Original-GIF einbetten", QMessageBox.ButtonRole.AcceptRole)
        else:
            self.setInformativeText(
                "Das GIF ist größer als die 150-KB-Grenze des Logitech-Icon-Editors. Eine Einbettung der "
                "Animation in die ICT-Vorlage ist nicht nachweislich kompatibel und wird nicht angeboten.\n\n"
                "Standbild: Das erste Bild wird bewusst als PNG eingebettet.")
        self.still = self.addButton("Standbild verwenden", QMessageBox.ButtonRole.ActionRole)
        self.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        self.setDefaultButton(self.still)
