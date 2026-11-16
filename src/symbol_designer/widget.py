"""SymbolDesignerWidget – reusable PySide6 editor for native Logitech ICT icon templates.

Public Python interface (used by the Lab and later by the Studio coordinator):

    new_template(text) / load_ict(path) / load_template(data, name, path)
    template_data() -> dict, ict_bytes() -> bytes, is_dirty()
    apply() / cancel() / reset_to_baseline()
    save_ict(path=None), export_png(path, size), export_svg(path), export_action_symbol(path, source=None),
    export_bundle(ExportOptions) -> ExportReport
    import_image(path, gif_mode=None), set_library_root(path)
    set_style_targets([StyleTarget]), apply_style_to(targets, aspects) -> [(StyleTarget, StyleResult)]

Signals: templateChanged(), dirtyChanged(bool), applied(dict), cancelled(), styleTransferred(list),
noticesChanged(list).
"""
from __future__ import annotations

import copy
from pathlib import Path

import shiboken6

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QUndoCommand, \
    QUndoStack
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFontComboBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget)

from .canvas import DesignCanvas
from .dialogs import (ExportDialog, ExportOptions, ExportReport, GifChoiceDialog, StyleTarget,
                      StyleTransferDialog)
from .ict import (DEFAULT_FONT, FONT_SIZES, GRID, IMAGE, LAYOUT_BY_KEY, LAYOUTS, MAX_IMAGE_BYTES, TEXT,
                  IconTemplate, IctError, StyleResult, apply_layout, detect_layout, editor_px, image_info,
                  transfer_style)
from .library import IconEntry
from .library_panel import LibraryPanel
from .render import (GIF_ORIGINAL, GIF_STILL, MAX_INPUT_BYTES, FALLBACK_FONT, PreparedImage, export_action_symbol,
                     export_png, export_svg, font_available, prepare_image, render_template)
from .ui import ColorButton, ui_icon

STYLE = """
#symbolDesigner { background: #0e0e0e; }
#symbolDesigner QLabel { color: #e6e6e6; }
#symbolDesigner QLabel#panelTitle { font-size: 16px; font-weight: 600; }
#symbolDesigner QLabel#hintLabel { color: #a0a0a0; }
#symbolDesigner QLabel#noticeLabel { color: #ffd479; }
#symbolDesigner QFrame#panel { background: #161616; border: 1px solid #2a2a2a; border-radius: 8px; }
#symbolDesigner QFrame#elementGroup { background: #121212; border: 1px solid #2e2e2e; border-radius: 8px; }
#symbolDesigner QFrame#elementGroup[selected="true"] { border: 1px solid #00D4C0; }
#symbolDesigner QToolButton { background: #262626; color: #e6e6e6; border: 1px solid #343434;
    border-radius: 6px; padding: 4px; }
#symbolDesigner QToolButton:hover { border-color: #00D4C0; }
#symbolDesigner QToolButton:checked { background: #0f3f3a; border-color: #00D4C0; }
#symbolDesigner QToolButton:disabled { color: #5a5a5a; background: #181818; }
#symbolDesigner QToolButton#packageHeader { background: transparent; border: none; font-weight: 600; }
#symbolDesigner QPushButton { background: #262626; color: #e6e6e6; border: 1px solid #3a3a3a;
    border-radius: 6px; padding: 7px 16px; }
#symbolDesigner QPushButton:hover { border-color: #00D4C0; }
#symbolDesigner QPushButton:disabled { color: #5a5a5a; background: #181818; border-color: #262626; }
#symbolDesigner QLabel#noticeLabel { background: transparent; }
#symbolDesigner QPushButton#primaryButton { background: #00D4C0; color: #00302b; font-weight: 700; border: none; }
#symbolDesigner QPushButton#primaryButton:disabled { background: #0f4d47; color: #5f8f8a; }
#symbolDesigner QPushButton#secondaryButton { background: #0f3f3a; color: #c9fbf4; border: 1px solid #00D4C0;
    font-weight: 600; }
#symbolDesigner QLineEdit, #symbolDesigner QPlainTextEdit, #symbolDesigner QSpinBox,
#symbolDesigner QComboBox { background: #0a0a0a; color: #eeeeee; border: 1px solid #3a3a3a;
    border-radius: 5px; padding: 3px; selection-background-color: #00897b; }
#symbolDesigner QComboBox QAbstractItemView { background: #1a1a1a; color: #eeeeee; }
#symbolDesigner QCheckBox { color: #d8d8d8; }
#symbolDesigner QScrollArea { background: transparent; border: none; }
#symbolDesigner QScrollArea > QWidget > QWidget { background: transparent; }
#symbolDesigner QListWidget { background: transparent; border: none; color: #ddd; }
#symbolDesigner QListWidget::item { background: #3a3a3a; border-radius: 4px; }
#symbolDesigner QListWidget::item:hover { background: #4a4a4a; }
#symbolDesigner QListWidget::item:selected { background: #0f6f66; }
#symbolDesigner QFrame#libraryPreview { background: #121212; border: 1px solid #2a2a2a; border-radius: 6px; }
#symbolDesigner QLabel#previewImage { background: #2a2a2a; border-radius: 4px; }
#symbolDesigner QSplitter::handle { background: #0e0e0e; }
"""
NAMES = {IMAGE: "Symbol", TEXT: "Text"}
HINT = ("Symbol links anklicken oder ein Bild hierher ziehen (max. 150 KB). Element anklicken, um es zu "
        "verschieben und über die Anfasser zu skalieren · Alt+Klick oder Tab: überlagertes Element · "
        "Shift: Seitenverhältnis umschalten · Strg: ohne Einrasten")


