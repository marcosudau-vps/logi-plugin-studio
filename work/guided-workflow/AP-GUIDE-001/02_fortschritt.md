# 02 – Fortschritt AP-GUIDE-001

Laufend gepflegte Checkliste. Ein Schritt gilt erst als abgeschlossen, wenn Implementierung **und** die
vorgesehenen Tests erfolgreich sind. Statuswerte wie in den bisherigen Arbeitsakten:
`OFFEN` · `IN_ARBEIT` · `IMPLEMENTED` · `SOFTWARE_VERIFIED` · `WINDOWS_PENDING` · `HARDWARE_PENDING`.
`SOFTWARE_VERIFIED` bedeutet hier: Tests unter Linux/offscreen bestanden; die Prüfung unter Windows steht aus.

| # | Stufe / Schritt | Ziel | Status | Betroffene Dateien | Teststatus | Nachweis | Offene Risiken |
|---|---|---|---|---|---|---|---|
| S0 | Stufe 0: Ausgangsbasis | Git-Struktur, Start-Commit, Basislauf | SOFTWARE_VERIFIED | `.gitignore`, `.gitattributes` | Basis 1.208 · 43 umgebungsbedingte Abweichungen (siehe 05) | `evidence/tests/baseline_linux_*` | Windows-Basislauf nur aus AP-POLISH-001 |
| S1 | Stufe 1: Konzept | Spezifikation, Sichtbarkeitsmatrix | SOFTWARE_VERIFIED | `docs/architecture/studio/widgets/WorkflowGuide.md` | – | Commit `4968ac8` | Begriffsliste noch offen (→ S9) |
| S2 | Stufe 2: Gerüst | Schrittmodell, Schrittleiste, Startseite, Schritt-Steuerung, Führungsthemen, Menü, Symbolleiste, Alles speichern, Expertenmodus, Build-Sperre | SOFTWARE_VERIFIED | `src/studio/workflow/*`, `src/studio/native_shell/workflow_controller.py`, `window.py`, `build_controller.py`, `app.py`, `guide_topics.de.json` | 27 neue Tests; T1 | Commit `636a9bb` | Windows-Darstellung |
| S3 | Stufe 3a: HandlerInspector | Handler anlegen/umbenennen/löschen, Handlerdatei aus Vorlage | SOFTWARE_VERIFIED | `src/studio/handler_inspector/*`, `coordinator.py` | 10 neue Tests | Commit `35f9436` | – |
| S4 | Stufe 3b: Zustandssicht | SDK-Zustände getrennt vom Python-Zustand | SOFTWARE_VERIFIED | `src/studio/workflow/overviews.py` | 2 neue Tests | Commit `4ceb4ed` | – |
| S5 | Stufe 3c: Belegung über virtuelle Ordner | Keypad zeigt im Schritt Belegung nur das bearbeitbare Autorenmodell | SOFTWARE_VERIFIED | `workflow_controller.py`, `window.py` | 2 neue Tests (Platzieren → Speichern → Schritt erfüllt) | Feature-Commit „Belegung über virtuelle Ordner“ | Windows-Darstellung |
| S6 | Stufe 4: Bauen und Installieren | deutsche Statuswerte, beschriftete Bereiche, Options+-Hinweis, Gerätetest | SOFTWARE_VERIFIED | `delivery_panels.py`, `workflow_controller.py` | T2: 0 neue Fehlschläge | `1e78b76` | Echter Build/Install nur unter Windows |
| S7 | Stufe 5: Wartung | installierte Plugins, Deaktivieren/Reaktivieren, Neuladen, Protokolle, Voraussetzungen | OFFEN | | | | Dienst-Neustart nicht sicher belegbar |
| S8 | Stufe 6: Dokumentation | Handbuch, STATUS, CHANGELOG, README, veraltete Dokumente, Benutzerabnahme | OFFEN | | | | |
| S9 | Stufe 6: Begriffsliste | ein Wort je Sache in den sichtbaren Texten | OFFEN | | | | |
| S10 | Stufe 6: Vollregression und Abschluss | 0 neue Fehlschläge, Abschlussbericht, Push, Spiegelung in den lokalen Projektordner | OFFEN | | | | Windows-Lauf durch Auftraggeber |

## Chronik

- **16.11.2026, 23:30** – Auftrag erhalten. Repository angebunden (leer). PySide6 6.12.0 und jsonschema 4.26.0
  in der Arbeitsumgebung installiert.
- Basislauf auf dem unveränderten Stand: 43 Abweichungen, alle umgebungsbedingt (Windows-Pfade, DPAPI,
  `python.exe`, `_overlapped`, Logitech-/.NET-Installation). **Befund:** Ohne `LOCALAPPDATA` scheitern unter Linux
  rund 200 Shell-Tests am `PairingStore` → Läufe setzen `LOCALAPPDATA` auf ein temporäres Verzeichnis.
- `main` mit README angelegt, `release/1.0.0` mit Start-Commit (461 Dateien). Herstellerdokumentation und
  historische Arbeitsakten per `.gitignore` ausgenommen; Geheimnisprüfung ohne Fund. Beide Branches gepusht.
- Stufe 1+2 auf `ap/GUIDE-01…` und `ap/GUIDE-02…` umgesetzt und in `feat/gefuehrter-ablauf` gemergt.
  **Entscheidung:** Der Ablauf ist ein Konstruktorschalter `NativeStudioShell(..., workflow=True)`; nur die
  Programmeinstiege schalten ihn ein. Dadurch bleiben alle bisherigen Tests, Labs und die Automatisierung
  (`automation.py`, `portable_selftest.py`) unverändert. Einziger angepasster Bestandstest: `test_v17…`
  (prüft jetzt den geführten Programmeinstieg).
- Sichtprüfung offscreen: Checkliste war zu hoch → Höhe passt sich jetzt der Zahl der Punkte an.
- Squash als „Feature: Geführter Ablauf“ auf `release/1.0.0`, gepusht.
- Stufe 3a HandlerInspector. **Befund:** Der Plugin-Host lehnt die Registrierung eines Handlers ab, den keine
  Aktion verwendet (`HANDLER_ENDPOINT` in `runtime/host.py`). Deshalb erzeugt die Vorlage nur Registrierungen für
  verwendete Handler, und eine Datei mit unbenutzten Registrierungen wird als Fehler gemeldet statt als Hinweis.
- Stufe 3b Übersichten Zustände und Symbole. Stufe 4 begonnen.
- **18.11.2026, 02:14** – Fortsetzungsauftrag. Arbeitsstand vollständig vorhanden. Stufe 4 committet
  (`97b98e6`), Lauf T2 ohne neue Fehlschläge. Diese Arbeitsakte angelegt und den bisherigen Verlauf nachgetragen.
- Stufe 4 als `1e78b76` auf `release/1.0.0`; alle Branches gepusht.
- Stufe 3c: **Befund:** Bei einem neuen Projekt zeigte die Tastenvorschau zuerst den nativen SDK-Folder
  (nur Anzeige); im Schritt Belegung konnte man so nichts ablegen. Jetzt stellt der Ablauf die Vorschau auf das
  virtuelle Autorenmodell und schaltet „Bearbeiten“ ein. **Befund:** Nach „Alles speichern“ wurde der Schrittstatus
  erst beim nächsten Zeitgeber-Tick aktualisiert, weil Extensionänderungen kein `coordinator.changed` auslösen →
  `_folders_changed` aktualisiert den Ablauf jetzt direkt.
