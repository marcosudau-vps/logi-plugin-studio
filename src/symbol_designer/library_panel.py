"""Left column: searchable icon library built from installed Logitech packages."""
from __future__ import annotations

import math
import os
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .library import ENV_VAR, IconEntry, IconPackage, LibraryScan, default_library_root, scan_library
from .ui import broken_pixmap, thumbnail, ui_icon

ROLE = Qt.ItemDataRole.UserRole
CELL = 52
THUMB = 40


class IconGrid(QListWidget):
    def __init__(self, entries: list[IconEntry], parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(CELL, CELL))
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder = QPixmap(THUMB, THUMB)
        placeholder.fill(Qt.GlobalColor.transparent)
        self._placeholder = QIcon(placeholder)
        for entry in entries:
            item = QListWidgetItem(self._placeholder, "")
            item.setData(ROLE, entry)
            item.setToolTip("%s\n%s · %s" % (entry.name, entry.format.upper(), entry.path))
            item.setSizeHint(QSize(CELL, CELL))
            self.addItem(item)
        self.pending = list(range(self.count()))

    def mimeData(self, items):
        # created by Qt so that Qt owns and deletes it after the drag (a Python-made QMimeData would be freed twice)
        data = super().mimeData(items)
        data.setUrls([QUrl.fromLocalFile(str(i.data(ROLE).path)) for i in items])
        return data

    def visible_count(self) -> int:
        return sum(1 for i in range(self.count()) if not self.item(i).isHidden())

    def fit_height(self) -> None:
        per_row = max(1, (self.viewport().width() or self.width()) // CELL)
        self.setFixedHeight(max(CELL, math.ceil(self.visible_count() / per_row) * CELL + 6))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def load_some(self, budget: int) -> int:
        done = 0
        while self.pending and done < budget:
            item = self.item(self.pending.pop(0))
            entry: IconEntry = item.data(ROLE)
            pixmap, error = thumbnail(entry.path, THUMB)
            if pixmap is None:
                item.setIcon(QIcon(broken_pixmap(THUMB)))
                item.setToolTip("%s\nNicht verwendbar: %s" % (entry.path, error))
                item.setData(Qt.ItemDataRole.UserRole + 1, error)
            else:
                item.setIcon(QIcon(pixmap))
            done += 1
        return done


class PackageSection(QWidget):
    toggled = Signal()

    def __init__(self, package: IconPackage, parent=None):
        super().__init__(parent)
        self.package = package
        self.grid: IconGrid | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        row = QHBoxLayout()
        self.header = QToolButton()
        self.header.setObjectName("packageHeader")
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.RightArrow)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self.set_expanded)
        self.menu_button = QToolButton()
        self.menu_button.setIcon(ui_icon("dots"))
        self.menu_button.setToolTip("Paketinformationen")
        self.menu_button.setAutoRaise(True)
        self.menu_button.clicked.connect(self.show_info_menu)
        row.addWidget(self.header, 1)
        row.addWidget(self.menu_button)
        layout.addLayout(row)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(4, 0, 0, 0)
        layout.addLayout(self.body)
        notes = []
        if package.unsupported:
            names = ", ".join(p.name for p in package.unsupported[:4])
            notes.append("%d Datei(en) nicht unterstützt: %s%s" % (len(package.unsupported), names,
                                                                   " …" if len(package.unsupported) > 4 else ""))
        notes += package.errors
        self.notes = QLabel("\n".join(notes))
        self.notes.setObjectName("hintLabel")
        self.notes.setWordWrap(True)
        self.notes.setVisible(False)
        self.body.addWidget(self.notes)
        self.matches = len(package.entries)
        self.update_header()

    def update_header(self, query: str = "") -> None:
        total = len(self.package.entries)
        count = "%d von %d" % (self.matches, total) if query else str(total)
        self.header.setText("%s  (%s)" % (self.package.display_name, count))

    def ensure_grid(self) -> IconGrid:
        if self.grid is None:
            self.grid = IconGrid(self.package.entries)
            self.body.insertWidget(0, self.grid)
            self.grid.setVisible(self.header.isChecked())
        return self.grid

    def set_expanded(self, expanded: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self.ensure_grid()
        if self.grid is not None:
            self.grid.setVisible(expanded)
            QTimer.singleShot(0, self.grid.fit_height)
        self.notes.setVisible(expanded and bool(self.notes.text()))
        self.toggled.emit()

    def filter(self, words: list[str]) -> int:
        if words or self.grid is not None:
            grid = self.ensure_grid()
            for index in range(grid.count()):
                item = grid.item(index)
                item.setHidden(not all(w in item.data(ROLE).search_text for w in words))
            self.matches = grid.visible_count()
            grid.fit_height()
        else:
            self.matches = len(self.package.entries)
        self.update_header(" ".join(words))
        self.setVisible(not words or self.matches > 0)
        return self.matches

    def show_info_menu(self) -> None:
        package = self.package
        menu = QMenu(self)
        info = [package.meta("description") or "Keine Beschreibung",
                "Autor: " + (package.meta("author") or "unbekannt"),
                "Version: " + (package.meta("version") or "–"),
                "Lizenz: " + package.license_text,
                "Formate: " + (", ".join("%s %d" % (k.upper(), v) for k, v in sorted(package.formats().items())) or "–"),
                "Pfad: " + str(package.root)]
        for line in info:
            action = menu.addAction(line if len(line) < 120 else line[:117] + "…")
            action.setToolTip(line)
            action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Paketordner im Explorer öffnen",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(package.root))))
        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))


