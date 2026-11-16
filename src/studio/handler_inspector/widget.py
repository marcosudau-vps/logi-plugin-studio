"""HandlerInspectorWidget: Handlerliste und Python-Handlerdatei eines Projekts.

Reine Ansicht mit Absichtssignalen. Das Widget hält keine Session und schreibt
keine Datei; der Host prüft Revision/Projekttoken und committet über die native
Projektsitzung bzw. legt die Handlerdatei einmalig aus der Vorlage an.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .lifecycle import check_handler_delete, handler_usage, suggest_handler_id

INTRO = ("Ein Handler ist die Stelle in deinem Python-Code, die aufgerufen wird, wenn eine Aktion ausgelöst wird. "
         "Mehrere Aktionen dürfen denselben Handler verwenden.")
FILE_INTRO = ("Die Handlerdatei liegt neben dem Projekt und enthält die Funktion register(host). "
              "Das Studio führt sie nie aus, sondern prüft sie nur. Den eigentlichen Code schreibst du in einem "
              "Editor deiner Wahl.")


class HandlerInspectorWidget(QWidget):
    createRequested = Signal(str)
    renameRequested = Signal(str, str)
    deleteRequested = Signal(str)
    templateRequested = Signal()
    chooseFileRequested = Signal()
    handlerSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("handlerInspector")
        self.setProperty("inspectorTopic", "guide.handlers")
        self._project = None
        self._syncing = False
        layout = QVBoxLayout(self)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 3)
        self.table.setObjectName("handlerTable")
        self.table.setHorizontalHeaderLabels(["Handler-ID", "Verwendet von", "In der Handlerdatei"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.new_button = QPushButton("+ Neuer Handler …")
        self.new_button.setObjectName("handlerNewButton")
        self.new_button.clicked.connect(self.ask_create)
        self.rename_button = QPushButton("Umbenennen …")
        self.rename_button.setObjectName("handlerRenameButton")
        self.rename_button.clicked.connect(self.ask_rename)
        self.delete_button = QPushButton("Löschen …")
        self.delete_button.setObjectName("handlerDeleteButton")
        self.delete_button.clicked.connect(self.ask_delete)
        for button in (self.new_button, self.rename_button, self.delete_button):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        box = QGroupBox("Python-Handlerdatei")
        box_layout = QVBoxLayout(box)
        file_intro = QLabel(FILE_INTRO)
        file_intro.setWordWrap(True)
        box_layout.addWidget(file_intro)
        self.file_status = QLabel()
        self.file_status.setObjectName("handlerFileStatus")
        self.file_status.setWordWrap(True)
        self.file_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box_layout.addWidget(self.file_status)
        file_row = QHBoxLayout()
        self.template_button = QPushButton("Handlerdatei aus Vorlage erzeugen")
        self.template_button.setObjectName("handlerTemplateButton")
        self.template_button.clicked.connect(self.templateRequested)
        self.choose_button = QPushButton("Vorhandene Datei auswählen …")
        self.choose_button.setObjectName("handlerChooseButton")
        self.choose_button.clicked.connect(self.chooseFileRequested)
        file_row.addWidget(self.template_button)
        file_row.addWidget(self.choose_button)
        file_row.addStretch(1)
        box_layout.addLayout(file_row)
        self.snippet_label = QLabel("Diese Zeilen fehlen in deiner Handlerdatei (innerhalb von register(host) einfügen):")
        self.snippet_label.setWordWrap(True)
        self.snippet = QPlainTextEdit()
        self.snippet.setObjectName("handlerSnippet")
        self.snippet.setReadOnly(True)
        self.snippet.setMaximumHeight(120)
        box_layout.addWidget(self.snippet_label)
        box_layout.addWidget(self.snippet)
        layout.addWidget(box)
        self.set_project(None)

    # -- Anzeige ------------------------------------------------------------
    def set_project(self, project, *, file="", file_error="", registered=None, unknown=(), snippet=""):
        """``registered``: Menge der in der Datei registrierten Handler oder None (unbekannt)."""
        selected = self.selected()
        self._project = project
        self._syncing = True
        handlers = project["handlers"] if project else []
        self.table.setRowCount(len(handlers))
        for row, handler in enumerate(handlers):
            usage = handler_usage(project, handler["id"])
            used = f"{len(usage)} Aktion(en): " + ", ".join(usage) if usage else "noch keiner Aktion"
            if registered is None:
                state = "–"
            elif handler["id"] in registered:
                state = "registriert" if usage else "registriert, aber unbenutzt – Zeile aus der Datei entfernen"
            else:
                state = "fehlt in der Datei" if usage else "nicht nötig (unbenutzt)"
            for column, text in enumerate((handler["id"], used, state)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
            if handler["id"] == selected:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self._syncing = False
        enabled = project is not None
        self.new_button.setEnabled(enabled)
        self.template_button.setEnabled(enabled and not file)
        self.choose_button.setEnabled(enabled)
        if not enabled:
            self.file_status.setText("Kein Projekt geöffnet.")
        elif not file:
            self.file_status.setText("○ Noch keine Handlerdatei zugeordnet.")
        elif file_error:
            self.file_status.setText(f"✖ {file}: {file_error}")
        elif unknown:
            self.file_status.setText(f"✖ {file}: registriert Handler, die im Projekt nicht verwendet werden "
                                     f"({', '.join(unknown)}). Der Plugin-Host würde so nicht starten; "
                                     "diese Zeilen aus der Datei entfernen.")
        else:
            self.file_status.setText(f"✔ {file}")
        self.snippet.setPlainText(snippet)
        self.snippet.setVisible(bool(snippet))
        self.snippet_label.setVisible(bool(snippet))
        self._update_buttons()

    def selected(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None and self.table.selectedItems() else None

    def select(self, handler_id):
        """Stiller Setter des Hosts."""
        self._syncing = True
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == handler_id:
                self.table.selectRow(row)
        self._syncing = False
        self._update_buttons()

    def _selection_changed(self):
        self._update_buttons()
        if not self._syncing and self.selected():
            self.handlerSelected.emit(self.selected())

    def _update_buttons(self):
        selected = self.selected()
        self.rename_button.setEnabled(bool(selected))
        allowed = False
        reason = "Einen Handler auswählen."
        if selected and self._project:
            check = check_handler_delete(self._project, selected)
            allowed, reason = check.allowed, check.reason
        self.delete_button.setEnabled(allowed)
        self.delete_button.setToolTip("" if allowed else reason)

    # -- Dialoge → Absichten -------------------------------------------------
    def ask_create(self):
        if self._project is None:
            return
        value, ok = QInputDialog.getText(self, "Neuer Handler", "Handler-ID (klein, ohne Leerzeichen):",
                                         text=suggest_handler_id(self._project))
        if ok and value.strip():
            self.createRequested.emit(value.strip())

    def ask_rename(self):
        selected = self.selected()
        if not selected:
            return
        usage = handler_usage(self._project, selected)
        value, ok = QInputDialog.getText(
            self, "Handler umbenennen",
            f"Neue ID für {selected}\n{len(usage)} Aktion(en) werden mit umgestellt. "
            "Die Handlerdatei musst du danach selbst anpassen.", text=selected)
        if ok and value.strip() and value.strip() != selected:
            self.renameRequested.emit(selected, value.strip())

    def ask_delete(self):
        selected = self.selected()
        if not selected:
            return
        answer = QMessageBox.question(self, "Handler löschen",
                                      f"Handler {selected} aus dem Projekt entfernen?\n"
                                      "Eine Registrierung in der Handlerdatei musst du selbst entfernen.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.deleteRequested.emit(selected)
