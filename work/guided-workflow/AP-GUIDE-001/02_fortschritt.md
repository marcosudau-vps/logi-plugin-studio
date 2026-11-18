# 02 – Fortschritt AP-GUIDE-001

Laufend gepflegte Checkliste. Ein Schritt gilt erst als abgeschlossen, wenn Implementierung **und** die
vorgesehenen Tests erfolgreich sind. Statuswerte wie in den bisherigen Arbeitsakten:
`OFFEN` · `IN_ARBEIT` · `IMPLEMENTED` · `SOFTWARE_VERIFIED` · `WINDOWS_PENDING` · `HARDWARE_PENDING`.
`SOFTWARE_VERIFIED` bedeutet hier: Tests unter Linux/offscreen bestanden; die Prüfung unter Windows steht aus.

| # | Stufe / Schritt | Ziel | Status | Betroffene Dateien | Teststatus | Nachweis | Offene Risiken |
|---|---|---|---|---|---|---|---|
| S0 | Stufe 0: Ausgangsbasis | Git-Struktur, Start-Commit, Basislauf | SOFTWARE_VERIFIED | `.gitignore`, `.gitattributes` | Basis 1.208 · 43 umgebungsbedingte Abweichungen (siehe 05) | `evidence/tests/baseline_linux_*` | Windows-Basislauf nur aus AP-POLISH-001 |
| S1 | Stufe 1: Konzept | Spezifikation, Sichtbarkeitsmatrix | SOFTWARE_VERIFIED | `docs/architecture/studio/widgets/WorkflowGuide.md` | – | Commit `4968ac8` | Begriffsliste in S9 |
| S2 | Stufe 2: Gerüst | Schrittmodell, Schrittleiste, Startseite, Schritt-Steuerung, Führungsthemen, Menü, Symbolleiste, Alles speichern, Expertenmodus, Build-Sperre | SOFTWARE_VERIFIED | `src/studio/workflow/*`, `src/studio/native_shell/workflow_controller.py`, `window.py`, `build_controller.py`, `app.py`, `guide_topics.de.json` | 27 neue Tests; T1 | Commit `636a9bb` | Windows-Darstellung |
| S3 | Stufe 3a: HandlerInspector | Handler anlegen/umbenennen/löschen, Handlerdatei aus Vorlage | SOFTWARE_VERIFIED | `src/studio/handler_inspector/*`, `coordinator.py` | 10 neue Tests | Commit `35f9436` | – |
| S4 | Stufe 3b: Zustandssicht | SDK-Zustände getrennt vom Python-Zustand | SOFTWARE_VERIFIED | `src/studio/workflow/overviews.py` | 2 neue Tests | Commit `4ceb4ed` | – |
| S5 | Stufe 3c: Belegung über virtuelle Ordner | Keypad zeigt im Schritt Belegung nur das bearbeitbare Autorenmodell | SOFTWARE_VERIFIED | `workflow_controller.py`, `window.py` | 2 neue Tests (Platzieren → Speichern → Schritt erfüllt) | Feature-Commit „Belegung über virtuelle Ordner“ | Windows-Darstellung |
| S6 | Stufe 4: Bauen und Installieren | deutsche Statuswerte, beschriftete Bereiche, Options+-Hinweis, Gerätetest | SOFTWARE_VERIFIED | `delivery_panels.py`, `workflow_controller.py` | T2: 0 neue Fehlschläge | `1e78b76` | Echter Build/Install nur unter Windows |
| S7 | Stufe 5: Wartung | installierte Plugins, Deaktivieren/Reaktivieren, Neuladen, Protokolle, Voraussetzungen | SOFTWARE_VERIFIED | `src/studio/maintenance/*`, `workflow_controller.py`, `start_page.py`, `guide_topics.de.json` | 7 neue Tests (mit Attrappe) | Feature-Commit „Wartung“, `evidence/screenshots/wartung.png` | echter Pluginordner nur unter Windows; Dienst-Neustart bewusst nicht angeboten |
| S8 | Stufe 6: Dokumentation | Handbuch, STATUS, CHANGELOG, README, veraltete Dokumente, Benutzerabnahme | SOFTWARE_VERIFIED | `docs/ANWENDERHANDBUCH.md`, `STATUS.md`, `CHANGELOG.md`, `README.md`, `docs/architecture/studio/README.md`, `widgets/KeypadPreview.md`, `work/planning/README.md`, `outputs/BENUTZERABNAHME.md` | – | Feature-Commit „Begriffe, Dokumentation und Abschluss“ | – |
| S9 | Stufe 6: Begriffsliste | ein Wort je Sache in den sichtbaren Texten | SOFTWARE_VERIFIED | `docs/architecture/studio/Begriffe.md`, 12 Quelldateien, 5 Hilfedateien | 3 Bestandstests im Wortlaut angepasst | wie S8 | SDK-Typnamen im Aktionskatalog bewusst unverändert |
| S10 | Stufe 6: Vollregression und Abschluss | 0 neue Fehlschläge, Abschlussbericht, Push, Spiegelung in den lokalen Projektordner | SOFTWARE_VERIFIED | `07_abschlussbericht.md` | 1.256 Tests, Fehlschlagliste identisch mit Basis | `evidence/tests/final_*` | Windows-Lauf durch Auftraggeber |

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
- Stufe 3c als Feature-Commit auf `release/1.0.0`, gepusht.
- Stufe 5 Wartung. **Technische Prüfung Dienst-Neustart:** Der Code kennt nur den dokumentierten Reload eines
  einzelnen Plugins (`loupedeck://plugin/<Name>/reload` über `LogiPluginServiceTool.exe`). Für einen Neustart des
  ganzen Dienstes gibt es keinen belegten Weg; er würde fremde Plugins und Geräte treffen. **Entscheidung:** nicht
  anbieten, im Fenster begründen, auf „Plugin neu laden“ verweisen. **Entscheidung Aktivieren/Deaktivieren:**
  Deaktivieren = vorhandene Deinstallation mit Sicherungsbeleg, Reaktivieren = vorhandene Wiederherstellung;
  keine neue Dateilogik im Pluginordner. „Shared-Peers“ war schon mit Stufe 2 hinter den Plugin-Typ Shared verlegt
  (Registerkarte nur in Schritt 7 und nur beim Plugin-Typ Shared).
