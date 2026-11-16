"""Explicit, build-only native Studio workflow using the accepted generator.

No Logitech installation, profile writes or service actions. The current saved
virtual-folder sidecar is projected into a frozen SDK layout before the worker.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import os
import shutil
import sys

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.naming import identifier, sdk_assembly_name
from studio.workers import BuildWorker
from .build_integration import (FOLDER_MODES, NativeBuildPreflightError, external_placements,
                                needs_entrypoints, prepare_native_build)
from .build_mode_store import DEFAULT_MODE, BuildModeStore


ROOT = Path(__file__).resolve().parents[3]


def build_root() -> Path:
    """Development builds stay in the source tree; the portable edition writes user data."""
    if os.environ.get("LOGI_STUDIO_DATA"):
        return Path(os.environ["LOGI_STUDIO_DATA"]) / "builds"
    if getattr(sys, "frozen", False) and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "LogiPluginStudio" / "builds"
    return ROOT / "work" / "generated" / "native-builds"


class BuildCancelled(Exception):
    """The user cancelled the multi-SDK-folder entrypoint mapping."""


class NativeBuildController(QObject):
    """Separate UI owner; the native shell remains the only project/session owner."""

    def __init__(self, shell, toolbar):
        super().__init__(shell)
        self.shell = shell
        self.worker = None
        self.last_result = None
        self.last_error = None
        # AP-06: remembered plugin type per project (user-local, not in the project).
        self.mode_store = BuildModeStore()
        self._restoring = False
        self._project_seen = None
        self.action = toolbar.addAction("SDK-Plugin bauen")
        self.action.setObjectName("nativePluginBuildAction")
        self.action.triggered.connect(self.start)
        self.panel = QWidget()
        self.panel.setObjectName("nativeBuildPanel")
        layout = QVBoxLayout(self.panel)
        self.summary = QLabel(
            "Build-only: Natives Projekt und optional gespeicherte virtuelle Ordner "
            "werden gemeinsam in ein SDK-Plugin übersetzt. Keine Installation oder Serviceänderung.")
        self.summary.setObjectName("nativeBuildSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.setObjectName("nativeBuildModeCombo")
        for key, (label, _) in FOLDER_MODES.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(self.mode.findData("compatible"))
        self.mode.setToolTip("Welcher Plugin-Typ wird erzeugt? Die Auswahl ist eine Buildoption, wird "
                             "benutzerlokal je Projekt gemerkt und verändert die Projektdatei nicht.")
        form.addRow("Plugin-Typ:", self.mode)
        self.mode_description = QLabel()
        self.mode_description.setObjectName("nativeBuildModeDescription")
        self.mode_description.setWordWrap(True)
        form.addRow("", self.mode_description)
        handler_row = QHBoxLayout()
        self.handler = QLineEdit()
        self.handler.setObjectName("nativeBuildHandler")
        self.handler.setPlaceholderText("optional: projektrelative Python-Datei mit register(host)")
        browse = QPushButton("Auswählen …")
        browse.setObjectName("nativeBuildHandlerBrowse")
        browse.clicked.connect(self.choose_handler)
        handler_row.addWidget(self.handler, 1)
        handler_row.addWidget(browse)
        form.addRow("Python-Handler:", handler_row)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("Voraussetzungen prüfen")
        self.check_button.setObjectName("nativeBuildPrereqButton")
        self.check_button.clicked.connect(self.check_prerequisites)
        self.cancel_button = QPushButton("Build abbrechen")
        self.cancel_button.setObjectName("nativeBuildCancelButton")
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.log = QPlainTextEdit()
        self.log.setObjectName("nativeBuildLog")
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        shell.tabs.addTab(self.panel, "Plugin-Build")
        self._mode_changed()
        self.update_enabled()
        shell.coordinator.changed.connect(self._project_maybe_changed)

    def _project_key(self):
        """(path identity, plugin ID) of the open project, or None (unsaved/none)."""
        session = self.shell.coordinator.session
        if session is None or session.path is None:
            return None
        from studio.virtual_folders.binding import project_identity
        try:
            return project_identity(session.path), session.snapshot()["plugin"]["id"]
        except (KeyError, OSError, ValueError):
            return None

    def _project_maybe_changed(self):
        token = self.shell.coordinator.project_token
        if token == self._project_seen:
            return
        self._project_seen = token
        self.restore_mode_for_project()

    def restore_mode_for_project(self) -> str:
        """Plugin type remembered for exactly this project (path AND plugin ID), else the default."""
        key = self._project_key()
        mode = self.mode_store.mode_for(*key) if key else DEFAULT_MODE
        self._restoring = True
        try:
            self.set_folder_mode(mode)
        finally:
            self._restoring = False
        if self.mode_store.last_error:
            self.log.appendPlainText(self.mode_store.last_error)
        return mode

    @property
    def running(self):
        return self.worker is not None

    def update_enabled(self):
        self.action.setEnabled(not self.running and self.shell.ict_dialog is None
                               and self.shell.coordinator.session is not None)
        self.mode.setEnabled(not self.running)
        self.cancel_button.setEnabled(self.running)

    @property
    def folder_mode(self) -> str:
        return self.mode.currentData()

    def set_folder_mode(self, mode: str) -> None:
        index = self.mode.findData(mode)
        if index < 0:
            raise ValueError("Unknown plugin type")
        self.mode.setCurrentIndex(index)

    def _mode_changed(self, *_):
        if not self._restoring:
            key = self._project_key() if hasattr(self, "mode_store") else None
            if key is not None and not self.mode_store.remember(*key, self.folder_mode):
                self.log.appendPlainText(self.mode_store.last_error or "Buildmodus nicht gespeichert.")
        label, text = FOLDER_MODES[self.folder_mode]
        extra = ""
        coordinator = getattr(self.shell, "coordinator", None)
        store = coordinator.extension_store if coordinator is not None else None
        externals = external_placements(store) if store is not None else []
        if externals:
            extra = f" Aktuell {len(externals)} externe Referenz(en) in den virtuellen Ordnern."
        self.mode_description.setText(f"Erzeugt wird: {label}. {text}{extra}")

    def choose_handler(self):
        session = self.shell.coordinator.session
        if session is None or session.path is None:
            return
        base = Path(session.path).resolve().parent
        chosen, _ = QFileDialog.getOpenFileName(self.shell, "Vertrauenswürdige Handler-Datei", str(base),
                                                "Python (*.py)")
        if chosen:
            path = Path(chosen).resolve()
            if not path.is_relative_to(base):
                self._reject("Handler-Datei muss im Projektordner liegen.")
                return
            self.handler.setText(path.relative_to(base).as_posix())

    def quick_prerequisites(self) -> list:
        """Fast pre-build check; never installs anything."""
        problems = []
        if not Path(DEFAULT_SDK_DLL).is_file():
            problems.append("PluginApi.dll der Logitech-Installation fehlt (Logi Options+ / Plugin Service installieren).")
        if shutil.which("dotnet") is None:
            problems.append(".NET SDK 8 oder neuer fehlt (kostenlos bei Microsoft).")
        return problems

    def check_prerequisites(self):
        from adapters.logitech.service import detect_prerequisites
        result = detect_prerequisites()
        self.log.appendPlainText("Voraussetzungen:")
        self.log.appendPlainText(f"  Logi Plugin Service: {result.plugin_service_version or 'fehlt'}"
                                 f" ({'läuft' if result.plugin_service_running else 'läuft nicht'})")
        self.log.appendPlainText(f"  PluginApi.dll: {result.plugin_api_dll or 'fehlt'}")
        self.log.appendPlainText(f"  .NET SDKs: {', '.join(result.dotnet_sdks) or 'fehlen'}")
        self.log.appendPlainText(f"  Host-Laufzeit für Python-Handler: {result.python_for_shared or 'fehlt'}")
        for issue in result.issues:
            self.log.appendPlainText(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
        if not result.issues:
            self.log.appendPlainText("  Alle Voraussetzungen erfüllt.")
        self.shell.tabs.setCurrentWidget(self.panel)
        return result

    def cancel(self):
        if self.worker is not None:
            self.worker.cancel()
            self.log.appendPlainText("Abbruch angefordert; laufender dotnet-Schritt wird beendet, dann gestoppt.")

    def _entrypoints(self, raw, store):
        """A single SDK-folder uses the configured virtual root automatically.

        Multiple real SDK-folders need an explicit choice of their start node
        rather than silently pretending they are a single shared SDK object.
        """
        if store.path is None:
            return None
        native = raw.get("folders", ())
        root = store.document.root_id
        if len(native) <= 1:
            return {folder["id"]: root for folder in native}
        folders = list(store.document.folders)
        labels = [f"{folder.name} [{folder.id}]" for folder in folders]
        root_label = next(label for label, folder in zip(labels, folders) if folder.id == root)
        result = {}
        for native_folder in native:
            chosen, ok = QInputDialog.getItem(
                self.shell, "Einstieg in nativen SDK-DynamicFolder",
                f"{native_folder['display_name']} ({native_folder['id']}): Startordner",
                labels, labels.index(root_label), False)
            if not ok:
                raise BuildCancelled()
            result[native_folder["id"]] = folders[labels.index(chosen)].id
        return result

    def start(self):
        if self.running or self.shell.ict_dialog is not None:
            return False
        c = self.shell.coordinator
        if c.session is None:
            self._reject("Kein natives Projekt geöffnet.")
            return False
        if self.shell.inspector.dirty:
            self._reject("Offenen Aktionsinspektor-Entwurf vor dem Build übernehmen oder verwerfen.")
            return False
        missing = self.quick_prerequisites()
        if missing:
            self._reject("Voraussetzung fehlt: " + " ".join(missing))
            return False
        mode = self.folder_mode
        try:
            entrypoints = (self._entrypoints(c.session.snapshot(), c.extension_store)
                           if needs_entrypoints(mode) else None)
            payload = prepare_native_build(c.session, c.extension_store, entrypoints=entrypoints,
                                           folder_mode=mode, shared_handler=self.handler.text().strip() or None)
        except BuildCancelled:
            return False
        except (NativeBuildPreflightError, ValueError, OSError) as exc:
            self._reject(str(exc))
            return False
        self.last_result, self.last_error = None, None
        out = build_root() / uuid4().hex
        label = FOLDER_MODES[payload.folder_mode][0]
        self.summary.setText(
            f"Build läuft – Plugin-Typ: {label}. Eingaben sind gespeicherte, eingefrorene Snapshots; "
            "kein Logitech-Service wird verändert.")
        self.log.clear()
        self.log.appendPlainText(f"Plugin-Typ: {label} (folder_mode={payload.folder_mode})")
        for warning in payload.warnings:
            self.log.appendPlainText("Hinweis: " + warning)
        if payload.shared_references:
            self.log.appendPlainText(f"Externe Referenzen in der Shared-Projektion: {len(payload.shared_references)}")
        if payload.shared_handler:
            self.log.appendPlainText(f"Python-Handler: {payload.shared_handler}")
        self.log.appendPlainText(f"Projekt: {payload.project_path}")
        self.log.appendPlainText(
            "Folderquelle: gespeicherte .vfolders.json" if payload.folder_runtime is not None
            else "Folderquelle: native SDK-Folderdefinitionen (kein Sidecar)")
        self.log.appendPlainText(f"Ausgabe: {out}")
        self.shell.tabs.setCurrentWidget(self.panel)
        self.worker = BuildWorker(
            payload.project_path, payload.raw_project, out,
            sdk_assembly_name("Studio", payload.raw_project["plugin"]["id"]),
            str(DEFAULT_SDK_DLL), folder_runtime=payload.folder_runtime, folder_mode=payload.folder_mode,
            shared_references=payload.shared_references, shared_handler=payload.shared_handler)
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(self._succeeded)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.update_enabled()
        self.shell.ict_action.setEnabled(False)
        self.worker.start()
        return True

    def _reject(self, message):
        self.last_error = message
        self.summary.setText("Build verweigert: " + message)
        self.log.appendPlainText("Build verweigert: " + message)
        self.shell.tabs.setCurrentWidget(self.panel)
        self.shell.coordinator.report_error("native-build", message)

    def _succeeded(self, result):
        self.last_result = result
        label = FOLDER_MODES.get(result.get("folder_mode"), (result.get("folder_mode"),))[0]
        self.summary.setText(
            f"BUILD_PROVEN: {label} – SDK-Build und gültiges Paket erstellt. "
            "Installation erst im Tab Installation nach Prüfung des Plans; keine Serviceänderung.")
        self.log.appendPlainText("BUILD_PROVEN")
        self.log.appendPlainText("Ausgabe: " + result["output"])
        self.log.appendPlainText("Paket: " + result["package"])
        self.shell.statusBar().showMessage("SDK-Build erfolgreich: " + result["output"])
        deployment = getattr(self.shell, "deployment_controller", None)
        if deployment is not None:
            deployment.accept_build(result)

    def _failed(self, error):
        self.last_error = error
        self.summary.setText("SDK-Build fehlgeschlagen; keine Installation.")
        self.log.appendPlainText(error)
        self.shell.coordinator.report_error("native-build", error)
        self.shell.statusBar().showMessage("SDK-Build fehlgeschlagen. Details im Plugin-Build-Tab.")

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.shell._refresh_status()
