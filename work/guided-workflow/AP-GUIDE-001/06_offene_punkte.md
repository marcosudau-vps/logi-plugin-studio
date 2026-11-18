# 06 – Offene Punkte und Grenzen (nach Priorität)

Wird bis zum Abschluss fortgeschrieben.

| Prio | ID | Punkt | Status | Begründung / Fortsetzung |
|---|---|---|---|---|
| P1 | OP-G01 | Prüfung unter Windows (Qt-Darstellung, echter Build, Installation, Tastendruck) | WINDOWS_PENDING | In dieser Sitzung steht nur Linux/offscreen zur Verfügung → Benutzerabnahme |
| P2 | OP-G02 | Neuer Release-Kandidat (Setup/Portable) | OFFEN | `tools/packaging/build_release.py` benötigt Windows, PyInstaller und Inno Setup; Schritt für den Auftraggeber |
| P3 | OP-G03 | Neustart des gesamten Logi Plugin Service (U-01) | bewusst nicht umgesetzt | kein belegter sicherer Weg; Wartung bietet Neuladen einzelner Plugins |
| P3 | OP-G04 | Wartung mit echtem Pluginordner | WINDOWS_PENDING | Tests nutzen eine Attrappe; die verwendeten Installationsfunktionen sind unverändert und bereits unter Windows geprüft |