- Stufe 5 als `caf0a44` auf `release/1.0.0`, gepusht.
- Stufe 6 Begriffsliste: „Action“ → „Aktion“ in sichtbaren Texten und Hilfethemen; Befehle „Projekt öffnen …“,
  „Projekt speichern“, „Ordner speichern“, „Rückgängig (Projekt|Ordner)“, Statuszeile „Projekt: … | Ordner: …“.
  Drei Bestandstests prüften den alten Wortlaut → nur die erwartete Formulierung angepasst.
  **Entscheidung:** SDK-Typnamen im Aktionskatalog bleiben (Daten- und Filtergrundlage des abgenommenen Widgets).
- Strg+S speichert im geführten Ablauf alles (im Expertenmodus wie bisher nur das Projekt; „Alles speichern“ dort
  Strg+Umschalt+S).
- **Befund Zeilenenden:** Fünf CRLF-Quelldateien waren in Stufe 2–5 beim Bearbeiten auf LF umgestellt worden
  (Schein-Diffs von über 3.000 Zeilen). Ursprüngliche Zeilenenden wiederhergestellt; alle geänderten Dateien
  gegen den Start-Commit geprüft – kein Unterschied mehr im Zeilenende.
- Sichtprüfung offscreen: Checkliste in Schritt 6 schnitt den vierten Punkt ab → Zeilenhöhe aus der Schrift
  berechnet. Version auf 1.0.0-rc2.
- Handbuch auf den geführten Ablauf umgeschrieben (Abschnitte 2–11), Benutzerabnahme für rc2 erstellt, STATUS,
  CHANGELOG, README, Studio-Architektur, KeypadPreview-Status und Planungsindex fortgeschrieben.
- Vollregression: 1.256 Tests, Fehlschlagliste identisch mit der Ausgangsbasis. **Status READY_FOR_REVIEW.**
- **Spiegelung in den lokalen Projektordner** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`
  (Stand `release/1.0.0` = `e5feba2`): 81 Dateien (49 neu, 32 geändert). Vorab geprüft: alle 32 zu ersetzenden
  Dateien waren lokal unverändert gegenüber dem Start-Commit (keine Konflikte). Sicherung der 32 Originale:
  `backups/20261118-vor-spiegelung-release-1.0.0.tar` (SHA-256 `05a55e3a…c846`, nur lokal). Nach dem Entpacken
  alle 81 Dateien per SHA-256 gegen den Release-Stand geprüft: 0 Abweichungen. Archiv und Manifest unter
  `work/generated/sync/` (nur lokal). Nichts wurde gelöscht.
- Dieser Vermerk liegt auf `feat/abschluss-dokumentation` und kommt mit dem nächsten Feature-Commit bzw. vor dem
  Merge nach `main` auf `release/1.0.0` (kein nachträgliches Umschreiben des bereits gepushten Release-Commits).

