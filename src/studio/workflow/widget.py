"""Schrittleiste des geführten Ablaufs: Schritte, nächster Handgriff, Checkliste.

Reine Anzeige mit Absichtssignalen. Das Widget kennt weder Session noch Dateien;
der Host liefert ``StepState``-Werte und entscheidet über jeden Schrittwechsel.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .model import DONE, LOCKED, STATUS_MARK, STATUS_TEXT, STEPS, complete, guidance


class WorkflowRail(QWidget):
    stepRequested = Signal(str)
    backRequested = Signal()
    nextRequested = Signal()
    helpRequested = Signal()
    criterionActivated = Signal(str)
    expertToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowRail")
        self._states = ()
        self._active = STEPS[0].key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        steps = QHBoxLayout()
        steps.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for definition in STEPS:
            button = QToolButton()
            button.setObjectName("workflowStep_" + definition.key)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, key=definition.key: self.stepRequested.emit(key))
            self.group.addButton(button)
            self.buttons[definition.key] = button
            steps.addWidget(button)
        self.expert = QCheckBox("Expertenmodus")
        self.expert.setObjectName("workflowExpertToggle")
        self.expert.setToolTip("Freie Ansicht: alle Registerkarten und Werkzeuge sind gleichzeitig erreichbar. "
                               "Der Schrittstatus wird weiter angezeigt.")
        self.expert.toggled.connect(self.expertToggled)
        steps.addWidget(self.expert)
        layout.addLayout(steps)
        row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("workflowTitle")
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        row.addWidget(self.title)
        self.hint = QLabel()
        self.hint.setObjectName("workflowHint")
        self.hint.setWordWrap(True)
        row.addWidget(self.hint, 1)
        self.help_button = QPushButton("Mehr dazu")
        self.help_button.setObjectName("workflowHelpButton")
        self.help_button.setToolTip("Zeigt die ausführliche Anleitung zu diesem Schritt in der Hilfe.")
        self.help_button.clicked.connect(self.helpRequested)
        self.back_button = QPushButton("← Zurück")
        self.back_button.setObjectName("workflowBackButton")
        self.back_button.clicked.connect(self.backRequested)
        self.next_button = QPushButton("Weiter →")
        self.next_button.setObjectName("workflowNextButton")
        self.next_button.clicked.connect(self.nextRequested)
        for button in (self.help_button, self.back_button, self.next_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.checklist = QListWidget()
        self.checklist.setObjectName("workflowChecklist")
        self.checklist.setAlternatingRowColors(True)
        self.checklist.setToolTip("Checkliste dieses Schritts. Doppelklick oder Eingabetaste springt zur Stelle.")
        self.checklist.itemActivated.connect(
            lambda item: self.criterionActivated.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.checklist)

    def set_states(self, states, active: str, *, expert: bool = False) -> None:
        """Vollständige neue Anzeige; programmatische Setter senden keine Signale."""
        self._states, self._active = tuple(states), active
        current = None
        for index, state in enumerate(self._states):
            button = self.buttons[state.step.key]
            button.setText(f"{STATUS_MARK[state.status]}  {state.step.number}  {state.step.title}")
            button.setToolTip(f"Schritt {state.step.number} von {len(STEPS)}: {state.step.title} – "
                              f"{STATUS_TEXT[state.status]}" + (" (optional)" if state.step.optional else ""))
            button.setAccessibleName(button.toolTip())
            button.setEnabled(expert or state.status != LOCKED)
            button.blockSignals(True)
            button.setChecked(state.step.key == active)
            button.blockSignals(False)
            if state.step.key == active:
                current = (index, state)
        self.expert.blockSignals(True)
        self.expert.setChecked(expert)
        self.expert.blockSignals(False)
        if current is None:
            return
        index, state = current
        self.title.setText(f"Schritt {state.step.number} von {len(STEPS)} – {state.step.title}:")
        self.hint.setText(guidance(state))
        self.back_button.setEnabled(index > 0)
        last = index == len(self._states) - 1
        self.next_button.setEnabled(not last and (expert or complete(state)))
        self.next_button.setToolTip("" if self.next_button.isEnabled() or last else
                                    "Erst möglich, wenn die offenen Punkte der Checkliste erledigt sind.")
        self.checklist.clear()
        for criterion in state.criteria:
            text = f"{STATUS_MARK[criterion.status]}  {criterion.text}  [{STATUS_TEXT[criterion.status]}]"
            if criterion.detail and criterion.status != DONE:
                text += "  –  " + criterion.detail
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, criterion.key)
            item.setToolTip(criterion.detail or criterion.text)
            self.checklist.addItem(item)
        rows = min(max(self.checklist.count(), 1), 5)
        self.checklist.setFixedHeight(rows * max(self.checklist.sizeHintForRow(0), 16) + 8)

    def active(self) -> str:
        return self._active

    def checklist_texts(self) -> list[str]:
        return [self.checklist.item(i).text() for i in range(self.checklist.count())]
