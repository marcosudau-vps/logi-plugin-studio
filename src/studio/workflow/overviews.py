"""Nur lesende Übersichten des geführten Ablaufs: Zustände (Schritt 3) und Symbole (Schritt 4).

Beide Widgets projizieren den nativen Projekt-Snapshot und senden Absichten.
Sie besitzen keine Daten: bearbeitet wird weiter im Aktionsinspektor bzw. im
SymbolDesigner.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .facts import ASSET_KEYS

TYPE_NAMES = {"PluginDynamicCommand": "Befehl", "PluginMultistateDynamicCommand": "Schalter mit Zuständen",
              "PluginDynamicAdjustment": "Regler", "ActionEditorCommand": "Aktion mit Einstelldialog"}
STATE_CHANGE = {"none": "kein automatischer Wechsel (dein Python-Code entscheidet)",
                "toggle": "umschalten zwischen beiden Zuständen", "increment": "zum nächsten Zustand",
                "decrement": "zum vorherigen Zustand"}
STATE_INTRO = ("<b>SDK-Zustand:</b> Bei einem Schalter merkt sich der Logi Plugin Service, welcher Zustand gilt, "
               "und zeigt dessen Namen und Bild. Diese Zustände stehen im Projekt und erscheinen hier. "
               "<b>Python-Zustand:</b> Werte, die dein eigener Code führt (zum Beispiel eine Lautstärke), "
               "gehören nicht zum Projekt und werden hier nicht angezeigt.")
SYMBOL_INTRO = ("Ohne eigenes Symbol zeigt das Gerät den Anzeigenamen der Aktion. Wähle eine Aktion und öffne den "
                "SymbolDesigner, um Bild, Text und Farben zu gestalten.")


class _Overview(QWidget):
    actionSelected = Signal(str)
    actionActivated = Signal(str)

    def __init__(self, name, topic, intro, headers, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setProperty("inspectorTopic", topic)
        self._ids = []
        self._syncing = False
        self.box = QVBoxLayout(self)
        label = QLabel(intro)
        label.setWordWrap(True)
        self.box.addWidget(label)
        self.table = QTableWidget(0, len(headers))
        self.table.setObjectName(name + "Table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemActivated.connect(lambda *_: self.selected() and self.actionActivated.emit(self.selected()))
        self.box.addWidget(self.table, 1)

    def _fill(self, rows):
        keep = self.selected()
        self._syncing = True
        self._ids = [row[0] for row in rows]
        self.table.setRowCount(len(rows))
        for index, (_identity, cells) in enumerate(rows):
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
        self.table.resizeColumnsToContents()
        if keep in self._ids:
            self.table.selectRow(self._ids.index(keep))
        self._syncing = False

    def selected(self):
        row = self.table.currentRow()
        return self._ids[row] if 0 <= row < len(self._ids) and self.table.selectedItems() else None

    def select(self, action_id):
        """Stiller Setter des Hosts."""
        self._syncing = True
        self.table.clearSelection()
        if action_id in self._ids:
            self.table.selectRow(self._ids.index(action_id))
        self._syncing = False
        self._selection_updated()

    def _selected(self):
        self._selection_updated()
        if not self._syncing and self.selected():
            self.actionSelected.emit(self.selected())

    def _selection_updated(self):
        pass


class StateOverviewWidget(_Overview):
    def __init__(self, parent=None):
        super().__init__("stateOverview", "guide.states", STATE_INTRO,
                         ["Aktion", "Art", "SDK-Zustände", "Wechsel beim Auslösen", "Varianten"], parent)
        hint = QLabel("Doppelklick öffnet die Aktion im Aktionsinspektor.")
        self.box.addWidget(hint)

    def set_project(self, raw):
        rows = []
        for action in (raw or {}).get("actions", ()):
            states = action.get("states") or ()
            listed = ", ".join(f"{s.get('index')} {s.get('display_name') or s.get('name')}" for s in states)
            change = STATE_CHANGE.get(action.get("state_change"), "–") if states else "–"
            parameters = action.get("parameters") or ()
            rows.append((action["id"], (
                f"{action.get('display_name', '')} ({action['id']})",
                TYPE_NAMES.get(action.get("sdk_type"), str(action.get("sdk_type"))),
                listed or "keine (kein Schalter)", change,
                ", ".join(p.get("display_name") or p.get("name", "") for p in parameters) or "–")))
        self._fill(rows)


class SymbolOverviewWidget(_Overview):
    editRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("symbolOverview", "guide.symbols", SYMBOL_INTRO,
                         ["Aktion", "Darstellung", "Dateien"], parent)
        row = QHBoxLayout()
        self.edit_button = QPushButton("Im SymbolDesigner bearbeiten …")
        self.edit_button.setObjectName("symbolOverviewEdit")
        self.edit_button.clicked.connect(lambda: self.selected() and self.editRequested.emit(self.selected()))
        row.addWidget(self.edit_button)
        row.addStretch(1)
        self.box.addLayout(row)
        self.actionActivated.connect(self.editRequested)
        self._selection_updated()

    def set_project(self, raw, project_dir=None):
        rows = []
        raw = raw or {}
        default = raw.get("plugin", {}).get("default_icon_template")
        base = Path(project_dir) if project_dir else None
        for action in raw.get("actions", ()):
            refs = [action[k] for k in ASSET_KEYS if isinstance(action.get(k), str)]
            refs += [s["image"] for s in action.get("states") or () if isinstance(s.get("image"), str)]
            if action.get("icon_template"):
                kind = "eigene Symbolvorlage"
            elif refs:
                kind = "eigenes Bild"
            elif default:
                kind = "Standardvorlage des Plugins"
            else:
                kind = "kein Symbol – das Gerät zeigt den Anzeigenamen"
            missing = [r for r in refs if base is not None and not (base / r).is_file()]
            files = ", ".join(refs) if refs else "–"
            if missing:
                files += "   ✖ nicht gefunden: " + ", ".join(missing)
            rows.append((action["id"], (f"{action.get('display_name', '')} ({action['id']})", kind, files)))
        self._fill(rows)
        self._selection_updated()

    def _selection_updated(self):
        if hasattr(self, "edit_button"):
            self.edit_button.setEnabled(self.selected() is not None)
