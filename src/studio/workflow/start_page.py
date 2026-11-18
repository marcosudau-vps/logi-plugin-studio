"""Startseite des geführten Ablaufs (Schritt 1): neu anlegen oder öffnen."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

INTRO = ("<h2>Ein Plugin in sieben Schritten</h2>"
         "<p>Das Studio führt dich vom leeren Projekt bis zur getesteten Taste am Gerät: "
         "<b>Projekt → Handler → Aktionen → Darstellung → Belegung → Prüfen und Bauen → "
         "Installieren und Testen</b>.</p>"
         "<p>Oben siehst du jederzeit, in welchem Schritt du bist und was als Nächstes zu tun ist. "
         "Ein Schritt wird frei, sobald der vorherige abgeschlossen ist; zurück geht es immer.</p>")


class StartPage(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    maintenanceRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowStartPage")
        self.setProperty("inspectorTopic", "guide.project")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.new_button = QPushButton("Neues Projekt …")
        self.new_button.setObjectName("workflowStartNew")
        self.new_button.setMinimumHeight(44)
        self.new_button.clicked.connect(self.newRequested)
        self.open_button = QPushButton("Vorhandenes Projekt öffnen …")
        self.open_button.setObjectName("workflowStartOpen")
        self.open_button.setMinimumHeight(44)
        self.open_button.clicked.connect(self.openRequested)
        self.maintenance_button = QPushButton("Wartung …")
        self.maintenance_button.setObjectName("workflowStartMaintenance")
        self.maintenance_button.setMinimumHeight(44)
        self.maintenance_button.setToolTip("Installierte Plugins prüfen, neu laden, deaktivieren und reaktivieren – "
                                           "auch ohne geöffnetes Projekt.")
        self.maintenance_button.clicked.connect(self.maintenanceRequested)
        row.addWidget(self.new_button)
        row.addWidget(self.open_button)
        row.addStretch(1)
        row.addWidget(self.maintenance_button)
        layout.addLayout(row)
        self.project = QLabel()
        self.project.setObjectName("workflowStartProject")
        self.project.setWordWrap(True)
        self.project.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.project)
        layout.addStretch(1)
        self.set_project(None)

    def set_project(self, summary) -> None:
        """``summary``: None oder (Anzeigename, Plugin-ID, Pfad, Aktionen, Handler)."""
        if summary is None:
            self.project.setText("Noch kein Projekt geöffnet.")
            return
        name, plugin_id, path, actions, handlers = summary
        self.project.setText(f"Geöffnet: {name}\nPlugin-ID: {plugin_id}\nDatei: {path}\n"
                             f"{actions} Aktion(en), {handlers} Handler")