class SnapshotCommand(QUndoCommand):
    _ids: dict[str, int] = {}

    def __init__(self, widget: "SymbolDesignerWidget", before: str, after: str, text: str, merge_key=None):
        super().__init__(text)
        self.widget, self.before, self.after, self.merge_key = widget, before, after, merge_key
        self._applied = True

    def id(self) -> int:
        if self.merge_key is None:
            return -1
        return SnapshotCommand._ids.setdefault(self.merge_key, len(SnapshotCommand._ids) + 1)

    def mergeWith(self, other) -> bool:
        if not isinstance(other, SnapshotCommand) or other.merge_key != self.merge_key:
            return False
        self.after = other.after
        return True

    def redo(self):
        if self._applied:
            self._applied = False
            return
        self.widget._restore(self.after)

    def undo(self):
        self.widget._restore(self.before)


class StyleTransferCommand(QUndoCommand):
    def __init__(self, widget: "SymbolDesignerWidget", rows: list, text: str):
        super().__init__(text)
        self.widget, self.rows = widget, rows
        self._applied = True

    def _set(self, index: int):
        for target, before, after, modified in self.rows:
            target.template.restore((before, after)[index])
            target.modified = modified if index == 0 else True
        self.widget.styleTransferred.emit([row[0] for row in self.rows])

    def redo(self):
        if self._applied:
            self._applied = False
            return
        self._set(1)

    def undo(self):
        self._set(0)


def layout_pixmap(key: str, size: int = 22) -> QPixmap:
    layout = LAYOUT_BY_KEY[key]
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = (size * 2 - 4) / GRID
    painter.setPen(QPen(QColor("#e6e6e6"), 2))
    painter.drawRoundedRect(QRectF(2, 2, GRID * scale, GRID * scale), 5, 5)
    x, y, w, h = layout.image
    painter.fillRect(QRectF(2 + (x + w * .2) * scale, 2 + (y + h * .2) * scale, w * .6 * scale, h * .6 * scale),
                     QColor("#00D4C0"))
    x, y, w, h = layout.text
    painter.setPen(QPen(QColor("#ffffff"), 3))
    mid = 2 + (y + h / 2) * scale
    painter.drawLine(int(2 + (x + w * .2) * scale), int(mid), int(2 + (x + w * .8) * scale), int(mid))
    painter.end()
    return pixmap


