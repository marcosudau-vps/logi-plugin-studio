from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.errors import LogitechAdapterError
from adapters.logitech.product import read_asset, validate_product
from core.errors import Diagnostic
from core.ids import is_valid_id
from core.validate import validate_project
from library.document import COLLECTIONS, ROOT, DocumentError, ProjectDocument, schema_default
from library.templates import callback_project
from runtime.wire import HostError, parse_json, project_digest
from studio.fields import ObjectEditor
from studio.images import export_image, render_tile
from studio.workers import BuildWorker, DeploymentWorker, DiagnosticWorker, ExportWorker

LABELS = {"components": "Komponenten / Aktionen", "states": "States",
          "bindings": "Bindings", "views": "Views / Folders",
          "presentations": "Presentations", "assets": "Assets"}


def project_header(raw: dict) -> dict:
    header = raw.get("project")
    return header if isinstance(header, dict) else {}


def project_rows(raw: dict, collection: str) -> list:
    rows = raw.get(collection)
    return rows if isinstance(rows, list) else []


class StudioWindow(QMainWindow):
    def __init__(self, project_path: str | Path | None = None):
        super().__init__()
        self.setObjectName("studioWindow")
        self.resize(1220, 820)
        self.document = ProjectDocument()
        if project_path is not None:
            self.document.load(project_path)
        self.editor: ObjectEditor | None = None
        self.selection = ("project", project_header(self.document.raw).get("id", ""))
        self._refreshing = False
        self._raw_pending = False
        self._build: BuildWorker | None = None
        self._diagnostic: DiagnosticWorker | None = None
        self._deployment: DeploymentWorker | None = None
        self._export: ExportWorker | None = None
        self.last_rollback_plan: dict | None = None
        self.last_build: dict | None = None
        self._preview_page = 0
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(300)
        self._validation_timer.timeout.connect(self.validate_live)
        self._create_ui()
        self.refresh()

    def _action(self, toolbar: QToolBar, text: str, callback, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        toolbar.addAction(action)
        return action

    def _create_ui(self):
        toolbar = QToolBar("Projekt")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._action(toolbar, "Neu", self.new_project, QKeySequence.StandardKey.New)
        self._action(toolbar, "Callback-Vorlage", self.new_callback_project)
        self._action(toolbar, "Oeffnen", self.open_project, QKeySequence.StandardKey.Open)
        self._action(toolbar, "Speichern", self.save_project, QKeySequence.StandardKey.Save)
        self._action(toolbar, "Speichern unter", self.save_as, QKeySequence.StandardKey.SaveAs)
        self._action(toolbar, "Native ICT / Symbol-Designer", lambda: self.open_native_symbol_designer())
        toolbar.addSeparator()
        self.undo_action = self._action(toolbar, "Rueckgaengig", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action(toolbar, "Wiederholen", self.redo, QKeySequence.StandardKey.Redo)
        add = QToolButton()
        add.setText("Hinzufuegen")
        add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add)
        for section, label in LABELS.items():
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, section=section: self.add_entity(section))
        action = menu.addAction("PNG importieren / exportieren")
        action.triggered.connect(self.import_asset)
        add.setMenu(menu)
        toolbar.addWidget(add)
        splitter = QSplitter()
        sidebar = QWidget()
        left = QVBoxLayout(sidebar)
        title = QLabel("PLUGIN STUDIO")
        title.setStyleSheet("font-size: 19px; font-weight: 650; padding: 8px 0;")
        left.addWidget(title)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("ID oder Anzeigename filtern")
        self.filter.textChanged.connect(self.filter_tree)
        left.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(245)
        self.tree.currentItemChanged.connect(self._tree_changed)
        left.addWidget(self.tree)
        row = QHBoxLayout()
        duplicate = QPushButton("Duplizieren")
        remove = QPushButton("Entfernen")
        duplicate.clicked.connect(self.duplicate_entity)
        remove.clicked.connect(self.remove_entity)
        row.addWidget(duplicate)
        row.addWidget(remove)
        left.addLayout(row)
        splitter.addWidget(sidebar)
        self.pages = QTabWidget()
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        editor_page = QWidget()
        editor_layout = QVBoxLayout(editor_page)
        self.editor_hint = QLabel("Eigenschaften bearbeiten; Apply oder Objektwechsel uebernimmt den Entwurf, Speichern schreibt die Datei.")
        self.editor_hint.setWordWrap(True)
        editor_layout.addWidget(self.editor_hint)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        editor_layout.addWidget(self.editor_scroll)
        self.apply_button = QPushButton("Eigenschaften uebernehmen")
        self.apply_button.clicked.connect(self.apply_editor)
        editor_layout.addWidget(self.apply_button)
        self.pages.addTab(editor_page, "Eigenschaften")
        self._preview_ui()
        validation_page = QWidget()
        validation_layout = QVBoxLayout(validation_page)
        self.validation_summary = QLabel()
        validation_layout.addWidget(self.validation_summary)
        self.validation_table = QTableWidget(0, 4)
        self.validation_table.setHorizontalHeaderLabels(["Schwere", "Code", "Projektpfad", "Meldung"])
        self.validation_table.horizontalHeader().setStretchLastSection(True)
        self.validation_table.setColumnWidth(1, 180)
        self.validation_table.setColumnWidth(2, 220)
        self.validation_table.cellDoubleClicked.connect(self._navigate_diagnostic)
        validation_layout.addWidget(self.validation_table)
        self.pages.addTab(validation_page, "Validierung")
        self._build_ui()
        self._diagnostic_ui()
        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        raw_layout.addWidget(QLabel("Kanonisches Projekt-JSON, einschliesslich Dependencies. Ungueltige Daten werden nicht still repariert."))
        self.project_json = QPlainTextEdit()
        self.project_json.setObjectName("projectJson")
        self.project_json.textChanged.connect(self._raw_changed)
        raw_layout.addWidget(self.project_json)
        apply = QPushButton("Projekt-JSON explizit uebernehmen")
        apply.clicked.connect(self.apply_raw)
        raw_layout.addWidget(apply)
        self.pages.addTab(raw_page, "Projekt-JSON")

    def create_native_symbol_dialog(self, project_path: str | Path):
        """Create the real SDK-native ICT editor without changing the legacy project."""
        from studio.native_symbol_dialog import NativeSymbolDesignerDialog
        return NativeSymbolDesignerDialog(project_path, self)

    def open_native_symbol_designer(self, project_path: str | Path | None = None):
        """Open a native project in the finished SymbolDesignerWidget.

        The generic legacy ProjectDocument does not support SDK-native
        project.json directly. Keep its editor undisturbed and select a native
        project explicitly instead of silently converting it.
        """
        if project_path is None:
            initial = str(self.document.path.parent if self.document.path else ROOT / "examples")
            filename, _ = QFileDialog.getOpenFileName(
                self, "SDK-natives Projekt für den Symbol-Designer", initial,
                "Logitech-Projekt (*.json)")
            if not filename:
                return None
            project_path = filename
        try:
            dialog = self.create_native_symbol_dialog(project_path)
        except (OSError, ValueError) as exc:
            self.show_error(exc)
            return None
        dialog.exec()
        return dialog

    def _preview_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        notice = QLabel("Design-Vorschau ohne Keypad. Eine physische Seite hat begrenzte Slots; logische Views sind unbegrenzt.\n"
                        "Der SDK-Folder verwendet automatische Pagination und einen Back-Button. Hardwareverhalten noch ungeprueft.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self.preview_view = QComboBox()
        self.preview_view.currentIndexChanged.connect(self._preview_view_changed)
        self.preview_variant = QComboBox()
        self.preview_variant.currentIndexChanged.connect(self.render_preview)
        row.addWidget(QLabel("View"))
        row.addWidget(self.preview_view, 1)
        row.addWidget(QLabel("Variante (nur Preview)"))
        row.addWidget(self.preview_variant, 1)
        layout.addLayout(row)
        self.preview_grid_widget = QWidget()
        self.preview_grid = QGridLayout(self.preview_grid_widget)
        layout.addWidget(self.preview_grid_widget, 1, Qt.AlignmentFlag.AlignTop)
        buttons = QHBoxLayout()
        previous = QPushButton("Vorherige Seite")
        following = QPushButton("Naechste Seite")
        self.preview_page_label = QLabel()
        previous.clicked.connect(lambda: self._change_page(-1))
        following.clicked.connect(lambda: self._change_page(1))
        buttons.addWidget(previous)
        buttons.addWidget(self.preview_page_label, 1)
        buttons.addWidget(following)
        layout.addLayout(buttons)
        self.pages.addTab(page, "Layout / Bilder")

    def _build_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.assembly = QLineEdit("MyStudioPlugin")
        self.output = QLineEdit()
        self.output.setPlaceholderText("Leer = work/generated/<Projekt-ID>/<Projektfingerprint>")
        self.sdk = QLineEdit(str(DEFAULT_SDK_DLL))
        form.addRow("Assembly-ID", self.assembly)
        form.addRow("Isoliertes Ausgabeverzeichnis", self.output)
        form.addRow("Echte SDK-DLL", self.sdk)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.build_button = QPushButton("Validieren, generieren und bauen")
        self.build_button.setObjectName("buildButton")
        self.build_button.clicked.connect(self.start_build)
        self.deploy_button = QPushButton("Eigene Installation: Dry-Run")
        self.deploy_button.setEnabled(False)
        self.deploy_button.clicked.connect(self.start_deployment_plan)
        buttons.addWidget(self.build_button)
        buttons.addWidget(self.deploy_button)
        layout.addLayout(buttons)
        row = QHBoxLayout()
        self.plan_save_button = QPushButton("Dry-Run als neue Datei speichern")
        self.plan_save_button.setEnabled(False)
        self.plan_save_button.clicked.connect(lambda: self.start_deployment_plan(save=True))
        self.package_button = QPushButton("Vorhandenes Paket: Dry-Run")
        self.package_button.clicked.connect(self.choose_package_plan)
        self.export_button = QPushButton("Sicheres Review-Quellarchiv")
        self.export_button.clicked.connect(self.start_export)
        row.addWidget(self.plan_save_button)
        row.addWidget(self.package_button)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.receipt = QLineEdit()
        self.receipt.setPlaceholderText("Eigener Installationsbeleg (*.receipt.json); enthaelt private Backupdaten")
        self.receipt.textChanged.connect(self._reset_rollback)
        choose_receipt = QPushButton("Beleg waehlen")
        choose_receipt.clicked.connect(self.choose_receipt)
        self.rollback_plan_button = QPushButton("Rollback nur pruefen")
        self.rollback_plan_button.clicked.connect(self.start_rollback_plan)
        self.rollback_button = QPushButton("Eigenes Rollback bestaetigen")
        self.rollback_button.setEnabled(False)
        self.rollback_button.clicked.connect(self.start_rollback)
        row.addWidget(self.receipt, 1)
        row.addWidget(choose_receipt)
        row.addWidget(self.rollback_plan_button)
        row.addWidget(self.rollback_button)
        layout.addLayout(row)
        self.build_status = QLabel("Noch kein Build. Build != Installation != Hardwaretest.")
        self.build_status.setWordWrap(True)
        layout.addWidget(self.build_status)
        self.build_log = QPlainTextEdit()
        self.build_log.setReadOnly(True)
        self.build_log.setMaximumBlockCount(5000)
        layout.addWidget(self.build_log)
        self.pages.addTab(page, "Build / Deployment")

    def _diagnostic_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Authentisierte Host-Diagnose im Worker. Kein Service-Neustart, kein Hardware-PASS."))
        row = QHBoxLayout()
        self.connection = QLineEdit()
        self.connection.setPlaceholderText("Pfad zur privaten studio.connection.json")
        browse = QPushButton("Waehlen")
        browse.clicked.connect(self.choose_connection)
        self.diagnostic_button = QPushButton("Host pruefen")
        self.diagnostic_button.clicked.connect(self.start_diagnostic)
        row.addWidget(self.connection, 1)
        row.addWidget(browse)
        row.addWidget(self.diagnostic_button)
        layout.addLayout(row)
        self.diagnostic_log = QPlainTextEdit()
        self.diagnostic_log.setReadOnly(True)
        layout.addWidget(self.diagnostic_log)
        layout.addWidget(QLabel("Standalone-Host und lokale simulierte Taste: siehe docs/13_Benutzerhandbuch.md.\n"
                               "Das Studio startet niemals beliebige Skripte aus Projektdaten."))
        self.pages.addTab(page, "Diagnose")

    def show_error(self, message):
        QMessageBox.warning(self, "Plugin Studio", str(message))

    def refresh(self):
        self._refreshing = True
        raw = self.document.raw
        self.tree.clear()
        root_item = QTreeWidgetItem([str(project_header(raw).get("display_name", "Projekt"))])
        root_item.setData(0, Qt.ItemDataRole.UserRole, ("project", project_header(raw).get("id", "")))
        self.tree.addTopLevelItem(root_item)
        selected = root_item
        for section in COLLECTIONS:
            parent = QTreeWidgetItem([LABELS[section]])
            root_item.addChild(parent)
            rows = raw.get(section, [])
            for index, entity in enumerate(rows if isinstance(rows, list) else []):
                if not isinstance(entity, dict):
                    item = QTreeWidgetItem([f"Ungueltiges Objekt [{index}] - Projekt-JSON"])
                    parent.addChild(item)
                    continue
                eid = entity.get("id", "")
                config = entity.get("config", {})
                name = config.get("display_name", "") if isinstance(config, dict) else ""
                item = QTreeWidgetItem([str(eid) + (f"  |  {name}" if name else "")])
                key = (section, eid)
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                parent.addChild(item)
                if key == self.selection:
                    selected = item
                if section == "views":
                    for placement in entity.get("placements", []) if isinstance(entity.get("placements"), list) else []:
                        if isinstance(placement, dict):
                            child = QTreeWidgetItem([str(placement.get("id", "?")) + " -> " + str(placement.get("component", "?"))])
                            child.setData(0, Qt.ItemDataRole.UserRole, key)
                            item.addChild(child)
            parent.setExpanded(True)
        root_item.setExpanded(True)
        self.tree.setCurrentItem(selected)
        self.selection = selected.data(0, Qt.ItemDataRole.UserRole)
        self.project_json.blockSignals(True)
        self.project_json.setPlainText(self.document.text)
        self.project_json.blockSignals(False)
        self._raw_pending = False
        self.preview_view.blockSignals(True)
        current_view = self.preview_view.currentText()
        self.preview_view.clear()
        self.preview_view.addItems([v["id"] for v in project_rows(raw, "views") if isinstance(v, dict) and isinstance(v.get("id"), str)])
        if current_view:
            self.preview_view.setCurrentText(current_view)
        self.preview_view.blockSignals(False)
        self.preview_variant.blockSignals(True)
        current_variant = self.preview_variant.currentText()
        self.preview_variant.clear()
        variants = {k for p in project_rows(raw, "presentations") if isinstance(p, dict) and isinstance(p.get("variants"), dict) for k in p["variants"]}
        self.preview_variant.addItems(["Default / Fallback"] + sorted(variants))
        if current_variant:
            self.preview_variant.setCurrentText(current_variant)
        self.preview_variant.blockSignals(False)
        self._render_editor()
        self._refreshing = False
        self.filter_tree()
        self.render_preview()
        self.validate_live()
        self._title()

    def _render_editor(self):
        section, eid = self.selection
        if section == "project":
            entity = self.document.raw.get("project", {})
        else:
            entity = next((r for r in project_rows(self.document.raw, section) if isinstance(r, dict) and r.get("id") == eid), None)
        previous = self.editor_scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self.editor = None
        if isinstance(entity, dict):
            self.editor = ObjectEditor(self.document, section, entity)
            self.editor.changed.connect(self._editor_changed)
            self.editor_scroll.setWidget(self.editor)

    def _title(self):
        pending = self.document.dirty or self._raw_pending or (self.editor and self.editor.pending)
        self.setWindowTitle((" * " if pending else "") + "Logitech Plugin Studio - " +
                            str(project_header(self.document.raw).get("display_name", "Projekt")))
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)

    def _editor_changed(self):
        self._title()
        self._validation_timer.start()

    def _raw_changed(self):
        if not self._refreshing:
            self._raw_pending = True
            self._title()

    def _commit_editor(self) -> bool:
        if self.editor is None or not self.editor.pending:
            return True
        try:
            value = self.editor.value()
            section, old = self.selection
            if section == "project":
                if not is_valid_id(value.get("id")) or not isinstance(value.get("display_name"), str):
                    raise DocumentError("Ungueltige Projekt-ID oder Anzeigename")
                self.document.mutate(lambda raw: raw.__setitem__("project", value))
            else:
                self.document.replace_entity(section, old, value)
            self.selection = (section, value["id"])
            self.editor.pending = False
            return True
        except (DocumentError, ValueError) as exc:
            self.show_error(exc)
            return False

    def apply_editor(self):
        if self._commit_editor():
            self.refresh()

    def apply_raw(self):
        try:
            raw = parse_json(self.project_json.toPlainText().encode("utf-8"), limit=16_777_216)
            self.document.replace_raw(raw)
            self.refresh()
        except (HostError, DocumentError, ValueError) as exc:
            self.show_error(exc)

    def _tree_changed(self, current, previous):
        if self._refreshing or current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        if self._raw_pending:
            self.show_error("Projekt-JSON zuerst explizit uebernehmen oder die Aenderungen rueckgaengig machen.")
            self._refreshing = True
            self.tree.setCurrentItem(previous)
            self._refreshing = False
            return
        if not self._commit_editor():
            self._refreshing = True
            self.tree.setCurrentItem(previous)
            self._refreshing = False
            return
        self.selection = tuple(key)
        self.refresh()
        self.pages.setCurrentIndex(0)

    def filter_tree(self):
        term = self.filter.text().casefold()
        root = self.tree.topLevelItem(0)
        if not root:
            return
        for i in range(root.childCount()):
            section = root.child(i)
            any_visible = False
            for j in range(section.childCount()):
                child = section.child(j)
                match = term in child.text(0).casefold() or any(
                    term in child.child(k).text(0).casefold() for k in range(child.childCount()))
                child.setHidden(not match)
                any_visible = any_visible or match
            section.setHidden(bool(term) and not any_visible)

    def validate_live(self):
        raw = self.document.raw
        issues = []
        try:
            if self.editor and self.editor.pending and not self._raw_pending:
                value = self.editor.value()
                section, old = self.selection
                if section == "project":
                    raw["project"] = value
                else:
                    index = next(i for i, row in enumerate(raw[section]) if isinstance(row, dict) and row.get("id") == old)
                    raw[section][index] = value
                    if value.get("id") != old:
                        ProjectDocument._rename_references(raw, section, old, value.get("id"))
            issues = [*self.document.registry_issues, *validate_project(raw, self.document.registry)]
            if not any(d.severity == "ERROR" for d in issues):
                try:
                    validate_product(raw, self.document.path.parent if self.document.path else ROOT)
                except (LogitechAdapterError, HostError, OSError, ValueError) as exc:
                    issues.append(Diagnostic("ADAPTER_CAPABILITY", "/", str(exc)))
        except (DocumentError, ValueError, StopIteration) as exc:
            issues.append(Diagnostic("EDITOR_VALUE", "/", str(exc)))
        self.validation_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            for column, text in enumerate((issue.severity, issue.code, issue.path, issue.message)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.validation_table.setItem(row, column, item)
        errors = sum(d.severity == "ERROR" for d in issues)
        self.validation_summary.setText(f"{errors} Fehler, {len(issues) - errors} Warnungen. Doppelklick navigiert zum Modellobjekt.")
        self.statusBar().showMessage(f"{errors} Fehler | {self.document.path or 'Noch nicht gespeichert'}")

    def _navigate_diagnostic(self, row, _):
        path = self.validation_table.item(row, 2).text().split("/")
        if len(path) > 2 and path[1] in COLLECTIONS and path[2].isdigit():
            rows = self.document.raw.get(path[1], [])
            index = int(path[2])
            if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
                if self._commit_editor():
                    self.selection = (path[1], rows[index].get("id", ""))
                    self.refresh()
                    self.pages.setCurrentIndex(0)

    def _ensure_applied(self) -> bool:
        if self._raw_pending:
            self.apply_raw()
            if self._raw_pending:
                return False
        return self._commit_editor()

    def _confirm_unsaved(self) -> bool:
        if not (self.document.dirty or self._raw_pending or (self.editor and self.editor.pending)):
            return True
        answer = QMessageBox.question(self, "Ungespeicherte Aenderungen", "Projekt vor dem Fortfahren speichern?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def new_project(self):
        if self._confirm_unsaved():
            self.document = ProjectDocument()
            self.selection = ("project", self.document.raw["project"]["id"])
            self.last_build = None
            self.deploy_button.setEnabled(False)
            self.refresh()

    def new_callback_project(self):
        if self._confirm_unsaved():
            self.document = ProjectDocument(callback_project())
            self.document._saved = ""  # New template has not yet been persisted.
            self.selection = ("project", "my.plugin")
            self.last_build = None
            self.deploy_button.setEnabled(False)
            self.refresh()

    def open_project(self):
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Projekt oeffnen", str(ROOT / "examples"), "Projekt (*.json)")
        if path:
            try:
                self.document.load(path)
                self.selection = ("project", project_header(self.document.raw).get("id", ""))
                self.last_build = None
                self.deploy_button.setEnabled(False)
                self.refresh()
            except (DocumentError, OSError) as exc:
                self.show_error(exc)

    def _save(self, target: Path, overwrite: bool = False) -> bool:
        try:
            if self.document.path and self.document.path.parent != target.parent:
                planned = []
                for asset in self.document.raw.get("assets", []):
                    content = read_asset(self.document.path.parent, asset)
                    destination = (target.parent / asset["path"]).resolve()
                    if not destination.is_relative_to(target.parent.resolve()):
                        raise DocumentError("Asset-Zielpfad verlaesst den neuen Projektordner")
                    if destination.exists() and destination.read_bytes() != content:
                        raise DocumentError("Speichern unter wuerde ein fremdes Asset ueberschreiben")
                    planned.append((destination, content))
                for destination, content in planned:
                    if not destination.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with destination.open("xb") as handle:
                            handle.write(content)
            self.document.save(target, replace_existing=overwrite)
            self.refresh()
            return True
        except (DocumentError, LogitechAdapterError, OSError, ValueError) as exc:
            self.show_error(exc)
            return False

    def save_project(self) -> bool:
        if not self._ensure_applied():
            return False
        if self.document.path is None:
            return self.save_as()
        return self._save(self.document.path)

    def save_as(self) -> bool:
        if not self._ensure_applied():
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", str(self.document.path or ROOT / "work" / "my-plugin" / "project.json"),
                                             "Projekt (*.json)")
        if not path:
            return False
        target = Path(path).resolve()
        return self._save(target, overwrite=target.exists())

    def undo(self):
        if self._ensure_applied():
            self.document.undo()
            self.refresh()

    def redo(self):
        if self._ensure_applied():
            self.document.redo()
            self.refresh()

    def add_entity(self, section: str):
        if not self._ensure_applied():
            return
        try:
            if section == "components":
                types = self.document.component_types()
                labels = [t.type_id + "@" + t.version for t in types]
                label, ok = QInputDialog.getItem(self, "Komponententyp", "Typmanifest waehlen", labels, 0, False)
                if not ok:
                    return
                manifest = types[labels.index(label)]
                eid = self.document.next_id(section, "action.new" if manifest.type_id == "core.command_action" else "handler.new")
                config = schema_default(manifest.config_schema)
                if "display_name" in config:
                    config["display_name"] = "Neue Aktion"
                if "callback_id" in config:
                    config["callback_id"] = eid
                entity = {"id": eid, "type": manifest.type_id, "version": manifest.version, "config": config}
            elif section == "states":
                eid = self.document.next_id(section, "state.new")
                entity = {"id": eid, "value_schema": {"type": "string"}, "scope": "project",
                          "authority": {"role": "host"}, "persistence": "none"}
            elif section == "presentations":
                eid = self.document.next_id(section, "visual.new")
                entity = {"id": eid, "variants": {"default": {"text": "Neue Darstellung", "background": "#243449"}}}
            elif section == "views":
                eid = self.document.next_id(section, "view.new")
                entity = {"id": eid, "type": "folder", "placements": []}
            elif section == "assets":
                self.import_asset()
                return
            else:
                eid = self.document.next_id(section, "binding.new")
                temporary = ObjectEditor(self.document, "bindings", {"id": eid, "kind": "command"})
                sources, targets = temporary._endpoints("out"), temporary._endpoints("in")
                temporary.deleteLater()
                if not sources or not targets:
                    raise DocumentError("Zuerst Komponenten / States / Presentations mit Ports anlegen")
                source = sources[0][1]
                target = next((e for _, e in targets if e["owner_kind"] == "component"), targets[0][1])
                entity = {"id": eid, "kind": "command", "source": source, "target": target}
            self.document.add(section, entity)
            self.selection = (section, eid)
            self.refresh()
        except (DocumentError, ValueError) as exc:
            self.show_error(exc)

    def duplicate_entity(self):
        if not self._ensure_applied() or self.selection[0] == "project":
            return
        try:
            section, eid = self.selection
            self.selection = (section, self.document.duplicate(section, eid))
            self.refresh()
        except (DocumentError, ValueError) as exc:
            self.show_error(exc)

    def remove_entity(self):
        if not self._ensure_applied() or self.selection[0] == "project":
            return
        section, eid = self.selection
        if QMessageBox.question(self, "Objekt entfernen", f"{eid} entfernen? Referenzierte Objekte werden nicht geloescht.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.document.remove(section, eid)
            self.selection = ("project", self.document.raw["project"]["id"])
            self.refresh()
        except DocumentError as exc:
            self.show_error(exc)

    def import_asset(self):
        if not self._ensure_applied():
            return
        if self.document.path is None and not self.save_project():
            return
        source, _ = QFileDialog.getOpenFileName(self, "Bild importieren", "", "Bild (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not source:
            return
        eid, ok = QInputDialog.getText(self, "Asset-ID", "Stabile ID", text=self.document.next_id("assets", "asset.image"))
        if not ok:
            return
        try:
            if not is_valid_id(eid):
                raise DocumentError("Ungueltige Asset-ID")
            relative = "assets/" + eid + ".png"
            destination = (self.document.path.parent / relative).resolve()
            if not destination.is_relative_to(self.document.path.parent):
                raise DocumentError("Asset-Ziel verlaesst den Projektordner")
            export_image(source, destination)
            self.document.add("assets", {"id": eid, "path": relative})
            self.selection = ("assets", eid)
            self.refresh()
        except (DocumentError, OSError) as exc:
            self.show_error(exc)

    def _preview_view_changed(self, *_):
        self._preview_page = 0
        self.render_preview()

    def _change_page(self, change):
        self._preview_page = max(0, self._preview_page + change)
        self.render_preview()

    def render_preview(self, *_):
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        raw = self.document.raw
        if any(d.severity == "ERROR" for d in self.document.diagnostics()):
            self.preview_grid.addWidget(QLabel("Vorschau blockiert: ungueltiges Modell. Details im Validierungs-Tab."), 0, 0)
            self.preview_page_label.setText("Keine Vorschau fuer ungueltige Projektdaten")
            return
        view = next((v for v in raw.get("views", []) if isinstance(v, dict) and v.get("id") == self.preview_view.currentText()), {})
        placements = [p for p in view.get("placements", []) if isinstance(p, dict)]
        placements.sort(key=lambda p: p.get("position") if type(p.get("position")) is int else 0)
        page_count = max(1, (len(placements) + 7) // 8)
        self._preview_page = min(self._preview_page, page_count - 1)
        start = self._preview_page * 8
        back = QLabel("BACK\nSDK-Navigation")
        back.setAlignment(Qt.AlignmentFlag.AlignCenter)
        back.setFixedSize(116, 116)
        back.setStyleSheet("background: #e4e8ed; border: 1px solid #a3afbb; color: #334155;")
        self.preview_grid.addWidget(back, 0, 0)
        variant = self.preview_variant.currentText() if self.preview_variant.currentIndex() > 0 else None
        for index, placement in enumerate(placements[start:start + 8], 1):
            label = QLabel()
            label.setPixmap(QPixmap.fromImage(render_tile(raw, self.document.path.parent if self.document.path else None, placement, variant)))
            label.setToolTip(f"{placement.get('id')} -> {placement.get('component')}\nLogische Position {placement.get('position')}")
            label.setFixedSize(116, 116)
            self.preview_grid.addWidget(label, index // 3, index % 3)
        self.preview_page_label.setText(f"Seite {self._preview_page + 1}/{page_count} | {len(placements)} logische Placements | max. 8 Inhalte + Back in dieser Vorschau")

    def start_build(self):
        if self._deployment is not None:
            self.show_error("Deployment-Auftrag zuerst abschliessen; kein paralleles Umschreiben eines Pakets.")
            return
        if self._build is not None or not self.save_project():
            return
        raw = self.document.raw
        if any(d.severity == "ERROR" for d in self.document.diagnostics()):
            self.pages.setCurrentIndex(2)
            self.show_error("Core-Fehler blockieren den Build.")
            return
        output = Path(self.output.text()) if self.output.text().strip() else (
            ROOT / "work" / "generated" / raw["project"]["id"] / project_digest(raw)[:16])
        self.build_button.setEnabled(False)
        self.deploy_button.setEnabled(False)
        self.plan_save_button.setEnabled(False)
        self.last_build = None
        self.build_log.clear()
        self.build_status.setText("Build laeuft im Worker; keine Installation.")
        self._build = BuildWorker(self.document.path, copy.deepcopy(raw), output, self.assembly.text(), self.sdk.text())
        self._build.progress.connect(self.build_log.appendPlainText)
        self._build.succeeded.connect(self._build_success)
        self._build.failed.connect(self._build_failed)
        self._build.finished.connect(self._build_finished)
        self._build.start()
        self.pages.setCurrentIndex(3)

    def _build_success(self, result):
        self.last_build = result
        self.connection.setText(result["connection"])
        self.deploy_button.setEnabled(True)
        self.plan_save_button.setEnabled(True)
        self.build_status.setText("BUILD_PROVEN: SDK-Assembly erzeugt. PROCESS_PROVEN erfordert separate Prozessprobe. "
                                 "HARDWARE_PENDING: nicht installiert oder am Geraet geprueft.")
        self.build_log.appendPlainText(json.dumps(result, indent=2, ensure_ascii=False))

    def _build_failed(self, message):
        self.build_status.setText("Build FEHLGESCHLAGEN. Keine Installation.")
        self.build_log.appendPlainText(message)

    def _build_finished(self):
        worker = self._build
        self._build = None
        self.build_button.setEnabled(True)
        if worker:
            worker.deleteLater()

    def choose_connection(self):
        path, _ = QFileDialog.getOpenFileName(self, "Private Verbindung waehlen", "", "Verbindung (*.json)")
        if path:
            self.connection.setText(path)

    def start_diagnostic(self):
        if self._diagnostic is not None or not self.connection.text():
            return
        self.diagnostic_button.setEnabled(False)
        self.diagnostic_log.setPlainText("Pruefe authentisierten lokalen Host ...")
        self._diagnostic = DiagnosticWorker(self.connection.text())
        self._diagnostic.succeeded.connect(lambda result: self.diagnostic_log.setPlainText(json.dumps(result, indent=2)))
        self._diagnostic.failed.connect(self.diagnostic_log.setPlainText)
        self._diagnostic.finished.connect(self._diagnostic_finished)
        self._diagnostic.start()

    def _diagnostic_finished(self):
        worker = self._diagnostic
        self._diagnostic = None
        self.diagnostic_button.setEnabled(True)
        if worker:
            worker.deleteLater()

    def start_deployment_plan(self, *, save=False):
        if self._deployment is not None or self.last_build is None:
            return
        if not self._ensure_applied():
            return
        if self.last_build["manifest"]["product"]["project_hash"] != project_digest(self.document.raw):
            self.show_error("Das Build gehoert zu einem anderen Projektstand. Aktuellen Stand neu bauen.")
            return
        save_path = None
        if save:
            save_path, _ = QFileDialog.getSaveFileName(self, "Neuen Dry-Run speichern; keine Installation", "", "Plan (*.json)")
            if not save_path:
                return
        self._start_deployment_worker(DeploymentWorker(self.last_build["package"], save_path=save_path))

    def _start_deployment_worker(self, worker):
        if self._deployment is not None or self._build is not None:
            self.show_error("Build-/Deployment-Auftrag zuerst abschliessen.")
            return
        self._deployment = worker
        for button in (self.deploy_button, self.plan_save_button, self.package_button, self.rollback_plan_button, self.rollback_button):
            button.setEnabled(False)
        self._deployment.succeeded.connect(self._deployment_success)
        self._deployment.failed.connect(self._deployment_failed)
        self._deployment.finished.connect(self._deployment_finished)
        self._deployment.start()

    def _deployment_success(self, plan):
        self.build_log.appendPlainText(json.dumps(plan, indent=2))
        if plan["format"] == "studio-rollback-plan-1":
            self.last_rollback_plan = None if plan.get("completed") else plan
            self.build_log.appendPlainText("Eigenes Link-Rollback ausgefuehrt; kein Service-Reload und kein Hardwarebeleg."
                                          if plan.get("completed") else "Rollback nur geprueft; noch keine Dateiaenderung.")
        else:
            self.build_log.appendPlainText("DRY_RUN_ONLY / HARDWARE_PENDING. Noch KEINE Installation; siehe Benutzerhandbuch.")

    def _deployment_failed(self, error):
        self._reset_rollback()
        self.build_log.appendPlainText(error)

    def _deployment_finished(self):
        worker = self._deployment
        self._deployment = None
        self.deploy_button.setEnabled(self.last_build is not None)
        self.plan_save_button.setEnabled(self.last_build is not None)
        for button in (self.package_button, self.rollback_plan_button):
            button.setEnabled(True)
        self.rollback_button.setEnabled(self.last_rollback_plan is not None)
        if worker:
            worker.deleteLater()

    def choose_package_plan(self):
        if self._deployment is not None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Eigenes development-package waehlen; nur pruefen")
        if directory:
            destination, _ = QFileDialog.getSaveFileName(self, "Neuen Dry-Run speichern", "", "Plan (*.json)")
            if destination:
                self._start_deployment_worker(DeploymentWorker(directory, save_path=destination))

    def _reset_rollback(self):
        self.last_rollback_plan = None
        self.rollback_button.setEnabled(False)

    def choose_receipt(self):
        file, _ = QFileDialog.getOpenFileName(self, "Eigenen privaten Installationsbeleg waehlen", "", "Beleg (*.receipt.json)")
        if file:
            self.receipt.setText(file)

    def start_rollback_plan(self):
        if self._deployment is not None:
            return
        self._reset_rollback()
        if not self.receipt.text().strip():
            self.show_error("Zuerst einen eigenen Installationsbeleg waehlen.")
            return
        self._start_deployment_worker(DeploymentWorker(self.receipt.text(), action="rollback-plan"))

    def start_rollback(self):
        if self._deployment is not None or self.last_rollback_plan is None:
            return
        plan = self.last_rollback_plan
        identity, ok = QInputDialog.getText(self, "Nur eigenes Link-Rollback",
                                          "Exakte Plugin-ID eingeben: " + plan["plugin_id"])
        if not ok:
            return
        if identity != plan["plugin_id"]:
            self.show_error("Plugin-ID stimmt nicht exakt ueberein. Nichts geaendert.")
            return
        answer = QMessageBox.question(self, "Explizite Dateiaenderung bestaetigen",
                                      f"{plan['operation']}\n{plan['target']}\nKein Service-Reload oder Profilzugriff.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._start_deployment_worker(DeploymentWorker(self.receipt.text(), action="rollback",
                                                           confirm_plugin_id=identity, expected_plan=plan))

    def start_export(self):
        if self._export is not None:
            return
        run, ok = QInputDialog.getText(self, "Bereinigtes Review-Quellarchiv",
                                      "Prueflauf FINAL-PRODUCT-NN. Kein Vollprojekt- oder Buildexport.",
                                      text="FINAL-PRODUCT-02")
        if not ok:
            return
        self.export_button.setEnabled(False)
        self._export = ExportWorker(ROOT, run, ROOT / "work" / "autopilot" / run / "delivery")
        self._export.succeeded.connect(lambda result: self.build_log.appendPlainText(json.dumps(result, indent=2)))
        self._export.failed.connect(self.build_log.appendPlainText)
        self._export.finished.connect(self._export_finished)
        self._export.start()

    def _export_finished(self):
        worker = self._export
        self._export = None
        self.export_button.setEnabled(True)
        if worker:
            worker.deleteLater()

    def closeEvent(self, event):
        if any(w is not None for w in (self._build, self._diagnostic, self._deployment, self._export)):
            self.show_error("Ein begrenzter Hintergrundauftrag laeuft noch. Nach Abschluss kann das Studio geschlossen werden.")
            event.ignore()
        elif self._confirm_unsaved():
            event.accept()
        else:
            event.ignore()


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Logitech Plugin Studio, PySide6 Widgets")
    parser.add_argument("project", nargs="?")
    parser.add_argument("--native", action="store_true", help="Explizite SDK-native Shell; keine Formatmigration")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from studio.version import PRODUCT_NAME, VERSION
    app.setApplicationName(PRODUCT_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("Plugin Studio")
    app.setStyle("Fusion")
    try:
        if args.native:
            from studio.native_shell import NativeStudioShell
            window = NativeStudioShell(args.project, workflow=True)
        else:
            window = StudioWindow(args.project)
    except (DocumentError, OSError, ValueError) as exc:
        QMessageBox.critical(None, "Plugin Studio", str(exc))
        return 2
    window.show()
    return app.exec()
