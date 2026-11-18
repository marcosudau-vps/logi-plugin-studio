# 06 – Offene Punkte und Grenzen (nach Priorität)

Wird bis zum Abschluss fortgeschrieben.

| Prio | ID | Punkt | Status | Begründung / Fortsetzung |
|---|---|---|---|---|
| P1 | OP-G01 | Prüfung unter Windows (Qt-Darstellung, echter Build, Installation, Tastendruck) | WINDOWS_PENDING | In dieser Sitzung steht nur Linux/offscreen zur Verfügung → Benutzerabnahme |
| P2 | OP-G02 | Neuer Release-Kandidat (Setup/Portable) | OFFEN | Version steht auf 1.0.0-rc2; `tools/packaging/build_release.py` benötigt Windows, PyInstaller und Inno Setup |
| P2 | OP-G05 | Benutzerabnahme und Merge nach `main` | OFFEN | nur durch den Auftraggeber (outputs/BENUTZERABNAHME.md) |
| P3 | OP-G03 | Neustart des gesamten Logi Plugin Service (U-01) | bewusst nicht umgesetzt | kein belegter sicherer Weg; Wartung bietet Neuladen einzelner Plugins |
| P3 | OP-G04 | Wartung mit echtem Pluginordner | WINDOWS_PENDING | Tests nutzen eine Attrappe; die verwendeten Installationsfunktionen sind unverändert und bereits unter Windows geprüft |
| P3 | OP-G06 | SDK-Typnamen im Aktionskatalog | bewusst unverändert | Daten-/Filtergrundlage des abgenommenen Widgets; Klartextnamen in „Zustände“, Hilfe und Handbuch |
| P3 | OP-G07 | Reihenfolge der Registerkarten in Schritt 6 (Probleme, Hilfe, Plugin-Build) | Kosmetik | Die Shell legt Registerkarten in fester Reihenfolge an; der Schritt öffnet trotzdem „Plugin-Build“ |
| P3 | OP-G08 | Fachbegriff „Sidecar“ im Hinweis der Tastenvorschau | Kosmetik | technischer Hinweistext des abgenommenen Keypad-Bindings |
| Info | OP-G09 | Visueller Designer für Options+-Einstelldialoge, ProfileExplorer, Python-SDK-API-Checkliste, Code-Signierung | zurückgestellt | laut Plan |
