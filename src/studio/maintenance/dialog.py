"""Fenster „Wartung“: projektunabhängige Übersicht der installierten Plugins."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from studio.native_shell.delivery_panels import OPTIONS_PLUS_NOTE, CallWorker
from .model import DeactivationStore, MaintenanceBackend, collect_rows, deactivate, reactivate

INTRO = ("Hier siehst du alle Plugins im Pluginordner des Logi Plugin Service. Studio-eigene Plugins kannst du neu "
         "laden, deaktivieren und wieder aktivieren; Plugins anderer Hersteller werden nur angezeigt und nie "
         "verändert. Das Deaktivieren entfernt das Plugin mit einer Sicherung, aus der „Reaktivieren“ es wieder "
         "herstellt.")
SERVICE_NOTE = ("Ein Neustart des gesamten Logi Plugin Service wird hier bewusst nicht angeboten: Er beträfe alle "
                "Plugins und Geräte, und ein sicherer Weg ist nicht belegt. „Plugin neu laden“ lädt nur das gewählte "
                "Plugin neu. Falls nötig, Logi Options+ beenden und neu starten.")


class MaintenanceDialog(QDialog):
    pluginChanged = Signal(str, bool)  # Plugin-ID, jetzt aktiv

    def __init__(self, parent=None, *, backend=None, store=None):
        super().__init__(parent)
        self.setObjectName("maintenanceDialog")
        self.setWindowTitle("Wartung")
        self.setProperty("inspectorTopic", "guide.maintenance")
        self.resize(980, 620)
        self.backend = backend or MaintenanceBackend()
        self.store = store or DeactivationStore()
        self.rows = []
        self.worker = None
        layout = QVBoxLayout(self)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("maintenanceTable")
        self.table.setHorizontalHeaderLabels(["Plugin", "Zustand", "Art", "Host-Laufzeit", "Ort"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._sync)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text in (("refresh", "Aktualisieren"), ("reload", "Plugin neu laden"), ("show_log", "Protokoll anzeigen"),
                          ("deactivate", "Deaktivieren …"), ("reactivate", "Reaktivieren"),
                          ("prerequisites", "Voraussetzungen prüfen")):
            button = QPushButton(text)
            button.setObjectName("maintenance_" + key)
            button.clicked.connect(getattr(self, key))
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        layout.addLayout(row)
        note = QLabel(SERVICE_NOTE)
        note.setObjectName("maintenanceServiceNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Protokoll:"))
        self.log = QPlainTextEdit()
        self.log.setObjectName("maintenanceLog")
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self.refresh()

    # -- Anzeige ------------------------------------------------------------
    def say(self, text):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')} {text}")

    def refresh(self):
        keep = self.selected()
        try:
            self.rows = collect_rows(self.backend, self.store)
        except Exception as exc:
            self.rows = []
            self.say(f"Pluginordner nicht lesbar: {exc}")
        self.table.setRowCount(len(self.rows))
        for index, item in enumerate(self.rows):
            title = item.plugin_id or item.name
            if item.plugin_name and item.plugin_name != title:
                title += f"  ({item.plugin_name})"
            for column, text in enumerate((title, item.state_text, item.kind_text, item.runtime, item.location)):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                if not item.own:
                    cell.setForeground(self.palette().placeholderText())
                self.table.setItem(index, column, cell)
            if keep is not None and (item.plugin_id, item.name) == (keep.plugin_id, keep.name):
                self.table.selectRow(index)
        self.table.resizeColumnsToContents()
        if not self.rows:
            self.say("Keine Plugins im Pluginordner gefunden.")
        self._sync()

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) and self.table.selectedItems() else None

    def select_plugin(self, plugin_id) -> bool:
        for index, item in enumerate(self.rows):
            if item.plugin_id == plugin_id:
                self.table.selectRow(index)
                return True
        return False

    def _sync(self):
        item, busy = self.selected(), self.worker is not None
        own_active = bool(item and item.own and item.active and item.plugin_name)
        self.buttons["refresh"].setEnabled(not busy)
        self.buttons["reload"].setEnabled(own_active and not busy)
        self.buttons["show_log"].setEnabled(bool(item and item.own and item.plugin_name) and not busy)
        self.buttons["deactivate"].setEnabled(own_active and not busy)
        self.buttons["reactivate"].setEnabled(bool(item and item.own and not item.active) and not busy)
        self.buttons["prerequisites"].setEnabled(not busy)

    # -- Vorgänge -----------------------------------------------------------
    def _run(self, label, fn, done):
        if self.worker is not None:
            self.say("Bitte warten: ein Vorgang läuft bereits.")
            return False
        self.say(label + " …")
        self.worker = CallWorker(fn)
        self.worker.succeeded.connect(done)
        self.worker.failed.connect(lambda error: self.say("FEHLER: " + error.splitlines()[0]))
        self.worker.finished.connect(self._finished)
        self._sync()
        self.worker.start()
        return True

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.refresh()

    def wait(self, timeout=60000) -> None:
        if self.worker is not None:
            self.worker.wait(timeout)
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

    def reload(self):
        item = self.selected()
        if not item or not item.plugin_name:
            return False
        return self._run(f"Plugin {item.plugin_name} neu laden", lambda: self.backend.reload(item.plugin_name),
                         lambda result: self.say("Neuladen angefordert. Ob das Plugin geladen ist, zeigt "
                                                 "„Protokoll anzeigen“."))

    def log_lines(self, item, hours=24):
        return self.backend.log_lines(item.plugin_name, time.time() - hours * 3600)

    def show_log(self):
        item = self.selected()
        if not item or not item.plugin_name:
            return False
        try:
            lines = self.log_lines(item)
        except Exception as exc:
            self.say(f"Protokoll nicht lesbar: {exc}")
            return False
        self.say(f"Protokoll des Logi Plugin Service für {item.plugin_name} (letzte 24 Stunden, "
                 f"{len(lines)} Einträge):")
        for line in lines[-60:]:
            stamp = time.strftime("%d.%m. %H:%M:%S", time.localtime(line["time"]))
            self.log.appendPlainText(f"  {stamp} [{line['level']}] {line['message']}")
        if not lines:
            self.log.appendPlainText("  keine Einträge")
        return True

    def deactivate(self, *, confirmed=False):
        item = self.selected()
        if not item or not item.own or not item.active:
            return False
        if not confirmed and QMessageBox.question(
                self, "Plugin deaktivieren",
                f"{item.plugin_id} deaktivieren?\nDas Plugin wird mit einer Sicherung aus dem Pluginordner entfernt "
                "und lässt sich hier mit „Reaktivieren“ wiederherstellen.\n\n" + OPTIONS_PLUS_NOTE,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return False

        def done(result):
            self.say(f"{item.plugin_id} deaktiviert. Sicherung: {result['receipt']}")
            if result.get("warning"):
                self.say("Hinweis: " + result["warning"])
            if result.get("residual_files"):
                self.say(f"{result['residual_files']} Laufzeitdatei(en) waren noch in Benutzung und werden bei der "
                         "nächsten Installation entfernt.")
            self.say(OPTIONS_PLUS_NOTE)
            self.pluginChanged.emit(item.plugin_id, False)
        return self._run(f"{item.plugin_id} deaktivieren", lambda: deactivate(self.backend, self.store, item), done)

    def reactivate(self):
        item = self.selected()
        if not item or item.active:
            return False

        def done(result):
            reload = result.get("reload") or {}
            self.say(f"{item.plugin_id} reaktiviert." + (f" Neuladen nicht möglich: {reload['error']}"
                                                          if "error" in reload else " Neuladen angefordert."))
            self.pluginChanged.emit(item.plugin_id, True)
        return self._run(f"{item.plugin_id} reaktivieren", lambda: reactivate(self.backend, self.store, item), done)

    def prerequisites(self):
        def done(result):
            self.say("Voraussetzungen auf diesem Rechner:")
            for text in (f"Logi Plugin Service: {result.plugin_service_version or ('installiert' if result.plugin_service_installed else 'fehlt')}"
                         f" ({'läuft' if result.plugin_service_running else 'läuft nicht'})",
                         f"Logi Options+: {'installiert' if result.options_plus_installed else 'fehlt'}",
                         f"PluginApi.dll: {result.plugin_api_dll or 'fehlt'}",
                         f".NET SDKs: {', '.join(result.dotnet_sdks) or 'fehlen'}",
                         f"Reload-Werkzeug: {result.service_tool or 'fehlt'}"):
                self.log.appendPlainText("  " + text)
            for issue in result.issues:
                self.log.appendPlainText(f"  [{issue['severity']}] {issue['message']}")
            if not result.issues:
                self.log.appendPlainText("  Alle Voraussetzungen erfüllt.")
        return self._run("Voraussetzungen prüfen", self.backend.prerequisites, done)

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.say("Bitte warten, bis der laufende Vorgang beendet ist.")
            return
        super().closeEvent(event)