class SymbolDesignerWidget(QWidget):
    templateChanged = Signal()
    dirtyChanged = Signal(bool)
    applied = Signal(dict)
    cancelled = Signal()
    styleTransferred = Signal(list)
    noticesChanged = Signal(list)

    def __init__(self, parent=None, library_root: str | Path | None = None, load_library: bool = True,
                 show_file_actions: bool = True):
        super().__init__(parent)
        self.setObjectName("symbolDesigner")
        self.setStyleSheet(STYLE)
        self.template = IconTemplate()
        self.path: Path | None = None
        self.name = "Neue Vorlage"
        self.ask_user = True
        self.last_error = ""
        self.notices: list[str] = []
        self.style_targets: list[StyleTarget] = []
        self.last_directory = Path.home()
        self.image_origin = ""
        self.undo_stack = QUndoStack(self)
        self._snapshot = self._baseline = self.template.snapshot()
        self._updating = False
        self._was_dirty = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self._update_size_previews)
        self._build(show_file_actions)
        self.canvas.template = self.template
        self.canvas.select(IMAGE)
        self.refresh_ui()
        if load_library:
            QTimer.singleShot(0, lambda: self.library.load(Path(library_root) if library_root else None))

    # ------------------------------------------------------------------ UI construction
    def _tool(self, icon: str, tip: str, slot=None, checkable=False, name="") -> QToolButton:
        button = QToolButton()
        button.setIcon(ui_icon(icon))
        button.setIconSize(QSize(20, 20))
        button.setToolTip(tip)
        button.setCheckable(checkable)
        if name:
            button.setObjectName(name)
        if slot is not None:
            (button.toggled if checkable else button.clicked).connect(slot)
        return button

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        return frame, layout

    def _build(self, show_file_actions: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        header.addWidget(self.title, 1)
        self.file_button = QToolButton()
        self.file_button.setObjectName("fileMenuButton")
        self.file_button.setText("Datei")
        self.file_button.setIcon(ui_icon("file"))
        self.file_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.file_button)
        menu.addAction("Neue Vorlage", self.new_template_interactive, QKeySequence.StandardKey.New)
        menu.addAction("ICT öffnen …", self.open_dialog, QKeySequence.StandardKey.Open)
        menu.addAction("Speichern", self.save_interactive, QKeySequence.StandardKey.Save)
        menu.addAction("Speichern unter …", self.save_as_dialog, QKeySequence.StandardKey.SaveAs)
        menu.addSeparator()
        menu.addAction("Exportieren (ICT/PNG/SVG/Action-Symbol) …", self.export_dialog)
        self.file_button.setMenu(menu)
        self.file_button.setVisible(show_file_actions)
        header.addWidget(self.file_button)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        self.library = LibraryPanel()
        self.library.setObjectName("panel")
        self.library.setMinimumWidth(250)
        self.library.iconActivated.connect(self._library_icon)
        self.library.importRequested.connect(self.import_dialog)
        splitter.addWidget(self.library)

        center, column = self._panel()
        tools = QHBoxLayout()
        self.undo_button = self._tool("undo", "Rückgängig (Strg+Z)", self.undo_stack.undo, name="undoButton")
        self.redo_button = self._tool("redo", "Wiederholen (Strg+Y)", self.undo_stack.redo, name="redoButton")
        self.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        self.undo_stack.indexChanged.connect(lambda _: self._emit_dirty())
        self.aids_button = self._tool("frame", "Bearbeitungshilfen (Rahmen ausgeblendeter Elemente) anzeigen",
                                      self._set_aids, True, "aidsButton")
        self.aids_button.blockSignals(True)
        self.aids_button.setChecked(True)
        self.aids_button.blockSignals(False)
        self.grid_button = self._tool("grid", "Raster und Mittellinien einblenden", self._set_grid, True, "gridButton")
        self.align_button = self._tool("align", "Ausrichten und Anordnen", name="alignButton")
        self.align_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.align_button.setMenu(self._align_menu())
        self.reset_button = self._tool("reset", "Alle Änderungen seit dem Laden/Übernehmen zurücksetzen",
                                       self.reset_to_baseline, name="resetButton")
        self.upload_button = self._tool("upload", "Eigenes Bild hinzufügen … (PNG, SVG, JPEG, BMP, WebP, GIF)",
                                        self.import_dialog, name="uploadButton")
        for widget in (self.undo_button, self.redo_button):
            tools.addWidget(widget)
        tools.addSpacing(12)
        for widget in (self.aids_button, self.grid_button, self.align_button):
            tools.addWidget(widget)
        tools.addStretch(1)
        tools.addWidget(self.reset_button)
        tools.addWidget(self.upload_button)
        column.addLayout(tools)
        stage = QHBoxLayout()
        self.canvas = DesignCanvas()
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.geometryEdited.connect(self._canvas_geometry)
        self.canvas.filesDropped.connect(self._files_dropped)
        self.canvas.textEditRequested.connect(lambda: (self.text_edit.setFocus(), self.text_edit.selectAll()))
        stage.addWidget(self.canvas, 1)
        side = QVBoxLayout()
        self.rotate_button = self._tool("rotate", "Symbol um 90° im Uhrzeigersinn drehen (imageRotation)",
                                        self.rotate_image, name="rotateButton")
        self.cycle_button = self._tool("layers", "Nächstes (auch überlagertes) Element auswählen (Tab)",
                                       lambda: self.canvas.cycle_selection(), name="cycleButton")
        self.preview_button = self._tool("eye", "Reiner Vorschaumodus ohne Auswahlrahmen", self._set_preview,
                                         True, "previewButton")
        for widget in (self.rotate_button, self.cycle_button, self.preview_button):
            side.addWidget(widget)
        side.addStretch(1)
        stage.addLayout(side)
        column.addLayout(stage, 1)
        hint = QLabel(HINT)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(hint)
        bottom = QHBoxLayout()
        self.size_labels = {}
        for size in (50, 80, 116):
            box = QVBoxLayout()
            box.setSpacing(2)
            label = QLabel()
            label.setFixedSize(size, size)
            label.setToolTip("Gerenderte Originalgröße %d × %d px (identisch mit dem PNG-Export)" % (size, size))
            caption = QLabel("%d px" % size)
            caption.setObjectName("hintLabel")
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            box.addStretch(1)
            box.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(caption)
            bottom.addLayout(box)
            self.size_labels[size] = label
        bottom.addSpacing(10)
        self.notice_label = QLabel()
        self.notice_label.setObjectName("noticeLabel")
        self.notice_label.setWordWrap(True)
        self.notice_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.notice_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notices = QScrollArea()
        notices.setWidgetResizable(True)
        notices.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        notices.setWidget(self.notice_label)
        notices.setFixedHeight(140)
        bottom.addWidget(notices, 1)
        column.addLayout(bottom)
        splitter.addWidget(center)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(320)
        properties, panel = self._panel()
        scroll.setWidget(properties)
        heading = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(ui_icon("pencil").pixmap(20, 20))
        heading.addWidget(icon)
        title = QLabel("Bearbeiten")
        title.setObjectName("panelTitle")
        heading.addWidget(title, 1)
        panel.addLayout(heading)
        form = QFormLayout()
        self.background_button = ColorButton("Hintergrundfarbe")
        self.background_button.setObjectName("backgroundColor")
        self.background_button.colorChanged.connect(self.set_background)
        form.addRow("Hintergrund:", self.background_button)
        layouts = QHBoxLayout()
        self.layout_buttons = {}
        for layout in LAYOUTS[:4]:
            button = QToolButton()
            button.setIcon(QIcon(layout_pixmap(layout.key)))
            button.setIconSize(QSize(26, 26))
            button.setCheckable(True)
            button.setToolTip("Layout: " + layout.label)
            button.setObjectName("layout_" + layout.key)
            button.clicked.connect(lambda _=False, k=layout.key: self.apply_layout(k))
            layouts.addWidget(button)
            self.layout_buttons[layout.key] = button
        more = QToolButton()
        more.setText("…")
        more.setToolTip("Weitere Layoutvorlagen")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more)
        for layout in LAYOUTS:
            more_menu.addAction(QIcon(layout_pixmap(layout.key)), layout.label,
                                lambda k=layout.key: self.apply_layout(k))
        more.setMenu(more_menu)
        layouts.addWidget(more)
        layouts.addStretch(1)
        form.addRow("Layout:", layouts)
        panel.addLayout(form)

        self.groups = {}
        self.eye_buttons = {}
        self.geometry_spins: dict[str, dict[str, QSpinBox]] = {}
        image_group, image_form = self._element_group(IMAGE)
        self.image_source = QLabel()
        self.image_source.setWordWrap(True)
        self.image_source.setObjectName("hintLabel")
        image_form.addRow(self.image_source)
        buttons = QHBoxLayout()
        choose = QPushButton("Bild wählen …")
        choose.setObjectName("chooseImage")
        choose.clicked.connect(self.import_dialog)
        self.remove_image_button = QPushButton("Entfernen")
        self.remove_image_button.setToolTip("Bildinhalt aus der Vorlage entfernen (rückgängig machbar)")
        self.remove_image_button.clicked.connect(self.remove_image)
        buttons.addWidget(choose)
        buttons.addWidget(self.remove_image_button)
        image_form.addRow(buttons)
        self.image_color_button = ColorButton("Symbolfarbe")
        self.image_color_button.setObjectName("imageColor")
        self.image_color_button.colorChanged.connect(self.set_image_color)
        image_form.addRow("Symbolfarbe:", self.image_color_button)
        self.image_color_note = QLabel()
        self.image_color_note.setWordWrap(True)
        self.image_color_note.setObjectName("hintLabel")
        image_form.addRow(self.image_color_note)
        self.rotation_combo = QComboBox()
        self.rotation_combo.setObjectName("rotation")
        for degrees in (0, 90, 180, 270):
            self.rotation_combo.addItem("%d°" % degrees, degrees)
        self.rotation_combo.currentIndexChanged.connect(
            lambda _: self._updating or self.set_rotation(self.rotation_combo.currentData()))
        image_form.addRow("Drehung:", self.rotation_combo)
        self._geometry_rows(IMAGE, image_form)
        panel.addWidget(image_group)

        text_group, text_form = self._element_group(TEXT)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("textContent")
        self.text_edit.setFixedHeight(58)
        self.text_edit.setPlaceholderText("Beschriftung (Zeilenumbruch mit Enter)")
        self.text_edit.textChanged.connect(lambda: self._updating or self.set_text(self.text_edit.toPlainText()))
        text_form.addRow("Text:", self.text_edit)
        self.font_combo = QFontComboBox()
        self.font_combo.setObjectName("fontName")
        self.font_combo.setEditable(True)
        self.font_combo.insertItem(0, DEFAULT_FONT)
        self.font_combo.currentTextChanged.connect(
            lambda name: self._updating or (name.strip() and self.set_font_name(name)))
        text_form.addRow("Schriftart:", self.font_combo)
        self.font_note = QLabel()
        self.font_note.setObjectName("hintLabel")
        self.font_note.setWordWrap(True)
        text_form.addRow(self.font_note)
        self.size_combo = QComboBox()
        self.size_combo.setObjectName("fontSize")
        for size in FONT_SIZES:
            self.size_combo.addItem("%d  (≈ %d px im 192-px-Editor)" % (size, editor_px(size)), size)
        self.size_combo.setToolTip("Nativer ICT-Schriftgrad 1–9; Options+ zeigt ihn als Pixelwert seiner "
                                   "192-px-Editorfläche an (5 = 27 px)")
        self.size_combo.currentIndexChanged.connect(
            lambda _: self._updating or self.set_font_size(self.size_combo.currentData()))
        text_form.addRow("Schriftgrad:", self.size_combo)
        self.text_color_button = ColorButton("Textfarbe")
        self.text_color_button.setObjectName("textColor")
        self.text_color_button.colorChanged.connect(self.set_text_color)
        text_form.addRow("Farbe:", self.text_color_button)
        self._geometry_rows(TEXT, text_form)
        panel.addWidget(text_group)
        panel.addStretch(1)
        splitter.addWidget(scroll)
        splitter.setSizes([300, 560, 360])
        splitter.setStretchFactor(1, 1)

        actions = QHBoxLayout()
        self.dirty_label = QLabel()
        self.dirty_label.setObjectName("hintLabel")
        actions.addWidget(self.dirty_label, 1)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setToolTip("Alle nicht übernommenen Änderungen verwerfen")
        self.cancel_button.clicked.connect(self.cancel_interactive)
        self.multi_button = QPushButton("Für mehrere übernehmen …")
        self.multi_button.setObjectName("secondaryButton")
        self.multi_button.setToolTip("Gestaltung (nicht Inhalte) auf weitere Vorlagen/Aktionen übertragen")
        self.multi_button.clicked.connect(self.open_style_dialog)
        self.apply_button = QPushButton("Übernehmen")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply)
        for widget in (self.cancel_button, self.multi_button, self.apply_button):
            actions.addWidget(widget)
        root.addLayout(actions)
        for sequence, slot in ((QKeySequence.StandardKey.Undo, self.undo_stack.undo),
                               (QKeySequence.StandardKey.Redo, self.undo_stack.redo),
                               (QKeySequence("Ctrl+Shift+Z"), self.undo_stack.redo)):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _element_group(self, kind: str) -> tuple[QFrame, QFormLayout]:
        frame = QFrame()
        frame.setObjectName("elementGroup")
        outer = QVBoxLayout(frame)
        top = QHBoxLayout()
        title = QPushButton(NAMES[kind])
        title.setFlat(True)
        title.setObjectName("select_" + kind)
        title.setToolTip("%s auf der Zeichenfläche auswählen" % NAMES[kind])
        title.setStyleSheet("text-align:left; font-size:15px; font-weight:700; border:none; background:transparent;")
        title.clicked.connect(lambda: self.select(kind))
        top.addWidget(title, 1)
        eye = self._tool("eye", "%s ein-/ausblenden (Inhalt bleibt erhalten)" % NAMES[kind],
                         lambda on, k=kind: self._updating or self.set_visible(k, on), True, "eye_" + kind)
        top.addWidget(eye)
        outer.addLayout(top)
        form = QFormLayout()
        outer.addLayout(form)
        self.groups[kind] = frame
        self.eye_buttons[kind] = eye
        return frame, form

    def _geometry_rows(self, kind: str, form: QFormLayout) -> None:
        grid = QGridLayout()
        spins = {}
        for index, (key, label) in enumerate((("x", "X"), ("y", "Y"), ("width", "B"), ("height", "H"))):
            spin = QSpinBox()
            spin.setRange(-100, 200) if key in ("x", "y") else spin.setRange(1, 200)
            spin.setObjectName("%s_%s" % (kind, key))
            spin.setToolTip("Einheiten des nativen 100×100-ICT-Rasters")
            spin.valueChanged.connect(lambda _, k=kind, f=key: self._updating or self._spin_changed(k, f))
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            grid.addWidget(spin, index // 2, (index % 2) * 2 + 1)
            spins[key] = spin
        self.geometry_spins[kind] = spins
        form.addRow("Bereich:", grid)
        lock = QCheckBox("Seitenverhältnis sperren")
        lock.setObjectName("lock_" + kind)
        lock.setChecked(self.canvas.lock_aspect[kind])
        lock.toggled.connect(lambda on, k=kind: self.canvas.lock_aspect.__setitem__(k, on))
        form.addRow(lock)
        spins["lock"] = lock

    def _align_menu(self) -> QMenu:
        menu = QMenu(self)
        for text, mode in (("Horizontal zentrieren", "hcenter"), ("Vertikal zentrieren", "vcenter"),
                           ("Mittig zentrieren", "center"), (None, None), ("Am linken Rand", "left"),
                           ("Am rechten Rand", "right"), ("Am oberen Rand", "top"), ("Am unteren Rand", "bottom"),
                           (None, None), ("Volle Breite", "fill_width"), ("Ganze Fläche", "fill")):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, lambda m=mode: self.align(self.canvas.selected, m))
        menu.addSeparator()
        menu.addAction("Positionen auf Layoutvorlage zurücksetzen", self.reset_positions)
        menu.addAction("Text über/unter Symbol legen (Reihenfolge)", self.swap_stacking)
        return menu

    # ------------------------------------------------------------------ state handling
    def _restore(self, snapshot: str) -> None:
        self.template.restore(snapshot)
        self._snapshot = snapshot
        self._changed()

    def _edit(self, text: str, change, merge_key=None) -> bool:
        try:
            change()
        except IctError as exc:
            self.template.restore(self._snapshot)
            self._report_error("Ungültige Eingabe", str(exc))
            self.refresh_ui()
            return False
        after = self.template.snapshot()
        if after == self._snapshot:
            return False
        self.undo_stack.push(SnapshotCommand(self, self._snapshot, after, text, merge_key))
        self._snapshot = after
        self._changed()
        return True

    def _changed(self) -> None:
        self.refresh_ui()
        self.templateChanged.emit()
        self._emit_dirty()

    def _emit_dirty(self) -> None:
        if not shiboken6.isValid(self.dirty_label):
            return
        dirty = self.is_dirty()
        self.dirty_label.setText("Nicht übernommene Änderungen" if dirty else "")
        if dirty != self._was_dirty:
            self._was_dirty = dirty
            self.dirtyChanged.emit(dirty)

    def _reset_history(self) -> None:
        self.undo_stack.clear()
        self._snapshot = self._baseline = self.template.snapshot()
        self.canvas.template = self.template
        self._changed()

    def _report_error(self, title: str, message: str) -> None:
        self.last_error = message
        self.set_notices([message], error=True)
        if self.ask_user:
            QMessageBox.warning(self, title, message)

    def set_notices(self, notices: list[str], error: bool = False) -> None:
        self.notices = list(notices)
        prefix = "⚠ " if error else "ℹ "
        self.notice_label.setText("\n".join(prefix + n for n in self.notices))
        self.notice_label.setStyleSheet("color:#ff8a80;" if error else "")
        self.noticesChanged.emit(self.notices)

    def refresh_ui(self) -> None:
        self._updating = True
        try:
            template = self.template
            self.title.setText("Symbol bearbeiten: %s" % self.name + (" *" if self.is_dirty() else ""))
            self.background_button.set_value(template.background)
            current = detect_layout(template)
            for key, button in self.layout_buttons.items():
                button.setChecked(key == current)
            info = template.image_info()
            data = template.image_bytes()
            item = template.item(IMAGE) or {}
            if data:
                source = "%s – %s" % (item.get("imageFileName") or "eingebettetes Bild", info.describe())
                if self.image_origin:
                    source += "\nHerkunft: " + self.image_origin
            elif item.get("imageFileName"):
                source = "Nur Dateiverweis '%s' (nicht eingebettet)" % item["imageFileName"]
            else:
                source = "Kein Bild – Symbol links wählen, eigenes Bild hinzufügen oder hierher ziehen"
            self.image_source.setText(source)
            tintable = bool(info and info.tintable)
            self.image_color_button.setEnabled(tintable)
            self.image_color_button.set_value(template.image_color)
            self.image_color_note.setText(
                "" if tintable else "Nicht einfärbbar: Logitech färbt nur einfarbige SVGs; mehrfarbige SVGs und "
                                    "Rasterbilder behalten ihre Farben. Der gespeicherte Wert bleibt erhalten.")
            self.image_color_note.setVisible(not tintable)
            self.remove_image_button.setEnabled(bool(item.get("image") or item.get("imageFileName")))
            self.rotation_combo.setCurrentIndex(self.rotation_combo.findData(template.rotation))
            self.rotate_button.setEnabled(template.item(IMAGE) is not None)
            if self.text_edit.toPlainText() != template.text:
                self.text_edit.setPlainText(template.text)
            if self.font_combo.currentText() != template.font_name:
                self.font_combo.setEditText(template.font_name)
            self.font_note.setText("" if font_available(template.font_name) else
                                   "Schrift ist auf diesem PC nicht installiert – Vorschau mit %s (Light). "
                                   "Logitech verwendet die Schrift aus der Vorlage." % FALLBACK_FONT)
            self.font_note.setVisible(not font_available(template.font_name))
            self.size_combo.setCurrentIndex(self.size_combo.findData(template.font_size))
            self.text_color_button.set_value(template.text_color)
            for kind in (IMAGE, TEXT):
                exists = template.item(kind) is not None
                eye = self.eye_buttons[kind]
                eye.setChecked(template.visible(kind) if exists else True)
                eye.setIcon(ui_icon("eye" if eye.isChecked() else "eye_off"))
                eye.setEnabled(exists)
                for key, value in zip(("x", "y", "width", "height"), template.area(kind)):
                    self.geometry_spins[kind][key].setValue(value)
                    self.geometry_spins[kind][key].setEnabled(exists)
                group = self.groups[kind]
                group.setProperty("selected", self.canvas.selected == kind)
                group.style().unpolish(group)
                group.style().polish(group)
            self.undo_button.setEnabled(self.undo_stack.canUndo())
            self.redo_button.setEnabled(self.undo_stack.canRedo())
            self.reset_button.setEnabled(self._snapshot != self._baseline)
            self.canvas.update()
            self._preview_timer.start()
        finally:
            self._updating = False

    def _update_size_previews(self) -> None:
        ratio = self.devicePixelRatioF()
        for size, label in self.size_labels.items():
            image = render_template(self.template, max(1, round(size * ratio)))
            image.setDevicePixelRatio(ratio)
            label.setPixmap(QPixmap.fromImage(image))

    # ------------------------------------------------------------------ selection and canvas
    def select(self, kind: str | None) -> None:
        self.canvas.select(kind)
        self.refresh_ui()

    def _selection_changed(self, kind) -> None:
        if not self._updating:
            self.refresh_ui()

    def _canvas_geometry(self, kind: str, area: tuple, final: bool) -> None:
        if final:
            label = "%s verschieben/skalieren" % NAMES[kind]
            self._edit(label, lambda: self.template.set_area(kind, *area))
        else:
            self.template.set_area(kind, *area)
            self._updating = True
            for key, value in zip(("x", "y", "width", "height"), area):
                self.geometry_spins[kind][key].setValue(value)
            self._updating = False
            self.canvas.update()

    def _spin_changed(self, kind: str, key: str) -> None:
        spins = self.geometry_spins[kind]
        values = {k: spins[k].value() for k in ("x", "y", "width", "height")}
        old = dict(zip(("x", "y", "width", "height"), self.template.area(kind)))
        if spins["lock"].isChecked() and key in ("width", "height") and old["width"] and old["height"]:
            ratio = old["width"] / old["height"]
            if key == "width":
                values["height"] = max(1, round(values["width"] / ratio))
            else:
                values["width"] = max(1, round(values["height"] * ratio))
        self._edit("%s-Bereich ändern" % NAMES[kind],
                   lambda: self.template.set_area(kind, values["x"], values["y"], values["width"], values["height"]),
                   "area:%s:%s" % (kind, key))

    def _set_aids(self, on: bool) -> None:
        self.canvas.show_aids = on
        self.canvas.update()

    def _set_grid(self, on: bool) -> None:
        self.canvas.show_grid = on
        self.canvas.update()

    def _set_preview(self, on: bool) -> None:
        self.canvas.preview_mode = on
        self.preview_button.setIcon(ui_icon("eye_off" if on else "eye"))
        self.canvas.update()

    def set_preview_mode(self, on: bool) -> None:
        self.preview_button.setChecked(on)

    # ------------------------------------------------------------------ editing API
    def set_background(self, argb: int) -> None:
        self._edit("Hintergrundfarbe ändern", lambda: setattr(self.template, "background", argb), "background")

    def apply_layout(self, key: str) -> None:
        if key not in LAYOUT_BY_KEY:
            raise IctError("Unbekannte Layoutvorlage: %s" % key)
        self._edit("Layout: " + LAYOUT_BY_KEY[key].label, lambda: apply_layout(self.template, key))
        self.refresh_ui()

    def reset_positions(self) -> None:
        self.apply_layout(detect_layout(self.template) or "image_top")

    def set_visible(self, kind: str, visible: bool) -> None:
        self._edit("%s %s" % (NAMES[kind], "einblenden" if visible else "ausblenden"),
                   lambda: self.template.set_visible(kind, visible))

    def set_area(self, kind: str, x: int, y: int, width: int, height: int) -> None:
        self._edit("%s-Bereich ändern" % NAMES[kind], lambda: self.template.set_area(kind, x, y, width, height))

    def align(self, kind: str | None, mode: str) -> None:
        if kind is None:
            self.set_notices(["Zum Ausrichten zuerst Symbol oder Text auswählen"])
            return
        x, y, w, h = self.template.area(kind)
        target = {"hcenter": (round((GRID - w) / 2), y, w, h), "vcenter": (x, round((GRID - h) / 2), w, h),
                  "center": (round((GRID - w) / 2), round((GRID - h) / 2), w, h), "left": (0, y, w, h),
                  "right": (GRID - w, y, w, h), "top": (x, 0, w, h), "bottom": (x, GRID - h, w, h),
                  "fill_width": (0, y, GRID, h), "fill": (0, 0, GRID, GRID)}[mode]
        self._edit("%s ausrichten" % NAMES[kind], lambda: self.template.set_area(kind, *target))

    def swap_stacking(self) -> None:
        items = self.template.items
        kinds = self.template.stacking()
        if len(kinds) < 2:
            return

        def swap():
            first = next(i for i, item in enumerate(items) if isinstance(item, dict) and item.get("itemType") == kinds[0])
            second = next(i for i, item in enumerate(items) if isinstance(item, dict) and item.get("itemType") == kinds[1])
            items[first], items[second] = items[second], items[first]
        self._edit("Reihenfolge Symbol/Text tauschen", swap)
        self.set_notices(["Reihenfolge der ICT-Elemente getauscht (%s liegt jetzt oben). Die Zeichenreihenfolge "
                          "im Logitech-Renderer ist nicht verifiziert." % NAMES[kinds[0]]])

    def set_rotation(self, degrees: int) -> None:
        self._edit("Symbol drehen", lambda: setattr(self.template, "rotation", degrees))

    def rotate_image(self) -> None:
        if self.template.item(IMAGE) is not None:
            self.set_rotation((self.template.rotation + 90) % 360)

    def set_image_color(self, argb: int) -> None:
        info = self.template.image_info()
        if not (info and info.tintable):
            self._report_error("Nicht einfärbbar", "Die Symbolfarbe gilt nur für einfarbige SVG-Bilder.")
            self.refresh_ui()
            return
        self._edit("Symbolfarbe ändern", lambda: setattr(self.template, "image_color", argb), "image_color")

    def set_text(self, text: str) -> None:
        self._edit("Text ändern", lambda: setattr(self.template, "text", text), "text")

    def set_font_name(self, name: str) -> None:
        self._edit("Schriftart ändern", lambda: setattr(self.template, "font_name", name), "font_name")

    def set_font_size(self, size: int) -> None:
        self._edit("Schriftgrad ändern", lambda: setattr(self.template, "font_size", size))

    def set_text_color(self, argb: int) -> None:
        self._edit("Textfarbe ändern", lambda: setattr(self.template, "text_color", argb), "text_color")

    def remove_image(self) -> None:
        self._edit("Bild entfernen", self.template.clear_image)
        self.image_origin = ""
        self.refresh_ui()

    # ------------------------------------------------------------------ images
    def import_image(self, path: str | Path, gif_mode: str | None = None, origin: str = "") -> PreparedImage | None:
        """Embed an image file; returns the prepared image or ``None`` when rejected/cancelled."""
        file = Path(path)
        try:
            if not file.is_file():
                raise IctError("Datei nicht gefunden: %s" % file)
            if file.stat().st_size > MAX_INPUT_BYTES:
                raise IctError("Datei ist größer als 8 MB und wird nicht importiert")
            data = file.read_bytes()
            info = image_info(data)
            if info.format == "gif" and info.animated and gif_mode is None:
                if not self.ask_user:
                    gif_mode = GIF_STILL
                else:
                    dialog = GifChoiceDialog(file.name, len(data), self)
                    dialog.exec()
                    if dialog.original is not None and dialog.clickedButton() is dialog.original:
                        gif_mode = GIF_ORIGINAL
                    elif dialog.clickedButton() is dialog.still:
                        gif_mode = GIF_STILL
                    else:
                        return None
            prepared = prepare_image(data, file.name, gif_mode or GIF_STILL)
        except (OSError, IctError) as exc:
            self._report_error("Bild kann nicht verwendet werden", "%s\n%s" % (file.name, exc))
            return None
        created = self.template.item(IMAGE) is None

        def change():
            self.template.set_image(prepared.data, prepared.filename)
            if created:
                self.template.set_visible(IMAGE, True)
        self._edit("Symbol ersetzen: " + prepared.filename, change)
        self.image_origin = origin or str(file)
        notes = ["Übernommen: %s – %s" % (prepared.filename, prepared.info.describe())] + prepared.notes
        if prepared.info.tintable:
            notes.append("Einfarbiges SVG: Symbolfarbe wurde auf die Originalfarbe gesetzt und ist änderbar")
        self.set_notices(notes)
        self.last_directory = file.parent
        if not origin:
            self.library.add_custom(file)
        self.select(IMAGE)
        return prepared

    def import_dialog(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Eigenes Bild auswählen", str(self.last_directory),
            "Bilder (*.png *.svg *.jpg *.jpeg *.bmp *.webp *.gif);;PNG (*.png);;SVG (*.svg);;Alle Dateien (*)")
        if name:
            self.import_image(name)

    def _library_icon(self, entry: IconEntry) -> None:
        package = self.library.package(entry.package_id)
        origin = "%s / %s" % (package.display_name if package else entry.package_id, entry.path.name)
        prepared = self.import_image(entry.path, origin=origin)
        if prepared is not None and package is not None and not package.bundled and package.id != "eigene-bilder":
            self.set_notices(self.notices + [
                "Das Bild wurde in die Vorlage eingebettet; der Export hängt nicht vom Bibliothekspfad ab. "
                "Lizenz des Pakets: %s – Nutzungsrechte vor Weitergabe prüfen." % package.license_text])

    def _files_dropped(self, paths: list) -> None:
        if not paths:
            return
        entry = self.library.find_entry(lambda e: e.path == paths[0])
        if entry is not None:
            self._library_icon(entry)
        else:
            self.import_image(paths[0])

    def set_library_root(self, root: str | Path | None) -> None:
        self.library.load(Path(root) if root else None)

    # ------------------------------------------------------------------ documents
    def is_dirty(self) -> bool:
        return self._snapshot != self._baseline

    def template_data(self) -> dict:
        return copy.deepcopy(self.template.data)

    def ict_bytes(self) -> bytes:
        return self.template.to_bytes()

    def load_template(self, data: dict | IconTemplate, name: str = "Vorlage", path: str | Path | None = None) -> None:
        template = data.copy() if isinstance(data, IconTemplate) else IconTemplate(copy.deepcopy(data))
        self.template = template
        self.path = Path(path) if path else None
        self.name = name
        self.image_origin = ""
        self._reset_history()
        self.canvas.select(IMAGE if template.item(IMAGE) is not None else (TEXT if template.item(TEXT) else None))
        self.set_notices(template.notices())
        self.refresh_ui()

    def new_template(self, text: str = "Neue Aktion") -> None:
        self.load_template(IconTemplate(), "Neue Vorlage")
        if text != "Neue Aktion":
            self.template.text = text
            self._reset_history()

    def load_ict(self, path: str | Path) -> IconTemplate:
        try:
            template = IconTemplate.load(path)
        except OSError as exc:
            raise IctError("ICT-Datei kann nicht gelesen werden: %s" % exc) from exc
        self.load_template(template, Path(path).stem, path)
        self.last_directory = Path(path).parent
        return self.template

    def save_ict(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise IctError("Kein Dateipfad – bitte „Speichern unter“ verwenden")
        if target.suffix.lower() != ".ict":
            target = target.with_suffix(".ict")
        self.template.save(target)
        self.path = target
        self.name = target.stem
        self._baseline = self._snapshot
        self.last_directory = target.parent
        self._changed()
        return target

    def apply(self) -> dict:
        """Accept the current design as the new baseline and hand it to the host."""
        self._baseline = self._snapshot
        self._changed()
        data = self.template_data()
        self.applied.emit(data)
        return data

    def cancel(self) -> None:
        self.template.restore(self._baseline)
        self._reset_history()
        self.cancelled.emit()

    def reset_to_baseline(self) -> None:
        self._edit("Zurücksetzen", lambda: self.template.restore(self._baseline))

    def _confirm_discard(self) -> bool:
        if not self.is_dirty() or not self.ask_user:
            return True
        answer = QMessageBox.question(self, "Änderungen verwerfen?",
                                      "Es gibt nicht übernommene Änderungen. Trotzdem fortfahren?")
        return answer == QMessageBox.StandardButton.Yes

    def new_template_interactive(self) -> None:
        if self._confirm_discard():
            self.new_template()

    def cancel_interactive(self) -> None:
        if self._confirm_discard():
            self.cancel()

    def open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "ICT-Vorlage öffnen", str(self.last_directory),
                                              "Logitech Icon Templates (*.ict);;Alle Dateien (*)")
        if name:
            try:
                self.load_ict(name)
            except IctError as exc:
                self._report_error("ICT kann nicht geöffnet werden", str(exc))

    def save_interactive(self) -> Path | None:
        if self.path is None:
            return self.save_as_dialog()
        try:
            return self.save_ict()
        except (OSError, IctError) as exc:
            self._report_error("Speichern fehlgeschlagen", str(exc))
            return None

    def save_as_dialog(self) -> Path | None:
        start = self.path or (self.last_directory / (self.name + ".ict"))
        name, _ = QFileDialog.getSaveFileName(self, "ICT-Vorlage speichern", str(start),
                                              "Logitech Icon Template (*.ict)")
        if not name:
            return None
        try:
            return self.save_ict(name)
        except (OSError, IctError) as exc:
            self._report_error("Speichern fehlgeschlagen", str(exc))
            return None

    # ------------------------------------------------------------------ export
    def export_png(self, path: str | Path, size: int) -> Path:
        return export_png(self.template, path, size)

    def export_svg(self, path: str | Path):
        return export_svg(self.template, path)

    def action_symbol_ready(self) -> bool:
        info = self.template.image_info()
        return bool(info and info.format == "svg" and info.monochrome)

    def export_action_symbol(self, path: str | Path, source: str | Path | None = None) -> Path:
        data = Path(source).read_bytes() if source else self.template.image_bytes()
        if not data:
            raise IctError("Kein Symbol vorhanden – bitte eine einfarbige SVG-Datei wählen")
        return export_action_symbol(data, path)

    def export_bundle(self, options: ExportOptions) -> ExportReport:
        report = ExportReport()
        directory = Path(options.directory)
        steps = []
        if options.ict:
            steps.append(("ICT", lambda: [self.template.save(directory / (options.stem + ".ict"))]))
        for size in options.png_sizes:
            steps.append(("PNG %d px" % size,
                          lambda s=size: [self.export_png(directory / ("%s_%dpx.png" % (options.stem, s)), s)]))
        if options.svg:
            def svg():
                result = self.export_svg(directory / (options.stem + ".svg"))
                report.notes.extend(result.notes)
                return [result.path]
            steps.append(("SVG", svg))
        if options.action_symbol:
            name = options.action_name or options.stem
            steps.append(("Action-Symbol", lambda: [self.export_action_symbol(
                directory / "actionsymbols" / (name + ".svg"), options.action_source)]))
        for label, step in steps:
            try:
                report.files.extend(step())
            except (OSError, IctError) as exc:
                report.errors.append("%s: %s" % (label, exc))
        if self.template.image_info() and self.template.image_info().animated:
            report.notes.append("PNG/SVG zeigen das erste Bild des animierten GIFs; die ICT enthält das Original")
        return report

    def export_dialog(self) -> ExportReport | None:
        dialog = ExportDialog(self.path.parent if self.path else self.last_directory,
                              self.path.stem if self.path else "symbol", self.action_symbol_ready(), self)
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return None
        report = self.export_bundle(dialog.options())
        lines = ["Geschrieben:"] + [str(p) for p in report.files] + report.notes
        if report.errors:
            lines += ["", "Fehler:"] + report.errors
        self.set_notices(report.notes + report.errors, error=bool(report.errors))
        if self.ask_user:
            (QMessageBox.warning if report.errors else QMessageBox.information)(self, "Export", "\n".join(lines))
        return report

    # ------------------------------------------------------------------ style transfer
    def set_style_targets(self, targets: list[StyleTarget]) -> None:
        self.style_targets = list(targets)

    def apply_style_to(self, targets: list[StyleTarget], aspects) -> list[tuple[StyleTarget, StyleResult]]:
        """Transfer design (never content) to ``targets`` as one undoable step."""
        rows, results = [], []
        for target in targets:
            before = target.template.snapshot()
            result = transfer_style(self.template, target.template, aspects)
            after = target.template.snapshot()
            results.append((target, result))
            if after != before:
                rows.append((target, before, after, target.modified))
                target.modified = True
        if rows:
            self.undo_stack.push(StyleTransferCommand(self, rows, "Gestaltung auf %d Vorlage(n) übertragen" % len(rows)))
            self.styleTransferred.emit([row[0] for row in rows])
        notes = ["Gestaltung auf %d von %d Ziel(en) übertragen (Strg+Z macht alles in einem Schritt rückgängig)"
                 % (len(rows), len(targets))]
        notes += ["%s: %s" % (t.name, s) for t, r in results for s in r.skipped]
        self.set_notices(notes)
        return results

    def open_style_dialog(self) -> list | None:
        dialog = StyleTransferDialog(self.template, self.style_targets, self)
        if dialog.exec() != StyleTransferDialog.DialogCode.Accepted:
            return None
        known = {id(t) for t in self.style_targets}
        self.style_targets += [t for t in dialog.targets if id(t) not in known]
        return self.apply_style_to(dialog.selected_targets(), dialog.aspects())
