"""Reuse the SymbolDesignerWidget for both standalone and session-bound ICTs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout)

from studio.keypad_contract import KeypadViewState
from studio.native_ict_binding import NativeIctBinding, NativeIctBindingError, NativeIctCoordinator
from symbol_designer.widget import SymbolDesignerWidget


class NativeSymbolDesignerDialog(QDialog):
    saved = Signal()

    def __init__(self, project_path: str | Path, parent=None, *, load_library: bool = True,
                 coordinator=None, action_id=None, action_parameter=None):
        super().__init__(parent)
        self.setObjectName("nativeSymbolDesignerDialog")
        self.setWindowTitle("SDK-native Symbolvorlagen – Logitech Plugin Studio")
        self.resize(1450, 950)
        self.coordinator = coordinator if coordinator is not None else NativeIctCoordinator(project_path)
        self.binding: NativeIctBinding | None = None
        self._selection_index = 0
        layout = QVBoxLayout(self)
        info = QLabel(
            "SDK-Projekt: " + str(self.coordinator.project_path) + "\n"
            "Das native ICT-Format bleibt erhalten. Ohne expliziten Bearbeitungsmodus "
            "ist diese Ansicht schreibgeschützt."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.PlainText)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(info)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Aktion:"))
        self.action_combo = QComboBox(self)
        for action in self.coordinator.project.actions:
            self.action_combo.addItem(f"{action.display_name}  [{action.id}]", action.id)
        self.action_combo.setObjectName("nativeActionSelector")
        controls.addWidget(self.action_combo, 1)
        self.edit_toggle = QCheckBox("Bearbeiten aktivieren", self)
        self.edit_toggle.setObjectName("nativeEditToggle")
        controls.addWidget(self.edit_toggle)
        layout.addLayout(controls)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.designer = SymbolDesignerWidget(
            parent=self, load_library=load_library, show_file_actions=False)
        self.designer.ask_user = False  # The parent owns unsaved-change decisions.
        # The widget's standalone Apply only resets its dirty baseline. In a
        # project binding that would *look* saved without writing the ICT.
        # Present one authoritative project-save action in the host dialog.
        for button in (self.designer.apply_button, self.designer.cancel_button,
                       self.designer.multi_button):
            button.hide()
        layout.addWidget(self.designer, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_button = QPushButton("ICT im Projekt speichern / zuordnen")
        self.save_button.setObjectName("nativeSaveIct")
        self.save_button.setEnabled(False)
        footer.addWidget(self.save_button)
        self.close_button = QPushButton("Schließen")
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.action_combo.currentIndexChanged.connect(self._switch_action)
        self.edit_toggle.toggled.connect(self._set_edit_mode)
        self.designer.dirtyChanged.connect(self._update_status)
        self.save_button.clicked.connect(self.save_current)
        self.close_button.clicked.connect(self.close)
        if action_id is not None:
            index = self.action_combo.findData(action_id)
            if index < 0:
                raise NativeIctBindingError("Aktion ist im Projekt nicht vorhanden.")
            with QSignalBlocker(self.action_combo):
                self.action_combo.setCurrentIndex(index)
        self._load_action(action_parameter)
        self._set_edit_mode(False)

    def _set_edit_mode(self, enabled: bool) -> None:
        self.designer.setEnabled(enabled and self.binding is not None)
        self.save_button.setEnabled(enabled and self.binding is not None)
        self._update_status()

    def _update_status(self, *_):
        if self.binding is None:
            return
        binding = self.binding
        origin = str(binding.source) if binding.source else "Neue ICT-Vorlage"
        scope = ("Neue aktionsspezifische ICT; geerbte/geteilte Vorlage bleibt unberührt"
                 if binding.forked else "Vorhandene aktionsspezifische ICT")
        session = getattr(self.coordinator, "session", None)
        if binding.forked and session and session.dirty:
            scope += ". Beim Zuordnen werden auch die offenen nativen Projektänderungen gespeichert."
        param = (f" | SDK-actionParameter: {binding.action_parameter!r}"
                 if binding.action_parameter is not None else "")
        self.status.setText(
            f"{scope}\nQuelle: {origin}\nZiel: {binding.target}"
            f"{param}\n"
            + ("Bearbeitungsmodus aktiv" if self.edit_toggle.isChecked() else "Vorschau – keine Änderungen")
            + (" | Nicht gespeichert" if self.designer.is_dirty() else "")
        )

    def _load_action(self, action_parameter: str | None = None) -> None:
        action_id = self.action_combo.currentData()
        if action_id is None:
            return
        binding = self.coordinator.open_action(action_id, action_parameter=action_parameter)
        # Use the actual widget/renderer. Do not make a second editor or alter a Qt preview image.
        self.designer.load_template(
            binding.template, name=action_id, path=binding.source)
        self.binding = binding
        self._selection_index = self.action_combo.currentIndex()
        self._set_edit_mode(self.edit_toggle.isChecked())

    def _confirm_unsaved(self) -> bool:
        if not self.designer.is_dirty():
            return True
        answer = QMessageBox.question(
            self, "Ungespeicherte ICT-Änderungen",
            "Die aktuelle Vorlage wurde verändert. Änderungen speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current()
        return answer == QMessageBox.StandardButton.Discard

    def _switch_action(self, index: int) -> None:
        if not self._confirm_unsaved():
            with QSignalBlocker(self.action_combo):
                self.action_combo.setCurrentIndex(self._selection_index)
            return
        try:
            self._load_action()
        except (OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            QMessageBox.warning(self, "ICT-Vorlage", str(exc))
            with QSignalBlocker(self.action_combo):
                self.action_combo.setCurrentIndex(self._selection_index)

    def select_slot(self, state: KeypadViewState, physical_index: int) -> None:
        """Keypad widgets pass a resolved DTO and an explicit edit intent."""
        binding = self.coordinator.from_slot(state, physical_index)
        index = self.action_combo.findData(binding.action_id)
        if index < 0:
            raise NativeIctBindingError("Aktion des SDK-Slots ist im Projekt nicht vorhanden")
        if not self._confirm_unsaved():
            raise NativeIctBindingError("Vorherige Vorlage wurde nicht freigegeben")
        with QSignalBlocker(self.action_combo):
            self.action_combo.setCurrentIndex(index)
        self._load_action(binding.action_parameter)
        self.edit_toggle.setChecked(True)

    def save_current(self) -> bool:
        if self.binding is None or (not self.edit_toggle.isChecked() and not self.designer.is_dirty()):
            return False
        try:
            self.coordinator.save(self.binding, self.designer.template)
        except (NativeIctBindingError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Native ICT speichern fehlgeschlagen", str(exc))
            return False
        self.designer.apply()
        try:
            self.binding = self.coordinator.open_action(
                self.binding.action_id, action_parameter=self.binding.action_parameter)
            self.designer.load_template(self.binding.template, name=self.binding.action_id,
                                        path=self.binding.source)
        except (OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            self.binding = None
            self._set_edit_mode(False)
            self.status.setText("Gespeichert, erneutes Laden fehlgeschlagen: " + str(exc))
        self._update_status()
        self.saved.emit()
        return True

    def reject(self):
        # QDialog routes both Escape and the window close button through reject.
        if self._confirm_unsaved():
            super().reject()