class LibraryPanel(QWidget):
    iconActivated = Signal(object)
    importRequested = Signal()
    rootChanged = Signal(object)

    def __init__(self, parent=None, root: Path | None = None):
        super().__init__(parent)
        self.setObjectName("libraryPanel")
        self.scan: LibraryScan | None = None
        self.sections: list[PackageSection] = []
        self.custom = IconPackage("eigene-bilder", "Eigene Bilder (diese Sitzung)", Path.cwd())
        self.custom.metadata = {"description": "In dieser Sitzung importierte eigene Bilder",
                                "license": "eigene Dateien – Rechte beim Benutzer"}
        self._root = root
        self._movie: QMovie | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QHBoxLayout()
        heading = QLabel("Symbolbibliothek")
        heading.setObjectName("panelTitle")
        icon = QLabel()
        icon.setPixmap(ui_icon("book").pixmap(20, 20))
        title.addWidget(icon)
        title.addWidget(heading, 1)
        for name, tip, slot in (("upload", "Eigenes Bild hinzufügen … (PNG, SVG, JPEG, BMP, WebP, GIF)",
                                 self.importRequested.emit),
                                ("refresh", "Bibliothek neu einlesen", lambda: self.load(self._root)),
                                ("folder", "Bibliothekspfad wählen …", self.choose_root)):
            button = QToolButton()
            button.setIcon(ui_icon(name))
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            button.setObjectName("library_" + name)
            title.addWidget(button)
        layout.addLayout(title)
        self.search = QLineEdit()
        self.search.setObjectName("librarySearch")
        self.search.setPlaceholderText("Suchen (alle Pakete)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(ui_icon("search"), QLineEdit.ActionPosition.TrailingPosition)
        layout.addWidget(self.search)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.apply_filter)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.status = QLabel()
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.sections_layout = QVBoxLayout(self.container)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)
        preview = QFrame()
        preview.setObjectName("libraryPreview")
        row = QHBoxLayout(preview)
        self.preview_image = QLabel()
        self.preview_image.setFixedSize(80, 80)
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setObjectName("previewImage")
        self.preview_info = QLabel("Symbol anklicken, um es zu übernehmen – oder auf die Zeichenfläche ziehen.")
        self.preview_info.setWordWrap(True)
        self.preview_info.setObjectName("hintLabel")
        row.addWidget(self.preview_image)
        row.addWidget(self.preview_info, 1)
        layout.addWidget(preview)
        self._loader = QTimer(self)
        self._loader.setInterval(0)
        self._loader.timeout.connect(self._load_thumbnails)

    # scanning
    def root(self) -> Path | None:
        return self._root

    def load(self, root: Path | None = None) -> LibraryScan:
        self._root = Path(root) if root else default_library_root()
        self.scan = scan_library(self._root)
        for section in self.sections:
            section.setParent(None)
            section.deleteLater()
        self.sections = []
        packages = self.scan.packages + ([self.custom] if self.custom.entries else [])
        for package in packages:
            section = PackageSection(package)
            section.toggled.connect(self._connect_grids)
            self.sections_layout.insertWidget(self.sections_layout.count() - 1, section)
            self.sections.append(section)
        if self.sections:
            self.sections[0].header.setChecked(True)
        self._connect_grids()
        self.update_status()
        self.apply_filter()
        self.rootChanged.emit(self._root)
        return self.scan

    def update_status(self) -> None:
        scan = self.scan
        if scan is None:
            return
        installed = [p for p in scan.packages if not p.bundled]
        text = "%d Pakete, %d Symbole · %s" % (len(scan.packages), scan.icon_count,
                                              scan.root if scan.root else "kein Pfad")
        if scan.errors:
            text += "\n⚠ " + "\n⚠ ".join(scan.errors)
        elif not installed:
            text += "\nKeine installierten Logitech-Pakete gefunden (%s)." % ENV_VAR
        self.status.setText(text)

    def choose_root(self) -> None:
        start = str(self._root) if self._root and self._root.exists() else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Ordner mit Logitech-Icon-Paketen wählen", start)
        if chosen:
            self.load(Path(chosen))

    def add_custom(self, path: Path) -> None:
        if any(e.path == path for e in self.custom.entries):
            return
        fmt = path.suffix.lower().lstrip(".").replace("jpg", "jpeg")
        self.custom.entries.append(IconEntry(path.stem, path, fmt, self.custom.id, "Eigene Bilder"))
        section = next((s for s in self.sections if s.package is self.custom), None)
        if section is not None:
            section.setParent(None)
            section.deleteLater()
            self.sections.remove(section)
        section = PackageSection(self.custom)
        section.toggled.connect(self._connect_grids)
        self.sections_layout.insertWidget(0, section)
        self.sections.insert(0, section)
        section.header.setChecked(True)
        self._connect_grids()
        self.apply_filter()

    # interaction
    def _connect_grids(self) -> None:
        for section in self.sections:
            grid = section.ensure_grid() if section.header.isChecked() else section.grid
            if grid is not None and not getattr(grid, "_wired", False):
                grid.itemClicked.connect(self._activate)
                grid.itemEntered.connect(lambda item: self.show_preview(item.data(ROLE)))
                grid._wired = True
        self._loader.start()

    def _activate(self, item: QListWidgetItem) -> None:
        entry: IconEntry = item.data(ROLE)
        self.show_preview(entry)
        error = item.data(Qt.ItemDataRole.UserRole + 1)
        if error:
            QMessageBox.warning(self, "Symbol nicht verwendbar", "%s\n\n%s" % (entry.path, error))
            return
        self.iconActivated.emit(entry)

    def package(self, package_id: str) -> IconPackage | None:
        return next((s.package for s in self.sections if s.package.id == package_id), None)

    def show_preview(self, entry: IconEntry | None) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        if entry is None:
            return
        package = self.package(entry.package_id)
        details = "<b>%s</b><br>%s · %s" % (entry.name, entry.format.upper(),
                                            package.display_name if package else entry.package_id)
        if entry.format == "gif":
            movie = QMovie(str(entry.path))
            if movie.isValid():
                movie.setScaledSize(QSize(72, 72))
                self.preview_image.setMovie(movie)
                movie.start()
                self._movie = movie
                frames = movie.frameCount()
                details += "<br>%s" % ("animiert, %d Bilder" % frames if frames > 1 else "Einzelbild")
        if self._movie is None:
            pixmap, error = thumbnail(entry.path, 72)
            self.preview_image.setPixmap(pixmap if pixmap is not None else broken_pixmap(72))
            if error:
                details += "<br><span style='color:#ff8080'>Nicht verwendbar: %s</span>" % error
        if package is not None:
            details += "<br>Lizenz: %s" % package.license_text
        self.preview_info.setText(details)

    def apply_filter(self) -> None:
        words = self.search.text().lower().split()
        total = 0
        for section in self.sections:
            if words and section.grid is None:
                section.ensure_grid()
            total += section.filter(words)
            if words and section.matches and not section.header.isChecked():
                section.header.setChecked(True)
        self._connect_grids()
        if words:
            self.preview_info.setText("%d Treffer für „%s“" % (total, self.search.text()))

    def _load_thumbnails(self) -> None:
        for section in self.sections:
            grid = section.grid
            if grid is not None and grid.isVisible() and grid.pending:
                grid.load_some(24)
                return
        self._loader.stop()

    def pending_thumbnails(self) -> int:
        return sum(len(s.grid.pending) for s in self.sections if s.grid is not None and s.grid.isVisible())

    def find_entry(self, predicate) -> IconEntry | None:
        return next((e for s in self.sections for e in s.package.entries if predicate(e)), None)
