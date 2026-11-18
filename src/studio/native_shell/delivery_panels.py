"""Studio tabs „Installation“ and „Shared-Peers“ (AP-RELEASE-FINAL-001 B/D).

UI only: all state changes go through ``adapters.logitech.workflow`` (own
plugin directory or development link, documented reload) and
``extensions.shared_folders.pairing`` (policy files). No transport, discovery
or SDK semantics live here.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STATUS_LABELS = (("build", "Build"), ("package", "Paket"), ("installed", "Installiert"),
                 ("loaded", "Plugin geladen"), ("connection", "Verbindung"),
                 ("hardware", "Hardwareprüfung"), ("rollback", "Rollback"))
GOOD = {"OK", "VALID", "INSTALLED", "UPDATED", "LOADED", "ACTIVE", "AVAILABLE", "HARDWARE_PASS"}
#: Anzeigetexte der Statuscodes für den geführten Ablauf (AP-GUIDE-001). Die Codes selbst bleiben
#: unverändert in ``status_codes`` und als Tooltip erhalten.
STATUS_TEXT_DE = {
    "OK": "in Ordnung", "VALID": "gültig", "INVALID": "ungültig", "UNKNOWN": "unbekannt", "NO": "nein",
    "INSTALLED": "installiert", "UPDATED": "aktualisiert", "ROLLED_BACK": "zurückgerollt", "REMOVED": "entfernt",
    "LOADED": "geladen", "LOAD_FAILED": "Laden fehlgeschlagen",
    "LOADED_FROM_OTHER_PATH": "aus einem anderen Ordner geladen",
    "ACTIVE": "aktiv", "HOST_NOT_RUNNING": "Python-Host läuft nicht",
    "HARDWARE_PENDING": "noch nicht am Gerät getestet", "HARDWARE_PASS": "am Gerät bestätigt",
    "AVAILABLE": "verfügbar", "NOT_AVAILABLE": "nicht verfügbar", "EXECUTED": "ausgeführt",
    "RESTORE_AVAILABLE": "Wiederherstellung verfügbar",
}
METHOD_TEXT = {
    "directory": "Verzeichnis-Installation: das Paket wird in den Studio-eigenen Ordner "
                 "Plugins\\<Name> des Logi Plugin Service kopiert und per Reload sofort geladen",
    "link": "Entwicklungs-Link: ein eigener .link-Eintrag verweist auf das Paket im Build-Ordner "
            "(wird vom Logi Plugin Service erst beim nächsten Dienststart gelesen)",
}
OPTIONS_PLUS_NOTE = ("Hinweis: Tastenbelegungen dieses Plugins im Logi-Options+-Profil werden vom Studio nicht "
                     "verändert. Sie können nach der Deinstallation auf dem Keypad sichtbar bleiben und müssen "
                     "dann in Logi Options+ entfernt werden.")


class CallWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    def run(self):
        try:
            self.succeeded.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")


class _Panel(QObject):
    def __init__(self, shell, title, object_name):
        super().__init__(shell)
        self.shell = shell
        self.worker = None
        self.panel = QWidget()
        self.panel.setObjectName(object_name)
        self.layout = QVBoxLayout(self.panel)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName(object_name + "Log")
        shell.tabs.addTab(self.panel, title)

    @property
    def running(self):
        return self.worker is not None

    def _button(self, row, text, name, slot):
        button = QPushButton(text)
        button.setObjectName(name)
        button.clicked.connect(slot)
        row.addWidget(button)
        return button

    def _run(self, label, fn, done, *args, **kwargs):
        if self.worker is not None:
            self.log.appendPlainText("Bitte warten: ein Vorgang läuft bereits.")
            return False
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')} {label} …")
        self.worker = CallWorker(fn, *args, **kwargs)
        self.worker.succeeded.connect(done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self._sync()
        self.worker.start()
        return True

    def _failed(self, error):
        self.log.appendPlainText("FEHLER: " + error)
        self.shell.statusBar().showMessage(error.splitlines()[0][:200])

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self._sync()

    def wait(self, timeout_ms=120_000):
        if self.worker is not None:
            self.worker.wait(timeout_ms)

    def _sync(self):
        pass


class DeploymentController(_Panel):
    """Build result → validated package → plan → own install → reload → diagnosis."""

    def __init__(self, shell):
        super().__init__(shell, "Installation", "deploymentPanel")
        self.result = None
        self.state = None
        self.host = None
        self.uninstall_receipt = None
        self.status_codes = {}  # unveränderte Statuscodes je Zeile, unabhängig vom Anzeigetext
        self.status_text = None  # optionale Übersetzung Code → Anzeigetext; None zeigt die Codes
        intro = QLabel("Installiert ausschließlich Studio-eigene Plugins – standardmäßig als Verzeichnis-Installation "
                       "in den eigenen Ordner Plugins\\<Name> des Logi Plugin Service (sofort per Reload geladen). "
                       "Jedes Plugin bringt seine eigene geprüfte Host-Laufzeit mit und läuft ohne geöffnetes Studio. "
                       "Vor jeder Änderung: Paketprüfung, Kollisionsprüfung, Sicherung, Rollback-Beleg. "
                       "Fremde Plugins, Options+-Profile und Geräteeinstellungen bleiben unberührt.")
        intro.setWordWrap(True)
        self.layout.addWidget(intro)
        box = QGroupBox("Status")
        grid = QGridLayout(box)
        self.status_labels = {}
        for row, (key, text) in enumerate(STATUS_LABELS):
            grid.addWidget(QLabel(text + ":"), row, 0)
            value = QLabel("–")
            value.setObjectName(f"deploymentStatus_{key}")
            grid.addWidget(value, row, 1)
            self.status_labels[key] = value
        self.layout.addWidget(box)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setObjectName("deploymentPlan")
        self.plan_view.setMaximumHeight(130)
        self.layout.addWidget(QLabel("Installationsplan (Probelauf, nichts geändert):"))
        self.layout.addWidget(self.plan_view)
        row = QHBoxLayout()
        self.plan_button = self._button(row, "Plan anzeigen", "deploymentPlanButton", self.show_plan)
        self.install_button = self._button(row, "Installieren / Aktualisieren …", "deploymentInstallButton", self.install)
        self.check_button = self._button(row, "Ladezustand prüfen", "deploymentCheckButton", self.check)
        self.host_button = self._button(row, "Test-Host starten", "deploymentHostButton", self.toggle_host)
        self.host_button.setToolTip("Startet den Python-Host der Build-Ausgabe zum Testen VOR der Installation. "
                                    "Installierte Plugins starten ihren Host selbst; dafür ist dieser Knopf nicht nötig.")
        self.layout.addLayout(row)
        row = QHBoxLayout()
        self.rollback_button = self._button(row, "Zurückrollen …", "deploymentRollbackButton", self.rollback)
        self.uninstall_button = self._button(row, "Deinstallieren …", "deploymentUninstallButton", self.uninstall)
        self.restore_button = self._button(row, "Deinstallation rückgängig", "deploymentRestoreButton", self.restore)
        self.inventory_button = self._button(row, "Installierte Plugins", "deploymentInventoryButton", self.show_inventory)
        self.layout.addLayout(row)
        self.inventory = QListWidget()
        self.inventory.setObjectName("deploymentInventory")
        self.inventory.setMaximumHeight(110)
        self.layout.addWidget(QLabel("Installierte Plugins (nach Klick auf „Installierte Plugins“):"))
        self.layout.addWidget(self.inventory)
        self.layout.addWidget(QLabel("Protokoll:"))
        self.layout.addWidget(self.log, 1)
        self._sync()

    # -- state -------------------------------------------------------------
    def set_status_text(self, mapping):
        """Anzeigetexte umschalten und bereits gezeigte Werte neu darstellen."""
        self.status_text = mapping
        for key, value in dict(self.status_codes).items():
            self.set_status(key, value)

    def set_status(self, key, value):
        self.status_codes[key] = value
        shown = self.status_text.get(value, value) if self.status_text else value
        self.status_labels[key].setText(shown)
        self.status_labels[key].setToolTip("" if shown == value else f"Statuscode: {value}")
        self.status_labels[key].setStyleSheet("color: #1b7f3b;" if value in GOOD else
                                              "color: #b00020;" if "FAIL" in value or "NOT" in value else "")

    def _apply(self, state):
        self.state = state
        for key, value in state.status.items():
            self.set_status(key, value)
        for step in state.steps[-6:]:
            self.log.appendPlainText(f"  {step['step']}: {step['result']}")
        self._sync()

    def _sync(self):
        busy = self.running
        package = self.result is not None and self.result.get("package")
        self.plan_button.setEnabled(bool(package) and not busy)
        self.install_button.setEnabled(bool(package) and not busy)
        self.check_button.setEnabled(self.state is not None and not busy)
        installed = self.state is not None and self.state.receipt is not None and \
            self.state.status.get("installed") in ("INSTALLED", "UPDATED")
        self.rollback_button.setEnabled(installed and not busy)
        self.uninstall_button.setEnabled(self.state is not None and not busy)
        self.restore_button.setEnabled(self.uninstall_receipt is not None and not busy)
        native_host = self.result is not None and self.result.get("host_bundle")
        self.host_button.setEnabled(bool(native_host) and not busy)
        self.host_button.setText("Test-Host stoppen" if self.host is not None and self.host.running
                                 else "Test-Host starten")

    def accept_build(self, result):
        from adapters.logitech import workflow
        self.result = result
        self.state = None
        self.set_status("build", "OK")
        for key in ("installed", "loaded", "connection", "rollback"):
            self.set_status(key, "–")
        self.set_status("hardware", "HARDWARE_PENDING")
        try:
            self.state = workflow.validate(result["package"])
            self.set_status("package", "VALID")
            self.log.appendPlainText(f"Paket gültig: {result['package']}")
        except Exception as exc:
            self.set_status("package", "INVALID")
            self.log.appendPlainText(f"Paket ungültig: {exc}")
        self._sync()

    def _receipts(self):
        return Path(self.result["output"]) / "receipts" / time.strftime("%Y%m%d-%H%M%S")

    # -- actions -----------------------------------------------------------
    def show_plan(self):
        from adapters.logitech import workflow
        try:
            state, plan = workflow.plan(self.result["package"])
        except Exception as exc:
            self.plan_view.setPlainText(f"Installation nicht möglich: {exc}")
            return None
        self.state = state
        self.plan = plan
        previous = plan.get("previous_files")
        from adapters.logitech.host_runtime import installed_runtime_status
        runtime = installed_runtime_status(plan["package"])
        runtime_text = {"PLUGIN_LOCAL": f"pluginlokal ({runtime.get('directory')}, geprüft)",
                        "SYSTEM_PYTHON": "keine eingebettete Laufzeit (Entwicklerbuild: Python 3.12–3.14 nötig)"
                        }.get(runtime["status"], runtime["status"])
        self.plan_view.setPlainText(
            f"Plugin-ID: {plan['plugin_id']}  (SDK-Name: {state.plugin_name})\n"
            f"Art: {METHOD_TEXT.get(state.method, state.method)}\n"
            f"Vorgang: {'Neuinstallation' if plan['operation'] == 'create' else 'Aktualisierung eines eigenen Plugins'}\n"
            f"Ziel: {plan['target']}\nPaket: {plan['package']} ({len(plan['new_files'])} Dateien)\n"
            f"Host-Laufzeit: {runtime_text}\n"
            f"Gesicherte Vorversion: {len(previous) if previous else 0} eigene Dateien\n"
            "Danach: gezielter Reload nur dieses Plugins, Ladediagnose, bei Fehlern automatischer Rollback.")
        return plan

    def install(self, *, confirmed=False):
        plan = self.show_plan()
        if plan is None:
            return False
        if not confirmed:
            answer = QMessageBox.question(self.shell, "Studio-Plugin installieren",
                                          self.plan_view.toPlainText() + "\n\nJetzt ausführen?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        from adapters.logitech import workflow
        return self._run("Installation / Reload / Diagnose", workflow.install_and_verify, self._installed,
                         self.result["package"], confirm_plugin_id=plan["plugin_id"],
                         receipt_dir=self._receipts(), expected_plan=plan, method=self.state.method)

    def _installed(self, state):
        self._apply(state)
        workflow_state = state.status
        if workflow_state["installed"] == "ROLLED_BACK":
            self.log.appendPlainText("Installation fehlgeschlagen und automatisch zurückgerollt; "
                                     "der vorherige Zustand ist wiederhergestellt.")
        else:
            where = "Verzeichnis " + str(state.loaded_from) if state.method == "directory" else "Entwicklungs-Link"
            self.log.appendPlainText(f"Installiert/aktualisiert ({where}). Rollback-Beleg: {state.receipt}")

    def check(self):
        from adapters.logitech import workflow

        def diagnose(state):
            adapter = workflow.ServiceAdapter()
            since = time.time() - 3600
            result = adapter.diagnose(state.plugin_name, state.package, since)
            state.status["loaded"] = result["status"]
            state.log("diagnose", result["status"])
            workflow.check_connection(state, adapter, timeout=3)
            return state
        return self._run("Ladezustand und Verbindung prüfen", diagnose, self._apply, self.state)

    def toggle_host(self):
        from adapters.logitech.host_runtime import ManagedHost
        if self.host is not None and self.host.running:
            code = self.host.stop()
            self.log.appendPlainText(f"Test-Host gestoppt (Exit {code}).")
            self.set_status("connection", "HOST_NOT_RUNNING")
        else:
            out = Path(self.result["output"])
            self.host = ManagedHost(self.result["host_bundle"], self.result["connection"], out / "native-host.log")
            try:
                pid = self.host.start()
                self.log.appendPlainText(f"Test-Host gestartet (PID {pid}); Log: {out / 'native-host.log'}")
            except Exception as exc:
                self.host = None
                self.log.appendPlainText(f"Test-Host nicht gestartet: {exc}")
        self._sync()

    def rollback(self, *, confirmed=False):
        what = ("die eigenen Plugin-Dateien im Verzeichnis auf den exakten Stand vor der letzten Installation"
                if self.state is not None and self.state.method == "directory" else
                "den eigenen Entwicklungs-Link auf den exakten Vorzustand")
        if not confirmed and QMessageBox.question(
                self.shell, "Zurückrollen", f"Jetzt {what} zurücksetzen? Danach wird das Plugin neu geladen.") \
                != QMessageBox.StandardButton.Yes:
            return False
        from adapters.logitech import workflow
        return self._run("Rollback", workflow.rollback, self._apply, self.state)

    def uninstall(self, *, confirmed=False):
        from adapters.logitech import deployment, directory_install, workflow
        method = self.state.method
        try:
            plan = (directory_install.plan_uninstall(self.state.plugin_name, self.state.plugin_id)
                    if method == "directory" else deployment.plan_uninstall(self.state.plugin_id))
        except Exception as exc:
            self.log.appendPlainText(f"Deinstallation nicht möglich: {exc}")
            return False
        what = ("Plugin-Verzeichnis (nur Studio-eigene Dateien inkl. Host-Laufzeit)" if method == "directory"
                else "Entwicklungs-Link (das Paket im Build-Ordner bleibt erhalten)")
        if not confirmed and QMessageBox.question(
                self.shell, "Studio-Plugin entfernen",
                f"Eigenes Plugin entfernen?\n{what}:\n{plan['target']}\n"
                "Eine Sicherung erlaubt „Deinstallation rückgängig“.\n\n" + OPTIONS_PLUS_NOTE) \
                != QMessageBox.StandardButton.Yes:
            return False
        return self._run("Deinstallation", workflow.uninstall, self._uninstalled, plan["plugin_id"],
                         confirm_plugin_id=plan["plugin_id"], receipt_dir=self._receipts(), method=method,
                         plugin_name=self.state.plugin_name)

    def _uninstalled(self, result):
        self.uninstall_receipt = result["receipt"]
        self.set_status("installed", "REMOVED")
        self.set_status("loaded", "–")
        self.set_status("rollback", "RESTORE_AVAILABLE")
        self.log.appendPlainText(f"Plugin erfolgreich entfernt: {result['removed']} (Beleg {result['receipt']})")
        if result.get("residual_files"):
            self.log.appendPlainText(f"{result['residual_files']} eigene Laufzeitdatei(en) waren noch in Benutzung und "
                                     "werden bei der nächsten Installation entfernt.")
        self.log.appendPlainText(OPTIONS_PLUS_NOTE)
        self.shell.statusBar().showMessage("Plugin entfernt – Options+-Belegungen ggf. in Logi Options+ entfernen.")
        self._sync()

    def restore(self):
        from adapters.logitech import deployment, directory_install
        try:
            if self.state.method == "directory":
                directory_install.restore_uninstalled(self.uninstall_receipt, confirm_plugin_id=self.state.plugin_id)
            else:
                deployment.restore_uninstalled(self.uninstall_receipt, confirm_plugin_id=self.state.plugin_id)
        except Exception as exc:
            self.log.appendPlainText(f"Wiederherstellung verweigert: {exc}")
            return False
        self.uninstall_receipt = None
        self.set_status("installed", "INSTALLED")
        where = "Plugin-Verzeichnis" if self.state.method == "directory" else "Entwicklungs-Link"
        self.log.appendPlainText(f"Eigener {where} wiederhergestellt. Der Logi Plugin Service lädt ihn nach einem Reload "
                                 "(„Ladezustand prüfen“ zeigt den Stand).")
        self._sync()
        return True

    def show_inventory(self):
        from adapters.logitech.deployment import inventory
        self.inventory.clear()
        try:
            rows = inventory()
        except Exception as exc:
            self.inventory.addItem(f"Pluginordner nicht lesbar: {exc}")
            return []
        from adapters.logitech.host_runtime import installed_runtime_status
        labels = {"PLUGIN_LOCAL": "pluginlokale Laufzeit", "PLUGIN_LOCAL_DAMAGED": "Laufzeit BESCHÄDIGT – neu installieren",
                  "SYSTEM_PYTHON": "ohne eingebettete Laufzeit", "INVALID_RECORD": "Laufzeit-Eintrag ungültig",
                  "NO_RECORD": "vor 1.0 gebaut (Host extern)"}
        for row in rows:
            owner = "Studio-eigen" if row["studio_owned"] else "fremd (nur angezeigt)"
            kind = "Verzeichnis" if row.get("kind") == "directory" else "Link"
            text = f"{row['link']} ({kind}) – {owner}"
            if row["studio_owned"] and row.get("package"):
                runtime = installed_runtime_status(row["package"])
                if runtime["status"] == "LEGACY_ABSOLUTE_PATH":
                    text += (" – ALTER absoluter Hostpfad" + ("" if runtime["executable_exists"] else " (FEHLT)")
                             + ": neu bauen und aktualisieren")
                else:
                    text += " – " + labels.get(runtime["status"], runtime["status"])
            self.inventory.addItem(text)
        return rows

    def shutdown(self):
        if self.host is not None and self.host.running:
            self.host.stop()
        self.wait()


class PairingController(_Panel):
    """Pairing of own Shared plugins and directed, exact permissions."""

    def __init__(self, shell):
        super().__init__(shell, "Shared-Peers", "pairingPanel")
        from extensions.shared_folders.pairing import PairingStore, shared_home
        self.store = PairingStore()
        intro = QLabel("Shared-Plugins finden sich nur, wenn sie gepaart sind. Paaren erlaubt noch KEINE "
                       "fremde Ausführung: Actions und Ordner werden einzeln, gerichtet freigegeben. "
                       f"Schlüssel liegen in {shared_home()}, sind mit Windows-DPAPI an Ihr Windows-Konto "
                       "gebunden und stehen nie im Projekt, Paket oder Protokoll. "
                       "Änderungen wirken nach dem nächsten Plugin-Start bzw. Reload.")
        intro.setWordWrap(True)
        self.layout.addWidget(intro)
        self.plugins = QTableWidget(0, 5)
        self.plugins.setObjectName("pairingPlugins")
        self.plugins.setHorizontalHeaderLabels(["Plugin", "Status", "SDK verbunden", "Peers", "Schlüsselablage"])
        self.plugins.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plugins.setMaximumHeight(150)
        self.layout.addWidget(self.plugins)
        row = QHBoxLayout()
        self.peer_a, self.peer_b = QComboBox(), QComboBox()
        for combo, name in ((self.peer_a, "pairingPeerA"), (self.peer_b, "pairingPeerB")):
            combo.setEditable(True)
            combo.setObjectName(name)
            row.addWidget(combo, 1)
        self._button(row, "Paaren", "pairingPairButton", self.pair)
        self._button(row, "Neu verschlüsseln", "pairingRekeyButton", self.rekey)
        self._button(row, "Entpaaren …", "pairingUnpairButton", self.unpair)
        self.layout.addLayout(row)
        self.grants = QTableWidget(0, 3)
        self.grants.setObjectName("pairingGrants")
        self.grants.setHorizontalHeaderLabels(["Empfänger", "Freigabe", "Operationen"])
        self.grants.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grants.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.layout.addWidget(QLabel("Freigaben dieses Projekts (Owner) an gepaarte Plugins:"))
        self.layout.addWidget(self.grants)
        row = QHBoxLayout()
        self.consumer = QComboBox()
        self.consumer.setObjectName("pairingConsumer")
        self.scope = QComboBox()
        self.scope.setObjectName("pairingScope")
        self.op_command = QCheckBox("Ausführen")
        self.op_adjust = QCheckBox("Drehen")
        row.addWidget(self.consumer, 1)
        row.addWidget(self.scope, 2)
        row.addWidget(self.op_command)
        row.addWidget(self.op_adjust)
        self._button(row, "Freigeben", "pairingGrantButton", self.grant)
        self._button(row, "Widerrufen", "pairingRevokeButton", self.revoke)
        self.layout.addLayout(row)
        row = QHBoxLayout()
        self._button(row, "Aktualisieren", "pairingRefreshButton", self.refresh)
        self._button(row, "Verbindungsdiagnose", "pairingDiagnoseButton", self.diagnose)
        self._button(row, "Plugin neu laden (Resync)", "pairingResyncButton", self.resync)
        row.addStretch(1)
        self.layout.addLayout(row)
        self.layout.addWidget(self.log, 1)
        self.offers = {}
        self._known = []
        self._owner_seen = None
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        shell.coordinator.changed.connect(self._project_changed)
        self.migrate_keys()
        self.refresh()

    def migrate_keys(self):
        """Protect plaintext keys of earlier versions (no new key, no new grant)."""
        try:
            result = self.store.migrate()
        except Exception as exc:
            self.log.appendPlainText(f"Schlüsselschutz nicht möglich: {exc}")
            return None
        if result["protected"]:
            self.log.appendPlainText("Schlüssel jetzt DPAPI-geschützt: " + ", ".join(result["protected"]))
        if result["kept_plaintext"]:
            self.log.appendPlainText(
                "Weiterhin Klartext (installierter Build vor 1.0 liest nur Klartext): "
                + ", ".join(result["kept_plaintext"]) + ". Plugin mit diesem Studio neu bauen und "
                "aktualisieren; danach werden die Schlüssel automatisch geschützt.")
        for plugin, error in result["failed"].items():
            self.log.appendPlainText(f"{plugin}: {error}")
        return result

    def _project_changed(self):
        owner = self.owner
        if owner != self._owner_seen:
            self._owner_seen = owner
            self.refresh()

    def _tick(self):
        # Status files are cheap; only poll while the tab is visible.
        if self.shell.tabs.currentWidget() is self.panel:
            self._refresh_status()

    @property
    def owner(self):
        session = self.shell.coordinator.session
        if session is None:
            return None
        return session.snapshot().get("plugin", {}).get("id")

    def known(self):
        ids = set(self.store.configured_plugins())
        if self.owner:
            ids.add(self.owner)
        try:
            from adapters.logitech.deployment import inventory
            ids.update(r["plugin_id"] for r in inventory() if r["studio_owned"])
        except Exception:
            pass
        return sorted(ids)

    def refresh(self):
        from extensions.shared_folders.pairing import project_offers
        from extensions.shared_folders.runtime_projection import initial_layout
        self.offers = {}
        session = self.shell.coordinator.session
        if session is not None:
            try:
                raw = session.snapshot()
                self.offers = project_offers(raw, initial_layout(raw)[0])
            except Exception as exc:
                self.log.appendPlainText(f"Freigabefähige Actions nicht ermittelbar: {exc}")
        known = self._known = self.known()
        for combo in (self.peer_a, self.peer_b):
            text = combo.currentText()
            combo.clear()
            combo.addItems(known)
            combo.setCurrentText(text)
        if self.owner and not self.peer_a.currentText():
            self.peer_a.setCurrentText(self.owner)
        self.scope.clear()
        for scope, ops in sorted(self.offers.items(), key=lambda kv: (kv[0].kind, kv[0].resource, kv[0].parameter or "")):
            label = f"{scope.kind}: {scope.resource}" + (f" [{scope.parameter}]" if scope.parameter else "")
            self.scope.addItem(label + (f"  ({', '.join(ops)})" if ops else "  (nur anzeigen)"), scope)
        self.consumer.clear()
        if self.owner:
            try:
                self.consumer.addItems(self.store.peers(self.owner))
            except Exception as exc:
                self.log.appendPlainText(str(exc))
        self._refresh_grants()
        self._refresh_status()

    def _refresh_grants(self):
        self.grants.setRowCount(0)
        if not self.owner:
            return
        try:
            grants = self.store.grants(self.owner)
        except Exception as exc:
            self.log.appendPlainText(str(exc))
            return
        for grant in grants:
            row = self.grants.rowCount()
            self.grants.insertRow(row)
            what = f"{grant.scope.kind}: {grant.scope.resource}" + (
                f" [{grant.scope.parameter}]" if grant.scope.parameter else "")
            for column, text in enumerate((grant.consumer, what, ", ".join(grant.operations) or "nur anzeigen")):
                item = QTableWidgetItem(text)
                if column == 1:
                    item.setData(256, grant.scope)
                self.grants.setItem(row, column, item)

    def _refresh_status(self):
        known = self._known
        self.plugins.setRowCount(len(known))
        for row, plugin in enumerate(known):
            status = self.store.status(plugin)
            try:
                peers = self.store.peers(plugin)
            except Exception:
                peers = ["(Policy ungültig)"]
            connected = [p for p, v in status["peers"].items() if v.get("connected")]
            storage = {"protected": "DPAPI-geschützt", "none": "–", "plaintext": "Klartext (wird geschützt)",
                       "plaintext-required": "Klartext (alter Plugin-Build)",
                       "invalid": "ungültig"}.get(self.store.key_storage(plugin), "?")
            cells = (plugin, "online" if status["online"] else ("registriert" if status["registered"] else "offline"),
                     "ja" if status.get("sdk_attached") else "nein",
                     ", ".join(f"{p}{' ✓' if p in connected else ' ✗'}" for p in peers) or "–", storage)
            for column, text in enumerate(cells):
                self.plugins.setItem(row, column, QTableWidgetItem(text))

    def _pair_ids(self):
        a, b = self.peer_a.currentText().strip(), self.peer_b.currentText().strip()
        if not a or not b:
            raise ValueError("Zwei Plugin-IDs wählen")
        return a, b

    def _guard(self, label, fn):
        try:
            result = fn()
            self.log.appendPlainText(f"{label}: OK")
            self.refresh()
            return result if result is not None else True
        except Exception as exc:
            self.log.appendPlainText(f"{label} verweigert: {exc}")
            return False

    def pair(self):
        return self._guard("Paaren", lambda: self.store.pair(*self._pair_ids()))

    def rekey(self):
        return self._guard("Neu verschlüsseln", lambda: self.store.pair(*self._pair_ids(), rekey=True))

    def unpair(self, *, confirmed=False):
        a, b = self._pair_ids()
        if not confirmed and QMessageBox.question(self.shell, "Entpaaren",
                f"Paarung {a} ↔ {b} und alle Freigaben zwischen beiden entfernen?") \
                != QMessageBox.StandardButton.Yes:
            return False
        return self._guard("Entpaaren", lambda: self.store.unpair(a, b))

    def grant(self, *, replace=False):
        scope = self.scope.currentData()
        consumer = self.consumer.currentText()
        ops = [op for op, box in (("command", self.op_command), ("adjustment", self.op_adjust)) if box.isChecked()]
        if scope is None or not consumer or not self.owner:
            self.log.appendPlainText("Freigabe: Empfänger und Action/Ordner wählen.")
            return False
        try:
            return self._guard("Freigabe", lambda: self.store.grant(self.owner, consumer, scope, ops,
                                                                    offers=self.offers, replace=replace))
        finally:
            pass

    def revoke(self):
        row = self.grants.currentRow()
        if row < 0 or not self.owner:
            self.log.appendPlainText("Widerrufen: eine Freigabe in der Tabelle auswählen.")
            return False
        consumer = self.grants.item(row, 0).text()
        scope = self.grants.item(row, 1).data(256)
        return self._guard("Widerruf", lambda: self.store.revoke(self.owner, consumer, scope))

    def diagnose(self):
        for plugin in self.known():
            status = self.store.status(plugin)
            problems = self.store.check(plugin)
            self.log.appendPlainText(
                f"{plugin}: {'online' if status['online'] else 'offline'}; SDK verbunden: "
                f"{'ja' if status.get('sdk_attached') else 'nein'}; Policy: {'gültig' if not problems else '; '.join(problems)}")
            for peer, row in status["peers"].items():
                self.log.appendPlainText(f"   ↔ {peer}: {'verbunden' if row.get('connected') else 'getrennt'} "
                                         f"(lokal {row.get('local')}, Kreis {row.get('circle')}, "
                                         f"Angebote {row.get('offers', 0)}, Ansichten {row.get('views', 0)})")
        return True

    def resync(self):
        """Policy changes apply at plugin start: reload own installed plugin(s)."""
        from adapters.logitech.deployment import inventory, _link_owner
        from adapters.logitech.service import package_plugin_name, request_plugin_reload
        targets = [self.peer_a.currentText().strip(), self.peer_b.currentText().strip()]
        done = []
        for row in inventory():
            if row["studio_owned"] and row["plugin_id"] in targets:
                try:
                    name = package_plugin_name(row["target"])
                    request_plugin_reload(name)
                    done.append(name)
                except Exception as exc:
                    self.log.appendPlainText(f"Reload {row['plugin_id']} nicht möglich: {exc}")
        self.log.appendPlainText(f"Reload angefordert: {', '.join(done) or 'kein installiertes eigenes Plugin gewählt'}")
        return done
